# -*- coding: utf-8 -*-
import sys, json, time, urllib.request, urllib.parse

BASE = "http://localhost:8000"

def query(q, model="ollama", sid="rtest"):
    payload = json.dumps({"query": q, "model": model, "session_id": sid},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/v1/query/", data=payload,
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=200) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e), "answer": "", "sources": [], "confidence": 0}

TESTS = [
    "الحد الأقصى لساعات العمل",
    "كيف أرفع قضية في المحكمة",
    "عقوبة القتل العمد",
    "حقوق الطفل في القانون الإماراتي",
    "عقد الإيجار وشروط الفسخ",
]

print("\n=== الاختبارات المتبقية (5 أسئلة) ===\n")
passed = 0
for i, q in enumerate(TESTS, 1):
    print(f"[{i}/5] {q}")
    t0 = time.time()
    r = query(q, sid=f"rt-{i:02d}")
    el = time.time() - t0
    if r.get("error"):
        print(f"  ✗ FAIL  ERR: {r['error'][:80]}")
    else:
        conf = int((r.get("confidence") or 0) * 100)
        src  = len(r.get("sources") or [])
        ans  = r.get("answer") or ""
        ok   = conf > 0 and src > 0 and len(ans) > 50
        if ok: passed += 1
        mark = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {mark}  conf={conf}%  src={src}  ans={len(ans)}c  ({el:.1f}s)")
        if ans: print(f"  → {ans[:100].replace(chr(10),' ')}…")
    print()

print(f"النتيجة: {passed}/5 PASS")
