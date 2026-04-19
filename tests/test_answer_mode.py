# -*- coding: utf-8 -*-
"""Tests for answer mode classification, post-processing, and context persistence."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.answer_mode import (
    classify_answer_mode, build_prompt_instruction,
    post_process_answer, AnswerMode, ConversationContext,
)

# ══ Classification ══

def test_salary_direct():
    assert classify_answer_mode("كم راتب الدرجة السابعة") == AnswerMode.DIRECT_SHORT

def test_salary_table():
    assert classify_answer_mode("جدول الرواتب", lookup_intent="salary_query") == AnswerMode.TABLE_ROW

def test_drug_list():
    """Drug names request → STRUCTURED_LIST when user asks for list."""
    assert classify_answer_mode("اكتب أسماء المواد المخدرة فوق بعض",
                                 lookup_intent="drug_table") == AnswerMode.STRUCTURED_LIST

def test_drug_table():
    assert classify_answer_mode("جدول المخدرات", lookup_intent="drug_table") == AnswerMode.TABLE_ROW

def test_brevity_signal():
    assert classify_answer_mode("ما عقوبة السرقة بشكل مختصر") == AnswerMode.DIRECT_SHORT

def test_legal_analysis():
    assert classify_answer_mode("ما أثر بطلان القبض على صحة الاعتراف") == AnswerMode.LEGAL_ANALYSIS

def test_followup_narrowing():
    assert classify_answer_mode("أنا سألت عن الدرجة السابعة فقط",
                                 history=[{"role":"user","content":"x"},{"role":"assistant","content":"y"}]) == AnswerMode.FOLLOWUP_SHORT

def test_greeting_direct():
    assert classify_answer_mode("مرحبا", brain_route="greeting") == AnswerMode.DIRECT_SHORT

def test_short_query_direct():
    assert classify_answer_mode("ما عقوبة السرقة") == AnswerMode.DIRECT_SHORT


# ══ Prompt Instructions ══

def test_direct_no_memo():
    inst = build_prompt_instruction(AnswerMode.DIRECT_SHORT)
    assert "📋" not in inst  # No emoji-style memo headers
    assert "رتّب:" not in inst  # No "arrange: X/Y/Z" pattern
    assert "مباشر" in inst

def test_analysis_has_structure_guidance():
    """LEGAL_ANALYSIS should guide LLM to structured response for complex queries."""
    inst = build_prompt_instruction(AnswerMode.LEGAL_ANALYSIS)
    # Must mention direct answer and legal basis
    assert "الإجابة المباشرة" in inst or "السند" in inst
    # Must mention the icon structure for personal consultations
    assert "📋" in inst or "الهيكل" in inst or "استشارات" in inst

def test_list_has_numbered():
    inst = build_prompt_instruction(AnswerMode.STRUCTURED_LIST, "اكتب أسماء المواد فوق بعض")
    assert "قائمة" in inst or "مرقم" in inst.lower() or "سطر" in inst

def test_user_pref_no_explanation():
    inst = build_prompt_instruction(AnswerMode.DIRECT_SHORT, "بدون شرح كم الراتب")
    assert "بدون" in inst


# ══ Post-Processing ══

def test_strip_memo_headers():
    text = "📋 التكييف القانوني:\nهذا سؤال بسيط.\n⚖️ السند:\nلا يوجد.\n✅ التوصية:\nالإجابة هنا."
    result = post_process_answer(text, AnswerMode.DIRECT_SHORT)
    assert "📋" not in result
    assert "⚖️" not in result
    assert "الإجابة هنا" in result

def test_keep_memo_for_analysis():
    text = "📋 التكييف القانوني:\nتحليل مفصل هنا.\n⚖️ السند:\nالمادة 300."
    result = post_process_answer(text, AnswerMode.LEGAL_ANALYSIS)
    assert "📋" in result  # Kept for analysis mode


# ══ Context Persistence ══

def test_context_topic_lock():
    ctx = ConversationContext()
    ctx.update("كم راتب موظف درجة سابعة", lookup_intent="salary_query")
    assert ctx.topic == "salary"
    assert "سابعة" in ctx.resolved_entity or "سابع" in ctx.resolved_entity
    # Simulate second turn
    ctx.update("وكم البدلات", lookup_intent="salary_query")
    assert ctx.should_stay_on_topic("طيب الدرجة السابعة بالضبط كم")

def test_context_prefs():
    ctx = ConversationContext()
    ctx.update("كم الراتب بدون شرح")
    assert "direct_only" in ctx.user_prefs


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__} — {e}")
            failed += 1
    print(f"\n  {passed}/{passed+failed} passed")
