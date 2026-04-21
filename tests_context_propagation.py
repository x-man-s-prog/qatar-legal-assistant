# -*- coding: utf-8 -*-
"""
tests_context_propagation.py — CP4 end-to-end regression suite.

Reproduces the production 7-turn user scenario that exposed three
systemic failures:
  1. CONTEXT LOSS — T3 structured details routed to `general`
  2. TOPIC PERSISTENCE — T4 standalone "اكتب المذكرة" asked for topic
  3. IRRELEVANT ANSWERS — T6/T7 traffic-noise returned flag-insult

Route assertions + content assertions per turn. Designed to be run as
a standalone script (no pytest dependency) against the live container.

Run:
    python tests_context_propagation.py

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


def _sse_post(query: str, session_id: str, history: list,
              timeout: int = 180) -> dict:
    body = json.dumps({
        "query": query,
        "session_id": session_id,
        "mode": "expert",
        "history": history,
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
    sid = f"ctx-prop-{int(time.time() * 1000)}"
    history: list = []
    results: list = []

    # (turn_query, allowed_routes)
    turns = [
        ("ما هي عقوبات المرور وسحب الرخصة",
         ("general", "general_degraded")),
        ("اكتب لي مذكرة اسقاط حضانه ضد طليقتي",
         ("memo_ask_details",)),
        ("1- احمد 3 سنوات 2- سوء سلوكها واهمال لتعليم المحضون "
         "3- لا لكن يوجد وثيقة طلاق بتاريخ 01/01/2023",
         ("memo",)),
        ("طيب اكتب المذكرة",
         ("memo",)),
        ("ذكرت الموضوع في الرسالة السابقة",
         ("memo",)),
        ("ما هي عقوبة تركيب اصوات مزعجة على السيارة",
         ("general", "general_degraded")),
        ("ما هي العقوبة بالضبط",
         ("general", "general_degraded", "continuation")),
    ]

    print("=" * 72)
    print(f" CP4 Context Propagation — 7-turn live scenario")
    print(f" Session: {sid}")
    print("=" * 72)

    for idx, (q, allowed) in enumerate(turns, 1):
        short_q = re.sub(r"\s+", " ", q)[:65]
        print(f"\n--- Turn {idx}: {short_q}")
        try:
            r = _sse_post(q, sid, history)
        except urllib.error.HTTPError as e:
            print(f"    HTTPError {e.code} — aborting")
            results.append({
                "turn": idx, "query": q,
                "route": "http-error", "allowed": allowed,
                "route_ok": False, "len": 0, "content": "",
            })
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": ""})
            time.sleep(6)
            continue
        except Exception as e:
            print(f"    ERROR {type(e).__name__}: {e}")
            results.append({
                "turn": idx, "query": q,
                "route": "error", "allowed": allowed,
                "route_ok": False, "len": 0, "content": "",
            })
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": ""})
            time.sleep(6)
            continue

        ans = r["content"]
        done = r["done"]
        route = done.get("route", "?")
        route_ok = route in allowed
        tag = "OK " if route_ok else "FAIL"
        print(f"    route={route:<22} len={len(ans):<5} {tag} (want: {allowed})")

        results.append({
            "turn": idx, "query": q, "route": route, "allowed": allowed,
            "route_ok": route_ok, "len": len(ans),
            "content": ans,
        })
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": ans})
        time.sleep(6)  # TPM pacing per FINDING #9

    # ── Content assertions ────────────────────────────────────────
    print()
    print("=" * 72)
    print(" CONTENT ASSERTIONS")
    print("=" * 72)

    content_checks: list = []

    # T3 — the memo itself
    t3 = results[2]
    t3_ans = t3["content"]
    t3_is_memo = t3["route"] == "memo" and len(t3_ans) >= 3000
    content_checks.append(("T3 memo generated (route=memo, len>=3000)", t3_is_memo))
    content_checks.append(("T3 contains 'احمد' or 'أحمد'",
                           ("احمد" in t3_ans) or ("أحمد" in t3_ans)))
    content_checks.append(("T3 contains 'سلوك'", "سلوك" in t3_ans))
    content_checks.append(("T3 contains '3 سنوات' or 'ثلاث'",
                           ("3 سنوات" in t3_ans) or ("ثلاث" in t3_ans)))

    # T4 — must NOT re-ask for topic
    t4 = results[3]
    t4_ans = t4["content"]
    t4_not_ask_topic = "لأصيغ لك مذكرة صحيحة أحتاج موضوعها" not in t4_ans
    content_checks.append(("T4 does NOT re-ask for topic", t4_not_ask_topic))

    # T5 — must NOT say "no details available"
    t5 = results[4]
    t5_ans = t5["content"]
    t5_not_context_loss = (
        "لا أملك تفاصيل الرسالة السابقة" not in t5_ans
        and "لا أملك تفاصيل" not in t5_ans
    )
    content_checks.append(("T5 does NOT report context loss", t5_not_context_loss))

    # T6 — must NOT return flag-insult / cyber-crime / hiding-criminals
    t6 = results[5]
    t6_ans = t6["content"]
    t6_irrelevant_signals = (
        "إهانة العلم", "العلم الوطني", "جرائم الإلكترونية",
        "إخفاء المجرمين", "جرائم إلكترونية",
    )
    t6_clean = not any(s in t6_ans for s in t6_irrelevant_signals)
    content_checks.append(("T6 does NOT return irrelevant penalties", t6_clean))

    # ── Report ───────────────────────────────────────────────────
    print()
    print("=" * 72)
    print(" RESULTS")
    print("=" * 72)

    print("\nROUTES:")
    for r in results:
        tag = "OK " if r["route_ok"] else "FAIL"
        print(f"  T{r['turn']} {tag} got={r['route']:<22} want={r['allowed']}")

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
