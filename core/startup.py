# -*- coding: utf-8 -*-
"""
core/startup.py — FastAPI lifespan (DB pool + service init + cleanup)
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI

from core import app_state
from core.config import (
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    OLLAMA_HOST, SESSION_TTL,
)
from core.prompts import OLLAMA_EXPERT_SYSTEM

log = logging.getLogger(__name__)
MODEL_OLLAMA_LLM = os.getenv("MODEL_OLLAMA_LLM", "qwen2.5:1.5b")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup → yield → shutdown."""
    from core.db_utils import _ensure_learning_tables
    from services.llm_service import embed

    # ── Sentry Observability ──
    try:
        from core.observability import init_sentry
        init_sentry()
    except ImportError:
        pass

    # ── DB pool ──
    try:
        app_state.pool = await asyncio.wait_for(
            asyncpg.create_pool(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
                min_size=1, max_size=5, ssl=False,
            ),
            timeout=5.0,
        )
        log.info("✓ DB pool متصل")
        await _ensure_learning_tables()
        await _init_services(embed)
    except Exception as _db_err:
        app_state.pool = None
        log.warning("⚠️ DB غير متاحة — سيعمل التطبيق بدون DB (%s)", _db_err)

    # ── Rate Limiter (connect Redis if available) ──
    try:
        from rate_limiter import get_rate_limiter
        _rl = get_rate_limiter()
        await _rl.connect()
        log.info("✓ rate_limiter مُهيَّأ")
    except Exception as _rl_err:
        log.info("rate_limiter: %s — سيعمل بوضع in-memory", _rl_err)

    # ── DB Knowledge Activation (lifts DB chunks into KnowledgeStore) ──
    # Mode default = "persisted" → loads snapshot if exists, else does nothing.
    # Production: set DB_KNOWLEDGE_ACTIVATION_MODE=incremental (one-time bootstrap
    # via MODE=full, then switch back).
    try:
        from core.knowledge.db_activation import activate_db_knowledge
        _act = await activate_db_knowledge(app_state.pool)
        log.info("[DB_KNOWLEDGE] mode=%s completed=%s ingested=%d quarantined=%d elapsed=%.2fs",
                 _act.get("mode"), _act.get("completed"),
                 _act.get("ingested", 0), _act.get("quarantined", 0),
                 _act.get("elapsed_seconds", 0))
    except Exception as _ka_err:
        log.warning("[DB_KNOWLEDGE] activation non-fatal error: %s", _ka_err)

    asyncio.create_task(_warmup_ollama())
    asyncio.create_task(_cleanup_loop())
    yield
    if app_state.pool:
        await app_state.pool.close()


async def _init_services(embed):
    """Initialize all pool-dependent services."""
    pool = app_state.pool
    if app_state.SS_AVAILABLE and app_state.init_search_service:
        app_state.init_search_service(pool, embed_fn=embed)
        log.info("✓ search_service مُهيَّأ")
    if app_state.SCS_AVAILABLE and app_state.init_cache_service:
        app_state.init_cache_service(embed_fn=embed, ttl_seconds=3600)
        log.info("✓ cache_service مُهيَّأ")
    if app_state.LS_AVAILABLE and app_state.init_logger_service:
        _ls = app_state.init_logger_service(pool)
        asyncio.create_task(_ls.ensure_table())
        log.info("✓ logger_service مُهيَّأ")
    if app_state.UM_AVAILABLE and app_state.init_user_memory:
        _um = app_state.init_user_memory(pool)
        asyncio.create_task(_um.ensure_table())
        log.info("✓ user_memory مُهيَّأ")
    if app_state.RERANKER_AVAILABLE and app_state.init_reranker:
        app_state.init_reranker()
        log.info("✓ reranker مُهيَّأ — heuristic mode")
    if app_state.CONV_SUM_AVAILABLE and app_state.init_conversation_summarizer:
        _cs = app_state.init_conversation_summarizer(pool)
        asyncio.create_task(_cs.ensure_table())
        log.info("✓ conversation_summarizer مُهيَّأ")
    if app_state.AUTH_AVAILABLE and app_state.init_auth_service:
        _auth = app_state.init_auth_service(pool)
        asyncio.create_task(_auth.ensure_table())
        log.info("✓ auth_service مُهيَّأ")
    if app_state.FB_AVAILABLE and app_state.init_feedback_service:
        _fb = app_state.init_feedback_service(pool)
        asyncio.create_task(_fb.ensure_table())
        log.info("✓ feedback_service مُهيَّأ")


async def _warmup_ollama():
    """Pre-load Ollama model to avoid cold-start latency."""
    try:
        await asyncio.sleep(2)
        async with httpx.AsyncClient(timeout=120) as c:
            await c.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": MODEL_OLLAMA_LLM,
                    "messages": [
                        {"role": "system", "content": OLLAMA_EXPERT_SYSTEM},
                        {"role": "user",   "content": "ما هي عقوبة السرقة في القانون القطري؟"},
                    ],
                    "stream": False, "keep_alive": "30m",
                    "options": {"num_predict": 5, "num_ctx": 3072},
                },
            )
        log.info("✓ Ollama (%s) محمّل ومستعد", MODEL_OLLAMA_LLM)
    except Exception as e:
        log.warning("Ollama warm-up: %s", e)


async def _cleanup_loop():
    """Periodic session cleanup (every 5 minutes)."""
    while True:
        await asyncio.sleep(300)
        try:
            if app_state.CTX_AVAILABLE:
                app_state.ctx_manager.cleanup_expired()
            else:
                now = time.time()
                expired = [k for k, ts in app_state.session_ts.items() if now - ts > SESSION_TTL]
                for k in expired:
                    app_state.sessions.pop(k, None)
                    app_state.session_ts.pop(k, None)
                if expired:
                    log.debug("cleanup: %d جلسة منتهية حُذفت", len(expired))
        except Exception as _ce:
            log.debug("cleanup loop: %s", _ce)
