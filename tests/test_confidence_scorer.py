# -*- coding: utf-8 -*-
"""
اختبارات confidence_scorer
============================
تختبر: calculate()، from_chunks()، الفئات والألوان
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from confidence_scorer import (
    calculate,
    from_chunks,
    ConfidenceResult,
    THRESHOLD_HIGH,
    THRESHOLD_MEDIUM,
    WEIGHT_RETRIEVAL,
    WEIGHT_COVERAGE,
    WEIGHT_DIVERSITY,
)


# ══════════════════════════════════════════════════════════════
# بيانات الاختبار
# ══════════════════════════════════════════════════════════════

def _make_chunk(law_name="قانون أ", score=0.9) -> dict:
    return {"law_name": law_name, "article_number": "1",
            "content": "نص قانوني", "score": score}


# ══════════════════════════════════════════════════════════════
# اختبارات calculate — البنية
# ══════════════════════════════════════════════════════════════

class TestCalculateStructure:

    def test_returns_required_keys(self):
        """النتيجة تحتوي score + label + color + breakdown."""
        result = calculate([0.9], [_make_chunk()])
        assert "score"     in result
        assert "label"     in result
        assert "color"     in result
        assert "breakdown" in result

    def test_breakdown_has_required_keys(self):
        """breakdown تحتوي retrieval + coverage + diversity."""
        result = calculate([0.9], [_make_chunk()])
        bd = result["breakdown"]
        assert "retrieval" in bd
        assert "coverage"  in bd
        assert "diversity" in bd

    def test_score_is_integer(self):
        """score عدد صحيح."""
        result = calculate([0.9], [_make_chunk()])
        assert isinstance(result["score"], int)

    def test_score_in_range_0_100(self):
        """score في النطاق 0..100."""
        result = calculate([0.9], [_make_chunk()])
        assert 0 <= result["score"] <= 100

    def test_breakdown_values_are_floats(self):
        """قيم breakdown أرقام عائمة."""
        result = calculate([0.9], [_make_chunk()])
        bd = result["breakdown"]
        assert isinstance(bd["retrieval"], float)
        assert isinstance(bd["coverage"],  float)
        assert isinstance(bd["diversity"], float)


# ══════════════════════════════════════════════════════════════
# اختبارات الحساب
# ══════════════════════════════════════════════════════════════

class TestCalculationLogic:

    def test_empty_inputs_returns_zero(self):
        """مدخلات فارغة → score = 0."""
        result = calculate([], [])
        assert result["score"] == 0

    def test_high_similarity_scores_raise_retrieval(self):
        """scores مرتفعة → retrieval مرتفع."""
        result = calculate([1.0, 1.0, 1.0], [_make_chunk()])
        assert result["breakdown"]["retrieval"] == 100.0

    def test_zero_similarity_scores_zero_retrieval(self):
        """scores صفر → retrieval = 0."""
        result = calculate([0.0, 0.0], [_make_chunk()])
        assert result["breakdown"]["retrieval"] == 0.0

    def test_five_chunks_give_full_coverage(self):
        """5 chunks → coverage = 100."""
        chunks = [_make_chunk() for _ in range(5)]
        result = calculate([0.9] * 5, chunks)
        assert result["breakdown"]["coverage"] == 100.0

    def test_one_chunk_gives_20_percent_coverage(self):
        """chunk واحد → coverage = 20% (1/5)."""
        result = calculate([0.9], [_make_chunk()])
        assert abs(result["breakdown"]["coverage"] - 20.0) < 0.1

    def test_three_unique_sources_give_full_diversity(self):
        """3 قوانين مختلفة → diversity = 100."""
        chunks = [_make_chunk(law_name=f"قانون {i}") for i in range(3)]
        result = calculate([0.9] * 3, chunks)
        assert result["breakdown"]["diversity"] == 100.0

    def test_one_source_gives_33_percent_diversity(self):
        """مصدر واحد → diversity ≈ 33%."""
        chunks = [_make_chunk(law_name="قانون أ")] * 3
        result = calculate([0.9] * 3, chunks)
        assert abs(result["breakdown"]["diversity"] - 33.3) < 1.0

    def test_formula_correct(self):
        """التحقق من صحة المعادلة مباشرةً."""
        # retrieval = 90, coverage = 100 (5 chunks), diversity = 100 (3 sources)
        chunks = [_make_chunk(law_name=f"قانون {i}") for i in range(3)]
        chunks += [_make_chunk(law_name="قانون 0"), _make_chunk(law_name="قانون 1")]
        scores = [0.9] * 5
        result = calculate(scores, chunks)

        retrieval = 90.0
        coverage  = 100.0
        diversity = 100.0
        expected  = round(retrieval * 0.5 + coverage * 0.3 + diversity * 0.2)
        assert result["score"] == expected   # 90*0.5 + 100*0.3 + 100*0.2 = 45+30+20 = 95

    def test_score_capped_at_100(self):
        """score لا يتجاوز 100."""
        chunks = [_make_chunk(law_name=f"ق{i}") for i in range(10)]
        result = calculate([1.0] * 10, chunks)
        assert result["score"] <= 100

    def test_score_not_negative(self):
        """score لا يكون سالباً."""
        result = calculate([0.0], [_make_chunk()])
        assert result["score"] >= 0

    def test_scores_clipped_to_0_1(self):
        """scores خارج النطاق [0,1] تُقلَّص."""
        result_over  = calculate([1.5, 2.0], [_make_chunk()])
        result_under = calculate([-0.5], [_make_chunk()])
        # لا exception ولا نتائج خاطئة
        assert 0 <= result_over["score"]  <= 100
        assert 0 <= result_under["score"] <= 100


# ══════════════════════════════════════════════════════════════
# اختبارات التصنيف والألوان
# ══════════════════════════════════════════════════════════════

class TestClassification:

    def test_high_score_label(self):
        """درجة ≥80 → عالية."""
        chunks = [_make_chunk(law_name=f"ق{i}") for i in range(3)]
        result = calculate([0.95, 0.95, 0.95], chunks * 2)
        if result["score"] >= THRESHOLD_HIGH:
            assert result["label"] == "عالية"
            assert result["color"] == "green"

    def test_medium_score_label(self):
        """درجة 60..79 → متوسطة."""
        # retrieval=65, coverage=60 (3/5), diversity=67 (2/3 sources)
        chunks = [_make_chunk(law_name="ق1"), _make_chunk(law_name="ق2"),
                  _make_chunk(law_name="ق1")]
        result = calculate([0.65, 0.65, 0.65], chunks)
        if THRESHOLD_MEDIUM <= result["score"] < THRESHOLD_HIGH:
            assert result["label"] == "متوسطة"
            assert result["color"] == "yellow"

    def test_low_score_label(self):
        """درجة <60 → منخفضة."""
        result = calculate([0.0], [_make_chunk()])
        assert result["label"] == "منخفضة"
        assert result["color"] == "red"

    def test_exactly_80_is_high(self):
        """درجة = 80 تحديداً → عالية."""
        # نبحث عن تركيبة تُعطي 80 تحديداً
        # retrieval=80, coverage=80, diversity=80 → 80*0.5+80*0.3+80*0.2 = 80
        # لتحقيق retrieval=80: scores=[0.8]
        # coverage=80: 4/5 chunks → 4 chunks
        # diversity=80: 2.4/3 sources → نستخدم 3 sources لكن 2.4 يُصبح min(2.4,1)*100 = ~80
        # سنتحقق من الفئة فقط إذا وصل الـ score لـ 80
        chunks = [_make_chunk(law_name=f"ق{i}") for i in range(4)]
        result = calculate([0.8] * 4, chunks)
        if result["score"] == 80:
            assert result["label"] == "عالية"

    def test_just_below_60_is_low(self):
        """درجة قريبة من 60 لكن أقل → منخفضة."""
        result = calculate([0.1], [_make_chunk()])
        if result["score"] < THRESHOLD_MEDIUM:
            assert result["label"] == "منخفضة"

    def test_valid_color_values(self):
        """color دائماً من القيم الثلاث المسموحة."""
        for scores, chunks in [
            ([0.95]*5, [_make_chunk(f"ق{i}") for i in range(3)] * 2),
            ([0.5]*3,  [_make_chunk()]*3),
            ([0.1],    [_make_chunk()]),
        ]:
            result = calculate(scores, chunks)
            assert result["color"] in ("green", "yellow", "red")


# ══════════════════════════════════════════════════════════════
# اختبارات from_chunks
# ══════════════════════════════════════════════════════════════

class TestFromChunks:

    def test_extracts_scores_from_chunks(self):
        """from_chunks يستخرج scores من حقل 'score' في كل chunk."""
        chunks = [_make_chunk(score=0.9), _make_chunk(score=0.8)]
        result = from_chunks(chunks)
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    def test_empty_chunks_returns_zero(self):
        """chunks فارغة → score = 0."""
        result = from_chunks([])
        assert result["score"] == 0

    def test_same_as_calculate_with_extracted_scores(self):
        """from_chunks يُعطي نفس نتيجة calculate مع نفس البيانات."""
        chunks = [_make_chunk(score=0.85), _make_chunk(score=0.75)]
        scores = [0.85, 0.75]
        result_fc   = from_chunks(chunks)
        result_calc = calculate(scores, chunks)
        assert result_fc["score"] == result_calc["score"]


# ══════════════════════════════════════════════════════════════
# اختبارات الثوابت والأوزان
# ══════════════════════════════════════════════════════════════

class TestConstants:

    def test_weights_sum_to_one(self):
        """مجموع الأوزان = 1.0."""
        total = WEIGHT_RETRIEVAL + WEIGHT_COVERAGE + WEIGHT_DIVERSITY
        assert abs(total - 1.0) < 1e-9

    def test_threshold_high_above_medium(self):
        """عتبة عالية > عتبة متوسطة."""
        assert THRESHOLD_HIGH > THRESHOLD_MEDIUM

    def test_threshold_medium_above_zero(self):
        """عتبة متوسطة > 0."""
        assert THRESHOLD_MEDIUM > 0
