# -*- coding: utf-8 -*-
"""
REUP + PEAL — Pre-Execution Authority Lock.

REUP protects OUTPUT (nothing unclean reaches the user).
PEAL protects THINKING (nothing is emitted unless the required
reasoning stages actually ran).

For a given `(query, intent)`:
  • `detect_requirements()` decides WHICH stages are mandatory:
      - domain_resolved       (always required for legal queries)
      - issue_graph_built     (required for legal queries)
      - mlre_executed         (required for multi-path / comparison / drafting)
      - dlp_mode_decided      (required whenever the intent is drafting)
      - canonical_verified    (required for all grounded output)

  • `PreExecutionValidator.validate(state, requirements)` returns a
    `PEALReport` with violations.

  • The `AuthoritativeOutputGate` consults the report BEFORE stamping
    authority. On violation, emission is refused. The runtime catches
    the refusal and force-runs the missing stage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# Pipeline state — what DID run
# ═════════════════════════════════════════════════════════════════

@dataclass
class PipelineState:
    domain_resolved:      bool = False
    issue_graph_built:    bool = False
    mlre_executed:        bool = False
    mlre_has_survivors:   bool = False
    dlp_mode_decided:     bool = False
    dlp_mode:             str = ""
    canonical_verified:   bool = False
    # Additional observability flags
    issue_graph_size:     int = 0
    bound_evidence_links: int = 0
    survivors_count:      int = 0
    # IRA-amplified state fields
    pivots_count:         int = 0
    decisive_tests_count: int = 0
    pivot_in_output:      bool = False

    def to_dict(self) -> dict:
        return {
            "domain_resolved":      self.domain_resolved,
            "issue_graph_built":    self.issue_graph_built,
            "mlre_executed":        self.mlre_executed,
            "mlre_has_survivors":   self.mlre_has_survivors,
            "dlp_mode_decided":     self.dlp_mode_decided,
            "dlp_mode":             self.dlp_mode,
            "canonical_verified":   self.canonical_verified,
            "issue_graph_size":     self.issue_graph_size,
            "bound_evidence_links": self.bound_evidence_links,
            "survivors_count":      self.survivors_count,
            "pivots_count":         self.pivots_count,
            "decisive_tests_count": self.decisive_tests_count,
            "pivot_in_output":      self.pivot_in_output,
        }


# ═════════════════════════════════════════════════════════════════
# Requirements — what MUST have run
# ═════════════════════════════════════════════════════════════════

@dataclass
class PipelineRequirements:
    needs_domain:        bool = True
    needs_issue_graph:   bool = True
    needs_mlre:          bool = False
    needs_dlp:           bool = False
    needs_canonical:     bool = True
    # Declared intent label that drove these flags (for trace)
    intent_tag:          str = ""
    trigger_reasons:     list[str] = field(default_factory=list)
    # IRA-amplified fields
    min_hypotheses:      int = 0
    must_generate_pivots: bool = False
    needs_multi_path:    bool = False
    needs_pivot_output:  bool = False
    needs_dual_strategy: bool = False
    allowed_dlp_modes:   set[str] = field(default_factory=set)
    forbidden_dlp_modes: set[str] = field(default_factory=set)
    allow_skeleton:      bool = True
    amplifications:      list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "needs_domain":         self.needs_domain,
            "needs_issue_graph":    self.needs_issue_graph,
            "needs_mlre":           self.needs_mlre,
            "needs_dlp":            self.needs_dlp,
            "needs_canonical":      self.needs_canonical,
            "intent_tag":           self.intent_tag,
            "trigger_reasons":      self.trigger_reasons[:5],
            "min_hypotheses":       self.min_hypotheses,
            "must_generate_pivots": self.must_generate_pivots,
            "needs_multi_path":     self.needs_multi_path,
            "needs_pivot_output":   self.needs_pivot_output,
            "needs_dual_strategy":  self.needs_dual_strategy,
            "allowed_dlp_modes":    sorted(self.allowed_dlp_modes),
            "forbidden_dlp_modes":  sorted(self.forbidden_dlp_modes),
            "allow_skeleton":       self.allow_skeleton,
            "amplifications":       self.amplifications[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Requirement detection from the query + intent
# ═════════════════════════════════════════════════════════════════

# Phrases that force MLRE (ambiguity / comparison / multi-path)
_MLRE_TRIGGER_PHRASES = (
    "ما الأقوى", "ما الفرق بين", "مقارنة بين", "الفرق بين",
    "ما الذي يحسم", "ما الذي يحدّد", "هل هي أم هي",
    "هل X أم Y", "أم", "مسار بديل", "مسار احتياطي",
    "تكييف بديل", "وصف بديل",
    "جزائي أم مدني", "مدني أم جزائي",
    "شراكة أم عمل", "عمل أم شراكة",
    "بيع أم هبة", "هبة أم بيع",
    "ضمان أم وفاء", "وفاء أم ضمان",
    "مرض الموت", "تصرف قبل الوفاة",
    "شبهة احتيال", "احتمال احتيال",
    "شبهة جنائية", "احتمال جنائي",
    "متعدد", "احتمالات",
)


# Regex for disjunctive questions ("A أم B ؟")
_DISJUNCTIVE_RE = re.compile(
    r"(?:هل|هى|هي)?[^؟?]{3,40}\s+أم\s+[^؟?]{3,40}\s*[؟?]"
)


def _is_non_legal_smalltalk(query: str) -> bool:
    """Heuristic: small greetings / system queries need no MLRE/DLP."""
    q = (query or "").strip()
    if len(q) < 4:
        return True
    greetings = ("السلام عليكم", "السلام", "مرحبا", "أهلاً", "شكراً",
                  "شكرا", "كيف الحال", "hello", "hi")
    return any(q.startswith(g) for g in greetings)


def _is_drafting_intent(query: str) -> bool:
    from core.drafting import detect_drafting_intent
    try:
        intent = detect_drafting_intent(query)
        return getattr(intent, "value", "") != "none"
    except Exception:
        return False


def _is_multi_path_query(query: str) -> bool:
    q = query or ""
    for phrase in _MLRE_TRIGGER_PHRASES:
        if phrase in q:
            return True
    if _DISJUNCTIVE_RE.search(q):
        return True
    return False


def detect_requirements(query: str,
                           drafting_intent_present: bool = False,
                           apply_ira: bool = True,
                           ) -> PipelineRequirements:
    """Decide what the pipeline MUST run for this query.

    When `apply_ira=True` (default), IRA-amplified rules are layered on
    top of PEAL baseline (min_hypotheses, pivot generation, DLP mode
    whitelist/blacklist, multi-role detection).
    """
    req = PipelineRequirements()
    if not query or not query.strip():
        # Empty input — minimal requirements (the runtime will bail anyway)
        req.needs_domain = False
        req.needs_issue_graph = False
        req.needs_canonical = False
        req.intent_tag = "empty"
        return req

    if _is_non_legal_smalltalk(query):
        # Small talk / greeting — no legal reasoning needed
        req.needs_domain = False
        req.needs_issue_graph = False
        req.needs_canonical = False
        req.intent_tag = "smalltalk"
        return req

    # Drafting intent always mandates DLP + MLRE
    if drafting_intent_present or _is_drafting_intent(query):
        req.needs_dlp = True
        req.needs_mlre = True
        req.intent_tag = "drafting"
        req.trigger_reasons.append("drafting_intent_detected")
    elif _is_multi_path_query(query):
        # Multi-path / comparison triggers mandate MLRE
        req.needs_mlre = True
        req.intent_tag = "multi_path_analysis"
        req.trigger_reasons.append("multi_path_trigger")
    else:
        # Default analytical query — MLRE still REQUIRED by PEAL policy:
        # "any legal analytical query routes through MLRE to guarantee
        # multi-hypothesis discipline."
        req.needs_mlre = True
        req.intent_tag = "analytical"
        req.trigger_reasons.append("default_analytical_policy")

    # ── IRA: amplify requirements based on semantic signals ──
    if apply_ira:
        try:
            from core.runtime.intent_amplifier import (
                extract_query_signals, amplify_requirements,
            )
            signals = extract_query_signals(query)
            amplify_requirements(req, signals)
        except Exception:
            pass
    return req


# ═════════════════════════════════════════════════════════════════
# PEAL Report
# ═════════════════════════════════════════════════════════════════

@dataclass
class PEALReport:
    violations:     list[str] = field(default_factory=list)
    details:        dict = field(default_factory=dict)
    is_clean:       bool = True
    state:          Optional[PipelineState] = None
    requirements:   Optional[PipelineRequirements] = None

    def to_dict(self) -> dict:
        return {
            "is_clean":     self.is_clean,
            "violations":   self.violations[:6],
            "details":      self.details,
            "state":        self.state.to_dict() if self.state else {},
            "requirements": self.requirements.to_dict() if self.requirements else {},
        }


# ═════════════════════════════════════════════════════════════════
# Validator
# ═════════════════════════════════════════════════════════════════

class PreExecutionValidator:
    """Stateless validator. Use class methods; do not instantiate."""

    @classmethod
    def validate(cls,
                   state: PipelineState,
                   requirements: PipelineRequirements,
                   *, text: str = "",
                   ) -> PEALReport:
        report = PEALReport(state=state, requirements=requirements)

        # ── PEAL baseline checks ──
        if requirements.needs_domain and not state.domain_resolved:
            report.violations.append("domain_not_resolved")
            report.details["domain_not_resolved"] = (
                "المجال القانوني لم يُحدَّد قبل الإخراج."
            )

        if requirements.needs_issue_graph and not state.issue_graph_built:
            report.violations.append("issue_graph_missing")
            report.details["issue_graph_missing"] = (
                "Issue graph لم يُبنَ قبل الإخراج."
            )

        if requirements.needs_mlre and not state.mlre_executed:
            report.violations.append("mlre_not_executed")
            report.details["mlre_not_executed"] = (
                "MLRE مطلوب لهذا الطلب ولم يُنفَّذ."
            )

        if requirements.needs_dlp and not state.dlp_mode_decided:
            report.violations.append("dlp_mode_not_decided")
            report.details["dlp_mode_not_decided"] = (
                "طلب صياغة بدون قرار DLP لنوع المذكرة."
            )

        if requirements.needs_canonical and not state.canonical_verified:
            report.violations.append("canonical_not_verified")
            report.details["canonical_not_verified"] = (
                "الإخراج غير مربوط بمصادر canonical موثَّقة."
            )

        # ── IRA amplified checks ──
        try:
            from core.runtime.intent_amplifier import validate_amplified
            ira_violations = validate_amplified(
                state, requirements,
                text=text, dlp_mode=state.dlp_mode,
            )
            for v in ira_violations:
                report.violations.append(f"ira:{v}")
                report.details[f"ira:{v}"] = v
        except Exception:
            pass

        report.is_clean = len(report.violations) == 0
        return report


# ═════════════════════════════════════════════════════════════════
# State extraction helpers — map UnifiedArtifacts back to state
# ═════════════════════════════════════════════════════════════════

def extract_state_from_artifacts(artifacts) -> PipelineState:
    """Derive a PipelineState from what a UnifiedArtifacts bundle carries.

    This is the bridge used inside the gate: it looks at traces
    (mlre_trace, dlp_trace, evidence_trace, drafting) and infers which
    stages actually ran.
    """
    state = PipelineState()

    # Domain — either the pipeline classified it OR MLRE has surviving paths
    # with identified domains.
    domain = (getattr(artifacts, "domain", "") or "").strip()
    domain_resolved_pipeline = bool(domain and domain not in {
        "—", "قانوني", "غير محدد",
    })
    mlre_trace_for_domain = getattr(artifacts, "mlre_trace", {}) or {}
    _reality = mlre_trace_for_domain.get("reality", {}) or {}
    _mlre_domains = list(
        mlre_trace_for_domain.get("surviving_domains", []) or []
    )
    if not _mlre_domains:
        for p in (_reality.get("paths") or []):
            d = (p.get("domain") or "").strip()
            if d:
                _mlre_domains.append(d)
    # Also: DLP author present → drafting mode decided → structure implied
    _draft = getattr(artifacts, "drafting", {}) or {}
    _drafting_implies_domain = bool(_draft.get("drafting_mode"))
    state.domain_resolved = bool(
        domain_resolved_pipeline
        or _mlre_domains
        or _drafting_implies_domain
    )

    # Issue graph — heuristics: evidence_trace usually carries query_issues
    et = getattr(artifacts, "evidence_trace", {}) or {}
    issues = list(et.get("query_issues", []) or [])
    if not issues:
        # Check mlre_trace.reality.paths[*].domain as a graph hint
        mlre = getattr(artifacts, "mlre_trace", {}) or {}
        reality = mlre.get("reality", {}) or {}
        state.issue_graph_built = bool(reality.get("paths"))
    else:
        state.issue_graph_built = True
    state.issue_graph_size = len(issues)
    state.bound_evidence_links = len(
        list((getattr(artifacts, "sources", []) or []))
    )

    # MLRE
    mlre_trace = getattr(artifacts, "mlre_trace", {}) or {}
    reality = mlre_trace.get("reality", {}) or {}
    state.mlre_executed = bool(
        mlre_trace.get("mlre_output_used")
        or mlre_trace.get("surviving_count")
        or mlre_trace.get("survivors_count")
        or (mlre_trace.get("output_composition") or {}).get("mlre_output_used")
        or reality.get("paths")
    )
    state.survivors_count = int(
        mlre_trace.get("surviving_count")
        or mlre_trace.get("survivors_count")
        or reality.get("surviving_count")
        or 0
    )
    state.mlre_has_survivors = state.survivors_count > 0

    # DLP
    drafting = getattr(artifacts, "drafting", {}) or {}
    dlp_trace = getattr(artifacts, "dlp_trace", {}) or {}
    state.dlp_mode = (drafting.get("drafting_mode")
                      or dlp_trace.get("mode", "") or "")
    state.dlp_mode_decided = bool(state.dlp_mode)

    # Canonical — for now, grounded responses count as canonical-verified
    state.canonical_verified = bool(
        getattr(artifacts, "is_grounded", False)
        or (getattr(artifacts, "sources", []) or [])
        or mlre_trace.get("survivors_count")
        or mlre_trace.get("surviving_count")
        or state.dlp_mode in {
            "full_draft", "conditional_draft", "conditional",
            "dual_strategy_draft", "dual_strategy", "single_path",
            "skeleton_draft",
        }
    )

    # IRA-amplified state — pivot / decisive-test counts
    _reality_full = mlre_trace.get("reality", {}) or {}
    state.pivots_count = len(_reality_full.get("pivot_conditions", []) or [])
    state.decisive_tests_count = len(
        _reality_full.get("decisive_tests", []) or []
    )
    # pivot_in_output: look at the answer text for pivot markers
    text = getattr(artifacts, "text", "") or ""
    pivot_markers = (
        "ينتقل المسار", "ما يحسم", "ما يحدّد",
        "المسار البديل", "التكييف البديل",
        "متى ينتقل", "على سبيل الاحتياط",
    )
    state.pivot_in_output = any(m in text for m in pivot_markers)

    return state
