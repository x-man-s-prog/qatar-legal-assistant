# -*- coding: utf-8 -*-
"""
tests_memo_continuity_c9_long.py — 10-turn memo regression test.

Reproduces the exact failing scenario a real user hit: a custody-memo
conversation over ten turns. Proves that memo context survives a long
conversation where the rich-signal turn (T4, with names + numbers) gets
buried deep in history and the subsequent turns are short follow-ups.

Current-state expectation (before Step-4 fix):
  - T3  passes (memo_ask_details)
  - T4  passes (memo produced)
  - T5–T9 pass (memo_continuation keeps firing)
  - T10 FAILS: handle_memo_smart's ``history[-8:]`` window no longer
    includes T4 → signals drop below ``min_signals["حضانة"] = 2`` →
    re-asks for details (route=memo_ask_details).

After the fix this file must hit 10/10 PASS.

Standalone runner — exit 0 on all-pass, exit 1 on any failure.
Mirrors the style of ``tests_memo_continuity_c1_c8.py``.
"""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"
SID = f"c9-long-{int(time.time())}"

# ─────────────────────────────────────────────────────────────────
# The 10-turn script — copied verbatim from the user's incident report
# ─────────────────────────────────────────────────────────────────

TURNS: list[tuple[str, str, dict]] = [
    # (turn_id, query, expectations)
    ("t1", "كيف الحال", {
        "want_route_any": ["greeting", "general", "continuation"],
        "min_len": 20,
    }),
    ("t2", "ما الفرق بين الدفع الجوهري والموضوعي؟", {
        "want_route": "general",
        "must_contain_any": [["الدفع", "الجوهري"]],
        "min_len": 300,
    }),
    ("t3", "اكتب مذكرة اسقاط حضانه ضد طليقتي", {
        "want_route": "memo_ask_details",
        "must_contain_any": [["أحتاج", "التفاصيل"], ["حضانة", "الإسقاط"]],
        "must_not_contain": ["بسم الله"],
    }),
    ("t4",
     "1- طفل واحد اسمه احمد وعمره 3 سنوات\n"
     "2- السبب سوء سلوك الحاضنة\n"
     "3- لا لكن يوجد وثيقة طلاق فقط ..... طلقتها وانا انفق عليها وعلى الولد\n"
     "لكن فيها سوء سلوك وماتستحق حضانة ابني",
     {
         "want_route": "memo",
         "must_contain_any": [["بسم الله"], ["المذكرة", "الموضوع", "الوقائع"]],
         "must_not_contain": ["أحتاج منك هذه التفاصيل"],
         "min_len": 3000,
     }),
    ("t5",
     "انا رفعت دعوى اسقاط حضانه ومحدد لنظرها جلسة لكن احتاجك تكتب لي مذكرة",
     {
         "want_route": "memo",
         "must_contain_any": [["بسم الله"], ["المذكرة", "الموضوع"]],
         "min_len": 2000,
     }),
    ("t6", "لا انت قم باعداد المذكرة لي", {
        "want_route": "memo",
        "must_contain_any": [["بسم الله"]],
        "min_len": 2000,
    }),
    ("t7", "قلت لك موضوع اسقاط حضانه", {
        "want_route": "memo",
        "must_contain_any": [["بسم الله"]],
        "min_len": 2000,
    }),
    ("t8", "ليش ماتكتب مذكره ؟", {
        "want_route": "memo",
        "must_contain_any": [["بسم الله"]],
        "min_len": 2000,
    }),
    ("t9",
     "قلت لك اكثر من مره اكتب مذكرة ضد طليقتي في دعوى اسقاط حضانه",
     {
         "want_route": "memo",
         "must_contain_any": [["بسم الله"]],
         "min_len": 2000,
     }),
    ("t10", "اكتب بالمعلومات المتوفرة", {
        "want_route": "memo",                  # ← the failing case
        "must_contain_any": [["بسم الله"]],
        "must_not_contain": ["أحتاج منك هذه التفاصيل"],
        "min_len": 2000,
    }),
]


# ─────────────────────────────────────────────────────────────────
# HTTP helper + assertion runner (sync urllib to match c1-c8 style)
# ─────────────────────────────────────────────────────────────────

def _sse_collect(query: str, history: list, timeout: int = 180) -> dict:
    body = json.dumps({
        "query": query,
        "session_id": SID,
        "mode": "expert",
        "history": history,
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


def _check(turn_id: str, query: str, answer: str, done: dict,
           expect: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    route = done.get("route", "?")

    if "want_route" in expect:
        if route != expect["want_route"]:
            errors.append(
                f"route='{route}' (wanted '{expect['want_route']}')"
            )
    if "want_route_any" in expect:
        if route not in expect["want_route_any"]:
            errors.append(
                f"route='{route}' (wanted one of {expect['want_route_any']})"
            )

    for group in expect.get("must_contain_any", []):
        if not any(phrase in answer for phrase in group):
            errors.append(f"missing any of {group}")

    for forbidden in expect.get("must_not_contain", []):
        if forbidden in answer:
            errors.append(f"must_not_contain hit: {forbidden!r}")

    if "min_len" in expect and len(answer) < expect["min_len"]:
        errors.append(
            f"answer too short: {len(answer)} < {expect['min_len']}"
        )

    return (not errors, errors)


def main() -> int:
    history: list[dict] = []
    results: list[tuple[str, bool, str, int, list[str]]] = []

    for turn_id, query, expect in TURNS:
        short_q = re.sub(r"\s+", " ", query)[:68]
        print(f"━━━ {turn_id}: {short_q}")

        t0 = time.perf_counter()
        try:
            r = _sse_collect(query, history)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append((turn_id, False, "http-error", 0, [str(e)]))
            # Still append to history so subsequent turns have context
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": ""})
            continue
        dt = time.perf_counter() - t0

        answer = r["answer"]
        done = r["done"]
        route = done.get("route", "?")
        ok, errs = _check(turn_id, query, answer, done, expect)
        tag = "✓ PASS" if ok else "✗ FAIL"
        print(f"  len={len(answer)}  dt={dt:.1f}s  route={route}  {tag}")
        if errs:
            for e in errs:
                print(f"    - {e}")
        print(f"    « {answer[:180].replace(chr(10), ' ')}{'…' if len(answer)>180 else ''} »")

        results.append((turn_id, ok, route, len(answer), errs))

        # Grow history for the next turn
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": answer})
        time.sleep(1.5)   # small gap to avoid TPM saturation

    passed = sum(1 for r in results if r[1])
    total = len(results)

    print()
    print(f"═══ RESULT: {passed}/{total} passed ═══")
    for turn_id, ok, route, ln, errs in results:
        tag = "✓" if ok else "✗"
        print(f"  {tag} {turn_id:<4} route={route:<18} len={ln:<6}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
