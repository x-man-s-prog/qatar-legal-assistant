# -*- coding: utf-8 -*-
"""
PHASE INTELLIGENT DECISION — Test Suite
=========================================
48 tests covering:
 - Branch generation (deterministic, no probability)
 - Strongest / safest / high-risk path identification
 - Dependency-sensitive branches
 - Branch summary output format
 - New issue type classification (banking / commercial / inheritance / IP)
 - Router precision improvements (criminal verb forms)
 - Grounding placeholder upgrade + cross-domain compat
 - Canonical runtime path
 - LLM polishing path remains OFF by default
 - End-to-end replay of 15 real difficult queries
 - Latency bounds preserved
"""
from __future__ import annotations
import time


def run_intelligent_decision_tests() -> dict:
    from core.intelligent_decision_engine import (
        IntelligentDecisionEngine, IntelligentDecisionPlan,
        DecisionBranch, BranchType, UrgencyLevel,
        DecisionStrategySelector,
        enhance_with_branches, get_intelligent_engine,
    )
    from core.controlled_reasoning_core import (
        ControlledLegalDecisionCore, LegalDecisionRecord, RankedFact,
        produce_controlled_answer,
    )
    from core.legal_thinking_engine import IssueType, ISSUE_TYPE_AR
    from core.legal_grounding import (
        LegalGroundingEngine, ground_legal_text, CitationConfidence,
    )
    from core.execution_pipeline import ExecutionPipeline, HardRouter
    from core.canonical_runtime import (
        CanonicalRuntime, CanonicalAnswer, answer_legal_query,
    )

    engine = IntelligentDecisionEngine()
    selector = DecisionStrategySelector()
    core = ControlledLegalDecisionCore()
    router = HardRouter()
    runtime = CanonicalRuntime()

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # A. Branch Generation (T01-T08)
    # ══════════════════════════════════════════════════════════════

    # T01: builds primary branch for employment dismissal
    rec = core.build_decision_record(
        "فصلوني من العمل، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟")
    plan = engine.build_decision_branches(rec)
    test("T01: primary branch built for employment dismissal",
         plan.primary_branch is not None
         and plan.primary_branch.branch_type == BranchType.PRIMARY)

    # T02: builds fallback branch
    test("T02: fallback branch built",
         plan.fallback_branch is not None
         and plan.fallback_branch.branch_type == BranchType.FALLBACK)

    # T03: builds high-risk branch when opposing arg is decisive/important
    test("T03: high-risk branch built when warranted",
         plan.high_risk_branch is not None
         and plan.high_risk_branch.branch_type == BranchType.HIGH_RISK)

    # T04: builds dependency-sensitive branch for fixable weakness
    # (use rental-no-notice query — that's a clearly fixable weakness)
    rec_dep4 = core.build_decision_record(
        "عندي مستأجر متأخر، ما أرسلت له إنذار رسمي، أبغى أطلعه")
    plan_dep4 = engine.build_decision_branches(rec_dep4)
    test("T04: dependency-sensitive branch built (fixable weakness present)",
         len(plan_dep4.dependency_sensitive_branches) >= 1
         and plan_dep4.dependency_sensitive_branches[0].branch_type == BranchType.DEPENDENCY)

    # T05: branch priority order populated
    test("T05: branch priority order populated",
         len(plan.branch_priority_order) >= 2)

    # T06: safest move identified
    test("T06: safest_next_move identified",
         bool(plan.safest_next_move))

    # T07: strongest move identified
    test("T07: strongest_available_move identified",
         bool(plan.strongest_available_move))

    # T08: branch generation deterministic (same record → same plan structure)
    plan2 = engine.build_decision_branches(rec)
    test("T08: branch generation deterministic",
         plan.primary_branch.label == plan2.primary_branch.label
         and plan.safest_next_move == plan2.safest_next_move)

    # ══════════════════════════════════════════════════════════════
    # B. Path identification correctness (T09-T14)
    # ══════════════════════════════════════════════════════════════

    # T09: primary branch contains supporting basis from record
    rec_emp = core.build_decision_record(
        "فصلوني، عندي تحويلات راتب، ما عندي عقد")
    plan = engine.build_decision_branches(rec_emp)
    test("T09: primary branch supporting basis populated from record",
         len(plan.primary_branch.supporting_basis) >= 1
         and any("تحويلات" in b for b in plan.primary_branch.supporting_basis),
         f"basis={plan.primary_branch.supporting_basis}")

    # T10: fallback branch references blocking weakness
    test("T10: fallback branch references blocking weakness",
         bool(plan.fallback_branch.strongest_point))

    # T11: high-risk branch identifies opposing argument as main risk
    test("T11: high-risk branch main_risk = strongest opposing",
         plan.high_risk_branch is None
         or plan.high_risk_branch.main_risk == rec_emp.strongest_opposing)

    # T12: appeal-deadline branch handles unknown service date
    rec_app = core.build_decision_record(
        "صدر حكم ضدي، ما أعرف متى تم تبليغي، أبغى أطعن")
    plan_app = engine.build_decision_branches(rec_app)
    test("T12: appeal branch primary references service date",
         plan_app.primary_branch is not None
         and "التبليغ" in plan_app.primary_branch.trigger_condition)

    # T13: rental no-notice → primary branch references formal notice
    rec_rent = core.build_decision_record(
        "عندي مستأجر متأخر، ما أرسلت إنذار، أبغى أطلعه")
    plan_rent = engine.build_decision_branches(rec_rent)
    test("T13: rental primary branch references formal notice",
         plan_rent.primary_branch is not None
         and "الإنذار" in plan_rent.primary_branch.trigger_condition)

    # T14: criminal contradictory witnesses → primary branch references contradictions
    rec_crim = core.build_decision_record(
        "تم اتهامي وفيه شهود متناقضين، ما أهم نقاط الدفاع؟")
    plan_crim = engine.build_decision_branches(rec_crim)
    test("T14: criminal primary branch references witness contradictions",
         plan_crim.primary_branch is not None
         and ("تناقض" in plan_crim.primary_branch.trigger_condition
              or "مذكرة الدفاع" in plan_crim.primary_branch.trigger_condition))

    # ══════════════════════════════════════════════════════════════
    # C. No verdict / no probability language (T15-T18)
    # ══════════════════════════════════════════════════════════════

    summary = engine.build_branch_summary(plan)
    banned_terms = ["ستفوز", "ستربح", "ستخسر", "محسومة", "نسبة",
                     "احتمال", "%"]
    test("T15: branch summary has no verdict/probability language",
         not any(b in summary for b in banned_terms))

    # T16: trigger_condition uses safe conditional language only
    test("T16: trigger conditions use 'إذا' framing only",
         plan.primary_branch.trigger_condition.startswith("إذا")
         and plan.fallback_branch.trigger_condition.startswith("إذا"))

    # T17: outcome frames use bounded language
    bounded_outcomes = ["يتقوى", "يضعف", "يتعرض", "يتوقف", "يحتاج"]
    test("T17: outcome frames use bounded language",
         any(b in plan.primary_branch.safe_outcome_frame for b in bounded_outcomes))

    # T18: no fabricated procedural outcomes
    fabricated = ["سيقبل القاضي", "ستحكم المحكمة", "النتيجة المحسومة"]
    test("T18: no fabricated procedural outcomes",
         not any(f in summary for f in fabricated))

    # ══════════════════════════════════════════════════════════════
    # D. Activation gate (T19-T22)
    # ══════════════════════════════════════════════════════════════

    # T19: activates on complex personal query
    test("T19: activates on complex personal query",
         engine.should_activate(rec_emp,
             "فصلوني، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟"))

    # T20: NOT activated for empty record
    test("T20: NOT activated for empty record",
         not engine.should_activate(LegalDecisionRecord(), "فصلوني"))

    # T21: NOT activated for short query
    test("T21: NOT activated for short query",
         not engine.should_activate(rec_emp, "فصلوني"))

    # T22: simple queries → no branching applied (output stays concise)
    rec_simple = core.build_decision_record("ما هي حقوقي")
    text = "نص بسيط"
    enhanced, plan, applied = enhance_with_branches(text, rec_simple, "ما هي حقوقي")
    test("T22: simple query → no branching enhancement",
         not applied and enhanced == text)

    # ══════════════════════════════════════════════════════════════
    # E. New issue type classification (T23-T28)
    # ══════════════════════════════════════════════════════════════

    # T23: banking unauthorized deduction classified
    rec = core.build_decision_record(
        "البنك خصم من حسابي مبلغاً بدون إذني وبدون تفويض، نقاط ضعفي؟")
    test("T23: banking unauthorized deduction classified",
         rec.issue_type == "banking_unauthorized_deduction"
         and rec.domain == "banking",
         f"issue={rec.issue_type} dom={rec.domain}")

    # T24: commercial partnership dispute classified
    rec = core.build_decision_record(
        "أنا شريك في مشروع، خسارة المشروع، يحملوني كامل المسؤولية، نقاط ضعفي؟")
    test("T24: commercial partnership dispute classified",
         rec.issue_type == "commercial_partnership_dispute"
         and rec.domain == "commercial")

    # T25: inheritance distribution dispute classified
    rec = core.build_decision_record(
        "أحد الورثة استولى على التركة قبل القسمة الرسمية، نقاط ضعفي؟")
    test("T25: inheritance dispute classified",
         rec.issue_type == "inheritance_distribution_dispute")

    # T26: IP idea misappropriation classified
    rec = core.build_decision_record(
        "شخص سرق فكرتي للتطبيق ونشرها بدون اتفاقية سرية، نقاط ضعفي؟")
    test("T26: IP misappropriation classified",
         rec.issue_type == "ip_idea_misappropriation")

    # T27: new issue types produce substantive records
    queries_new = [
        "البنك خصم من حسابي بدون إذني، نقاط ضعفي؟",
        "أنا شريك ويحملوني خسارة قراراً جماعياً، نقاط ضعفي؟",
        "استولى أحد الورثة على التركة قبل القسمة، ما نقاط ضعفي؟",
        "سرق فكرتي بدون اتفاقية سرية، نقاط ضعفي؟",
    ]
    sub = sum(1 for q in queries_new
              if core.build_decision_record(q).is_substantive())
    test("T27: 4 new issue types produce substantive records",
         sub == 4, f"substantive={sub}/4")

    # T28: new issue types each have authority paths
    new_types = [
        IssueType.BANKING_UNAUTHORIZED_DEDUCTION,
        IssueType.COMMERCIAL_PARTNERSHIP_DISPUTE,
        IssueType.INHERITANCE_DISTRIBUTION_DISPUTE,
        IssueType.IP_IDEA_MISAPPROPRIATION,
    ]
    from core.legal_thinking_engine import LegalAuthorityPathResolver
    auth = LegalAuthorityPathResolver()
    paths_present = all(auth.resolve(t)[0] != "" and "غير محدد" not in auth.resolve(t)[0]
                          for t in new_types)
    test("T28: all 4 new issue types have authority paths",
         paths_present)

    # ══════════════════════════════════════════════════════════════
    # F. Router precision improvements (T29-T32)
    # ══════════════════════════════════════════════════════════════

    # T29: criminal verb form "اتهامي" routes correctly
    r = router.route("تم اتهامي في قضية مخدرات وفيه شهود متناقضين")
    test("T29: 'تم اتهامي' routes to criminal",
         r.domain == "criminal", f"got={r.domain}")

    # T30: banking router signal recognized
    r = router.route("البنك خصم من حسابي بدون تفويض، نقاط ضعفي؟")
    test("T30: banking deduction routes to banking",
         r.domain == "banking", f"got={r.domain}")

    # T31: commercial partnership routes correctly
    r = router.route("أنا شريك في مشروع وخسارة المشروع")
    test("T31: partnership routes to commercial",
         r.domain == "commercial", f"got={r.domain}")

    # T32: inheritance routes to family domain
    r = router.route("استولى أحد الورثة على التركة قبل القسمة")
    test("T32: inheritance routes to family",
         r.domain == "family", f"got={r.domain}")

    # ══════════════════════════════════════════════════════════════
    # G. Grounding placeholder upgrade (T33-T35)
    # ══════════════════════════════════════════════════════════════

    grounding = LegalGroundingEngine()

    # T33: placeholder for unverified citation is cleaner
    text = "وفقاً لقانون التشريع الإلكتروني رقم 999 لسنة 2050، يحق المطالبة"
    res = grounding.ground_text(text)
    test("T33: cleaner placeholder for unverified citation",
         "[مرجع غير موثّق]" not in res.text
         and ("القانون المختص" in res.text or "النص القانوني" in res.text))

    # T34: cross-domain placeholder is cleaner
    text = "في قضية الإيجار، وفقاً لقانون العقوبات رقم 11 لسنة 2004"
    res = grounding.ground_text(text, "rental")
    test("T34: cleaner placeholder for domain mismatch",
         "[مرجع غير مناسب للمجال]" not in res.text)

    # T35: relaxed cross-domain — debt + criminal (fraud overlap) allowed
    text = "في قضية الدين، وفقاً لقانون العقوبات رقم 11 لسنة 2004 المتعلق بالاحتيال"
    res = grounding.ground_text(text, "debt")
    test("T35: relaxed cross-domain debt + criminal fraud allowed",
         not any("domain mismatch" in c.block_reason for c in res.citations_blocked))

    # ══════════════════════════════════════════════════════════════
    # H. Canonical runtime (T36-T40)
    # ══════════════════════════════════════════════════════════════

    # T36: CanonicalRuntime returns CanonicalAnswer
    ans = runtime.answer(
        "فصلوني من العمل، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟",
        session_id="t36")
    test("T36: CanonicalRuntime returns CanonicalAnswer",
         isinstance(ans, CanonicalAnswer)
         and ans.text and ans.request_id.startswith("req_"))

    # T37: branching applied for complex query
    test("T37: branches_applied=True for complex consultation",
         ans.branches_applied)

    # T38: text contains strategic section
    test("T38: text contains strategic analysis section",
         "🧭 التحليل الاستراتيجي" in ans.text
         or "المسار الأقوى" in ans.text)

    # T39: LLM remains OFF by default
    test("T39: LLM remains OFF by default in canonical runtime",
         not ans.used_llm)

    # T40: simple query → no branching, concise output
    ans_simple = runtime.answer("مرحبا", session_id="t40")
    test("T40: greeting → no branching, concise",
         not ans_simple.branches_applied
         and "🧭" not in ans_simple.text)

    # ══════════════════════════════════════════════════════════════
    # I. End-to-end replay of 15 real queries (T41-T45)
    # ══════════════════════════════════════════════════════════════

    real_queries = [
        ("فصلوني من العمل بدون عقد، عندي تحويلات راتب، نقاط ضعفي؟", "employment"),
        ("شخص يعترف عليه دين، يختلف على المبلغ، ما عندي إلا واتساب", "civil"),
        ("صدر حكم ضدي، ما أعرف متى تبليغي، أبغى أطعن", "procedural"),
        ("عندي مستأجر متأخر، ما أرسلت إنذار، أبغى أطلعه", "rental"),
        ("منفصل عن زوجتي، خلاف حضانة، ما عندي سوابق", "family"),
        ("تم اتهامي وفيه شهود متناقضين، ما أهم نقاط الدفاع؟", "criminal"),
        ("عندي حكم وأبغى أنفذه، ما تم تبليغ الطرف الثاني", "procedural"),
        ("جاني قرار إداري وتأخرت، نقاط ضعفي؟", "administrative"),
        ("البنك خصم من حسابي بدون تفويض، نقاط ضعفي؟", "banking"),
        ("شريك في مشروع، خسارة، يحملوني المسؤولية، نقاط ضعفي؟", "commercial"),
        ("أحد الورثة استولى على التركة قبل القسمة، نقاط ضعفي؟", "family"),
        ("شخص سرق فكرة تطبيقي بدون اتفاقية سرية، نقاط ضعفي؟", "commercial"),
        ("شركة التأمين رفضت تعويضي بدون مبرر مقنع، نقاط ضعفي؟", "civil"),
        ("ادعى علي شخص بتوقيعي على عقد لم أوقعه، نقاط ضعفي؟", "civil"),
        ("الكفيل/الضامن طُولب بسداد الدين بعد إعسار المدين، نقاط ضعفي؟", "civil"),
    ]

    # T41: all 15 queries return non-empty CanonicalAnswer
    successes = 0
    for q, _ in real_queries:
        a = runtime.answer(q, session_id=f"replay_{hash(q)}")
        if a.text and len(a.text) > 50 and not a.fallback_applied:
            successes += 1
    test(f"T41: 15 real queries return useful answers ({successes}/15)",
         successes >= 12,
         f"successes={successes}/15")

    # T42: no hallucinated citations across all 15 replays
    import re
    fake_pat = re.compile(r"المادة\s*\(?\s*9{3,}|قانون\s+التشريع\s+الإلكتروني|"
                            r"قانون\s+مزيف|قانون\s+لا\s+يوجد")
    no_fakes = True
    for q, _ in real_queries:
        a = runtime.answer(q, session_id=f"fake_{hash(q)}")
        if fake_pat.search(a.text):
            no_fakes = False
            break
    test("T42: no hallucinated citations in 15 real replays", no_fakes)

    # T43: branching activates on at least 8 of 15 replay queries
    branch_count = 0
    for q, _ in real_queries:
        a = runtime.answer(q, session_id=f"branch_{hash(q)}")
        if a.branches_applied:
            branch_count += 1
    test(f"T43: branching activates on most replay queries ({branch_count}/15)",
         branch_count >= 8,
         f"branched={branch_count}/15")

    # T44: latency stays bounded across 15 replays
    times = []
    for q, _ in real_queries:
        s = time.time()
        runtime.answer(q, session_id=f"lat_{hash(q)}")
        times.append(time.time() - s)
    avg_t = sum(times) / len(times)
    test(f"T44: avg replay latency under 100ms ({avg_t*1000:.1f}ms)",
         avg_t < 0.1,
         f"avg={avg_t*1000:.1f}ms max={max(times)*1000:.1f}ms")

    # T45: domain matches expected for ≥10 of 15 queries
    correct_domain = 0
    for q, expected in real_queries:
        a = runtime.answer(q, session_id=f"dom_{hash(q)}")
        if a.domain == expected:
            correct_domain += 1
    test(f"T45: domain classification accurate ({correct_domain}/15)",
         correct_domain >= 10, f"correct={correct_domain}/15")

    # ══════════════════════════════════════════════════════════════
    # J. Strategy selector (T46-T48)
    # ══════════════════════════════════════════════════════════════

    # T46: selector identifies dependency-sensitive case
    rec_dep = core.build_decision_record(
        "عندي مستأجر متأخر، ما أرسلت إنذار، أبغى أطلعه")
    test("T46: rental no-notice flagged as dependency-sensitive",
         selector.is_dependency_sensitive(rec_dep))

    # T47: selector identifies high-risk factor
    rec_hr = core.build_decision_record(
        "فصلوني، ما عندي عقد، عندي تحويلات راتب")
    test("T47: opposing decisive arg flagged as high-risk",
         selector.has_high_risk_factor(rec_hr))

    # T48: selector returns safest move when proof is dominant priority
    safest = selector.select_safest_move(rec_dep)
    test("T48: safest_move returns proof step for fixable weakness",
         safest and ("إنذار" in safest or "كاتب العدل" in safest),
         f"safest={safest}")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"INTELLIGENT DECISION TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_intelligent_decision_tests()
