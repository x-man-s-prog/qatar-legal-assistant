# -*- coding: utf-8 -*-
"""Test Prompt 25 — Post-merge comprehensive test (20 questions)"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

QUESTIONS = [
    # الأسئلة الـ 4 الضعيفة (كانت conf<25)
    ("Q1", "ما هي حالات إنهاء العقد بدون إشعار؟", "known", ["المادة 61", "61"]),
    ("Q2", "متى يسقط الحق في رفع الدعوى الجنائية؟", "known", ["10 سنوات", "3 سنوات", "تقادم"]),
    ("Q3", "ما هو الشرط الجزائي في العقود؟", "known", ["265", "تعويض", "اتفاقي"]),
    ("Q4", "واحد ماخذ فلوسي وما يبي يردهم", "known", ["أمر أداء", "دعوى", "354"]),
    # إجابات جاهزة جديدة
    ("Q5", "ما عقوبة التزوير؟", "known", ["238", "240", "تزوير"]),
    ("Q6", "ما عقوبة الرشوة؟", "known", ["140", "رشوة"]),
    ("Q7", "ما عقوبة خيانة الأمانة؟", "known", ["355", "خيانة"]),
    ("Q8", "ما حكم الإفلاس في قطر؟", "known", ["إفلاس", "تصفية"]),
    ("Q9", "كيف أسجل علامة تجارية؟", "known", ["علامة", "تجارية", "تسجيل"]),
    ("Q10", "ما هي إصابة العمل وحقوقي فيها؟", "known", ["109", "إصابة", "علاج"]),
    # صياغة بالقوالب المحسّنة
    ("Q11", "صيغ لي مذكرة دفاع في قضية ضرب — المتهم دافع عن نفسه", "draft", ["304", "308", "49", "دفاع شرعي"]),
    ("Q12", "صيغ لي لائحة فصل تعسفي — 10 سنوات خدمة — بدون إنذار", "draft", ["61", "62", "54", "تعسفي"]),
    ("Q13", "صيغ لي مذكرة شيك بدون رصيد — الشيك كان ضمان", "draft", ["357", "شيك", "ضمان"]),
    ("Q14", "صيغ لي مذكرة طعن بالتمييز — الحكم ما رد على دفوعي", "draft", ["277", "تمييز", "قصور"]),
    # عامية + مواضيع جديدة
    ("Q15", "الكفيل طفشني بعد 8 سنين وش أسوي", "rag", ["فصل", "تعسفي", "مكافأة", "تعويض"]),
    ("Q16", "واحد ناصبني بعملات رقمية مزورة", "rag", ["354", "نصب", "احتيال"]),
    ("Q17", "مقاول ما خلص شغلي وهرب", "rag", ["مقاولة", "عقد", "تعويض"]),
    ("Q18", "أبي أفك رهن عقاري", "rag", ["رهن", "فك"]),
    ("Q19", "وش حكم التسوية الودية في قطر؟", "rag", ["صلح", "تسوية"]),
    ("Q20", "حرمتي تبي خلع وأنا مب موافق وعندها تقارير ضرب", "rag", ["109", "خلع", "طلاق"]),
]

results = []
for qid, question, qtype, expected_words in QUESTIONS:
    print(f"{qid}...", end=" ", flush=True)
    try:
        r = requests.post(API, json={"query": question, "model": "openai", "session_id": f"p25_{qid}"}, headers=H, timeout=120)
        d = r.json()
        answer = d.get("answer", "")
        conf = d.get("confidence", 0)
        domain = d.get("domain", "")
        is_known = d.get("from_known_answer", False)

        # Check expected words
        found_words = [w for w in expected_words if w in answer]
        n_articles = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+|مادة\s*\d+", answer))
        has_blanks = "[رقم" in answer or "[اسم" in answer or "[___]" in answer

        grade = "pass" if (len(found_words) >= 1 and conf >= 20 and len(answer) > 80) else "fail"
        if qtype == "known" and (is_known or conf == 100):
            grade = "pass"
        if has_blanks and qtype == "draft":
            grade = "warn"

        results.append({
            "id": qid, "question": question[:50], "type": qtype,
            "confidence": conf, "domain": domain, "is_known": is_known,
            "answer_len": len(answer), "found_words": found_words,
            "n_articles": n_articles, "has_blanks": has_blanks, "grade": grade,
        })
        symbol = {"pass": "OK", "fail": "FAIL", "warn": "WARN"}[grade]
        print(f"{symbol} conf={conf} arts={n_articles} known={is_known} found={len(found_words)}/{len(expected_words)}")
        time.sleep(2)
    except Exception as e:
        print(f"ERROR: {e}")
        results.append({"id": qid, "question": question[:50], "grade": "fail", "error": str(e)})

# Summary
with open("scripts/test25_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] in ("pass", "warn"))
print(f"\n{'='*60}")
print(f"RESULT: {passed}/20")
print(f"{'='*60}")
for r in results:
    symbol = {"pass": "✓", "fail": "✗", "warn": "⚠"}[r["grade"]]
    print(f"  {symbol} {r['id']}: conf={r.get('confidence','?')} known={r.get('is_known','')} arts={r.get('n_articles',0)} — {r['question']}")
