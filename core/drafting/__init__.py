# -*- coding: utf-8 -*-
"""
Legal Drafting Engine.

Integrated into the unified runtime. Does NOT bypass fail-closed.
Produces structured memoranda ONLY when:
  1. domain is resolved
  2. issue graph has enough nodes
  3. evidence binding is adequate
  4. canonical citations are verified

Public API:
    from core.drafting import (
        DraftingRequest, DraftingResult, DraftingSafetyMode,
        detect_drafting_intent, build_memo,
    )
"""
from core.drafting.drafting_engine import (
    DraftingRequest, DraftingResult, DraftingSafetyMode,
    DocumentType, ClientSide,
    detect_drafting_intent, build_memo, DraftingIntent,
)

__all__ = [
    "DraftingRequest", "DraftingResult", "DraftingSafetyMode",
    "DocumentType", "ClientSide",
    "detect_drafting_intent", "build_memo", "DraftingIntent",
]
