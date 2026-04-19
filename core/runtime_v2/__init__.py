# -*- coding: utf-8 -*-
"""
runtime_v2 — ground-up legal analytics runtime.

Public API
==========
    from core.runtime_v2 import answer
    resp = answer("…")
    resp.to_dict()

Runtime contract
================
  • Single entry point: `answer(query) -> Response`.
  • Single output shape: `Response` (and `Response.to_dict()`).
  • Single final-text author (core.runtime_v2.composer).
  • No calls to any legacy composer, drafting helper, or insufficiency
    text. No fallback to any pre-v2 runtime.
  • Scope: the four pilot cases — employment-vs-partnership,
    guarantee-cheque, death-illness-vs-debt, code-ownership-prior-libs.
  • Out-of-scope queries return a skeleton Response (never a refusal
    shape from the old system).
"""
from __future__ import annotations

from core.runtime_v2.pipeline import answer
from core.runtime_v2.types import (
    DomainKey, DraftingMode, Intent, ReasoningMode, Response,
    PathHypothesis, Pivot, EvidenceItem, FactMarker, Issue, DomainRules,
)

__all__ = [
    "answer",
    # Enumerations
    "DomainKey", "Intent", "ReasoningMode", "DraftingMode",
    # Data classes
    "Response", "PathHypothesis", "Pivot", "EvidenceItem",
    "FactMarker", "Issue", "DomainRules",
]
