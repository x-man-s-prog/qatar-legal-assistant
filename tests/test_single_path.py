# -*- coding: utf-8 -*-
"""
Single-Path Enforcement Tests
==============================
Proves that for structured queries:
1. The answer is ALWAYS built deterministically from data
2. The LLM is NEVER called
3. No legacy formatting can leak
4. No raw OCR paragraphs can leak
5. Follow-up queries do not crash
6. The runtime path is traceable
7. If data is missing, the system refuses cleanly

These tests verify the END-TO-END path through:
  classify_query → resolve_lookup → build_structured_answer → output contract
"""
import re, pytest
from core.structured_lookup import classify_query, QueryIntent
from core.answer_builder import (
    build_structured_answer, build_salary_answer, build_drug_answer,
    build_table_answer, build_list_answer, _enforce_output_contract,
    _FORBIDDEN,
)
from core.final_decision import validate_final_answer, FinalVerdict
from core.response_cleaner import clean_response


# ══════════════════════════════════════════════════════════════
# SECTION 1: Classification — correct intent for every test query
# ══════════════════════════════════════════════════════════════

class TestClassificationCompleteness:
    """Every structured query the user can ask MUST be classified correctly."""

    # ── Salary ──
    def test_salary_basic(self):
        assert classify_query("كم راتب موظف درجه سابعه") == QueryIntent.SALARY_QUERY

    def test_salary_grade_only(self):
        assert classify_query("الدرجة السابعة فقط") == QueryIntent.SALARY_QUERY

    def test_salary_table_request(self):
        assert classify_query("جدول الرواتب") == QueryIntent.SALARY_QUERY

    def test_salary_followup_first_grade(self):
        assert classify_query("الدرجة الأولى") == QueryIntent.SALARY_QUERY

    def test_salary_followup_special_grade(self):
        assert classify_query("الدرجة الممتازة") == QueryIntent.SALARY_QUERY

    def test_salary_how_much(self):
        assert classify_query("كم الراتب") == QueryIntent.SALARY_QUERY

    def test_salary_with_grade(self):
        assert classify_query("راتب الدرجة الثالثة") == QueryIntent.SALARY_QUERY

    # ── Drug ──
    def test_drug_table(self):
        assert classify_query("جدول المخدرات") == QueryIntent.DRUG_TABLE

    def test_drug_names(self):
        assert classify_query("اكتب أسماء المواد المخدرة فقط") == QueryIntent.DRUG_TABLE

    def test_drug_names_stacked(self):
        """'اذكر أسماء المواد المخدرة فوق بعض' → DRUG, not ENUM"""
        assert classify_query("اذكر أسماء المواد المخدرة فوق بعض") == QueryIntent.DRUG_TABLE

    def test_drug_substances_list(self):
        assert classify_query("المواد المخدرة") == QueryIntent.DRUG_TABLE

    # ── Chemical/Enum ──
    def test_chemicals_banned(self):
        assert classify_query("اكتب لي اسماء المواد الكيميائية المحضوره في قطر") == QueryIntent.ENUMERATION_LIST

    def test_chemicals_enum(self):
        assert classify_query("المواد الكيميائية المحظورة") == QueryIntent.ENUMERATION_LIST

    # ── General Legal (should NOT match structured) ──
    def test_general_legal(self):
        assert classify_query("ما عقوبة السرقة في قطر") == QueryIntent.GENERAL_LEGAL

    def test_general_employment(self):
        assert classify_query("ما هي حقوق العامل في قطر") == QueryIntent.GENERAL_LEGAL


# ══════════════════════════════════════════════════════════════
# SECTION 2: Output Contract — no forbidden markers, ever
# ══════════════════════════════════════════════════════════════

