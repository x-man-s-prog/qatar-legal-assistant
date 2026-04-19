from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import asyncpg, httpx, os, re, uuid
from collections import defaultdict

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ── نموذج الذكاء الاصطناعي المحلي (Ollama) ──
OLLAMA_URL    = "http://host.docker.internal:11434"
OLLAMA_MODEL  = "qwen2.5:1.5b"   # أسرع على CPU (10-30s بدلاً من 3+ دقائق)
OLLAMA_MODEL2 = "qwen2.5:7b"     # احتياطي للاستفسارات المعقدة

# ── تخزين المحادثات في الذاكرة ──
# { conv_id: [ {"role": "user"|"assistant", "content": "..."}, ... ] }
_convs: Dict[str, List[Dict]] = defaultdict(list)
MAX_HIST = 10  # أقصى عدد رسائل (5 تبادلات كاملة)

# ══════════════════════════════════════════════════════════════════
#  SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════════

EXPERT_SYSTEM = """أنت "مستشار" — مساعد قانوني قطري ذكي ومتخصص في القانون القطري.

عند الإجابة على أسئلة قانونية:
- استند للنصوص المُقدَّمة حصراً. لا تخترع أرقاماً أو عقوبات أو تواريخ.
- إذا غاب النص: قل "لا يتوفر نص صريح في المصادر المتاحة."
- أجب بالعربية الفصحى. ابدأ مباشرةً بالجواب.

صيغة الإجابة القانونية:
**المادة (X) — [القانون] لسنة (Y):** "[نص المادة]"
**التحليل:** [3-4 جمل تحليل مختصر بناءً على النص]"""

GENERAL_SYSTEM = """أنت "مستشار" — مساعد قانوني قطري يشرح القانون بأسلوب واضح وبسيط.

عند الإجابة على أسئلة قانونية:
- استند للنصوص المُقدَّمة فقط. لا تخترع معلومات.
- ابدأ بجملة مباشرة تُجيب السؤال مباشرة.
- اذكر العقوبة بأرقام واضحة من النص.
- ضع المرجع في النهاية.

صيغة الإجابة:
[الجواب المباشر والواضح]
📖 المادة (X) من [القانون] رقم (Y) لسنة (Z)"""

CHAT_SYSTEM = """أنت "مستشار" — مساعد قانوني قطري ذكي وودود. هذه هويتك الوحيدة.
- اسمك: مستشار. لا تذكر Qwen أو Alibaba أو أي نموذج آخر أبداً.
- إذا سألك أحد "من أنت؟": قل أنك مستشار، نظام ذكاء اصطناعي متخصص في القانون القطري.
- تتحدث بالعربية بشكل طبيعي ودافئ — أنت محترف ومنفتح.
- ردّ على التحيات بشكل طبيعي ودافئ.
- يمكنك الحديث عن أي موضوع، لكن تخصصك الأساسي القانون القطري.
- لا تُطوّل — 2-3 أسطر كافية للمحادثة العامة.
- لا تبدأ كل رد بـ "كمستشار قانوني" — كن طبيعياً."""

# ══════════════════════════════════════════════════════════════════
#  ARABIC LEGAL SEARCH ENGINE
# ══════════════════════════════════════════════════════════════════

_STOP = {
    'في','من','على','إلى','عن','هل','ما','كيف','متى','أين','لماذا','و','أو','مع',
    'هذا','هذه','ذلك','تلك','التي','الذي','قد','لا','لم','لن','كان','يكون','يكن',
    'بعد','قبل','حتى','إذا','إذ','أن','إن','بأن','الذين','بما','مما',
    'قانون','القانون','مادة','المادة','قطر','قطري','القطري','دولة','الدولة',
    'حكم','الحكم','نص','النص','يجب','يجوز','حق','الحق','شخص','الشخص',
    'عقوبة','العقوبة','جريمة','الجريمة','يعاقب','عليه','منه','بها','فيه',
}

