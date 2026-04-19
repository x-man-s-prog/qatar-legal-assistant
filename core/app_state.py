# -*- coding: utf-8 -*-
"""
core/app_state.py — Mutable runtime state container.
Populated during lifespan startup. No local module imports.
"""
from collections import defaultdict, deque
from typing import Optional, Any

# ── DB Pool — set during lifespan ──
pool: Optional[Any] = None
embed_fn: Optional[Any] = None

# ── Session memory (fallback when ctx_manager unavailable) ──
sessions: Any = defaultdict(lambda: deque(maxlen=8))
session_ts: dict = {}

# ── Module instances — set during startup ──
ctx_manager  = None
query_engine = None
intelligence = None
dre          = None
llm_gw       = None

# ── Availability flags — set during startup ──
CTX_AVAILABLE           = False
QE_AVAILABLE            = False
IL_AVAILABLE            = False
DRE_AVAILABLE           = False
INTENT_ROUTER_AVAILABLE = False
CS_AVAILABLE            = False
CE_AVAILABLE            = False
COMPRESSOR_AVAILABLE    = False
QL_AVAILABLE            = False
LDE_AVAILABLE           = False
LAE_AVAILABLE           = False
UA_AVAILABLE            = False
DR_AVAILABLE            = False
LP_AVAILABLE            = False
CG_AVAILABLE            = False
LRE_AVAILABLE           = False
PH_AVAILABLE            = False
GW_AVAILABLE            = False
SS_AVAILABLE            = False
SCS_AVAILABLE           = False
QEXP_AVAILABLE          = False
CB_AVAILABLE            = False
SCORER_AVAILABLE        = False
LS_AVAILABLE            = False
UM_AVAILABLE            = False
RERANKER_AVAILABLE      = False
CONV_SUM_AVAILABLE      = False
QC_AVAILABLE            = False
SC_AVAILABLE            = False
SR2_AVAILABLE           = False
QP2_AVAILABLE           = False

# ── Imported module functions — set during startup (or None) ──
dre_classify   = None
cs_score       = None
cs_action      = None
cs_soften      = None
cs_relevance   = None
CS_THRESHOLD_FALLBACK = 60
CS_THRESHOLD_SOFTEN   = 80
ce_ambiguity   = None
ce_clarify     = None
ce_build_response = None
CE_THRESHOLD   = 0.6
compress_answer = None
ql_low_confidence = None
ql_fallback    = None
ql_clarification = None
ql_hallucination = None
ql_stats       = None
lde_build      = None
lde_apply      = None
lae_build      = None
lae_apply      = None
ua_analyze     = None
ua_to_mode     = None
ua_to_frame    = None
dr_build_prompt     = None
dr_ollama_prompt    = None
dr_fallback_prompt  = None
dr_max_tokens       = None
dr_temperature      = None
lp_perfect     = None
lp_rules       = None
cg_mmr         = None
cg_validate    = None
cg_grounding   = None
cg_multi_domain_q  = None
cg_merge_domains   = None
lre_build      = None
lre_apply      = None
ph_rate_check  = None
ph_health      = None
ph_cache       = None
ph_rotating_log = None
ph_rate_stats  = None

# intent_router functions
Intent                    = None
classify_intent           = None
route_mode                = None
normalize_to_legal_query  = None
extract_legal_meaning     = None
apply_domain_boost        = None
validate_primary_source   = None
check_alignment           = None
detect_user_level         = None
get_user_aware_instruction = None
build_multi_queries       = None
build_structured_context  = None
get_mode_system_prompt    = None
get_fallback_system       = None
build_legal_writing_prompt = None
build_emotional_to_legal_prompt = None
self_critique_answer      = None
CONVERSATION_SYSTEM       = ""
LEGAL_WRITING_SYSTEM      = ""
FALLBACK_REASONING_SYSTEM = ""
ANSWER_STRATEGY_HINT      = ""
adjust_generation_strategy = None
get_answer_opening        = None

# service getters
get_search_service   = None
init_search_service  = None
get_cache_service    = None
init_cache_service   = None
get_logger_service   = None
init_logger_service  = None
get_user_memory      = None
init_user_memory     = None
get_reranker         = None
init_reranker        = None
get_conversation_summarizer = None
init_conversation_summarizer = None
classify_query_fn    = None

qexp_expand    = None
qexp_entities  = None
qexp_synonyms  = None
build_citations = None
retrieval_confidence = None

# Self-Correction v2
self_correction = None

# Smart Reranker v2
smart_reranker = None

# Query Planner v2
query_planner_v2 = None
qp2_analyze = None

# Metadata Filter
MF_AVAILABLE = False
metadata_filter = None

# Chunk Overlap
CO_AVAILABLE = False
chunk_overlap = None
