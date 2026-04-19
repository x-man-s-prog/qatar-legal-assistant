# -*- coding: utf-8 -*-
"""
Deterministic Refusal Engine
=============================
Produces clean, short, context-aware refusal responses for structured queries
when data is not found in the database.

RULES:
- ZERO LLM involvement — every refusal is a deterministic string
- Short and direct — no analysis, no legal memo, no suggestions
- Intent-specific — each intent gets its own refusal template
- Context-aware — if query contains a grade/entity, mention it
- Style-clean — no forbidden markers, no emoji, no long text
"""
import re
import logging
from typing import Optional

log = logging.getLogger("refusal_engine")

# ══════════════════════════════════════════════════════════════
# Structured intent set — queries that MUST NOT reach LLM
# ══════════════════════════════════════════════════════════════

STRUCTURED_INTENTS = frozenset({
    "salary_query", "drug_table", "table_lookup", "enumeration_list",
})

# ══════════════════════════════════════════════════════════════
# Base refusal templates (intent → Arabic text)
# ══════════════════════════════════════════════════════════════

_BASE_REFUSALS = {
    "salary_query":     "لا توجد بيانات دقيقة في النظام لهذه الدرجة حالياً.",
    "drug_table":       "قائمة المواد غير متوفرة حالياً بشكل كامل في النظام.",
    "table_lookup":     "الجدول المطلوب غير متوفر حالياً في قاعدة البيانات.",
    "enumeration_list": "القائمة المطلوبة غير متوفرة حالياً بشكل دقيق.",
}

# Catch-all for any structured intent not explicitly listed
_FALLBACK_REFUSAL = "المعلومات المطلوبة غير متوفرة حالياً في النظام."

# ══════════════════════════════════════════════════════════════
# Grade extraction for context-aware salary refusals
# ══════════════════════════════════════════════════════════════

_GRADE_NAMES = {
    "ممتازة": "الممتازة", "الممتازة": "الممتازة",
    "خاصة": "الخاصة", "الخاصة": "الخاصة",
    "أولى": "الأولى", "الأولى": "الأولى",
    "ثانية": "الثانية", "الثانية": "الثانية",
    "ثالثة": "الثالثة", "الثالثة": "الثالثة",
    "رابعة": "الرابعة", "الرابعة": "الرابعة",
    "خامسة": "الخامسة", "الخامسة": "الخامسة",
    "سادسة": "السادسة", "السادسة": "السادسة",
    "سابعة": "السابعة", "السابعة": "السابعة", "سابعه": "السابعة",
    "ثامنة": "الثامنة", "الثامنة": "الثامنة",
    "تاسعة": "التاسعة", "التاسعة": "التاسعة",
    "عاشرة": "العاشرة", "العاشرة": "العاشرة",
}

# Known valid grades in the system (for hint mode)
_VALID_GRADES = [
    "الممتازة", "الخاصة", "الأولى", "الثانية", "الثالثة",
    "الرابعة", "الخامسة", "السادسة", "السابعة",
]


def _extract_grade_from_query(query: str) -> Optional[str]:
    """Extract grade name from query for context-aware refusal."""
    q = query.strip()
    m = re.search(
        r'(?:الدرجة|درجة)\s*(?:ال)?(ممتازة|الممتازة|خاصة|الخاصة|'
        r'أولى|الأولى|ثانية|الثانية|ثالثة|الثالثة|رابعة|الرابعة|'
        r'خامسة|الخامسة|سادسة|السادسة|سابعة|السابعة|سابعه|'
        r'ثامنة|الثامنة|تاسعة|التاسعة|عاشرة|العاشرة|\d+)',
        q
    )
    if m:
        raw = m.group(1)
        return _GRADE_NAMES.get(raw, raw)
    return None


def _find_nearest_grade(grade: str) -> Optional[str]:
    """Find the nearest valid grade for hint mode. Deterministic, no LLM."""
    if grade in _VALID_GRADES:
        return None  # Already valid, no hint needed
    # For numeric grades beyond range, suggest the last valid one
    if grade and re.match(r"\d+", grade):
        try:
            num = int(grade)
            if num > 7:
                return "السابعة"
            elif num < 1:
                return "الأولى"
        except ValueError:
            pass
    # For named grades not in valid set
    if grade in ("الثامنة", "التاسعة", "العاشرة"):
        return "السابعة"
    return None


# ══════════════════════════════════════════════════════════════
# Main API
# ══════════════════════════════════════════════════════════════

def is_structured_intent(intent: str) -> bool:
    """Check if an intent string belongs to the structured set.
    These intents MUST NEVER be routed to LLM fallback."""
    return intent in STRUCTURED_INTENTS


