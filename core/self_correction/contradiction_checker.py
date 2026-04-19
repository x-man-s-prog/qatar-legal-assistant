# -*- coding: utf-8 -*-
"""
Contradiction Checker — detects when the answer contradicts retrieved evidence.

Two layers:
  1. Deterministic: negation mismatch, number mismatch
  2. LLM: semantic contradiction (only for high-risk answers)
"""
import re, logging
from typing import Callable, Optional
from .schemas import Contradiction, ContradictionResult

log = logging.getLogger(__name__)

# Negation pairs — if answer says X and evidence says NOT-X
_NEGATION_PAIRS = [
    ("يحق", "لا يحق"),
    ("يجوز", "لا يجوز"),
    ("يجب", "لا يجب"),
    ("يستحق", "لا يستحق"),
    ("تسقط", "لا تسقط"),
    ("ملزم", "غير ملزم"),
    ("مشروع", "غير مشروع"),
    ("قانوني", "غير قانوني"),
    ("جائز", "غير جائز"),
    ("مقبول", "غير مقبول"),
    ("صحيح", "باطل"),
    ("نافذ", "غير نافذ"),
]

# Number extraction for penalty/duration comparison
_NUMBER_RE = re.compile(r"(\d+)\s*(سن[وة]|أشهر?|شهور|يوم|أيام|ريال)", re.UNICODE)


def _extract_numbers(text: str) -> list[tuple[int, str]]:
    """Extract (number, unit) pairs."""
    return [(int(m.group(1)), m.group(2)) for m in _NUMBER_RE.finditer(text)]


def _check_negation(answer: str, evidence: str,
                    law_name: str) -> list[Contradiction]:
    """Detect negation contradictions deterministically."""
    results = []
    ans_lower = answer.lower()
    ev_lower = evidence.lower()

    for positive, negative in _NEGATION_PAIRS:
        # Answer says positive, evidence says negative
        if positive in ans_lower and negative in ev_lower:
            # Find surrounding context
            pos_idx = ans_lower.index(positive)
            ans_seg = answer[max(0, pos_idx - 30):pos_idx + 60].strip()
            neg_idx = ev_lower.index(negative)
            ev_seg = evidence[max(0, neg_idx - 30):neg_idx + 60].strip()

            results.append(Contradiction(
                answer_segment=ans_seg,
                evidence_segment=ev_seg,
                source_law=law_name,
                severity="major",
                explanation=f"الإجابة تقول '{positive}' لكن النص القانوني يقول '{negative}'",
            ))
        # Answer says negative, evidence says positive
        elif negative in ans_lower and positive in ev_lower and negative not in ev_lower:
            pos_idx = ans_lower.index(negative)
            ans_seg = answer[max(0, pos_idx - 30):pos_idx + 60].strip()
            neg_idx = ev_lower.index(positive)
            ev_seg = evidence[max(0, neg_idx - 30):neg_idx + 60].strip()

            results.append(Contradiction(
                answer_segment=ans_seg,
                evidence_segment=ev_seg,
                source_law=law_name,
                severity="major",
                explanation=f"الإجابة تقول '{negative}' لكن النص القانوني يقول '{positive}'",
            ))

    return results


def _check_number_mismatch(answer: str, evidence: str,
                           law_name: str) -> list[Contradiction]:
    """Detect when answer cites a different number than evidence."""
    ans_nums = _extract_numbers(answer)
    ev_nums = _extract_numbers(evidence)

    results = []
    for a_num, a_unit in ans_nums:
        for e_num, e_unit in ev_nums:
            # Same unit but different number — potential contradiction
            if a_unit == e_unit and a_num != e_num:
                # Only flag if significant difference
                if abs(a_num - e_num) > min(a_num, e_num) * 0.1:
                    results.append(Contradiction(
                        answer_segment=f"{a_num} {a_unit}",
                        evidence_segment=f"{e_num} {e_unit}",
                        source_law=law_name,
                        severity="major" if abs(a_num - e_num) > 1 else "minor",
                        explanation=f"رقم مختلف: الإجابة={a_num} {a_unit}، النص={e_num} {e_unit}",
                    ))
    return results


_LLM_CONTRADICTION_PROMPT = """أنت مدقق قانوني. هل توجد تناقضات بين الإجابة والنص القانوني؟

الإجابة:
{answer_segment}

النص القانوني:
{evidence}

أجب بـ JSON:
{{"has_contradiction": true/false, "contradictions": [{{"answer": "...", "evidence": "...", "severity": "major/minor", "explanation": "..."}}]}}"""


async def check_contradictions(
    answer: str,
    chunks: list[dict],
    llm_caller: Optional[Callable] = None,
    use_llm: bool = False,
) -> ContradictionResult:
    """
    Multi-layer contradiction detection.
    Layer 1: Negation pairs (deterministic)
    Layer 2: Number mismatches (deterministic)
    Layer 3: LLM semantic check (only if use_llm=True and high-value chunks)
    """
    all_contradictions: list[Contradiction] = []

    for ch in chunks[:7]:  # Top 7 most relevant chunks
        content = ch.get("content", "") or ""
        law = ch.get("law_name", "") or ""

        if len(content) < 30:
            continue

        # Layer 1: Negation
        neg = _check_negation(answer, content, law)
        all_contradictions.extend(neg)

        # Layer 2: Number mismatch
        num = _check_number_mismatch(answer, content, law)
        all_contradictions.extend(num)

    # Layer 3: LLM (only for complex answers with no deterministic findings)
    if (use_llm and llm_caller and not all_contradictions
            and len(answer.split()) > 50 and chunks):
        try:
            import json as _json
            evidence = "\n---\n".join(
                ch.get("content", "")[:400] for ch in chunks[:3]
            )
            prompt = _LLM_CONTRADICTION_PROMPT.format(
                answer_segment=answer[:600], evidence=evidence[:1200]
            )
            result = await llm_caller(
                "أنت مدقق قانوني. أجب بـ JSON فقط.",
                [{"role": "user", "content": prompt}]
            )
            data = _json.loads(result.strip().strip("`").replace("```json", "").replace("```", ""))
            if data.get("has_contradiction"):
                for c in data.get("contradictions", [])[:3]:
                    all_contradictions.append(Contradiction(
                        answer_segment=c.get("answer", ""),
                        evidence_segment=c.get("evidence", ""),
                        severity=c.get("severity", "minor"),
                        explanation=c.get("explanation", ""),
                    ))
        except Exception as e:
            log.debug("llm contradiction check: %s", e)

    has_major = any(c.severity == "major" for c in all_contradictions)

    return ContradictionResult(
        contradictions=all_contradictions,
        has_major=has_major,
        count=len(all_contradictions),
    )
