# -*- coding: utf-8 -*-
"""
IRA — Intelligent Requirement Amplifier.

PEAL ensures required stages run.
IRA ensures they run WITH SUFFICIENT DEPTH.

For a given query, IRA:
  1. Extracts structured semantic signals (comparison, classification
     dispute, decisive-factor question, drafting intent, multi-role
     situations).
  2. Amplifies the bare `PipelineRequirements` into a stricter policy:
        • min_hypotheses (MLRE must generate at least N)
        • must_generate_pivots (MLRE must yield pivot_conditions)
        • allowed_dlp_modes / forbidden_dlp_modes
        • allow_skeleton (fallback policy)
        • needs_multi_path / needs_dual_strategy
        • needs_pivot_output (text must surface pivot factor)

A PEAL check informed by IRA amplification will reject:
  • MLRE results with only 1 hypothesis when multi-path was required
  • DLP returning NOT_DRAFTABLE when drafting + multi-path were requested
  • Responses missing pivot content when a "ما الذي يحسم" question was asked
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from core.runtime.pre_execution_validator import (
    PipelineRequirements, PipelineState,
)


# ═════════════════════════════════════════════════════════════════
# Semantic signal extraction — structural, not keyword-only
# ═════════════════════════════════════════════════════════════════

# Disjunctive comparison (X أم Y)
_DISJUNCTIVE_RE = re.compile(
    r"([^\s؟?]{2,40})\s+أم\s+([^\s؟?]{2,40})"
)

# Strongest-path / decisive-factor triggers
_STRONGEST_TRIGGERS = (
    "ما الأقوى", "الأقوى", "المسار الأقوى",
    "التكييف الأقوى", "الرأي الراجح",
)

_DECISIVE_TRIGGERS = (
    "ما الذي يحسم", "ما يحسم", "ما الذي يرجح",
    "ما الذي يغيّر", "ما الذي يغيِّر", "ما الفيصل",
    "نقطة الحسم", "الدليل الحاسم", "ما الفاصل",
)

_CLASSIFICATION_DISPUTE_TRIGGERS = (
    "تكييف", "تكييفه", "وصف قانوني", "الوصف القانوني",
    "جزائي أم مدني", "مدني أم جزائي",
    "جنائي أم مدني", "مدني أم جنائي",
    "جنائي أم تجاري", "تجاري أم جنائي",
    "شراكة أم عمل", "عمل أم شراكة",
    "بيع أم هبة", "هبة أم بيع",
    "ضمان أم وفاء", "وفاء أم ضمان",
    "إيجار أم بيع", "بيع أم إيجار",
    "إرث أم هبة", "هبة أم إرث",
)

# Multi-role detection (e.g. "موظف + شريك", "زوجة وشريكة")
_ROLE_WORDS = {
    "employee":    ("موظف", "عامل"),
    "partner":     ("شريك", "شريكة"),
    "spouse":      ("زوج", "زوجة"),
    "heir":        ("وارث", "وريث"),
    "manager":     ("مدير", "إدارة"),
    "owner":       ("مالك", "صاحب العمل"),
    "creditor":    ("دائن"),
    "debtor":      ("مدين"),
    "guardian":    ("وصي", "ولي"),
    "contractor":  ("مقاول"),
    "agent":       ("وكيل"),
}

# Drafting intent markers (reuse from DLP with a minimal local list)
_DRAFTING_WORDS = (
    "اكتب لي مذكرة", "اكتب مذكرة", "صيغ لي",
    "صيغ مذكرة", "اكتب صحيفة", "اكتب نقاط",
    "مذكرة دفاع", "مذكرة رد", "صحيفة دعوى",
    "نقاط مرافعة",
)


@dataclass
class QuerySignals:
    """Structured features extracted from the query."""
    has_disjunction:             bool = False
    disjunction_pairs:           list[tuple[str, str]] = field(default_factory=list)
    asks_strongest:              bool = False
    asks_decisive_factor:        bool = False
    has_classification_dispute:  bool = False
    classification_dispute_text: str = ""
    has_drafting_intent:         bool = False
    roles_detected:              list[str] = field(default_factory=list)
    role_count:                  int = 0

    def to_dict(self) -> dict:
        return {
            "has_disjunction":             self.has_disjunction,
            "disjunction_pairs":           [list(p) for p in self.disjunction_pairs[:3]],
            "asks_strongest":              self.asks_strongest,
            "asks_decisive_factor":        self.asks_decisive_factor,
            "has_classification_dispute":  self.has_classification_dispute,
            "classification_dispute_text": self.classification_dispute_text[:60],
            "has_drafting_intent":         self.has_drafting_intent,
            "roles_detected":              self.roles_detected[:5],
            "role_count":                  self.role_count,
        }


def extract_query_signals(query: str) -> QuerySignals:
    """Parse the query for IRA-relevant semantic features."""
    sig = QuerySignals()
    if not query:
        return sig
    q = query

    # Disjunctions — "X أم Y"
    for m in _DISJUNCTIVE_RE.finditer(q):
        a, b = m.group(1).strip(), m.group(2).strip()
        if a and b and a != b:
            sig.has_disjunction = True
            sig.disjunction_pairs.append((a, b))

    # Strongest / decisive questions
    sig.asks_strongest = any(t in q for t in _STRONGEST_TRIGGERS)
    sig.asks_decisive_factor = any(t in q for t in _DECISIVE_TRIGGERS)

    # Classification dispute
    for marker in _CLASSIFICATION_DISPUTE_TRIGGERS:
        if marker in q:
            sig.has_classification_dispute = True
            sig.classification_dispute_text = marker
            break

    # Drafting intent
    sig.has_drafting_intent = any(t in q for t in _DRAFTING_WORDS)

    # Roles — count distinct role classes present in the query
    for role_key, words in _ROLE_WORDS.items():
        for w in (words if isinstance(words, tuple) else (words,)):
            if w and w in q:
                if role_key not in sig.roles_detected:
                    sig.roles_detected.append(role_key)
                break
    sig.role_count = len(sig.roles_detected)

    return sig


# ═════════════════════════════════════════════════════════════════
# Amplified requirements
# ═════════════════════════════════════════════════════════════════

def amplify_requirements(
    base: PipelineRequirements,
    signals: QuerySignals,
) -> PipelineRequirements:
    """Tighten a base PipelineRequirements object using IRA rules.

    Mutates and returns `base` (same object) so caller-side state is
    preserved. Adds amplified fields and adjusts the intent_tag.
    """
    # Ensure amplified fields exist on base (with safe defaults)
    if not hasattr(base, "min_hypotheses"):
        base.min_hypotheses = 0
    if not hasattr(base, "must_generate_pivots"):
        base.must_generate_pivots = False
    if not hasattr(base, "allowed_dlp_modes"):
        base.allowed_dlp_modes = set()
    if not hasattr(base, "forbidden_dlp_modes"):
        base.forbidden_dlp_modes = set()
    if not hasattr(base, "allow_skeleton"):
        base.allow_skeleton = True
    if not hasattr(base, "needs_multi_path"):
        base.needs_multi_path = False
    if not hasattr(base, "needs_pivot_output"):
        base.needs_pivot_output = False
    if not hasattr(base, "needs_dual_strategy"):
        base.needs_dual_strategy = False
    if not hasattr(base, "amplifications"):
        base.amplifications = []

    # ── Rule 1: Disjunction / classification dispute → multi-path ──
    if signals.has_disjunction or signals.has_classification_dispute:
        base.needs_mlre = True
        base.needs_multi_path = True
        base.min_hypotheses = max(base.min_hypotheses, 2)
        base.must_generate_pivots = True
        base.needs_pivot_output = True
        base.amplifications.append("multi_path_on_disjunction")

    # ── Rule 2: Decisive-factor question → pivots required in output ──
    if signals.asks_decisive_factor:
        base.needs_mlre = True
        base.needs_pivot_output = True
        base.must_generate_pivots = True
        base.amplifications.append("decisive_factor_requires_pivots")

    # ── Rule 3: "الأقوى" request → MLRE + pivots + alternative path ──
    if signals.asks_strongest:
        base.needs_mlre = True
        base.min_hypotheses = max(base.min_hypotheses, 2)
        base.must_generate_pivots = True
        base.amplifications.append("strongest_requires_alternatives")

    # ── Rule 4: Drafting + multi-path → forbid NOT_DRAFTABLE ──
    if signals.has_drafting_intent and (
        signals.has_disjunction
        or signals.has_classification_dispute
        or signals.asks_strongest
    ):
        base.needs_dlp = True
        base.needs_multi_path = True
        base.needs_dual_strategy = True
        base.min_hypotheses = max(base.min_hypotheses, 2)
        base.allowed_dlp_modes = {
            "conditional_draft", "conditional",
            "dual_strategy_draft", "dual_strategy",
            "skeleton_draft",
        }
        base.forbidden_dlp_modes = {
            "not_draftable_yet",
            "not_draftable_mlre",
        }
        base.amplifications.append("drafting_multipath_forbids_not_draftable")

    # ── Rule 5: Drafting alone → allow skeleton as last-resort; forbid
    # explicit NOT_DRAFTABLE when ANY graph structure can exist ──
    if signals.has_drafting_intent:
        base.needs_dlp = True
        base.allow_skeleton = True
        base.amplifications.append("drafting_allows_skeleton")

    # ── Rule 6: Multiple roles → multi-path reasoning ──
    if signals.role_count >= 2:
        base.needs_mlre = True
        base.needs_multi_path = True
        base.min_hypotheses = max(base.min_hypotheses, 2)
        base.must_generate_pivots = True
        base.amplifications.append(f"multi_role:{signals.role_count}")

    # Update intent_tag to reflect amplification, without overriding
    # drafting which remains the top-level tag.
    if signals.has_drafting_intent and base.needs_multi_path:
        base.intent_tag = "drafting_multi_path"
    elif base.needs_multi_path and base.intent_tag != "drafting":
        base.intent_tag = "multi_path_analysis"

    return base


# ═════════════════════════════════════════════════════════════════
# State-extension — pivots / decisive-tests counts
# ═════════════════════════════════════════════════════════════════

def extend_state_with_amplified_signals(state: PipelineState,
                                             mlre_trace: dict) -> PipelineState:
    """Fill the amplified-signal state fields from an MLRE trace."""
    # Ensure fields exist
    if not hasattr(state, "pivots_count"):
        state.pivots_count = 0
    if not hasattr(state, "decisive_tests_count"):
        state.decisive_tests_count = 0
    if not hasattr(state, "pivot_in_output"):
        state.pivot_in_output = False

    trace = mlre_trace or {}
    reality = trace.get("reality") or {}
    state.pivots_count = len(reality.get("pivot_conditions", []) or [])
    state.decisive_tests_count = len(reality.get("decisive_tests", []) or [])
    return state


# ═════════════════════════════════════════════════════════════════
# Enhanced validator — consumes amplified requirements + state
# ═════════════════════════════════════════════════════════════════

def validate_amplified(
    state: PipelineState,
    req: PipelineRequirements,
    *, text: str = "",
    dlp_mode: str = "",
) -> list[str]:
    """Return the list of IRA-specific violations. Empty list = clean."""
    violations: list[str] = []

    # Hypothesis floor
    min_h = getattr(req, "min_hypotheses", 0)
    if getattr(req, "needs_multi_path", False) and min_h > 0:
        if state.survivors_count < min_h:
            violations.append(
                f"insufficient_hypotheses:need>={min_h}:got={state.survivors_count}"
            )

    # Pivots must be generated
    if getattr(req, "must_generate_pivots", False):
        p = getattr(state, "pivots_count", 0) or 0
        dt = getattr(state, "decisive_tests_count", 0) or 0
        if p == 0 and dt == 0:
            violations.append("pivots_not_generated")

    # Pivot must surface in output text
    if getattr(req, "needs_pivot_output", False) and text:
        pivot_markers = (
            "ينتقل المسار",          # MLRE pivot section
            "ما يحسم",                # decisive
            "ما يحدّد",
            "المسار البديل",
            "التكييف البديل",
            "متى ينتقل",
            "على سبيل الاحتياط",
        )
        if not any(m in text for m in pivot_markers):
            violations.append("pivot_not_reflected_in_output")

    # DLP mode constraints
    allowed = getattr(req, "allowed_dlp_modes", None) or set()
    forbidden = getattr(req, "forbidden_dlp_modes", None) or set()
    mode = (dlp_mode or getattr(state, "dlp_mode", "") or "")
    if forbidden and mode in forbidden:
        violations.append(f"dlp_mode_forbidden:{mode}")
    if allowed and mode and mode not in allowed:
        # Allowed-list is a whitelist — if set and mode is outside it, block
        violations.append(f"dlp_mode_not_in_allowed:{mode}")

    # Dual strategy expected but skeleton/single_path returned
    if getattr(req, "needs_dual_strategy", False) and mode:
        if mode in ("single_path", "full_draft"):
            # Acceptable only if survivors < 2 (data truly doesn't support dual)
            if state.survivors_count >= 2:
                violations.append("dual_expected_got_single")

    return violations
