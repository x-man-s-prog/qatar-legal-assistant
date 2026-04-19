#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/benchmark.py — قياس جودة النظام
=========================================
يُقيّم النظام على 20 سؤال قانوني قطري ويُنتج تقرير JSON.

الاستخدام:
  python scripts/benchmark.py                 # mock mode
  python scripts/benchmark.py --live          # live API mode (يتطلب تشغيل السيرفر)
  python scripts/benchmark.py --out report.json

المعايير:
  avg_ms          — متوسط وقت الاستجابة
  avg_confidence  — متوسط مستوى الثقة (هدف: > 70)
  citation_rate   — نسبة الإجابات بمصادر قانونية (هدف: > 80%)
  success_rate    — نسبة الإجابات التي تحتوي كلمات مفتاحية
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# ── 20 سؤال قانوني قطري حقيقي ─────────────────────────────────
QUESTIONS = [
    # ── قانون العمل ──────────────────────────────────────────
    {
        "id":               "q01",
        "category":         "عمالي",
        "query":            "كم مدة إشعار إنهاء عقد العمل في قطر؟",
        "must_contain_any": ["شهر", "30", "إشعار", "مهلة"],
        "must_cite":        True,
    },
    {
        "id":               "q02",
        "category":         "عمالي",
        "query":            "ما هي مكافأة نهاية الخدمة في قانون العمل القطري؟",
        "must_contain_any": ["مكافأة", "خدمة", "راتب", "سنة"],
        "must_cite":        True,
    },
    {
        "id":               "q03",
        "category":         "عمالي",
        "query":            "ما مدة الإجازة السنوية المستحقة للعامل في قطر؟",
        "must_contain_any": ["إجازة", "أسبوع", "يوم", "سنة"],
        "must_cite":        True,
    },
    {
        "id":               "q04",
        "category":         "عمالي",
        "query":            "هل يحق لصاحب العمل فصل العامل دون سبب مشروع؟",
        "must_contain_any": ["فصل", "تعسف", "تعويض", "مشروع"],
        "must_cite":        True,
    },
    # ── قانون الأسرة ───────────────────────────────────��──────
    {
        "id":               "q05",
        "category":         "أسري",
        "query":            "ما إجراءات الطلاق في القانون القطري؟",
        "must_contain_any": ["طلاق", "محكمة", "إجراءات", "زوجة"],
        "must_cite":        True,
    },
    {
        "id":               "q06",
        "category":         "أسري",
        "query":            "من يحق له حضانة الأطفال بعد الطلاق في قطر؟",
        "must_contain_any": ["حضانة", "أم", "أب", "طفل"],
        "must_cite":        True,
    },
    {
        "id":               "q07",
        "category":         "أسري",
        "query":            "ما شروط المهر في قانون الأسرة القطري؟",
        "must_contain_any": ["مهر", "زواج", "شرط", "عقد"],
        "must_cite":        True,
    },
    # ── قانون العقوبات ────────────────────────────────────────
    {
        "id":               "q08",
        "category":         "جزائي",
        "query":            "ما عقوبة السرقة في القانون القطري؟",
        "must_contain_any": ["عقوبات", "سجن", "حبس", "غرامة"],
        "must_cite":        True,
    },
    {
        "id":               "q09",
        "category":         "جزائي",
        "query":            "ما عقوبة الاعتداء الجسدي في قطر؟",
        "must_contain_any": ["عقوبات", "حبس", "غرامة", "اعتداء"],
        "must_cite":        True,
    },
    {
        "id":               "q10",
        "category":         "جزائي",
        "query":            "ما حكم الاحتيال والنصب في القانون القطري؟",
        "must_contain_any": ["احتيال", "نصب", "عقوبة", "غرامة"],
        "must_cite":        True,
    },
    # ── قانون الإيجارات ───────────────────────────────────────
    {
        "id":               "q11",
        "category":         "مدني",
        "query":            "ما حقوق المستأجر عند رفع الإيجار في قطر؟",
        "must_contain_any": ["إيجار", "مستأجر", "لجنة", "رفع"],
        "must_cite":        True,
    },
    {
        "id":               "q12",
        "category":         "مدني",
        "query":            "متى يحق لصاحب العقار إخلاء المستأجر؟",
        "must_contain_any": ["إخلاء", "مستأجر", "مالك", "عقد"],
        "must_cite":        True,
    },
    # ── قانون الشركات ─────────────────────────────────────────
    {
        "id":               "q13",
        "category":         "تجاري",
        "query":            "ما شروط تأسيس شركة ذات مسؤولية محدودة في قطر؟",
        "must_contain_any": ["شركة", "تأسيس", "رأس مال", "ترخيص"],
        "must_cite":        True,
    },
    # ── قانون المرور ──────────────────────────────��───────────
    {
        "id":               "q14",
        "category":         "مرور",
        "query":            "ما عقوبة القيادة تحت تأثير الكحول في قطر؟",
        "must_contain_any": ["مرور", "كحول", "غرامة", "سحب"],
        "must_cite":        True,
    },
    # ── قانون الإقامة ─────────────────────────────────────────
    {
        "id":               "q15",
        "category":         "إقامة",
        "query":            "ما شروط الحصول على الإقامة الدائمة في قطر؟",
        "must_contain_any": ["إقامة", "إقامة دائمة", "سنة", "شروط"],
        "must_cite":        True,
    },
    # ── أسئلة خارج النطاق ──────────────────────��─────────────
    {
        "id":               "q16",
        "category":         "خارج النطاق",
        "query":            "ما سعر النفط اليوم؟",
        "must_contain_any": ["لا تتوفر", "خارج", "غير متاح", "لا أملك", "اقتصادي"],
        "must_cite":        False,
    },
    {
        "id":               "q17",
        "category":         "خارج النطاق",
        "query":            "كيف أطبخ الكبسة؟",
        "must_contain_any": ["لا تتوفر", "خارج", "طبخ", "لا أملك"],
        "must_cite":        False,
    },
    # ── أسئلة إجرائية ─────────────────────────────────────────
    {
        "id":               "q18",
        "category":         "إجراءات",
        "query":            "كيف أرفع شكوى عمالية في قطر؟",
        "must_contain_any": ["شكوى", "وزارة", "عمل", "إجراءات"],
        "must_cite":        True,
    },
    {
        "id":               "q19",
        "category":         "إجراءات",
        "query":            "ما إجراءات تسجيل عقد الزواج في المحكمة؟",
        "must_contain_any": ["زواج", "محكمة", "تسجيل", "وثيقة"],
        "must_cite":        True,
    },
    {
        "id":               "q20",
        "category":         "عمالي",
        "query":            "ما حقوق العامل في إجازة الأمومة في قطر؟",
        "must_contain_any": ["أمومة", "إجازة", "أسبوع", "راتب"],
        "must_cite":        True,
    },
]


