# -*- coding: utf-8 -*-
"""Test Prompt 26 — Pattern fix + style guide + suggestions test"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

QUESTIONS = [
    # 4 previously weak (must be known_answer now)
    ("Q1", "ما هي حالات إنهاء العقد بدون إشعار", ["61", "بدون إشعار"]),
    ("Q2", "متى يسقط الحق في رفع الدعوى الجنائية", ["تقادم", "10 سنوات", "3 سنوات"]),
    ("Q3", "ما هو الشرط الجزائي في العقود", ["265", "شرط جزائي", "تعويض"]),
    ("Q4", "واحد ماخذ فلوسي وما يبي يردهم", ["أمر أداء", "دعوى", "354"]),
    # New known_answers
    ("Q5", "ما عقوبة التزوير", ["238", "240", "تزوير"]),
    ("Q6", "ما عقوبة الرشوة", ["140", "رشوة"]),
    ("Q7", "ما عقوبة خيانة الأمانة", ["355", "خيانة"]),
    ("Q8", "ما حكم الإفلاس في قطر", ["إفلاس", "606"]),
    ("Q9", "كيف أسجل علامة تجارية", ["علامة", "تسجيل"]),
    ("Q10", "ما هي إصابة العمل وحقوقي فيها", ["إصابة", "109"]),
    # Drafting with style guide
    ("Q11", "صيغ لي مذكرة دفاع في قضية سرقة — صياغة مخصصة — ما عندي سوابق", ["334", "سرقة"]),
    ("Q12", "صيغ لي لائحة دعوى تعويض — صياغة مخصصة — حادث سيارة — كسر بالساق", ["199", "200", "تعويض"]),
    ("Q13", "صيغ لي مذكرة دفاع مخدرات — صياغة مخصصة — التفتيش بدون إذن", ["تفتيش", "مخدرات"]),
    ("Q14", "صيغ لي مذكرة طعن بالتمييز — صياغة مخصصة — قصور في التسبيب", ["277", "تمييز", "قصور"]),
    # Compound/slang
    ("Q15", "واحد ضربني وسرق جوالي وش أسوي", ["ضرب", "سرق"]),
    ("Q16", "الشركة فصلتني وما عطتني راتب 3 شهور ولا نهاية خدمة", ["فصل", "راتب"]),
    # Suggestions check
    ("Q17", "ما حقوقي عند الفصل التعسفي", ["فصل", "تعسفي"]),
    ("Q18", "ما عقوبة الضرب", ["304", "308"]),
    # Greetings
    ("Q19", "السلام عليكم", []),
    ("Q20", "شكراً جزيلاً على المساعدة", []),
]

results = []
for qid, q, expected in QUESTIONS:
    print(f"{qid}...", end=" ", flush=True)
    try:
        r = requests.post(API, json={"query": q, "model": "openai", "session_id": f"p26_{qid}"}, headers=H, timeout=120)
        d = r.json()
        a = d.get("answer", "")
        conf = d.get("confidence", 0)
        is_known = d.get("from_known_answer", False)
        domain = d.get("domain", "")
        sources = len(d.get("sources", []))

        found = [w for w in expected if w in a]
        has_suggest = "تريد أيضاً" in a or "هل تريد" in a or "💡" in a
        has_style = any(p in a for p in ["المستقر عليه", "الثابت بيقين", "ولما كان ذلك", "وترتيباً على", "مردود عليه", "ومن ثم فإن", "بناءً على ما تقدم", "يلتمس الدفاع"])

        grade = "pass"
        if qid in ("Q19", "Q20"):  # greetings
            grade = "pass" if (sources == 0 and conf >= 90) else "warn"
        elif is_known or conf == 100:
            grade = "pass"
        elif len(found) >= 1 and conf >= 20 and len(a) > 80:
            grade = "pass"
        else:
            grade = "fail"

        results.append({
            "id": qid, "question": q[:50], "conf": conf, "known": is_known,
            "found": f"{len(found)}/{len(expected)}", "suggest": has_suggest,
            "style": has_style, "grade": grade, "domain": domain, "sources": sources,
        })
        sym = {"pass": "OK", "fail": "FAIL", "warn": "WARN"}[grade]
        extra = f" known={is_known}" if is_known else ""
        extra += f" suggest" if has_suggest else ""
        extra += f" STYLE" if has_style else ""
        print(f"{sym} conf={conf} found={len(found)}/{len(expected)}{extra}")
        time.sleep(2)
    except Exception as e:
        print(f"ERROR: {e}")
        results.append({"id": qid, "question": q[:50], "grade": "fail", "error": str(e)})

with open("scripts/test26_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] in ("pass", "warn"))
known_count = sum(1 for r in results if r.get("known"))
suggest_count = sum(1 for r in results if r.get("suggest"))
style_count = sum(1 for r in results if r.get("style"))

print(f"\n{'='*60}")
print(f"RESULT: {passed}/20")
print(f"Known answers matched: {known_count}")
print(f"Suggestions shown: {suggest_count}")
print(f"Style phrases used: {style_count}")
print(f"{'='*60}")
