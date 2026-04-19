# -*- coding: utf-8 -*-
"""test_final_50.py — اختبار شامل نهائي 50 سؤال"""
import urllib.request, json, time, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:80/api/v1/query/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
MODEL = "openai"

QUESTIONS = [
    # الفئة 1: التحيات (5)
    ("السلام عليكم", "تحية", "تحية فقط"),
    ("مساء الخير", "تحية", "تحية فقط"),
    ("شكراً على المساعدة", "تحية", "شكر"),
    ("مين أنت؟", "تحية", "تعريف"),
    ("هلا والله", "تحية", "تحية خليجية"),
    # الفئة 2: أسئلة قانونية مباشرة (10)
    ("ما عقوبة السرقة؟", "قانوني", "عقوبات"),
    ("ما هي شروط الطلاق؟", "قانوني", "أسرة"),
    ("كم مدة الإجازة السنوية في قانون العمل؟", "قانوني", "عمل"),
    ("ما عقوبة الضرب؟", "قانوني", "عقوبات"),
    ("هل يحق للمستأجر فسخ العقد قبل انتهائه؟", "قانوني", "مدني"),
    ("ما هي عقوبة السحر والشعوذة؟", "قانوني", "عقوبات"),
    ("كيف أحصل على رد اعتبار؟", "قانوني", "إجراءات"),
    ("ما عقوبة التشهير؟", "قانوني", "عقوبات"),
    ("ما هي حقوق المرأة في الميراث؟", "قانوني", "أسرة"),
    ("ما عقوبة حيازة المخدرات؟", "قانوني", "عقوبات"),
    # الفئة 3: لهجة خليجية (5)
    ("واحد ظلمني وش أسوي؟", "لهجة", "توضيح"),
    ("ابي اعرف حقوقي في الشغل", "لهجة", "عمل"),
    ("كيف اقدم شكوا على الكفيل", "لهجة", "شكوى"),
    ("مب راضي يعطيني حقوقي صاحب العمل", "لهجة", "عمل"),
    ("فيه شي صار لي في الشغل مب زين", "لهجة", "توضيح"),
    # الفئة 4: مركّبة (5)
    ("شخص اعتدى علي ونشر فيديو الاعتداء", "مركّب", "عقوبات+إلكتروني"),
    ("شريكي سرق أموال الشركة وهرب", "مركّب", "شركات+عقوبات"),
    ("تم فصلي بعد ما رفضت التوقيع على مخالصة", "مركّب", "عمل"),
    ("المؤجر يهددني بالطرد ويرفض يصلح الشقة", "مركّب", "إيجار"),
    ("موظف سرّب بيانات العملاء وابتزهم", "مركّب", "إلكتروني+عقوبات"),
    # الفئة 5: صياغة عقود (5)
    ("صيغ لي عقد إيجار شقة", "عقد", "عقد إيجار"),
    ("أبي نموذج عقد عمل", "عقد", "عقد عمل"),
    ("اكتب لي شكوى ضد صاحب العمل لعدم دفع الراتب", "عقد", "شكوى"),
    ("صيغ لي عقد شراكة تجارية", "عقد", "عقد شراكة"),
    ("نموذج مذكرة دفاع في قضية سب وقذف", "عقد", "مذكرة"),
    # الفئة 6: صعبة/حدية (10)
    ("ما هي سن المسؤولية الجنائية؟", "صعب", "عقوبات"),
    ("هل يجوز تسجيل مكالمة بدون علم الطرف الآخر؟", "صعب", "خصوصية"),
    ("هل يحق للشرطة تفتيش الهاتف بدون إذن؟", "صعب", "إجراءات"),
    ("ما الفرق بين الجنحة والجناية؟", "صعب", "عقوبات"),
    ("هل يحق لصاحب العمل حجز جواز السفر؟", "صعب", "عمل"),
    ("عقد شراكة بدون توثيق رسمي والطرف الآخر أنكر", "صعب", "مدني"),
    ("شخص يدّعي عليّ بدين وأنا ما عليّ شيء", "صعب", "مدني"),
    ("نزاع على ملكية عقار بدون أوراق كاملة", "صعب", "عقاري"),
    ("تهديد عبر الإنترنت بدون معرفة هوية المهدد", "صعب", "إلكتروني"),
    ("هل يُعاقب على محاولة الانتحار؟", "صعب", "عقوبات"),
    # الفئة 7: قوانين جديدة (5)
    ("ما هي حقوق الولي على أموال القاصر؟", "جديد", "ولاية"),
    ("ما حقوق العاملة المنزلية في قطر؟", "جديد", "عمالة منزلية"),
    ("ما هي إجراءات شهر الإفلاس؟", "جديد", "تجاري"),
    ("ما عقوبة مزاولة مهنة الطب بدون ترخيص؟", "جديد", "صحي"),
    ("ما هي إجراءات التنفيذ القضائي؟", "جديد", "تنفيذ"),
    # الفئة 8: أخطاء إملائية (5)
    ("ما عقوبت السرقه", "إملاء", "عقوبات"),
    ("كيف ارفع قظية", "إملاء", "إجراءات"),
    ("حقوق الموظف عند الفسل", "إملاء", "عمل"),
    ("هل يجوز الطالق بدون سبب", "إملاء", "أسرة"),
    ("ما عقوبة الظرب", "إملاء", "عقوبات"),
]

