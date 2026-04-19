# -*- coding: utf-8 -*-
"""Test Prompt 27 — 50-question comprehensive test"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

QUESTIONS = [
    # known_answers (10) — should be conf=100
    ("Q1", "ما عقوبة السرقة"),
    ("Q2", "ما حقوقي عند الفصل التعسفي"),
    ("Q3", "كيف إجراءات الطلاق في قطر"),
    ("Q4", "ما عقوبة حيازة المخدرات"),
    ("Q5", "ما حقوق الحضانة بعد الطلاق"),
    ("Q6", "ما عقوبة التزوير"),
    ("Q7", "ما عقوبة الرشوة"),
    ("Q8", "ما هو الشرط الجزائي"),
    ("Q9", "ما حالات إنهاء العقد بدون إشعار"),
    ("Q10", "واحد ماخذ فلوسي وما يبي يردهم"),
    # عامية (10) — should understand
    ("Q11", "الكفيل طفشني من الشغل"),
    ("Q12", "حرمتي تبي تنفصل"),
    ("Q13", "واحد ناصبني بمبلغ كبير"),
    ("Q14", "ريال هددني بالواتساب"),
    ("Q15", "شيك طاير وش أسوي"),
    ("Q16", "مسكوني وودوني المخفر"),
    ("Q17", "الحكم ظالم أبي أستأنف"),
    ("Q18", "ولدي انضرب بالمدرسة"),
    ("Q19", "صاحب البيت يبي يطلعني"),
    ("Q20", "يبزني بصور خاصة"),
    # مركّبة (5) — multi-aspect
    ("Q21", "واحد ضربني وسرق جوالي"),
    ("Q22", "الشركة فصلتني وما عطتني راتب 3 شهور ولا نهاية خدمة"),
    ("Q23", "شريكي يحول فلوس الشركة لحسابه"),
    ("Q24", "مقاول ما خلص البناء وهرب بالفلوس"),
    ("Q25", "زوجي يضربني وأبي طلاق مع حضانة العيال"),
    # صياغة (5)
    ("Q26", "صيغ لي مذكرة دفاع ضرب"),
    ("Q27", "صيغ لي لائحة فصل تعسفي"),
    ("Q28", "صيغ لي مذكرة شيك بدون رصيد"),
    ("Q29", "صيغ لي عقد إيجار شقة"),
    ("Q30", "صيغ لي عقد شراكة تجارية"),
    # أسئلة عن النظام + تحيات (4)
    ("Q31", "وش المهام الي تقدر تسويها"),
    ("Q32", "من أنت"),
    ("Q33", "السلام عليكم"),
    ("Q34", "شكراً جزيلاً"),
    # نادرة/صعبة (6)
    ("Q35", "هل يحق لي رفض التفتيش"),
    ("Q36", "ما الفرق بين الجنحة والجناية"),
    ("Q37", "كم مدة الحبس الاحتياطي"),
    ("Q38", "هل الزواج العرفي معترف به في قطر"),
    ("Q39", "ما حقوق المرأة الحامل في العمل"),
    ("Q40", "هل يحق للأجنبي تملك عقار في قطر"),
    # سيناريوهات (5)
    ("Q41", "أنا مهندس رفضت أوقع على تقارير مزورة وفصلوني"),
    ("Q42", "اشتريت سيارة وطلعت فيها عيب مخفي والبائع يرفض يرجع الفلوس"),
    ("Q43", "جاري بنى طابق إضافي يحجب الشمس عن شقتي"),
    ("Q44", "موظف سابق سرق بيانات العملاء وأسس شركة منافسة"),
    ("Q45", "والدي توفي وأخوي الكبير مسيطر على الميراث ويرفض يقسم"),
    # عامية صعبة (5)
    ("Q46", "خويي عطاني شيك وطلع طاير وأنا قدمته للبنك"),
    ("Q47", "الكفيل ما يبي يعطيني نقل والشغل عند واحد ثاني"),
    ("Q48", "حرمتي سافرت بالعيال لبلدها وما ترجع"),
    ("Q49", "مستأجر بمحلي التجاري ما يدفع إيجار 8 شهور"),
    ("Q50", "واحد سوى لي حادث وهرب ومالقيته"),
]

results = []
known_count = 0; total_conf = 0; slang_pass = 0; draft_arts = 0; greet_clean = 0

for qid, q in QUESTIONS:
    print(f"{qid}...", end=" ", flush=True)
    try:
        r = requests.post(API, json={"query": q, "model": "openai", "session_id": f"p27_{qid}"}, headers=H, timeout=120)
        d = r.json()
        a = d.get("answer", "")
        conf = d.get("confidence", 0)
        is_known = d.get("from_known_answer", False)
        domain = d.get("domain", "")
        sources = len(d.get("sources", []))
        n_arts = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+", a))
        n_rulings = len(re.findall(r"محكمة التمييز|طعن رقم", a))

        total_conf += conf
        if is_known: known_count += 1

        grade = "pass"
        qnum = int(qid[1:])
        if qnum <= 10:  # known
            grade = "pass" if is_known or conf == 100 else "fail"
        elif qnum <= 20:  # slang
            grade = "pass" if conf > 15 and len(a) > 80 else "fail"
            if grade == "pass": slang_pass += 1
        elif qnum <= 25:  # compound
            grade = "pass" if conf > 15 and len(a) > 100 else "fail"
        elif qnum <= 30:  # drafting
            grade = "pass" if conf >= 80 and len(a) > 200 else "fail"
            draft_arts += n_arts
        elif qnum <= 34:  # system/greetings
            grade = "pass" if conf >= 90 else "fail"
            if sources == 0: greet_clean += 1
        else:  # hard/scenarios
            grade = "pass" if conf > 15 and len(a) > 80 else "fail"

        results.append({"id": qid, "conf": conf, "known": is_known, "arts": n_arts, "rul": n_rulings, "grade": grade, "len": len(a)})
        sym = "OK" if grade == "pass" else "FAIL"
        extra = " known" if is_known else ""
        print(f"{sym} conf={conf} arts={n_arts}{extra}")
        time.sleep(2)
    except Exception as e:
        print(f"ERR: {e}")
        results.append({"id": qid, "conf": 0, "grade": "fail", "error": str(e)})

with open("scripts/test27_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] == "pass")
avg_conf = total_conf / len(results) if results else 0
weak = sorted([r for r in results if r["grade"] == "fail"], key=lambda x: x.get("conf", 0))[:5]

print(f"\n{'='*60}")
print(f"RESULT: {passed}/50")
print(f"Known answers matched: {known_count}/10")
print(f"Slang understood: {slang_pass}/10")
print(f"Draft articles: {draft_arts} total in 5 memos")
print(f"Greetings clean: {greet_clean}/4")
print(f"Average confidence: {avg_conf:.0f}%")
if weak:
    print(f"Weakest 5:")
    for w in weak:
        print(f"  {w['id']}: conf={w.get('conf',0)}")
print(f"{'='*60}")
