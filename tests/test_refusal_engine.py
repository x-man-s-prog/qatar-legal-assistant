# -*- coding: utf-8 -*-
"""
Tests for Deterministic Refusal Engine
=======================================
Validates:
1. Every structured intent gets a deterministic refusal
2. No LLM is ever called (mock guard)
3. Refusals are short and style-clean
4. Context-aware enrichment works
5. Hint mode suggests nearest grade
6. Assertion guards catch violations
7. No-pool refusals work
"""
import sys, os, re, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.refusal_engine import (
    generate_refusal,
    generate_no_pool_refusal,
    is_structured_intent,
    assert_refusal_clean,
    STRUCTURED_INTENTS,
    _enforce_refusal_style,
    _extract_grade_from_query,
    _find_nearest_grade,
)


# ══════════════════════════════════════════════════════════════
# 1. Basic refusal generation — every structured intent
# ══════════════════════════════════════════════════════════════

class TestBasicRefusals:
    """Every structured intent must produce a non-empty, short, clean refusal."""

    @pytest.mark.parametrize("intent", list(STRUCTURED_INTENTS))
    def test_all_intents_produce_refusal(self, intent):
        result = generate_refusal(intent)
        assert result, f"Empty refusal for {intent}"
        assert len(result) <= 200, f"Refusal too long for {intent}: {len(result)} chars"
        assert "📋" not in result
        assert "⚖️" not in result
        assert "بناءً على" not in result
        assert "يمكنك مراجعة" not in result

    def test_salary_refusal_content(self):
        r = generate_refusal("salary_query")
        assert "بيانات" in r or "الدرجة" in r or "الرواتب" in r

    def test_drug_refusal_content(self):
        r = generate_refusal("drug_table")
        assert "المواد" in r or "قائمة" in r

    def test_table_refusal_content(self):
        r = generate_refusal("table_lookup")
        assert "الجدول" in r or "متوفر" in r

    def test_enum_refusal_content(self):
        r = generate_refusal("enumeration_list")
        assert "القائمة" in r or "متوفرة" in r

    def test_unknown_intent_fallback(self):
        r = generate_refusal("unknown_intent")
        assert r, "Should produce fallback refusal"
        assert len(r) <= 200


# ══════════════════════════════════════════════════════════════
# 2. Intent classification guard
# ══════════════════════════════════════════════════════════════

class TestIntentGuard:
    """is_structured_intent must correctly identify structured intents."""

    def test_salary_is_structured(self):
        assert is_structured_intent("salary_query")

    def test_drug_is_structured(self):
        assert is_structured_intent("drug_table")

    def test_table_is_structured(self):
        assert is_structured_intent("table_lookup")

    def test_enum_is_structured(self):
        assert is_structured_intent("enumeration_list")

    def test_general_legal_is_NOT_structured(self):
        assert not is_structured_intent("general_legal")

    def test_article_lookup_is_NOT_structured(self):
        assert not is_structured_intent("article_lookup")

    def test_empty_is_NOT_structured(self):
        assert not is_structured_intent("")

    def test_random_is_NOT_structured(self):
        assert not is_structured_intent("foo_bar")


# ══════════════════════════════════════════════════════════════
# 3. Context-aware salary refusals
# ══════════════════════════════════════════════════════════════

class TestContextAwareRefusals:
    """Salary refusals should mention specific grades when possible."""

    def test_salary_with_grade_seven(self):
        r = generate_refusal("salary_query", "كم راتب الدرجة السابعة")
        assert "السابعة" in r

    def test_salary_with_grade_first(self):
        r = generate_refusal("salary_query", "راتب الدرجة الأولى")
        assert "الأولى" in r

    def test_salary_with_grade_special(self):
        r = generate_refusal("salary_query", "كم راتب الدرجة الممتازة")
        assert "الممتازة" in r

    def test_salary_without_grade(self):
        r = generate_refusal("salary_query", "كم الراتب")
        # Should still produce valid refusal without grade personalization
        assert r and len(r) <= 200

    def test_table_with_number(self):
        r = generate_refusal("table_lookup", "أريد جدول رقم 3")
        assert "3" in r

    def test_enum_with_entity(self):
        r = generate_refusal("enumeration_list", "اذكر لي المواد الكيميائية")
        # Should mention what was asked about
        assert "كيميائي" in r or "قائمة" in r or "القائمة" in r


# ══════════════════════════════════════════════════════════════
# 4. Hint mode — nearest grade suggestion
# ══════════════════════════════════════════════════════════════

class TestHintMode:
    """When a grade doesn't exist, suggest the nearest valid one."""

    def test_grade_ten_hints_seven(self):
        r = generate_refusal("salary_query", "كم راتب الدرجة العاشرة", enable_hints=True)
        assert "السابعة" in r, f"Should hint at السابعة, got: {r}"

    def test_grade_nine_hints_seven(self):
        r = generate_refusal("salary_query", "كم راتب الدرجة التاسعة", enable_hints=True)
        assert "السابعة" in r

    def test_grade_eight_hints_seven(self):
        r = generate_refusal("salary_query", "كم راتب الدرجة الثامنة", enable_hints=True)
        assert "السابعة" in r

    def test_valid_grade_no_hint(self):
        # Grade 5 exists — no hint needed
        r = generate_refusal("salary_query", "كم راتب الدرجة الخامسة", enable_hints=True)
        # Should NOT contain "أقرب درجة" since grade 5 is valid
        assert "أقرب" not in r

    def test_hints_disabled(self):
        r = generate_refusal("salary_query", "كم راتب الدرجة العاشرة", enable_hints=False)
        # Should NOT contain hint when disabled
        assert "أقرب" not in r


