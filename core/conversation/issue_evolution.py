# -*- coding: utf-8 -*-
"""
Focus Shift Detector + Issue Evolution.

Given (current state, follow-up verdict) → decide:
  - which focus the NEW answer must hit
  - which issues are carried forward
  - which are dropped
  - what additional medium/sub-issue is added
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.conversation.state_engine import LegalConversationState
from core.conversation.followup_intent import FollowUpIntent, FollowUpVerdict


class FocusShift(str, Enum):
    NONE             = "none"
    OFFENSE_TO_PUNISHMENT    = "offense_to_punishment"
    OFFENSE_TO_PROOF         = "offense_to_proof"
    OFFENSE_TO_DEFENSE       = "offense_to_defense"
    OFFENSE_TO_PROCEDURE     = "offense_to_procedure"
    PUNISHMENT_TO_DEFENSE    = "punishment_to_defense"
    PUNISHMENT_TO_PROOF      = "punishment_to_proof"
    MEDIUM_ADDED             = "medium_added"
    FACT_CONDITIONAL_ADDED   = "fact_conditional_added"
    REPHRASE_NO_SHIFT        = "rephrase_no_shift"
    NEW_CASE                 = "new_case"


@dataclass
class FocusShiftVerdict:
    shift:            FocusShift       = FocusShift.NONE
    new_focus:        str              = ""
    carry_domain:     bool             = False
    carry_offense:    bool             = False
    carry_facts:      bool             = True
    add_medium:       str              = ""
    add_issue_tags:   list[str]        = field(default_factory=list)
    drop_issue_tags:  list[str]        = field(default_factory=list)
    answer_mode:      str              = "direct_short"   # direct_short | analysis
    reason:           str              = ""

    def to_trace(self) -> dict:
        return {
            "shift":         self.shift.value,
            "new_focus":     self.new_focus,
            "carry_domain":  self.carry_domain,
            "carry_offense": self.carry_offense,
            "carry_facts":   self.carry_facts,
            "add_medium":    self.add_medium,
            "add_issues":    self.add_issue_tags,
            "drop_issues":   self.drop_issue_tags,
            "answer_mode":   self.answer_mode,
            "reason":        self.reason,
        }


def detect_focus_shift(
    state: Optional[LegalConversationState],
    verdict: FollowUpVerdict,
) -> FocusShiftVerdict:
    """Derive focus shift from state + follow-up intent."""
    out = FocusShiftVerdict()

    if verdict.intent == FollowUpIntent.NO_PRIOR_CONTEXT:
        out.shift = FocusShift.NONE
        out.reason = "first_turn"
        return out

    if verdict.intent == FollowUpIntent.NEW_CASE:
        out.shift = FocusShift.NEW_CASE
        out.carry_domain = False
        out.carry_offense = False
        out.carry_facts = False
        out.reason = "new_case_detected"
        return out

    # From here on: domain carries over
    out.carry_domain = True
    out.carry_offense = True
    out.carry_facts = True

    last_focus = (state.last_focus if state else "") or "offense"

    if verdict.intent == FollowUpIntent.DEFENSE_SHIFT:
        out.new_focus = "defense"
        out.answer_mode = "analysis"
        if last_focus in ("offense", ""):
            out.shift = FocusShift.OFFENSE_TO_DEFENSE
        elif last_focus == "punishment":
            out.shift = FocusShift.PUNISHMENT_TO_DEFENSE
        else:
            out.shift = FocusShift.OFFENSE_TO_DEFENSE
        out.add_issue_tags = ["defense_available", "admissibility", "burden_failure"]
        out.drop_issue_tags = ["punishment_range"]
        out.reason = "shift_to_defense_or_acquittal"
        return out

    if verdict.intent == FollowUpIntent.EVIDENCE_SHIFT:
        out.new_focus = "proof"
        out.answer_mode = "analysis"
        if last_focus == "punishment":
            out.shift = FocusShift.PUNISHMENT_TO_PROOF
        else:
            out.shift = FocusShift.OFFENSE_TO_PROOF
        out.add_issue_tags = ["admissibility", "burden_of_proof",
                                "electronic_evidence"]
        out.reason = "shift_to_evidence_questions"
        return out

    if verdict.intent == FollowUpIntent.PROCEDURAL_SHIFT:
        out.new_focus = "procedure"
        out.answer_mode = "direct_short"
        out.shift = FocusShift.OFFENSE_TO_PROCEDURE
        out.add_issue_tags = ["jurisdiction", "filing_procedure"]
        out.reason = "shift_to_procedural"
        return out

    if verdict.intent == FollowUpIntent.REMEDY_SHIFT:
        out.new_focus = "punishment"
        out.answer_mode = "direct_short"
        out.shift = FocusShift.OFFENSE_TO_PUNISHMENT
        out.add_issue_tags = ["punishment_range"]
        out.reason = "shift_to_remedy"
        return out

    if verdict.intent == FollowUpIntent.MEDIUM_CHANGE:
        out.new_focus = "medium_application"
        out.answer_mode = "direct_short"
        out.shift = FocusShift.MEDIUM_ADDED
        out.add_medium = verdict.detected_medium
        # Digital medium triggers electronic-law overlap
        if "digital" in (verdict.detected_medium or ""):
            out.add_issue_tags = ["electronic_publication", "cyber_law_overlap"]
        out.reason = f"medium_change:{verdict.detected_medium}"
        return out

    if verdict.intent == FollowUpIntent.FACT_CHANGE:
        out.new_focus = "conditional_fact_variant"
        out.answer_mode = "analysis"
        out.shift = FocusShift.FACT_CONDITIONAL_ADDED
        # Keep facts but note the conditional overlay
        out.reason = "conditional_fact_added"
        return out

    if verdict.intent == FollowUpIntent.SAME_ISSUE_REPHRASE:
        out.new_focus = last_focus or "offense"
        out.shift = FocusShift.REPHRASE_NO_SHIFT
        out.reason = "rephrase_same_intent"
        return out

    if verdict.intent == FollowUpIntent.SAME_ISSUE_NARROWING:
        out.new_focus = last_focus or "offense"
        out.shift = FocusShift.NONE
        out.reason = "narrowing_within_issue"
        return out

    if verdict.intent == FollowUpIntent.CLARIFICATION_ONLY:
        out.new_focus = last_focus or "offense"
        out.reason = "too_short_for_shift"
        return out

    out.reason = "default_fallthrough"
    return out
