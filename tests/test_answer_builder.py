# -*- coding: utf-8 -*-
"""
Tests for Data-First Answer Builder
=====================================
Ensures deterministic, clean output with:
- No 📋⚖️🔍✅📊 headers
- No explanatory text
- No filler
- Exact data only
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.answer_builder import (
    build_salary_answer, build_drug_answer, build_table_answer,
    build_list_answer, build_structured_answer,
    _clean_salary_row, _clean_salary_table, _clean_table_content,
)


# ══════════════════════════════════════════════════════════════
# 1. Salary Builder
# ══════════════════════════════════════════════════════════════

class TestSalaryBuilder:
    def test_single_grade_with_two_numbers(self):
        result = build_salary_answer(
            content="", law_name="قانون الموارد البشرية",
            target_grade="السابعة",
            grade_row="الدرجة السابعة: المربوط 25,000 نهاية المربوط 35,000",
        )
        assert "السابعة" in result
        assert "25,000" in result
        assert "35,000" in result
        assert "📋" not in result
        assert "التكييف" not in result

    def test_single_grade_with_one_number(self):
        result = build_salary_answer(
            content="", law_name="قانون الخدمة المدنية",
            target_grade="الأولى",
            grade_row="الدرجة الأولى: 50,000",
        )
        assert "الأولى" in result
        assert "50,000" in result
        assert "📋" not in result

    def test_full_table(self):
        content = (
            "الدرجة الأولى: 50,000\n"
            "الدرجة الثانية: 45,000\n"
            "الدرجة السابعة: 25,000\n"
        )
        result = build_salary_answer(content=content, law_name="قانون الموارد البشرية")
        assert "جدول الدرجات" in result
        assert "50,000" in result
        assert "25,000" in result
        assert "📋" not in result

    def test_source_reference_at_end(self):
        result = build_salary_answer(
            content="الدرجة الأولى: 50,000", law_name="قانون الموارد البشرية",
        )
        assert "المصدر" in result
        assert "الموارد البشرية" in result

    def test_no_headers_in_output(self):
        result = build_salary_answer(
            content="الدرجة الأولى: 50,000", law_name="",
            target_grade="الأولى", grade_row="الدرجة الأولى: 50,000",
        )
        for marker in ["📋", "⚖️", "🔍", "✅", "📊", "التكييف", "السند", "التحليل"]:
            assert marker not in result, f"Found forbidden marker: {marker}"


# ══════════════════════════════════════════════════════════════
# 2. Drug Builder
# ══════════════════════════════════════════════════════════════

class TestDrugBuilder:
    def test_extracts_numbered_items(self):
        chunks = [{"content": "1- مورفين\n2- كوكايين\n3- هيروين\n4- حشيش", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        assert "مورفين" in result
        assert "كوكايين" in result
        assert "📋" not in result
        # Should be numbered
        assert "1-" in result or "1 -" in result

    def test_extracts_english_names(self):
        chunks = [{"content": "Substances:\nMORPHINE\nCOCAINE\nHEROIN", "law_name": "Drug Law"}]
        result = build_drug_answer(chunks)
        assert "MORPHINE" in result
        assert "COCAINE" in result

    def test_no_headers(self):
        chunks = [{"content": "1- مورفين\n2- كوكايين", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        for marker in ["📋", "⚖️", "🔍", "✅", "📊"]:
            assert marker not in result

    def test_source_at_end(self):
        chunks = [{"content": "1- مورفين\n2- كوكايين", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        assert "المصدر" in result


# ══════════════════════════════════════════════════════════════
# 3. Table Builder
# ══════════════════════════════════════════════════════════════

class TestTableBuilder:
    def test_extracts_rows(self):
        chunks = [{"content": "1- البند الأول: معدات\n2- البند الثاني: مواد خام\n3- البند الثالث: خدمات",
                    "law_name": "قانون المناقصات"}]
        result = build_table_answer(chunks)
        assert "البند الأول" in result
        assert "البند الثاني" in result
        assert "📋" not in result

    def test_keeps_pipe_tables(self):
        chunks = [{"content": "الاسم | القيمة\nأولاً | 100\nثانياً | 200", "law_name": ""}]
        result = build_table_answer(chunks)
        assert "|" in result

    def test_drops_old_headers(self):
        chunks = [{"content": "📋 من قانون:\n1- بند\n2- بند آخر", "law_name": "قانون"}]
        result = build_table_answer(chunks)
        assert "📋" not in result


# ══════════════════════════════════════════════════════════════
# 4. List Builder
# ══════════════════════════════════════════════════════════════

class TestListBuilder:
    def test_numbered_output(self):
        chunks = [{"content": "1- مادة أولى\n2- مادة ثانية\n3- مادة ثالثة",
                    "law_name": "قانون المواد"}]
        result = build_list_answer(chunks)
        assert "1-" in result
        assert "2-" in result
        assert "مادة أولى" in result

    def test_no_headers_or_filler(self):
        chunks = [{"content": "• عنصر أول\n• عنصر ثاني\n• عنصر ثالث", "law_name": ""}]
        result = build_list_answer(chunks)
        for marker in ["📋", "⚖️", "🔍", "✅", "📊", "بناءً على", "التكييف"]:
            assert marker not in result


# ══════════════════════════════════════════════════════════════
# 5. Main Router (build_structured_answer)
# ══════════════════════════════════════════════════════════════

class TestStructuredRouter:
    def test_salary_intent_routes(self):
        result = build_structured_answer(
            intent="salary_query",
            raw_content="الدرجة الأولى: 50,000",
            law_name="قانون الموارد البشرية",
        )
        assert result is not None
        assert "50,000" in result

    def test_drug_intent_routes(self):
        result = build_structured_answer(
            intent="drug_table",
            raw_content="1- مورفين\n2- كوكايين",
            law_name="قانون المخدرات",
        )
        assert result is not None
        assert "مورفين" in result

    def test_table_intent_routes(self):
        result = build_structured_answer(
            intent="table_lookup",
            raw_content="1- بند أول\n2- بند ثاني",
            law_name="",
        )
        assert result is not None

    def test_enum_intent_routes(self):
        result = build_structured_answer(
            intent="enumeration_list",
            raw_content="1- مادة\n2- مادة",
            law_name="",
        )
        assert result is not None

    def test_general_legal_returns_none(self):
        result = build_structured_answer(
            intent="general_legal",
            raw_content="some text",
        )
        assert result is None

    def test_grade_specific_salary(self):
        result = build_structured_answer(
            intent="salary_query",
            raw_content="full table",
            law_name="قانون الموارد البشرية",
            target_grade="السابعة",
            grade_row="الدرجة السابعة: المربوط 25,000 نهاية المربوط 35,000",
        )
        assert "السابعة" in result
        assert "25,000" in result


# ══════════════════════════════════════════════════════════════
# 6. Clean Helpers
# ══════════════════════════════════════════════════════════════

class TestCleanHelpers:
    def test_clean_salary_row_two_numbers(self):
        row = "الدرجة السابعة: المربوط 25,000 نهاية المربوط 35,000"
        result = _clean_salary_row(row, "السابعة")
        assert "25,000" in result
        assert "35,000" in result
        assert "السابعة" in result

    def test_clean_salary_table_drops_headers(self):
        content = "📋 جدول الرواتب — من قانون:\nالدرجة الأولى: 50,000\n---\nملاحظات"
        result = _clean_salary_table(content)
        assert "📋" not in result
        assert "50,000" in result

    def test_clean_table_content_drops_old_headers(self):
        content = "📋 من قانون:\n1- بند أول\n2- بند ثاني\n---"
        result = _clean_table_content(content)
        assert "📋" not in result
        assert "بند أول" in result


# ══════════════════════════════════════════════════════════════
# 7. No Headers Rule — comprehensive check
# ══════════════════════════════════════════════════════════════

class TestNoHeadersRule:
    """Every builder must produce output with ZERO memo headers."""

    FORBIDDEN = ["📋", "⚖️", "🔍", "✅", "📊", "التكييف", "السند النظامي", "التحليل القانوني"]

    def _check_no_headers(self, text):
        for marker in self.FORBIDDEN:
            assert marker not in text, f"Forbidden marker '{marker}' found in: {text[:100]}"

    def test_salary_no_headers(self):
        result = build_salary_answer(
            content="الدرجة الأولى: 50,000", law_name="قانون",
        )
        self._check_no_headers(result)

    def test_drug_no_headers(self):
        result = build_drug_answer([{"content": "1- مورفين\n2- كوكايين", "law_name": ""}])
        self._check_no_headers(result)

    def test_table_no_headers(self):
        result = build_table_answer([{"content": "1- بند\n2- بند", "law_name": ""}])
        self._check_no_headers(result)

    def test_list_no_headers(self):
        result = build_list_answer([{"content": "1- مادة\n2- مادة", "law_name": ""}])
        self._check_no_headers(result)


# ══════════════════════════════════════════════════════════════
# 8. Targeted Regression Tests — reported failure cases
# ══════════════════════════════════════════════════════════════

class TestSalaryRegressions:
    """Fixes for: salary returns full table + headers instead of single row."""

    def test_single_grade_returns_one_line_only(self):
        """'الدرجة السابعة فقط' must return ONLY that grade, not full table."""
        result = build_salary_answer(
            content="الدرجة الأولى: 50,000\nالدرجة الثانية: 45,000\nالدرجة السابعة: 25,000 — 35,000",
            law_name="قانون الموارد البشرية",
            target_grade="السابعة",
            grade_row="الدرجة السابعة: المربوط 25,000 نهاية المربوط 35,000",
        )
        # Must contain the target grade
        assert "السابعة" in result
        assert "25,000" in result
        # Must NOT contain other grades
        assert "الأولى" not in result
        assert "الثانية" not in result
        assert "50,000" not in result
        # Must NOT have full table header
        assert "جدول الدرجات" not in result
        # Must NOT have emoji headers
        assert "📋" not in result

    def test_salary_query_grade_specific_no_table_dump(self):
        """'كم راتب الدرجة السابعة' — no full table dump."""
        result = build_salary_answer(
            content="الدرجة الممتازة: 80,000\nالدرجة الخاصة: 70,000\nالدرجة الأولى: 50,000\nالدرجة الثانية: 45,000\nالدرجة الثالثة: 40,000\nالدرجة الرابعة: 35,000\nالدرجة الخامسة: 30,000\nالدرجة السادسة: 28,000\nالدرجة السابعة: 25,000",
            law_name="قانون الموارد البشرية",
            target_grade="السابعة",
            grade_row="الدرجة السابعة: 25,000",
        )
        lines = [l for l in result.split('\n') if l.strip()]
        # Should be at most 2 lines: grade row + source
        assert len(lines) <= 3, f"Too many lines ({len(lines)}): {result}"

    def test_salary_via_router(self):
        """build_structured_answer routes salary correctly."""
        result = build_structured_answer(
            intent="salary_query",
            raw_content="full table...",
            law_name="قانون الموارد البشرية",
            target_grade="السابعة",
            grade_row="الدرجة السابعة: المربوط 25,000 نهاية المربوط 35,000",
        )
        assert "السابعة" in result
        assert "📋" not in result
        assert "الأولى" not in result


class TestDrugRegressions:
    """Fixes for: drug queries output raw OCR text."""

    def test_drug_drops_long_ocr_paragraphs(self):
        """Long OCR paragraphs (>120 chars) must be filtered out."""
        ocr_garbage = "a" * 150  # simulate long OCR paragraph
        chunks = [{"content": f"1- مورفين\n2- كوكايين\n{ocr_garbage}\n3- هيروين", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        assert "مورفين" in result
        assert "كوكايين" in result
        assert "هيروين" in result
        assert ocr_garbage not in result

    def test_drug_drops_emoji_headers_in_content(self):
        """📋 headers inside chunk content must be stripped."""
        chunks = [{"content": "📋 من قانون المخدرات:\n1- مورفين\n2- كوكايين", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        assert "📋" not in result
        assert "مورفين" in result

    def test_drug_deduplicates_across_chunks(self):
        """Same substance in multiple chunks should appear once."""
        chunks = [
            {"content": "1- مورفين\n2- كوكايين", "law_name": "قانون المخدرات"},
            {"content": "1- مورفين\n2- هيروين", "law_name": "قانون المخدرات"},
        ]
        result = build_drug_answer(chunks)
        # Count occurrences of مورفين — should be exactly 1
        assert result.count("مورفين") == 1
        assert "كوكايين" in result
        assert "هيروين" in result

    def test_drug_names_only_no_explanations(self):
        """Output must be substance names only, no legal explanations."""
        chunks = [{"content": "1- مورفين\n2- كوكايين\n3- هيروين", "law_name": "قانون المخدرات"}]
        result = build_drug_answer(chunks)
        assert "بناءً على" not in result
        assert "التكييف" not in result
        assert "التحليل" not in result


class TestOutputGuard:
    """Verify that no structured answer can ever contain forbidden markers."""

    FORBIDDEN = ["📋", "⚖️", "🔍", "✅", "📊"]

    def test_salary_guard(self):
        result = build_structured_answer(
            intent="salary_query",
            raw_content="📋 الدرجة الأولى: 50,000",
            law_name="قانون",
        )
        for m in self.FORBIDDEN:
            assert m not in result, f"Marker {m} leaked through"

    def test_drug_guard(self):
        result = build_structured_answer(
            intent="drug_table",
            raw_content="📋 من قانون:\n1- مورفين\n2- كوكايين",
            law_name="قانون المخدرات",
        )
        for m in self.FORBIDDEN:
            assert m not in result, f"Marker {m} leaked through"

    def test_table_guard(self):
        result = build_structured_answer(
            intent="table_lookup",
            raw_content="📋 جدول:\n1- بند أول\n2- بند ثاني",
            law_name="",
        )
        for m in self.FORBIDDEN:
            assert m not in result, f"Marker {m} leaked through"

    def test_list_guard(self):
        result = build_structured_answer(
            intent="enumeration_list",
            raw_content="📋 قائمة:\n1- مادة\n2- مادة",
            law_name="",
        )
        for m in self.FORBIDDEN:
            assert m not in result, f"Marker {m} leaked through"
