# -*- coding: utf-8 -*-
"""
Final Decision Control Layer
=============================
Last gate before any answer reaches the user.

1. Validate: does the LLM answer match query intent + expected structure?
2. Enforce: per-intent MUST-contain / MUST-NOT-contain rules
3. Build:   for structured intents, build answer from data — not raw chunks
4. Reject:  if validation fails, return hard refusal — never partial garbage

Usage (both JSON and streaming paths):
    from core.final_decision import validate_final_answer, FinalVerdict

    verdict = validate_final_answer(
        answer=llm_output,
        query=original_query,
        intent=lookup_intent,       # from structured_lookup.classify_query
        answer_mode=answer_mode,    # from answer_mode.classify_answer_mode
        source_types=used_sources,  # list of source_type strings
    )
    if verdict.accepted:
        return verdict.answer       # possibly cleaned
    else:
        return verdict.refusal      # hard refusal text
"""
import re, logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("final_decision")


# ══════════════════════════════════════════════════════════════
# Verdict — immutable output of the validation pipeline
# ══════════════════════════════════════════════════════════════

@dataclass
class FinalVerdict:
    accepted: bool
    answer: str                         # cleaned answer (if accepted)
    refusal: str = ""                   # refusal text (if rejected)
    rejection_reason: str = ""          # internal log tag
    source_used: str = ""               # which source_type was actually used
    confidence_adjustment: int = 0      # ±N to add to confidence score


# ══════════════════════════════════════════════════════════════
# Hard refusal — one standard message for rejected answers
# ══════════════════════════════════════════════════════════════

HARD_REFUSAL = "لا توجد بيانات دقيقة في النظام للإجابة على هذا السؤال بشكل موثوق. أنصحك بمراجعة بوابة الميزان (almeezan.qa)."

_INTENT_REFUSALS = {
    "salary_query": (
        "⚠️ لم أتمكن من استخراج بيانات الراتب المطلوبة بدقة. "
        "أنصحك بمراجعة جدول الدرجات والرواتب على بوابة الميزان (almeezan.qa)."
    ),
    "drug_table": (
        "⚠️ لم أتمكن من استخراج أسماء المواد المخدرة بدقة. "
        "أنصحك بمراجعة الجداول الملحقة بقانون المخدرات على بوابة الميزان."
    ),
    "table_lookup": (
        "⚠️ لم أتمكن من استخراج محتوى الجدول المطلوب بدقة. "
        "أنصحك بمراجعة الملحقات الرسمية على بوابة الميزان (almeezan.qa)."
    ),
    "enumeration_list": (
        "⚠️ لم أتمكن من استخراج القائمة المطلوبة بدقة. "
        "أنصحك بمراجعة الجداول الرسمية على بوابة الميزان."
    ),
}


# ══════════════════════════════════════════════════════════════
# Per-Intent Validators — MUST / MUST-NOT rules
# ══════════════════════════════════════════════════════════════

def _validate_salary(answer: str) -> tuple[bool, str]:
    """SALARY: MUST have grade names + numbers. MUST NOT be generic HR explanation."""
    # MUST contain
    grade_words = re.findall(
        r"(?:الدرجة|درجة|الممتازة|الخاصة|الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة)",
        answer
    )
    salary_nums = re.findall(r"\d{2,3},\d{3}|\d{4,6}", answer)
    has_data = len(grade_words) >= 1 and len(salary_nums) >= 1

    if not has_data:
        return False, "salary_no_data: grades=%d nums=%d" % (len(grade_words), len(salary_nums))

    # MUST NOT: generic HR explanation without numbers
    generic_signals = [
        "يختلف الراتب حسب", "يتم تحديد الراتب", "الرواتب تعتمد على",
        "لا يمكنني تحديد الراتب", "الراتب يعتمد على عدة عوامل",
        "يرجى مراجعة جهة العمل",
    ]
    is_generic = any(s in answer for s in generic_signals) and len(salary_nums) < 2
    if is_generic:
        return False, "salary_generic_explanation"

    return True, ""


