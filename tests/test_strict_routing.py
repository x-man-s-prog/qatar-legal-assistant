# -*- coding: utf-8 -*-
"""Tests for strict query routing and answer enforcement."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.structured_lookup import (
    classify_query, QueryIntent,
    _enforce_salary, _enforce_drug_content, _enforce_table_content,
)

# ══ Classification ══

def test_salary_direct():
    assert classify_query("كم راتب موظف درجة سابعه") == QueryIntent.SALARY_QUERY

def test_salary_table():
    """'جدول الرواتب' must route to SALARY, not TABLE."""
    assert classify_query("جدول الرواتب") == QueryIntent.SALARY_QUERY

def test_salary_grades():
    assert classify_query("جدول الدرجات والرواتب") == QueryIntent.SALARY_QUERY

def test_salary_scale():
    assert classify_query("سلم الرواتب الحكومي") == QueryIntent.SALARY_QUERY

def test_drug_table():
    assert classify_query("جدول المخدرات") == QueryIntent.DRUG_TABLE

def test_drug_names():
    assert classify_query("اسماء المواد المخدرة") == QueryIntent.DRUG_TABLE

def test_drug_via_enum():
    """Drug enumeration → DRUG_TABLE, not ENUMERATION."""
    assert classify_query("اذكر اسماء المخدرات") == QueryIntent.DRUG_TABLE

def test_enum_chemical():
    assert classify_query("ما هي المواد المحظوره كيميائيا") == QueryIntent.ENUMERATION_LIST

def test_enum_list():
    assert classify_query("عدد لي المواد الكيميائية") == QueryIntent.ENUMERATION_LIST

def test_table_generic():
    assert classify_query("جدول رقم 3 الملحق بالقانون") == QueryIntent.TABLE_LOOKUP

def test_article():
    assert classify_query("نص المادة 173 من قانون الأسرة") == QueryIntent.ARTICLE_LOOKUP

def test_general():
    assert classify_query("ما عقوبة السرقة") == QueryIntent.GENERAL_LEGAL

def test_greeting():
    assert classify_query("مرحبا") == QueryIntent.GENERAL_LEGAL


# ══ Enforcement ══

def test_enforce_salary_good():
    content = "الدرجة المالية | بداية المربوط | نهاية المربوط الممتازة | 23,000 | 26,000 الخاصة | 19,000 | 23,000 الأولى | 17,000 | 20,000"
    assert _enforce_salary(content) is True

def test_enforce_salary_bad():
    """Text that mentions grade but has no salary numbers → REJECT."""
    content = "يكون الراتب وفقاً للجدول المرفق بهذا القانون"
    assert _enforce_salary(content) is False

def test_enforce_drug_good():
    content = "1-ACETORPHINE 2-CANNABIS and CANNABIS RESIN 3-COCAINE"
    assert _enforce_drug_content(content) is True

def test_enforce_drug_bad():
    """Amendment text without substance names → REJECT."""
    content = "يُضاف إلى قائمة المواد المدرجة في الجدول بند جديد"
    assert _enforce_drug_content(content) is False

def test_enforce_table_good():
    content = "1- البند الأول شرح تفصيلي\n2- البند الثاني شرح آخر\n3- البند الثالث مزيد"
    assert _enforce_table_content(content) is True

def test_enforce_table_ref_only():
    """Reference-only text with no items → REJECT."""
    content = "يطبق وفقاً للجدول المرفق بهذا القانون"
    assert _enforce_table_content(content) is False


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
