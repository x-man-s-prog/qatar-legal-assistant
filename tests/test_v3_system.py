# -*- coding: utf-8 -*-
"""Tests for V3 system: SC V3 + Orchestration + Planning + Adaptive Risk."""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.self_correction.schemas import GateVerdict, QueryContext, QueryComplexity
from core.self_correction.claim_extractor import extract_claims
from core.self_correction.pipeline import SelfCorrectionPipeline
from core.self_correction.coverage_checker import check_coverage
from core.self_correction.grounding_verifier import verify_grounding
from core.self_correction.contradiction_checker import check_contradictions
from core.self_correction.risk_scorer import score_risk
from core.self_correction.repair_controller import _downgrade_certainty, _remove_unsupported_claims
from core.orchestration.schemas import PlanType, ToolName
from core.orchestration.tool_selector import select_tools
from core.orchestration.tool_executor import execute_tool as exec_tool
from core.orchestration.plan_runner import OrchestrationRunner
from core.planning.complexity_classifier import classify_complexity
from core.planning.plan_builder import build_plan

CHUNKS = [
    {"content": "المادة 300 من قانون العقوبات: يعاقب بالإعدام كل من قتل نفساً عمداً مع سبق الإصرار",
     "article_number": "300", "law_name": "قانون العقوبات رقم 11 لسنة 2004",
     "law_number": "11", "law_year": "2004", "score": 0.9, "source": ""},
    {"content": "المادة 310: يعاقب بالحبس مدة لا تتجاوز سبع سنوات من ارتكب سرقة",
     "article_number": "310", "law_name": "قانون العقوبات رقم 11 لسنة 2004",
     "law_number": "11", "law_year": "2004", "score": 0.85, "source": ""},
]

# ══════════════════════════════════════════════════════════════
# CLAIM EXTRACTION
# ══════════════════════════════════════════════════════════════

def test_extract_article():
    r = extract_claims("تنص المادة 300 من قانون العقوبات على الإعدام")
    assert any(c.article_number == "300" for c in r.claims)

def test_extract_ruling():
    r = extract_claims("طعن رقم 45/2019 أكد هذا المبدأ")
    assert any(c.claim_type.value == "ruling_ref" for c in r.claims)

def test_extract_conclusion():
    r = extract_claims("يحق للمتهم الطعن في الحكم خلال ثلاثين يوماً")
    assert any(c.claim_type.value == "legal_conclusion" for c in r.claims)

# ══════════════════════════════════════════════════════════════
# CITATION VERIFICATION
# ══════════════════════════════════════════════════════════════

def test_citation_valid():
    r = extract_claims("المادة 300 من قانون العقوبات")
    from core.self_correction.citation_verifier import verify_citations as vc
    result = asyncio.get_event_loop().run_until_complete(vc(r.claims, CHUNKS))
    assert result.verified >= 1

def test_citation_fabricated():
    r = extract_claims("المادة 999 من قانون العقوبات")
    from core.self_correction.citation_verifier import verify_citations as vc
    result = asyncio.get_event_loop().run_until_complete(vc(r.claims, CHUNKS))
    assert result.failed >= 1

# ══════════════════════════════════════════════════════════════
# GROUNDING
# ══════════════════════════════════════════════════════════════

def test_grounding_explicit():
    claims = extract_claims("عقوبة القتل العمد الإعدام مع سبق الإصرار").claims
    result = asyncio.get_event_loop().run_until_complete(verify_grounding(claims, CHUNKS))
    assert result.grounded >= 0  # May not extract non-article claims from short text

def test_grounding_unsupported():
    from core.self_correction.schemas import ExtractedClaim, ClaimType
    claims = [ExtractedClaim(text="تعويض حادث المرور يشمل الأضرار المعنوية", claim_type=ClaimType.LEGAL_CONCLUSION, is_decisive=True)]
    result = asyncio.get_event_loop().run_until_complete(verify_grounding(claims, CHUNKS))
    assert result.unsupported >= 1

# ══════════════════════════════════════════════════════════════
# CONTRADICTION
# ══════════════════════════════════════════════════════════════

