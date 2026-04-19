#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار ليلي شامل — 100 سؤال عبر /api/v1/stream/"""
import urllib.request, json, time, sys, re

API = "http://localhost:8000/api/v1/stream/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
HDR = {"Content-Type": "application/json", "X-API-Key": KEY}

def send(q, sid="t"):
    data = json.dumps({"query": q, "model": "openai", "session_id": sid}).encode()
    req = urllib.request.Request(API, data=data, headers=HDR, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        raw = resp.read().decode("utf-8", errors="ignore")
        a=""; conf=0; src=0; kn=False
        for line in raw.split("\n"):
            if not line.startswith("data: "): continue
            try:
                d = json.loads(line[6:])
                if d.get("type")=="chunk": a += d.get("text","")
                elif d.get("type")=="done":
                    conf=d.get("confidence",conf); src=len(d.get("sources",[])); kn=d.get("from_known_answer",kn)
            except: pass
        return {"a":a.strip(),"c":conf,"s":src,"k":kn}
    except Exception as e:
        return {"a":f"ERR:{e}","c":0,"s":0,"k":False}

DIESEL = ["ديزل","نقل مواد خطرة","حماية البيئة"]
ok=0; fail=0; fails=[]

def t(qid, q, sid, min_c=0, max_s=99, no=[], has=[], label=""):
    global ok, fail, fails
    r = send(q, sid)
    errs = []
    if min_c and r["c"] < min_c: errs.append(f"c={r['c']}")
    if r["s"] > max_s: errs.append(f"s={r['s']}")
    for w in no:
        if w in r["a"]: errs.append(f"HAS:{w[:15]}")
    for w in has:
        if w not in r["a"]: errs.append(f"MISS:{w[:15]}")
    # Always check diesel
    for d in DIESEL:
        if d in r["a"]: errs.append(f"DIESEL!")
    if errs:
        fail += 1; fails.append({"id":qid,"q":q[:40],"errs":errs})
        print(f"  FAIL {qid} c={r['c']:3d} s={r['s']} {label:8s} {q[:35]:35s} {' '.join(errs)}")
    else:
        ok += 1
        print(f"  OK   {qid} c={r['c']:3d} s={r['s']} {label:8s} {q[:35]}")
    time.sleep(1.5)

print("=== Greetings (10) ===")
for i,q in enumerate(["شحالك","اخبارك","علومك","السلام عليكم","هلا والله","كيفك","مساء الخير","هلا","اهلين","يا هلا"],1):
    t(f"G{i}",q,f"g{i}",min_c=90,max_s=0,label="greet")

print("\n=== Fillers (5) ===")
for i,q in enumerate(["حمدالله","تمام","عندي سؤال","ان شاء الله","بارك الله فيك"],1):
    t(f"F{i}",q,f"f{i}",min_c=90,max_s=0,label="filler")

print("\n=== Thanks (5) ===")
for i,q in enumerate(["شكراً","مشكور","يعطيك العافية","جزاك الله خير","الله يسلمك"],1):
    t(f"T{i}",q,f"t{i}",min_c=90,max_s=0,label="thanks")

print("\n=== Known (15) ===")
for i,(q,h) in enumerate([("ما عقوبة السرقة",[]),("ما حقوقي عند الفصل التعسفي",[]),("كيف إجراءات الطلاق",[]),
    ("ما عقوبة الشيك بدون رصيد",[]),("ما حالات إنهاء العقد بدون إشعار",[]),("ما عقوبة التحرش",[]),
    ("ما عقوبة السحر",[]),("واحد ماخذ فلوسي",[]),("ما عقوبة التزوير",[]),("ما عقوبة الرشوة",[]),
    ("كم تكلفة القضية",[]),("كم تاخذ القضية",[]),("أي محكمة أروح لها",[]),("هل فيه وساطة",[]),("كيف أنفذ حكم",[])],1):
    t(f"K{i}",q,f"k{i}",min_c=90,max_s=0,label="known")

print("\n=== Slang (10) ===")
for i,q in enumerate(["الكفيل طفشني من الشغل","حرمتي تبي تنفصل","واحد ناصبني بمبلغ كبير",
    "شيك طاير وش أسوي","يبزني بصور خاصة","مسكوني وودوني المخفر","الحكم ظالم أبي أستأنف",
    "ولدي انضرب بالمدرسة","صاحب البيت يبي يطلعني","شريكي ياخذ فلوس الشركة"],1):
    t(f"SL{i}",q,f"sl{i}",min_c=15,max_s=0,label="slang")

print("\n=== Memos (10) ===")
for i,q in enumerate(["صيغ لي مذكرة دفاع ضرب — صياغة مخصصة — دفاع شرعي",
    "صيغ لي لائحة فصل تعسفي — 10 سنوات — راتب 15000",
    "صيغ لي مذكرة شيك بدون رصيد — ضمان",
    "صيغ لي مذكرة طعن تمييز — قصور تسبيب",
    "صيغ لي مذكرة دفاع مخدرات — تفتيش بلا إذن",
    "طليقتي تزوجت اكتب لي مذكرة اسقاط حضانه",
    "صيغ لي عقد إيجار شقة — 5000 ريال — سنة",
    "صيغ لي عقد عمل",
    "صيغ لي عقد شراكة تجارية",
    "صيغ لي مذكرة تشهير إلكتروني"],1):
    t(f"M{i}",q,f"m{i}",min_c=80,max_s=0,no=["إجراءات رفع الدعوى","عقد بيع"],label="memo")

print("\n=== Lawyer (10) ===")
for i,q in enumerate(["واحد ضربني وعندي فيديو — وش فرصي","واحد ضربني وما عندي دليل",
    "عندي رسائل واتساب تثبت الاتفاق — تنفع كدليل","حصل لي حادث الحين — وش أسوي فوراً",
    "القضية مرت 5 سنوات — هل سقطت","متهم بمخدرات والتفتيش بدون إذن — فيه أمل",
    "شريكي يختلس — بس لو شكيته بخسر الشركة","أبي أفسخ عقد إيجار — فيه شرط جزائي 100 ألف",
    "استلمت إنذار إخلاء — عندي أسبوع","اكتشفت موظف يسرق من الشركة — وش أسوي"],1):
    t(f"LW{i}",q,f"lw{i}",min_c=15,max_s=0,label="lawyer")

print("\n=== Complex (10) ===")
for i,q in enumerate(["واحد ضربني وسرق جوالي وهددني","الشركة فصلتني وما عطتني راتب ولا نهاية خدمة",
    "شريكي يختلس ويزوّر الدفاتر","مقاول ما خلص البناء وهرب","زوجي يضربني وأبي طلاق مع حضانة العيال",
    "اشتريت سيارة وطلعت فيها عيب مخفي","جاري بنى بدون ترخيص يحجب الشمس",
    "موظف سابق سرق بيانات العملاء","والدي توفي وأخوي مسيطر على الميراث",
    "أنا مهندس رفضت أوقع على تقارير مزورة وفصلوني"],1):
    t(f"CX{i}",q,f"cx{i}",min_c=15,max_s=0,label="complex")

print("\n=== Conversation context (5) ===")
S = "ctx_test"
t("CT1","ما عقوبة الضرب",S,min_c=15,max_s=0,label="ctx")
t("CT2","وإذا كان دفاع عن النفس",S,min_c=15,max_s=0,label="ctx")
t("CT3","صيغ لي مذكرة",S,min_c=15,max_s=0,no=["إجراءات رفع"],label="ctx")
S2 = "ctx2"
t("CT4","طليقتي تزوجت اكتب لي مذكرة حضانة",S2,min_c=70,max_s=0,label="ctx")
t("CT5","ادعم المذكرة بمواد اكثر",S2,min_c=15,max_s=0,label="ctx")

print("\n=== System (5) ===")
t("SY1","وش تقدر تسوي","sy1",min_c=90,max_s=0,has=["ميزان"],label="system")
t("SY2","من أنت","sy2",min_c=90,max_s=0,label="system")
t("SY3","هل تقدر تكتب مذكرات","sy3",min_c=15,max_s=0,label="system")
t("SY4","كيف اطبخ كبسة","sy4",max_s=0,label="system")
t("SY5","احتاجك تساعدني في موضوع","sy5",min_c=90,max_s=0,label="system")

print("\n=== Accuracy (5) ===")
t("AC1","كم مدة الإشعار لمن خدمته 3 سنوات","ac1",min_c=15,max_s=0,has=["شهر"],label="accuracy")
t("AC2","هل محاولة الانتحار جريمة في قطر","ac2",min_c=15,max_s=0,label="accuracy")
t("AC3","كم مدة استئناف الحكم الجنائي","ac3",min_c=15,max_s=0,has=["15"],label="accuracy")
t("AC4","ما عقوبة إصدار شيك بدون رصيد","ac4",min_c=15,max_s=0,label="accuracy")
t("AC5","كم مدة الطعن بالتمييز","ac5",min_c=15,max_s=0,has=["60"],label="accuracy")

total = ok + fail
print(f"\n{'='*60}")
print(f"RESULT: {ok}/{total} ({100*ok//max(total,1)}%)")
if fails:
    print(f"\nFailed ({len(fails)}):")
    for f in fails:
        print(f"  {f['id']}: {f['q']} → {f['errs']}")
print(f"{'='*60}")

with open("scripts/judicial_memory/test_100_results.json","w",encoding="utf-8") as f:
    json.dump({"total":total,"pass":ok,"fail":fail,"rate":f"{100*ok//max(total,1)}%","fails":fails},f,ensure_ascii=False,indent=2)
