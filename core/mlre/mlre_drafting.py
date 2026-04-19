# -*- coding: utf-8 -*-
"""
MLRE-driven drafting — single / conditional / dual strategy.

Uses surviving hypotheses to shape the memo:
  SINGLE_PATH    → one clean memo on the dominant path
  CONDITIONAL    → memo on primary + conditional paragraph for fallback
  DUAL_STRATEGY  → memo with two parallel strategies
  NOT_DRAFTABLE  → explain WHY (from MLRE), not a generic refusal
"""
from __future__ import annotations

from typing import Optional

from core.mlre.orchestrator import MLREResult, DraftingV2Mode
from core.drafting import (
    DraftingRequest, DraftingResult, DraftingSafetyMode,
    DocumentType, ClientSide, build_memo,
)
from core.domain_pipeline.issue_graph import build_issue_graph, IssueGraph
from core.domain_pipeline.evidence_linker import bind_evidence_to_issues
from core.evidence import get_retriever
from core.legal_gates import LegalIssueClassifier, FactPatternExtractor


def _derive_doc_type_from_intent(intent_str: str) -> DocumentType:
    mapping = {
        "write_defense_memo":  DocumentType.DEFENSE_MEMO,
        "write_reply_memo":    DocumentType.REPLY_MEMO,
        "write_claim_brief":   DocumentType.CLAIM_BRIEF,
        "write_pleading":      DocumentType.PLEADING_POINTS,
        "convert_to_memo":     DocumentType.EXPLANATORY_MEMO,
        "defense_checklist":   DocumentType.DEFENSE_CHECKLIST,
        "write_generic_memo":  DocumentType.DEFENSE_MEMO,
    }
    return mapping.get(intent_str, DocumentType.DEFENSE_MEMO)


def _build_evidence_for(hypothesis, query: str) -> tuple:
    """Retrieve + bind evidence for a single hypothesis's graph."""
    try:
        graph = hypothesis.issue_graph
        if graph is None:
            return (None, None)
        c = LegalIssueClassifier().classify(query)
        f = FactPatternExtractor().extract(query)
        es = get_retriever().retrieve(
            query=query,
            classification=c,
            fact_pattern=f,
            issue_keywords=[n.question[:30] for n in graph.nodes.values()],
        )
        bound = bind_evidence_to_issues(
            graph, es.records,
            issue_keywords=[n.question for n in graph.nodes.values()],
        )
        return (graph, bound)
    except Exception:
        return (None, None)


def build_memo_from_mlre(
    mlre: MLREResult,
    query: str,
    facts: list[str],
    drafting_intent: str,
    client_side: ClientSide = ClientSide.NEUTRAL,
) -> dict:
    """Produce a drafting response shaped by MLRE survivors.

    Returns a dict with the final memo text and drafting trace fields.
    """
    doc_type = _derive_doc_type_from_intent(drafting_intent)
    survivors = mlre.survivors
    mode_str = mlre.drafting_v2_mode or DraftingV2Mode.SINGLE_PATH.value

    # ── No survivors → DLP SKELETON_DRAFT (never a bare refusal) ──
    if not survivors:
        return _skeleton_from_mlre(
            mlre=mlre, doc_type=doc_type,
            query=query, facts=facts, client_side=client_side,
        )

    # ── SINGLE_PATH ──
    if mode_str == DraftingV2Mode.SINGLE_PATH.value or len(survivors) == 1:
        return _single_path_memo(
            survivors[0][0], query, facts, doc_type, client_side, mlre
        )

    # ── CONDITIONAL ──
    if mode_str == DraftingV2Mode.CONDITIONAL.value:
        return _conditional_memo(
            survivors[0][0], survivors[1][0],
            query, facts, doc_type, client_side, mlre
        )

    # ── DUAL_STRATEGY ──
    return _dual_strategy_memo(
        survivors[0][0], survivors[1][0],
        query, facts, doc_type, client_side, mlre
    )


