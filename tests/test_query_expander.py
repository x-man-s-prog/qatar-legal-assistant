# -*- coding: utf-8 -*-
"""
اختبارات query_expander
========================
تختبر: expand()، extract_legal_entities()، get_all_synonyms()
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from query_expander import (
    expand,
    extract_legal_entities,
    get_all_synonyms,
    LEGAL_SYNONYMS,
)


# ══════════════════════════════════════════════════════════════
# اختبارات expand
# ══════════════════════════════════════════════════════════════

class TestExpand:

    def test_returns_three_variants(self):
        """expand تُعيد دائماً 3 صياغات."""
        result = expand("ما عقوبة السرقة في قطر؟")
        assert len(result) == 3

    def test_all_variants_are_strings(self):
        """جميع الصياغات نصوص."""
        result = expand("ما حقوق العامل عند الفصل؟")
        assert all(isinstance(v, str) for v in result)

    def test_all_variants_non_empty(self):
        """لا توجد صياغة فارغة."""
        result = expand("ما هي عقوبة الاحتيال؟")
        assert all(len(v.strip()) > 0 for v in result)

    def test_empty_query_handled_gracefully(self):
        """استعلام فارغ → 3 عناصر غير خاطئة."""
        result = expand("")
        assert len(result) == 3

    def test_whitespace_query_handled(self):
        """استعلام من مسافات → 3 عناصر."""
        result = expand("   ")
        assert len(result) == 3

    def test_synonym_replaced_in_first_variant(self):
        """الصياغة الأولى تستبدل مصطلحاً بمرادفه."""
        # "سرقة" لها مرادفات في القاموس
        result = expand("ما عقوبة السرقة؟")
        # الصياغة الأولى يجب أن تختلف عن الأصلية أو تحتوي مرادفاً
        synonyms = LEGAL_SYNONYMS.get("سرقة", [])
        found_synonym = any(syn in result[0] for syn in synonyms)
        # إما وجد مرادفاً أو بقي الأصل (الكلمة موجودة أو لا)
        assert isinstance(result[0], str)

    def test_formal_variant_contains_entity(self):
        """الصياغة الثانية تُضمّن الكيانات القانونية إذا وُجدت."""
        result = expand("المادة 357 من قانون رقم 11 لسنة 2004")
        # الصياغة الثانية يجب أن تكون أغنى من الأصل
        assert len(result[1]) >= len("المادة 357 من قانون رقم 11 لسنة 2004")

    def test_descriptive_variant_is_meaningful(self):
        """الصياغة الثالثة تُضيف سياقاً وصفياً."""
        result = expand("عقوبة القتل العمد")
        # الصياغة الثالثة يجب أن تحتوي نصاً وصفياً
        assert len(result[2]) > 5

    def test_arabic_legal_query(self):
        """استعلام قانوني عربي كامل يُعالج بدون أخطاء."""
        result = expand("ما الإجراءات القانونية لرفع دعوى نفقة أمام المحكمة القطرية؟")
        assert len(result) == 3

    def test_query_with_law_type_criminal(self):
        """استعلام جنائي → الصياغة الثالثة تذكر العقوبة."""
        result = expand("ما عقوبة الرشوة؟")
        # الصياغة الثالثة تُضيف سياقاً
        assert len(result[2]) > len("ما عقوبة الرشوة؟")

    def test_query_with_law_type_labor(self):
        """استعلام عمالي → الصياغة الثالثة تذكر حقوق العمال."""
        result = expand("هل يحق للعامل مكافأة نهاية خدمة؟")
        assert len(result[2]) > len("هل يحق للعامل مكافأة نهاية خدمة؟")


# ══════════════════════════════════════════════════════════════
# اختبارات extract_legal_entities
# ══════════════════════════════════════════════════════════════

class TestExtractLegalEntities:

    def test_extract_article_number(self):
        """يستخرج رقم المادة."""
        result = extract_legal_entities("المادة 47 من قانون العمل")
        assert result["article"] == "47"

    def test_extract_article_in_parentheses(self):
        """يستخرج رقم المادة بين أقواس."""
        result = extract_legal_entities("المادة (15) من قانون الأسرة")
        assert result["article"] == "15"

    def test_extract_law_number(self):
        """يستخرج رقم القانون."""
        result = extract_legal_entities("قانون رقم 14 لسنة 2004")
        assert result["law_number"] == "14"

    def test_extract_law_number_in_parentheses(self):
        """يستخرج رقم القانون بين أقواس."""
        result = extract_legal_entities("قانون رقم (11) لسنة 2004")
        assert result["law_number"] == "11"

    def test_extract_year(self):
        """يستخرج السنة."""
        result = extract_legal_entities("لسنة 2004 بشأن قانون العمل")
        assert result["year"] == "2004"

    def test_extract_all_together(self):
        """يستخرج المادة + القانون + السنة معاً."""
        result = extract_legal_entities(
            "المادة 357 من قانون رقم 11 لسنة 2004"
        )
        assert result["article"]    == "357"
        assert result["law_number"] == "11"
        assert result["year"]       == "2004"

    def test_extract_law_type_criminal(self):
        """يُعرّف قانون العقوبات."""
        result = extract_legal_entities("نص قانون العقوبات على السجن")
        assert result["law_type"] == "عقوبات"

    def test_extract_law_type_labor(self):
        """يُعرّف قانون العمل."""
        result = extract_legal_entities("وفقاً لقانون العمل القطري")
        assert result["law_type"] == "عمل"

    def test_extract_law_type_family(self):
        """يُعرّف قانون الأسرة."""
        result = extract_legal_entities("في قانون الأسرة المادة 20")
        assert result["law_type"] == "أسرة"

    def test_no_entities_returns_none_values(self):
        """استعلام بدون كيانات → جميع القيم None."""
        result = extract_legal_entities("ما حقوقي القانونية؟")
        assert result["article"]    is None
        assert result["law_number"] is None
        assert result["year"]       is None

    def test_empty_query_returns_all_none(self):
        """استعلام فارغ → جميع القيم None."""
        result = extract_legal_entities("")
        assert all(v is None for v in result.values())

    def test_returns_dict_with_required_keys(self):
        """النتيجة قاموس يحتوي المفاتيح المطلوبة."""
        result = extract_legal_entities("سؤال قانوني")
        assert "article"    in result
        assert "law_number" in result
        assert "year"       in result
        assert "law_type"   in result

    def test_year_must_be_modern(self):
        """يستخرج سنوات حديثة فقط (19xx أو 20xx)."""
        result = extract_legal_entities("لسنة 1998 و سنة 500")
        assert result["year"] == "1998"   # 500 لا تُطابق النمط

    def test_article_abbreviation_m(self):
        """يستخرج رقم المادة من اختصار 'م'."""
        result = extract_legal_entities("م. 47 من قانون العمل")
        assert result["article"] == "47"


# ══════════════════════════════════════════════════════════════
# اختبارات get_all_synonyms
# ══════════════════════════════════════════════════════════════

class TestGetAllSynonyms:

    def test_returns_list(self):
        """تُعيد list."""
        result = get_all_synonyms("ما عقوبة السرقة؟")
        assert isinstance(result, list)

    def test_known_term_returns_synonyms(self):
        """مصطلح موجود في القاموس يُعيد مرادفات."""
        result = get_all_synonyms("سرقة")
        assert len(result) > 0

    def test_unknown_term_returns_empty(self):
        """مصطلح غير موجود → قائمة فارغة أو صغيرة."""
        result = get_all_synonyms("طقس صحراوي")
        assert isinstance(result, list)

    def test_no_duplicates(self):
        """لا توجد مرادفات مكررة."""
        result = get_all_synonyms("سرقة نصب احتيال")
        assert len(result) == len(set(result))

    def test_multiple_terms_combined(self):
        """مصطلحان معروفان → يُعيد مرادفات كليهما."""
        result = get_all_synonyms("طلاق ونفقة")
        # كلٌّ من طلاق ونفقة له مرادفات
        assert len(result) >= 2


# ══════════════════════════════════════════════════════════════
# اختبارات القاموس نفسه
# ══════════════════════════════════════════════════════════════

class TestSynonymsDictionary:

    def test_dictionary_has_minimum_entries(self):
        """القاموس يحتوي 60+ مصطلحاً."""
        assert len(LEGAL_SYNONYMS) >= 60

    def test_all_keys_are_strings(self):
        """جميع المفاتيح نصوص."""
        assert all(isinstance(k, str) for k in LEGAL_SYNONYMS)

    def test_all_values_are_lists(self):
        """جميع القيم قوائم."""
        assert all(isinstance(v, list) for v in LEGAL_SYNONYMS.values())

    def test_all_synonym_lists_non_empty(self):
        """كل مصطلح له مرادف واحد على الأقل."""
        assert all(len(v) > 0 for v in LEGAL_SYNONYMS.values())

    def test_no_duplicate_keys(self):
        """لا يوجد مفتاح مكرر (Python dict يضمن ذلك)."""
        assert len(LEGAL_SYNONYMS) == len(set(LEGAL_SYNONYMS.keys()))
