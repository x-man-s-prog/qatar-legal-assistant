# -*- coding: utf-8 -*-
"""Tests for مربوط vs إجمالي salary scope detection."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.structured_lookup import _classify_salary_scope
from core.answer_builder import build_salary_answer, build_structured_answer


# ── _classify_salary_scope ─────────────────────────────────────

def test_scope_basic_marbout():
    assert _classify_salary_scope("كم مربوط الدرجة السابعة") == "basic"


def test_scope_basic_alasasi():
    assert _classify_salary_scope("الراتب الأساسي للدرجة السابعة") == "basic"


def test_scope_total_ijmali():
    assert _classify_salary_scope("كم إجمالي راتب الدرجة السابعة") == "total"


def test_scope_total_with_allowances():
    assert _classify_salary_scope("راتب الدرجة السابعة بالعلاوات") == "total"


def test_scope_total_full_salary():
    assert _classify_salary_scope("كامل الراتب للدرجة السابعة") == "total"


def test_scope_unspecified():
    assert _classify_salary_scope("راتب الدرجة السابعة") == "unspecified"


def test_scope_basic_overrides_when_both_present():
    # If query mentions both مربوط and إجمالي, basic wins (more specific)
    assert _classify_salary_scope(
        "ما الفرق بين مربوط وإجمالي الدرجة السابعة"
    ) == "basic"


# ── builder behavior with scope ────────────────────────────────

def test_builder_basic_no_note():
    out = build_salary_answer(
        content="", law_name="قانون الموارد البشرية",
        target_grade="السابعة",
        grade_row="الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
        scope="basic",
    )
    assert "السابعة" in out
    assert "العلاوات" not in out  # no clarifier on basic


def test_builder_total_adds_note():
    out = build_salary_answer(
        content="", law_name="قانون الموارد البشرية",
        target_grade="السابعة",
        grade_row="الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
        scope="total",
    )
    assert "السابعة" in out
    assert "العلاوات" in out  # clarifier present


def test_builder_unspecified_no_note():
    out = build_salary_answer(
        content="", law_name="قانون الموارد البشرية",
        target_grade="السابعة",
        grade_row="الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
        scope="unspecified",
    )
    assert "السابعة" in out
    # We chose to be silent on unspecified to keep responses brief
    assert "العلاوات" not in out


def test_structured_answer_routes_scope():
    out = build_structured_answer(
        intent="salary_query",
        raw_content="",
        law_name="قانون الموارد البشرية",
        target_grade="السابعة",
        grade_row="الدرجة السابعة | بداية المربوط: 4000 | نهاية المربوط: 5500",
        scope="total",
    )
    assert out is not None
    assert "العلاوات" in out