# ── Mock answers (representative realistic responses) ──────────
_MOCK_ANSWERS: dict[str, dict] = {
    "q01": {"answer": "وفقاً للمادة 49 من قانون العمل القطري [1]، مدة الإشعار شهر واحد.", "confidence": 88, "sources_count": 2},
    "q02": {"answer": "تُحتسب مكافأة نهاية الخدمة بثلاثة أسابيع راتب عن كل سنة [1].", "confidence": 85, "sources_count": 3},
    "q03": {"answer": "تُمنح إجازة سنوية لا تقل عن ثلاثة أسابيع وفق المادة 80 [1].", "confidence": 82, "sources_count": 2},
    "q04": {"answer": "الفصل التعسفي يُلزم صاحب العمل بالتعويض وفق المادة 61 [1].", "confidence": 80, "sources_count": 2},
    "q05": {"answer": "تبدأ إجراءات الطلاق بتقديم طلب للمحكمة الشرعية [1].", "confidence": 79, "sources_count": 2},
    "q06": {"answer": "الحضانة للأم بعد الطلاق حتى بلوغ الطفل سن السابعة [1].", "confidence": 81, "sources_count": 2},
    "q07": {"answer": "المهر ركن أساسي في عقد الزواج يُحدد بالاتفاق [1].", "confidence": 76, "sources_count": 1},
    "q08": {"answer": "عقوبة السرقة الحبس مدة لا تتجاوز 3 سنوات وغرامة [1].", "confidence": 90, "sources_count": 3},
    "q09": {"answer": "الاعتداء الجسدي يُعاقب عليه بالحبس والغرامة وفق المادة 287 [1].", "confidence": 88, "sources_count": 2},
    "q10": {"answer": "الاحتيال يُعاقب عليه بالسجن 3 سنوات وغرامة [1].", "confidence": 85, "sources_count": 2},
    "q11": {"answer": "للمستأجر حق التظلم أمام لجنة تحديد الإيجارات [1].", "confidence": 77, "sources_count": 2},
    "q12": {"answer": "يحق الإخلاء عند انتهاء العقد أو إخلاله بشروط الإيجار [1].", "confidence": 74, "sources_count": 2},
    "q13": {"answer": "تأسيس الشركة يتطلب رأس مال أدنى وترخيص تجاري [1].", "confidence": 72, "sources_count": 2},
    "q14": {"answer": "القيادة تحت تأثير الكحول تُعاقب بسحب الرخصة وغرامة وفق قانون المرور [1].", "confidence": 83, "sources_count": 2},
    "q15": {"answer": "الإقامة الدائمة تتطلب إقامة قانونية لمدة لا تقل عن 10 سنوات [1].", "confidence": 70, "sources_count": 1},
    "q16": {"answer": "لا تتوفر لديّ معلومات حول أسعار النفط، هذا خارج نطاق اختصاصي القانوني.", "confidence": 0, "sources_count": 0},
    "q17": {"answer": "لا أملك معلومات عن الطبخ، اختصاصي في القانون القطري فقط.", "confidence": 0, "sources_count": 0},
    "q18": {"answer": "يُقدَّم شكوى عمالية في وزارة العمل إلكترونياً [1].", "confidence": 78, "sources_count": 2},
    "q19": {"answer": "يُسجَّل عقد الزواج في المحكمة الشرعية بعد استيفاء الوثائق [1].", "confidence": 75, "sources_count": 1},
    "q20": {"answer": "إجازة الأمومة 50 يوم راتب كامل وفق قانون العمل [1].", "confidence": 82, "sources_count": 2},
}


