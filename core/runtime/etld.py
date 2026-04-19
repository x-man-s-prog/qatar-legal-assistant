# -*- coding: utf-8 -*-
"""
ETLD — Execution Trace & Leak Detector.

Diagnostic instrument. NOT a production path — it only observes.

For each request's final response dict, ETLD:

  • Reconstructs an `ExecutionTrace` snapshot (entry → handler →
    routing → pipeline state → composer → output author → final text).
  • Scans for anomalies across 11 categories (ILLEGAL_ENTRY,
    MISROUTED_REQUEST, MLRE_BYPASS, DLP_BYPASS, ISSUE_GRAPH_MISSING,
    LEGACY_EXECUTION, EXCEPTION_FALLBACK, MERGE_LEAK, MULTI_AUTHOR_OUTPUT,
    LEGACY_SIGNATURE_LEAK, MISSING_AUTHOR_STAMP).
  • Produces a structured `ROOT_CAUSES` list with file/function hints,
    triggers, evidence snippets, and impact assessments.

Use:
    from core.runtime.etld import (
        build_trace_from_response, detect_anomalies,
        render_trace_report, render_root_causes_report,
    )

This module NEVER emits text to the user. It only diagnoses.
"""
from __future__ import annotations

import re
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


# ═════════════════════════════════════════════════════════════════
# Trace container
# ═════════════════════════════════════════════════════════════════

@dataclass
class ExecutionTrace:
    request_id:                  str = ""
    raw_query:                   str = ""
    entry_point:                 str = ""      # API | CLI | WS | TEST
    handler:                     str = ""      # function that handled it
    # Routing / intent
    router_decision:             str = ""
    detected_intent:             str = ""
    domain:                      str = ""
    domain_resolution:           str = ""
    # Pipeline state
    issue_graph_built:           bool = False
    issue_graph_size:            int  = 0
    mlre_required:               bool = False
    mlre_executed:               bool = False
    mlre_hypotheses_count:       int  = 0
    mlre_survivors_count:        int  = 0
    dlp_required:                bool = False
    dlp_executed:                bool = False
    dlp_mode:                    str  = ""
    ux_executed:                 bool = False
    # Composer / author
    composer_inputs:             list[str] = field(default_factory=list)
    composer_author_selected:    str = ""
    # Legacy / exception paths
    legacy_called:               list[str] = field(default_factory=list)
    exception_path_taken:        bool = False
    fallback_used:               bool = False
    # Output
    output_builder:              str = ""
    authoritative_gate_passed:   bool = False
    final_author:                str = ""
    final_text_length:           int  = 0
    final_text_preview:          str = ""
    legacy_signatures_in_output: list[str] = field(default_factory=list)
    # Anomalies accumulated during the scan
    anomalies:                   list[dict] = field(default_factory=list)
    # Timestamps
    started_at:                  float = 0.0
    finished_at:                 float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ═════════════════════════════════════════════════════════════════
# Reconstruct trace from a response dict
# ═════════════════════════════════════════════════════════════════

