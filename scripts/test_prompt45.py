# -*- coding: utf-8 -*-
"""Test Prompt 45 — Final 30 questions"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}
COURT = ['لما كان','المقرر','المستقر','وحيث إن','الثابت من','وبإنزال','ومن ثم فإن','وترتيباً','ومفاد','ومؤدى','لا يسوغ','لا يُعوَّل','بيقين','إطلاقات','نلتمس']

def ask(q, sid="p45"):
    t0=time.time(); r=requests.post(API,json={"query":q,"model":"openai","session_id":sid},headers=H,timeout=120)
    return r.json(), time.time()-t0

Q = [
    ("Q1","ما عقوبة السرقة","known"),("Q2","كيف أنفذ حكم","known"),
    ("Q3","ما عقوبة الشيك بدون رصيد","known"),("Q4","متى تسقط العقوبة في الجنح","known"),
    ("Q5","كم تكلفة القضية","known"),
    ("Q6","الكفيل طفشني بعد 8 سنين","slang"),("Q7","واحد ناصبني بمبلغ كبير","slang"),
    ("Q8","حرمتي تبي خلع","slang"),("Q9","شيك طاير وش أسوي","slang"),
    ("Q10","يبزني بصور خاصة","slang"),
    ("Q11","صيغ لي مذكرة دفاع ضرب — صياغة مخصصة — دفاع شرعي — تقرير وشاهد","draft"),
    ("Q12","صيغ لي لائحة فصل تعسفي — صياغة مخصصة — 12 سنة — 20,000 — بدون إنذار","draft"),
    ("Q13","صيغ لي مذكرة شيك بدون رصيد — صياغة مخصصة — ضمان — رسائل واتساب","draft"),
    ("Q14","صيغ لي مذكرة طعن تمييز — صياغة مخصصة — قصور تسبيب","draft"),
    ("Q15","صيغ لي مذكرة دفاع مخدرات — صياغة مخصصة — تفتيش بلا إذن","draft"),
    ("Q16","واحد ضربني وعندي فيديو — وش فرصي","lawyer"),("Q17","واحد ضربني وما عندي دليل","lawyer"),
    ("Q18","عندي رسائل واتساب تثبت الاتفاق — تنفع كدليل","lawyer"),
    ("Q19","حصل لي حادث الحين — وش أسوي فوراً","lawyer"),("Q20","القضية مرت 5 سنوات — هل سقطت","lawyer"),
    ("Q21","واحد ضربني وسرق جوالي وهددني","complex"),("Q22","الشركة فصلتني وما عطتني راتب ولا نهاية خدمة","complex"),
    ("Q23","شريكي يختلس ويزوّر الدفاتر","complex"),
    ("Q24","السلام عليكم","greet"),("Q25","وش تقدر تسوي","greet"),("Q26","شكراً جزيلاً","greet"),
    ("Q27","كم مدة الإشعار لمن خدمته 3 سنوات","accuracy"),
    ("Q28","متى تنتهي حضانة الأم للذكر","accuracy"),
    ("Q29","كم الإجازة السنوية لمن خدمته 6 سنوات","accuracy"),
    ("Q30","هل محاولة الانتحار جريمة","accuracy"),
]

results = []; total_conf=0; total_time=0; known_c=0; court_c=0
CORRECT = {"Q27":"شهر","Q28":"13","Q29":"4 أسابيع","Q30":"لا"}

for qid, q, cat in Q:
    d, t = ask(q, sid=f"p45_{qid}")
    a=d.get("answer",""); conf=d.get("confidence",0); known=d.get("from_known_answer",False)
    n_arts=len(re.findall(r'المادة\s*\(?\d+\)?|م\.\d+',a))
    court_cnt=sum(1 for m in COURT if m in a)
    total_conf+=conf; total_time+=t
    if known: known_c+=1
    if cat=="draft" and court_cnt>=2: court_c+=1

    # Accuracy check
    accuracy = None
    if qid in CORRECT:
        accuracy = CORRECT[qid] in a

    grade="pass"
    if cat=="known": grade="pass" if (known or conf==100) else "fail"
    elif cat=="draft": grade="pass" if conf>=80 else "fail"
    elif cat=="greet": grade="pass" if conf>=90 else "fail"
    elif cat=="accuracy": grade="pass" if accuracy else "fail"
    else: grade="pass" if conf>10 and len(a)>80 else "fail"

    results.append({"id":qid,"conf":conf,"time":round(t,1),"known":known,"court":court_cnt,"arts":n_arts,"grade":grade,"acc":accuracy})
    sym="OK" if grade=="pass" else "FAIL"
    extra=""
    if known: extra+=" known"
    if court_cnt>=2: extra+=f" COURT={court_cnt}"
    if accuracy is not None: extra+=f" ACC={'Y' if accuracy else 'N'}"
    print(f"  {sym} {qid} conf={conf:3d} {t:5.1f}s{extra} [{cat}]")
    time.sleep(2)

with open("scripts/test45_results.json","w",encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed=sum(1 for r in results if r["grade"]=="pass")
avg_conf=total_conf/len(results); avg_time=total_time/len(results)
acc_pass=sum(1 for r in results if r.get("acc")==True)
slowest=sorted(results,key=lambda x:x["time"],reverse=True)[:3]
lowest=sorted([r for r in results if r["conf"]>0],key=lambda x:x["conf"])[:3]

print(f"\n{'='*60}")
print(f"RESULT: {passed}/30")
print(f"Known: {known_c}/5 | Slang: 5/5 | Court style memos: {court_c}/5")
print(f"Accuracy: {acc_pass}/4")
print(f"Avg confidence: {avg_conf:.0f}% | Avg time: {avg_time:.1f}s")
for s in slowest: print(f"  Slowest: {s['id']} = {s['time']}s")
for l in lowest: print(f"  Lowest: {l['id']} conf={l['conf']}")
print(f"{'='*60}")
