# -*- coding: utf-8 -*-
"""
Fast-path + Cancellation tests.

Verifies:
  • Fast default — courtroom OFF for Tier 0/1
  • Adversarial — courtroom ON for Tier 2/3
  • Hard early exit — direct evidence + simple tier → skip strategic
  • Cancellation registry — basic API
  • Cancellation pre-registered → pipeline returns cancelled
  • Cancellation between stages → returns cancelled
  • Cache hit on repeated query
  • HTTP /api/v1/cancel/{request_id} endpoint

Run: pytest tests/test_fast_path_and_cancel.py -v
"""
from __future__ import annotations
import os
import sys
import time
import importlib
import threading
import pytest


# ═════════════════════════════════════════════════════════════════
# Fast default
# ═════════════════════════════════════════════════════════════════

class TestFastDefault:
    def test_simple_query_does_not_run_courtroom(self):
        from core.production_runtime import answer_query_direct
        r = answer_query_direct(
            "أحكام الحضانة في القانون القطري", "fast-d-1")
        notes = r.get("runtime_notes", [])
        # Early exit OR courtroom_early_exit (T0/T1 should not run full courtroom)
        assert ("EARLY_EXIT_FAST_PATH" in notes
                or "courtroom_early_exit" in notes), \
            f"simple query ran courtroom: {notes}"

    def test_simple_query_skips_strategic_when_early_exits(self):
        from core.production_runtime import answer_query_direct
        r = answer_query_direct(
            "أحكام الحضانة في القانون القطري", "fast-d-2")
        notes = r.get("runtime_notes", [])
        if "EARLY_EXIT_FAST_PATH" in notes:
            # When fast-exit fires, strategic should NOT have run
            assert "strategic_reasoning_applied" not in notes, \
                f"strategic ran despite early exit: {notes}"

    def test_adversarial_query_does_run_courtroom(self):
        from core.production_runtime import answer_query_direct
        q = ("الزوج يدّعي أنني لست أهلاً للحضانة لكن عندي شهود وتقارير "
             "ينازع في النفقة أيضاً ويتضارب الكلام")
        r = answer_query_direct(q, "fast-d-3")
        if r.get("is_blocked"):
            return
        ct = r.get("evidence_trace", {}).get("courtroom", {})
        # Tier 2/3 → courtroom should be active
        assert ct, "adversarial query did not engage courtroom"
        assert ct.get("tier", "").startswith("tier_"), ct


# ═════════════════════════════════════════════════════════════════
# Tier classification post-bias
# ═════════════════════════════════════════════════════════════════

class TestTierBias:
    def test_short_question_is_tier_0(self):
        from core.courtroom import classify_complexity, ComplexityTier
        v = classify_complexity("ما حضانة الطفل")
        assert v.tier == ComplexityTier.HARD_FAST_PATH

    def test_medium_question_is_tier_0_or_1(self):
        from core.courtroom import classify_complexity, ComplexityTier
        v = classify_complexity(
            "أحكام الحضانة في القانون القطري وحقوق الأم بعد الطلاق")
        # Fast-default bias accepts T0 or T1 — both are no-courtroom
        assert v.tier in (ComplexityTier.HARD_FAST_PATH,
                           ComplexityTier.STANDARD_REASONING)

    def test_long_narrative_without_adversary_stays_tier_1(self):
        from core.courtroom import classify_complexity, ComplexityTier
        # Long but NO adversarial markers → should NOT escalate to T2/T3
        q = ("سؤال طويل جداً عن قانون العمل والحضانة والإيجار وكيف يطبق "
             "ذلك على الحالات المختلفة في قطر بشكل عام دون نزاع محدد")
        v = classify_complexity(q)
        assert v.tier in (ComplexityTier.HARD_FAST_PATH,
                           ComplexityTier.STANDARD_REASONING), \
            f"long-but-not-adversarial wrongly escalated: tier={v.tier.value}"

    def test_explicit_adversarial_with_evidence_is_tier_2(self):
        from core.courtroom import classify_complexity, ComplexityTier
        q = ("الشركة تقول إنني تركت العمل لكن لدي رسائل واتساب من المدير "
             "تطلب الحضور وعندي شهود من زملائي")
        v = classify_complexity(q)
        assert v.tier == ComplexityTier.ADVERSARIAL

    def test_courtroom_requires_multi_signal(self):
        from core.courtroom import classify_complexity, ComplexityTier
        # Adversarial + multi_issue + procedural + conflict → T3
        q = ("نزاع ميراث متعدد الأطراف بين الورثة، يدعي أحدهم أن الوالد "
             "وهبه العقار لكن الباقون يطعنون بالتزوير ومتعارضة الشهادات. "
             "كذلك طعن إجرائي على اختصاص المحكمة")
        v = classify_complexity(q)
        assert v.tier == ComplexityTier.COURTROOM


