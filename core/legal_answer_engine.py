# -*- coding: utf-8 -*-
"""
core/legal_answer_engine.py — reasoning layer for LEGAL Q&A (non-memo).

WHY THIS EXISTS (CP7 FINDING #17)
==================================
The memo pipeline got a reasoning layer in CP6 (``legal_reasoning_engine``).
It characterizes the legal ground, selects 2-3 relevant articles, reranks
precedents by principle, composes prose, verifies grounding.

But ``handle_general`` — the path every FACTUAL LEGAL QUESTION takes
("ما هي عقوبات المرور", "ما عقوبة السرقة", "اذكر أحكام تمييز...") —
STILL hits OpenAI with raw RAG chunks and gets back whatever the LLM
feels like saying. Result: vague deflective answers with no article
numbers, no law citations, no cassation refs.

Symptom (the user's T1 + T6):
  Q: "ما هي عقوبات المرور وسحب الرخصة؟"
  A: "العقوبات تشمل الغرامات المالية وسحب الرخصة في حالات معينة.
      يُفضل الاطلاع على قانون المرور للحصول على تفاصيل دقيقة."
     (No article. No law number. No penalty table. Just advice to
     "go look it up yourself".)

Root cause: the pipeline has NO answer-composition reasoning. It
retrieves, it prompts, it dumps. There is no layer that SELECTS the
best-supporting articles and COMPOSES a cited, structured answer.

DESIGN — symmetric to legal_reasoning_engine (memo)
====================================================
Same 5 stages, adapted for Q&A:

  1. CLASSIFY      — is this a definitional Q, procedure Q, penalty Q,
                     case-analysis Q, or general info Q?
  2. SELECT        — from retrieved RAG chunks, pick the 2-3 that
                     ACTUALLY answer the question (not just text-similar).
  3. RERANK (opt)  — if precedents were retrieved, rerank by question fit.
  4. COMPOSE       — LLM writes a CITED structured answer.
                     Never dumps chunk text verbatim.
                     Every legal claim has an article citation.
                     Every case reference has a ruling number.
  5. VERIFY        — programmatic check: every article number cited must
                     be in the candidate chunk set.

The composer prompt enforces:
  - Use ONLY the provided sources (articles + precedents).
  - Cite article numbers WITH law names and years.
  - Quote the relevant legal text when possible.
  - Structure: direct answer → legal basis → practical advice.
  - No vague deflection ("استشر محامي"), no "لم أستطع الإجابة" escapes.

CONTRACT
========
Primary entry point:
    async compose_reasoned_answer(
        query, history, retrieved_chunks, query_domain
    ) -> ReasonedAnswerResult

ReasonedAnswerResult captures:
  • answer_text      — composed answer (prose with citations)
  • question_type    — classification result
  • selected_sources — chunks the composer actually used
  • verification     — grounding report
  • used_engine      — True on success, False on fallback

On ANY stage failure → used_engine=False, caller falls back to
existing raw-LLM path.

NON-GOALS
=========
  • Does NOT replace the retrieval layer (``_llm.search``).
  • Does NOT replace handle_general's history/case_memory logic.
  • Does NOT modify the RAG pipeline.
  • ONLY replaces the final "generate answer" step.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

_LLM_TIMEOUT_SECONDS     = 12.0
_CACHE_TTL_SECONDS       = 1800       # 30 min — answers evolve faster than memos
_MAX_SELECTED_SOURCES    = 5
_CLASSIFY_MAX_TOKENS     = 300
_SELECT_SOURCES_MAX_TOKENS = 400
_COMPOSE_ANSWER_MAX_TOKENS = 1800


# ═══════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════

@dataclass
class QuestionClassification:
    """What KIND of legal question is this?"""
    question_type:  str         = ""   # definitional / procedure / penalty / analysis / general
    expected_scope: str         = ""   # "single article" / "multi-article" / "domain-wide"
    key_concepts:   list[str]   = field(default_factory=list)
    confidence:     float       = 0.0


@dataclass
class SelectedSource:
    """One source chunk the composer chose to cite."""
    article_number:  str = ""
    law_name:        str = ""
    law_year:        str = ""
    content_snippet: str = ""
    relevance_score: float = 0.0
    reason:          str = ""


@dataclass
class AnswerVerification:
    """Programmatic check after composition."""
    passed:            bool       = True
    invented_articles: list[str]  = field(default_factory=list)
    warnings:          list[str]  = field(default_factory=list)


@dataclass
class ReasonedAnswerResult:
    answer_text:       str                         = ""
    classification:    QuestionClassification      = field(default_factory=QuestionClassification)
    selected_sources:  list[SelectedSource]        = field(default_factory=list)
    verification:      AnswerVerification          = field(default_factory=AnswerVerification)
    used_engine:       bool                        = False
    elapsed_seconds:   float                       = 0.0
    failure_reason:    Optional[str]               = None


# ═══════════════════════════════════════════════════════════════════
# System prompts
# ═══════════════════════════════════════════════════════════════════

_CLASSIFY_QUESTION_SYSTEM = """\
أنت محامٍ قطري خبير. حدد نوع السؤال القانوني المطروح.

