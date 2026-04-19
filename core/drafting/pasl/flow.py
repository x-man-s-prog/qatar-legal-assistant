# -*- coding: utf-8 -*-
"""
PASL — Flow Smoothing.

Inserts inter-paragraph transitions so the reader walks from one idea
to the next without jarring jumps. Transitions are rotated so the memo
doesn't fall into a "وبالانتقال إلى..." × 5 rhythm.

Transition banks:
  • BETWEEN arguments     — "وبالانتقال إلى..."  / "أما عن..."
  • BEFORE conclusion    — "تأسيساً على ما تقدَّم..."
  • BEFORE opponent     — "وفي معرض الرد على ما قد يدفع به الخصم..."
  • BEFORE prayer       — "ولهذه الأسباب جميعها..."

Rules:
  • Only insert when the current paragraph does NOT already start with a
    transition phrase.
  • Headings (**...**), bullet lines, and ordinal labels are not touched.
  • Pre-existing hand-crafted transitions are left untouched.
"""
from __future__ import annotations

import re


# ═════════════════════════════════════════════════════════════════
# Transition banks
# ═════════════════════════════════════════════════════════════════

_BETWEEN_ARGS = [
    "وبالانتقال إلى ",
    "أما عن ",
    "وفي الشأن ذاته، ",
    "وعلى هذا الأساس، ",
]

_BEFORE_CONCLUSION = "تأسيساً على ما تقدَّم، "
_BEFORE_OPPONENT   = "وفي معرض الرد على ما قد يدفع به الخصم، "
_BEFORE_PRAYER     = "ولهذه الأسباب جميعها، "


# Phrases that indicate the paragraph ALREADY leads with a transition
_EXISTING_TRANSITIONS = (
    "وبالانتقال",
    "أما عن",
    "وفي الشأن",
    "وعلى هذا الأساس",
    "تأسيساً على",
    "ولهذه الأسباب",
    "وفي معرض",
    "ومؤدى ذلك",
    "ومقتضى ذلك",
    "وعليه",
    "ومن ثم",
    "والمستفاد",
    "والثابت",
    "الثابت من",
    "من المستقر",
    "من المقرر",
    "من الثابت",
    "من البيّن",
    "ولمّا كان",
    "وحيث إن",
    "ولا يغيِّر",
    "ويُردّ",
    "ومردود",
    "غير أن",
    "إلا أن",
)


def _has_transition(para: str) -> bool:
    low = para.lstrip()
    if low.startswith(("**", "•", "—", "(")):
        return True
    return any(low.startswith(t) for t in _EXISTING_TRANSITIONS)


def _is_structural(para: str) -> bool:
    """A header, heading, bullet, or numbered-list line — do not touch."""
    low = para.strip()
    if not low:
        return True
    if low.startswith("**"):
        return True
    if low.startswith("•") or low.startswith("—"):
        return True
    if re.match(r"^\(\d+\)", low):
        return True
    if re.match(r"^\d+[\-.)]", low):
        return True
    return False


# ═════════════════════════════════════════════════════════════════
# Section-level transitions
# ═════════════════════════════════════════════════════════════════

def smooth_between_arguments(body: str, *, base_idx: int = 0) -> str:
    """Within the application section, add transitions BETWEEN argument
    headings ONLY — never inside the body of an argument."""
    if not body:
        return ""
    # Split into "blocks" by the argument-heading pattern "**(N) بشأن: ...**"
    arg_header_re = re.compile(r"^(\*\*\(\d+\)\s+بشأن:[^*]+\*\*)$",
                                  re.MULTILINE)

    lines = body.split("\n")
    transformed: list[str] = []
    arg_idx = 0
    for line in lines:
        m = arg_header_re.match(line)
        if m and arg_idx > 0:
            # Insert an empty line before the next argument if not already there
            if transformed and transformed[-1].strip() != "":
                transformed.append("")
            # Prepend the transition as a short sentence line before the header
            pre = _BETWEEN_ARGS[(base_idx + arg_idx) % len(_BETWEEN_ARGS)]
            pre_clean = pre.rstrip()
            # Ensure a clean space between the transition and the follow-up
            transformed.append(pre_clean + " ما يلي:")
            transformed.append("")
            transformed.append(line)
            arg_idx += 1
            continue
        if m and arg_idx == 0:
            arg_idx += 1
            transformed.append(line)
            continue
        transformed.append(line)

    return "\n".join(transformed)


def add_section_lead(body: str, kind: str) -> str:
    """Prepend a short sentence to the section body when natural.

    Used for: conclusion, prayer, opponent model.
    Only prepended when the first paragraph does NOT already lead with
    a transition phrase.
    """
    if not body or _is_structural(body.split("\n", 1)[0]):
        return body

    lead = {
        "conclusion": _BEFORE_CONCLUSION,
        "prayer":     _BEFORE_PRAYER,
        "opponent":   _BEFORE_OPPONENT,
    }.get(kind, "")
    if not lead:
        return body

    first_para = body.split("\n\n", 1)[0]
    if _has_transition(first_para):
        return body
    # Guard against MQE's own conclusion openers
    if kind == "conclusion" and any(
        m in first_para for m in (
            "يتبيّن مما تقدَّم", "يتبيّن مما تقدّم",
            "يتّضح مما تقدَّم", "يتّضح مما تقدّم",
            "يُستخلص مما تقدَّم", "يُستخلص مما تقدّم",
        )
    ):
        return body

    return lead + body.lstrip()


def count_missing_transitions(body: str, *, min_args_expected: int = 2) -> int:
    """Count how many argument blocks lack a leading transition."""
    if not body:
        return 0
    arg_header_re = re.compile(r"^\*\*\(\d+\)\s+بشأن:", re.MULTILINE)
    hits = arg_header_re.findall(body)
    if len(hits) < min_args_expected:
        return 0
    # Walk: count headings that are NOT preceded by a transition line
    missing = 0
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if not arg_header_re.match(line.strip()):
            continue
        # Look back for a transition line within 3 previous non-empty lines
        found = False
        for j in range(i - 1, max(-1, i - 4), -1):
            prev = lines[j].strip()
            if not prev:
                continue
            if any(prev.startswith(t) for t in _EXISTING_TRANSITIONS):
                found = True
                break
            break
        if not found and i > 0:
            missing += 1
    return missing
