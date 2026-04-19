# -*- coding: utf-8 -*-
"""
services/llm_service.py — LLM calls and search functions extracted from main.py.
"""
import httpx, json, re, logging, asyncio, os
from typing import AsyncIterator
from core import app_state
from core.config import (
    ANTHROPIC_KEY, GEMINI_KEY, OPENAI_KEY, OLLAMA_HOST,
    MODEL_CLAUDE_MAIN, MODEL_CLAUDE_FAST, MODEL_GEMINI, MODEL_OPENAI,
    PRIMARY_MODEL,
)
from core.prompts import COT_SYSTEM, RERANK_SYSTEM
from core.nlp_utils import (
    normalize_ar, make_mizan_link,
    extract_kw, extract_phrases, detect_legal_domain, _LEGAL_DOMAINS,
    _LEGAL_EXPANSIONS, _detect_fixed_phrases, expand_keywords_with_synonyms,
    _detect_ambiguity, _semantic_local_rerank, _deduplicate_law_versions,
    _al_phrase_variants, kw_variants, _law_year_score_boost,
)

log = logging.getLogger(__name__)

MODEL_OLLAMA_LLM = __import__('os').getenv("MODEL_OLLAMA_LLM", "qwen2.5:1.5b")

# ── Optional intent_router (build_structured_context) ──
try:
    from intent_router import build_structured_context as build_structured_context
    _INTENT_ROUTER_AVAILABLE = True
except ImportError:
    _INTENT_ROUTER_AVAILABLE = False
    build_structured_context = None  # type: ignore

async def call_claude(system: str, messages: list[dict],
                      model: str | None = None, max_tokens: int = 3000) -> str:
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY غير مُعيَّن")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model or MODEL_CLAUDE_MAIN, "max_tokens": max_tokens,
                  "system": system, "messages": messages},
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]

async def stream_claude(system: str, messages: list[dict],
                        model: str | None = None, max_tokens: int = 3000) -> AsyncIterator[str]:
    """بث الإجابة حرفاً بحرف"""
    if not ANTHROPIC_KEY:
        yield "خطأ: ANTHROPIC_API_KEY غير مُعيَّن"; return
    async with httpx.AsyncClient(timeout=180) as c:
        async with c.stream(
            "POST", "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model or MODEL_CLAUDE_MAIN, "max_tokens": max_tokens,
                  "system": system, "messages": messages, "stream": True},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                        if d.get("type") == "content_block_delta":
                            yield d["delta"].get("text", "")
                    except Exception:
                        pass

# ══════════════════════════════════════════════════════════
# استدعاء Ollama (محلي — مجاني 100%)
# ══════════════════════════════════════════════════════════
MODEL_OLLAMA_LLM = os.getenv("MODEL_OLLAMA_LLM", "qwen2.5:1.5b")  # 1.5b أسرع بـ 30x من 7b

