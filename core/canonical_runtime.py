# -*- coding: utf-8 -*-
"""
Canonical Runtime — single source-of-truth answer path
========================================================
Wraps the ExecutionPipeline as the canonical runtime for legal consultation
queries. Provides a stable façade that the FastAPI router (or any caller)
can use without knowing about the underlying pipeline composition.

Hard rules:
  - exactly one canonical path for consultation answers
  - legacy orchestrator may still exist but is not the canonical authority
  - LLM polishing path is opt-in via env / parameter (OFF by default)
  - measurable end-to-end latency
"""
from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.execution_pipeline import (
    ExecutionPipeline, StructuredOutput, RouterResult, QueryType,
)
from core.controlled_reasoning_core import LegalDecisionRecord
from core.intelligent_decision_engine import (
    enhance_with_branches, IntelligentDecisionPlan,
)

log = logging.getLogger("canonical_runtime")


@dataclass
class CanonicalAnswer:
    """The single canonical answer object for any legal consultation query."""
    request_id: str = ""
    text: str = ""
    issue_type: str = ""
    domain: str = ""
    branches_applied: bool = False
    used_llm: bool = False
    fallback_applied: bool = False
    grounding_blocked: int = 0
    pipeline_steps: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# CanonicalRuntime
# ══════════════════════════════════════════════════════════════

# Env flag — opt-in to LLM polishing (default OFF)
_LLM_POLISH_ENABLED = os.getenv("LEGAL_LLM_POLISH", "").lower() in (
    "1", "true", "yes", "on")


class CanonicalRuntime:
    """
    The single canonical entry point. Use this from FastAPI / production code.
    """

    def __init__(self, llm_caller: Optional[Callable[[str, str], str]] = None):
        # Only wire LLM if the env flag is set AND a caller is provided
        effective_llm = llm_caller if (llm_caller and _LLM_POLISH_ENABLED) else None
        self._pipeline = ExecutionPipeline(llm_caller=effective_llm)

    def answer(self, query: str,
                 session_id: Optional[str] = None,
                 request_ip: str = "",
                 request_headers: Optional[dict] = None,
                 enable_branching: bool = True
                 ) -> CanonicalAnswer:
        """Return the canonical answer for a legal consultation query."""
        start = time.time()

        out = self._pipeline.execute(
            query=query, session_id=session_id,
            request_ip=request_ip, request_headers=request_headers,
        )

        canonical = CanonicalAnswer(
            request_id=out.request_id,
            text=out.formatted_text,
            issue_type=out.issue_type,
            domain=out.domain,
            fallback_applied=out.fallback_applied,
            grounding_blocked=out.grounding_blocked,
            pipeline_steps=list(out.pipeline_steps_completed),
        )
        # Pull notes through
        canonical.notes.extend(out.notes)

        # ─── Branching status from pipeline ───
        # The ExecutionPipeline already runs intelligent branching at step 6.7.
        # Reflect that in the CanonicalAnswer flag — do NOT re-append.
        if any("intelligent_branching_applied" in n for n in out.notes):
            canonical.branches_applied = True

        # Pull LLM-usage flag from notes
        for n in out.notes:
            if n.startswith("formatter_used_llm:"):
                canonical.used_llm = n.split(":", 1)[1].strip() == "True"

        canonical.elapsed_seconds = time.time() - start
        log.info("[CANONICAL] req=%s issue=%s branches=%s elapsed=%.3fs",
                 canonical.request_id, canonical.issue_type,
                 canonical.branches_applied, canonical.elapsed_seconds)
        return canonical


# ══════════════════════════════════════════════════════════════
# Module-level singleton
# ══════════════════════════════════════════════════════════════

_runtime: Optional[CanonicalRuntime] = None


def get_canonical_runtime(llm_caller: Optional[Callable] = None) -> CanonicalRuntime:
    global _runtime
    if _runtime is None:
        _runtime = CanonicalRuntime(llm_caller=llm_caller)
    return _runtime


def answer_legal_query(query: str,
                         session_id: Optional[str] = None,
                         **kwargs) -> CanonicalAnswer:
    """Convenience: top-level production entry point."""
    return get_canonical_runtime().answer(query, session_id=session_id, **kwargs)