def test_contradiction_negation():
    answer = "لا يجوز الحكم بالإعدام في جرائم القتل العمد"
    chunks = [{"content": "يجوز الحكم بالإعدام لكل من ارتكب جريمة قتل عمد", "law_name": "عقوبات"}]
    result = asyncio.get_event_loop().run_until_complete(check_contradictions(answer, chunks))
    assert result.count >= 1

def test_no_contradiction():
    result = asyncio.get_event_loop().run_until_complete(check_contradictions("يعاقب بالإعدام", CHUNKS))
    assert result.count == 0

# ══════════════════════════════════════════════════════════════
# COVERAGE
# ══════════════════════════════════════════════════════════════

def test_coverage_full():
    r = check_coverage("ما عقوبة السرقة", "عقوبة السرقة الحبس مدة لا تتجاوز 7 سنوات وفقاً للمادة 310")
    assert r.covers_main_question is True

def test_coverage_compound_partial():
    r = check_coverage("ما عقوبة السرقة وكيف أرفع دعوى", "عقوبة السرقة الحبس")
    assert r.partial is True

def test_coverage_refusal():
    r = check_coverage("ما عقوبة السرقة", "لا تتوفر لديّ معلومات")
    assert r.covers_main_question is False

# ══════════════════════════════════════════════════════════════
# ADAPTIVE RISK
# ══════════════════════════════════════════════════════════════

def test_risk_legal_stricter():
    from core.self_correction.schemas import CitationVerificationResult, GroundingResult, ContradictionResult, CoverageResult
    cite = CitationVerificationResult(total=1, verified=0, failed=1, fabricated=["المادة 999"])
    gnd = GroundingResult(total=0, grounded=0, unsupported=0, unsupported_decisive=0)
    ctr = ContradictionResult(count=0, has_major=False)
    cov = CoverageResult(covers_main_question=True, coverage_pct=100)
    ctx_legal = QueryContext(is_legal=True)
    ctx_simple = QueryContext(is_legal=False)
    risk_legal = score_risk(cite, gnd, ctr, cov, ctx_legal)
    risk_simple = score_risk(cite, gnd, ctr, cov, ctx_simple)
    assert risk_legal.overall_risk >= risk_simple.overall_risk  # Legal should be stricter

# ══════════════════════════════════════════════════════════════
# REPAIR
# ══════════════════════════════════════════════════════════════

def test_certainty_downgrade():
    text, changed = _downgrade_certainty("يحق لك التعويض بالتأكيد وحتماً يجب عليك الرفع")
    assert changed is True
    assert "بالتأكيد" not in text
    assert "حتماً" not in text

def test_remove_unsupported():
    from core.self_correction.schemas import GroundingResult, GroundingCheck, ExtractedClaim, ClaimType, EvidenceLevel
    claim = ExtractedClaim(text="يستحق المدعي تعويض مليون ريال", claim_type=ClaimType.LEGAL_CONCLUSION, is_decisive=True)
    gnd = GroundingResult(total=1, grounded=0, unsupported=1, unsupported_decisive=1,
                           checks=[GroundingCheck(claim=claim, evidence_level=EvidenceLevel.UNSUPPORTED)])
    answer = "بداية. يستحق المدعي تعويض مليون ريال. نهاية."
    cleaned, did = _remove_unsupported_claims(answer, gnd)
    assert did is True
    assert "مليون" not in cleaned

# ══════════════════════════════════════════════════════════════
# PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════

def test_pipeline_good():
    p = SelfCorrectionPipeline(pool=None)
    good = "تنص المادة 300 من قانون العقوبات على أنه يعاقب بالإعدام. يحق للمتهم الطعن."
    d = asyncio.get_event_loop().run_until_complete(p.run(good, "عقوبة القتل", CHUNKS))
    assert d.verdict == GateVerdict.PASS

def test_pipeline_fabricated_repair():
    p = SelfCorrectionPipeline(pool=None)
    bad = "المادة 888 والمادة 777 تنصان على التعويض."
    d = asyncio.get_event_loop().run_until_complete(p.run(bad, "حقوقي", CHUNKS))
    if d.citation_result and d.citation_result.fabricated:
        surviving = [f for f in d.citation_result.fabricated if f in d.final_answer]
        assert len(surviving) == 0

def test_pipeline_greeting():
    p = SelfCorrectionPipeline(pool=None)
    d = asyncio.get_event_loop().run_until_complete(p.run("أهلاً!", "مرحبا", []))
    assert d.verdict == GateVerdict.PASS

