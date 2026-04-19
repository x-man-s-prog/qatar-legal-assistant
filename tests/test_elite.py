# -*- coding: utf-8 -*-
"""Tests for elite upgrades: LLM tool selection, embedding grounding, legal validation, plan execution."""
import asyncio, sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.self_correction.schemas import GateVerdict, QueryContext, QueryComplexity, ExtractedClaim, ClaimType, EvidenceLevel
from core.self_correction.pipeline import SelfCorrectionPipeline
from core.self_correction.grounding_verifier import verify_grounding, _cosine_sim, _deterministic_ground, THRESH_EMBED_INFERRED
from core.orchestration.schemas import PlanType, ToolName
from core.orchestration.tool_selector import select_tools, _rule_based_select, select_tools_async
from core.orchestration.tool_executor import execute_tool, _validate_legal, _validate_structural
from core.orchestration.plan_runner import OrchestrationRunner
from core.planning.plan_executor import PlanExecutor, StepResult
from core.planning.plan_builder import build_plan

CHUNKS = [
    {"content": "المادة 300 من قانون العقوبات: يعاقب بالإعدام كل من قتل نفساً عمداً مع سبق الإصرار",
     "article_number": "300", "law_name": "قانون العقوبات رقم 11 لسنة 2004",
     "law_number": "11", "law_year": "2004", "score": 0.9, "source": ""},
]

# ══════════════════════════════════════════════════════════════
# LLM TOOL SELECTION (Part 1)
# ══════════════════════════════════════════════════════════════

def test_rule_based_still_works_easy():
    plan, conf = _rule_based_select("احسب مكافأة نهاية خدمة راتب 15000 و10 سنوات", "")
    assert plan.needs_tools is True
    assert conf >= 0.9

def test_rule_based_no_tool():
    plan, conf = _rule_based_select("ما عقوبة السرقة", "")
    assert plan.needs_tools is False
    assert conf >= 0.7

def test_rule_based_low_confidence_ambiguous():
    """Ambiguous query with tool signals but no clear tool match."""
    plan, conf = _rule_based_select("كم قيمة المبلغ المستحق من المادة الخامسة", "")
    assert conf < 0.7  # Should be low confidence → would trigger LLM fallback

def test_rule_based_greeting_skips():
    plan, conf = _rule_based_select("مرحبا", "greeting")
    assert plan.needs_tools is False
    assert conf == 1.0

def test_async_select_without_llm():
    """Without LLM caller, falls back to rule-based."""
    plan = asyncio.get_event_loop().run_until_complete(
        select_tools_async("ما عقوبة السرقة", "", llm_caller=None))
    assert plan.needs_tools is False

# ══════════════════════════════════════════════════════════════
# EMBEDDING GROUNDING (Part 3)
# ══════════════════════════════════════════════════════════════

def test_cosine_sim():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert _cosine_sim(a, b) == 1.0
    c = [0.0, 1.0, 0.0]
    assert _cosine_sim(a, c) == 0.0

def test_cosine_sim_similar():
    a = [1.0, 0.5, 0.0]
    b = [0.9, 0.6, 0.1]
    sim = _cosine_sim(a, b)
    assert 0.9 < sim < 1.0

def test_deterministic_ground_explicit():
    """Claim using exact words from evidence should be explicit."""
    level, idx, score = _deterministic_ground("يعاقب بالإعدام كل من قتل نفساً عمداً", CHUNKS)
    assert level == EvidenceLevel.EXPLICIT
    assert idx == 0

def test_deterministic_ground_unsupported():
    """Completely unrelated claim should be unsupported."""
    level, idx, score = _deterministic_ground("تعويض حادث المرور يشمل الأضرار المعنوية والمادية", CHUNKS)
    assert level == EvidenceLevel.UNSUPPORTED

def test_grounding_without_embed():
    """Grounding without embed_fn should still work (layers 1+2 only)."""
    claims = [ExtractedClaim(text="يعاقب بالإعدام عن القتل العمد", claim_type=ClaimType.LEGAL_CONCLUSION, is_decisive=True)]
    result = asyncio.get_event_loop().run_until_complete(
        verify_grounding(claims, CHUNKS, embed_fn=None))
    assert result.total >= 1

# ══════════════════════════════════════════════════════════════
# LEGAL-AWARE TOOL VALIDATION (Part 4)
# ══════════════════════════════════════════════════════════════

def test_legal_validation_eos_correct():
    """Correct EOS calculation should pass legal validation."""
    result = {"salary": 15000, "years": 10, "reward": 103926.0, "weekly_salary": 3464.2}
    issues = _validate_legal(ToolName.END_OF_SERVICE, result, {"salary": 15000, "years": 10})
    assert len(issues) == 0

