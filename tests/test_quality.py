# -*- coding: utf-8 -*-
"""
tests/test_quality.py — اختبارات جودة الإجابات القانونية
==========================================================
كل اختبار يستخدم mock — بدون اتصال حقيقي بـ LLM أو DB.
المعيار: الإجابة تحتوي الكلمات المطلوبة + الاستشهادات عند الحاجة.
"""
import sys
import os
import re
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from user_memory import _extract_topic, _detect_detail_preference, _empty_prefs


# ══════════════════════════════════════════════════════════════
# BENCHMARK
# ══════════════════════════════════════════════════════════════
BENCHMARK = [
    {
        "id":               "labor_notice",
        "query":            "كم مدة إشعار إنهاء عقد العمل في قطر؟",
        "must_contain_any": ["شهر", "30", "إشعار", "مهلة"],
        "must_cite":        True,
        "max_ms":           5000,
        "expected_topic":   "قانون العمل",
    },
    {
        "id":               "criminal_assault",
        "query":            "ما عقوبة الاعتداء الجسدي في القانون القطري؟",
        "must_contain_any": ["عقوبات", "غرامة", "حبس", "سجن"],
        "must_cite":        True,
        "expected_topic":   "قانون العقوبات",
    },
    {
        "id":               "off_topic",
        "query":            "ما سعر النفط اليوم؟",
        "must_contain_any": ["لا تتوفر", "خارج", "غير متاح", "لا أملك"],
        "must_cite":        False,
        "expected_topic":   "",
    },
    {
        "id":               "family_law",
        "query":            "ما حقوق المرأة في قانون الأسرة القطري؟",
        "must_contain_any": ["أسرة", "زواج", "طلاق", "نفقة"],
        "must_cite":        True,
        "expected_topic":   "قانون الأسرة",
    },
]

# ── إجابات mock تُمثّل مخرجات مثالية من النظام ──────────────
MOCK_ANSWERS = {
    "labor_notice": (
        "وفقاً للمادة 49 من قانون العمل القطري رقم 14 لسنة 2004 [1]، "
        "يلتزم صاحب العمل بتقديم إشعار مسبق مدّته شهر واحد كامل قبل إنهاء عقد "
        "العمل غير المحدد المدة. وتُعدّ مهلة الإشعار حقاً للعامل لا يجوز التنازل "
        "عنه، وفي حال عدم تقديم الإشعار تُحتسب بدل إشعار تعادل 30 يوم راتب [2]."
    ),
    "criminal_assault": (
        "طبقاً للمادة 287 من قانون العقوبات القطري رقم 11 لسنة 2004 [1]، "
        "تتراوح عقوبة الاعتداء الجسدي البسيط بين غرامة مالية وحبس لمدة لا تتجاوز "
        "ستة أشهر. وفي حالة الاعتداء المفضي إلى عجز دائم تصل العقوبة إلى السجن "
        "سبع سنوات [2]، مع احتمال التعويض المدني للمتضرر."
    ),
    "off_topic": (
        "لا تتوفر لديّ معلومات حول أسعار النفط، إذ إن هذا الموضوع خارج نطاق "
        "اختصاصي القانوني. يُرجى مراجعة المصادر الاقتصادية المتخصصة للحصول "
        "على هذه البيانات، مثل منصات متابعة أسواق الطاقة العالمية."
    ),
    "family_law": (
        "يُنظّم قانون الأسرة القطري رقم 22 لسنة 2006 [1] حقوق المرأة في الزواج "
        "والطلاق والنفقة. تشمل هذه الحقوق: الحق في المهر المحدد بالعقد، والنفقة "
        "الزوجية، وحضانة الأطفال بعد الطلاق لحين بلوغهم، فضلاً عن حق المرأة في "
        "طلب الخلع أمام المحكمة الشرعية [2]."
    ),
}


# ══════════════════════════════════════════════════════════════
# Pure quality helpers
# ══════════════════════════════════════════════════════════════

def _validate_answer(answer: str, benchmark: dict) -> dict:
    """يتحقق من جودة الإجابة وفق معايير الـ benchmark."""
    keywords_ok  = any(kw in answer for kw in benchmark["must_contain_any"])
    has_citation = bool(re.search(r"\[\d+\]", answer))
    citation_ok  = (not benchmark["must_cite"]) or has_citation
    return {
        "keywords_ok":  keywords_ok,
        "citation_ok":  citation_ok,
        "answer_len":   len(answer),
        "passes":       keywords_ok and citation_ok,
    }


def _has_citation(text: str) -> bool:
    return bool(re.search(r"\[\d+\]", text))


# ══════════════════════════════════════════════════════════════
# TestTopicExtraction
# ══════════════════════════════════════════════════════════════
class TestTopicExtraction:
    def test_labor_query_identified(self):
        bm = next(b for b in BENCHMARK if b["id"] == "labor_notice")
        assert _extract_topic(bm["query"]) == bm["expected_topic"]

    def test_criminal_query_identified(self):
        bm = next(b for b in BENCHMARK if b["id"] == "criminal_assault")
        assert _extract_topic(bm["query"]) == bm["expected_topic"]

    def test_off_topic_returns_empty(self):
        bm = next(b for b in BENCHMARK if b["id"] == "off_topic")
        assert _extract_topic(bm["query"]) == ""

    def test_family_law_identified(self):
        bm = next(b for b in BENCHMARK if b["id"] == "family_law")
        assert _extract_topic(bm["query"]) == bm["expected_topic"]

    def test_all_legal_benchmarks_have_topic(self):
        legal = [b for b in BENCHMARK if b["expected_topic"]]
        for bm in legal:
            assert _extract_topic(bm["query"]) != "", f"فشل: {bm['query']}"


