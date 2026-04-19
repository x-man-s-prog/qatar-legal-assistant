# -*- coding: utf-8 -*-
"""Test Prompt 30 — Principles integration test"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="default"):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=120)
    return r.json(), time.time() - t0

QUESTIONS = [
    # Drafting with principles
    ("Q1", "صيغ لي مذكرة دفاع ضرب — صياغة مخصصة — دفاع شرعي — عندي تقرير وشاهد",
     ["دفاع شرعي", "304", "308", "49"], ["المقرر", "المستقر", "محكمة التمييز"]),
    ("Q2", "صيغ لي مذكرة دفاع مخدرات — صياغة مخصصة — التفتيش بدون إذن",
     ["تفتيش", "بطلان", "إذن"], ["المقرر", "بطلان", "التمييز"]),
    ("Q3", "صيغ لي مذكرة طعن بالتمييز — صياغة مخصصة — قصور في التسبيب",
     ["تمييز", "تسبيب", "277"], ["قصور", "التسبيب", "التمييز"]),
    ("Q4", "صيغ لي لائحة فصل تعسفي — صياغة مخصصة — 10 سنوات — بدون إنذار",
     ["فصل", "تعسفي", "61", "62"], ["المقرر", "العمل"]),
    ("Q5", "صيغ لي مذكرة شيك بدون رصيد — صياغة مخصصة — الشيك ضمان",
     ["357", "شيك", "ضمان"], ["شيك", "وفاء", "التمييز"]),
    # Cross-law analysis
    ("Q6", "واحد ضربني وسرق جوالي",
     ["ضرب", "سرق"], []),
    ("Q7", "شريكي يختلس من الشركة",
     ["اختلاس", "شرك", "خيانة"], []),
    ("Q8", "صار لي حادث مرور ومات الشخص الثاني",
     ["حادث", "قتل خطأ", "تعويض"], []),
    # Known answers (should be 100%)
    ("Q9", "ما عقوبة التزوير", ["تزوير", "238"], []),
    ("Q10", "ما حالات إنهاء العقد بدون إشعار", ["61", "بدون إشعار"], []),
]

results = []
principles_found = 0; cross_law = 0

for qid, q, expected_words, principle_markers in QUESTIONS:
    print(f"{qid}...", end=" ", flush=True)
    d, t = ask(q, sid=f"p30_{qid}")
    a = d.get("answer", "")
    conf = d.get("confidence", 0)
    is_known = d.get("from_known_answer", False)
    n_arts = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+", a))
    n_prin = sum(1 for pm in principle_markers if pm in a)
    found_words = [w for w in expected_words if w in a]

    # Check multi-law analysis
    law_refs = set()
    for law_name in ["العقوبات", "المدني", "العمل", "الأسرة", "التجارة", "الإجراءات", "المرافعات", "المرور"]:
        if law_name in a:
            law_refs.add(law_name)
    multi_law = len(law_refs) >= 2

    if n_prin > 0: principles_found += 1
    if multi_law and qid in ("Q6","Q7","Q8"): cross_law += 1

    grade = "pass" if (len(found_words) >= 1 and len(a) > 100) else "fail"
    results.append({"id": qid, "conf": conf, "time": round(t,1), "arts": n_arts,
                    "principles": n_prin, "multi_law": multi_law, "grade": grade,
                    "known": is_known, "found": f"{len(found_words)}/{len(expected_words)}"})
    sym = "OK" if grade == "pass" else "FAIL"
    extra = f" prin={n_prin}" if n_prin > 0 else ""
    extra += " MULTI-LAW" if multi_law else ""
    extra += " known" if is_known else ""
    print(f"{sym} conf={conf} {t:.1f}s arts={n_arts}{extra} found={len(found_words)}/{len(expected_words)}")
    time.sleep(2)

with open("scripts/test30_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] == "pass")
avg_conf = sum(r["conf"] for r in results) / len(results)
avg_time = sum(r["time"] for r in results) / len(results)

print(f"\n{'='*60}")
print(f"RESULT: {passed}/10")
print(f"Memos with principles: {principles_found}/5")
print(f"Multi-law analysis: {cross_law}/3")
print(f"Avg confidence: {avg_conf:.0f}%")
print(f"Avg time: {avg_time:.1f}s")
print(f"{'='*60}")