def build_trace_from_response(
    response: dict,
    *,
    raw_query: str = "",
    entry_point: str = "API",
    handler: str = "ProductionRuntime.answer_json",
) -> ExecutionTrace:
    """Reconstruct an ExecutionTrace from a unified response dict.

    The response dict is treated as the single source of truth (REUP
    ensures nothing useful is written elsewhere).
    """
    t = ExecutionTrace(
        request_id=response.get("request_id", "") or "",
        raw_query=raw_query,
        entry_point=entry_point,
        handler=handler,
    )
    t.started_at = time.time()

    peal = response.get("_peal", {}) or {}
    req  = peal.get("requirements", {}) or {}
    st   = peal.get("state", {}) or {}

    # Routing / intent
    t.detected_intent = req.get("intent_tag", "") or ""
    t.domain = response.get("domain", "") or ""
    t.router_decision = t.detected_intent or "default"
    t.domain_resolution = (
        "pipeline_classification"
        if st.get("domain_resolved") else "unresolved"
    )

    # Pipeline state
    t.issue_graph_built    = bool(st.get("issue_graph_built"))
    t.issue_graph_size     = int(st.get("issue_graph_size", 0) or 0)
    t.mlre_required        = bool(req.get("needs_mlre"))
    t.mlre_executed        = bool(st.get("mlre_executed"))
    t.mlre_survivors_count = int(st.get("survivors_count", 0) or 0)
    mlre_trace = response.get("mlre", {}) or {}
    t.mlre_hypotheses_count = int(
        mlre_trace.get("hypothesis_count")
        or mlre_trace.get("total_hypotheses")
        or 0
    )
    t.dlp_required  = bool(req.get("needs_dlp"))
    t.dlp_executed  = bool(st.get("dlp_mode_decided"))
    t.dlp_mode      = st.get("dlp_mode", "") or ""
    t.ux_executed   = bool(response.get("ux"))

    # Composer / author
    t.final_author              = response.get("output_author", "") or ""
    t.composer_author_selected  = t.final_author
    notes = list(response.get("runtime_notes", []) or [])
    t.composer_inputs = _infer_composer_inputs(notes, response)

    # Legacy / exception
    t.legacy_called = _detect_legacy_calls(notes, response)
    t.exception_path_taken = any(
        "exception" in (n or "").lower() for n in notes
    )
    t.fallback_used = bool(response.get("fallback_used", False))
    # The unified pipeline always reports fallback_used=False.
    # An exception-path rescue still shows via output_author=internal_failure.
    if t.final_author == "internal_failure":
        t.exception_path_taken = True

    # Output
    t.output_builder = (
        "AuthoritativeOutputGate"
        if response.get("authoritative_execution_path")
           == "UNIFIED_LEGAL_RUNTIME"
        else "UNKNOWN_BUILDER"
    )
    t.authoritative_gate_passed = (
        response.get("authoritative_execution_path")
        == "UNIFIED_LEGAL_RUNTIME"
    )
    text = response.get("answer", "") or ""
    t.final_text_length = len(text)
    t.final_text_preview = text[:180]
    t.legacy_signatures_in_output = _scan_signatures(text, t.domain)

    t.finished_at = time.time()
    return t


def _infer_composer_inputs(notes: list[str], response: dict) -> list[str]:
    """Best-effort inference of which composer produced the text.

    Reads the runtime_notes and trace dicts attached to the response
    (mlre, dlp, ux) to list every producer that CONTRIBUTED.
    """
    inputs: list[str] = []
    has_mlre_used = any("mlre_output_used:true" in n for n in notes)
    has_dlp_mode  = any(n.startswith("dlp:mode=") for n in notes)
    has_pasl      = any(n.startswith("pasl:") for n in notes)
    has_mqe       = any(n.startswith("mqe:") for n in notes)
    has_aib       = any(n.startswith("aib_adaptation:") for n in notes)

    if has_mlre_used:
        inputs.append("MLRE")
    if has_dlp_mode:
        inputs.append("DLP")
    if has_mqe:
        inputs.append("MQE")
    if has_pasl:
        inputs.append("PASL")
    if has_aib:
        inputs.append("AIB")
    if response.get("ux"):
        inputs.append("UX")
    if response.get("output_author") == "fail_closed_pipeline":
        inputs.append("FAIL_CLOSED_PIPELINE")
    if response.get("output_author") == "internal_failure":
        inputs.append("INTERNAL_FAILURE")
    # Preserve order, de-dupe
    seen: set[str] = set()
    out: list[str] = []
    for i in inputs:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


_LEGACY_NOTE_PATTERNS = (
    "legacy_answer_replaced",
    "legacy_fallback",
    "legacy_path",
    "legacy:",
)


def _detect_legacy_calls(notes: list[str], response: dict) -> list[str]:
    calls: list[str] = []
    for n in notes:
        low = (n or "").lower()
        # "legacy_answer_replaced" is MLRE taking over — not a legacy CALL
        if low == "legacy_answer_replaced":
            continue
        for p in _LEGACY_NOTE_PATTERNS:
            if p in low and low != "legacy_answer_replaced":
                calls.append(n)
                break
    return calls


# ═════════════════════════════════════════════════════════════════
# Signature scan (Phase 7)
# ═════════════════════════════════════════════════════════════════

