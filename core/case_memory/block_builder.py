# -*- coding: utf-8 -*-
"""
core/case_memory/block_builder.py — prompt injection formatter.

Renders a compact Arabic block describing the top-N matched prior
cases, to be concatenated into the system prompt between
``_concept_context`` and ``_precedent_block``.

Rules
-----
- **Compact prose**, not a bullet wall (keeps token budget low).
- Hard cap **≈ 230 tokens** (~700 chars in Arabic). Truncate at line
  boundary if needed.
- Empty string when ``matches`` is empty — **never** inject a heading
  with nothing beneath it.
- Similarity is shown as a human-readable percentage, not a float.
- Tells the model *how* to use the context in one sentence at the end.

Pure function — no I/O, no clock access beyond the stored ``age_seconds``
property (which reads ``time.time()`` at call time; documented there).

Status: CP2 · Part D. Implementation live; cm21/cm21b/cm21c/cm22 exercise it.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    # Import-time avoidance — keeps block_builder independent of store.
    from core.case_memory.store import StoredCase


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

# Hard cap on block size in characters. Arabic averages ~3 chars/token
# with the tokenisers in play, so 700 chars ≈ 230 tokens.
_MAX_BLOCK_CHARS: int = 700

# At most this many matched cases are rendered, even if the caller
# passed more (defence-in-depth against a caller bug).
_MAX_CASES_IN_BLOCK: int = 3

# Per-case summary is trimmed before rendering so one huge summary
# can't starve the other slots.
_PER_CASE_SUMMARY_CHARS: int = 180


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def build_case_memory_block(
    matches: Sequence[Tuple["StoredCase", float]],
    current_query: str,
) -> str:
    """Format the case-memory prompt block.

    Parameters
    ----------
    matches : Sequence[(StoredCase, similarity)]
        Output of ``CaseMemoryStore.find_similar`` — pre-sorted desc
        by similarity, threshold-filtered.
    current_query : str
        The query that triggered the lookup. Accepted for API symmetry
        with callers that may want to interpolate cues; currently
        unused to keep the block deterministic.

    Returns
    -------
    str
        The block, including a leading blank-line separator. Empty
        string when ``matches`` is empty.
    """
    if not matches:
        return ""

    top = list(matches)[:_MAX_CASES_IN_BLOCK]

    lines: List[str] = ["\n\n📂 قضايا سابقة ذات صلة في هذه الجلسة:\n"]

    for case, sim in top:
        age_label = _humanize_age(case.age_seconds)
        sim_pct = int(round(sim * 100))
        summary = _truncate_summary(case.summary, _PER_CASE_SUMMARY_CHARS)
        lines.append(f"- قبل {age_label}: {summary} (تطابق {sim_pct}%)")

    lines.append(
        "\nإذا كان السؤال الحالي امتداداً لإحدى هذه القضايا، "
        "اربط إجابتك بالسياق السابق بصراحة."
    )

    block = "".join(lines)

    if len(block) > _MAX_BLOCK_CHARS:
        block = _truncate_block(block, _MAX_BLOCK_CHARS)

    return block


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _humanize_age(age_seconds: float) -> str:
    """Render ``age_seconds`` as an Arabic age label respecting
    singular / dual / plural (2-10) / plural (11+) forms.

    Boundaries (intentionally coarse — model doesn't need seconds):

        <   60 s          → ``لحظات``
        <    2 min        → ``دقيقة``
        <    3 min        → ``دقيقتين``
        <   11 min        → ``N دقائق`` (2-10)
        <   60 min        → ``N دقيقة`` (11+)
        <    2 h          → ``ساعة``
        <    3 h          → ``ساعتين``
        <   11 h          → ``N ساعات``
        <   24 h          → ``N ساعة``
        <    2 d          → ``يوم``
        <    3 d          → ``يومين``
        <   11 d          → ``N أيام``
        else             → ``N يوماً``
    """
    if age_seconds < 60:
        return "لحظات"

    minutes = age_seconds / 60
    if minutes < 60:
        if minutes < 2:
            return "دقيقة"
        if minutes < 3:
            return "دقيقتين"
        if minutes < 11:
            return f"{int(minutes)} دقائق"
        return f"{int(minutes)} دقيقة"

    hours = age_seconds / 3600
    if hours < 24:
        if hours < 2:
            return "ساعة"
        if hours < 3:
            return "ساعتين"
        if hours < 11:
            return f"{int(hours)} ساعات"
        return f"{int(hours)} ساعة"

    days = age_seconds / 86400
    if days < 2:
        return "يوم"
    if days < 3:
        return "يومين"
    if days < 11:
        return f"{int(days)} أيام"
    return f"{int(days)} يوماً"


def _truncate_summary(summary: str, max_chars: int) -> str:
    """Trim ``summary`` to ``max_chars``, preferring a sentence-like
    boundary (``،  . ؟ ! ``) in the last 40 % of the window.

    Returns the original string if already within the cap.
    Appends ``...`` when truncated.
    """
    if len(summary) <= max_chars:
        return summary

    truncated = summary[:max_chars]
    for sep in ("، ", ". ", "؟ ", "! "):
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.6:
            return truncated[:idx] + "..."

    return truncated + "..."


def _truncate_block(block: str, max_chars: int) -> str:
    """Trim ``block`` at a newline boundary to stay under ``max_chars``.

    Prefers losing whole lines over mid-sentence cuts — the reader is
    an LLM that copes better with a truncated list than with a
    half-sentence.
    """
    if len(block) <= max_chars:
        return block

    result: List[str] = []
    total = 0
    for line in block.split("\n"):
        candidate_len = total + len(line) + 1
        if candidate_len > max_chars:
            break
        result.append(line)
        total = candidate_len

    return "\n".join(result)


__all__ = ["build_case_memory_block"]
