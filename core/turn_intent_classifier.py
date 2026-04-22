# -*- coding: utf-8 -*-
"""
core/turn_intent_classifier.py — LLM-based intent classification
per turn.

WHY THIS EXISTS (CP9 FINDING #19)
==================================
Pre-CP9 routing worked like this:

  if session.phase in (AWAITING_MEMO_DETAILS, AWAITING_MEMO_TOPIC):
      if query starts with {"ما هي عقوبة", "كيف", ...}:
          release phase
      else:
          force memo handler

This had a SILENT CATASTROPHIC FAILURE mode. Consider a user
mid-memo typing:

  "احبك"                           → memo generated (!?)
  "كم عدد المبادئ القضائية عندك؟"  → memo generated (!!)
  "افهم السؤال قبل تجاوب"         → memo generated (!!!)

None of these are "ما هي عقوبة" pattern. So the pivot didn't
fire. The state machine kept forcing memo, producing nonsense
memos in response to casual messages, meta-questions, and
complaints.

Root cause: PATTERN MATCHING is not intent recognition. A fixed
list of prefixes cannot cover the infinite variety of human
conversational turns. Real users type:
  • Casual: "احبك", "شكراً", "يعطيك العافية", "هلا"
  • Meta: "كم مبدأ عندك؟", "شنو قدراتك؟", "هل تقدر تسوي X؟"
  • Complaint: "افهم السؤال", "أنت غلط", "هذا مو اللي طلبته"
  • Clarification: "ماذا تقصد؟", "وضح أكثر", "ما فهمت"
  • Command: "اختصر", "اعد الصياغة", "احفظ المذكرة"
  • New legal Q: "ما عقوبة السرقة؟" (covered by old prefix list)
  • Memo continue: more details being added

The OLD prefix list handled ONLY the last two. Everything else
broke.

THE FIX — LLM INTENT CLASSIFIER
================================
For each turn, a cheap LLM call classifies the turn's INTENT
given the current phase and recent history. The decision drives
a routing verdict:

Intent values:
  - MEMO_CONTINUE_DETAILS: user is providing memo facts/details
  - MEMO_CONTINUE_REFINE:  user is asking to modify a drafted memo
  - NEW_LEGAL_QUESTION:    fresh legal question, pivot from memo
  - META_SYSTEM_QUERY:     asking about the system itself
  - CASUAL_SOCIAL:         greeting / emotional / small talk
  - COMPLAINT_FEEDBACK:    user complaining about previous answer
  - CLARIFICATION:         asking what the system meant
  - COMMAND:               "اختصر", "اعد", "اكتب مجدداً"
  - LEGAL_DRAFT_REQUEST:   explicit new memo request

Each intent has a routing verdict:
  - route_to: "memo" / "general" / "meta" / "casual" / "command"
  - release_phase: True/False (should we drop MEMO_DRAFTING?)

DESIGN
======
One LLM call per turn, ~200-400 tokens, cached by
sha1(query + last_assistant_preview).

Fallback: if LLM fails, degrade to the OLD prefix-match behavior
so pre-CP9 correctness is preserved. Never raises.

Cache TTL 10 min (short — conversation context changes fast).
Redis db=2.

NON-GOALS
=========
  • Does NOT replace session_state (CP5). It AUGMENTS routing.
  • Does NOT replace fact_extractor (CP1). Different layer.
  • Does NOT classify the legal DOMAIN of a query. That's a
    separate concern handled elsewhere.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

log = logging.getLogger(__name__)

_LLM_TIMEOUT_SECONDS = 6.0
_CACHE_TTL_SECONDS   = 600    # 10 min
_MAX_TOKENS          = 250


# ═══════════════════════════════════════════════════════════════════
# Intent values
# ═══════════════════════════════════════════════════════════════════

class TurnIntent(str, Enum):
    # Memo-context intents
    MEMO_CONTINUE_DETAILS = "memo_continue_details"  # providing facts
    MEMO_CONTINUE_REFINE  = "memo_continue_refine"   # modify drafted memo
    LEGAL_DRAFT_REQUEST   = "legal_draft_request"    # new memo request

    # Pivot intents
    NEW_LEGAL_QUESTION    = "new_legal_question"     # fresh legal Q
    META_SYSTEM_QUERY     = "meta_system_query"      # about the system
    CASUAL_SOCIAL         = "casual_social"          # chit-chat
    COMPLAINT_FEEDBACK    = "complaint_feedback"     # user dissatisfied
    CLARIFICATION         = "clarification"          # "ماذا تقصد؟"
    COMMAND               = "command"                # "اختصر" etc.

    # Default fallback
    UNCLEAR               = "unclear"


@dataclass
class IntentClassification:
    intent:           TurnIntent = TurnIntent.UNCLEAR
    confidence:       float       = 0.0
    route_to:         str         = "default"  # memo/general/meta/casual/command
    release_phase:    bool        = False       # drop MEMO_* phase?
    reset_hard:       bool        = False       # wipe topic+facts (FINDING #20)
    reasoning:        str         = ""


# ═══════════════════════════════════════════════════════════════════
# Routing rules per intent
# ═══════════════════════════════════════════════════════════════════

_INTENT_ROUTING = {
    TurnIntent.MEMO_CONTINUE_DETAILS: {"route_to": "memo",    "release_phase": False, "reset_hard": False},
    TurnIntent.MEMO_CONTINUE_REFINE:  {"route_to": "memo",    "release_phase": False, "reset_hard": False},
    # FINDING #20: a NEW draft request must HARD-reset memo slots.
    # Without reset, prior topic's facts (e.g. drug case) leak into
    # the new memo (e.g. custody) producing hybrid nonsense.
    TurnIntent.LEGAL_DRAFT_REQUEST:   {"route_to": "memo",    "release_phase": True,  "reset_hard": True},
    TurnIntent.NEW_LEGAL_QUESTION:    {"route_to": "general", "release_phase": True,  "reset_hard": False},
    TurnIntent.META_SYSTEM_QUERY:     {"route_to": "meta",    "release_phase": True,  "reset_hard": False},
    TurnIntent.CASUAL_SOCIAL:         {"route_to": "casual",  "release_phase": True,  "reset_hard": False},
    TurnIntent.COMPLAINT_FEEDBACK:    {"route_to": "casual",  "release_phase": False, "reset_hard": False},
    TurnIntent.CLARIFICATION:         {"route_to": "general", "release_phase": False, "reset_hard": False},
    TurnIntent.COMMAND:               {"route_to": "command", "release_phase": False, "reset_hard": False},
    TurnIntent.UNCLEAR:               {"route_to": "default", "release_phase": False, "reset_hard": False},
}


# ═══════════════════════════════════════════════════════════════════
# LLM system prompt
# ═══════════════════════════════════════════════════════════════════

_INTENT_CLASSIFY_SYSTEM = """\
أنت مصنّف نوايا للمحادثات القانونية. مهمتك: تحديد نية كل رسالة مستخدم
بناءً على محتواها والسياق.

