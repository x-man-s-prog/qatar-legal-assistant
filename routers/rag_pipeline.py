# -*- coding: utf-8 -*-
"""
routers/rag_pipeline.py — RAG Pipeline
========================================
Search → Rerank → Context Building → Grounding
Extracted from query_router.py for maintainability.
"""
import logging
from core import app_state
from core.nlp_utils import _semantic_local_rerank, _check_retrieval_relevance, _has_clear_legal_domain
from services.llm_service import (
    chain_of_thought, search, rerank,
    _deduplicate_chunks, build_context, build_context_smart,
    filter_rag_results, build_multi_layer_context,
    _exact_article_search, _extract_article_query,
    call_claude, stream_gemini, stream_openai,
)
from core.config import ANTHROPIC_KEY, GEMINI_KEY, OPENAI_KEY, MODEL_CLAUDE_FAST
from core.timing import timing_context

log = logging.getLogger(__name__)


async def run_cot_analysis(normalized_q: str, model: str = "ollama") -> dict:
    """Run chain-of-thought analysis on the query."""
    async with timing_context("cot"):
        return await chain_of_thought(normalized_q, model=model)


def expand_queries(normalized_q: str, semantic_frame: dict, cot_queries: list, is_ollama: bool) -> tuple[list, list]:
    """
    Expand queries using query_engine + query_expander.
    Returns (queries, qe_legal_terms).
    """
    queries = list(cot_queries)
    qe_legal_terms = []

    if app_state.INTENT_ROUTER_AVAILABLE and semantic_frame:
        queries = app_state.build_multi_queries(normalized_q, semantic_frame, cot_queries)

    return queries, qe_legal_terms


async def expand_queries_with_engine(normalized_q: str, queries: list, key_terms: list,
                                       is_ollama: bool) -> tuple[list, list, list]:
    """
    Use query_engine and query_expander for additional expansion.
    Returns (queries, key_terms, qe_legal_terms).
    """
    qe_legal_terms = []

    if app_state.QE_AVAILABLE:
        try:
            rb_json = app_state.query_engine._rule_based_expand(normalized_q)
            qe_legal_terms = rb_json.get("legal_terms", [])[:5]

            if is_ollama:
                expanded_qs = await app_state.query_engine.expand_fast(normalized_q)
            else:
                async def _qe_llm(sys, msgs):
                    if ANTHROPIC_KEY:
                        return await call_claude(sys, msgs, MODEL_CLAUDE_FAST, 300)
                    elif GEMINI_KEY:
                        parts = []
                        async for t in stream_gemini(sys, msgs, max_tokens=300):
                            parts.append(t)
                        return "".join(parts)
                    return ""
                exp = await app_state.query_engine.expand(normalized_q, llm_caller=_qe_llm)
                expanded_qs = exp.get("search_queries", [])
                qe_legal_terms = exp.get("legal_terms", qe_legal_terms)[:5]
                if exp.get("law_domain") and exp["law_domain"] != "غير محدد":
                    key_terms = list(dict.fromkeys(key_terms + [exp["law_domain"]]))
            queries = list(dict.fromkeys(queries + qe_legal_terms[:3] + expanded_qs))[:6]
        except Exception as e:
            log.debug("query_engine error (non-critical): %s", e)

    if app_state.QEXP_AVAILABLE and app_state.qexp_expand:
        try:
            variants = app_state.qexp_expand(normalized_q)
            queries = list(dict.fromkeys(queries + variants))[:8]
            syns = app_state.qexp_synonyms(normalized_q) if app_state.qexp_synonyms else []
            if syns:
                key_terms = list(dict.fromkeys(key_terms + syns[:2]))
        except Exception as e:
            log.debug("query_expander (non-critical): %s", e)

    return queries, key_terms, qe_legal_terms


