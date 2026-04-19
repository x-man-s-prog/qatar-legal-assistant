# -*- coding: utf-8 -*-
"""
PASL — Style Scorer.

Five axes, each 0..1:
  • persuasion_strength — presence of decisive leads & burden phrases
  • clarity             — sentence-length health, no overlong mega-sentences
  • flow                — transitions between argument blocks present
  • variation           — paragraph openers are not all identical
  • professionalism     — legal register, no colloquial markers

Overall = weighted mean. Caller decides whether to iterate a second
polish pass when overall < target.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.drafting.pasl import (
    precision, emphasis, flow, opponent_pressure,
    burden_emphasis, conclusion_power, anti_pattern,
)
from core.drafting.pasl.section_parser import (
    parse_memo,
    KIND_APPLICATION, KIND_OPPONENT, KIND_PROOF_BURDEN,
    KIND_CONCLUSION, KIND_PRAYER,
)


@dataclass
class StyleScore:
    persuasion_strength: float = 0.0
    clarity:             float = 0.0
    flow:                float = 0.0
    variation:           float = 0.0
    professionalism:     float = 0.0
    overall:             float = 0.0
    notes:               list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "persuasion_strength": round(self.persuasion_strength, 3),
            "clarity":             round(self.clarity, 3),
            "flow":                round(self.flow, 3),
            "variation":           round(self.variation, 3),
            "professionalism":     round(self.professionalism, 3),
            "overall":             round(self.overall, 3),
            "notes":               self.notes[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Persuasion strength
# ═════════════════════════════════════════════════════════════════

_DECISIVE_MARKERS = (
    "الثابت", "المستقر", "المقرر", "البيِّن", "مستقر القضاء",
    "ومؤدى ذلك", "ومقتضى ذلك", "يتعيَّن", "يتعيّن",
    "ولا يغيِّر من ذلك",
    "ولم يقدِّم", "خلوُّ الأوراق", "خلو الأوراق",
    "تأسيساً على ما تقدَّم", "وبناءً على ما تقدَّم",
)

_WEAK_MARKERS = (
    "يبدو", "ربما", "قد يكون", "من الممكن",
)


def _score_persuasion(text: str) -> float:
    if not text:
        return 0.0
    length = max(1, len(text))
    decisive = sum(text.count(m) for m in _DECISIVE_MARKERS)
    weak = sum(text.count(m) for m in _WEAK_MARKERS)
    density = 1000.0 / length
    positive = min(0.80, decisive * 0.12 * density + 0.20)
    penalty = min(0.40, weak * 0.15 * density)
    return round(max(0.0, min(1.0, positive - penalty + 0.20)), 3)


# ═════════════════════════════════════════════════════════════════
# Clarity — sentence-length health
# ═════════════════════════════════════════════════════════════════

def _score_clarity(text: str) -> float:
    if not text:
        return 0.0
    # Approximate sentences by splitting on "." / "؟" / "!"
    sentences = re.split(r"[.!؟]\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 0.0
    over_long = sum(1 for s in sentences if len(s) > 320)
    very_short = sum(1 for s in sentences if 0 < len(s) < 25)
    n = len(sentences)
    over_long_ratio = over_long / n
    very_short_ratio = very_short / n
    # Ideal: average sentence length 70–180 chars
    avg = sum(len(s) for s in sentences) / n
    window_penalty = 0.0
    if avg < 40 or avg > 260:
        window_penalty = 0.25
    penalty = min(0.6, over_long_ratio * 0.6 + very_short_ratio * 0.25
                  + window_penalty)
    return round(max(0.0, 1.0 - penalty), 3)


# ═════════════════════════════════════════════════════════════════
# Flow — transitions between argument blocks
# ═════════════════════════════════════════════════════════════════

def _score_flow(text: str) -> float:
    parsed = parse_memo(text)
    app = parsed.get(KIND_APPLICATION)
    if app is None or not app.body.strip():
        return 0.70  # neutral baseline when there is no application section
    missing = flow.count_missing_transitions(
        app.body, min_args_expected=2,
    )
    # Count total argument headings to make the penalty proportional
    arg_count = len(re.findall(r"^\*\*\(\d+\)\s+بشأن:", app.body, re.MULTILINE))
    if arg_count <= 1:
        return 0.90
    penalty = min(0.6, missing / max(1, arg_count))
    return round(1.0 - penalty, 3)


# ═════════════════════════════════════════════════════════════════
# Variation — no echo of the same opener
# ═════════════════════════════════════════════════════════════════

def _score_variation(text: str) -> float:
    if not text:
        return 0.0
    repeats = anti_pattern.count_repeated_openers(text)
    penalty = min(0.6, repeats * 0.15)
    return round(max(0.0, 1.0 - penalty), 3)


# ═════════════════════════════════════════════════════════════════
# Professionalism — register + colloquial markers
# ═════════════════════════════════════════════════════════════════

_COLLOQUIAL_MARKERS = (
    "يعني", "طبعاً", "باين", "بصراحة", "لازم",
)


def _score_professionalism(text: str) -> float:
    if not text:
        return 0.0
    imprecise = precision.count_imprecise_phrases(text)
    bland_leads = emphasis.count_bland_leads(text)
    colloq = sum(text.count(m) for m in _COLLOQUIAL_MARKERS)
    length = max(1, len(text))
    density = 1000.0 / length
    penalty = min(0.6, (imprecise * 0.05 + bland_leads * 0.08 + colloq * 0.20)
                  * density)
    return round(max(0.0, 1.0 - penalty), 3)


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def score_style(text: str) -> StyleScore:
    """Compute the 5-axis style score for an MQE+PASL-composed memo."""
    s = StyleScore()
    if not text or not text.strip():
        return s  # overall stays 0.0
    s.persuasion_strength = _score_persuasion(text)
    s.clarity             = _score_clarity(text)
    s.flow                = _score_flow(text)
    s.variation           = _score_variation(text)
    s.professionalism     = _score_professionalism(text)
    s.overall = round(
        0.26 * s.persuasion_strength
        + 0.18 * s.clarity
        + 0.18 * s.flow
        + 0.18 * s.variation
        + 0.20 * s.professionalism,
        3,
    )
    if s.persuasion_strength < 0.6:
        s.notes.append("persuasion_below_0.6")
    if s.flow < 0.6:
        s.notes.append("flow_below_0.6")
    if s.variation < 0.6:
        s.notes.append("variation_below_0.6")
    if s.professionalism < 0.7:
        s.notes.append("professionalism_below_0.7")
    return s


STYLE_FLOOR             = 0.55    # below this → iterate once
STRONG_STYLE_CEILING    = 0.75    # above this → publication-ready
