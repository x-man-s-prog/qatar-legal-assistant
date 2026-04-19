# -*- coding: utf-8 -*-
"""
Live Path Verification
======================
Verifies the EXACT queries specified in the mandate.
Tests the full classify → resolve_lookup → build pipeline.

Since we can't hit the DB in tests, we test the classify + build pipeline
and verify that the routing is correct for each query.
"""
import re
from core.structured_lookup import classify_query, QueryIntent
from core.answer_builder import build_structured_answer, _FORBIDDEN

# ══════════════════════════════════════════════════════════════
# Test Queries — from the mandate
# ══════════════════════════════════════════════════════════════

VERIFICATION_CASES = [
    {
        "query": "كم راتب موظف درجه سابعه",
        "expected_intent": QueryIntent.SALARY_QUERY,
        "expects_llm": False,
        "description": "Grade-specific salary query",
    },
    {
        "query": "الدرجة السابعة فقط",
        "expected_intent": QueryIntent.SALARY_QUERY,
        "expects_llm": False,
        "description": "Follow-up: grade-only narrowing",
    },
    {
        "query": "جدول الرواتب",
        "expected_intent": QueryIntent.SALARY_QUERY,
        "expects_llm": False,
        "description": "Full salary table request",
    },
    {
        "query": "جدول المخدرات",
        "expected_intent": QueryIntent.DRUG_TABLE,
        "expects_llm": False,
        "description": "Drug table request",
    },
    {
        "query": "اكتب أسماء المواد المخدرة فقط",
        "expected_intent": QueryIntent.DRUG_TABLE,
        "expects_llm": False,
        "description": "Drug names only request",
    },
    {
        "query": "اذكر أسماء المواد المخدرة فوق بعض",
        "expected_intent": QueryIntent.DRUG_TABLE,
        "expects_llm": False,
        "description": "Drug names stacked request",
    },
    {
        "query": "اكتب لي اسماء المواد الكيميائية المحضوره في قطر",
        "expected_intent": QueryIntent.ENUMERATION_LIST,
        "expects_llm": False,
        "description": "Chemical substances list",
    },
    {
        "query": "اريد المركبات والمكونات الخاصة بالمتفجرات",
        "expected_intent": QueryIntent.ENUMERATION_LIST,
        "expects_llm": False,
        "description": "Explosives components list",
    },
]


def verify_all():
    """Run all verification cases and print results."""
    print("=" * 70)
    print("LIVE PATH VERIFICATION")
    print("=" * 70)

    all_pass = True
    for i, case in enumerate(VERIFICATION_CASES, 1):
        q = case["query"]
        expected = case["expected_intent"]
        desc = case["description"]

        # 1. Classify
        actual_intent = classify_query(q)
        intent_ok = actual_intent == expected

        # 2. Test LLM bypass
        is_structured = actual_intent not in (QueryIntent.GENERAL_LEGAL, QueryIntent.ARTICLE_LOOKUP)
        llm_blocked = is_structured == (not case["expects_llm"])

        # 3. Test builder output (with sample data)
        builder_output = None
        if is_structured:
            if actual_intent == QueryIntent.SALARY_QUERY:
                builder_output = build_structured_answer(
                    intent="salary_query",
                    raw_content="الدرجة الأولى: 50,000\nالدرجة السابعة: 25,000",
                    law_name="قانون الموارد البشرية",
                    target_grade="السابعة",
                    grade_row="الدرجة السابعة: 25,000 — 35,000",
                )
            elif actual_intent == QueryIntent.DRUG_TABLE:
                builder_output = build_structured_answer(
                    intent="drug_table",
                    raw_content="",
                    chunks=[{"content": "1- مورفين\n2- كوكايين\n3- هيروين\n4- AMPHETAMINE", "law_name": "قانون المخدرات"}],
                )
            elif actual_intent == QueryIntent.ENUMERATION_LIST:
                builder_output = build_structured_answer(
                    intent="enumeration_list",
                    raw_content="",
                    chunks=[{"content": "1- أسيتون\n2- حمض الكبريتيك\n3- نترات الأمونيوم", "law_name": "قانون المواد الكيميائية"}],
                )
            elif actual_intent == QueryIntent.TABLE_LOOKUP:
                builder_output = build_structured_answer(
                    intent="table_lookup",
                    raw_content="",
                    chunks=[{"content": "1- بند أول\n2- بند ثاني\n3- بند ثالث", "law_name": ""}],
                )

        # 4. Check output contract
        output_clean = True
        if builder_output:
            for marker in _FORBIDDEN:
                if marker in builder_output:
                    output_clean = False

        passed = intent_ok and llm_blocked and output_clean

        # Print
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"\n{i}. {status} — {desc}")
        print(f"   Query:    {q}")
        print(f"   Intent:   {actual_intent.value} {'✓' if intent_ok else '✗ expected ' + expected.value}")
        print(f"   LLM:      {'BLOCKED' if not case['expects_llm'] else 'CALLED'} {'✓' if llm_blocked else '✗'}")
        if builder_output:
            preview = builder_output[:100].replace('\n', ' | ')
            print(f"   Output:   {preview}{'...' if len(builder_output) > 100 else ''}")
            print(f"   Clean:    {'✓' if output_clean else '✗ FORBIDDEN MARKERS FOUND'}")
        print(f"   Asserts:  {'ALL PASSED' if passed else 'FAILED'}")

        if not passed:
            all_pass = False

    print("\n" + "=" * 70)
    if all_pass:
        print("RESULT: ALL 8 VERIFICATION CASES PASSED ✅")
    else:
        print("RESULT: SOME CASES FAILED ❌")
    print("=" * 70)

    return all_pass


if __name__ == "__main__":
    ok = verify_all()
    exit(0 if ok else 1)
