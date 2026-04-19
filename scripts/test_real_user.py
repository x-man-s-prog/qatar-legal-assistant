#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار خارق — يحاكي المستخدم الحقيقي على /api/v1/stream/"""
import urllib.request, json, time, sys, re

API = "http://localhost:8000/api/v1/stream/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
HDR = {"Content-Type": "application/json", "X-API-Key": KEY}

def send(q, sid="t", timeout=120):
    data = json.dumps({"query": q, "model": "openai", "session_id": sid}).encode()
    req = urllib.request.Request(API, data=data, headers=HDR, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8", errors="ignore")
        answer = ""; conf = 0; sources = 0; known = False
        for line in raw.split("\n"):
            if not line.startswith("data: "): continue
            try:
                d = json.loads(line[6:])
                if d.get("type") == "chunk": answer += d.get("text", "")
                elif d.get("type") == "done":
                    conf = d.get("confidence", conf)
                    sources = len(d.get("sources", []))
                    known = d.get("from_known_answer", known)
            except: pass
        return {"answer": answer.strip(), "conf": conf, "src": sources, "known": known}
    except Exception as e:
        return {"answer": f"ERROR: {e}", "conf": 0, "src": 0, "known": False}

def chk(r, rules, q=""):
    errs = []
    a = r["answer"]
    if rules.get("min_conf") and r["conf"] < rules["min_conf"]: errs.append(f"conf={r['conf']}")
    if rules.get("max_src") is not None and r["src"] > rules["max_src"]: errs.append(f"src={r['src']}")
    for w in rules.get("no", []):
        if w in a: errs.append(f"HAS '{w[:25]}'")
    if rules.get("min_len") and len(a) < rules["min_len"]: errs.append(f"short={len(a)}")
    if rules.get("has"):
        for w in rules["has"]:
            if w not in a: errs.append(f"miss '{w}'")
    return errs

total_ok = 0; total_fail = 0

def test(qid, q, sid, rules, label=""):
    global total_ok, total_fail
    r = send(q, sid)
    errs = chk(r, rules, q)
    sym = "OK" if not errs else "FAIL"
    if not errs: total_ok += 1
    else: total_fail += 1
    print(f"  {sym} {qid} conf={r['conf']:3d} src={r['src']} {label:15s} {q[:40]:40s} {' '.join(errs)}")
    if errs and len(r["answer"]) > 0: print(f"       {r['answer'][:100]}")
    time.sleep(2)
    return r

NO_DIESEL = ["ديزل", "نقل مواد خطرة", "حماية البيئة"]
NO_PROC = ["إجراءات رفع الدعوى", "المرافعات المدنية"]

print("\n" + "="*70)
print("=== 1. تحيات (7) ===")
for i, q in enumerate(["اخبارك","شحالك","علومك","السلام عليكم","هلا والله","كيفك","مساء الخير"], 1):
    test(f"G{i}", q, f"g{i}", {"min_conf": 90, "max_src": 0, "no": NO_DIESEL})

print("\n=== 2. حضانة (5) ===")
S = "custody"
test("C1", "هلا", S, {"min_conf": 90, "max_src": 0, "no": NO_DIESEL})
test("C2", "طليقتي تزوجت وابي ارفع دعوى اسقاط حضانة بنتي عنها اكتب لي مذكره", S,
     {"min_conf": 70, "max_src": 0, "no": NO_DIESEL + NO_PROC + ["m85","m815"], "has": ["حضانة"], "min_len": 200})
test("C3", "وش المواد القانونية الي تدعم موقفي", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("C4", "طيب وليش ما تذكر هالمواد بالمذكرة ادعمها اكثر", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("C5", "تمام مشكور", S, {"min_conf": 90, "max_src": 0, "no": NO_DIESEL})

print("\n=== 3. مخدرات (5) ===")
S = "drugs"
test("D1", "الحين وقفتني دورية شرطة وفتشتني ولقت عندي مخدرات وصار علي قضية كيف وضعي القانوني هل اقدر احصل براءه", S,
     {"min_conf": 15, "max_src": 0, "no": NO_DIESEL, "min_len": 100})
test("D2", "اكتب لي مذكرة دفاع", S,
     {"min_conf": 70, "max_src": 0, "no": NO_DIESEL + NO_PROC + ["عقد بيع"], "min_len": 200})
test("D3", "ادعم المذكرة بنصوص قانونية", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL, "min_len": 100})
test("D4", "وش فرصتي اكسب القضية", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("D5", "الله يعطيك العافية", S, {"min_conf": 90, "max_src": 0, "no": NO_DIESEL})

print("\n=== 4. عمالي (4) ===")
S = "labor"
test("L1", "الكفيل طفشني من الشغل بعد 10 سنوات وما عطاني نهاية خدمة ولا راتب آخر شهرين", S,
     {"min_conf": 15, "max_src": 0, "no": NO_DIESEL, "min_len": 100})
test("L2", "اكتب لي لائحة دعوى عشان ارفعها على الشركة", S,
     {"min_conf": 70, "max_src": 0, "no": NO_DIESEL + NO_PROC, "min_len": 200})
test("L3", "كم تتوقع التعويض تقريباً راتبي كان 15 الف", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("L4", "يعطيك العافية", S, {"min_conf": 90, "max_src": 0, "no": NO_DIESEL})

print("\n=== 5. مركّب (3) ===")
S = "complex"
test("X1", "واحد ضربني وسرق جوالي وبعدها هددني بالواتساب عندي فيديو وسكرينشوتات", S,
     {"min_conf": 15, "max_src": 0, "no": NO_DIESEL, "min_len": 100})
test("X2", "صيغ لي مذكرة دعوى ضده", S,
     {"min_conf": 70, "max_src": 0, "no": NO_DIESEL + NO_PROC, "min_len": 200})
test("X3", "هل فيديو الكاميرا يكفي كدليل", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})

print("\n=== 6. نظام (3) ===")
test("S1", "وش تقدر تسوي من مهام", "sys1", {"min_conf": 90, "max_src": 0, "no": NO_DIESEL, "has": ["ميزان"]})
test("S2", "هل تقدر تكتب مذكرات قانونية احترافية", "sys2", {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("S3", "كيف اطبخ كبسة", "sys3", {"max_src": 0, "no": NO_DIESEL})

print("\n=== 7. ابتزاز (3) ===")
S = "blackmail"
test("B1", "واحد يبتزني بصور خاصة ويطلب 50 الف خايف وما ابي احد يدري", S,
     {"min_conf": 15, "max_src": 0, "no": NO_DIESEL, "min_len": 100})
test("B2", "هل البلاغ سري ولا بيعرفون اهلي", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("B3", "وش عقوبة الابتزاز عليه", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})

print("\n=== 8. تبديل مواضيع (4) ===")
S = "switch"
test("W1", "ما عقوبة الضرب", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("W2", "وكم مدة استئناف الحكم الجنائي", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("W3", "ارجع لموضوع الضرب هل الدفاع الشرعي يخفف العقوبة", S, {"min_conf": 15, "max_src": 0, "no": NO_DIESEL})
test("W4", "شكراً", S, {"min_conf": 90, "max_src": 0, "no": NO_DIESEL})

total = total_ok + total_fail
print(f"\n{'='*70}")
print(f"RESULT: {total_ok}/{total} ({100*total_ok//max(total,1)}%)")
print(f"{'='*70}")
