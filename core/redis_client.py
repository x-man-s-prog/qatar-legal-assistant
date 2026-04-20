# -*- coding: utf-8 -*-
"""
core/redis_client.py — Canonical async Redis client (Phase 2 Layer 3).

SCOPE
-----
Used by:
  • app/core/case_memory/store.py      (Layer 3 — async path)

NOT used by:
  • routers/query_router._get_redis()  (Layer 1 legacy — remains sync)

The two coexist safely because they operate on disjoint key namespaces:
  • Sync  legacy : ``answer_memory:*``
  • Async Layer 3: ``case:*``, ``case_index:*``

FUTURE MIGRATION (separate session, not this one)
-------------------------------------------------
Once other async callsites appear, the sync path in ``query_router``
can migrate here. Not done now — out of scope. Rationale captured in
``core/FINDINGS.md §8``.

PATTERN
-------
Mirrors the asyncpg pool handling pattern that stabilised Layer 2:

  • Singleton per (db, event_loop) pair — prevents cross-loop binding.
  • Lazy creation + PING verification at construction time.
  • ``_reset_redis_pool_for_loop()`` helper is **test-only**; invoked
    from ``tests/phase3/conftest.py`` to guarantee pytest isolation.

STATUS
------
Implemented in CP2 · Part A. Both ``get_redis_client`` and
``_reset_redis_pool_for_loop`` are live; rc1-rc4 exercise them.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Tuple

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Internal state — singleton cache keyed by (db_number, id(loop))
# ─────────────────────────────────────────────────────────────────

_redis_clients: Dict[Tuple[int, int], aioredis.Redis] = {}

# Connection parameters — matched to docker-compose service name.
_REDIS_HOST: str = "legal_redis"
_REDIS_PORT: int = 6379
_CONNECT_TIMEOUT: float = 2.0
_SOCKET_TIMEOUT: float = 2.0
_HEALTH_CHECK_INTERVAL: int = 30


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

async def get_redis_client(db: int = 2) -> aioredis.Redis:
    """
    Return an async Redis client bound to the **current** event loop.

    Lazy creation: the first call in a given (db, loop) pair constructs
    a fresh ``redis.asyncio.Redis`` instance, PINGs it, and caches it.
    Subsequent calls in the same (db, loop) pair return the cached
    instance — singleton-per-loop, matching Layer 2's asyncpg pattern.

    Liveness: cached clients are PINGed on every call. If the PING
    fails (stale connection, loop closed, server bounced) the entry
    is evicted and a fresh client is constructed.

    Parameters
    ----------
    db : int
        Redis logical database number. Layer 3 uses ``db=2``.

    Returns
    -------
    redis.asyncio.Redis
        Connected async client. ``await client.ping()`` returns ``True``.

    Raises
    ------
    ConnectionError / redis.exceptions.*
        Raised loudly if the server is unreachable or PING fails at
        creation. No silent fallback — the caller decides.
    """
    loop = asyncio.get_running_loop()
    key = (db, id(loop))

    cached = _redis_clients.get(key)
    if cached is not None:
        # Cheap liveness check — 2s timeout configured at creation.
        try:
            await cached.ping()
            return cached
        except Exception:
            # Stale — evict and fall through to fresh construction.
            _redis_clients.pop(key, None)

    client = aioredis.Redis(
        host=_REDIS_HOST,
        port=_REDIS_PORT,
        db=db,
        decode_responses=True,
        socket_connect_timeout=_CONNECT_TIMEOUT,
        socket_timeout=_SOCKET_TIMEOUT,
        health_check_interval=_HEALTH_CHECK_INTERVAL,
    )

    # Verify connection at creation — fail loud. No silent fallback.
    await client.ping()

    _redis_clients[key] = client
    return client


# ─────────────────────────────────────────────────────────────────
# Test-only helpers (NOT for production use)
# ─────────────────────────────────────────────────────────────────

async def _reset_redis_pool_for_loop() -> None:
    """
    Close and evict every Redis client bound to the **current** event loop.

    Why this exists
    ---------------
    ``pytest-asyncio`` creates a fresh event loop per test function by
    default. Without this helper, a client created in test-1's loop is
    cached and re-used in test-2, whose loop is different — triggering
    ``Event loop is closed`` errors identical to the asyncpg issue
    documented in ``FINDINGS §7``.

    Invoked by the autouse ``reset_case_memory_state`` fixture in
    ``tests/phase3/conftest.py``. **Never invoke from production code.**

    Idempotent: calling on a loop with no clients is a no-op.

    Note on exception handling
    --------------------------
    ``aclose()`` failures during reset are logged at DEBUG and
    swallowed — this helper exists for cleanup and must always
    succeed. This is NOT the fail-loud policy violation; it is the
    documented exception for cleanup paths (see CP2 rule 4).
    """
    loop = asyncio.get_running_loop()
    loop_id = id(loop)

    keys_to_remove = [k for k in _redis_clients.keys() if k[1] == loop_id]

    for key in keys_to_remove:
        client = _redis_clients.pop(key, None)
        if client is None:
            continue
        try:
            await client.aclose()
        except Exception as e:
            # Log-only; reset must always succeed.
            log.debug(
                "redis client close failed during reset (db=%d): %s: %s",
                key[0], type(e).__name__, e,
            )


__all__ = [
    "get_redis_client",
]
