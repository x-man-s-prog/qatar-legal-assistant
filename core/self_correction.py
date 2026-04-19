# -*- coding: utf-8 -*-
"""
core/self_correction.py — Self-Correction Loop
================================================
LLM → draft → Validator (DB + citations) → IF error → regenerate

Instead of blindly trusting the LLM output, this module validates
the draft answer against the actual database and regenerates if needed.

Architecture:
    1. Extract all legal citations from the draft
    2. Validate each citation against the DB (article number + law name)
    3. Check for hallucinated content not in provided context
    4. If validation fails → build correction prompt → regenerate
    5. Max 2 correction rounds to prevent infinite loops
"""
import re
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# ── Citation extraction patterns ──
_ARTICLE_PATTERN = re.compile(
    r'(?:المادة|م\.?)\s*(?:رقم\s*)?(\d{1,4})\s*(?:من\s+)?'
    r'(قانون[^،\n\.]{3,60}|القانون[^،\n\.]{3,60})?',
    re.UNICODE
)

_LAW_NAME_PATTERN = re.compile(
    r'(?:قانون|القانون)\s+([^،\n\.]{3,60}?)(?:\s+رقم\s+\d+)?(?:\s+لسنة\s+\d+)?',
    re.UNICODE
)


def extract_citations(text: str) -> list[dict]:
    """
    Extract all legal citations from an answer.
    Returns list of {"article": str, "law_hint": str, "full_match": str}.
    """
    citations = []
    for m in _ARTICLE_PATTERN.finditer(text):
        citations.append({
            "article": m.group(1),
            "law_hint": (m.group(2) or "").strip(),
            "full_match": m.group(0).strip(),
            "start": m.start(),
            "end": m.end(),
        })
    return citations


async def validate_citations_against_db(citations: list[dict], pool) -> list[dict]:
    """
    Validate extracted citations against the actual database.
    Returns list of validation results with 'valid' flag.
    """
    if not pool or not citations:
        return citations

    async with pool.acquire() as conn:
        for cit in citations:
            art_num = cit["article"]
            law_hint = cit.get("law_hint", "")

            # Try exact match first
            if law_hint:
                # Clean law hint for ILIKE
                clean_hint = law_hint.replace("قانون ", "").replace("القانون ", "").strip()
                row = await conn.fetchval(
                    "SELECT COUNT(*) FROM chunks WHERE is_active=true "
                    "AND article_number = $1 AND law_name ILIKE $2 "
                    "AND law_name NOT ILIKE '%أحكام محكمة التمييز%'",
                    art_num, f"%{clean_hint}%"
                )
                cit["valid"] = row > 0
                cit["validation"] = "exact_match" if row > 0 else "law_mismatch"
            else:
                # Check if article exists in any law
                row = await conn.fetchval(
                    "SELECT COUNT(*) FROM chunks WHERE is_active=true "
                    "AND article_number = $1 "
                    "AND law_name NOT ILIKE '%أحكام محكمة التمييز%'",
                    art_num
                )
                cit["valid"] = row > 0
                cit["validation"] = "article_exists" if row > 0 else "article_not_found"

    return citations


def check_grounding(answer: str, context: str) -> dict:
    """
    Check if the answer is grounded in the provided context.
    Returns grounding report with score and issues.
    """
    if not context or not answer:
        return {"grounded": True, "score": 1.0, "issues": []}

    issues = []

    # Extract key claims from answer (sentences with legal refs)
    sentences = re.split(r'[.،\n]', answer)
    legal_sentences = [s.strip() for s in sentences if _ARTICLE_PATTERN.search(s)]

    # Check if cited articles appear in context
    for sent in legal_sentences:
        for m in _ARTICLE_PATTERN.finditer(sent):
            art_num = m.group(1)
            if f"المادة {art_num}" not in context and f"م.{art_num}" not in context and f"مادة {art_num}" not in context:
                issues.append({
                    "type": "ungrounded_citation",
                    "article": art_num,
                    "sentence": sent[:100],
                })

    score = 1.0 - (len(issues) * 0.2)  # Each issue reduces by 20%
    score = max(0.0, score)

    return {
        "grounded": len(issues) == 0,
        "score": score,
        "issues": issues,
    }


