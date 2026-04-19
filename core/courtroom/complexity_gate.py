# -*- coding: utf-8 -*-
"""
Complexity Gate — decides which Tier handles a query.

Deterministic rule-based classifier. No LLM. Output controls reasoning
depth so simple lookups don't pay for opponent modeling.

Tiers:
  Tier 0 — HARD_FAST_PATH   : exact article lookup / single-fact answer
  Tier 1 — STANDARD_REASONING: 1 issue, evidence direct, no adversary
  Tier 2 — ADVERSARIAL       : 2 stories, burden matters, mixed evidence
  Tier 3 — COURTROOM         : multi-issue, multi-party, procedural,
                                conflicting evidence, opponent modeling
                                required

Signal axes (each contributes weight):
  - query length (words)
  - exact-article markers ("المادة X")
  - adversarial markers (هو قال/هي قالت/الشركة تقول/يدّعي)
  - multi-party markers (الورثة/الشركاء/الأطراف)
  - procedural markers (طعن/استئناف/تمييز/إجراءات)
  - evidence markers (شهود/رسائل/تقارير)
  - conflicting evidence markers (متضارب/متناقض/مزور)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ComplexityTier(str, Enum):
    HARD_FAST_PATH      = "tier_0_lookup"
    STANDARD_REASONING  = "tier_1_standard"
    ADVERSARIAL         = "tier_2_adversarial"
    COURTROOM           = "tier_3_courtroom"

    def reasoning_budget(self) -> dict:
        """Hard budgets per tier — TIGHTENED for ultra-fast default."""
        return {
            ComplexityTier.HARD_FAST_PATH: {
                "max_evidence":    2,        # was 3 — tightened
                "max_branches":    0,
                "opponent_model":  False,
                "decisive_detect": False,
                "outcome_framing": False,
                "courtroom_active": False,    # NEW — explicit gate
            },
            ComplexityTier.STANDARD_REASONING: {
                "max_evidence":    3,        # was 5 — tightened
                "max_branches":    0,
                "opponent_model":  False,
                "decisive_detect": False,    # was True — disabled for fast path
                "outcome_framing": False,
                "courtroom_active": False,    # NEW — courtroom OFF by default
            },
            ComplexityTier.ADVERSARIAL: {
                "max_evidence":    5,        # was 6
                "max_branches":    2,
                "opponent_model":  True,
                "decisive_detect": True,
                "outcome_framing": True,
                "courtroom_active": True,    # NEW — courtroom ON for T2+
            },
            ComplexityTier.COURTROOM: {
                "max_evidence":    7,        # was 8
                "max_branches":    4,
                "opponent_model":  True,
                "decisive_detect": True,
                "outcome_framing": True,
                "courtroom_active": True,
            },
        }[self]


@dataclass
class ComplexityVerdict:
    tier:           ComplexityTier
    score:          int
    signals:        list[str] = field(default_factory=list)
    word_count:     int = 0
    has_article_ref: bool = False
    is_adversarial: bool = False
    is_multi_issue: bool = False
    has_procedural: bool = False
    has_evidence_terms: bool = False
    has_conflict:   bool = False

    def to_dict(self) -> dict:
        return {
            "tier":              self.tier.value,
            "score":             self.score,
            "signals":           self.signals,
            "word_count":        self.word_count,
            "has_article_ref":   self.has_article_ref,
            "is_adversarial":    self.is_adversarial,
            "is_multi_issue":    self.is_multi_issue,
            "has_procedural":    self.has_procedural,
            "has_evidence_terms": self.has_evidence_terms,
            "has_conflict":      self.has_conflict,
            "budget":            self.tier.reasoning_budget(),
        }


# ── Marker sets (single-pass detection) ──

_ARTICLE_RE = re.compile(r"المادة\s+\d+", re.UNICODE)

_ADVERSARIAL = (
    "يدّعي", "يدعي", "يقول", "تقول", "زعم", "تزعم", "يدفع",
    "يحاجج", "ينازع", "يطعن",
    "الشركة تقول", "هو قال", "هي قالت",
    "متهم", "متهمة", "خصمي", "ضدي",
    # Adversarial-narrative connectors
    "بينما", "في حين", "بحجة", "بزعم", "في المقابل",
    "الطرف الآخر", "الخصم",
)

_MULTI_PARTY = (
    "ورثة", "الورثة", "الشركاء", "الأطراف",
    "ثلاثة أطراف", "أطراف متعددة",
)

_MULTI_ISSUE = (
    "بالإضافة", "علاوة على", "أيضاً", "كذلك", "وفي نفس الوقت",
)

_PROCEDURAL = (
    "طعن", "تمييز", "نقض", "استئناف", "إجراءات",
    "حكم مستعجل", "أمر وقتي", "تنفيذ حكم",
    "اختصاص", "صلاحية المحكمة",
)

_EVIDENCE = (
    "شهود", "شاهد", "رسائل", "واتساب", "إيميلات",
    "تقارير", "وثائق", "إيصالات", "فواتير", "محضر",
    "صور", "تسجيل صوتي", "كاميرا",
)

_CONFLICT = (
    "متضارب", "متناقض", "مزور", "نزاع",
    "متضاربة", "متناقضة", "مختلف عليها",
)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def classify_complexity(query: str) -> ComplexityVerdict:
    """Map query → ComplexityTier. Pure function, no I/O."""
    q = query or ""
    words = q.split()
    wc = len(words)

    has_article    = bool(_ARTICLE_RE.search(q))
    is_adversarial = _has_any(q, _ADVERSARIAL)
    is_multi_issue = _has_any(q, _MULTI_ISSUE) or _has_any(q, _MULTI_PARTY)
    has_procedural = _has_any(q, _PROCEDURAL)
    has_evidence   = _has_any(q, _EVIDENCE)
    has_conflict   = _has_any(q, _CONFLICT)

    signals: list[str] = []
    score = 0

    # Length contribution
    if wc < 8:
        score += 0
    elif wc < 16:
        score += 1
    elif wc < 30:
        score += 2
    else:
        score += 3
        signals.append("long_narrative")

    if has_article and wc < 12:
        score -= 1   # bias toward Tier 0 for short article lookup
        signals.append("article_lookup")
    if is_adversarial:
        score += 2
        signals.append("adversarial_markers")
    if is_multi_issue:
        score += 2
        signals.append("multi_issue")
    if has_procedural:
        score += 1
        signals.append("procedural_markers")
    if has_evidence:
        score += 1
        signals.append("evidence_referenced")
    if has_conflict:
        score += 2
        signals.append("conflicting_evidence_signal")

    # Map score → tier (FAST-DEFAULT BIAS: T0/T1 are default).
    # Tier 2/3 require STRONG adversarial signals AND additional markers.
    if score <= 1:
        tier = ComplexityTier.HARD_FAST_PATH
    elif score <= 4:
        tier = ComplexityTier.STANDARD_REASONING
    elif is_adversarial and (has_evidence or has_conflict or is_multi_issue):
        # Require explicit adversarial marker + at least one supporting signal
        if (is_adversarial and is_multi_issue
                and (has_procedural or has_conflict)):
            tier = ComplexityTier.COURTROOM
        else:
            tier = ComplexityTier.ADVERSARIAL
    else:
        # High score but no adversarial → still standard
        tier = ComplexityTier.STANDARD_REASONING
        signals.append("downgraded_no_adversarial")

    return ComplexityVerdict(
        tier=tier, score=score, signals=signals,
        word_count=wc,
        has_article_ref=has_article,
        is_adversarial=is_adversarial,
        is_multi_issue=is_multi_issue,
        has_procedural=has_procedural,
        has_evidence_terms=has_evidence,
        has_conflict=has_conflict,
    )