الأنواع المحتملة:
- "definitional": سؤال عن تعريف (مثل: ما هو الخلع؟)
- "procedure": سؤال عن إجراءات (مثل: كيف أرفع دعوى؟)
- "penalty": سؤال عن عقوبة/جزاء (مثل: ما عقوبة السرقة؟)
- "analysis": تحليل لحالة محددة
- "general": معلومات عامة عن قانون

الـ scope:
- "single article": الإجابة تعتمد على مادة واحدة رئيسية.
- "multi-article": تحتاج عدة مواد من نفس القانون.
- "domain-wide": تحتاج مراجعة مجال قانوني كامل.

استخرج أيضاً key_concepts — 2-5 مصطلحات قانونية في السؤال.
ثقة (confidence) من 0 إلى 1.

أخرج JSON فقط بهذه البنية:
{
  "question_type": "...",
  "expected_scope": "...",
  "key_concepts": ["...", "..."],
  "confidence": 0.0
}
"""


_SELECT_SOURCES_SYSTEM = """\
أنت محامٍ قطري خبير. من قائمة نصوص قانونية مسترجعة، اختر 2-5 فقط
هي الأكثر ارتباطاً بالسؤال. ارفض البقية.

قواعد:
1. اختر فقط المواد التي تُجيب على السؤال مباشرة.
2. ارفض المواد التي تُغطي مواضيع مشابهة لكن ليست المطلوب.
3. ارفض المواد خارج المجال الموضوعي للسؤال.
4. ثقة كل اختيار (relevance_score) بين 0 و 1.
5. اذكر السبب لكل اختيار.

أخرج JSON فقط:
{
  "selected": [
    {"article_number": "...", "relevance_score": 0.0, "reason": "..."},
    ...
  ]
}

لا تُرقّم المواد من خيالك — استخدم أرقام المواد من قائمة المصادر المقدمة.
"""


_COMPOSE_ANSWER_SYSTEM = """\
أنت محامٍ قطري خبير يُجيب على أسئلة قانونية. اكتب إجابة مُستشهدة،
منظمة، دقيقة. ممنوع التعميم والتهرب.

القيود القطعية:
1. استشهد بأرقام المواد مع اسم القانون ورقمه وسنته.
   مثال: "المادة (357) من قانون العقوبات القطري رقم (11) لسنة 2004".
2. اقتبس النص القانوني المناسب حرفياً بين «...» عند الحاجة.
3. لا تذكر مادة غير موجودة في قائمة المصادر المقدّمة.
4. لا تذكر حكم تمييز (رقم طعن) غير موجود في قائمة المصادر.
5. ممنوع الإجابات المعممة: "استشر محامي" أو "يُفضل الاطلاع على القانون"
   إلا كإضافة في نهاية الإجابة، ليس بديلاً عنها.

هيكل الإجابة:
1. **الإجابة المباشرة** (جملة أو جملتين واضحتين).
2. **السند القانوني** (المواد المختارة مع الاستشهاد + الاقتباس).
3. **تفصيل عملي** (كيف تنطبق على الحالات المختلفة).
4. **توصية ختامية** (إذا مناسب — عند تعقيد يستحق محامي).

الأسلوب:
- استخدم العربية الفصحى القانونية.
- كن محدداً: أرقام، مدد، مبالغ، استثناءات.
- prose متماسكة، ليست bullets جافة.

