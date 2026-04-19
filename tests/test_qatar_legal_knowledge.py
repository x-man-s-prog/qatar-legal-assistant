# -*- coding: utf-8 -*-
"""
اختبارات core/qatar_legal_knowledge.py
========================================
تختبر: QATAR_LAWS_MAP, Qatar_NON_CRIMES, QATAR_LEGAL_SYNONYMS,
       DOMAIN_THRESHOLDS, QATAR_KNOWN_ANSWERS, SYSTEM_CAPABILITY_RESPONSE,
       match_known_answer(), is_non_crime(), get_domain_threshold()
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.qatar_legal_knowledge import (
    QATAR_LAWS_MAP,
    Qatar_NON_CRIMES,
    QATAR_LEGAL_SYNONYMS,
    DOMAIN_THRESHOLDS,
    QATAR_KNOWN_ANSWERS,
    SYSTEM_CAPABILITY_RESPONSE,
    match_known_answer,
    is_non_crime,
    get_domain_threshold,
)


# ══════════════════════════════════════════════════════════════
# اختبارات البنية الأساسية
# ══════════════════════════════════════════════════════════════
class TestStructure:

    def test_qatar_laws_map_is_dict(self):
        assert isinstance(QATAR_LAWS_MAP, dict)

    def test_qatar_laws_map_has_key_laws(self):
        """القوانين الأساسية موجودة"""
        assert "قانون العقوبات" in QATAR_LAWS_MAP
        assert "قانون العمل" in QATAR_LAWS_MAP
        assert "قانون الإجراءات الجنائية" in QATAR_LAWS_MAP
        assert "قانون الأسرة" in QATAR_LAWS_MAP

    def test_labor_law_has_article_49(self):
        """قانون العمل يحتوي على مادة 49 (إشعار)"""
        labor = QATAR_LAWS_MAP["قانون العمل"]
        notice = labor["مواضيع_رئيسية"]["إشعار_إنهاء_العقد"]
        assert notice["مادة"] == "49"

    def test_labor_law_article_54_gratuity(self):
        """قانون العمل يحتوي على مادة 54 (مكافأة)"""
        labor = QATAR_LAWS_MAP["قانون العمل"]
        gratuity = labor["مواضيع_رئيسية"]["مكافأة_نهاية_الخدمة"]
        assert gratuity["مادة"] == "54"

    def test_criminal_procedure_rehabilitation_articles(self):
        """قانون الإجراءات الجنائية يحتوي مواد رد الاعتبار 377-384"""
        cpa = QATAR_LAWS_MAP["قانون الإجراءات الجنائية"]
        assert cpa["رد_الاعتبار"]["مواد"] == "377-384"

    def test_non_crimes_is_dict(self):
        assert isinstance(Qatar_NON_CRIMES, dict)

    def test_suicide_is_non_crime(self):
        """محاولة الانتحار في قائمة الأفعال غير المجرَّمة"""
        assert "محاولة الانتحار" in Qatar_NON_CRIMES

    def test_synonyms_is_dict(self):
        assert isinstance(QATAR_LEGAL_SYNONYMS, dict)

    def test_synonyms_has_labor_terms(self):
        """المرادفات تحتوي مصطلحات عمالية"""
        assert "فصل" in QATAR_LEGAL_SYNONYMS
        assert "راتب" in QATAR_LEGAL_SYNONYMS
        assert "إشعار" in QATAR_LEGAL_SYNONYMS

    def test_domain_thresholds_is_dict(self):
        assert isinstance(DOMAIN_THRESHOLDS, dict)

    def test_domain_thresholds_has_default(self):
        assert "default" in DOMAIN_THRESHOLDS

    def test_criminal_threshold_high(self):
        """المجال الجنائي له عتبة ثقة أعلى من العمالي"""
        assert DOMAIN_THRESHOLDS.get("جنائي", 0) >= DOMAIN_THRESHOLDS.get("عمالي", 0)

    def test_hadd_threshold_highest(self):
        """مجال الحدود له أعلى عتبة ثقة"""
        assert DOMAIN_THRESHOLDS.get("حدود", 0) >= DOMAIN_THRESHOLDS.get("جنائي", 0)

    def test_known_answers_is_dict(self):
        assert isinstance(QATAR_KNOWN_ANSWERS, dict)

    def test_known_answers_has_suicide(self):
        assert "محاولة_الانتحار" in QATAR_KNOWN_ANSWERS

    def test_known_answers_has_notice_period(self):
        assert "مدة_إشعار_إنهاء_العقد" in QATAR_KNOWN_ANSWERS

    def test_known_answers_has_gratuity(self):
        assert "مكافأة_نهاية_الخدمة" in QATAR_KNOWN_ANSWERS

    def test_known_answers_has_rehabilitation(self):
        assert "رد_الاعتبار" in QATAR_KNOWN_ANSWERS

    def test_capability_response_is_string(self):
        assert isinstance(SYSTEM_CAPABILITY_RESPONSE, str)
        assert len(SYSTEM_CAPABILITY_RESPONSE) > 50


# ══════════════════════════════════════════════════════════════
# اختبارات match_known_answer
# ══════════════════════════════════════════════════════════════
class TestMatchKnownAnswer:

    def test_suicide_question_returns_answer(self):
        """سؤال عن محاولة الانتحار → إجابة معلَّبة"""
        result = match_known_answer("ما عقوبة محاولة الانتحار في قطر؟")
        assert result is not None
        assert "غير مجرّمة" in result or "لا توجد عقوبة" in result

    def test_suicide_keyword_only(self):
        """كلمة الانتحار وحدها تُطابق"""
        result = match_known_answer("ما حكم الانتحار في قانون العقوبات القطري؟")
        assert result is not None

    def test_notice_period_question(self):
        """سؤال عن مدة الإشعار → إجابة معلَّبة"""
        result = match_known_answer("ما مدة إشعار إنهاء عقد العمل؟")
        assert result is not None
        assert "49" in result  # المادة 49

    def test_notice_period_alternate_phrasing(self):
        """صياغة بديلة للإشعار"""
        result = match_known_answer("كم مدة الإشعار عند إنهاء عقد العمل؟")
        assert result is not None

    def test_gratuity_question(self):
        """سؤال عن مكافأة نهاية الخدمة → إجابة معلَّبة"""
        result = match_known_answer("كيف تحسب مكافأة نهاية الخدمة؟")
        assert result is not None
        assert "54" in result  # المادة 54

    def test_rehabilitation_question(self):
        """سؤال عن رد الاعتبار → إجابة معلَّبة"""
        result = match_known_answer("ما هي إجراءات رد الاعتبار؟")
        assert result is not None
        assert "377" in result or "378" in result

    def test_unrelated_question_returns_none(self):
        """سؤال غير مرتبط → None"""
        result = match_known_answer("ما هو نظام الضريبة في قطر؟")
        assert result is None

    def test_murder_returns_known_answer(self):
        """سؤال القتل العمد → إجابة معلَّبة (المادة 300)"""
        result = match_known_answer("ما عقوبة القتل العمد في قطر؟")
        assert result is not None
        assert "300" in result

    def test_theft_returns_known_answer(self):
        """سؤال السرقة → إجابة معلَّبة (المادة 310)"""
        result = match_known_answer("ما حكم السرقة في القانون القطري؟")
        assert result is not None
        assert "310" in result

    def test_empty_string_returns_none(self):
        result = match_known_answer("")
        assert result is None

    def test_none_input_returns_none(self):
        result = match_known_answer(None)
        assert result is None

    def test_answer_is_string(self):
        """الإجابة المُعادة نص وليس None"""
        result = match_known_answer("ما عقوبة محاولة الانتحار؟")
        assert isinstance(result, str)
        assert len(result) > 20

    def test_notice_period_contains_article_49(self):
        """إجابة الإشعار تحتوي على المادة 49"""
        result = match_known_answer("ما مدة إشعار إنهاء عقد العمل؟")
        assert result is not None
        assert "49" in result

    def test_rehabilitation_contains_articles(self):
        """إجابة رد الاعتبار تحتوي المواد"""
        result = match_known_answer("ما شروط رد الاعتبار؟")
        assert result is not None
        assert "377" in result


# ══════════════════════════════════════════════════════════════
# اختبارات is_non_crime
# ══════════════════════════════════════════════════════════════
class TestIsNonCrime:

    def test_suicide_is_non_crime(self):
        """محاولة الانتحار → non_crime"""
        result = is_non_crime("ما عقوبة محاولة الانتحار؟")
        assert result is not None
        assert "الحكم" in result

    def test_suicide_keyword_alone(self):
        """كلمة الانتحار → non_crime"""
        result = is_non_crime("هل الانتحار جريمة في قطر؟")
        assert result is not None

    def test_vagrancy_is_non_crime(self):
        """التشرد → non_crime"""
        result = is_non_crime("هل التشرد جريمة في قانون العقوبات؟")
        assert result is not None

    def test_dual_nationality_is_non_crime(self):
        """ازدواج الجنسية → non_crime"""
        result = is_non_crime("هل ازدواج الجنسية جريمة في قطر؟")
        assert result is not None

    def test_theft_is_not_non_crime(self):
        """السرقة ليست في قائمة غير المجرَّمات → None"""
        result = is_non_crime("ما عقوبة السرقة في قطر؟")
        assert result is None

    def test_murder_is_not_non_crime(self):
        """القتل جريمة — ليس في قائمة غير المجرَّمات"""
        result = is_non_crime("ما عقوبة القتل العمد؟")
        assert result is None

    def test_murder_has_known_answer_with_article(self):
        """القتل العمد له إجابة معلَّبة تحتوي مادة 300"""
        result = match_known_answer("ما عقوبة القتل العمد في قطر؟")
        assert result is not None
        assert "300" in result

    def test_empty_returns_none(self):
        result = is_non_crime("")
        assert result is None

    def test_none_returns_none(self):
        result = is_non_crime(None)
        assert result is None

    def test_non_crime_has_interpretation(self):
        """نتيجة غير المجرَّم تحتوي التفسير"""
        result = is_non_crime("ما حكم محاولة الانتحار في القانون القطري؟")
        assert result is not None
        assert "التفسير" in result
        assert len(result["التفسير"]) > 10


# ══════════════════════════════════════════════════════════════
# اختبارات get_domain_threshold
# ══════════════════════════════════════════════════════════════
class TestGetDomainThreshold:

    def test_criminal_threshold(self):
        assert get_domain_threshold("جنائي") >= 0.55

    def test_labor_threshold(self):
        assert get_domain_threshold("عمالي") <= 0.50

    def test_default_threshold(self):
        t = get_domain_threshold("")
        assert 0.0 < t <= 1.0

    def test_unknown_domain_returns_default(self):
        t = get_domain_threshold("مجال_غريب_جداً")
        assert t == DOMAIN_THRESHOLDS["default"]

    def test_threshold_in_range(self):
        for domain in DOMAIN_THRESHOLDS:
            t = get_domain_threshold(domain)
            assert 0.0 <= t <= 1.0, f"domain={domain} threshold={t} خارج النطاق"


# ══════════════════════════════════════════════════════════════
# اختبارات المحتوى
# ══════════════════════════════════════════════════════════════
class TestContent:

    def test_known_answer_suicide_not_criminal(self):
        """إجابة الانتحار تُؤكد عدم التجريم"""
        ans = QATAR_KNOWN_ANSWERS["محاولة_الانتحار"]
        assert "لا" in ans or "غير" in ans  # لا توجد عقوبة / غير مجرَّمة

    def test_known_answer_notice_period_has_one_month(self):
        """إجابة الإشعار تذكر شهراً"""
        ans = QATAR_KNOWN_ANSWERS["مدة_إشعار_إنهاء_العقد"]
        assert "شهر" in ans

    def test_known_answer_gratuity_has_3_weeks(self):
        """إجابة المكافأة تذكر 3 أسابيع"""
        ans = QATAR_KNOWN_ANSWERS["مكافأة_نهاية_الخدمة"]
        assert "3" in ans or "ثلاثة" in ans

    def test_known_answer_rehabilitation_has_conditions(self):
        """إجابة رد الاعتبار تذكر الشروط"""
        ans = QATAR_KNOWN_ANSWERS["رد_الاعتبار"]
        assert "شروط" in ans or "سنوات" in ans or "سنة" in ans

    def test_non_crime_suicide_says_no_punishment(self):
        """وصف غير الجريمة للانتحار يذكر عدم العقوبة"""
        nc = Qatar_NON_CRIMES["محاولة الانتحار"]
        assert "غير" in nc["الحكم"] or "لا" in nc["التفسير"]

    def test_synonyms_list_not_empty(self):
        """كل قيمة في المرادفات قائمة غير فارغة"""
        for key, vals in QATAR_LEGAL_SYNONYMS.items():
            assert isinstance(vals, list), f"قيمة '{key}' ليست قائمة"
            assert len(vals) > 0, f"قيمة '{key}' فارغة"

    def test_capability_response_mentions_qatar(self):
        """رد القدرات يذكر القانون القطري"""
        assert "قطر" in SYSTEM_CAPABILITY_RESPONSE or "قطري" in SYSTEM_CAPABILITY_RESPONSE