الأنواع المحتملة (اختر واحداً فقط):

1. "memo_continue_details": المستخدم يُقدّم تفاصيل/حقائق لمذكرة طلبها
   سابقاً. أمثلة: قائمة مرقّمة (1- 2- 3-)، أرقام/أسماء/تواريخ، إجابات
   على أسئلة محامي.

2. "memo_continue_refine": المستخدم يطلب تعديل/إعادة صياغة مذكرة
   موجودة. أمثلة: "اعد كتابتها أقصر"، "أضف فقرة عن...", "اكتب
   المذكرة مجدداً".

3. "legal_draft_request": طلب مذكرة جديدة صريح. أمثلة: "اكتب مذكرة
   فصل تعسفي"، "احتاج مذكرة حضانة".

4. "new_legal_question": سؤال قانوني جديد منفصل. أمثلة: "ما عقوبة
   السرقة؟"، "كيف أرفع دعوى خلع؟"، "ما حقوقي في الميراث؟".

5. "meta_system_query": سؤال عن النظام نفسه لا عن القانون. أمثلة:
   "كم عدد المبادئ القضائية عندك؟"، "شنو قدراتك؟"، "هل تقدر تسوي X؟"،
   "عرفني عليك".

6. "casual_social": تحية/مجاملة/عاطفة/محادثة عادية. أمثلة: "احبك"،
   "شكراً"، "مرحبا"، "هلا"، "كيف الحال"، "يعطيك العافية".

