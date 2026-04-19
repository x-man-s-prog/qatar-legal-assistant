# -*- coding: utf-8 -*-
"""
PHASE CORE FIX — Real Manual Query Replay (10 queries)
========================================================
Replays the exact 10 manual queries from Part 11 against the live
LegalThinkingEngine and verifies for each:
 - correct issue classification
 - strengths / weaknesses / opposing arguments
 - proof gaps
 - authority path
 - next step
 - no domain leakage
 - no hallucinated citations
"""
from __future__ import annotations


def run_core_fix_replay() -> dict:
    from core.legal_thinking_engine import (
        LegalThinkingEngine, IssueType, format_legal_analysis,
        enhance_with_legal_thinking,
    )
    import re

    engine = LegalThinkingEngine()
    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    # The 10 real manual queries from PART 11
    queries = [
        {
            "id": "R01",
            "query": ("فصلوني من العمل بدون سبب واضح، وما عندي عقد مكتوب، "
                       "لكن عندي تحويلات راتب ورسائل واتساب تثبت عملي، "
                       "هل هذا يكفي لإثبات العلاقة؟ وماذا ممكن يحتج به صاحب العمل ضدي؟"),
            "expected_issue": IssueType.EMPLOYMENT_DISMISSAL,
            "must_have_supp_marker": ["تحويلات", "الأجر"],  # any
            "must_have_weak_marker": ["عقد", "العقد"],
            "must_have_opposing_marker": ["إنكار", "مشروع", "استقالة"],
            "must_have_next_step_marker": ["علاقات العمل", "وزارة العمل", "شكوى"],
            "forbidden_domains": ["حضانة", "طلاق", "مخدرات", "إخلاء"],
        },
        {
            "id": "R02",
            "query": ("شخص يعترف أنه عليه دين لي، لكن يختلف معي على قيمة المبلغ، "
                       "وما عندي عقد مكتوب، فقط تحويلات ورسائل، "
                       "كيف تفصل المحكمة في هذه الحالة؟ وما نقاط ضعفي؟"),
            "expected_issue": IssueType.DEBT_MONEY_CLAIM,
            "must_have_supp_marker": ["الاعتراف", "اعتراف", "التحويلات"],
            "must_have_weak_marker": ["العقد", "عقد", "القيمة"],
            "must_have_opposing_marker": ["قيمة", "المبلغ"],
            "must_have_next_step_marker": ["ابتدائية", "مدني", "المحكمة"],
            "forbidden_domains": ["حضانة", "طلاق", "مخدرات", "إخلاء"],
        },
        {
            "id": "R03",
            "query": ("صدر حكم ضدي، وأبغى أطعن، لكن ما أعرف متى تم تبليغي رسمياً، "
                       "وهل تبدأ المهلة من تاريخ الحكم أو التبليغ؟ "
                       "وماذا أفعل لو شكيت أن المهلة انتهت؟"),
            "expected_issue": IssueType.APPEAL_DEADLINE,
            "must_have_supp_marker": [],  # supporting may be empty here
            "must_have_weak_marker": ["التبليغ", "المدة", "الميعاد", "المهلة"],
            "must_have_opposing_marker": ["ميعاد", "المدة", "الطعن"],
            "must_have_next_step_marker": ["محضر التبليغ", "قلم المحكمة"],
            "forbidden_domains": ["حضانة", "مخدرات", "إيجار", "راتب"],
        },
        {
            "id": "R04",
            "query": ("عندي مستأجر متأخر في الدفع، وأبغى أطلعه من العقار، "
                       "لكن ما أرسلت له إنذار رسمي، هل أقدر أرفع دعوى مباشرة؟ "
                       "وإذا لا، ما الخطوة الصحيحة قبلها؟"),
            "expected_issue": IssueType.RENTAL_EVICTION,
            "must_have_supp_marker": [],
            "must_have_weak_marker": ["إنذار"],
            "must_have_opposing_marker": ["إنذار", "الإنذار"],
            "must_have_next_step_marker": ["إنذار", "كاتب العدل"],
            "forbidden_domains": ["حضانة", "طلاق", "مخدرات", "راتب"],
        },
        {
            "id": "R05",
            "query": ("أنا شريك في مشروع، وصار فيه خسارة، "
                       "وباقي الشركاء يحاولون يحملوني كامل المسؤولية، "
                       "رغم أن القرار كان جماعي، "
                       "كيف ممكن يتم تحديد المسؤولية؟ وماذا قد يستخدمونه ضدي؟"),
            # PHASE INTELLIGENT DECISION: now correctly classifies as
            # COMMERCIAL_PARTNERSHIP_DISPUTE (more precise than CONTRACT_BREACH).
            "expected_issue": IssueType.COMMERCIAL_PARTNERSHIP_DISPUTE,
            "must_have_supp_marker": [],
            "must_have_weak_marker": ["المحاضر", "محاضر", "الشراكة", "المسؤولية"],
            "must_have_opposing_marker": ["الشركاء", "القرار", "الحصص"],
            "must_have_next_step_marker": ["محاضر", "الشراكة", "تجاري"],
            "forbidden_domains": ["حضانة", "طلاق", "مخدرات", "إيجار", "إخلاء"],
        },
        {
            "id": "R06",
            "query": ("رفعت قضية على شخص أخذ مني مبلغ، "
                       "لكن دليلي فقط محادثات واتساب فيها اعتراف جزئي، "
                       "هل تعتبر دليل كافي؟ وما الحالات اللي ممكن تضعف هذا الدليل؟"),
            "expected_issue": IssueType.DEBT_MONEY_CLAIM,
            "must_have_supp_marker": ["الاعتراف", "اعتراف"],
            "must_have_weak_marker": ["واتساب", "المحادثات"],
            "must_have_opposing_marker": ["واتساب", "المحادثات", "حجية"],
            "must_have_next_step_marker": ["مدنية", "المحكمة"],
            "forbidden_domains": ["حضانة", "طلاق", "مخدرات"],
        },
        {
            "id": "R07",
            "query": ("أنا منفصل عن زوجتي، وهي تقول أني غير مناسب لحضانة الأطفال، "
                       "لكن ما عندي أي سوابق أو أحكام، "
                       "على أي أساس يتم الحكم في مثل هذه الحالات؟ ومتى ممكن يُرفض طلبي؟"),
            "expected_issue": IssueType.FAMILY_CUSTODY,
            "must_have_supp_marker": ["سوابق"],
            "must_have_weak_marker": ["الصلاحية", "الأهلية", "غير مناسب"],
            "must_have_opposing_marker": ["أهلية", "مناسب", "الحاضن"],
            "must_have_next_step_marker": ["الأسرة", "محكمة"],
            "forbidden_domains": ["راتب", "إيجار", "مخدرات"],
        },
        {
            "id": "R08",
            "query": ("عندي حكم قضائي وأبغى أنفذه، "
                       "لكن الطرف الثاني ما تم تبليغه رسمياً، "
                       "هل أقدر أبدأ التنفيذ مباشرة؟ "
                       "أو ممكن يتوقف التنفيذ بسبب هذا الشيء؟"),
            "expected_issue": IssueType.ENFORCEMENT_PROCEDURAL,
            "must_have_supp_marker": ["النهائي", "الحكم"],
            "must_have_weak_marker": ["التبليغ", "تبليغ"],
            "must_have_opposing_marker": ["التبليغ", "التنفيذ"],
            "must_have_next_step_marker": ["التنفيذ"],
            "forbidden_domains": ["حضانة", "طلاق", "راتب"],
        },
        {
            "id": "R09",
            "query": ("جاني قرار من جهة حكومية وأبغى أعترض عليه، "
                       "لكن تأخرت في اتخاذ الإجراء، "
                       "كيف أعرف إذا المهلة ما زالت مفتوحة أو انتهت؟ وما الخيارات إذا انتهت؟"),
            "expected_issue": IssueType.ADMINISTRATIVE_OBJECTION,
            "must_have_supp_marker": [],
            "must_have_weak_marker": ["المهلة", "المدة", "الميعاد"],
            "must_have_opposing_marker": ["الميعاد", "التظلم", "المدة"],
            "must_have_next_step_marker": ["تظلم", "إداري"],
            "forbidden_domains": ["حضانة", "طلاق", "راتب", "إيجار"],
        },
        {
            "id": "R10",
            "query": ("تم اتهامي في قضية، لكن الأدلة ضدي غير مباشرة، "
                       "وفيه شهود لكن أقوالهم متناقضة، "
                       "كيف يتم تقييم هذا النوع من الأدلة؟ وما أهم نقاط الدفاع في حالتي؟"),
            "expected_issue": IssueType.CRIMINAL_ACCUSATION,
            "must_have_supp_marker": [],
            "must_have_weak_marker": ["تناقض", "الشهود", "القرائن",
                                        "المباشرة", "الشهادات"],
            "must_have_opposing_marker": ["النيابة", "الشهادات", "القرائن"],
            "must_have_next_step_marker": ["محام", "الدفاع"],
            "forbidden_domains": ["حضانة", "طلاق", "إيجار", "راتب"],
        },
    ]

    print(f"\n{'='*60}")
    print(f"PHASE CORE FIX — REPLAY {len(queries)} REAL USER QUERIES")
    print(f"{'='*60}")

    fake_article_re = re.compile(r"المادة\s*\(?\s*\d+")

    for q in queries:
        qid = q["id"]
        print(f"\n── {qid} ──")
        print(f"   Q: {q['query'][:80]}...")

        analysis = engine.build_legal_analysis(q["query"])

        # Check 1: issue classification
        test(f"{qid}a: issue classification",
             analysis.issue_type == q["expected_issue"],
             f"got={analysis.issue_type.value} expected={q['expected_issue'].value}")

        # Check 2: supporting facts include an expected marker (if specified)
        if q["must_have_supp_marker"]:
            all_supp = " ".join(analysis.supporting_facts)
            has_any = any(m in all_supp for m in q["must_have_supp_marker"])
            test(f"{qid}b: supporting facts include expected marker",
                 has_any,
                 f"supp={analysis.supporting_facts} expected_any={q['must_have_supp_marker']}")

        # Check 3: weakening facts include an expected marker
        if q["must_have_weak_marker"]:
            all_weak = " ".join(analysis.weakening_facts)
            has_any = any(m in all_weak for m in q["must_have_weak_marker"])
            test(f"{qid}c: weakening facts include expected marker",
                 has_any,
                 f"weak={analysis.weakening_facts} expected_any={q['must_have_weak_marker']}")

        # Check 4: opposing arguments are bounded + present
        test(f"{qid}d: opposing arguments present + bounded",
             len(analysis.opposing_arguments) >= 2
             and all(o.startswith(("قد يحتج", "قد يدفع", "قد ينازع",
                                       "قد يطلب", "قد يطعن", "قد يتمسّك",
                                       "قد تتمسّك", "قد تدفع", "قد تحتج",
                                       "قد يُحتج", "قد تعتمد"))
                     for o in analysis.opposing_arguments),
             f"opposing={analysis.opposing_arguments}")

        # Check 5: opposing arguments contain expected marker
        if q["must_have_opposing_marker"]:
            all_opp = " ".join(analysis.opposing_arguments)
            has_any = any(m in all_opp for m in q["must_have_opposing_marker"])
            test(f"{qid}e: opposing arguments include expected theme",
                 has_any,
                 f"opp={analysis.opposing_arguments}")

        # Check 6: authority path is correct
        test(f"{qid}f: authority path present",
             bool(analysis.authority_path),
             f"authority={analysis.authority_path[:80]}")

        # Check 7: next step present + matches expected marker
        if q["must_have_next_step_marker"]:
            has_any = any(m in analysis.next_step
                           for m in q["must_have_next_step_marker"])
            test(f"{qid}g: next step includes expected channel",
                 has_any,
                 f"next_step={analysis.next_step}")

        # Check 8: formatted output has no domain leakage
        formatted = format_legal_analysis(analysis)
        leaked = [f for f in q["forbidden_domains"] if f in formatted]
        test(f"{qid}h: no domain leakage in formatted output",
             not leaked,
             f"leaked={leaked}")

        # Check 9: no hallucinated article numbers
        test(f"{qid}i: no hallucinated article numbers",
             not fake_article_re.search(formatted))

    # Summary
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*60}")
    print(f"PHASE CORE FIX REPLAY: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*60}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_core_fix_replay()
