# -*- coding: utf-8 -*-
"""
Grounding Verifier V3 — 4-layer hybrid:
  1. Deterministic keyword overlap (fast, free)
  2. Root-matching semantic similarity (fast, free)
  3. Embedding cosine similarity (medium, decisive claims only)
  4. LLM verification (expensive, ambiguous decisive only)
"""
import re, math, logging
from typing import Callable, Optional
from .schemas import (
    ExtractedClaim, ClaimType, EvidenceLevel,
    GroundingCheck, GroundingResult,
)

log = logging.getLogger("sc_pipeline")

_GROUNDABLE_TYPES = {
    ClaimType.PENALTY, ClaimType.LEGAL_CONCLUSION,
    ClaimType.PROCEDURAL, ClaimType.FACTUAL,
}

_STOP_WORDS = {
    "من", "في", "على", "إلى", "عن", "أن", "إن", "هذا", "هذه",
    "التي", "الذي", "كان", "يكون", "لا", "ما", "هو", "هي",
    "أو", "ذلك", "تلك", "بين", "كل", "قد", "بعد", "قبل",
    "عند", "حتى", "مع", "ثم", "لم", "لن", "إذا", "أي",
}

# Configurable thresholds
THRESH_EXPLICIT = 0.55
THRESH_INFERRED = 0.30
THRESH_EMBED_EXPLICIT = 0.80
THRESH_EMBED_INFERRED = 0.60


def _extract_words(text: str) -> set[str]:
    words = set(re.findall(r"[\u0600-\u06FF]{3,}", text))
    return words - _STOP_WORDS


def _semantic_similarity(claim_words: set[str], chunk_words: set[str]) -> float:
    if not claim_words or not chunk_words:
        return 0.0
    direct = len(claim_words & chunk_words)
    root_matches = 0
    for cw in claim_words - chunk_words:
        if any(ew.startswith(cw[:3]) for ew in chunk_words):
            root_matches += 1
    return min(1.0, (direct + root_matches * 0.5) / len(claim_words))


def _deterministic_ground(claim_text: str, chunks: list[dict]) -> tuple[EvidenceLevel, int | None, float]:
    claim_words = _extract_words(claim_text)
    if len(claim_words) < 2:
        return EvidenceLevel.INFERRED, None, 0.5

    best_score, best_idx = 0.0, None
    for i, ch in enumerate(chunks):
        chunk_words = _extract_words(ch.get("content", "") or "")
        if not chunk_words:
            continue
        sim = _semantic_similarity(claim_words, chunk_words)
        if sim > best_score:
            best_score, best_idx = sim, i

    if best_score >= THRESH_EXPLICIT:
        return EvidenceLevel.EXPLICIT, best_idx, best_score
    elif best_score >= THRESH_INFERRED:
        return EvidenceLevel.INFERRED, best_idx, best_score
    return EvidenceLevel.UNSUPPORTED, best_idx, best_score


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


async def _embedding_ground(claim_text: str, chunks: list[dict],
                             embed_fn: Callable) -> tuple[EvidenceLevel, int | None, float]:
    """Embedding-based grounding: cosine similarity between claim and evidence embeddings."""
    try:
        claim_emb = await embed_fn(claim_text[:500])
        best_sim, best_idx = 0.0, None
        for i, ch in enumerate(chunks[:7]):  # Top 7 only for latency
            content = (ch.get("content", "") or "")[:500]
            if len(content) < 20:
                continue
            chunk_emb = await embed_fn(content)
            sim = _cosine_sim(claim_emb, chunk_emb)
            if sim > best_sim:
                best_sim, best_idx = sim, i

        log.info("[GROUND] embedding: best_sim=%.3f idx=%s", best_sim, best_idx)
        if best_sim >= THRESH_EMBED_EXPLICIT:
            return EvidenceLevel.EXPLICIT, best_idx, best_sim
        elif best_sim >= THRESH_EMBED_INFERRED:
            return EvidenceLevel.INFERRED, best_idx, best_sim
        return EvidenceLevel.UNSUPPORTED, best_idx, best_sim
    except Exception as e:
        log.warning("[GROUND] embedding failed: %s", e)
        return EvidenceLevel.UNSUPPORTED, None, 0.0


