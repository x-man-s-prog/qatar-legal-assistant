# -*- coding: utf-8 -*-
"""Live tests m1-m8 — memo fix + FAMILY_NAFAQA."""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"

TESTS = [
    ("m1",
     "اكتب لي مذكرة نفقة",
     {"expect_kind": "ask",  # should ask questions, not produce a memo
      "must_contain_any": [["نفقة", "أحتاج", "التفاصيل", "نفقة زوجية", "الأطفال"]],
      "must_not_contain": ["يُتمسّك بتحقق عنصر اقدمها"]}),
    ("m2",
     "اكتب لي مذكرة نفقة زوجية وأطفال لموكلتي المطلقة لها 3 أطفال "
     "أعمارهم 5 و 8 و 12 سنة وطليقها موظف حكومي راتبه 25000 ريال "
     "وامتنع عن الإنفاق منذ 6 أشهر",
     {"expect_kind": "memo",
      "must_contain_any": [["57", "75"], ["قانون الأسرة", "رقم (22)", "22 لسنة 2006"]],
      "must_not_contain": ["يُتمسّك بتحقق عنصر اقدمها"]}),
    ("m3",
     "اكتب مذكرة اقدمها للمحكمة عن دعوة نفقه لاني تطلقت",
     {"expect_kind": "ask",
      "must_contain_any": [["نفقة", "التفاصيل", "أحتاج", "أطفال", "الدخل"]],
      "must_not_contain": ["يُتمسّك بتحقق عنصر اقدمها للمحكمة"]}),
    ("m4",
     "اكتب مذكرة دفاع حضانة لموكلتي المطلقة لها طفلان عمر 5 و 9 سنوات "
     "الأب يطالب بالحضانة بحجة عملها",
     {"expect_kind": "memo",
      "must_contain_any": [["حضان", "طفل"], ["الأسرة", "قانون"]]}),
    ("m5",
     "ما هي شروط النفقة الزوجية في القانون القطري",
     {"expect_kind": "analytical",
      "must_contain_any": [["نفقة", "الزوجة"], ["قانون الأسرة", "22", "2006"]]}),
    ("m6",
     "السلام عليكم",
     {"expect_kind": "greeting",
      "must_contain_any": [["وعليكم", "أهلاً", "مرحب", "السلام"]]}),
    ("m7",
     "احسب مكافأة نهاية الخدمة لموظف راتبه 15000 ريال خدم 10 سنوات",
     {"expect_kind": "calculator",
      "must_contain_any": [["15000", "10"], ["مكافأة", "نهاية الخدمة"]]}),
    ("m8",
     "عندي موظف سرق من الشركة 50 الف واعترف وعنده سوابق ما العقوبة",
     {"expect_kind": "analytical",
      "must_contain_any": [["خيانة", "354", "عقوبة"]]}),
]


def _sse_collect(query: str, sid: str, timeout: int = 120) -> dict:
    body = json.dumps({
        "query": query, "session_id": sid, "mode": "expert", "history": [],
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": KEY},
    )
    answer = []
    memo_text = None
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
                    memo_text = obj.get("memo") or memo_text
    full = "".join(answer)
    return {
        "answer": full,
        "memo": memo_text,
        "done": done_frame or {},
    }


def run():
    results = []
    for tid, q, checks in TESTS:
        print(f"\n━━━ {tid}: {q[:80]}{'…' if len(q)>80 else ''}", flush=True)
        t0 = time.time()
        try:
            res = _sse_collect(q, sid=tid)
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
        for group in checks.get("must_contain_any", []):
            if not any(v in ans for v in group):
                ok = False
                reasons.append(f"missing any of {group!r}")
        for s in checks.get("must_not_contain", []):
            if s in ans:
                ok = False
                reasons.append(f"forbidden substring {s!r} appeared")

        # Kind classification heuristic — for reporting only
        ans_lower = ans.lower()
        kind_seen = "memo" if any(m in ans for m in [
            "بسم الله", "أولاً: الوقائع", "السيد رئيس المحكمة",
        ]) else ("ask" if any(m in ans for m in [
            "أحتاج منك", "أحتاج التفاصيل", "قبل ما أكتب",
        ]) else "analytical")

        if ok:
            print(f"  ✓ PASS  (kind≈{kind_seen})")
            print(f"    « {re.sub(chr(10), ' ', ans)[:240]} »")
        else:
            print(f"  ✗ FAIL — {'; '.join(reasons)}")
            print(f"    first240: « {re.sub(chr(10), ' ', ans)[:240]} »")
        results.append({
            "id": tid, "ok": ok, "reasons": reasons, "kind": kind_seen,
            "len": len(ans), "dt": dt, "route": route,
        })

    passed = sum(1 for r in results if r["ok"])
    print(f"\n═══ RESULT: {passed}/{len(results)} passed ═══")
    for r in results:
        flag = "✓" if r["ok"] else "✗"
        print(f"  {flag} {r['id']}  kind={r.get('kind','?')}  "
              f"len={r.get('len',0)}  route={r.get('route','?')}")
        if not r["ok"]:
            for why in r.get("reasons", []):
                print(f"      - {why}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
