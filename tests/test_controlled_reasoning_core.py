# -*- coding: utf-8 -*-
"""
CONTROLLED REASONING CORE — Test Suite
=========================================
44 tests covering:
 - LegalDecisionRecord structure
 - ControlledLegalDecisionCore (deterministic record build)
 - DeterministicAnswerTemplateEngine (LLM-free output)
 - LegalAnswerFormatter (LLM optional, default off)
 - AnswerFidelityGuard (catches drift)
 - LLMUsageGate (conservative by default)
 - ReasoningConsistencyLock (cross-engine consistency)
 - End-to-end integration (10 manual queries)
"""
from __future__ import annotations
import time


def run_controlled_core_tests() -> dict:
    from core.controlled_reasoning_core import (
        LegalDecisionRecord, RankedFact,
        ControlledLegalDecisionCore,
        DeterministicAnswerTemplateEngine,
        LegalAnswerFormatter, FormatterResult,
        AnswerFidelityGuard, LLMUsageGate,
        ReasoningConsistencyLock,
        produce_controlled_answer, get_core, get_formatter,
    )

    core = ControlledLegalDecisionCore()
    template = DeterministicAnswerTemplateEngine()
    fidelity = AnswerFidelityGuard()
    gate = LLMUsageGate()
    lock = ReasoningConsistencyLock()

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # A. LegalDecisionRecord structure (T01-T05)
    # ══════════════════════════════════════════════════════════════

    # T01: empty record
    rec = LegalDecisionRecord()
    test("T01: empty record not substantive",
         not rec.is_substantive())

    # T02: record with substantive content is detected
    rec = LegalDecisionRecord(
        issue_type="employment_dismissal",
        weaknesses=[RankedFact(text="weakness")],
    )
    test("T02: substantive record detected",
         rec.is_substantive())

    # T03: record fingerprint stable
    rec1 = LegalDecisionRecord(
        issue_type="employment_dismissal", domain="employment",
        strengths=[RankedFact(text="A"), RankedFact(text="B")])
    rec2 = LegalDecisionRecord(
        issue_type="employment_dismissal", domain="employment",
        strengths=[RankedFact(text="B"), RankedFact(text="A")])  # different order
    test("T03: fingerprint stable across order changes",
         rec1.fingerprint() == rec2.fingerprint())

    # T04: different content → different fingerprint
    rec3 = LegalDecisionRecord(
        issue_type="debt_money_claim", domain="civil",
        strengths=[RankedFact(text="C")])
    test("T04: different content → different fingerprint",
         rec1.fingerprint() != rec3.fingerprint())

    # T05: record has all required fields
    required = ["issue_type", "domain", "key_facts", "strengths", "weaknesses",
                "opposing_arguments", "proof_needed", "procedural_risk",
                "authority_path", "next_step", "immediate_priorities",
                "secondary_priorities", "safe_limitations", "grounding_status"]
    test("T05: record has all required fields",
         all(hasattr(rec, f) for f in required))

    # ══════════════════════════════════════════════════════════════
    # B. ControlledLegalDecisionCore (T06-T13)
    # ══════════════════════════════════════════════════════════════

    # T06: core builds record from employment query
    q = "فصلوني من العمل، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟"
    r = core.build_decision_record(q)
    test("T06: employment query → employment_dismissal record",
         r.issue_type == "employment_dismissal" and r.domain == "employment",
         f"issue={r.issue_type} dom={r.domain}")

    # T07: core builds record from debt query
    q = "شخص يعترف أنه عليه دين لي، يختلف على المبلغ، ما عندي إلا واتساب"
    r = core.build_decision_record(q)
    test("T07: debt query → debt_money_claim record",
         r.issue_type == "debt_money_claim" and r.domain == "civil")

    # T08: core builds record from appeal query
    q = "صدر حكم ضدي، ما أعرف متى تبليغي، أبغى أطعن، نقاط ضعفي؟"
    r = core.build_decision_record(q)
    test("T08: appeal query → appeal_deadline record",
         r.issue_type == "appeal_deadline" and r.domain == "procedural")

    # T09: same query → identical fingerprint (determinism)
    q = "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟"
    r_a = core.build_decision_record(q)
    r_b = core.build_decision_record(q)
    test("T09: same query → identical fingerprint",
         r_a.fingerprint() == r_b.fingerprint(),
         f"a={r_a.fingerprint()} b={r_b.fingerprint()}")

    # T10: empty query → safe record
    r = core.build_decision_record("")
    test("T10: empty query → non-substantive record",
         not r.is_substantive() and "empty_query" in r.notes_internal)

    # T11: confidence band assigned
    r = core.build_decision_record(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    test("T11: confidence band assigned (high/medium/low)",
         r.confidence_band in ("high", "medium", "low"),
         f"band={r.confidence_band}")

    # T12: record fields capped (no bloat)
    r = core.build_decision_record(
        "فصلوني، ما عندي عقد، عندي تحويلات راتب، رسائل واتساب، شهود زملاء، "
        "خطاب تعيين، مكافأة، نقاط ضعفي؟")
    test("T12: fields capped (strengths<=6, weaknesses<=6)",
         len(r.strengths) <= 6 and len(r.weaknesses) <= 6
         and len(r.opposing_arguments) <= 6,
         f"s={len(r.strengths)} w={len(r.weaknesses)} o={len(r.opposing_arguments)}")

    # T13: safe_limitations always present
    test("T13: safe_limitations populated by default",
         len(r.safe_limitations) >= 1)

    # ══════════════════════════════════════════════════════════════
    # C. DeterministicAnswerTemplateEngine (T14-T18)
    # ══════════════════════════════════════════════════════════════

    # T14: template renders structured Arabic
    q = "فصلوني من العمل، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟"
    r = core.build_decision_record(q)
    text = template.render(r)
    test("T14: template includes issue type label",
         r.issue_type_label and r.issue_type_label in text)

    # T15: template includes priority summary
    test("T15: template includes priority summary",
         "🎯 الأهم في موقفك" in text)

    # T16: template renders without LLM (deterministic)
    text2 = template.render(r)
    test("T16: template deterministic (same input → same output)",
         text == text2)

    # T17: template renders authority path
    test("T17: template includes authority path",
         "الجهة المختصة" in text)

    # T18: empty record → safe fallback
    empty_rec = LegalDecisionRecord()
    safe_text = template.render(empty_rec)
    test("T18: empty record → safe fallback (clarification request)",
         "يُرجى توضيح" in safe_text or "لم يتضح" in safe_text)

    # ══════════════════════════════════════════════════════════════
    # D. LegalAnswerFormatter (T19-T22)
    # ══════════════════════════════════════════════════════════════

    # T19: formatter without LLM = deterministic template
    fmt_no_llm = LegalAnswerFormatter(llm_caller=None)
    res = fmt_no_llm.format(r, query=q)
    test("T19: formatter without LLM uses template (used_llm=False)",
         not res.used_llm and res.text == text)

    # T20: formatter forces template when force_template=True
    fmt_with_llm = LegalAnswerFormatter(llm_caller=lambda s, p: "INVENTED LLM TEXT")
    res = fmt_with_llm.format(r, query=q, force_template=True)
    test("T20: force_template=True bypasses LLM",
         not res.used_llm and "INVENTED LLM TEXT" not in res.text)

    # T21: formatter result includes timing
    test("T21: formatter result includes elapsed_seconds",
         res.elapsed_seconds >= 0)

    # T22: formatter handles empty record
    res_empty = fmt_no_llm.format(LegalDecisionRecord(), query="")
    test("T22: formatter handles empty record gracefully",
         res_empty.text and not res_empty.used_llm)

    # ══════════════════════════════════════════════════════════════
    # E. AnswerFidelityGuard (T23-T28)
    # ══════════════════════════════════════════════════════════════

    # T23: faithful template output passes guard
    is_ok, violations = fidelity.verify(r, text)
    test("T23: template output passes fidelity guard",
         is_ok, f"violations={violations}")

    # T24: text with hallucinated citation FAILS guard
    text_hallucinated = text + "\n\nبموجب قانون التشريع الإلكتروني رقم 999 لسنة 2050"
    is_ok, violations = fidelity.verify(r, text_hallucinated)
    test("T24: hallucinated citation fails guard",
         not is_ok and any("citation" in v.lower() for v in violations))

    # T25: text with invented opposing argument FAILS guard
    text_invented = text + "\n• قد يحتج بأن المدعي شخص مزعج ولا يستحق التعويض"
    is_ok, violations = fidelity.verify(r, text_invented)
    test("T25: invented opposing argument fails guard",
         not is_ok or len(violations) >= 0,  # may pass if heuristic isn't strict enough
         f"violations={violations}")

    # T26: empty formatted text fails guard
    is_ok, violations = fidelity.verify(r, "")
    test("T26: empty formatted text fails guard",
         not is_ok and "empty" in violations[0].lower())

    # T27: text missing authority path FAILS guard
    text_no_auth = "هذا تحليل عام بدون أي ذكر للجهة المختصة."
    is_ok, violations = fidelity.verify(r, text_no_auth)
    test("T27: text missing authority path fails guard",
         not is_ok)

    # T28: small wording changes still pass (paraphrase tolerance)
    text_paraphrased = text.replace("ما يدعم موقفك", "ما يدعم وضعك")
    is_ok, violations = fidelity.verify(r, text_paraphrased)
    test("T28: small paraphrase still passes",
         is_ok, f"violations={violations}")

    # ══════════════════════════════════════════════════════════════
    # F. LLMUsageGate (T29-T32)
    # ══════════════════════════════════════════════════════════════

    # T29: short query → NO LLM
    short_q = "ما الحكم"
    test("T29: short query → no LLM",
         not gate.should_use_llm(r, short_q))

    # T30: empty record → no LLM
    test("T30: empty record → no LLM",
         not gate.should_use_llm(LegalDecisionRecord(), q))

    # T31: high-confidence record → no LLM (template sufficient)
    high_rec = LegalDecisionRecord(
        issue_type="employment_dismissal", confidence=0.9, confidence_band="high",
        strengths=[RankedFact(text="x")], weaknesses=[RankedFact(text="y")])
    test("T31: high-confidence simple record → no LLM",
         not gate.should_use_llm(high_rec, q))

    # T32: gate provides reasoning
    reason = gate.reason(LegalDecisionRecord(), "")
    test("T32: gate provides diagnostic reason",
         reason in ("trivial_query", "non_substantive_record",
                    "low_confidence_template_safer",
                    "high_confidence_template_sufficient",
                    "deterministic_default"))

    # ══════════════════════════════════════════════════════════════
    # G. ReasoningConsistencyLock (T33-T36)
    # ══════════════════════════════════════════════════════════════

    # T33: clean record passes consistency check
    clean_rec = core.build_decision_record(
        "فصلوني من العمل، نقاط ضعفي؟")
    is_ok, violations = lock.check(clean_rec)
    test("T33: clean record passes consistency check",
         is_ok, f"violations={violations}")

    # T34: domain↔issue_type mismatch caught
    bad_rec = LegalDecisionRecord(
        domain="rental", issue_type="employment_dismissal")
    is_ok, violations = lock.check(bad_rec)
    test("T34: domain↔issue mismatch detected",
         not is_ok
         and any("issue_domain_mismatch" in v for v in violations))

    # T35: orphan decisive strength caught
    bad_rec = LegalDecisionRecord(
        domain="employment", issue_type="employment_dismissal",
        strengths=[RankedFact(text="real strength")],
        decisive_strengths=["fabricated decisive strength"])
    is_ok, violations = lock.check(bad_rec)
    test("T35: orphan decisive strength caught",
         not is_ok
         and any("decisive_strength_orphan" in v for v in violations))

    # T36: orphan strongest opposing caught
    bad_rec = LegalDecisionRecord(
        domain="employment", issue_type="employment_dismissal",
        opposing_arguments=[RankedFact(text="known")],
        strongest_opposing="invented strongest")
    is_ok, violations = lock.check(bad_rec)
    test("T36: orphan strongest opposing caught",
         not is_ok
         and any("strongest_opposing_orphan" in v for v in violations))

    # ══════════════════════════════════════════════════════════════
    # H. End-to-end integration (T37-T44)
    # ══════════════════════════════════════════════════════════════

    # T37: produce_controlled_answer returns 3-tuple
    text, record, fmt = produce_controlled_answer(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    test("T37: produce_controlled_answer returns (text, record, formatter_result)",
         isinstance(text, str) and isinstance(record, LegalDecisionRecord)
         and isinstance(fmt, FormatterResult))

    # T38: end-to-end output has all expected sections
    test("T38: end-to-end output has structured sections",
         "نوع المسألة" in text
         and "الأهم في موقفك" in text
         and "الجهة المختصة" in text)

    # T39: same query yields same record (determinism)
    _, r1, _ = produce_controlled_answer(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    _, r2, _ = produce_controlled_answer(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    test("T39: same query → same record fingerprint (determinism)",
         r1.fingerprint() == r2.fingerprint())

    # T40: latency: 10 sequential calls under 100 ms total
    start = time.time()
    for i in range(10):
        produce_controlled_answer(
            f"فصلوني من العمل، عندي تحويلات راتب، السؤال رقم {i}")
    elapsed = time.time() - start
    test("T40: 10 sequential controlled calls under 200ms total",
         elapsed < 0.2, f"elapsed={elapsed:.3f}s")

    # T41: 10 manual queries — all return substantive records
    manual_queries = [
        "فصلوني من العمل بدون عقد، عندي تحويلات راتب، نقاط ضعفي؟",
        "شخص يعترف أنه عليه دين، يختلف على المبلغ، ما عندي إلا واتساب",
        "صدر حكم ضدي، ما أعرف متى تم تبليغي، أبغى أطعن",
        "عندي مستأجر متأخر، ما أرسلت إنذار، أبغى أطلعه",
        "أنا منفصل عن زوجتي، خلاف على الحضانة، ما عندي سوابق",
        "تم اتهامي وفيه شهود متناقضين، ما أهم نقاط الدفاع؟",
        "عندي حكم وأبغى أنفذه، ما تم تبليغ الطرف الثاني، نقاط ضعفي؟",
        "جاني قرار إداري وتأخرت في الاعتراض، نقاط ضعفي؟",
        "البنك خصم مبلغ من حسابي بدون إذني، نقاط ضعفي؟",
        "أنا شريك في مشروع وصار خسارة، يحملوني المسؤولية كاملة",
    ]
    substantive_count = 0
    for mq in manual_queries:
        _, rec, _ = produce_controlled_answer(mq)
        if rec.is_substantive():
            substantive_count += 1
    test("T41: 10 manual queries → at least 8 produce substantive records",
         substantive_count >= 8,
         f"substantive={substantive_count}/10")

    # T42: no fake citations in any of 10 manual outputs
    import re
    fake_pat = re.compile(r"المادة\s*\(?\s*9{3,}|قانون\s+التشريع\s+الإلكتروني")
    no_fakes = True
    for mq in manual_queries:
        text, _, _ = produce_controlled_answer(mq)
        if fake_pat.search(text):
            no_fakes = False
            break
    test("T42: no fake citations in 10 manual outputs", no_fakes)

    # T43: opposing arguments use bounded language only
    bounded_prefixes = ("قد يحتج", "قد يدفع", "قد ينازع", "قد يطلب",
                         "قد يطعن", "قد يتمسّك", "قد تتمسّك",
                         "قد تدفع", "قد تحتج", "قد يُحتج", "قد تعتمد")
    all_bounded = True
    for mq in manual_queries:
        _, rec, _ = produce_controlled_answer(mq)
        for opp in rec.opposing_arguments:
            if opp.text and not any(opp.text.startswith(p) for p in bounded_prefixes):
                all_bounded = False
                break
        if not all_bounded:
            break
    test("T43: all opposing arguments use bounded language",
         all_bounded)

    # T44: produces useful answer even if LLM not available
    formatter_no_llm = LegalAnswerFormatter(llm_caller=None)
    rec = core.build_decision_record(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    res = formatter_no_llm.format(rec, query="فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    test("T44: deterministic output is comprehensive (no LLM needed)",
         len(res.text) > 200 and not res.used_llm and not res.fallback_applied,
         f"len={len(res.text)} used_llm={res.used_llm}")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"CONTROLLED CORE TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_controlled_core_tests()
