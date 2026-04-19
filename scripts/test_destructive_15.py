# -*- coding: utf-8 -*-
"""test_destructive_15.py — اختبار تدميري 15 سؤال شديد التعقيد"""
import urllib.request, json, time, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:80/api/v1/query/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
MODEL = "openai"

QUESTIONS = [
    "أنا قطري الجنسية متزوج من امرأة بريطانية منذ 12 سنة ولدينا 4 أطفال يحملون جنسيتين. زوجتي اكتشفت أنني تزوجت زواجاً شرعياً ثانياً من قطرية قبل سنة بدون علمها. الآن زوجتي الأولى تطلب الطلاق للضرر أمام المحكمة القطرية وفي نفس الوقت رفعت دعوى في لندن تطلب حضانة الأطفال والنصف من ثروتي. زوجتي الثانية حامل وتطلب نفقة. أي محكمة لها الاختصاص؟ وكيف يتم تقسيم الثروة بين نظامين قانونيين مختلفين؟ صيغ لي مذكرة دفاع شاملة.",
    "أنا عضو مجلس إدارة في شركة مساهمة قطرية مدرجة في بورصة قطر. اكتشفنا أن المدير التنفيذي حوّل 15 مليون لشركات وهمية وتلاعب بالقوائم المالية ووزّع أرباحاً وهمية. الشركة على حافة الإفلاس والمساهمون يهددون بمقاضاة مجلس الإدارة. هل أنا مسؤول كعضو مجلس إدارة؟ صيغ لي مذكرة دفاع عن نفسي + لائحة دعوى ضد المدير التنفيذي.",
    "ابني (22 سنة مهندس) توفي في حادث. 4 أطراف مسؤولة: سائق شاحنة + حفرة في الطريق لم تُصلح + إشارة مرور معطلة + عيب في مكابح السيارة. ابني كان يعيل والدته المطلقة وأخته القاصرة. راتبه المتوقع 25,000 ريال. صيغ لي لائحة دعوى تعويض شاملة ضد جميع الأطراف مع حساب تفصيلي للتعويض.",
    "أسست تطبيق توصيل طعام واستثمرت 8 مليون. المدير التقني نسخ الكود وقاعدة بيانات 200,000 عميل وأنشأ تطبيقاً منافساً من دبي. استقطب 15 مطوراً و8 مندوبي مبيعات مع بند عدم منافسة ساري. صيغ لي: بلاغ جنائي + طلب أمر مستعجل + دعوى تعويض + شكوى حماية بيانات.",
    "جدي المتوفى ترك تركة ضخمة (145 مليون ريال). وصية بخط يده يحوّل المجمع التجاري لوقف ويوصي لي بثلث التركة ويحرم ابنه. الورثة: 6 أبناء من 3 زوجات + 7 أحفاد. نزاع على الوصية والوقف والشراكة في أرض. صيغ لي مذكرة قانونية شاملة بالتقسيم الشرعي.",
    "شركتي أبرمت عقد توريد معدات طبية مع شركة حكومية سعودية بـ 50 مليون. حكم تحكيم ICC لصالحنا بـ 55 مليون. الشركة السعودية تتمسك بحصانة الدولة. لديها أصول في قطر. صيغ لي طلب تنفيذ الحكم مع طلب حجز تحفظي.",
    "صيغ لي مذكرة دفاع — أنا مدير مالي متهم بـ: تزوير قوائم مالية م.238 عقوبات + خيانة أمانة م.354 + غسيل أموال. عندي محاضر مجلس إدارة وإيميلات من المدير التنفيذي وعقود موردين. المذكرة يجب أن تتضمن دفوع شكلية وموضوعية لكل تهمة مع أرقام المواد وأحكام تمييز.",
    "أنا CEO بنك رقمي في QFC. اختراق إلكتروني سرق بيانات 50,000 عميل. عميل كبير خسر 2 مليون. QFCRA تهدد بسحب الترخيص. لم نبلّغ خلال 72 ساعة. صيغ لي: خطة استجابة قانونية + مذكرة دفاع + رد على إنذار QFCRA.",
    "بنيت فيلا بـ 4 مليون على أرض ورثتها. البلدية اكتشفت أن ترخيص البناء مزوّر من المكتب الهندسي. قرار إزالة فوري. أنا حسن النية وعائلتي ساكنة والبنك عنده رهن. صيغ لي: طعن في قرار الإزالة + دعوى تعويض + طلب وقف تنفيذ.",
    "شركتي (مشترك قطري 51% وياباني 49%) عقد BOT لمحطة تحلية مع هيئة حكومية — 2 مليار ريال 25 سنة. الحكومة تريد تخفيض التعرفة 30% وتأخرت في السداد 300 مليون. الشريك الياباني يريد الخروج. صيغ لي مذكرة قانونية شاملة.",
    "صيغ لي مذكرة طعن بالتمييز — حكم استئناف ألزمني بدفع 3 مليون لشريكي السابق. أعترض: لم أُناقش تقرير الخبير + التقادم 6 سنوات + حساب خاطئ لم يخصم 4 مليون ديون + تجاهل شرط التحكيم.",
    "صيغ لي عقد EPC — بناء مجمع سكني 200 شقة في لوسيل. صاحب المشروع قطري والمقاول تركي. 500 مليون ريال. 30 شهراً. دفعة مقدمة 15%. ضمان بنكي 10%. غرامة تأخير 0.1% يومياً. ضمان 10 سنوات هيكل. قوة قاهرة تشمل أوبئة. تحكيم ICC.",
    "صيغ لي مذكرة دفاع — موكلي طبيب جراح متهم بقتل مريض خطأً م.305. العملية كانت روتينية لكن المريض لم يُبلّغ عن أدوية سيولة + طبيب التخدير أخطأ + المستشفى لم يوفر جهاز مراقبة. عندي فيديو العملية وخطابات للإدارة.",
    "أملك 20% من شركة عائلية. أبناء عمي (80%) لم يوزعوا أرباح 5 سنوات + عيّنوا أنفسهم برواتب مبالغة + أجّروا عقارات الشركة لأنفسهم بأقل من السوق + رفضوا إطلاعي على القوائم + خفّضوا حصتي من 20% لـ 8%. صيغ لي حزمة قانونية كاملة.",
    "أريد تأسيس منصة FinTech في قطر: دفع إلكتروني + تحويلات + إقراض جماعي + عملات رقمية. المستثمرون: قطري 40% + بريطاني 35% + هندي 25%. رأس مال 30 مليون. أحتاج: هيكل قانوني + تراخيص + عقد تأسيس + اتفاقية مساهمين + سياسة بيانات + سياسة مكافحة غسيل أموال + عقد مدير تنفيذي.",
]

