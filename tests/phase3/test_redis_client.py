# -*- coding: utf-8 -*-
"""
tests/phase3/test_redis_client.py — unit tests rc1..rc4.

Validates the canonical async Redis client introduced for Layer 3
(see ``FINDINGS §8``).

STATUS
------
CP2 · Part A — live. All four tests exercise the real implementation
in ``core.redis_client``.
"""
import asyncio

import pytest

from core.redis_client import (
    _redis_clients,
    _reset_redis_pool_for_loop,
    get_redis_client,
)


# ─────────────────────────────────────────────────────────────────
# rc1 — client connects and PINGs
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rc1_get_client_returns_connected():
    """``get_redis_client(db=2)`` returns a client whose ``ping()``
    returns ``True`` (async redis returns bool, not ``b"PONG"``)."""
    client = await get_redis_client(db=2)
    result = await client.ping()
    assert result is True, f"expected True from ping(), got {result!r}"


# ─────────────────────────────────────────────────────────────────
# rc2 — singleton per (db, event loop)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rc2_singleton_per_loop():
    """Two calls to ``get_redis_client(db=2)`` in the same event loop
    return the **same** instance (``is`` comparison)."""
    c1 = await get_redis_client(db=2)
    c2 = await get_redis_client(db=2)
    assert c1 is c2, "expected same instance within same event loop"


# ─────────────────────────────────────────────────────────────────
# rc3 — different dbs get different clients
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rc3_different_dbs_different_clients():
    """Distinct ``db`` numbers produce distinct client instances in the
    same loop (keyed by ``(db, id(loop))``)."""
    c_db2 = await get_redis_client(db=2)
    c_db0 = await get_redis_client(db=0)
    assert c_db2 is not c_db0, "expected distinct clients for different dbs"


# ─────────────────────────────────────────────────────────────────
# rc4 — reset closes and evicts for current loop
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rc4_reset_closes_and_removes():
    """After ``_reset_redis_pool_for_loop()``, the next ``get_redis_client``
    call constructs a **fresh** instance (not the previously cached one)
    and the new instance is usable."""
    c1 = await get_redis_client(db=2)
    await _reset_redis_pool_for_loop()
    c2 = await get_redis_client(db=2)
    assert c1 is not c2, "expected new instance after reset"
    assert await c2.ping() is True, "new instance must be alive"
