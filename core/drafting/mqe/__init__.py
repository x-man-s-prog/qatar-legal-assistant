# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine (MQE).

Raises memo quality from "compiles" to "submittable":
  • Every argument carries claim → basis → evidence → application → consequence
  • Every paragraph is bound to an issue + evidence + statute
  • Every prayer is precise, court-actionable, not vague
  • Every conditional/dual memo is explicitly framed (no leakage between paths)
  • Every memo is scored on 7 dimensions; low scores downgrade safety

Public API:
    from core.drafting.mqe import (
        compose_memo, compose_memo_conditional, compose_memo_dual,
        MQEComposeResult,
        LegalArgument, build_arguments, render_arguments_block,
        Prayer, build_prayer, render_prayer, is_vague_prayer,
        MemoQualityScore, score_memo,
        QUALITY_FLOOR, STRONG_QUALITY_FLOOR,
        FirewallReport, audit_memo,
        build_opponent_paragraph,
        wrap_conditional, wrap_dual,
        refine,
        build_not_draftable_message,
    )
"""
from core.drafting.mqe.argument import (
    LegalArgument, build_arguments, render_arguments_block, render_argument,
)
from core.drafting.mqe.structure import (
    MemoSection, section_order, section_title,
    format_section_header, parties_line,
)
from core.drafting.mqe.prayer import (
    Prayer, build_prayer, render_prayer, is_vague_prayer,
)
from core.drafting.mqe.style import (
    refine, count_weak_words, count_role_leaks, count_repeated_openers,
)
from core.drafting.mqe.firewall import (
    FirewallReport, audit_memo,
)
from core.drafting.mqe.scorer import (
    MemoQualityScore, score_memo, is_acceptable, is_publication_ready,
    QUALITY_FLOOR, STRONG_QUALITY_FLOOR,
)
from core.drafting.mqe.opponent import build_opponent_paragraph
from core.drafting.mqe.conditional_frame import wrap_conditional, wrap_dual
from core.drafting.mqe.not_draftable import build_not_draftable_message
from core.drafting.mqe.orchestrator import (
    MQEComposeResult, compose_memo,
    compose_memo_conditional, compose_memo_dual,
)

__all__ = [
    # Argument spine
    "LegalArgument", "build_arguments", "render_arguments_block", "render_argument",
    # Structure
    "MemoSection", "section_order", "section_title",
    "format_section_header", "parties_line",
    # Prayer
    "Prayer", "build_prayer", "render_prayer", "is_vague_prayer",
    # Style
    "refine", "count_weak_words", "count_role_leaks", "count_repeated_openers",
    # Firewall
    "FirewallReport", "audit_memo",
    # Scorer
    "MemoQualityScore", "score_memo", "is_acceptable", "is_publication_ready",
    "QUALITY_FLOOR", "STRONG_QUALITY_FLOOR",
    # Opponent
    "build_opponent_paragraph",
    # Conditional / dual
    "wrap_conditional", "wrap_dual",
    # Not draftable
    "build_not_draftable_message",
    # Orchestrator
    "MQEComposeResult", "compose_memo",
    "compose_memo_conditional", "compose_memo_dual",
]