# ══════════════════════════════════════════════════════════════
# TestDetailPreference
# ══════════════════════════════════════════════════════════════
class TestDetailPreference:
    def test_benchmark_queries_return_valid_pref(self):
        valid = {"standard", "detailed", "brief"}
        for bm in BENCHMARK:
            assert _detect_detail_preference(bm["query"]) in valid

    def test_detailed_keyword_detected(self):
        assert _detect_detail_preference("اشرح لي بالتفصيل قانون العمل") == "detailed"

    def test_brief_keyword_detected(self):
        assert _detect_detail_preference("باختصار ما عقوبة السرقة؟") == "brief"

    def test_plain_question_is_standard(self):
        assert _detect_detail_preference("ما عقوبة الاعتداء؟") == "standard"


# ══════════════════════════════════════════════════════════════
# TestAnswerQualityValidator
# ══════════════════════════════════════════════════════════════
class TestAnswerQualityValidator:
    def test_good_answer_passes(self):
        bm = next(b for b in BENCHMARK if b["id"] == "labor_notice")
        result = _validate_answer(MOCK_ANSWERS["labor_notice"], bm)
        assert result["passes"] is True

    def test_missing_keywords_fails(self):
        bm = next(b for b in BENCHMARK if b["id"] == "labor_notice")
        bad = "إجابة عامة لا تتضمن أي معلومات محددة حول العقد."
        result = _validate_answer(bad, bm)
        assert result["keywords_ok"] is False

    def test_missing_citation_fails_when_required(self):
        bm = next(b for b in BENCHMARK if b["id"] == "labor_notice")
        no_cite = "يجب تقديم إشعار مسبق لمدة شهر قبل إنهاء العقد."
        result = _validate_answer(no_cite, bm)
        assert result["citation_ok"] is False

    def test_off_topic_passes_without_citation(self):
        bm = next(b for b in BENCHMARK if b["id"] == "off_topic")
        result = _validate_answer(MOCK_ANSWERS["off_topic"], bm)
        assert result["passes"] is True

    def test_citation_format_detected(self):
        assert _has_citation("وفقاً للمادة 49 [1] من قانون العمل") is True

    def test_citation_format_not_detected_in_plain_text(self):
        assert _has_citation("إجابة بدون استشهاد رقمي") is False

    def test_criminal_answer_passes(self):
        bm = next(b for b in BENCHMARK if b["id"] == "criminal_assault")
        result = _validate_answer(MOCK_ANSWERS["criminal_assault"], bm)
        assert result["passes"] is True

    def test_family_law_answer_passes(self):
        bm = next(b for b in BENCHMARK if b["id"] == "family_law")
        result = _validate_answer(MOCK_ANSWERS["family_law"], bm)
        assert result["passes"] is True


# ══════════════════════════════════════════════════════════════
# TestBenchmarkSuite — اختبار مستقل لكل benchmark
# ══════════════════════════════════════════════════════════════
class TestBenchmarkSuite:
    def test_labor_notice(self):
        bm = next(b for b in BENCHMARK if b["id"] == "labor_notice")
        r = _validate_answer(MOCK_ANSWERS["labor_notice"], bm)
        assert r["passes"], f"فشل labor_notice: {r}"

    def test_criminal_assault(self):
        bm = next(b for b in BENCHMARK if b["id"] == "criminal_assault")
        r = _validate_answer(MOCK_ANSWERS["criminal_assault"], bm)
        assert r["passes"], f"فشل criminal_assault: {r}"

    def test_off_topic(self):
        bm = next(b for b in BENCHMARK if b["id"] == "off_topic")
        r = _validate_answer(MOCK_ANSWERS["off_topic"], bm)
        assert r["passes"], f"فشل off_topic: {r}"

    def test_family_law(self):
        bm = next(b for b in BENCHMARK if b["id"] == "family_law")
        r = _validate_answer(MOCK_ANSWERS["family_law"], bm)
        assert r["passes"], f"فشل family_law: {r}"

    def test_mock_answers_sufficient_length(self):
        for bid, answer in MOCK_ANSWERS.items():
            assert len(answer) >= 100, f"الإجابة قصيرة جداً لـ {bid}"

    def test_benchmark_ids_unique(self):
        ids = [b["id"] for b in BENCHMARK]
        assert len(ids) == len(set(ids))

    def test_all_benchmarks_have_keywords(self):
        for bm in BENCHMARK:
            assert len(bm["must_contain_any"]) > 0, f"بدون كلمات مفتاحية: {bm['id']}"

    def test_legal_benchmarks_require_citation(self):
        legal = [b for b in BENCHMARK if b["expected_topic"]]
        for bm in legal:
            assert bm["must_cite"] is True, f"{bm['id']} يجب أن يتطلب استشهاداً"


# ══════════════════════════════════════════════════════════════
# TestQualityHelpers
# ══════════════════════════════════════════════════════════════
class TestQualityHelpers:
    def test_empty_prefs_default_detail(self):
        p = _empty_prefs("test_session")
        assert p["preferred_detail_level"] == "standard"

    def test_empty_prefs_zero_count(self):
        p = _empty_prefs("test_session")
        assert p["query_count"] == 0

    def test_all_legal_queries_have_topics(self):
        for bm in BENCHMARK:
            if bm["expected_topic"]:
                topic = _extract_topic(bm["query"])
                assert topic != "", f"لم يُستخرج موضوع لـ: {bm['query']}"

    def test_off_topic_no_legal_topic(self):
        non_legal = [
            "ما طقس الدوحة؟",
            "كيف أطبخ المجبوس؟",
            "ما هو ثمن الذهب؟",
        ]
        for q in non_legal:
            assert _extract_topic(q) == "", f"موضوع خاطئ للسؤال: {q}"
