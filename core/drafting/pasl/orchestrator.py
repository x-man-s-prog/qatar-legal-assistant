# -*- coding: utf-8 -*-
"""
PASL — Orchestrator.

Applies style passes to an MQE-composed memo in order:
    1) precision     — replace residual weak phrases
    2) emphasis      — strengthen argument leads
    3) flow          — transitions between arguments
    4) opponent      — tighten opponent model
    5) burden        — high-impact burden-of-proof line
    6) conclusion    — strong synthesis closer
    7) prayer        — canonical opener
    8) conditional   — soften fallback tone
    9) anti_pattern  — break opener repetition

Each pass is wrapped by INVARIANT CHECKS — if a pass reduces citation
count, section count, or fact-bullet count, it is rolled back.

If the final style score is below STYLE_FLOOR, the polish is rolled back
and a note is recorded. (The memo always ships; a weak polish never
replaces a readable MQE output.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.drafting.pasl import (
    precision, emphasis, flow, opponent_pressure, burden_emphasis,
    conclusion_power, prayer_polish, conditional_tone, anti_pattern,
    style_scorer,
)
from core.drafting.pasl.section_parser import (
    parse_memo, rebuild_memo, section_count, citation_count,
    fact_bullet_count,
    KIND_APPLICATION, KIND_OPPONENT, KIND_PROOF_BURDEN, KIND_CONCLUSION,
    KIND_PRAYER, KIND_CONDITIONAL, KIND_REPLY_POINTS, KIND_SUBST_DEF,
    KIND_PROC_DEF,
)
from core.drafting.pasl.style_scorer import (
    StyleScore, score_style, STYLE_FLOOR,
)


@dataclass
class PASLResult:
    text:            str = ""
    original_text:   str = ""
    applied_passes:  list[str] = field(default_factory=list)
    style_before:    Optional[StyleScore] = None
    style_after:     Optional[StyleScore] = None
    rolled_back:     bool = False
    rollback_reason: str = ""
    notes:           list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text_len":        len(self.text),
            "applied_passes":  self.applied_passes,
            "style_before":    self.style_before.to_dict() if self.style_before else {},
            "style_after":     self.style_after.to_dict() if self.style_after else {},
            "rolled_back":     self.rolled_back,
            "rollback_reason": self.rollback_reason,
            "notes":           self.notes[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Invariant check
# ═════════════════════════════════════════════════════════════════

def _invariants_preserved(before: str, after: str) -> tuple[bool, str]:
    """Section count, citation count, and fact-bullet count MUST NOT drop."""
    if section_count(after) < section_count(before):
        return False, f"section_count:{section_count(before)}->{section_count(after)}"
    if citation_count(after) < citation_count(before):
        return False, f"citation_count:{citation_count(before)}->{citation_count(after)}"
    if fact_bullet_count(after) < fact_bullet_count(before):
        return False, f"fact_bullet_count:{fact_bullet_count(before)}->{fact_bullet_count(after)}"
    return True, ""


# ═════════════════════════════════════════════════════════════════
# Pass runners — each returns (new_text, applied: bool)
# ═════════════════════════════════════════════════════════════════

def _apply_precision(parsed, *, is_conditional_global: bool):
    """Tier-scrub remaining weak phrases across ALL non-conditional sections."""
    touched = False
    for seg in parsed.segments:
        if seg.kind == KIND_CONDITIONAL:
            continue
        new_body = precision.tighten(
            seg.body, is_conditional_context=False,
        )
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_emphasis(parsed):
    """Strengthen argument leads in application/reply sections."""
    touched = False
    target_kinds = {KIND_APPLICATION, KIND_REPLY_POINTS,
                     KIND_SUBST_DEF, KIND_PROC_DEF}
    for i, seg in enumerate(parsed.segments):
        if seg.kind not in target_kinds:
            continue
        new_body = emphasis.strengthen_argument_leads(
            seg.body, base_idx=i,
        )
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_flow(parsed):
    """Add inter-argument transitions inside the application section, and
    section-leads for conclusion/prayer/opponent blocks."""
    touched = False
    for i, seg in enumerate(parsed.segments):
        if seg.kind == KIND_APPLICATION:
            new_body = flow.smooth_between_arguments(seg.body, base_idx=i)
            if new_body != seg.body:
                seg.body = new_body
                touched = True
        elif seg.kind in {KIND_CONCLUSION, KIND_PRAYER, KIND_OPPONENT}:
            lead_key = {
                KIND_CONCLUSION: "conclusion",
                KIND_PRAYER:     "prayer",
                KIND_OPPONENT:   "opponent",
            }[seg.kind]
            new_body = flow.add_section_lead(seg.body, kind=lead_key)
            if new_body != seg.body:
                seg.body = new_body
                touched = True
    return touched


def _apply_opponent(parsed):
    touched = False
    for seg in parsed.segments:
        if seg.kind != KIND_OPPONENT:
            continue
        new_body = opponent_pressure.polish_opponent_block(seg.body)
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_burden(parsed, *, client_side: str):
    touched = False
    for i, seg in enumerate(parsed.segments):
        if seg.kind != KIND_PROOF_BURDEN:
            continue
        new_body = burden_emphasis.polish_burden_block(
            seg.body, client_side=client_side, base_idx=i,
        )
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_conclusion(parsed, *, client_side: str):
    touched = False
    for seg in parsed.segments:
        if seg.kind != KIND_CONCLUSION:
            continue
        new_body = conclusion_power.polish_conclusion(
            seg.body, client_side=client_side,
        )
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_prayer(parsed):
    touched = False
    for seg in parsed.segments:
        if seg.kind != KIND_PRAYER:
            continue
        new_body = prayer_polish.polish_prayer_block(seg.body)
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_conditional(parsed):
    """Only touches sections of kind CONDITIONAL."""
    touched = False
    for seg in parsed.segments:
        if seg.kind != KIND_CONDITIONAL:
            continue
        new_body = conditional_tone.polish_conditional_block(seg.body)
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


def _apply_anti_pattern(parsed):
    """Break repeated paragraph openers inside application & reply blocks."""
    touched = False
    target_kinds = {KIND_APPLICATION, KIND_REPLY_POINTS, KIND_SUBST_DEF}
    for seg in parsed.segments:
        if seg.kind not in target_kinds:
            continue
        new_body = anti_pattern.break_opener_patterns(seg.body)
        if new_body != seg.body:
            seg.body = new_body
            touched = True
    return touched


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def polish(
    text: str,
    *,
    is_conditional_context: bool = False,
    client_side: str = "neutral",
) -> PASLResult:
    """Apply PASL style passes to an MQE-composed memo.

    Always returns a PASLResult. If invariants break or the style score
    regresses past tolerance, the original text is returned and
    rolled_back is True (the caller can still trust the text).
    """
    result = PASLResult(original_text=text or "", text=text or "")
    if not text or not text.strip():
        return result

    result.style_before = score_style(text)

    parsed = parse_memo(text)
    if not parsed.segments:
        # Unstructured text (e.g. NOT_DRAFTABLE message) — we only do
        # precision tightening in that case to avoid breaking formatting.
        # But since there's no conditional frame and no prayer/application,
        # the risk is low.
        tighter = precision.tighten(
            text, is_conditional_context=is_conditional_context,
        )
        ok, why = _invariants_preserved(text, tighter)
        if ok:
            result.text = tighter
            result.applied_passes.append("precision_unstructured")
        else:
            result.rolled_back = True
            result.rollback_reason = why
        result.style_after = score_style(result.text)
        return result

    # Structured memo — run full pass chain
    passes: list[tuple[str, callable]] = [
        ("precision",    lambda: _apply_precision(parsed,
                                                     is_conditional_global=is_conditional_context)),
        ("emphasis",     lambda: _apply_emphasis(parsed)),
        ("flow",         lambda: _apply_flow(parsed)),
        ("opponent",     lambda: _apply_opponent(parsed)),
        ("burden",       lambda: _apply_burden(parsed,
                                                  client_side=client_side)),
        ("conclusion",   lambda: _apply_conclusion(parsed,
                                                      client_side=client_side)),
        ("prayer",       lambda: _apply_prayer(parsed)),
        ("conditional",  lambda: _apply_conditional(parsed)),
        ("anti_pattern", lambda: _apply_anti_pattern(parsed)),
    ]

    # Apply each pass with an invariant checkpoint
    for name, runner in passes:
        before = rebuild_memo(parsed)
        changed = runner()
        if not changed:
            continue
        after = rebuild_memo(parsed)
        ok, why = _invariants_preserved(before, after)
        if not ok:
            # Roll THIS pass back by re-parsing the BEFORE text
            result.notes.append(f"pass_rolled_back:{name}:{why}")
            parsed = parse_memo(before)
            continue
        result.applied_passes.append(name)

    final = rebuild_memo(parsed)

    # Compare overall invariants vs the original
    ok, why = _invariants_preserved(text, final)
    if not ok:
        result.text = text
        result.rolled_back = True
        result.rollback_reason = why
        result.style_after = result.style_before
        return result

    result.text = final
    result.style_after = score_style(final)

    # Guard: regression check
    if (result.style_after.overall < result.style_before.overall - 0.10):
        # Significant regression — fall back to original
        result.text = text
        result.rolled_back = True
        result.rollback_reason = (
            f"style_regression:{result.style_before.overall:.2f}"
            f"->{result.style_after.overall:.2f}"
        )
        result.style_after = result.style_before
    return result