def call_api(q):
    data = json.dumps({"query": q, "mode": "expert", "model": MODEL}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": KEY})
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read().decode("utf-8"))

def has_eng(text):
    return bool(re.findall(r'[A-Za-z]{3,}(?:\s+[A-Za-z]{3,}){2,}', text))

categories = {}
results = []
total_ok = 0
total_warn = 0
total_err = 0

print("=" * 70)
print(f"  اختبار شامل نهائي — {len(QUESTIONS)} سؤال — النموذج: {MODEL}")
print("=" * 70)

for i, (q, cat, expect) in enumerate(QUESTIONS):
    if cat not in categories:
        categories[cat] = {"ok": 0, "warn": 0, "err": 0, "total": 0}
    categories[cat]["total"] += 1

    try:
        d = call_api(q)
        answer = d.get("answer", "")
        conf = d.get("confidence", 0)
        known = d.get("from_known_answer", False)
        domain = d.get("domain", "?")

        eng = has_eng(answer)
        has_answer = len(answer) > 20 and "خطأ تقني" not in answer

        if has_answer and not eng:
            status = "OK"
            total_ok += 1
            categories[cat]["ok"] += 1
        elif has_answer and eng:
            status = "WARN"
            total_warn += 1
            categories[cat]["warn"] += 1
        else:
            status = "ERR"
            total_err += 1
            categories[cat]["err"] += 1

        # Print compact result
        tag = "known" if known else "RAG"
        ans_preview = answer.replace("\n", " ")[:150]
        print(f"  {i+1:2d}. [{status:4s}] conf={conf:3d} [{tag:5s}] [{cat:6s}] {q[:35]:35s} | {ans_preview[:80]}")
        results.append({"q": q, "cat": cat, "status": status, "conf": conf, "eng": eng, "ans_len": len(answer)})

    except Exception as e:
        err_msg = str(e)[:50]
        print(f"  {i+1:2d}. [ERR ] [{cat:6s}] {q[:35]:35s} | {err_msg}")
        total_err += 1
        categories[cat]["err"] += 1
        results.append({"q": q, "cat": cat, "status": "ERR", "error": str(e)})

    time.sleep(2)

# Summary
print(f"\n\n{'=' * 70}")
print("  النتائج الإجمالية")
print("=" * 70)
print(f"  النجاح: {total_ok}/50 ({100*total_ok/50:.0f}%)")
print(f"  مقبول:  {total_warn}/50")
print(f"  فشل:    {total_err}/50")
print(f"\n  حسب الفئة:")
for cat, stats in categories.items():
    ok_pct = 100 * stats["ok"] / stats["total"] if stats["total"] > 0 else 0
    print(f"    {cat:8s}: {stats['ok']}/{stats['total']} OK ({ok_pct:.0f}%)")

# Failed questions
failed = [r for r in results if r["status"] == "ERR"]
if failed:
    print(f"\n  الأسئلة الفاشلة:")
    for r in failed:
        print(f"    - [{r['cat']}] {r['q'][:50]} | {r.get('error','')[:50]}")

with open("scripts/test_final_50_results.json", "w", encoding="utf-8") as f:
    json.dump({"total_ok": total_ok, "total_warn": total_warn, "total_err": total_err,
               "categories": categories, "results": results}, f, ensure_ascii=False, indent=2)
print(f"\n  محفوظة: scripts/test_final_50_results.json")
