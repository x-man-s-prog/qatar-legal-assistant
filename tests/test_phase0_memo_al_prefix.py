# -*- coding: utf-8 -*-
"""
tests/test_phase0_memo_al_prefix.py — phase0 memo-trigger ال-prefix tests.

Two suites here:

  Test 1 — ``test_memo_request_handles_al_prefix``
           Direct unit tests on ``is_memo_request`` with the core cases
           listed in the incident report. Fails today because the flat
           substring matcher in ``_MEMO_TRIGGERS`` doesn't tolerate the
           ال (definite article) prefix: ``"اكتب المذكرة"`` slips past
           the literal ``"اكتب مذكرة"`` substring check.

  Test 4 — Matrix coverage (positive + negative)
           Ensures (a) the whole family of common ال-prefixed variants
           matches after the fix, AND (b) boundary cases do NOT
           false-positive (e.g. ``"اكتبت مذكرة"`` — wrong tense —
           must still return False).

Contract after Step-4 fix:
  Every query in ``POSITIVE_VARIANTS`` → ``is_memo_request`` == True.
  Every query in ``NEGATIVE_VARIANTS`` → ``is_memo_request`` == False.
"""
import pytest

from core.phase0_router import is_memo_request


# ─────────────────────────────────────────────────────────────────
# Test 1 — incident-report cases
# ─────────────────────────────────────────────────────────────────

_T1_CASES = [
    # (query, expected_is_memo_request)
    ("اكتب مذكرة حضانة",   True),   # baseline — passes today
    ("اكتب المذكرة",        True),   # ← FAILS today (ال on noun)
    ("اكتب لي المذكرة",      True),   # ← FAILS today
    ("صيغ المذكرة",         True),   # ← FAILS today
    ("احتاج المذكرة",        True),   # ← FAILS today
    ("ما عقوبة السرقة",      False),  # must remain general
    ("",                    False),
]


@pytest.mark.parametrize("query,expected", _T1_CASES)
def test_memo_request_handles_al_prefix(query: str, expected: bool):
    """``is_memo_request`` treats ``ال`` as optional on the memo noun.

    Same root-cause pattern as CP2 Part B ``_match_word`` — Arabic
    morphology (the definite article ``ال``) must be first-class for
    substring-style matchers. Naive ``kw in q`` misses the very common
    ``"اكتب المذكرة"`` user phrasing.
    """
    assert is_memo_request(query) is expected, (
        f"is_memo_request({query!r}) returned "
        f"{is_memo_request(query)!r}, expected {expected!r}"
    )


# ─────────────────────────────────────────────────────────────────
# Test 4 — matrix (positive + negative)
# ─────────────────────────────────────────────────────────────────
# POSITIVE: the ال-prefixed variant must match because it is the same
#           memo intent. Prevents regression if any trigger is ever
#           added / removed / re-worded.
#
# NEGATIVE: word-boundary correctness. A ال-tolerant matcher must NOT
#           accidentally treat inflected forms or possessive suffixes
#           as the bare trigger. Without boundary care the fix would
#           over-match:
#             "اكتبت مذكرة"  ← كتب past-tense feminine + ت suffix
#             "يكتب مذكرة"   ← كتب present-tense 3rd person
#             "اكتب مذكرتي"  ← مذكرة + possessive ي suffix
#           All must remain False.

_POSITIVE_VARIANTS = [
    "اكتب مذكرة",
    "اكتب المذكرة",
    "اكتب لي مذكرة",
    "اكتب لي المذكرة",
    "احتاج مذكرة",
    "احتاج المذكرة",
    "صيغ مذكرة",
    "صيغ المذكرة",
    "جهز مذكرة",
    "جهز المذكرة",
]

_NEGATIVE_VARIANTS = [
    # Wrong verb morphology — must NOT match
    "اكتبت مذكرة",         # past tense ("she wrote …")
    "يكتب مذكرة",           # 3rd-person present ("he writes …")
    # Wrong noun morphology — must NOT match
    "اكتب مذكرتي",          # possessive suffix on noun
    # Unrelated queries — classic general-route content
    "ما عقوبة السرقة",
    "كيف الحال",
    "",
]


@pytest.mark.parametrize("query", _POSITIVE_VARIANTS)
def test_memo_variants_al_prefix_matrix_positive(query: str):
    """Every variant in the positive matrix must be recognised after the fix."""
    assert is_memo_request(query) is True, (
        f"expected is_memo_request({query!r}) == True"
    )


@pytest.mark.parametrize("query", _NEGATIVE_VARIANTS)
def test_memo_variants_al_prefix_matrix_negative(query: str):
    """Boundary cases — word-boundary correctness.

    Guards against the ال-tolerant regex accidentally matching inflected
    verb forms or possessive-suffixed nouns.
    """
    assert is_memo_request(query) is False, (
        f"expected is_memo_request({query!r}) == False"
    )
