# -*- coding: utf-8 -*-
"""Live tests f1-f12 — deep cleanup verification. Runs INSIDE the container."""
import json
import re
import sys
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"


def sse_collect(query, sid, history=None, timeout=120):
    body = json.dumps({
        "query": query, "session_id": sid, "mode": "expert",
        "history": history or [],
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": KEY},
    )
    parts = []
    done = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if line.startswith(b"data: "):
                try:
                    o = json.loads(line[6:].decode("utf-8"))
                except Exception:
                    continue
                t = o.get("type")
                if t == "chunk":
                    parts.append(o.get("content") or o.get("text") or "")
                elif t == "done":
                    done = o
    return {"answer": "".join(parts), "done": done or {}}


results = []


def record(tid, ok, route, length, reasons, snippet):
    results.append({"id": tid, "ok": ok, "route": route,
                    "len": length, "reasons": reasons})
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {tid:<4} route={route:<24} len={length}")
    if reasons:
        for r in reasons:
            print(f"       - {r}")
    if snippet:
        snip = re.sub(r"\s+", " ", snippet)[:200]
        print(f"       « {snip} »")


# ─── f1: review for contract ─────────────────────────────────────
print("\n=== f1: review(عقد) — route check ===")
from core.phase0_router import route_query
r = route_query("راجع هذا العقد", [])
got = r.get("route")
record("f1", got == "review", got, 0,
       [] if got == "review" else [f"got {got!r}"], "")

# ─── f2: tie-breaker — شيك بلا رصيد ارتد ─────────────────────────
print("\n=== f2: tie-breaker (شيك بلا رصيد) ===")
from core.runtime_v2.domains import resolve_domain
got = resolve_domain("شيك بلا رصيد ارتد").value
record("f2", got == "bad_check", got, 0,
       [] if got == "bad_check" else [f"got {got!r}"], "")

# ─── f3: tie-breaker — طلاق للضرر ───────────────────────────────
print("\n=== f3: tie-breaker (طلاق للضرر) ===")
got = resolve_domain("طلاق للضرر زوجي يضربني").value
record("f3", got == "divorce_for_harm", got, 0,
       [] if got == "divorce_for_harm" else [f"got {got!r}"], "")

# ─── f4: self_info counts ───────────────────────────────────────
print("\n=== f4: self_info counts ===")
r = sse_collect("كم عدد النصوص القانونية عندك", sid="f4")
ans = r["answer"]
ok = any(s in ans for s in ("49,048", "49,000+", "49000"))
record("f4", ok, r["done"].get("route", "?"), len(ans),
       [] if ok else ["missing updated count 49,048/49,000+"], ans[:200])

# ─── f5: new concept — التقادم ───────────────────────────────────
print("\n=== f5: التقادم الجنائي ===")
r = sse_collect("ما هو التقادم الجنائي في قطر", sid="f5")
ans = r["answer"]
ok = ("10" in ans and ("سنوات" in ans or "سنه" in ans)) and ("14" in ans or "م14" in ans)
record("f5", ok, r["done"].get("route", "?"), len(ans),
       [] if ok else ["missing 10 years or م14"], ans[:200])

# ─── f6: new concept — قرينة البراءة ────────────────────────────
print("\n=== f6: قرينة البراءة ===")
r = sse_collect("ما هي قرينة البراءة", sid="f6")
ans = r["answer"]
ok = ("النيابة" in ans) and ("المتهم" in ans) and ("عبء" in ans or "إثبات" in ans)
record("f6", ok, r["done"].get("route", "?"), len(ans),
       [] if ok else ["should mention عبء الإثبات على النيابة"], ans[:200])

# ─── f7: new concept — الاعتراف ─────────────────────────────────
print("\n=== f7: الاعتراف القضائي ===")
r = sse_collect("ما شروط صحة الاعتراف القضائي", sid="f7")
ans = r["answer"]
ok = ("طوعي" in ans or "طواعية" in ans or "حر" in ans or "إكراه" in ans or "الإكراه" in ans)
record("f7", ok, r["done"].get("route", "?"), len(ans),
       [] if ok else ["should mention طوعي/إكراه"], ans[:200])

# ─── f8: imports clean ──────────────────────────────────────────
print("\n=== f8: imports clean ===")
try:
    from routers.query_router import router as _r
    from core.legal_concepts import LEGAL_CONCEPTS
    ok = hasattr(_r, "routes") and len(LEGAL_CONCEPTS) == 21
    record("f8", ok, "-", len(LEGAL_CONCEPTS),
           [] if ok else [f"concepts={len(LEGAL_CONCEPTS)} (expected 21)"],
           f"concepts={len(LEGAL_CONCEPTS)}")
except Exception as e:
    record("f8", False, "-", 0, [f"{type(e).__name__}: {e}"], "")

# ─── f9: greeting ───────────────────────────────────────────────
print("\n=== f9: greeting ===")
r = sse_collect("السلام عليكم", sid="f9")
ans = r["answer"]
route = r["done"].get("route", "?")
ok = route == "greeting" and ("وعليكم" in ans or "أهلاً" in ans)
record("f9", ok, route, len(ans),
       [] if ok else ["greeting broken"], ans[:200])

# ─── f10: memo nafaqa with details ──────────────────────────────
print("\n=== f10: مذكرة نفقة (تفاصيل كاملة) ===")
r = sse_collect(
    "اكتب مذكرة نفقة زوجية لموكلتي المطلقة لها 3 اطفال 5 و 8 و 12 سنة طليقها راتبه 25000",
    sid="f10",
)
ans = r["answer"]
route = r["done"].get("route", "?")
ok = ("57" in ans or "75" in ans) and "بسم الله" in ans
record("f10", ok, route, len(ans),
       [] if ok else ["missing articles 57/75 or بسم الله"], ans[:200])

# ─── f11: مركّب (موظف سرق) ─────────────────────────────────────
print("\n=== f11: موظف سرق ===")
r = sse_collect("عندي موظف سرق 50 الف واعترف وعنده سوابق ما العقوبة", sid="f11")
ans = r["answer"]
route = r["done"].get("route", "?")
ok = ("354" in ans or "خيانة" in ans or "317" in ans or "أمانة" in ans)
record("f11", ok, route, len(ans),
       [] if ok else ["missing article reference"], ans[:200])

# ─── f12: حاسبة ─────────────────────────────────────────────────
print("\n=== f12: حاسبة نهاية الخدمة ===")
r = sse_collect(
    "احسب مكافأة نهاية الخدمة لموظف راتبه 15000 ريال خدم 10 سنوات",
    sid="f12",
)
ans = r["answer"]
route = r["done"].get("route", "?")
ok = route == "calculator" and ("15000" in ans or "15,000" in ans)
record("f12", ok, route, len(ans),
       [] if ok else ["calculator broken"], ans[:200])

# ─── summary ────────────────────────────────────────────────────
passed = sum(1 for r in results if r["ok"])
print(f"\n{'='*50}\nRESULT: {passed}/{len(results)} passed\n{'='*50}")
for r in results:
    flag = "PASS" if r["ok"] else "FAIL"
    extra = ""
    if not r["ok"]:
        extra = " — " + "; ".join(r["reasons"])
    print(f"  [{flag}] {r['id']}  route={r['route']:<22}  len={r['len']:<5}{extra}")

sys.exit(0 if passed == len(results) else 1)
