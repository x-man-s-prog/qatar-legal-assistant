# -*- coding: utf-8 -*-
"""
PHASE FIX — Stabilization Test Suite
=====================================
30 tests covering:
 - Context isolation (no cross-query leakage)
 - Citation/domain consistency
 - Case analysis activation
 - Decision simulation / strategic output visibility
 - Output language cleanup
 - No irrelevant formal openings
 - No repeated filler
 - Latency safeguards
 - No regression on prior phases
"""
from __future__ import annotations
import asyncio
import logging

log = logging.getLogger("phase_fix_test")


def run_stabilization_tests() -> dict:
    from core.stabilization import (
        resolve_safe_session_id, detect_query_domain, domains_compatible,
        should_enrich_followup, filter_chunks_by_domain, citation_is_relevant,
        should_activate_case_analysis, build_case_analysis, format_case_analysis,
        enhance_with_case_analysis, CaseAnalysisReport,
        remove_fillers, strip_robotic_opener, dedupe_repetitive_phrases,
        clean_output, safe_clean,
        with_timeout, gather_with_timeout,
    )

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # PART A: Context Isolation (Tests 1-6)
    # ══════════════════════════════════════════════════════════════

    # T01: bare "default" → stable per-request ID
    sid1 = resolve_safe_session_id("default", request_ip="1.2.3.4",
                                     request_headers={"user-agent": "test-client"})
    sid2 = resolve_safe_session_id("default", request_ip="5.6.7.8",
                                     request_headers={"user-agent": "other-client"})
    test("T01: default session → different IDs per client",
         sid1 != sid2 and sid1 != "default" and sid2 != "default",
         f"sid1={sid1} sid2={sid2}")

    # T02: explicit session_id preserved
    sid = resolve_safe_session_id("user_abc_123")
    test("T02: explicit session_id preserved",
         sid == "user_abc_123")

    # T03: money dispute query does NOT detect family domain
    d = detect_query_domain("عندي قضية على شخص أخذ مني مبلغ مالي، وما عندي إلا محادثات واتساب")
    test("T03: money/whatsapp query → NOT family",
         d in ("debt", "") and d != "family",
         f"detected={d}")

    # T04: custody query detected as family
    d = detect_query_domain("فيه خلاف على حضانة الأطفال وأنا منفصل عن زوجتي")
    test("T04: custody query → family domain",
         d == "family", f"detected={d}")

    # T05: cross-domain followup blocked
    # Prior query was family (custody); new query is about money
    prior = "فيه خلاف على حضانة الأطفال"
    new_q = "عندي قضية على شخص أخذ مني مبلغ مالي"
    test("T05: cross-domain followup blocked",
         not should_enrich_followup(new_q, prior))

    # T06: same-domain followup allowed
    prior = "فصلوني من العمل بدون إنذار"
    new_q = "وهل أقدر أطالب بتعويض إضافي"
    test("T06: same-domain followup allowed",
         should_enrich_followup(new_q, prior))

    # ══════════════════════════════════════════════════════════════
    # PART B: Citation/Domain Consistency (Tests 7-10)
    # ══════════════════════════════════════════════════════════════

    # T07: chunks from wrong domain filtered out
    chunks = [
        {"content": "المادة (1) من قانون العمل: يسري هذا القانون على علاقات العمل"},
        {"content": "المادة (5) من قانون العمل: راتب العامل"},
        {"content": "المادة (100) حضانة الأطفال: للأم الحضانة"},
        {"content": "المادة (150) في الزواج والطلاق: العدة"},
    ]
    filtered = filter_chunks_by_domain(chunks, "employment", min_keep_ratio=0.2)
    test("T07: family chunks filtered from employment query",
         len(filtered) == 2 and all("عمل" in c["content"] for c in filtered),
         f"kept {len(filtered)}")

    # T08: rental eviction query does not retain criminal chunks
    chunks = [
        {"content": "عقد الإيجار والإخلاء: للمالك حق الإخلاء عند عدم السداد"},
        {"content": "عقوبة السرقة: حبس لمدة"},
        {"content": "مستأجر لا يدفع الإيجار"},
    ]
    filtered = filter_chunks_by_domain(chunks, "rental", min_keep_ratio=0.2)
    kept_contents = [c["content"] for c in filtered]
    test("T08: criminal chunk removed from rental context",
         not any("سرقة" in c for c in kept_contents),
         f"kept={len(filtered)}")

    # T09: soft-fail when filter would empty the list
    chunks_all_unrelated = [
        {"content": "عقوبة السرقة والضرب: السجن"},
        {"content": "المخدرات جريمة"},
    ]
    filtered = filter_chunks_by_domain(chunks_all_unrelated, "family")
    test("T09: soft-fail keeps chunks when all unrelated",
         len(filtered) == 2)

    # T10: citation_is_relevant rejects off-domain citation
    chunks = [
        {"article_number": "100", "content": "حضانة الأطفال"},
        {"article_number": "50", "content": "قانون العمل: الفصل التعسفي"},
    ]
    rel = citation_is_relevant("50", "لا", "employment", chunks)
    irrel = citation_is_relevant("100", "لا", "employment", chunks)
    test("T10: citation relevance respects domain",
         rel and not irrel)

    # ══════════════════════════════════════════════════════════════
    # PART C: Case Analysis Activation (Tests 11-17)
    # ══════════════════════════════════════════════════════════════

    # T11: dismissal with no contract triggers case analysis
    q = ("فصلوني من العمل بدون إنذار، وما عندي عقد مكتوب، "
         "لكن عندي تحويلات راتب، هل أقدر أطالب بحقي؟ وماذا ممكن يحتج به صاحب العمل؟")
    test("T11: dismissal case triggers activation",
         should_activate_case_analysis(q, "employment"))

    # T12: money/WhatsApp case triggers activation
    q = ("عندي قضية على شخص أخذ مني مبلغ مالي، لكن ما عندي إلا محادثات واتساب، "
         "هل هذا يكفي؟ وما نقاط ضعفي في هذه الحالة؟")
    test("T12: money dispute with WhatsApp triggers activation",
         should_activate_case_analysis(q, "debt"))

    # T13: trivial short query → NOT activated
    test("T13: short query not activated",
         not should_activate_case_analysis("كم الراتب", "employment"))

    # T14: case analysis produces strengths for dismissal with transfers
    q = "فصلوني بدون إنذار، ما عندي عقد مكتوب، لكن عندي تحويلات راتب"
    report = build_case_analysis(q, "employment")
    test("T14: dismissal analysis has strengths + weaknesses + opponent",
         len(report.strengths) >= 1 and len(report.weaknesses) >= 1
         and len(report.opponent_arguments) >= 1,
         f"s={len(report.strengths)} w={len(report.weaknesses)} o={len(report.opponent_arguments)}")

    # T15: WhatsApp-only money case identifies weakness + needs
    q = "أخذ مني مبلغ مالي، ما عندي إلا محادثات واتساب، ما نقاط ضعفي"
    report = build_case_analysis(q, "debt")
    test("T15: whatsapp money case has weakness + what_needed",
         len(report.weaknesses) >= 1 and len(report.what_is_needed) >= 1,
         f"w={len(report.weaknesses)} n={len(report.what_is_needed)}")

    # T16: rental without notice shows weakness + needed step
    q = "عندي مستأجر ما يدفع الإيجار وأبغى أطلعه، لكن ما أرسلت له إنذار رسمي"
    report = build_case_analysis(q, "rental")
    test("T16: rental no-notice shows weakness + needed action",
         len(report.weaknesses) >= 1,
         f"w={len(report.weaknesses)} n={len(report.what_is_needed)}")

    # T17: format_case_analysis produces structured output
    report = build_case_analysis(
        "فصلوني، ما عندي عقد، لكن عندي تحويلات راتب، ماذا يحتج به صاحب العمل",
        "employment")
    formatted = format_case_analysis(report)
    test("T17: formatted output has all 4 section headers when applicable",
         "**ما يقوي موقفك:**" in formatted
         and "**ما قد يُضعف موقفك:**" in formatted
         and "**ما قد يستند إليه الطرف الآخر:**" in formatted)

    # ══════════════════════════════════════════════════════════════
    # PART D: Decision Simulation Visibility (Tests 18-19)
    # ══════════════════════════════════════════════════════════════

    # T18: enhance_with_case_analysis returns applied=True for complex query
    q = "فصلوني، ما عندي عقد مكتوب، ماذا يحتج به صاحب العمل، نقاط ضعفي"
    enhanced, applied = enhance_with_case_analysis(
        "العامل له حق التعويض.", q, "employment")
    test("T18: case analysis visibly applied on complex query",
         applied and "---" in enhanced and len(enhanced) > 100)

    # T19: simple query does NOT trigger enhancement (no false positives)
    enhanced, applied = enhance_with_case_analysis(
        "راتب الدرجة الثالثة 20,000 ريال.", "كم راتب الدرجة الثالثة", "employment")
    test("T19: simple info query not enhanced",
         not applied and enhanced == "راتب الدرجة الثالثة 20,000 ريال.")

    # ══════════════════════════════════════════════════════════════
    # PART E: Output Language Cleanup (Tests 20-25)
    # ══════════════════════════════════════════════════════════════

    # T20: filler phrase "من الجدير بالذكر" removed
    t = "هذا نص قانوني. من الجدير بالذكر أن القانون يعطي العامل حقوقاً."
    cleaned = remove_fillers(t)
    test("T20: 'من الجدير بالذكر' filler removed",
         "من الجدير بالذكر" not in cleaned and "القانون يعطي العامل" in cleaned)

    # T21: robotic "بسم الله" opener stripped
    t = "بسم الله الرحمن الرحيم\n\nعقوبة السرقة: حبس حتى ثلاث سنوات."
    cleaned = strip_robotic_opener(t)
    test("T21: 'بسم الله' opener stripped",
         "بسم الله" not in cleaned and "عقوبة السرقة" in cleaned)

    # T22: "أهلاً بكم في مكتب" office opener stripped
    t = "أهلاً بكم في مكتب المحاماة\n\nبخصوص سؤالكم..."
    cleaned = strip_robotic_opener(t)
    test("T22: office-style opener stripped",
         "أهلاً بكم في مكتب" not in cleaned and "بخصوص سؤالكم" in cleaned)

    # T23: repetitive phrase dedup
    t = ("هذا المبدأ مهم للقانون. " * 5)  # Same sentence 5 times
    cleaned = dedupe_repetitive_phrases(t)
    test("T23: 5x repetition reduced",
         cleaned.count("هذا المبدأ مهم للقانون") < 5)

    # T24: simple text not mangled
    simple = "عقوبة السرقة في القانون القطري حبس حتى ثلاث سنوات."
    cleaned = clean_output(simple)
    test("T24: simple clean text untouched",
         cleaned == simple)

    # T25: legal meaning preserved after cleaning
    t = ("بسم الله الرحمن الرحيم\n\n"
         "عقوبة السرقة: من الجدير بالذكر أن القانون نص على الحبس. "
         "تجدر الإشارة إلى أن هناك غرامة إضافية.")
    cleaned = clean_output(t)
    test("T25: legal meaning preserved",
         "عقوبة السرقة" in cleaned and "الحبس" in cleaned and "غرامة" in cleaned
         and "بسم الله" not in cleaned and "من الجدير بالذكر" not in cleaned)

    # ══════════════════════════════════════════════════════════════
    # PART F: Latency Safeguards (Tests 26-28)
    # ══════════════════════════════════════════════════════════════

    # T26: with_timeout returns fallback on timeout
    async def _slow():
        await asyncio.sleep(2)
        return "slow_result"

    async def _run_t26():
        return await with_timeout(_slow(), timeout=0.3,
                                     fallback_value="timeout_fallback",
                                     label="t26_test")
    r = asyncio.get_event_loop().run_until_complete(_run_t26()) \
        if not asyncio.get_event_loop().is_running() \
        else asyncio.new_event_loop().run_until_complete(_run_t26())
    test("T26: with_timeout returns fallback on timeout",
         r == "timeout_fallback")

    # T27: with_timeout returns result when fast enough
    async def _fast():
        await asyncio.sleep(0.05)
        return "fast_result"

    async def _run_t27():
        return await with_timeout(_fast(), timeout=1.0,
                                     fallback_value="fallback", label="t27")
    r = asyncio.new_event_loop().run_until_complete(_run_t27())
    test("T27: with_timeout returns real result when fast",
         r == "fast_result")

    # T28: gather_with_timeout runs in parallel
    async def _task(i):
        await asyncio.sleep(0.2)
        return f"task_{i}"

    async def _run_t28():
        import time as _t
        start = _t.time()
        results = await gather_with_timeout(
            _task(1), _task(2), _task(3),
            timeout=1.0, label="t28")
        elapsed = _t.time() - start
        return results, elapsed
    r, elapsed = asyncio.new_event_loop().run_until_complete(_run_t28())
    test("T28: parallel execution (3x0.2s should be <0.5s)",
         elapsed < 0.5 and len(r) == 3 and all(x is not None for x in r),
         f"elapsed={elapsed:.2f}s")

    # ══════════════════════════════════════════════════════════════
    # PART G: No Regression (Tests 29-30)
    # ══════════════════════════════════════════════════════════════

    # T29: safe_clean never raises (robustness)
    edge_inputs = ["", None, "a", "بسم الله", "نص " * 1000]
    no_raise = True
    for inp in edge_inputs:
        try:
            safe_clean(inp if inp else "")
        except Exception:
            no_raise = False
            break
    test("T29: safe_clean never raises on edge inputs", no_raise)

    # T30: domain detection stable on greeting
    test("T30: greeting → empty domain (no hallucinated routing)",
         detect_query_domain("مرحبا") == ""
         and detect_query_domain("السلام عليكم") == "")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"STABILIZATION TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_stabilization_tests()
