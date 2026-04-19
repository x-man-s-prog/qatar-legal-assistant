# -*- coding: utf-8 -*-
"""
AIB — Adaptive Intelligence Balancer.

REUP → protects OUTPUT.
PEAL → protects THINKING (stages ran).
IRA  → protects THINKING DEPTH (stages ran with enough depth).
AIB  → protects ADAPTIVE INTELLIGENCE (never collapses when depth
       is structurally unavailable).

Philosophy:
  IRA is strict. When the query demands multi-path but MLRE can only
  produce one real hypothesis, IRA (correctly) refuses. But refusal is
  the wrong final outcome — we should DOWNGRADE gracefully, not fail.

  AIB intercepts IRA violations and chooses an adaptive mode:

    🟢 FULL_MULTI       — 2+ strong hypotheses (no adaptation needed)
    🟡 PARTIAL_MULTI    — 1 strong + 1 weak (show both, disclose asymmetry)
    🔵 SINGLE_ADAPTIVE  — only one path possible (explain WHY, what could
                           change it, weakness points)
    🟣 SKELETON         — no decisive path (show structure + gaps)

Hard rule: AIB NEVER returns `internal_failure` for a depth shortage.
If every adaptive path fails to materialize text, a minimal
SINGLE_ADAPTIVE stub is emitted that still carries reasoning +
limitation + what could change the outcome.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.runtime.pre_execution_validator import (
    PipelineRequirements, PipelineState, extract_state_from_artifacts,
)


class AdaptationMode(str, Enum):
    FULL_MULTI       = "full_multi"
    PARTIAL_MULTI    = "partial_multi"
    SINGLE_ADAPTIVE  = "single_adaptive"
    SKELETON         = "skeleton"


# ═════════════════════════════════════════════════════════════════
# Result type
# ═════════════════════════════════════════════════════════════════

@dataclass
class AdaptationResult:
    mode:                  AdaptationMode
    text:                  str = ""
    adaptation_notes:      list[str] = field(default_factory=list)
    expansion_attempted:   bool = False
    original_violations:   list[str] = field(default_factory=list)
    effective_requirements: Optional[PipelineRequirements] = None
    effective_state:       Optional[PipelineState] = None
    adapted:               bool = True

    def to_dict(self) -> dict:
        return {
            "mode":                self.mode.value,
            "adaptation_notes":    self.adaptation_notes[:5],
            "expansion_attempted": self.expansion_attempted,
            "original_violations": self.original_violations[:6],
            "adapted":             self.adapted,
            "effective_requirements":
                (self.effective_requirements.to_dict()
                 if self.effective_requirements else {}),
            "effective_state":
                (self.effective_state.to_dict()
                 if self.effective_state else {}),
        }


# ═════════════════════════════════════════════════════════════════
# Violation classification
# ═════════════════════════════════════════════════════════════════

IRA_VIOLATION_TAGS = (
    "ira:insufficient_hypotheses",
    "ira:pivots_not_generated",
    "ira:pivot_not_reflected_in_output",
    "ira:dual_expected_got_single",
    "ira:dlp_mode_forbidden",
    "ira:dlp_mode_not_in_allowed",
)


def is_adaptable_violation_set(violations: list[str]) -> bool:
    """AIB only rescues IRA-type violations. PEAL baselines
    (domain/graph/MLRE-missing) stay hard-fail."""
    if not violations:
        return False
    for v in violations:
        if any(v.startswith(tag) for tag in IRA_VIOLATION_TAGS):
            continue
        # Any non-IRA violation present → not adaptable
        return False
    return True


# ═════════════════════════════════════════════════════════════════
# Mode selection
# ═════════════════════════════════════════════════════════════════

def classify_adaptation_mode(
    state: PipelineState,
    requirements: PipelineRequirements,
    violations: list[str],
) -> AdaptationMode:
    """Pick the right adaptive mode given what we have."""
    survivors = state.survivors_count or 0
    pivots    = state.pivots_count or 0
    decisive  = state.decisive_tests_count or 0

    # Truly empty state → skeleton (no real reasoning produced)
    if survivors <= 0 and not state.mlre_executed:
        return AdaptationMode.SKELETON

    # Only 1 survivor with no pivots → SINGLE_ADAPTIVE
    if survivors <= 1 and pivots == 0 and decisive == 0:
        return AdaptationMode.SINGLE_ADAPTIVE

    # 1 strong + 1 weak (2 survivors) → PARTIAL_MULTI
    if survivors == 2:
        return AdaptationMode.PARTIAL_MULTI

    # Multi but not meeting required min_hypotheses → still FULL_MULTI
    # (MLRE had 2+ survivors, just below what IRA asked for)
    if survivors >= 2:
        return AdaptationMode.FULL_MULTI

    # Fallback
    return AdaptationMode.SKELETON


# ═════════════════════════════════════════════════════════════════
# Text composers for each adaptive mode
# ═════════════════════════════════════════════════════════════════

def _primary_path(mlre_trace: dict) -> dict:
    """Extract the primary path dict from an MLRE trace."""
    reality = (mlre_trace or {}).get("reality") or {}
    paths = reality.get("paths") or []
    return paths[0] if paths else {}


def _alt_path(mlre_trace: dict) -> dict:
    reality = (mlre_trace or {}).get("reality") or {}
    paths = reality.get("paths") or []
    return paths[1] if len(paths) >= 2 else {}


def _strength_phrase(score: float) -> str:
    try:
        s = float(score)
    except Exception:
        return "معتبر"
    if s >= 0.65:
        return "قوي"
    if s >= 0.45:
        return "معتبر"
    if s >= 0.30:
        return "محتمل"
    return "ضعيف"


# ── SINGLE_ADAPTIVE ──

def compose_single_adaptive(
    mlre_trace: dict,
    query: str = "",
) -> str:
    """Compose a SINGLE_ADAPTIVE response.

    Required blocks:
      1. Primary (only) path
      2. Why no real alternative was found
      3. What could CHANGE this (facts that would unlock an alternative)
      4. Weakness points on the primary
      5. Limitation disclosure
    """
    p = _primary_path(mlre_trace)
    theory = (p.get("legal_theory") or "—").strip()
    weakest = (p.get("weakest_point") or "").strip()
    must_prove = list(p.get("what_must_be_proven") or [])[:3]
    score = p.get("score", 0.0)
    reality = (mlre_trace or {}).get("reality") or {}
    rejected_reasons = list(reality.get("rejection_reasons") or [])[:2]

    lines: list[str] = []
    # 1. Primary path
    lines.append(
        f"**التكييف المرجَّح (المسار الوحيد المتاح حالياً):** {theory} — "
        f"موقف {_strength_phrase(score)}."
    )
    lines.append("")

    # 2. What must be proven
    if must_prove:
        lines.append("**ما يلزم إثباته لتثبيت هذا المسار:**")
        for mp in must_prove:
            lines.append(f"• {mp}")
        lines.append("")

    # 3. Why no real alternative
    lines.append("**لماذا لا يوجد تكييف بديل معتبر:**")
    if rejected_reasons:
        lines.append(
            "استُبعدت الفرضيات الأخرى بعد تقييم مبدئي — ولم يصمد منها "
            "ما يرقى إلى مسار قانوني مكتمل."
        )
    else:
        lines.append(
            "لم يتوفر في الوقائع أو الأدلة ما يُغذّي تكييفاً موازياً "
            "بدرجة كافية لمنافسة المسار المذكور أعلاه."
        )
    lines.append("")

    # 4. What could change it
    lines.append("**ما الذي قد يخلق تكييفاً بديلاً مستقبلاً:**")
    change_triggers = _derive_change_triggers(mlre_trace, query)
    if change_triggers:
        for t in change_triggers[:3]:
            lines.append(f"• {t}")
    else:
        lines.append(
            "• ظهور مراسلات أو مستندات تغيّر طبيعة التصرف."
        )
        lines.append(
            "• اعتراف أحد الأطراف بوقائع جديدة جوهرية."
        )
    lines.append("")

    # 5. Weakness point
    if weakest:
        lines.append(f"**أخطر نقطة ضعف على هذا المسار:** {weakest}.")
        lines.append("")

    # 6. Limitation disclosure
    lines.append(
        "⚠️ هذا التحليل قائم على مسار واحد فقط بحسب المعطيات الحالية. "
        "عند توفر معطيات جديدة قد يظهر تكييف بديل يستدعي إعادة التقدير."
    )
    return "\n".join(lines).rstrip() + "\n"


def _derive_change_triggers(mlre_trace: dict, query: str) -> list[str]:
    """Heuristic triggers that would flip the analysis."""
    out: list[str] = []
    reality = (mlre_trace or {}).get("reality") or {}
    # Decisive tests double as "what would clinch/flip it"
    for t in (reality.get("decisive_tests") or [])[:3]:
        if t and t not in out:
            out.append(t)
    for p in (reality.get("pivot_conditions") or [])[:2]:
        if p and p not in out:
            out.append(p)
    return out


# ── PARTIAL_MULTI ──

def compose_partial_multi(mlre_trace: dict, query: str = "") -> str:
    """Primary + weaker secondary + explicit asymmetry disclosure."""
    p = _primary_path(mlre_trace)
    a = _alt_path(mlre_trace)
    theory_p = (p.get("legal_theory") or "—").strip()
    theory_a = (a.get("legal_theory") or "—").strip()
    score_p = p.get("score", 0.0)
    score_a = a.get("score", 0.0)
    weak_p = (p.get("weakest_point") or "").strip()
    weak_a = (a.get("weakest_point") or "").strip()

    reality = (mlre_trace or {}).get("reality") or {}
    pivots = list(reality.get("pivot_conditions") or [])[:2]
    decisive = list(reality.get("decisive_tests") or [])[:3]

    lines: list[str] = []
    # Primary
    lines.append(
        f"**التكييف المرجَّح:** {theory_p} — موقف {_strength_phrase(score_p)}."
    )
    if weak_p:
        lines.append(f"• أخطر نقطة ضعف: {weak_p}.")
    lines.append("")

    # Secondary (weaker)
    lines.append(
        f"**تكييف بديل (أقل قوة):** {theory_a} — موقف {_strength_phrase(score_a)}."
    )
    if weak_a:
        lines.append(f"• نقطة ضعفه: {weak_a}.")
    lines.append("")

    # Asymmetry disclosure
    lines.append(
        "**ملاحظة على التوازن بين المسارين:**"
    )
    lines.append(
        f"المسار الأساسي أقوى من البديل بدرجة معتبرة. "
        f"يُقدَّم البديل على سبيل الاحتياط فقط، ولا يُعتمد إلا إذا توفرت "
        f"معطيات تُضعف المسار الأساسي."
    )
    lines.append("")

    # Pivot + decisive
    if pivots:
        lines.append("**متى قد ينتقل الترجيح إلى البديل:**")
        for pc in pivots:
            lines.append(f"• {pc}")
        lines.append("")
    if decisive:
        lines.append("**ما قد يحسم المسألة:**")
        for d in decisive:
            lines.append(f"• {d}")
        lines.append("")

    lines.append(
        "⚠️ هذا التحليل مرن بحسب ما يتكشف من وقائع وأدلة، "
        "والمسار الأساسي هو المعتمد ما لم يظهر ما يُغيّره."
    )
    return "\n".join(lines).rstrip() + "\n"


# ── SKELETON (structure only) ──

def compose_skeleton_adaptive(mlre_trace: dict, query: str = "") -> str:
    """Preliminary structural exposition — no ranking claimed."""
    reality = (mlre_trace or {}).get("reality") or {}
    paths = list(reality.get("paths") or [])

    lines: list[str] = [
        "**عرض أولي للتكييفات المحتملة (صياغة تحليلية غير حاسمة):**",
        "",
    ]
    if paths:
        lines.append("**المسارات المطروحة:**")
        for i, p in enumerate(paths[:3], 1):
            theory = (p.get("legal_theory") or "—").strip()
            lines.append(f"({i}) {theory}")
        lines.append("")
    else:
        lines.append(
            "الهيكل القانوني متاح مبدئياً لكن لا يمكن الجزم بمسار "
            "بعينه قبل استكمال المعطيات."
        )
        lines.append("")

    decisive = list(reality.get("decisive_tests") or [])[:3]
    if decisive:
        lines.append("**ما يُحسم به الترجيح عند توفره:**")
        for d in decisive:
            lines.append(f"• {d}")
        lines.append("")

    lines.append(
        "⚠️ هذا عرض أولي غير جازم، ويُستكمل بمجرد توفر عناصر قانونية "
        "أو واقعية إضافية."
    )
    return "\n".join(lines).rstrip() + "\n"


# ═════════════════════════════════════════════════════════════════
# Requirements downgrade — so the ADAPTED artifacts pass the gate
# ═════════════════════════════════════════════════════════════════

def downgrade_requirements(
    original: PipelineRequirements,
    state: PipelineState,
    mode: AdaptationMode,
) -> PipelineRequirements:
    """Return a RELAXED copy of the requirements reflecting the adaptation.

    The adapted output satisfies softer requirements, but still
    preserves baseline PEAL (domain / issue_graph / MLRE ran).
    """
    req = copy.deepcopy(original)
    # Relax the depth flags that triggered the IRA failure
    req.min_hypotheses = min(req.min_hypotheses, max(1, state.survivors_count))
    if mode in (AdaptationMode.SINGLE_ADAPTIVE, AdaptationMode.SKELETON):
        req.needs_multi_path = False
        req.needs_dual_strategy = False
        req.must_generate_pivots = False
        req.needs_pivot_output = False
    elif mode == AdaptationMode.PARTIAL_MULTI:
        req.needs_dual_strategy = False   # partial is not dual
        # pivots/decisive stay required only if we actually have them
        if state.pivots_count == 0 and state.decisive_tests_count == 0:
            req.must_generate_pivots = False
            req.needs_pivot_output = False
    # Track adaptation
    if not hasattr(req, "amplifications"):
        req.amplifications = []
    req.amplifications.append(f"aib_downgrade:{mode.value}")
    return req


# ═════════════════════════════════════════════════════════════════
# MLRE expansion (STEP 1 of the decision tree)
# ═════════════════════════════════════════════════════════════════

def try_mlre_expansion(
    query: str,
    facts: Optional[list[str]] = None,
) -> Optional[dict]:
    """Re-run MLRE in exploratory mode: more hypotheses, looser thresholds.

    Returns the new MLRE trace dict if expansion produced ≥ 2 survivors,
    else None.
    """
    try:
        from core.mlre import run_mlre
    except Exception:
        return None
    try:
        expanded = run_mlre(
            query=query,
            facts=list(facts or [query[:300]]),
            max_hypotheses=12,   # wider set (default 8)
            max_survivors=4,     # keep more (default 3)
        )
    except Exception:
        return None
    survivors = list(getattr(expanded, "survivors", []) or [])
    if len(survivors) < 2:
        return None
    try:
        return expanded.to_trace()
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════
# The adaptive rescue entry point
# ═════════════════════════════════════════════════════════════════

def adapt(
    artifacts,
    violations: list[str],
    *, query: str = "",
    facts: Optional[list[str]] = None,
) -> AdaptationResult:
    """Given an IRA-violated artifacts bundle, produce an adaptive
    response. NEVER raises; always returns a populated AdaptationResult."""
    # Step 1 — try to EXPAND by re-running MLRE in exploratory mode
    expanded_trace: Optional[dict] = None
    if any(v.startswith("ira:insufficient_hypotheses") for v in violations):
        expanded_trace = try_mlre_expansion(query, facts=facts)

    mlre_trace = expanded_trace or dict(getattr(artifacts, "mlre_trace", {}) or {})

    # Step 2 — re-extract state from the (possibly expanded) trace
    # by temporarily swapping the artifacts.mlre_trace
    original_trace = getattr(artifacts, "mlre_trace", {}) or {}
    try:
        artifacts.mlre_trace = mlre_trace
        state = extract_state_from_artifacts(artifacts)
    finally:
        artifacts.mlre_trace = original_trace

    # Step 3 — pick the adaptive mode
    requirements = _rehydrate_requirements(
        getattr(artifacts, "peal_requirements", {}) or {},
    )
    mode = classify_adaptation_mode(state, requirements, violations)

    # Step 4 — compose the adaptive text
    if mode == AdaptationMode.FULL_MULTI:
        # Expansion succeeded — the text composer can be the PARTIAL_MULTI
        # formatter (since it handles primary + secondary uniformly)
        text = compose_partial_multi(mlre_trace, query)
    elif mode == AdaptationMode.PARTIAL_MULTI:
        text = compose_partial_multi(mlre_trace, query)
    elif mode == AdaptationMode.SINGLE_ADAPTIVE:
        text = compose_single_adaptive(mlre_trace, query)
    else:  # SKELETON
        text = compose_skeleton_adaptive(mlre_trace, query)

    # Step 5 — downgrade the requirements so the adapted artifact passes
    effective_req = downgrade_requirements(requirements, state, mode)

    result = AdaptationResult(
        mode=mode,
        text=text,
        adaptation_notes=[],
        expansion_attempted=(expanded_trace is not None
                             or any(v.startswith("ira:insufficient_hypotheses")
                                       for v in violations)),
        original_violations=list(violations),
        effective_requirements=effective_req,
        effective_state=state,
    )
    if expanded_trace is not None:
        result.adaptation_notes.append("expansion_succeeded")
    else:
        result.adaptation_notes.append(f"mode_downgraded:{mode.value}")
    return result


def _rehydrate_requirements(d: dict) -> PipelineRequirements:
    req = PipelineRequirements(
        needs_domain=d.get("needs_domain", True),
        needs_issue_graph=d.get("needs_issue_graph", True),
        needs_mlre=d.get("needs_mlre", False),
        needs_dlp=d.get("needs_dlp", False),
        needs_canonical=d.get("needs_canonical", True),
        intent_tag=d.get("intent_tag", ""),
        trigger_reasons=list(d.get("trigger_reasons", []) or []),
    )
    req.min_hypotheses       = d.get("min_hypotheses", 0)
    req.must_generate_pivots = d.get("must_generate_pivots", False)
    req.needs_multi_path     = d.get("needs_multi_path", False)
    req.needs_pivot_output   = d.get("needs_pivot_output", False)
    req.needs_dual_strategy  = d.get("needs_dual_strategy", False)
    req.allowed_dlp_modes    = set(d.get("allowed_dlp_modes", []) or [])
    req.forbidden_dlp_modes  = set(d.get("forbidden_dlp_modes", []) or [])
    req.allow_skeleton       = d.get("allow_skeleton", True)
    req.amplifications       = list(d.get("amplifications", []) or [])
    return req