async def stream_ollama(system: str, messages: list[dict], max_tokens: int = 3000) -> AsyncIterator[str]:
    """بث الإجابة عبر Ollama المحلي"""
    msgs = [{"role": "system", "content": system}] + messages
    async with httpx.AsyncClient(timeout=300) as c:
        async with c.stream(
            "POST", f"{OLLAMA_HOST}/api/chat",
            json={"model": MODEL_OLLAMA_LLM, "messages": msgs, "stream": True,
                  "keep_alive": "15m",          # إبقاء النموذج محملاً 15 دقيقة
                  "options": {
                      "num_predict": max_tokens,
                      "num_ctx": 3072,           # ← زيادة 2× لتحليل أعمق وسياق أشمل
                      "temperature": 0.05,       # استقرار أعلى — أدق للنصوص القانونية
                      "top_k": 20,               # تقليل التشتت — ردود أكثر تركيزاً
                      "top_p": 0.85,
                      "repeat_penalty": 1.15,    # يمنع التكرار الممل
                  }},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    try:
                        d = json.loads(line)
                        t = d.get("message", {}).get("content", "")
                        if t: yield t
                        if d.get("done"): break
                    except Exception:
                        pass

async def call_ollama(system: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """استدعاء Ollama المحلي بدون streaming"""
    parts = []
    async for t in stream_ollama(system, messages, max_tokens):
        parts.append(t)
    return "".join(parts)

# ══════════════════════════════════════════════════════════
# مولّد الإجابة الموحّد — OpenAI → Gemini → Claude → Ollama
# ══════════════════════════════════════════════════════════
async def _generate_answer(model: str, system: str, messages: list[dict],
                           max_tokens: int = 3000) -> str:
    """
    مولّد الإجابة الموحّد — يستخدم LLMGateway عند توفره.
    Fallback chain: OpenAI → Gemini → Claude → Ollama
    """
    # ── المسار الجديد: LLMGateway (الأفضل) ──
    if app_state.GW_AVAILABLE:
        return await app_state.llm_gw.call(
            system=system,
            messages=messages,
            provider=model or PRIMARY_MODEL,
            max_tokens=max_tokens,
        )

    # ── المسار القديم: fallback إذا لم يتوفر الـ gateway ──
    effective = model or PRIMARY_MODEL
    if effective == "openai" or (OPENAI_KEY and effective not in ("gemini","claude","ollama")):
        try:
            parts: list[str] = []
            async for t in stream_openai(system, messages, max_tokens=max_tokens):
                parts.append(t)
            result = "".join(parts)
            if result.strip():
                return result
        except Exception as e:
            log.warning("OpenAI فشل: %s", e)

    if effective == "gemini" or (GEMINI_KEY and not OPENAI_KEY):
        try:
            parts = []
            async for t in stream_gemini(system, messages, max_tokens=max_tokens):
                parts.append(t)
            result = "".join(parts)
            if result.strip():
                return result
        except Exception as e:
            log.warning("Gemini فشل: %s", e)

    if ANTHROPIC_KEY:
        try:
            return await call_claude(system, messages, max_tokens=max_tokens)
        except Exception as e:
            log.warning("Claude فشل: %s", e)

    parts = []
    async for t in stream_ollama(system, messages, max_tokens=max_tokens):
        parts.append(t)
    return "".join(parts)

# ══════════════════════════════════════════════════════════
# استدعاء OpenAI / ChatGPT (النموذج الرئيسي)
# ══════════════════════════════════════════════════════════
async def stream_openai(system: str, messages: list[dict], max_tokens: int = 3000) -> AsyncIterator[str]:
    """بث الإجابة عبر OpenAI API (GPT-4o)"""
    if not OPENAI_KEY:
        yield "خطأ: OPENAI_API_KEY غير مُعيَّن"; return
    msgs = [{"role": "system", "content": system}] + messages
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL_OPENAI,
                    "messages": msgs,
                    "max_tokens": max_tokens,
                    "stream": True,
                    "temperature": 0.3,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    log.error("OpenAI error %d: %s", resp.status_code, body[:200])
                    yield f"خطأ OpenAI ({resp.status_code})"; return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue
    except Exception as e:
        log.error("stream_openai: %s", e)
        yield f"خطأ في الاتصال بـ OpenAI: {e}"

async def call_openai(system: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """استدعاء OpenAI بدون streaming"""
    parts = []
    async for t in stream_openai(system, messages, max_tokens=max_tokens):
        parts.append(t)
    return "".join(parts)

# استدعاء Gemini (مجاناً)
# ══════════════════════════════════════════════════════════
async def stream_gemini(system: str, messages: list[dict], max_tokens: int = 3000) -> AsyncIterator[str]:
    """بث الإجابة عبر Gemini API (مجاني)"""
    if not GEMINI_KEY:
        yield "خطأ: GEMINI_API_KEY غير مُعيَّن"; return
    # تحويل الرسائل لصيغة Gemini
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    # إضافة system_instruction عبر الحقل الرسمي لـ Gemini API (أكثر فاعلية من حقنه في أول رسالة)
    request_body = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.3,          # استقرار أعلى للنصوص القانونية
            "topP": 0.85,
            "topK": 40,
        },
    }
    async with httpx.AsyncClient(timeout=180) as c:
        async with c.stream(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_GEMINI}:streamGenerateContent?alt=sse&key={GEMINI_KEY}",
            json=request_body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                        text = d["candidates"][0]["content"]["parts"][0]["text"]
                        yield text
                    except Exception:
                        pass

# ══════════════════════════════════════════════════════════
# Legal Query Expansion Map — concept → specific articles
# Colloquial phrasing in user queries → precise legal terms
# with article numbers that live in the Qatari law corpus.
# ══════════════════════════════════════════════════════════

_LEGAL_QUERY_EXPANSION: dict[str, list[str]] = {
    # ── جرائم الأموال ──
    "سرق|سرقة|يسرق": [
        "سرقة المادة 317 عقوبات",
        "خيانة أمانة المادة 354 عقوبات",
        "اختلاس المادة 161 عقوبات",
    ],
    "موظف سرق|سرقة موظف|سرق من الشركة|سرق من العمل": [
        "خيانة الأمانة المادة 354 عقوبات موظف",
        "اختلاس موظف عام المادة 161 عقوبات",
        "سرقة المادة 317 عقوبات",
    ],
    "خيانة أمانة|خيانة الأمانة|خان الأمانة": [
        "خيانة الأمانة المادة 354 قانون العقوبات",
    ],
    "اختلاس|اختلس": [
        "اختلاس المادة 161 قانون العقوبات موظف عام",
    ],
    "نصب|احتيال|نصاب|احتال": [
        "النصب والاحتيال المادة 349 قانون العقوبات",
        "الاستيلاء بطريق الاحتيال",
    ],
    "تزوير|زوّر|مزوّر": [
        "تزوير محررات رسمية المادة 255 عقوبات",
        "تزوير محررات عرفية المادة 260 عقوبات",
        "استعمال محرر مزور المادة 261 عقوبات",
    ],
    "رشوة|رشا|ارتشاء": [
        "الرشوة المادة 140 قانون العقوبات",
    ],
    "شيك بدون رصيد|شيك طاير|شيك مرتجع|شيك بدون": [
        "شيك بدون رصيد المادة 357 قانون العقوبات",
    ],

    # ── جرائم الاعتداء ──
    "ضرب|ضربني|اعتداء|اعتدى": [
        "الضرب والإيذاء المادة 304 قانون العقوبات",
        "الإيذاء العمدي المادة 305 عقوبات",
    ],
    "قتل|قتله|قاتل": [
        "القتل العمد المادة 300 قانون العقوبات",
        "القتل الخطأ المادة 308 قانون العقوبات",
    ],
    "تهديد|هدد|هددني": [
        "التهديد المادة 318 قانون العقوبات",
    ],

    # ── ظروف مشددة ومخففة ──
    "سوابق|سابقة|عود|معاود|مكرر|تكرار": [
        "العود المادة 58 قانون العقوبات تشديد العقوبة",
        "سوابق جنائية صحيفة الحالة الجنائية",
    ],
    "اعتراف|اعترف|أقر|إقرار": [
        "الاعتراف المادة 232 قانون الإجراءات الجنائية شروط صحة",
        "الإقرار القضائي",
    ],
    "دفاع شرعي|دفاع عن النفس|حق الدفاع": [
        "الدفاع الشرعي المادة 43 قانون العقوبات إباحة",
    ],

    # ── إجراءات ──
    "تعويض|تعويض مدني|ضرر|أضرار": [
        "التعويض عن الضرر المادة 199 القانون المدني",
        "الادعاء بالحق المدني المادة 20 إجراءات جنائية",
        "دعوى التعويض المدني",
    ],
    "خطوات|إجراءات|كيف أرفع|ماذا أفعل|بلاغ": [
        "إجراءات رفع الدعوى الجنائية النيابة العامة",
        "تقديم بلاغ الشرطة",
        "الادعاء المدني أمام المحكمة الجنائية المادة 20",
    ],
    "تقادم|سقوط|مدة التقادم|انقضاء الدعوى": [
        "تقادم الدعوى الجنائية المادة 14 إجراءات جنائية",
        "انقضاء الدعوى بمضي المدة",
    ],

    # ── رد الاعتبار ──
    "رد الاعتبار|رد اعتبار|اعتبار قضائي|محو السوابق": [
        "رد الاعتبار القضائي المادة 380 إجراءات جنائية",
        "رد الاعتبار بحكم القانون المادة 384 إجراءات جنائية",
        "محو السوابق من الصحيفة الجنائية",
    ],

    # ── قانون الأسرة ──
    "حضانة|حاضنة|حاضن": [
        "الحضانة المادة 166 قانون الأسرة",
        "سن الحضانة المادة 173 قانون الأسرة",
        "سقوط الحضانة المادة 175 قانون الأسرة",
    ],
    "طلاق|طلّق|طلقني|خلع|مخالعة": [
        "الطلاق المادة 109 قانون الأسرة",
        "الخلع المادة 120 قانون الأسرة",
    ],
    "نفقة|نفقة زوجة|نفقة أطفال|نفقة أولاد": [
        "نفقة الزوجة المادة 57 قانون الأسرة",
        "نفقة الأولاد المادة 75 قانون الأسرة",
    ],
    "زواج|عقد زواج|زوجة|تزوج": [
        "عقد الزواج المادة 12 قانون الأسرة",
        "شروط الزواج",
    ],

    # ── قانون العمل ──
    "فصل|فصلني|فصل تعسفي|طرد|طردني": [
        "الفصل التعسفي المادة 49 قانون العمل",
        "إنهاء عقد العمل بدون سبب",
        "التعويض عن الفصل التعسفي",
    ],
    "مكافأة نهاية الخدمة|مكافأة خدمة|نهاية خدمة": [
        "مكافأة نهاية الخدمة المادة 54 قانون العمل",
    ],
    "راتب|أجر|رواتب متأخرة": [
        "الأجر المادة 26 قانون العمل",
        "تأخر صرف الراتب",
    ],
    "إجازة|إجازات|إجازة سنوية": [
        "الإجازة السنوية المادة 37 قانون العمل",
    ],
    "استقالة|استقلت|قدمت استقالتي": [
        "الاستقالة المادة 49 قانون العمل إنهاء العقد",
        "مدة الإخطار",
    ],
    "شهادة خبرة|شهادة عمل": [
        "شهادة الخبرة المادة 50 قانون العمل",
    ],
}


def _expand_legal_query(query: str) -> list[str]:
    """Expand a natural-language legal query into precise legal phrases
    that carry specific article numbers. Each expansion is a short
    query suitable for hybrid search.

    Example: "موظف سرق وعنده سوابق واعترف"
        → ["خيانة الأمانة المادة 354 عقوبات موظف",
           "العود المادة 58 قانون العقوبات تشديد العقوبة",
           "الاعتراف المادة 232 قانون الإجراءات الجنائية شروط صحة"]
    """
    q_lower = (query or "").lower()
    expansions: list[str] = []
    matched_keys: set[str] = set()
    # Longest key groups first (more specific match wins)
    sorted_keys = sorted(
        _LEGAL_QUERY_EXPANSION.keys(), key=lambda k: -len(k),
    )
    for key_group in sorted_keys:
        if key_group in matched_keys:
            continue
        for trigger in (t.strip() for t in key_group.split("|")):
            if trigger and trigger in q_lower:
                matched_keys.add(key_group)
                for exp in _LEGAL_QUERY_EXPANSION[key_group]:
                    if exp not in expansions:
                        expansions.append(exp)
                break
    return expansions[:8]


# ══════════════════════════════════════════════════════════
# Direct Article Injection — precise SQL fetch of known articles
# Bypasses RAG scoring for articles we KNOW we want, by using the
# (article_number, law_pattern) pairs extracted from the expansion
# results and querying PostgreSQL directly.
# ══════════════════════════════════════════════════════════

# Law-name patterns tuned to actual Qatari corpus in `chunks.law_name`.
# Patterns are ILIKE-ready (contain % wildcards).
_LAW_NAME_PATTERNS: dict[str, str] = {
    "إجراءات جنائية":   "%الإجراءات الجنائية%",
    "إجراءات جزائية":   "%الإجراءات الجزائية%",
    "إجراءات":          "%الإجراءات%جنائية%",
    "عقوبات":           "%العقوبات%11/2004%",
    "قانون العقوبات":   "%العقوبات%11/2004%",
    "قانون العمل":      "%قانون العمل رقم 14%",
    "عمل":              "%قانون العمل رقم 14%",
    "قانون الأسرة":     "%الأسرة رقم 22/2006%",
    "الأسرة":           "%الأسرة رقم 22/2006%",
    "أسرة":             "%الأسرة رقم 22/2006%",
    "المدني":           "%المدني%",
    "قانون المدني":     "%المدني%",
    "مدني":             "%المدني%",
    "التجارة":          "%قانون التجارة%",
    "تجارة":            "%قانون التجارة%",
    "الجرائم الإلكترونية": "%الجرائم الإلكترونية%",
    "إلكترونية":        "%الجرائم الإلكترونية%",
    "مخدرات":           "%مكافحة المخدرات%",
}

_ARTICLE_NUM_RE = re.compile(r"الماد[ةه]\s*\(?\s*(\d+)", re.UNICODE)


def _extract_article_targets(
    expansions: list[str],
) -> list[tuple[str, str]]:
    """From a list of legal-expansion phrases (output of
    `_expand_legal_query`), extract `(article_number, law_pattern)`
    pairs suitable for direct SQL fetch.

    Example:
      "خيانة الأمانة المادة 354 عقوبات" → ("354", "%العقوبات%11/2004%")
      "رد الاعتبار القضائي المادة 380 إجراءات جنائية"
                                       → ("380", "%الإجراءات الجنائية%")
    """
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for exp in expansions:
        m = _ARTICLE_NUM_RE.search(exp)
        if not m:
            continue
        art_num = m.group(1)
        exp_lc = exp.lower()
        pattern: str | None = None
        # Prefer longest-key-first — "الإجراءات الجنائية" before "إجراءات"
        for key in sorted(_LAW_NAME_PATTERNS, key=lambda k: -len(k)):
            if key in exp_lc or key in exp:
                pattern = _LAW_NAME_PATTERNS[key]
                break
        if pattern is None:
            pattern = "%"
        k = (art_num, pattern)
        if k not in seen:
            seen.add(k)
            targets.append(k)
    return targets[:12]


async def direct_article_fetch(
    pool, article_targets: list[tuple[str, str]],
    max_per_article: int = 2,
) -> list[dict]:
    """Fetch specific articles directly from the chunks table by
    (article_number, law_name pattern). Returns chunk-shaped dicts
    with score=0.99 and source_type='direct_injection' so the caller
    can prioritize them."""
    if not pool or not article_targets:
        return []
    results: list[dict] = []
    seen_keys: set[tuple] = set()
    try:
        async with pool.acquire() as conn:
            for art_num, law_pattern in article_targets:
                try:
                    rows = await conn.fetch(
                        """
                        SELECT id, law_id, source, law_name, law_number,
                               law_year, article_number, content, domain
                        FROM chunks
                        WHERE article_number = $1
                          AND law_name ILIKE $2
                          AND (is_active IS NULL OR is_active = TRUE)
                          AND law_name NOT ILIKE '%أحكام محكمة التمييز%'
                        ORDER BY LENGTH(content) DESC
                        LIMIT $3
                        """,
                        art_num, law_pattern, max_per_article,
                    )
                except Exception as e:
                    log.warning(
                        "direct_article_fetch art=%s law=%s: %s",
                        art_num, law_pattern, e,
                    )
                    continue
                for r in rows:
                    key = (r["law_name"], r["article_number"])
                    if key not in seen_keys:
                        seen_keys.add(key)
                        d = dict(r)
                        d["score"] = 0.99
                        d["source_type"] = "direct_injection"
                        results.append(d)
    except Exception as e:
        log.warning("direct_article_fetch pool acquire: %s", e)
        return []
    log.info(
        "direct_article_fetch: %d targets → %d chunks",
        len(article_targets), len(results),
    )
    return results


# ══════════════════════════════════════════════════════════
# Chain of Thought — تفكير داخلي
# ══════════════════════════════════════════════════════════
def rule_based_cot(q: str) -> dict:
    """
    تحليل قائم على القواعد — يعمل مع جميع النماذج بدون استدعاء LLM.
    يكتشف مجال القانون ويولّد 2-4 استعلامات بحث متنوعة.
    الآن يدعم: العبارات المركبة (رد الاعتبار)، المصطلحات القصيرة، البحث المتعدد المجالات.
    """
    kws = extract_kw(q)
    domain = detect_legal_domain(kws)
    domain_ar = _LEGAL_DOMAINS[domain]['ar'] if domain else ""

    # استعلام 1: السؤال الأصلي
    queries = [q]

    # ── اكتشاف العبارات المركبة الثابتة (الأولوية القصوى) ──
    # مثال: 'رد الاعتبار' → ['رد الاعتبار', 'رد اعتبار', 'إعادة الاعتبار']
    fixed_phrases = _detect_fixed_phrases(q)
    for fp in fixed_phrases[:2]:
        if fp not in queries:
            queries.insert(1, fp)  # أضفها بعد السؤال الأصلي مباشرةً

    # استعلام: الكلمات المفتاحية الأساسية فقط (بدون أدوات)
    core = ' '.join(kws[:4])
    if core and core != q and core not in queries:
        queries.append(core)

    # استعلام: مع مصطلح المجال القانوني (إذا عُرف)
    if domain and kws:
        domain_term = _LEGAL_DOMAINS[domain]['terms'][0]
        domain_q = f"{' '.join(kws[:2])} {domain_term}"
        if domain_q not in queries:
            queries.append(domain_q)

    # أضف المرادفات كاستعلام إضافي إذا كانت متاحة
    expanded = expand_keywords_with_synonyms(kws)
    extra_kws = [k for k in expanded if k not in kws]
    if extra_kws:
        syn_q = ' '.join(extra_kws[:3])
        if syn_q not in queries:
            queries.append(syn_q)

    # ═══ Legal Query Expansion — colloquial → specific articles ═══
    legal_expansions = _expand_legal_query(q)
    if legal_expansions:
        for exp in legal_expansions[:3]:
            if exp not in queries:
                queries.append(exp)
        log.info(
            "legal_expansion: %d for '%s': %s",
            len(legal_expansions),
            q[:40],
            [e[:45] for e in legal_expansions[:3]],
        )

    complexity = "معقد" if len(kws) >= 5 else "بسيط" if len(kws) <= 2 else "متوسط"
    law_areas = [domain_ar] if domain_ar else []

    # ── كشف الغموض ──
    needs_clarif, clarif_q = _detect_ambiguity(q, kws)

    # التكييف القانوني المبدئي
    legal_char = ""
    if domain == "criminal":
        legal_char = "مسألة جنائية / عقوبات"
    elif domain == "civil":
        legal_char = "مسألة مدنية / التزامات"
    elif domain == "family":
        legal_char = "أحوال شخصية وأسرة"
    elif domain == "commercial":
        legal_char = "مسألة تجارية"
    elif domain == "labor":
        legal_char = "علاقة عمل / قانون العمل"
    elif domain == "administrative":
        legal_char = "مسألة إدارية"
    elif domain == "cyber":
        legal_char = "جريمة إلكترونية / معلوماتية"
    elif domain == "procedural":
        legal_char = "إجراءات قضائية"

    log.info("rule_based_cot: domain=%s, queries=%d, kws=%s, fixed=%s, clarif=%s",
             domain, len(queries), kws[:3], fixed_phrases[:2], needs_clarif)
    return {
        "search_queries": queries[:8],
        "law_areas": law_areas,
        "complexity": complexity,
        "legal_characterization": legal_char,
        "needs_clarification": needs_clarif,
        "clarification_question": clarif_q,
        "missing_facts": [],
    }


async def chain_of_thought(q: str, model: str = "ollama") -> dict:
    """
    يحلل السؤال ويستخرج خطة البحث.
    - جميع النماذج: يستخدم rule_based_cot (سريع، بدون LLM)
    - Claude فقط: يُشغّل التحليل العميق إضافةً
    """
    # الاستخدام القاعدي أولاً (يعمل دائماً)
    base = rule_based_cot(q)

    # مع Claude فقط: عزّز بتحليل LLM
    if model not in ("ollama", "gemini") and ANTHROPIC_KEY:
        try:
            msgs = [{"role": "user", "content": f"السؤال: {q}"}]
            raw = await call_claude(system=COT_SYSTEM, messages=msgs,
                                    model=MODEL_CLAUDE_FAST, max_tokens=400)
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
                # ادمج: احتفظ بـ search_queries من LLM مع إضافة queries القاعدية
                llm_queries = result.get("search_queries", [])
                merged = list(dict.fromkeys(llm_queries + base["search_queries"]))[:4]
                result["search_queries"] = merged
                log.info("CoT+LLM: complexity=%s, areas=%s", result.get("complexity"), result.get("law_areas"))
                return result
        except Exception as e:
            log.warning("CoT LLM فشل — استخدام القاعدي: %s", e)

    return base

# ══════════════════════════════════════════════════════════
# Embedding
# ══════════════════════════════════════════════════════════
async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{OLLAMA_HOST}/api/embeddings",
                         json={"model": "nomic-embed-text", "prompt": text[:2000]})
        r.raise_for_status()
        return r.json()["embedding"]

