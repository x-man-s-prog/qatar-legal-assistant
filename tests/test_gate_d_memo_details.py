# -*- coding: utf-8 -*-
"""Unit tests for Gate D — structured memo-details response detection.

Gate D sits in routers/query_router.py and catches the case where a
user answers a prior memo_ask_details prompt with structured content
(numbered list, multi-line details, or direct answer starters).
Existing Gates A/B/C miss this when the server history is partially
truncated or when the query lacks a memo keyword.
"""
import pytest

from routers.query_router import _is_memo_details_response


def test_gate_d_numbered_list_after_ask():
    """Classic case: user answers numbered gap questions."""
    history = [
        {"role": "user", "content": "اكتب مذكرة حضانة"},
        {"role": "assistant",
         "content": ("قبل ما أكتب مذكرة حضانة احترافية، أحتاج منك "
                     "هذه التفاصيل: ما أعمار الأطفال وأسماؤهم?")},
    ]
    query = "1- احمد 3 سنوات 2- سوء سلوك"
    assert _is_memo_details_response(query, history) is True


def test_gate_d_no_prior_ask():
    """Gate must NOT fire if prior assistant was not asking details."""
    history = [
        {"role": "user", "content": "مرحبا"},
        {"role": "assistant", "content": "أهلا كيف يمكنني مساعدتك"},
    ]
    query = "1- احمد 3 سنوات"
    assert _is_memo_details_response(query, history) is False


def test_gate_d_empty_history():
    """No history → no gate trigger (nothing to continue)."""
    assert _is_memo_details_response("1- احمد", []) is False
    assert _is_memo_details_response("1- احمد", None) is False


def test_gate_d_direct_answer_starter():
    """Non-numbered answer that starts with an answer word is also
    a valid structured response to a gap question."""
    history = [
        {"role": "user", "content": "اكتب مذكرة"},
        {"role": "assistant",
         "content": ("أحتاج منك هذه التفاصيل: "
                     "ما أعمار الأطفال وأسماؤهم")},
    ]
    query = "اسمه احمد وعمره 3 سنوات"
    assert _is_memo_details_response(query, history) is True


def test_gate_d_unrelated_query():
    """Unrelated new query after memo-ask must NOT be treated as
    a details response."""
    history = [
        {"role": "user", "content": "اكتب مذكرة"},
        {"role": "assistant", "content": "أحتاج منك هذه التفاصيل"},
    ]
    query = "ما هي عقوبة السرقة"
    assert _is_memo_details_response(query, history) is False


def test_gate_d_multi_arabic_comma():
    """Details separated by Arabic commas (typical when typed on phone)."""
    history = [
        {"role": "user", "content": "اكتب مذكرة فصل"},
        {"role": "assistant",
         "content": "قبل ما أكتب مذكرة فصل احتاج منك هذه التفاصيل"},
    ]
    query = "الراتب 8000، الخدمة 5 سنوات، الفصل في 01/01/2024، بدون إنذار"
    assert _is_memo_details_response(query, history) is True
