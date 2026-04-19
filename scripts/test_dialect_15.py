# -*- coding: utf-8 -*-
"""test_dialect_15.py — اختبار لهجة + صياغة مع ربط"""
import urllib.request, json, time, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:80/api/v1/query/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"

QUESTIONS = [
    # لهجة (1-10)
    ("الكفيل طفشني من الشغل ومارد فلوسي وحاجز جوازي وش أسوي", "لهجة"),
    ("حرمتي تبي خلع وأنا مب موافق وتبي تاخذ العيال", "لهجة"),
    ("واحد ناصبني بمبلغ 200 ألف عن طريق مشروع وهمي", "لهجة"),
    ("ريال هددني بالواتساب وقال بفضحني", "لهجة"),
    ("صاحب البيت يبي يطلعني ما خلصت السنة", "لهجة"),
    ("خويي ماخذ مني فلوس وما ردهم ومعي شيكات", "لهجة"),
    ("الشركة ماعطتني نهاية خدمة ولا شهادة خبرة", "لهجة"),
    ("تورطت بقضية شيك طاير وأبي أعرف العقوبة", "لهجة"),
    ("واحد سوى حساب باسمي بالانستقرام وينشر أشياء", "لهجة"),
    ("ولدي انضرب بالمدرسة وابي أشتكي", "لهجة"),
    # صياغة (11-15)
    ("صيغ لي مذكرة — صياغة مخصصة — الكفيل طفشني بعد 8 سنوات شغل وما عطاني نهاية خدمة ولا إنذار", "صياغة"),
    ("صيغ لي مذكرة — صياغة مخصصة — واحد ضربني ورحت المستشفى وعندي تقرير", "صياغة"),
    ("صيغ لي لائحة — صياغة مخصصة — حرمتي تبي طلاق للضرر عندها تقارير طبية ضرب", "صياغة"),
    ("صيغ لي مذكرة — صياغة مخصصة — ابتزاز إلكتروني بصور خاصة يطلب 100 ألف", "صياغة"),
    ("صيغ لي مذكرة — صياغة مخصصة — شريكي بالشركة ياخذ فلوس بدون علمي وعندي كشف حساب", "صياغة"),
]

def call_api(q):
    data = json.dumps({"query": q, "mode": "expert", "model": "openai"}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": KEY})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=180)
    return json.loads(resp.read().decode("utf-8")), time.time() - t0

results = []
for i, (q, cat) in enumerate(QUESTIONS):
    print(f"\n{'='*60}")
    print(f"  [{cat}] #{i+1}: {q[:55]}...")
    print(f"{'='*60}")
    try:
        d, elapsed = call_api(q)
        answer = d.get("answer", "")
        conf = d.get("confidence", 0) or 0
        arts = len(re.findall(r'الماد[ةه]\s*\(?\s*\d+\s*\)?', answer))
        tmz = len(re.findall(r'(?:طعن|الطعن|التمييز في)\s*(?:رقم)?\s*\d+', answer))
        understood = len(answer) > 50 and "لا أفهم" not in answer
        preview = answer.replace('\n', ' ')[:300]
        print(f"  conf={conf}% | {elapsed:.1f}s | مواد={arts} | تمييز={tmz} | فهم={understood}")
        print(f"  الرد: {preview}")
        results.append({"num": i+1, "cat": cat, "understood": understood, "arts": arts, "tmz": tmz, "conf": conf, "len": len(answer)})
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"num": i+1, "cat": cat, "status": "error"})
    time.sleep(4)

# Summary
ok_dialect = sum(1 for r in results if r.get("cat") == "لهجة" and r.get("understood"))
ok_draft = sum(1 for r in results if r.get("cat") == "صياغة" and r.get("understood"))
with_arts = sum(1 for r in results if r.get("cat") == "صياغة" and r.get("arts", 0) > 0)
with_tmz = sum(1 for r in results if r.get("cat") == "صياغة" and r.get("tmz", 0) > 0)

print(f"\n{'='*60}")
print(f"  فهم اللهجة: {ok_dialect}/10")
print(f"  صياغة ناجحة: {ok_draft}/5")
print(f"  صياغة مع مواد: {with_arts}/5")
print(f"  صياغة مع تمييز: {with_tmz}/5")

with open("scripts/test_dialect_15_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
