# -*- coding: utf-8 -*-
"""
tests/phase2/conftest.py — pytest-asyncio event-loop + pool hygiene.

Why this file exists
--------------------
Under ``pytest-asyncio`` (auto mode) every test function gets a fresh
event loop, but ``core.app_state.pool`` is a **module-level global** —
once populated by the first test, it is re-used by subsequent tests.

asyncpg pools bind their connections to the loop that created them.
When test-2 runs in a fresh loop and tries to use the pool created by
test-1, asyncpg raises:

    • ``Event loop is closed``
    • ``cannot perform operation: another operation is in progress``

Production runtime does not hit this: FastAPI's lifespan owns the pool
for the whole app lifecycle, so there is only ever one loop. But pytest
exercises a different lifecycle — we fix it here without touching
production code paths.

What this fixture does
----------------------
Calls ``_reset_pool_state()`` from ``core.precedent_linker`` before and
after every test in this directory. That helper closes and nulls out
``app_state.pool`` so the next ``_ensure_pool()`` inside the test
creates a fresh pool bound to the current event loop.

Scope: function (one reset per test).
Autouse: yes — every test in tests/phase2/ gets it automatically.
"""
import asyncio
import pytest
import pytest_asyncio

from core.precedent_linker import _reset_pool_state


@pytest.fixture(scope="function")
def event_loop():
    """
    New event loop per test — documents the guarantee explicitly.

    pytest-asyncio ≥1.x in auto mode defaults to function-scoped loops,
    so in practice this override is a no-op. We keep it so the file is
    self-documenting for future readers who may wonder about loop
    lifetime.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def reset_precedent_linker_pool():
    """Reset app_state.pool binding before and after each test."""
    await _reset_pool_state()
    yield
    await _reset_pool_state()