7. "complaint_feedback": شكوى من إجابة سابقة. أمثلة: "افهم السؤال"،
   "هذا مو اللي طلبته"، "خطأ"، "اجابتك غلط"، "رد غبي".

8. "clarification": طلب توضيح. أمثلة: "ماذا تقصد؟"، "وضح أكثر"،
   "ما فهمت"، "اشرح أكثر".

9. "command": أمر إجرائي. أمثلة: "اختصر"، "اعد الصياغة"، "احفظ".

10. "unclear": إذا لم يوضح أي من أعلاه.

قواعد حاسمة:
1. "احبك" = casual_social دائماً، ليس مذكرة.
2. سؤال يبدأ بـ "كم" أو "شنو" عن النظام = meta_system_query.
3. "افهم السؤال" / "خطأ" / "رد غبي" = complaint_feedback.
4. قائمة مرقّمة مع تفاصيل = memo_continue_details (لكن فقط إذا
   السياق السابق كان طلب مذكرة).
5. تحية بسيطة = casual_social.

قواعد إضافية مهمة (لتجنّب الإفراط في توجيه المذكرات):
6. إذا الرسالة تصف وقائع (أسماء/أرقام/ادعاءات) بدون طلب صريح لكتابة
   مذكرة، ولم يكن هناك سياق طلب مذكرة سابق → "unclear"
   (دع النظام يقرر طبيعياً، لا تُجبر على memo).
7. "legal_draft_request" يتطلب فعل صريح مثل "اكتب/صغ/احتاج مذكرة/
   عريضة/لائحة/صحيفة دعوى". بدون هذا الفعل، الرسالة التي تصف
   حالة قانونية تُصنَّف كـ "new_legal_question" أو "unclear".
8. "موكلي يريد X..." بدون فعل صياغة = new_legal_question عادةً
   (استشارة، لا طلب صياغة).
9. "لماذا لم تكتب" / "لماذا ما فهمت" = complaint_feedback،
   لكن إذا السياق كان مذكرة مطلوبة → memo_continue_refine بدل
   complaint_feedback.
10. عند الشك بين memo_continue_details و new_legal_question:
    - إذا آخر رد من المساعد كان "قبل ما أكتب مذكرة" / "أحتاج
      منك هذه التفاصيل" → memo_continue_details.
    - غير ذلك → new_legal_question أو unclear.

قواعد حاسمة جداً للتمييز بين meta والسؤال القانوني (تجنّب الخلط):
11. "meta_system_query" = سؤال عن موارد/قدرات النظام نفسه فقط. أمثلة
    دقيقة: "كم عدد المبادئ/الأحكام/المواد/التشريعات عندك؟"، "شنو
    قدراتك؟"، "عرفني عليك"، "هل تستطيع صياغة عقد؟".
12. كل سؤال "كم يبلغ/كم قيمة/كم نسبة/كم راتب/كم أجر/كم تعويض/
    كم مدة/كم سنة/كم يوم/كم ساعة" عن محتوى قانوني حقيقي = سؤال
    محتوى (new_legal_question)، وليس meta. مثال: "كم يبلغ راتب
    موظف بدرجة سابعة في المجلس الوطني؟" = new_legal_question، لأنه
    سؤال إداري/قانوني عن راتب موظف، وليس عن موارد النظام.