def call_api(q):
    data = json.dumps({"query": q, "mode": "expert", "model": MODEL}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": KEY})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=180)
    elapsed = time.time() - t0
    return json.loads(resp.read().decode("utf-8")), elapsed

results = []
total_conf = 0
total_time = 0

print("=" * 70)
print(f"  اختبار تدميري — {len(QUESTIONS)} سؤال — النموذج: {MODEL}")
print("=" * 70)

for i, q in enumerate(QUESTIONS):
    print(f"\n{'='*70}")
    print(f"  #{i+1} | {q[:50]}...")
    print(f"{'='*70}")
    try:
        d, elapsed = call_api(q)
        answer = d.get("answer", "")
        conf = d.get("confidence", 0) or 0
        total_conf += conf
        total_time += elapsed

        article_refs = re.findall(r'الماد[ةه]\s*\(?\s*\d+\s*\)?', answer)
        law_refs = re.findall(r'قانون\s+\S+\s+رقم\s+\d+', answer)
        tamyeez_refs = re.findall(r'(?:طعن|الطعن|التمييز في)\s*(?:رقم)?\s*\d+', answer)
        linked = bool(article_refs and tamyeez_refs)
        has_bismillah = 'بسم الله' in answer
        has_irac = any(k in answer for k in ['المسألة:', 'القاعدة:', 'التطبيق:', 'بإنزال', 'ولما كان', 'ومن ثم'])

        print(f"  طول: {len(answer)} | conf={conf}% | وقت={elapsed:.1f}s")
        print(f"  مواد={len(article_refs)} | قوانين={len(law_refs)} | تمييز={len(tamyeez_refs)} | مترابط={linked}")
        print(f"  بسم_الله={has_bismillah} | IRAC={has_irac}")
        print(f"\n  الرد الكامل:")
        print(f"  {'─'*50}")
        for line in answer.split('\n'):
            print(f"  {line}")
        print(f"  {'─'*50}")

        results.append({"num": i+1, "len": len(answer), "conf": conf, "time": elapsed,
                        "articles": len(article_refs), "laws": len(law_refs),
                        "tamyeez": len(tamyeez_refs), "linked": linked,
                        "bismillah": has_bismillah, "irac": has_irac, "status": "ok"})
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"num": i+1, "status": "error", "error": str(e)[:100]})
    time.sleep(5)

# Summary
ok = [r for r in results if r.get("status") == "ok"]
print(f"\n\n{'='*70}")
print(f"  ملخص الاختبار التدميري")
print(f"{'='*70}")
print(f"  نجح: {len(ok)}/15")
print(f"  متوسط الثقة: {total_conf/max(len(ok),1):.0f}%")
print(f"  متوسط الوقت: {total_time/max(len(ok),1):.1f}s")
print(f"  متوسط الطول: {sum(r.get('len',0) for r in ok)/max(len(ok),1):.0f} chars")

drafting = [r for r in ok if r.get("bismillah")]
print(f"\n  مذكرات/عقود (بسم الله): {len(drafting)}/15")
with_articles = [r for r in ok if r.get("articles", 0) > 0]
print(f"  ذكرت أرقام مواد: {len(with_articles)}/15")
with_tamyeez = [r for r in ok if r.get("tamyeez", 0) > 0]
print(f"  ذكرت أحكام تمييز: {len(with_tamyeez)}/15")
with_linked = [r for r in ok if r.get("linked")]
print(f"  ربطت بين المادة والحكم: {len(with_linked)}/15")
with_irac = [r for r in ok if r.get("irac")]
print(f"  استخدمت IRAC: {len(with_irac)}/15")

longest = max(ok, key=lambda r: r.get("len", 0))
shortest = min(ok, key=lambda r: r.get("len", 0))
print(f"\n  أطول رد: #{longest['num']} ({longest['len']} chars)")
print(f"  أقصر رد: #{shortest['num']} ({shortest['len']} chars)")

with open("scripts/test_destructive_15_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n  محفوظة: scripts/test_destructive_15_results.json")
