# -*- coding: utf-8 -*-
"""
CORE EXECUTION REBUILD — Test Suite
=====================================
42 tests covering:
 - Request isolation (RequestContext)
 - Hard routing (HardRouter)
 - Cache safety (SafeCache)
 - Context isolation (ContextGuard)
 - Pipeline execution flow (8 strict steps)
 - Grounding enforcement (HARD GATE)
 - Output structure lock (StructuredOutput)
 - Performance / timeout / early exit
 - Error containment
 - Stability under repeated calls
"""
from __future__ import annotations
import time


def run_core_execution_tests() -> dict:
    from core.execution_pipeline import (
        RequestContext, HardRouter, RouterResult, QueryType,
        SafeCache, ContextGuard, SafeExecutionWrapper,
        StructuredOutput, ExecutionPipeline, execute_pipeline,
        get_pipeline,
    )

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    pipeline = ExecutionPipeline()
    router = HardRouter()
    cache = SafeCache()
    guard = ContextGuard()

    # ══════════════════════════════════════════════════════════════
    # A. Request Isolation (T01-T08)
    # ══════════════════════════════════════════════════════════════

    # T01: every RequestContext gets a unique request_id
    c1 = RequestContext.create("سؤال 1")
    c2 = RequestContext.create("سؤال 2")
    test("T01: each request gets unique request_id",
         c1.request_id != c2.request_id and c1.request_id.startswith("req_"))

    # T02: missing session_id → auto-generated unique session
    c3 = RequestContext.create("سؤال", session_id=None)
    c4 = RequestContext.create("سؤال", session_id=None)
    test("T02: missing session_id → unique generated sessions",
         c3.session_id != c4.session_id and c3.session_id.startswith("anon_"),
         f"sid3={c3.session_id} sid4={c4.session_id}")

    # T03: explicit session_id preserved
    c5 = RequestContext.create("q", session_id="user_alice")
    test("T03: explicit session_id preserved",
         c5.session_id == "user_alice")

    # T04: 'default' session NOT shared across IPs
    c6 = RequestContext.create("q", session_id="default",
                                  request_ip="1.1.1.1",
                                  request_headers={"user-agent": "client_a"})
    c7 = RequestContext.create("q", session_id="default",
                                  request_ip="2.2.2.2",
                                  request_headers={"user-agent": "client_b"})
    test("T04: 'default' session isolated per client",
         c6.session_id != c7.session_id)

    # T05: isolated_memory is per-request (not shared)
    c1.isolated_memory["k"] = "v1"
    c2.isolated_memory["k"] = "v2"
    test("T05: isolated_memory not shared across requests",
         c1.isolated_memory["k"] == "v1" and c2.isolated_memory["k"] == "v2")

    # T06: pipeline_steps_completed isolated
    c1.mark_step("step_a")
    c2.mark_step("step_b")
    test("T06: pipeline_steps tracked per request",
         "step_a" in c1.pipeline_steps_completed
         and "step_b" not in c1.pipeline_steps_completed)

    # T07: timestamp recorded
    test("T07: timestamp recorded on context creation",
         c1.timestamp > 0)

    # T08: raw_query preserved as-is
    c8 = RequestContext.create("  بعض المسافات   ")
    test("T08: raw_query stripped",
         c8.raw_query == "بعض المسافات")

    # ══════════════════════════════════════════════════════════════
    # B. Hard Routing (T09-T15)
    # ══════════════════════════════════════════════════════════════

    # T09: empty query → REJECT
    r = router.route("")
    test("T09: empty query → REJECT",
         r.query_type == QueryType.REJECT)

    # T10: greeting → GREETING type
    r = router.route("مرحبا")
    test("T10: greeting → GREETING type",
         r.query_type == QueryType.GREETING)

    # T11: employment query → employment domain
    r = router.route("فصلوني من العمل وعندي تحويلات راتب، نقاط ضعفي؟")
    test("T11: employment query → employment domain",
         r.domain == "employment"
         and r.query_type == QueryType.LEGAL_CONSULTATION,
         f"got domain={r.domain} type={r.query_type.value}")

    # T12: criminal query → criminal domain
    r = router.route("تم اتهامي في قضية مخدرات، ما نقاط الدفاع؟")
    test("T12: criminal query → criminal domain",
         r.domain == "criminal")

    # T13: family query → family domain
    r = router.route("أنا منفصل عن زوجتي وفيه خلاف على الحضانة")
    test("T13: family query → family domain",
         r.domain == "family")

    # T14: rental query → rental domain
    r = router.route("عندي مستأجر متأخر بالإيجار وأبغى أطلعه")
    test("T14: rental query → rental domain",
         r.domain == "rental")

    # T15: general query (no clear domain) → 'general'
    r = router.route("ما هي حقوق الإنسان في القانون")
    test("T15: ambiguous query → general or fallback",
         r.domain in ("general", "civil"),
         f"got={r.domain}")

    # ══════════════════════════════════════════════════════════════
    # C. SafeCache (T16-T20)
    # ══════════════════════════════════════════════════════════════

    cache.clear()

    # T16: cache key includes domain
    k1 = SafeCache.make_key("نفس السؤال", "employment")
    k2 = SafeCache.make_key("نفس السؤال", "criminal")
    test("T16: same query, different domain → different keys",
         k1 != k2)

    # T17: cache key includes issue_type
    k3 = SafeCache.make_key("سؤال", "employment", "consultation")
    k4 = SafeCache.make_key("سؤال", "employment", "general_info")
    test("T17: same query+domain, different issue → different keys",
         k3 != k4)

    # T18: cache get returns None for missing keys
    test("T18: cache returns None for unknown key",
         cache.get("nonexistent") is None)

    # T19: cache TTL expires entries
    cache.put("temp", "value", ttl=0.1)
    time.sleep(0.2)
    test("T19: cache TTL expires entries",
         cache.get("temp") is None)

    # T20: cache stores+retrieves valid entries
    cache.put("k", "v", ttl=10.0)
    test("T20: cache stores and retrieves entries",
         cache.get("k") == "v")

    # ══════════════════════════════════════════════════════════════
    # D. ContextGuard (T21-T25)
    # ══════════════════════════════════════════════════════════════

    # T21: domain shift → clear context
    test("T21: domain shift triggers context clear",
         guard.should_clear("employment", "family", similarity=0.9))

    # T22: same domain + high similarity → keep context
    test("T22: same domain + high similarity → keep",
         not guard.should_clear("employment", "employment", similarity=0.9))

    # T23: low similarity → clear (even same domain)
    test("T23: low similarity → clear",
         guard.should_clear("employment", "employment", similarity=0.05))

    # T24: explicit followup marker detected
    test("T24: explicit followup marker detected",
         guard.is_explicit_followup("طيب وبالنسبة للتعويض؟"))

    # T25: non-followup query rejected
    test("T25: non-followup query → no followup allowed",
         not guard.should_allow_followup("ما عقوبة السرقة"))

    # ══════════════════════════════════════════════════════════════
    # E. Pipeline Execution Flow (T26-T31)
    # ══════════════════════════════════════════════════════════════

    pipeline.clear_cache()

    # T26: pipeline runs all 8 steps for a complex query
    # PHASE CONTROLLED CORE: step 4 is now 'controlled_core', step 5 is
    # 'formatter' (deterministic template by default), step 6.5 added
    # for fidelity guard.
    out = pipeline.execute(
        "فصلوني من العمل وعندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟",
        session_id="t26")
    expected_steps = ["1.context_init", "2.router", "3.normalization",
                       "4.controlled_core", "5.formatter", "6.grounding",
                       "6.5.fidelity_guard",
                       "7.output_assembler", "8.response_cleaner"]
    test("T26: pipeline completes all controlled-core steps for valid query",
         all(s in out.pipeline_steps_completed for s in expected_steps),
         f"completed={out.pipeline_steps_completed}")

    # T27: pipeline returns StructuredOutput object
    test("T27: pipeline returns StructuredOutput",
         isinstance(out, StructuredOutput) and out.request_id.startswith("req_"))

    # T28: greeting query → early exit (no analysis steps)
    out_g = pipeline.execute("مرحبا", session_id="t28")
    test("T28: greeting → early exit, no analysis steps",
         out_g.fallback_applied
         and "4.legal_thinking" not in out_g.pipeline_steps_completed)

    # T29: empty query → reject + safe fallback
    out_e = pipeline.execute("", session_id="t29")
    test("T29: empty query → reject + safe fallback",
         out_e.fallback_applied
         and len(out_e.formatted_text) > 0)

    # T30: pipeline never crashes on malformed input
    crashed = False
    try:
        pipeline.execute("؟؟؟؟؟؟", session_id="t30")
        pipeline.execute("." * 5000, session_id="t30b")
    except Exception:
        crashed = True
    test("T30: pipeline robust to malformed input",
         not crashed)

    # T31: structured output has all required fields
    test("T31: StructuredOutput has all required fields",
         hasattr(out, "issue_type") and hasattr(out, "key_facts")
         and hasattr(out, "strengths") and hasattr(out, "weaknesses")
         and hasattr(out, "opposing_arguments") and hasattr(out, "proof_needed")
         and hasattr(out, "next_step"))

    # ══════════════════════════════════════════════════════════════
    # F. Grounding Enforcement (T32-T35)
    # ══════════════════════════════════════════════════════════════

    # T32: pipeline output has no fake article numbers
    import re
    fake_art = re.compile(r"المادة\s*\(?\s*9{3,}")
    test("T32: pipeline output has no out-of-range article numbers",
         not fake_art.search(out.formatted_text))

    # T33: pipeline output has no unverified law names
    test("T33: pipeline output has no unverified law markers (no 'قانون التشريع الإلكتروني')",
         "قانون التشريع الإلكتروني" not in out.formatted_text)

    # T34: cross-query: criminal output never contains family terms
    out_crim = pipeline.execute(
        "تم اتهامي في قضية مخدرات وفيه شهود متناقضين", session_id="t34")
    forbidden = ["حضانة", "طلاق", "نفقة"]
    leaked = [f for f in forbidden if f in out_crim.formatted_text]
    test("T34: criminal output → no family domain leakage",
         not leaked, f"leaked={leaked}")

    # T35: rental output never contains employment terms
    out_rent = pipeline.execute(
        "عندي مستأجر متأخر بالإيجار وما أرسلت إنذار رسمي", session_id="t35")
    forbidden = ["تحويلات راتب", "صاحب العمل", "مكافأة نهاية الخدمة"]
    leaked = [f for f in forbidden if f in out_rent.formatted_text]
    test("T35: rental output → no employment domain leakage",
         not leaked, f"leaked={leaked}")

    # ══════════════════════════════════════════════════════════════
    # G. Output Structure Lock (T36-T38)
    # ══════════════════════════════════════════════════════════════

    # T36: structured fields populated for complex query
    out_full = pipeline.execute(
        "فصلوني من العمل وما عندي عقد، عندي تحويلات راتب، نقاط ضعفي؟",
        session_id="t36")
    test("T36: complex query → structured fields populated",
         out_full.issue_type != "unknown"
         and (len(out_full.strengths) > 0 or len(out_full.weaknesses) > 0)
         and out_full.next_step != "",
         f"issue={out_full.issue_type} s={len(out_full.strengths)} w={len(out_full.weaknesses)}")

    # T37: formatted_text contains structured sections
    test("T37: formatted_text has structured Arabic sections",
         ("نوع المسألة" in out_full.formatted_text
          or "موقفك" in out_full.formatted_text))

    # T38: pipeline output domain matches router decision
    test("T38: output domain matches router classification",
         out_full.domain == "employment")

    # ══════════════════════════════════════════════════════════════
    # H. Performance / Timeout / Early Exit (T39-T41)
    # ══════════════════════════════════════════════════════════════

    # T39: deterministic pipeline runs in well under budget
    start = time.time()
    out_p = pipeline.execute(
        "فصلوني من العمل، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟",
        session_id="t39")
    elapsed = time.time() - start
    test("T39: full pipeline completes under 3 seconds",
         elapsed < 3.0,
         f"elapsed={elapsed:.2f}s")

    # T40: cache hit on repeated query → faster
    pipeline.clear_cache()
    q40 = "فصلوني، نقاط ضعفي، عندي تحويلات راتب"
    pipeline.execute(q40, session_id="t40")  # warm cache
    start = time.time()
    out_cached = pipeline.execute(q40, session_id="t40")
    cached_elapsed = time.time() - start
    test("T40: cache hit much faster than first run",
         cached_elapsed < 0.5
         and any("cache_hit" in n for n in out_cached.notes),
         f"cached_elapsed={cached_elapsed:.3f}s notes={out_cached.notes}")

    # T41: 10 sequential runs are all fast and stable
    pipeline.clear_cache()
    times = []
    domains = []
    for i in range(10):
        s = time.time()
        out_i = pipeline.execute(
            f"فصلوني من العمل وعندي تحويلات راتب، طلب رقم {i}",
            session_id=f"loadtest_{i}")
        times.append(time.time() - s)
        domains.append(out_i.domain)
    avg_t = sum(times) / len(times)
    all_employment = all(d == "employment" for d in domains)
    test("T41: 10 sequential runs stable + correct domain",
         avg_t < 1.0 and all_employment,
         f"avg={avg_t:.3f}s domains={domains[:3]}...")

    # ══════════════════════════════════════════════════════════════
    # I. Error Containment + Stability (T42)
    # ══════════════════════════════════════════════════════════════

    # T42: SafeExecutionWrapper.safe_call returns fallback on exception
    def boom():
        raise ValueError("boom")
    val, ok = SafeExecutionWrapper.safe_call(boom, fallback="OK")
    test("T42: SafeExecutionWrapper catches exceptions, returns fallback",
         val == "OK" and ok is False)

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"CORE EXECUTION TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_core_execution_tests()
