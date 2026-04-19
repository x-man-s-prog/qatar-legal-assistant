# -*- coding: utf-8 -*-
"""
core/modules.py — Optional module loader
=========================================
يُحمَّل كل وحدة اختيارية بشكل مستقل.
إذا فشل تحميل وحدة، تُسجَّل تحذيراً ويستمر النظام.
استدعِ load_all() مرة واحدة عند بدء التشغيل.
"""
import logging
from core import app_state

log = logging.getLogger(__name__)


def _try_load(loader_fn):
    """Wrapper: run loader_fn, catch ImportError silently."""
    try:
        loader_fn()
    except ImportError as _e:
        pass   # loader_fn logs the warning itself


def load_all():
    """Load every optional module into app_state."""
    _load_context_manager()
    _load_query_engine()
    _load_intelligence_layer()
    _load_domain_relevance()
    _load_intent_router()
    _load_confidence_scoring()
    _load_clarification_engine()
    _load_answer_compressor()
    _load_quality_logger()
    _load_legal_decision_engine()
    _load_legal_argumentation_engine()
    _load_unified_analyzer()
    _load_deep_reasoning_engine()
    _load_language_perfection()
    _load_citation_guard()
    _load_legal_reasoning_engine()
    _load_production_hardening()
    _load_llm_gateway()
    _load_search_service()
    _load_cache_service()
    _load_logger_service()
    _load_user_memory()
    _load_reranker()
    _load_conversation_summarizer()
    _load_query_classifier()
    _load_feedback_service()
    _load_auth_service()
    _load_query_expander()
    _load_citation_builder()
    _load_confidence_scorer()
    _load_self_correction()
    _load_smart_reranker_v2()
    _load_query_planner_v2()
    _load_metadata_filter()
    _load_chunk_overlap()


# ── Individual loaders ─────────────────────────────────────────

def _load_context_manager():
    try:
        from context_manager import AdvancedContextManager
        app_state.ctx_manager = AdvancedContextManager()
        app_state.CTX_AVAILABLE = True
        log.info("✓ context_manager محمّل")
    except ImportError as _e:
        app_state.ctx_manager = None
        app_state.CTX_AVAILABLE = False
        log.warning("context_manager غير متاح (%s)", _e)


def _load_query_engine():
    try:
        from query_engine import QueryExpansionEngine
        app_state.query_engine = QueryExpansionEngine()
        app_state.QE_AVAILABLE = True
        log.info("✓ query_engine محمّل")
    except ImportError as _e:
        app_state.query_engine = None
        app_state.QE_AVAILABLE = False
        log.warning("query_engine غير متاح (%s)", _e)


def _load_intelligence_layer():
    try:
        from intelligence_layer import IntelligenceLayer
        app_state.intelligence = IntelligenceLayer()
        app_state.IL_AVAILABLE = True
        log.info("✓ intelligence_layer محمّل")
    except ImportError as _e:
        app_state.intelligence = None
        app_state.IL_AVAILABLE = False
        log.warning("intelligence_layer غير متاح (%s)", _e)


def _load_domain_relevance():
    try:
        from domain_relevance_engine import DomainRelevanceEngine, classify_query_domain as _dre_classify
        app_state.dre = DomainRelevanceEngine()
        app_state.dre_classify = _dre_classify
        app_state.DRE_AVAILABLE = True
        log.info("✓ domain_relevance_engine محمّل")
    except ImportError as _e:
        app_state.dre = None
        app_state.dre_classify = None
        app_state.DRE_AVAILABLE = False
        log.warning("domain_relevance_engine غير متاح (%s)", _e)