def _validate_drug(answer: str) -> tuple[bool, str]:
    """DRUG: MUST have substance names. MUST NOT be amendment-only."""
    has_english = bool(re.search(r"[A-Z]{3,}", answer))
    has_arabic_substances = any(s in answer for s in [
        "مورفين", "كوكايين", "حشيش", "هيروين", "أفيون", "أمفيتامين",
        "كودايين", "ميثادون", "ترامادول", "اسيتورفين",
    ])
    has_numbered_items = len(re.findall(r"\d+\s*[\-ـ\.]\s*[^\d\n]{4,}", answer)) >= 3

    if not (has_english or has_arabic_substances or has_numbered_items):
        return False, "drug_no_substances"

    # MUST NOT: amendment-only text
    amendment_signals = ["المعدل بموجب", "استبدال الفقرة", "يعدل نص المادة"]
    is_amendment = sum(1 for s in amendment_signals if s in answer) >= 2
    if is_amendment and not (has_english or has_arabic_substances):
        return False, "drug_amendment_only"

    return True, ""


def _validate_table(answer: str) -> tuple[bool, str]:
    """TABLE: MUST have rows/items. MUST NOT be reference-only."""
    has_rows = len(re.findall(r"\d+[\s\-\.ـ]+[^\d\n]{4,}", answer)) >= 2
    has_pipe = "|" in answer
    has_structured = has_rows or has_pipe

    if not has_structured:
        return False, "table_no_rows"

    # MUST NOT: reference-only text
    ref_signals = ["وفقاً للجدول", "وفقًا للجدول", "كما هو موضح في الجدول",
                    "حسب الجدول المرفق", "الجدول الملحق"]
    ref_count = sum(1 for s in ref_signals if s in answer)
    if ref_count >= 2 and not has_pipe and not has_rows:
        return False, "table_reference_only"

    return True, ""


def _validate_list(answer: str) -> tuple[bool, str]:
    """ENUMERATION_LIST: MUST have numbered/bulleted items."""
    numbered = re.findall(r"^\s*\d+[\.\-\)ـ]\s*.{4,}", answer, re.MULTILINE)
    bulleted = re.findall(r"^\s*[-•●▪]\s*.{4,}", answer, re.MULTILINE)

    if len(numbered) < 2 and len(bulleted) < 2:
        return False, "list_no_items"

    return True, ""


# ══════════════════════════════════════════════════════════════
# Single Source Rule — reject mixed sources
# ══════════════════════════════════════════════════════════════

_ALLOWED_SOURCES = {
    "salary_query": {"salary_table", "statute_table"},
    "drug_table": {"statute_table"},
    "table_lookup": {"statute_table", "appendix", "schedule"},
    "enumeration_list": {"statute_table", "appendix", "schedule"},
}

def _check_source_purity(intent: str, source_types: list) -> tuple[bool, str]:
    """Ensure answer only uses allowed source types for this intent."""
    if not source_types or intent not in _ALLOWED_SOURCES:
        return True, ""  # can't validate, pass through

    allowed = _ALLOWED_SOURCES[intent]
    violations = [s for s in source_types if s and s not in allowed]

    if violations:
        return False, "source_mixing: allowed=%s got=%s" % (allowed, violations)

    return True, ""


# ══════════════════════════════════════════════════════════════
# Style Validation — answer mode compliance
# ══════════════════════════════════════════════════════════════

_MEMO_MARKERS = ["📋 التكييف", "⚖️ السند", "🔍 التحليل", "✅ التوصية", "📊 الثقة"]

def _validate_style(answer: str, answer_mode: str) -> tuple[bool, str, str]:
    """Check answer matches expected style. Returns (ok, reason, cleaned_answer)."""
    cleaned = answer

    if answer_mode in ("direct_short", "followup_short"):
        # Should NOT have memo structure
        memo_count = sum(1 for m in _MEMO_MARKERS if m in answer)
        if memo_count >= 3:
            # Strip memo markers instead of rejecting
            for m in _MEMO_MARKERS:
                cleaned = cleaned.replace(m, "")
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            log.info("[FINAL_VALIDATE] stripped %d memo markers from direct answer", memo_count)
            return True, "style_cleaned", cleaned

        # Should be short — warn if very long but don't reject
        word_count = len(answer.split())
        if word_count > 200:
            log.warning("[FINAL_VALIDATE] direct answer too long: %d words", word_count)

    elif answer_mode == "structured_list":
        # Should have numbered items
        numbered = re.findall(r"^\s*\d+[\.\-\)ـ]", answer, re.MULTILINE)
        if len(numbered) < 2:
            log.warning("[FINAL_VALIDATE] list answer lacks numbered items")

    elif answer_mode == "table_row":
        # Should have data rows, not paragraphs
        pass  # Handled by per-intent validators above

    return True, "", cleaned


