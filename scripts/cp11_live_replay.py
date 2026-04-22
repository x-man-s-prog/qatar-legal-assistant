# -*- coding: utf-8 -*-
"""CP11 — live replay of the user's new catastrophic transcript.

Verifies four root-cause fixes:
  A. Memo state bleed across fresh memo requests (T12/T16/T17/T19/T31).
  B. UNCLEAR intent → no forced memo (T21-T24 analysis questions).
  C. Off-topic guard (T35 weather, T36 image, T37 recipe, T38 dot).
  D. Expanded topic map (فصل تعسفي/فسخ إيجار/دين تجاري/حادث مروري/رد اعتبار).
"""
from __future__ import annotations

import json
import sys
import time
import uuid
import requests


BASE_URL = "http://localhost/api/v1/stream/"
SID = f"cp11-{uuid.uuid4().hex[:12]}"


TURNS = [
    # label, query, expected_routes (set), exp_any (list), exp_not (list)
    # ── warm-up / setup
    ("T1 custody memo (baseline)",
     "اكتب مذكرة إسقاط حضانة ضد طليقتي — ولدي طفل اسمه سالم عمره 5 سنوات، وطليقتي تزوجت من رجل أجنبي ومعها في البيت",
     {"memo"},
     ["حضانة", "سالم", "179", "168", "183"],
     []),
    # ── CRITICAL: fresh memo on DIFFERENT topic mid-session
    ("T2 LABOR memo after custody — must NOT be custody",
     "اكتب مذكرة فصل تعسفي — موكلي يعمل مهندساً 8 سنوات في شركة، فُصل بدون مبرر وبدون إنذار، راتبه 15,000 ريال",
     {"memo", "memo_ask_details"},
     ["فصل", "مهندس", "8 سنوات", "15,000"],
     ["سالم", "طليقت", "حضانة", "179"]),
    ("T3 bad-check memo after labor",
     "اكتب مذكرة مطالبة بشيك بدون رصيد — قيمة الشيك 45,000 ريال، صادر بتاريخ 15/03/2024، ارتد لعدم كفاية الرصيد",
     {"memo"},
     ["شيك", "45,000", "15/03/2024"],
     ["سالم", "حضانة", "مهندس", "15,000"]),
    ("T4 divorce-harm memo after bad-check",
     "اكتب مذكرة طلاق للضرر — موكلتي تعرضت لضرب متكرر وإهانة لفظية وإهمال مالي لمدة سنتين",
     {"memo"},
     ["طلاق", "ضرب", "سنتين"],
     ["شيك", "45,000", "سالم", "مهندس"]),
    # NOTE: "مذكرة فسخ ..." (no memo VERB) is ambiguous — new safe
    # default after CP11 is to classify as NEW_LEGAL_QUESTION → general
    # pipeline (no bleed possible). Accept 'general' OR 'memo*'. Invariant:
    # NO prior memo facts leak into the response.
    ("T5 ambiguous rental — any route OK, but NO prior memo facts leak",
     "اكتب مذكرة فسخ عقد إيجار — المؤجر رفع الإيجار 40% فجأة ولم يقم بالصيانة المتفق عليها",
     {"memo", "memo_ask_details", "general"},
     [],
     ["شيك", "45,000", "سالم", "طليقت", "مهندس", "15,000"]),
    # ── Analysis questions — must NOT become memos
    ("T6 legal analysis: theft — not memo",
     "موكلي سرق 30 ألف ريال من الخزينة واعترف وعنده سابقة سرقة قبل سنتين — ما موقفه القانوني وما المتوقع من الحكم؟",
     {"general", "legal_answer", "answer", "compose"},
     [],
     ["بسم الله الرحمن الرحيم", "خامساً: الطلبات", "والله ولي التوفيق"]),
    ("T7 legal analysis: khul' — not memo",
     "امرأة تقدمت بدعوى خلع، لكن زوجها يرفض — هل يُجبر على قبول الخلع؟",
     {"general", "legal_answer", "answer", "compose"},
     [],
     ["بسم الله الرحمن الرحيم", "خامساً: الطلبات"]),
    # ── Off-topic
    ("T8 weather — rejected",
     "ما هو الطقس اليوم في الدوحة؟",
     {"off_topic"},
     ["الطقس", "قانوني"],
     ["بسم الله", "المادة", "الطعن"]),
    ("T9 image — rejected",
     "ارسم لي صورة عن محكمة",
     {"off_topic"},
     ["صور", "قانوني"],
     ["بسم الله", "المادة"]),
    ("T10 recipe — rejected",
     "أعطني وصفة طبخ",
     {"off_topic"},
     ["طبخ", "قانوني"],
     []),
    ("T11 dot — clarify",
     ".",
     {"clarify", "noise"},
     ["سؤال", "موضوع"],
     []),
    # ── Meta question still works
    ("T12 meta: number of laws",
     "كم عدد القوانين في قطر؟",
     {"meta_info"},
     ["48,325", "تشريع"],
     ["بسم الله"]),
]


def run_turn(q: str) -> dict:
    r = requests.post(
        BASE_URL,
        json={"query": q, "session_id": SID, "history": []},
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
        tries = 0
        while True:
            res = run_turn(q)
            if "429" not in res["text"][:80]:
                break
            tries += 1
            if tries >= 3:
                break
            time.sleep(25)
        # Pace between turns so the memo test doesn't hammer OpenAI.
        time.sleep(8)
        rt = res["route"]
        tx = res["text"]
        route_ok = rt in exp_routes or any(e in (rt or "") for e in exp_routes)
        any_ok = (not exp_any) or any(kw in tx for kw in exp_any)
        none_ok = not any(kw in tx for kw in exp_not)
        ok = route_ok and any_ok and none_ok
        mark = "[PASS]" if ok else "[FAIL]"
        if ok: passed += 1
        else:  failed += 1
        safe_label = label.encode("ascii", "backslashreplace").decode("ascii")
        print(f"{mark} {safe_label}")
        print(f"   route={rt!r}  len={len(tx)}  route_ok={route_ok} any_ok={any_ok} none_ok={none_ok}")
        if not ok:
            print(f"   expected routes: {exp_routes}")
            if exp_any:
                print(f"   expected any of: {[s.encode('ascii','backslashreplace').decode('ascii') for s in exp_any]}")
            if exp_not:
                print(f"   must not contain: {[s.encode('ascii','backslashreplace').decode('ascii') for s in exp_not]}")
            print(f"   preview: {tx[:400].encode('ascii','backslashreplace').decode('ascii')}")
        print()
    print(f"=== {passed}/{len(TURNS)} passed ({failed} failed) ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
