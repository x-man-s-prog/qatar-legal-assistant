# -*- coding: utf-8 -*-
"""
PASL — Argument Emphasis.

Replaces bland leads like "يثبت كذا" with varied, decisive phrasings:
  • "الثابت من الوقائع أن..."
  • "ومؤدى ذلك أن..."
  • "ولا يغير من ذلك..."
  • "وعليه فإن..."

Rotation is deterministic (based on paragraph index in the section) so
no two neighboring paragraphs lead with the same phrase.
"""
from __future__ import annotations

import re


_AR = r"[\u0621-\u064A]"
_PREFIX = r"([وفلبكس]?)"


# ═════════════════════════════════════════════════════════════════
# Decisive lead banks (rotated per paragraph)
# ═════════════════════════════════════════════════════════════════

_ASSERTIVE_LEADS = [
    "الثابت من الأوراق أن",
    "ومقتضى ذلك أن",
    "ومؤدى ذلك أن",
    "والمستفاد من الوقائع أن",
    "وعليه فإن",
    "ولا يغيِّر من ذلك",
]


_BLAND_STARTERS = [
    # (pattern, replacement-index into _ASSERTIVE_LEADS)
    (re.compile(rf"^{_PREFIX}يثبت\s+أن\s+", re.MULTILINE), 0),
    (re.compile(rf"^{_PREFIX}يثبت\s+", re.MULTILINE),       0),
    (re.compile(rf"^{_PREFIX}يظهر\s+أن\s+", re.MULTILINE),  3),
    (re.compile(rf"^{_PREFIX}يتضح\s+أن\s+", re.MULTILINE),  1),
    (re.compile(rf"^{_PREFIX}ظهر\s+أن\s+", re.MULTILINE),   3),
]


# ═════════════════════════════════════════════════════════════════
# Consequence markers — replace bland follow-up sentences
# ═════════════════════════════════════════════════════════════════

_CONSEQUENCE_REWRITES = [
    # "ولذلك فإن" is frequent and flat → vary
    (re.compile(rf"(?<!{_AR}){_PREFIX}ولذلك فإن"),
        ["\\1وعليه فإن", "\\1ومقتضى ذلك أن", "\\1ومؤدى ذلك أن"]),
    # "ومن ثم" alone is flat → tighten
    (re.compile(rf"(?<!{_AR}){_PREFIX}ومن ثم\s+فإن"),
        ["\\1ومن ثم فإن", "\\1وعلى ذلك فإن"]),
]


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def _rotate(idx: int, bank: list[str]) -> str:
    return bank[idx % len(bank)]


def strengthen_argument_leads(body: str, *, base_idx: int = 0) -> str:
    """Replace bland paragraph openers with assertive leads, rotated."""
    if not body:
        return ""
    paragraphs = body.split("\n\n")
    out: list[str] = []
    idx = base_idx
    for para in paragraphs:
        p = para
        replaced = False
        for pat, lead_idx in _BLAND_STARTERS:
            # Rotate the exact lead we inject so neighbors differ
            lead = _rotate(idx + lead_idx, _ASSERTIVE_LEADS)
            new = pat.sub(lambda m: f"{m.group(1) or ''}{lead} ", p, count=1)
            if new != p:
                p = new
                idx += 1
                replaced = True
                break
        # Reword repeated "ولذلك فإن" in the body
        for pat, alternates in _CONSEQUENCE_REWRITES:
            hits = pat.findall(p)
            if hits:
                # Keep first occurrence, rewrite subsequent ones
                def _r(match, counter=[0]):
                    counter[0] += 1
                    if counter[0] == 1:
                        return match.group(0)
                    alt = alternates[(idx + counter[0]) % len(alternates)]
                    # alt still has \1 placeholder — render it manually
                    return re.sub(r"\\1", match.group(1) or "", alt)
                p = pat.sub(_r, p)
        out.append(p)
    return "\n\n".join(out)


def count_bland_leads(text: str) -> int:
    if not text:
        return 0
    return sum(len(pat.findall(text)) for pat, _ in _BLAND_STARTERS)