def _load_intent_router():
    try:
        from intent_router import (
            Intent, classify_intent, route_mode, normalize_to_legal_query,
            extract_legal_meaning, apply_domain_boost, validate_primary_source,
            check_alignment, detect_user_level, get_user_aware_instruction,
            build_multi_queries, build_structured_context, get_mode_system_prompt,
            get_fallback_system, build_legal_writing_prompt, build_emotional_to_legal_prompt,
            self_critique_answer, CONVERSATION_SYSTEM, LEGAL_WRITING_SYSTEM,
            FALLBACK_REASONING_SYSTEM, ANSWER_STRATEGY_HINT,
            adjust_generation_strategy, get_answer_opening,
        )
        app_state.Intent = Intent
        app_state.classify_intent = classify_intent
        app_state.route_mode = route_mode
        app_state.normalize_to_legal_query = normalize_to_legal_query
        app_state.extract_legal_meaning = extract_legal_meaning
        app_state.apply_domain_boost = apply_domain_boost
        app_state.validate_primary_source = validate_primary_source
        app_state.check_alignment = check_alignment
        app_state.detect_user_level = detect_user_level
        app_state.get_user_aware_instruction = get_user_aware_instruction
        app_state.build_multi_queries = build_multi_queries
        app_state.build_structured_context = build_structured_context
        app_state.get_mode_system_prompt = get_mode_system_prompt
        app_state.get_fallback_system = get_fallback_system
        app_state.build_legal_writing_prompt = build_legal_writing_prompt
        app_state.build_emotional_to_legal_prompt = build_emotional_to_legal_prompt
        app_state.self_critique_answer = self_critique_answer
        app_state.CONVERSATION_SYSTEM = CONVERSATION_SYSTEM
        app_state.LEGAL_WRITING_SYSTEM = LEGAL_WRITING_SYSTEM
        app_state.FALLBACK_REASONING_SYSTEM = FALLBACK_REASONING_SYSTEM
        app_state.ANSWER_STRATEGY_HINT = ANSWER_STRATEGY_HINT
        app_state.adjust_generation_strategy = adjust_generation_strategy
        app_state.get_answer_opening = get_answer_opening
        app_state.INTENT_ROUTER_AVAILABLE = True
        log.info("✓ intent_router v3 محمّل")
    except ImportError as _e:
        app_state.INTENT_ROUTER_AVAILABLE = False
        log.warning("intent_router غير متاح (%s)", _e)


def _load_confidence_scoring():
    try:
        from confidence_scoring import (
            score_answer as _cs_score, get_confidence_action as _cs_action,
            apply_confidence_softening as _cs_soften,
            THRESHOLD_FALLBACK as _CS_THRESHOLD_FALLBACK,
            THRESHOLD_SOFTEN as _CS_THRESHOLD_SOFTEN,
            check_answer_relevance as _cs_relevance,
        )
        app_state.cs_score = _cs_score
        app_state.cs_action = _cs_action
        app_state.cs_soften = _cs_soften
        app_state.cs_relevance = _cs_relevance
        app_state.CS_THRESHOLD_FALLBACK = _CS_THRESHOLD_FALLBACK
        app_state.CS_THRESHOLD_SOFTEN = _CS_THRESHOLD_SOFTEN
        app_state.CS_AVAILABLE = True
        log.info("✓ confidence_scoring محمّل")
    except ImportError as _e:
        app_state.CS_AVAILABLE = False
        log.warning("confidence_scoring غير متاح (%s)", _e)


def _load_clarification_engine():
    try:
        from clarification_engine import (
            compute_ambiguity_score as _ce_ambiguity,
            generate_clarification_question as _ce_clarify,
            build_clarification_response as _ce_build_response,
            AMBIGUITY_THRESHOLD as _CE_THRESHOLD,
        )
        app_state.ce_ambiguity = _ce_ambiguity
        app_state.ce_clarify = _ce_clarify
        app_state.ce_build_response = _ce_build_response
        app_state.CE_THRESHOLD = _CE_THRESHOLD
        app_state.CE_AVAILABLE = True
        log.info("✓ clarification_engine محمّل")
    except ImportError as _e:
        app_state.CE_AVAILABLE = False
        log.warning("clarification_engine غير متاح (%s)", _e)


def _load_answer_compressor():
    try:
        from answer_compressor import compress_answer as _compress_answer
        app_state.compress_answer = _compress_answer
        app_state.COMPRESSOR_AVAILABLE = True
        log.info("✓ answer_compressor محمّل")
    except ImportError as _e:
        app_state.COMPRESSOR_AVAILABLE = False
        log.warning("answer_compressor غير متاح (%s)", _e)


def _load_quality_logger():
    try:
        from quality_logger import (
            log_low_confidence as _ql_low_confidence, log_fallback as _ql_fallback,
            log_clarification as _ql_clarification, log_hallucination as _ql_hallucination,
            get_recent_stats as _ql_stats,
        )
        app_state.ql_low_confidence = _ql_low_confidence
        app_state.ql_fallback = _ql_fallback
        app_state.ql_clarification = _ql_clarification
        app_state.ql_hallucination = _ql_hallucination
        app_state.ql_stats = _ql_stats
        app_state.QL_AVAILABLE = True
        log.info("✓ quality_logger محمّل")
    except ImportError as _e:
        app_state.QL_AVAILABLE = False
        log.warning("quality_logger غير متاح (%s)", _e)


