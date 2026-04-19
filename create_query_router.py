# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
lines = open('main.py', encoding='utf-8').readlines()

# Query router: lines 3548-5087 (0-indexed: 3547-5087)
query_body = ''.join(lines[3547:5088])

replacements = [
    ('@app.get(', '@router.get('),
    ('@app.post(', '@router.post('),
    ('@app.delete(', '@router.delete('),
    ('@app.put(', '@router.put('),
    ('_GW_AVAILABLE', 'app_state.GW_AVAILABLE'),
    ('_llm_gw', 'app_state.llm_gw'),
    ('_pool', 'app_state.pool'),
    ('_SCS_AVAILABLE', 'app_state.SCS_AVAILABLE'),
    ('_get_cache_service', 'app_state.get_cache_service'),
    ('_LS_AVAILABLE', 'app_state.LS_AVAILABLE'),
    ('_get_logger_service', 'app_state.get_logger_service'),
    ('_SS_AVAILABLE', 'app_state.SS_AVAILABLE'),
    ('_get_search_service', 'app_state.get_search_service'),
    ('_QEXP_AVAILABLE', 'app_state.QEXP_AVAILABLE'),
    ('_qexp_expand', 'app_state.qexp_expand'),
    ('_qexp_entities', 'app_state.qexp_entities'),
    ('_qexp_synonyms', 'app_state.qexp_synonyms'),
    ('_CB_AVAILABLE', 'app_state.CB_AVAILABLE'),
    ('_build_citations', 'app_state.build_citations'),
    ('_SCORER_AVAILABLE', 'app_state.SCORER_AVAILABLE'),
    ('_retrieval_confidence', 'app_state.retrieval_confidence'),
    ('_CTX_AVAILABLE', 'app_state.CTX_AVAILABLE'),
    ('_ctx_manager', 'app_state.ctx_manager'),
    ('_QE_AVAILABLE', 'app_state.QE_AVAILABLE'),
    ('_query_engine', 'app_state.query_engine'),
    ('_IL_AVAILABLE', 'app_state.IL_AVAILABLE'),
    ('_intelligence', 'app_state.intelligence'),
    ('_DRE_AVAILABLE', 'app_state.DRE_AVAILABLE'),
    ('_dre', 'app_state.dre'),
    ('_dre_classify', 'app_state.dre_classify'),
    ('_INTENT_ROUTER_AVAILABLE', 'app_state.INTENT_ROUTER_AVAILABLE'),
    ('_CS_AVAILABLE', 'app_state.CS_AVAILABLE'),
    ('_cs_score', 'app_state.cs_score'),
    ('_cs_action', 'app_state.cs_action'),
    ('_cs_soften', 'app_state.cs_soften'),
    ('_CS_THRESHOLD_FALLBACK', 'app_state.CS_THRESHOLD_FALLBACK'),
    ('_CS_THRESHOLD_SOFTEN', 'app_state.CS_THRESHOLD_SOFTEN'),
    ('_CE_AVAILABLE', 'app_state.CE_AVAILABLE'),
    ('_ce_ambiguity', 'app_state.ce_ambiguity'),
    ('_ce_clarify', 'app_state.ce_clarify'),
    ('_ce_build_response', 'app_state.ce_build_response'),
    ('_CE_THRESHOLD', 'app_state.CE_THRESHOLD'),
    ('_COMPRESSOR_AVAILABLE', 'app_state.COMPRESSOR_AVAILABLE'),
    ('_compress_answer', 'app_state.compress_answer'),
    ('_QL_AVAILABLE', 'app_state.QL_AVAILABLE'),
    ('_ql_low_confidence', 'app_state.ql_low_confidence'),
    ('_ql_fallback', 'app_state.ql_fallback'),
    ('_ql_clarification', 'app_state.ql_clarification'),
    ('_ql_hallucination', 'app_state.ql_hallucination'),
    ('_LDE_AVAILABLE', 'app_state.LDE_AVAILABLE'),
    ('_lde_build', 'app_state.lde_build'),
    ('_lde_apply', 'app_state.lde_apply'),
    ('_LAE_AVAILABLE', 'app_state.LAE_AVAILABLE'),
    ('_lae_build', 'app_state.lae_build'),
    ('_lae_apply', 'app_state.lae_apply'),
    ('_UA_AVAILABLE', 'app_state.UA_AVAILABLE'),
    ('_ua_analyze', 'app_state.ua_analyze'),
    ('_ua_to_mode', 'app_state.ua_to_mode'),
    ('_ua_to_frame', 'app_state.ua_to_frame'),
    ('_DR_AVAILABLE', 'app_state.DR_AVAILABLE'),
    ('_dr_build_prompt', 'app_state.dr_build_prompt'),
    ('_dr_ollama_prompt', 'app_state.dr_ollama_prompt'),
    ('_dr_fallback_prompt', 'app_state.dr_fallback_prompt'),
    ('_dr_max_tokens', 'app_state.dr_max_tokens'),
    ('_dr_temperature', 'app_state.dr_temperature'),
    ('_LP_AVAILABLE', 'app_state.LP_AVAILABLE'),
    ('_lp_perfect', 'app_state.lp_perfect'),
    ('_lp_rules', 'app_state.lp_rules'),
    ('_CG_AVAILABLE', 'app_state.CG_AVAILABLE'),
    ('_cg_mmr', 'app_state.cg_mmr'),
    ('_cg_validate', 'app_state.cg_validate'),
    ('_cg_grounding', 'app_state.cg_grounding'),
    ('_cg_multi_domain_q', 'app_state.cg_multi_domain_q'),
    ('_cg_merge_domains', 'app_state.cg_merge_domains'),
    ('_LRE_AVAILABLE', 'app_state.LRE_AVAILABLE'),
    ('_lre_build', 'app_state.lre_build'),
    ('_lre_apply', 'app_state.lre_apply'),
    ('_PH_AVAILABLE', 'app_state.PH_AVAILABLE'),
    ('_ph_rate_check', 'app_state.ph_rate_check'),
    # intent_router functions from app_state
    ('classify_intent(', 'app_state.classify_intent('),
    ('route_mode(', 'app_state.route_mode('),
    ('normalize_to_legal_query(', 'app_state.normalize_to_legal_query('),
    ('extract_legal_meaning(', 'app_state.extract_legal_meaning('),
    ('apply_domain_boost(', 'app_state.apply_domain_boost('),
    ('validate_primary_source(', 'app_state.validate_primary_source('),
    ('check_alignment(', 'app_state.check_alignment('),
    ('detect_user_level(', 'app_state.detect_user_level('),
    ('get_user_aware_instruction(', 'app_state.get_user_aware_instruction('),
    ('build_multi_queries(', 'app_state.build_multi_queries('),
    ('build_structured_context(', 'app_state.build_structured_context('),
    ('get_mode_system_prompt(', 'app_state.get_mode_system_prompt('),
    ('get_fallback_system(', 'app_state.get_fallback_system('),
    ('build_legal_writing_prompt(', 'app_state.build_legal_writing_prompt('),
    ('build_emotional_to_legal_prompt(', 'app_state.build_emotional_to_legal_prompt('),
    ('self_critique_answer(', 'app_state.self_critique_answer('),
    ('adjust_generation_strategy(', 'app_state.adjust_generation_strategy('),
    ('get_answer_opening(', 'app_state.get_answer_opening('),
    # intent_router constants
    ('CONVERSATION_SYSTEM', 'app_state.CONVERSATION_SYSTEM'),
    ('LEGAL_WRITING_SYSTEM', 'app_state.LEGAL_WRITING_SYSTEM'),
    ('FALLBACK_REASONING_SYSTEM', 'app_state.FALLBACK_REASONING_SYSTEM'),
    ('ANSWER_STRATEGY_HINT', 'app_state.ANSWER_STRATEGY_HINT'),
]

