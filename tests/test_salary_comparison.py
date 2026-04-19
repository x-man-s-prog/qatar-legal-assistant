# -*- coding: utf-8 -*-
"""Tests for salary comparison queries (multi-grade)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.structured_lookup import (
    _extract_multiple_grades,
    _is_comparison_query,
    _parse_salary_table,
    _extract_grade_row,
)
from core.answer_builder import build_salary_comparison, build_structured_answer


# Realistic salary table chunk
SAMPLE_TABLE = """جدول الدرجات والرواتب من قانون الموارد البشرية المدنية:
الدرجة الممتازة | 12000 | 18000
الدرجة الخاصة | 10000 | 14000
الدرجة الأولى | 8000 | 11000
الدرجة الثانية | 7000 | 9500
الدرجة الثالثة | 6000 | 8500
الدرجة الرابعة | 5500 | 7500
الدرجة الخامسة | 5000 | 7000
الدرجة السادسة | 4500 | 6000
الدرجة السابعة | 4000 | 5500
"""


# ── _extract_multiple_grades ──────────────────────────────────

def test_extract_two_grades():
    g = _extract_multiple_grades("قارن بين الدرجة السادسة والدرجة السابعة")
    assert "السادسة" in g and "السابعة" in g
    assert len(g) == 2


def test_extract_three_grades():
    g = _extract_multiple_grades(
        "الفرق بين الدرجة الأولى والدرجة الثانية والدرجة الثالثة"
    )
    assert len(g) == 3
    assert "الأولى" in g and "الثانية" in g and "الثالثة" in g


def test_extract_zero_grades():
    g = _extract_multiple_grades("ما هي الدرجات الموجودة")
    assert g == []


def test_extract_dedupes():
    g = _extract_multiple_grades("الدرجة السابعة والدرجة السابعة")
    assert g == ["السابعة"]


# ── _is_comparison_query ──────────────────────────────────────

def test_is_comparison_qaran():
    assert _is_comparison_query("قارن بين الدرجة السادسة والسابعة") is True


def test_is_comparison_alfar7():
    assert _is_comparison_query("الفرق بين الدرجة الأولى والدرجة الثانية") is True


def test_is_comparison_single_grade_not():
    # Only one grade → not a comparison
    assert _is_comparison_query("راتب الدرجة السابعة") is False


def test_is_comparison_no_signal_not():
    # Two grades but no "compare" signal → not a comparison
    assert _is_comparison_query("راتب الدرجة السادسة وراتب الدرجة السابعة") is False


# ── build_salary_comparison ───────────────────────────────────

def test_build_comparison_two_rows():
    rows = [
        "الدرجة السادسة | بداية المربوط: 4500 | نهاية المربوط: 6000",
        "الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
    ]
    out = build_salary_comparison(rows, law_name="قانون الموارد البشرية")
    assert "السادسة" in out
    assert "السابعة" in out
    assert "4500" in out and "6000" in out
    assert "4000" in out and "5500" in out
    assert "مقارنة" in out
    # No forbidden markers
    assert "📋" not in out
    assert "⚖️" not in out


def test_build_comparison_with_missing():
    rows = ["الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500"]
    out = build_salary_comparison(
        rows, law_name="قانون الموارد البشرية",
        missing=["العاشرة"],
        grades_requested=["السابعة", "العاشرة"],
    )
    assert "السابعة" in out
    assert "العاشرة" in out
    assert "ملاحظة" in out


def test_build_comparison_empty_rows():
    out = build_salary_comparison([], law_name="")
    # Even empty, should produce some structure (header+empty body)
    assert "مقارنة" in out


# ── build_structured_answer routing ───────────────────────────

def test_build_structured_routes_comparison():
    rows = [
        "الدرجة السادسة | بداية المربوط: 4500 | نهاية المربوط: 6000",
        "الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
    ]
    out = build_structured_answer(
        intent="salary_query",
        raw_content=SAMPLE_TABLE,
        law_name="قانون الموارد البشرية المدنية",
        comparison_rows=rows,
        comparison_grades=["السادسة", "السابعة"],
    )
    assert out is not None
    assert "السادسة" in out and "السابعة" in out
    assert "4500" in out and "4000" in out
    # Should NOT dump the full table when comparison is requested
    assert "الممتازة" not in out
    assert "الخاصة" not in out


def test_build_structured_no_comparison_uses_single():
    out = build_structured_answer(
        intent="salary_query",
        raw_content=SAMPLE_TABLE,
        law_name="قانون الموارد البشرية المدنية",
        target_grade="السابعة",
        grade_row="الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
    )
    assert out is not None
    assert "السابعة" in out
    assert "4000" in out
    # Should NOT include other grades
    assert "السادسة" not in out
    assert "الممتازة" not in out


# ── End-to-end: parse → extract rows for multiple grades ──────

def test_extract_grade_eleventh_multiword():
    from core.structured_lookup import _extract_grade
    assert _extract_grade("راتب الدرجة الحادية عشرة") == "الحادية عشرة"
    assert _extract_grade("راتب الدرجة الثانية عشرة") == "الثانية عشرة"
    assert _extract_grade("راتب الدرجة الثالثة عشر") == "الثالثة عشرة"


def test_extract_grade_unknown_returns_word():
    """Unknown grade words are still returned (not None) so the refusal
    engine can fire instead of falling through to a full-table dump."""
    from core.structured_lookup import _extract_grade
    g = _extract_grade("راتب الدرجة المستحدثة")
    assert g is not None
    assert g == "المستحدثة"


def test_extract_grade_no_grade_word_returns_none():
    from core.structured_lookup import _extract_grade
    assert _extract_grade("جدول الرواتب") is None


def test_extract_multiple_grade_rows_from_real_table():
    grades = ["السادسة", "السابعة"]
    rows = []
    for g in grades:
        r = _extract_grade_row(SAMPLE_TABLE, g)
        assert r is not None, f"grade {g} not found"
        rows.append(r)
    assert len(rows) == 2
    out = build_salary_comparison(rows, law_name="قانون الموارد البشرية المدنية")
    assert "4500" in out
    assert "4000" in out
    assert "السادسة" in out
    assert "السابعة" in out
