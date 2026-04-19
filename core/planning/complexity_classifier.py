# -*- coding: utf-8 -*-
"""
Complexity Classifier — determines query difficulty and required path.
Deterministic (no LLM needed).
"""
import re, logging
from core.self_correction.schemas import QueryComplexity

log = logging.getLogger("planning")

_SIMPLE_ROUTES = {"greeting", "filler", "thanks", "self_info"}
_TOOL_ROUTES = {"article_text", "table"}

_COMPOUND_RE = re.compile(r'\s+و(?:هل|كيف|متى|ما|كم)\s+', re.UNICODE)
_MULTI_TOPIC_KEYWORDS = {
    "حضانة", "نفقة", "طلاق", "فصل", "مكافأة", "سرقة",
    "مخدرات", "إيجار", "شركات", "تعويض", "ميراث",
}
_CALC_KEYWORDS = ["احسب", "حاسب", "كم مكافأة", "كم مكافاة", "كم تعويض", "مكافأة نهاية", "نهاية خدمة"]


def classify_complexity(query: str, brain_route: str = "", has_tools: bool = False) -> QueryComplexity:
    """Classify query complexity for path routing."""
    q = query.lower()
    words = q.split()

    # Simple (greeting, filler)
    if brain_route in _SIMPLE_ROUTES or len(words) <= 3:
        return QueryComplexity.SIMPLE

    # Tool-required
    if brain_route in _TOOL_ROUTES or has_tools or any(kw in q for kw in _CALC_KEYWORDS):
        return QueryComplexity.TOOL_REQUIRED

    # Compound question detection
    compound_parts = _COMPOUND_RE.split(query)
    topics_found = sum(1 for kw in _MULTI_TOPIC_KEYWORDS if kw in q)

    if len(compound_parts) > 1 or topics_found >= 2:
        if has_tools or any(kw in q for kw in _CALC_KEYWORDS):
            return QueryComplexity.COMPLEX
        return QueryComplexity.LEGAL_MULTI

    # Long detailed question
    if len(words) > 25:
        return QueryComplexity.LEGAL_MULTI

    # Default legal single
    return QueryComplexity.LEGAL_SINGLE