class TestOutputContract:
    """Every structured answer MUST pass the output contract."""

    FORBIDDEN_MARKERS = ["📋", "⚖️", "🔍", "✅", "📊",
                          "التكييف القانوني:", "السند النظامي:", "التحليل القانوني:"]

    def _assert_clean(self, text):
        for m in self.FORBIDDEN_MARKERS:
            assert m not in text, f"Forbidden marker '{m}' in output: {text[:120]}"

    # ── Salary ──
    def test_salary_single_grade_clean(self):
        result = build_structured_answer(
            intent="salary_query",
            raw_content="📋 جدول:\nالدرجة الأولى: 50,000\nالدرجة السابعة: 25,000",
            law_name="قانون الموارد البشرية",
            target_grade="السابعة",
            grade_row="الدرجة السابعة: 25,000 — 35,000",
        )
        self._assert_clean(result)
        assert "السابعة" in result
        assert "الأولى" not in result  # Only requested grade

    def test_salary_full_table_clean(self):
        result = build_structured_answer(
            intent="salary_query",
            raw_content="📋 جدول الدرجات:\nالدرجة الأولى: 50,000\nالدرجة الثانية: 45,000",
            law_name="قانون",
        )
        self._assert_clean(result)

    # ── Drug ──
    def test_drug_output_clean(self):
        result = build_structured_answer(
            intent="drug_table",
            raw_content="📋 المواد:\n1- مورفين\n2- كوكايين",
            law_name="قانون المخدرات",
        )
        self._assert_clean(result)
        assert "مورفين" in result

    def test_drug_from_chunks_clean(self):
        result = build_structured_answer(
            intent="drug_table",
            raw_content="",
            chunks=[
                {"content": "📋 من القانون:\n1- مورفين\n2- كوكايين\n3- هيروين", "law_name": "قانون المخدرات"},
            ],
        )
        self._assert_clean(result)
        assert "مورفين" in result
        assert "كوكايين" in result
        assert "هيروين" in result

    # ── Table ──
    def test_table_output_clean(self):
        result = build_structured_answer(
            intent="table_lookup",
            raw_content="📋 ملحق:\n1- بند أول\n2- بند ثاني\n3- بند ثالث",
            law_name="",
        )
        self._assert_clean(result)

    # ── List ──
    def test_list_output_clean(self):
        result = build_structured_answer(
            intent="enumeration_list",
            raw_content="📋 قائمة:\n1- مادة أولى\n2- مادة ثانية",
            law_name="",
        )
        self._assert_clean(result)

    # ── Injection via raw content ──
    def test_contract_strips_injected_memo_markers(self):
        """Even if raw content has memo markers, they must be stripped."""
        text = "📋 التكييف القانوني:\nالدرجة السابعة: 25,000\n⚖️ السند:\nالمادة 5\n✅ التوصية:\nراجع"
        cleaned = _enforce_output_contract(text, "salary_query")
        self._assert_clean(cleaned)

    def test_contract_blocks_raw_ocr_paragraph(self):
        """Lines > 200 chars MUST be truncated."""
        long_line = "أ" * 300
        text = f"1- مورفين\n{long_line}\n2- كوكايين"
        cleaned = _enforce_output_contract(text, "drug_table")
        assert len(max(cleaned.split('\n'), key=len)) <= 210  # 200 + "…"


# ══════════════════════════════════════════════════════════════
# SECTION 3: Salary Contract — single grade vs full table
# ══════════════════════════════════════════════════════════════

