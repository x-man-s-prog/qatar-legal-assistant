# -*- coding: utf-8 -*-
"""Self-Correction Pipeline V3 — with adaptive risk + re-validation."""
import time, logging
from typing import Callable, Optional
from .schemas import GateDecision, GateVerdict, QueryContext, QueryComplexity
from .claim_extractor import extract_claims
from .citation_verifier import verify_citations
from .grounding_verifier import verify_grounding
from .contradiction_checker import check_contradictions
from .coverage_checker import check_coverage
from .risk_scorer import score_risk, RISK_REPAIR
from .repair_controller import attempt_repair
from .gate import decide

log = logging.getLogger("sc_pipeline")


class SelfCorrectionPipeline:

    def __init__(self, pool=None):
        self.pool = pool

    async def _run_checks(self, answer, query, chunks, llm_caller, use_llm, ctx, embed_fn=None):
        claims_result = extract_claims(answer)
        if claims_result.total_claims == 0:
            return claims_result, None, None, None, None, None

        citation_result = await verify_citations(claims_result.claims, chunks, pool=self.pool)
        grounding_result = await verify_grounding(
            claims_result.claims, chunks,
            llm_caller=llm_caller if use_llm else None,
            embed_fn=embed_fn)
        contradiction_result = await check_contradictions(
            answer, chunks,
            llm_caller=llm_caller if use_llm else None,
            use_llm=use_llm)
        coverage_result = check_coverage(query, answer)
        risk = score_risk(citation_result, grounding_result,
                          contradiction_result, coverage_result, ctx=ctx)
        return claims_result, citation_result, grounding_result, contradiction_result, coverage_result, risk

    async def run(
        self,
        answer: str,
        query: str,
        chunks: list[dict],
        llm_caller: Optional[Callable] = None,
        use_llm_verification: bool = False,
        context: Optional[QueryContext] = None,
        embed_fn: Optional[Callable] = None,
    ) -> GateDecision:
        t0 = time.perf_counter()
        ctx = context or QueryContext()

        if len(answer.strip()) < 30 or not chunks:
            return GateDecision(verdict=GateVerdict.PASS, final_answer=answer, latency_ms=0)

        claims, citation, grounding, contradiction, coverage, risk = \
            await self._run_checks(answer, query, chunks, llm_caller, use_llm_verification, ctx, embed_fn=embed_fn)

        if risk is None:
            return GateDecision(verdict=GateVerdict.PASS, final_answer=answer,
                                latency_ms=int((time.perf_counter() - t0) * 1000))

        log.info("[SC] risk=%.2f cite=%.2f ground=%.2f contra=%.2f cover=%.2f factors=%s",
                 risk.overall_risk, risk.citation_risk, risk.grounding_risk,
                 risk.contradiction_risk, risk.coverage_risk, risk.risk_factors[:3])

        # ── Repair if needed ──
        repair_result = None
        if risk.overall_risk > RISK_REPAIR or (citation and citation.fabricated):
            repair_result = await attempt_repair(
                answer=answer, risk=risk, citation=citation,
                grounding=grounding, contradiction=contradiction,
                coverage=coverage, chunks=chunks, llm_caller=llm_caller)
            log.info("[SC] repair rounds=%d actions=%s",
                     repair_result.rounds_used,
                     [a.action for a in repair_result.actions_taken])

            # ── Re-validate after repair ──
            if repair_result.repaired_answer != answer:
                _, cit2, gnd2, ctr2, cov2, risk2 = \
                    await self._run_checks(
                        repair_result.repaired_answer, query, chunks,
                        llm_caller, use_llm_verification, ctx, embed_fn=embed_fn)
                if risk2 is not None:
                    log.info("[SC] post-repair risk=%.2f (was %.2f)", risk2.overall_risk, risk.overall_risk)
                    if risk2.overall_risk <= risk.overall_risk:
                        citation, grounding, contradiction, coverage, risk = cit2, gnd2, ctr2, cov2, risk2
                    else:
                        repair_result.repaired_answer = answer
                        log.warning("[SC] repair worsened — reverting")

        # ── Gate ──
        decision = decide(answer=answer, risk=risk, citation=citation,
                          grounding=grounding, contradiction=contradiction,
                          coverage=coverage, repair=repair_result)
        decision.latency_ms = int((time.perf_counter() - t0) * 1000)

        if decision.verdict == GateVerdict.REFUSE:
            log.warning("[GATE] REFUSED: %s q='%s'", decision.refused_reason, query[:60])
        else:
            log.info("[GATE] verdict=%s conf_adj=%d ms=%d",
                     decision.verdict.value, decision.confidence_adjustment, decision.latency_ms)
        return decision