_SYNONYMS = {
    'نصب':      ['احتيال','احتيالية','استيلاء','نصب'],
    'غش':       ['احتيال','تدليس','تغرير','غش'],
    'اختلاس':   ['اختلاس','استيلاء'],
    'رشوة':     ['رشوة','إرشاء','مرتشٍ','راشٍ'],
    'تزوير':    ['تزوير','تزييف','مزوّر'],
    'قتل':      ['القتل','قتل','قتلت','قاتل','مقتول','اغتيال'],
    'ايذاء':    ['إيذاء','ضرب','جرح','إيذاء'],
    'إيذاء':    ['إيذاء','ضرب','جرح'],
    'اغتصاب':   ['اغتصاب','إكراه','اعتداء'],
    'حضانة':    ['حضانة','رعاية','ولاية'],
    'طلاق':     ['طلاق','فرقة','خلع','فسخ'],
    'إرث':      ['الإرث','التركة','الوراثة','وراثة'],
    'ميراث':    ['الإرث','التركة','الوارث','ميراث'],
    'عمل':      ['عمال','العمل','الأجر','العامل','عمالة'],
    'اجار':     ['إيجار','المستأجر','المؤجر'],
    'إيجار':    ['إيجار','المستأجر','المؤجر'],
    'عقار':     ['عقار','الأراضي','العقارات','الأرض'],
    'سرقة':     ['سرقة','سارق','سرق','يسرق'],
    'شيك':      ['شيك','شيكات','صكوك'],
    'ضرب':      ['ضرب','إيذاء','جرح','عنف','اعتداء'],
    'شركة':     ['شركة','شركات','مؤسسة','تجارية'],
    'نفقة':     ['نفقة','مصاريف','إعالة','مؤونة'],
    'إهانة':    ['إهانة','تشهير','قذف','سب','شتم'],
    'مخدرات':   ['مخدرات','مؤثرات','تعاطي','تهريب'],
    'سلاح':     ['سلاح','أسلحة','ذخيرة'],
    'تهريب':    ['تهريب','مهربين','تهريب'],
    'إرهاب':    ['إرهاب','إرهابي','تمويل'],
    'فساد':     ['فساد','رشوة','اختلاس'],
    'انتحال':   ['انتحال','تظاهر','ادعاء كاذب'],
    'قاصر':     ['قاصر','أطفال','طفل','حدث'],
    'تشهير':    ['تشهير','قذف','إهانة','ذم'],
    'زواج':     ['زواج','نكاح','عقد زواج','زوجة','زوج'],
    'عقد':      ['عقد','اتفاق','تعاقد'],
    'دية':          ['دية','أرش','تعويض','جناية'],
    'حبس':          ['حبس','سجن','توقيف','اعتقال'],
    'غرامة':        ['غرامة','غرامات','مالية'],
    # ── قانون العمل ──
    'فصل':          ['إنهاء عقد','إنهاء الخدمة','انتهاء الخدمة','مكافأة نهاية','فصل','تسريح','استخدام'],
    'تعسفي':        ['تعسفي','بدون مبرر','إنهاء غير مشروع','مكافأة نهاية'],
    'حقوق':         ['استحقاقات','مستحقات','التعويض','الحقوق','مستحق'],
    'راتب':         ['الأجر','الراتب','المرتب','الأجور','أجر'],
    'أمومة':        ['أمومة','وضع','ولادة','حمل','رضاعة'],
    'إجازة':        ['إجازة','الإجازة','إجازة سنوية','الإجازات'],
    'موظف':         ['موظف','عامل','الموظفين','عمالة','مستخدم'],
    'عامل':         ['عامل','عمال','مستخدم','المستخدم','صاحب العمل','عقد الاستخدام'],
    'انهاء':        ['إنهاء','انتهاء','فسخ','إلغاء','إنذار'],
    # ── عقود وتجارة ──
    'تأسيس':        ['تأسيس','تسجيل شركة','إنشاء شركة','ترخيص'],
    'عقد':          ['عقد','اتفاق','اتفاقية','تعاقد'],
}

def strip_al(w: str) -> str:
    for prefix in ('وال','فال','بال','لل','كال','وب','فب'):
        if w.startswith(prefix) and len(w) > len(prefix)+2:
            return w[len(prefix):]
    if len(w) > 3 and w.startswith('ال'):
        return w[2:]
    if len(w) > 4 and w[1:3] == 'ال':
        return w[3:]
    return w

def normalize_arabic(w: str) -> str:
    """تطبيع الأحرف العربية للمطابقة الأوسع"""
    w = re.sub(r'[أإآ]', 'ا', w)
    w = re.sub(r'[ىئ]', 'ي', w)
    w = w.replace('ة', 'ه')
    w = w.replace('ؤ', 'و')
    return w