# ══════════════════════════════════════════════════════════════
# 5. No-pool refusals
# ══════════════════════════════════════════════════════════════

class TestNoPoolRefusal:
    """When DB pool is unavailable, return deterministic refusal."""

    def test_no_pool_returns_refusal(self):
        r = generate_no_pool_refusal("salary_query")
        assert r
        assert "قاعدة البيانات" in r or "غير متصلة" in r

    def test_no_pool_is_short(self):
        r = generate_no_pool_refusal("drug_table")
        assert len(r) <= 200

    def test_no_pool_no_forbidden(self):
        r = generate_no_pool_refusal("table_lookup")
        assert "📋" not in r
        assert "⚖️" not in r


# ══════════════════════════════════════════════════════════════
# 6. Assertion guard
# ══════════════════════════════════════════════════════════════

class TestAssertionGuard:
    """assert_refusal_clean must catch violations."""

    def test_clean_refusal_passes(self):
        text = "لا توجد بيانات دقيقة في النظام لهذه الدرجة حالياً."
        assert_refusal_clean(text, "salary_query")  # Should not raise

    def test_empty_refusal_fails(self):
        with pytest.raises(AssertionError, match="empty refusal"):
            assert_refusal_clean("", "salary_query")

    def test_long_refusal_fails(self):
        with pytest.raises(AssertionError, match="too long"):
            assert_refusal_clean("x" * 201, "salary_query")

    def test_forbidden_marker_fails(self):
        with pytest.raises(AssertionError, match="forbidden marker"):
            assert_refusal_clean("📋 الجدول غير متوفر", "table_lookup")

    def test_forbidden_phrase_fails(self):
        with pytest.raises(AssertionError, match="forbidden phrase"):
            assert_refusal_clean("بناءً على المعطيات لا يوجد", "salary_query")

    def test_multiline_refusal_fails(self):
        with pytest.raises(AssertionError, match="too many lines"):
            assert_refusal_clean("line1\nline2\nline3", "salary_query")


# ══════════════════════════════════════════════════════════════
# 7. Style enforcement
# ══════════════════════════════════════════════════════════════

class TestStyleEnforcement:
    """_enforce_refusal_style must strip all forbidden content."""

    def test_strips_emoji(self):
        r = _enforce_refusal_style("📋 الجدول غير متوفر")
        assert "📋" not in r

    def test_strips_phrases(self):
        r = _enforce_refusal_style("بناءً على المعطيات، لا يوجد")
        assert "بناءً على" not in r

    def test_caps_length(self):
        r = _enforce_refusal_style("a" * 300)
        assert len(r) <= 200

    def test_never_empty(self):
        r = _enforce_refusal_style("")
        assert r  # Should return fallback

    def test_collapses_whitespace(self):
        r = _enforce_refusal_style("  لا   توجد    بيانات  ")
        assert "   " not in r


# ══════════════════════════════════════════════════════════════
# 8. Grade extraction helpers
# ══════════════════════════════════════════════════════════════

class TestGradeExtraction:
    def test_extract_seventh(self):
        assert _extract_grade_from_query("كم راتب الدرجة السابعة") == "السابعة"

    def test_extract_first(self):
        assert _extract_grade_from_query("راتب الدرجة الأولى") == "الأولى"

    def test_extract_special(self):
        assert _extract_grade_from_query("الدرجة الممتازة") == "الممتازة"

    def test_extract_tenth(self):
        assert _extract_grade_from_query("الدرجة العاشرة") == "العاشرة"

    def test_no_grade(self):
        assert _extract_grade_from_query("كم الراتب") is None

    def test_nearest_for_tenth(self):
        assert _find_nearest_grade("العاشرة") == "السابعة"

    def test_nearest_for_valid(self):
        assert _find_nearest_grade("الخامسة") is None  # No hint needed


# ══════════════════════════════════════════════════════════════
# 9. Zero-LLM guarantee — no LLM module imported
# ══════════════════════════════════════════════════════════════

class TestNoLLMDependency:
    """The refusal engine must not import or call any LLM module."""

    def test_no_openai_import(self):
        import core.refusal_engine as mod
        source = open(mod.__file__, encoding="utf-8").read()
        assert "openai" not in source.lower()
        assert "stream_openai" not in source
        assert "stream_gemini" not in source
        assert "stream_claude" not in source
        assert "stream_ollama" not in source
        assert "_generate_answer" not in source

    def test_no_llm_call_in_generate(self):
        """Run generate_refusal for all intents and verify it returns synchronously."""
        for intent in STRUCTURED_INTENTS:
            # If this were async or called LLM, it would fail or hang
            r = generate_refusal(intent, "test query")
            assert isinstance(r, str)
            assert len(r) > 0
