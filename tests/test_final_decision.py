# -*- coding: utf-8 -*-
"""
Tests for Final Decision Control Layer + Response Cleaner V2
=============================================================
Covers:
- Per-intent validators (salary, drug, table, list)
- Source purity enforcement
- Style validation
- Fallback blocking
- Hard rejection
- Response cleaner
- Streaming cleaner
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.final_decision import (
    validate_final_answer, FinalVerdict,
    _validate_salary, _validate_drug, _validate_table, _validate_list,
    _check_source_purity, _validate_style, HARD_REFUSAL,
)
from core.response_cleaner import clean_response, clean_for_streaming


# ══════════════════════════════════════════════════════════════
# 1. Salary Validation
# ══════════════════════════════════════════════════════════════

class TestSalaryValidation:
    def test_valid_salary_with_grades_and_numbers(self):
        text = "الدرجة السابعة: 25,000 ريال\nالدرجة السادسة: 30,000 ريال"
        ok, reason = _validate_salary(text)
        assert ok, f"Should pass: {reason}"

    def test_salary_no_numbers_rejected(self):
        text = "الدرجة السابعة لها راتب محدد حسب النظام"
        ok, reason = _validate_salary(text)
        assert not ok
        assert "salary_no_data" in reason

    def test_salary_with_some_data_but_generic(self):
        text = "يختلف الراتب حسب الجهة الحكومية والمؤهل. الدرجة الأولى 50,000"
        ok, reason = _validate_salary(text)
        # Has 1 grade + 1 number (passes has_data) but has generic signal with <2 numbers
        assert not ok
        assert "salary_generic" in reason

    def test_salary_pure_generic_rejected(self):
        text = "يختلف الراتب حسب الجهة والقطاع. يرجى مراجعة جهة العمل."
        ok, reason = _validate_salary(text)
        assert not ok
        assert "salary" in reason


# ══════════════════════════════════════════════════════════════
# 2. Drug Validation
# ══════════════════════════════════════════════════════════════

class TestDrugValidation:
    def test_valid_drug_english_names(self):
        text = "1- MORPHINE\n2- COCAINE\n3- HEROIN\n4- CANNABIS"
        ok, reason = _validate_drug(text)
        assert ok

    def test_valid_drug_arabic_names(self):
        text = "تشمل مورفين وكوكايين وهيروين"
        ok, reason = _validate_drug(text)
        assert ok

    def test_valid_drug_numbered_items(self):
        text = "1- مادة كيميائية أولى\n2- مادة كيميائية ثانية\n3- مادة كيميائية ثالثة\n4- مادة رابعة"
        ok, reason = _validate_drug(text)
        assert ok

    def test_drug_no_substances_rejected(self):
        text = "قانون مكافحة المخدرات يعاقب بالسجن. العقوبة تشمل الغرامة."
        ok, reason = _validate_drug(text)
        assert not ok
        assert "drug_no_substances" in reason

    def test_drug_amendment_only_rejected(self):
        text = "المعدل بموجب القانون رقم 5. استبدال الفقرة الأولى. يعدل نص المادة."
        ok, reason = _validate_drug(text)
        assert not ok
        # No actual substance names → rejected as no_substances (before amendment check)
        assert "drug_no_substances" in reason


# ══════════════════════════════════════════════════════════════
# 3. Table Validation
# ══════════════════════════════════════════════════════════════

class TestTableValidation:
    def test_valid_table_with_rows(self):
        text = "1- البند الأول: معدات\n2- البند الثاني: مواد خام\n3- البند الثالث: خدمات"
        ok, reason = _validate_table(text)
        assert ok

    def test_valid_table_with_pipe(self):
        text = "الاسم | القيمة | الوصف\nأولاً | 100 | بند أول"
        ok, reason = _validate_table(text)
        assert ok

    def test_table_no_rows_rejected(self):
        text = "الجدول يحتوي على معلومات مهمة حول الموضوع."
        ok, reason = _validate_table(text)
        assert not ok
        assert "table_no_rows" in reason


# ══════════════════════════════════════════════════════════════
# 4. List Validation
# ══════════════════════════════════════════════════════════════

class TestListValidation:
    def test_valid_numbered_list(self):
        text = "1. مورفين\n2. كوكايين\n3. هيروين"
        ok, reason = _validate_list(text)
        assert ok

    def test_valid_bulleted_list(self):
        text = "• مادة أولى\n• مادة ثانية\n• مادة ثالثة"
        ok, reason = _validate_list(text)
        assert ok

    def test_list_no_items_rejected(self):
        text = "المواد المحظورة كثيرة ومتنوعة حسب القانون."
        ok, reason = _validate_list(text)
        assert not ok
        assert "list_no_items" in reason


# ══════════════════════════════════════════════════════════════
# 5. Source Purity
# ══════════════════════════════════════════════════════════════

class TestSourcePurity:
    def test_salary_from_salary_table_ok(self):
        ok, _ = _check_source_purity("salary_query", ["salary_table"])
        assert ok

    def test_salary_from_statute_text_rejected(self):
        ok, reason = _check_source_purity("salary_query", ["salary_table", "statute_text"])
        assert not ok
        assert "source_mixing" in reason

    def test_drug_from_statute_table_ok(self):
        ok, _ = _check_source_purity("drug_table", ["statute_table"])
        assert ok

    def test_general_legal_any_source_ok(self):
        ok, _ = _check_source_purity("general_legal", ["statute_text", "judgment"])
        assert ok

    def test_empty_sources_passes(self):
        ok, _ = _check_source_purity("salary_query", [])
        assert ok


# ══════════════════════════════════════════════════════════════
# 6. Style Validation
# ══════════════════════════════════════════════════════════════

class TestStyleValidation:
    def test_direct_answer_with_memo_gets_cleaned(self):
        answer = "📋 التكييف: جنائي\n⚖️ السند: المادة 5\n🔍 التحليل: تحليل\n✅ التوصية: توصية\n📊 الثقة: 90%"
        ok, reason, cleaned = _validate_style(answer, "direct_short")
        assert ok
        assert "📋 التكييف" not in cleaned
        assert "📊 الثقة" not in cleaned

    def test_analysis_mode_untouched(self):
        answer = "📋 التكييف: جنائي\n⚖️ السند: المادة 5"
        ok, reason, cleaned = _validate_style(answer, "legal_analysis")
        assert ok
        assert cleaned == answer


# ══════════════════════════════════════════════════════════════
# 7. Fallback Blocking
# ══════════════════════════════════════════════════════════════

class TestFallbackBlocking:
    def test_generic_fallback_blocked_for_salary(self):
        verdict = validate_final_answer(
            answer="لا تتوفر لدي معلومات كافية عن الرواتب.",
            intent="salary_query",
        )
        assert not verdict.accepted
        # Rejected at intent validation (no grades/nums) before fallback check
        assert "salary" in verdict.rejection_reason

    def test_generic_fallback_blocked_for_drug(self):
        verdict = validate_final_answer(
            answer="ليس لدي بيانات محددة عن المخدرات.",
            intent="drug_table",
        )
        assert not verdict.accepted

    def test_real_data_not_blocked(self):
        verdict = validate_final_answer(
            answer="الدرجة السابعة: 25,000 ريال\nالدرجة السادسة: 30,000",
            intent="salary_query",
        )
        assert verdict.accepted


# ══════════════════════════════════════════════════════════════
# 8. Hard Rejection
# ══════════════════════════════════════════════════════════════

class TestHardRejection:
    def test_empty_answer_rejected(self):
        verdict = validate_final_answer(answer="", intent="salary_query")
        assert not verdict.accepted
        assert verdict.refusal == HARD_REFUSAL

    def test_whitespace_answer_rejected(self):
        verdict = validate_final_answer(answer="   \n  ", intent="salary_query")
        assert not verdict.accepted

    def test_salary_no_data_gets_specific_refusal(self):
        verdict = validate_final_answer(
            answer="الراتب يعتمد على عدة عوامل.",
            intent="salary_query",
        )
        assert not verdict.accepted
        assert "الراتب" in verdict.refusal or "بوابة الميزان" in verdict.refusal


# ══════════════════════════════════════════════════════════════
# 9. Lookup Data Priority
# ══════════════════════════════════════════════════════════════

class TestLookupPriority:
    def test_lookup_data_overrides_llm(self):
        verdict = validate_final_answer(
            answer="some generic LLM output",
            intent="salary_query",
            lookup_data="📋 جدول الدرجات والرواتب — من قانون الموارد البشرية:\nالدرجة السابعة: 25,000",
        )
        assert verdict.accepted
        assert "جدول الدرجات" in verdict.answer
        assert verdict.source_used == "structured_lookup"

    def test_no_lookup_uses_llm(self):
        verdict = validate_final_answer(
            answer="الدرجة السابعة: 25,000 ريال\nالدرجة السادسة: 30,000",
            intent="salary_query",
            lookup_data="",
        )
        assert verdict.accepted
        assert "25,000" in verdict.answer


# ══════════════════════════════════════════════════════════════
# 10. Response Cleaner V2
# ══════════════════════════════════════════════════════════════

class TestResponseCleaner:
    def test_strips_memo_headers_for_direct(self):
        answer = "📋 التكييف القانوني: جنائي\n⚖️ السند النظامي: المادة 5\nالإجابة هنا"
        cleaned = clean_response(answer, answer_mode="direct_short")
        assert "التكييف القانوني" not in cleaned
        assert "السند النظامي" not in cleaned
        assert "الإجابة هنا" in cleaned

    def test_keeps_memo_for_analysis(self):
        answer = "📋 التكييف: جنائي\n⚖️ السند: المادة 5"
        cleaned = clean_response(answer, answer_mode="legal_analysis")
        assert "التكييف" in cleaned

    def test_strips_confidence_always(self):
        answer = "الإجابة هنا.\n📊 الثقة: 85%"
        cleaned = clean_response(answer, answer_mode="legal_analysis")
        assert "85%" not in cleaned
        assert "الإجابة هنا" in cleaned

    def test_strips_filler_openings(self):
        answer = "بناءً على النصوص القانونية المتوفرة، يحق للموظف المطالبة"
        cleaned = clean_response(answer, answer_mode="direct_short")
        assert not cleaned.startswith("بناءً على")
        assert "المطالبة" in cleaned

    def test_compresses_whitespace(self):
        answer = "سطر أول\n\n\n\n\nسطر ثاني"
        cleaned = clean_response(answer)
        assert "\n\n\n" not in cleaned

    def test_empty_answer_passes_through(self):
        assert clean_response("") == ""
        assert clean_response("   ") == "   "

    def test_direct_strips_standalone_emojis(self):
        answer = "الإجابة\n📋\nتفاصيل"
        cleaned = clean_response(answer, answer_mode="direct_short")
        assert "\n📋\n" not in cleaned


# ══════════════════════════════════════════════════════════════
# 11. Streaming Cleaner
# ══════════════════════════════════════════════════════════════

class TestStreamingCleaner:
    def test_strips_memo_for_direct(self):
        chunk = "📋 التكييف: "
        result = clean_for_streaming(chunk, answer_mode="direct_short")
        assert result is None or "التكييف" not in (result or "")

    def test_keeps_content_for_analysis(self):
        chunk = "📋 التكييف: جنائي"
        result = clean_for_streaming(chunk, answer_mode="legal_analysis")
        assert result is not None
        assert "التكييف" in result

    def test_strips_confidence_inline(self):
        chunk = "📊 الثقة: 90%"
        result = clean_for_streaming(chunk, answer_mode="direct_short")
        assert result is None or "90%" not in (result or "")

    def test_empty_chunk(self):
        assert clean_for_streaming("") == ""
        assert clean_for_streaming(None) is None


# ══════════════════════════════════════════════════════════════
# 12. Integration — validate_final_answer end-to-end
# ══════════════════════════════════════════════════════════════

class TestEndToEnd:
    def test_general_legal_passes_normally(self):
        verdict = validate_final_answer(
            answer="عقوبة السرقة في القانون القطري هي السجن.",
            intent="general_legal",
            answer_mode="direct_short",
        )
        assert verdict.accepted

    def test_salary_with_real_data_passes(self):
        verdict = validate_final_answer(
            answer="الدرجة الأولى: المربوط 50,000 ريال\nالدرجة الثانية: المربوط 45,000 ريال",
            intent="salary_query",
            answer_mode="table_row",
        )
        assert verdict.accepted

    def test_drug_with_names_passes(self):
        verdict = validate_final_answer(
            answer="1- MORPHINE\n2- COCAINE\n3- HEROIN",
            intent="drug_table",
            answer_mode="structured_list",
        )
        assert verdict.accepted

    def test_salary_garbage_rejected(self):
        verdict = validate_final_answer(
            answer="القانون ينظم الخدمة المدنية في الدولة.",
            intent="salary_query",
        )
        assert not verdict.accepted

    def test_source_mixing_rejected(self):
        verdict = validate_final_answer(
            answer="الدرجة السابعة: 25,000 ريال",
            intent="salary_query",
            source_types=["salary_table", "judgment"],
        )
        assert not verdict.accepted
        assert "source_mixing" in verdict.rejection_reason
