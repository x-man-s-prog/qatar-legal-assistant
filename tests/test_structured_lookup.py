# -*- coding: utf-8 -*-
"""Tests for structured lookup V3 — intent classification + enforcement."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.structured_lookup import classify_query, QueryIntent

# ══ Intent Classification ══

def test_salary_keywords():
    """Salary-specific keywords must classify as SALARY_QUERY."""
    assert classify_query("كم راتب موظف درجة سابعه") == QueryIntent.SALARY_QUERY
    assert classify_query("سلم الرواتب الحكومي") == QueryIntent.SALARY_QUERY
    assert classify_query("جدول الدرجات والرواتب") == QueryIntent.SALARY_QUERY
    assert classify_query("راتب درجة سابعة") == QueryIntent.SALARY_QUERY
    assert classify_query("كم الراتب") == QueryIntent.SALARY_QUERY

def test_drug_keywords():
    """Drug-specific keywords must classify as DRUG_TABLE."""
    assert classify_query("جدول المخدرات") == QueryIntent.DRUG_TABLE
    assert classify_query("المواد المخدرة") == QueryIntent.DRUG_TABLE
    assert classify_query("المؤثرات العقلية") == QueryIntent.DRUG_TABLE

def test_enum_keywords():
    """Enumeration requests must classify properly."""
    assert classify_query("اذكر اسماء المواد المحظورة") == QueryIntent.ENUMERATION_LIST
    assert classify_query("عدد لي المواد الكيميائية") == QueryIntent.ENUMERATION_LIST

def test_enum_drug_crossover():
    """Drug-related enumerations should classify as DRUG_TABLE."""
    assert classify_query("اذكر اسماء المواد المخدرة") == QueryIntent.DRUG_TABLE
    assert classify_query("عدد لي المواد المخدرة والمؤثرات") == QueryIntent.DRUG_TABLE

def test_table_keywords():
    """Generic table requests must classify as TABLE_LOOKUP."""
    assert classify_query("جدول رقم 1 الملحق بالقانون") == QueryIntent.TABLE_LOOKUP
    assert classify_query("ملحق رقم 3 من قانون المخدرات") == QueryIntent.TABLE_LOOKUP

def test_article_lookup():
    """Article text requests classify as ARTICLE_LOOKUP."""
    assert classify_query("نص المادة 173 من قانون الأسرة") == QueryIntent.ARTICLE_LOOKUP

def test_general_legal():
    """Non-lookup queries must classify as GENERAL_LEGAL."""
    assert classify_query("ما عقوبة السرقة") == QueryIntent.GENERAL_LEGAL
    assert classify_query("هل يحق للزوجة طلب الخلع") == QueryIntent.GENERAL_LEGAL
    assert classify_query("مرحبا") == QueryIntent.GENERAL_LEGAL
    assert classify_query("ما الفرق بين الجنحة والجناية") == QueryIntent.GENERAL_LEGAL

def test_salary_before_table():
    """Salary queries must take priority over generic table queries."""
    # "جدول الرواتب" has both salary and table keywords — salary should win
    assert classify_query("جدول الرواتب") == QueryIntent.SALARY_QUERY
    assert classify_query("جدول الدرجات") == QueryIntent.SALARY_QUERY


# ══ Enforcement Functions ══

from core.structured_lookup import _enforce_salary, _enforce_drug_content, _enforce_table_content

def test_enforce_salary_with_grades():
    """Must have grade words AND salary numbers."""
    good = "الدرجة الأولى: 50,000 | الدرجة الثانية: 45,000 | الدرجة الثالثة: 40,000"
    assert _enforce_salary(good) == True

def test_enforce_salary_no_numbers():
    """Reject content without salary numbers."""
    bad = "الدرجة الأولى والدرجة الثانية بحسب الجدول"
    assert _enforce_salary(bad) == False

def test_enforce_drug_english():
    """Drug content with English names should pass."""
    good = "1- ACETORPHINE\n2- MORPHINE\n3- COCAINE"
    assert _enforce_drug_content(good) == True

def test_enforce_drug_arabic():
    """Drug content with Arabic substance names should pass."""
    good = "اسيتورفين | مورفين | كوكايين | حشيش"
    assert _enforce_drug_content(good) == True

def test_enforce_drug_penalties():
    """Penalty-only text without substance names should fail."""
    bad = "يعاقب بالحبس مدة لا تجاوز عشر سنوات وبالغرامة التي لا تقل عن خمسين"
    assert _enforce_drug_content(bad) == False

def test_enforce_table_with_items():
    """Table content with numbered items should pass."""
    good = "1- مادة مورفين\n2- مادة كوكايين\n3- مادة حشيش\n4- مادة هيروين"
    assert _enforce_table_content(good) == True

def test_enforce_table_reference_only():
    """Reference-only content should fail."""
    bad = "يكون الراتب وفقاً للجدول المرفق بهذا القانون"
    assert _enforce_table_content(bad) == False


# ══ Edge Cases ══

def test_short_query_general():
    """Very short queries without lookup signals → GENERAL_LEGAL."""
    assert classify_query("طلاق") == QueryIntent.GENERAL_LEGAL
    assert classify_query("حضانة") == QueryIntent.GENERAL_LEGAL

def test_followup_not_lookup():
    """Follow-up phrases should not trigger lookup."""
    assert classify_query("طيب وبعدين") == QueryIntent.GENERAL_LEGAL
    assert classify_query("اشرح اكثر") == QueryIntent.GENERAL_LEGAL


# ══ Grade Extraction ══

from core.structured_lookup import _extract_grade, _extract_grade_row
from core.answer_builder import build_salary_answer

def test_extract_grade_seventh():
    """'درجة سابعة' extracts السابعة."""
    assert _extract_grade("كم راتب درجة سابعة") == "السابعة"
    assert _extract_grade("راتب الدرجة السابعة") == "السابعة"
    assert _extract_grade("درجة سابعه") == "السابعة"

def test_extract_grade_first():
    assert _extract_grade("راتب الدرجة الأولى") == "الأولى"

def test_extract_grade_special():
    assert _extract_grade("الدرجة الخاصة") == "الخاصة"
    assert _extract_grade("الدرجة الممتازة") == "الممتازة"

def test_extract_grade_number():
    assert _extract_grade("راتب درجة 7") == "السابعة"
    assert _extract_grade("درجة 3") == "الثالثة"

def test_extract_grade_none():
    """General salary queries without grade return None."""
    assert _extract_grade("سلم الرواتب الحكومي") is None
    assert _extract_grade("كم الراتب") is None

def test_extract_grade_row_found():
    content = "الدرجة الأولى: 50,000\nالدرجة الثانية: 45,000\nالدرجة السابعة: 25,000\nعلاوة: 500"
    row = _extract_grade_row(content, "السابعة")
    assert row is not None
    assert "السابعة" in row
    assert "25,000" in row

def test_extract_grade_row_not_found():
    content = "الدرجة الأولى: 50,000\nالدرجة الثانية: 45,000"
    row = _extract_grade_row(content, "السابعة")
    assert row is None

def test_format_salary_grade():
    """Legacy test updated: now uses answer_builder which produces clean output (no 📋)."""
    result = build_salary_answer(
        content="", law_name="قانون الموارد البشرية",
        target_grade="السابعة",
        grade_row="الدرجة السابعة: 25,000",
    )
    assert "السابعة" in result
    assert "25,000" in result
    assert "📋" not in result  # Clean output — no emoji headers


# ══ Grade 8-10 Extraction (new) ══

def test_extract_grade_eighth():
    """Grade 8 must now be recognized."""
    assert _extract_grade("راتب الدرجة الثامنة") == "الثامنة"

def test_extract_grade_ninth():
    assert _extract_grade("الدرجة التاسعة") == "التاسعة"

def test_extract_grade_tenth():
    assert _extract_grade("راتب الدرجة العاشرة") == "العاشرة"

def test_extract_grade_number_8():
    assert _extract_grade("درجة 8") == "الثامنة"

def test_extract_grade_number_10():
    assert _extract_grade("درجة 10") == "العاشرة"


# ══ Grade-Miss Refusal (new) ══

def test_grade_miss_returns_none_for_row():
    """If grade is extracted but NOT in the table, _extract_grade_row must return None."""
    content = "الدرجة الأولى: 50,000\nالدرجة السابعة: 25,000"
    assert _extract_grade_row(content, "العاشرة") is None
    assert _extract_grade_row(content, "الثامنة") is None


def test_builder_produces_grade_specific_not_full_table():
    """When a specific grade is requested and found, builder must NOT dump full table."""
    full_table = (
        "الدرجة الأولى: المربوط 25,000\n"
        "الدرجة الثانية: المربوط 18,000\n"
        "الدرجة السابعة: المربوط 4,000\n"
    )
    result = build_salary_answer(
        content=full_table, law_name="قانون",
        target_grade="السابعة",
        grade_row="الدرجة السابعة: المربوط 4,000",
    )
    # Must contain the requested grade
    assert "السابعة" in result
    assert "4,000" in result
    # Must NOT contain other grades
    assert "الأولى" not in result
    assert "الثانية" not in result


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__} — {e}")
            failed += 1
    print(f"\n  {passed}/{passed+failed} passed")
