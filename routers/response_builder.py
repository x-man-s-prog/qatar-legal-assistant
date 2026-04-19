# -*- coding: utf-8 -*-
"""
routers/response_builder.py — Response Building & Post-Processing
==================================================================
Verification → Citation guard → Self-critique → Language perfection →
Compression → Confidence scoring → Legal reasoning engines
"""
import logging
from core import app_state
from core.nlp_utils import _chain_of_verification
from services.llm_service import verify_citations

log = logging.getLogger(__name__)


async def post_process_answer(
    answer: str,
    relevant: list,
    normalized_q: str,
    q: str,
    cot: dict,
    unified_analysis: dict,
    semantic_frame: dict,
    user_level: str,
    mode: str,
    is_ollama: bool,
    fast_llm=None,
    effective_domain: str = "",
    sid: str = "default",
) -> tuple[str, list, float, str]:
    """
    Full post-processing pipeline.
    Returns (answer, all_warnings, conf_score, conf_action).
    """
    all_warnings = []
    conf_score = 0.0
    conf_action = "ok"

    # Ollama format
    if is_ollama and app_state.IL_AVAILABLE and answer:
        try:
            answer = app_state.intelligence.format_answer_basic(answer)
        except Exception:
            pass

    # Response Opening
    if not app_state.DR_AVAILABLE and app_state.INTENT_ROUTER_AVAILABLE and answer and not is_ollama:
        try:
            opening = app_state.get_answer_opening(semantic_frame, cot.get("complexity", "بسيط"), mode, answer)
            if opening:
                first_char = answer.lstrip()[:1]
                if first_char not in ("📋", "⚖️", "🔍", "✅", "⚠️", ">", "#"):
                    answer = opening + answer
        except Exception:
            pass

    # Chain of Verification
    answer, cov_warnings = _chain_of_verification(answer, relevant, normalized_q)
    answer, hallucinated = verify_citations(answer, relevant)
    all_warnings = list(set(cov_warnings + hallucinated))

    # Citation Guard
    if app_state.CG_AVAILABLE and answer and relevant and not is_ollama:
        try:
            answer, cg_hallucinated = app_state.cg_validate(answer, relevant, strict=True)
            if cg_hallucinated:
                all_warnings = list(set(all_warnings + cg_hallucinated))
                if app_state.QL_AVAILABLE:
                    app_state.ql_hallucination(q, cg_hallucinated[:3], sid)
                log.warning("citation_guard: %d hallucinations suppressed", len(cg_hallucinated))
        except Exception:
            pass

    # Self-Critique
    complexity = cot.get("complexity", "بسيط") if cot else "بسيط"
    if (app_state.INTENT_ROUTER_AVAILABLE and not is_ollama
            and complexity in ("معقد", "متوسط")
            and mode in ("legal_pipeline", "emotional_legal")):
        try:
            answer = await app_state.self_critique_answer(
                question=q, answer=answer, llm_caller=fast_llm, max_tokens=3000
            )
        except Exception:
            pass

    # Contradiction Detection
    if (app_state.INTENT_ROUTER_AVAILABLE and not is_ollama and relevant
            and effective_domain in ("criminal", "labor", "family", "civil")):
        try:
            answer = await app_state.check_alignment(
                answer=answer, chunks=relevant, question=q,
                llm_caller=fast_llm, max_tokens=2500
            )
        except Exception:
            pass

    # Language Perfection
    if app_state.LP_AVAILABLE and answer and not is_ollama:
        try:
            lp_analysis = unified_analysis if unified_analysis else {
                "user_goal": "معلومة",
                "emotional_state": "محايد",
                "user_level": user_level,
            }
            answer = await app_state.lp_perfect(
                answer, lp_analysis, q,
                llm_caller=(fast_llm if lp_analysis.get("user_level") == "expert" else None)
            )
        except Exception:
            pass

    # Compression
    if app_state.COMPRESSOR_AVAILABLE and answer:
        try:
            answer = await app_state.compress_answer(answer, llm_caller=None, use_llm=False)
        except Exception:
            pass

    # Confidence Scoring
    if app_state.CS_AVAILABLE and answer and relevant:
        try:
            conf_score = app_state.cs_score(answer, relevant, q)
            conf_action = app_state.cs_action(conf_score)

            if conf_action == "soften":
                answer = app_state.cs_soften(answer, conf_score)
                if app_state.QL_AVAILABLE:
                    app_state.ql_low_confidence(q, answer, conf_score, effective_domain, sid)
            elif conf_action == "fallback":
                if app_state.QL_AVAILABLE:
                    app_state.ql_fallback(q, f"confidence={conf_score:.1f}", effective_domain, sid)
                answer = (
                    f"> ⚠️ **تنبيه مهم**: درجة الثقة منخفضة ({conf_score:.0f}%). "
                    "قد تكون بعض المعلومات غير دقيقة. يُرجى التحقق من بوابة الميزان أو مستشار قانوني.\n\n"
                    + answer
                )
        except Exception:
            pass

    # Log hallucinations
    if app_state.QL_AVAILABLE and hallucinated:
        try:
            app_state.ql_hallucination(q, hallucinated[:3], sid)
        except Exception:
            pass

    return answer, all_warnings, conf_score, conf_action


