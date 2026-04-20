# -*- coding: utf-8 -*-
"""
tests_memo_no_history_al.py — memo intent survives empty history.

Covers the production failure mode where the UI submits
``history=[]`` (verified via server logs at 20:27:54), making
``memo_continuation`` A/B/C all fall through. The query
``"اكتب المذكرة"`` must then be recognised by phase0 on its own
— which requires ال-prefix tolerance.

Three assertion bundles on ONE request — reduces HTTP cost to one
call per scenario, and all three angles of the regression are
validated from the same observation.

Scenario N1 — ``"اكتب المذكرة"`` with empty history
  T2 expectation: ``done.route == "memo_ask_topic"`` (NOT ``general``).
  T3 expectation: response is a topic-ask (must name ≥ 1 topic option).
  T5 expectation: response is SHORT (< 500 chars) — not a full memo.

Scenario N2 — ``"اكتب مذكرة"`` (no ال) with empty history
  Regression guard. Must already pass today via the direct substring
  match. Kept so the fix doesn't accidentally break the happy path.

Standalone runner — exit 0 on all-pass, exit 1 on any failure.
"""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"


SCENARIOS: list[tuple[str, str, dict]] = [
    ("N1_al_prefix_empty_history",
     "اكتب المذكرة",
     {
         # Test 2: route gate
         "want_route": "memo_ask_topic",
         "must_not_route_be": ["general", "memo"],
         # Test 3 & 5: content + length gates
         "must_contain_any": [
             ["الموضوع", "حضانة", "نفقة", "دعوى"],   # asks for a topic
         ],
         "must_not_contain": [
             "بسم الله الرحمن الرحيم",               # full-memo body
             "السادة / قضاة المحكمة",
         ],
         "max_len": 500,
     }),

    ("N2_regression_guard_no_al",
     "اكتب مذكرة",
     {
         # Without ال, today's code reaches handle_memo_smart via the
         # existing "اكتب مذكرة" trigger. With empty history + no topic
         # it must NOT produce a full memo silently — the Fix-B
         # fallback applies equally here.
         "want_route": "memo_ask_topic",
         "must_not_route_be": ["general"],
         "must_contain_any": [
             ["الموضوع", "حضانة", "نفقة", "دعوى"],
         ],
         "max_len": 500,
     }),
]


def _sse_collect(query: str, timeout: int = 120) -> dict:
    body = json.dumps({
        "query": query,
        "session_id": f"no-hist-{int(time.time()*1000)}",
        "mode": "expert",
        "history": [],                         # ← critical: empty
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
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

    for banned in expect.get("must_not_route_be", []):
        if route == banned:
            errors.append(f"route='{route}' is banned (must_not_route_be)")

    for group in expect.get("must_contain_any", []):
        if not any(phrase in answer for phrase in group):
            errors.append(f"missing any of {group}")

    for forbidden in expect.get("must_not_contain", []):
        if forbidden in answer:
            errors.append(f"must_not_contain hit: {forbidden!r}")

    if "max_len" in expect and len(answer) > expect["max_len"]:
        errors.append(
            f"answer too long: {len(answer)} > max {expect['max_len']} "
            f"(expected a short topic-ask, not a full memo)"
        )

    return (not errors, errors)


def main() -> int:
    results = []
    for scenario_id, query, expect in SCENARIOS:
        short_q = re.sub(r"\s+", " ", query)[:60]
        print(f"━━━ {scenario_id}: {short_q}")

        try:
            r = _sse_collect(query)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append((scenario_id, False, "http-error", 0, [str(e)]))
            continue

        answer = r["answer"]
        done = r["done"]
        route = done.get("route", "?")
        ok, errs = _check(answer, done, expect)
        tag = "✓ PASS" if ok else "✗ FAIL"
        print(f"  len={len(answer)}  route={route}  {tag}")
        for e in errs:
            print(f"    - {e}")
        print(f"    « {answer[:150].replace(chr(10), ' ')}{'…' if len(answer)>150 else ''} »")
        results.append((scenario_id, ok, route, len(answer), errs))
        time.sleep(1.0)                         # pace for rate limiter

    passed = sum(1 for r in results if r[1])
    total = len(results)
    print()
    print(f"═══ RESULT: {passed}/{total} passed ═══")
    for scenario_id, ok, route, ln, errs in results:
        tag = "✓" if ok else "✗"
        print(f"  {tag} {scenario_id:<36} route={route:<18} len={ln}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
