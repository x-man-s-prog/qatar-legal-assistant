# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        Clarification Engine — المساعد القانوني القطري                        ║
║        يكتشف الغموض ويطرح سؤالاً توضيحياً قبل الدخول في RAG                ║
╚══════════════════════════════════════════════════════════════════════════════╝

الاستخدام:
    score = compute_ambiguity_score(question, semantic_frame, history)
    if score > AMBIGUITY_THRESHOLD:
        q = await generate_clarification_question(question, llm_caller)
        return {"clarification_needed": True, "question": q}
"""
from __future__ import annotations

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── عتبة الغموض ──────────────────────────────────────────────────────────────
AMBIGUITY_THRESHOLD = 0.68   # فوق هذا → اطلب توضيحاً

# ── مؤشرات وجود لغة قانونية ──────────────────────────────────────────────────
_LEGAL_ANCHORS = re.compile(
    r"(المادة|القانون|عقوبة|محكمة|طلاق|عقد|توثيق|دعوى|شكوى|غرامة|"
    r"نفقة|حضانة|عمل|فصل|راتب|سرقة|اعتداء|جريمة|ميراث|إرث|شركة|"
    r"تعويض|إيجار|ترخيص|جواز|إقامة|تأشيرة|ضريبة|وصية)",
    re.UNICODE,
)

# ── ضمائر مبهمة بدون مرجع ────────────────────────────────────────────────────
_VAGUE_PRONOUNS = re.compile(r"\b(هو|هي|هم|هن|هذا|هذه|ذلك|تلك|فلان|شخص ما)\b", re.UNICODE)

# ── عبارات الطلب المبهم ──────────────────────────────────────────────────────
_VAGUE_REQUEST = re.compile(
    r"^(ابغى|أبغى|أريد|بغيت|بدي|احتاج|كيف|وش|إيش|شو)\s*(اعرف|أعرف|أعلم)?\s*$",
    re.UNICODE,
)

_CLARIFICATION_PROMPT = """أنت مساعد قانوني قطري ذكي.

استلمت هذا السؤال الغامض: "{question}"

مهمتك: اطرح سؤالاً توضيحياً واحداً فقط باللغة العربية الفصحى البسيطة
لفهم ما يريده المستخدم بالضبط.

القواعد:
- سؤال واحد فقط
- قصير ومحدد (أقل من 25 كلمة)
- لا تعطِ إجابة ولا شرحاً الآن
- ابدأ بـ "لكي أساعدك..."

أعِد السؤال التوضيحي مباشرة:"""


def compute_ambiguity_score(
    question: str,
    semantic_frame: Optional[dict] = None,
    history: Optional[list[dict]] = None,
) -> float:
    """
    يحسب درجة غموض السؤال من 0.0 إلى 1.0.

    المؤشرات (مرجّحة):
      1. قِصَر السؤال جداً          → +0.30
      2. غياب المصطلحات القانونية    → +0.25
      3. ضمائر مبهمة بدون مرجع      → +0.20
      4. طلب غامض (ابغى / أريد)    → +0.25
      5. semantic_frame فارغ        → +0.15
      6. سياق المحادثة يوضح الغرض  → −0.20
    """
    if not question or not question.strip():
        return 1.0

    q = question.strip()
    word_count = len(q.split())
    score = 0.0

    # 1. السؤال قصير جداً (أقل من 4 كلمات)
    if word_count <= 3:
        score += 0.30
    elif word_count <= 6:
        score += 0.10

    # 2. لا توجد مصطلحات قانونية
    if not _LEGAL_ANCHORS.search(q):
        score += 0.25

    # 3. ضمائر مبهمة
    vague_hits = len(_VAGUE_PRONOUNS.findall(q))
    if vague_hits >= 2:
        score += 0.20
    elif vague_hits == 1 and word_count <= 8:
        score += 0.10

    # 4. طلب غامض من نوع "ابغى"
    if _VAGUE_REQUEST.match(q):
        score += 0.25

    # 5. الإطار الدلالي فارغ أو بدون legal_issue
    if semantic_frame is not None:
        legal_issue = (semantic_frame.get("legal_issue") or "").strip()
        if not legal_issue or legal_issue in ("unknown", "غير محدد", ""):
            score += 0.15
    # إذا لم يُمرَّر semantic_frame نُضيف 0.10 فقط (غير محسوب)
    else:
        score += 0.10

    # 6. إذا كان في المحادثة السابقة سياق يوضح الغرض → اخصم
    if history:
        recent_msgs = " ".join(
            m.get("content", "") for m in history[-4:] if m.get("role") == "user"
        )
        if _LEGAL_ANCHORS.search(recent_msgs):
            score -= 0.20

    final = round(max(0.0, min(1.0, score)), 3)
    log.info("ambiguity_score=%.3f for q='%s'", final, q[:60])
    return final


async def generate_clarification_question(
    question: str,
    llm_caller=None,
) -> str:
    """
    يُولّد سؤالاً توضيحياً مناسباً.
    إذا لم يكن LLM متاحاً → يُعيد سؤالاً قياسياً.
    """
    if llm_caller:
        try:
            prompt = _CLARIFICATION_PROMPT.format(question=question.strip())
            msgs   = [{"role": "user", "content": prompt}]
            result = (await llm_caller("", msgs)).strip()
            if result and len(result) > 10:
                log.info("clarification_q [LLM]: %s", result[:80])
                return result
        except Exception as e:
            log.debug("generate_clarification_question LLM error: %s", e)

    # Fallback: قوالب بحسب نوع الغموض
    q_lower = question.lower().strip()

    if any(w in q_lower for w in ("طلاق", "زواج", "نفقة", "حضانة")):
        return "لكي أساعدك بشكل صحيح، هل سؤالك يتعلق بإجراءات الطلاق، أم بالنفقة، أم بحضانة الأطفال؟"

    if any(w in q_lower for w in ("عمل", "راتب", "فصل", "إجازة")):
        return "لكي أساعدك بشكل صحيح، هل تسأل عن حقوق العامل، أم عن إجراءات إنهاء العقد، أم عن التعويضات؟"

    if any(w in q_lower for w in ("شركة", "عقد", "تجارة")):
        return "لكي أساعدك بشكل صحيح، ما نوع العقد أو المعاملة التجارية التي تقصدها؟"

    if any(w in q_lower for w in ("جريمة", "اعتداء", "سرقة", "شكوى")):
        return "لكي أساعدك بشكل صحيح، هل أنت المتضرر وتريد تقديم شكوى، أم تسأل عن العقوبة المقررة؟"

    # قالب عام
    return "لكي أساعدك بشكل صحيح، هل يمكنك توضيح طبيعة المشكلة القانونية التي تواجهها؟"


def build_clarification_response(clarification_q: str, original_q: str) -> dict:
    """
    يبني استجابة API كاملة عندما يُطلب التوضيح.
    """
    return {
        "answer": clarification_q,
        "sources": [],
        "domain": "توضيح",
        "confidence": 0,
        "is_grounded": False,
        "clarification_needed": True,
        "original_question": original_q,
    }
