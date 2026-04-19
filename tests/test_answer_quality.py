# -*- coding: utf-8 -*-
"""
Comprehensive tests for answer quality, routing, and style enforcement.
Tests the FULL pipeline: answer_mode → prompt instruction → post_process.
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.answer_mode import (
    classify_answer_mode, build_prompt_instruction, post_process_answer,
    get_context, AnswerMode, ConversationContext,
)
from core.structured_lookup import classify_query, QueryIntent
from core.nlp_utils import _is_topic_change, filter_history_for_llm, enrich_followup_query


# ══════════════════════════════════════════════════════════════
# A) Query Routing — wrong classification tests
# ══════════════════════════════════════════════════════════════

class TestQueryRouting:
    """Verify queries route to correct answer modes."""

    def test_simple_question_gets_direct(self):
        """Simple 'what' questions must NOT get full analysis."""
        mode = classify_answer_mode("ما الفرق بين الجنحة والجناية")
        assert mode in (AnswerMode.DIRECT_SHORT, AnswerMode.LEGAL_ANALYSIS)
        # Short questions must be DIRECT_SHORT
        mode2 = classify_answer_mode("ما عقوبة السرقة")
        assert mode2 == AnswerMode.DIRECT_SHORT  # 3 words

    def test_greeting_stays_short(self):
        mode = classify_answer_mode("مرحبا كيف حالك", brain_route="greeting")
        assert mode == AnswerMode.DIRECT_SHORT

    def test_salary_query_routes_to_table(self):
        mode = classify_answer_mode("كم راتب الدرجة السابعة", lookup_intent="salary_query")
        assert mode == AnswerMode.TABLE_ROW

    def test_salary_with_brevity_is_direct(self):
        mode = classify_answer_mode("كم راتب الدرجة السابعة فقط", lookup_intent="salary_query")
        assert mode == AnswerMode.DIRECT_SHORT

    def test_drug_list_request(self):
        mode = classify_answer_mode("اذكر اسماء المواد المخدرة فوق بعض", lookup_intent="drug_table")
        assert mode in (AnswerMode.STRUCTURED_LIST, AnswerMode.TABLE_ROW)

    def test_consultation_gets_analysis(self):
        mode = classify_answer_mode("واحد ضربني وكسر يدي وش اسوي", brain_route="consultation")
        assert mode == AnswerMode.LEGAL_ANALYSIS

    def test_memo_drafting_gets_analysis(self):
        mode = classify_answer_mode("اكتب مذكرة دفاع في قضية سرقة", brain_route="drafting")
        assert mode == AnswerMode.LEGAL_ANALYSIS


# ══════════════════════════════════════════════════════════════
# B) Answer Enforcement — style matching
# ══════════════════════════════════════════════════════════════

class TestAnswerEnforcement:
    """Verify the LLM instruction and post-processing enforce the right style."""

    def test_direct_instruction_no_memo(self):
        """DIRECT_SHORT instruction must explicitly ban memo structure."""
        inst = build_prompt_instruction(AnswerMode.DIRECT_SHORT)
        assert "لا تستخدم" in inst
        assert "مباشر" in inst

    def test_table_instruction_no_explanation(self):
        inst = build_prompt_instruction(AnswerMode.TABLE_ROW)
        assert "جدول" in inst or "صفوف" in inst
        assert "لا" in inst  # "لا تضف شرحاً طويلاً"

    def test_list_instruction_numbered(self):
        inst = build_prompt_instruction(AnswerMode.STRUCTURED_LIST, "اذكر المواد فوق بعض")
        assert "قائمة" in inst or "مرقم" in inst or "سطر" in inst

    def test_followup_no_repetition(self):
        inst = build_prompt_instruction(AnswerMode.FOLLOWUP_SHORT)
        assert "لا تعيد" in inst

    def test_post_process_strips_memo_headers(self):
        """Post-processing must strip 📋/⚖️/🔍 headers for non-analysis modes."""
        answer = "📋 التكييف:\nسرقة بسيطة\n⚖️ السند:\nالمادة 379\n🔍 التحليل:\nتحليل"
        result = post_process_answer(answer, AnswerMode.DIRECT_SHORT)
        assert "📋 التكييف" not in result
        assert "⚖️ السند" not in result
        assert "🔍 التحليل" not in result
        # Content should remain
        assert "سرقة" in result or "المادة" in result

    def test_post_process_keeps_analysis(self):
        """LEGAL_ANALYSIS mode should keep memo structure intact."""
        answer = "📋 التكييف:\nسرقة بسيطة\n⚖️ السند:\nالمادة 379"
        result = post_process_answer(answer, AnswerMode.LEGAL_ANALYSIS)
        assert result == answer  # Unchanged

    def test_brevity_signals_add_constraints(self):
        """'فقط' and 'بدون شرح' must add extra constraints."""
        inst = build_prompt_instruction(AnswerMode.DIRECT_SHORT, "كم الراتب فقط بدون شرح")
        assert "لا تضف" in inst or "بدون" in inst

    def test_post_process_strips_filler_opening(self):
        """Filler openings must be stripped for DIRECT_SHORT."""
        answer = "بناءً على النصوص القانونية المتوفرة، نعم يحق لك."
        result = post_process_answer(answer, AnswerMode.DIRECT_SHORT)
        assert not result.startswith("بناءً على النصوص")


# ══════════════════════════════════════════════════════════════
# C) Follow-Up Continuity
# ══════════════════════════════════════════════════════════════

class TestFollowUpContinuity:
    """Verify follow-up questions maintain context."""

    def test_topic_change_clears_history(self):
        """Topic change must clear LLM history."""
        history = [
            {"role": "user", "content": "ما عقوبة السرقة في قطر"},
            {"role": "assistant", "content": "العقوبة هي الحبس..."},
        ]
        # New topic: salary
        filtered = filter_history_for_llm("كم راتب الدرجة السابعة", history)
        assert filtered == []  # History cleared

    def test_same_topic_keeps_history(self):
        """Same topic must keep recent history."""
        history = [
            {"role": "user", "content": "ما عقوبة السرقة في قطر"},
            {"role": "assistant", "content": "العقوبة هي الحبس..."},
        ]
        filtered = filter_history_for_llm("وما عقوبة الشروع في السرقة", history)
        assert len(filtered) > 0  # History kept

    def test_conversation_context_tracks_topic(self):
        """ConversationContext must track salary topic."""
        ctx = ConversationContext()
        ctx.update("كم راتب الدرجة السابعة", lookup_intent="salary_query")
        assert ctx.topic == "salary"
        assert "السابعة" in ctx.resolved_entity or "سابعة" in ctx.resolved_entity

    def test_conversation_context_tracks_prefs(self):
        """User preference 'فقط' must be recorded."""
        ctx = ConversationContext()
        ctx.update("كم الراتب فقط بدون شرح")
        assert "direct_only" in ctx.user_prefs

    def test_followup_enrichment(self):
        """Short follow-up must be enriched with previous context."""
        history = [
            {"role": "user", "content": "ما عقوبة تعاطي المخدرات"},
            {"role": "assistant", "content": "العقوبة هي الحبس..."},
        ]
        enriched = enrich_followup_query("وبعدين", history)
        assert "سابق" in enriched or "تعاطي" in enriched

    def test_independent_query_not_enriched(self):
        """Query with its own topic must NOT be enriched."""
        history = [
            {"role": "user", "content": "ما عقوبة تعاطي المخدرات"},
            {"role": "assistant", "content": "العقوبة هي الحبس..."},
        ]
        result = enrich_followup_query("كم راتب الدرجة السابعة", history)
        # Should NOT prepend previous question context
        assert result == "كم راتب الدرجة السابعة"


# ══════════════════════════════════════════════════════════════
# D) Structured Lookup + Answer Mode Integration
# ══════════════════════════════════════════════════════════════

class TestLookupIntegration:
    """Verify structured lookup intent feeds into answer mode correctly."""

    def test_salary_lookup_intent(self):
        intent = classify_query("سلم الرواتب الحكومي")
        assert intent == QueryIntent.SALARY_QUERY
        mode = classify_answer_mode("سلم الرواتب الحكومي", lookup_intent=intent.value)
        assert mode == AnswerMode.TABLE_ROW

    def test_drug_lookup_intent(self):
        intent = classify_query("جدول المخدرات والمؤثرات العقلية")
        assert intent == QueryIntent.DRUG_TABLE
        mode = classify_answer_mode("جدول المخدرات", lookup_intent=intent.value)
        assert mode == AnswerMode.TABLE_ROW

    def test_enum_lookup_intent(self):
        intent = classify_query("اذكر اسماء المواد المحظورة")
        assert intent == QueryIntent.ENUMERATION_LIST
        mode = classify_answer_mode("اذكر اسماء", lookup_intent=intent.value)
        assert mode == AnswerMode.STRUCTURED_LIST

    def test_general_legal_no_lookup(self):
        intent = classify_query("ما حكم السرقة")
        assert intent == QueryIntent.GENERAL_LEGAL


# ══════════════════════════════════════════════════════════════
# E) Post-Processor — OCR Cleanup and Memo Suppression
# ══════════════════════════════════════════════════════════════

class TestPostProcessor:
    """Verify post-processing cleans answers properly."""

    def test_triple_newlines_cleaned(self):
        answer = "سطر أول\n\n\n\nسطر ثاني\n\n\n\n\nسطر ثالث"
        result = post_process_answer(answer, AnswerMode.DIRECT_SHORT)
        assert "\n\n\n" not in result

    def test_confidence_section_stripped(self):
        answer = "الإجابة هنا\n\n📊 الثقة:\n95% — مبنية على نص صريح"
        result = post_process_answer(answer, AnswerMode.DIRECT_SHORT)
        assert "📊 الثقة" not in result

    def test_empty_answer_handled(self):
        result = post_process_answer("", AnswerMode.DIRECT_SHORT)
        assert result == ""


# ══════════════════════════════════════════════════════════════
# F) Refusal Logic
# ══════════════════════════════════════════════════════════════

class TestRefusalLogic:
    """Verify system refuses when data is missing rather than hallucinating."""

    def test_salary_no_numbers_rejected(self):
        """Content without salary numbers must be rejected by enforcement."""
        from core.structured_lookup import _enforce_salary
        bad = "الدرجة الخاصة هي أعلى درجة في سلم الرواتب الحكومي"
        assert _enforce_salary(bad) == False

    def test_drug_no_substances_rejected(self):
        from core.structured_lookup import _enforce_drug_content
        bad = "يعاقب من يحوز أو يتعاطى المواد المخدرة بالسجن والغرامة"
        assert _enforce_drug_content(bad) == False

    def test_table_reference_not_content(self):
        from core.structured_lookup import _enforce_table_content
        bad = "تسري أحكام هذا القانون وفقاً للجدول المرفق بهذا القانون"
        assert _enforce_table_content(bad) == False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