# ══════════════════════════════════════════════════════════
# Vector Search
# ══════════════════════════════════════════════════════════
async def vector_search(conn, emb: list[float], top_k: int = 20) -> list[dict]:
    emb_str = "[" + ",".join(map(str, emb)) + "]"
    # فلتر is_active: لا تُعيد قوانين ملغاة أو قديمة متجاوَزة
    rows = await conn.fetch("""
        SELECT id, law_id, source, law_name, law_number, law_year, article_number, content, domain,
               1 - (embedding <=> $1::vector) AS score
        FROM chunks
        WHERE (is_active IS NULL OR is_active = TRUE)
        ORDER BY embedding <=> $1::vector LIMIT $2
    """, emb_str, top_k)
    results = []
    for r in rows:
        d = dict(r)
        # أضف منحة السنة للقوانين الحديثة
        d["score"] = min(1.0, float(d["score"]) + _law_year_score_boost(d.get("law_year", "")))
        results.append(d)
    return results

# ══════════════════════════════════════════════════════════
# Keyword Search
# ══════════════════════════════════════════════════════════
_AR_PATTERN = re.compile(r'[\u0600-\u06FF]')

def _is_quality_chunk(content: str) -> bool:
    """
    يرفض المقاطع الرديئة: قوائم السنوات، روابط الميزان، محتوى تنقل موقع.
    المشكلة: بعض مقاطع "مقدمة" تحتوي فقط على "الميزان | التشريعات | ..." أو أرقام سنوات أو
    عناصر تنقل (إبحث في مواد التشريع / اتصل بنا / ملفات متعلقة...).
    """
    stripped = content.strip()
    if len(stripped) < 50:
        return False
    ar_chars = len(_AR_PATTERN.findall(stripped))
    # يجب أن يكون ربع المحتوى على الأقل عربياً (يُصفّي أرقام السنوات وروابط HTML)
    if ar_chars < 50 or ar_chars / max(len(stripped), 1) < 0.20:
        return False
    # نصوص التنقل الشائعة في موقع الميزان (بدون نصوص قانونية حقيقية)
    _NAV_PATTERNS = ('إبحث في مواد التشريع', 'ملفات متعلقة', 'اتصل بنا', 'إتصل بنا',
                     'almeezan@', 'الميزان | البوابة')
    if any(p in stripped for p in _NAV_PATTERNS):
        return False
    return True

async def keyword_search(conn, keywords: list[str], top_k: int = 15,
                         phrases: list[str] | None = None) -> list[dict]:
    """
    بحث كلمي متعدد المستويات:
    1. بحث بالعبارة الكاملة (أعلى دقة)
    2. بحث AND بـ 3 كلمات
    3. بحث AND بـ 2 كلمات
    4. بحث OR لكل كلمة
    يستخدم الكلمات الأصلية (لا المعيارية) في ILIKE لتجنّب مشاكل التشكيل.
    """
    if not keywords: return []
    # جميع المتغيرات (أصلية + معيارية + جذور) لحساب التطابقات
    variants = list(dict.fromkeys(v for kw in keywords[:8] for v in kw_variants(kw) if len(v) >= 3))
    # الكلمات الأصلية فقط للـ ILIKE (أكثر دقة)
    orig_kws = keywords[:6]   # الأصلية من extract_kw (بدون تعيير) — مُقيَّدة للـ AND/OR للدقة

    if not variants: return []
    all_res: dict = {}

    # ── (-1). بحث مباشر بعمود article_number إذا وُجد pattern "المادة X" ──
    # يحل مشكلة ILIKE '%المادة 54%' الذي يجد أرقاماً مشابهة كـ art:5
    _art_exact_num: str | None = None
    _art_re_kw = re.compile(r'^المادة\s+(\d+)$')
    for _src in (list(phrases or []) + list(keywords[:6])):
        _mm = _art_re_kw.match(_src.strip())
        if _mm:
            _art_exact_num = _mm.group(1)
            break
    if _art_exact_num:
        try:
            rows_art = await conn.fetch(
                "SELECT id, law_id, source, law_name, law_number, law_year,"
                " article_number, content, domain"
                " FROM chunks WHERE article_number = $1"
                " AND (is_active IS NULL OR is_active = TRUE) LIMIT $2",
                _art_exact_num, top_k * 2,
            )
            for r in rows_art:
                k = (r["law_name"], r["article_number"])
                all_res[k] = {**dict(r), "score": 0.99,
                              "keyword_match": True, "match_count": 1, "exact_article": True}
            log.info("keyword article_number='%s' → %d نتيجة مباشرة", _art_exact_num, len(rows_art))
        except Exception as _art_kw_err:
            log.warning("keyword article_number search: %s", _art_kw_err)

    # ── 0. بحث بالعبارة الكاملة (أعلى دقة — score = 0.97) ──
    # LIMIT أكبر (top_k*5) لأن PostgreSQL يعيد الصفوف بترتيب عشوائي (heap scan)
    # وقد يكون الصف الأكثر صلة في النهاية → نجلب أكثر ثم نُرتّب بالسكور
    # يُوسَّع كل عبارة بمتغيرات ال (رد اعتبار ↔ رد الاعتبار)
    if phrases:
        phrases_expanded = []
        for ph in phrases[:8]:   # رُفع من 5 → 8 لتشمل المصطلحات القانونية ذات الأولوية
            for variant in _al_phrase_variants(ph):
                if variant not in phrases_expanded:
                    phrases_expanded.append(variant)
        for ph in phrases_expanded[:10]:   # رُفع من 6 → 10
            try:
                rows = await conn.fetch(
                    "SELECT id, law_id, source, law_name, law_number, law_year, article_number, content, domain"
                    " FROM chunks WHERE content ILIKE $1"
                    " AND (is_active IS NULL OR is_active = TRUE) LIMIT $2", f"%{ph}%", top_k * 5)
                for r in rows:
                    if not _is_quality_chunk(r["content"]): continue
                    k = (r["law_name"], r["article_number"])
                    content_norm = normalize_ar(r["content"])
                    mc = sum(1 for v in variants if v in content_norm)
                    # مكافأة كبيرة إذا كانت إحدى العبارات تظهر في اسم القانون نفسه
                    law_name_lower = r["law_name"].lower()
                    phrases_here = phrases or []
                    # مكافأة فقط للعبارات الثلاثية (3 كلمات) لتجنب التحيز نحو قوانين الأسعار
                    # مثال: "الحد الأقصى" تظهر في مئات قوانين الأسعار → لا مكافأة
                    # لكن "الحد الأقصى لساعات" أو "لساعات العمل" أكثر تحديداً → مكافأة
                    law_name_phrase_boost = 0.06 if any(
                        ph.lower() in law_name_lower and len(ph.split()) >= 3
                        for ph in phrases_here
                    ) else 0.0
                    # مكافأة ثانية: اسم القانون يحتوي كلمة من الاستعلام (جذر ≥ 4 حروف)
                    # نستثني: حد/الحد/قطر (شائعة جداً) + كل أشكال "أقصى" (تظهر في قوانين الأسعار بكثرة)
                    _COMMON_EXCLUDED = {'الحد','حد','قطر','الأقصى','الاقصا','أقصى','اقصا','الأكثر','الاكثر','رقم'}
                    law_name_norm = normalize_ar(r["law_name"])
                    law_kw_boost = 0.03 if any(
                        v in law_name_norm for v in variants
                        if len(v) >= 4 and v not in _COMMON_EXCLUDED
                    ) else 0.0
                    old_score = all_res.get(k, {}).get("score", 0)
                    # مقاطع "مقدمة" تحصل على عقوبة -0.12: المواد المرقّمة أكثر دقة بكثير
                    intro_penalty = -0.12 if str(r["article_number"]) in ('مقدمة', 'مقدمه', '') else 0.0
                    year_boost = _law_year_score_boost(r["law_year"])
                    # قاعدة 0.80: تترك مجالاً لـ mc*0.10 + boosts للتمييز بين النتائج
                    new_score = min(0.97, 0.80 + mc/max(len(variants),1)*0.10 + law_name_phrase_boost + law_kw_boost + intro_penalty + year_boost)
                    if new_score > old_score:
                        all_res[k] = {**dict(r), "score": new_score,
                                      "keyword_match": True, "match_count": mc, "phrase_match": True}
            except Exception as e:
                log.warning("phrase '%s': %s", ph, e)

    # ── بحث AND للكلمات الأساسية (الأصلية — بدون تعيير) ──
    # نجرّب 3 كلمات أولاً (أكثر دقة)، ثم 2 كلمات دائماً (لا نوقف)
    # السبب: بعض الكلمات مشوّهة في PDF فيفشل الـ AND بها، لكن مجموعة مختلفة تنجح
    and_candidates = orig_kws[:6]   # زيادة من 4 إلى 6 لتشمل كل الكلمات المفتاحية المهمة
    for n_kws in ([3, 2] if len(orig_kws) >= 3 else [2]):
        if len(and_candidates) < n_kws:
            continue
        primary = and_candidates[:n_kws]
        try:
            params = [f"%{v}%" for v in primary] + [top_k * 5]
            rows = await conn.fetch(
                "SELECT id, law_id, source, law_name, law_number, law_year, article_number, content, domain FROM chunks"
                f" WHERE {' AND '.join(f'content ILIKE ${i+1}' for i in range(len(primary)))}"
                f" AND (is_active IS NULL OR is_active = TRUE)"
                f" LIMIT ${len(primary)+1}", *params)
            kw_added = 0
            for r in rows:
                if not _is_quality_chunk(r["content"]): continue
                k = (r["law_name"], r["article_number"])
                content_norm = normalize_ar(r["content"])
                mc = sum(1 for v in variants if v in content_norm)
                law_norm = normalize_ar(r["law_name"])
                _EXCL = {'الحد','حد','قطر','الأقصى','الاقصا','أقصى','اقصا','الأكثر','الاكثر','رقم'}
                law_kw_b = 0.03 if any(
                    v in law_norm for v in variants if len(v) >= 4 and v not in _EXCL
                ) else 0.0
                score_boost = 0.02 if n_kws >= 3 else 0.0
                intro_penalty = -0.10 if str(r["article_number"]) in ('مقدمة', 'مقدمه', '') else 0.0
                year_boost = _law_year_score_boost(r["law_year"])
                new_score = min(0.97, 0.76 + score_boost + law_kw_b + mc/max(len(variants),1)*0.12 + intro_penalty + year_boost)
                old_score = all_res.get(k, {}).get("score", 0)
                if new_score >= old_score:   # تحديث فقط إذا أفضل
                    all_res[k] = {**dict(r), "score": new_score,
                                  "keyword_match": True, "match_count": mc}
                    kw_added += 1
            log.info("AND(%d): found %d rows, added %d new", n_kws, len(rows), kw_added)
            # نتابع دائماً للـ 2-keyword AND بغض النظر (لمعالجة تشويه PDF)
        except Exception as e:
            log.warning("kw AND(%d): %s", n_kws, e)

    # ── بحث AND موسّع: يستبدل الاسم بالفعل (عقوبة→عاقب، سرقة→سرق) ──
    # المشكلة: القانون يقول "يُعاقب كل من سرق" لا "عقوبة السرقة"
    # الحل: استخدم الجذر الفعلي فقط لكل كلمة لها توسّع قانوني.
    # مثال: 'شروط الطلاق وحضانة الأطفال' → فقط 'طلق' AND 'حاضن'
    #         (شروط والأطفال لا توسع لهما → نتجاهلهما لأنهما يُضيّقان البحث)
    expanded_only = []  # الكلمات المُوسَّعة فقط (التي لها فعل في القانون)
    # نفحص القائمة الكاملة (keywords وليس orig_kws) لأن المصطلحات القانونية قد تأتي في مواضع متأخرة
    for kw in keywords:
        n = normalize_ar(kw)
        # جرّد بادئة و (وحضانه → حضانه)
        if n.startswith('و') and len(n) >= 5:
            n = n[1:]
        # جرّد بادئة ال/وال/بال (السرقه→سرقه، العقوبه→عقوبه، الطلاق→طلاق)
        n_clean = re.sub(r'^(وال|فال|بال|كال|ال)', '', n)
        if len(n_clean) >= 3:
            n = n_clean
        exps = _LEGAL_EXPANSIONS.get(n, [])
        if exps:
            # اختر أقصر صيغة (≥3 حروف) — أكثر شمولاً في ILIKE:
            # عقوبه→['يعاقب','عاقب'] → 'عاقب' يطابق 'يُعاقب'
            # طلاق→['طلق','مطلقه','طالق'] → 'طلق' يطابق 'مطلقة'/'يطلق'
            best = min((e for e in exps if len(e) >= 3), key=len, default=exps[0])
            expanded_only.append(best)
    # نفّذ فقط إذا وُجد توسّع لكلمة واحدة على الأقل
    if expanded_only:
        for n_kws in ([2, 1] if len(expanded_only) >= 2 else [1]):
            if len(expanded_only) < n_kws:
                continue
            primary_exp = expanded_only[:n_kws]
            try:
                params = [f"%{v}%" for v in primary_exp] + [top_k * 5]
                rows = await conn.fetch(
                    "SELECT id, law_id, source, law_name, law_number, law_year, article_number, content, domain FROM chunks"
                    f" WHERE {' AND '.join(f'content ILIKE ${i+1}' for i in range(len(primary_exp)))}"
                    f" AND (is_active IS NULL OR is_active = TRUE)"
                    f" LIMIT ${len(primary_exp)+1}", *params)
                exp_added = 0
                for r in rows:
                    if not _is_quality_chunk(r["content"]): continue
                    k = (r["law_name"], r["article_number"])
                    content_norm = normalize_ar(r["content"])
                    mc = sum(1 for v in variants if v in content_norm)
                    law_norm = normalize_ar(r["law_name"])
                    _EXCL = {'الحد','حد','قطر','الأقصى','الاقصا','أقصى','اقصا','الأكثر','الاكثر','رقم'}
                    law_kw_b = 0.03 if any(v in law_norm for v in variants if len(v) >= 4 and v not in _EXCL) else 0.0
                    intro_penalty = -0.10 if str(r["article_number"]) in ('مقدمة', 'مقدمه', '') else 0.0
                    score_boost = 0.02 if n_kws >= 3 else 0.0
                    year_boost = _law_year_score_boost(r["law_year"])
                    new_score = min(0.97, 0.72 + score_boost + law_kw_b + mc/max(len(variants),1)*0.12 + intro_penalty + year_boost)
                    old_score = all_res.get(k, {}).get("score", 0)
                    if new_score >= old_score:
                        all_res[k] = {**dict(r), "score": new_score, "keyword_match": True, "match_count": mc}
                        exp_added += 1
                log.info("AND-expanded(%d) kws=%s: found %d rows, added %d", n_kws, primary_exp, len(rows), exp_added)
            except Exception as e:
                log.warning("kw AND-expanded(%d): %s", n_kws, e)

    # ── بحث OR لكل كلمة أصلية كاحتياط ──
    if len(all_res) < top_k:
        # استخدم الكلمات الأصلية + الجذور (بعد حذف البادئة) للبحث
        search_terms = list(dict.fromkeys(
            v for kw in orig_kws[:6]
            for v in kw_variants(kw)
            if len(v) >= 3
        ))[:10]
        for v in search_terms:
            try:
                rows = await conn.fetch(
                    "SELECT id, law_id, source, law_name, law_number, law_year, article_number, content, domain"
                    " FROM chunks WHERE content ILIKE $1"
                    " AND (is_active IS NULL OR is_active = TRUE) LIMIT $2", f"%{v}%", top_k * 3)
                for r in rows:
                    if not _is_quality_chunk(r["content"]): continue
                    k = (r["law_name"], r["article_number"])
                    if k not in all_res:
                        content_norm = normalize_ar(r["content"])
                        mc = sum(1 for vv in variants if vv in content_norm)
                        law_norm = normalize_ar(r["law_name"])
                        law_mc = sum(1 for vv in variants if vv in law_norm)
                        law_boost = min(0.04, law_mc/max(len(variants),1)*0.08)
                        year_boost = _law_year_score_boost(r["law_year"])
                        all_res[k] = {**dict(r), "score": min(0.97, 0.62 + law_boost + mc/max(len(variants),1)*0.15 + year_boost),
                                      "keyword_match": True, "match_count": mc}
            except Exception as e:
                log.warning("kw OR '%s': %s", v, e)

    return sorted(all_res.values(), key=lambda x: x["score"], reverse=True)[:top_k]