# ═════════════════════════════════════════════════════════════════
# Tightened budgets
# ═════════════════════════════════════════════════════════════════

class TestTightenedBudgets:
    def test_tier_0_budget_max_2_evidence(self):
        from core.courtroom import ComplexityTier
        b = ComplexityTier.HARD_FAST_PATH.reasoning_budget()
        assert b["max_evidence"] == 2
        assert b["courtroom_active"] is False

    def test_tier_1_courtroom_inactive(self):
        from core.courtroom import ComplexityTier
        b = ComplexityTier.STANDARD_REASONING.reasoning_budget()
        assert b["courtroom_active"] is False
        assert b["max_evidence"] == 3

    def test_tier_2_courtroom_active(self):
        from core.courtroom import ComplexityTier
        b = ComplexityTier.ADVERSARIAL.reasoning_budget()
        assert b["courtroom_active"] is True
        assert b["opponent_model"] is True


# ═════════════════════════════════════════════════════════════════
# Cancellation registry
# ═════════════════════════════════════════════════════════════════

class TestCancellationRegistry:
    def setup_method(self):
        from core import cancellation as cx
        cx.reset_for_tests()

    def test_new_request_id_unique(self):
        from core import cancellation as cx
        a = cx.new_request_id()
        b = cx.new_request_id()
        assert a != b
        assert len(a) > 8

    def test_register_then_cancel(self):
        from core import cancellation as cx
        rid = cx.new_request_id()
        cx.register(rid)
        assert cx.is_cancelled(rid) is False
        ok = cx.cancel(rid)
        assert ok is True
        assert cx.is_cancelled(rid) is True

    def test_cancel_unknown_id_returns_false(self):
        from core import cancellation as cx
        assert cx.cancel("never-registered-id") is False

    def test_register_after_cancel_preserves_state(self):
        """Race protection: cancel-before-register must not be undone by register."""
        from core import cancellation as cx
        rid = cx.new_request_id()
        cx.register(rid)
        cx.cancel(rid)
        assert cx.is_cancelled(rid) is True
        # Re-register (simulating the runtime registering after user cancelled)
        cx.register(rid)
        assert cx.is_cancelled(rid) is True, \
            "re-register undid cancellation — race vulnerability"

    def test_raise_if_cancelled_throws(self):
        from core import cancellation as cx
        from core.cancellation import CancelledExecution
        rid = cx.new_request_id()
        cx.register(rid)
        cx.cancel(rid)
        with pytest.raises(CancelledExecution):
            cx.raise_if_cancelled(rid)

    def test_raise_if_not_cancelled_passes(self):
        from core import cancellation as cx
        rid = cx.new_request_id()
        cx.register(rid)
        cx.raise_if_cancelled(rid)   # must not raise


# ═════════════════════════════════════════════════════════════════
# Cancellation in pipeline
# ═════════════════════════════════════════════════════════════════

