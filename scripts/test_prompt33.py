# -*- coding: utf-8 -*-
"""Test Prompt 33 — Stress test 30 questions"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="p33"):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=120)
    return r.json(), time.time() - t0

CONV_SID = "p33_conv"
Q = [
    # Practical (5)
    ("Q1", "أبي أرفع قضية عمالية — وين أروح أول شي", "practical"),
    ("Q2", "كم تكلفة القضية المدنية تقريباً", "practical"),
    ("Q3", "واحد ماخذ مني فلوس بإيصال — وش أسرع طريقة أرجعهم", "practical"),
    ("Q4", "كم تاخذ قضية الطلاق عادة", "practical"),
    ("Q5", "هل أحتاج محامي لقضية إيجار", "practical"),
    # Gaps filled (5)
    ("Q6", "كيف أنفّذ حكم صادر لصالحي", "gap"),
    ("Q7", "كم مدة الحبس الاحتياطي", "gap"),
    ("Q8", "ما هو أمر الأداء وكيف أستخدمه", "gap"),
    ("Q9", "أي محكمة أروح لها", "gap"),
    ("Q10", "هل فيه وساطة قبل المحكمة", "gap"),
    # Complex contracts (5)
    ("Q11", "صيغ لي عقد امتياز تجاري فرانشايز — مطعم — 5 سنوات — إتاوة 6%", "contract"),
    ("Q12", "صيغ لي عقد توظيف مدير تنفيذي — راتب 50,000 — بند عدم منافسة", "contract"),
    ("Q13", "صيغ لي عقد مقاولة بناء فيلا — 3 مليون ريال — 18 شهر", "contract"),
    ("Q14", "صيغ لي اتفاقية تسوية ودية — نزاع شراكة", "contract"),
    ("Q15", "صيغ لي عقد سرية NDA — بين شركتين — 3 سنوات", "contract"),
    # Conversation (5)
    ("Q16", "واحد ضربني", "conv"),
    ("Q17", "عندي تقرير طبي يثبت الإصابة", "conv"),
    ("Q18", "وش أسوي الحين بالضبط — خطوة بخطوة", "conv"),
    ("Q19", "وإذا أبي تعويض مادي كم تقريباً", "conv"),
    ("Q20", "صيغ لي مذكرة بناءً على كل اللي قلته", "conv"),
    # Realistic slang (5)
    ("Q21", "أنا موظف حكومي وتم نقلي لمكان بعيد بدون سبب كانتقام", "scenario"),
    ("Q22", "صاحب المحل اللي بجنبي يشغّل موسيقى عالية لين الليل ومقدر أنام", "scenario"),
    ("Q23", "اكتشفت إن السيارة اللي شريتها عليها حادث سابق والبائع ما قال لي", "scenario"),
    ("Q24", "بنتي عمرها 14 سنة تتعرض للتنمر بالمدرسة والإدارة ما تتحرك", "scenario"),
    ("Q25", "جاري يبني بدون ترخيص ويحجب الشمس عن بيتي", "scenario"),
    # Rare (5)
    ("Q26", "هل يحق لي تصوير رجال الشرطة أثناء مخالفة مرورية", "rare"),
    ("Q27", "هل التنصت على المكالمات قانوني", "rare"),
    ("Q28", "هل الزواج العرفي معترف به في قطر", "rare"),
    ("Q29", "هل يحق للمحكمة مصادرة هاتفي كدليل", "rare"),
    ("Q30", "ما حقوق ذوي الإعاقة في بيئة العمل", "rare"),
]

results = []
cats = {}; cats_total = {}; total_conf = 0; total_time = 0; known_c = 0

for qid, q, cat in Q:
    sid = CONV_SID if cat == "conv" else f"p33_{qid}"
    print(f"  {qid}...", end=" ", flush=True)
    d, t = ask(q, sid=sid)
    a = d.get("answer", "")
    conf = d.get("confidence", 0)
    is_known = d.get("from_known_answer", False)
    n_arts = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+", a))
    has_practical = any(w in a for w in ["توجه", "أروح", "مركز", "إدارة", "محكمة", "خطوة", "أولاً", "ثانياً"])

    total_conf += conf; total_time += t
    if is_known: known_c += 1
    cats_total[cat] = cats_total.get(cat, 0) + 1

    grade = "pass"
    if cat == "gap":
        grade = "pass" if (is_known or conf >= 50) and len(a) > 80 else ("pass" if conf > 15 and len(a) > 80 else "fail")
    elif cat == "contract":
        grade = "pass" if conf >= 80 and len(a) > 200 else "fail"
    elif cat == "conv":
        grade = "pass" if len(a) > 30 else "fail"
    elif cat in ("practical", "scenario", "rare"):
        grade = "pass" if conf > 10 and len(a) > 80 else "fail"

    if grade == "pass": cats[cat] = cats.get(cat, 0) + 1
    results.append({"id": qid, "conf": conf, "time": round(t,1), "known": is_known, "arts": n_arts, "practical": has_practical, "grade": grade, "cat": cat, "len": len(a)})
    sym = "OK" if grade == "pass" else "FAIL"
    extra = " known" if is_known else ""
    extra += " PRACT" if has_practical else ""
    print(f"{sym} conf={conf:3d} {t:5.1f}s{extra} [{cat}]")
    time.sleep(2)

with open("scripts/test33_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] == "pass")
avg_conf = total_conf / len(results)
avg_time = total_time / len(results)
slowest = sorted(results, key=lambda x: x["time"], reverse=True)[:3]
weakest = sorted([r for r in results if r["conf"] > 0], key=lambda x: x["conf"])[:3]

print(f"\n{'='*60}")
print(f"RESULT: {passed}/30")
print(f"{'='*60}")
for cat_name in ["practical","gap","contract","conv","scenario","rare"]:
    print(f"  {cat_name}: {cats.get(cat_name,0)}/{cats_total.get(cat_name,0)}")
print(f"Known answers: {known_c}")
print(f"Avg confidence: {avg_conf:.0f}%")
print(f"Avg time: {avg_time:.1f}s")
for s in slowest: print(f"  Slowest: {s['id']} = {s['time']}s")
for w in weakest: print(f"  Weakest: {w['id']} conf={w['conf']}")
print(f"{'='*60}")
