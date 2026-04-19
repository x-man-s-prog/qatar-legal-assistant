# -*- coding: utf-8 -*-
"""
UX Intelligence Layer.

Sits ABOVE the analytical pipeline. Does not bypass fail-closed or
canonical grounding. Adds:
  • missing-data detection (what's needed for a complete answer)
  • smart question generation (issue-tied, deduplicated, prioritized)
  • response modes (READY / PARTIAL / NOT_READY)
  • user-intent detection (analysis/action/drafting/assessment/chances)
  • anti-frustration guards (≤3 questions, no repetition)

Public API:
    from core.ux import (
        MissingDataReport, analyze_gaps,
        LegalQuestion, generate_questions,
        UserIntent, detect_user_intent,
        ResponseMode, assess_readiness,
        build_ux_enhancement,
    )
"""
from core.ux.missing_data import (
    MissingDataReport, GapLevel, IssueGap, analyze_gaps,
)
from core.ux.question_generator import (
    LegalQuestion, generate_questions,
)
from core.ux.user_intent import (
    UserIntent, detect_user_intent,
)
from core.ux.response_mode import (
    ResponseMode, assess_readiness,
)
from core.ux.orchestrator import (
    UXEnhancement, build_ux_enhancement,
)

__all__ = [
    "MissingDataReport", "GapLevel", "IssueGap", "analyze_gaps",
    "LegalQuestion", "generate_questions",
    "UserIntent", "detect_user_intent",
    "ResponseMode", "assess_readiness",
    "UXEnhancement", "build_ux_enhancement",
]
