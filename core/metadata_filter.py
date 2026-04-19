# -*- coding: utf-8 -*-
"""
core/metadata_filter.py — Metadata Filtering for RAG Search
=============================================================
Filters search results by metadata fields: law_name, law_year,
law_domain, article_number, etc.

Usage:
    filtered = apply_metadata_filters(chunks, filters={
        "law_domain": "عمالي",
        "year_range": (2000, 2024),
        "law_name_contains": "العمل",
    })
"""
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Domain keyword mapping ──
DOMAIN_KEYWORDS = {
    "عمالي": ["عمل", "عمال", "عامل", "عمالة", "صاحب العمل", "مكافأة", "إجازة", "فصل", "استقالة"],
    "جزائي": ["عقوبة", "جريمة", "جزاء", "حبس", "سجن", "غرامة", "جناية", "جنحة"],
    "أسري": ["زواج", "طلاق", "حضانة", "نفقة", "خلع", "أسرة", "أحوال شخصية"],
    "تجاري": ["شركة", "تجارة", "تجاري", "سجل", "ترخيص", "إفلاس", "تصفية"],
    "مدني": ["عقد", "تعويض", "مسؤولية", "ضمان", "ملكية", "إيجار", "رهن"],
    "إداري": ["إداري", "موظف", "حكومي", "مناقصة", "وظيفة عامة"],
}


def detect_domain_from_query(query: str) -> Optional[str]:
    """Detect legal domain from query keywords."""
    query_lower = query.strip()
    best_domain = None
    best_count = 0

    for domain, keywords in DOMAIN_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in query_lower)
        if count > best_count:
            best_count = count
            best_domain = domain

    return best_domain if best_count > 0 else None


def extract_year_filter(query: str) -> Optional[tuple]:
    """Extract year or year range from query."""
    # Exact year: "قانون 2004" or "لسنة 2004"
    year_match = re.search(r'(?:سنة|لسنة|عام)\s*(\d{4})', query)
    if year_match:
        year = int(year_match.group(1))
        return (year, year)

    # Year range: "من 2000 إلى 2020"
    range_match = re.search(r'من\s*(\d{4})\s*(?:إلى|حتى|لـ)\s*(\d{4})', query)
    if range_match:
        return (int(range_match.group(1)), int(range_match.group(2)))

    return None


def extract_law_name_filter(query: str) -> Optional[str]:
    """Extract specific law name from query."""
    # "قانون العمل" or "قانون الأسرة" etc.
    law_match = re.search(r'قانون\s+([\w\s]{2,30}?)(?:\s+رقم|\s+لسنة|\s+القطري|[،,\.]|$)', query)
    if law_match:
        return law_match.group(1).strip()
    return None


def apply_metadata_filters(
    chunks: list,
    query: str = "",
    filters: dict = None,
    auto_detect: bool = True,
) -> list:
    """
    Filter chunks by metadata.

    Args:
        chunks: RAG search results
        query: Original query (for auto-detection)
        filters: Explicit filters dict
        auto_detect: Auto-detect filters from query

    Returns:
        Filtered chunks (preserves order, boosts matching chunks)
    """
    if not chunks:
        return chunks

    # Build filters
    effective_filters = dict(filters or {})

    if auto_detect and query:
        # Auto-detect domain
        if "law_domain" not in effective_filters:
            domain = detect_domain_from_query(query)
            if domain:
                effective_filters["law_domain"] = domain

        # Auto-detect year
        if "year_range" not in effective_filters:
            year_range = extract_year_filter(query)
            if year_range:
                effective_filters["year_range"] = year_range

        # Auto-detect law name
        if "law_name_contains" not in effective_filters:
            law_name = extract_law_name_filter(query)
            if law_name:
                effective_filters["law_name_contains"] = law_name

    if not effective_filters:
        return chunks

    log.info("metadata_filter: applying filters %s", list(effective_filters.keys()))

    # Score each chunk based on filter match
    for chunk in chunks:
        boost = 0.0
        meta = chunk.get("metadata", {})
        law_name = chunk.get("law_name", "") or meta.get("law_name", "")
        law_year = chunk.get("law_year", 0) or meta.get("law_year", 0)

        # Domain filter
        if "law_domain" in effective_filters:
            domain = effective_filters["law_domain"]
            chunk_domain = chunk.get("domain", "") or meta.get("domain", "")
            if domain in chunk_domain or chunk_domain in domain:
                boost += 0.15
            elif domain in DOMAIN_KEYWORDS:
                # Check if law_name contains domain keywords
                kws = DOMAIN_KEYWORDS[domain]
                if any(kw in law_name for kw in kws):
                    boost += 0.10

        # Year filter
        if "year_range" in effective_filters and law_year:
            yr_min, yr_max = effective_filters["year_range"]
            try:
                y = int(law_year)
                if yr_min <= y <= yr_max:
                    boost += 0.10
                elif y < yr_min:
                    boost -= 0.05  # Older than requested
            except (ValueError, TypeError):
                pass

        # Law name filter
        if "law_name_contains" in effective_filters:
            target = effective_filters["law_name_contains"]
            if target in law_name:
                boost += 0.20

        # Apply boost to score
        orig_score = float(chunk.get("score", 0))
        chunk["metadata_boost"] = boost
        chunk["score"] = min(1.0, orig_score + boost)

    # Re-sort by new score
    chunks.sort(key=lambda c: float(c.get("score", 0)), reverse=True)

    filtered_count = sum(1 for c in chunks if c.get("metadata_boost", 0) > 0)
    log.info("metadata_filter: %d/%d chunks boosted", filtered_count, len(chunks))

    return chunks
