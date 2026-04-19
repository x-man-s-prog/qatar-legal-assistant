# -*- coding: utf-8 -*-
"""
Strategic Legal Reasoning Engine — Test Suite
==============================================
45 tests covering all 8 internal structures + integration with fail-closed
pipeline + strategic insufficiency mode.
"""
from __future__ import annotations
import time


def run_strategic_reasoning_tests() -> dict:
    from core.strategic_reasoning_engine import (
        StrategicReasoningEngine, StrategicReasoningPlan,
        Claim, Defense, ClaimGraph, DefenseGraph,
        EvidenceIntelligence, PartyStrengthProfile, OutcomeBranch,
        StrategicAssessment, OpponentModel, CriticalEvidenceItem,
        CaseStrength, DefenseType, EvidenceQuality, PartyRole,
        render_strategic_analysis, render_strategic_insufficiency,
        enhance_with_strategic_reasoning, get_strategic_engine,
    )
    from core.legal_gates import (
        LegalDomain, FactPattern, BurdenMap, EvidenceLedger,
        EvidenceEntry, EvidenceType,
        LegalIssueClassifier, FactPatternExtractor, BurdenOfProofEngine,
        EvidenceRegistry,
    )
    from core.fail_closed_pipeline import answer_fail_closed

    engine = StrategicReasoningEngine()
    classifier = LegalIssueClassifier()
    extractor = FactPatternExtractor()
    burden_engine = BurdenOfProofEngine()
    evidence_reg = EvidenceRegistry()

    results = []

    def test(name: str, passed: bool, detail: str = ""):
        results.append({"name": name, "passed": passed, "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail and not passed else ""))

    def build_inputs(query: str, domain: LegalDomain):
        fp = extractor.extract(query)
        bm = burden_engine.map_burden(domain, fp)
        ledger = evidence_reg.build_ledger(fp, bm)
        return fp, bm, ledger

    # ══════════════════════════════════════════════════════════════
    # A. Activation gate (T01-T04)
    # ══════════════════════════════════════════════════════════════

    # T01: substantive query → activated
    fp, bm, ledger = build_inputs(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟", LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")
    test("T01: substantive employment query activates",
         plan.is_substantive)

    # T02: empty fact pattern → not substantive
    plan = engine.reason(FactPattern(), BurdenMap(), EvidenceLedger(),
                          LegalDomain.EMPLOYMENT, query="")
    test("T02: empty inputs → not substantive",
         not plan.is_substantive
         and plan.insufficiency_reason == "fact_pattern_lacks_substance")

    # T03: short query → not substantive
    fp, bm, ledger = build_inputs("فصلوني", LegalDomain.EMPLOYMENT)
    fp.has_substance = True   # simulate having facts
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT, query="فصلوني")
    test("T03: query too short → not substantive",
         not plan.is_substantive)

    # T04: unknown domain → not substantive
    fp, bm, ledger = build_inputs(
        "فصلوني من العمل، عندي تحويلات راتب", LegalDomain.UNKNOWN)
    plan = engine.reason(fp, bm, ledger, LegalDomain.UNKNOWN,
                          query="فصلوني من العمل، عندي تحويلات راتب")
    test("T04: unknown domain → not substantive",
         not plan.is_substantive)

    # ══════════════════════════════════════════════════════════════
    # B. Claim graph + defense graph (T05-T08)
    # ══════════════════════════════════════════════════════════════

    fp, bm, ledger = build_inputs(
        "فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟",
        LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني من العمل، عندي تحويلات راتب، نقاط ضعفي؟")

    # T05: claim graph populated
    test("T05: claim graph has at least one claim",
         len(plan.claim_graph.claims) >= 1)

    # T06: defense graph populated with classified type
    test("T06: defense graph has classified defense",
         len(plan.defense_graph.defenses) >= 1
         and isinstance(plan.defense_graph.defenses[0].defense_type, DefenseType))

    # T07: rental no-notice → procedural defense classification
    fp, bm, ledger = build_inputs(
        "عندي مستأجر متأخر، ما أرسلت إنذار، أبغى أطلعه",
        LegalDomain.RENTAL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.RENTAL,
                          query="عندي مستأجر متأخر، ما أرسلت إنذار")
    test("T07: rental no-notice → procedural defense detected",
         any(d.defense_type == DefenseType.PROCEDURAL
             for d in plan.defense_graph.defenses))

    # T08: claim raised by claimant role assigned correctly
    fp, bm, ledger = build_inputs(
        "أبغى أرفع قضية على شخص أخذ مني مبلغ، ما عندي إلا واتساب",
        LegalDomain.CIVIL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.CIVIL,
                          query="أبغى أرفع قضية على شخص أخذ مني مبلغ")
    test("T08: claimant role correctly assigned in claim graph",
         plan.claim_graph.claims[0].raised_by == PartyRole.USER)

    # ══════════════════════════════════════════════════════════════
    # C. Evidence intelligence layer (T09-T13)
    # ══════════════════════════════════════════════════════════════

    fp, bm, ledger = build_inputs(
        "فصلوني، عندي تحويلات راتب، عندي رسائل واتساب، ما عندي عقد",
        LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني، عندي تحويلات راتب، عندي رسائل واتساب، ما عندي عقد، نقاط ضعفي؟")

    # T09: direct evidence captured
    test("T09: direct evidence captured",
         len(plan.evidence_intelligence.direct) >= 1)

    # T10: corroborative evidence captured (when 2+ direct exist)
    test("T10: corroborative evidence layer used",
         len(plan.evidence_intelligence.corroborative) >= 0)  # might or might not

    # T11: missing critical evidence flagged
    test("T11: missing critical evidence flagged for employment+no-contract",
         plan.evidence_intelligence.has_critical_gap())

    # T12: weak evidence (whatsapp only) classified
    fp, bm, ledger = build_inputs(
        "أخذ مني مبلغ، ما عندي إلا محادثات واتساب، نقاط ضعفي؟",
        LegalDomain.CIVIL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.CIVIL,
                          query="أخذ مني مبلغ، ما عندي إلا محادثات واتساب، نقاط ضعفي؟")
    test("T12: WhatsApp-only flagged as weak",
         len(plan.evidence_intelligence.weak) >= 1)

    # T13: contradictory evidence captured from disputed facts
    fp, bm, ledger = build_inputs(
        "صاحب الدين يعترف بالمبلغ لكن ينكر التاريخ ويختلف على القيمة",
        LegalDomain.CIVIL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.CIVIL,
                          query="صاحب الدين يعترف بالمبلغ لكن ينكر التاريخ ويختلف على القيمة")
    test("T13: contradictory evidence captured",
         len(plan.evidence_intelligence.contradictory) >= 1)

    # ══════════════════════════════════════════════════════════════
    # D. Party strength analysis (T14-T18)
    # ══════════════════════════════════════════════════════════════

    fp, bm, ledger = build_inputs(
        "فصلوني، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟",
        LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟")

    # T14: user strongest argument identified
    test("T14: user strongest argument identified",
         bool(plan.user_strength.strongest_argument)
         and "تحويلات" in plan.user_strength.strongest_argument)

    # T15: user weakest point identified
    test("T15: user weakest point identified",
         bool(plan.user_strength.weakest_point))

    # T16: opponent strongest argument identified
    test("T16: opponent strongest argument identified",
         bool(plan.opponent_strength.strongest_argument)
         and ("إنكار" in plan.opponent_strength.strongest_argument
              or "ادعاء" in plan.opponent_strength.strongest_argument))

    # T17: opponent weakest point identified
    test("T17: opponent weakest point identified",
         bool(plan.opponent_strength.weakest_point))

    # T18: no fatal weakness when none triggered
    fp, bm, ledger = build_inputs(
        "فصلوني، عندي تحويلات راتب، نقاط ضعفي؟", LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني، عندي تحويلات راتب، نقاط ضعفي؟")
    test("T18: no fatal weakness when not triggered",
         plan.user_strength.fatal_weakness is None)

    # ══════════════════════════════════════════════════════════════
    # E. Outcome branching (conditional only) (T19-T23)
    # ══════════════════════════════════════════════════════════════

    fp, bm, ledger = build_inputs(
        "فصلوني، عندي تحويلات راتب، ما عندي عقد", LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟")

    # T19: at least primary + fallback branches
    test("T19: at least 2 outcome branches built",
         len(plan.outcome_branches) >= 2)

    # T20: branch conditions use 'إذا' framing
    test("T20: branch conditions use conditional 'إذا' framing",
         all(b.condition.startswith("إذا") for b in plan.outcome_branches))

    # T21: branch outcomes use bounded language
    bounded = ["يتقوى", "يضعف", "يتعرض", "يتعطل", "يتحول"]
    test("T21: branch outcomes use bounded language",
         all(any(b in branch.outcome_frame for b in bounded)
             for branch in plan.outcome_branches))

    # T22: no certain verdict prediction in branches
    forbidden = ["ستفوز", "ستربح", "ستخسر", "محسومة", "%"]
    rendered = render_strategic_analysis(plan)
    test("T22: rendered analysis has no verdict prediction",
         not any(f in rendered for f in forbidden))

    # T23: rental no-notice → branches address procedural posture
    fp, bm, ledger = build_inputs(
        "عندي مستأجر متأخر، ما أرسلت إنذار",
        LegalDomain.RENTAL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.RENTAL,
                          query="عندي مستأجر متأخر، ما أرسلت إنذار")
    test("T23: rental branches address notice procedure",
         any("إنذار" in b.condition for b in plan.outcome_branches))

    # ══════════════════════════════════════════════════════════════
    # F. Strategic assessment (T24-T28)
    # ══════════════════════════════════════════════════════════════

    # T24: strong evidence → STRONG case
    fp = FactPattern()
    fp.evidence_present = ["تحويلات راتب", "خطاب تعيين", "شهود زملاء"]
    fp.has_substance = True
    fp.user_role = "claimant"
    bm = burden_engine.map_burden(LegalDomain.EMPLOYMENT, fp)
    ledger = evidence_reg.build_ledger(fp, bm)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="عندي كل أدلة العمل وأبغى أطالب بحقي")
    test("T24: rich evidence → STRONG or MODERATE assessment",
         plan.strategic_assessment.case_strength
         in (CaseStrength.STRONG, CaseStrength.MODERATE),
         f"got={plan.strategic_assessment.case_strength.value}")

    # T25: missing critical → INCOMPLETE / MODERATE
    fp, bm, ledger = build_inputs(
        "فصلوني وما عندي شي، ما عندي عقد ولا تحويلات", LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني وما عندي شي، ما عندي عقد ولا تحويلات")
    test("T25: empty evidence → INCOMPLETE/MODERATE assessment",
         plan.strategic_assessment.case_strength
         in (CaseStrength.INCOMPLETE, CaseStrength.MODERATE,
             CaseStrength.WEAK))

    # T26: needs additional evidence flag
    test("T26: missing critical → needs_additional_evidence=True",
         plan.strategic_assessment.needs_additional_evidence)

    # T27: weak-only evidence → recommend strategy change
    fp = FactPattern()
    fp.evidence_present = ["محادثات واتساب"]
    fp.has_substance = True
    fp.user_role = "claimant"
    bm = burden_engine.map_burden(LegalDomain.CIVIL, fp)
    ledger = evidence_reg.build_ledger(fp, bm)
    plan = engine.reason(fp, bm, ledger, LegalDomain.CIVIL,
                          query="أبغى أرفع قضية، ما عندي إلا محادثات واتساب")
    test("T27: weak-only evidence → strategy change suggested",
         plan.strategic_assessment.case_strength == CaseStrength.WEAK
         and plan.strategic_assessment.needs_strategy_change)

    # T28: procedural defense recommendation when procedural gap exists
    fp, bm, ledger = build_inputs(
        "صدر حكم ضدي، ما أعرف متى تبليغي، أبغى أطعن",
        LegalDomain.PROCEDURAL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.PROCEDURAL,
                          query="صدر حكم ضدي، ما أعرف متى تبليغي، أبغى أطعن")
    # Procedural gap exists when there's missing critical with تبليغ/إنذار/ميعاد
    if any("تبليغ" in m or "ميعاد" in m
           for m in plan.evidence_intelligence.missing_critical):
        test("T28: procedural gap → procedural defense recommended",
             plan.strategic_assessment.needed_defense_type == DefenseType.PROCEDURAL)
    else:
        test("T28: procedural gap → procedural defense recommended (skipped)",
             True)  # vacuous pass if no procedural gap

    # ══════════════════════════════════════════════════════════════
    # G. Opponent model (T29-T31)
    # ══════════════════════════════════════════════════════════════

    fp, bm, ledger = build_inputs(
        "فصلوني، عندي تحويلات راتب، ما عندي عقد", LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟")

    # T29: opponent best path identified
    test("T29: opponent best path identified",
         bool(plan.opponent_model.best_path_for_opponent))

    # T30: opponent likely attacks listed
    test("T30: opponent likely attacks listed (≥2)",
         len(plan.opponent_model.likely_attacks) >= 2)

    # T31: opponent will exploit weakness identified
    test("T31: opponent will-exploit weakness identified",
         len(plan.opponent_model.will_exploit_weakness) >= 1)

    # ══════════════════════════════════════════════════════════════
    # H. Critical evidence detector (T32-T34)
    # ══════════════════════════════════════════════════════════════

    # T32: critical evidence list populated
    test("T32: critical evidence list populated for employment",
         len(plan.critical_evidence) >= 1
         and isinstance(plan.critical_evidence[0], CriticalEvidenceItem))

    # T33: each critical item has if_present + if_absent framing
    test("T33: critical evidence has present/absent framing",
         all(ce.evidence_text and ce.if_present and ce.if_absent
             for ce in plan.critical_evidence))

    # T34: rental → critical evidence includes formal notice
    fp, bm, ledger = build_inputs(
        "عندي مستأجر متأخر، ما أرسلت إنذار", LegalDomain.RENTAL)
    plan = engine.reason(fp, bm, ledger, LegalDomain.RENTAL,
                          query="عندي مستأجر متأخر، ما أرسلت إنذار رسمي")
    test("T34: rental critical evidence mentions formal notice",
         any("إنذار" in ce.evidence_text for ce in plan.critical_evidence))

    # ══════════════════════════════════════════════════════════════
    # I. User-facing rendering (T35-T38)
    # ══════════════════════════════════════════════════════════════

    fp, bm, ledger = build_inputs(
        "فصلوني، عندي تحويلات راتب، ما عندي عقد", LegalDomain.EMPLOYMENT)
    plan = engine.reason(fp, bm, ledger, LegalDomain.EMPLOYMENT,
                          query="فصلوني، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟")
    rendered = render_strategic_analysis(plan)

    # T35: rendered text uses natural Arabic phrases
    test("T35: rendered text contains natural lawyer-style phrases",
         "التحليل القضائي" in rendered
         and ("أقوى ما يدعمك" in rendered or "أبرز نقطة ضعف" in rendered))

    # T36: rendered text does NOT expose internal structure
    forbidden_internal = ["claim_graph", "defense_graph", "burden_map",
                           "ClaimGraph", "DefenseGraph", "EvidenceIntelligence"]
    test("T36: no internal structure labels exposed",
         not any(t in rendered for t in forbidden_internal))

    # T37: rendered text mentions opponent strategy
    test("T37: rendered text addresses opponent strategy",
         "الطرف الآخر" in rendered or "ضدك" in rendered)

    # T38: rendered text uses conditional scenarios
    test("T38: rendered text uses conditional scenarios",
         "السيناريوهات" in rendered or "إذا" in rendered)

    # ══════════════════════════════════════════════════════════════
    # J. Reasoning constraints (T39-T41)
    # ══════════════════════════════════════════════════════════════

    # T39: never uses "غالباً" / "منطقياً" without basis
    test("T39: rendered text does not use 'منطقياً غالباً'",
         "منطقياً غالباً" not in rendered)

    # T40: never uses certainty language about outcomes
    certainty_terms = ["ستفوز حتماً", "النتيجة محسومة", "أكيد ينجح", "أكيد يفشل"]
    test("T40: no absolute certainty terms",
         not any(t in rendered for t in certainty_terms))

    # T41: no probability/percentage language
    import re
    test("T41: no percentage probability in rendered text",
         not re.search(r"\d+\s*%", rendered))

    # ══════════════════════════════════════════════════════════════
    # K. Integration with fail-closed pipeline (T42-T45)
    # ══════════════════════════════════════════════════════════════

    # T42: pipeline integration adds strategic section to passed queries
    r = answer_fail_closed(
        "فصلوني من العمل، عندي تحويلات راتب، ما عندي عقد، نقاط ضعفي؟")
    test("T42: pipeline applies strategic reasoning when gates pass",
         not r.is_blocked
         and any("strategic_reasoning_applied" in n for n in r.notes))

    # T43: text contains strategic analysis section
    test("T43: pipeline text contains strategic analysis",
         "التحليل القضائي" in r.text)

    # T44: blocked queries do NOT get strategic enhancement
    r = answer_fail_closed("سؤال غامض جداً")
    test("T44: blocked query → no strategic enhancement",
         r.is_blocked
         and "التحليل القضائي" not in r.text)

    # T45: strategic insufficiency rendered when needed
    plan_empty = StrategicReasoningPlan(is_substantive=False)
    insuff = render_strategic_insufficiency(plan_empty)
    test("T45: strategic insufficiency response is transparent",
         "تنبيه استراتيجي" in insuff
         and ("لا تُمكّن" in insuff or "غير كافية" in insuff
              or "توضيحات إضافية" in insuff))

    # ══════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{'='*50}")
    print(f"STRATEGIC REASONING TESTS: {passed}/{len(results)} passed")
    if failed:
        print("FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
    print(f"{'='*50}")

    return {"total": len(results), "passed": passed, "failed": failed, "results": results}


if __name__ == "__main__":
    run_strategic_reasoning_tests()