# ══════════════════════════════════════════════════════════
# Exact Article Search — بحث دقيق بعمود article_number
# ══════════════════════════════════════════════════════════
_EXACT_ART_RE  = re.compile(r'المادة\s*[(\[]?\s*(\d+)\s*[)\]]?', re.UNICODE)
_LAW_HINT_RE   = re.compile(
    r'المادة\s*\d+\s*(?:من|في|لـ|بـ|الواردة في|المنصوص في|بموجب)\s*(.{2,60}?)(?=[؟?،,]|$)',
    re.UNICODE,
)

def _extract_article_query(query: str):
    """يستخرج (article_number, law_hint) من استعلام 'المادة X من قانون Y'."""
    m = _EXACT_ART_RE.search(query or "")
    if not m:
        return None, None
    art_num = m.group(1)
    mh = _LAW_HINT_RE.search(query)
    law_hint = " ".join(mh.group(1).strip().split()[:3]) if mh else None
    return art_num, law_hint

async def _exact_article_search(
    conn,
    article_num: str,
    domain: str | None = None,
    law_hint: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    بحث دقيق بعمود article_number = $1 (score=0.99).
    يُستخدم لاستعلامات 'ما نص المادة X من قانون Y'.
    """
    try:
        rows = await conn.fetch("""
            SELECT id, law_id, source, law_name, law_number, law_year,
                   article_number, content, domain
            FROM chunks
            WHERE article_number = $1
              AND (is_active IS NULL OR is_active = TRUE)
              AND ($2::text IS NULL OR domain = $2)
              AND ($3::text IS NULL OR law_name ILIKE '%' || $3 || '%')
            ORDER BY
              CASE WHEN $2 IS NOT NULL AND domain = $2 THEN 0 ELSE 1 END,
              LENGTH(content) DESC
            LIMIT $4
        """, article_num, domain or None, law_hint or None, top_k)
        results = []
        for r in rows:
            d = dict(r)
            d["score"]          = 0.99
            d["keyword_match"]  = True
            d["match_count"]    = 1
            d["exact_article"]  = True
            results.append(d)
        log.info(
            "_exact_article_search: art=%s domain=%s law='%s' → %d نتيجة",
            article_num, domain or "-", law_hint or "-", len(results),
        )
        return results
    except Exception as _ea_err:
        log.warning("_exact_article_search خطأ: %s", _ea_err)
        return []

# ══════════════════════════════════════════════════════════
# دمج + Multi-Query Search
# ══════════════════════════════════════════════════════════
def merge(vec: list, kw: list, n: int = 15) -> list:
    """
    دمج نتائج البحث المتجهي والكلمي.

    ملاحظة مهمة: nomic-embed-text يُعطي نتائج عشوائية للنصوص القانونية العربية
    (أعلى النتائج: قطر للغاز، مؤسسة قطر العلمية، قوانين البلدية — غير ذات صلة)
    لذا نُهمل البحث المتجهي تقريباً ونعتمد الكلمي بالكامل.
    """
    mk = max((float(r["score"]) for r in kw), default=1.0) or 1.0
    mv = max((float(r["score"]) for r in vec), default=1.0) or 1.0
    m: dict = {}
    # أضف نتائج الكلمي أولاً (هي الأساس)
    for r in kw:
        k = (r["law_name"], r["article_number"])
        nk = float(r["score"]) / mk
        m[k] = {**r, "_vec": 0.0, "_kw": nk, "score": nk}
    # أضف نتائج المتجهي فقط إذا كانت موجودة في الكلمي أيضاً (tiny boost)
    for r in vec:
        k = (r["law_name"], r["article_number"])
        nv = float(r["score"]) / mv
        if k in m:
            # مكافأة صغيرة جداً للنتائج المشتركة (لا تُغيّر الترتيب بشكل كبير)
            m[k]["score"] = min(1.0, m[k]["_kw"] + nv * 0.03)
            m[k]["_vec"] = nv
        # إذا لم تكن في الكلمي: نتجاهل نتيجة المتجهي (جودتها ضعيفة للعربية)
    return sorted(m.values(), key=lambda x: x["score"], reverse=True)[:n]

async def trgm_search(conn, keywords: list[str], top_k: int = 10) -> list[dict]:
    """
    بحث pg_trgm بالتشابه الحرفي — يعالج الأشكال الصرفية والأخطاء الإملائية.
    يُستخدم كطبقة دعم للبحث الكلمي إذا جاءت نتائجه أقل من المطلوب.
    """
    if not keywords:
        return []
    try:
        # ابحث عن كل كلمة منفصلة بتشابه ≥ 15%
        results: dict = {}
        for kw in keywords[:6]:
            n_kw = normalize_ar(kw)
            if len(n_kw) < 3:
                continue
            rows = await conn.fetch("""
                SELECT id, law_id, source, law_name, law_number, law_year, article_number, content,
                       similarity(content, $1) AS score
                FROM chunks
                WHERE content % $1
                  AND (is_active IS NULL OR is_active = TRUE)
                ORDER BY score DESC
                LIMIT $2
            """, n_kw, top_k * 2)
            for r in rows:
                if not _is_quality_chunk(r["content"]):
                    continue
                k = (r["law_name"], r["article_number"])
                sc = float(r["score"]) * 0.82   # طبق معامل تقليل (أقل ثقة من ILIKE)
                if k not in results or sc > results[k]["score"]:
                    results[k] = {**dict(r), "score": sc, "keyword_match": True, "match_count": 1}
        return sorted(results.values(), key=lambda x: x["score"], reverse=True)[:top_k]
    except Exception as e:
        log.debug("trgm_search غير متاح (pg_trgm مفقود؟): %s", e)
        return []

async def _enrich_with_fts(conn, query_text: str, existing: list[dict], top_k: int,
                           domain: str | None = None) -> list[dict]:
    """
    إثراء نتائج البحث الحالية بـ Full-Text Search عبر SearchService.

    - إذا لم يكن app_state.SS_AVAILABLE أو app_state.get_search_service() is None → يُعيد existing كما هو.
    - يُضيف فقط النتائج الجديدة من FTS التي لم تظهر في existing.
    - يُطبّق RRF بين existing وFTS ثم يُعيد top_k نتيجة.
    """
    if not app_state.SS_AVAILABLE or not app_state.get_search_service:
        return existing
    _ss = app_state.get_search_service()
    if not _ss:
        return existing
    try:
        fts_results = await _ss.fulltext_search(conn, query_text, top_k * 2, domain=domain)
        if not fts_results:
            return existing
        # ── تطبيق article boost على نتائج FTS ──
        try:
            from search_service import _apply_boosts, _extract_article_number
            _article_num = _extract_article_number(query_text)
            if domain or _article_num:
                fts_results = _apply_boosts(fts_results, domain, _article_num)
        except ImportError:
            pass
        # أضف رتبة وهمية لـ existing لتطبيق RRF
        existing_ranked = [dict(r, search_type="kw") for r in existing]
        merged = _ss.rrf_fusion(existing_ranked, fts_results, top_n=top_k)
        log.debug("_enrich_with_fts: existing=%d, fts=%d, merged=%d", len(existing), len(fts_results), len(merged))
        return merged
    except Exception as _fts_err:
        log.debug("_enrich_with_fts خطأ: %s", _fts_err)
        return existing



# ══════════════════════════════════════════════════════════
# Domain-aware boosting — rerank chunks by legal domain match
# ══════════════════════════════════════════════════════════

_DOMAIN_LAW_KEYWORDS: dict[str, tuple[str, ...]] = {
    "criminal":       ("قانون العقوبات", "الإجراءات الجنائية", "الإجراءات الجزائية",
                       "مكافحة المخدرات", "جرائم إلكترونية", "الجرائم الإلكترونية"),
    "procedural":     ("الإجراءات الجنائية", "الإجراءات الجزائية", "قانون المرافعات"),
    "labor":          ("قانون العمل",),
    "family":         ("قانون الأسرة", "الأحوال الشخصية"),
    "civil":          ("القانون المدني",),
    "commercial":     ("قانون التجارة", "قانون الشركات", "الإفلاس"),
    "property":       ("الملكية", "التسجيل العقاري", "الإيجار"),
    "administrative": ("إداري", "إدارية", "الخدمة المدنية"),
}


def _domain_boost(chunks: list[dict], domain: str | None) -> list[dict]:
    if not domain or not chunks:
        return chunks
    accept_kws = _DOMAIN_LAW_KEYWORDS.get(domain, ())
    if not accept_kws:
        return chunks
    # every other domain's keywords = reject set
    reject_kws: list[str] = []
    for d, kws in _DOMAIN_LAW_KEYWORDS.items():
        if d != domain:
            reject_kws.extend(kws)
    for ch in chunks:
        law = (ch.get("law_name", "") or "")
        ch_domain = (ch.get("domain", "") or "").lower()
        is_matching = (
            ch_domain == domain
            or any(kw in law for kw in accept_kws)
        )
        is_wrong_domain = (
            not is_matching
            and any(kw in law for kw in reject_kws)
        )
        try:
            score = float(ch.get("score", 0) or 0)
        except Exception:
            score = 0.0
        if is_matching:
            ch["score"] = min(1.0, score + 0.25)
        elif is_wrong_domain:
            ch["score"] = max(0.0, score - 0.35)
    chunks.sort(key=lambda x: float(x.get("score", 0) or 0), reverse=True)
    return chunks


async def search(queries: list[str], key_terms: list[str], top_k: int = 15,
                 domain: str | None = None) -> list[dict]:
    if not app_state.pool:
        return []  # لا توجد قاعدة بيانات — يعمل بـ Gemini مباشرة
    async with app_state.pool.acquire() as conn:
        # ── استخراج + توسيع الكلمات المفتاحية بالمرادفات ──
        combined_kw = extract_kw(queries[0])
        # أضف كلمات من الاستعلامات الأخرى (rule_based_cot يولّد 3-5)
        for extra_q in queries[1:5]:
            for kw in extract_kw(extra_q):
                if kw not in combined_kw:
                    combined_kw.append(kw)
        # أضف key_terms (مجالات القانون المكتشفة)
        for t in key_terms[:3]:
            if len(t) >= 2 and t not in combined_kw:
                combined_kw.append(t)
        # وسّع بالمرادفات القانونية
        combined_kw = expand_keywords_with_synonyms(combined_kw)[:16]  # متسق مع الدالة

        # ── استخراج العبارات (يشمل متغيرات ال والعبارات المركبة الثابتة) ──
        phrases = extract_phrases(queries[0])
        # أضف العبارات المركبة الثابتة من الاستعلام الأصلي
        for fp in _detect_fixed_phrases(queries[0])[:3]:
            if fp not in phrases:
                phrases.append(fp)
        # ── حقن "المادة X" كعبارة ذات أولوية إذا وُجدت في الاستعلام ──
        _art_m = _EXACT_ART_RE.search(queries[0])
        if _art_m:
            _art_phrase = f"المادة {_art_m.group(1)}"
            if _art_phrase not in phrases:
                phrases.insert(0, _art_phrase)
        # أضف المصطلحات القانونية الدقيقة من استعلامات QE القصيرة (أولوية عالية)
        # مصطلحات عالية الخصوصية: كلمة واحدة تُعرّف قانوناً محدداً بدقة
        _specific_single = {
            'ابتزاز',  # قانون الجرائم الإلكترونية — المادة 9
            # 'مكافاة'/'مكافأة' حُذفت: ILIKE '%مكافأة%' عام جداً ← يطابق جمارك/شركات
            # البديل: 'مكافأة نهاية الخدمة' تُعالَج بـ _detect_fixed_phrases (أعلى دقة)
            'حضانه', 'حضانة',   # قانون الأسرة
            'نفقه', 'نفقة',     # قانون الأسرة
            'تركه', 'تركة',     # قانون المواريث
            # 'اهمال' حُذف: ILIKE '%إهمال%' يطابق قوانين كثيرة غير ذات صلة
            # البديل: حقن 'بخطئه' المباشر أدناه (فريد لقانون العقوبات م.311)
        }
        # مصطلحات عبارة (2-4 كلمات) محددة تحتوي على مصطلح قانوني
        _legal_phrase_set = {
            'ابتزاز', 'مكافاة', 'مكافأة', 'حضانه', 'نفقه', 'تركه',
            'تقاعد', 'ميراث', 'شيك', 'سرقه', 'اقامه', 'اعتبار',
        }
        _added_legal = set()
        for extra_q in queries[1:]:
            _words = extra_q.split()
            # 1) كلمات منفردة عالية الخصوصية فقط
            for _w in _words:
                _wn = normalize_ar(_w)
                if _wn in _specific_single and len(_w) >= 5 \
                        and _w not in phrases and _w not in _added_legal:
                    phrases.insert(0, _w)
                    _added_legal.add(_w)
            # 2) عبارات 2-4 كلمات تحتوي على مصطلح قانوني
            if 2 <= len(_words) <= 4 and extra_q not in phrases:
                if any(normalize_ar(w) in _legal_phrase_set or
                       any(normalize_ar(w).endswith(k) or normalize_ar(w).startswith(k)
                           for k in _legal_phrase_set)
                       for w in _words):
                    phrases.insert(len(_added_legal), extra_q)

        # ── حقن خاص: قتل خطأ / إهمال جنائي ← المادة 311 قانون العقوبات ──
        # 'بخطئه' كلمة فريدة جداً لا تظهر إلا في مادة القتل الخطأ (م.311)
        # "كل من تسبب بخطئه في موت شخص بأن كان ذلك ناشئاً عن إهماله أو رعونته"
        # تُفعَّل فقط عند اجتماع إشارتَي الإهمال + الوفاة → لا تتداخل مع استعلامات أخرى
        _qs_joined_norm = normalize_ar(' '.join(queries[:5]))
        _has_negligence = 'اهمال' in _qs_joined_norm or 'اهمل' in _qs_joined_norm
        _has_death      = any(w in _qs_joined_norm for w in ('وفاة', 'موت', 'مات', 'قتل'))
        if _has_negligence and _has_death and 'بخطئه' not in phrases:
            phrases.insert(0, 'بخطئه')

        # ── حقن خاص: شيك بدون رصيد ← المادة 357 قانون العقوبات ──
        # المادة 357 تستخدم "شيكاً لا يقابله رصيد" وليس "شيك بدون رصيد"
        # 'لا يقابله رصيد' عبارة فريدة تُعرّف هذه المادة بدقة عالية
        if 'شيك' in _qs_joined_norm and ('رصيد' in _qs_joined_norm or 'مرتجع' in _qs_joined_norm):
            if 'لا يقابله رصيد' not in phrases:
                phrases.insert(0, 'لا يقابله رصيد')

        # ── حقن خاص: مكافأة نهاية الخدمة ← المادة 15 قانون المرافعات المدنية (13/1990) ──
        # "يؤدي مكافأة نهاية خدمة" عبارة شبه فريدة (نتيجتان فقط في DB)
        # تُضمن وصول المادة 15 إلى top-15 حتى لو تنافست مع قوانين حديثة أكثر
        # تُفعَّل فقط عند وجود إشارتَي: مكافاه (مكافأة) + نهايه خدمه معاً
        _has_mkafaa = 'مكافاه' in _qs_joined_norm or 'مكافاة' in _qs_joined_norm
        _has_khidma = ('نهايه' in _qs_joined_norm or 'نهاية' in _qs_joined_norm) \
                      and ('خدمه' in _qs_joined_norm or 'خدمة' in _qs_joined_norm or 'خدم' in _qs_joined_norm)
        if _has_mkafaa and _has_khidma:
            if 'يؤدي مكافأة نهاية خدمة' not in phrases:
                phrases.insert(0, 'يؤدي مكافأة نهاية خدمة')

        # ── بحث متوازٍ: keyword + vector في نفس الوقت ──
        async def _do_kw_search():
            return await keyword_search(conn, combined_kw, top_k, phrases=phrases)

        async def _do_vec_search():
            all_vec: dict = {}
            for q_v in queries[:2]:
                try:
                    emb = await embed(q_v)
                    for r in await vector_search(conn, emb, 20):
                        k = (r["law_name"], r["article_number"])
                        if k not in all_vec or float(r["score"]) > float(all_vec[k]["score"]):
                            all_vec[k] = r
                except Exception as e:
                    log.warning("vector search '%s': %s", q_v[:30], e)
            return all_vec

        kw_res, all_vec = await asyncio.gather(_do_kw_search(), _do_vec_search())
        log.info("parallel search: kw=%d, vec=%d, kws=%s", len(kw_res), len(all_vec), combined_kw[:3])

        # ── إذا كانت النتائج أقل من المطلوب → ادعم بـ trgm ──
        if len(kw_res) < top_k // 2:
            trgm_res = await trgm_search(conn, combined_kw[:4], top_k // 2)
            if trgm_res:
                log.info("trgm_search أضاف %d نتيجة إضافية", len(trgm_res))
                # أضف نتائج trgm التي لم تظهر في kw_res
                kw_keys_set = {(r["law_name"], r["article_number"]) for r in kw_res}
                for r in trgm_res:
                    if (r["law_name"], r["article_number"]) not in kw_keys_set:
                        kw_res.append(r)

        # ── إذا وجد البحث الكلمي نتائج كافية → أعطها الأولوية ──
        if len(kw_res) >= 3:
            result = merge(list(all_vec.values()), kw_res, top_k)
            # ── إزالة نسخ القوانين القديمة المتجاوَزة ──
            result = _deduplicate_law_versions(result)
            # أولوية 1: نتائج تطابق العبارة (phrase_match)
            phrase_keys  = {(r["law_name"], r["article_number"]) for r in kw_res if r.get("phrase_match")}
            # أولوية 2: أفضل 5 نتائج كلمية
            kw_keys      = {(r["law_name"], r["article_number"]) for r in kw_res[:5]}
            phrase_first = [r for r in result if (r["law_name"], r["article_number"]) in phrase_keys]
            kw_second    = [r for r in result if (r["law_name"], r["article_number"]) in kw_keys
                                                  and (r["law_name"], r["article_number"]) not in phrase_keys]
            rest         = [r for r in result if (r["law_name"], r["article_number"]) not in kw_keys
                                                  and (r["law_name"], r["article_number"]) not in phrase_keys]
            ordered = (phrase_first + kw_second + rest)[:top_k]
            # ── إثراء اختياري بـ FTS (Search Service) ──
            ordered = await _enrich_with_fts(conn, queries[0], ordered, top_k, domain=domain)
            # ── Domain-aware boosting ──
            ordered = _domain_boost(ordered, domain)
            return ordered

        merged = merge(list(all_vec.values()), kw_res, top_k)
        merged = _deduplicate_law_versions(merged)
        # ── إثراء اختياري بـ FTS (Search Service) ──
        merged = await _enrich_with_fts(conn, queries[0], merged, top_k, domain=domain)
        # ── Domain-aware boosting ──
        merged = _domain_boost(merged, domain)
        return merged

# ══════════════════════════════════════════════════════════
# Re-ranking
# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
# PRECISION 6: RAG Dedup — إزالة القطع المتكررة المعنى
# ══════════════════════════════════════════════════════════
def _deduplicate_chunks(chunks: list[dict], overlap_threshold: float = 0.82) -> list[dict]:
    """
    يُزيل القطع التي تتشارك أكثر من overlap_threshold من كلماتها مع قطعة سابقة أعلى.
    يحافظ على القطعة ذات الـ score الأعلى عند التكرار.
    """
    if len(chunks) <= 2:
        return chunks

    kept: list[dict] = []
    for chunk in chunks:
        content_words = set(
            re.findall(r'\w{3,}', chunk.get("content", ""))
        )
        if not content_words:
            kept.append(chunk)
            continue

        is_dup = False
        for prev in kept:
            prev_words = set(re.findall(r'\w{3,}', prev.get("content", "")))
            if not prev_words:
                continue
            overlap = len(content_words & prev_words) / max(len(content_words), 1)
            if overlap >= overlap_threshold:
                # إذا كانت الجديدة أعلى score → استبدل القديمة
                if float(chunk.get("score", 0)) > float(prev.get("score", 0)):
                    kept.remove(prev)
                    kept.append(chunk)
                is_dup = True
                break

        if not is_dup:
            kept.append(chunk)

    removed = len(chunks) - len(kept)
    if removed > 0:
        log.info("dedup_chunks: أُزيلت %d قطع مكررة (threshold=%.0f%%)", removed, overlap_threshold * 100)
    return kept


async def rerank(q: str, chunks: list[dict]) -> list[dict]:
    if len(chunks) <= 3: return chunks
    try:
        snippets = "\n\n".join(
            f"[{i}] {c['law_name']} م.{c['article_number']}:\n{c['content'][:200]}"
            for i, c in enumerate(chunks[:10]))
        msgs_r = [{"role":"user","content":f"السؤال: {q}\n\n{snippets}"}]
        if ANTHROPIC_KEY:
            raw = await call_claude(RERANK_SYSTEM, msgs_r, MODEL_CLAUDE_FAST, 100)
        elif GEMINI_KEY:
            parts = []
            async for t in stream_gemini(RERANK_SYSTEM, msgs_r, max_tokens=100):
                parts.append(t)
            raw = "".join(parts)
        else:
            raw = await call_ollama(RERANK_SYSTEM, msgs_r, max_tokens=100)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            idx = json.loads(m.group()).get("ranked", [])
            if len(idx) >= 3:
                ranked = [chunks[i] for i in idx if i < len(chunks)]
                rest   = [chunks[i] for i in range(len(chunks)) if i not in set(idx)]
                return ranked + rest
    except Exception as e:
        log.warning("rerank: %s", e)
    return chunks

# ══════════════════════════════════════════════════════════
# بناء السياق
# ══════════════════════════════════════════════════════════
_CHAPTER_RE = re.compile(
    r'(الباب\s+(?:الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\w+)'
    r'|الفصل\s+(?:الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر|\w+)'
    r'|القسم\s+\w+)',
    re.UNICODE
)

def _extract_chapter_section(content: str) -> str:
    """يستخرج رقم الباب أو الفصل من أول 300 حرف من النص — يساعد النموذج على فهم السياق التشريعي"""
    m = _CHAPTER_RE.search(content[:300])
    return m.group(0).strip() if m else ""


_RE_GARBAGE = re.compile(
    r"(ع[\d@\-]{2,})|(سس\s*[=\-])|(للظب[ةا])|(عدأعشو)|(دإ\s+عط\s+شس)"
    r"|([\x00-\x08\x0B\x0C\x0E-\x1F])"
)
_RE_ARABIC_CHARS = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')

# ══════════════════════════════════════════════════════════
# فهرس الربط بين المواد القانونية وأحكام التمييز
# يُحمّل مرة واحدة عند بدء التطبيق
# ══════════════════════════════════════════════════════════
import os as _os, json as _json_mod
_INDEX_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "scripts", "article_ruling_compact.json")
_ARTICLE_RULING_INDEX: dict[str, list[int]] = {}
try:
    if _os.path.exists(_INDEX_PATH):
        with open(_INDEX_PATH, "r", encoding="utf-8") as _f:
            _ARTICLE_RULING_INDEX = _json_mod.load(_f)
        log.info("article_ruling_index loaded: %d keys", len(_ARTICLE_RULING_INDEX))
except Exception as _e:
    log.warning("article_ruling_index load failed: %s", _e)

# ══════════════════════════════════════════════════════════
# تصنيف نوع الـ chunk وبناء سياق مهيكل
# ══════════════════════════════════════════════════════════

def classify_chunk_type(chunk: dict) -> str:
    """يصنّف نوع الـ chunk: نص_قانوني / مبدأ_تمييز / حكم_تمييز / نموذج"""
    art = chunk.get("article_number", "") or ""
    name = chunk.get("law_name", "") or ""
    content = chunk.get("content", "") or ""

    if "مبدأ-تمييز" in art or "sjc-مبدأ" in art:
        return "مبدأ_تمييز"
    if "حكم-تمييز" in art:
        return "حكم_تمييز"
    if "نموذج-" in art or "نماذج" in name:
        return "نموذج"
    if "مبادئ قضائية" in name or "مبدأ قضائي" in content[:50]:
        return "مبدأ_تمييز"
    if "أحكام محكمة التمييز" in name:
        return "حكم_تمييز"
    return "نص_قانوني"


def _lookup_linked_ruling_ids(law_chunks: list[dict]) -> list[int]:
    """يبحث في فهرس الربط عن chunk IDs لأحكام تمييز مرتبطة بالمواد القانونية"""
    if not _ARTICLE_RULING_INDEX:
        return []
    linked_ids = []
    for ch in law_chunks:
        content = ch.get("content", "") or ""
        # Extract article numbers from the law chunk
        art_nums = re.findall(r'(?:الماد[ةه]|المواد)\s*\(?\s*(\d+)\s*\)?', content)
        law_name = ch.get("law_name", "") or ""
        for art in art_nums[:3]:
            # Try multiple key patterns
            for key_prefix in [f"م{art}_", f"م{art}_قانون"]:
                for idx_key, ids in _ARTICLE_RULING_INDEX.items():
                    if idx_key.startswith(key_prefix):
                        linked_ids.extend(ids[:2])
                        break
    return list(set(linked_ids))[:5]


_LEGAL_KEYWORD_MAP = {
    "فصل": ["فصل", "إنهاء", "عمل", "تعسفي", "العمل"],
    "سرقة": ["سرقة", "اختلاس", "سرق", "العقوبات"],
    "ضرب": ["ضرب", "إيذاء", "اعتداء", "جسدي", "العقوبات", "261", "262", "264"],
    "طلاق": ["طلاق", "خلع", "حضانة", "نفقة", "أسرة", "الأسرة"],
    "إيجار": ["إيجار", "مستأجر", "مؤجر", "إخلاء", "الإيجار"],
    "شركة": ["شركة", "شريك", "مساهم", "أرباح", "الشركات"],
    "تشهير": ["تشهير", "سب", "قذف", "سمعة", "إلكتروني", "الجرائم"],
    "شيك": ["شيك", "رصيد", "بنك", "تجارة"],
    "قتل": ["قتل", "وفاة", "خطأ", "305", "مسؤولية"],
    "ميراث": ["ميراث", "وصية", "تركة", "ورثة"],
    "عقار": ["عقار", "ملكية", "أرض", "بناء", "عقاري", "إزالة"],
    "تحكيم": ["تحكيم", "تنفيذ", "أجنبي"],
    "مخدرات": ["مخدرات", "حيازة", "تعاطي"],
    "تزوير": ["تزوير", "مزور", "وثائق", "238"],
    "احتيال": ["احتيال", "نصب", "غش"],
    "مرور": ["مرور", "حادث", "سيارة"],
    "بيانات": ["بيانات", "خصوصية", "اختراق"],
    "خيانة": ["خيانة", "أمانة", "354"],
    "غسيل": ["غسيل", "أموال", "تمويل"],
}


_TOPIC_TO_LAW_KEYS = {
    "فصل": ["العمل", "61", "63", "49", "54"],
    "تعسفي": ["العمل", "61", "63"],
    "راتب": ["العمل"],
    "إنذار": ["العمل", "49"],
    "نهاية خدمة": ["العمل", "54"],
    "سرقة": ["العقوبات", "310", "315"],
    "ضرب": ["العقوبات", "261", "262", "264", "308"],
    "إيذاء": ["العقوبات", "261", "262"],
    "اعتداء": ["العقوبات", "261", "308"],
    "دفاع شرعي": ["العقوبات", "43", "49"],
    "قتل": ["العقوبات", "300", "301", "305"],
    "خطأ طبي": ["العقوبات", "305"],
    "تشهير": ["العقوبات", "الجرائم", "الإلكترونية"],
    "ابتزاز": ["العقوبات", "الجرائم", "الإلكترونية", "9"],
    "شيك": ["العقوبات", "التجارة"],
    "طلاق": ["الأسرة", "102", "109", "120"],
    "خلع": ["الأسرة", "109"],
    "حضانة": ["الأسرة", "174", "178"],
    "نفقة": ["الأسرة"],
    "إيجار": ["الإيجار", "المدني"],
    "إخلاء": ["الإيجار"],
    "شركة": ["الشركات"],
    "شريك": ["الشركات"],
    "مساهم": ["الشركات", "240", "235"],
    "تزوير": ["العقوبات", "238"],
    "خيانة أمانة": ["العقوبات", "354"],
    "اختلاس": ["العقوبات"],
    "غسيل أموال": ["العقوبات"],
    "مخدرات": ["العقوبات"],
    "حادث": ["المرور", "المدني"],
    "بيانات": ["الإلكترونية", "البيانات"],
    "عقار": ["المدني", "العقاري"],
    "ملكية فكرية": ["الملكية"],
    "تحكيم": ["التحكيم", "المرافعات"],
    "استئناف": ["المرافعات", "الإجراءات"],
    "تمييز": ["المرافعات", "الإجراءات"],
}


def inject_linked_pairs(query: str) -> str:
    """
    يبحث في فهرس الربط عن أزواج (مادة ← حكم تمييز) مرتبطة بموضوع السؤال
    """
    if not _ARTICLE_RULING_INDEX:
        return ""

    q_lower = query.lower()

    # 1. خريطة الموضوع → كلمات بحث في الفهرس
    search_terms = []
    for topic, terms in _TOPIC_TO_LAW_KEYS.items():
        if topic in q_lower:
            search_terms.extend(terms)
    # أيضاً أضف من _LEGAL_KEYWORD_MAP
    for topic, kws in _LEGAL_KEYWORD_MAP.items():
        for kw in kws:
            if kw in q_lower:
                search_terms.extend(kws)
                break
    search_terms = list(set(search_terms)) if search_terms else q_lower.split()[:5]

    # 2. طابق مع مفاتيح الفهرس — بتسجيل نقاط
    scored_keys = []
    for idx_key in _ARTICLE_RULING_INDEX:
        score = 0
        for term in search_terms:
            if term in idx_key:
                score += 2 if len(term) > 3 else 1
        if score > 0:
            scored_keys.append((idx_key, score))

    scored_keys.sort(key=lambda x: -x[1])
    matched = scored_keys[:5]

    if not matched:
        return ""

    # 3. ابنِ نص الحقن مع معلومات مفصّلة
    injection = "\n═══ سند قانوني وقضائي — إلزامي الاستشهاد به في المذكرة ═══\n\n"

    for i, (key, score) in enumerate(matched, 1):
        ruling_ids = _ARTICLE_RULING_INDEX[key]
        # حلّل المفتاح لاستخراج معلومات المادة
        parts = key.replace("م", "المادة ").split("_")
        article_ref = " من ".join(p for p in parts if p.strip())

        injection += f"【{i}】 📜 {article_ref}\n"
        injection += f"     ⚖️ فسّرتها {len(ruling_ids)} أحكام تمييز\n"
        injection += f"     → استخدم: \"وفقاً لـ{article_ref}... وقد قضت محكمة التمييز بأن...\"\n\n"

    injection += (
        "⚠️ تعليمات إلزامية:\n"
        "- في كل دفع: اذكر رقم المادة + اسم القانون + رقمه + سنته\n"
        "- بعد كل مادة: اذكر أن محكمة التمييز أكدت هذا المبدأ\n"
        "- لا تترك أي دفع بدون سند قانوني\n"
    )
    return injection


# ═══════════════════════════════════════════════════════════════
# حقن المبادئ القضائية المستخلصة (بروبمت 30)
# ═══════════════════════════════════════════════════════════════
_PRINCIPLES_INDEX: dict = {}
try:
    import os as _os
    for _pp in [
        _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "scripts", "principles_index.json"),
        "/app/scripts/principles_index.json",
    ]:
        if _os.path.exists(_pp):
            with open(_pp, "r", encoding="utf-8") as _pf:
                _PRINCIPLES_INDEX = json.load(_pf)
            break
except Exception:
    pass

_PRINCIPLE_TOPIC_KW = {
    "إثبات": ["إثبات", "دليل", "بيّنة", "شهادة", "شاهد", "تقرير"],
    "إجراءات": ["بطلان", "تفتيش", "قبض", "إجراء", "إذن", "تفتيش"],
    "عقوبات": ["عقوبة", "جريمة", "قصد", "سرقة", "ضرب", "قتل", "تزوير", "رشوة"],
    "عقود": ["عقد", "فسخ", "تعويض", "شرط جزائي", "التزام"],
    "عمل": ["عامل", "فصل", "أجر", "إنهاء", "عمل", "كفيل", "طفشني"],
    "أسرة": ["طلاق", "حضانة", "نفقة", "زواج", "خلع", "ميراث"],
    "تجارة": ["شيك", "شركة", "تجاري", "إفلاس", "شريك"],
    "مسؤولية": ["مسؤولية", "تعويض", "ضرر", "خطأ", "حادث"],
    "طعن": ["طعن", "تمييز", "نقض", "استئناف", "تسبيب", "قصور"],
    "ملكية": ["ملكية", "عقار", "تسجيل", "حيازة"],
}


def inject_principles(query: str) -> str:
    """يحقن مبادئ قضائية مركّزة مرتبطة بموضوع السؤال."""
    if not _PRINCIPLES_INDEX:
        return ""

    q_lower = query.lower()
    matched = []

    for topic, keywords in _PRINCIPLE_TOPIC_KW.items():
        if any(kw in q_lower for kw in keywords):
            for p in _PRINCIPLES_INDEX.get(topic, [])[:3]:
                matched.append(p)

    if not matched:
        return ""

    # أقصى 5 مبادئ
    matched = matched[:5]

    text = "\n═══ مبادئ محكمة التمييز القطرية (استشهد بها في المذكرة) ═══\n\n"
    for i, p in enumerate(matched, 1):
        ref = p.get("ref", "")
        ref_str = f" ({ref})" if ref else ""
        text += f"[مبدأ {i}]{ref_str}:\n  «{p['text'][:350]}»\n\n"

    text += "⚠️ استشهد بهذه المبادئ: \"وقد استقرت محكمة التمييز على أن...\" ثم نص المبدأ\n"
    return text


# ═══════════════════════════════════════════════════════════════
# حقن نسب نجاح الدفوع + السوابق القضائية (بروبمت 36)
# ═══════════════════════════════════════════════════════════════
_OPTIMAL_DEFENSE_MAP: dict = {}
_PRECEDENT_DB: dict = {}
try:
    for _dp in [
        _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "scripts", "self_training_results", "optimal_defense_map.json"),
        "/app/scripts/self_training_results/optimal_defense_map.json",
    ]:
        if _os.path.exists(_dp):
            with open(_dp, "r", encoding="utf-8") as _df:
                _OPTIMAL_DEFENSE_MAP = json.load(_df)
            break
    for _pp2 in [
        _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "scripts", "self_training_results", "precedent_database.json"),
        "/app/scripts/self_training_results/precedent_database.json",
    ]:
        if _os.path.exists(_pp2):
            with open(_pp2, "r", encoding="utf-8") as _pf2:
                _PRECEDENT_DB = json.load(_pf2)
            break
except Exception:
    pass

_DEFENSE_TOPIC_KW = {
    "ضرب": ["ضرب","إيذاء","اعتداء","انضرب","دفاع شرعي"],
    "سرقة": ["سرقة","سرق","اختلاس"],
    "شيك": ["شيك","بدون رصيد","طاير"],
    "مخدرات": ["مخدرات","حيازة","تعاطي"],
    "تزوير": ["تزوير","مزور","زوّر"],
    "قتل": ["قتل","وفاة","خطأ طبي","حادث مرور"],
    "تفتيش": ["تفتيش","قبض","بدون إذن"],
    "فصل": ["فصل","تعسفي","طفشني","طردني"],
    "طلاق": ["طلاق","خلع"],
    "تعويض": ["تعويض","ضرر","حادث"],
    "شركة": ["شركة","شريك","مساهم"],
    "تشهير": ["تشهير","سب","قذف"],
}


def inject_defense_intelligence(query: str) -> str:
    """يحقن استراتيجية الدفاع مع نسب نجاح فعلية من أحكام التمييز."""
    if not _OPTIMAL_DEFENSE_MAP:
        return ""
    q_lower = query.lower()
    matched = None
    for topic, kws in _DEFENSE_TOPIC_KW.items():
        if any(kw in q_lower for kw in kws):
            matched = topic
            break
    if not matched or matched not in _OPTIMAL_DEFENSE_MAP:
        return ""
    defenses = _OPTIMAL_DEFENSE_MAP[matched]
    if not defenses:
        return ""
    text = f"\n═══ استراتيجية الدفاع (من تحليل أحكام التمييز الفعلية) ═══\n"
    text += f"الموضوع: {matched}\n"
    for i, d in enumerate(defenses, 1):
        name = d["defense"].replace("_", " ")
        rate = d.get("success_rate", d.get("rate", 0))
        total = d.get("total_cases", d.get("total", 0))
        icon = "🟢" if rate >= 50 else ("🟡" if rate >= 35 else "🔴")
        text += f"  {i}. {name} — {icon} {rate}% نجاح ({total} حالة)\n"
    text += "⚠️ ابدأ بالدفع الأقوى. هذه النسب من أحكام محكمة التمييز القطرية.\n\n"
    return text


def inject_precedents(query: str) -> str:
    """يحقن سوابق قضائية مصنّفة من قاعدة الـ 342 سابقة."""
    if not _PRECEDENT_DB:
        return ""
    q_lower = query.lower()
    matched_topics = []
    for topic, kws in _DEFENSE_TOPIC_KW.items():
        if any(kw in q_lower for kw in kws):
            matched_topics.append(topic)
    if not matched_topics:
        return ""
    precs = []
    for t in matched_topics:
        precs.extend(_PRECEDENT_DB.get(t, [])[:3])
    if not precs:
        return ""
    seen = set(); unique = []
    for p in precs:
        k = p.get("principle","")[:60]
        if k not in seen: seen.add(k); unique.append(p)
    text = "\n═══ سوابق قضائية — محكمة التمييز القطرية ═══\n\n"
    for i, p in enumerate(unique[:5], 1):
        ref = p.get("ref", p.get("ruling_ref", ""))
        prin = p.get("principle", "")[:350]
        text += f"[سابقة {i}]"
        if ref: text += f" ({ref})"
        text += f":\n  {prin}\n\n"
    text += "⚠️ استشهد: 'وقد استقرت محكمة التمييز في الطعن رقم ___ على أن...'\n\n"
    return text


# ═══════════════════════════════════════════════════════════════
# حقن قضايا واقعية + ثغرات قانونية (بروبمت 42)
# ═══════════════════════════════════════════════════════════════
_CASE_PATTERNS = []
_LEGAL_LOOPHOLES = []
try:
    for _cwp in [
        _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "scripts", "deep_web_learning", "comprehensive_knowledge.json"),
        "/app/scripts/deep_web_learning/comprehensive_knowledge.json",
    ]:
        if _os.path.exists(_cwp):
            with open(_cwp, "r", encoding="utf-8") as _cwf:
                _cwd = json.load(_cwf)
                _CASE_PATTERNS = _cwd.get("cases", [])
                _LEGAL_LOOPHOLES = _cwd.get("loopholes", [])
            break
except Exception:
    pass

_CASE_KW = {
    "فصل تعسفي": ["فصل","طفشني","طردني","إنهاء","استقالة"],
    "شيك ضمان": ["شيك","رصيد","ضمان","طاير"],
    "بطلان تفتيش": ["تفتيش","قبض","إذن","مخدرات"],
    "دفاع شرعي": ["ضرب","دفاع","اعتداء","انضرب"],
    "تقادم": ["تقادم","سقط","سنوات","مدة"],
    "حضانة": ["حضانة","عيال","أطفال","أم"],
    "عيب خفي": ["عيب","معيب","غش","إخفاء","سيارة"],
    "شرط جزائي": ["شرط جزائي","مقاول","تأخير"],
}
_LOOPHOLE_KW = {
    "غموض": ["فصل","إنهاء","إخلال","م.61","عمل"],
    "شيك": ["شيك","ضمان","رصيد"],
    "اختصاص": ["اختصاص","محكمة"],
    "جواز": ["جواز","حجز","كفيل"],
}


def inject_similar_cases(query: str) -> str:
    if not _CASE_PATTERNS: return ""
    q = query.lower()
    matched = [c for c in _CASE_PATTERNS if any(kw in q for kws in _CASE_KW.values() for kw in kws if c.get("topic","") in [t for t,ks in _CASE_KW.items() if kw in ks])]
    if not matched:
        for c in _CASE_PATTERNS:
            topic = c.get("topic","")
            if topic in _CASE_KW and any(kw in q for kw in _CASE_KW[topic]):
                matched.append(c)
    if not matched: return ""
    text = "\n═══ قضايا مشابهة من الواقع ═══\n\n"
    for i, c in enumerate(matched[:2], 1):
        text += f"[قضية {i}] {c.get('topic','')}: {c.get('pattern','')}\n  الدرس: {c.get('lesson','')}\n\n"
    return text


def inject_loopholes(query: str) -> str:
    if not _LEGAL_LOOPHOLES: return ""
    q = query.lower()
    matched = []
    for lh in _LEGAL_LOOPHOLES:
        issue = lh.get("issue","")
        for kw_group, kws in _LOOPHOLE_KW.items():
            if any(k in issue for k in kw_group.split()) and any(k in q for k in kws):
                matched.append(lh); break
    if not matched: return ""
    text = "\n═══ ثغرات قانونية للدفاع ═══\n\n"
    for lh in matched[:2]:
        text += f"  🔍 {lh.get('issue','')}\n  → {lh.get('use','')}\n\n"
    return text


# ═══════════════════════════════════════════════════════════════
# حقن أسلوب المحكمة من 472 نمط (بروبمت 44)
# ═══════════════════════════════════════════════════════════════
_RULING_PATTERNS_DEEP: dict = {}
try:
    for _rpd in [
        _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "scripts", "ruling_deep_learning", "ruling_patterns_deep.json"),
        "/app/scripts/ruling_deep_learning/ruling_patterns_deep.json",
    ]:
        if _os.path.exists(_rpd):
            with open(_rpd, "r", encoding="utf-8") as _rpf:
                _RULING_PATTERNS_DEEP = json.load(_rpf)
            break
except Exception:
    pass


def inject_court_style(query: str) -> str:
    """يحقن أسلوب محكمة التمييز — مختصر ومركّز (أقصى 1000 حرف)."""
    if not _RULING_PATTERNS_DEEP:
        return ""

    reasoning = _RULING_PATTERNS_DEEP.get("reasoning", {})
    phrases = _RULING_PATTERNS_DEEP.get("phrases", [])
    defenses = _RULING_PATTERNS_DEEP.get("defenses", {})

    items = []
    for c in reasoning.get("connectors", [])[:2]:
        items.append(c[:150])
    for lf in reasoning.get("law_to_fact", [])[:1]:
        items.append(lf[:150])
    for p in phrases[:2]:
        items.append(p[:150])
    for r in defenses.get("reject", [])[:1]:
        items.append(r[:150])

    if not items:
        return ""

    text = "\n⚠️ صِغ المذكرة بأسلوب محكمة التمييز — استخدم هذه العبارات الفعلية:\n"
    for item in items:
        text += f"• {item}\n"
    text += "\n"
    return text


# ── حقن إثراء لغوي واستدلالي (من التعلّم الذاتي) ──
_ARABIC_ENRICHMENT = {}
_REASONING_ENRICHMENT = {}
try:
    import os as _os4
    _ae_path = _os4.path.join(_os4.path.dirname(_os4.path.dirname(__file__)), "scripts", "arabic_enrichment.json")
    if _os4.path.exists(_ae_path):
        with open(_ae_path, "r", encoding="utf-8") as _f4:
            _ARABIC_ENRICHMENT = json.load(_f4)
        log.info("arabic_enrichment loaded: %d phrases", len(_ARABIC_ENRICHMENT.get("rhetorical_phrases", [])))
    _re_path = _os4.path.join(_os4.path.dirname(_os4.path.dirname(__file__)), "scripts", "reasoning_enrichment.json")
    if _os4.path.exists(_re_path):
        with open(_re_path, "r", encoding="utf-8") as _f5:
            _REASONING_ENRICHMENT = json.load(_f5)
        log.info("reasoning_enrichment loaded: %d patterns", len(_REASONING_ENRICHMENT.get("argument_patterns", [])))
except Exception as _e4:
    log.warning("enrichment load failed: %s", _e4)


def inject_writing_enrichment(query: str) -> str:
    """يحقن عبارات بلاغية وأدوات ربط وأساليب إقناع لتحسين الصياغة."""
    parts = []

    # عبارات بلاغية (أفضل 8)
    phrases = _ARABIC_ENRICHMENT.get("rhetorical_phrases", [])
    if phrases:
        sel = []
        for p in phrases[:15]:
            txt = p.get("phrase", str(p)) if isinstance(p, dict) else str(p)
            if txt and len(txt) > 10:
                sel.append(txt)
            if len(sel) >= 8:
                break
        if sel:
            parts.append("عبارات بلاغية للاستخدام في المذكرة:")
            for s in sel:
                parts.append(f"• {s}")

    # أدوات ربط (أفضل 6)
    connectors = _ARABIC_ENRICHMENT.get("connectors", [])
    if connectors:
        sel2 = []
        for c in connectors[:10]:
            txt = c.get("connector", str(c)) if isinstance(c, dict) else str(c)
            if txt and len(txt) > 5:
                sel2.append(txt)
            if len(sel2) >= 6:
                break
        if sel2:
            parts.append("أدوات ربط:")
            parts.append(" | ".join(sel2))

    # أساليب إقناع (أفضل 3)
    patterns = _REASONING_ENRICHMENT.get("persuasion_techniques", [])
    if patterns:
        sel3 = []
        for p in patterns[:5]:
            name = p.get("name", p.get("technique", str(p))) if isinstance(p, dict) else str(p)
            if name and len(name) > 5:
                sel3.append(name[:80])
            if len(sel3) >= 3:
                break
        if sel3:
            parts.append("أساليب إقناع:")
            for s in sel3:
                parts.append(f"• {s}")

    if not parts:
        return ""
    return "\n📝 إثراء لغوي:\n" + "\n".join(parts) + "\n"


def build_multi_layer_context(chunks: list[dict], max_content: int = 500) -> str:
    """
    يبني سياق مهيكل متعدد الطبقات — يفصل النصوص القانونية عن المبادئ عن الأحكام.
    إذا لم تُوجد أحكام تمييز → يبحث في فهرس الربط عن أحكام مرتبطة بالمواد المكتشفة.
    """
    laws = []
    principles = []
    rulings = []
    templates = []

    for ch in chunks:
        ch_type = classify_chunk_type(ch)
        if ch_type == "نص_قانوني":
            laws.append(ch)
        elif ch_type == "مبدأ_تمييز":
            principles.append(ch)
        elif ch_type == "حكم_تمييز":
            rulings.append(ch)
        elif ch_type == "نموذج":
            templates.append(ch)

    # إذا وُجدت مواد قانونية لكن لا أحكام/مبادئ → ابحث في فهرس الربط
    if laws and not principles and not rulings and _ARTICLE_RULING_INDEX:
        linked_ids = _lookup_linked_ruling_ids(laws)
        if linked_ids:
            # Create placeholder chunks from index (will be enriched by DB lookup later)
            for cid in linked_ids:
                principles.append({
                    "content": f"[حكم تمييز مرتبط — chunk_id={cid}]",
                    "law_name": "حكم تمييز مرتبط",
                    "article_number": f"linked-{cid}",
                    "_linked_from_index": True,
                })

    parts = []

    if laws:
        parts.append("═══ النصوص القانونية ═══")
        for i, ch in enumerate(laws[:5]):
            content = ch.get("content", "")[:max_content]
            ref = f"{ch.get('law_name','')} — المادة ({ch.get('article_number','')})"
            parts.append(f"[{i+1}] {ref}\n{content}")

    if principles:
        parts.append("\n═══ مبادئ محكمة التمييز ═══")
        for i, ch in enumerate(principles[:5]):
            content = ch.get("content", "")[:max_content]
            parts.append(f"[م{i+1}] {content}")

    if rulings:
        parts.append("\n═══ أحكام محكمة التمييز ═══")
        for i, ch in enumerate(rulings[:3]):
            content = ch.get("content", "")[:max_content]
            ref = ch.get("law_name", "")
            parts.append(f"[ح{i+1}] {ref}\n{content}")

    if templates:
        parts.append("\n═══ نماذج مرجعية ═══")
        for i, ch in enumerate(templates[:2]):
            content = ch.get("content", "")[:max_content]
            parts.append(f"[ن{i+1}] {ch.get('law_name','')}\n{content}")

    if not parts:
        return ""

    header = "⚡ النتائج مصنّفة: نصوص قانونية + مبادئ تمييز + أحكام. اربط بينها واستخدم أرقام المواد وأحكام التمييز.\n\n"
    return header + "\n\n---\n\n".join(parts)


def filter_rag_results(chunks: list[dict], min_score: float = 0.35, max_results: int = 5) -> list[dict]:
    """
    تصفية نتائج RAG قبل إرسالها للنموذج:
    - حذف نتائج بدرجة صلة منخفضة
    - حذف نصوص تالفة (OCR مشوه)
    - حذف مكررات
    - إبقاء أفضل max_results فقط
    """
    filtered = []
    seen_content = set()
    for ch in chunks:
        # تخطي درجة صلة منخفضة
        if ch.get("score", 0) < min_score:
            continue
        # تخطي نصوص تالفة
        content = ch.get("content", "")
        if _RE_GARBAGE.search(content):
            continue
        # تخطي نسبة عربية منخفضة جداً (أقل من 15%)
        ar_count = len(_RE_ARABIC_CHARS.findall(content))
        if len(content) > 50 and ar_count / len(content) < 0.15:
            continue
        # تخطي مكررات
        content_hash = hash(content[:200])
        if content_hash in seen_content:
            continue
        seen_content.add(content_hash)
        filtered.append(ch)
        if len(filtered) >= max_results:
            break
    return filtered


def build_context(chunks: list[dict], max_content: int = 400) -> str:
    """
    يبني السياق القانوني المُرسَل للنموذج.
    max_content: الحد الأقصى لأحرف كل مقطع
    يُضيف: مؤشر عمر القانون + الباب/الفصل + مؤشر الثقة
    """
    _SOURCE_LABEL = {"attachment": "[مرفق رسمي]", "almeezan": "[الميزان]", "txt": "[نص قانوني]"}
    parts = []
    for i, ch in enumerate(chunks):
        conf = "★★★" if ch["score"] > 0.85 else "★★☆" if ch["score"] > 0.70 else "★☆☆"
        content = ch['content'][:max_content]
        if len(ch['content']) > max_content:
            content += "…"
        src_label = _SOURCE_LABEL.get(ch.get("source", ""), "")

        # مؤشر صحة القانون: هل هو حديث أم قديم؟
        try:
            y = int(str(ch.get('law_year', '') or '0').strip())
        except ValueError:
            y = 0
        if y >= 2000:
            age_label = "✅ نافذ"
        elif y >= 1990:
            age_label = "⚠️ قديم"
        elif y > 0:
            age_label = "⛔ قديم جداً"
        else:
            age_label = ""

        # استخراج الباب/الفصل من النص
        chapter_info = _extract_chapter_section(ch['content'])
        chapter_str = f" | {chapter_info}" if chapter_info else ""

        # علامة المادة الأولى — الأكثر صلة — للنموذج الصغير
        primary_marker = "▶▶ [المادة الأكثر صلة — استخدم هذه أساساً]\n" if i == 0 else ""

        parts.append(
            f"{primary_marker}[{i+1}] {conf} {age_label} {src_label}\n"
            f"📖 {ch['law_name']}\n"
            f"القانون ({ch['law_number']}) لسنة ({ch['law_year']}) — المادة ({ch['article_number']}){chapter_str}\n"
            f"{content}"
        )
    return "\n\n---\n\n".join(parts)


def build_context_smart(chunks: list[dict], max_content: int = 700, top_k: int = 5) -> str:
    """
    المرحلة 5: Structured Context Injection
    يستخدم build_structured_context من intent_router إن كان متاحاً،
    وإلا يرجع لـ build_context القديم.
    """
    if _INTENT_ROUTER_AVAILABLE:
        return build_structured_context(chunks, max_content=max_content, top_k=top_k)
    return build_context(chunks[:top_k], max_content=max_content)

# ══════════════════════════════════════════════════════════
# التحقق من الاستشهادات
# ══════════════════════════════════════════════════════════
def verify_citations(answer: str, chunks: list[dict]) -> tuple[str, list[str]]:
    cited = re.findall(
        r'المادة\s*\(?\s*(\d+)\s*\)?\s*من.*?القانون.*?رقم\s*\(?\s*(\d+)\s*\)?\s*لسنة\s*\(?\s*(\d+)\s*\)?',
        answer)
    valid = {(str(c.get("article_number","")), str(c.get("law_number","")),
              str(c.get("law_year",""))) for c in chunks}
    hallucinated = [
        f"المادة ({a}) القانون ({ln}) {ly}"
        for a, ln, ly in cited
        if not any((aa==a or aa=="") and (ll==ln or ll=="") and (yy==ly or yy=="")
                   for aa, ll, yy in valid)
    ]
    if hallucinated:
        answer += "\n\n---\n⚠️ **تحقق من الاستشهادات:** بعض المراجع قد تحتاج تأكيداً من المصدر الأصلي."
    return answer, hallucinated

# ══════════════════════════════════════════════════════════