def generate_refusal(intent: str, query: str = "", enable_hints: bool = True) -> str:
    """
    Generate a deterministic refusal for a structured query.

    Args:
        intent: QueryIntent value string (e.g. "salary_query")
        query: Original user query (for context extraction)
        enable_hints: If True, add nearest-grade hints when applicable

    Returns:
        Clean Arabic refusal string. Always < 200 chars.
        NEVER calls LLM. NEVER returns empty string.
    """
    base = _BASE_REFUSALS.get(intent, _FALLBACK_REFUSAL)

    # ── Context-aware enrichment (no LLM, query parsing only) ──

    if intent == "salary_query" and query:
        grade = _extract_grade_from_query(query)
        if grade:
            # Specific grade mentioned → personalize refusal
            base = f"الدرجة {grade} غير موجودة في جدول الرواتب المتوفر حالياً."

            # Hint mode: suggest nearest valid grade
            if enable_hints:
                nearest = _find_nearest_grade(grade)
                if nearest:
                    base += f"\nأقرب درجة متوفرة: {nearest}."
                    log.info("[REFUSAL_ENGINE] hint: %s → %s", grade, nearest)

    elif intent == "drug_table" and query:
        # Check if asking about a specific substance
        q_lower = query.lower()
        if "جدول" in q_lower and re.search(r"(أول|ثان|ثالث|رابع|خامس)", q_lower):
            base = "الجدول المحدد غير متوفر حالياً في قاعدة البيانات."

    elif intent == "table_lookup" and query:
        # Try to extract table number for personalization
        m = re.search(r"جدول\s*(?:رقم)?\s*(\d+)", query)
        if m:
            base = f"الجدول رقم {m.group(1)} غير متوفر حالياً في قاعدة البيانات."

    elif intent == "enumeration_list" and query:
        # Extract the thing being listed for personalization
        m = re.search(r"(?:اذكر|عدد)\s+(?:لي\s+)?([\u0600-\u06FF\s]{3,20})", query)
        if m:
            entity = m.group(1).strip()
            if len(entity) > 3:
                base = f"قائمة {entity} غير متوفرة حالياً بشكل دقيق."

    # ── Final safety: enforce length and style ──
    result = _enforce_refusal_style(base)

    log.info("[REFUSAL_ENGINE] intent=%s len=%d text='%s'", intent, len(result), result[:80])
    return result


def generate_no_pool_refusal(intent: str, query: str = "") -> str:
    """
    Special refusal when database pool is unavailable.
    Still deterministic, still no LLM.
    """
    result = "قاعدة البيانات غير متصلة حالياً. يرجى المحاولة لاحقاً."
    log.warning("[REFUSAL_ENGINE] NO_POOL intent=%s", intent)
    return _enforce_refusal_style(result)


# ══════════════════════════════════════════════════════════════
# Style enforcement
# ══════════════════════════════════════════════════════════════

_FORBIDDEN_MARKERS = ["📋", "⚖️", "🔍", "✅", "📊"]
_FORBIDDEN_PHRASES = ["بناءً على", "يمكنك مراجعة", "التكييف القانوني:", "السند النظامي:", "التحليل القانوني:"]


def _enforce_refusal_style(text: str) -> str:
    """
    Hard style enforcement on refusal text.
    - No forbidden markers
    - No forbidden phrases
    - Max 200 chars
    - No multi-paragraph
    - No empty result
    """
    # Strip forbidden markers
    for marker in _FORBIDDEN_MARKERS:
        text = text.replace(marker, "")

    # Strip forbidden phrases
    for phrase in _FORBIDDEN_PHRASES:
        text = text.replace(phrase, "")

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Allow up to 2 lines (main refusal + optional hint)
    lines = text.split("\n")
    if len(lines) > 2:
        text = "\n".join(lines[:2])

    # Hard length cap
    if len(text) > 200:
        text = text[:195].rsplit(" ", 1)[0] + "."

    # Never return empty
    if not text.strip():
        text = _FALLBACK_REFUSAL

    return text.strip()


# ══════════════════════════════════════════════════════════════
# Assertion guard — call before returning refusal to client
# ══════════════════════════════════════════════════════════════

def assert_refusal_clean(text: str, intent: str) -> None:
    """
    Hard assertion guard. Raises AssertionError if refusal violates contract.
    Call this before returning ANY refusal to the client.
    """
    assert text and len(text.strip()) > 0, f"[REFUSAL_GUARD] empty refusal for {intent}"
    assert len(text) <= 200, f"[REFUSAL_GUARD] refusal too long ({len(text)} chars) for {intent}"

    for marker in _FORBIDDEN_MARKERS:
        assert marker not in text, f"[REFUSAL_GUARD] forbidden marker '{marker}' in refusal for {intent}"

    for phrase in _FORBIDDEN_PHRASES:
        assert phrase not in text, f"[REFUSAL_GUARD] forbidden phrase '{phrase}' in refusal for {intent}"

    # No paragraphs (max 2 lines for hint mode)
    assert text.count("\n") <= 1, f"[REFUSAL_GUARD] too many lines in refusal for {intent}"

    log.info("[REFUSAL_GUARD] PASS intent=%s len=%d", intent, len(text))
