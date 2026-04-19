# -*- coding: utf-8 -*-
"""
Tool Executor V2 — execution + structural validation + legal-aware validation.
"""
import logging
from .schemas import ToolCall, ToolOutput, ToolValidation, ToolName
from .tool_registry import TOOL_REGISTRY

log = logging.getLogger("orchestration")

MAX_RETRIES = 1

# Legal rules for calculator validation
_EOS_LEGAL_RULES = {
    "min_years": 1,
    "max_years": 50,
    "min_salary": 500,
    "max_salary": 500000,
    "weeks_per_year": 3,  # Article 54: 3 weeks per year
}


def _validate_structural(tool_name: ToolName, result: dict) -> list[str]:
    """Structural validation: schema, non-null, type checks."""
    issues = []
    if not result:
        return ["نتيجة فارغة"]
    if "error" in result:
        return [result["error"]]
    if tool_name in (ToolName.END_OF_SERVICE, ToolName.UNFAIR_DISMISSAL):
        reward = result.get("reward") or result.get("total") or 0
        if reward < 0:
            issues.append("قيمة سالبة")
        if reward > 10_000_000:
            issues.append(f"قيمة عالية جداً: {reward:,.0f}")
    if tool_name in (ToolName.ARTICLE_LOOKUP, ToolName.TABLE_LOOKUP):
        if not result.get("found", False):
            issues.append(result.get("error", "لم يُعثر"))
    return issues


def _validate_legal(tool_name: ToolName, result: dict, call_args: dict) -> list[str]:
    """Legal-aware validation: consistency with Qatari labor law rules."""
    issues = []

    if tool_name == ToolName.END_OF_SERVICE:
        salary = call_args.get("salary", 0)
        years = call_args.get("years", 0)
        reward = result.get("reward", 0)

        # Check: 3 weeks per year (Article 54)
        expected_weekly = salary / 4.33
        expected_reward = expected_weekly * 3 * years
        if reward > 0 and abs(reward - expected_reward) > 1:
            issues.append(f"[TOOL_VALIDATE] حساب غير متطابق مع المادة 54: متوقع={expected_reward:.0f} فعلي={reward:.0f}")

        # Check: years sanity
        if years > _EOS_LEGAL_RULES["max_years"]:
            issues.append(f"سنوات خدمة غير واقعية: {years}")
        if salary > _EOS_LEGAL_RULES["max_salary"]:
            issues.append(f"راتب مرتفع جداً: {salary:,.0f}")

    elif tool_name == ToolName.UNFAIR_DISMISSAL:
        salary = call_args.get("salary", 0)
        years = call_args.get("years", 0)
        total = result.get("total", 0)

        # Article 49: minimum 2 months salary
        min_dismissal = salary * 2
        dismissal_comp = result.get("dismissal_comp", 0)
        if dismissal_comp > 0 and dismissal_comp < min_dismissal:
            issues.append(f"[TOOL_VALIDATE] تعويض أقل من الحد الأدنى (شهرين): {dismissal_comp:,.0f} < {min_dismissal:,.0f}")

        # Total sanity
        if total > salary * 200:
            issues.append(f"[TOOL_VALIDATE] إجمالي مبالغ فيه: {total:,.0f}")

    elif tool_name == ToolName.ARTICLE_LOOKUP:
        content = result.get("content", "")
        if result.get("found") and len(content) < 20:
            issues.append("[TOOL_VALIDATE] نص المادة قصير جداً — قد يكون غير مكتمل")

    return issues


def _build_result_text(tool_name: ToolName, result: dict, legal_issues: list[str]) -> str:
    """Build readable text, including legal caveats if validation found issues."""
    text = ""
    caveat = ""
    if legal_issues:
        caveat = "\n\n> ⚠️ **ملاحظة**: " + " | ".join(legal_issues[:2])

    if tool_name == ToolName.END_OF_SERVICE:
        r = result
        text = (
            f"🧮 **مكافأة نهاية الخدمة:**\n"
            f"• الراتب: {r.get('salary',0):,.0f} ريال\n"
            f"• المدة: {int(r.get('years',0))} سنة\n"
            f"• **المكافأة: {r.get('reward',0):,.0f} ريال**\n"
            f"📎 {r.get('legal_basis','')}"
        )
    elif tool_name == ToolName.UNFAIR_DISMISSAL:
        text = f"🧮 **تعويض الفصل التعسفي:**\n{result.get('breakdown','')}\n📎 {result.get('legal_basis','')}"
    elif tool_name in (ToolName.ARTICLE_LOOKUP, ToolName.TABLE_LOOKUP):
        text = result.get("content", "") if result.get("found") else result.get("error", "لم يُعثر")
    else:
        text = str(result)

    return text + caveat


async def execute_tool(call: ToolCall, pool=None) -> tuple[ToolOutput, ToolValidation]:
    spec = TOOL_REGISTRY.get(call.tool_name)
    if not spec:
        return (
            ToolOutput(tool_name=call.tool_name, success=False, error="أداة غير مسجّلة"),
            ToolValidation(tool_name=call.tool_name, valid=False, issues=["أداة غير مسجّلة"]))

    for arg in spec.required_args:
        if arg not in call.arguments or not call.arguments[arg]:
            return (
                ToolOutput(tool_name=call.tool_name, success=False, error=f"وسيط ناقص: {arg}"),
                ToolValidation(tool_name=call.tool_name, valid=False, issues=[f"وسيط ناقص: {arg}"]))

    for attempt in range(MAX_RETRIES + 1):
        try:
            args = dict(call.arguments)
            if spec.needs_pool:
                args["pool"] = pool
            result = (await spec.fn(**args)) if spec.is_async else spec.fn(**args)

            # Layer 1: Structural validation
            struct_issues = _validate_structural(call.tool_name, result)
            # Layer 2: Legal-aware validation
            legal_issues = _validate_legal(call.tool_name, result, call.arguments)

            all_issues = struct_issues + legal_issues
            valid = len(struct_issues) == 0  # structural failures = invalid; legal warnings = valid but flagged

            result_text = _build_result_text(call.tool_name, result, legal_issues)

            output = ToolOutput(
                tool_name=call.tool_name, success=valid,
                result=result, result_text=result_text,
                error="; ".join(struct_issues) if struct_issues else "")

            validation = ToolValidation(
                tool_name=call.tool_name, valid=valid, issues=all_issues)

            log.info("[TOOL] %s: valid=%s struct=%s legal=%s",
                     call.tool_name.value, valid, struct_issues[:2], legal_issues[:2])
            return output, validation

        except Exception as e:
            log.warning("[TOOL] %s attempt %d: %s", call.tool_name.value, attempt + 1, e)
            if attempt == MAX_RETRIES:
                return (
                    ToolOutput(tool_name=call.tool_name, success=False, error=str(e)),
                    ToolValidation(tool_name=call.tool_name, valid=False, issues=[str(e)]))

    return (
        ToolOutput(tool_name=call.tool_name, success=False, error="فشل"),
        ToolValidation(tool_name=call.tool_name, valid=False, issues=["فشل"]))
