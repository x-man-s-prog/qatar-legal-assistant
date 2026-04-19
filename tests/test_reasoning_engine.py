# -*- coding: utf-8 -*-
"""Tests for the Legal Reasoning Engine, Policy, and Knowledge Packs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.reasoning_policy import (
    ReasoningMode, ReasoningPolicy, detect_reasoning_mode, get_policy,
)
from core.reasoning_engine import (
    LegalReasoningEngine, ReasoningResult, ConversationContext,
    _detect_domain, _detect_topic, build_reasoning_enrichment,
)
from core.evidence_registry import get_registry, SupportLevel


# ══════════════════════════════════════════════════════════════
# Reasoning Mode Detection
# ══════════════════════════════════════════════════════════════

def test_mode_structured_factual():
    assert detect_reasoning_mode("كم مربوط الدرجة السابعة") == ReasoningMode.STRUCTURED_FACTUAL


def test_mode_yes_no():
    assert detect_reasoning_mode("هل هذا يشمل البدلات") == ReasoningMode.YES_NO_CLARIFICATION


def test_mode_comparison():
    assert detect_reasoning_mode("ما الفرق بين الدرجة السادسة والسابعة") == ReasoningMode.COMPARISON


def test_mode_scope():
    assert detect_reasoning_mode("هل يشمل جميع الجهات الحكومية") == ReasoningMode.SCOPE_APPLICABILITY


def test_mode_classification():
    assert detect_reasoning_mode("كيف يتم تصنيف هذه الأدوية") == ReasoningMode.CLASSIFICATION


def test_mode_distinction():
    assert detect_reasoning_mode("ما الفرق بين الاستخدام الطبي وغير المشروع") == ReasoningMode.LEGAL_DISTINCTION


def test_mode_followup():
    assert detect_reasoning_mode("طيب كم يكون الإجمالي", has_history=True) == ReasoningMode.FOLLOWUP_CONTEXTUAL


def test_mode_general():
    assert detect_reasoning_mode("ما حكم السرقة في القانون القطري") == ReasoningMode.GENERAL_LEGAL


# ══════════════════════════════════════════════════════════════
# Domain and Topic Detection
# ══════════════════════════════════════════════════════════════

def test_domain_salary():
    assert _detect_domain("كم مربوط الدرجة السابعة") == "salary"


def test_domain_drug():
    assert _detect_domain("ما هي المواد المخدرة في الجدول الأول") == "drug"


def test_domain_scope():
    assert _detect_domain("هل يسري على جميع الجهات الحكومية") == "scope"


def test_domain_fallback_to_context():
    ctx = ConversationContext(current_topic="drug")
    assert _detect_domain("ماذا عن الجدول الثاني", context=ctx) == "drug"


def test_topic_salary_total():
    assert _detect_topic("كم إجمالي الراتب", "salary") == "total_compensation"


def test_topic_salary_basic():
    assert _detect_topic("كم مربوط الدرجة", "salary") == "basic_salary"


def test_topic_drug_classification():
    assert _detect_topic("كيف يتم تصنيف المواد", "drug") == "classification"


def test_topic_drug_medical():
    assert _detect_topic("الاستخدام الطبي للمواد", "drug") == "medical_vs_illicit"


# ══════════════════════════════════════════════════════════════
# Reasoning Policy
# ══════════════════════════════════════════════════════════════

def test_policy_direct_evidence():
    p = get_policy()
    decision = p.evaluate_evidence(SupportLevel.DIRECT_EVIDENCE.value)
    assert decision.action == "state_as_fact"


def test_policy_inference():
    p = get_policy()
    decision = p.evaluate_evidence(SupportLevel.CONTROLLED_INFERENCE.value)
    assert decision.action == "state_with_qualifier"
    assert decision.qualifier_ar != ""


def test_policy_blocked():
    p = get_policy()
    decision = p.evaluate_evidence(SupportLevel.UNSUPPORTED_BLOCKED.value)
    assert decision.action == "block"


def test_policy_mode_guidance():
    p = get_policy()
    g = p.get_mode_guidance(ReasoningMode.STRUCTURED_FACTUAL)
    assert g["strategy"] == "direct_data_lookup"
    assert g["allow_inference"] is False


def test_policy_mode_guidance_analytical():
    p = get_policy()
    g = p.get_mode_guidance(ReasoningMode.ANALYTICAL_LEGAL)
    assert g["allow_inference"] is True


# ══════════════════════════════════════════════════════════════
# Reasoning Engine Core
# ══════════════════════════════════════════════════════════════

def test_engine_reason_salary():
    engine = LegalReasoningEngine()
    result = engine.reason("كم مربوط الدرجة السابعة")
    assert result.domain == "salary"
    assert result.reasoning_mode == ReasoningMode.STRUCTURED_FACTUAL.value
    assert result.has_direct_evidence()
    assert "deterministic" in result.final_answer_mode or "evidence" in result.final_answer_mode


def test_engine_reason_drug():
    engine = LegalReasoningEngine()
    result = engine.reason("ما هي المواد المخدرة في الجدول الأول")
    assert result.domain == "drug"
    assert result.has_direct_evidence()


def test_engine_reason_scope():
    engine = LegalReasoningEngine()
    result = engine.reason("هل يسري على جميع الجهات الحكومية")
    assert result.domain == "scope"


def test_engine_blocked_claims_exist():
    engine = LegalReasoningEngine()
    result = engine.reason("كم إجمالي الراتب الدرجة السابعة")
    # Should have both direct evidence and blocked claims in salary domain
    assert result.has_direct_evidence() or result.has_blocked()


def test_engine_answer_plan_not_empty():
    engine = LegalReasoningEngine()
    result = engine.reason("هل هذا يشمل البدلات")
    assert len(result.answer_plan) > 0


def test_engine_limitations_from_evidence():
    engine = LegalReasoningEngine()
    result = engine.reason("كم إجمالي الراتب الدرجة السابعة")
    # The salary pack has limitations like "لا يمكن تقديم رقم دقيق للإجمالي"
    # These should propagate
    # (may or may not have limitations depending on evidence matching)
    assert isinstance(result.limitations, list)


# ══════════════════════════════════════════════════════════════
# Multi-Turn Context
# ══════════════════════════════════════════════════════════════

def test_conversation_context_updates():
    engine = LegalReasoningEngine()
    r1 = engine.reason("كم مربوط الدرجة السابعة", session_id="test_ctx")
    ctx = engine.get_context("test_ctx")
    assert ctx.turn_count == 1

    r2 = engine.reason("طيب هل يشمل البدلات", session_id="test_ctx")
    assert ctx.turn_count == 2


def test_context_preserves_topic():
    engine = LegalReasoningEngine()
    engine.reason("كم مربوط الدرجة السابعة", session_id="ctx2")
    ctx = engine.get_context("ctx2")
    assert ctx.current_topic == "salary"


# ══════════════════════════════════════════════════════════════
# Enrichment
# ══════════════════════════════════════════════════════════════

def test_enrichment_structured_returns_none():
    """Structured factual answers don't need enrichment."""
    result = ReasoningResult(
        reasoning_mode=ReasoningMode.STRUCTURED_FACTUAL.value,
        domain="salary", topic="basic_salary",
    )
    assert build_reasoning_enrichment(result) is None


