# -*- coding: utf-8 -*-
"""
test_prompt4.py — اختبار البرومبت الرابع مع OpenAI (10 أسئلة)
يعرض الرد الكامل + أول 3 نتائج RAG + التقييم
"""
import urllib.request
import json
import time
import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API = "http://localhost:80/api/v1/query/"
KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
MODEL = "openai"

QUESTIONS = [
    {"q": "مساء الخير", "expect": "تحية فقط بدون قانون"},
    {"q": "ما عقوبة القيادة بدون رخصة؟", "expect": "إجابة من قانون المرور أو اعتذار"},
    {"q": "هل يحق لصاحب العمل فصل الموظف بدون سبب؟", "expect": "إجابة من قانون العمل م61-63"},
    {"q": "ما هي سن المسؤولية الجنائية في قطر؟", "expect": "إجابة صحيحة أو اعتذار"},
    {"q": "هل يجوز تسجيل مكالمة بدون علم الطرف الآخر؟", "expect": "قانون العقوبات أو الجرائم الإلكترونية"},
    {"q": "اشتريت سيارة واتضح فيها عيب، هل أستطيع إرجاعها؟", "expect": "القانون المدني ضمان العيوب الخفية"},
    {"q": "واحد ظلمني، وش أسوي؟", "expect": "سؤال توضيحي"},
    {"q": "شخص نشر صورتي بدون إذني", "expect": "قانون العقوبات أو الجرائم الإلكترونية"},
    {"q": "هل يحق للشرطة تفتيش الهاتف؟", "expect": "قانون الإجراءات الجنائية"},
    {"q": "ما الفرق بين الجنحة والجناية؟", "expect": "قانون العقوبات م24-25"},
]


def call_api(question, model=MODEL):
    data = json.dumps(
        {"query": question, "mode": "expert", "model": model},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        API,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-API-Key": KEY,
        },
    )
    resp = urllib.request.urlopen(req, timeout=90)
    return json.loads(resp.read().decode("utf-8"))


def main():
    print("=" * 70)
    print(f"  اختبار البرومبت الرابع — النموذج: {MODEL}")
    print(f"  عدد الأسئلة: {len(QUESTIONS)}")
    print("=" * 70)

    results = []

    for i, item in enumerate(QUESTIONS):
        q = item["q"]
        expect = item["expect"]
        print(f"\n{'─' * 70}")
        print(f"  سؤال {i+1}/10: {q}")
        print(f"  المتوقع: {expect}")
        print(f"{'─' * 70}")

        try:
            d = call_api(q)
            answer = d.get("answer", "")
            conf = d.get("confidence", 0)
            known = d.get("from_known_answer", False)
            sources = d.get("sources", [])
            conf_action = d.get("confidence_action", "")
            cot = d.get("cot_analysis", {})
            domain = cot.get("law_domain", "") if cot else ""
            primary_law = cot.get("primary_law", "") if cot else ""

            print(f"\n  📊 مستوى الثقة: {conf}% | {'known_answer' if known else 'RAG'} | {conf_action}")
            if domain:
                print(f"  📁 المجال: {domain} | القانون الحاكم: {primary_law}")

            print(f"\n  💬 الرد الكامل:")
            print(f"  {'─' * 50}")
            # Print answer with indentation
            for line in answer.split("\n"):
                print(f"  {line}")
            print(f"  {'─' * 50}")

            if sources:
                print(f"\n  📚 أول 3 نتائج RAG:")
                for j, src in enumerate(sources[:3]):
                    law = src.get("law_name", "?")
                    art = src.get("article_number", "?")
                    score = src.get("score", 0)
                    print(f"    [{j+1}] {law[:50]} | م.{art} | صلة: {score:.2f}")

            results.append({
                "q": q,
                "expect": expect,
                "conf": conf,
                "known": known,
                "answer_len": len(answer),
                "sources_count": len(sources),
                "status": "ok",
            })

        except Exception as e:
            print(f"\n  ❌ خطأ: {e}")
            results.append({
                "q": q,
                "expect": expect,
                "status": "error",
                "error": str(e),
            })

        time.sleep(3)  # Rate limit

    # Summary
    print(f"\n\n{'=' * 70}")
    print("  ملخص النتائج")
    print("=" * 70)
    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")
    print(f"  نجح: {ok_count}/10 | فشل: {err_count}/10")
    for r in results:
        status = "OK" if r["status"] == "ok" else "ERR"
        conf = r.get("conf", "?")
        print(f"  [{status}] conf={conf} | {r['q'][:40]}")

    # Save JSON
    with open("scripts/test_prompt4_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  النتائج محفوظة: scripts/test_prompt4_results.json")


if __name__ == "__main__":
    main()
