# -*- coding: utf-8 -*-
"""Live tests c1-c8 — memo conversation continuity."""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"

ASK_Q = ("قبل ما أكتب مذكرة نفقة احترافية بأسماء ووقائعك الحقيقية، "
         "أحتاج منك هذه التفاصيل: 1. هل الدعوى نفقة زوجية أم نفقة أطفال "
         "أم كلاهما؟ 2. كم عدد الأطفال؟")

TESTS = [
    # c1: "اكتب مذكرة" after answers to memo questions
    ("c1",
     "طيب اكتب لي مذكرة",
     [
         {"role": "user",      "content": "اكتب لي مذكرة نفقة لاني تطلقت"},
         {"role": "assistant", "content": ASK_Q},
         {"role": "user",
          "content": "كلاهما 3 اطفال اعمارهم 4 و 7 و 10 وطليقي ملازم في الداخلية وتطلقت 11/11/2025 وهو ممتنع عن النفقة منذ طلقني"},
     ],
     {"want_route": "memo", "must_produce_memo": True,
      "must_contain_any": [["بسم الله", "الوقائع"],
                           ["57", "75"],
                           ["قانون الأسرة", "22", "2006"]],
      "must_not_contain": ["أحتاج منك هذه التفاصيل"]}),

    # c2: answering details right after memo question
    ("c2",
     "كلاهما 3 اطفال اعمارهم 4 و 7 و 10 وطليقي ملازم في الداخلية وتطلقت 11/11/2025",
     [
         {"role": "user",      "content": "اكتب لي مذكرة نفقة"},
         {"role": "assistant", "content": ASK_Q},
     ],
     {"want_route": "memo", "must_produce_memo": True,
      "must_contain_any": [["بسم الله", "الوقائع"],
                           ["57", "75"]]}),

    # c3: "يلا اكتب" after user already gave details
    ("c3",
     "يلا اكتب المذكرة",
     [
         {"role": "user",      "content": "اكتب مذكرة نفقة"},
         {"role": "assistant", "content": ASK_Q},
         {"role": "user",
          "content": "نفقة زوجية واطفال لي 3 اطفال 5 و 8 و 12 سنة طليقي موظف حكومي راتبه 25000 ريال"},
         {"role": "assistant", "content": "شكراً للتفاصيل. بناءً على المادة 75..."},
     ],
     {"want_route": "memo", "must_produce_memo": True,
      "must_contain_any": [["بسم الله", "الوقائع"]]}),

    # c4: full-detail memo from scratch
    ("c4",
     "اكتب لي مذكرة نفقة زوجية وأطفال لموكلتي المطلقة لها 3 أطفال أعمارهم 5 و 8 و 12 سنة وطليقها موظف حكومي راتبه 25000 ريال وامتنع عن الإنفاق منذ 6 أشهر",
     [],
     {"want_route": "memo", "must_produce_memo": True,
      "must_contain_any": [["بسم الله"], ["57", "75"]]}),

    # c5: memo with no details — must ask
    ("c5",
     "اكتب لي مذكرة نفقة",
     [],
     {"want_route": "memo_ask_details", "must_produce_memo": False,
      "must_contain_any": [["أحتاج", "التفاصيل"], ["نفقة"]],
      "must_not_contain": ["بسم الله"]}),

    # c6: greeting
    ("c6",
     "السلام عليكم",
     [],
     {"want_route": "greeting",
      "must_contain_any": [["وعليكم", "أهلاً", "مرحب"]]}),

    # c7: general legal question — must NOT go to memo
    ("c7",
     "ما عقوبة السرقة في القانون القطري",
     [],
     {"want_route": "general",
      "must_contain_any": [["سرقة", "عقوب"]],
      "must_not_contain": ["أحتاج منك هذه التفاصيل", "بسم الله"]}),

    # c8: calculator
    ("c8",
     "احسب مكافأة نهاية الخدمة لموظف راتبه 15000 ريال خدم 10 سنوات",
     [],
     {"want_route": "calculator",
      "must_contain_any": [["15000", "10"], ["مكافأة", "نهاية"]]}),
]


def _sse_collect(query: str, sid: str, history: list, timeout: int = 120) -> dict:
    body = json.dumps({
        "query": query, "session_id": sid, "mode": "expert",
        "history": history,
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": KEY},
    )
    answer = []
    done_frame = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if not line.strip():
                continue
            if line.startswith(b"data: "):
                try:
                    obj = json.loads(line[6:].decode("utf-8"))
                except Exception:
                    continue
                t = obj.get("type")
                if t == "chunk":
                    txt = obj.get("content") or obj.get("text") or ""
                    answer.append(txt)
                elif t == "done":
                    done_frame = obj
    return {
        "answer": "".join(answer),
        "done": done_frame or {},
    }


def run():
    results = []
    for tid, q, hist, checks in TESTS:
        print(f"\n━━━ {tid}: {q[:80]}{'…' if len(q)>80 else ''}", flush=True)
        t0 = time.time()
        try:
            res = _sse_collect(q, sid=tid, history=hist)
        except Exception as e:
            results.append({"id": tid, "ok": False,
                            "reasons": [f"{type(e).__name__}: {e}"]})
            print(f"  ✗ {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        ans = res["answer"]
        done = res["done"]
        route = done.get("route", "?")
        print(f"  len={len(ans)}  dt={dt:.1f}s  route={route}")

        ok = True
        reasons = []

        want_route = checks.get("want_route")
        if want_route:
            if route != want_route:
                ok = False
                reasons.append(f"route={route!r} (wanted {want_route!r})")

        must_produce_memo = checks.get("must_produce_memo", None)
        has_memo_shape = ("بسم الله" in ans) or ("أولاً: الوقائع" in ans)
        if must_produce_memo is True and not has_memo_shape:
            ok = False
            reasons.append("expected memo (بسم الله) but none produced")
        if must_produce_memo is False and has_memo_shape:
            ok = False
            reasons.append("unexpected memo produced")

        for group in checks.get("must_contain_any", []):
            if not any(v in ans for v in group):
                ok = False
                reasons.append(f"missing any of {group!r}")
        for s in checks.get("must_not_contain", []):
            if s in ans:
                ok = False
                reasons.append(f"forbidden {s!r} appeared")

        if ok:
            print(f"  ✓ PASS")
            print(f"    « {re.sub(chr(10), ' ', ans)[:200]} »")
        else:
            print(f"  ✗ FAIL — {'; '.join(reasons)}")
            print(f"    first200: « {re.sub(chr(10), ' ', ans)[:200]} »")
        results.append({
            "id": tid, "ok": ok, "reasons": reasons,
            "len": len(ans), "dt": dt, "route": route,
        })

    passed = sum(1 for r in results if r["ok"])
    print(f"\n═══ RESULT: {passed}/{len(results)} passed ═══")
    for r in results:
        flag = "✓" if r["ok"] else "✗"
        print(f"  {flag} {r['id']}  route={r.get('route','?'):<20}  "
              f"len={r.get('len',0)}  dt={r.get('dt',0):.1f}s")
        if not r["ok"]:
            for why in r.get("reasons", []):
                print(f"      - {why}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
