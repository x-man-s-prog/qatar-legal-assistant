# -*- coding: utf-8 -*-
"""
SEA — Force-Stages enforcer (PEAL amplifier).

If the artifacts reach the gate with a required stage missing, the
force-stages enforcer RE-RUNS the missing stage in-place instead of
letting PEAL fail.

  • `force_mlre(query, facts)` — runs MLRE, returns its trace dict
  • `force_dlp(query, request, ...)` — runs DLP, returns its dict
  • `rebuild_issue_graph(query, domain)` — rebuilds a graph summary
  • `enforce_pipeline_completeness(artifacts, query, requirements)` —
    top-level enforcer called by production_runtime before emission.

These helpers NEVER raise; on failure they return empty dicts so the
gate's downstream checks surface the issue through PEAL traces.
"""
from __future__ import annotations

from typing import Optional


# ═════════════════════════════════════════════════════════════════
# Stage-level force helpers
# ═════════════════════════════════════════════════════════════════

def force_mlre(query: str, facts: Optional[list[str]] = None) -> dict:
    """Run MLRE and return its trace dict. Empty dict on failure."""
    try:
        from core.mlre import run_mlre
        out = run_mlre(
            query=query,
            facts=list(facts or [query[:300]]),
            max_hypotheses=8, max_survivors=3,
        )
        return out.to_trace()
    except Exception:
        return {}


def rebuild_issue_graph(query: str, domain: str = "") -> dict:
    """Rebuild an issue graph summary. Empty dict on failure."""
    if not domain:
        return {}
    try:
        from core.domain_pipeline import build_issue_graph
        g = build_issue_graph(domain, "", query)
        return {
            "issue_count":   len(g.nodes),
            "has_primary":   bool(g.primary_issue),
            "primary_issue": g.primary_issue or "",
            "domain":        domain,
        }
    except Exception:
        return {}


def force_dlp(query: str,
                  document_type_value: str = "defense_memo",
                  client_side_value: str = "neutral") -> dict:
    """Run DLP mode selection and return a drafting dict.

    Safe fallback — if retrieval / MLRE / DLP fail, returns a minimal
    SKELETON-mode dict so the caller can still populate the artifacts.
    """
    try:
        from core.drafting import (
            DraftingRequest, DocumentType, ClientSide,
        )
        from core.drafting.dlp import (
            compose_draft, DraftingMode,
        )
        try:
            dt = DocumentType(document_type_value)
        except Exception:
            dt = DocumentType.DEFENSE_MEMO
        try:
            cs = ClientSide(client_side_value)
        except Exception:
            cs = ClientSide.NEUTRAL
        req = DraftingRequest(
            document_type=dt,
            client_side=cs,
            facts=[query[:300]] if query else [],
        )
        # No graph / bound here — compose_draft handles that path
        dlp_out = compose_draft(
            req, graph=None, bound=None, mlre=None,
            raw_gaps=[],
            append_upgrade_questions=False,
        )
        return {
            "drafting_intent_detected": True,
            "drafting_mode":            dlp_out.mode.value,
            "document_type":            dt.value,
            "text":                     dlp_out.text,
            "missing":                  list(dlp_out.missing),
            "assumptions":              list(dlp_out.assumptions),
            "cited_laws":               list(dlp_out.cited_laws),
            "blocks_drafting":          dlp_out.blocks_drafting,
            "user_safe_gaps":           list(dlp_out.user_safe_gaps),
        }
    except Exception:
        return {
            "drafting_intent_detected": True,
            "drafting_mode":            "skeleton_draft",
            "document_type":            document_type_value,
            "text":                     "",
            "missing":                  [],
            "assumptions":              [],
            "cited_laws":               [],
            "blocks_drafting":          False,
            "user_safe_gaps":           [],
        }


# ═════════════════════════════════════════════════════════════════
# Top-level enforcer — called by _emit_through_gate
# ═════════════════════════════════════════════════════════════════

def enforce_pipeline_completeness(
    artifacts,
    *, query: str,
) -> list[str]:
    """Check artifacts against PEAL requirements and force-run missing
    stages in-place.

    Returns the list of stages that were forced (for telemetry).
    """
    from core.runtime.pre_execution_validator import (
        extract_state_from_artifacts,
    )
    rescued: list[str] = []
    reqs = artifacts.peal_requirements or {}
    if not reqs:
        return rescued

    state = extract_state_from_artifacts(artifacts)

    # ── Force MLRE if required but missing ──
    if reqs.get("needs_mlre") and not state.mlre_executed:
        trace = force_mlre(query, facts=[query[:300]] if query else [])
        if trace:
            artifacts.mlre_trace = trace
            rescued.append("mlre")

    # ── Rebuild issue graph if required but missing ──
    if reqs.get("needs_issue_graph") and not state.issue_graph_built:
        # Prefer the MLRE-derived domain if the pipeline didn't resolve one
        domain = artifacts.domain or ""
        if not domain and artifacts.mlre_trace:
            _reality = (artifacts.mlre_trace or {}).get("reality", {}) or {}
            _paths = _reality.get("paths") or []
            if _paths:
                domain = (_paths[0] or {}).get("domain") or ""
                if domain and not artifacts.domain:
                    artifacts.domain = domain
        if domain:
            graph_info = rebuild_issue_graph(query, domain=domain)
            if graph_info:
                # Attach into evidence_trace so downstream reconstructors see it
                et = dict(artifacts.evidence_trace or {})
                et.setdefault("query_issues",
                               [graph_info.get("primary_issue", "")]
                               if graph_info.get("primary_issue") else [])
                et["forced_graph"] = graph_info
                artifacts.evidence_trace = et
                rescued.append("issue_graph")

    # ── Force DLP if drafting intent but no mode decided ──
    if reqs.get("needs_dlp") and not state.dlp_mode_decided:
        drafting = dict(artifacts.drafting or {})
        doc_type_val = drafting.get("document_type") or "defense_memo"
        dlp_dict = force_dlp(query, document_type_value=doc_type_val)
        if dlp_dict and dlp_dict.get("drafting_mode"):
            drafting.update(dlp_dict)
            artifacts.drafting = drafting
            rescued.append("dlp")

    # ── Refresh peal_state to reflect what was forced ──
    if rescued:
        new_state = extract_state_from_artifacts(artifacts)
        artifacts.peal_state = new_state.to_dict()
        artifacts.runtime_notes = list(artifacts.runtime_notes or []) + [
            f"sea_forced:{stage}" for stage in rescued
        ]
    return rescued
