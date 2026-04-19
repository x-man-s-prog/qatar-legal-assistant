# -*- coding: utf-8 -*-
"""
core/smart_reranker.py — Smart Reranker
=========================================
Implements two reranking strategies:

1. LLM Rerank — Uses the LLM to judge relevance of each chunk
   (More accurate, ~500ms per query, uses existing API keys)

2. Cross-Encoder Rerank — Uses a local cross-encoder model
   (Fastest, ~50ms per query, requires model download)

Architecture:
    query + chunks → reranker → scored_chunks → sorted by relevance

The LLM reranker is the default since it requires no additional dependencies.
"""
import re
import json
import logging
import time
from typing import Optional, Callable

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Strategy 1: LLM Reranker
# ══════════════════════════════════════════════════════════

_RERANK_SYSTEM = """أنت محكّم لتقييم صلة النصوص القانونية بالسؤال المطروح.
لكل نص، أعطِ درجة من 0 إلى 10:
- 10: النص يجيب مباشرة على السؤال
- 7-9: النص مرتبط جداً ويحتوي معلومات مفيدة
- 4-6: النص مرتبط جزئياً
- 1-3: النص بعيد عن الموضوع
- 0: لا علاقة إطلاقاً

أجب بـ JSON فقط: {"scores": [score1, score2, ...]}"""


async def llm_rerank(
    query: str,
    chunks: list[dict],
    llm_caller: Optional[Callable] = None,
    top_k: int = 8,
) -> list[dict]:
    """
    Rerank chunks using LLM judgment.

    Args:
        query: User question
        chunks: List of chunk dicts with 'content', 'law_name', 'score'
        llm_caller: async fn(system, messages, max_tokens) → str
        top_k: Max results to return

    Returns:
        Reranked chunks with updated scores
    """
    if not chunks or not llm_caller:
        return chunks[:top_k]

    t_start = time.time()

    # Build evaluation prompt
    eval_parts = []
    for i, ch in enumerate(chunks[:10]):  # Max 10 chunks for efficiency
        content_preview = ch.get("content", "")[:300]
        law_name = ch.get("law_name", "")
        eval_parts.append(f"[نص {i+1}] {law_name}:\n{content_preview}")

    eval_prompt = (
        f"السؤال: {query}\n\n"
        f"النصوص القانونية:\n{''.join(eval_parts)}\n\n"
        f"قيّم صلة كل نص بالسؤال (0-10). أجب بـ JSON: {{\"scores\": [...]}} فقط."
    )

    try:
        response = await llm_caller(
            _RERANK_SYSTEM,
            [{"role": "user", "content": eval_prompt}],
            200
        )

        # Parse JSON response
        json_match = re.search(r'\{[^}]*"scores"\s*:\s*\[[\d\s,\.]+\][^}]*\}', response)
        if json_match:
            result = json.loads(json_match.group())
            scores = result.get("scores", [])

            # Apply LLM scores
            for i, ch in enumerate(chunks[:len(scores)]):
                llm_score = float(scores[i]) / 10.0  # Normalize to 0-1
                original_score = float(ch.get("score", 0))
                # Weighted average: 60% LLM, 40% original
                ch["rerank_score"] = 0.6 * llm_score + 0.4 * original_score
                ch["llm_relevance"] = llm_score

            # Sort by rerank score
            chunks = sorted(chunks, key=lambda x: x.get("rerank_score", x.get("score", 0)), reverse=True)

            latency = int((time.time() - t_start) * 1000)
            log.info("llm_rerank: %d chunks scored in %dms", len(scores), latency)
        else:
            log.debug("llm_rerank: could not parse response")
    except Exception as e:
        log.debug("llm_rerank error (non-critical): %s", e)

    return chunks[:top_k]


# ══════════════════════════════════════════════════════════
# Strategy 2: Heuristic Cross-Encoder (no model download)
# ══════════════════════════════════════════════════════════