def expand_synonyms(kws: list) -> list:
    expanded = list(kws)
    for kw in kws:
        bare = strip_al(kw)
        # Try direct match
        if bare in _SYNONYMS:
            for syn in _SYNONYMS[bare]:
                if syn not in expanded: expanded.append(syn)
        # Try normalized match
        bare_norm = normalize_arabic(bare)
        for key, syns in _SYNONYMS.items():
            if normalize_arabic(key) == bare_norm:
                for syn in syns:
                    if syn not in expanded: expanded.append(syn)
    return expanded

def extract_keywords(q: str) -> list:
    words = re.findall(r'[\u0600-\u06ff]{3,}', q)
    kws = [w for w in words if w not in _STOP]
    kws = list(dict.fromkeys(kws))[:10]
    return expand_synonyms(kws)

# ══════════════════════════════════════════════════════════════════
#  SEARCH ENGINE
# ══════════════════════════════════════════════════════════════════

async def embed(text: str):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text[:2000]}
        )
        return r.json()["embedding"]

MIZAN_BASE = "https://almeezan.qa/LawPage.aspx"

def make_mizan_link(law_id, law_number: str, law_year: str) -> str:
    if law_id and str(law_id).isdigit():
        return f"{MIZAN_BASE}?id={law_id}&language=ar"
    if law_number and law_year:
        return f"https://almeezan.qa/LawPage.aspx?opt=print&law={law_number}&year={law_year}"
    return ""

async def vector_search(conn, emb, top_k=20):
    rows = await conn.fetch("""
        SELECT id, law_id, source, law_name, law_number, law_year, article_number, content,
               1 - (embedding <=> $1::vector) AS score
        FROM chunks
        ORDER BY embedding <=> $1::vector
        LIMIT $2
    """, str(emb), top_k)
    return [dict(r) for r in rows]

async def keyword_search(conn, keywords: list, top_k=20):
    if not keywords:
        return []
    # كلمات البحث (المُوسَّعة بالمرادفات) — للبحث ILIKE فقط
    expanded = list(dict.fromkeys([strip_al(kw) for kw in keywords if len(strip_al(kw)) >= 3]))
    trivial = {'هي','هو','هم','هن','انت','أنت','نحن','ما','من','في'}
    search_kws = [kw for kw in expanded if kw not in trivial]

    # الكلمات الأصلية فقط (قبل توسيع المرادفات) — للتسجيل Scoring
    # نأخذ أوائل الكلمات قبل التوسيع؛ هذه الكلمات هي الأكثر صلة بالسؤال
    core_kws = [strip_al(kw) for kw in keywords[:3] if len(strip_al(kw)) >= 3 and strip_al(kw) not in trivial]

    all_results = {}
    SCAN_LIMIT = 120  # زيادة الحد لضمان العثور على المواد الصحيحة
    for kw in search_kws[:8]:
        try:
            rows = await conn.fetch(
                "SELECT id, law_id, source, law_name, law_number, law_year, article_number, content "
                "FROM chunks WHERE content ILIKE $1 LIMIT $2",
                f"%{kw}%", SCAN_LIMIT
            )
            for r in rows:
                key = (r["law_name"], r["article_number"])
                content = r["content"]
                c200 = content[:200]
                # التسجيل: الكلمات الأصلية أهم (تزن ضعف المرادفات)
                core_matches = sum(1 for k in core_kws if k in content)
                all_matches  = sum(1 for k in search_kws if k in content)
                # مكافأة الظهور المبكر والتكرار (يرفع المواد الموضوعية على الإشارات العرضية)
                early_bonus  = 0.04 if any(k in c200 for k in core_kws) else 0.0
                repeat_bonus = 0.03 if any(content.count(k) >= 3 for k in core_kws) else 0.0
                # مكافأة هيكل مادة عقوبة (يُعاقب في أول 200 حرف = مادة تجريمية أساسية)
                crime_bonus  = 0.05 if ('يُعاقب' in c200 or 'يعاقب' in c200) else 0.0
                # أولوية: الكلمات الأصلية تحصل على وزن أعلى
                score = 0.85 + (core_matches * 0.08) + (all_matches * 0.01) + early_bonus + repeat_bonus + crime_bonus
                score = min(score, 0.99)
                if key not in all_results or all_results[key]["score"] < score:
                    all_results[key] = {
                        "id":             r["id"],
                        "law_id":         r["law_id"],
                        "source":         r["source"],
                        "law_name":       r["law_name"],
                        "law_number":     r["law_number"],
                        "law_year":       r["law_year"],
                        "article_number": r["article_number"],
                        "content":        content,
                        "score":          score,
                        "keyword_match":  True,
                    }
        except Exception:
            continue
    return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:top_k]

