# -*- coding: utf-8 -*-
"""
Unified Legal Runtime — REUP (Root Execution Unification Protocol).

The ONE runtime path. No duplicates, no overrides, no legacy fallbacks.

Public API:
    from core.runtime import (
        ResponseAuthor, UnifiedArtifacts,
        AuthoritativeOutputGate, AuthoritativeOutputViolation,
        AUTHORITATIVE_PATH,
        build_internal_failure_artifacts,
        build_cancelled_artifacts,
        detect_legacy_signatures, LegacyDetectionReport,
        is_output_legacy_free,
    )
"""
from core.runtime.legacy_detector import (
    detect_legacy_signatures, is_output_legacy_free,
    LegacyDetectionReport,
)
from core.runtime.authoritative_output import (
    ResponseAuthor, UnifiedArtifacts,
    AuthoritativeOutputGate, AuthoritativeOutputViolation,
    AUTHORITATIVE_PATH,
    build_internal_failure_artifacts,
    build_cancelled_artifacts,
)
from core.runtime.pre_execution_validator import (
    PipelineState, PipelineRequirements, PEALReport,
    PreExecutionValidator,
    detect_requirements, extract_state_from_artifacts,
)
from core.runtime.intent_amplifier import (
    QuerySignals, extract_query_signals,
    amplify_requirements, validate_amplified,
    extend_state_with_amplified_signals,
)
from core.runtime.adaptive_balancer import (
    AdaptationMode, AdaptationResult,
    adapt as aib_adapt,
    is_adaptable_violation_set,
    classify_adaptation_mode,
    compose_single_adaptive,
    compose_partial_multi,
    compose_skeleton_adaptive,
    try_mlre_expansion,
    downgrade_requirements,
)
from core.runtime.unified_entry import (
    unified_entry_context, is_in_unified_context,
    current_entry_source, current_entry_depth,
    assert_entered_via_unified,
    IllegalDirectResponseError,
    detect_split_execution,
    sealed_legacy,
)
from core.runtime.force_stages import (
    force_mlre, force_dlp, rebuild_issue_graph,
    enforce_pipeline_completeness,
)

__all__ = [
    # Legacy detector
    "detect_legacy_signatures", "is_output_legacy_free",
    "LegacyDetectionReport",
    # Gate
    "ResponseAuthor", "UnifiedArtifacts",
    "AuthoritativeOutputGate", "AuthoritativeOutputViolation",
    "AUTHORITATIVE_PATH",
    "build_internal_failure_artifacts",
    "build_cancelled_artifacts",
    # PEAL
    "PipelineState", "PipelineRequirements", "PEALReport",
    "PreExecutionValidator",
    "detect_requirements", "extract_state_from_artifacts",
    # IRA
    "QuerySignals", "extract_query_signals",
    "amplify_requirements", "validate_amplified",
    "extend_state_with_amplified_signals",
    # AIB
    "AdaptationMode", "AdaptationResult",
    "aib_adapt", "is_adaptable_violation_set",
    "classify_adaptation_mode",
    "compose_single_adaptive", "compose_partial_multi",
    "compose_skeleton_adaptive",
    "try_mlre_expansion", "downgrade_requirements",
    # SEA — Single Entry Authority
    "unified_entry_context", "is_in_unified_context",
    "current_entry_source", "current_entry_depth",
    "assert_entered_via_unified",
    "IllegalDirectResponseError",
    "detect_split_execution",
    "sealed_legacy",
    # SEA — force-stage enforcers (PEAL amplifier)
    "force_mlre", "force_dlp", "rebuild_issue_graph",
    "enforce_pipeline_completeness",
]