def _skeleton_from_mlre(
    *, mlre, doc_type, query: str, facts: list[str],
    client_side: ClientSide,
) -> dict:
    """Compose a SKELETON_DRAFT when MLRE produced no survivors but the
    issue graph or reality paths still offer legal structure."""
    try:
        from core.drafting.dlp import (
            build_skeleton, DraftingMode,
            build_draft_upgrade_questions, render_upgrade_questions,
        )
    except Exception:
        # Fall back to the old structured NOT_DRAFTABLE if DLP is unavailable
        return _not_draftable_from_mlre(mlre, doc_type)

    # Try to pull a graph from ANY known fact / domain — best effort
    graph = None
    bound = None
    # Attempt a cheap reconstruction via fact pattern if the first survivor
    # is gone but reality or pipeline metadata may still carry hints.
    reality = getattr(mlre, "reality", None)
    domain_hint = ""
    if reality is not None and getattr(reality, "paths", []):
        p = reality.paths[0]
        domain_hint = getattr(p, "domain", "") or ""

    if domain_hint:
        try:
            from core.domain_pipeline.issue_graph import build_issue_graph
            graph = build_issue_graph(domain_hint, "", query)
        except Exception:
            graph = None

    # If we ended up with a graph, also attempt retrieval+binding
    if graph is not None:
        try:
            from core.evidence import get_retriever
            from core.legal_gates import LegalIssueClassifier, FactPatternExtractor
            from core.domain_pipeline.evidence_linker import bind_evidence_to_issues
            c = LegalIssueClassifier().classify(query)
            fp = FactPatternExtractor().extract(query)
            es = get_retriever().retrieve(
                query=query, classification=c, fact_pattern=fp,
                issue_keywords=[n.question[:30] for n in graph.nodes.values()],
            )
            bound = bind_evidence_to_issues(
                graph, es.records,
                issue_keywords=[n.question for n in graph.nodes.values()],
            )
        except Exception:
            bound = None

    raw_gaps = ["mlre_no_surviving_hypothesis"]
    if reality is not None and not getattr(reality, "can_be_answered", True):
        raw_gaps.append("issue_graph_unavailable")

    # If there is NEITHER reality path NOR a usable graph NOR evidence,
    # fall back to the structured NOT_DRAFTABLE message.
    has_structure = bool(
        graph is not None and graph.nodes
        or (reality is not None and getattr(reality, "paths", []))
        or (bound is not None and bound.links)
    )
    if not has_structure:
        return _not_draftable_from_mlre(mlre, doc_type)

    sk = build_skeleton(
        doc_type=doc_type,
        client_side=client_side,
        facts=list(facts or []),
        graph=graph, bound=bound, mlre=mlre,
        raw_gaps=raw_gaps,
    )

    # Add UX pivot questions so the user can push the case toward FULL
    upgrade_questions = build_draft_upgrade_questions(
        mlre=mlre, graph=graph, max_questions=3,
    )
    text = sk.text
    if upgrade_questions:
        block = render_upgrade_questions(
            upgrade_questions, mode=DraftingMode.SKELETON_DRAFT.value,
        )
        if block and block not in text:
            text = text.rstrip() + "\n\n" + block + "\n"

    # Scrub any lingering technical leaks
    try:
        from core.mlre.output_firewall import sanitize_user_output
        fw = sanitize_user_output(text)
        if fw.cleaned_text:
            text = fw.cleaned_text
    except Exception:
        pass

    return {
        "text":                       text,
        "safety_mode":                DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS.value,
        "drafting_mode":              DraftingMode.SKELETON_DRAFT.value,
        "document_type":              doc_type.value,
        "missing":                    list(sk.missing),
        "assumptions":                list(sk.missing),
        "cited_laws":                 list(sk.cited_laws),
        "blocks_drafting":            False,
        "missing_elements":           list(sk.missing),
        "drafting_intent_detected":   True,
        "user_safe_gaps":             list(sk.user_safe_gaps),
        "upgrade_questions":          list(upgrade_questions),
    }