def merge_results(vec_res, kw_res, max_results=10):
    seen = set(); merged = []
    # خريطة لنتائج keyword مع درجاتها
    kw_map = {(r["law_name"], r["article_number"]): r for r in kw_res}
    # 1) تطابق مزدوج (أعلى ثقة) — يأخذ أفضل درجة من الاثنين + مكافأة
    for r in vec_res:
        key = (r["law_name"], r["article_number"])
        if key in kw_map and key not in seen:
            kw_score  = float(kw_map[key].get("score", 0.85))
            vec_score = float(r.get("score", 0))
            combined  = min(max(kw_score, vec_score) + 0.02, 0.99)  # مكافأة التطابق المزدوج
            r = dict(r)
            r["score"] = combined
            r["keyword_match"] = True
            merged.append(r); seen.add(key)
    # 2) keyword فقط
    for r in kw_res:
        key = (r["law_name"], r["article_number"])
        if key not in seen: merged.append(r); seen.add(key)
    # 3) vector فقط (توسيع السياق)
    for r in vec_res:
        key = (r["law_name"], r["article_number"])
        if key not in seen: merged.append(r); seen.add(key)
    return merged[:max_results]

# ──────────────────────────────────────────────────────────────────
# تصحيح أسماء القوانين المشوّهة بسبب OCR
# ──────────────────────────────────────────────────────────────────
_GARBLED_PENAL   = re.compile(r'صالحيات الوزراء|تحديد صالحيات', re.IGNORECASE)
_CRIME_MARKER    = re.compile(r'(يُعاقب|يعاقب|بالإعدام|بالسجن|بالحبس|وبالغرامة)')
_GARBLED_PROC    = re.compile(r'(قانون\s*(رقم)?\s*\(\s*\)\s*15|إجراءات.*1971.*معدل)', re.IGNORECASE)

def _normalize_chunk(c: dict) -> dict:
    """تصحيح أسماء القوانين المشوّهة التي نتجت عن أخطاء OCR في الفهرسة"""
    name = c.get("law_name") or ""
    content = c.get("content", "")
    # حالة 1: اسم "صالحيات الوزراء" مع محتوى قانون العقوبات
    if _GARBLED_PENAL.search(name) and _CRIME_MARKER.search(content[:300]):
        c = dict(c)
        c["law_name"]   = "قانون رقم (11) لسنة 2004 بإصدار قانون العقوبات"
        c["law_number"] = "11"
        c["law_year"]   = "2004"
        return c
    return c

async def hybrid_search(q: str, conv_history: list = None, top_k=12):
    """بحث هجين — البحث دائماً بالسؤال الحالي فقط (السياق للـ LLM فقط)"""
    # ملاحظة: لا نُدمج السياق في البحث لتجنب تلوّث نتائج الاستفسارات الجديدة
    search_q = q  # البحث دائماً بالسؤال الحالي فحسب

    conn = await asyncpg.connect(
        host="postgres", port=5432,
        database="ragdb", user="raguser", password="RAGsecret2024!"
    )
    try:
        emb      = await embed(search_q[:1500])
        vec_res  = await vector_search(conn, emb, top_k=25)
        keywords = extract_keywords(search_q)
        kw_res   = await keyword_search(conn, keywords, top_k=20)
    finally:
        await conn.close()

    merged = merge_results(vec_res, kw_res, max_results=top_k + 5)  # هامش إضافي للمُعيد-الترتيب
    # تصحيح أسماء القوانين المشوّهة
    return [_normalize_chunk(c) for c in merged]

# ══════════════════════════════════════════════════════════════════
#  LLM — Ollama qwen2.5:7b
# ══════════════════════════════════════════════════════════════════

async def ollama_chat(messages: list, system: str, complex_query: bool = False) -> str:
    """استدعاء نموذج Ollama مع الحفاظ على سياق المحادثة"""
    model = OLLAMA_MODEL2 if complex_query else OLLAMA_MODEL
    payload = {
        "model":    model,
        "system":   system,
        "messages": messages,
        "stream":   False,
        "options":  {
            "temperature":    0.05,   # دقة قصوى للإجابات القانونية
            "top_p":          0.9,
            "num_ctx":        4096,   # سياق 4K — كافٍ للقانون وأسرع
            "num_predict":    600,    # أقصى توكن في الرد
            "repeat_penalty": 1.15,
        }
    }
    timeout = 300 if complex_query else 120
    async with httpx.AsyncClient(timeout=timeout) as c:
        try:
            r = await c.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"]
        except httpx.TimeoutException:
            return "خطأ: استغرق النموذج وقتاً طويلاً. يُرجى إعادة المحاولة."
        except Exception as e:
            return f"خطأ في النموذج: {str(e)}"

