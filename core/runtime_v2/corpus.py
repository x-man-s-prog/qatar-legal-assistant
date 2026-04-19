# -*- coding: utf-8 -*-
"""
runtime_v2.corpus — thin, synchronous DB reader over the Qatari legal
corpus (49k+ chunks, 11k+ تمييز rulings).

Exposes two sync functions the memo composer uses:
    get_article_text(law_pattern, article_num) → str | None
    get_rulings(pattern, limit=2)              → tuple[str, ...]

Implementation: asyncpg connection pool running on a single background
asyncio loop thread. Every call is memoized via functools.lru_cache.
DB outages degrade gracefully: returns None / empty tuple.

No legacy runtime imports. No RAG / vector search. Pure literal lookup
on the `chunks` table (article_number + law_name pattern, or content
LIKE pattern for rulings).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from functools import lru_cache
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# DB DSN — pulled from env, with a sensible in-docker default
# ─────────────────────────────────────────────────────────────────────

_DSN = (
    os.environ.get("DB_DSN")
    or "postgresql://raguser:RAGsecret2024!@legal_db:5432/ragdb"
)

_TIMEOUT = 4.0   # per call (seconds); keep short — memo rendering is live


# ─────────────────────────────────────────────────────────────────────
# Async loop confined to a background thread
# ─────────────────────────────────────────────────────────────────────

class _BgLoop:
    """Runs a dedicated asyncio loop in a daemon thread. Sync callers
    submit coroutines via .run() and get results synchronously."""
    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()

    def _runner(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def _ensure(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._runner, name="runtime_v2-corpus-loop",
            daemon=True,
        )
        self._thread.start()
        self._started.wait(timeout=2.0)

    def run(self, coro):
        self._ensure()
        if self._loop is None:
            raise RuntimeError("corpus loop not initialized")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=_TIMEOUT + 1.0)


_bg = _BgLoop()


# ─────────────────────────────────────────────────────────────────────
# asyncpg pool (lazy, single-shot init)
# ─────────────────────────────────────────────────────────────────────

_POOL_BOX: dict = {}
_POOL_LOCK = threading.Lock()


async def _get_pool():
    import asyncpg
    if "pool" not in _POOL_BOX:
        _POOL_BOX["pool"] = await asyncpg.create_pool(
            _DSN,
            min_size=1,
            max_size=3,
            timeout=_TIMEOUT,
            command_timeout=_TIMEOUT,
        )
    return _POOL_BOX["pool"]


# ─────────────────────────────────────────────────────────────────────
# Law-family exclusions — keep article lookups out of unrelated corpora.
# Article numbers like "49" and "54" collide across dozens of laws
# (الخدمة الوطنية، الدستور، النظام السياسي، اتجار بالبشر، قانون الدخل…)
# so the composer's law_pattern is augmented with a hard NOT-LIKE
# block against families that are known to be legally unrelated to the
# kinds of memos runtime_v2 produces.
# ─────────────────────────────────────────────────────────────────────

_HARD_LAW_EXCLUSIONS: tuple[str, ...] = (
    "%أحكام محكمة التمييز%",
    "%خدمة وطنية%",
    "%الخدمة الوطنية%",
    "%الدستور%",
    "%النظام السياسي%",
    "%أمر أميري%",
    "%مجلس الوزراء%",
    "%اتجار بالبشر%",
    "%تمويل الإرهاب%",
    "%قانون الدخل%",
    "%الدخل الصادر%",
    "%مجموعة البنوك%",
    "%الخليج الدولي%",
    "%الخليج العربية%",
    "%التصديق الأجنبية%",
    "%الرياضية%",
    "%مرسوم أميري%",
)


def _exclusion_clause(start_idx: int) -> tuple[str, list[str]]:
    """Build the AND-NOT-LIKE clause fragment for `_HARD_LAW_EXCLUSIONS`,
    starting at positional argument index `start_idx`. Returns the SQL
    fragment + the list of arguments to bind."""
    parts: list[str] = []
    args: list[str] = []
    for i, pat in enumerate(_HARD_LAW_EXCLUSIONS):
        parts.append(f"AND law_name NOT LIKE ${start_idx + i}")
        args.append(pat)
    return " ".join(parts), args


async def _fetch_article(law_pattern: str, article_num: str) -> Optional[str]:
    pool = await _get_pool()
    excl_sql, excl_args = _exclusion_clause(start_idx=3)
    query = (
        "SELECT content FROM chunks "
        "WHERE is_active=true AND article_number=$1 AND law_name LIKE $2 "
        f"{excl_sql} "
        "ORDER BY length(content) DESC LIMIT 1"
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, article_num, law_pattern, *excl_args)
        return row["content"] if row else None


async def _fetch_rulings(pattern: str, limit: int) -> list[str]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT LEFT(content, 480) AS c FROM chunks "
            "WHERE is_active=true "
            "AND law_name LIKE '%أحكام محكمة التمييز%' "
            "AND content LIKE $1 "
            # keep rulings out of obviously unrelated subject areas
            "AND content NOT LIKE '%حضانة أطفال%' "      # daycare
            "AND content NOT LIKE '%حضانة دار%' "
            "AND content NOT LIKE '%الإرهاب%' "
            "AND content NOT LIKE '%خدمة وطنية%' "
            "AND content NOT LIKE '%اتجار بالبشر%' "
            "AND content NOT LIKE '%نظام سياسي%' "
            "AND content NOT LIKE '%مجلس الشورى%' "
            "ORDER BY length(content) DESC LIMIT $2",
            pattern, limit,
        )
        return [r["c"] for r in rows]


# ─────────────────────────────────────────────────────────────────────
# Public sync API — memoized, fail-safe
# ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=256)
def get_article_text(law_pattern: str, article_num: str) -> Optional[str]:
    """Return the full text of a single article, or None on miss / DB
    failure. Memoized: subsequent calls for the same key are free."""
    if not article_num or not law_pattern:
        return None
    try:
        return _bg.run(_fetch_article(law_pattern, article_num))
    except Exception as e:
        log.debug("corpus.get_article_text miss (%s, %s): %s",
                  law_pattern, article_num, e)
        return None


@lru_cache(maxsize=128)
def get_rulings(pattern: str, limit: int = 2) -> tuple[str, ...]:
    """Return up to `limit` matching Tameez ruling snippets, or an
    empty tuple on miss / DB failure. Memoized."""
    if not pattern:
        return ()
    try:
        return tuple(_bg.run(_fetch_rulings(pattern, int(limit))))
    except Exception as e:
        log.debug("corpus.get_rulings miss (%s): %s", pattern, e)
        return ()


def article_summary(law_pattern: str, article_num: str,
                    max_chars: int = 320) -> Optional[str]:
    """Short, wrap-safe excerpt of an article for inline citation."""
    txt = get_article_text(law_pattern, article_num)
    if not txt:
        return None
    t = " ".join(txt.split())
    return t[:max_chars] + ("…" if len(t) > max_chars else "")