# ─────────────────────────────────────────────────────────────────
# SINGLE_PATH
# ─────────────────────────────────────────────────────────────────

def _single_path_memo(hypothesis, query, facts, doc_type, client_side, mlre):
    graph, bound = _build_evidence_for(hypothesis, query)
    request = DraftingRequest(
        document_type=doc_type,
        client_side=client_side,
        domain=hypothesis.domain,
        subdomain=hypothesis.subdomain,
        facts=facts,
    )
    # Pass mlre so MQE can render the opponent-model paragraph
    result = build_memo(
        request, graph=graph, bound_evidence=bound, mlre=mlre,
        is_conditional_context=False,
    )
    return _to_response_dict(
        result, mode="single_path",
        secondary_addendum="",
    )


# ─────────────────────────────────────────────────────────────────
# CONDITIONAL
# ─────────────────────────────────────────────────────────────────

def _conditional_memo(primary, secondary, query, facts,
                        doc_type, client_side, mlre):
    """Primary memo + clean conditional fallback via MQE frame."""
    from core.drafting.mqe import compose_memo_conditional
    graph, bound = _build_evidence_for(primary, query)
    request = DraftingRequest(
        document_type=doc_type,
        client_side=client_side,
        domain=primary.domain,
        subdomain=primary.subdomain,
        facts=facts,
    )
    # Primary memo with MQE quality (mlre provided for opponent model)
    result = build_memo(
        request, graph=graph, bound_evidence=bound, mlre=mlre,
        is_conditional_context=False,
    )

    # Build a short fallback body grounded in the secondary hypothesis
    pivot_conditions = []
    if mlre and mlre.reality and mlre.reality.pivot_conditions:
        pivot_conditions = list(mlre.reality.pivot_conditions[:2])
    fallback_body = (
        "يُطلب على سبيل الاحتياط إعمال التكييف البديل إذا تراءى للمحكمة "
        "أن ظاهر الأوراق لا يحتمل المسار الأساسي."
    )
    framed = compose_memo_conditional(
        primary_text=result.text,
        fallback_theory=secondary.legal_theory,
        pivot_conditions=pivot_conditions,
        fallback_body=fallback_body,
    )
    result.text = framed
    return _to_response_dict(
        result, mode="conditional",
        secondary_addendum="",
    )


# ─────────────────────────────────────────────────────────────────
# DUAL_STRATEGY
# ─────────────────────────────────────────────────────────────────

def _dual_strategy_memo(primary, secondary, query, facts,
                          doc_type, client_side, mlre):
    """Two parallel strategies, each with its own issue graph; framed by MQE."""
    from core.drafting.mqe import compose_memo_dual
    g1, b1 = _build_evidence_for(primary, query)
    g2, b2 = _build_evidence_for(secondary, query)

    req1 = DraftingRequest(
        document_type=doc_type, client_side=client_side,
        domain=primary.domain, subdomain=primary.subdomain,
        facts=facts,
    )
    req2 = DraftingRequest(
        document_type=doc_type, client_side=client_side,
        domain=secondary.domain, subdomain=secondary.subdomain,
        facts=facts,
    )
    # Both drafts go through MQE (is_conditional_context=True on the second
    # so style.refine preserves conditional hedges).
    r1 = build_memo(req1, graph=g1, bound_evidence=b1, mlre=mlre,
                    is_conditional_context=False)
    r2 = build_memo(req2, graph=g2, bound_evidence=b2, mlre=mlre,
                    is_conditional_context=True)

    combined = compose_memo_dual(
        primary_text=r1.text,
        secondary_text=r2.text,
        primary_label=primary.legal_theory or "المسار الأقوى",
        secondary_label=secondary.legal_theory or "المسار البديل",
    )

    # Use the worse-off safety mode as the combined safety
    safety = DraftingSafetyMode.DRAFTABLE
    if (r1.safety_mode == DraftingSafetyMode.NOT_DRAFTABLE_YET
            or r2.safety_mode == DraftingSafetyMode.NOT_DRAFTABLE_YET):
        safety = DraftingSafetyMode.NOT_DRAFTABLE_YET
    elif (r1.safety_mode == DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS
            or r2.safety_mode == DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS):
        safety = DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS

    merged = DraftingResult(
        safety_mode=safety,
        document_type=r1.document_type,
        text=combined,
        missing_inputs=list(set(r1.missing_inputs + r2.missing_inputs)),
        assumptions=list(set(r1.assumptions + r2.assumptions)),
        cited_laws=list(set(r1.cited_laws + r2.cited_laws)),
    )
    return _to_response_dict(
        merged, mode="dual_strategy",
        secondary_addendum="",
    )