# ══════════════════════════════════════════════════════════════════
#  API ENDPOINT
# ══════════════════════════════════════════════════════════════════

class Q(BaseModel):
    query:           str
    mode:            Optional[str] = "expert"
    conversation_id: Optional[str] = None

@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok", "version": "5.0",
        "llm": OLLAMA_MODEL, "search": "hybrid-v2",
        "features": ["multi-turn", "anti-hallucination", "legal-analysis"]
    }

# ── تصنيف الاستفسارات وإعادة الترتيب ──
_CRIME_Q  = re.compile(r'(عقوبة|جريمة|سرقة|قتل|احتيال|نصب|رشوة|تزوير|اختلاس|ضرب|اغتصاب|إهانة|قذف|إرهاب|مخدرات|تهريب|غش|خيانة امانة|انتحال)', re.IGNORECASE)
_LABOR_Q  = re.compile(r'(عامل|عمال|عمل|راتب|أجر|فصل تعسفي|إنهاء خدمة|إجازة|تأمين|ضمان اجتماعي|كفالة)', re.IGNORECASE)
_FAMILY_Q = re.compile(r'(زواج|طلاق|خلع|حضانة|نفقة|ميراث|إرث|وصية|ولاية)', re.IGNORECASE)
_CORP_Q   = re.compile(r'(شركة|تأسيس|استثمار|ترخيص|تجاري|تسجيل)', re.IGNORECASE)

_CRIME_CONTENT  = re.compile(r'(يُعاقب|يعاقب|الإعدام|الحبس المؤبد|بالسجن|بالحبس مدة|وبالغرامة)', re.IGNORECASE)
_LABOR_CONTENT  = re.compile(r'(صاحب العمل|المستخدم|مكافأة نهاية الخدمة|عقد الاستخدام|فصل العامل|حقوق العامل|بالإنهاء)', re.IGNORECASE)
_IS_TOC         = re.compile(r'\|.*\|\s*\d+')         # فهرس المحتويات: "الفصل | 123"
_IS_AMENDMENT   = re.compile(r'^[\s\n]*(يُستبدل|يستبدل|ُيستبدل|يُضاف|يُضاف)')  # مادة تعديلية (أول سطر فقط)

def _rerank_by_domain(chunks: list, q: str) -> list:
    """إعادة ترتيب النتائج بحسب: نوع القانون، وبنية المادة، وقرب الكلمة المفتاحية.
    يُخفِّض رتبة رؤوس الفصول وفهرس المحتويات."""
    # الكلمات المفتاحية الجوهرية للسؤال
    core_kws = extract_keywords(q)[:4]

    def boost(c: dict) -> float:
        name       = (c.get("law_name") or "").lower()
        content    = c.get("content", "")
        art_num    = str(c.get("article_number") or "")
        score      = float(c.get("score", 0))

        # ─── خفض: رؤوس الفصول والمواد التعديلية ───
        is_header    = (art_num in ("مقدمة", "تمهيد", "ديباجة") or
                        bool(_IS_TOC.search(content[:200])))
        is_amendment = bool(_IS_AMENDMENT.match(content[:200]))  # "يُستبدل بنص..." (أول 200 حرف)
        if is_header or is_amendment:
            return score - 0.5

        # ─── رفع: الكلمة المفتاحية قريبة من بداية المادة = الموضوع الرئيسي ───
        c200 = content[:200]
        proximity_bonus = 0.0
        for kw in core_kws[:2]:
            bare_kw = strip_al(kw)
            in_c200 = (kw in c200) or (bare_kw in c200)
            kw_count = content.count(kw) + content.count(bare_kw)
            if in_c200 and kw_count >= 3:
                proximity_bonus = 0.40  # كلمة رئيسية + تكرار = الموضوع الأساسي
            elif in_c200:
                proximity_bonus = max(proximity_bonus, 0.20)  # تظهر مبكراً
            elif kw_count >= 3:
                proximity_bonus = max(proximity_bonus, 0.20)  # موضوع متكرر
            if proximity_bonus >= 0.40:
                break

        # ─── رفع: نوع القانون ───
        if _CRIME_Q.search(q):
            name_match    = "عقوبات" in name or "جزائي" in name or "جنائي" in name
            content_match = bool(_CRIME_CONTENT.search(content[:400]))
            domain = (0.8 if (name_match and content_match) else
                      0.6 if name_match else
                      0.3 if content_match else 0.0)
            return score + domain + proximity_bonus

        if _LABOR_Q.search(q):
            name_match    = "عمل" in name or "عمال" in name
            content_match = bool(_LABOR_CONTENT.search(content[:500]))
            if name_match and content_match: return score + 0.6 + proximity_bonus
            if name_match:                   return score + 0.4 + proximity_bonus
            if content_match:                return score + 0.3 + proximity_bonus

        if _FAMILY_Q.search(q) and ("أسرة" in name or "أحوال شخصية" in name or "زواج" in name):
            return score + 0.4 + proximity_bonus

        if _CORP_Q.search(q) and ("شركات" in name or "تجارة" in name or "استثمار" in name):
            return score + 0.3 + proximity_bonus

        return score + proximity_bonus

    return sorted(chunks, key=boost, reverse=True)