def _load_legal_decision_engine():
    try:
        from legal_decision_engine import (
            build_legal_position as _lde_build,
            apply_decision_to_answer as _lde_apply,
        )
        app_state.lde_build = _lde_build
        app_state.lde_apply = _lde_apply
        app_state.LDE_AVAILABLE = True
        log.info("✓ legal_decision_engine محمّل")
    except ImportError as _e:
        app_state.LDE_AVAILABLE = False
        log.warning("legal_decision_engine غير متاح (%s)", _e)


def _load_legal_argumentation_engine():
    try:
        from legal_argumentation_engine import (
            build_legal_argumentation as _lae_build,
            apply_argumentation_to_answer as _lae_apply,
        )
        app_state.lae_build = _lae_build
        app_state.lae_apply = _lae_apply
        app_state.LAE_AVAILABLE = True
        log.info("✓ legal_argumentation_engine محمّل")
    except ImportError as _e:
        app_state.LAE_AVAILABLE = False
        log.warning("legal_argumentation_engine غير متاح (%s)", _e)


def _load_unified_analyzer():
    try:
        from unified_analyzer import (
            analyze_user_input as _ua_analyze,
            analysis_to_intent_mode as _ua_to_mode,
            analysis_to_semantic_frame as _ua_to_frame,
        )
        app_state.ua_analyze = _ua_analyze
        app_state.ua_to_mode = _ua_to_mode
        app_state.ua_to_frame = _ua_to_frame
        app_state.UA_AVAILABLE = True
        log.info("✓ unified_analyzer محمّل")
    except ImportError as _e:
        app_state.UA_AVAILABLE = False
        log.warning("unified_analyzer غير متاح (%s)", _e)


def _load_deep_reasoning_engine():
    try:
        from deep_reasoning_engine import (
            build_deep_reasoning_prompt as _dr_build_prompt,
            build_ollama_reasoning_prompt as _dr_ollama_prompt,
            build_fallback_reasoning_prompt as _dr_fallback_prompt,
            get_max_tokens_by_complexity as _dr_max_tokens,
            get_temperature_by_risk as _dr_temperature,
        )
        app_state.dr_build_prompt = _dr_build_prompt
        app_state.dr_ollama_prompt = _dr_ollama_prompt
        app_state.dr_fallback_prompt = _dr_fallback_prompt
        app_state.dr_max_tokens = _dr_max_tokens
        app_state.dr_temperature = _dr_temperature
        app_state.DR_AVAILABLE = True
        log.info("✓ deep_reasoning_engine محمّل")
    except ImportError as _e:
        app_state.DR_AVAILABLE = False
        log.warning("deep_reasoning_engine غير متاح (%s)", _e)


def _load_language_perfection():
    try:
        from language_perfection import (
            perfect_answer as _lp_perfect,
            perfect_answer_rules as _lp_rules,
        )
        app_state.lp_perfect = _lp_perfect
        app_state.lp_rules = _lp_rules
        app_state.LP_AVAILABLE = True
        log.info("✓ language_perfection محمّل")
    except ImportError as _e:
        app_state.LP_AVAILABLE = False
        log.warning("language_perfection غير متاح (%s)", _e)


def _load_citation_guard():
    try:
        from citation_guard import (
            mmr_rerank as _cg_mmr, validate_citations as _cg_validate,
            build_grounding_instruction as _cg_grounding,
            build_multi_domain_queries as _cg_multi_domain_q,
            merge_multi_domain_chunks as _cg_merge_domains,
        )
        app_state.cg_mmr = _cg_mmr
        app_state.cg_validate = _cg_validate
        app_state.cg_grounding = _cg_grounding
        app_state.cg_multi_domain_q = _cg_multi_domain_q
        app_state.cg_merge_domains = _cg_merge_domains
        app_state.CG_AVAILABLE = True
        log.info("✓ citation_guard محمّل")
    except ImportError as _e:
        app_state.CG_AVAILABLE = False
        log.warning("citation_guard غير متاح (%s)", _e)


def _load_legal_reasoning_engine():
    try:
        from legal_reasoning_engine import (
            build_legal_reasoning as _lre_build,
            apply_reasoning_to_answer as _lre_apply,
        )
        app_state.lre_build = _lre_build
        app_state.lre_apply = _lre_apply
        app_state.LRE_AVAILABLE = True
        log.info("✓ legal_reasoning_engine محمّل")
    except ImportError as _e:
        app_state.LRE_AVAILABLE = False
        log.warning("legal_reasoning_engine غير متاح (%s)", _e)


