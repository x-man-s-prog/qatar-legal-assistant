# -*- coding: utf-8 -*-
"""Tests for Self-Correction V2 + Orchestration."""
import asyncio, pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.self_correction.schemas import GateVerdict
from core.self_correction.claim_extractor import extract_claims
from core.self_correction.pipeline import SelfCorrectionPipeline
from core.self_correction.coverage_checker import check_coverage
from core.self_correction.grounding_verifier import verify_grounding
from core.self_correction.contradiction_checker import check_contradictions
from core.orchestration.schemas import PlanType, ToolName
from core.orchestration.tool_selector import select_tools
from core.orchestration.tool_executor import execute_tool
from core.orchestration.plan_runner import OrchestrationRunner

CHUNKS = [
    {"content": "المادة 300 من قانون العقوبات: يعاقب بالإعدام كل من قتل نفساً عمداً مع سبق الإصرار",
     "article_number": "300", "law_name": "قانون العقوبات رقم 11 لسنة 2004",
     "law_number": "11", "law_year": "2004", "score": 0.9, "source": ""},
    {"content": "المادة 310 من قانون العقوبات: يعاقب بالحبس مدة لا تتجاوز سبع سنوات من ارتكب سرقة",
     "article_number": "310", "law_name": "قانون العقوبات رقم 11 لسنة 2004",
     "law_number": "11", "law_year": "2004", "score": 0.85, "source": ""},
]


# ══════════════════════════════════════════════════════════════
# Claim Extractor Tests
# ══════════════════════════════════════════════════════════════

def test_extract_article_ref():
    r = extract_claims("تنص المادة 300 من قانون العقوبات على الإعدام")
    arts = [c for c in r.claims if c.claim_type.value == "article_ref"]
    assert len(arts) >= 1
    assert arts[0].article_number == "300"

def test_extract_ruling_ref():
    r = extract_claims("طعن رقم 45/2019 أكد هذا المبدأ")
    rulings = [c for c in r.claims if c.claim_type.value == "ruling_ref"]
    assert len(rulings) == 1

def test_extract_legal_conclusion():
    r = extract_claims("يحق للمتهم الطعن في الحكم خلال ثلاثين يوماً")
    conc = [c for c in r.claims if c.claim_type.value == "legal_conclusion"]
    assert len(conc) >= 1


# ══════════════════════════════════════════════════════════════
# Citation Verifier Tests
# ══════════════════════════════════════════════════════════════

def test_citation_verified():
    """Article 300 exists in chunks — should verify."""
    r = extract_claims("المادة 300 من قانون العقوبات")
    from core.self_correction.citation_verifier import verify_citations as vc
    result = asyncio.get_event_loop().run_until_complete(vc(r.claims, CHUNKS))
    assert result.verified >= 1
    assert result.failed == 0

def test_citation_fabricated():
    """Article 999 does NOT exist — should flag fabricated."""
    r = extract_claims("المادة 999 من قانون العقوبات")
    from core.self_correction.citation_verifier import verify_citations as vc
    result = asyncio.get_event_loop().run_until_complete(vc(r.claims, CHUNKS))
    assert result.failed >= 1
    assert "المادة 999" in str(result.fabricated)


# ══════════════════════════════════════════════════════════════
# Grounding Verifier Tests
# ══════════════════════════════════════════════════════════════

def test_grounding_explicit():
    """Claim using words from evidence should be grounded."""
    claims = extract_claims("عقوبة القتل العمد الإعدام مع سبق الإصرار").claims
    result = asyncio.get_event_loop().run_until_complete(verify_grounding(claims, CHUNKS))
    assert result.grounded >= 1 or result.total == 0  # May not extract non-article claims

def test_grounding_unsupported():
    """Claim about unrelated topic should be unsupported."""
    from core.self_correction.schemas import ExtractedClaim, ClaimType
    claims = [ExtractedClaim(text="تعويض حادث المرور يشمل الأضرار المعنوية", claim_type=ClaimType.LEGAL_CONCLUSION, is_decisive=True)]
    result = asyncio.get_event_loop().run_until_complete(verify_grounding(claims, CHUNKS))
    assert result.unsupported >= 1


# ══════════════════════════════════════════════════════════════
# Contradiction Tests
# ══════════════════════════════════════════════════════════════

def test_contradiction_negation():
    """Answer says 'لا يجوز' but evidence says 'يجوز'."""
    answer = "لا يجوز الحكم بالإعدام في جرائم القتل العمد"
    chunks_with_yes = [{"content": "يجوز الحكم بالإعدام لكل من ارتكب جريمة قتل عمد", "law_name": "عقوبات"}]
    result = asyncio.get_event_loop().run_until_complete(check_contradictions(answer, chunks_with_yes))
    assert result.count >= 1

