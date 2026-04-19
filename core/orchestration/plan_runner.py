# -*- coding: utf-8 -*-
"""
Plan Runner V2 — orchestrates tool selection (with LLM fallback), execution, validation.
"""
import time, logging
from typing import Optional, Callable
from .schemas import PlanType, OrchestrationPlan, ToolOutput, ToolValidation, AuditRecord
from .tool_selector import select_tools, select_tools_async
from .tool_executor import execute_tool

log = logging.getLogger("orchestration")


class OrchestrationResult:
    __slots__ = ("plan", "tool_text", "tool_context", "needs_rag",
                 "needs_llm", "audit", "early_return")

    def __init__(self):
        self.plan: Optional[OrchestrationPlan] = None
        self.tool_text: str = ""
        self.tool_context: str = ""
        self.needs_rag: bool = True
        self.needs_llm: bool = True
        self.audit: Optional[AuditRecord] = None
        self.early_return: bool = False


class OrchestrationRunner:

    def __init__(self, pool=None):
        self.pool = pool

    async def run(self, query: str, brain_route: str = "",
                  llm_caller: Optional[Callable] = None) -> OrchestrationResult:
        t0 = time.perf_counter()
        out = OrchestrationResult()

        # Step 1: Tool selection (with LLM fallback if available)
        if llm_caller:
            plan = await select_tools_async(query, brain_route, llm_caller)
        else:
            plan = select_tools(query, brain_route)

        out.plan = plan
        audit = AuditRecord(query=query[:200], plan=plan, final_plan_type=plan.plan_type.value)

        if not plan.needs_tools:
            out.needs_rag = plan.needs_rag
            audit.latency_ms = int((time.perf_counter() - t0) * 1000)
            out.audit = audit
            return out

        log.info("[ORCH] plan=%s tools=%s", plan.plan_type.value,
                 [tc.tool_name.value for tc in plan.tool_calls])

        # Step 2: Execute tools
        all_outputs: list[ToolOutput] = []
        all_validations: list[ToolValidation] = []
        tool_texts: list[str] = []

        for call in plan.tool_calls:
            output, validation = await execute_tool(call, pool=self.pool)
            all_outputs.append(output)
            all_validations.append(validation)
            if output.success and output.result_text:
                tool_texts.append(output.result_text)

        audit.tool_outputs = all_outputs
        audit.validations = all_validations

        any_success = any(o.success for o in all_outputs)
        if not any_success:
            log.warning("[ORCH] all tools failed → RAG fallback")
            out.needs_rag = True
            audit.latency_ms = int((time.perf_counter() - t0) * 1000)
            out.audit = audit
            return out

        merged = "\n\n".join(tool_texts)

        if plan.plan_type == PlanType.TOOL_ONLY:
            out.tool_text = merged
            out.early_return = True
            out.needs_rag = False
            out.needs_llm = False
        elif plan.plan_type == PlanType.TOOL_THEN_RAG:
            out.tool_context = f"\n\nنتيجة الحساب:\n{merged}\n"
            out.needs_rag = True
        else:
            out.tool_context = f"\n\nنتائج الأدوات:\n{merged}\n"
            out.needs_rag = True

        audit.merged_context = merged[:500]
        audit.latency_ms = int((time.perf_counter() - t0) * 1000)
        out.audit = audit
        log.info("[ORCH] done: early=%s rag=%s ms=%d", out.early_return, out.needs_rag, audit.latency_ms)
        return out
