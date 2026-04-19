# -*- coding: utf-8 -*-
"""
Repair Controller V3 — deterministic-first, strict ordering:
  1. Remove fabricated citations
  2. Remove unsupported decisive claims
  3. Downgrade certainty language
  4. Enforce citation linkage disclaimer
  5. LLM constrained rewrite (only if still needed)
"""
import re, logging
from typing import Callable, Optional
from .schemas import (
    RiskScore, CitationVerificationResult, GroundingResult,
    ContradictionResult, CoverageResult,
    RepairAction, RepairResult, EvidenceLevel,
)
from .risk_scorer import RISK_PASS, RISK_REPAIR

log = logging.getLogger("sc_pipeline")
MAX_REPAIR_ROUNDS = 2

_DISCLAIMER_AR = (
    "\n\n> ⚠️ **تنبيه**: بعض المعلومات قد لا تكون مؤكدة. يُنصح بمراجعة محامٍ مختص."
)

_CERTAINTY_DOWNGRADES = [
    ("يحق لك", "قد يحق لك — حسب النصوص المتاحة —"),
    ("يجب عليك", "يُستحسن — بناءً على النصوص المتاحة —"),
    ("بالتأكيد", "على الأرجح"),
    ("حتماً", "في الغالب"),
    ("قطعاً", "على الأرجح"),
    ("بشكل مؤكد", "بناءً على النصوص المتاحة"),
]

_REPAIR_SYSTEM = """أنت مصحح قانوني. أعد كتابة الإجابة بتصحيح المشكلات فقط.
لا تضف معلومات جديدة. لا تغيّر ما هو صحيح. اكتب بالعربية الفصحى.
إذا لم تجد سنداً للادعاء في النصوص — احذفه أو أضف تحفظاً."""

_REPAIR_TEMPLATE = """الإجابة الأصلية:
{answer}

المشكلات:
{issues}

النصوص القانونية الصحيحة:
{evidence}

أعد كتابة الإجابة بتصحيح المشكلات فقط. لا تذكر مواد لم ترد في النصوص."""


def _remove_fabricated(answer: str, fabricated: list[str]) -> tuple[str, bool]:
    cleaned = answer
    changed = False
    for fab in fabricated:
        if fab in cleaned:
            cleaned = cleaned.replace(fab, "")
            changed = True
        art_match = re.search(r"(\d+)", fab)
        if art_match:
            art_num = art_match.group(1)
            for pat in [
                rf"وفقاً?\s+للمادة\s+\(?\s*{art_num}\s*\)?\s*(?:من[^\.،]+)?[\.،]?\s*",
                rf"(?:كما\s+)?(?:تنص|نصت)\s+المادة\s+\(?\s*{art_num}\s*\)?\s*(?:من[^\.،]+)?[^\.]*\.\s*",
            ]:
                new = re.sub(pat, "", cleaned)
                if new != cleaned:
                    cleaned = new
                    changed = True
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, changed


def _remove_unsupported_claims(answer: str, grounding: GroundingResult) -> tuple[str, bool]:
    """Remove sentences containing unsupported decisive claims."""
    cleaned = answer
    changed = False
    for gc in grounding.checks:
        if gc.evidence_level == EvidenceLevel.UNSUPPORTED and gc.claim.is_decisive:
            claim_text = gc.claim.text
            # Try to remove the sentence containing this claim
            for sent in re.split(r'[.。\n]', answer):
                sent = sent.strip()
                if claim_text[:20] in sent and len(sent) > 10:
                    cleaned = cleaned.replace(sent + ".", "").replace(sent, "")
                    changed = True
                    break
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, changed


def _downgrade_certainty(answer: str) -> tuple[str, bool]:
    changed = False
    result = answer
    for old_text, replacement in _CERTAINTY_DOWNGRADES:
        if old_text in result:
            result = result.replace(old_text, replacement)
            changed = True
    return result, changed


async def attempt_repair(
    answer: str,
    risk: RiskScore,
    citation: CitationVerificationResult,
    grounding: GroundingResult,
    contradiction: ContradictionResult,
    coverage: CoverageResult,
    chunks: list[dict],
    llm_caller: Optional[Callable] = None,
) -> RepairResult:
    result = RepairResult(original_answer=answer, repaired_answer=answer, rounds_used=0)
    current = answer

    # ══ Round 1: Deterministic fixes (strict order) ══

    # Step 1: Remove fabricated citations
    if citation.fabricated:
        current, did = _remove_fabricated(current, citation.fabricated)
        if did:
            result.actions_taken.append(RepairAction(
                action="remove_fabricated", target=", ".join(citation.fabricated),
                instruction="حذف مواد مفبركة", applied=True))

    # Step 2: Remove unsupported decisive claims
    if grounding.unsupported_decisive > 0 and citation.verified == 0:
        current, did = _remove_unsupported_claims(current, grounding)
        if did:
            result.actions_taken.append(RepairAction(
                action="remove_unsupported", target="decisive claims",
                instruction="حذف ادعاءات بدون سند", applied=True))

    # Step 3: Downgrade certainty language
    if risk.overall_risk > RISK_PASS:
        current, did = _downgrade_certainty(current)
        if did:
            result.actions_taken.append(RepairAction(
                action="downgrade_certainty", target="language",
                instruction="تخفيف لغة اليقين", applied=True))

    # Step 4: Add disclaimer if still risky
    if grounding.unsupported_decisive > 0 and risk.overall_risk > RISK_PASS:
        if _DISCLAIMER_AR not in current:
            current += _DISCLAIMER_AR
            result.actions_taken.append(RepairAction(
                action="add_disclaimer", target="end", instruction="تنبيه", applied=True))

    result.repaired_answer = current
    result.rounds_used = 1

    if risk.overall_risk <= RISK_REPAIR:
        return result

    # ══ Round 2: LLM constrained rewrite ══
    if llm_caller and risk.overall_risk > RISK_REPAIR and result.rounds_used < MAX_REPAIR_ROUNDS:
        try:
            issues = []
            if citation.fabricated:
                issues.append("مواد مفبركة: " + "، ".join(citation.fabricated))
            for gc in grounding.checks:
                if gc.evidence_level == EvidenceLevel.UNSUPPORTED and gc.claim.is_decisive:
                    issues.append(f"ادعاء بدون سند: {gc.claim.text}")
            for ct in contradiction.contradictions:
                if ct.severity == "major":
                    issues.append(f"تناقض: '{ct.answer_segment}' مقابل '{ct.evidence_segment}'")
            evidence = "\n---\n".join(ch.get("content", "")[:500] for ch in chunks[:5])
            prompt = _REPAIR_TEMPLATE.format(
                answer=current[:1500], issues="\n".join(f"• {i}" for i in issues),
                evidence=evidence[:2000])
            rewritten = await llm_caller(_REPAIR_SYSTEM, [{"role": "user", "content": prompt}])
            if rewritten and len(rewritten.strip()) > 50:
                result.repaired_answer = rewritten.strip()
                result.actions_taken.append(RepairAction(
                    action="llm_rewrite", target="full_answer",
                    instruction="إعادة كتابة مقيّدة", applied=True))
                result.rounds_used = 2
        except Exception as e:
            log.warning("[REPAIR] LLM rewrite failed: %s", e)

    return result
