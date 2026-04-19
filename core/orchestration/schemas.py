# -*- coding: utf-8 -*-
"""Typed schemas for tool orchestration."""
from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ToolName(str, Enum):
    END_OF_SERVICE = "end_of_service"
    UNFAIR_DISMISSAL = "unfair_dismissal"
    ARTICLE_LOOKUP = "article_lookup"
    TABLE_LOOKUP = "table_lookup"
    PENALTY_LOOKUP = "penalty_lookup"
    RAG_SEARCH = "rag_search"


class PlanType(str, Enum):
    DIRECT = "direct"            # answer from RAG/known answer alone
    TOOL_ONLY = "tool_only"      # pure tool computation
    RAG_THEN_TOOL = "rag_then_tool"  # retrieve context, then compute
    TOOL_THEN_RAG = "tool_then_rag"  # compute, then enrich with legal basis
    MULTI_STEP = "multi_step"    # complex: decompose + multiple steps


class ToolCall(BaseModel):
    tool_name: ToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ToolOutput(BaseModel):
    tool_name: ToolName
    success: bool = False
    result: Any = None
    error: str = ""
    result_text: str = ""        # human-readable result


class ToolValidation(BaseModel):
    tool_name: ToolName
    valid: bool = True
    issues: list[str] = Field(default_factory=list)


class OrchestrationPlan(BaseModel):
    plan_type: PlanType = PlanType.DIRECT
    needs_tools: bool = False
    needs_rag: bool = True
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning: str = ""


class AuditRecord(BaseModel):
    query: str = ""
    plan: Optional[OrchestrationPlan] = None
    tool_outputs: list[ToolOutput] = Field(default_factory=list)
    validations: list[ToolValidation] = Field(default_factory=list)
    merged_context: str = ""
    final_plan_type: str = ""
    latency_ms: int = 0
