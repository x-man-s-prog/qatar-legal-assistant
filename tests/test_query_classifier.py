# -*- coding: utf-8 -*-
"""
اختبارات query_classifier
============================
تختبر: classify_query, get_search_params, format_badge, helpers.
Pure functions — لا DB ولا LLM.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from query_classifier import (
    classify_query,
    get_search_params,
    format_badge,
    _classify_type,
    _classify_domain,
    _classify_complexity,
)

VALID_TYPES       = {"factual", "procedural", "comparative", "hypothetical"}
VALID_DOMAINS     = {"عمالي", "أسري", "جزائي", "مدني", "تجاري", "إداري", "أخرى"}
VALID_COMPLEXITIES = {"بسيط", "متوسط", "معقد"}


# ══════════════════════════════════════════════════════════════
# TestClassifyType
# ══════════════════════════════════════════════════════════════
class TestClassifyType:
    def test_comparative_detected(self):
        assert _classify_type("ما الفرق بين قانون العمل وقانون الخدمة المدنية؟") == "comparative"

    def test_comparative_verb(self):
        assert _classify_type("قارن بين عقوبتَي السرقة والاعتداء") == "comparative"

    def test_procedural_كيف(self):
        assert _classify_type("كيف أرفع دعوى قضائية؟") == "procedural"

    def test_procedural_إجراءات(self):
        assert _classify_type("ما إجراءات الطلاق في قطر؟") == "procedural"

    def test_hypothetical_إذا(self):
        assert _classify_type("إذا رفض صاحب العمل دفع الراتب ما الحل؟") == "hypothetical"

    def test_hypothetical_لو(self):
        assert _classify_type("لو لم يُسجَّل العقد هل يبقى صحيحاً؟") == "hypothetical"

    def test_factual_default(self):
        assert _classify_type("ما عقوبة السرقة في قطر؟") == "factual"

    def test_factual_empty(self):
        assert _classify_type("") == "factual"


# ══════════════════════════════════════════════════════════════
# TestClassifyDomain
# ══════════════════════════════════════════════════════════════
class TestClassifyDomain:
    def test_labor_domain(self):
        assert _classify_domain("ما حقوق العامل في نهاية الخدمة؟") == "عمالي"

    def test_family_domain(self):
        assert _classify_domain("ما أحكام الطلاق في القانون القطري؟") == "أسري"

    def test_criminal_domain(self):
        assert _classify_domain("ما عقوبة السرقة؟") == "جزائي"

    def test_civil_domain(self):
        assert _classify_domain("ما هي شروط صحة عقد البيع؟") == "مدني"

    def test_commercial_domain(self):
        assert _classify_domain("ما إجراءات تأسيس شركة في قطر؟") == "تجاري"

    def test_admin_domain(self):
        assert _classify_domain("ما حقوق الموظف في الخدمة المدنية؟") == "إداري"

    def test_unknown_returns_other(self):
        assert _classify_domain("ما طقس الدوحة اليوم؟") == "أخرى"

    def test_empty_returns_other(self):
        assert _classify_domain("") == "أخرى"


# ══════════════════════════════════════════════════════════════
# TestClassifyComplexity
# ══════════════════════════════════════════════════════════════
class TestClassifyComplexity:
    def test_complex_detected(self):
        assert _classify_complexity("ما حالات التعارض بين قانون العمل وقانون الإقامة؟") == "معقد"

    def test_complex_lawsuit(self):
        assert _classify_complexity("كيف أرفع دعوى استئناف أمام محكمة الاستئناف؟") == "معقد"

    def test_simple_ما(self):
        assert _classify_complexity("ما تعريف عقد الإيجار؟") == "بسيط"

    def test_simple_هل(self):
        assert _classify_complexity("هل الوصية واجبة قانوناً؟") == "بسيط"

    def test_medium_default(self):
        assert _classify_complexity("أريد معرفة حقوقي في قضية عمالية") == "متوسط"


# ══════════════════════════════════════════════════════════════
# TestClassifyQuery — combined
# ══════════════════════════════════════════════════════════════
class TestClassifyQuery:
    def test_returns_all_keys(self):
        result = classify_query("ما عقوبة السرقة؟")
        assert "query_type"  in result
        assert "domain"      in result
        assert "complexity"  in result

    def test_all_values_in_valid_sets(self):
        queries = [
            "ما عقوبة السرقة؟",
            "كيف أرفع دعوى طلاق؟",
            "قارن قانون العمل وقانون الخدمة المدنية",
            "إذا رفض صاحب العمل الراتب ما الحل؟",
            "ما طقس الدوحة؟",
        ]
        for q in queries:
            c = classify_query(q)
            assert c["query_type"]  in VALID_TYPES,       f"{q}: type={c['query_type']}"
            assert c["domain"]      in VALID_DOMAINS,     f"{q}: domain={c['domain']}"
            assert c["complexity"]  in VALID_COMPLEXITIES, f"{q}: complexity={c['complexity']}"

    def test_labor_query_classification(self):
        c = classify_query("كم مدة إشعار إنهاء عقد العمل في قطر؟")
        assert c["domain"]  == "عمالي"
        assert c["query_type"] in ("factual", "procedural")

    def test_criminal_query_classification(self):
        c = classify_query("ما عقوبة الاعتداء الجسدي؟")
        assert c["domain"] == "جزائي"

    def test_family_query_classification(self):
        c = classify_query("ما حقوق المرأة في الطلاق؟")
        assert c["domain"] == "أسري"

    def test_empty_query_no_crash(self):
        c = classify_query("")
        assert c["query_type"] == "factual"
        assert c["domain"]     == "أخرى"


# ══════════════════════════════════════════════════════════════
# TestGetSearchParams
# ══════════════════════════════════════════════════════════════
class TestGetSearchParams:
    def test_comparative_triggers_compare(self):
        c = classify_query("قارن قانون العمل وقانون الخدمة المدنية")
        params = get_search_params(c)
        assert params["trigger_compare"] is True

    def test_factual_simple_vector_only(self):
        params = get_search_params({"query_type": "factual", "domain": "أخرى", "complexity": "بسيط"})
        assert params["use_keyword"] is False
        assert params["top_k"] == 8

    def test_complex_increases_top_k(self):
        params = get_search_params({"query_type": "factual", "domain": "جزائي", "complexity": "معقد"})
        assert params["top_k"] == 15

    def test_default_params(self):
        params = get_search_params({"query_type": "factual", "domain": "عمالي", "complexity": "متوسط"})
        assert params["top_k"]           == 10
        assert params["use_vector"]      is True
        assert params["use_keyword"]     is True
        assert params["trigger_compare"] is False

    def test_procedural_uses_both_search_types(self):
        params = get_search_params({"query_type": "procedural", "domain": "مدني", "complexity": "متوسط"})
        assert params["use_vector"]  is True
        assert params["use_keyword"] is True


# ══════════════════════════════════════════════════════════════
# TestFormatBadge
# ══════════════════════════════════════════════════════════════
class TestFormatBadge:
    def test_badge_contains_domain(self):
        c = classify_query("ما عقوبة السرقة؟")
        badge = format_badge(c)
        assert "جزائي" in badge

    def test_badge_contains_complexity(self):
        c = classify_query("ما تعريف عقد البيع؟")
        badge = format_badge(c)
        assert "بسيط" in badge or "متوسط" in badge

    def test_badge_contains_icon(self):
        c = {"query_type": "comparative", "domain": "عمالي", "complexity": "متوسط"}
        badge = format_badge(c)
        assert "⚖️" in badge

    def test_badge_non_empty(self):
        for q in ["ما؟", "كيف؟", "قارن؟", "إذا؟"]:
            assert format_badge(classify_query(q)) != ""
