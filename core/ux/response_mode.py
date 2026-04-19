# -*- coding: utf-8 -*-
"""
Response Mode Assessor.

Given a MissingDataReport (and optionally the user's intent), classify
the response as:

  READY     — enough info; return full answer / memo
  PARTIAL   — useful analysis possible; still need 1-3 clarifications
  NOT_READY — too many critical gaps; ask questions first, no answer
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from core.ux.missing_data import MissingDataReport
from core.ux.user_intent import UserIntent


class ResponseMode(str, Enum):
    READY      = "ready"
    PARTIAL    = "partial"
    NOT_READY  = "not_ready"


def assess_readiness(
    report: MissingDataReport,
    intent: Optional[UserIntent] = None,
) -> ResponseMode:
    """Map report → response mode.

    Rules:
      - Drafting intent + blocks_drafting → NOT_READY (even if 0 gaps)
      - blocks_ruling → NOT_READY
      - 0 critical gaps AND 0 medium → READY
      - 0 critical gaps AND some medium → PARTIAL
      - 1 critical gap (analysis) → PARTIAL
      - 1 critical gap (drafting) → NOT_READY
      - ≥2 critical gaps → NOT_READY
    """
    # Drafting demands a ready graph. If drafting is blocked by the report,
    # force NOT_READY even when no gap items were produced.
    if intent == UserIntent.DRAFTING and report.blocks_drafting:
        return ResponseMode.NOT_READY

    # Hard block on ruling when upstream declared it
    if report.blocks_ruling:
        return ResponseMode.NOT_READY

    if report.critical_count == 0 and report.medium_count == 0:
        return ResponseMode.READY

    if report.critical_count == 0:
        return ResponseMode.PARTIAL

    if intent == UserIntent.DRAFTING:
        return ResponseMode.NOT_READY

    if report.critical_count == 1:
        return ResponseMode.PARTIAL

    return ResponseMode.NOT_READY
