# -*- coding: utf-8 -*-
"""
Plan Executor V2 — real step-by-step execution with data passing between steps.
"""
import time, logging
from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from .plan_builder import ExecutionPlan, PlanStep

log = logging.getLogger("planning")


@dataclass
class StepResult:
    step_type: str
    success: bool = True
    output: Any = None
    error: str = ""
    latency_ms: int = 0


@dataclass
class PlanResult:
    steps_completed: list[StepResult] = field(default_factory=list)
    step_outputs: dict[str, Any] = field(default_factory=dict)
    requires_buffered_output: bool = True
    requires_sc: bool = True
    total_latency_ms: int = 0
    failed_step: str = ""
    plan_adjusted: bool = False


class PlanExecutor:
    """
    Executes plan steps, passing outputs between them.
    Actual RAG/LLM calls are delegated to callbacks provided by the caller.
    """

    def __init__(self):
        self._callbacks: dict[str, Callable] = {}

    def register_callback(self, step_type: str, fn: Callable):
        """Register an async callback for a step type."""
        self._callbacks[step_type] = fn

    async def execute(self, plan: ExecutionPlan, initial_context: dict = None) -> PlanResult:
        t0 = time.perf_counter()
        result = PlanResult(
            requires_buffered_output=plan.requires_buffered_output,
            requires_sc=plan.requires_sc,
        )
        ctx = dict(initial_context or {})

        for step in plan.steps:
            st0 = time.perf_counter()

            # Check if a callback is registered for this step
            callback = self._callbacks.get(step.step_type)

            try:
                if callback:
                    # Execute actual callback with accumulated context
                    step_output = await callback(step, ctx)
                    # Store output for later steps
                    if step.output_key and step_output is not None:
                        ctx[step.output_key] = step_output
                        result.step_outputs[step.output_key] = step_output

                    ms = int((time.perf_counter() - st0) * 1000)
                    result.steps_completed.append(StepResult(
                        step_type=step.step_type, success=True,
                        output=step_output, latency_ms=ms))
                    log.info("[PLAN_EXEC] step=%s ok output_key=%s ms=%d",
                             step.step_type, step.output_key, ms)
                else:
                    # No callback — mark as delegation point
                    ms = int((time.perf_counter() - st0) * 1000)
                    result.steps_completed.append(StepResult(
                        step_type=step.step_type, success=True, latency_ms=ms))
                    log.info("[PLAN_EXEC] step=%s delegated ms=%d", step.step_type, ms)

            except Exception as e:
                ms = int((time.perf_counter() - st0) * 1000)
                sr = StepResult(step_type=step.step_type, success=False,
                                error=str(e), latency_ms=ms)
                result.steps_completed.append(sr)

                if step.skip_if_failed:
                    log.warning("[PLAN_EXEC] step=%s failed (skippable): %s", step.step_type, e)
                    # Adjust plan if a skippable step fails
                    result.plan_adjusted = True
                else:
                    log.error("[PLAN_EXEC] step=%s failed (required): %s", step.step_type, e)
                    result.failed_step = step.step_type
                    break

        result.total_latency_ms = int((time.perf_counter() - t0) * 1000)
        log.info("[PLAN_EXEC] done: %d/%d steps, %dms, adjusted=%s",
                 sum(1 for s in result.steps_completed if s.success),
                 len(plan.steps), result.total_latency_ms, result.plan_adjusted)
        return result
