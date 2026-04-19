# -*- coding: utf-8 -*-
"""
MOCK-DATA RUNTIME TRACE
========================
Simulates real DB content to trace the EXACT builder output.
This catches the case where the builder gets real data but still
returns full table dumps instead of grade-specific rows.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.structured_lookup import classify_query, _extract_grade, _extract_grade_row
from core.answer_builder import (
    build_structured_answer, build_salary_answer,
    _clean_salary_table, _clean_salary_row,
)
from core.refusal_engine import is_structured_intent, generate_refusal

# ═══════════════════════════════════════════════════════
# Realistic salary table content (as it appears in DB)
# ═══════════════════════════════════════════════════════
REAL_SALARY_TABLE = """جدول الدرجات والرواتب الملحق بقانون الموارد البشرية المدنية
📋 من قانون إدارة الموارد البشرية المدنية رقم (15) لسنة 2016:
الدرجة الممتازة: المربوط 45,000 — نهاية المربوط 55,000
الدرجة الخاصة: المربوط 35,000 — نهاية المربوط 45,000
الدرجة الأولى: المربوط 25,000 — نهاية المربوط 35,000
الدرجة الثانية: المربوط 18,000 — نهاية المربوط 25,000
الدرجة الثالثة: المربوط 14,000 — نهاية المربوط 18,000
الدرجة الرابعة: المربوط 10,000 — نهاية المربوط 14,000
الدرجة الخامسة: المربوط 7,500 — نهاية المربوط 10,000
الدرجة السادسة: المربوط 5,500 — نهاية المربوط 7,500
الدرجة السابعة: المربوط 4,000 — نهاية المربوط 5,500
---
(المصدر: almeezan.qa)"""

REAL_LAW_NAME = "قانون إدارة الموارد البشرية المدنية رقم (15) لسنة 2016"

def trace(label, value):
    print(f"  [{label}] {value}")

def run_query(query: str):
    """Simulate the full path for a query with real-like data."""
    print("\n" + "=" * 80)
    print(f"  QUERY: {query}")
    print("=" * 80)

    # Step 1: Classification
    intent = classify_query(query)
    trace("CLASSIFY", f"intent={intent.value}")

    is_struct = is_structured_intent(intent.value)
    trace("STRUCTURED", f"{is_struct}")

    if not is_struct:
        trace("PATH", "→ RAG/LLM (not structured)")
        return {"ok": True, "path": "not_structured"}

    # Step 2: Grade extraction
    grade = _extract_grade(query)
    trace("GRADE", f"extracted='{grade}'" if grade else "extracted=None (full table)")

    # Step 3: Simulate resolve_lookup behavior
    if grade:
        grade_row = _extract_grade_row(REAL_SALARY_TABLE, grade)
        trace("GRADE_ROW", f"found='{grade_row}'" if grade_row else "NOT FOUND")

        if grade_row:
            # Simulate what resolve_lookup returns for a grade hit
            raw_data = {
                "raw_content": REAL_SALARY_TABLE,
                "law_name": REAL_LAW_NAME,
                "target_grade": grade,
                "grade_row": grade_row,
            }
            trace("RESOLVE", "HIT — grade-specific data found")
        else:
            # Grade not found in table → refusal
            refusal = generate_refusal(intent.value, query)
            trace("RESOLVE", f"REFUSAL — grade '{grade}' not in table")
            trace("REFUSAL_TEXT", refusal)
            trace("LLM_CALLED", "NO")
            return {"ok": True, "path": "refusal", "result": refusal}
    else:
        # No specific grade → full table
        raw_data = {
            "raw_content": REAL_SALARY_TABLE,
            "law_name": REAL_LAW_NAME,
            "target_grade": "",
            "grade_row": "",
        }
        trace("RESOLVE", "HIT — full table data")

    # Step 4: Build answer
    built = build_structured_answer(
        intent=intent.value,
        raw_content=raw_data["raw_content"],
        law_name=raw_data["law_name"],
        target_grade=raw_data.get("target_grade", ""),
        grade_row=raw_data.get("grade_row", ""),
        chunks=None,
    )
    trace("BUILDER_CALLED", "YES")
    trace("BUILDER_OUTPUT_LEN", f"{len(built)} chars")

    print(f"\n  ┌─ BUILDER OUTPUT ─────────────────────────────┐")
    for line in built.split('\n'):
        print(f"  │ {line}")
    print(f"  └──────────────────────────────────────────────┘")

    # Step 5: Validate
    issues = []

    # Check forbidden markers
    for marker in ["📋", "⚖️", "🔍", "✅", "📊"]:
        if marker in built:
            issues.append(f"FORBIDDEN MARKER: '{marker}' still in output")

    # Check for raw OCR lines
    for i, line in enumerate(built.split('\n')):
        if len(line.strip()) > 200:
            issues.append(f"RAW OCR LINE {i}: {len(line.strip())} chars")

    # Check grade-specific queries return ONLY that grade
    if grade and "فقط" in query:
        lines = [l for l in built.split('\n') if l.strip() and not l.strip().startswith("(المصدر")]
        if len(lines) > 3:
            issues.append(f"'فقط' constraint VIOLATED: {len(lines)} data lines (expected ≤3)")
        # Check that ONLY the requested grade appears
        other_grades = ["الممتازة", "الخاصة", "الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة", "السابعة"]
        if grade in other_grades:
            other_grades.remove(grade)
        for og in other_grades:
            if og in built and og not in raw_data.get("law_name", ""):
                issues.append(f"OTHER GRADE LEAKED: '{og}' in grade-specific answer for '{grade}'")

    # Check grade-specific queries don't dump full table
    if grade:
        total_grades_in_output = sum(1 for g in ["الممتازة", "الخاصة", "الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة", "السابعة"]
                                     if g in built)
        if total_grades_in_output > 2:
            issues.append(f"FULL TABLE DUMPED: {total_grades_in_output} grades in answer (expected 1)")

    trace("LLM_CALLED", "NO")

    if issues:
        print(f"\n  ❌ VALIDATION FAILED:")
        for issue in issues:
            print(f"     ❌ {issue}")
    else:
        print(f"\n  ✅ ALL VALIDATION CHECKS PASS")

    return {"ok": len(issues) == 0, "path": "DATA_FIRST", "result": built, "issues": issues}


def main():
    print("#" * 80)
    print("  MOCK-DATA RUNTIME TRACE — Testing builder output with realistic data")
    print("#" * 80)

    queries = [
        ("جدول الرواتب", "Full table request"),
        ("كم راتب الدرجة السابعة", "Specific grade request"),
        ("كم مربوط الدرجة السابعة فقط", "Grade-specific with 'only' constraint"),
        ("راتب الدرجة العاشرة", "Non-existent grade → refusal"),
        ("الدرجة الأولى", "Follow-up style — first grade"),
    ]

    results = []
    for query, desc in queries:
        print(f"\n  --- {desc} ---")
        r = run_query(query)
        r["desc"] = desc
        r["query"] = query
        results.append(r)

    # Summary
    print("\n\n" + "#" * 80)
    print("  SUMMARY")
    print("#" * 80)
    all_ok = True
    for r in results:
        status = "✅" if r["ok"] else "❌"
        if not r["ok"]:
            all_ok = False
        preview = (r.get("result", "")[:60] + "...") if r.get("result") and len(r.get("result", "")) > 60 else r.get("result", "N/A")
        print(f"  {status} {r['query']} ({r['desc']})")
        print(f"     Path: {r['path']} | Result: {preview}")
        if r.get("issues"):
            for issue in r["issues"]:
                print(f"     ❌ {issue}")

    print(f"\n  {'✅ ALL QUERIES CORRECT' if all_ok else '❌ ISSUES FOUND — SEE ABOVE'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
