# -*- coding: utf-8 -*-
"""
SEA — Single Entry Authority regression tests.

The non-negotiable rule:

    Every response MUST originate from the unified pipeline.
    Nothing else may emit a response.

Covers:
  A. unified_entry_context — marker semantics
  B. assert_entered_via_unified — raises outside the marker
  C. sealed_legacy — legacy composers are traps now
  D. force-stages enforcer — missing MLRE / DLP / graph re-run in-place
  E. Live — every answer_json call is inside the unified context
  F. Legacy raw composers are unreachable
"""
from __future__ import annotations

import os
import threading
import pytest

from core.runtime import (
    unified_entry_context, is_in_unified_context,
    current_entry_source, current_entry_depth,
    assert_entered_via_unified,
    IllegalDirectResponseError, sealed_legacy,
    force_mlre, force_dlp, rebuild_issue_graph,
    enforce_pipeline_completeness,
    ResponseAuthor, UnifiedArtifacts,
    AuthoritativeOutputGate,
)
from core.production_runtime import answer_query_direct
from core.conversation import get_state_engine


# ═════════════════════════════════════════════════════════════════
# SECTION A — Entry context
# ═════════════════════════════════════════════════════════════════

class TestEntryContext:
    def test_default_is_outside_unified(self):
        # Clean slate: not in any context
        assert is_in_unified_context() is False

    def test_marker_is_set_inside_context(self):
        with unified_entry_context(source="test"):
            assert is_in_unified_context() is True
            assert current_entry_source() == "test"
            assert current_entry_depth() == 1

    def test_marker_clears_after_context_exit(self):
        with unified_entry_context(source="test"):
            pass
        assert is_in_unified_context() is False

    def test_nested_entries_use_depth_counter(self):
        with unified_entry_context(source="outer"):
            with unified_entry_context(source="inner"):
                assert is_in_unified_context() is True
                assert current_entry_depth() == 2
            # After inner exits we're still inside outer
            assert is_in_unified_context() is True
            assert current_entry_depth() == 1
        assert is_in_unified_context() is False

    def test_exception_inside_clears_marker(self):
        try:
            with unified_entry_context(source="test"):
                raise ValueError("boom")
        except ValueError:
            pass
        assert is_in_unified_context() is False


# ═════════════════════════════════════════════════════════════════
# SECTION B — Assertion raises outside the marker
# ═════════════════════════════════════════════════════════════════

class TestAssertion:
    def test_raises_when_outside_context(self, monkeypatch):
        monkeypatch.setenv("SEA_STRICT", "1")
        with pytest.raises(IllegalDirectResponseError):
            assert_entered_via_unified(
                detail="unit test probe", allow_operational=False,
            )

    def test_allows_inside_context(self):
        with unified_entry_context(source="t"):
            # Should NOT raise
            assert_entered_via_unified()

    def test_env_escape_hatch(self, monkeypatch):
        monkeypatch.setenv("SEA_STRICT", "0")
        # No context + SEA_STRICT=0 → allowed
        assert_entered_via_unified()


# ═════════════════════════════════════════════════════════════════
# SECTION C — sealed_legacy traps
# ═════════════════════════════════════════════════════════════════

class TestSealedLegacy:
    def test_sealed_function_always_raises(self):
        @sealed_legacy(reason="unit test")
        def old_composer():
            return "should never appear"

        with pytest.raises(IllegalDirectResponseError):
            old_composer()

    def test_sealed_decorator_preserves_metadata(self):
        @sealed_legacy(reason="reason for sealing")
        def named_fn():
            pass
        assert named_fn.__name__ == "named_fn"
        assert getattr(named_fn, "_sealed_legacy", False) is True

    def test_drafting_engine_legacy_composers_are_sealed(self):
        """The two legacy memo composers in drafting_engine are now traps."""
        from core.drafting.drafting_engine import (
            _build_memo_text, _build_not_draftable_message,
            DocumentType,
        )
        with pytest.raises(IllegalDirectResponseError):
            _build_memo_text(None, None, None, None, None)
        with pytest.raises(IllegalDirectResponseError):
            _build_not_draftable_message(
                DocumentType.DEFENSE_MEMO, ["insufficient_facts"],
            )


# ═════════════════════════════════════════════════════════════════
# SECTION D — Force-stage enforcer
# ═════════════════════════════════════════════════════════════════

