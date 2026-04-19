#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/phase14_bench.py — اختبار Phase 14
20 سؤال قانوني مع المقارنة قبل/بعد known_answers الجديدة
"""
import json, time, urllib.request, sys

BASE_URL = "http://localhost:80"
MODEL = "gemini"   # ollama unhealthy — use gemini for RAG questions
API_KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"

# ── النتائج السابقة من Phase 13 (قبل) ─────────────────────────
PHASE13_RESULTS = {
    "q01": 100, "q02":  39, "q03":  31, "q04":  45,
    "q05":  57, "q06":  42, "q07": 100, "q08": 100,
    "q09":  38, "q10":  61, "q11": 100, "q12":  49,
    "q13":  75, "q14":  63, "q15":  44, "q16":  51,
    "q17": 100, "q18":  67, "q19": 100, "q20": 100,
}

# ── الـ20 سؤال (مُعاد بناؤها من BENCHMARK_REPORT + summary) ────
QUESTIONS = [
    {"id": "q01", "type": "known",   "query": "كم مدة إشعار إنهاء عقد العمل بعد سنتين في قطر؟"},
    {"id": "q02", "type": "rag",     "query": "ما حقوقي إذا فُصلت تعسفياً من العمل؟"},
    {"id": "q03", "type": "rag",     "query": "كم إجازتي السنوية في القانون القطري؟"},
    {"id": "q04", "type": "rag",     "query": "ما نص المادة 54 من قانون العمل القطري؟"},
    {"id": "q05", "type": "rag",     "query": "ما شروط الحضانة في قانون الأسرة القطري؟"},
    {"id": "q06", "type": "rag",     "query": "هل يحق لي الاستقالة الفورية بدون إشعار؟"},
    {"id": "q07", "type": "known",   "query": "ما عقوبة السرقة في القانون القطري؟"},
    {"id": "q08", "type": "known",   "query": "ما عقوبة القتل العمد في قطر؟"},
    {"id": "q09", "type": "rag",     "query": "ما عقوبة حيازة المخدرات في قطر؟"},
    {"id": "q10", "type": "rag",     "query": "ما ساعات العمل اليومية في القانون القطري؟"},
    {"id": "q11", "type": "known",   "query": "ما مكافأة نهاية الخدمة في قانون العمل القطري؟"},
    {"id": "q12", "type": "rag",     "query": "ما شروط الطلاق في القانون القطري؟"},
    {"id": "q13", "type": "rag",     "query": "من يحق له حضانة الأطفال بعد الطلاق في قطر؟"},
    {"id": "q14", "type": "rag",     "query": "ما عقوبة الاعتداء الجسدي في قطر؟"},
    {"id": "q15", "type": "rag",     "query": "ما الحد الأدنى لسن الزواج في قطر؟"},
    {"id": "q16", "type": "rag",     "query": "كيف أرفع دعوى قضائية في قطر؟"},
    {"id": "q17", "type": "known",   "query": "كيف أحصل على رد الاعتبار في قطر؟"},
    {"id": "q18", "type": "rag",     "query": "كيف أرفع شكوى عمالية في قطر؟"},
    {"id": "q19", "type": "conv",    "query": "ما اسمك وما هي قدراتك؟"},
    {"id": "q20", "type": "conv",    "query": "هل تستطيع مساعدتي في أمور غير قانونية؟"},
]

def call_api(query: str) -> tuple[float, int, float]:
    payload = json.dumps({"query": query, "mode": "expert", "model": MODEL}, ensure_ascii=False).encode("utf-8")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/v1/query/",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": API_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        ms = (time.time() - t0) * 1000
        return float(data.get("confidence", 0)), len(data.get("sources", [])), ms
    except Exception as e:
        ms = (time.time() - t0) * 1000
        print(f"  ERROR: {e}", file=sys.stderr)
        return 0.0, 0, ms

def emoji(conf: float) -> str:
    if conf >= 55: return "OK "
    if conf >= 35: return "~~ "
    return "XX "

print(f"\n{'='*70}")
print("  Phase 14 Benchmark — المقارنة قبل/بعد")
print(f"  النموذج: {MODEL} | الأسئلة: {len(QUESTIONS)}")
print(f"{'='*70}\n")
print(f"  {'Q':4}  {'قبل':>5}  {'بعد':>5}  {'فرق':>5}  {'نوع':6}  السؤال")
print(f"  {'-'*65}")

results = []
total_before = 0
total_after  = 0

for q in QUESTIONS:
    conf_before = PHASE13_RESULTS.get(q["id"], 0)
    conf_after, sources, ms = call_api(q["query"])

    delta = conf_after - conf_before
    delta_str = f"+{delta:.0f}" if delta > 0 else f"{delta:.0f}"
    em = emoji(conf_after)

    print(f"  {q['id']:4}  {conf_before:5.0f}  {conf_after:5.0f}  {delta_str:>5}  "
          f"{q['type']:6}  {em} {q['query'][:38]}")

    results.append({
        "id": q["id"], "type": q["type"],
        "before": conf_before, "after": conf_after,
        "delta": delta, "sources": sources, "ms": ms,
    })
    total_before += conf_before
    total_after  += conf_after

# ── ملخص ──────────────────────────────────────────────────────
pass_after  = sum(1 for r in results if r["after"] >= 55)
pass_before = sum(1 for r in results if r["before"] >= 55)

print(f"\n{'='*70}")
print("  الملخص")
print(f"{'='*70}")
print(f"  avg confidence   qbl: {total_before/len(results):.1f}%   bad: {total_after/len(results):.1f}%")
print(f"  OK conf>=55%     qbl: {pass_before}/20        bad: {pass_after}/20")

improved = [r for r in results if r["after"] > r["before"]]
regressed = [r for r in results if r["after"] < r["before"] - 5]
print(f"  muhassan: {len(improved)}   munhadar: {len(regressed)}")

if regressed:
    print("  [!] تراجع في:", [r["id"] for r in regressed])

print(f"{'='*70}\n")

# حفظ JSON
out_path = "phase14_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"questions": results,
               "avg_before": total_before/len(results),
               "avg_after":  total_after/len(results)}, f, ensure_ascii=False, indent=2)
print(f"✅ النتائج محفوظة: {out_path}")