_LLM_GROUNDING_PROMPT = """أنت مدقق قانوني. هل الادعاء التالي مدعوم بالنص القانوني؟

الادعاء: {claim}

النص القانوني:
{evidence}

أجب بـ JSON فقط:
{{"supported": true/false, "level": "explicit|inferred|unsupported", "reason": "سبب مختصر"}}"""


async def _llm_ground(claim_text: str, evidence: str, llm_caller: Callable) -> EvidenceLevel:
    try:
        prompt = _LLM_GROUNDING_PROMPT.format(claim=claim_text, evidence=evidence[:800])
        result = await llm_caller("أنت مدقق قانوني صارم. أجب بـ JSON فقط.", [{"role": "user", "content": prompt}])
        import json
        clean = result.strip().strip("`").replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        mapping = {"explicit": EvidenceLevel.EXPLICIT, "inferred": EvidenceLevel.INFERRED,
                    "unsupported": EvidenceLevel.UNSUPPORTED}
        return mapping.get(data.get("level", "unsupported"), EvidenceLevel.UNSUPPORTED)
    except Exception as e:
        log.debug("[GROUND] LLM failed: %s", e)
        return EvidenceLevel.UNSUPPORTED


async def verify_grounding(
    claims: list[ExtractedClaim],
    chunks: list[dict],
    llm_caller: Optional[Callable] = None,
    embed_fn: Optional[Callable] = None,
) -> GroundingResult:
    """
    4-layer grounding verification:
    1. Deterministic (all claims)
    2. Embedding (decisive unsupported only, if embed_fn provided)
    3. LLM (still-unsupported decisive only, if llm_caller provided)
    """
    groundable = [c for c in claims if c.claim_type in _GROUNDABLE_TYPES]
    if not groundable:
        return GroundingResult(total=0, grounded=0, unsupported=0, unsupported_decisive=0)

    checks: list[GroundingCheck] = []
    for claim in groundable:
        # Layer 1+2: Deterministic + root matching
        level, chunk_idx, det_score = _deterministic_ground(claim.text, chunks)
        method = f"det={det_score:.2f}"

        # Layer 3: Embedding (decisive unsupported only)
        if (level == EvidenceLevel.UNSUPPORTED and claim.is_decisive and embed_fn):
            emb_level, emb_idx, emb_score = await _embedding_ground(claim.text, chunks, embed_fn)
            method += f" emb={emb_score:.2f}"
            if emb_level in (EvidenceLevel.EXPLICIT, EvidenceLevel.INFERRED):
                level = emb_level
                chunk_idx = emb_idx if emb_idx is not None else chunk_idx

        # Layer 4: LLM (still unsupported decisive only)
        if (level == EvidenceLevel.UNSUPPORTED and claim.is_decisive
                and llm_caller and chunk_idx is not None):
            evidence = chunks[chunk_idx].get("content", "")[:800]
            level = await _llm_ground(claim.text, evidence, llm_caller)
            method += f" llm={level.value}"

        checks.append(GroundingCheck(
            claim=claim, evidence_level=level,
            supporting_chunk_idx=chunk_idx,
            explanation=method,
        ))

    grounded = sum(1 for c in checks if c.evidence_level in (EvidenceLevel.EXPLICIT, EvidenceLevel.INFERRED))
    unsupported = sum(1 for c in checks if c.evidence_level == EvidenceLevel.UNSUPPORTED)
    unsupported_decisive = sum(1 for c in checks if c.evidence_level == EvidenceLevel.UNSUPPORTED and c.claim.is_decisive)

    return GroundingResult(checks=checks, total=len(checks), grounded=grounded,
                           unsupported=unsupported, unsupported_decisive=unsupported_decisive)