def heuristic_rerank(
    query: str,
    chunks: list[dict],
    top_k: int = 8,
) -> list[dict]:
    """
    Rerank using advanced heuristics that simulate cross-encoder behavior.
    Uses: keyword overlap, legal term matching, article number matching,
    domain relevance, and content quality signals.

    This is a zero-dependency alternative to model-based reranking.
    """
    if not chunks:
        return []

    t_start = time.time()
    query_lower = query.strip().lower()
    query_words = set(re.findall(r'[\u0600-\u06FF]+', query))

    # Extract article numbers from query
    query_articles = set(re.findall(r'(\d{1,4})', query))

    # Legal domain keywords
    _DOMAIN_KEYWORDS = {
        "criminal": {"عقوبة","جريمة","سرقة","قتل","ضرب","مخدرات","تعاطي","حبس","غرامة","جنحة","جناية"},
        "labor": {"عمل","فصل","راتب","إجازة","عامل","صاحب العمل","استقالة","مكافأة","خدمة"},
        "family": {"طلاق","حضانة","نفقة","زواج","خلع","عدة","أسرة","ميراث","وصية"},
        "civil": {"عقد","إيجار","تعويض","ضمان","ملكية","بيع","شراء"},
        "traffic": {"مرور","رخصة","حادث","مخالفة"},
    }

    # Detect query domain
    query_domain = ""
    max_overlap = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        overlap = len(query_words & keywords)
        if overlap > max_overlap:
            max_overlap = overlap
            query_domain = domain

    for ch in chunks:
        content = ch.get("content", "")
        content_words = set(re.findall(r'[\u0600-\u06FF]+', content.lower()))
        law_name = ch.get("law_name", "").lower()
        article_num = ch.get("article_number", "")
        original_score = float(ch.get("score", 0))

        boost = 0.0

        # 1. Keyword overlap (most important)
        word_overlap = len(query_words & content_words)
        boost += min(word_overlap * 0.03, 0.15)

        # 2. Article number match
        if article_num and article_num in query_articles:
            boost += 0.25  # Strong signal

        # 3. Domain relevance
        if query_domain:
            domain_kw = _DOMAIN_KEYWORDS.get(query_domain, set())
            domain_overlap = len(domain_kw & content_words)
            boost += min(domain_overlap * 0.02, 0.1)

        # 4. Content quality signals
        if len(content) > 200:
            boost += 0.02  # Prefer longer, more detailed chunks
        if any(kw in content for kw in ["يُعاقب","يجوز","يحق","يلتزم","يجب"]):
            boost += 0.03  # Legal operative language

        # 5. Ruling/precedent match for precedent queries
        if any(w in query for w in ["حكم","تمييز","قضاء","مبدأ"]):
            if "تمييز" in law_name or "أحكام" in law_name:
                boost += 0.1

        # 6. Penalty for irrelevant domain
        if query_domain:
            domain_kw = _DOMAIN_KEYWORDS.get(query_domain, set())
            if not (domain_kw & content_words) and query_domain in ("criminal", "family"):
                boost -= 0.1  # Strong penalty for wrong domain in strict areas

        ch["rerank_score"] = min(1.0, original_score + boost)
        ch["heuristic_boost"] = round(boost, 3)

    # Sort by rerank score
    chunks = sorted(chunks, key=lambda x: x.get("rerank_score", 0), reverse=True)

    latency = int((time.time() - t_start) * 1000)
    log.info("heuristic_rerank: %d chunks in %dms (domain=%s)", len(chunks), latency, query_domain or "none")

    return chunks[:top_k]


# ══════════════════════════════════════════════════════════
# Unified Interface
# ══════════════════════════════════════════════════════════

async def smart_rerank(
    query: str,
    chunks: list[dict],
    llm_caller: Optional[Callable] = None,
    strategy: str = "auto",
    top_k: int = 8,
) -> list[dict]:
    """
    Smart reranking with automatic strategy selection.

    Strategies:
        "auto"      — LLM if available, heuristic fallback
        "llm"       — Force LLM reranking
        "heuristic" — Force heuristic reranking

    Returns reranked chunks.
    """
    if not chunks:
        return []

    if strategy == "llm" or (strategy == "auto" and llm_caller):
        result = await llm_rerank(query, chunks, llm_caller, top_k)
        # Verify LLM actually scored them
        if any(ch.get("rerank_score") for ch in result):
            return result

    # Fallback to heuristic
    return heuristic_rerank(query, chunks, top_k)