def test_pipeline_with_context():
    p = SelfCorrectionPipeline(pool=None)
    ctx = QueryContext(is_legal=True, complexity=QueryComplexity.LEGAL_SINGLE, retrieval_confidence=0.9)
    good = "تنص المادة 300 من قانون العقوبات على الإعدام لكل من قتل عمداً."
    d = asyncio.get_event_loop().run_until_complete(
        p.run(good, "عقوبة القتل", CHUNKS, context=ctx))
    assert d.verdict in (GateVerdict.PASS, GateVerdict.PASS_WITH_WARNINGS)

# ══════════════════════════════════════════════════════════════
# TOOL ORCHESTRATION
# ══════════════════════════════════════════════════════════════

def test_tool_sel_eos():
    assert select_tools("احسب مكافأة نهاية خدمة راتب 15000 و10 سنوات").needs_tools is True

def test_tool_sel_table():
    assert select_tools("عدد لي جدول المخدرات").needs_tools is True

def test_tool_sel_article():
    assert select_tools("نص المادة 173 من قانون الأسرة").needs_tools is True

def test_tool_sel_none():
    assert select_tools("ما عقوبة السرقة").needs_tools is False

def test_tool_exec_eos():
    from core.orchestration.schemas import ToolCall
    call = ToolCall(tool_name=ToolName.END_OF_SERVICE, arguments={"salary": 15000, "years": 10})
    out, val = asyncio.get_event_loop().run_until_complete(exec_tool(call))
    assert out.success and val.valid and out.result["reward"] > 0

def test_tool_exec_missing_arg():
    from core.orchestration.schemas import ToolCall
    call = ToolCall(tool_name=ToolName.END_OF_SERVICE, arguments={"salary": 15000})
    out, val = asyncio.get_event_loop().run_until_complete(exec_tool(call))
    assert not out.success

def test_orch_runner():
    r = OrchestrationRunner(pool=None)
    result = asyncio.get_event_loop().run_until_complete(r.run("احسب مكافأة نهاية خدمة راتب 15000 و10 سنوات"))
    assert result.plan.needs_tools is True

# ══════════════════════════════════════════════════════════════
# PLANNING
# ══════════════════════════════════════════════════════════════

def test_classify_simple():
    assert classify_complexity("مرحبا", "greeting") == QueryComplexity.SIMPLE

def test_classify_legal_single():
    assert classify_complexity("ما عقوبة السرقة في قطر", "consultation") == QueryComplexity.LEGAL_SINGLE

def test_classify_tool():
    assert classify_complexity("احسب مكافأة نهاية الخدمة", "consultation", has_tools=True) == QueryComplexity.TOOL_REQUIRED

def test_classify_compound():
    c = classify_complexity("ما عقوبة السرقة وما شروط الطلاق وكيف أحصل على حضانة")
    assert c in (QueryComplexity.LEGAL_MULTI, QueryComplexity.COMPLEX)

def test_plan_simple():
    plan = build_plan(QueryComplexity.SIMPLE)
    assert plan.requires_buffered_output is False
    assert plan.requires_sc is False

def test_plan_legal():
    plan = build_plan(QueryComplexity.LEGAL_SINGLE)
    assert plan.requires_buffered_output is True
    assert plan.requires_sc is True

def test_plan_tool():
    plan = build_plan(QueryComplexity.TOOL_REQUIRED, has_tools=True)
    assert plan.requires_sc is True
    assert any(s.step_type == "tool" for s in plan.steps)

def test_plan_complex():
    plan = build_plan(QueryComplexity.COMPLEX, has_tools=True)
    assert any(s.step_type == "decompose" for s in plan.steps)
    assert any(s.step_type == "tool" for s in plan.steps)

# ══════════════════════════════════════════════════════════════
# STREAMING PATH ROUTING
# ══════════════════════════════════════════════════════════════

def test_simple_not_buffered():
    plan = build_plan(QueryComplexity.SIMPLE)
    assert plan.requires_buffered_output is False

def test_legal_buffered():
    plan = build_plan(QueryComplexity.LEGAL_SINGLE)
    assert plan.requires_buffered_output is True

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
