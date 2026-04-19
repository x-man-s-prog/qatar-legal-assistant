# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — 7-Dimensional Quality Score.

Scores every memo on seven axes, each 0..1:
  1. structure            — required sections present + ordered
  2. legal_grounding      — canonical citations present + applied
  3. issue_coverage       — arguments per issue in the graph
  4. evidence_application — arguments use the bound evidence
  5. request_precision    — prayer is precise, not vague
  6. language_quality     — no hedges, no robotic repetition
  7. anti_repetition      — no duplicate openers/sentences/bullets

Below QUALITY_FLOOR → force DRAFTABLE_WITH_ASSUMPTIONS or downgrade.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from core.drafting.drafting_engine import DocumentType
from core.drafting.mqe.argument import LegalArgument
from core.drafting.mqe.prayer import Prayer, is_vague_prayer
from core.drafting.mqe.style import (
    count_weak_words, count_role_leaks, count_repeated_openers,
)


QUALITY_FLOOR          = 0.45    # overall score below this → downgrade
STRONG_QUALITY_FLOOR   = 0.65    # above this → DRAFTABLE fully


@dataclass
class MemoQualityScore:
    structure:            float = 0.0
    legal_grounding:      float = 0.0
    issue_coverage:       float = 0.0
    evidence_application: float = 0.0
    request_precision:    float = 0.0
    language_quality:     float = 0.0
    anti_repetition:      float = 0.0
    overall:              float = 0.0
    notes:                list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "structure":            round(self.structure, 3),
            "legal_grounding":      round(self.legal_grounding, 3),
            "issue_coverage":       round(self.issue_coverage, 3),
            "evidence_application": round(self.evidence_application, 3),
            "request_precision":    round(self.request_precision, 3),
            "language_quality":     round(self.language_quality, 3),
            "anti_repetition":      round(self.anti_repetition, 3),
            "overall":              round(self.overall, 3),
            "notes":                self.notes[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Per-axis scorers
# ═════════════════════════════════════════════════════════════════

_REQUIRED_SECTIONS = {
    DocumentType.DEFENSE_MEMO:   ["issues", "statute", "application", "prayer"],
    DocumentType.CLAIM_BRIEF:    ["facts", "issues", "statute", "prayer"],
    DocumentType.REPLY_MEMO:     ["reply", "prayer"],
    DocumentType.DEFENSE_CHECKLIST: ["defense"],
    DocumentType.PLEADING_POINTS:[ "application", "prayer"],
    DocumentType.PETITION_MEMO:  ["statute", "prayer"],
}


_SECTION_MARKERS = {
    "facts":       ["موجز الوقائع", "الوقائع الثابتة"],
    "issues":      ["المسائل القانونية"],
    "statute":     ["السند القانوني", "السند الحاكم"],
    "application": ["التطبيق على الوقائع"],
    "prayer":      ["الطلبات", "أصلياً:"],
    "reply":       ["الرد التفصيلي", "موجز دفوع الخصم"],
    "defense":     ["دفوع إجرائية", "دفوع موضوعية", "قائمة الدفوع"],
}


def _score_structure(text: str, doc_type: DocumentType) -> float:
    required = _REQUIRED_SECTIONS.get(doc_type,
                                       ["issues", "statute", "prayer"])
    hit = 0
    for req in required:
        markers = _SECTION_MARKERS.get(req, [])
        if any(m in text for m in markers):
            hit += 1
    return round(hit / max(1, len(required)), 3)


def _score_legal_grounding(text: str, cited_laws: list[str],
                              arguments: list[LegalArgument]) -> float:
    """Citations must be present AND applied in arguments."""
    if not cited_laws:
        return 0.0 if not arguments else 0.25
    cited_in_body = sum(1 for c in cited_laws if c and c in text)
    score = 0.30 + 0.50 * (cited_in_body / max(1, len(cited_laws)))
    if arguments:
        applied = sum(1 for a in arguments if a.statute_refs)
        score += 0.20 * (applied / max(1, len(arguments)))
    return round(min(1.0, score), 3)


def _score_issue_coverage(arguments: list[LegalArgument],
                              issue_count: int) -> float:
    if issue_count <= 0:
        return 0.0
    distinct = len({a.issue_id for a in arguments if a.issue_id})
    ratio = distinct / issue_count
    # Cap at 1.0 (more args than issues doesn't help)
    return round(min(1.0, ratio), 3)


def _score_evidence_application(arguments: list[LegalArgument]) -> float:
    if not arguments:
        return 0.0
    have_ev = sum(1 for a in arguments if a.evidence_refs)
    return round(have_ev / len(arguments), 3)


def _score_request_precision(prayer: Prayer) -> float:
    total = len(prayer.primary) + len(prayer.alternative) + len(prayer.fallback)
    if total == 0:
        return 0.0
    vague = sum(1 for r in prayer.primary + prayer.alternative + prayer.fallback
                if is_vague_prayer(r))
    if vague >= total:
        return 0.0
    return round(1.0 - (vague / total), 3)


def _score_language_quality(text: str,
                                 is_conditional_context: bool = False) -> float:
    if not text:
        return 0.0
    length = max(1, len(text))
    role_leaks = count_role_leaks(text)
    weak = count_weak_words(text) if not is_conditional_context else 0
    # Penalties scaled by text length (per-1000 chars)
    density = 1000.0 / length
    leak_pen = min(0.5, role_leaks * 0.15 * density)
    weak_pen = min(0.3, weak * 0.05 * density)
    return round(max(0.0, 1.0 - leak_pen - weak_pen), 3)


def _score_anti_repetition(text: str, arguments: list[LegalArgument]) -> float:
    if not text:
        return 0.0
    repeated = count_repeated_openers(text)
    # Count duplicate-ish argument claims
    seen: set[str] = set()
    dup_claims = 0
    for a in arguments:
        sig = (a.claim or "").strip()[:60]
        if not sig:
            continue
        if sig in seen:
            dup_claims += 1
        seen.add(sig)
    penalty = min(0.70, repeated * 0.10 + dup_claims * 0.12)
    return round(max(0.0, 1.0 - penalty), 3)


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def score_memo(
    text: str,
    doc_type: DocumentType,
    arguments: list[LegalArgument],
    prayer: Prayer,
    cited_laws: list[str],
    issue_count: int,
    is_conditional_context: bool = False,
) -> MemoQualityScore:
    """Compute the 7-axis score for a rendered memo."""
    s = MemoQualityScore()
    s.structure            = _score_structure(text, doc_type)
    s.legal_grounding      = _score_legal_grounding(text, cited_laws, arguments)
    s.issue_coverage       = _score_issue_coverage(arguments, issue_count)
    s.evidence_application = _score_evidence_application(arguments)
    s.request_precision    = _score_request_precision(prayer)
    s.language_quality     = _score_language_quality(
        text, is_conditional_context=is_conditional_context,
    )
    s.anti_repetition      = _score_anti_repetition(text, arguments)

    # Weighted overall — structure + grounding carry most
    overall = (
        0.18 * s.structure
        + 0.18 * s.legal_grounding
        + 0.16 * s.issue_coverage
        + 0.14 * s.evidence_application
        + 0.14 * s.request_precision
        + 0.12 * s.language_quality
        + 0.08 * s.anti_repetition
    )
    s.overall = round(overall, 3)

    # Notes
    if s.structure < 0.6:
        s.notes.append("structure_below_0.6")
    if s.legal_grounding < 0.5:
        s.notes.append("legal_grounding_below_0.5")
    if s.issue_coverage < 0.5:
        s.notes.append("issue_coverage_below_0.5")
    if s.request_precision < 0.6:
        s.notes.append("request_precision_below_0.6")
    if s.language_quality < 0.7:
        s.notes.append("language_quality_below_0.7")
    return s


def is_acceptable(score: MemoQualityScore,
                    minimum: float = QUALITY_FLOOR) -> bool:
    return score.overall >= minimum


def is_publication_ready(score: MemoQualityScore) -> bool:
    return score.overall >= STRONG_QUALITY_FLOOR
