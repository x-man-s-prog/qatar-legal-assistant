# -*- coding: utf-8 -*-
"""
PHASE ADVANCED — Expert Legal Analysis Test Suite
===================================================
38 tests covering:
 - Categorical weighting (decisive/important/secondary)
 - Ranking of supporting / weakening / proof / opposing arguments
 - Decisive strength + decisive weakness identification
 - Highest-risk gap identification
 - Strongest opposing argument
 - Most important missing proof
 - Priority sequencing (immediate vs secondary)
 - Fixable vs non-fixable weaknesses
 - Output upgrade (decisive items surface FIRST)
 - No verdict / no probability language
 - Authority path preserved
 - No regression in legal thinking output
"""
from __future__ import annotations


def run_advanced_tests() -> dict:
    from core.expert_legal_analysis import (
        ExpertLegalAnalysisEngine, ExpertLegalAnalysis, RankedItem,
        ImportanceCategory, LegalWeightingEngine,
        OpposingArgumentStrengthAnalyzer, LegalPrioritySequencer,
        format_expert_analysis, enhance_with_expert_analysis,
        analyze_expert, _BANNED_TERMS,
    )
    from core.legal_thinking_engine import (
        IssueType, analyze_legal_issue,
    )

    engine = ExpertLegalAnalysisEngine()
    weighting = LegalWeightingEngine()
    opp_strength = OpposingArgumentStrengthAnalyzer()
    sequencer = LegalPrioritySequencer()

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # ══════════════════════════════════════════════════════════════
    # A. Categorical weighting (T01-T08)
    # ══════════════════════════════════════════════════════════════

    # T01: decisive employment supporting fact
    cat = weighting.categorize(
        "تحويلات الراتب تُعد قرينة قوية على وجود علاقة عمل فعلية",
        IssueType.EMPLOYMENT_DISMISSAL, "supporting")
    test("T01: salary transfers → DECISIVE supporting (employment)",
         cat == ImportanceCategory.DECISIVE,
         f"got={cat.value}")

    # T02: secondary employment supporting fact
    cat = weighting.categorize(
        "شهادة الزملاء قد تدعم إثبات الحضور والمهام",
        IssueType.EMPLOYMENT_DISMISSAL, "supporting")
    test("T02: colleague witnesses → IMPORTANT (not decisive)",
         cat == ImportanceCategory.IMPORTANT,
         f"got={cat.value}")

    # T03: decisive debt weakness — WhatsApp only
    cat = weighting.categorize(
        "الاعتماد على واتساب فقط دليل قابل للإنكار",
        IssueType.DEBT_MONEY_CLAIM, "weakening")
    test("T03: WhatsApp-only → DECISIVE weakness (debt)",
         cat == ImportanceCategory.DECISIVE,
         f"got={cat.value}")

    # T04: rental no-notice = decisive weakness
    cat = weighting.categorize(
        "عدم إرسال إنذار رسمي قد يُعيق قبول دعوى الإخلاء",
        IssueType.RENTAL_EVICTION, "weakening")
    test("T04: rental no-notice → DECISIVE weakness",
         cat == ImportanceCategory.DECISIVE,
         f"got={cat.value}")

    # T05: appeal unknown date = decisive weakness
    cat = weighting.categorize(
        "عدم معرفة تاريخ التبليغ يُصعّب تحديد المدة",
        IssueType.APPEAL_DEADLINE, "weakening")
    test("T05: appeal unknown date → DECISIVE weakness",
         cat == ImportanceCategory.DECISIVE,
         f"got={cat.value}")

    # T06: enforcement no service = decisive weakness
    cat = weighting.categorize(
        "عدم التبليغ الرسمي يُوقف إجراءات التنفيذ",
        IssueType.ENFORCEMENT_PROCEDURAL, "weakening")
    test("T06: enforcement no service → DECISIVE weakness",
         cat == ImportanceCategory.DECISIVE,
         f"got={cat.value}")

    # T07: criminal contradictory witnesses = decisive (in user's favor)
    cat = weighting.categorize(
        "تناقض أقوال الشهود يُضعف قوة دليل الشهادة",
        IssueType.CRIMINAL_ACCUSATION, "weakening")
    test("T07: criminal contradictory witnesses → DECISIVE",
         cat == ImportanceCategory.DECISIVE,
         f"got={cat.value}")

    # T08: unknown pattern → SECONDARY (default)
    cat = weighting.categorize(
        "نص لا يطابق أي نمط معروف",
        IssueType.EMPLOYMENT_DISMISSAL, "supporting")
    test("T08: unmatched pattern → SECONDARY default",
         cat == ImportanceCategory.SECONDARY,
         f"got={cat.value}")

    # ══════════════════════════════════════════════════════════════
    # B. Ranking (T09-T13)
    # ══════════════════════════════════════════════════════════════

    # T09: ranking puts decisive first
    facts = [
        "شهادة الزملاء قد تدعم إثبات الحضور والمهام",
        "تحويلات الراتب تُعد قرينة قوية على وجود علاقة عمل فعلية",
        "خطاب التعيين أو عرض العمل يُثبت العلاقة رسمياً",
    ]
    ranked = engine.rank_supporting_facts(facts, IssueType.EMPLOYMENT_DISMISSAL)
    test("T09: ranking puts DECISIVE first",
         ranked[0].category == ImportanceCategory.DECISIVE,
         f"order={[(r.category.value, r.text[:30]) for r in ranked]}")

    # T10: weakening sorted by danger (decisive on top)
    facts = [
        "غياب الشهود يُضعف إثبات الوقائع اليومية",  # SECONDARY
        "الاستقالة الطوعية تُسقط بعض حقوق التعويض",  # DECISIVE
        "غياب العقد المكتوب يُصعّب إثبات شروط العلاقة ومدتها",  # IMPORTANT
    ]
    ranked = engine.rank_weakening_facts(facts, IssueType.EMPLOYMENT_DISMISSAL)
    test("T10: weakening ranked decisive→important→secondary",
         ranked[0].category == ImportanceCategory.DECISIVE
         and ranked[-1].category == ImportanceCategory.SECONDARY,
         f"order={[r.category.value for r in ranked]}")

    # T11: proof items ranked
    proof = [
        "اجمع التحويلات البنكية للأجر وكشف الحساب الرسمي",  # DECISIVE
        "وثّق رسائل العمل عبر كاتب عدل أو خبير إلكتروني معتمد",  # IMPORTANT
    ]
    ranked = engine.rank_proof_needed(proof, IssueType.EMPLOYMENT_DISMISSAL)
    test("T11: proof needed ranked decisive first",
         ranked[0].category == ImportanceCategory.DECISIVE)

    # T12: opposing arguments ranked
    opp = [
        "قد يدفع بأن المستحقات قد صُرفت كاملة",   # SECONDARY
        "قد يحتج صاحب العمل بإنكار العلاقة العمالية كلياً",  # DECISIVE
    ]
    ranked = opp_strength.rank(opp, IssueType.EMPLOYMENT_DISMISSAL)
    test("T12: opposing arguments ranked decisive first",
         ranked[0].category == ImportanceCategory.DECISIVE)

    # T13: empty input → empty output (no crash)
    test("T13: empty input handled safely",
         engine.rank_supporting_facts([], IssueType.EMPLOYMENT_DISMISSAL) == []
         and opp_strength.rank([], IssueType.EMPLOYMENT_DISMISSAL) == [])

    # ══════════════════════════════════════════════════════════════
    # C. Decisive identification (T14-T18)
    # ══════════════════════════════════════════════════════════════

    # T14: identify decisive strength (employment + transfers)
    q = ("فصلوني من العمل، ما عندي عقد مكتوب، لكن عندي تحويلات راتب، "
         "هل أقدر أطالب بحقي؟")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T14: decisive strength identified for employment+transfers",
         len(e.decisive_strengths) >= 1
         and any("تحويلات" in d.text for d in e.decisive_strengths),
         f"decisive_strengths={[d.text[:40] for d in e.decisive_strengths]}")

    # T15: identify decisive weakness (debt + WhatsApp only)
    q = ("شخص يعترف أنه عليه دين لي، لكن ما عندي إلا محادثات واتساب، "
         "ما نقاط ضعفي؟")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T15: decisive weakness for debt+WhatsApp only",
         len(e.decisive_weaknesses) >= 1
         and any("واتساب" in w.text for w in e.decisive_weaknesses),
         f"decisive_weaknesses={[w.text[:40] for w in e.decisive_weaknesses]}")

    # T16: highest-risk gap for appeal+unknown date
    q = ("صدر حكم ضدي وأبغى أطعن، لكن ما أعرف متى تم تبليغي رسمياً")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T16: highest-risk gap = service-record verification",
         e.highest_risk_gap is not None
         and ("محضر التبليغ" in e.highest_risk_gap.text
              or "تاريخ التبليغ" in e.highest_risk_gap.text),
         f"gap={e.highest_risk_gap.text if e.highest_risk_gap else None}")

    # T17: strongest opposing argument identified for rental no-notice
    q = ("عندي مستأجر متأخر وأبغى أطلعه، لكن ما أرسلت له إنذار رسمي")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T17: strongest opposing arg for rental = missing notice",
         e.strongest_opposing_argument is not None
         and ("إنذار" in e.strongest_opposing_argument.text
              or "الإنذار" in e.strongest_opposing_argument.text),
         f"strongest_opp={e.strongest_opposing_argument.text if e.strongest_opposing_argument else None}")

    # T18: most important missing proof for criminal contradictions
    q = ("تم اتهامي وفيه شهود لكن أقوالهم متناقضة، ما أهم نقاط الدفاع")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T18: most important proof for criminal contradictions",
         e.most_important_proof_needed is not None
         and ("التناقض" in e.most_important_proof_needed.text
              or "وثّق" in e.most_important_proof_needed.text),
         f"proof={e.most_important_proof_needed.text if e.most_important_proof_needed else None}")

    # ══════════════════════════════════════════════════════════════
    # D. Priority sequencing (T19-T23)
    # ══════════════════════════════════════════════════════════════

    # T19: rental no-notice → fixable weakness identified
    q = ("عندي مستأجر متأخر وأبغى أطلعه، ما أرسلت له إنذار رسمي")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T19: rental no-notice marked fixable",
         len(e.fixable_weaknesses) >= 1
         and any("إنذار" in w.text for w in e.fixable_weaknesses),
         f"fixable={[w.text[:30] for w in e.fixable_weaknesses]}")

    # T20: appeal expired deadline → non-fixable weakness identified
    q = ("صدر حكم ضدي من 6 شهور وأبغى أطعن، تأخرت كثيراً والمهلة انتهت")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T20: appeal expired-deadline marked NON-fixable",
         any("فوات" in w.text or "انقضاء" in w.text or "التأخر" in w.text
             for w in e.non_fixable_weaknesses),
         f"non_fixable={[w.text[:40] for w in e.non_fixable_weaknesses]}")

    # T21: immediate priorities populated
    q = ("فصلوني، ما عندي عقد، لكن عندي تحويلات راتب، هل أقدر أطالب بحقي")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T21: immediate priorities populated",
         len(e.immediate_priorities) >= 1,
         f"immediate={e.immediate_priorities}")

    # T22: priority sequence reflects ranking (proof first)
    q = ("شخص أخذ مني مبلغ، ما عندي إلا محادثات واتساب، ما نقاط ضعفي")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    first_immediate = e.immediate_priorities[0] if e.immediate_priorities else ""
    test("T22: most decisive proof leads immediate priorities",
         "واتساب" in first_immediate or "توثيق" in first_immediate
         or "وثّق" in first_immediate,
         f"first_immediate={first_immediate}")

    # T23: secondary priorities exist for non-decisive items
    q = ("فصلوني، عندي تحويلات راتب، عندي رسائل واتساب، ولكن ما عندي شهود")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    test("T23: secondary priority list created (no crash)",
         isinstance(e.secondary_priorities, list))

    # ══════════════════════════════════════════════════════════════
    # E. Output upgrade (T24-T29)
    # ══════════════════════════════════════════════════════════════

    # T24: formatted output opens with summary section
    q = ("فصلوني من العمل بدون عقد، عندي تحويلات راتب، ماذا يحتج به صاحب العمل")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    formatted = format_expert_analysis(e, a)
    test("T24: output opens with priority summary",
         "🎯 الأهم في موقفك" in formatted)

    # T25: 'أقوى ما يدعم موقفك' present
    test("T25: 'أقوى ما يدعم موقفك' surfaced in summary",
         "أقوى ما يدعم موقفك" in formatted)

    # T26: 'أخطر ما يضعف موقفك' present
    test("T26: 'أخطر ما يضعف موقفك' surfaced",
         "أخطر ما يضعف موقفك" in formatted)

    # T27: 'أقوى ما قد يحتج به الطرف الآخر' present
    test("T27: 'أقوى ما قد يحتج به الطرف الآخر' surfaced",
         "أقوى ما قد يحتج به الطرف الآخر" in formatted)

    # T28: 'ابدأ أولاً' present
    test("T28: 'ابدأ أولاً' priority surfaced",
         "ابدأ أولاً" in formatted)

    # T29: detailed sections still present (ranked)
    test("T29: detailed ranked sections still present",
         "ما يدعم موقفك" in formatted
         and "ما يضعف موقفك" in formatted
         and "ما تحتاج إثباته" in formatted)

    # ══════════════════════════════════════════════════════════════
    # F. Banned language / no verdict prediction (T30-T32)
    # ══════════════════════════════════════════════════════════════

    # T30: no verdict language in output
    q = ("فصلوني من العمل، عندي تحويلات راتب، هل أكسب القضية؟")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    formatted = format_expert_analysis(e, a)
    has_banned = any(b in formatted for b in _BANNED_TERMS)
    test("T30: no banned verdict/probability language",
         not has_banned,
         f"text_len={len(formatted)}")

    # T31: no numeric probability anywhere
    import re
    pct_pattern = re.compile(r"\d+\s*%")
    test("T31: no percentage probability in output",
         not pct_pattern.search(formatted))

    # T32: no "ستفوز/ستخسر" in output
    test("T32: no win/lose verdict words",
         "ستفوز" not in formatted and "ستخسر" not in formatted
         and "محسومة" not in formatted)

    # ══════════════════════════════════════════════════════════════
    # G. Authority + integration (T33-T35)
    # ══════════════════════════════════════════════════════════════

    # T33: authority path preserved in expert output
    q = ("صدر حكم ضدي، ما أعرف متى تم تبليغي، أبغى أطعن")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    formatted = format_expert_analysis(e, a)
    test("T33: authority path preserved in expert output",
         "الجهة المختصة" in formatted
         and ("قلم المحكمة" in formatted or "إدارة التنفيذ" in formatted),
         f"text[:200]={formatted[:200]}")

    # T34: enhance_with_expert_analysis returns applied=True for complex query
    enhanced, applied, expert = enhance_with_expert_analysis(
        "", "فصلوني، ما عندي عقد، عندي تحويلات راتب، نقاط ضعفي")
    test("T34: enhance_with_expert_analysis applies on complex query",
         applied and expert is not None and "🎯" in enhanced)

    # T35: simple/short queries skipped
    enhanced, applied, expert = enhance_with_expert_analysis(
        "answer", "كم راتب الدرجة الثالثة")
    test("T35: simple query NOT enhanced",
         not applied and enhanced == "answer")

    # ══════════════════════════════════════════════════════════════
    # H. Bloat control + decisive surfacing (T36-T38)
    # ══════════════════════════════════════════════════════════════

    # T36: same point not repeated 3+ times
    q = ("فصلوني، ما عندي عقد مكتوب، عندي تحويلات راتب")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    formatted = format_expert_analysis(e, a)
    # Count any sentence-level repetition
    sentences = [s.strip() for s in formatted.split("\n") if s.strip()]
    from collections import Counter
    counts = Counter(sentences)
    over_repeated = [(s, c) for s, c in counts.items() if c >= 3 and len(s) > 20]
    test("T36: no sentence repeated 3+ times",
         not over_repeated,
         f"over_repeated={over_repeated[:2]}")

    # T37: decisive weakness appears in summary, not buried at bottom
    q = ("شخص يعترف أنه عليه دين لي، ما عندي إلا محادثات واتساب")
    a = analyze_legal_issue(q)
    e = engine.build_expert_analysis(a)
    formatted = format_expert_analysis(e, a)
    summary_section = formatted.split("**ما يدعم موقفك")[0]
    test("T37: decisive weakness appears in TOP summary",
         "أخطر ما يضعف" in summary_section
         and "واتساب" in summary_section)

    # T38: ranked list visibly differs from raw order (real ranking happened)
    facts = [
        "غياب الشهود يُضعف إثبات الوقائع اليومية",  # SECONDARY
        "الاستقالة الطوعية تُسقط بعض حقوق التعويض",  # DECISIVE
        "غياب العقد المكتوب يُصعّب إثبات شروط العلاقة ومدتها",  # IMPORTANT
    ]
    ranked = engine.rank_weakening_facts(facts, IssueType.EMPLOYMENT_DISMISSAL)
    raw_order = [f for f in facts]
    ranked_order = [r.text for r in ranked]
    test("T38: ranking actually changes order vs input",
         raw_order != ranked_order,
         f"raw[0]='{raw_order[0][:30]}' ranked[0]='{ranked_order[0][:30]}'")

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"PHASE ADVANCED TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_advanced_tests()
