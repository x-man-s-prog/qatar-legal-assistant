# -*- coding: utf-8 -*-
"""
core/query_planner_v2.py — Multi-Step Query Planner
=====================================================
Decomposes complex legal questions into sub-queries,
executes each independently, and merges into a coherent answer.

Architecture:
    Query → Complexity Analysis → Plan → Sub-queries → Parallel Search → Merge

Example:
    "ما هي حقوقي إذا فُصلت تعسفياً وعندي عقد محدد المدة؟"

    Decomposes to:
    1. "ما هي حقوق العامل عند الفصل التعسفي في قطر؟"
    2. "ما هي أحكام العقد محدد المدة في قانون العمل القطري؟"
    3. "ما هو التعويض عن الفصل التعسفي في العقد محدد المدة؟"
"""
import re
import json
import logging
import time
from typing import Optional, Callable

log = logging.getLogger(__name__)


# ── Complexity Detection ──

_COMPLEX_INDICATORS = {
    "conjunctions": ["و", "أو", "ثم", "بعدها", "وإذا", "وكمان", "وبعد", "لكن"],
    "multi_question": ["؟.*؟", "ما.*وما", "كيف.*وكم", "هل.*وهل"],
    "conditional": ["إذا", "لو", "في حال", "في حالة", "عند", "متى"],
    "comparison": ["الفرق بين", "مقارنة", "أيهما", "ولا"],
    "multi_topic": ["و.*قانون.*و.*قانون", "عقوبة.*و.*تعويض"],
}


def analyze_complexity(query: str) -> dict:
    """
    Analyze query complexity to decide if decomposition is needed.

    Returns:
        {
            "complexity": "simple" | "medium" | "complex",
            "score": float (0-1),
            "indicators": list[str],
            "needs_planning": bool,
            "suggested_sub_queries": int
        }
    """
    score = 0.0
    indicators = []

    # Word count
    words = query.split()
    word_count = len(words)
    if word_count > 30:
        score += 0.2
        indicators.append("long_query")
    if word_count > 50:
        score += 0.1
        indicators.append("very_long_query")

    # Question marks
    q_marks = query.count("؟")
    if q_marks >= 2:
        score += 0.3
        indicators.append(f"{q_marks}_questions")

    # Conjunctions between legal topics
    for conj in _COMPLEX_INDICATORS["conjunctions"]:
        if conj in query:
            score += 0.05

    # Conditional clauses
    for cond in _COMPLEX_INDICATORS["conditional"]:
        if cond in query:
            score += 0.1
            indicators.append(f"conditional:{cond}")

    # Comparison
    for comp in _COMPLEX_INDICATORS["comparison"]:
        if comp in query:
            score += 0.2
            indicators.append(f"comparison:{comp}")

    # Multiple legal domains
    _DOMAIN_KW = {
        "criminal": ["عقوبة", "جريمة", "حبس"],
        "labor": ["فصل", "عمل", "راتب", "مكافأة"],
        "family": ["طلاق", "حضانة", "نفقة"],
        "civil": ["تعويض", "عقد", "إيجار"],
    }
    domains_found = []
    for domain, kws in _DOMAIN_KW.items():
        if any(kw in query for kw in kws):
            domains_found.append(domain)
    if len(domains_found) >= 2:
        score += 0.3
        indicators.append(f"multi_domain:{'+'.join(domains_found)}")

    score = min(1.0, score)

    if score >= 0.5:
        complexity = "complex"
    elif score >= 0.25:
        complexity = "medium"
    else:
        complexity = "simple"

    return {
        "complexity": complexity,
        "score": round(score, 2),
        "indicators": indicators,
        "needs_planning": score >= 0.4,
        "suggested_sub_queries": min(4, max(1, int(score * 5) + 1)),
        "domains": domains_found,
    }


# ── Rule-Based Decomposition ──

def decompose_rule_based(query: str, complexity: dict) -> list[str]:
    """
    Decompose a complex query into sub-queries using rule-based patterns.
    Works without LLM — fast and reliable.
    """
    sub_queries = []

    # Strategy 1: Split on question marks
    if "؟" in query:
        parts = [p.strip() for p in query.split("؟") if len(p.strip()) > 10]
        if len(parts) >= 2:
            for p in parts[:4]:
                if not p.endswith("؟"):
                    p += "؟"
                sub_queries.append(p)

    # Strategy 2: Split on conjunctions between legal clauses
    if not sub_queries and any(ind.startswith("conditional") for ind in complexity.get("indicators", [])):
        # Split: "ما عقوبة X وإذا كان Y"
        parts = re.split(r'\s*(?:وإذا|ولو|وفي حال|ومتى)\s*', query)
        if len(parts) >= 2:
            sub_queries = [p.strip() + "؟" for p in parts if len(p.strip()) > 10]

    # Strategy 3: Split comparison into two lookups
    if not sub_queries and any(ind.startswith("comparison") for ind in complexity.get("indicators", [])):
        match = re.search(r'(?:الفرق بين|مقارنة بين)\s*(.+?)\s*(?:و|وبين)\s*(.+?)(?:\?|؟|$)', query)
        if match:
            sub_queries = [
                f"ما هو {match.group(1).strip()}؟",
                f"ما هو {match.group(2).strip()}؟",
                query,  # Also search the full comparison query
            ]

    # Strategy 4: Multi-domain → one query per domain
    if not sub_queries and len(complexity.get("domains", [])) >= 2:
        for domain in complexity["domains"]:
            # Extract the part relevant to this domain
            sub_queries.append(query)  # Use full query, domain filtering will handle it

    # Fallback: no decomposition needed
    if not sub_queries:
        sub_queries = [query]

    return sub_queries[:4]  # Max 4 sub-queries


