# -*- coding: utf-8 -*-
"""Tests for the Improvement Memory system."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="imp_mem_test_")
os.environ["FAILURE_LOG_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib
from core import failure_logger
importlib.reload(failure_logger)

from core.failure_logger import log_failure, clear_failures, FailureType
from core.improvement_memory import (
    detect_failure_patterns,
    get_knowledge_gaps,
    detect_new_gaps,
    generate_improvement_candidates,
    get_evidence_debts,
    generate_improvement_report,
)


def setup_function(_):
    clear_failures()


def test_detect_patterns_empty():
    patterns = detect_failure_patterns()
    assert patterns == []


def test_detect_repeated_refusal():
    for _ in range(4):
        log_failure(FailureType.REFUSAL, "راتب الدرجة العاشرة", intent="salary_query")
    patterns = detect_failure_patterns(min_count=3)
    assert len(patterns) >= 1
    assert patterns[0].pattern_type == "repeated_refusal"
    assert patterns[0].occurrence_count >= 4


def test_knowledge_gaps_exist():
    gaps = get_knowledge_gaps()
    assert len(gaps) >= 3
    assert any(g.gap_id == "gap_salary_allowances" for g in gaps)


def test_detect_new_gaps_from_patterns():
    for _ in range(5):
        log_failure(FailureType.REFUSAL, "سؤال متكرر جداً", intent="salary_query")
    new_gaps = detect_new_gaps()
    assert len(new_gaps) >= 1


def test_generate_candidates():
    candidates = generate_improvement_candidates()
    # At minimum, known gaps should generate candidates
    assert len(candidates) >= 3


def test_evidence_debts_exist():
    debts = get_evidence_debts()
    assert len(debts) >= 3
    assert any(d.debt_id == "debt_total_salary" for d in debts)


def test_improvement_report_structure():
    report = generate_improvement_report()
    assert "failure_patterns" in report
    assert "knowledge_gaps" in report
    assert "improvement_candidates" in report
    assert "evidence_debts" in report
    assert "summary" in report
    assert isinstance(report["summary"]["gap_count"], int)