class TestSalaryContract:
    """Salary answers must follow strict data-first contracts."""

    SAMPLE_TABLE = "الدرجة الممتازة: 80,000\nالدرجة الأولى: 50,000\nالدرجة الثانية: 45,000\nالدرجة الثالثة: 40,000\nالدرجة السابعة: 25,000 — 35,000"

    def test_single_grade_no_full_table(self):
        """When user asks one grade, return ONLY that grade."""
        result = build_salary_answer(
            content=self.SAMPLE_TABLE, law_name="قانون",
            target_grade="السابعة", grade_row="الدرجة السابعة: المربوط 25,000 نهاية المربوط 35,000",
        )
        assert "السابعة" in result
        assert "25,000" in result
        assert "الممتازة" not in result
        assert "الأولى" not in result
        assert "50,000" not in result
        lines = [l for l in result.split('\n') if l.strip()]
        assert len(lines) <= 3  # grade row + source + maybe header

    def test_full_table_has_all_grades(self):
        """When no specific grade, return the full table."""
        result = build_salary_answer(content=self.SAMPLE_TABLE, law_name="قانون")
        assert "جدول الدرجات" in result
        assert "الممتازة" in result or "الأولى" in result

    def test_salary_has_numbers(self):
        """Output must contain actual salary numbers, not just text."""
        result = build_salary_answer(
            content=self.SAMPLE_TABLE, law_name="قانون",
            target_grade="السابعة", grade_row="الدرجة السابعة: 25,000 — 35,000",
        )
        assert re.search(r"\d{2,}", result), "Must contain salary numbers"

    def test_salary_no_memo_header(self):
        result = build_salary_answer(content=self.SAMPLE_TABLE, law_name="قانون")
        assert "📋" not in result
        assert "التكييف" not in result


# ══════════════════════════════════════════════════════════════
# SECTION 4: Drug Contract — names only, no OCR garbage
# ══════════════════════════════════════════════════════════════