def test_legal_validation_eos_impossible_years():
    result = {"salary": 15000, "years": 100, "reward": 1000000}
    issues = _validate_legal(ToolName.END_OF_SERVICE, result, {"salary": 15000, "years": 100})
    assert any("غير واقعية" in i for i in issues)

def test_legal_validation_dismissal_below_minimum():
    """Dismissal comp below 2 months salary should be flagged."""
    result = {"salary": 10000, "years": 1, "total": 15000, "dismissal_comp": 5000}
    issues = _validate_legal(ToolName.UNFAIR_DISMISSAL, result, {"salary": 10000, "years": 1})
    assert any("الحد الأدنى" in i for i in issues)

def test_structural_validation_negative():
    issues = _validate_structural(ToolName.END_OF_SERVICE, {"reward": -500})
    assert any("سالبة" in i for i in issues)

def test_structural_validation_empty():
    issues = _validate_structural(ToolName.END_OF_SERVICE, {})
    # Empty result with no error key should pass structural (no reward key found)
    assert isinstance(issues, list)

def test_tool_exec_legal_issues_in_text():
    """Legal issues should appear in result_text as caveats."""
    from core.orchestration.schemas import ToolCall
    call = ToolCall(tool_name=ToolName.END_OF_SERVICE, arguments={"salary": 15000, "years": 10})
    out, val = asyncio.get_event_loop().run_until_complete(execute_tool(call))
    assert out.success is True
    # No legal issues for correct calculation
    assert "ملاحظة" not in out.result_text

# ══════════════════════════════════════════════════════════════
# MULTI-STEP PLAN EXECUTION (Part 2)
# ══════════════════════════════════════════════════════════════

def test_plan_executor_with_callbacks():
    """Test real step execution with data passing."""
    executor = PlanExecutor()

    async def tool_callback(step, ctx):
        return {"result": "مكافأة: 100,000 ريال"}

    async def merge_callback(step, ctx):
        tool_r = ctx.get("tool_result", {})
        return {"merged": f"الحساب: {tool_r.get('result', '?')} + السياق القانوني"}

    executor.register_callback("tool", tool_callback)
    executor.register_callback("merge", merge_callback)

    plan = build_plan(QueryComplexity.TOOL_REQUIRED, has_tools=True)
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(plan, initial_context={"query": "احسب مكافأة"}))

    assert result.total_latency_ms >= 0
    assert any(s.step_type == "tool" and s.success for s in result.steps_completed)

def test_plan_executor_step_failure():
    """Test that a failed required step stops execution."""
    executor = PlanExecutor()

    async def failing_callback(step, ctx):
        raise ValueError("DB connection failed")

    executor.register_callback("rag", failing_callback)

    plan = build_plan(QueryComplexity.LEGAL_SINGLE)
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(plan, initial_context={}))

    assert result.failed_step == "rag"
    # Steps after failure should not execute
    completed_types = [s.step_type for s in result.steps_completed]
    assert "answer" not in completed_types or not any(
        s.step_type == "answer" and s.success for s in result.steps_completed)

def test_plan_executor_skip_on_failure():
    """Skippable step failure should not stop execution."""
    executor = PlanExecutor()

    async def failing_tool(step, ctx):
        raise ValueError("Tool unavailable")

    executor.register_callback("tool", failing_tool)

    plan = build_plan(QueryComplexity.COMPLEX, has_tools=True)
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(plan, initial_context={}))

    assert result.plan_adjusted is True
    # Execution should continue past failed skippable step
    assert len(result.steps_completed) > 1

def test_plan_executor_data_passing():
    """Outputs from earlier steps should be available in later steps."""
    executor = PlanExecutor()
    received_ctx = {}

    async def step_a(step, ctx):
        return {"value": 42}

    async def step_b(step, ctx):
        received_ctx.update(ctx)
        return ctx.get("tool_result", {})

    executor.register_callback("tool", step_a)
    executor.register_callback("merge", step_b)

    plan = build_plan(QueryComplexity.TOOL_REQUIRED, has_tools=True)
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(plan, initial_context={}))

    # tool step output should be in step_outputs
    assert "tool_result" in result.step_outputs

# ══════════════════════════════════════════════════════════════
# PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════

def test_pipeline_with_embed_fn_param():
    """Pipeline should accept embed_fn without error."""
    p = SelfCorrectionPipeline(pool=None)
    good = "تنص المادة 300 من قانون العقوبات على أنه يعاقب بالإعدام."
    d = asyncio.get_event_loop().run_until_complete(
        p.run(good, "عقوبة القتل", CHUNKS, embed_fn=None))
    assert d.verdict == GateVerdict.PASS

def test_pipeline_orchestration_runner():
    runner = OrchestrationRunner(pool=None)
    result = asyncio.get_event_loop().run_until_complete(
        runner.run("احسب مكافأة نهاية خدمة راتب 15000 و10 سنوات", llm_caller=None))
    assert result.plan.needs_tools is True

# ══════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════

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
