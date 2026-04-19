# -*- coding: utf-8 -*-
"""
Semantic Memory Test Suite — 20 tests covering all memory behaviors.
"""
from __future__ import annotations
import logging

log = logging.getLogger("memory_test")


def run_semantic_memory_tests() -> dict:
    """Run all 20 semantic memory tests. Returns summary dict."""
    from core.semantic_memory import (
        SemanticMemoryEngine, SemanticMemoryPolicy, MemorySafetyGuard,
        SemanticMemoryState, FactRecord, FactType,
        _detect_domain, _extract_entities, _extract_facts_from_query,
        _extract_timeline, _detect_user_goal, _memory_store,
    )

    results = []
    engine = SemanticMemoryEngine()
    policy = SemanticMemoryPolicy()
    safety = MemorySafetyGuard()

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # Clear store before tests
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 1: Follow-up uses correct prior context
    # ══════════════════════════════════════════════════════════════
    sid = "test_01"
    state = engine.build_memory_state(sid, "فصلوني من الشغل بدون سبب", "employment")
    engine.update_memory_state(state, "فصلوني من الشغل بدون سبب")
    enriched = engine.enrich_followup_query(sid, "طيب بالنسبة للبدلات؟")
    test("T01: follow-up uses prior context",
         "عمل" in enriched or "employment" in enriched.lower(),
         f"enriched='{enriched[:60]}'")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 2: New clear fact overrides older vague fact
    # ══════════════════════════════════════════════════════════════
    sid = "test_02"
    state = engine.build_memory_state(sid, "استقلت من الشغل", "employment")
    engine.update_memory_state(state, "استقلت من الشغل")
    # Now user says they were fired (contradicts resignation)
    state = engine.build_memory_state(sid, "يعني فصلوني مو استقالة", "employment")
    engine.update_memory_state(state, "يعني فصلوني مو استقالة")
    usable = state.usable_facts()
    has_termination = any("terminated" in f.text for f in usable)
    resignation_superseded = all(
        f.superseded_by != "" for f in state.established_facts if "resigned" in f.text)
    test("T02: new fact overrides older conflicting fact",
         has_termination and resignation_superseded,
         f"termination={has_termination} resignation_superseded={resignation_superseded}")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 3: Stale context not reused across topic shift
    # ══════════════════════════════════════════════════════════════
    sid = "test_03"
    state = engine.build_memory_state(sid, "فصلوني من الشغل", "employment")
    engine.update_memory_state(state, "فصلوني من الشغل")
    # Topic shift to family
    engine.clear_irrelevant_context(sid, "family")
    state = engine.build_memory_state(sid, "أبي طلاق", "family")
    engine.update_memory_state(state, "أبي طلاق")
    ctx = engine.get_relevant_context(sid, "كم النفقة", "family")
    employment_facts = [f for f in ctx["facts"] if "terminated" in f["text"]]
    test("T03: stale employment context not reused in family",
         len(employment_facts) == 0)
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 4: Unresolved fact not treated as confirmed
    # ══════════════════════════════════════════════════════════════
    sid = "test_04"
    unresolved = FactRecord(
        fact_id="f_unresolved", text="employment duration unknown",
        fact_type=FactType.UNRESOLVED, domain="employment",
        source_turn=1, confidence=0.1, can_be_used_for_answer=False)
    test("T04: unresolved fact not usable",
         not unresolved.is_usable() and not policy.is_fact_reusable(unresolved, 2, "employment"))

    # ══════════════════════════════════════════════════════════════
    # TEST 5: Inferred fact not used as hard fact
    # ══════════════════════════════════════════════════════════════
    sid = "test_05"
    inferred_low = FactRecord(
        fact_id="f_low", text="probably unfair dismissal",
        fact_type=FactType.SYSTEM_INFERRED_LOW, domain="employment",
        source_turn=1, confidence=0.3, can_be_used_for_answer=True)
    test("T05: low-confidence inferred fact not reusable",
         not policy.is_fact_reusable(inferred_low, 2, "employment"))

    # ══════════════════════════════════════════════════════════════
    # TEST 6: Mixed-domain conversation stays separated
    # ══════════════════════════════════════════════════════════════
    sid = "test_06"
    state = engine.build_memory_state(sid, "فصلوني من الشغل", "employment")
    engine.update_memory_state(state, "فصلوني من الشغل")
    state = engine.build_memory_state(sid, "وعندي مشكلة إيجار", "rental")
    engine.update_memory_state(state, "وعندي مشكلة إيجار")
    # Get rental context — should not include employment facts
    ctx = engine.get_relevant_context(sid, "المالك رفع الإيجار", "rental")
    emp_facts = [f for f in ctx["facts"] if f.get("text", "").find("terminated") >= 0]
    test("T06: mixed-domain facts separated",
         len(emp_facts) == 0,
         f"rental_ctx_facts={len(ctx['facts'])} emp_facts={len(emp_facts)}")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 7: High-risk context preserved only when relevant
    # ══════════════════════════════════════════════════════════════
    sid = "test_07"
    state = engine.build_memory_state(sid, "مسكوني الشرطة بقضية مخدرات", "criminal")
    engine.update_memory_state(state, "مسكوني الشرطة بقضية مخدرات")
    test("T07: high-risk facts preserved in same domain",
         len(state.active_risk_markers) > 0 and "مخدرات" in state.active_risk_markers)
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 8: Salary follow-up works correctly
    # ══════════════════════════════════════════════════════════════
    sid = "test_08"
    state = engine.build_memory_state(sid, "كم راتب الدرجة الثالثة", "employment")
    engine.update_memory_state(state, "كم راتب الدرجة الثالثة")
    enriched = engine.enrich_followup_query(sid, "وبالنسبة للعلاوات؟")
    test("T08: salary follow-up gets employment context",
         "عمل" in enriched,
         f"enriched='{enriched[:50]}'")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 9: Family follow-up works correctly
    # ══════════════════════════════════════════════════════════════
    sid = "test_09"
    state = engine.build_memory_state(sid, "طليقتي تمنعني أشوف عيالي", "family")
    engine.update_memory_state(state, "طليقتي تمنعني أشوف عيالي")
    enriched = engine.enrich_followup_query(sid, "هل أقدر أرفع قضية؟")
    has_family_ctx = "أحوال شخصية" in enriched or "طليقتي" in enriched
    test("T09: family follow-up gets family context",
         has_family_ctx,
         f"enriched='{enriched[:60]}'")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 10: Criminal follow-up works correctly
    # ══════════════════════════════════════════════════════════════
    sid = "test_10"
    state = engine.build_memory_state(sid, "حكموا علي غيابياً", "criminal")
    engine.update_memory_state(state, "حكموا علي غيابياً")
    enriched = engine.enrich_followup_query(sid, "هل أقدر أطعن؟")
    has_criminal_ctx = "جنائي" in enriched or "judgment" in str(
        engine.get_relevant_context(sid, "هل أقدر أطعن", "criminal")["facts"])
    test("T10: criminal follow-up preserves judgment context",
         has_criminal_ctx,
         f"enriched='{enriched[:60]}'")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 11: Timeline markers carried safely
    # ══════════════════════════════════════════════════════════════
    sid = "test_11"
    state = engine.build_memory_state(sid, "شغلت 5 سنوات وفصلوني", "employment")
    engine.update_memory_state(state, "شغلت 5 سنوات وفصلوني")
    test("T11: timeline markers extracted",
         len(state.active_timeline_markers) > 0,
         f"markers={state.active_timeline_markers}")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 12: Memory safety guard catches leakage
    # ══════════════════════════════════════════════════════════════
    sid = "test_12"
    state = engine.build_memory_state(sid, "مسكوني بقضية مخدرات", "criminal")
    engine.update_memory_state(state, "مسكوني بقضية مخدرات")
    leak = safety.detect_context_leak(state, "employment")
    test("T12: safety guard detects cross-domain risk leak",
         leak is True)
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 13: No hallucination introduced
    # ══════════════════════════════════════════════════════════════
    sid = "test_13"
    state = engine.build_memory_state(sid, "ساعدني", "")
    engine.update_memory_state(state, "ساعدني")
    ctx = engine.get_relevant_context(sid, "ساعدني")
    test("T13: vague query produces no fabricated facts",
         len(ctx["facts"]) == 0,
         f"facts={ctx['facts']}")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 14: Deterministic answers remain unchanged
    # ══════════════════════════════════════════════════════════════
    sid = "test_14"
    # Memory enrichment only enriches short follow-ups
    long_q = "شغلت 3 سنين وما عطوني مكافأة نهاية خدمة كم لي هل يحق لي أطالب بمكافأة"
    enriched = engine.enrich_followup_query(sid, long_q)
    test("T14: long deterministic queries not modified",
         enriched == long_q)

    # ══════════════════════════════════════════════════════════════
    # TEST 15: Context clearing works
    # ══════════════════════════════════════════════════════════════
    sid = "test_15"
    state = engine.build_memory_state(sid, "فصلوني", "employment")
    engine.update_memory_state(state, "فصلوني")
    engine.clear_session(sid)
    ctx = engine.get_relevant_context(sid, "وش أسوي")
    test("T15: session clear removes all context",
         not ctx["has_context"] and ctx["turn_count"] == 0)
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 16: Semantic retrieval improves precision
    # ══════════════════════════════════════════════════════════════
    sid = "test_16"
    state = engine.build_memory_state(sid, "فصلوني من الشغل والمدير رفض يعطيني شهادة خبرة", "employment")
    engine.update_memory_state(state, "فصلوني من الشغل والمدير رفض يعطيني شهادة خبرة")
    ctx = engine.get_relevant_context(sid, "وبالنسبة للتعويض؟", "employment")
    test("T16: semantic retrieval returns confirmed facts",
         ctx["has_context"] and any("terminated" in f["text"] for f in ctx["facts"]))
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 17: Entity extraction works
    # ══════════════════════════════════════════════════════════════
    entities = _extract_entities("كفيلي ما يبي يعطيني إذن خروج")
    test("T17: entity extraction identifies employer",
         "employer" in entities,
         f"entities={entities}")

    # ══════════════════════════════════════════════════════════════
    # TEST 18: Conditional facts marked as ambiguous
    # ══════════════════════════════════════════════════════════════
    sid = "test_18"
    state = engine.build_memory_state(sid, "إذا عندي عقد هل يحمي حقوقي", "employment")
    engine.update_memory_state(state, "إذا عندي عقد هل يحمي حقوقي")
    conditional = [f for f in state.established_facts if f.fact_type == FactType.USER_STATED_AMBIGUOUS]
    test("T18: conditional facts marked as ambiguous",
         len(conditional) > 0,
         f"conditional_count={len(conditional)}")
    _memory_store.clear()

    # ══════════════════════════════════════════════════════════════
    # TEST 19: Fact conflict detection works
    # ══════════════════════════════════════════════════════════════
    fact_a = FactRecord(fact_id="a", text="user has written contract",
                         fact_type=FactType.USER_STATED_CONFIRMED, confidence=0.9)
    fact_b = FactRecord(fact_id="b", text="user has no written contract",
                         fact_type=FactType.USER_STATED_CONFIRMED, confidence=0.9)
    conflict = safety.detect_fact_conflict([fact_a], fact_b)
    test("T19: fact conflict detection works",
         conflict is not None and conflict.fact_id == "a")

    # ══════════════════════════════════════════════════════════════
    # TEST 20: Domain detection accurate
    # ══════════════════════════════════════════════════════════════
    test("T20: domain detection works",
         _detect_domain("فصلوني من الشغل") == "employment"
         and _detect_domain("حكموا علي غيابياً") == "criminal"
         and _detect_domain("أبي طلاق") == "family"
         and _detect_domain("المالك رفع الإيجار") == "rental")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"SEMANTIC MEMORY TESTS: {passed}/{len(results)} passed")
    if failed:
        print(f"FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


if __name__ == "__main__":
    run_semantic_memory_tests()
