# -*- coding: utf-8 -*-
"""CP10 — live replay of the exact 9-turn transcript the user posted.

Verifies three root-cause fixes:
  A. Topic carry-over on new memo request (drug → custody).
  B. Meta false-positive on "كم يبلغ راتب موظف...".
  C. Meta unknown-metric → must degrade to general, not identity card.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
import requests


BASE_URL = "http://localhost/api/v1/stream/"
SID = f"cp10-{uuid.uuid4().hex[:12]}"


TURNS = [
    # (label, query, expected_route, expected_substrings (any), expected_not (forbidden))
    ("T1 عقوبات المرور",
     "ما هي عقوبات المرور وسحب الرخصة؟",
     {"general", "legal_answer", "answer", "compose"},
     [],
     []),
    ("T2 هل من بينها حجز المركبة",
     "هل من بينها حجز المركبة ؟",
     {"general", "legal_answer", "answer", "compose"},
     [],
     []),
    ("T3 اكتب مذكرة مخدرات (ask-details)",
     "اكتب لي مذكرة في قضية تعاطي مخدرات",
     {"memo_ask_details", "memo_ask_topic"},
     [],
     []),
    ("T4 تفاصيل مخدرات → memo",
     "1- حشييش 20 قرام 2- بدورية ميدانية 3- انكر 4- لا",
     {"memo"},
     ["مخدر", "حشيش"],
     []),
    ("T5 طلب مذكرة اسقاط حضانة (NEW topic, must NOT be drug memo)",
     "اكتب مذكرة اسقاط حضانه",
     {"memo", "memo_ask_details", "memo_ask_topic"},
     ["حضانة", "حضان", "طفل"],
     ["حشيش", "مخدر", "المادة (39", "تعاطي"]),
    ("T6 كم مبدأ قضائي (meta real)",
     "كم مبدأ قضائي عندك ؟",
     {"meta_info"},
     ["663", "مبدأ"],
     []),
    ("T7 كم عدد التشريعات (meta real — NOT identity card)",
     "كم عدد التشريعات ؟",
     {"meta_info"},
     ["48,325", "تشريع"],
     ["ماذا أقدر أسوي", "استشارات قانونية مُستشهدة"]),
    ("T8 كم يبلغ راتب موظف (legal content, NOT meta/identity)",
     "كم يبلغ اجمالي راتب موظف بدرجة سابعة في المجلس الوطني للتخطيط",
     {"general", "legal_answer", "answer", "compose", "ready"},
     [],
     ["ماذا أقدر أسوي", "أنا ميزان", "مستشارك القانوني القطري الذكي"]),
    ("T9 ماتعرف تجاوب (complaint → casual)",
     "ماتعرف تجاوب ؟",
     {"casual"},
     [],
     []),
]


def run_turn(q: str) -> dict:
    """Stream and collect the SSE response into {route, text}."""
    r = requests.post(
        BASE_URL,
        json={
            "query":      q,
            "session_id": SID,
            "history":    [],
        },
        stream=True,
        timeout=180,
    )
    text_chunks: list[str] = []
    route = ""
    for raw in r.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        payload = raw[5:].strip()
        if not payload:
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if obj.get("type") == "chunk" and obj.get("content"):
            text_chunks.append(obj["content"])
        elif obj.get("type") == "done":
            route = obj.get("route") or obj.get("meta", {}).get("route", "")
    return {"route": route, "text": "".join(text_chunks)}


def main() -> int:
    passed = 0
    failed = 0
    print(f"Session: {SID}\n")
    for label, q, exp_routes, exp_any, exp_not in TURNS:
        res = run_turn(q)
        rt = res["route"]
        tx = res["text"]
        route_ok = rt in exp_routes or any(e in (rt or "") for e in exp_routes)
        any_ok = (not exp_any) or any(kw in tx for kw in exp_any)
        none_ok = not any(kw in tx for kw in exp_not)
        ok = route_ok and any_ok and none_ok
        mark = "[PASS]" if ok else "[FAIL]"
        if ok:
            passed += 1
        else:
            failed += 1
        safe_label = label.encode("ascii", "backslashreplace").decode("ascii")
        print(f"{mark} {safe_label}")
        print(f"   route={rt!r}  len={len(tx)}  route_ok={route_ok} any_ok={any_ok} none_ok={none_ok}")
        if not ok:
            print(f"   expected routes: {exp_routes}")
            if exp_any:
                safe_any = [s.encode('ascii','backslashreplace').decode('ascii') for s in exp_any]
                print(f"   expected any of: {safe_any}")
            if exp_not:
                safe_not = [s.encode('ascii','backslashreplace').decode('ascii') for s in exp_not]
                print(f"   must not contain: {safe_not}")
            safe_prev = tx[:300].encode('ascii','backslashreplace').decode('ascii')
            print(f"   preview: {safe_prev}")
        print()
    print(f"=== {passed}/{len(TURNS)} passed ({failed} failed) ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