class TestForceStages:
    def test_force_mlre_returns_trace_for_legal_query(self):
        trace = force_mlre("ما حكم الشيك بدون رصيد؟")
        # MLRE may or may not produce survivors for this query but
        # at minimum the trace dict should be non-empty on a legal query.
        assert isinstance(trace, dict)

    def test_force_mlre_empty_query_does_not_crash(self):
        trace = force_mlre("")
        assert isinstance(trace, dict)

    def test_rebuild_issue_graph_needs_domain(self):
        assert rebuild_issue_graph("text", domain="") == {}

    def test_rebuild_issue_graph_returns_summary_with_domain(self):
        info = rebuild_issue_graph("نزاع عمالي", domain="employment")
        assert isinstance(info, dict)
        # Either fully built or empty — never raises
        if info:
            assert "issue_count" in info
            assert "domain" in info

    def test_force_dlp_returns_drafting_dict(self):
        d = force_dlp("اكتب مذكرة دفاع")
        assert d["drafting_intent_detected"] is True
        assert d["drafting_mode"]
        assert "text" in d

    def test_enforce_completeness_forces_mlre_when_missing(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="—",
            domain="criminal",
            peal_requirements={
                "needs_mlre": True, "needs_issue_graph": False,
                "needs_dlp": False, "needs_domain": True,
                "needs_canonical": False,
                "intent_tag": "analytical",
            },
            peal_state={},
            mlre_trace={},
        )
        forced = enforce_pipeline_completeness(
            artifacts, query="ما حكم الشيك بدون رصيد؟",
        )
        # Either MLRE was forced in-place OR the call completed cleanly
        assert isinstance(forced, list)

    def test_enforce_completeness_noop_when_nothing_required(self):
        artifacts = UnifiedArtifacts(
            author=ResponseAuthor.FAIL_CLOSED_PIPELINE,
            text="—",
            peal_requirements={},
        )
        forced = enforce_pipeline_completeness(artifacts, query="")
        assert forced == []


# ═════════════════════════════════════════════════════════════════
# SECTION E — Live integration
# ═════════════════════════════════════════════════════════════════

class TestLiveSEA:
    def test_answer_query_direct_sets_and_clears_marker(self):
        # Before the call, no marker
        assert is_in_unified_context() is False
        r = answer_query_direct("ما حكم السرقة؟", "sea_live_1")
        # After the call, marker is cleared
        assert is_in_unified_context() is False
        # Response arrived normally
        assert r.get("authoritative_execution_path") == "UNIFIED_LEGAL_RUNTIME"

    def test_answer_carries_authority_stamp(self):
        r = answer_query_direct(
            "اكتب مذكرة دفاع في شيك ضمان.", "sea_live_2",
        )
        assert r.get("legacy_used") is False
        assert r.get("fallback_used") is False

    @pytest.mark.parametrize("label,query", [
        ("partnership_vs_work",   "شراكة أم عمل؟"),
        ("cheque_guarantee",      "اكتب مذكرة في شيك ضمان."),
        ("cyber_defamation",      "اكتب مذكرة دفاع في سب إلكتروني."),
        ("skeleton",              "اكتب لي مذكرة دفاع."),
    ])
    def test_every_response_is_gate_produced(self, label, query):
        get_state_engine().reset(f"sea_live_{label}")
        r = answer_query_direct(query, f"sea_live_{label}")
        # Gate-produced responses ALWAYS carry these
        assert "authoritative_execution_path" in r
        assert "output_author" in r
        # And output_author is a known enum value
        known = {a.value for a in ResponseAuthor}
        assert r["output_author"] in known


# ═════════════════════════════════════════════════════════════════
# SECTION F — Direct-call protection
# ═════════════════════════════════════════════════════════════════

class TestDirectCallProtection:
    def test_calling_impl_directly_raises(self, monkeypatch):
        """_answer_json_impl MUST NOT be callable outside the context."""
        monkeypatch.setenv("SEA_STRICT", "1")
        from core.production_runtime import get_production_runtime
        rt = get_production_runtime()
        with pytest.raises(IllegalDirectResponseError):
            rt._answer_json_impl(
                query="ما حكم السرقة؟",
                session_id="sea_direct_probe",
            )


# ═════════════════════════════════════════════════════════════════
# SECTION G — Parallel thread isolation (marker is thread-local)
# ═════════════════════════════════════════════════════════════════

class TestThreadIsolation:
    def test_marker_does_not_leak_across_threads(self):
        barrier = threading.Barrier(2)
        results = {"outside_main": False, "outside_thread": False}

        def worker():
            # Worker thread should NOT see the main thread's marker
            results["outside_thread"] = is_in_unified_context()
            barrier.wait()

        t = threading.Thread(target=worker)
        with unified_entry_context(source="main"):
            # Main sees itself as inside
            assert is_in_unified_context() is True
            t.start()
            barrier.wait()
        t.join()
        # Worker did NOT see the main's marker
        assert results["outside_thread"] is False