def build_correction_prompt(
    original_question: str,
    draft_answer: str,
    validation_results: list[dict],
    grounding_report: dict,
    context: str,
) -> str:
    """
    Build a correction prompt that tells the LLM to fix specific issues.
    """
    invalid_citations = [c for c in validation_results if not c.get("valid")]
    ungrounded = grounding_report.get("issues", [])

    prompt = "⚠️ المراجعة التلقائية وجدت أخطاء في مسودتك:\n\n"

    if invalid_citations:
        prompt += "❌ مواد قانونية غير صحيحة (غير موجودة في قاعدة البيانات):\n"
        for c in invalid_citations:
            prompt += f"  • {c['full_match']} — {c['validation']}\n"
        prompt += "\n"

    if ungrounded:
        prompt += "❌ استشهادات غير مدعومة بالنصوص المقدمة:\n"
        for u in ungrounded:
            prompt += f"  • المادة {u['article']} — غير موجودة في السياق\n"
        prompt += "\n"

    prompt += (
        "📝 أعد كتابة إجابتك مع التصحيحات التالية:\n"
        "1. احذف أو صحّح المواد غير الصحيحة\n"
        "2. استخدم فقط المواد الموجودة في النصوص المقدمة أدناه\n"
        "3. إذا لم تجد مادة مناسبة → اذكر اسم القانون فقط بدون رقم مادة\n"
        "4. لا تختلق أرقام مواد جديدة\n\n"
        f"النصوص القانونية المتاحة:\n{context[:3000]}\n\n"
        f"السؤال الأصلي: {original_question}\n\n"
        f"المسودة (تحتاج تصحيح):\n{draft_answer[:2000]}\n\n"
        "أعد كتابة الإجابة مصححة:"
    )

    return prompt


async def self_correct(
    question: str,
    draft_answer: str,
    context: str,
    relevant_chunks: list,
    pool,
    llm_generator=None,
    system_prompt: str = "",
    max_rounds: int = 2,
) -> tuple[str, dict]:
    """
    Main self-correction loop.

    Args:
        question: Original user question
        draft_answer: First LLM draft
        context: RAG context provided to LLM
        relevant_chunks: RAG chunks for validation
        pool: DB pool for citation validation
        llm_generator: Async function(system, messages, max_tokens) → str
        system_prompt: System prompt for regeneration
        max_rounds: Max correction rounds (default 2)

    Returns:
        (final_answer, correction_report)
    """
    t_start = time.time()
    report = {
        "rounds": 0,
        "original_issues": 0,
        "final_issues": 0,
        "corrections_made": [],
        "latency_ms": 0,
    }

    current_answer = draft_answer

    for round_num in range(max_rounds):
        # Step 1: Extract citations
        citations = extract_citations(current_answer)
        if not citations:
            # No citations to validate
            break

        # Step 2: Validate against DB
        citations = await validate_citations_against_db(citations, pool)

        # Step 3: Check grounding
        grounding = check_grounding(current_answer, context)

        # Step 4: Count issues
        invalid = [c for c in citations if not c.get("valid")]
        issues_count = len(invalid) + len(grounding.get("issues", []))

        if round_num == 0:
            report["original_issues"] = issues_count

        if issues_count == 0:
            # All citations valid — done
            log.info("self_correction: round %d — no issues found (%d citations checked)",
                     round_num + 1, len(citations))
            break

        log.info("self_correction: round %d — %d issues found (%d invalid citations, %d ungrounded)",
                 round_num + 1, issues_count, len(invalid), len(grounding.get("issues", [])))

        # Step 5: Build correction prompt and regenerate
        if llm_generator:
            correction_prompt = build_correction_prompt(
                question, current_answer, citations, grounding, context
            )
            try:
                current_answer = await llm_generator(
                    system_prompt or "أنت مساعد قانوني قطري. صحّح الإجابة بناءً على التعليمات.",
                    [{"role": "user", "content": correction_prompt}],
                    2500
                )
                report["corrections_made"].append({
                    "round": round_num + 1,
                    "invalid_citations": len(invalid),
                    "ungrounded": len(grounding.get("issues", [])),
                })
            except Exception as e:
                log.warning("self_correction regeneration failed: %s", e)
                break
        else:
            # No LLM available for regeneration — just strip invalid citations
            for cit in reversed(invalid):
                # Remove the invalid citation text
                current_answer = current_answer.replace(cit["full_match"], f"({cit['law_hint'] or 'القانون المختص'})")
            report["corrections_made"].append({
                "round": round_num + 1,
                "action": "strip_invalid",
                "stripped": len(invalid),
            })
            break

        report["rounds"] = round_num + 1

    # Final validation
    final_citations = extract_citations(current_answer)
    if pool and final_citations:
        final_citations = await validate_citations_against_db(final_citations, pool)
        report["final_issues"] = len([c for c in final_citations if not c.get("valid")])

    report["latency_ms"] = int((time.time() - t_start) * 1000)

    if report["original_issues"] > 0:
        log.info("self_correction complete: %d→%d issues, %d rounds, %dms",
                 report["original_issues"], report["final_issues"],
                 report["rounds"], report["latency_ms"])

    return current_answer, report
