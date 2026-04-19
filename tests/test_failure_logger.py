# -*- coding: utf-8 -*-
"""Tests for the self-improvement failure logger."""
import os
import sys
import tempfile
from pathlib import Path

# Use a temp dir BEFORE importing the module
_TMP = tempfile.mkdtemp(prefix="failure_logger_test_")
os.environ["FAILURE_LOG_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force re-import with the env var set
import importlib
from core import failure_logger
importlib.reload(failure_logger)

from core.failure_logger import (
    log_failure,
    read_failures,
    summarize_failures,
    find_repeated_failures,
    clear_failures,
    FailureType,
)


def setup_function(_):
    """Clear log before each test."""
    clear_failures()


def test_log_and_read_single():
    log_failure(
        failure_type=FailureType.REFUSAL,
        query="راتب الدرجة العاشرة",
        intent="salary_query",
        confidence=0,
        refusal_text="غير موجودة",
    )
    records = read_failures()
    assert len(records) == 1
    assert records[0]["type"] == "refusal"
    assert records[0]["intent"] == "salary_query"
    assert "العاشرة" in records[0]["query"]


def test_log_multiple_and_summarize():
    for i in range(3):
        log_failure(FailureType.REFUSAL, "راتب الدرجة العاشرة",
                    intent="salary_query")
    log_failure(FailureType.GRADE_MISS, "راتب الدرجة الحادية عشرة",
                intent="salary_query")
    log_failure(FailureType.PARSE_FAILURE, "جدول المخدرات",
                intent="drug_table")

    summary = summarize_failures()
    assert summary["total"] == 5
    assert summary["by_type"]["refusal"] == 3
    assert summary["by_type"]["grade_miss"] == 1
    assert summary["by_type"]["parse_failure"] == 1
    assert summary["by_intent"]["salary_query"] == 4
    assert summary["by_intent"]["drug_table"] == 1


def test_find_repeated_failures():
    for _ in range(4):
        log_failure(FailureType.REFUSAL, "نفس السؤال",
                    intent="salary_query")
    log_failure(FailureType.REFUSAL, "سؤال آخر",
                intent="drug_table")

    repeated = find_repeated_failures(min_count=3)
    assert len(repeated) == 1
    assert repeated[0]["query"] == "نفس السؤال"
    assert repeated[0]["count"] == 4


def test_log_never_raises_on_bad_input():
    # None types, weird unicode, huge strings — must not raise
    log_failure(FailureType.REFUSAL, None, intent=None, confidence=None)
    log_failure("unknown_type", "x" * 10000, intent="???", confidence=999999)
    # Should still be readable
    records = read_failures()
    assert len(records) == 2


def test_clear_returns_count():
    log_failure(FailureType.REFUSAL, "س1", intent="salary_query")
    log_failure(FailureType.REFUSAL, "س2", intent="salary_query")
    n = clear_failures()
    assert n == 2
    assert read_failures() == []


def test_summary_empty():
    summary = summarize_failures()
    assert summary["total"] == 0
    assert summary["by_type"] == {}
    assert summary["top_queries"] == []