# ── LLM-Based Decomposition ──

_PLANNER_SYSTEM = """أنت مخطط استعلامات قانونية. مهمتك تقسيم السؤال المعقد إلى أسئلة فرعية بسيطة.

قواعد:
- كل سؤال فرعي يجب أن يكون مستقل ومحدد
- لا تزيد الأسئلة عن 4
- كل سؤال فرعي يتعلق بجانب واحد فقط
- أجب بـ JSON: {"sub_queries": ["سؤال1", "سؤال2", ...], "merge_strategy": "sequential|comparative|conditional"}"""


async def decompose_with_llm(
    query: str,
    llm_caller: Optional[Callable] = None,
) -> tuple[list[str], str]:
    """
    Decompose using LLM for better understanding of intent.
    Returns (sub_queries, merge_strategy).
    """
    if not llm_caller:
        return [query], "sequential"

    try:
        prompt = f"قسّم هذا السؤال القانوني إلى أسئلة فرعية:\n{query}"
        response = await llm_caller(
            _PLANNER_SYSTEM,
            [{"role": "user", "content": prompt}],
            300
        )

        json_match = re.search(r'\{[^}]*"sub_queries"\s*:\s*\[.*?\][^}]*\}', response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            subs = result.get("sub_queries", [query])
            strategy = result.get("merge_strategy", "sequential")
            return subs[:4], strategy
    except Exception as e:
        log.debug("LLM decomposition failed: %s", e)

    return [query], "sequential"


# ── Answer Merging ──

def merge_answers(
    sub_answers: list[dict],
    strategy: str = "sequential",
    original_query: str = "",
) -> str:
    """
    Merge sub-answers into a coherent final answer.

    Args:
        sub_answers: list of {"query": str, "answer": str, "sources": list}
        strategy: "sequential" | "comparative" | "conditional"
        original_query: The original complex query

    Returns:
        Merged answer string
    """
    if not sub_answers:
        return ""

    if len(sub_answers) == 1:
        return sub_answers[0].get("answer", "")

    if strategy == "comparative":
        # Side-by-side comparison
        parts = ["📊 **مقارنة:**\n"]
        for i, sa in enumerate(sub_answers, 1):
            parts.append(f"\n**{i}. {sa.get('query', '')[:80]}**\n{sa['answer']}\n")
        parts.append("\n---\n**الخلاصة:** ")
        return "\n".join(parts)

    elif strategy == "conditional":
        # Present conditions and outcomes
        parts = ["⚖️ **التحليل حسب الحالات:**\n"]
        for i, sa in enumerate(sub_answers, 1):
            parts.append(f"\n**الحالة {i}:** {sa.get('query', '')[:80]}\n{sa['answer']}\n")
        return "\n".join(parts)

    else:
        # Sequential merge (default)
        parts = []
        for i, sa in enumerate(sub_answers, 1):
            answer = sa.get("answer", "")
            if len(sub_answers) > 1:
                # Add section headers for multi-part answers
                parts.append(f"\n**{i}.** {answer}")
            else:
                parts.append(answer)
        return "\n".join(parts)


# ══ Main Planner Interface ══

async def plan_and_execute(
    query: str,
    search_fn=None,
    llm_caller=None,
    use_llm_planning: bool = True,
) -> dict:
    """
    Full planning pipeline.

    Args:
        query: User question
        search_fn: async fn(queries, key_terms, top_k, domain) → chunks
        llm_caller: async fn(system, messages, max_tokens) → str
        use_llm_planning: Use LLM for decomposition (default True)

    Returns:
        {
            "complexity": dict,
            "sub_queries": list[str],
            "merge_strategy": str,
            "planned": bool,
        }
    """
    t_start = time.time()

    # Step 1: Analyze complexity
    complexity = analyze_complexity(query)

    if not complexity["needs_planning"]:
        return {
            "complexity": complexity,
            "sub_queries": [query],
            "merge_strategy": "sequential",
            "planned": False,
            "latency_ms": int((time.time() - t_start) * 1000),
        }

    # Step 2: Decompose
    if use_llm_planning and llm_caller:
        sub_queries, strategy = await decompose_with_llm(query, llm_caller)
    else:
        sub_queries = decompose_rule_based(query, complexity)
        strategy = "sequential"

    log.info("planner: complexity=%s score=%.2f → %d sub_queries (strategy=%s)",
             complexity["complexity"], complexity["score"], len(sub_queries), strategy)

    return {
        "complexity": complexity,
        "sub_queries": sub_queries,
        "merge_strategy": strategy,
        "planned": len(sub_queries) > 1,
        "latency_ms": int((time.time() - t_start) * 1000),
    }
