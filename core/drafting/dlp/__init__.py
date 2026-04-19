# -*- coding: utf-8 -*-
"""
Drafting Liberation Protocol (DLP).

Replaces the binary "draftable / not draftable" gate with a five-way
mode selector:

    FULL_DRAFT
    CONDITIONAL_DRAFT
    DUAL_STRATEGY_DRAFT
    SKELETON_DRAFT      ← new: real preliminary legal document
    NOT_DRAFTABLE_YET   ← last-resort only

Drafting is NEVER refused when any legal structure exists (domain +
issue graph, or MLRE survivors, or bound evidence). Even when facts are
partial, SKELETON_DRAFT delivers a useful preliminary document the user
can iterate on.

Public API:
    from core.drafting.dlp import (
        compose_draft, DLPResult,
        DraftingMode, DraftingDecision, DraftingSignals,
        build_signals, select_mode,
        build_skeleton, SkeletonDraftResult,
        humanize_gap, humanize_gaps,
        build_draft_upgrade_questions, render_upgrade_questions,
        build_final_not_draftable_message,
    )
"""
from core.drafting.dlp.mode import (
    DraftingMode, DraftingSignals, DraftingDecision,
    build_signals, select_mode,
    STRONG_COMPOSITE, GOOD_COMPOSITE, MIN_COMPOSITE,
    STRONG_COVERAGE, GOOD_COVERAGE, MIN_COVERAGE,
    DUAL_GAP_THRESHOLD,
)
from core.drafting.dlp.humanize import (
    humanize_gap, humanize_gaps,
)
from core.drafting.dlp.skeleton_draft import (
    build_skeleton, SkeletonDraftResult,
)
from core.drafting.dlp.not_draftable_final import (
    build_final_not_draftable_message,
)
from core.drafting.dlp.ux_questions import (
    build_draft_upgrade_questions, render_upgrade_questions,
)
from core.drafting.dlp.orchestrator import (
    DLPResult, compose_draft,
)


__all__ = [
    # Modes
    "DraftingMode", "DraftingSignals", "DraftingDecision",
    "build_signals", "select_mode",
    "STRONG_COMPOSITE", "GOOD_COMPOSITE", "MIN_COMPOSITE",
    "STRONG_COVERAGE", "GOOD_COVERAGE", "MIN_COVERAGE",
    "DUAL_GAP_THRESHOLD",
    # Humanizer
    "humanize_gap", "humanize_gaps",
    # Skeleton draft
    "build_skeleton", "SkeletonDraftResult",
    # NOT_DRAFTABLE final
    "build_final_not_draftable_message",
    # UX pivot questions
    "build_draft_upgrade_questions", "render_upgrade_questions",
    # Orchestrator
    "DLPResult", "compose_draft",
]