أخرج نص الإجابة مباشرة — لا JSON، لا تعليق.
"""


# ═══════════════════════════════════════════════════════════════════
# Public entry point
# ═══════════════════════════════════════════════════════════════════

async def compose_reasoned_answer(
    *,
    query:              str,
    history:            Optional[list],
    retrieved_chunks:   list[dict],
    query_domain:       Optional[str] = None,
) -> ReasonedAnswerResult:
    """Compose a lawyer-quality cited answer via LLM reasoning."""
    t0 = time.time()
    result = ReasonedAnswerResult()

    try:
        # ── Stage 1: Classify question ──────────────────────────
        classification = await _classify_question(query=query, history=history)
        result.classification = classification

        if not retrieved_chunks:
            # No sources to reason over — fall back.
            result.failure_reason = "no retrieved chunks"
            return result

        # ── Stage 2: Select relevant sources ─────────────────────
        # If we have few candidates (<=4) use them ALL — skipping the
        # LLM-filter step saves latency AND prevents over-rejection
        # when retrieval itself is already narrow. The LLM filter
        # helps when retrieval returns 8-12 mixed chunks.
        if len(retrieved_chunks) <= 4:
            selected = [
                SelectedSource(
                    article_number=str(c.get("article_number", "")),
                    law_name=str(c.get("law_name", "")),
                    law_year=str(c.get("law_year", "")),
                    content_snippet=(c.get("content") or "")[:500],
                    relevance_score=1.0,
                    reason="auto-kept (narrow retrieval)",
                )
                for c in retrieved_chunks
                if c.get("content")
            ]
        else:
            selected = await _select_sources(
                query=query,
                classification=classification,
                candidates=retrieved_chunks,
            )
        if not selected:
            # Filter rejected everything — fall back gracefully
            result.failure_reason = "no sources selected"
            return result
        result.selected_sources = selected

        # ── CP8 — pull domain expertise (if detected domain) ─────
        _expertise = None
        if query_domain:
            try:
                from core.qatar_legal_expertise import get_domain_expertise
                # Map legacy query_domain to new domain_key when possible
                _domain_key_map = {
                    "عمالي":   "unlawful_termination",
                    "أسري":    "family_custody",  # default for family
                    "جزائي":   None,              # dispatched below
                    "family":  "family_custody",
                    "labor":   "unlawful_termination",
                    "traffic": "traffic",
                }
                _mapped_key = _domain_key_map.get(query_domain, query_domain)
                if _mapped_key:
                    _expertise = get_domain_expertise(_mapped_key)
                # Secondary dispatch — refine by query content
                q_lower = (query or "").lower()
                if "مخدر" in q_lower or "حشيش" in q_lower or "تعاط" in q_lower:
                    _alt = get_domain_expertise("criminal_drug_use")
                    if _alt:
                        _expertise = _alt
                elif "نفقة" in q_lower:
                    _alt = get_domain_expertise("family_nafaqa")
                    if _alt:
                        _expertise = _alt
                elif "طلاق" in q_lower and "ضرر" in q_lower:
                    _alt = get_domain_expertise("divorce_for_harm")
                    if _alt:
                        _expertise = _alt
                elif "شيك" in q_lower:
                    _alt = get_domain_expertise("bad_check")
                    if _alt:
                        _expertise = _alt
                elif (
                    "مرور" in q_lower or "رخصة" in q_lower
                    or "سياره" in q_lower or "سيارة" in q_lower
                ):
                    _alt = get_domain_expertise("traffic")
                    if _alt:
                        _expertise = _alt
            except Exception as _exp_err:
                log.debug("answer_engine: expertise fetch failed: %s", _exp_err)

        # ── Stage 3: Compose cited answer ───────────────────────
        answer_text = await _compose_answer(
            query=query,
            classification=classification,
            selected_sources=selected,
            history=history,
            domain_expertise=_expertise,
        )
        if not answer_text or len(answer_text) < 100:
            result.failure_reason = f"compose produced short output ({len(answer_text or '')})"
            return result
        result.answer_text = answer_text

        # ── Stage 4: Verify grounding ───────────────────────────
        result.verification = _verify_grounding(
            answer_text=answer_text,
            allowed_article_numbers={
                s.article_number for s in selected if s.article_number
            },
        )

        result.used_engine = True
        result.elapsed_seconds = time.time() - t0
        log.info(
            "answer_engine: composed via engine (type=%s, sources=%d, "
            "%.1fs, grounded=%s)",
            classification.question_type,
            len(selected),
            result.elapsed_seconds,
            result.verification.passed,
        )
        return result

    except Exception as e:
        result.failure_reason = f"{type(e).__name__}: {e}"
        result.elapsed_seconds = time.time() - t0
        log.warning("answer_engine: pipeline failure — %s", result.failure_reason)
        return result


# ═══════════════════════════════════════════════════════════════════
# Stage 1 — Classify
# ═══════════════════════════════════════════════════════════════════

async def _classify_question(
    query:   str,
    history: Optional[list],
) -> QuestionClassification:
    cache_key = _fingerprint({"stage": "classify", "query": query})
    cached = await _cache_get(cache_key)
    if cached:
        try:
            return QuestionClassification(**cached)
        except Exception:
            pass

    # Brief history context for pronoun resolution
    recent = ""
    if history:
        last_user = [
            m.get("content", "") for m in history[-4:]
            if m.get("role") == "user"
        ]
        if last_user:
            recent = "\nسياق الرسائل السابقة: " + " | ".join(last_user[-2:])

    user_message = f"السؤال الحالي:\n{query}{recent}"

    raw = await _llm_json_call(
        system=_CLASSIFY_QUESTION_SYSTEM,
        user_message=user_message,
        max_tokens=_CLASSIFY_MAX_TOKENS,
    )
    if not raw:
        return QuestionClassification()

    try:
        c = QuestionClassification(
            question_type  = str(raw.get("question_type", "general")),
            expected_scope = str(raw.get("expected_scope", "single article")),
            key_concepts   = [str(x) for x in raw.get("key_concepts", [])][:5],
            confidence     = float(raw.get("confidence", 0.5)),
        )
    except Exception:
        return QuestionClassification()

    await _cache_set(cache_key, {
        "question_type":  c.question_type,
        "expected_scope": c.expected_scope,
        "key_concepts":   c.key_concepts,
        "confidence":     c.confidence,
    })
    return c


# ═══════════════════════════════════════════════════════════════════
# Stage 2 — Select Sources
# ═══════════════════════════════════════════════════════════════════

async def _select_sources(
    query:          str,
    classification: QuestionClassification,
    candidates:     list[dict],
) -> list[SelectedSource]:
    if not candidates:
        return []

    # Build candidate summary: article_number + law_name + snippet
    lines: list[str] = []
    for i, c in enumerate(candidates[:12]):
        art = str(c.get("article_number", "") or "")
        law = str(c.get("law_name", "") or "")
        content = (c.get("content") or "")[:200]
        lines.append(f"[{i+1}] المادة ({art or '?'}) من {law}: {content}...")
    candidates_text = "\n".join(lines)

    user_message = (
        f"السؤال: {query}\n"
        f"نوع السؤال: {classification.question_type}\n"
        f"المصطلحات المفتاحية: {', '.join(classification.key_concepts)}\n\n"
        f"المصادر المرشحة ({len(candidates)}):\n{candidates_text}\n\n"
        f"اختر 2-5 مواد فقط — الأكثر ارتباطاً بالسؤال."
    )

    raw = await _llm_json_call(
        system=_SELECT_SOURCES_SYSTEM,
        user_message=user_message,
        max_tokens=_SELECT_SOURCES_MAX_TOKENS,
    )
    if not raw:
        return []

    selected_raw = raw.get("selected", [])
    if not isinstance(selected_raw, list):
        return []

    by_art = {str(c.get("article_number", "")): c for c in candidates}
    out: list[SelectedSource] = []
    for item in selected_raw[:_MAX_SELECTED_SOURCES]:
        art = str(item.get("article_number", "")).strip()
        if not art:
            continue
        src = by_art.get(art, {})
        out.append(SelectedSource(
            article_number = art,
            law_name       = str(src.get("law_name", "")),
            law_year       = str(src.get("law_year", "")),
            content_snippet= (src.get("content") or "")[:500],
            relevance_score= float(item.get("relevance_score", 0.0)),
            reason         = str(item.get("reason", ""))[:200],
        ))
    return out


# ═══════════════════════════════════════════════════════════════════
# Stage 3 — Compose Answer
# ═══════════════════════════════════════════════════════════════════

async def _compose_answer(
    query:            str,
    classification:   QuestionClassification,
    selected_sources: list[SelectedSource],
    history:          Optional[list],
    domain_expertise=None,        # CP8 — DomainExpertise or None
) -> str:
    sources_block = "\n".join(
        f"المادة ({s.article_number}) من {s.law_name}"
        f"{' لسنة ' + s.law_year if s.law_year else ''}\n"
        f"النص: «{s.content_snippet[:350]}...»\n"
        f"(الصلة: {s.reason})"
        for s in selected_sources
    ) or "(لم يتم اختيار مصادر محددة — أجب من المبادئ العامة بحذر)"

    # Brief conversational context
    history_note = ""
    if history:
        last_few = [
            m for m in history[-4:]
            if m.get("role") in ("user", "assistant")
        ]
        if last_few:
            ctx = "\n".join(
                f"{m.get('role')}: {(m.get('content', '') or '')[:200]}"
                for m in last_few
            )
            history_note = f"\nسياق المحادثة السابقة:\n{ctx}\n"

    # CP8 — inject Qatari domain expertise when available
    expertise_block = ""
    if domain_expertise is not None:
        try:
            expertise_block = (
                "\n═══ خبرة قانونية قطرية متخصصة (استخدمها لإثراء الإجابة) ═══\n"
                + domain_expertise.to_prompt_hints()
                + "\n"
            )
        except Exception:
            expertise_block = ""

    user_message = (
        f"السؤال:\n{query}\n\n"
        f"نوع السؤال: {classification.question_type}\n"
        f"النطاق المتوقع: {classification.expected_scope}\n"
        f"{history_note}\n"
        f"المصادر القانونية المختارة للاستشهاد (لا تضف غيرها):\n"
        f"{sources_block}"
        f"{expertise_block}\n"
        f"اكتب الإجابة المُستشهدة الآن — استخدم الخبرة المتخصصة أعلاه "
        f"(الأسس الشائعة، المبادئ الراسخة، الإجراءات، المحكمة المختصة) "
        f"لإعطاء إجابة احترافية مفصلة."
    )

    try:
        from services.llm_service import call_openai
    except ImportError:
        return ""

    try:
        resp = await asyncio.wait_for(
            call_openai(
                system=_COMPOSE_ANSWER_SYSTEM,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=_COMPOSE_ANSWER_MAX_TOKENS,
            ),
            timeout=_LLM_TIMEOUT_SECONDS * 2,
        )
    except asyncio.TimeoutError:
        return ""
    except Exception as e:
        log.warning("answer_engine: compose LLM failed: %s", e)
        return ""

    if not resp or not isinstance(resp, str):
        return ""
    if resp.strip().startswith("خطأ"):
        return ""
    return resp.strip()


# ═══════════════════════════════════════════════════════════════════
# Stage 4 — Verify (programmatic)
# ═══════════════════════════════════════════════════════════════════

def _verify_grounding(
    answer_text:             str,
    allowed_article_numbers: set[str],
) -> AnswerVerification:
    import re
    vr = AnswerVerification()

    cited_articles = set()
    for m in re.finditer(r"المادة\s*[\(\[]?(\d+)[\)\]]?", answer_text):
        cited_articles.add(m.group(1))

    if allowed_article_numbers:
        for cited in cited_articles:
            if cited not in allowed_article_numbers:
                vr.invented_articles.append(cited)
                vr.passed = False

    return vr


# ═══════════════════════════════════════════════════════════════════
# LLM + cache helpers (shared semantics with legal_reasoning_engine)
# ═══════════════════════════════════════════════════════════════════

async def _llm_json_call(
    system:       str,
    user_message: str,
    max_tokens:   int,
) -> Optional[dict]:
    try:
        from services.llm_service import call_openai
    except ImportError:
        return None

    try:
        resp = await asyncio.wait_for(
            call_openai(
                system=system,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=max_tokens,
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None

    if not resp or not isinstance(resp, str):
        return None
    if resp.strip().startswith("خطأ"):
        return None

    cleaned = resp.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:])
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _fingerprint(obj: Any) -> str:
    try:
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:24]


async def _cache_get(key: str) -> Optional[Any]:
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        raw = await client.get(f"answer_engine:{key}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None


async def _cache_set(key: str, value: Any) -> None:
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        await client.set(
            f"answer_engine:{key}",
            json.dumps(value, ensure_ascii=False),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass


__all__ = [
    "QuestionClassification", "SelectedSource",
    "AnswerVerification", "ReasonedAnswerResult",
    "compose_reasoned_answer",
]
