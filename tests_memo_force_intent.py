# -*- coding: utf-8 -*-
"""
tests_memo_force_intent.py — force-memo intent detection with empty history.

Covers two scenarios that must route to ``handle_memo_smart`` without
relying on any history-based continuation:

  f_a — "canonical" memo request that already matches phase0 triggers.
        Serves as a regression guard (must always route=memo_ask_details).

  f_b — verb-variant request ("احتاجك تكتب لي مذكرة …") that the current
        ``_MEMO_TRIGGERS`` list misses because it hard-codes "اكتب"
        imperative forms, not "تكتب" / "احتاج ... تكتب" variations.

Current-state expectation (before Step-4 fix):
  • f_a passes (regression guard). Kept to prevent future breakage.
  • f_b FAILS — current phase0 routes it to ``general`` because the
    substring "اكتب مذكرة" is not present; "تكتب" isn't listed.
    After the fix (force-memo = memo-verb + "مذكرة" + topic-keyword),
    it must route to ``memo_ask_details``.

Standalone runner — exit 0 on all-pass, exit 1 on any failure.
"""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"


TESTS: list[tuple[str, str, dict]] = [
    # (test_id, query, expectations)
    ("f_a",
     "اكتب مذكرة إسقاط حضانة ضد طليقتي",
     {
         "want_route": "memo_ask_details",
         "must_contain_any": [["أحتاج", "التفاصيل"], ["حضانة", "الإسقاط"]],
         "must_not_contain_route": ["general"],
     }),

    ("f_b",
     "احتاجك تكتب لي مذكرة إسقاط حضانة",
     {
         "want_route": "memo_ask_details",
         "must_contain_any": [["أحتاج", "التفاصيل"], ["حضانة"]],
         "must_not_contain_route": ["general"],
     }),
]


def _sse_collect(query: str, timeout: int = 120) -> dict:
    body = json.dumps({
        "query": query,
        "session_id": f"force-intent-{int(time.time()*1000)}",
        "mode": "expert",
        "history": [],                # explicit empty history
    }).encode("utf-8")
    req = urllib.request.Request(
        API,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": KEY},
    )
    answer = ""
    done = {}
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            txt = line.decode("utf-8", errors="replace")
            if not txt.startswith("data: "):
                continue
            try:
                obj = json.loads(txt[6:])
            except Exception:
                continue
            if obj.get("type") == "chunk":
                answer += obj.get("content") or obj.get("text") or ""
            elif obj.get("type") == "done":
                done = obj
    return {"answer": answer, "done": done}


def _check(answer: str, done: dict, expect: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    route = done.get("route", "?")

    if "want_route" in expect and route != expect["want_route"]:
        errors.append(f"route='{route}' (wanted '{expect['want_route']}')")

    for banned in expect.get("must_not_contain_route", []):
        if route == banned:
            errors.append(f"route='{route}' is in must_not_contain_route")

    for group in expect.get("must_contain_any", []):
        if not any(phrase in answer for phrase in group):
            errors.append(f"missing any of {group}")

    return (not errors, errors)


def main() -> int:
    results = []
    for test_id, query, expect in TESTS:
        short_q = re.sub(r"\s+", " ", query)[:60]
        print(f"━━━ {test_id}: {short_q}")

        t0 = time.perf_counter()
        try:
            r = _sse_collect(query)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append((test_id, False, "http-error", 0, [str(e)]))
            continue
        dt = time.perf_counter() - t0

        answer = r["answer"]
        done = r["done"]
        route = done.get("route", "?")
        ok, errs = _check(answer, done, expect)
        tag = "✓ PASS" if ok else "✗ FAIL"
        print(f"  len={len(answer)}  dt={dt:.1f}s  route={route}  {tag}")
        for e in errs:
            print(f"    - {e}")
        print(f"    « {answer[:150].replace(chr(10), ' ')}{'…' if len(answer)>150 else ''} »")

        results.append((test_id, ok, route, len(answer), errs))
        time.sleep(1.0)

    passed = sum(1 for r in results if r[1])
    total = len(results)

    print()
    print(f"═══ RESULT: {passed}/{total} passed ═══")
    for test_id, ok, route, ln, errs in results:
        tag = "✓" if ok else "✗"
        print(f"  {tag} {test_id:<4} route={route:<18} len={ln}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
