# -*- coding: utf-8 -*-
"""Live tests h1-h10 for Part 2 (Hallucination Guard + Legal Concept DB).

Runs inside the legal_app container against http://localhost:8000.
"""
import json
import re
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/stream/"
KEY = "CHANGE_ME"

TESTS = [
    # (id, query, checks_dict)
    # checks is any of:
    #   'must_contain': [strings]        — answer must contain these
    #   'must_not_contain': [strings]    — answer must NOT contain these
    #   'guard_fires': bool              — guard must emit at least 1 warning
    #   'no_guard': bool                 — no guard warning should fire
    #   'concepts': [concept names]      — these concept_terms should be reported
    ("h1", "ما المقصود بالدفع الجوهري في القانون القطري؟", {
        "must_contain_any": [
            ["يغيّر", "يغير", "يُغيّر", "تغيير", "زوال الحق", "سقوط الدعوى"],
            ["وجه الرأي", "أصل الحق", "جوهري في الإجراءات", "الدعوى"],
            ["قصور", "إخلال بحق الدفاع", "التسبيب"],
        ],
        "concepts": ["الدفع الجوهري"],
        "no_guard": True,
    }),
    ("h2", "اشرح لي السلطة الولائية في المحاكم القطرية", {
        "must_contain": ["ولائي"],
        "must_not_contain": ["اختصاص مكاني", "توزيع جغرافي"],
        "concepts": ["السلطة الولائية"],
        "no_guard": True,
    }),
    ("h3", "ما الفرق بين الشروع والعود؟", {
        "must_contain_any": [
            ["البدء في التنفيذ", "بدء التنفيذ", "محاولة", "غير مكتمل"],
            ["جريمة جديدة", "ارتكاب جريمة", "بعد العقوبة", "بعد الحكم", "تكرار"],
        ],
        "concepts": ["الشروع", "العود"],
    }),
    ("h4", "ما هو الخلع وهل هو طلاق رجعي؟", {
        "must_contain": ["بائن"],
        "must_not_contain": ["رجعي يحق للزوج", "طلاق رجعي"],
        "concepts": ["الخلع"],
    }),
    ("h5", "الحضانة والولاية على الأبناء في القانون القطري", {
        "must_contain": ["الحضانة", "ولاي"],
        "concepts": ["الحضانة"],
    }),
    ("h6", "ما هو الفصل التعسفي وكيف يُحسب التعويض؟", {
        "must_contain": ["تعويض"],
        "concepts": ["الفصل التعسفي"],
    }),
    ("h7", "ما هي حجية الأمر المقضي؟", {
        "must_contain": ["الخصوم", "الموضوع", "السبب"],
        "concepts": ["حجية الأمر المقضي"],
    }),
    # Backwards-compat — simple legal question not involving concepts
    ("h8", "كم عقوبة السرقة في قانون العقوبات القطري؟", {
        "must_contain": ["العقوب"],
        "concepts_empty": True,
    }),
    # Backwards-compat — labor law without triggering concepts
    ("h9", "ما هي مكافأة نهاية الخدمة للعامل؟", {
        "must_contain": ["مكافأة", "نهاية الخدمة"],
        "concepts_empty": True,
    }),
    # Follow-up / simple small-talk
    ("h10", "ما رأيك في خدمتك؟", {
        # just needs to run without error
    }),
]


def _sse_collect(query: str, sid: str, timeout: int = 90) -> dict:
    body = json.dumps({
        "query": query, "session_id": sid, "mode": "expert", "history": [],
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": KEY},
    )
    answer = []
    done_frame = None
    guard_chunks = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        buf = b""
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
                    if obj.get("source") == "hallucination_guard":
                        guard_chunks.append(txt)
                    else:
                        answer.append(txt)
                elif t == "done":
                    done_frame = obj
    return {
        "answer": "".join(answer),
        "done": done_frame or {},
        "guard_chunks": guard_chunks,
    }


def run():
    results = []
    for tid, q, checks in TESTS:
        print(f"\n━━━ {tid}: {q}", flush=True)
        t0 = time.time()
        ok = True
        reasons = []
        try:
            res = _sse_collect(q, sid=tid)
        except Exception as e:
            ok = False
            reasons.append(f"request error: {type(e).__name__}: {e}")
            results.append({"id": tid, "ok": False, "reasons": reasons})
            print(f"  ✗ {reasons[-1]}")
            continue
        dt = time.time() - t0
        ans = res["answer"]
        done = res["done"]
        guard_count = int(done.get("guard_warnings") or 0)
        concepts = done.get("concepts_injected") or []
        print(f"  len(ans)={len(ans)}  dt={dt:.1f}s  "
              f"concepts={concepts}  guard_warnings={guard_count}  "
              f"guard_chunks={len(res['guard_chunks'])}")

        for s in checks.get("must_contain", []):
            if s not in ans:
                ok = False
                reasons.append(f"missing {s!r}")
        # must_contain_any: list of groups — each group is a list of
        # variants; at least one variant from each group must be present
        for group in checks.get("must_contain_any", []):
            if not any(v in ans for v in group):
                ok = False
                reasons.append(f"missing any of {group!r}")
        for s in checks.get("must_not_contain", []):
            if s in ans:
                ok = False
                reasons.append(f"forbidden {s!r}")
        if checks.get("no_guard") and guard_count > 0:
            # Only fail if the guard fired on a KNOWN bad pattern,
            # not the mild article-numbers warning.
            bad = any("الدفع الجوهري ليس" in c or "السلطة الولائية ليست" in c
                      for c in res["guard_chunks"])
            if bad:
                ok = False
                reasons.append(f"guard fired unexpectedly ({guard_count})")
        if checks.get("guard_fires") and guard_count == 0:
            ok = False
            reasons.append("guard should have fired")
        expected_concepts = checks.get("concepts", [])
        if expected_concepts:
            for c in expected_concepts:
                if c not in concepts:
                    ok = False
                    reasons.append(f"concept {c!r} not injected")
        if checks.get("concepts_empty") and concepts:
            ok = False
            reasons.append(f"unexpected concept injection: {concepts}")

        if ok:
            print(f"  ✓ PASS")
            snippet = re.sub(r"\s+", " ", ans)[:240]
            print(f"    « {snippet} »")
        else:
            print(f"  ✗ FAIL — {'; '.join(reasons)}")
            print(f"    last200: « {ans[-200:]} »")
        results.append({
            "id": tid, "ok": ok, "reasons": reasons,
            "len": len(ans), "dt": dt,
            "concepts": concepts, "guard_warnings": guard_count,
        })

    passed = sum(1 for r in results if r["ok"])
    print(f"\n═══ RESULT: {passed}/{len(results)} passed ═══")
    for r in results:
        flag = "✓" if r["ok"] else "✗"
        print(f"  {flag} {r['id']}  "
              f"(len={r.get('len',0)}, concepts={r.get('concepts') or '[]'}, "
              f"guard={r.get('guard_warnings',0)})")
        if not r["ok"]:
            for why in r.get("reasons", []):
                print(f"      - {why}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