def _content_is_relevant(content: str, keywords: list) -> bool:
    """
    تحقق أن المحتوى ذو صلة رئيسية بالسؤال.
    تفحص كلاً من الكلمة الأصلية والكلمة المجرّدة (بدون ال).
    """
    if not keywords: return True
    c350 = content[:350]
    for kw in keywords[:6]:
        bare = strip_al(kw)  # الكلمة بدون "ال" التعريف
        # ظهور مبكر (أول 350 حرف = نص المادة الرئيسي)
        if kw in c350:   return True
        if bare in c350: return True
        # تكرار الكلمة مرتين = موضوع رئيسي
        if content.count(kw) >= 2:   return True
        if content.count(bare) >= 2: return True
    return False

def _filter_relevant_chunks(chunks: list, q: str) -> list:
    """تصفية النتائج بحسب الصلة الرئيسية بالسؤال"""
    kws = extract_keywords(q)
    if not kws: return chunks
    valid = [c for c in chunks if _content_is_relevant(c["content"], kws)]
    return valid if valid else chunks  # لا نحذف كل شيء إذا لم يبقَ شيء

def _clean_chunk_text(text: str, art: str) -> str:
    """تنظيف النص: إزالة أسطر رقم المادة البادئة (المادة\n300\n أو المادة 300)"""
    lines = text.strip().split("\n")
    # حذف أسطر الرقم البادئة: "المادة"، ثم "300" في سطر منفصل
    while lines:
        stripped = lines[0].strip()
        if re.match(r'^(المادة\s*)?$', stripped):           # سطر "المادة" فارغ
            lines = lines[1:]
        elif re.match(r'^\d+\s*$', stripped):               # سطر رقم فقط
            lines = lines[1:]
        elif re.match(r'^المادة\s*\d+\s*$', stripped):      # "المادة 300"
            lines = lines[1:]
        else:
            break
    return "\n".join(lines).strip()

def _format_direct_expert(chunks: list, q: str) -> str:
    """تنسيق مباشر للمواد القانونية بدون LLM — للاستفسارات المباشرة"""
    lines = []
    for i, c in enumerate(chunks[:3]):
        art  = c.get("article_number", "")
        name = c.get("law_name", "")
        year = c.get("law_year", "")
        text = _clean_chunk_text(c["content"], str(art))

        # ترويسة المادة
        header = f"**المادة ({art}) — {name}"
        if year: header += f" لسنة {year}"
        header += ":**"
        lines.append(header)
        lines.append(f'"{text}"')
        lines.append("")

    if len(chunks) > 1:
        lines.append(f"---\n*تم العثور على {len(chunks)} نص ذي صلة — المصادر أدناه.*")

    return "\n".join(lines)

def _format_direct_general(chunk: dict) -> str:
    """تنسيق مبسّط للمستخدم العام بدون LLM"""
    art  = chunk.get("article_number", "")
    name = chunk.get("law_name", "")
    year = chunk.get("law_year", "")
    num  = chunk.get("law_number", "")
    text = _clean_chunk_text(chunk["content"], str(art))

    lines = [text, ""]
    ref = f"📖 المادة ({art})"
    if name: ref += f" من {name}"
    if num:  ref += f" رقم ({num})"
    if year: ref += f" لسنة {year}"
    lines.append(ref)
    return "\n".join(lines)