def apply_legal_reasoning(
    answer: str,
    q: str,
    relevant: list,
    cot: dict,
    unified_analysis: dict,
    semantic_frame: dict,
    mode: str,
    is_ollama: bool,
    effective_domain: str = "",
    conf_score: float = 0.0,
    ambiguity_score: float = 0.0,
) -> tuple[str, dict, dict]:
    """
    Apply legal reasoning engines (LRE or LDE+LAE).
    Returns (answer, legal_decision, legal_arg).
    """
    reasoning_result = {}
    legal_decision = {}
    legal_arg = {}

    if (app_state.LRE_AVAILABLE and not is_ollama
            and mode in ("legal_pipeline", "emotional_legal") and answer):
        try:
            analysis = unified_analysis if unified_analysis else {
                "domain": effective_domain,
                "legal_issue": semantic_frame.get("legal_issue", "") if semantic_frame else "",
                "action": semantic_frame.get("action", "") if semantic_frame else "",
                "actors": semantic_frame.get("actors", "") if semantic_frame else "",
                "complexity": cot.get("complexity", "متوسط") if cot else "متوسط",
                "ambiguity_score": ambiguity_score,
                "possible_claims": semantic_frame.get("possible_crimes_or_claims", []) if semantic_frame else [],
                "urgency": semantic_frame.get("urgency", "not_urgent") if semantic_frame else "not_urgent",
            }
            reasoning_result = app_state.lre_build(q, answer, analysis, relevant, mode)
            answer = app_state.lre_apply(answer, reasoning_result)
            legal_decision = reasoning_result
        except Exception:
            pass
    else:
        # Fallback: old separate engines
        if (app_state.LDE_AVAILABLE and not is_ollama
                and mode in ("legal_pipeline", "emotional_legal") and answer):
            try:
                legal_decision = app_state.lde_build(
                    question=q, answer=answer, semantic_frame=semantic_frame,
                    chunks=relevant, domain=effective_domain, mode=mode,
                    answer_confidence=float(conf_score) if app_state.CS_AVAILABLE else 75.0,
                )
                answer = app_state.lde_apply(answer, legal_decision)
            except Exception:
                pass
        if (app_state.LAE_AVAILABLE and not is_ollama
                and mode in ("legal_pipeline", "emotional_legal")
                and legal_decision.get("show_decision") and answer):
            try:
                legal_arg = app_state.lae_build(
                    question=q, semantic_frame=semantic_frame, chunks=relevant,
                    domain=effective_domain, cot=cot or {}, legal_decision=legal_decision,
                )
                answer = app_state.lae_apply(answer, legal_arg)
            except Exception:
                pass

    return answer, legal_decision, legal_arg


def build_sources_list(relevant: list) -> list:
    """Build serializable sources list from relevant chunks."""
    from core.qatar_legal_knowledge import normalize_law_name
    from core.nlp_utils import make_mizan_link

    return [{
        "title": normalize_law_name(ch.get("law_name", "") or ""),
        "law_num": ch["law_number"],
        "law_year": ch["law_year"],
        "article": ch["article_number"],
        "source": ch.get("source", ""),
        "score": round(float(ch["score"]), 3),
        "excerpt": ch["content"][:500],
        "mizan_link": make_mizan_link(ch.get("law_id"), ch["law_number"], ch["law_year"]),
    } for ch in relevant]
