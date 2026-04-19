# -*- coding: utf-8 -*-
"""
Plan Builder — creates structured execution plans for complex queries.
"""
import logging
from dataclasses import dataclass, field
from core.self_correction.schemas import QueryComplexity

log = logging.getLogger("planning")


@dataclass
class PlanStep:
    step_type: str       # "rag", "tool", "verify", "merge", "answer"
    description: str
    inputs: dict = field(default_factory=dict)
    output_key: str = ""
    skip_if_failed: bool = False


@dataclass
class ExecutionPlan:
    complexity: QueryComplexity
    steps: list[PlanStep] = field(default_factory=list)
    requires_buffered_output: bool = True
    requires_sc: bool = True


def build_plan(
    complexity: QueryComplexity,
    has_tools: bool = False,
    brain_route: str = "",
) -> ExecutionPlan:
    """Build execution plan based on complexity classification."""

    # ── Simple: direct streaming, no SC ──
    if complexity == QueryComplexity.SIMPLE:
        return ExecutionPlan(
            complexity=complexity,
            steps=[PlanStep("answer", "direct response")],
            requires_buffered_output=False,
            requires_sc=False,
        )

    # ── Tool-required: tool → optional RAG → SC → answer ──
    if complexity == QueryComplexity.TOOL_REQUIRED:
        steps = [
            PlanStep("tool", "execute tool", output_key="tool_result"),
            PlanStep("rag", "retrieve legal context", output_key="rag_context"),
            PlanStep("merge", "combine tool + legal context", output_key="merged"),
            PlanStep("answer", "generate answer from merged context"),
            PlanStep("verify", "self-correction"),
        ]
        return ExecutionPlan(
            complexity=complexity, steps=steps,
            requires_buffered_output=True, requires_sc=True)

    # ── Legal single: RAG → answer → SC ──
    if complexity == QueryComplexity.LEGAL_SINGLE:
        steps = [
            PlanStep("rag", "retrieve legal context", output_key="rag_context"),
            PlanStep("answer", "generate legal answer"),
            PlanStep("verify", "self-correction"),
        ]
        return ExecutionPlan(
            complexity=complexity, steps=steps,
            requires_buffered_output=True, requires_sc=True)

    # ── Legal multi: decompose → RAG per sub-query → merge → answer → SC ──
    if complexity == QueryComplexity.LEGAL_MULTI:
        steps = [
            PlanStep("decompose", "break into sub-questions", output_key="sub_queries"),
            PlanStep("rag", "retrieve for all sub-questions", output_key="rag_context"),
            PlanStep("answer", "generate comprehensive answer"),
            PlanStep("verify", "self-correction with coverage check"),
        ]
        return ExecutionPlan(
            complexity=complexity, steps=steps,
            requires_buffered_output=True, requires_sc=True)

    # ── Complex: full pipeline ──
    steps = [
        PlanStep("decompose", "break into sub-questions", output_key="sub_queries"),
        PlanStep("tool", "execute tools if needed", output_key="tool_result", skip_if_failed=True),
        PlanStep("rag", "retrieve legal context", output_key="rag_context"),
        PlanStep("merge", "combine all sources", output_key="merged"),
        PlanStep("answer", "generate answer"),
        PlanStep("verify", "full self-correction"),
    ]
    return ExecutionPlan(
        complexity=complexity, steps=steps,
        requires_buffered_output=True, requires_sc=True)