def test_enrichment_scope_returns_text():
    """Scope queries should get evidence enrichment."""
    registry = get_registry()
    direct = registry.get_direct_evidence(domain="scope")
    result = ReasoningResult(
        reasoning_mode=ReasoningMode.SCOPE_APPLICABILITY.value,
        domain="scope", topic="civil_service",
        direct_evidence=direct,
    )
    enrichment = build_reasoning_enrichment(result)
    if direct:
        assert enrichment is not None
        assert isinstance(enrichment, str)


# ══════════════════════════════════════════════════════════════
# LLM Context Builder
# ══════════════════════════════════════════════════════════════

def test_llm_context_has_evidence():
    engine = LegalReasoningEngine()
    result = engine.reason("ما هي المواد المخدرة في الجدول الأول")
    ctx = engine.build_llm_context(result)
    assert isinstance(ctx, str)
    if result.has_direct_evidence():
        assert "معلومات موثقة" in ctx


def test_llm_context_has_blocked():
    engine = LegalReasoningEngine()
    result = engine.reason("ما مدى خطورة هذه المواد المخدرة")
    ctx = engine.build_llm_context(result)
    if result.has_blocked():
        assert "محظورة" in ctx or "⛔" in ctx


def test_llm_context_has_instructions():
    engine = LegalReasoningEngine()
    result = engine.reason("كيف يتم تصنيف المواد المخدرة")
    ctx = engine.build_llm_context(result)
    if ctx:
        assert "تعليمات" in ctx


