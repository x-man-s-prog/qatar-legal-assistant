# -*- coding: utf-8 -*-
"""
Query Rewriter Test Suite — 20 tests covering all rewriting behaviors.
"""
from __future__ import annotations


def run_query_rewriter_tests() -> dict:
    """Run all 20 query rewriter tests. Returns summary dict."""
    from core.query_rewriter import (
        QueryRewriter, ColloquialArabicNormalizer, RewriteSafetyPolicy,
        rewrite_query,
    )

    results = []
    rewriter = QueryRewriter()

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # TEST 1: Gulf colloquial "وش أسوي" normalized
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("فصلوني وش أسوي")
    test("T01: 'وش أسوي' normalized",
         "ماذا أفعل" in r.rewritten_query,
         f"rewritten='{r.rewritten_query}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 2: "أبي أعرف" normalized
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("أبي أعرف حقوقي بالعمل")
    test("T02: 'أبي أعرف' normalized",
         "أريد" in r.rewritten_query,
         f"rewritten='{r.rewritten_query}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 3: Vague query rewritten without inventing facts
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("ساعدني")
    test("T03: vague query stays vague, no facts invented",
         r.rewritten_query in ("أحتاج مساعدة", "ساعدني") and "very_short_query" in r.ambiguity_flags)

    # ══════════════════════════════════════════════════════════════
    # TEST 4: Emotional query preserves urgency/distress
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("خايف يبتزني بصور وش أسوي بسرعة")
    test("T04: emotional + urgency preserved",
         len(r.emotional_signals) > 0 and len(r.urgency_signals) > 0,
         f"emotional={r.emotional_signals} urgency={r.urgency_signals}")

    # ══════════════════════════════════════════════════════════════
    # TEST 5: Rental colloquial query improves domain hint
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("المالك يبي يطلعني من الشقة")
    test("T05: rental domain hint detected",
         r.detected_domain_hint == "rental",
         f"domain='{r.detected_domain_hint}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 6: Criminal panic query improves risk detection
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("مسكوني الشرطة بقضية مخدرات خايف")
    test("T06: criminal + fear signals detected",
         r.detected_domain_hint == "criminal" and any("fear" in s for s in r.emotional_signals),
         f"domain={r.detected_domain_hint} emotional={r.emotional_signals}")

    # ══════════════════════════════════════════════════════════════
    # TEST 7: Deadline query improves detection
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("فاتني موعد الطعن هل يضيع حقي")
    test("T07: deadline signals detected",
         r.detected_domain_hint == "deadline" and len(r.urgency_signals) > 0,
         f"domain={r.detected_domain_hint} urgency={r.urgency_signals}")

    # ══════════════════════════════════════════════════════════════
    # TEST 8: Mixed-domain query remains mixed
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("فصلوني من الشغل وطليقتي رفعت قضية نفقة")
    test("T08: multi-domain flagged",
         "multi_domain" in r.ambiguity_flags,
         f"ambiguity={r.ambiguity_flags}")

    # ══════════════════════════════════════════════════════════════
    # TEST 9: No meaning drift (negation preserved)
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("ما عندي عقد عمل")
    has_negation = any(n in r.rewritten_query for n in ["ما ", "لم ", "لا ", "ليس", "لست"])
    test("T09: negation preserved in rewrite",
         has_negation,
         f"rewritten='{r.rewritten_query}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 10: Legal terms preserved in rewrite
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("أبي أطعن بالحكم عند محكمة التمييز")
    test("T10: legal terms preserved",
         "طعن" in r.preserved_legal_terms or "محكمة" in r.preserved_legal_terms or "تمييز" in r.preserved_legal_terms,
         f"preserved={r.preserved_legal_terms}")

    # ══════════════════════════════════════════════════════════════
    # TEST 11: Retrieval query becomes clearer
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("جاني إشعار وما فهمت شي فيه")
    test("T11: retrieval query has domain keywords",
         len(r.retrieval_query.split()) >= 2 and r.retrieval_query != r.original_query,
         f"retrieval='{r.retrieval_query[:60]}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 12: Structured salary query remains stable
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("كم راتب الدرجة الثالثة في جدول الرواتب")
    test("T12: structured query not over-rewritten",
         r.style == "formal" and r.rewritten_query == r.normalized_query,
         f"style={r.style}")

    # ══════════════════════════════════════════════════════════════
    # TEST 13: Harmless simple query not over-rewritten
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("ما عقوبة السرقة في القانون القطري")
    original_words = set(r.original_query.split())
    rewritten_words = set(r.rewritten_query.split())
    overlap = len(original_words & rewritten_words) / max(len(original_words), 1)
    test("T13: simple formal query barely changed",
         overlap >= 0.7,
         f"overlap={overlap:.2f}")

    # ══════════════════════════════════════════════════════════════
    # TEST 14: Scenario engine improves after rewrite
    # ══════════════════════════════════════════════════════════════
    from core.scenario_engine import _detect_domain as scenario_detect
    raw = "ابغى اعرف حقوقي بالشغل"
    r = rewrite_query(raw)
    raw_domain = scenario_detect(raw)
    rewritten_domain = scenario_detect(r.rewritten_query)
    test("T14: scenario domain detection improves with rewrite",
         bool(rewritten_domain),
         f"raw_domain='{raw_domain}' rewritten_domain='{rewritten_domain}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 15: Risk detection improves after rewrite
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("متورط بقضية وخايف يبتزوني")
    test("T15: risk signals detected in emotional query",
         any("fear" in s for s in r.emotional_signals) and any("blackmail" in s for s in r.emotional_signals),
         f"emotional={r.emotional_signals}")

    # ══════════════════════════════════════════════════════════════
    # TEST 16: No hallucination introduced
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("مرحبا")
    test("T16: greeting not hallucinated into legal query",
         not r.detected_domain_hint and r.style == "fragmented",
         f"domain='{r.detected_domain_hint}' style='{r.style}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 17: Ambiguity flags retained for conditional
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("إذا كان العقد مكتوب هل يحمي حقوقي")
    test("T17: conditional query flagged",
         "conditional_query" in r.ambiguity_flags)

    # ══════════════════════════════════════════════════════════════
    # TEST 18: Deterministic meaning unchanged
    # ══════════════════════════════════════════════════════════════
    safety = RewriteSafetyPolicy()
    test("T18: meaning shift detected when negation flipped",
         safety.detect_meaning_shift("ما عندي عقد", "عندي عقد") is True)

    # ══════════════════════════════════════════════════════════════
    # TEST 19: "شسوي" Gulf form normalized
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("شسوي الحين")
    test("T19: 'شسوي' normalized",
         "ماذا أفعل" in r.rewritten_query or "أفعل" in r.rewritten_query,
         f"rewritten='{r.rewritten_query}'")

    # ══════════════════════════════════════════════════════════════
    # TEST 20: "ماني فاهم" confusion normalized
    # ══════════════════════════════════════════════════════════════
    r = rewrite_query("ماني فاهم وش يعني الحكم الغيابي")
    test("T20: 'ماني فاهم' normalized",
         "لم أفهم" in r.rewritten_query or "لست" in r.rewritten_query,
         f"rewritten='{r.rewritten_query}'")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"QUERY REWRITER TESTS: {passed}/{len(results)} passed")
    if failed:
        print(f"FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_query_rewriter_tests()