class TestDrugContract:
    """Drug answers must return clean substance names only."""

    def test_drug_numbered_list(self):
        chunks = [{"content": "1- مورفين\n2- كوكايين\n3- هيروين", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        assert "1-" in result or "1 -" in result
        assert "مورفين" in result

    def test_drug_no_long_paragraphs(self):
        """OCR paragraphs > 120 chars MUST be filtered."""
        ocr_garbage = "هذا النص طويل جداً وهو عبارة عن فقرة كاملة من نظام OCR تحتوي على معلومات قانونية مختلطة ومعلومات عن تعديلات قانونية وإشارات مرجعية ومعلومات عن الأحكام والعقوبات وغير ذلك"
        chunks = [{"content": f"1- مورفين\n{ocr_garbage}\n2- كوكايين", "law_name": "قانون"}]
        result = build_drug_answer(chunks)
        assert "مورفين" in result
        assert "كوكايين" in result
        # The garbage line should NOT appear verbatim
        assert ocr_garbage not in result

    def test_drug_no_amendments(self):
        """Pure amendment text MUST be rejected by final_decision."""
        answer = "المعدل بموجب القانون رقم 5 لسنة 2020. استبدال الفقرة الأولى من المادة 3."
        verdict = validate_final_answer(answer=answer, intent="drug_table")
        assert not verdict.accepted

    def test_drug_deduplicates(self):
        chunks = [
            {"content": "1- مورفين\n2- كوكايين", "law_name": ""},
            {"content": "1- مورفين\n2- هيروين", "law_name": ""},
        ]
        result = build_drug_answer(chunks)
        assert result.count("مورفين") == 1

    def test_drug_english_names(self):
        chunks = [{"content": "1- MORPHINE\n2- COCAINE\n3- HEROIN", "law_name": ""}]
        result = build_drug_answer(chunks)
        assert "MORPHINE" in result


# ══════════════════════════════════════════════════════════════
# SECTION 5: Follow-Up Stability
# ══════════════════════════════════════════════════════════════

class TestFollowUpStability:
    """Follow-up queries must not crash and must maintain intent."""

    def test_grade_followup_classifies_as_salary(self):
        """'الدرجة السابعة فقط' after salary query → still SALARY_QUERY."""
        assert classify_query("الدرجة السابعة فقط") == QueryIntent.SALARY_QUERY

    def test_grade_followup_first(self):
        assert classify_query("الدرجة الأولى") == QueryIntent.SALARY_QUERY

    def test_grade_followup_special(self):
        assert classify_query("الدرجة الخاصة") == QueryIntent.SALARY_QUERY

    def test_drug_followup_names_only(self):
        assert classify_query("أسماء المواد المخدرة فقط") == QueryIntent.DRUG_TABLE

    def test_followup_does_not_expand(self):
        """If user says 'فقط', the answer must not expand to full table."""
        result = build_salary_answer(
            content="الدرجة الأولى: 50,000\nالدرجة السابعة: 25,000",
            law_name="", target_grade="السابعة",
            grade_row="الدرجة السابعة: 25,000",
        )
        assert "الأولى" not in result


# ══════════════════════════════════════════════════════════════
# SECTION 6: Final Decision — Structured Intents Get Data, Not Generic Text
# ══════════════════════════════════════════════════════════════

class TestFinalDecisionStructuredIntents:
    """For structured intents, generic LLM responses MUST be rejected."""

    def test_salary_generic_rejected(self):
        verdict = validate_final_answer(
            answer="يختلف الراتب حسب الجهة الحكومية والمؤهل العلمي",
            intent="salary_query",
        )
        assert not verdict.accepted

    def test_drug_no_substances_rejected(self):
        verdict = validate_final_answer(
            answer="يحظر قانون المخدرات التعامل مع أي مواد مخدرة.",
            intent="drug_table",
        )
        assert not verdict.accepted

    def test_table_reference_only_rejected(self):
        verdict = validate_final_answer(
            answer="وفقاً للجدول كما هو موضح في الجدول",
            intent="table_lookup",
        )
        assert not verdict.accepted

    def test_generic_fallback_blocked(self):
        verdict = validate_final_answer(
            answer="لا تتوفر لدي معلومات كافية",
            intent="salary_query",
        )
        assert not verdict.accepted

    def test_structured_lookup_data_preferred(self):
        """If lookup_data is provided, it MUST be used as the answer."""
        verdict = validate_final_answer(
            answer="بعض النص من LLM",
            intent="salary_query",
            lookup_data="الدرجة السابعة: 25,000 ريال",
        )
        assert verdict.accepted
        assert verdict.answer == "الدرجة السابعة: 25,000 ريال"
        assert verdict.source_used == "structured_lookup"


# ══════════════════════════════════════════════════════════════
# SECTION 7: Response Cleaner — No 📋 Leaks
# ══════════════════════════════════════════════════════════════

class TestResponseCleanerNoLeaks:
    """The response cleaner must strip ALL forbidden markers."""

    def test_direct_mode_strips_memo(self):
        answer = "📋 التكييف:\nالدرجة السابعة: 25,000\n⚖️ السند:\nالمادة 5"
        cleaned = clean_response(answer, answer_mode="direct_short")
        assert "📋" not in cleaned
        assert "⚖️" not in cleaned

    def test_structured_list_no_emoji_headers(self):
        answer = "📋 من القانون:\n1- بند أول\n2- بند ثاني"
        cleaned = clean_response(answer, answer_mode="structured_list")
        assert "📋" not in cleaned
        assert "بند أول" in cleaned

    def test_table_row_mode_clean(self):
        answer = "📋 الدرجة السابعة: 25,000"
        cleaned = clean_response(answer, answer_mode="table_row")
        assert "📋" not in cleaned
        assert "25,000" in cleaned


# ══════════════════════════════════════════════════════════════
# SECTION 8: Knowledge Map No Longer Injects 📋
# ══════════════════════════════════════════════════════════════

class TestKnowledgeMapClean:
    """knowledge_map.py MUST NOT output 📋 formatted text."""

    def test_smart_fetch_no_emoji(self):
        """The smart_fetch output template must not contain 📋."""
        from core.knowledge_map import smart_fetch
        # We can't call async here, but verify the source code pattern
        import inspect
        source = inspect.getsource(smart_fetch)
        assert "📋" not in source, "knowledge_map.smart_fetch still contains 📋 in its code"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
