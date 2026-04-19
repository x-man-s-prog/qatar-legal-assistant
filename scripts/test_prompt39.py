# -*- coding: utf-8 -*-
"""Test Prompt 39 — Final 30 questions"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="p39"):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=120)
    return r.json(), time.time() - t0

Q = [
    ("Q1","ما عقوبة السرقة","known"),("Q2","كيف أنفذ حكم صادر لصالحي","known"),
    ("Q3","ما عقوبة الشيك بدون رصيد","known"),("Q4","ما حقوقي عند الفصل التعسفي","known"),
    ("Q5","كيف إجراءات الطلاق","known"),
    ("Q6","الكفيل طفشني من الشغل","slang"),("Q7","حرمتي تبي خلع","slang"),
    ("Q8","واحد ناصبني","slang"),("Q9","شيك طاير وش أسوي","slang"),
    ("Q10","يبزني بصور خاصة","slang"),
    ("Q11","صيغ لي مذكرة دفاع ضرب — صياغة مخصصة — دفاع شرعي","draft"),
    ("Q12","صيغ لي لائحة فصل تعسفي — صياغة مخصصة — 10 سنوات","draft"),
    ("Q13","صيغ لي مذكرة شيك بدون رصيد — صياغة مخصصة — ضمان","draft"),
    ("Q14","صيغ لي مذكرة طعن تمييز — صياغة مخصصة — قصور تسبيب","draft"),
    ("Q15","صيغ لي مذكرة دفاع مخدرات — صياغة مخصصة — تفتيش بلا إذن","draft"),
    ("Q16","واحد ضربني وعندي فيديو — وش فرصي","lawyer"),
    ("Q17","واحد ضربني وما عندي دليل","lawyer"),
    ("Q18","عندي رسائل واتساب — هل تنفع كدليل","lawyer"),
    ("Q19","حصل لي حادث الحين — وش أسوي فوراً","lawyer"),
    ("Q20","القضية مرت 5 سنوات — هل سقطت","lawyer"),
    ("Q21","واحد ضربني وسرق جوالي وهددني","complex"),
    ("Q22","الشركة فصلتني وما عطتني راتب ولا نهاية خدمة","complex"),
    ("Q23","شريكي يختلس ويزوّر","complex"),
    ("Q24","السلام عليكم","greet"),("Q25","وش المهام الي تقدر تسويها","greet"),
    ("Q26","شكراً","greet"),
    ("Q27","هل يحق لي رفض التفتيش","rare"),("Q28","ما الفرق بين الجنحة والجناية","rare"),
    ("Q29","هل يحق للأجنبي تملك عقار","rare"),("Q30","ما عقوبة البلاغ الكاذب","rare"),
]

results = []; cats = {}; total_conf = 0; total_time = 0; known_c = 0
slang_confs = []; draft_prins = 0

for qid, q, cat in Q:
    d, t = ask(q, sid=f"p39_{qid}")
    a = d.get("answer",""); conf = d.get("confidence",0); known = d.get("from_known_answer",False)
    has_prin = any(p in a for p in ["المقرر","المستقر","محكمة التمييز على أن","استقرت"])
    total_conf += conf; total_time += t
    if known: known_c += 1
    if cat == "slang": slang_confs.append(conf)
    if cat == "draft" and has_prin: draft_prins += 1

    grade = "pass"
    if cat == "known": grade = "pass" if (known or conf==100) else "fail"
    elif cat == "draft": grade = "pass" if conf >= 80 else "fail"
    elif cat == "greet": grade = "pass" if conf >= 90 else "fail"
    elif cat in ("slang","complex","rare","lawyer"): grade = "pass" if conf > 10 and len(a) > 80 else "fail"

    cats[cat] = cats.get(cat,0) + (1 if grade=="pass" else 0)
    results.append({"id":qid,"conf":conf,"time":round(t,1),"known":known,"prin":has_prin,"grade":grade,"cat":cat})
    sym = "OK" if grade=="pass" else "FAIL"
    extra = " known" if known else ""
    extra += " PRIN" if has_prin else ""
    print(f"  {sym} {qid} conf={conf:3d} {t:5.1f}s{extra} [{cat}]")
    time.sleep(2)

with open("scripts/test39_results.json","w",encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"]=="pass")
avg_conf = total_conf/len(results); avg_time = total_time/len(results)
avg_slang = sum(slang_confs)/max(len(slang_confs),1)

print(f"\n{'='*60}")
print(f"RESULT: {passed}/30")
print(f"Known: {known_c}/5 (targets)")
print(f"Slang avg conf: {avg_slang:.0f}% (was 49%)")
print(f"Drafts with principles: {draft_prins}/5")
print(f"Avg confidence: {avg_conf:.0f}%")
print(f"Avg time: {avg_time:.1f}s")
print(f"{'='*60}")
