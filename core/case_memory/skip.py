# -*- coding: utf-8 -*-
"""
core/case_memory/skip.py — pure-function skip logic for case_memory.

Truth table
-----------
====================================  ===============  =================
condition (any one true)              skip?            reason
====================================  ===============  =================
history_length <= 0                   True             first_turn
phase0_class in ALWAYS_SKIP_CLASSES   True             phase0_<class>
query starts with definitional prefix True             definitional
concepts is empty                     True             no_concepts
otherwise                             False            eligible
====================================  ===============  =================

Reason strings are parse-safe (no free-form text) so they can feed
metrics dashboards and log filters.

No I/O. No async. No side effects. Pure function.

Status: CP2 · Part B. Implementation live; cm11-cm14 + cm14b exercise it.
"""
from __future__ import annotations

from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────
# Definitional prefixes
# ─────────────────────────────────────────────────────────────────
# Queries starting with these want article text, NOT case memory.
# Shared philosophy with precedent_linker's skip logic (FINDING §5).

_DEFINITIONAL_PREFIXES: Tuple[str, ...] = (
    "ما هو",
    "ما هي",
    "ماهو",
    "ماهي",
    "ما عقوبة",
    "عقوبة",
    "تعريف",
    "متى",
    "أين",
    "كيف",
    "لماذا",
    "هل يجوز",
    "هل يمكن",
)


# ─────────────────────────────────────────────────────────────────
# phase0 classes that always skip
# ─────────────────────────────────────────────────────────────────

_ALWAYS_SKIP_PHASE0_CLASSES: frozenset[str] = frozenset({
    "greeting",
    "meta",
    "capability_query",
    "gratitude",
    "farewell",
})


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _is_definitional(query: str) -> bool:
    """Return True iff ``query`` (after strip) begins with any
    definitional prefix. Case / whitespace trivial."""
    if not query:
        return False
    stripped = query.strip()
    for prefix in _DEFINITIONAL_PREFIXES:
        if stripped.startswith(prefix):
            return True
    return False


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def should_skip_case_memory(
    query: str,
    phase0_class: Optional[str],
    concepts: List[str],
    history_length: int,
) -> Tuple[bool, str]:
    """Pure decision: skip case-memory for this turn?

    Parameters
    ----------
    query : str
        Raw user query.
    phase0_class : Optional[str]
        The phase-0 classification label (``greeting``, ``memo``,
        ``case_analysis``, …). ``None`` when phase-0 is not applicable.
    concepts : list[str]
        Legal concepts extracted upstream. Empty list means "nothing
        to key the memory on".
    history_length : int
        Number of prior turns in this session. ``0`` → first turn.

    Returns
    -------
    (skip, reason) : tuple[bool, str]
        ``reason`` is one of:
        ``first_turn | phase0_<class> | definitional | no_concepts | eligible``.
    """
    if history_length <= 0:
        return (True, "first_turn")

    if phase0_class and phase0_class in _ALWAYS_SKIP_PHASE0_CLASSES:
        return (True, f"phase0_{phase0_class}")

    if _is_definitional(query):
        return (True, "definitional")

    if not concepts:
        return (True, "no_concepts")

    return (False, "eligible")


__all__ = ["should_skip_case_memory"]