# ─────────────────────────────────────────────────────────────────
# NOT_DRAFTABLE with MLRE context
# ─────────────────────────────────────────────────────────────────

def _not_draftable_from_mlre(mlre: MLREResult, doc_type) -> dict:
    """Explain why drafting is blocked using MLRE findings — not generic.

    Uses the MQE NOT_DRAFTABLE builder for WHAT / WHY / WHAT-UNBLOCKS,
    then appends the MLRE-specific unresolved message.
    """
    from core.drafting.mqe import build_not_draftable_message
    base = build_not_draftable_message(
        doc_type,
        missing=["issue_graph_unavailable", "no_bound_evidence"],
    )
    tail_parts = []
    if mlre.reality and mlre.reality.unresolved_message:
        tail_parts.append("")
        tail_parts.append("**ملاحظة من محرك التكييف المتعدد:**")
        tail_parts.append(mlre.reality.unresolved_message)
    text = base.rstrip() + ("\n" + "\n".join(tail_parts) if tail_parts else "")
    return {
        "text":         text,
        "safety_mode":  DraftingSafetyMode.NOT_DRAFTABLE_YET.value,
        "drafting_mode": "not_draftable_mlre",
        "document_type": doc_type.value,
        "missing":       ["mlre_no_surviving_hypothesis"],
        "assumptions":   [],
        "cited_laws":    [],
        "blocks_drafting": True,
        "missing_elements": ["mlre_no_surviving_hypothesis"],
        "drafting_intent_detected": True,
    }


def _to_response_dict(result, mode, secondary_addendum="") -> dict:
    text = result.text
    if secondary_addendum:
        text = text + "\n\n" + secondary_addendum
    # ── Scrub any technical leakage before returning to HTTP layer ──
    try:
        from core.mlre.output_firewall import sanitize_user_output
        fw = sanitize_user_output(text)
        if fw.cleaned_text:
            text = fw.cleaned_text
    except Exception:
        pass
    # REUP: when build_memo routed through DLP and picked SKELETON,
    # propagate that mode instead of the caller's legacy label.
    effective_mode = mode
    for note in (result.notes or []):
        if note.startswith("dlp:mode="):
            try:
                dlp_mode = note.split("dlp:mode=", 1)[1].split()[0]
                if dlp_mode in ("skeleton_draft", "not_draftable_mlre"):
                    effective_mode = dlp_mode
            except Exception:
                pass
            break
    return {
        "text":           text,
        "safety_mode":    result.safety_mode.value,
        "drafting_mode":  effective_mode,
        "document_type":  result.document_type,
        "missing":        result.missing_inputs,
        "assumptions":    result.assumptions,
        "cited_laws":     result.cited_laws,
        "blocks_drafting": result.safety_mode.value == "not_draftable_yet",
        "missing_elements": result.missing_inputs,
        "drafting_intent_detected": True,
    }