# ══════════════════════════════════════════════════════════════
# Legacy builders REMOVED — all structured answers now built by
# core/answer_builder.py (deterministic, no 📋 headers)
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# Main Entry Point — validate_final_answer
# ══════════════════════════════════════════════════════════════

def validate_final_answer(
    answer: str,
    query: str = "",
    intent: str = "",
    answer_mode: str = "",
    source_types: list = None,
    lookup_data: str = "",
) -> FinalVerdict:
    """
    Final gate. Validates the LLM answer against intent, structure, source rules.

    If lookup_data is provided (from structured_lookup), it takes absolute priority
    over the LLM answer for structured intents.

    Returns FinalVerdict with accepted=True/False.
    """
    if not answer or not answer.strip():
        log.info("[FINAL_REJECT] empty answer")
        return FinalVerdict(
            accepted=False, answer="", refusal=HARD_REFUSAL,
            rejection_reason="empty_answer",
        )

    source_types = source_types or []

    # ── STEP 0: If structured lookup already resolved this, prefer it ──
    if lookup_data and intent in ("salary_query", "drug_table", "table_lookup", "enumeration_list"):
        log.info("[FINAL_ACCEPT] using structured lookup data for intent=%s", intent)
        return FinalVerdict(
            accepted=True, answer=lookup_data,
            source_used="structured_lookup",
            confidence_adjustment=5,
        )

    # ── STEP 1: Per-intent content validation ──
    intent_ok = True
    intent_reason = ""

    if intent == "salary_query":
        intent_ok, intent_reason = _validate_salary(answer)
    elif intent == "drug_table":
        intent_ok, intent_reason = _validate_drug(answer)
    elif intent == "table_lookup":
        intent_ok, intent_reason = _validate_table(answer)
    elif intent == "enumeration_list":
        intent_ok, intent_reason = _validate_list(answer)
    # general_legal and article_lookup: no strict content validation

    if not intent_ok:
        refusal = _INTENT_REFUSALS.get(intent, HARD_REFUSAL)
        log.warning("[FINAL_REJECT] intent=%s reason=%s", intent, intent_reason)
        return FinalVerdict(
            accepted=False, answer=answer, refusal=refusal,
            rejection_reason=intent_reason,
            confidence_adjustment=-20,
        )

    # ── STEP 2: Source purity check ──
    source_ok, source_reason = _check_source_purity(intent, source_types)
    if not source_ok:
        log.warning("[FINAL_REJECT] source violation: %s", source_reason)
        refusal = _INTENT_REFUSALS.get(intent, HARD_REFUSAL)
        return FinalVerdict(
            accepted=False, answer=answer, refusal=refusal,
            rejection_reason=source_reason,
            confidence_adjustment=-15,
        )

    # ── STEP 3: Style validation ──
    style_ok, style_reason, cleaned = _validate_style(answer, answer_mode)
    if not style_ok:
        log.warning("[FINAL_REJECT] style violation: %s", style_reason)
        return FinalVerdict(
            accepted=False, answer=answer, refusal=HARD_REFUSAL,
            rejection_reason=style_reason,
        )

    # ── STEP 4: Fallback blocking ──
    # If this is a structured intent and the answer is just generic explanation
    if intent in ("salary_query", "drug_table", "table_lookup", "enumeration_list"):
        generic_fallbacks = [
            "لا تتوفر لدي معلومات كافية",
            "لا أستطيع الإجابة بدقة",
            "ليس لدي بيانات محددة",
            "يرجى مراجعة المصادر الرسمية",
            "لم أعثر على",
        ]
        is_fallback = any(f in answer for f in generic_fallbacks) and len(answer.split()) < 50
        if is_fallback:
            refusal = _INTENT_REFUSALS.get(intent, HARD_REFUSAL)
            log.info("[FINAL_REJECT] generic fallback blocked for intent=%s", intent)
            return FinalVerdict(
                accepted=False, answer=answer, refusal=refusal,
                rejection_reason="generic_fallback_blocked",
                confidence_adjustment=-10,
            )

    # ── All checks passed ──
    source = "structured_lookup" if lookup_data else ("mixed" if len(set(source_types)) > 1 else (source_types[0] if source_types else "llm"))
    log.info("[FINAL_ACCEPT] intent=%s mode=%s source=%s", intent, answer_mode, source)
    return FinalVerdict(
        accepted=True,
        answer=cleaned if cleaned != answer else answer,
        source_used=source,
    )
