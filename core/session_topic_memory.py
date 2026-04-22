# -*- coding: utf-8 -*-
"""
core/session_topic_memory.py — per-session memo topic persistence.

Purpose
=======
Keeps the detected memo topic alive across turns within a session so
that standalone follow-up requests like "اكتب المذكرة" do not lose
the topic captured in an earlier turn.

Why this exists (CP4 FINDING #14)
---------------------------------
User session reproduced the regression:
  T2: "اكتب لي مذكرة اسقاط حضانه ضد طليقتي"   → topic=حضانة
  T3: "1- احمد 3 سنوات 2- سوء سلوكها..."      → memo produced
  T4: "طيب اكتب المذكرة"                       → topic=عام ← LOSS
  T5: "ذكرت الموضوع في الرسالة السابقة"       → memo_ask_topic ← catastrophic

Topic lives only in the current-turn handler scope; a fresh turn with
no topic keyword re-detects "عام" and falls into ``ask_topic_gen``.

Design
------
• Redis db=2 (the existing case_memory infrastructure bucket —
  see FINDING #8). No new Redis DB. No new infrastructure.
• Key: ``session_topic:{session_id}``
• TTL: 1 hour. Matches typical memo-drafting session duration.
• Both async and sync entry points (composer-chain is sync; routers
  are async).
• Graceful degradation: every Redis failure is logged at debug,
  never raises. Callers treat ``None`` as "no topic stored" and
  behave exactly as pre-CP4.

Integration points
------------------
handle_memo_smart (routers/query_router.py):
  1. START — before topic detection, try get_session_topic_sync.
  2. AFTER detection (topic != "عام") — store it.
  3. ask_topic_gen guard — skip if a stored topic exists.

NEVER call from composer.py or anywhere outside the routers layer.
Session state belongs to the routing tier.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

_SESSION_TOPIC_TTL = 3600  # 1 hour
_KEY_PATTERN = "session_topic:{sid}"


# ═══════════════════════════════════════════════════════════════════
# Async primary API
# ═══════════════════════════════════════════════════════════════════

async def set_session_topic(session_id: str, topic: str) -> bool:
    """Store ``topic`` for ``session_id``.

    Refuses to store empty / whitespace-only topics or the sentinel
    ``"عام"`` (which means "no topic detected" by convention).

    Returns True on successful Redis SET, False otherwise.
    Never raises.
    """
    if not session_id or not topic:
        return False
    topic = topic.strip()
    if not topic or topic == "عام":
        return False
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        key = _KEY_PATTERN.format(sid=session_id)
        await client.set(key, topic, ex=_SESSION_TOPIC_TTL)
        log.info(
            "session_topic: stored '%s' for sid=%s",
            topic, session_id[:12],
        )
        return True
    except Exception as e:
        log.warning("session_topic: store failed: %s", e)
        return False


async def clear_session_topic(session_id: str) -> bool:
    """Delete any stored topic for ``session_id``.

    Used when the user explicitly pivots to a new memo on a different
    topic (``LEGAL_DRAFT_REQUEST`` with ``reset_hard=True``) — the
    prior topic must NOT be silently reused. FINDING #20.

    Returns True if the key was deleted (or didn't exist), False only
    on Redis failure. Never raises.
    """
    if not session_id:
        return False
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        key = _KEY_PATTERN.format(sid=session_id)
        await client.delete(key)
        log.info("session_topic: cleared sid=%s", session_id[:12])
        return True
    except Exception as e:
        log.warning("session_topic: clear failed: %s", e)
        return False


async def get_session_topic(session_id: str) -> Optional[str]:
    """Retrieve topic stored for ``session_id``.

    Returns ``None`` if:
      • session_id is empty, OR
      • no topic was ever stored for this session, OR
      • the Redis lookup failed for any reason.

    Never raises.
    """
    if not session_id:
        return None
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        key = _KEY_PATTERN.format(sid=session_id)
        raw = await client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        raw = raw.strip()
        return raw if raw and raw != "عام" else None
    except Exception as e:
        log.debug("session_topic: get failed: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════
# Sync wrappers (for routers that are sync-within-async contexts
# like handle_memo_smart which iterates a sync generator)
# ═══════════════════════════════════════════════════════════════════

def set_session_topic_sync(session_id: str, topic: str) -> bool:
    """Sync wrapper over ``set_session_topic``.

    Uses the proven ``_corpus_bg`` background loop pattern (same as
    fact_extractor / precedent_linker). Never raises.
    """
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
        return bool(_corpus_bg.run(set_session_topic(session_id, topic)))
    except Exception as e:
        log.debug("session_topic_sync: set failed: %s", e)
        return False


def get_session_topic_sync(session_id: str) -> Optional[str]:
    """Sync wrapper over ``get_session_topic``. Never raises."""
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
        return _corpus_bg.run(get_session_topic(session_id))
    except Exception as e:
        log.debug("session_topic_sync: get failed: %s", e)
        return None


def clear_session_topic_sync(session_id: str) -> bool:
    """Sync wrapper over ``clear_session_topic``. Never raises."""
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
        return bool(_corpus_bg.run(clear_session_topic(session_id)))
    except Exception as e:
        log.debug("session_topic_sync: clear failed: %s", e)
        return False


__all__ = [
    "set_session_topic",
    "get_session_topic",
    "clear_session_topic",
    "set_session_topic_sync",
    "get_session_topic_sync",
    "clear_session_topic_sync",
]