# Signatures that MUST NOT appear outside an explicit NOT_DRAFTABLE /
# SKELETON context.
_OUTPUT_SIGNATURE_PATTERNS = [
    (re.compile(r"تعذّر صياغة"),                "تعذّر_صياغة"),
    (re.compile(r"لم تتوفر شروط"),               "لم_تتوفر_شروط"),
    (re.compile(r"ما ينقص حالياً"),              "ما_ينقص_حالياً"),
    (re.compile(r"دفوع شكلية"),                   "دفوع_شكلية"),
    (re.compile(r"السند حكم قضائي"),              "السند_حكم_قضائي"),
    (re.compile(r"low_issue_coverage"),           "low_issue_coverage_raw"),
    (re.compile(r"no_bound_evidence"),            "no_bound_evidence_raw"),
    (re.compile(r"composite\s*[:=]\s*[\d.]+"),    "composite_score_raw"),
    (re.compile(r"محاضر اجتماعات الشركاء"),      "partner_minutes"),
    (re.compile(r"أقوى ما يدعمك[:：]"),          "strategic_strongest"),
    (re.compile(r"ما يُتوقع أن يدفع به الخصم"), "strategic_opponent"),
]


def _scan_signatures(text: str, domain: str = "") -> list[str]:
    hits: list[str] = []
    if not text:
        return hits
    # Allow signatures inside SKELETON / NOT_DRAFTABLE contexts
    in_skeleton = (
        "صياغة أولية" in text
        or "SKELETON DRAFT" in text
    )
    in_not_draftable = (
        "ما ينقص" in text and "ما يجعلها قابلة" in text
    )
    for pat, sig_id in _OUTPUT_SIGNATURE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        # Soft signatures allowed inside the structured contexts
        if sig_id in ("تعذّر_صياغة", "لم_تتوفر_شروط", "ما_ينقص_حالياً"):
            if in_skeleton or in_not_draftable:
                continue
        hits.append(sig_id)
    return hits


# ═════════════════════════════════════════════════════════════════
# Anomaly detection
# ═════════════════════════════════════════════════════════════════

