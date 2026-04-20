# -*- coding: utf-8 -*-
"""
tests/phase3/conftest.py — event loop + Redis/store hygiene.

Mirrors the pattern that stabilised Phase 2 (see ``FINDINGS §7``):
fresh event loop per test, plus an autouse fixture that resets any
cached client bound to a previous loop.

STATUS
------
CP2 · Part C — functional. The autouse fixture:

  1. Before each test: resets the per-loop Redis client pool and
     flushes all ``case:test-*`` / ``case_index:test-*`` keys so the
     test starts with a clean db=2 namespace.
  2. Yields control to the test.
  3. After the test: same cleanup, in reverse order.

Test session IDs MUST start with ``test-`` to be reached by the
cleanup sweep. Using a non-prefixed session_id will leak state across
tests — treat that as a test bug, not a fixture limitation.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from core.redis_client import (
    _reset_redis_pool_for_loop,
    get_redis_client,
)


@pytest.fixture(scope="function")
def event_loop():
    """Fresh event loop per test — prevents cross-loop Redis binding.

    pytest-asyncio ≥1.x in auto mode already defaults to function-scoped
    loops; we override explicitly so this file is self-documenting.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def reset_case_memory_state():
    """Clean Redis + reset per-loop client cache before and after each test.

    Delete pattern ``case:test-*`` and ``case_index:test-*`` — any
    session_id prefixed with ``test-`` is swept.
    """
    # BEFORE test
    await _reset_redis_pool_for_loop()
    await _flush_test_keys()

    yield

    # AFTER test
    await _flush_test_keys()
    await _reset_redis_pool_for_loop()


async def _flush_test_keys() -> None:
    """Delete all Redis keys matching the test-only patterns in db=2.

    Uses ``SCAN`` to avoid blocking the server on large keyspaces
    (irrelevant here since db=2 holds at most a few dozen test keys,
    but the habit is cheap).
    """
    client = await get_redis_client(db=2)

    patterns = ("case:test-*", "case_index:test-*")
    for pattern in patterns:
        async for key in client.scan_iter(match=pattern, count=100):
            await client.delete(key)
