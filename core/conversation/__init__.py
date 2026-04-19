# -*- coding: utf-8 -*-
"""
Conversational Legal Intelligence (CLI).

Public API:
    from core.conversation import (
        LegalConversationState, get_state_engine,
        FollowUpIntent, classify_followup,
        FocusShift, detect_focus_shift,
        rewrite_for_context, ConversationTurnResult,
    )
"""
from core.conversation.state_engine import (
    LegalConversationState, get_state_engine,
    LegalConversationStateEngine,
)
from core.conversation.followup_intent import (
    FollowUpIntent, classify_followup, FollowUpVerdict,
)
from core.conversation.issue_evolution import (
    FocusShift, detect_focus_shift, FocusShiftVerdict,
)
from core.conversation.contextual_rewriter import (
    rewrite_for_context, ConversationTurnResult,
)

__all__ = [
    "LegalConversationState", "get_state_engine", "LegalConversationStateEngine",
    "FollowUpIntent", "classify_followup", "FollowUpVerdict",
    "FocusShift", "detect_focus_shift", "FocusShiftVerdict",
    "rewrite_for_context", "ConversationTurnResult",
]
