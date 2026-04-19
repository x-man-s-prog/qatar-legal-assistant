# -*- coding: utf-8 -*-
"""Test Prompt 21 — Dynamic Knowledge Base"""
import requests
import json
import re
import time

API = "http://localhost:80/api/v1/query/"
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394",
}

QUESTIONS = [
    ("Q1", "صيغ لي مذكرة — واحد ضربني ودافعت عن نفسي — عندي تقرير طبي وشاهد"),
    ("Q2", "صيغ لي لائحة فصل تعسفي — 12 سنة — راتب 20,000 — بدون إنذار"),
    ("Q3", "صيغ لي مذكرة تشهير إلكتروني — نشر كلام كاذب على تويتر"),
    ("Q4", "صيغ لي مذكرة شيك بدون رصيد — الشيك ضمان"),
    ("Q5", "الكفيل طفشني بعد 8 سنين وش أسوي"),
    ("Q6", "حرمتي تبي خلع وأنا مب موافق"),
    ("Q7", "واحد ناصبني بـ 200 ألف"),
    ("Q8", "صيغ لي مذكرة قتل خطأ طبيب — العملية تمت بالبروتوكول"),
    ("Q9", "شخص زوّر توكيل وباع أرضي"),
    ("Q10", "واحد سوى حساب وهمي باسمي على الانستقرام"),
    ("Q11", "شريكي بالشركة ياخذ فلوس بدون علمي — أبي مذكرة"),
    ("Q12", "ولدي انضرب بالمدرسة وأبي أشتكي"),
]


def count_articles(text):
    patterns = [
        r"المادة\s*\(?\d+\)?",
        r"م\.\d+",
        r"مادة\s*\d+",
    ]
    found = set()
    for p in patterns:
        for m in re.finditer(p, text):
            found.add(m.group())
    return len(found)


def count_rulings(text):
    patterns = [
        r"محكمة التمييز",
        r"طعن رقم",
        r"الطعن رقم",
        r"حكم محكمة",
    ]
    count = 0
    for p in patterns:
        count += len(re.findall(p, text))
    return count


def has_db_content(text):
    """Check if text contains rich content that was likely pulled from DB."""
    indicators = [
        "يعاقب", "الحبس", "الغرامة", "لا تجاوز", "لا تقل",
        "قانون العقوبات", "قانون العمل", "قانون الأسرة",
        "رقم 11 لسنة", "رقم 14 لسنة", "رقم 22 لسنة",
    ]
    score = sum(1 for ind in indicators if ind in text)
    return score >= 2


results = []
for qid, question in QUESTIONS:
    sid = f"test21_{qid}"
    print(f"Testing {qid}...", end=" ", flush=True)
    try:
        r = requests.post(
            API,
            json={"query": question, "model": "openai", "session_id": sid},
            headers=HEADERS,
            timeout=120,
        )
        data = r.json()
        answer = data.get("answer", "")
        conf = data.get("confidence", 0)
        domain = data.get("domain", "")

        n_articles = count_articles(answer)
        n_rulings = count_rulings(answer)
        db_pulled = has_db_content(answer)

        results.append({
            "id": qid,
            "question": question[:50],
            "confidence": conf,
            "articles": n_articles,
            "rulings": n_rulings,
            "db_content": db_pulled,
            "domain": domain,
            "answer_len": len(answer),
        })
        print(f"OK conf={conf} arts={n_articles} rul={n_rulings} db={db_pulled}")
        time.sleep(2)
    except Exception as e:
        print(f"ERROR: {e}")
        results.append({
            "id": qid, "question": question[:50],
            "confidence": 0, "articles": 0, "rulings": 0,
            "db_content": False, "domain": "error", "answer_len": 0,
        })

# Save results
print("\n" + "=" * 70)
print(f"{'ID':<5} {'سحب DB':<8} {'مواد':<6} {'أحكام':<6} {'ثقة':<6} {'التقييم'}")
print("=" * 70)

total_pass = 0
for r in results:
    db_str = "نعم" if r["db_content"] else "لا"
    # Evaluate
    if r["articles"] >= 2 and r["db_content"]:
        grade = "ممتاز"
        total_pass += 1
    elif r["articles"] >= 1:
        grade = "جيد"
        total_pass += 1
    else:
        grade = "ضعيف"
    print(f"{r['id']:<5} {db_str:<8} {r['articles']:<6} {r['rulings']:<6} {r['confidence']:<6} {grade}")

print("=" * 70)
print(f"النتيجة: {total_pass}/12")

# Save detailed results to file
with open("scripts/test21_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("Results saved to scripts/test21_results.json")
