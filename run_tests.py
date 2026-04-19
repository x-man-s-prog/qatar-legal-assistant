# -*- coding: utf-8 -*-
"""تشغيل الاختبارات وحفظ النتائج في ملف — يعمل مع Ollama البطيء"""
import sys, io, json, time, urllib.request, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://localhost:8000"
OUT  = r"C:\Users\sa2005599\Desktop\المساعد القانوني\الكود\test_results.json"

TESTS = [
    {"id": 1, "q": "شخص سرق من منزل مسكون بالقوة ليلاً وكان يحمل سلاحاً، ما العقوبة؟"},
    {"id": 2, "q": "رجل توفي وخلف زوجتين وثلاثة أبناء وبنتين، كيف تُوزَّع التركة؟"},
    {"id": 3, "q": "عملت 7 سنوات في شركة خاصة وفصلوني بدون سبب ويرفضون مكافأة نهاية الخدمة، ما حقوقي؟"},
    {"id": 4, "q": "شخص يهددني بنشر صوري الخاصة مقابل المال، ما العقوبة وكيف أرفع شكوى؟"},
    {"id": 5, "q": "مالك الشقة يريد طردي قبل انتهاء عقد الإيجار، هل يحق له ذلك؟"},
    {"id": 6, "q": "صدر قرار بإحالتي للتقاعد المبكر رغم أنني لم أبلغ سن التقاعد، ما الإجراءات؟"},
    {"id": 7, "q": "أعطاني شخص شيك بدون رصيد بقيمة 50000 ريال، ما الإجراءات والعقوبة؟"},
    {"id": 8, "q": "طُلقت وعندي أطفال عمرهم 4 و7 و12 سنة، من يحق له الحضانة ومتى تنتهي؟"},
    {"id": 9, "q": "تسببت بحادث سيارة أدى لوفاة شخص بسبب الإهمال، ما التبعات الجنائية والمدنية؟"},
    {"id": 10, "q": "ما حكم هذا؟"},
]

def call_debug(q):
    url = f"{BASE}/api/v1/debug_search?q={urllib.parse.quote(q)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

def call_query(q, sid):
    url  = f"{BASE}/api/v1/query/"
    body = json.dumps({"query": q, "model": "ollama", "session_id": sid},
                      ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(url, data=body,
                                  headers={"Content-Type":"application/json; charset=utf-8"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=200) as r:
            data = json.loads(r.read().decode("utf-8"))
        data["_ok"] = True
        data["_lat"] = round(time.time()-t0, 1)
        return data
    except Exception as e:
        return {"_ok": False, "_err": str(e), "_lat": round(time.time()-t0, 1)}

results = []
for tc in TESTS:
    i, q = tc["id"], tc["q"]
    print(f"[{i}/10] {q[:60]}...", flush=True)

    dbg = call_debug(q)
    print(f"  debug: domain={dbg.get('dre_detected_domain','?')} relevance={dbg.get('relevance_check','?')}")
    print(f"  DRE top1: {(dbg.get('top3_after_dre') or [{}])[0].get('law','?')[:50]}")

    r = call_query(q, f"tc_{i}")
    status = "OK" if r.get("_ok") else f"ERR: {r.get('_err','?')[:50]}"
    print(f"  query: {status} | lat={r.get('_lat')}s | conf={r.get('confidence','?')}% | srcs={len(r.get('sources',[]))}")

    entry = {
        "id": i, "q": q,
        "debug": {
            "domain": dbg.get("dre_detected_domain",""),
            "relevance": dbg.get("relevance_check", False),
            "top3_before": [(c.get("law","")[:50], c.get("year",""), c.get("score",0))
                            for c in dbg.get("top3_before_dre",[])[:3]],
            "top3_after":  [(c.get("law","")[:50], c.get("year",""), c.get("dre_score",0))
                            for c in dbg.get("top3_after_dre",[])[:3]],
            "cot_primary_law": dbg.get("cot_primary_law",""),
        },
        "answer": {
            "ok": r.get("_ok", False),
            "error": r.get("_err",""),
            "latency": r.get("_lat"),
            "confidence": r.get("confidence", 0),
            "answer_len": len(r.get("answer","")),
            "answer_preview": r.get("answer","")[:500],
            "sources": [(s.get("law_name","")[:50], s.get("article_number",""), s.get("law_year",""))
                        for s in r.get("sources",[])[:5]],
            "warnings": r.get("hallucination_warnings",[]),
        }
    }
    results.append(entry)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  محفوظ. ({i}/10 مكتمل)\n")

print(f"\nاكتمل. النتائج في: {OUT}")
