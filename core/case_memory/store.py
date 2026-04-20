# -*- coding: utf-8 -*-
"""
core/case_memory/store.py — Redis-backed session-scoped case graph.

Keys
----
  • ``case:{session_id}:{case_hash}``   — JSON blob per case
  • ``case_index:{session_id}``         — ZSET of case_hash → last_access_ts

TTL
---
30 days per case. Touched on every hit via ``touch()``. Index ZSET
itself also gets the same TTL so it never outlives its cases.

LRU cap
-------
50 cases per session. On ``store()`` we evict the oldest-accessed
case(s) in a **second** atomic pipeline — the initial write pipeline
just sets the new case + index entry; a follow-up
``_evict_if_over_cap`` reads the overflow and deletes both the index
entry and the case blob atomically. Brief ``count == 51`` window
between the two pipelines is eventually consistent; that's fine
because LRU eviction is the only path that shrinks.

Similarity search
-----------------
``find_similar`` loads all cases in the session via one ``MGET``
round-trip (N ≤ 50 by LRU cap), filters by same-domain, computes
Jaccard, sorts desc, and returns the top-N. Single Redis round-trip
for data fetch plus one prior ``ZRANGE`` for the hash list.

Atomicity
---------
Writes use a Redis ``MULTI/EXEC`` pipeline so either all of
``(SET case, ZADD index, EXPIRE index)`` succeed or none. Eviction is
its own atomic pipeline (``ZREM + DEL × N``).

Cross-loop safety
-----------------
Uses ``core.redis_client.get_redis_client`` which singletons per
``(db, event_loop)``. ``_reset_store_state`` delegates to
``_reset_redis_pool_for_loop`` for pytest isolation.

Fail-loud policy
----------------
- Redis errors in ``store``, ``get_by_signature``, ``touch`` bubble up.
- In ``find_similar`` a single malformed JSON blob is logged and
  skipped (see docstring) — the alternative (crash the whole request
  because one legacy entry is corrupt) is strictly worse for users.
- Input validation (threshold range, max_results) raises ``ValueError``.

Status: CP2 · Part C. Implementation live; cm15-cm19 exercise it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from core.case_memory.signature import CaseSignature
from core.redis_client import (
    _reset_redis_pool_for_loop,
    get_redis_client,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Key templates + tunables
# ─────────────────────────────────────────────────────────────────

KEY_CASE: str = "case:{session_id}:{case_hash}"
KEY_INDEX: str = "case_index:{session_id}"

TTL_DAYS: int = 30
TTL_SECONDS: int = TTL_DAYS * 24 * 3600
MAX_CASES_PER_SESSION: int = 50
REDIS_DB: int = 2


# ─────────────────────────────────────────────────────────────────
# Value object
# ─────────────────────────────────────────────────────────────────

@dataclass
class StoredCase:
    """A case record as read back from Redis.

    Fields serialised as JSON under ``KEY_CASE``. The index entry lives
    separately in ``KEY_INDEX`` (ZSET, score = last_access_ts).
    ``age_seconds`` is derived at read-time — not stored.
    """

    case_hash: str
    session_id: str
    signature: CaseSignature
    summary: str
    legal_frame: dict = field(default_factory=dict)
    turn_count: int = 1
    created_at: float = 0.0
    last_access: float = 0.0

    @property
    def age_seconds(self) -> float:
        """Wall-clock seconds since ``created_at``."""
        return time.time() - self.created_at

    # ─── Serialisation ──────────────────────────────────────────

    def to_redis_value(self) -> str:
        """JSON-serialise the case for Redis storage.

        ``ensure_ascii=False`` keeps Arabic readable when inspecting
        keys via redis-cli (debugging aid, no functional impact).

        ``CaseSignature`` is frozen — we project to a plain dict here
        and reconstruct in ``from_redis_value``.
        """
        payload = {
            "case_hash": self.case_hash,
            "session_id": self.session_id,
            "signature": {
                "domain": self.signature.domain,
                "primary_concepts": list(self.signature.primary_concepts),
                "entity_tags": list(self.signature.entity_tags),
            },
            "summary": self.summary,
            "legal_frame": self.legal_frame,
            "turn_count": self.turn_count,
            "created_at": self.created_at,
            "last_access": self.last_access,
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_redis_value(cls, raw: str) -> "StoredCase":
        """JSON-deserialise a case blob.

        Fail-loud: malformed JSON → ``json.JSONDecodeError``; missing
        expected keys → ``KeyError``. Callers in ``find_similar`` catch
        and log-then-skip (see class docstring); callers in
        ``get_by_signature`` and ``touch`` let it propagate.
        """
        data = json.loads(raw)

        sig_data = data["signature"]
        signature = CaseSignature(
            domain=sig_data["domain"],
            primary_concepts=tuple(sig_data["primary_concepts"]),
            entity_tags=tuple(sig_data["entity_tags"]),
        )

        return cls(
            case_hash=data["case_hash"],
            session_id=data["session_id"],
            signature=signature,
            summary=data["summary"],
            legal_frame=data["legal_frame"],
            turn_count=data["turn_count"],
            created_at=data["created_at"],
            last_access=data["last_access"],
        )


# ─────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────

class CaseMemoryStore:
    """Redis-backed async case store. Cross-loop safe, stateless.

    Single instance is fine to share across requests — all state
    (Redis client, locks) is sourced on-demand per event loop via
    ``core.redis_client.get_redis_client``. There is no per-store
    mutable state.
    """

    # ─── store ──────────────────────────────────────────────────

    async def store(
        self,
        session_id: str,
        signature: CaseSignature,
        summary: str,
        legal_frame: dict,
    ) -> StoredCase:
        """Insert (or overwrite-by-hash) a case. Returns the StoredCase.

        Atomic main write pipeline:
          1. ``SET case:{sid}:{hash}`` with ``EX=TTL_SECONDS``.
          2. ``ZADD case_index:{sid}`` (``case_hash`` → now_ts).
          3. ``EXPIRE case_index:{sid}`` to keep the index aligned.

        Follow-up: if the session now holds more than
        ``MAX_CASES_PER_SESSION`` cases, the oldest-accessed are
        evicted (see ``_evict_if_over_cap``).
        """
        now = time.time()

        case = StoredCase(
            case_hash=signature.hash,
            session_id=session_id,
            signature=signature,
            summary=summary,
            legal_frame=legal_frame,
            turn_count=1,
            created_at=now,
            last_access=now,
        )

        case_key = KEY_CASE.format(session_id=session_id, case_hash=signature.hash)
        index_key = KEY_INDEX.format(session_id=session_id)

        client = await get_redis_client(db=REDIS_DB)

        async with client.pipeline(transaction=True) as pipe:
            pipe.set(case_key, case.to_redis_value(), ex=TTL_SECONDS)
            pipe.zadd(index_key, {signature.hash: now})
            pipe.expire(index_key, TTL_SECONDS)
            await pipe.execute()

        await self._evict_if_over_cap(client, session_id)

        return case

    # ─── LRU eviction ───────────────────────────────────────────

    async def _evict_if_over_cap(
        self,
        client: Any,
        session_id: str,
    ) -> None:
        """Drop the oldest-accessed cases if session exceeds the cap.

        Reads ``ZCARD`` → if over cap, ``ZRANGE 0 N-1`` fetches the
        oldest hashes (ascending score = oldest first), then a single
        transaction deletes the index entries and the case blobs.

        Idempotent: repeated calls with no overflow are no-ops.
        """
        index_key = KEY_INDEX.format(session_id=session_id)

        count = await client.zcard(index_key)
        if count <= MAX_CASES_PER_SESSION:
            return

        to_evict = count - MAX_CASES_PER_SESSION
        oldest_hashes = await client.zrange(index_key, 0, to_evict - 1)
        if not oldest_hashes:
            return

        async with client.pipeline(transaction=True) as pipe:
            pipe.zrem(index_key, *oldest_hashes)
            for h in oldest_hashes:
                case_key = KEY_CASE.format(session_id=session_id, case_hash=h)
                pipe.delete(case_key)
            await pipe.execute()

        log.info(
            "case_memory LRU evicted %d case(s) from session %s",
            len(oldest_hashes),
            session_id,
        )

    # ─── exact lookup ───────────────────────────────────────────

    async def get_by_signature(
        self,
        session_id: str,
        signature: CaseSignature,
    ) -> Optional[StoredCase]:
        """Exact-match lookup by ``signature.hash``.

        Returns ``None`` when the key is absent (either never stored
        or expired via TTL). Any JSON decoding failure bubbles up —
        this path is used for the upsert decision, and silent
        corruption there would cause duplicate inserts.
        """
        case_key = KEY_CASE.format(session_id=session_id, case_hash=signature.hash)

        client = await get_redis_client(db=REDIS_DB)
        raw = await client.get(case_key)
        if raw is None:
            return None

        return StoredCase.from_redis_value(raw)

    # ─── touch (recency update) ─────────────────────────────────

    async def touch(
        self,
        session_id: str,
        case_hash: str,
    ) -> bool:
        """Mark a case as recently used.

        Updates ``last_access`` on the JSON blob, increments
        ``turn_count``, refreshes the case TTL and the index score.
        All three writes execute in one atomic pipeline.

        Returns ``True`` if the case existed; ``False`` if not found
        (no writes performed).
        """
        case_key = KEY_CASE.format(session_id=session_id, case_hash=case_hash)
        index_key = KEY_INDEX.format(session_id=session_id)

        client = await get_redis_client(db=REDIS_DB)
        raw = await client.get(case_key)
        if raw is None:
            return False

        case = StoredCase.from_redis_value(raw)
        now = time.time()
        case.last_access = now
        case.turn_count += 1

        async with client.pipeline(transaction=True) as pipe:
            pipe.set(case_key, case.to_redis_value(), ex=TTL_SECONDS)
            pipe.zadd(index_key, {case_hash: now})
            pipe.expire(index_key, TTL_SECONDS)
            await pipe.execute()

        return True

    # ─── similarity search ──────────────────────────────────────

    async def find_similar(
        self,
        session_id: str,
        current_sig: CaseSignature,
        threshold: float = 0.60,
        max_results: int = 3,
    ) -> List[Tuple[StoredCase, float]]:
        """Return (case, similarity) pairs above ``threshold``.

        Algorithm:
          1. ``ZRANGE`` the session's full hash list (≤ 50 entries).
          2. Single ``MGET`` for all case blobs.
          3. Deserialise, filter same-domain, exclude self.
          4. Compute Jaccard via ``CaseSignature.similarity``.
          5. Filter by ``>= threshold``, sort desc, truncate.

        Domain is a hard filter here: cross-domain matches are never
        useful for case memory (مدني ↔ جنائي cases don't inform each
        other). ``similarity`` itself ignores domain by design.

        A single malformed blob is **logged-and-skipped** — crashing
        the whole lookup because one legacy entry is corrupt would be
        strictly worse. The explicit exception path documented in the
        module docstring.

        A stale index entry (raw is ``None``) — possible only under a
        tight TTL clock-skew race — is silently skipped.
        """
        if threshold < 0.0 or threshold > 1.0:
            raise ValueError(f"threshold must be in [0.0, 1.0], got {threshold}")
        if max_results < 1:
            raise ValueError(f"max_results must be >= 1, got {max_results}")

        index_key = KEY_INDEX.format(session_id=session_id)

        client = await get_redis_client(db=REDIS_DB)
        all_hashes = await client.zrange(index_key, 0, -1)
        if not all_hashes:
            return []

        case_keys = [
            KEY_CASE.format(session_id=session_id, case_hash=h)
            for h in all_hashes
        ]
        raw_values = await client.mget(*case_keys)

        scored: List[Tuple[StoredCase, float]] = []
        for raw in raw_values:
            if raw is None:
                # Stale index entry (case expired, index didn't shrink in time).
                continue
            try:
                stored = StoredCase.from_redis_value(raw)
            except (json.JSONDecodeError, KeyError) as e:
                log.warning(
                    "case_memory: malformed entry in session %s: %s: %s",
                    session_id, type(e).__name__, e,
                )
                continue

            # Same-domain filter (see docstring).
            if stored.signature.domain != current_sig.domain:
                continue

            # Don't match against self.
            if stored.case_hash == current_sig.hash:
                continue

            sim = current_sig.similarity(stored.signature)
            if sim >= threshold:
                scored.append((stored, sim))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:max_results]


# ─────────────────────────────────────────────────────────────────
# Test-only helpers (NOT for production use)
# ─────────────────────────────────────────────────────────────────

async def _reset_store_state() -> None:
    """Drop any per-loop caches held by this module and delegate to
    ``core.redis_client._reset_redis_pool_for_loop``.

    Currently ``CaseMemoryStore`` is stateless (no per-loop caches of
    its own), so this is effectively a delegation. The hook remains
    in place so test harnesses have a single call-site should we add
    module-level caches (e.g. connection reuse, statement caches) in
    a future iteration.

    Called by ``tests/phase3/conftest.py`` around each test.
    **Never invoke from production code.**
    """
    await _reset_redis_pool_for_loop()


__all__ = [
    "CaseMemoryStore",
    "StoredCase",
    "KEY_CASE",
    "KEY_INDEX",
    "TTL_DAYS",
    "TTL_SECONDS",
    "MAX_CASES_PER_SESSION",
    "REDIS_DB",
]
