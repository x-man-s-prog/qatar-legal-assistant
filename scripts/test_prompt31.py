# -*- coding: utf-8 -*-
"""Test Prompt 31 — Final 40-question comprehensive test"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="p31_default"):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=120)
    return r.json(), time.time() - t0

Q = [
    # Known (8) — must be conf=100
    ("Q1", "ما عقوبة السرقة", "known"),
    ("Q2", "ما حقوقي عند الفصل التعسفي", "known"),
    ("Q3", "كيف إجراءات الطلاق", "known"),
    ("Q4", "ما عقوبة الشيك بدون رصيد", "known"),
    ("Q5", "ما حالات إنهاء العقد بدون إشعار", "known"),
    ("Q6", "ما عقوبة التحرش", "known"),
    ("Q7", "ما عقوبة السحر والشعوذة", "known"),
    ("Q8", "واحد ماخذ فلوسي وما يبي يردهم", "known"),
    # Slang (8)
    ("Q9", "الكفيل طفشني من الشغل", "slang"),
    ("Q10", "حرمتي تبي خلع", "slang"),
    ("Q11", "واحد ناصبني بمبلغ كبير", "slang"),
    ("Q12", "شيك طاير وش أسوي", "slang"),
    ("Q13", "مسكوني وودوني المخفر", "slang"),
    ("Q14", "ولدي انضرب بالمدرسة", "slang"),
    ("Q15", "الحكم ظالم أبي أستأنف", "slang"),
    ("Q16", "يبزني بصور خاصة", "slang"),
    # Drafting (5)
    ("Q17", "صيغ لي مذكرة دفاع ضرب — صياغة مخصصة — دفاع شرعي — تقرير طبي وشاهد", "draft"),
    ("Q18", "صيغ لي لائحة فصل تعسفي — صياغة مخصصة — 10 سنوات — راتب 15,000", "draft"),
    ("Q19", "صيغ لي مذكرة شيك بدون رصيد — صياغة مخصصة — الشيك ضمان", "draft"),
    ("Q20", "صيغ لي مذكرة طعن بالتمييز — صياغة مخصصة — قصور في التسبيب", "draft"),
    ("Q21", "صيغ لي مذكرة دفاع مخدرات — صياغة مخصصة — تفتيش بلا إذن", "draft"),
    # Cross-law (4)
    ("Q22", "واحد ضربني وسرق جوالي وهددني", "cross"),
    ("Q23", "الشركة فصلتني وما عطتني راتب 3 شهور ولا نهاية خدمة", "cross"),
    ("Q24", "شريكي يختلس من الشركة ويزوّر الدفاتر", "cross"),
    ("Q25", "صار لي حادث مرور ومات الشخص الثاني", "cross"),
    # Conversation (3) — same session
    ("Q26", "ما عقوبة الضرب", "conv"),
    ("Q27", "وإذا كان دفاع عن النفس", "conv"),
    ("Q28", "صيغ لي مذكرة", "conv"),
    # Edge cases (4)
    ("Q29", "السلام عليكم", "greet"),
    ("Q30", "وش المهام الي تقدر تسويها", "greet"),
    ("Q31", "كيف أطبخ كبسة", "edge"),
    ("Q32", "شكراً جزيلاً", "greet"),
    # Rare (5)
    ("Q33", "هل يحق لي رفض التفتيش", "rare"),
    ("Q34", "كم مدة الحبس الاحتياطي", "rare"),
    ("Q35", "ما الفرق بين الجنحة والجناية", "rare"),
    ("Q36", "هل يحق للأجنبي تملك عقار في قطر", "rare"),
    ("Q37", "ما عقوبة البلاغ الكاذب", "rare"),
    # Complex scenarios (3)
    ("Q38", "خويي عطاني شيك وطلع طاير وأنا قدمته للبنك", "complex"),
    ("Q39", "حرمتي سافرت بالعيال لبلدها وما ترجع", "complex"),
    ("Q40", "زوجي يضربني ويهددني ومانع عيالي يروحون المدرسة", "complex"),
]

results = []
cats = {"known": 0, "slang": 0, "draft": 0, "cross": 0, "greet": 0, "rare": 0, "conv": 0, "edge": 0, "complex": 0}
cats_total = {"known": 0, "slang": 0, "draft": 0, "cross": 0, "greet": 0, "rare": 0, "conv": 0, "edge": 0, "complex": 0}
total_conf = 0; total_time = 0; known_c = 0; prin_c = 0
CONV_SID = "p31_conv_test"

for qid, q, cat in Q:
    sid = CONV_SID if cat == "conv" else f"p31_{qid}"
    d, t = ask(q, sid=sid)
    a = d.get("answer", "")
    conf = d.get("confidence", 0)
    is_known = d.get("from_known_answer", False)
    n_arts = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+", a))
    has_prin = any(p in a for p in ["المقرر", "المستقر", "محكمة التمييز على أن", "استقرت"])
    total_conf += conf; total_time += t
    if is_known: known_c += 1
    if has_prin and cat == "draft": prin_c += 1
    cats_total[cat] = cats_total.get(cat, 0) + 1

    # Grade per category
    grade = "pass"
    if cat == "known":
        grade = "pass" if (is_known or conf == 100) else "fail"
    elif cat == "slang":
        grade = "pass" if conf > 15 and len(a) > 80 else "fail"
    elif cat == "draft":
        grade = "pass" if conf >= 80 and len(a) > 200 else "fail"
    elif cat == "cross":
        grade = "pass" if conf > 15 and len(a) > 100 else "fail"
    elif cat == "greet":
        grade = "pass" if conf >= 90 else "fail"
    elif cat == "edge":
        grade = "pass"  # any response OK
    elif cat == "rare":
        grade = "pass" if conf > 15 and len(a) > 80 else "fail"
    elif cat == "conv":
        grade = "pass" if len(a) > 50 else "fail"
    elif cat == "complex":
        grade = "pass" if conf > 15 and len(a) > 80 else "fail"

    if grade == "pass": cats[cat] = cats.get(cat, 0) + 1
    results.append({"id": qid, "conf": conf, "time": round(t,1), "known": is_known, "arts": n_arts, "prin": has_prin, "grade": grade, "cat": cat})
    sym = "OK" if grade == "pass" else "FAIL"
    extra = " known" if is_known else ""
    extra += " PRIN" if has_prin else ""
    print(f"  {sym} {qid} conf={conf:3d} {t:5.1f}s arts={n_arts}{extra} [{cat}]")
    time.sleep(2)

with open("scripts/test31_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] == "pass")
avg_conf = total_conf / len(results)
avg_time = total_time / len(results)
slowest = sorted(results, key=lambda x: x["time"], reverse=True)[:3]
weakest = sorted([r for r in results if r["conf"] > 0 and r["cat"] not in ("greet","edge")], key=lambda x: x["conf"])[:3]

print(f"\n{'='*60}")
print(f"FINAL RESULT: {passed}/40")
print(f"{'='*60}")
print(f"Known answers: {cats.get('known',0)}/{cats_total.get('known',0)}")
print(f"Slang understood: {cats.get('slang',0)}/{cats_total.get('slang',0)}")
print(f"Drafts pass: {cats.get('draft',0)}/{cats_total.get('draft',0)}")
print(f"Drafts with principles: {prin_c}/{cats_total.get('draft',0)}")
print(f"Cross-law: {cats.get('cross',0)}/{cats_total.get('cross',0)}")
print(f"Conversation: {cats.get('conv',0)}/{cats_total.get('conv',0)}")
print(f"Greetings: {cats.get('greet',0)}/{cats_total.get('greet',0)}")
print(f"Rare (conf>15): {cats.get('rare',0)}/{cats_total.get('rare',0)}")
print(f"Complex: {cats.get('complex',0)}/{cats_total.get('complex',0)}")
print(f"Avg confidence: {avg_conf:.0f}%")
print(f"Avg time: {avg_time:.1f}s")
for s in slowest: print(f"  Slowest: {s['id']} = {s['time']}s")
for w in weakest: print(f"  Weakest: {w['id']} conf={w['conf']}")
print(f"{'='*60}")
