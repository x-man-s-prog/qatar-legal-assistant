# -*- coding: utf-8 -*-
"""
PASL — Precision Language.

Replaces remaining weak/hedged language with decisive legal register.
Complements (does NOT duplicate) MQE's style.py — this layer targets
residual phrases that survive MQE and operate at the SENTENCE level.

Rules:
  • Conditional / fallback sections are EXEMPT (they NEED hedged language).
  • Every replacement preserves the Arabic prefix (و / ف / ل / ب / ك / س).
  • Never strengthens a hedge into a statement of fact the memo cannot back.
"""
from __future__ import annotations

import re


_AR = r"[\u0621-\u064A]"
_PREFIX = r"([وفلبكس]?)"

# Tier 1 — bland/hedged → decisive legal register
_TIER_1 = [
    (re.compile(rf"(?<!{_AR}){_PREFIX}من الواضح(?!{_AR})"),
        r"\1الثابت"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}من المعلوم(?!{_AR})"),
        r"\1من المستقر"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}يمكن القول(?!{_AR})"),
        r"\1يتعيَّن القول"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}من الممكن(?!{_AR})"),
        r"\1من المتعيَّن"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}نفترض(?!{_AR})"),
        r"\1يترجّح"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}نظن(?!{_AR})"),
        r"\1يترجّح"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}من المحتمل(?!{_AR})"),
        r"\1يترجّح أن"),
]

# Tier 2 — generic evidence lead-ins → specific legal register
_TIER_2 = [
    (re.compile(rf"(?<!{_AR}){_PREFIX}يوجد دليل على(?!{_AR})"),
        r"\1قام الدليل على"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}يُظهر هذا(?!{_AR})"),
        r"\1ومؤدى ذلك"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}نستنتج(?!{_AR})"),
        r"\1يُستخلص"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}نلاحظ(?!{_AR})"),
        r"\1يتبيَّن"),
    # Assistant-style phrasing leaks ("يمكنك / ينبغي لك") — strip them entirely
    (re.compile(rf"(?<!{_AR}){_PREFIX}يمكنك أن(?!{_AR})"),
        r"\1"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}ينبغي لك(?!{_AR})"),
        r"\1"),
]

# Tier 3 — colloquial / robotic markers
_TIER_3 = [
    (re.compile(rf"(?<!{_AR}){_PREFIX}بشكل كبير(?!{_AR})"),
        r"\1بدرجة جوهرية"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}بشكل واضح(?!{_AR})"),
        r"\1بوضوح"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}بشكل عام(?!{_AR})"),
        r"\1إجمالاً"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}بشكل خاص(?!{_AR})"),
        r"\1تخصيصاً"),
]

_ALL_TIERS = _TIER_1 + _TIER_2 + _TIER_3


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def tighten(text: str, *, is_conditional_context: bool = False) -> str:
    """Apply precision substitutions. Conditional text is untouched."""
    if not text or is_conditional_context:
        return text or ""
    out = text
    for pat, repl in _ALL_TIERS:
        out = pat.sub(repl, out)
    # Clean up any double spaces the empty replacements may have left
    out = re.sub(r"  +", " ", out)
    return out


def count_imprecise_phrases(text: str) -> int:
    if not text:
        return 0
    return sum(len(pat.findall(text)) for pat, _ in _ALL_TIERS)
