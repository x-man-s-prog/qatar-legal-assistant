# -*- coding: utf-8 -*-
"""
Citation Verifier — checks every article/ruling reference against:
  1. The retrieved context chunks (fast, no DB)
  2. The database directly (authoritative fallback)
Purely deterministic — no LLM.
"""
import re, logging
from typing import Optional
from .schemas import (
    ExtractedClaim, ClaimType,
    CitationCheck, CitationVerificationResult,
)

log = logging.getLogger(__name__)


def _normalize_article(num: str) -> str:
    """Normalize article number for comparison."""
    return re.sub(r"\s+", "", num).strip()


def _context_has_article(article_num: str, law_fragment: str,
                         chunks: list[dict]) -> tuple[bool, Optional[str]]:
    """Check if article_num appears in the retrieved chunks."""
    norm_art = _normalize_article(article_num)
    law_lower = law_fragment.lower().strip() if law_fragment else ""

    for ch in chunks:
        ch_art = str(ch.get("article_number", "") or "").strip()
        ch_law = str(ch.get("law_name", "") or "").lower()
        ch_content = str(ch.get("content", "") or "")

        # Direct article number match
        if ch_art == norm_art:
            # If law name specified, also check law
            if law_lower and law_lower not in ch_law:
                continue
            return True, ch_content[:300]

        # Fallback: article number mentioned in content text
        if f"المادة {norm_art}" in ch_content or f"مادة {norm_art}" in ch_content:
            if law_lower and law_lower not in ch_law:
                continue
            return True, ch_content[:300]

    return False, None


async def _db_has_article(pool, article_num: str,
                          law_fragment: str) -> tuple[bool, Optional[str]]:
    """Direct database check — authoritative source of truth."""
    if not pool:
        return False, None

    norm_art = _normalize_article(article_num)
    try:
        async with pool.acquire() as conn:
            if law_fragment:
                row = await conn.fetchrow(
                    "SELECT content, law_name FROM chunks "
                    "WHERE is_active=true AND article_number=$1 "
                    "AND law_name ILIKE $2 LIMIT 1",
                    norm_art, f"%{law_fragment}%"
                )
            else:
                row = await conn.fetchrow(
                    "SELECT content, law_name FROM chunks "
                    "WHERE is_active=true AND article_number=$1 LIMIT 1",
                    norm_art
                )
            if row:
                return True, row["content"][:300]
    except Exception as e:
        log.debug("citation_verifier db check: %s", e)

    return False, None


async def verify_citations(
    claims: list[ExtractedClaim],
    chunks: list[dict],
    pool=None,
) -> CitationVerificationResult:
    """
    Verify every article_ref and ruling_ref claim.
    Returns detailed results per citation.
    """
    citation_claims = [
        c for c in claims
        if c.claim_type in (ClaimType.ARTICLE_REF, ClaimType.RULING_REF)
    ]

    if not citation_claims:
        return CitationVerificationResult(total=0, verified=0, failed=0)

    checks: list[CitationCheck] = []
    fabricated: list[str] = []

    for claim in citation_claims:
        art = claim.article_number or ""
        law = claim.law_name or ""

        # Step 1: Check retrieved context (fast)
        in_ctx, ctx_content = _context_has_article(art, law, chunks)

        # Step 2: If not in context, check DB (authoritative)
        in_db = False
        db_content = None
        if not in_ctx and pool and art:
            in_db, db_content = await _db_has_article(pool, art, law)

        verified = in_ctx or in_db
        actual = ctx_content or db_content

        mismatch = None
        if not verified:
            mismatch = f"المادة {art} غير موجودة في القاعدة"
            if law:
                mismatch += f" (بحث في: {law})"
            fabricated.append(claim.text)

        checks.append(CitationCheck(
            claim=claim,
            found_in_context=in_ctx,
            found_in_db=in_db,
            actual_content=actual,
            mismatch_detail=mismatch,
            verified=verified,
        ))

    verified_count = sum(1 for c in checks if c.verified)
    failed_count = sum(1 for c in checks if not c.verified)

    return CitationVerificationResult(
        checks=checks,
        total=len(checks),
        verified=verified_count,
        failed=failed_count,
        fabricated=fabricated,
    )