async def run_search(queries: list, key_terms: list, normalized_q: str,
                     search_domain: str = None, is_ollama: bool = False,
                     qe_legal_terms: list = None) -> list:
    """
    Execute RAG search + exact article search + reranking + domain boost.
    Returns ranked relevant chunks.
    """
    art_num, law_hint = _extract_article_query(normalized_q)

    async with timing_context("search"):
        chunks = await search(queries, key_terms, 5, domain=search_domain)

    # Exact article search
    if art_num and app_state.pool:
        async with app_state.pool.acquire() as conn:
            exact = await _exact_article_search(conn, art_num, search_domain, law_hint, top_k=5)
        if exact:
            existing_keys = {(c["law_name"], c["article_number"]) for c in chunks}
            for ec in exact:
                k = (ec["law_name"], ec["article_number"])
                if k not in existing_keys:
                    chunks.insert(0, ec)
                else:
                    for i, c in enumerate(chunks):
                        if (c["law_name"], c["article_number"]) == k:
                            chunks[i]["score"] = 0.99
                            chunks[i]["exact_article"] = True
                            break

    # Score filter
    relevant = [c for c in chunks
                if float(c["score"]) > 0.55
                or c.get("exact_article")
                or (c.get("keyword_match") and c.get("match_count", 0) > 0)][:8]

    # Semantic reranking
    if relevant:
        relevant = _semantic_local_rerank(normalized_q, relevant)

    # DRE reranking
    if app_state.DRE_AVAILABLE and relevant:
        try:
            cot_domain = search_domain or ""
            relevant = app_state.dre.rerank(
                normalized_q, relevant,
                extra_terms=qe_legal_terms[:5] if qe_legal_terms else None,
                domain_hint=cot_domain or None,
            )
        except Exception as e:
            log.warning("DRE (non-critical): %s", e)

    # Domain boost + source trust
    effective_domain = (search_domain or "").lower()
    if app_state.INTENT_ROUTER_AVAILABLE and relevant and effective_domain:
        relevant = app_state.apply_domain_boost(relevant, effective_domain)
        strict_domains = ("criminal", "labor", "family")
        relevant = app_state.validate_primary_source(
            relevant, effective_domain, strict=(effective_domain in strict_domains)
        )

    # Relevance check
    cot_law_domain = search_domain or ""
    if relevant and not _check_retrieval_relevance(normalized_q, relevant, extra_terms=qe_legal_terms):
        if _has_clear_legal_domain(normalized_q, cot_law_domain) or effective_domain:
            log.warning("Low coverage but domain detected — continuing (q='%s')", normalized_q[:50])
        else:
            log.warning("Irrelevant results — q='%s'", normalized_q[:60])
            relevant = []

    # Cloud reranking
    if not is_ollama and relevant:
        async with timing_context("rerank"):
            relevant = await rerank(normalized_q, relevant)

    # MMR diversity
    if app_state.CG_AVAILABLE and relevant and len(relevant) > 3 and not is_ollama:
        relevant = app_state.cg_mmr(relevant, lambda_param=0.6, top_k=8)
    elif relevant and len(relevant) > 2:
        relevant = _deduplicate_chunks(relevant)

    # Ollama relevance filter
    if is_ollama and relevant:
        top_score = max(float(c.get("dre_score") or c.get("score") or 0) for c in relevant)
        if top_score < 0.35:
            log.warning("ollama_relevance_filter: score=%.3f < 0.35 → reject (q='%s')", top_score, normalized_q[:60])
            relevant = []

    return relevant


def build_rag_context(relevant: list, is_ollama: bool, q: str) -> tuple[str, str]:
    """
    Build RAG context + knowledge base context + grounding instruction.
    Returns (context, grounding_instruction).
    """
    relevant = filter_rag_results(relevant, min_score=0.35, max_results=10)
    max_chars = 300 if is_ollama else 500

    rag_ctx = (build_multi_layer_context(relevant, max_content=max_chars)
               if not is_ollama
               else build_context_smart(relevant, max_content=max_chars, top_k=5))

    kb_ctx = ""
    if not is_ollama and app_state.pool:
        # Note: caller should await get_dynamic_knowledge_context
        pass  # handled by caller since this is async
    elif not is_ollama:
        from core.legal_knowledge_base import get_knowledge_base_context
        kb_ctx = get_knowledge_base_context(q)

    context = kb_ctx + rag_ctx if kb_ctx else rag_ctx

    grounding = ""
    if app_state.CG_AVAILABLE and not is_ollama and relevant:
        grounding = app_state.cg_grounding(relevant)

    return context, grounding