13. إذا السؤال يبدأ بـ "كم" لكن يحتوي على كلمات محتوى قانوني
    حقيقية (راتب، موظف، درجة، عقوبة، تعويض، نفقة، حضانة، ميراث،
    قانون رقم X، المادة Y، محكمة، قضية، دعوى) → new_legal_question.
14. إذا السؤال يبدأ بـ "كم" واللاحق منه مفرد/إحصاء لمورد في النظام
    فقط (المبادئ، الأحكام، المواد، التشريعات، القضايا، المجالات)
    → meta_system_query.
15. عند الشك بين meta و new_legal_question: الافتراض الآمن هو
    new_legal_question (نترك النظام يعالجه قانونياً)، لأن خطأ
    "meta-وهو-قانوني" يُفقد الإجابة، بينما خطأ "قانوني-وهو-meta"
    يُنتج إجابة قانونية صحيحة غالباً.

أخرج JSON فقط:
{
  "intent": "casual_social",
  "confidence": 0.9,
  "reasoning": "تعبير عاطفي لا يطلب إجراء قانوني"
}

لا نص خارج JSON.
"""


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

async def classify_turn(
    query:           str,
    current_phase:   str = "",      # idle / awaiting_memo_details / memo_drafting / ...
    last_assistant:  str = "",
    recent_user_msgs: Optional[list[str]] = None,
) -> IntentClassification:
    """Classify the intent of the current turn.

    Returns ``IntentClassification`` with intent + routing verdict.
    Never raises. Falls back to prefix-match heuristics on LLM
    failure.
    """
    if not query or not query.strip():
        c = IntentClassification()
        c.intent = TurnIntent.UNCLEAR
        return c

    q = query.strip()

    # Cache by (query + last_assistant preview)
    cache_key = _fingerprint({
        "q": q,
        "phase": current_phase,
        "last_asst_preview": (last_assistant or "")[:100],
    })
    cached = await _cache_get(cache_key)
    if cached:
        try:
            c = IntentClassification(
                intent        = TurnIntent(cached.get("intent", "unclear")),
                confidence    = float(cached.get("confidence", 0.0)),
                route_to      = str(cached.get("route_to", "default")),
                release_phase = bool(cached.get("release_phase", False)),
                reset_hard    = bool(cached.get("reset_hard", False)),
                reasoning     = str(cached.get("reasoning", "")),
            )
            return c
        except Exception:
            pass

    # ── Fast-path heuristic (avoids LLM for obvious cases) ──
    fast = _fast_path_classify(q)
    if fast is not None:
        await _cache_set(cache_key, _to_dict(fast))
        return fast

    # ── LLM classification ──
    recent_ctx = ""
    if recent_user_msgs:
        recent_ctx = "\nرسائل المستخدم الأخيرة (للسياق فقط):\n" + "\n".join(
            f"- {m[:150]}" for m in recent_user_msgs[-3:]
        )

    user_msg = (
        f"الرسالة الحالية من المستخدم:\n{q}\n\n"
        f"الحالة الحالية في النظام: {current_phase or 'idle'}\n"
        f"آخر رد من المساعد: {(last_assistant or '')[:200]}..."
        f"{recent_ctx}"
    )

    raw = await _llm_json_call(
        _INTENT_CLASSIFY_SYSTEM, user_msg, _MAX_TOKENS,
    )
    if not raw:
        # LLM failed — fall back to prefix heuristic
        return _prefix_fallback(q)

    try:
        intent_str = str(raw.get("intent", "unclear")).strip()
        intent = TurnIntent(intent_str) if intent_str in [
            e.value for e in TurnIntent
        ] else TurnIntent.UNCLEAR
        routing = _INTENT_ROUTING.get(intent, _INTENT_ROUTING[TurnIntent.UNCLEAR])
        c = IntentClassification(
            intent        = intent,
            confidence    = float(raw.get("confidence", 0.5)),
            route_to      = routing["route_to"],
            release_phase = routing["release_phase"],
            reset_hard    = routing.get("reset_hard", False),
            reasoning     = str(raw.get("reasoning", ""))[:200],
        )
    except Exception as e:
        log.warning("intent_classifier: parse failed: %s", e)
        return _prefix_fallback(q)

    await _cache_set(cache_key, _to_dict(c))
    return c


# ═══════════════════════════════════════════════════════════════════
# Fast-path + fallback heuristics
# ═══════════════════════════════════════════════════════════════════

# Obvious short casual expressions — skip LLM call
_FAST_CASUAL = frozenset({
    "احبك", "احبّك", "أحبك", "هلا", "اهلا", "أهلاً", "مرحبا",
    "مرحباً", "هاي", "شكرا", "شكراً", "مشكور", "يعطيك العافية",
    "تسلم", "صباح الخير", "مساء الخير", "السلام عليكم", "وعليكم السلام",
    "كيف الحال", "كيفك", "شخبارك", "انت بخير",
})

# ── Meta fast-path — NARROW and system-term-gated (FINDING #20) ──
# Before FINDING #20, "كم عدد" was a prefix match which caused
# false-meta routing for queries like "كم يبلغ راتب موظف".
# Now fast-path requires BOTH (a) a known system-term phrase OR
# (b) an explicit identity/capability phrase.
#
# The presence of legal content terms (راتب/موظف/عقوبة/تعويض/...)
# in _LEGAL_CONTENT_HINTS disables the meta fast-path entirely —
# we defer to the LLM classifier so it can decide content vs meta.

_FAST_META_EXACT_PHRASES = (
    # Stats about system resources (exact phrases, anchored)
    "كم عدد المبادئ", "كم عدد الأحكام", "كم عدد المواد",
    "كم عدد التشريعات", "كم عدد القوانين", "كم عدد القضايا",
    "كم عدد المجالات", "كم مبدأ عندك", "كم مادة عندك",
    "كم حكم تمييز", "كم حكم عندك", "كم قانون عندك",
    # Identity / self
    "من انت", "من أنت", "عرفني عليك", "عرّفني عليك",
    # Capabilities
    "شنو قدراتك", "وش قدراتك", "ايش قدراتك", "ما قدراتك",
    "شنو تسوي", "ايش تسوي", "وش تسوي",
    "هل تستطيع", "هل تقدر", "تقدر تسوي",
)

# Phrases that DISABLE meta fast-path — content-heavy even if they
# start with "كم". If ANY of these appears in the query, defer to LLM.
_LEGAL_CONTENT_HINTS = (
    "راتب", "اجر", "أجر", "مرتب", "بدل", "علاوة", "تعويض",
    "نفقة", "حضانة", "ميراث", "عقوبة", "غرامة", "رسوم",
    "مدة", "سنة", "يوم", "شهر", "اسبوع",
    "قضية", "دعوى", "موظف", "عامل", "محكمة",
    "درجة سابعة", "درجة أولى", "درجة ثانية", "المجلس",
    "الوزارة", "الهيئة", "الجهاز",
    # Specific numeric-content terms
    "قيمة", "مقدار", "نسبة", "حد", "حدّ",
)

_FAST_COMPLAINT_PATTERNS = (
    "افهم السؤال", "مو كذا", "هذا مو اللي", "اجابتك غلط",
    "جوابك غلط", "غلط", "خطأ", "رد غبي", "جواب غبي",
    "لا تفهم", "ما فهمت السؤال",
)

_FAST_COMMAND_EXACT = frozenset({
    "اختصر", "اختصرها", "اختصرلي", "اعد", "اعد الصياغة",
    "اعد الكتابة", "بدون تفصيل", "باختصار", "اختصر اكثر",
})


def _fast_path_classify(q: str) -> Optional[IntentClassification]:
    """Handle obvious cases without calling LLM."""
    q_lower = q.lower().strip()

    # Casual — single-word emotional expressions
    if q_lower in _FAST_CASUAL:
        r = _INTENT_ROUTING[TurnIntent.CASUAL_SOCIAL]
        return IntentClassification(
            intent        = TurnIntent.CASUAL_SOCIAL,
            confidence    = 0.95,
            route_to      = r["route_to"],
            release_phase = r["release_phase"],
            reset_hard    = r.get("reset_hard", False),
            reasoning     = "fast-path: exact casual phrase",
        )

    # Meta fast-path — DISABLED when the query carries legal content
    # terms (FINDING #20). "كم يبلغ راتب موظف..." must never be
    # classified as meta via the fast-path; defer to the LLM.
    _has_content_hint = any(hint in q_lower for hint in _LEGAL_CONTENT_HINTS)
    if not _has_content_hint:
        for p in _FAST_META_EXACT_PHRASES:
            if p in q_lower:
                r = _INTENT_ROUTING[TurnIntent.META_SYSTEM_QUERY]
                return IntentClassification(
                    intent        = TurnIntent.META_SYSTEM_QUERY,
                    confidence    = 0.9,
                    route_to      = r["route_to"],
                    release_phase = r["release_phase"],
                    reset_hard    = r.get("reset_hard", False),
                    reasoning     = f"fast-path: meta phrase '{p}'",
                )

    # Complaint substring match
    for p in _FAST_COMPLAINT_PATTERNS:
        if p in q_lower:
            r = _INTENT_ROUTING[TurnIntent.COMPLAINT_FEEDBACK]
            return IntentClassification(
                intent        = TurnIntent.COMPLAINT_FEEDBACK,
                confidence    = 0.85,
                route_to      = r["route_to"],
                release_phase = r["release_phase"],
                reset_hard    = r.get("reset_hard", False),
                reasoning     = f"fast-path: complaint pattern '{p}'",
            )

    # Exact command match
    if q_lower in _FAST_COMMAND_EXACT:
        r = _INTENT_ROUTING[TurnIntent.COMMAND]
        return IntentClassification(
            intent        = TurnIntent.COMMAND,
            confidence    = 0.95,
            route_to      = r["route_to"],
            release_phase = r["release_phase"],
            reset_hard    = r.get("reset_hard", False),
            reasoning     = "fast-path: exact command",
        )

    return None


def _prefix_fallback(q: str) -> IntentClassification:
    """Legacy prefix fallback when LLM classifier is unavailable."""
    q_lower = q.lower().strip()
    _LEGAL_Q_PREFIXES = (
        "ما هي عقوبة", "ما عقوبة", "ما هي عقوبات",
        "ما الفرق", "ما الحكم", "كيف ", "هل ",
    )
    if any(q_lower.startswith(p) for p in _LEGAL_Q_PREFIXES):
        r = _INTENT_ROUTING[TurnIntent.NEW_LEGAL_QUESTION]
        return IntentClassification(
            intent        = TurnIntent.NEW_LEGAL_QUESTION,
            confidence    = 0.6,
            route_to      = r["route_to"],
            release_phase = r["release_phase"],
            reasoning     = "fallback: legal-Q prefix match",
        )
    return IntentClassification(intent=TurnIntent.UNCLEAR)


def _to_dict(c: IntentClassification) -> dict:
    return {
        "intent":        c.intent.value,
        "confidence":    c.confidence,
        "route_to":      c.route_to,
        "release_phase": c.release_phase,
        "reset_hard":    c.reset_hard,
        "reasoning":     c.reasoning,
    }


# ═══════════════════════════════════════════════════════════════════
# LLM + cache helpers
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

    if not resp or not isinstance(resp, str) or resp.strip().startswith("خطأ"):
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
        raw = await client.get(f"intent:{key}")
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
            f"intent:{key}",
            json.dumps(value, ensure_ascii=False),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass


__all__ = ["TurnIntent", "IntentClassification", "classify_turn"]
