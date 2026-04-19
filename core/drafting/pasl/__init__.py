# -*- coding: utf-8 -*-
"""
Professional Advocate Style Layer (PASL).

Runs AFTER MQE composes a memo and BEFORE the final output. Lifts the
memo from "correct and organized" to "convincing in the voice of a
senior advocate" — without touching facts, statute, or argument spine.

Public API:
    from core.drafting.pasl import (
        polish,
        PASLResult,
        StyleScore, score_style, STYLE_FLOOR, STRONG_STYLE_CEILING,
    )
"""
from core.drafting.pasl.section_parser import (
    parse_memo, rebuild_memo, ParsedMemo, MemoSegment,
    section_count, citation_count, fact_bullet_count,
)
from core.drafting.pasl.style_scorer import (
    StyleScore, score_style, STYLE_FLOOR, STRONG_STYLE_CEILING,
)
from core.drafting.pasl.orchestrator import (
    polish, PASLResult,
)

__all__ = [
    # Section parsing
    "parse_memo", "rebuild_memo", "ParsedMemo", "MemoSegment",
    "section_count", "citation_count", "fact_bullet_count",
    # Scoring
    "StyleScore", "score_style", "STYLE_FLOOR", "STRONG_STYLE_CEILING",
    # Orchestrator
    "polish", "PASLResult",
]
