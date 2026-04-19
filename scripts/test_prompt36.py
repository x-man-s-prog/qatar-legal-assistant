# -*- coding: utf-8 -*-
"""Test Prompt 36 — Defense intelligence + precedents + strategic analysis"""
import requests, json, time, re

API = "http://localhost:80/api/v1/query/"
H = {"Content-Type": "application/json", "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"}

def ask(q, sid="p36"):
    t0 = time.time()
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=H, timeout=120)
    return r.json(), time.time() - t0

Q = [
    # Success rates test
    ("Q1", "واحد ضربني وعندي فيديو — وش فرصي أكسب"),
    ("Q2", "متهم بمخدرات والتفتيش كان بدون إذن — فيه أمل"),
    ("Q3", "القضية مرت عليها 5 سنوات — هل سقطت"),
    # Drafting with defense intel
    ("Q4", "صيغ لي مذكرة دفاع ضرب — صياغة مخصصة — دفاع شرعي + تقرير طبي"),
    ("Q5", "صيغ لي مذكرة دفاع مخدرات — صياغة مخصصة — التفتيش بدون إذن"),
    ("Q6", "صيغ لي مذكرة طعن بالتمييز — صياغة مخصصة — قصور تسبيب + إخلال بحق الدفاع"),
    # Q4/Q8 fix test
    ("Q7", "أنا متهم بعنف أسري — زوجتي عندها تقارير ضرب لكن أنا ما ضربتها — التقارير مزورة — وش أسوي"),
    ("Q8", "واحد يبتزني بصور خاصة ويطلب 50 ألف — خايف وما أبي أحد يدري"),
    # Precedents in memos
    ("Q9", "صيغ لي مذكرة شيك بدون رصيد — صياغة مخصصة — الشيك ضمان"),
    ("Q10", "صيغ لي لائحة فصل تعسفي — صياغة مخصصة — 8 سنوات — راتب 12,000"),
    # Compound
    ("Q11", "شريكي يختلس من الشركة ويزوّر الدفاتر — عندي كشف حساب يثبت"),
    ("Q12", "صار لي حادث — الطرف الثاني مات — أنا ما كنت متجاوز السرعة وعندي داشكام"),
    # Speed tests
    ("Q13", "ما عقوبة السرقة"),
    ("Q14", "السلام عليكم"),
    ("Q15", "صيغ لي عقد إيجار شقة — 5000 ريال — سنة"),
]

results = []
for qid, q in Q:
    print(f"  {qid}...", end=" ", flush=True)
    d, t = ask(q, sid=f"p36_{qid}")
    a = d.get("answer", "")
    conf = d.get("confidence", 0)
    is_known = d.get("from_known_answer", False)
    n_arts = len(re.findall(r"المادة\s*\(?\d+\)?|م\.\d+", a))
    has_rate = bool(re.search(r'\d+%', a))
    has_precedent = "محكمة التمييز" in a and ("طعن" in a or "المقرر" in a or "المستقر" in a)
    has_empathy = any(w in a for w in ["أفهم", "صعب", "حساس", "سري", "سرية"])
    is_strategic = not is_known and len(a) > 200 and any(w in a for w in ["موقف", "أدلة", "خطوة", "فرص"])

    grade = "pass"
    qnum = int(qid[1:])
    if qnum <= 3:  # rates
        grade = "pass" if conf > 10 and len(a) > 80 else "fail"
    elif qnum <= 6:  # drafting
        grade = "pass" if conf >= 80 and len(a) > 200 else "fail"
    elif qnum <= 8:  # Q7/Q8 fix
        grade = "pass" if not is_known and len(a) > 200 else "fail"
    elif qnum <= 10:  # precedent memos
        grade = "pass" if conf >= 80 and len(a) > 200 else "fail"
    elif qnum <= 12:  # compound
        grade = "pass" if conf > 10 and len(a) > 100 else "fail"
    elif qnum == 13:  # known speed
        grade = "pass" if is_known and t < 3 else "fail"
    elif qnum == 14:  # greeting
        grade = "pass" if conf >= 90 and t < 5 else "fail"
    elif qnum == 15:  # contract
        grade = "pass" if conf >= 80 else "fail"

    results.append({"id": qid, "conf": conf, "time": round(t,1), "known": is_known,
                    "arts": n_arts, "rate": has_rate, "precedent": has_precedent,
                    "empathy": has_empathy, "strategic": is_strategic, "grade": grade, "len": len(a)})

    sym = "OK" if grade == "pass" else "FAIL"
    extra = ""
    if has_rate: extra += " RATE"
    if has_precedent: extra += " PREC"
    if has_empathy: extra += " EMPA"
    if is_strategic: extra += " STRAT"
    if is_known: extra += " known"
    print(f"{sym} conf={conf:3d} {t:5.1f}s{extra}")
    time.sleep(2)

with open("scripts/test36_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["grade"] == "pass")
memo_prec = sum(1 for r in results if r.get("precedent") and r["id"] in ("Q4","Q5","Q9","Q10"))
memo_rate = sum(1 for r in results if r.get("rate") and r["id"] in ("Q4","Q5","Q6"))
q7_strat = results[6].get("strategic", False) if len(results) > 6 else False
q8_empa = results[7].get("empathy", False) if len(results) > 7 else False

print(f"\n{'='*60}")
print(f"RESULT: {passed}/15")
print(f"Memos with precedents: {memo_prec}/4")
print(f"Memos with success rates: {memo_rate}/3")
print(f"Q7 (violence) strategic analysis: {'YES' if q7_strat else 'NO'}")
print(f"Q8 (blackmail) empathy+steps: {'YES' if q8_empa else 'NO'}")
avg_conf = sum(r["conf"] for r in results) / len(results)
avg_time = sum(r["time"] for r in results) / len(results)
print(f"Avg confidence: {avg_conf:.0f}%")
print(f"Avg time: {avg_time:.1f}s")
print(f"{'='*60}")
