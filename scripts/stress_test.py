#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/stress_test.py — اختبار الحمل (Stress Test)
=====================================================
يُرسل 50 طلباً متزامناً إلى /api/v1/query ويقيس:
  - avg_ms    : متوسط وقت الاستجابة
  - p95_ms    : النسبة المئوية 95
  - p99_ms    : النسبة المئوية 99
  - error_rate: نسبة الأخطاء (هدف: < 1%)

الاستخدام:
  python scripts/stress_test.py                         # 50 طلب على localhost:8000
  python scripts/stress_test.py --n 100                 # تغيير عدد الطلبات
  python scripts/stress_test.py --url http://myhost:8000
  python scripts/stress_test.py --model ollama          # تحديد النموذج
  python scripts/stress_test.py --out results.json      # حفظ النتائج
"""
from __future__ import annotations

import sys, io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse
import asyncio
import json
import statistics
import time
import uuid
from pathlib import Path

try:
    import aiohttp
except ImportError:
    print("ERROR: aiohttp مطلوب — pip install aiohttp")
    sys.exit(1)

# ── قائمة الأسئلة المتنوعة ──────────────────────────────────────
QUERIES = [
    "كم مدة إشعار إنهاء عقد العمل في قطر؟",
    "ما هي حقوق العمال في قانون العمل القطري؟",
    "ما هي عقوبة الاحتيال المالي في القانون القطري؟",
    "ما هي شروط تسجيل شركة ذات مسؤولية محدودة في قطر؟",
    "ما هي إجراءات نقل ملكية العقار في قطر؟",
    "ما هي قوانين الطلاق والأحوال الشخصية في قطر؟",
    "ما هي عقوبات المرور وسحب رخصة القيادة؟",
    "ما هي شروط الحصول على الإقامة الدائمة في قطر؟",
    "كيف يتم تقديم شكوى عمالية في قطر؟",
    "ما هي حقوق المستهلك وفق قانون حماية المستهلك القطري؟",
]


async def single_request(
    session: "aiohttp.ClientSession",
    base_url: str,
    query: str,
    model: str,
    timeout: int,
) -> dict:
    """إرسال طلب واحد وإعادة نتيجة مفردة."""
    payload = {
        "query":      query,
        "session_id": str(uuid.uuid4()),
        "model":      model,
        "mode":       "expert",
    }
    t0 = time.perf_counter()
    try:
        async with session.post(
            f"{base_url}/api/v1/query",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            ms = (time.perf_counter() - t0) * 1000
            body = await resp.json(content_type=None)
            success = resp.status == 200
            return {
                "ok":         success,
                "status":     resp.status,
                "ms":         ms,
                "confidence": body.get("confidence") if success else None,
                "error":      None if success else body.get("detail", str(resp.status)),
            }
    except asyncio.TimeoutError:
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": False, "status": 0, "ms": ms, "confidence": None, "error": "timeout"}
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": False, "status": 0, "ms": ms, "confidence": None, "error": str(exc)}


async def run_stress(
    base_url: str,
    n: int,
    model: str,
    timeout: int,
    concurrency: int,
) -> dict:
    """تشغيل n طلباً بـ concurrency متزامن."""
    # بناء قائمة الطلبات (دوري على QUERIES)
    tasks_queries = [QUERIES[i % len(QUERIES)] for i in range(n)]

    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Health check أولاً
        try:
            async with session.get(f"{base_url}/api/v1/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    print(f"⚠️  Health check فشل — {r.status}. هل السيرفر يعمل على {base_url}?")
                    sys.exit(1)
        except Exception as exc:
            print(f"⚠️  لا يمكن الوصول إلى {base_url}: {exc}")
            sys.exit(1)

        print(f"✅ السيرفر متاح — بدء اختبار الحمل ({n} طلب، {concurrency} متزامن) …\n")
        wall_t0 = time.perf_counter()

        # إرسال جميع الطلبات بشكل متزامن
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded(q: str) -> dict:
            async with semaphore:
                return await single_request(session, base_url, q, model, timeout)

        results = await asyncio.gather(*[bounded(q) for q in tasks_queries])
        wall_ms = (time.perf_counter() - wall_t0) * 1000

    return {"results": results, "wall_ms": wall_ms}


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    data_sorted = sorted(data)
    idx = int(len(data_sorted) * p / 100)
    idx = min(idx, len(data_sorted) - 1)
    return round(data_sorted[idx], 1)


def analyse(raw: dict, n: int) -> dict:
    results  = raw["results"]
    wall_ms  = raw["wall_ms"]

    ok_results  = [r for r in results if r["ok"]]
    err_results = [r for r in results if not r["ok"]]

    all_ms  = [r["ms"] for r in results]
    ok_ms   = [r["ms"] for r in ok_results]

    error_rate   = len(err_results) / len(results) * 100 if results else 100.0
    avg_ms       = round(statistics.mean(all_ms), 1)   if all_ms  else 0.0
    p95          = percentile(all_ms, 95)
    p99          = percentile(all_ms, 99)
    min_ms       = round(min(all_ms), 1) if all_ms else 0.0
    max_ms       = round(max(all_ms), 1) if all_ms else 0.0

    confidences  = [r["confidence"] for r in ok_results if r["confidence"] is not None]
    avg_conf     = round(statistics.mean(confidences), 1) if confidences else None

    throughput   = round(len(results) / (wall_ms / 1000), 1) if wall_ms > 0 else 0

    # Error breakdown
    error_counts: dict[str, int] = {}
    for r in err_results:
        key = r.get("error") or str(r.get("status", "unknown"))
        error_counts[key] = error_counts.get(key, 0) + 1

    return {
        "total":        len(results),
        "success":      len(ok_results),
        "errors":       len(err_results),
        "error_rate":   round(error_rate, 2),
        "avg_ms":       avg_ms,
        "p95_ms":       p95,
        "p99_ms":       p99,
        "min_ms":       min_ms,
        "max_ms":       max_ms,
        "avg_confidence": avg_conf,
        "wall_ms":      round(wall_ms, 1),
        "throughput_rps": throughput,
        "error_breakdown": error_counts,
        # Targets
        "targets": {
            "error_rate_pct": {"value": round(error_rate, 2), "target": "< 1%",  "pass": error_rate < 1.0},
            "p95_ms":         {"value": p95,                  "target": "< 3000", "pass": p95 < 3000},
            "avg_ms":         {"value": avg_ms,               "target": "< 1500", "pass": avg_ms < 1500},
        },
    }


def print_report(stats: dict) -> None:
    ok_icon    = lambda v: "✅" if v else "❌"
    sep        = "─" * 50

    print(sep)
    print("  📊  نتائج اختبار الحمل")
    print(sep)
    print(f"  الطلبات الكلية  : {stats['total']}")
    print(f"  ناجحة           : {stats['success']}")
    print(f"  فاشلة           : {stats['errors']}")
    print(sep)
    print(f"  متوسط الوقت     : {stats['avg_ms']} ms  {ok_icon(stats['targets']['avg_ms']['pass'])}")
    print(f"  P95             : {stats['p95_ms']} ms  {ok_icon(stats['targets']['p95_ms']['pass'])}")
    print(f"  P99             : {stats['p99_ms']} ms")
    print(f"  أقل وقت         : {stats['min_ms']} ms")
    print(f"  أعلى وقت        : {stats['max_ms']} ms")
    print(sep)
    print(f"  نسبة الأخطاء    : {stats['error_rate']}%  {ok_icon(stats['targets']['error_rate_pct']['pass'])}")
    print(f"  الإنتاجية       : {stats['throughput_rps']} req/s")
    if stats["avg_confidence"] is not None:
        print(f"  متوسط الثقة     : {stats['avg_confidence']}%")
    print(sep)

    all_pass = all(t["pass"] for t in stats["targets"].values())
    if all_pass:
        print("  🎉  جميع الأهداف محققة!")
    else:
        print("  ⚠️  بعض الأهداف لم تتحقق:")
        for name, t in stats["targets"].items():
            if not t["pass"]:
                print(f"     • {name}: {t['value']} (الهدف: {t['target']})")

    if stats["error_breakdown"]:
        print(sep)
        print("  تفاصيل الأخطاء:")
        for err, cnt in stats["error_breakdown"].items():
            print(f"     • {err}: {cnt}")

    print(sep)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress test للمساعد القانوني")
    parser.add_argument("--url",    default="http://localhost:8000", help="Base URL للسيرفر")
    parser.add_argument("--n",      type=int, default=50,            help="عدد الطلبات (افتراضي: 50)")
    parser.add_argument("--model",  default="ollama",                help="النموذج (ollama/openai/claude/gemini)")
    parser.add_argument("--timeout",type=int, default=30,            help="مهلة الطلب بالثواني (افتراضي: 30)")
    parser.add_argument("--concurrency", type=int, default=10,       help="الطلبات المتزامنة (افتراضي: 10)")
    parser.add_argument("--out",    default=None,                    help="حفظ النتائج JSON في ملف")
    args = parser.parse_args()

    raw   = asyncio.run(run_stress(args.url, args.n, args.model, args.timeout, args.concurrency))
    stats = analyse(raw, args.n)

    print_report(stats)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  💾 النتائج محفوظة في: {out_path}")

    # Exit code: 0 إذا نجحت كل الأهداف، 1 إذا فشل أي منها
    all_pass = all(t["pass"] for t in stats["targets"].values())
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
