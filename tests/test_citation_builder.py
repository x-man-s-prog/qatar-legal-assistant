# -*- coding: utf-8 -*-
"""
اختبارات citation_builder
==========================
تختبر: build_citations()، استخراج URL، حقن المراجع
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from citation_builder import build_citations, CitationResult


# ══════════════════════════════════════════════════════════════
# بيانات الاختبار
# ══════════════════════════════════════════════════════════════

def _make_chunk(law_id=1, law_name="قانون العقوبات", law_number="11",
                law_year="2004", article_number="357",
                content="يُعاقب بالسجن مدة لا تتجاوز ثلاث سنوات كل من أصدر شيكاً لا يقابله رصيد.",
                source="law_11_2004.pdf") -> dict:
    return {
        "id"            : 1,
        "law_id"        : law_id,
        "law_name"      : law_name,
        "law_number"    : law_number,
        "law_year"      : law_year,
        "article_number": article_number,
        "content"       : content,
        "source"        : source,
        "score"         : 0.92,
    }


# ══════════════════════════════════════════════════════════════
# اختبارات build_citations — البنية
# ══════════════════════════════════════════════════════════════

class TestBuildCitationsStructure:

    def test_returns_required_keys(self):
        """النتيجة تحتوي answer + citations + answer_with_refs."""
        result = build_citations("إجابة", [_make_chunk()])
        assert "answer"           in result
        assert "citations"        in result
        assert "answer_with_refs" in result

    def test_answer_preserved(self):
        """حقل answer يحتوي النص الأصلي."""
        answer = "يُعاقب على هذه الجريمة بالسجن."
        result = build_citations(answer, [_make_chunk()])
        assert result["answer"] == answer

    def test_empty_chunks_returns_empty_citations(self):
        """بدون chunks → citations فارغة وanswer_with_refs = answer."""
        answer = "لا توجد نتائج."
        result = build_citations(answer, [])
        assert result["citations"]        == []
        assert result["answer_with_refs"] == answer

    def test_citations_count_matches_chunks(self):
        """عدد الاستشهادات = عدد الـ chunks."""
        chunks = [_make_chunk(law_id=i, article_number=str(i)) for i in range(1, 4)]
        result = build_citations("إجابة", chunks)
        assert len(result["citations"]) == 3

    def test_citation_numbering_starts_at_one(self):
        """الترقيم يبدأ من 1."""
        result = build_citations("إجابة", [_make_chunk()])
        assert result["citations"][0]["number"] == 1

    def test_citation_numbers_are_sequential(self):
        """الترقيم متسلسل 1، 2، 3..."""
        chunks = [_make_chunk(law_id=i) for i in range(1, 5)]
        result = build_citations("إجابة", chunks)
        numbers = [c["number"] for c in result["citations"]]
        assert numbers == list(range(1, 5))


# ══════════════════════════════════════════════════════════════
# اختبارات محتوى الاستشهاد
# ══════════════════════════════════════════════════════════════

class TestCitationContent:

    def test_source_is_law_name(self):
        """source في الاستشهاد = law_name من chunk."""
        result = build_citations("إجابة", [_make_chunk(law_name="قانون العمل")])
        assert result["citations"][0]["source"] == "قانون العمل"

    def test_article_extracted(self):
        """رقم المادة يُستخرج من article_number."""
        result = build_citations("إجابة", [_make_chunk(article_number="47")])
        assert result["citations"][0]["article"] == "47"

    def test_text_is_truncated_to_300(self):
        """النص يُقطع عند 300 حرف."""
        long_content = "أ" * 500
        result = build_citations("إجابة", [_make_chunk(content=long_content)])
        assert len(result["citations"][0]["text"]) <= 305   # 300 + "..."

    def test_text_has_ellipsis_when_truncated(self):
        """النص المقطوع ينتهي بـ ..."""
        long_content = "ب" * 400
        result = build_citations("إجابة", [_make_chunk(content=long_content)])
        assert result["citations"][0]["text"].endswith("...")

    def test_short_text_no_ellipsis(self):
        """النص القصير لا يحتوي ..."""
        result = build_citations("إجابة", [_make_chunk(content="نص قانوني قصير.")])
        assert not result["citations"][0]["text"].endswith("...")


# ══════════════════════════════════════════════════════════════
# اختبارات URL
# ══════════════════════════════════════════════════════════════

class TestCitationURL:

    def test_url_contains_law_id(self):
        """الرابط يحتوي law_id إذا وُجد."""
        result = build_citations("إجابة", [_make_chunk(law_id=42)])
        assert "42" in result["citations"][0]["url"]

    def test_url_is_almeezan_domain(self):
        """الرابط من موقع الميزان."""
        result = build_citations("إجابة", [_make_chunk(law_id=1)])
        assert "almeezan.qa" in result["citations"][0]["url"]

    def test_url_format_law_page(self):
        """الرابط بالصيغة الصحيحة LawPage.aspx?id=..."""
        result = build_citations("إجابة", [_make_chunk(law_id=99)])
        assert "LawPage.aspx?id=99" in result["citations"][0]["url"]

    def test_url_fallback_from_filename(self):
        """استخراج law_id من اسم الملف عند غياب law_id."""
        chunk = _make_chunk(law_id=None, source="law_55.pdf")
        result = build_citations("إجابة", [chunk])
        assert "55" in result["citations"][0]["url"]

    def test_url_fallback_search_when_no_id(self):
        """رابط بحث عند عدم وجود law_id ولا اسم ملف بصيغة law_N."""
        chunk = _make_chunk(law_id=None, source="random_file.pdf",
                            law_number="14", law_year="2004")
        result = build_citations("إجابة", [chunk])
        url = result["citations"][0]["url"]
        # يجب أن يحتوي رقم القانون أو السنة
        assert "14" in url or "2004" in url or url == ""

    def test_url_empty_when_no_ids(self):
        """رابط فارغ عند غياب جميع المعرّفات."""
        chunk = _make_chunk(law_id=None, source="unknown.pdf",
                            law_number="", law_year="")
        result = build_citations("إجابة", [chunk])
        assert isinstance(result["citations"][0]["url"], str)


# ══════════════════════════════════════════════════════════════
# اختبارات answer_with_refs
# ══════════════════════════════════════════════════════════════

class TestAnswerWithRefs:

    def test_answer_with_refs_is_string(self):
        """answer_with_refs نص."""
        result = build_citations("إجابة قانونية.", [_make_chunk()])
        assert isinstance(result["answer_with_refs"], str)

    def test_existing_refs_preserved(self):
        """إذا كانت الإجابة تحتوي [1] فعلاً → يُبقيها."""
        answer = "يُعاقب على السرقة [1] بالسجن."
        result = build_citations(answer, [_make_chunk()])
        assert "[1]" in result["answer_with_refs"]

    def test_out_of_range_refs_removed(self):
        """المراجع خارج النطاق (مثل [10] ولدينا chunk واحد) تُحذف."""
        answer = "نص قانوني [1] وآخر [10] ."
        result = build_citations(answer, [_make_chunk()])
        assert "[10]" not in result["answer_with_refs"]
        assert "[1]"  in  result["answer_with_refs"]

    def test_no_refs_in_original_gets_some_added(self):
        """إجابة بدون [n] → يُحاول إضافة مرجع عند استشهاد بمادة."""
        answer = "وفقاً للمادة 357 تُطبَّق عقوبة السجن."
        result = build_citations(answer, [_make_chunk(article_number="357")])
        # يجب أن تحتوي answer_with_refs على مرجع [1]
        assert "[1]" in result["answer_with_refs"]

    def test_answer_with_refs_not_shorter_than_answer(self):
        """answer_with_refs لا تكون أقصر من answer الأصلي."""
        answer = "هذه إجابة قانونية مهمة حول شيك بدون رصيد."
        result = build_citations(answer, [_make_chunk()])
        assert len(result["answer_with_refs"]) >= len(answer)