def _load_production_hardening():
    try:
        from production_hardening import (
            check_rate_limit as _ph_rate_check, get_health as _ph_health,
            response_cache as _ph_cache, rotating_logger as _ph_rotating_log,
            get_rate_limiter_stats as _ph_rate_stats,
        )
        app_state.ph_rate_check = _ph_rate_check
        app_state.ph_health = _ph_health
        app_state.ph_cache = _ph_cache
        app_state.ph_rotating_log = _ph_rotating_log
        app_state.ph_rate_stats = _ph_rate_stats
        app_state.PH_AVAILABLE = True
        log.info("✓ production_hardening محمّل")
    except ImportError as _e:
        app_state.PH_AVAILABLE = False
        log.warning("production_hardening غير متاح (%s)", _e)


def _load_llm_gateway():
    try:
        from llm_gateway import get_gateway as _get_llm_gateway
        app_state.llm_gw = _get_llm_gateway()
        app_state.GW_AVAILABLE = True
        log.info("✓ llm_gateway محمّل — المزود: %s", app_state.llm_gw.primary_provider().upper())
    except ImportError as _e:
        app_state.llm_gw = None
        app_state.GW_AVAILABLE = False
        log.warning("llm_gateway غير متاح (%s)", _e)


def _load_search_service():
    try:
        from search_service import init_search_service as _init, get_search_service as _get
        app_state.init_search_service = _init
        app_state.get_search_service  = _get
        app_state.SS_AVAILABLE = True
        log.info("✓ search_service محمّل")
    except ImportError as _e:
        app_state.init_search_service = None
        app_state.get_search_service  = None
        app_state.SS_AVAILABLE = False
        log.warning("search_service غير متاح (%s)", _e)


def _load_cache_service():
    try:
        from cache_service import init_cache_service as _init, get_cache_service as _get
        app_state.init_cache_service = _init
        app_state.get_cache_service  = _get
        app_state.SCS_AVAILABLE = True
        log.info("✓ cache_service محمّل")
    except ImportError as _e:
        app_state.init_cache_service = None
        app_state.get_cache_service  = None
        app_state.SCS_AVAILABLE = False
        log.warning("cache_service غير متاح (%s)", _e)


def _load_logger_service():
    try:
        from logger_service import init_logger_service as _init, get_logger_service as _get
        app_state.init_logger_service = _init
        app_state.get_logger_service  = _get
        app_state.LS_AVAILABLE = True
        log.info("✓ logger_service محمّل")
    except ImportError as _e:
        app_state.init_logger_service = None
        app_state.get_logger_service  = None
        app_state.LS_AVAILABLE = False
        log.warning("logger_service غير متاح (%s)", _e)


def _load_user_memory():
    try:
        from user_memory import init_user_memory as _init, get_user_memory as _get
        app_state.init_user_memory = _init
        app_state.get_user_memory  = _get
        app_state.UM_AVAILABLE = True
        log.info("✓ user_memory محمّل")
    except ImportError as _e:
        app_state.init_user_memory = None
        app_state.get_user_memory  = None
        app_state.UM_AVAILABLE = False
        log.warning("user_memory غير متاح (%s)", _e)


def _load_reranker():
    try:
        from reranker import init_reranker as _init, get_reranker as _get
        app_state.init_reranker       = _init
        app_state.get_reranker        = _get
        app_state.RERANKER_AVAILABLE  = True
        log.info("✓ reranker محمّل")
    except ImportError as _e:
        app_state.init_reranker      = None
        app_state.get_reranker       = None
        app_state.RERANKER_AVAILABLE = False
        log.warning("reranker غير متاح (%s)", _e)


def _load_conversation_summarizer():
    try:
        from conversation_summarizer import (
            init_conversation_summarizer as _init,
            get_conversation_summarizer  as _get,
        )
        app_state.init_conversation_summarizer = _init
        app_state.get_conversation_summarizer  = _get
        app_state.CONV_SUM_AVAILABLE           = True
        log.info("✓ conversation_summarizer محمّل")
    except ImportError as _e:
        app_state.init_conversation_summarizer = None
        app_state.get_conversation_summarizer  = None
        app_state.CONV_SUM_AVAILABLE           = False
        log.warning("conversation_summarizer غير متاح (%s)", _e)


def _load_query_classifier():
    try:
        from query_classifier import classify_query as _classify
        app_state.classify_query_fn = _classify
        app_state.QC_AVAILABLE      = True
        log.info("✓ query_classifier محمّل")
    except ImportError as _e:
        app_state.classify_query_fn = None
        app_state.QC_AVAILABLE      = False
        log.warning("query_classifier غير متاح (%s)", _e)