_CONVERSATIONAL = re.compile(
    r'(^(كيف حالك|كيف الحال|كيف أنت|كيف انت|ازيك|إزيك|شلونك|شلونج|ما أخبارك|ما اخبارك|أخبارك|اخبارك)'
    r'|^(شكر|مرحب|أهلاً|أهلا|هلا|هلو|صباح|مساء|مع السلامة|باي|وداع|السلام عليكم|وعليكم)'
    r'|^(هل أنت|من أنت|ماذا تفعل|ما اسم|ما قدرات|ماذا تستطيع|أنت ذكاء|أنت روبوت|كيف تعمل)'
    r'|^(شكراً|شكرا|ممنون|مشكور|عظيم|ممتاز|تمام|حسناً|حسنا|أوكي|ok\b|معليش|آسف|عفواً|عفوا)'
    r'|^(أنا بخير|أنا تمام|لا شيء|لا شئ|فقط أسأل|مجرد سؤال))',
    re.IGNORECASE
)
_NEEDS_ANALYSIS = re.compile(
    r'(هل يتعارض|ما الفرق|قارن|حلل|استنبط|ما شروط|هل يجوز|ما مدى|كيف تفسر|'
    r'ما أثر|في حال|بناءً على|يترتب على|ما الحكم.*إذا|ما التكييف|ما التفسير|'
    r'ما حقوق|ما التزامات|ما إجراءات|ما الخطوات|ما الشروط|ما الواجبات)',
    re.IGNORECASE
)
# كلمات تدل على وجود سؤال قانوني حقيقي
_LEGAL_KWS = re.compile(
    r'(عقوبة|جريمة|قانون|مادة|محكمة|قضاء|دعوى|عقد|إيجار|طلاق|زواج|ميراث|'
    r'ترخيص|شركة|تعويض|غرامة|حبس|سجن|إعدام|رشوة|سرقة|قتل|اغتصاب|احتيال|'
    r'تزوير|نصب|شيك|راتب|خدمة مدنية|موظف حكومي|استئناف|تقاضي|نزاع|تسوية)',
    re.IGNORECASE
)

def _route_query(q: str, top_score: float) -> str:
    """
    direct → استخراج فوري من النص (بدون LLM)
    llm    → تحليل بالنموذج
    chat   → رد محادثي (تحية / أسئلة شخصية / موضوع خارج القانون)
    """
    q_strip = q.strip()
    # 1) تحيّة أو محادثة شخصية → chat فوراً
    if _CONVERSATIONAL.search(q_strip): return "chat"
    # 2) سؤال لا يحتوي مصطلحاً قانونياً واضحاً وثقة النتائج منخفضة → chat
    if not _LEGAL_KWS.search(q) and top_score < 0.82: return "chat"
    # 3) أسئلة تحليلية → LLM
    if _NEEDS_ANALYSIS.search(q): return "llm"
    # 4) نتيجة واضحة → استخراج مباشر
    if top_score >= 0.80: return "direct"
    if top_score >= 0.45: return "direct"
    return "llm"

