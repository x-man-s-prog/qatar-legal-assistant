# -*- coding: utf-8 -*-
"""
Tool Selector — two-layer: deterministic fast filter + LLM fallback for ambiguous cases.
"""
import re, json, logging
from typing import Callable, Optional
from .schemas import ToolName, ToolCall, PlanType, OrchestrationPlan

log = logging.getLogger("orchestration")

_SALARY_RE = re.compile(r"(?:راتب|راتبي|أتقاضى|معاش|أجر)\s*(?:الشهري|الأساسي)?\s*(\d[\d,\.]*)", re.UNICODE)
_YEARS_RE = re.compile(r"(\d+)\s*(?:سن[وة]ات?|سنه|أعوام|عام)", re.UNICODE)
_ARTICLE_RE = re.compile(r"(?:نص\s+)?(?:المادة|الماده|م\.?\s*)\s*\(?(\d{1,4})\)?", re.UNICODE)

_CALC_KEYWORDS = [
    "احسب", "حاسب", "كم مكافأة", "كم مكافاة", "كم تعويض",
    "كم يطلع", "كم يصير", "كم استحق", "كم أستحق",
    "مكافأة نهاية", "مكافاة نهاية", "نهاية خدمة",
]
_DISMISSAL_KEYWORDS = ["فصل تعسفي", "تعويض الفصل"]
_TABLE_KEYWORDS = {
    "مخدرات": ["مخدر", "مؤثر عقلي"],
    "رواتب": ["راتب", "رواتب", "درجة", "سلم"],
    "كيميائية": ["كيميائ", "سام", "محظور"],
}

# Signals that suggest tool need but rule-based can't resolve
_AMBIGUOUS_TOOL_SIGNALS = [
    "كم", "حساب", "مبلغ", "قيمة", "تكلفة", "أجر", "مستحقات",
    "المادة", "الماده", "جدول", "ملحق",
]

_LLM_TOOL_PROMPT = """أنت مساعد يحدد الأداة المطلوبة. الأدوات المتاحة:
1. end_of_service: حساب مكافأة نهاية الخدمة (يحتاج: salary, years)
2. unfair_dismissal: حساب تعويض الفصل التعسفي (يحتاج: salary, years)
3. article_lookup: البحث عن نص مادة قانونية (يحتاج: article_number, law_name اختياري)
4. table_lookup: البحث عن جدول/ملحق (يحتاج: table_type من: مخدرات/رواتب/كيميائية)
5. none: لا حاجة لأداة — إجابة من البحث القانوني

السؤال: {query}

أجب بـ JSON فقط:
{{"tool": "end_of_service|unfair_dismissal|article_lookup|table_lookup|none", "arguments": {{}}, "confidence": 0.0-1.0, "needs_rag": true/false, "reasoning": "..."}}"""


def _extract_numbers(query: str) -> tuple[float, float]:
    salary, years = 0.0, 0.0
    sm = _SALARY_RE.search(query)
    if sm:
        salary = float(sm.group(1).replace(",", ""))
    ym = _YEARS_RE.search(query)
    if ym:
        years = float(ym.group(1))
    if salary == 0 or years == 0:
        for n in re.findall(r"(\d[\d,]*)", query):
            val = float(n.replace(",", ""))
            if salary == 0 and 1000 <= val <= 500000:
                salary = val
            elif years == 0 and 1 <= val <= 50:
                years = val
    return salary, years


def _rule_based_select(query: str, brain_route: str) -> tuple[OrchestrationPlan, float]:
    """Layer 1: deterministic selection. Returns (plan, confidence)."""
    q = query.lower()

    if brain_route in ("greeting", "filler", "thanks", "review_wait", "review_document", "self_info"):
        return OrchestrationPlan(plan_type=PlanType.DIRECT, needs_tools=False), 1.0

    # Calculator
    if any(kw in q for kw in _CALC_KEYWORDS):
        salary, years = _extract_numbers(query)
        tool = ToolName.UNFAIR_DISMISSAL if any(kw in q for kw in _DISMISSAL_KEYWORDS) else ToolName.END_OF_SERVICE
        tools = [ToolCall(tool_name=tool, arguments={"salary": salary, "years": years}, reason="حساب")]
        if salary > 0 and years > 0:
            return OrchestrationPlan(plan_type=PlanType.TOOL_THEN_RAG, needs_tools=True, needs_rag=True, tool_calls=tools, reasoning="حساب + سياق"), 0.95
        return OrchestrationPlan(plan_type=PlanType.DIRECT, needs_tools=False, reasoning="أرقام ناقصة"), 0.7

    # Table
    for ttype, keywords in _TABLE_KEYWORDS.items():
        if any(kw in q for kw in keywords) and any(t in q for t in ["جدول", "ملحق", "عدد لي", "اذكر لي"]):
            tools = [ToolCall(tool_name=ToolName.TABLE_LOOKUP, arguments={"table_type": ttype}, reason=f"جدول {ttype}")]
            return OrchestrationPlan(plan_type=PlanType.TOOL_ONLY, needs_tools=True, needs_rag=False, tool_calls=tools), 0.95

    # Article
    am = _ARTICLE_RE.search(query)
    if am and any(t in q for t in ["نص المادة", "نص الماده", "عطني نص", "اكتب نص"]):
        law = ""
        for name in ["أسرة", "اسرة", "عقوبات", "عمل", "مدني", "تجار", "مرافعات"]:
            if name in q:
                law = name
                break
        tools = [ToolCall(tool_name=ToolName.ARTICLE_LOOKUP, arguments={"article_number": am.group(1), "law_name": law}, reason="نص مادة")]
        return OrchestrationPlan(plan_type=PlanType.TOOL_ONLY, needs_tools=True, needs_rag=False, tool_calls=tools), 0.95

    # Check for ambiguous signals
    signal_count = sum(1 for s in _AMBIGUOUS_TOOL_SIGNALS if s in q)
    if signal_count >= 2:
        return OrchestrationPlan(plan_type=PlanType.DIRECT, needs_tools=False, needs_rag=True), 0.4  # low confidence → trigger LLM

    return OrchestrationPlan(plan_type=PlanType.DIRECT, needs_tools=False, needs_rag=True), 0.85


