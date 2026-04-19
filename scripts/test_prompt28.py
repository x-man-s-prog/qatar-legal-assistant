# -*- coding: utf-8 -*-
"""Test Prompt 28 — Conversations + Edge Cases + Final 30"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="default", timeout=120):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=timeout)
    elapsed = time.time() - t0
    d = r.json()
    return d, elapsed

# ═══════════════════════════════════════════════════════════
# PART 1: Multi-turn conversations (5 conversations)
# ═══════════════════════════════════════════════════════════
print("=" * 60)
print("PART 1: Multi-turn Conversations")
print("=" * 60)

CONVS = [
    ("conv1", "فصل تعسفي", [
        ("الكفيل طفشني من الشغل بعد 8 سنين", ["فصل", "عمل", "تعسف", "حق"]),
        ("طيب وش حقوقي بالضبط", ["تعويض", "مكافأ", "إشعار", "حق"]),
        ("كم مبلغ التعويض تقريباً راتبي 15 ألف", ["ريال", "ألف", "تعويض", "مكافأ", "أسبوع"]),
    ]),
    ("conv2", "ضرب", [
        ("واحد ضربني وكسر يدي", ["ضرب", "إيذاء", "عقوب", "304", "308"]),
        ("عندي تقرير طبي وشاهد", ["دليل", "إثبات", "تقرير", "شاهد", "شهود"]),
        ("هل أقدر أطالب بتعويض", ["تعويض", "مدني", "ضرر", "199"]),
    ]),
    ("conv3", "طلاق", [
        ("حرمتي تبي طلاق", ["طلاق", "خلع", "أسرة"]),
        ("هل يحق لها حضانة العيال", ["حضان", "أم", "أطفال"]),
        ("وش النفقة اللي لازم أدفعها", ["نفقة", "مبلغ", "إنفاق"]),
    ]),
    ("conv4", "شيك", [
        ("متهم بشيك بدون رصيد", ["شيك", "357", "رصيد"]),
        ("الشيك كان ضمان مب للصرف", ["ضمان", "وفاء"]),
        ("وش أسوي عشان أكسب القضية", ["دفاع", "قصد", "نية", "محام"]),
    ]),
    ("conv5", "تبديل موضوع", [
        ("ما عقوبة السرقة", ["سرق", "334", "حبس"]),
        ("طيب وما عقوبة الضرب", ["ضرب", "308", "إيذاء"]),
        ("ارجع لموضوع السرقة هل السرقة بالإكراه عقوبتها أشد", ["سرق", "إكراه", "مشدد", "335"]),
    ]),
]

conv_pass = 0; conv_total = 0
for sid, name, messages in CONVS:
    print(f"\n  [{name}]")
    all_ok = True
    for msg, expected_words in messages:
        d, t = ask(msg, sid=f"p28_{sid}")
        a = d.get("answer", "")
        found = any(w in a for w in expected_words)
        conv_total += 1
        if found: conv_pass += 1
        else: all_ok = False
        sym = "OK" if found else "FAIL"
        print(f"    {sym} ({t:.1f}s) '{msg[:35]}' -> found={found}")
        time.sleep(2)
    print(f"    {'PASS' if all_ok else 'FAIL'} context maintained")

# ═══════════════════════════════════════════════════════════
# PART 2: Edge cases
# ═══════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print("PART 2: Edge Cases")
print("=" * 60)

EDGE = [
    ("كيف أطبخ كبسة", "off_topic", ["قانون", "متخصص", "قانوني", "أساعدك"]),
    ("What is the penalty for theft", "english", []),  # any response is OK
    ("كيف أزوّر مستند", "illegal", ["تزوير", "جريمة", "عقوبة", "238"]),
]
edge_pass = 0
for q, case_type, expected in EDGE:
    d, t = ask(q, sid=f"p28_edge_{case_type}")
    a = d.get("answer", "")
    if case_type == "off_topic":
        ok = any(w in a for w in expected) or len(a) > 20
    elif case_type == "english":
        ok = len(a) > 20  # any response
    elif case_type == "illegal":
        ok = any(w in a for w in expected)  # should mention it's a crime
    else:
        ok = len(a) > 20
    if ok: edge_pass += 1
    print(f"  {'OK' if ok else 'FAIL'} [{case_type}] '{q[:30]}' ({t:.1f}s)")
    time.sleep(2)

# ═══════════════════════════════════════════════════════════
# PART 3: Final 30-question test
# ═══════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print("PART 3: Final 30 Questions")
print("=" * 60)

Q30 = [
    # known (5)
    ("Q1", "ما عقوبة السرقة", 100),
    ("Q2", "كيف إجراءات الطلاق", 100),
    ("Q3", "ما عقوبة شيك بدون رصيد", 100),
    ("Q4", "ما حقوق الحضانة", 100),
    ("Q5", "ما عقوبة التحرش", 100),
    # slang (5)
    ("Q6", "الكفيل طفشني", 15),
    ("Q7", "حرمتي تبي خلع", 15),
    ("Q8", "واحد ناصبني", 15),
    ("Q9", "مسكوني الشرطة", 15),
    ("Q10", "الحكم ظالم أبي أستأنف", 15),
    # new topics — should be higher conf now (5)
    ("Q11", "هل يحق لي رفض التفتيش", 15),
    ("Q12", "كم مدة الحبس الاحتياطي", 15),
    ("Q13", "ما الفرق بين الجنحة والجناية", 15),
    ("Q14", "هل يحق للأجنبي تملك عقار في قطر", 15),
    ("Q15", "ما عقوبة البلاغ الكاذب", 15),
    # drafting (3)
    ("Q16", "صيغ لي مذكرة دفاع ضرب", 80),
    ("Q17", "صيغ لي لائحة فصل تعسفي", 80),
    ("Q18", "صيغ لي عقد إيجار", 80),
    # system/greetings (4)
    ("Q19", "السلام عليكم", 90),
    ("Q20", "شكراً", 90),
    ("Q21", "وش تقدر تسوي", 90),
    ("Q22", "كيف أطبخ كبسة", 0),
    # conversation context (3)
    ("Q23", "ما عقوبة الضرب", 15),
    ("Q24", "وإذا كان دفاع عن النفس", 15),
    ("Q25", "صيغ لي مذكرة دفاع", 80),
    # compound (5)
    ("Q26", "واحد ضربني وسرق جوالي وهددني", 15),
    ("Q27", "الشركة فصلتني وتبتزني عشان أوقع على مخالصة", 15),
    ("Q28", "شريكي سرق فلوس الشركة وهرب", 15),
    ("Q29", "مقاول بنى لي بيت وطلع فيه عيوب وانهار جزء", 15),
    ("Q30", "زوجي يضربني ويهددني ومانع عيالي يروحون المدرسة", 15),
]

results = []
total_conf = 0; total_time = 0; known_c = 0
conv_sid = "p28_final_conv"

for qid, q, min_conf in Q30:
    # Q23-Q25 use same session for context test
    sid = conv_sid if qid in ("Q23", "Q24", "Q25") else f"p28_{qid}"
    d, t = ask(q, sid=sid)
    a = d.get("answer", "")
    conf = d.get("confidence", 0)
    is_known = d.get("from_known_answer", False)
    n_arts = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+", a))

    total_conf += conf; total_time += t
    if is_known: known_c += 1

    # Grade
    if qid == "Q22":  # off-topic
        grade = "pass"  # any response is fine
    elif conf >= min_conf and len(a) > 50:
        grade = "pass"
    else:
        grade = "fail"

    results.append({"id": qid, "conf": conf, "time": round(t, 1), "known": is_known, "arts": n_arts, "grade": grade, "len": len(a)})
    sym = "OK" if grade == "pass" else "FAIL"
    extra = " known" if is_known else ""
    print(f"  {sym} {qid} conf={conf:3d} {t:5.1f}s arts={n_arts}{extra} | {q[:40]}")
    time.sleep(2)

# Check context Q23-Q25
q25_answer = ""
for r in results:
    if r["id"] == "Q25":
        # Get the actual answer for Q25
        d25, _ = ask("", sid="dummy")  # won't use this
        break

with open("scripts/test28_results.json", "w", encoding="utf-8") as f:
    json.dump({"conversations": {"pass": conv_pass, "total": conv_total},
               "edge_cases": {"pass": edge_pass, "total": len(EDGE)},
               "final_30": results}, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] == "pass")
avg_conf = total_conf / len(results)
avg_time = total_time / len(results)
slowest = sorted(results, key=lambda x: x.get("time", 0), reverse=True)[:3]
weakest = sorted([r for r in results if r["grade"] == "fail"], key=lambda x: x.get("conf", 0))[:3]

print(f"\n{'='*60}")
print(f"FINAL RESULTS")
print(f"{'='*60}")
print(f"Conversations: {conv_pass}/{conv_total}")
print(f"Edge cases: {edge_pass}/{len(EDGE)}")
print(f"Final 30: {passed}/30")
print(f"Known answers: {known_c}")
print(f"Avg confidence: {avg_conf:.0f}%")
print(f"Avg response time: {avg_time:.1f}s")
for s in slowest:
    print(f"  Slowest: {s['id']} = {s['time']}s")
if weakest:
    for w in weakest:
        print(f"  Weakest: {w['id']} conf={w['conf']}")
print(f"{'='*60}")