# ════════════════════��═════════════════════════════════════════
# Quality validation helpers
# ══════════════════════════════════════════════════════════════

def _has_citation(text: str) -> bool:
    return bool(re.search(r"\[\d+\]", text))


def _validate(q: dict, answer: str, confidence: float, sources_count: int) -> dict:
    keywords_ok  = any(kw in answer for kw in q["must_contain_any"])
    has_cite     = _has_citation(answer)
    citation_ok  = (not q["must_cite"]) or has_cite
    return {
        "id":           q["id"],
        "category":     q["category"],
        "keywords_ok":  keywords_ok,
        "citation_ok":  citation_ok,
        "confidence":   confidence,
        "sources_count": sources_count,
        "passes":       keywords_ok and citation_ok,
    }


# ══════════════════════════════════════════════════════════════
# Live API mode
# ══════════════════════════════════════════════════════════════

_BENCH_API_KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"


def _call_live_api(q: dict, base_url: str = "http://localhost:80") -> tuple[str, float, int, int]:
    """يستدعي API الحقيقي ويُعيد (answer, confidence, sources_count, latency_ms)."""
    import urllib.request
    import json as _json

    payload = _json.dumps({"query": q["query"], "mode": "expert", "model": "gemini"}, ensure_ascii=False).encode("utf-8")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/query/",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8", "X-API-Key": _BENCH_API_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
        latency = int((time.time() - t0) * 1000)
        return (
            data.get("answer", ""),
            float(data.get("confidence", 0)),
            len(data.get("sources", [])),
            latency,
        )
    except Exception as e:
        return (f"ERROR: {e}", 0, 0, int((time.time() - t0) * 1000))


# ═════════════════════════════��════════════════════════════════
# Mock mode
# ══════════════════════════════════════════════════════════════

