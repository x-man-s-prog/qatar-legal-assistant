# -*- coding: utf-8 -*-
"""Test Prompt 34 — Lawyer thinking test"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="p34"):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=120)
    return r.json(), time.time() - t0

Q = [
    # Position assessment (strong/weak)
    ("Q1", "واحد ضربني بالسوق وعندي فيديو من كاميرا المحل وتقرير طبي — وش فرصي"),
    ("Q2", "واحد ضربني بس ما عندي أي دليل ولا شهود — وش أسوي"),
    ("Q3", "الشركة فصلتني بعد 15 سنة وعندي العقد والإنذارات — هل أكسب"),
    ("Q4", "واحد يبتزني بصور خاصة — ما أبي أحد يدري — فيه حل بدون شرطة"),
    ("Q5", "شريكي بالشركة يسرق فلوس — بس لو شكيته بخسر الشركة كلها"),
    # Anticipate opponent
    ("Q6", "أنا متهم بضرب — بس أنا اللي انضربت أول والطرف الثاني عنده واسطة"),
    ("Q7", "أبي أفسخ عقد إيجار — بس المؤجر يقول فيه شرط جزائي 100 ألف"),
    # Strategic thinking
    ("Q8", "زوجتي تبي طلاق ومعاها تقارير ضرب — لكن أنا ما ضربتها — التقارير مزورة"),
    ("Q9", "شخص نشر عني كلام كاذب على تويتر — بس الكلام اللي نشره جزء منه صحيح"),
    ("Q10", "عندي قضية وأبي أعرف — أرفع دعوى ولا أتصالح"),
    # Evidence evaluation
    ("Q11", "عندي رسائل واتساب تثبت الاتفاق — هل تنفع كدليل"),
    ("Q12", "عندي شاهد واحد بس هو قريبي — يُقبل"),
    # Urgent practical
    ("Q13", "حصل لي حادث الحين — وش أول شي أسويه قانونياً"),
    ("Q14", "اكتشفت إن موظف يسرق من الشركة — وش أسوي قبل ما يهرب"),
    ("Q15", "استلمت إنذار إخلاء من المؤجر — عندي أسبوع بس"),
]

LAWYER_MARKERS = {
    "assessment": ["موقف", "قوي", "ضعيف", "فرص", "متوسط", "صعب", "نقاط قوة", "نقاط ضعف"],
    "honesty": ["بصراحة", "صعب", "لكن", "رغم", "ومع ذلك", "واقعي"],
    "opponent": ["الخصم", "الطرف الآخر", "سيدّعي", "سيحتج", "الدفوع", "المدعى عليه", "المدعي"],
    "practical": ["خطوة", "أولاً", "ثانياً", "توجه", "قدّم", "اتصل", "فوراً", "عاجل"],
    "evidence": ["دليل", "إثبات", "قاطع", "قوي", "مقبول", "ضعيف", "يكفي", "تعزيز"],
}

results = []
total_lawyer_score = 0

for qid, q in Q:
    print(f"  {qid}...", end=" ", flush=True)
    d, t = ask(q, sid=f"p34_{qid}")
    a = d.get("answer", "")
    conf = d.get("confidence", 0)

    # Score lawyer-like thinking
    score = 0; traits = []
    for trait, markers in LAWYER_MARKERS.items():
        if any(m in a for m in markers):
            score += 1; traits.append(trait)
    total_lawyer_score += score

    grade = "lawyer" if score >= 3 else ("good" if score >= 2 else ("ok" if score >= 1 else "robotic"))
    results.append({"id": qid, "conf": conf, "time": round(t,1), "score": score, "traits": traits, "grade": grade, "len": len(a)})

    sym = {"lawyer": "LAWYER", "good": "GOOD", "ok": "OK", "robotic": "ROBOT"}[grade]
    print(f"{sym} conf={conf} {t:.1f}s score={score}/5 traits={traits}")
    time.sleep(2)

with open("scripts/test34_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] in ("lawyer", "good"))
avg_score = total_lawyer_score / len(results)

print(f"\n{'='*60}")
print(f"RESULT: {passed}/15 lawyer-like")
print(f"Avg lawyer score: {avg_score:.1f}/5")
print(f"Grades: lawyer={sum(1 for r in results if r['grade']=='lawyer')} good={sum(1 for r in results if r['grade']=='good')} ok={sum(1 for r in results if r['grade']=='ok')} robotic={sum(1 for r in results if r['grade']=='robotic')}")
print(f"{'='*60}")