@app.post("/api/v1/query/")
async def query(req: Q):
    try:
        q       = req.query.strip()
        m       = req.mode or "expert"
        conv_id = req.conversation_id or str(uuid.uuid4())
        system  = EXPERT_SYSTEM if m == "expert" else GENERAL_SYSTEM

        # ── سجل المحادثة ──
        history = _convs[conv_id]

        # ── بحث في التشريعات ──
        chunks  = await hybrid_search(q, conv_history=history, top_k=15)

        # ── تصفية النتائج ──
        relevant = [
            c for c in chunks
            if float(c["score"]) > 0.38 or c.get("keyword_match")
        ][:12]

        # تصفية الصلة الحقيقية + إعادة الترتيب بحسب نوع الاستفسار
        relevant = _filter_relevant_chunks(relevant, q) if relevant else relevant
        relevant = _rerank_by_domain(relevant, q)
        top_score = float(relevant[0]["score"]) if relevant else 0

        # اكتشاف أسئلة المتابعة القصيرة فقط ("اشرح أكثر"، "وضّح")
        # أما أسئلة "وما هي العقوبة" فهي أسئلة قانونية جديدة → direct
        follow_up = bool(history) and re.search(
            r'^(اشرح|وضّح|أضف|استمر|ما المزيد|أعِد|وضّح لي)', q.strip()
        ) and len(q) < 40  # فقط الأسئلة القصيرة جداً

        route = "llm" if follow_up else _route_query(q, top_score)

        # ── ردود هوية جاهزة (تتجاوز النموذج تماماً) ──
        _IDENTITY_Q = re.compile(
            r'(من أنت|ما اسمك|ما هو اسمك|ماذا تفعل|ما قدراتك|ماذا تستطيع|'
            r'أنت ذكاء|أنت روبوت|أنت برنامج|كيف تعمل|ما هو عملك|من صنعك|من طورك)',
            re.IGNORECASE
        )
        if _IDENTITY_Q.search(q):
            answer = (
                "أنا **مستشار** 👋 — نظام ذكاء اصطناعي متخصص في القانون القطري.\n\n"
                "يمكنني مساعدتك في:\n"
                "⚖️ البحث عن العقوبات والمواد القانونية\n"
                "📋 تحليل العقود والحقوق والالتزامات\n"
                "🏛️ الإجابة عن أسئلة قانون الأسرة، التجاري، الجنائي\n"
                "💬 والحديث معك بشكل عام!\n\n"
                "ما الذي يمكنني مساعدتك به اليوم؟"
            )
            _convs[conv_id].append({"role": "user", "content": q})
            _convs[conv_id].append({"role": "assistant", "content": answer})
            return {
                "answer": answer, "sources": [], "domain": "عام",
                "confidence": 100, "is_grounded": False,
                "conversation_id": conv_id, "route": "identity"
            }

        # ══════════════════════════════════════════
        #  مسار 1: استخراج مباشر بدون LLM (سريع)
        # ══════════════════════════════════════════
        if route == "direct" and relevant:
            if m == "expert":
                answer = _format_direct_expert(relevant, q)
            else:
                answer = _format_direct_general(relevant[0])

        # ══════════════════════════════════════════
        #  مسار 2: ردّ محادثي — نموذج 7b للجودة
        # ══════════════════════════════════════════
        elif route == "chat":
            # نموذج 1.5b (سريع) مع سياق المحادثة
            msgs = list(history[-4:])
            msgs.append({"role": "user", "content": q})
            answer = await ollama_chat(msgs, CHAT_SYSTEM)

        # ══════════════════════════════════════════
        #  مسار 3: تحليل LLM مع السياق القانوني
        # ══════════════════════════════════════════
        else:
            if relevant:
                # أفضل 3 مصادر، 350 حرف لكل واحد (مختصر للسرعة)
                ctx_parts = []
                for i, c in enumerate(relevant[:3]):
                    ctx_parts.append(
                        f"[{i+1}] {c['law_name']} م({c['article_number']})\n"
                        f"{c['content'][:400]}"
                    )
                context = "\n---\n".join(ctx_parts)
                user_msg = (
                    f"النصوص (استند لها فقط):\n{context}\n---\n"
                    f"السؤال: {q}"
                )
            else:
                user_msg = f"السؤال: {q}\n[لا توجد نصوص ذات صلة — أخبر المستخدم بذلك]"

            # بناء الرسائل مع السجل
            msgs = list(history[-6:])   # آخر 3 تبادلات
            msgs.append({"role": "user", "content": user_msg})
            answer = await ollama_chat(msgs, system)

        # ── حفظ المحادثة ──
        _convs[conv_id].append({"role": "user",      "content": q})
        _convs[conv_id].append({"role": "assistant",  "content": answer})
        if len(_convs[conv_id]) > MAX_HIST * 2:
            _convs[conv_id] = _convs[conv_id][-MAX_HIST * 2:]

        # ── المصادر ──
        sources = [{
            "title":      c["law_name"],
            "law_num":    c["law_number"],
            "law_year":   c["law_year"],
            "article":    c["article_number"],
            "score":      round(float(c["score"]), 3),
            "excerpt":    c["content"][:350],
            "domain":     "قانوني",
            "source":     c.get("source", ""),
            "mizan_link": make_mizan_link(c.get("law_id"), c.get("law_number",""), c.get("law_year","")),
        } for c in relevant]

        return {
            "answer":          answer,
            "sources":         sources,
            "domain":          "قانوني",
            "confidence":      round(top_score * 100),
            "is_grounded":     bool(relevant),
            "conversation_id": conv_id,
            "route":           route,
        }

    except Exception as e:
        return {
            "answer":          f"خطأ تقني: {str(e)}",
            "sources":         [],
            "domain":          "خطأ",
            "confidence":      0,
            "is_grounded":     False,
            "conversation_id": req.conversation_id or "",
        }