def _load_feedback_service():
    try:
        from feedback_service import init_feedback_service as _init, get_feedback_service as _get
        app_state.init_feedback_service = _init
        app_state.get_feedback_service  = _get
        app_state.FB_AVAILABLE          = True
        log.info("✓ feedback_service محمّل")
    except ImportError as _e:
        app_state.init_feedback_service = None
        app_state.get_feedback_service  = None
        app_state.FB_AVAILABLE          = False
        log.warning("feedback_service غير متاح (%s)", _e)


def _load_auth_service():
    try:
        from auth_service import init_auth_service as _init, get_auth_service as _get
        app_state.init_auth_service = _init
        app_state.get_auth_service  = _get
        app_state.AUTH_AVAILABLE    = True
        log.info("✓ auth_service محمّل")
    except ImportError as _e:
        app_state.init_auth_service = None
        app_state.get_auth_service  = None
        app_state.AUTH_AVAILABLE    = False
        log.warning("auth_service غير متاح (%s)", _e)


def _load_query_expander():
    try:
        from query_expander import (
            expand as _expand,
            extract_legal_entities as _entities,
            get_all_synonyms as _synonyms,
        )
        app_state.qexp_expand    = _expand
        app_state.qexp_entities  = _entities
        app_state.qexp_synonyms  = _synonyms
        app_state.QEXP_AVAILABLE = True
        log.info("✓ query_expander محمّل")
    except ImportError as _e:
        app_state.qexp_expand    = None
        app_state.qexp_entities  = None
        app_state.qexp_synonyms  = None
        app_state.QEXP_AVAILABLE = False
        log.warning("query_expander غير متاح (%s)", _e)


def _load_citation_builder():
    try:
        from citation_builder import build_citations as _build
        app_state.build_citations = _build
        app_state.CB_AVAILABLE    = True
        log.info("✓ citation_builder محمّل")
    except ImportError as _e:
        app_state.build_citations = None
        app_state.CB_AVAILABLE    = False
        log.warning("citation_builder غير متاح (%s)", _e)


def _load_confidence_scorer():
    try:
        from confidence_scorer import from_chunks as _from_chunks
        app_state.retrieval_confidence = _from_chunks
        app_state.SCORER_AVAILABLE     = True
        log.info("✓ confidence_scorer محمّل")
    except ImportError as _e:
        app_state.retrieval_confidence = None
        app_state.SCORER_AVAILABLE     = False
        log.warning("confidence_scorer غير متاح (%s)", _e)


def _load_self_correction():
    try:
        from core.self_correction import self_correct
        app_state.self_correction = self_correct
        app_state.SC_AVAILABLE = True
        log.info("✓ self_correction محمّل")
    except ImportError as _e:
        app_state.self_correction = None
        app_state.SC_AVAILABLE = False
        log.warning("self_correction غير متاح (%s)", _e)


def _load_smart_reranker_v2():
    try:
        from core.smart_reranker import smart_rerank
        app_state.smart_reranker = smart_rerank
        app_state.SR2_AVAILABLE = True
        log.info("✓ smart_reranker محمّل")
    except ImportError as _e:
        app_state.smart_reranker = None
        app_state.SR2_AVAILABLE = False
        log.warning("smart_reranker غير متاح (%s)", _e)


def _load_query_planner_v2():
    try:
        from core.query_planner_v2 import plan_and_execute, analyze_complexity
        app_state.query_planner_v2 = plan_and_execute
        app_state.qp2_analyze = analyze_complexity
        app_state.QP2_AVAILABLE = True
        log.info("✓ query_planner_v2 محمّل")
    except ImportError as _e:
        app_state.query_planner_v2 = None
        app_state.qp2_analyze = None
        app_state.QP2_AVAILABLE = False
        log.warning("query_planner_v2 غير متاح (%s)", _e)


def _load_metadata_filter():
    try:
        from core.metadata_filter import apply_metadata_filters
        app_state.metadata_filter = apply_metadata_filters
        app_state.MF_AVAILABLE = True
        log.info("✓ metadata_filter محمّل")
    except ImportError as _e:
        app_state.MF_AVAILABLE = False
        log.warning("metadata_filter غير متاح (%s)", _e)


def _load_chunk_overlap():
    try:
        from core.chunk_overlap import expand_relevant_chunks
        app_state.chunk_overlap = expand_relevant_chunks
        app_state.CO_AVAILABLE = True
        log.info("✓ chunk_overlap محمّل")
    except ImportError as _e:
        app_state.CO_AVAILABLE = False
        log.warning("chunk_overlap غير متاح (%s)", _e)