def detect_anomalies(t: ExecutionTrace) -> list[dict]:
    """Scan the trace and return a list of anomaly dicts.

    Each anomaly dict has:
        {type, location, trigger, evidence, impact}
    """
    out: list[dict] = []

    # 1) ILLEGAL_ENTRY
    if not t.authoritative_gate_passed:
        out.append({
            "type":     "ILLEGAL_ENTRY",
            "location": "AuthoritativeOutputGate",
            "trigger":  "authoritative_execution_path missing",
            "evidence": f"output_builder={t.output_builder!r}",
            "impact":   "Response not emitted by the unified pipeline.",
        })

    # 2) MISROUTED_REQUEST
    if t.detected_intent == "drafting" and not t.dlp_required:
        out.append({
            "type":     "MISROUTED_REQUEST",
            "location": "detect_requirements",
            "trigger":  "drafting intent without DLP requirement",
            "evidence": f"intent={t.detected_intent!r} dlp_required={t.dlp_required}",
            "impact":   "Drafting path may not route to DLP.",
        })

    # 3) MLRE_BYPASS
    if t.mlre_required and not t.mlre_executed:
        out.append({
            "type":     "MLRE_BYPASS",
            "location": "core.production_runtime (MLRE stage)",
            "trigger":  "peal requires MLRE but state says not executed",
            "evidence": f"mlre_required=True mlre_executed=False",
            "impact":   "Reasoning shallow — MLRE multi-path enforcement lost.",
        })

    # 4) DLP_BYPASS
    if t.dlp_required and not t.dlp_executed:
        out.append({
            "type":     "DLP_BYPASS",
            "location": "core.drafting.drafting_engine.build_memo / DLP dispatch",
            "trigger":  "drafting intent present but no DLP mode decided",
            "evidence": f"dlp_required=True dlp_executed=False",
            "impact":   "Drafting routed without mode selection — legacy shape likely.",
        })

    # 5) ISSUE_GRAPH_MISSING
    if t.detected_intent not in ("empty", "smalltalk") \
            and not t.issue_graph_built:
        out.append({
            "type":     "ISSUE_GRAPH_MISSING",
            "location": "core.domain_pipeline.build_issue_graph",
            "trigger":  "legal query with no issue graph built",
            "evidence": f"issue_graph_size={t.issue_graph_size}",
            "impact":   "No issue-bound reasoning — evidence binding absent.",
        })

    # 6) LEGACY_EXECUTION
    if t.legacy_called:
        out.append({
            "type":     "LEGACY_EXECUTION",
            "location": "; ".join(t.legacy_called[:3]),
            "trigger":  "legacy invocation detected in runtime_notes",
            "evidence": f"legacy_calls={t.legacy_called[:3]}",
            "impact":   "Response text possibly composed by a retired path.",
        })

    # 7) EXCEPTION_FALLBACK
    if t.exception_path_taken and t.final_author == "internal_failure":
        out.append({
            "type":     "EXCEPTION_FALLBACK",
            "location": "core.production_runtime._emit_through_gate",
            "trigger":  "gate emitted internal_failure bundle",
            "evidence": f"final_author={t.final_author!r}",
            "impact":   "User got a structured failure instead of a normal answer.",
        })

    # 8) MERGE_LEAK — two PRIMARY authors in composer_inputs
    primary_authors = {"MLRE", "DLP", "FAIL_CLOSED_PIPELINE"}
    primary_hit = [a for a in t.composer_inputs if a in primary_authors]
    if len(primary_hit) > 1:
        out.append({
            "type":     "MERGE_LEAK",
            "location": "production_runtime composer dispatch",
            "trigger":  "multiple primary composers contributed text",
            "evidence": f"composer_inputs={t.composer_inputs}",
            "impact":   "Response text may mix outputs from two sources.",
        })

    # 9) MULTI_AUTHOR_OUTPUT — final_author ambiguous
    if not t.final_author:
        out.append({
            "type":     "NO_AUTHOR_CONTROL",
            "location": "AuthoritativeOutputGate._stamp_authority",
            "trigger":  "final_author missing on gate output",
            "evidence": "output_author field absent",
            "impact":   "Cannot attribute the response to a known composer.",
        })

    # 10) LEGACY_SIGNATURE_LEAK
    if t.legacy_signatures_in_output:
        out.append({
            "type":     "LEGACY_SIGNATURE_LEAK",
            "location": "final response answer text",
            "trigger":  "forbidden signature(s) detected in user-facing text",
            "evidence": f"signatures={t.legacy_signatures_in_output[:3]}",
            "impact":   "User visible text matches legacy template phrases.",
        })

    # 11) MISSING_AUTHOR_STAMP — never empty when unified
    if t.authoritative_gate_passed and not t.final_author:
        out.append({
            "type":     "MISSING_AUTHOR_STAMP",
            "location": "AuthoritativeOutputGate._stamp_authority",
            "trigger":  "authority path set but output_author empty",
            "evidence": f"author={t.final_author!r}",
            "impact":   "Internal authority accounting inconsistent.",
        })

    t.anomalies = out
    return out


# ═════════════════════════════════════════════════════════════════
# Human-readable reporting
# ═════════════════════════════════════════════════════════════════

def render_trace_report(t: ExecutionTrace) -> str:
    lines: list[str] = []
    lines.append(f"┌── TRACE  request_id={t.request_id or '—'}")
    lines.append(f"│  raw_query        : {t.raw_query[:80]!r}")
    lines.append(f"│  entry_point      : {t.entry_point}")
    lines.append(f"│  handler          : {t.handler}")
    lines.append(f"│  detected_intent  : {t.detected_intent}")
    lines.append(f"│  domain           : {t.domain}")
    lines.append(f"│  issue_graph      : built={t.issue_graph_built}  "
                 f"size={t.issue_graph_size}")
    lines.append(f"│  mlre             : required={t.mlre_required}  "
                 f"executed={t.mlre_executed}  "
                 f"hypotheses={t.mlre_hypotheses_count}  "
                 f"survivors={t.mlre_survivors_count}")
    lines.append(f"│  dlp              : required={t.dlp_required}  "
                 f"executed={t.dlp_executed}  "
                 f"mode={t.dlp_mode or '—'}")
    lines.append(f"│  ux_executed      : {t.ux_executed}")
    lines.append(f"│  composer_inputs  : {t.composer_inputs}")
    lines.append(f"│  composer_author  : {t.composer_author_selected}")
    lines.append(f"│  legacy_called    : {t.legacy_called}")
    lines.append(f"│  exception_path   : {t.exception_path_taken}")
    lines.append(f"│  fallback_used    : {t.fallback_used}")
    lines.append(f"│  output_builder   : {t.output_builder}")
    lines.append(f"│  gate_passed      : {t.authoritative_gate_passed}")
    lines.append(f"│  final_author     : {t.final_author}")
    lines.append(f"│  final_text_len   : {t.final_text_length}")
    lines.append(f"│  signatures_in_out: {t.legacy_signatures_in_output}")
    lines.append(f"│  anomalies        : {len(t.anomalies)}")
    if t.anomalies:
        for a in t.anomalies:
            lines.append(f"│    • {a.get('type')} "
                         f"→ {a.get('location')}  "
                         f"trigger={a.get('trigger')}")
    lines.append("└──")
    return "\n".join(lines)


