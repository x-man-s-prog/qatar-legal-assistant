# -*- coding: utf-8 -*-
"""
tests_cp5_production_scenario.py — exact 8-turn user failure replay.

Re-runs the 8-turn scenario from the user's production transcript
where CP4's pattern-match gates evaporated because the UI sends
EMPTY history on memo-bearing turns. CP5's server-side state
machine must survive this without any client-supplied history.

CRITICAL: each request sends ``history=[]`` on purpose. Any test
that "works" only because the client sends full history is
worthless here — production doesn't. This file is the truth.

Run:
    python tests_cp5_production_scenario.py

Exit 0 on all-pass, 1 otherwise.
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error

API = "http://localhost:80/api/v1/stream/"
KEY = "CHANGE_ME"


def _sse_post_empty_history(query: str, session_id: str, timeout: int = 180) -> dict:
    """POST with EMPTY history on purpose — simulates UI bug that
    drops history on memo-bearing turns (FINDING #12 Cause B)."""
    body = json.dumps({
        "query": query,
        "session_id": session_id,
        "mode": "expert",
        "history": [],  # ← THE KEY POINT. Production UI does this.
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": KEY,
        },
    )
    content = ""
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
            t = obj.get("type")
            if t == "chunk":
                content += obj.get("content") or obj.get("text") or ""
            elif t == "done":
                done = obj
    return {"content": content, "done": done}


def main() -> int:
    sid = f"cp5-prod-{int(time.time() * 1000)}"
    results: list = []

    # Exact 8-turn transcript from the user's production failure.
    turns = [
        ("ما هي عقوبات المرور وسحب الرخصة",
         ("general", "general_degraded"),
         "t1"),
        ("اكتب لي مذكرة اسقاط حضانه ضد طليقتي",
         ("memo_ask_details",),
         "t2"),
        ("1- احمد 3 سنوات 2- سوء سلوكها واهمال لتعليم المحضون "
         "3- لا لكن يوجد وثيقة طلاق بتاريخ 01/01/2023",
         ("memo",),
         "t3"),
        ("لماذا لم تكتب المذكرة ؟",
         ("memo", "general"),  # either ok — state allows for clarification
         "t4"),
        ("اكتب مذكرة اسقاط حضانه",
         ("memo",),
         "t5"),
        ("اكتب بالمعلومات المتوفرة",
         ("memo",),
         "t6"),
        ("ما هي عقوبة تركيب اصوات مزعجة على السيارة",
         ("general", "general_degraded"),
         "t7"),
        ("ما هي العقوبة بالضبط",
         ("general", "general_degraded", "continuation"),
         "t8"),
    ]

    print("=" * 72)
    print(f" CP5 Production Scenario — 8-turn replay")
    print(f" Session: {sid}")
    print(f" history=[] on EVERY request (simulates UI bug)")
    print("=" * 72)

    for q, allowed, label in turns:
        short_q = re.sub(r"\s+", " ", q)[:65]
        print(f"\n--- {label}: {short_q}")
        try:
            r = _sse_post_empty_history(q, sid)
        except urllib.error.HTTPError as e:
            print(f"    HTTPError {e.code}")
            results.append({
                "label": label, "query": q,
                "route": "http-error", "allowed": allowed,
                "route_ok": False, "len": 0, "content": "",
            })
            time.sleep(8)
            continue
        except Exception as e:
            print(f"    ERROR {type(e).__name__}: {e}")
            results.append({
                "label": label, "query": q,
                "route": "error", "allowed": allowed,
                "route_ok": False, "len": 0, "content": "",
            })
            time.sleep(8)
            continue

        ans = r["content"]
        done = r["done"]
        route = done.get("route", "?")
        route_ok = route in allowed
        tag = "OK " if route_ok else "FAIL"
        print(f"    route={route:<22} len={len(ans):<5} {tag} (want: {allowed})")

        results.append({
            "label": label, "query": q, "route": route,
            "allowed": allowed, "route_ok": route_ok,
            "len": len(ans), "content": ans,
        })
        time.sleep(8)  # TPM pacing

    # ─── Content assertions ────────────────────────────────────
    print()
    print("=" * 72)
    print(" CONTENT ASSERTIONS")
    print("=" * 72)

    by_label = {r["label"]: r for r in results}

    content_checks: list = []

    # T3 — the memo itself (the critical failure point)
    t3 = by_label.get("t3", {})
    t3_ans = t3.get("content", "")
    # CP6 note — threshold lowered from 2500 to 800. Pre-CP6 memos were
    # template-dumps (all 7 domain articles + all helper blocks) typically
    # 4500+ chars. CP6 engine produces *prose* memos — denser, shorter,
    # targeted. A well-formed 1000-char prose memo is legally stronger than
    # a 4700-char template dump.
    t3_is_memo = t3.get("route") == "memo" and len(t3_ans) >= 800
    content_checks.append(("T3 memo generated (route=memo, len>=800)", t3_is_memo))
    content_checks.append(("T3 contains 'احمد' or 'أحمد'",
                           ("احمد" in t3_ans) or ("أحمد" in t3_ans)))
    content_checks.append(("T3 contains 'سلوك'", "سلوك" in t3_ans))

    # T4 — should NOT say "سؤالك لم يتضمن طلباً صريحاً"
    t4 = by_label.get("t4", {})
    t4_ans = t4.get("content", "")
    t4_not_context_loss = (
        "سؤالك لم يتضمن طلباً صريحاً" not in t4_ans
        and "لم يتضمن طلباً" not in t4_ans
    )
    content_checks.append(("T4 does NOT report context loss", t4_not_context_loss))

    # T5 — should NOT re-ask for details from scratch
    t5 = by_label.get("t5", {})
    t5_ans = t5.get("content", "")
    t5_not_reask = (
        "قبل ما أكتب مذكرة حضانة احترافية بأسماء ووقائعك الحقيقية"
        not in t5_ans
    )
    content_checks.append(("T5 does NOT re-ask for details from scratch",
                           t5_not_reask))

    # T6 — "اكتب بالمعلومات المتوفرة" must produce a memo, NOT
    #     "يرجى توضيح السؤال أو الموضوع"
    t6 = by_label.get("t6", {})
    t6_ans = t6.get("content", "")
    t6_not_confused = (
        "يرجى توضيح السؤال أو الموضوع" not in t6_ans
        and "يرجى توضيح السؤال" not in t6_ans
    )
    content_checks.append(("T6 does NOT ask for clarification", t6_not_confused))

    # T7 — fresh pivot to traffic question; MUST release memo state
    t7 = by_label.get("t7", {})
    t7_route_ok = t7.get("route") in ("general", "general_degraded")
    content_checks.append(("T7 routes away from memo (pivot accepted)",
                           t7_route_ok))

    # T7 — no irrelevant criminal penalties
    t7_ans = t7.get("content", "")
    t7_irrelevant = (
        "إهانة العلم", "العلم الوطني", "إخفاء المجرمين",
    )
    t7_clean = not any(s in t7_ans for s in t7_irrelevant)
    content_checks.append(("T7 no flag-insult / fugitive penalties",
                           t7_clean))

    # T8 — follow-up routing (NOT memo)
    t8 = by_label.get("t8", {})
    t8_route_ok = t8.get("route") in ("general", "general_degraded",
                                      "continuation")
    content_checks.append(("T8 routes away from memo", t8_route_ok))

    # ── Report ───────────────────────────────────────────────
    print()
    print("=" * 72)
    print(" RESULTS")
    print("=" * 72)

    print("\nROUTES:")
    for r in results:
        tag = "OK " if r["route_ok"] else "FAIL"
        print(f"  {r['label']} {tag} got={r['route']:<22} want={r['allowed']}")

    print("\nCONTENT:")
    for label, ok in content_checks:
        tag = "OK " if ok else "FAIL"
        print(f"  {tag} {label}")

    route_pass = sum(1 for r in results if r["route_ok"])
    content_pass = sum(1 for _, ok in content_checks if ok)
    total_pass = route_pass + content_pass
    total = len(results) + len(content_checks)

    print()
    print("=" * 72)
    print(f" TOTAL: {total_pass}/{total} passed "
          f"({route_pass}/{len(results)} routes + "
          f"{content_pass}/{len(content_checks)} content)")
    print("=" * 72)

    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