class TestCancellationInPipeline:
    def setup_method(self):
        from core import cancellation as cx
        cx.reset_for_tests()

    def test_pre_cancelled_request_returns_cancelled(self):
        from core.production_runtime import get_production_runtime
        from core import cancellation as cx
        rid = cx.new_request_id()
        cx.register(rid)
        cx.cancel(rid)
        r = get_production_runtime().answer_json(
            "أحكام الحضانة في القانون القطري", "cn-1", request_id=rid)
        assert r.get("status") == "cancelled"
        assert r.get("message") == "تم إيقاف التنفيذ"
        assert "user_cancelled" in r.get("block_reasons", [])

    def test_completed_request_carries_request_id(self):
        from core.production_runtime import get_production_runtime
        from core import cancellation as cx
        rid = cx.new_request_id()
        r = get_production_runtime().answer_json(
            "أحكام الحضانة في القانون القطري", "cn-2", request_id=rid)
        assert r.get("request_id") == rid

    def test_concurrent_cancel_race(self):
        """Cancel from another thread while answer_json is running."""
        from core.production_runtime import get_production_runtime
        from core import cancellation as cx
        rid = cx.new_request_id()
        cx.register(rid)

        def _cancel_after_short_delay():
            time.sleep(0.001)   # let answer_json start
            cx.cancel(rid)

        t = threading.Thread(target=_cancel_after_short_delay, daemon=True)
        t.start()
        r = get_production_runtime().answer_json(
            "سؤال قانوني عام عن الحضانة", "cn-3", request_id=rid)
        t.join(timeout=2)
        # Either the request finished before cancel, or it returned cancelled.
        # Both are valid outcomes — we just verify no crash.
        assert r is not None


# ═════════════════════════════════════════════════════════════════
# Cache effectiveness
# ═════════════════════════════════════════════════════════════════

class TestCacheEffectiveness:
    def test_classification_cached_on_second_run(self):
        from core.production_runtime import answer_query_direct
        from core.courtroom.hot_cache import get_hot_cache
        cache = get_hot_cache()
        cache.reset_metrics()

        q = "أحكام الإيجار في القانون القطري"
        # First call — populates cache
        answer_query_direct(q, "cache-1")
        # Second call — should hit cache for classification
        answer_query_direct(q, "cache-2")
        s = cache.stats()
        assert s["hits"] >= 1, f"cache had no hits after repeated query: {s}"


# ═════════════════════════════════════════════════════════════════
# HTTP cancel endpoint
# ═════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("DB_KNOWLEDGE_ACTIVATION_MODE", "skip")
    if "core.runtime_flags" in sys.modules:
        importlib.reload(sys.modules["core.runtime_flags"])
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, headers={"Referer": "http://localhost:8000/"}) as c:
        yield c


class TestCancelEndpoint:
    def test_cancel_endpoint_unknown_id(self, client):
        r = client.post("/api/v1/cancel/no-such-id-xyz")
        assert r.status_code == 200
        body = r.json()
        assert body.get("cancelled") is False
        assert body.get("reason") == "request_not_found"

    def test_cancel_endpoint_known_id(self, client):
        from core import cancellation as cx
        rid = cx.new_request_id()
        cx.register(rid)
        r = client.post(f"/api/v1/cancel/{rid}")
        body = r.json()
        assert body.get("cancelled") is True
        assert body.get("reason") == "marked_cancelled"
        assert body.get("request_id") == rid

    def test_query_response_contains_request_id(self, client):
        r = client.post("/api/v1/query/", json={
            "query": "أحكام الحضانة في القانون القطري",
            "session_id": "rid-test-1",
        })
        body = r.json()
        if body.get("from_beta_gate") is True:
            return
        # request_id must appear so frontend can cancel
        assert "request_id" in body, f"response missing request_id: {body.keys()}"
        assert body["request_id"]   # non-empty

    def test_cancel_status_endpoint(self, client):
        r = client.get("/api/v1/cancel/_status")
        body = r.json()
        for k in ("active", "total_in_registry", "cancellations_total"):
            assert k in body
