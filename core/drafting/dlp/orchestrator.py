# -*- coding: utf-8 -*-
"""
DLP — Orchestrator.

The single entry point that replaces the binary drafting gate with an
intelligent mode selector. Callers pass:

  • request (DraftingRequest) — document type, client side, facts
  • graph   (IssueGraph)      — issue decomposition (may be None)
  • bound   (IssueBoundEvidenceSet) — bound evidence (may be None)
  • mlre    (MLREResult)      — multi-path analysis (may be None)
  • raw_gaps (list[str])      — reason codes the legacy gate would emit

The orchestrator:
  1. Builds DraftingSignals
  2. Chooses a DraftingMode via `select_mode`
  3. Dispatches to the appropriate composer (MQE for full/conditional/
     dual, dedicated skeleton builder for SKELETON_DRAFT)
  4. Appends 1-3 UX pivot questions when useful
  5. Returns a DLPResult with the text + trace

The caller is expected to map `safety_mode` to the dict it needs to
emit. `DLPResult` carries both the DLP `mode` and the underlying
`safety_mode` so the HTTP schema stays backward-compatible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.drafting.drafting_engine import (
    DraftingRequest, DraftingResult, DraftingSafetyMode,
    DocumentType, ClientSide,
)
from core.drafting.mqe import compose_memo as _mqe_compose
from core.drafting.dlp.mode import (
    DraftingMode, DraftingSignals, DraftingDecision,
    build_signals, select_mode,
)
from core.drafting.dlp.skeleton_draft import (
    build_skeleton, SkeletonDraftResult,
)
from core.drafting.dlp.not_draftable_final import (
    build_final_not_draftable_message,
)
from core.drafting.dlp.humanize import humanize_gaps
from core.drafting.dlp.ux_questions import (
    build_draft_upgrade_questions, render_upgrade_questions,
)


# ═════════════════════════════════════════════════════════════════
# Result container
# ═════════════════════════════════════════════════════════════════

@dataclass
class DLPResult:
    text:               str = ""
    mode:               DraftingMode = DraftingMode.NOT_DRAFTABLE_YET
    safety_mode:        DraftingSafetyMode = DraftingSafetyMode.NOT_DRAFTABLE_YET
    decision:           Optional[DraftingDecision] = None
    cited_laws:         list[str] = field(default_factory=list)
    assumptions:        list[str] = field(default_factory=list)
    missing:            list[str] = field(default_factory=list)
    user_safe_gaps:     list[str] = field(default_factory=list)
    upgrade_questions:  list[str] = field(default_factory=list)
    notes:              list[str] = field(default_factory=list)

    @property
    def blocks_drafting(self) -> bool:
        return self.mode == DraftingMode.NOT_DRAFTABLE_YET

    def to_dict(self) -> dict:
        return {
            "text_len":          len(self.text),
            "mode":              self.mode.value,
            "safety_mode":       self.safety_mode.value,
            "decision":          self.decision.to_dict() if self.decision else {},
            "cited_laws":        self.cited_laws[:5],
            "assumptions":       self.assumptions[:5],
            "missing":           self.missing[:5],
            "user_safe_gaps":    self.user_safe_gaps[:5],
            "upgrade_questions": list(self.upgrade_questions),
            "blocks_drafting":   self.blocks_drafting,
            "notes":             self.notes[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Per-mode composers
# ═════════════════════════════════════════════════════════════════

def _compose_full(request, graph, bound, mlre, raw_gaps) -> DLPResult:
    """FULL_DRAFT: delegate to MQE — assume everything is ready."""
    mqe_out = _mqe_compose(
        request=request, graph=graph, bound=bound,
        safety_mode=DraftingSafetyMode.DRAFTABLE,
        missing=[],
        mlre=mlre,
        is_conditional_context=False,
    )
    r = DLPResult(
        text=mqe_out.text,
        mode=DraftingMode.FULL_DRAFT,
        safety_mode=mqe_out.safety_mode,
        cited_laws=list(mqe_out.cited_laws),
        assumptions=list(mqe_out.assumptions),
    )
    return r


def _compose_conditional_or_dual(
    request, graph, bound, mlre,
    raw_gaps, decision: DraftingDecision,
) -> DLPResult:
    """CONDITIONAL / DUAL — MQE emits the body; mlre_drafting adds framing
    when multi-path. Here we delegate to MQE with safety = DRAFTABLE_WITH_ASSUMPTIONS
    because multi-path drafts usually carry some unresolved pivots."""
    safety = DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS
    missing = list(raw_gaps or [])
    mqe_out = _mqe_compose(
        request=request, graph=graph, bound=bound,
        safety_mode=safety,
        missing=missing,
        mlre=mlre,
        is_conditional_context=(
            decision.mode == DraftingMode.CONDITIONAL_DRAFT
        ),
    )
    r = DLPResult(
        text=mqe_out.text,
        mode=decision.mode,
        safety_mode=mqe_out.safety_mode,
        cited_laws=list(mqe_out.cited_laws),
        assumptions=list(mqe_out.assumptions),
        missing=missing,
        user_safe_gaps=humanize_gaps(missing),
    )
    return r


def _compose_skeleton(
    request, graph, bound, mlre, raw_gaps,
) -> DLPResult:
    """SKELETON_DRAFT — the new, useful-on-gap mode."""
    sk = build_skeleton(
        doc_type=request.document_type,
        client_side=request.client_side,
        facts=list(request.facts or []),
        graph=graph, bound=bound, mlre=mlre,
        raw_gaps=list(raw_gaps or []),
    )
    r = DLPResult(
        text=sk.text,
        mode=DraftingMode.SKELETON_DRAFT,
        # Skeleton safety sits between the old DRAFTABLE_WITH_ASSUMPTIONS
        # and NOT_DRAFTABLE_YET — we keep the HTTP schema happy by reporting
        # DRAFTABLE_WITH_ASSUMPTIONS; `blocks_drafting` is False.
        safety_mode=DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS,
        cited_laws=list(sk.cited_laws),
        assumptions=list(sk.missing),
        missing=list(sk.missing),
        user_safe_gaps=list(sk.user_safe_gaps),
    )
    r.notes.extend(sk.notes)
    return r


def _compose_not_draftable(
    request, mlre, raw_gaps,
) -> DLPResult:
    """Only called when literally nothing can be drafted."""
    text = build_final_not_draftable_message(
        doc_type=request.document_type,
        raw_gaps=list(raw_gaps or []),
        mlre=mlre,
    )
    return DLPResult(
        text=text,
        mode=DraftingMode.NOT_DRAFTABLE_YET,
        safety_mode=DraftingSafetyMode.NOT_DRAFTABLE_YET,
        missing=list(raw_gaps or ["mlre_no_surviving_hypothesis"]),
        user_safe_gaps=humanize_gaps(raw_gaps or []),
    )


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def compose_draft(
    request: DraftingRequest,
    *,
    graph=None,
    bound=None,
    mlre=None,
    raw_gaps: Optional[list[str]] = None,
    append_upgrade_questions: bool = True,
) -> DLPResult:
    """Produce a DLP-chosen memo for the given request.

    NEVER returns a bare refusal as long as any legal structure exists.
    """
    raw_gaps = list(raw_gaps or [])

    # ── 1) Build signals and pick mode ──
    signals = build_signals(
        mlre=mlre, graph=graph, bound=bound,
        facts=list(request.facts or []),
        doc_type_value=(
            request.document_type.value
            if hasattr(request.document_type, "value")
            else str(request.document_type)
        ),
        raw_gaps=raw_gaps,
    )
    decision = select_mode(signals)

    # ── 2) Dispatch to the mode-specific composer ──
    if decision.mode == DraftingMode.FULL_DRAFT:
        result = _compose_full(request, graph, bound, mlre, raw_gaps)
    elif decision.mode in (DraftingMode.CONDITIONAL_DRAFT,
                              DraftingMode.DUAL_STRATEGY_DRAFT):
        result = _compose_conditional_or_dual(
            request, graph, bound, mlre, raw_gaps, decision,
        )
    elif decision.mode == DraftingMode.SKELETON_DRAFT:
        result = _compose_skeleton(request, graph, bound, mlre, raw_gaps)
    else:  # NOT_DRAFTABLE_YET
        result = _compose_not_draftable(request, mlre, raw_gaps)

    result.decision = decision
    result.notes.append(
        f"dlp:mode={decision.mode.value} "
        f"rule={decision.rule_fired}"
    )

    # ── 3) Append upgrade questions on SKELETON / CONDITIONAL / DUAL ──
    if append_upgrade_questions and decision.mode in (
        DraftingMode.SKELETON_DRAFT,
        DraftingMode.CONDITIONAL_DRAFT,
        DraftingMode.DUAL_STRATEGY_DRAFT,
    ):
        qs = build_draft_upgrade_questions(
            mlre=mlre, graph=graph, max_questions=3,
        )
        if qs:
            result.upgrade_questions = list(qs)
            block = render_upgrade_questions(qs, mode=decision.mode.value)
            if block and block not in result.text:
                result.text = result.text.rstrip() + "\n\n" + block + "\n"

    return result