_TOOL_NAME_MAP = {
    "end_of_service": ToolName.END_OF_SERVICE,
    "unfair_dismissal": ToolName.UNFAIR_DISMISSAL,
    "article_lookup": ToolName.ARTICLE_LOOKUP,
    "table_lookup": ToolName.TABLE_LOOKUP,
}


async def _llm_fallback_select(query: str, llm_caller: Callable) -> Optional[OrchestrationPlan]:
    """Layer 2: LLM-assisted selection for ambiguous cases."""
    try:
        prompt = _LLM_TOOL_PROMPT.format(query=query[:300])
        raw = await llm_caller("أجب بـ JSON فقط.", [{"role": "user", "content": prompt}])
        clean = raw.strip().strip("`").replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)

        tool_str = data.get("tool", "none")
        confidence = float(data.get("confidence", 0))
        needs_rag = bool(data.get("needs_rag", True))
        reasoning = data.get("reasoning", "")
        args = data.get("arguments", {})

        log.info("[TOOL_SELECT] LLM fallback: tool=%s conf=%.2f reason=%s", tool_str, confidence, reasoning[:60])

        if tool_str == "none" or confidence < 0.5:
            return None

        tool_name = _TOOL_NAME_MAP.get(tool_str)
        if not tool_name:
            log.warning("[TOOL_SELECT] LLM returned unknown tool: %s", tool_str)
            return None

        # Validate arguments
        if tool_name in (ToolName.END_OF_SERVICE, ToolName.UNFAIR_DISMISSAL):
            salary = float(args.get("salary", 0))
            years = float(args.get("years", 0))
            if salary <= 0 or years <= 0:
                salary, years = _extract_numbers(query)
            args = {"salary": salary, "years": years}
        elif tool_name == ToolName.ARTICLE_LOOKUP:
            if not args.get("article_number"):
                am = _ARTICLE_RE.search(query)
                if am:
                    args["article_number"] = am.group(1)
                else:
                    return None
        elif tool_name == ToolName.TABLE_LOOKUP:
            if not args.get("table_type"):
                return None

        tools = [ToolCall(tool_name=tool_name, arguments=args, reason=reasoning[:100])]
        plan_type = PlanType.TOOL_ONLY if not needs_rag else PlanType.TOOL_THEN_RAG

        return OrchestrationPlan(
            plan_type=plan_type, needs_tools=True, needs_rag=needs_rag,
            tool_calls=tools, reasoning=f"LLM: {reasoning[:80]}")

    except Exception as e:
        log.warning("[TOOL_SELECT] LLM fallback failed: %s", e)
        return None


async def select_tools_async(query: str, brain_route: str = "",
                              llm_caller: Optional[Callable] = None) -> OrchestrationPlan:
    """Two-layer tool selection: rule-based first, LLM fallback if low confidence."""
    plan, confidence = _rule_based_select(query, brain_route)
    log.info("[TOOL_SELECT] rule-based: tools=%s conf=%.2f", plan.needs_tools, confidence)

    if confidence >= 0.7 or not llm_caller:
        return plan

    # Low confidence → try LLM fallback
    log.info("[TOOL_SELECT] low confidence (%.2f), trying LLM fallback", confidence)
    llm_plan = await _llm_fallback_select(query, llm_caller)
    if llm_plan:
        return llm_plan

    return plan


def select_tools(query: str, brain_route: str = "") -> OrchestrationPlan:
    """Sync wrapper for backward compatibility."""
    plan, _ = _rule_based_select(query, brain_route)
    return plan
