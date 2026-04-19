# -*- coding: utf-8 -*-
"""
ETLD — unit tests for the trace + anomaly detector.

These tests confirm the instrument itself reports correctly.
They do NOT emit fixes — diagnosis only.
"""
from __future__ import annotations

import pytest

from core.runtime.etld import (
    ExecutionTrace, build_trace_from_response, detect_anomalies,
    render_trace_report, render_root_causes_report,
)


# ═════════════════════════════════════════════════════════════════
# SECTION A — Trace reconstruction
# ═════════════════════════════════════════════════════════════════

class TestTraceReconstruction:
    def test_minimum_response_produces_trace(self):
        resp = {
            "answer": "جواب",
            "domain": "criminal",
            "output_author": "mlre_output_composer",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "_peal": {
                "requirements": {"needs_mlre": True, "intent_tag": "multi_path_analysis"},
                "state": {
                    "mlre_executed": True, "survivors_count": 3,
                    "issue_graph_built": True, "domain_resolved": True,
                },
            },
            "mlre": {"surviving_count": 3, "total_hypotheses": 5},
            "runtime_notes": ["mlre_output_used:true"],
        }
        t = build_trace_from_response(resp, raw_query="q")
        assert t.authoritative_gate_passed is True
        assert t.final_author == "mlre_output_composer"
        assert t.mlre_executed is True
        assert t.mlre_survivors_count == 3
        assert "MLRE" in t.composer_inputs

    def test_trace_exposes_dlp_mode(self):
        resp = {
            "answer": "memo",
            "domain": "criminal",
            "output_author": "dlp_conditional_draft",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "_peal": {
                "requirements": {"needs_dlp": True},
                "state": {
                    "dlp_mode_decided": True, "dlp_mode": "conditional",
                    "issue_graph_built": True, "domain_resolved": True,
                    "mlre_executed": True,
                },
            },
            "runtime_notes": ["dlp:mode=conditional"],
        }
        t = build_trace_from_response(resp, raw_query="q")
        assert t.dlp_executed is True
        assert t.dlp_mode == "conditional"
        assert "DLP" in t.composer_inputs


# ═════════════════════════════════════════════════════════════════
# SECTION B — Anomaly detection
# ═════════════════════════════════════════════════════════════════

class TestAnomalyDetection:
    def test_illegal_entry_flagged(self):
        resp = {"answer": "x"}  # no authority stamp
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        assert any(a["type"] == "ILLEGAL_ENTRY" for a in t.anomalies)

    def test_mlre_bypass_flagged(self):
        resp = {
            "answer": "x",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "output_author": "fail_closed_pipeline",
            "_peal": {
                "requirements": {"needs_mlre": True, "intent_tag": "analytical"},
                "state": {"mlre_executed": False, "issue_graph_built": True,
                          "domain_resolved": True},
            },
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        assert any(a["type"] == "MLRE_BYPASS" for a in t.anomalies)

    def test_dlp_bypass_flagged(self):
        resp = {
            "answer": "x",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "output_author": "dlp_full_draft",
            "_peal": {
                "requirements": {"needs_dlp": True, "intent_tag": "drafting"},
                "state": {"dlp_mode_decided": False,
                          "issue_graph_built": True,
                          "domain_resolved": True, "mlre_executed": True},
            },
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        assert any(a["type"] == "DLP_BYPASS" for a in t.anomalies)

    def test_legacy_signature_leak_flagged(self):
        resp = {
            "answer": "📌 لم تتوفر شروط إصدار جواب قانوني نهائي.",
            "domain": "inheritance",
            "output_author": "fail_closed_pipeline",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "_peal": {
                "requirements": {"needs_mlre": True, "intent_tag": "analytical"},
                "state": {"mlre_executed": True, "issue_graph_built": True,
                          "domain_resolved": True},
            },
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        assert any(a["type"] == "LEGACY_SIGNATURE_LEAK" for a in t.anomalies)

    def test_exception_fallback_flagged(self):
        resp = {
            "answer": "تعذّر إنتاج إجابة قانونية آمنة...",
            "output_author": "internal_failure",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "runtime_notes": ["internal_failure:gate_violation"],
            "_peal": {
                "requirements": {"needs_mlre": True},
                "state": {},
            },
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        assert any(a["type"] == "EXCEPTION_FALLBACK" for a in t.anomalies)

    def test_clean_response_no_anomalies(self):
        resp = {
            "answer": "**التكييف المرجَّح:** مسؤولية مدنية.\nومؤدى ذلك…",
            "domain": "civil",
            "output_author": "mlre_output_composer",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "runtime_notes": ["mlre_output_used:true"],
            "_peal": {
                "requirements": {"needs_mlre": True,
                                   "intent_tag": "multi_path_analysis"},
                "state": {"mlre_executed": True, "survivors_count": 3,
                          "issue_graph_built": True, "domain_resolved": True,
                          "pivots_count": 1, "pivot_in_output": True},
            },
            "mlre": {"surviving_count": 3},
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        # No anomalies expected on a fully-unified clean response
        assert t.anomalies == []


# ═════════════════════════════════════════════════════════════════
# SECTION C — Report rendering
# ═════════════════════════════════════════════════════════════════

class TestReportRendering:
    def test_render_trace_report_is_multiline_and_contains_author(self):
        resp = {
            "answer": "x",
            "domain": "criminal",
            "output_author": "mlre_output_composer",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "_peal": {"requirements": {}, "state": {}},
        }
        t = build_trace_from_response(resp, raw_query="q")
        report = render_trace_report(t)
        assert "TRACE" in report
        assert "mlre_output_composer" in report

    def test_root_causes_empty_on_clean_traces(self):
        resp = {
            "answer": "**التكييف**",
            "domain": "civil",
            "output_author": "mlre_output_composer",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "runtime_notes": ["mlre_output_used:true"],
            "_peal": {
                "requirements": {"needs_mlre": True},
                "state": {"mlre_executed": True, "issue_graph_built": True,
                          "domain_resolved": True, "survivors_count": 3},
            },
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        rc, verdict = render_root_causes_report([t])
        assert rc == []
        assert "NO ANOMALIES" in verdict

    def test_root_causes_populated_on_leaks(self):
        resp = {
            "answer": "ما ينقص حالياً: أدلة إضافية.",
            "domain": "inheritance",
            "output_author": "fail_closed_pipeline",
            "authoritative_execution_path": "UNIFIED_LEGAL_RUNTIME",
            "_peal": {
                "requirements": {"needs_mlre": True,
                                   "intent_tag": "analytical"},
                "state": {"mlre_executed": True, "issue_graph_built": True,
                          "domain_resolved": True, "survivors_count": 2},
            },
        }
        t = build_trace_from_response(resp, raw_query="q")
        detect_anomalies(t)
        rc, verdict = render_root_causes_report([t])
        assert len(rc) >= 1
        assert "LEGACY_SIGNATURE_LEAK" in verdict
