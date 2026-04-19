# -*- coding: utf-8 -*-
"""test_prompt5.py — اختبار البرومبت الخامس (10 أسئلة)"""
import urllib.request, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:80/api/v1/query/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
MODEL = "openai"

QUESTIONS = [
    # التسريب الإنجليزي
    {"q": "هل يحق لصاحب العمل فصل الموظف بدون سبب؟", "expect": "عربي 100% - قانون العمل", "cat": "تسريب"},
    {"q": "ما الفرق بين الجنحة والجناية؟", "expect": "عربي 100% - قانون العقوبات", "cat": "تسريب"},
    # المنطق الاستدلالي
    {"q": "تم فصلي من العمل بعد تقديم شكوى داخلية ضد الشركة، هل يعتبر هذا فصل تعسفي؟", "expect": "فصل تعسفي + حماية مبلغين", "cat": "مركّب"},
    {"q": "شخص اعتدى علي ونشر فيديو الاعتداء على الإنترنت", "expect": "عقوبات + جرائم إلكترونية", "cat": "مركّب"},
    {"q": "شريكي أخذ أموال من الشركة بدون علمي", "expect": "شركات + عقوبات (اختلاس)", "cat": "مركّب"},
    # صياغة العقود
    {"q": "صيغ لي عقد إيجار شقة", "expect": "عقد إيجار احترافي", "cat": "عقد"},
    {"q": "أبي نموذج عقد عمل", "expect": "عقد عمل + قانون العمل", "cat": "عقد"},
    {"q": "اكتب لي مذكرة دفاع في قضية فصل تعسفي", "expect": "مذكرة قانونية", "cat": "عقد"},
    # لهجة + إملاء
    {"q": "ابي اعرف عن حقوقي في الشغل", "expect": "حقوق عمالية", "cat": "لهجة"},
    {"q": "كيف اقدم شكوا على الكفيل", "expect": "شكوى عمالية", "cat": "إملاء"},
]

def call_api(q):
    data = json.dumps({"query": q, "mode": "expert", "model": MODEL}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": KEY})
    resp = urllib.request.urlopen(req, timeout=90)
    return json.loads(resp.read().decode("utf-8"))

def has_english(text):
    """Check if text contains English sentences (not just single words)."""
    import re
    # Find sequences of 3+ English words
    eng = re.findall(r'[A-Za-z]{3,}(?:\s+[A-Za-z]{3,}){2,}', text)
    return eng

print("=" * 70)
print(f"  اختبار البرومبت الخامس — النموذج: {MODEL}")
print("=" * 70)

results = []
for i, item in enumerate(QUESTIONS):
    q, expect, cat = item["q"], item["expect"], item["cat"]
    print(f"\n{'─' * 70}")
    print(f"  [{cat}] سؤال {i+1}/10: {q}")
    print(f"  المتوقع: {expect}")
    print(f"{'─' * 70}")

    try:
        d = call_api(q)
        answer = d.get("answer", "")
        conf = d.get("confidence", 0)
        known = d.get("from_known_answer", False)
        sources = d.get("sources", [])

        # Check for English leakage
        eng_leaked = has_english(answer)
        leak_status = f"⚠️ تسريب EN: {eng_leaked[:2]}" if eng_leaked else "✅ عربي 100%"

        print(f"\n  📊 ثقة: {conf}% | {'known' if known else 'RAG'} | {leak_status}")

        # Print answer
        lines = answer.split("\n")
        print(f"\n  💬 الرد:")
        for line in lines[:20]:  # First 20 lines
            print(f"  {line}")
        if len(lines) > 20:
            print(f"  ... ({len(lines)-20} سطر إضافي)")

        # Sources
        if sources:
            print(f"\n  📚 مصادر RAG:")
            for j, src in enumerate(sources[:3]):
                print(f"    [{j+1}] {src.get('law_name','?')[:50]} | م.{src.get('article_number','?')} | {src.get('score',0):.2f}")

        results.append({"q": q, "cat": cat, "conf": conf, "eng_leak": bool(eng_leaked), "answer_len": len(answer), "status": "ok"})
    except Exception as e:
        print(f"\n  ❌ خطأ: {e}")
        results.append({"q": q, "cat": cat, "status": "error", "error": str(e)})
    time.sleep(3)

# Summary
print(f"\n\n{'=' * 70}")
print("  ملخص النتائج")
print("=" * 70)
ok = sum(1 for r in results if r["status"] == "ok")
leaks = sum(1 for r in results if r.get("eng_leak"))
print(f"  نجح: {ok}/10 | تسريب EN: {leaks}/10")
for r in results:
    s = "OK" if r["status"] == "ok" else "ERR"
    leak = "🔴EN" if r.get("eng_leak") else "🟢AR"
    print(f"  [{s}] [{leak}] conf={r.get('conf','?')} | [{r['cat']}] {r['q'][:40]}")

with open("scripts/test_prompt5_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n  محفوظة: scripts/test_prompt5_results.json")