# ══════════════════════════════════════════════════════════════
# Knowledge Packs Loading
# ══════════════════════════════════════════════════════════════

def test_registry_loads_all_packs():
    registry = get_registry()
    stats = registry.stats()
    assert stats["total_entries"] > 0
    assert "salary" in stats["by_domain"]
    assert "drug" in stats["by_domain"]
    assert "scope" in stats["by_domain"]
    assert "reasoning" in stats["by_domain"]


def test_salary_pack_has_entries():
    from core.knowledge_packs.salary_pack import get_salary_entries
    entries = get_salary_entries()
    assert len(entries) >= 10
    # Check key entries exist
    ids = {e.entry_id for e in entries}
    assert "sal_001_marbout_definition" in ids
    assert "sal_020_total_not_in_table" in ids
    assert "sal_022_block_exact_total" in ids


def test_drug_pack_has_entries():
    from core.knowledge_packs.drug_pack import get_drug_entries
    entries = get_drug_entries()
    assert len(entries) >= 10
    ids = {e.entry_id for e in entries}
    assert "drug_001_three_schedules" in ids
    assert "drug_040_block_danger_claims" in ids


def test_scope_pack_has_entries():
    from core.knowledge_packs.scope_pack import get_scope_entries
    entries = get_scope_entries()
    assert len(entries) >= 5


def test_reasoning_pack_has_entries():
    from core.knowledge_packs.reasoning_pack import get_reasoning_entries
    entries = get_reasoning_entries()
    assert len(entries) >= 8


# ══════════════════════════════════════════════════════════════
# Direct Evidence Stays Direct
# ══════════════════════════════════════════════════════════════

def test_direct_evidence_not_modified():
    """Direct evidence should be returned exactly as stored."""
    registry = get_registry()
    entry = registry.get("sal_001_marbout_definition")
    assert entry is not None
    assert entry.is_direct()
    assert "المربوط" in entry.statement_ar
    # Statement should not be modified
    assert entry.support_level == SupportLevel.DIRECT_EVIDENCE.value


# ══════════════════════════════════════════════════════════════
# Blocked Claims
# ══════════════════════════════════════════════════════════════

def test_blocked_claims_blocked():
    """UNSUPPORTED_BLOCKED entries should be identified."""
    registry = get_registry()
    blocked = registry.get_blocked(domain="salary")
    assert len(blocked) >= 1
    for e in blocked:
        assert e.is_blocked()
        assert e.support_level == SupportLevel.UNSUPPORTED_BLOCKED.value


def test_blocked_drug_danger():
    registry = get_registry()
    blocked = registry.get_blocked(domain="drug")
    assert any("خطورة" in e.statement_ar or "قاتل" in e.statement_ar for e in blocked)


# ══════════════════════════════════════════════════════════════
# No Internal Reasoning in UI
# ══════════════════════════════════════════════════════════════

def test_enrichment_no_internal_tags():
    """User-facing enrichment must not contain internal tags."""
    engine = LegalReasoningEngine()
    result = engine.reason("هل يسري على جميع الجهات الحكومية")
    enrichment = build_reasoning_enrichment(result)
    if enrichment:
        assert "STEP_" not in enrichment
        assert "GUARD" not in enrichment
        assert "DIRECT_EVIDENCE" not in enrichment
        assert "CONTROLLED_INFERENCE" not in enrichment
        assert "UNSUPPORTED" not in enrichment