def render_root_causes_report(
    traces: list[ExecutionTrace],
) -> tuple[list[dict], str]:
    """Collect anomalies across traces into ROOT_CAUSES + a VERDICT."""
    root_causes: list[dict] = []
    by_type: dict[str, int] = {}
    by_location: dict[str, int] = {}
    for t in traces:
        for a in t.anomalies:
            root_causes.append({
                **a,
                "request_id": t.request_id,
                "raw_query":  t.raw_query[:60],
                "evidence_trace": {
                    "mlre_required":  t.mlre_required,
                    "mlre_executed":  t.mlre_executed,
                    "dlp_required":   t.dlp_required,
                    "dlp_executed":   t.dlp_executed,
                    "survivors":      t.mlre_survivors_count,
                    "composer_inputs": t.composer_inputs,
                    "final_author":   t.final_author,
                    "signatures":     t.legacy_signatures_in_output,
                },
            })
            by_type[a.get("type", "?")] = by_type.get(a.get("type", "?"), 0) + 1
            by_location[a.get("location", "?")] = (
                by_location.get(a.get("location", "?"), 0) + 1
            )

    verdict = _build_verdict(by_type, by_location, traces)
    return root_causes, verdict


def _build_verdict(by_type: dict,
                     by_location: dict,
                     traces: list[ExecutionTrace]) -> str:
    total = sum(by_type.values())
    if total == 0:
        return (
            "VERDICT: NO ANOMALIES DETECTED.\n"
            "All traced requests routed through UNIFIED_LEGAL_RUNTIME, passed "
            "the gate, and produced text with no legacy signatures, no "
            "MLRE/DLP bypass, no exception fallback, and no merge leaks."
        )

    # Dominant anomaly
    dom_type, dom_count = max(by_type.items(), key=lambda kv: kv[1])
    dom_loc,  _         = max(by_location.items(), key=lambda kv: kv[1])

    diagnosis: list[str] = []
    if dom_type in ("MLRE_BYPASS", "DLP_BYPASS", "ISSUE_GRAPH_MISSING"):
        diagnosis.append("The problem is in ROUTING / pre-pipeline state.")
    elif dom_type == "MERGE_LEAK":
        diagnosis.append("The problem is in the COMPOSER dispatch.")
    elif dom_type == "ILLEGAL_ENTRY":
        diagnosis.append("The problem is in the ENTRY path.")
    elif dom_type == "EXCEPTION_FALLBACK":
        diagnosis.append("The problem is in exception handling depth.")
    elif dom_type == "LEGACY_SIGNATURE_LEAK":
        diagnosis.append("The problem is in the COMPOSER output (legacy "
                          "phrases surviving the firewall).")
    elif dom_type == "LEGACY_EXECUTION":
        diagnosis.append("The problem is that a legacy code path was called.")
    else:
        diagnosis.append(f"The problem category is '{dom_type}'.")

    lines = [
        f"VERDICT: {total} anomalies across {len(traces)} traced requests.",
        f"  • Dominant anomaly : {dom_type} ({dom_count} × occurrences)",
        f"  • Dominant location: {dom_loc}",
        "",
        "Anomaly breakdown (by type):",
    ]
    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"  • {k:28s} × {v}")
    lines.append("")
    lines.append("Diagnosis:")
    for d in diagnosis:
        lines.append(f"  → {d}")
    return "\n".join(lines)