def _mock_response(q: dict) -> tuple[str, float, int, int]:
    mock = _MOCK_ANSWERS.get(q["id"], {
        "answer": "إجابة افتراضية", "confidence": 65, "sources_count": 1
    })
    latency = 150 + hash(q["id"]) % 300   # 150–450ms mock
    return mock["answer"], float(mock["confidence"]), mock["sources_count"], latency


# ══════════════════════════════════════════════════════════════
# Main benchmark runner
# ══════════════════════════════════════════════════════════════

def run_benchmark(live: bool = False, base_url: str = "http://localhost:8000") -> dict:
    results  = []
    total_ms = 0

    print(f"\n{'='*60}")
    print("  المساعد القانوني — Benchmark v1.0")
    print(f"  الوضع: {'Live API' if live else 'Mock'} | الأسئلة: {len(QUESTIONS)}")
    print(f"{'='*60}\n")

    for i, q in enumerate(QUESTIONS, 1):
        if live:
            answer, confidence, sources, latency = _call_live_api(q, base_url)
        else:
            answer, confidence, sources, latency = _mock_response(q)

        result = _validate(q, answer, confidence, sources)
        result["latency_ms"]     = latency
        result["answer_snippet"] = answer[:80]
        results.append(result)

        status = "PASS" if result["passes"] else "FAIL"
        print(f"  [{i:02d}] {status} {q['id']} | {q['category']:8s} | "
              f"{latency:4d}ms | conf:{confidence:3.0f} | {q['query'][:40]}")
        total_ms += latency

    # ── Aggregate metrics ──────────────────���──────────────────
    passing        = [r for r in results if r["passes"]]
    legal_results  = [r for r in results if r["confidence"] > 0]
    citation_ok    = [r for r in results if r["citation_ok"]]

    metrics = {
        "total_questions":  len(results),
        "passing":          len(passing),
        "success_rate":     round(len(passing)     / len(results) * 100, 1),
        "avg_ms":           round(total_ms         / len(results),       1),
        "avg_confidence":   round(
            sum(r["confidence"] for r in legal_results) / max(len(legal_results), 1), 1
        ),
        "citation_rate":    round(
            sum(1 for r in results if r["citation_ok"] and r["confidence"] > 0)
            / max(sum(1 for r in results if r["confidence"] > 0), 1) * 100, 1
        ),
        "goals": {
            "avg_confidence_goal_met": False,
            "citation_rate_goal_met":  False,
        },
    }
    metrics["goals"]["avg_confidence_goal_met"] = metrics["avg_confidence"] > 70
    metrics["goals"]["citation_rate_goal_met"]  = metrics["citation_rate"]  > 80

    # ── Summary ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  النتائج الإجمالية")
    print(f"{'='*60}")
    print(f"  الأسئلة:          {metrics['total_questions']}")
    print(f"  معدل النجاح:      {metrics['success_rate']}%")
    print(f"  متوسط الوقت:      {metrics['avg_ms']:.0f} ms")
    print(f"  متوسط الثقة:      {metrics['avg_confidence']:.1f}  [{'OK' if metrics['goals']['avg_confidence_goal_met'] else 'FAIL'}] (هدف: > 70)")
    print(f"  معدل الاستشهاد:   {metrics['citation_rate']:.1f}%  [{'OK' if metrics['goals']['citation_rate_goal_met'] else 'FAIL'}] (هدف: > 80%)")
    print(f"{'='*60}\n")

    return {"metrics": metrics, "results": results}


# ═════════════════════════════════════���════════════════════════
# Entry point
# ═════════════════════════════════════════════��════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Legal AI Benchmark")
    parser.add_argument("--live",    action="store_true", help="استخدام Live API بدل Mock")
    parser.add_argument("--url",     default="http://localhost:8000", help="عنوان السيرفر")
    parser.add_argument("--out",     default="",          help="ملف JSON للتقرير")
    args = parser.parse_args()

    report = run_benchmark(live=args.live, base_url=args.url)

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"✅ التقرير محفوظ: {args.out}")
    else:
        print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