for old, new in replacements:
    query_body = query_body.replace(old, new)

header = '''# -*- coding: utf-8 -*-
"""
routers/query_router.py - Main query endpoints (JSON and SSE streaming).
"""
import re, json, time, asyncio, logging
from typing import Optional, AsyncIterator
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from core import app_state
from core.config import (
    ANTHROPIC_KEY, GEMINI_KEY, OPENAI_KEY,
    MODEL_CLAUDE_FAST, PRIMARY_MODEL,
)
from core.prompts import (
    EXPERT_SYSTEM, OLLAMA_EXPERT_SYSTEM, GENERAL_SYSTEM,
    QATAR_LEGAL_PROMPT, COT_SYSTEM, RERANK_SYSTEM,
)
from core.nlp_utils import (
    normalize_ar, make_mizan_link, extract_kw, extract_phrases,
    get_history, add_to_history,
    classify_query, _get_instant_response,
    _check_retrieval_relevance, _has_clear_legal_domain,
    _chain_of_verification, verify_citations,
    build_context, build_context_smart,
    _build_context_prefix, _run_background_summarize,
    _semantic_local_rerank, _CHINESE_RE,
)
from core.db_utils import log_query, check_cache, save_to_cache
from services.llm_service import (
    _generate_answer, stream_ollama, stream_gemini, call_claude, stream_claude,
    stream_openai,
    chain_of_thought, embed, search, rerank, keyword_search, merge,
    _deduplicate_chunks, _deduplicate_law_versions,
)

log = logging.getLogger(__name__)
router = APIRouter()

'''

full = header + query_body

with open('routers/query_router.py', 'w', encoding='utf-8') as f:
    f.write(full)

print(f"Written {len(full.splitlines())} lines")
