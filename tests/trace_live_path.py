# -*- coding: utf-8 -*-
"""
LIVE RUNTIME PATH TRACER
==========================
Connects to the REAL database and traces the EXACT execution path
for structured queries through: classify → resolve_lookup → answer_builder.

This is NOT a unit test — it hits the real DB and prints a full trace log.
"""
import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Set up detailed trace logging ──
logging.basicConfig(
    level=logging.DEBUG,
    format="%(name)-20s | %(levelname)-7s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("TRACE")

# Suppress noisy loggers
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("asyncpg").setLevel(logging.WARNING)


async def trace_query(pool, query: str):
    """Full execution trace for a single query."""
    print("\n" + "=" * 80)
    print(f"  QUERY: {query}")
    print("=" * 80)

    # ── Step 1: Classification ──
    from core.structured_lookup import classify_query, QueryIntent
    intent = classify_query(query)
    print(f"\n[TRACE-1] CLASSIFICATION: {intent.value}")

    # ── Step 2: Is it structured? ──
    from core.refusal_engine import is_structured_intent
    is_struct = is_structured_intent(intent.value)
    print(f"[TRACE-2] IS_STRUCTURED: {is_struct}")

    if not is_struct:
        print(f"[TRACE-2] → NOT a structured intent. Would go to RAG/LLM path.")
        return {"query": query, "intent": intent.value, "path": "RAG/LLM", "result": None}

    # ── Step 3: Resolve lookup ──
    print(f"[TRACE-3] CALLING resolve_lookup()")
    from core.structured_lookup import resolve_lookup
    result = await resolve_lookup(query, pool)

    if result is None:
        print(f"[TRACE-3] → resolve_lookup returned None (should never happen for structured)")
        from core.refusal_engine import generate_refusal
        refusal = generate_refusal(intent.value, query)
        print(f"[TRACE-3] → SAFETY REFUSAL: {refusal}")
        return {"query": query, "intent": intent.value, "path": "SAFETY_REFUSAL", "result": refusal}

    print(f"[TRACE-3] → is_refusal={result.get('is_refusal')}, confidence={result.get('confidence')}")

    if result.get("is_refusal"):
        print(f"[TRACE-4] REFUSAL ENGINE RESULT:")
        print(f"  Text: {result['result']}")
        print(f"  Len: {len(result['result'])} chars")
        print(f"  LLM_CALLED: NO")
        return {"query": query, "intent": intent.value, "path": "REFUSAL", "result": result["result"]}

    # ── Step 4: Data hit — check builder output ──
    print(f"[TRACE-4] DATA HIT:")
    print(f"  Intent: {result['intent']}")
    print(f"  Confidence: {result['confidence']}")
    print(f"  Raw data keys: {list(result.get('raw_data', {}).keys()) if result.get('raw_data') else 'None'}")

    built_text = result["result"]
    print(f"\n[TRACE-5] BUILDER OUTPUT ({len(built_text)} chars):")
    print(f"  --------- BEGIN ---------")
    # Print first 500 chars
    print(f"  {built_text[:500]}")
    if len(built_text) > 500:
        print(f"  ... ({len(built_text) - 500} more chars)")
    print(f"  ---------- END ----------")

    # ── Step 5: Validate output ──
    print(f"\n[TRACE-6] VALIDATION:")
    issues = []

    # Check for forbidden markers
    forbidden = ["📋", "⚖️", "🔍", "✅", "📊"]
    for marker in forbidden:
        if marker in built_text:
            issues.append(f"FORBIDDEN MARKER: '{marker}'")

    # Check for raw OCR dumps (lines > 200 chars)
    for i, line in enumerate(built_text.split('\n')):
        if len(line.strip()) > 200:
            issues.append(f"RAW OCR LINE {i}: {len(line.strip())} chars")

    # Check for full table dumps (> 1000 chars total)
    if len(built_text) > 1000:
        issues.append(f"RESPONSE TOO LONG: {len(built_text)} chars")

    # Check if "only" constraint is honored for specific grade queries
    from core.structured_lookup import _extract_grade
    grade = _extract_grade(query)
    if grade and "فقط" in query:
        line_count = len([l for l in built_text.split('\n') if l.strip()])
        if line_count > 5:
            issues.append(f"GRADE-SPECIFIC but {line_count} lines returned (should be ≤5)")

    if issues:
        print(f"  ISSUES FOUND:")
        for issue in issues:
            print(f"    ❌ {issue}")
    else:
        print(f"  ✅ ALL CHECKS PASS")

    print(f"\n[TRACE-7] LLM_CALLED: NO")
    print(f"[TRACE-7] PATH: classify → resolve_lookup → build_structured_answer → DIRECT RETURN")

    return {
        "query": query, "intent": intent.value, "path": "DATA_FIRST",
        "result": built_text, "issues": issues,
        "confidence": result["confidence"], "len": len(built_text),
    }


async def main():
    """Run all 3 test queries against the real database."""
    print("\n" + "#" * 80)
    print("  LIVE RUNTIME PATH TRACER — Connecting to real database")
    print("#" * 80)

    # ── Connect to DB ──
    try:
        import asyncpg
        from core.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
        pool = await asyncio.wait_for(
            asyncpg.create_pool(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
                min_size=1, max_size=3, ssl=False,
            ),
            timeout=5.0,
        )
        print(f"\n✅ Connected to PostgreSQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    except Exception as e:
        print(f"\n❌ DB CONNECTION FAILED: {e}")
        print("Running in OFFLINE mode (no real data)")
        pool = None

    # ── Test queries ──
    queries = [
        "جدول الرواتب",
        "كم راتب الدرجة السابعة",
        "كم مربوط الدرجة السابعة فقط",
    ]

    results = []
    for q in queries:
        r = await trace_query(pool, q)
        results.append(r)

    # ── Summary ──
    print("\n\n" + "#" * 80)
    print("  SUMMARY")
    print("#" * 80)
    for r in results:
        status = "✅" if not r.get("issues") else "❌"
        path = r["path"]
        intent = r["intent"]
        result_preview = (r["result"][:60] + "...") if r.get("result") and len(r["result"]) > 60 else r.get("result", "None")
        print(f"\n  {status} [{intent}] {r['query']}")
        print(f"     Path: {path}")
        print(f"     Result: {result_preview}")
        if r.get("issues"):
            for issue in r["issues"]:
                print(f"     ❌ {issue}")

    # ── Cleanup ──
    if pool:
        await pool.close()

    # Return exit code
    all_ok = all(not r.get("issues") for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
