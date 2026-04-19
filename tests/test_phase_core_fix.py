# -*- coding: utf-8 -*-
"""
PHASE CORE FIX — Legal Thinking Engine Test Suite
==================================================
32 tests covering:
 - Issue-type classification (9 types)
 - Fact quality analysis (supporting/weakening/proof)
 - Opposing argument generation (bounded language)
 - Authority path resolution (correct per domain)
 - Activation gate (complex vs simple)
 - Integration output structure
 - No hallucination / no domain leakage / no robotic filler
"""
from __future__ import annotations


def run_core_fix_tests() -> dict:
    from core.legal_thinking_engine import (
        LegalThinkingEngine, IssueType, ISSUE_TYPE_AR, LegalAnalysis,
        IssueClassifier, FactQualityAnalyzer, OpposingArgumentEngine,
        LegalAuthorityPathResolver,
        should_activate_legal_thinking, analyze_legal_issue,
        format_legal_analysis, enhance_with_legal_thinking,
    )

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    engine = LegalThinkingEngine()
    classifier = IssueClassifier()
    authority = LegalAuthorityPathResolver()

    # ══════════════════════════════════════════════════════════════
    # A. Issue-type classification (T01-T09)
    # ══════════════════════════════════════════════════════════════

    # T01: Employment dismissal
    q = ("فصلوني من العمل بدون سبب واضح، وما عندي عقد مكتوب، "
         "لكن عندي تحويلات راتب ورسائل واتساب تثبت عملي")
    issue, conf = classifier.classify(q)
    test("T01: employment dismissal classified correctly",
         issue == IssueType.EMPLOYMENT_DISMISSAL and conf >= 0.5,
         f"issue={issue.value} conf={conf}")

    # T02: Debt with partial acknowledgment
    q = ("شخص يعترف أنه عليه دين لي، لكن يختلف معي على قيمة المبلغ، "
         "وما عندي عقد مكتوب، فقط تحويلات ورسائل")
    issue, conf = classifier.classify(q)
    test("T02: debt claim classified correctly",
         issue == IssueType.DEBT_MONEY_CLAIM,
         f"issue={issue.value} conf={conf}")

    # T03: Appeal with unknown service date
    q = ("صدر حكم ضدي، وأبغى أطعن، لكن ما أعرف متى تم تبليغي رسمياً، "
         "هل تبدأ المهلة من تاريخ الحكم أو التبليغ؟")
    issue, conf = classifier.classify(q)
    test("T03: appeal/deadline classified correctly",
         issue == IssueType.APPEAL_DEADLINE,
         f"issue={issue.value}")

    # T04: Rental eviction without notice
    q = ("عندي مستأجر متأخر في الدفع، وأبغى أطلعه من العقار، "
         "لكن ما أرسلت له إنذار رسمي")
    issue, _ = classifier.classify(q)
    test("T04: rental eviction classified correctly",
         issue == IssueType.RENTAL_EVICTION,
         f"issue={issue.value}")

    # T05: Family custody suitability
    q = ("أنا منفصل عن زوجتي، وهي تقول أني غير مناسب لحضانة الأطفال، "
         "لكن ما عندي أي سوابق")
    issue, _ = classifier.classify(q)
    test("T05: family/custody classified correctly",
         issue == IssueType.FAMILY_CUSTODY,
         f"issue={issue.value}")

    # T06: Enforcement without notification
    q = ("عندي حكم قضائي وأبغى أنفذه، لكن الطرف الثاني ما تم تبليغه رسمياً")
    issue, _ = classifier.classify(q)
    test("T06: enforcement/procedural classified correctly",
         issue == IssueType.ENFORCEMENT_PROCEDURAL,
         f"issue={issue.value}")

    # T07: Administrative objection with delay
    q = ("جاني قرار من جهة حكومية وأبغى أعترض عليه، لكن تأخرت في اتخاذ الإجراء")
    issue, _ = classifier.classify(q)
    test("T07: administrative objection classified correctly",
         issue == IssueType.ADMINISTRATIVE_OBJECTION,
         f"issue={issue.value}")

    # T08: Criminal with weak evidence
    q = ("تم اتهامي في قضية، لكن الأدلة ضدي غير مباشرة، وفيه شهود لكن أقوالهم متناقضة")
    issue, _ = classifier.classify(q)
    test("T08: criminal accusation classified correctly",
         issue == IssueType.CRIMINAL_ACCUSATION,
         f"issue={issue.value}")

    # T09: Partnership breach → now correctly classified as
    # COMMERCIAL_PARTNERSHIP_DISPUTE (more precise than the old
    # CONTRACT_BREACH bucket).
    q = ("أنا شريك في مشروع، وصار فيه خسارة، وباقي الشركاء يحاولون يحملوني كامل المسؤولية، "
         "رغم أن القرار كان جماعي")
    issue, _ = classifier.classify(q)
    test("T09: partnership breach → COMMERCIAL_PARTNERSHIP_DISPUTE",
         issue == IssueType.COMMERCIAL_PARTNERSHIP_DISPUTE,
         f"issue={issue.value}")

    # ══════════════════════════════════════════════════════════════
    # B. Fact quality analysis (T10-T16)
    # ══════════════════════════════════════════════════════════════

    # T10: employment — salary transfers = supporting, no contract = weakening
    q = ("فصلوني بدون إنذار، ما عندي عقد مكتوب، "
         "لكن عندي تحويلات راتب ورسائل")
    a = engine.build_legal_analysis(q)
    supp_has_transfers = any("تحويلات" in s for s in a.supporting_facts)
    weak_has_nocontract = any("عقد" in w for w in a.weakening_facts)
    test("T10: employment facts correctly categorized",
         supp_has_transfers and weak_has_nocontract,
         f"supp={a.supporting_facts} weak={a.weakening_facts}")

    # T11: debt — admission = supporting, WhatsApp-only = weakening
    q = ("شخص معترف أنه عليه دين لي، لكن ما عندي إلا محادثات واتساب")
    a = engine.build_legal_analysis(q)
    supp_has_admission = any("اعتراف" in s or "الاعتراف" in s for s in a.supporting_facts)
    weak_has_whatsapp = any("واتساب" in w for w in a.weakening_facts)
    test("T11: debt facts correctly categorized",
         supp_has_admission and weak_has_whatsapp,
         f"supp={a.supporting_facts} weak={a.weakening_facts}")

    # T12: appeal — unknown service date = weakening
    q = ("صدر حكم ضدي من حوالي شهرين وأبغى أطعن، "
         "لكن ما أعرف بالضبط متى تم تبليغي رسمياً")
    a = engine.build_legal_analysis(q)
    weak_has_unknown = any("التبليغ" in w or "المدة" in w or "الميعاد" in w
                              for w in a.weakening_facts)
    test("T12: appeal unknown-service-date → weakness",
         weak_has_unknown,
         f"weak={a.weakening_facts}")

    # T13: rental no-notice → weakening + proof_needed
    q = ("عندي مستأجر ما يدفع الإيجار وأبغى أطلعه، ما أرسلت له إنذار رسمي")
    a = engine.build_legal_analysis(q)
    weak_has_notice = any("إنذار" in w for w in a.weakening_facts)
    proof_has_notice = any("إنذار" in p for p in a.proof_requirements)
    test("T13: rental no-notice → weakness + proof",
         weak_has_notice and proof_has_notice,
         f"weak={a.weakening_facts} proof={a.proof_requirements}")

    # T14: custody — no record = supporting
    q = ("أنا منفصل عن زوجتي، حضانة الأطفال، ما عندي أي سوابق")
    a = engine.build_legal_analysis(q)
    supp_has_clean = any("سوابق" in s for s in a.supporting_facts)
    test("T14: custody no-criminal-record → supporting",
         supp_has_clean,
         f"supp={a.supporting_facts}")

    # T15: criminal — contradictory witnesses = weakening
    q = ("تم اتهامي وفيه شهود لكن أقوالهم متناقضة")
    a = engine.build_legal_analysis(q)
    weak_has_contradict = any("تناقض" in w or "الشهود" in w or "الشهادة" in w
                                 for w in a.weakening_facts)
    test("T15: criminal contradictory witnesses → weakness",
         weak_has_contradict,
         f"weak={a.weakening_facts}")

    # T16: proof requirement produced for debt WhatsApp case
    q = ("أخذ مني مبلغ، ما عندي إلا محادثات واتساب")
    a = engine.build_legal_analysis(q)
    test("T16: debt WhatsApp case generates proof requirement",
         len(a.proof_requirements) >= 1,
         f"proof={a.proof_requirements}")

    # ══════════════════════════════════════════════════════════════
    # C. Opposing argument engine (T17-T20)
    # ══════════════════════════════════════════════════════════════

    # T17: employment — employer denial
    q = ("فصلوني من العمل وما عندي عقد مكتوب، ماذا ممكن يحتج به صاحب العمل؟")
    a = engine.build_legal_analysis(q)
    has_denial = any("إنكار" in o or "يحتج" in o for o in a.opposing_arguments)
    test("T17: employer denial argument generated",
         has_denial and len(a.opposing_arguments) >= 2,
         f"opposing={a.opposing_arguments}")

    # T18: debt — amount dispute argument
    q = ("شخص يعترف أنه عليه دين لي، يختلف على قيمة المبلغ")
    a = engine.build_legal_analysis(q)
    has_amount = any("قيمة" in o or "المبلغ" in o for o in a.opposing_arguments)
    test("T18: debt amount-dispute argument generated",
         has_amount,
         f"opposing={a.opposing_arguments}")

    # T19: bounded language — every opposing argument uses قد يحتج/يدفع/ينازع
    q = ("فصلوني وما عندي عقد، يحتج به صاحب العمل")
    a = engine.build_legal_analysis(q)
    allowed_prefixes = ("قد يحتج", "قد يدفع", "قد ينازع", "قد يطلب",
                         "قد تدفع", "قد تحتج", "قد يتمسّك", "قد تعتمد",
                         "قد يُحتج", "قد يطعن")
    all_bounded = all(any(o.startswith(p) for p in allowed_prefixes)
                       for o in a.opposing_arguments)
    test("T19: opposing arguments use bounded language only",
         all_bounded,
         f"args={a.opposing_arguments}")

    # T20: appeal — opposing party relies on expired deadline
    q = ("صدر حكم ضدي وتأخرت في الطعن")
    a = engine.build_legal_analysis(q)
    has_deadline_defense = any("ميعاد" in o or "المدة" in o or "الطعن" in o
                                  for o in a.opposing_arguments)
    test("T20: appeal → opponent relies on expired deadline",
         has_deadline_defense,
         f"opposing={a.opposing_arguments}")

    # ══════════════════════════════════════════════════════════════
    # D. Authority path resolver (T21-T25)
    # ══════════════════════════════════════════════════════════════

    # T21: labor dismissal → labor authority (NOT criminal)
    path_emp, step_emp = authority.resolve(IssueType.EMPLOYMENT_DISMISSAL)
    test("T21: employment → labor authority (not criminal)",
         ("عمل" in path_emp or "العمل" in path_emp)
         and "النيابة" not in path_emp and "جنائي" not in path_emp,
         f"path={path_emp}")

    # T22: rental → rental dispute body (NOT criminal)
    path_r, _ = authority.resolve(IssueType.RENTAL_EVICTION)
    test("T22: rental → rental dispute path",
         ("إيجار" in path_r or "الإيجار" in path_r)
         and "جنائي" not in path_r,
         f"path={path_r}")

    # T23: family → family court (NOT appeal/penal)
    path_f, _ = authority.resolve(IssueType.FAMILY_CUSTODY)
    test("T23: family → family court path",
         ("الأسرة" in path_f or "الأحوال الشخصية" in path_f),
         f"path={path_f}")

    # T24: appeal → court clerk for service record (NOT labor route)
    path_a, step_a = authority.resolve(IssueType.APPEAL_DEADLINE)
    test("T24: appeal → court clerk + service-date verification",
         ("قلم المحكمة" in path_a or "التبليغ" in step_a or "محضر التبليغ" in step_a),
         f"path={path_a} step={step_a}")

    # T25: criminal → defense/investigation route
    path_c, step_c = authority.resolve(IssueType.CRIMINAL_ACCUSATION)
    test("T25: criminal → NIY/defense route",
         ("النيابة" in path_c or "محامٍ" in path_c or "محامي" in step_c),
         f"path={path_c} step={step_c}")

    # ══════════════════════════════════════════════════════════════
    # E. Activation gate (T26-T28)
    # ══════════════════════════════════════════════════════════════

    # T26: complex personal query → activated
    test("T26: complex personal query activates engine",
         should_activate_legal_thinking(
             "فصلوني وما عندي عقد، هل أقدر أطالب بحقي وماذا يحتج به صاحب العمل؟"))

    # T27: short factual query → NOT activated
    test("T27: short factual query does not activate",
         not should_activate_legal_thinking("كم راتب الدرجة الثالثة"))

    # T28: medium consultation query → activated
    test("T28: medium consultation query activates",
         should_activate_legal_thinking(
             "عندي مستأجر ما يدفع الإيجار وأبغى أطلعه، ما أرسلت له إنذار رسمي"))

    # ══════════════════════════════════════════════════════════════
    # F. Output structure + banned behavior (T29-T32)
    # ══════════════════════════════════════════════════════════════

    # T29: formatted output contains all 6 sections for a complete case
    q = ("فصلوني بدون سبب واضح، ما عندي عقد مكتوب، لكن عندي تحويلات راتب، "
         "هل أقدر أطالب بحقي وماذا يحتج به صاحب العمل؟")
    a = engine.build_legal_analysis(q)
    formatted = format_legal_analysis(a)
    sections_present = all(m in formatted for m in [
        "نوع المسألة",
        "ما يقوي موقفك",
        "ما قد يُضعف موقفك",
        "ما قد يحتج به الطرف الآخر",
        "ما يحتاج إثبات",
        "الخطوة العملية التالية",
        "الجهة المختصة",
    ])
    test("T29: formatted output has all required sections",
         sections_present,
         f"text_len={len(formatted)}")

    # T30: no hallucinated article numbers in output
    import re
    fake_article_pattern = re.compile(r"المادة\s*\(?\s*\d+")
    test("T30: no hallucinated article numbers",
         not fake_article_pattern.search(formatted))

    # T31: no generic "consult a lawyer" as main answer (no standalone filler)
    generic_refusals = [
        "أنصحك باستشارة محامٍ فقط",
        "لا أستطيع الإجابة",
        "لا يمكنني الإجابة",
        "راجع محامياً",
    ]
    test("T31: no generic refusal as main answer",
         not any(g in formatted for g in generic_refusals),
         f"formatted[:200]={formatted[:200]}")

    # T32: no domain leakage — employment case must not mention family/criminal
    q = ("فصلوني من العمل وما عندي عقد، لكن عندي تحويلات راتب")
    a = engine.build_legal_analysis(q)
    formatted = format_legal_analysis(a)
    forbidden = ["حضانة", "طلاق", "مخدرات", "إخلاء"]
    leaked = [f for f in forbidden if f in formatted]
    test("T32: no domain leakage from employment to other domains",
         not leaked,
         f"leaked={leaked}")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"PHASE CORE FIX TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_core_fix_tests()
