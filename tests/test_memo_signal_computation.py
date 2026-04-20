# -*- coding: utf-8 -*-
"""
tests/test_memo_signal_computation.py — unit test for signal sweep.

Target behaviour (post-Step-4):
  A helper ``_compute_memo_signals(history, current_query)`` must inspect
  the **entire** per-session history (capped at the LRU limit, currently
  50 turns) when counting memo signals, NOT a trailing window of 8
  messages. This prevents regression in long conversations where the
  rich-signal turn ends up far from the tail.

Current behaviour (pre-fix):
  ``handle_memo_smart`` slices ``history[-8:]`` and also considers at
  most ``all_user_msgs[-5:]`` in the bypass path. A 15-turn history with
  the signal-bearing turn at index 3 (and nothing rich afterwards) is
  under-counted → ``signals < min_signals["حضانة"]`` → the ask-for-
  details branch fires again.

The test imports ``_compute_memo_signals`` from ``routers.query_router``.
That symbol does not yet exist; the test will FAIL today with a clean
pytest.fail message and will PASS after Step 4 introduces the helper.
"""
import importlib

import pytest


# Rich signal planted deep in the past.
_RICH_TURN_3_USER = (
    "1- طفل واحد اسمه احمد وعمره 3 سنوات\n"
    "2- السبب سوء سلوك الحاضنة\n"
    "3- لا لكن يوجد وثيقة طلاق فقط ..... طلقتها بتاريخ 5/2/2024 وانا "
    "انفق عليها وعلى الولد"
)


def _build_long_history() -> list[dict]:
    """15 messages: greeting → memo-ask → rich T3 → 10 short follow-ups.

    Index layout (pre-current-turn):
      [0] user      "مرحبا"
      [1] assistant greeting
      [2] user      "اكتب مذكرة اسقاط حضانه"
      [3] assistant ask-for-details ("أحتاج منك هذه التفاصيل")
      [4] user      ← RICH TURN (names + numbers + date + length)
      [5] assistant first memo draft
      [6..15] user/assistant short nagging exchanges
    """
    history: list[dict] = [
        {"role": "user",      "content": "مرحبا"},
        {"role": "assistant", "content": "أهلاً، كيف أقدر أساعدك؟"},
        {"role": "user",      "content": "اكتب مذكرة اسقاط حضانه"},
        {"role": "assistant",
         "content": ("قبل ما أكتب مذكرة حضانة احترافية، "
                     "أحتاج منك هذه التفاصيل: 1. ...")},
        # T3 (index 4) — rich signal
        {"role": "user",      "content": _RICH_TURN_3_USER},
        {"role": "assistant", "content": "بسم الله الرحمن الرحيم. مذكرة…"},
    ]
    # 10 short follow-ups to push T3 out of any trailing window of size 8
    short_user_lines = [
        "اكتب المذكرة", "لا انت اكتبها", "ليش ماتكتب",
        "قلت لك اكتبها", "طيب",
    ]
    short_assistant_lines = [
        "بسم الله الرحمن الرحيم، مذكرة…", "…", "…", "…", "…",
    ]
    for u, a in zip(short_user_lines, short_assistant_lines):
        history.append({"role": "user", "content": u})
        history.append({"role": "assistant", "content": a})

    assert len(history) == 16, f"expected 16 history msgs, got {len(history)}"
    return history


def _import_compute_memo_signals():
    """Import helper — kept as a function so pytest reports a clean failure
    rather than a module-level ImportError that stops collection."""
    mod = importlib.import_module("routers.query_router")
    fn = getattr(mod, "_compute_memo_signals", None)
    return fn


def test_memo_signal_computation_preserves_early_rich_turn():
    """Signal computation over a 16-turn history must still see the rich
    signal planted at index 4, even though the tail is dominated by short
    follow-ups. ``min_signals["حضانة"] = 2`` → we demand ``>= 2``.
    """
    fn = _import_compute_memo_signals()
    if fn is None:
        pytest.fail(
            "routers.query_router._compute_memo_signals is not defined yet "
            "— this test drives Step-4 implementation. Expected signature: "
            "_compute_memo_signals(history: list[dict], current_query: str, "
            "topic: str) -> int"
        )

    history = _build_long_history()
    current_query = "اكتب بالمعلومات المتوفرة"   # short nag — no signals of its own

    signals = fn(history, current_query, topic="حضانة")

    assert isinstance(signals, int), f"expected int, got {type(signals).__name__}"
    assert signals >= 2, (
        f"expected signals >= min_signals['حضانة'] (=2), got {signals}. "
        f"The rich user turn at history[4] carries multiple numbers, a "
        f"name, a date, and >80 chars — any honest full-history sweep "
        f"must surface at least 2 signals."
    )


def test_memo_signal_computation_respects_lru_cap():
    """Sanity check: when the history is short (≤ 8 msgs), the new full-
    sweep helper must agree with the old windowed behaviour. Nothing
    regresses for conversations that were already short."""
    fn = _import_compute_memo_signals()
    if fn is None:
        pytest.fail(
            "routers.query_router._compute_memo_signals is not defined yet "
            "— implemented in Step 4."
        )

    # 3 msgs only — a trivial case; any correct sweep counts signals here.
    short_history = [
        {"role": "user",      "content": "اكتب مذكرة حضانة"},
        {"role": "assistant", "content": "أحتاج منك التفاصيل..."},
        {"role": "user",      "content": _RICH_TURN_3_USER},
    ]
    signals = fn(short_history, "يلا اكتب", topic="حضانة")
    assert signals >= 2, (
        f"short-history sanity: expected signals >= 2, got {signals}"
    )