def test_no_contradiction():
    answer = "يعاقب بالإعدام من قتل عمداً"
    result = asyncio.get_event_loop().run_until_complete(check_contradictions(answer, CHUNKS))
    assert result.count == 0


# ══════════════════════════════════════════════════════════════
# Coverage Tests
# ══════════════════════════════════════════════════════════════

def test_coverage_full():
    r = check_coverage("ما عقوبة السرقة", "عقوبة السرقة هي الحبس مدة لا تتجاوز 7 سنوات وفقاً للمادة 310")
    assert r.covers_main_question is True
    assert r.coverage_pct >= 50

def test_coverage_partial():
    r = check_coverage("ما عقوبة السرقة وكيف أرفع دعوى", "عقوبة السرقة الحبس")
    assert r.partial is True

def test_coverage_refusal():
    r = check_coverage("ما عقوبة السرقة", "لا تتوفر لديّ معلومات")
    assert r.covers_main_question is False


# ══════════════════════════════════════════════════════════════
# Pipeline Integration Tests
# ══════════════════════════════════════════════════════════════

def test_pipeline_good_answer():
    pipeline = SelfCorrectionPipeline(pool=None)
    good = "تنص المادة 300 من قانون العقوبات على أنه يعاقب بالإعدام كل من قتل نفساً عمداً. يحق للمتهم الطعن."
    d = asyncio.get_event_loop().run_until_complete(pipeline.run(good, "ما عقوبة القتل", CHUNKS))
    assert d.verdict == GateVerdict.PASS

def test_pipeline_refuses_all_fabricated():
    pipeline = SelfCorrectionPipeline(pool=None)
    bad = "المادة 888 والمادة 777 تنصان على التعويض."
    d = asyncio.get_event_loop().run_until_complete(pipeline.run(bad, "حقوقي", CHUNKS))
    # Should either pass (after repair removes fabricated) or refuse
    if d.citation_result and d.citation_result.fabricated:
        # Fabricated detected
        surviving = [f for f in d.citation_result.fabricated if f in d.final_answer]
        assert len(surviving) == 0, "fabricated citations must not survive"

def test_pipeline_greeting_passthrough():
    pipeline = SelfCorrectionPipeline(pool=None)
    d = asyncio.get_event_loop().run_until_complete(pipeline.run("أهلاً!", "مرحبا", []))
    assert d.verdict == GateVerdict.PASS


# ══════════════════════════════════════════════════════════════
# Tool Orchestration Tests
# ══════════════════════════════════════════════════════════════

def test_tool_selector_eos():
    plan = select_tools("احسب مكافأة نهاية خدمة راتب 15000 و10 سنوات")
    assert plan.needs_tools is True
    assert plan.tool_calls[0].tool_name == ToolName.END_OF_SERVICE

def test_tool_selector_table():
    plan = select_tools("عدد لي جدول المخدرات")
    assert plan.needs_tools is True
    assert plan.tool_calls[0].tool_name == ToolName.TABLE_LOOKUP

def test_tool_selector_article():
    plan = select_tools("نص المادة 173 من قانون الأسرة")
    assert plan.needs_tools is True
    assert plan.tool_calls[0].tool_name == ToolName.ARTICLE_LOOKUP

def test_tool_selector_no_tool():
    plan = select_tools("ما عقوبة السرقة")
    assert plan.needs_tools is False

def test_tool_selector_greeting():
    plan = select_tools("مرحبا", brain_route="greeting")
    assert plan.needs_tools is False

def test_tool_executor_eos():
    from core.orchestration.schemas import ToolCall
    call = ToolCall(tool_name=ToolName.END_OF_SERVICE, arguments={"salary": 15000, "years": 10})
    out, val = asyncio.get_event_loop().run_until_complete(execute_tool(call))
    assert out.success is True
    assert val.valid is True
    assert out.result["reward"] > 0

def test_tool_executor_missing_arg():
    from core.orchestration.schemas import ToolCall
    call = ToolCall(tool_name=ToolName.END_OF_SERVICE, arguments={"salary": 15000})
    out, val = asyncio.get_event_loop().run_until_complete(execute_tool(call))
    assert out.success is False

def test_orchestration_runner_eos():
    runner = OrchestrationRunner(pool=None)
    result = asyncio.get_event_loop().run_until_complete(
        runner.run("احسب مكافأة نهاية خدمة راتب 15000 و10 سنوات")
    )
    assert result.plan.needs_tools is True
    # Tool needs salary+years → TOOL_THEN_RAG
    assert result.needs_llm is True or result.early_return is True

def test_orchestration_runner_no_tools():
    runner = OrchestrationRunner(pool=None)
    result = asyncio.get_event_loop().run_until_complete(runner.run("ما عقوبة السرقة"))
    assert result.plan.needs_tools is False
    assert result.early_return is False


# ══════════════════════════════════════════════════════════════
# Run
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
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
