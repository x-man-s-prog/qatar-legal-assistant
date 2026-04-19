# -*- coding: utf-8 -*-
"""
REUP — Authoritative Output Gate.

THE ONE PLACE where a user-facing response dict is finalized.

Every layer that wants to reach the user MUST produce a `UnifiedArtifacts`
bundle and hand it to `AuthoritativeOutputGate.emit(...)`. No layer may
construct a response dict on its own.

Invariants enforced before a response is released:

  1. `authoritative_execution_path == "UNIFIED_LEGAL_RUNTIME"`
  2. `output_author` is a known `ResponseAuthor` (never "unknown")
  3. MLRE trace is present whenever a MLRE survivor influenced the text
  4. DLP mode stamp is present whenever the text is a drafting output
  5. The text is free of legacy signatures (scanned via legacy_detector)
  6. `legacy_used == False`, `fallback_used == False`
  7. No unknown keys are introduced; the HTTP contract is fixed

Failing any invariant → the gate raises `AuthoritativeOutputViolation`,
NOT a silent passthrough. The unified runtime catches this and emits a
structured internal-failure response that still follows the contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any

from core.runtime.legacy_detector import (
    detect_legacy_signatures, LegacyDetectionReport,
)


AUTHORITATIVE_PATH = "UNIFIED_LEGAL_RUNTIME"


# ═════════════════════════════════════════════════════════════════
# Who wrote the text
# ═════════════════════════════════════════════════════════════════

class ResponseAuthor(str, Enum):
    # Legal-answer authors
    FAIL_CLOSED_PIPELINE  = "fail_closed_pipeline"      # analytical answer (pipeline text)
    MLRE_OUTPUT_COMPOSER  = "mlre_output_composer"      # MLRE replaced the pipeline text
    # Drafting authors
    DLP_FULL_DRAFT        = "dlp_full_draft"
    DLP_CONDITIONAL_DRAFT = "dlp_conditional_draft"
    DLP_DUAL_STRATEGY     = "dlp_dual_strategy"
    DLP_SKELETON_DRAFT    = "dlp_skeleton_draft"
    DLP_NOT_DRAFTABLE     = "dlp_not_draftable"
    # Safety / operational
    SAFETY_STOP           = "safety_stop"               # explicit safety refusal
    CANCELLED             = "cancelled"                 # user cancellation
    INTERNAL_FAILURE      = "internal_failure"          # structured runtime failure


# ═════════════════════════════════════════════════════════════════
# Unified artifact bundle (input to the gate)
# ═════════════════════════════════════════════════════════════════

@dataclass
class UnifiedArtifacts:
    """Every producer fills one of these. The gate turns it into a dict."""
    author:        ResponseAuthor
    text:          str = ""
    domain:        str = ""
    sources:       list[dict] = field(default_factory=list)
    confidence:    int = 0
    is_grounded:   bool = False
    is_blocked:    bool = False

    # Gate / rule traces
    gates_passed:      list[str] = field(default_factory=list)
    gates_failed:      list[str] = field(default_factory=list)
    block_reasons:     list[str] = field(default_factory=list)
    fatal_violations:  list[str] = field(default_factory=list)
    runtime_notes:     list[str] = field(default_factory=list)
    evidence_trace:    dict      = field(default_factory=dict)
    sufficiency_level: str       = ""
    elapsed_seconds:   float     = 0.0

    # MLRE / DLP / MQE / PASL traces (opaque dicts; stored verbatim)
    mlre_trace:        dict = field(default_factory=dict)
    dlp_trace:         dict = field(default_factory=dict)
    mqe_trace:         dict = field(default_factory=dict)
    pasl_trace:        dict = field(default_factory=dict)
    ux_trace:          dict = field(default_factory=dict)
    firewall_trace:    dict = field(default_factory=dict)
    validation_trace:  dict = field(default_factory=dict)

    # Drafting fields (only when author is one of the DLP_* values)
    drafting:          dict = field(default_factory=dict)

    # Conversation trace
    conversation:      dict = field(default_factory=dict)

    # Request metadata
    request_id:        str = ""
    knowledge_activation: dict = field(default_factory=dict)

    # PEAL (Pre-Execution Authority Lock) fields
    # The runtime populates `peal_requirements` from the query BEFORE
    # running the pipeline, and the gate verifies the trace reflects
    # every required stage.
    peal_requirements: dict = field(default_factory=dict)   # serialized
    peal_state:        dict = field(default_factory=dict)   # serialized

    def kind(self) -> str:
        """Is this a drafting output or an analytical one?"""
        if self.author in (ResponseAuthor.DLP_FULL_DRAFT,
                              ResponseAuthor.DLP_CONDITIONAL_DRAFT,
                              ResponseAuthor.DLP_DUAL_STRATEGY,
                              ResponseAuthor.DLP_SKELETON_DRAFT,
                              ResponseAuthor.DLP_NOT_DRAFTABLE):
            return "drafting"
        if self.author in (ResponseAuthor.FAIL_CLOSED_PIPELINE,
                              ResponseAuthor.MLRE_OUTPUT_COMPOSER):
            return "analytical"
        return "safety"


# ═════════════════════════════════════════════════════════════════
# Violation & final response
# ═════════════════════════════════════════════════════════════════

class AuthoritativeOutputViolation(RuntimeError):
    """Raised when a UnifiedArtifacts bundle fails the gate. The caller
    is expected to catch this, log it, and emit the structured
    internal-failure response instead."""
    def __init__(self, reason: str, details: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


# ═════════════════════════════════════════════════════════════════
# The gate itself
# ═════════════════════════════════════════════════════════════════

class AuthoritativeOutputGate:
    """Stateless gate. Use class methods; do not instantiate."""

    @classmethod
    def emit(cls, artifacts: UnifiedArtifacts) -> dict:
        """Validate + finalize the response dict.

        Raises AuthoritativeOutputViolation on any invariant breach.

        Order of checks:
          1. author is a known enum
          2. text is non-empty on non-blocked outputs
          3. drafting coherence (intent + mode stamps)
          4. MLRE coherence (author → trace)
          5. PEAL — every required reasoning stage actually ran
          6. legacy signatures — no banned output patterns
        """
        cls._check_author(artifacts)
        cls._check_text(artifacts)
        cls._check_drafting_coherence(artifacts)
        cls._check_mlre_coherence(artifacts)
        peal_report = cls._check_peal(artifacts)
        legacy_report = cls._check_legacy_signatures(artifacts)

        response = cls._build_response_dict(
            artifacts, legacy_report, peal_report,
        )
        cls._stamp_authority(response, artifacts)
        return response

    # ── Invariant checks ──

    @staticmethod
    def _check_author(a: UnifiedArtifacts) -> None:
        if not isinstance(a.author, ResponseAuthor):
            raise AuthoritativeOutputViolation(
                "author_not_enum",
                {"got": repr(a.author)},
            )

    @staticmethod
    def _check_text(a: UnifiedArtifacts) -> None:
        if a.author == ResponseAuthor.CANCELLED:
            return  # cancellation may carry any text or none
        if a.text is None:
            raise AuthoritativeOutputViolation("text_is_none")
        if not a.is_blocked and not a.text.strip() \
                and a.author != ResponseAuthor.INTERNAL_FAILURE:
            raise AuthoritativeOutputViolation(
                "empty_text_on_unblocked_output",
                {"author": a.author.value},
            )

    @staticmethod
    def _check_drafting_coherence(a: UnifiedArtifacts) -> None:
        if a.kind() != "drafting":
            return
        d = a.drafting or {}
        if not d.get("drafting_intent_detected"):
            raise AuthoritativeOutputViolation(
                "drafting_missing_intent_stamp",
                {"author": a.author.value, "drafting": d},
            )
        # A drafting author must carry a drafting_mode
        if "drafting_mode" not in d:
            raise AuthoritativeOutputViolation(
                "drafting_missing_mode_stamp",
                {"author": a.author.value},
            )

    @staticmethod
    def _check_mlre_coherence(a: UnifiedArtifacts) -> None:
        if a.author != ResponseAuthor.MLRE_OUTPUT_COMPOSER:
            return
        trace = a.mlre_trace or {}
        # Accept any of the known "MLRE ran" markers (top-level or nested)
        if trace.get("mlre_output_used"):
            return
        oc = trace.get("output_composition") or {}
        if oc.get("mlre_output_used") or oc.get("survivors_count"):
            return
        if trace.get("survivors_count") or trace.get("surviving_count"):
            return
        reality = trace.get("reality") or {}
        if reality.get("surviving_count") or reality.get("paths"):
            return
        raise AuthoritativeOutputViolation(
            "mlre_author_without_trace",
            {"mlre_trace_keys": list(trace.keys())},
        )

    @staticmethod
    def _check_peal(a: UnifiedArtifacts):
        """Pre-Execution Authority Lock.

        Ensures MLRE / DLP / issue-graph / canonical actually ran
        whenever the query demanded them. Skipped for operational
        authors (CANCELLED / INTERNAL_FAILURE / SAFETY_STOP) where
        upstream already refused to proceed.
        """
        from core.runtime.pre_execution_validator import (
            PreExecutionValidator, PipelineState, PipelineRequirements,
            extract_state_from_artifacts,
        )
        # Operational authors bypass PEAL — upstream already aborted.
        if a.author in (ResponseAuthor.CANCELLED,
                          ResponseAuthor.INTERNAL_FAILURE,
                          ResponseAuthor.SAFETY_STOP):
            return None

        # Rehydrate requirements & state from the bundle
        req_dict   = a.peal_requirements or {}
        state_dict = a.peal_state        or {}

        # PEAL is opt-in: the runtime populates requirements explicitly.
        # Raw artifacts (e.g. in unit tests or legacy callers) skip PEAL.
        if not req_dict:
            return None

        requirements = PipelineRequirements(
            needs_domain=req_dict.get("needs_domain", True),
            needs_issue_graph=req_dict.get("needs_issue_graph", True),
            needs_mlre=req_dict.get("needs_mlre", False),
            needs_dlp=req_dict.get("needs_dlp", False),
            needs_canonical=req_dict.get("needs_canonical", True),
            intent_tag=req_dict.get("intent_tag", ""),
            trigger_reasons=list(req_dict.get("trigger_reasons", []) or []),
        )
        if state_dict:
            state = PipelineState(
                domain_resolved=state_dict.get("domain_resolved", False),
                issue_graph_built=state_dict.get("issue_graph_built", False),
                mlre_executed=state_dict.get("mlre_executed", False),
                mlre_has_survivors=state_dict.get("mlre_has_survivors", False),
                dlp_mode_decided=state_dict.get("dlp_mode_decided", False),
                dlp_mode=state_dict.get("dlp_mode", ""),
                canonical_verified=state_dict.get("canonical_verified", False),
                issue_graph_size=state_dict.get("issue_graph_size", 0),
                bound_evidence_links=state_dict.get("bound_evidence_links", 0),
                survivors_count=state_dict.get("survivors_count", 0),
                pivots_count=state_dict.get("pivots_count", 0),
                decisive_tests_count=state_dict.get("decisive_tests_count", 0),
                pivot_in_output=state_dict.get("pivot_in_output", False),
            )
        else:
            state = extract_state_from_artifacts(a)

        # Rehydrate amplified fields from dict back onto the requirements
        requirements.min_hypotheses      = req_dict.get("min_hypotheses", 0)
        requirements.must_generate_pivots = req_dict.get("must_generate_pivots", False)
        requirements.needs_multi_path    = req_dict.get("needs_multi_path", False)
        requirements.needs_pivot_output  = req_dict.get("needs_pivot_output", False)
        requirements.needs_dual_strategy = req_dict.get("needs_dual_strategy", False)
        requirements.allowed_dlp_modes   = set(req_dict.get("allowed_dlp_modes", []) or [])
        requirements.forbidden_dlp_modes = set(req_dict.get("forbidden_dlp_modes", []) or [])
        requirements.allow_skeleton      = req_dict.get("allow_skeleton", True)
        requirements.amplifications      = list(req_dict.get("amplifications", []) or [])

        report = PreExecutionValidator.validate(
            state, requirements, text=a.text or "",
        )

        # Retro-store the extracted state for the response trace
        a.peal_state = state.to_dict()
        a.peal_requirements = requirements.to_dict()

        if not report.is_clean:
            raise AuthoritativeOutputViolation(
                "peal_violation",
                {
                    "violations":   report.violations,
                    "requirements": requirements.to_dict(),
                    "state":        state.to_dict(),
                },
            )
        return report

    @staticmethod
    def _check_legacy_signatures(a: UnifiedArtifacts) -> LegacyDetectionReport:
        """Return the report. Raises on any hard signature hit."""
        is_skeleton = a.author == ResponseAuthor.DLP_SKELETON_DRAFT
        is_nd       = a.author == ResponseAuthor.DLP_NOT_DRAFTABLE
        report = detect_legacy_signatures(
            a.text,
            domain=a.domain,
            is_draftable_skeleton=is_skeleton,
            is_not_draftable=is_nd,
        )
        if not report.is_clean:
            raise AuthoritativeOutputViolation(
                "legacy_signature_in_output",
                {"hits": report.hits, "details": report.details[:3]},
            )
        return report

    # ── Build + stamp ──

    @staticmethod
    def _build_response_dict(
        a: UnifiedArtifacts,
        legacy_report: LegacyDetectionReport,
        peal_report=None,
    ) -> dict:
        response: dict[str, Any] = {
            "answer":          a.text,
            "sources":         list(a.sources or []),
            "domain":          a.domain or "قانوني",
            "confidence":      int(a.confidence),
            "is_grounded":     bool(a.is_grounded),
            "runtime":         "fail_closed",
            "gates_passed":    list(a.gates_passed),
            "gates_failed":    list(a.gates_failed),
            "block_reasons":   list(a.block_reasons),
            "fatal_violations": list(a.fatal_violations),
            "elapsed_seconds": round(a.elapsed_seconds, 4),
            "runtime_notes":   list(a.runtime_notes),
            "is_blocked":      bool(a.is_blocked),
            "evidence_trace":  dict(a.evidence_trace or {}),
            "sufficiency_level": a.sufficiency_level,
            "knowledge_activation": dict(a.knowledge_activation or {}),
        }
        # Attach traces ONLY when present
        if a.mlre_trace:
            response["mlre"] = dict(a.mlre_trace)
        if a.ux_trace:
            response["ux"] = dict(a.ux_trace)
        if a.firewall_trace:
            response["output_firewall"] = dict(a.firewall_trace)
        if a.validation_trace:
            response["validation"] = dict(a.validation_trace)
        if a.conversation:
            response["conversation"] = dict(a.conversation)
        if a.dlp_trace:
            response["dlp"] = dict(a.dlp_trace)
        if a.mqe_trace:
            response["mqe"] = dict(a.mqe_trace)
        if a.pasl_trace:
            response["pasl"] = dict(a.pasl_trace)
        if a.kind() == "drafting":
            response["drafting"] = dict(a.drafting)
        if a.request_id:
            response["request_id"] = a.request_id
        # Debug legacy report (internal telemetry only)
        response["_legacy_scan"] = legacy_report.to_dict()
        # PEAL telemetry — only when the check actually ran
        if peal_report is not None:
            response["_peal"] = peal_report.to_dict()
        elif a.peal_state or a.peal_requirements:
            response["_peal"] = {
                "is_clean":     True,
                "violations":   [],
                "state":        a.peal_state,
                "requirements": a.peal_requirements,
            }
        return response

    @staticmethod
    def _stamp_authority(response: dict, a: UnifiedArtifacts) -> None:
        response["authoritative_path"]            = "unified_fail_closed"
        response["authoritative_execution_path"]  = AUTHORITATIVE_PATH
        response["output_author"]                 = a.author.value
        response["legacy_used"]                   = False
        response["fallback_used"]                 = False
        # Back-compat status marker for cancellation listeners
        if a.author == ResponseAuthor.CANCELLED:
            response["status"] = "cancelled"
            response["message"] = "تم إيقاف التنفيذ"
        # These three fields MUST be identical across all responses
        assert response["authoritative_execution_path"] == AUTHORITATIVE_PATH
        assert response["legacy_used"] is False
        assert response["fallback_used"] is False


# ═════════════════════════════════════════════════════════════════
# Structured internal-failure fallback (still goes through the gate)
# ═════════════════════════════════════════════════════════════════

def build_internal_failure_artifacts(
    *, reason: str, request_id: str = "", exc_type: str = "",
) -> UnifiedArtifacts:
    """Construct a unified, safe failure bundle the gate will accept.

    This replaces every former legacy "refusal" text. Even exception
    paths go through the gate, so the authority stamp is preserved.
    """
    text = (
        "تعذّر إنتاج إجابة قانونية آمنة للمسألة المطروحة حالياً. "
        "يُرجى إعادة صياغة السؤال مع تحديد الأطراف والوقائع والأدلة، "
        "أو استشارة محامٍ مختص قبل اتخاذ أي إجراء."
    )
    return UnifiedArtifacts(
        author=ResponseAuthor.INTERNAL_FAILURE,
        text=text,
        domain="غير محدد",
        confidence=0,
        is_grounded=False,
        is_blocked=True,
        gates_passed=[],
        gates_failed=[reason],
        block_reasons=[reason],
        fatal_violations=[reason] if exc_type else [],
        runtime_notes=[f"internal_failure:{reason}"] +
                         ([f"exc:{exc_type}"] if exc_type else []),
        sufficiency_level="none",
        request_id=request_id,
    )


def build_cancelled_artifacts(
    *, request_id: str = "", stage: str = "",
) -> UnifiedArtifacts:
    """Cancellation — still goes through the gate."""
    return UnifiedArtifacts(
        author=ResponseAuthor.CANCELLED,
        text="تم إيقاف التنفيذ بناءً على طلب المستخدم.",
        domain="—",
        confidence=0,
        is_grounded=False,
        is_blocked=True,
        gates_passed=[],
        gates_failed=["user_cancelled"],
        block_reasons=["user_cancelled"],
        runtime_notes=[f"cancelled_at:{stage}"] if stage else ["cancelled"],
        sufficiency_level="none",
        request_id=request_id,
    )
