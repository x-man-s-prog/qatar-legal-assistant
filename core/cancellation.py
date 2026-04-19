# -*- coding: utf-8 -*-
"""
Cancellation Registry — user can stop any in-flight request.

Thread-safe. Bounded LRU (auto-evicts old request_ids). Each request gets
a UUID at entry. The pipeline checks `is_cancelled(rid)` at hot points
(before retrieval, before reasoning, before output assembly). On cancel,
`raise_if_cancelled()` raises CancelledExecution which the runtime
catches and turns into a clean cancelled response.

Public API:
    register(request_id) -> None
    cancel(request_id) -> bool
    is_cancelled(request_id) -> bool
    raise_if_cancelled(request_id) -> None     # raises CancelledExecution
    new_request_id() -> str
    active_count() -> int
    snapshot() -> dict
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from typing import Optional


class CancelledExecution(Exception):
    """Raised inside pipeline when the user cancelled."""
    def __init__(self, request_id: str):
        super().__init__(f"cancelled:{request_id}")
        self.request_id = request_id


class _CancellationRegistry:
    """LRU registry: request_id → cancelled_flag (bool)."""

    def __init__(self, max_size: int = 4096, ttl_seconds: int = 600):
        self._lock = threading.RLock()
        self._store: OrderedDict[str, tuple[bool, float]] = OrderedDict()
        self._max = max_size
        self._ttl = ttl_seconds
        self._cancellations_total = 0

    def new_request_id(self) -> str:
        return uuid.uuid4().hex

    def register(self, request_id: str) -> None:
        """Register a request_id. PRESERVES cancelled state if already cancelled.

        This prevents a race where the user calls /cancel BEFORE the runtime
        registers the request — re-registering as 'not cancelled' would
        silently undo the cancellation.
        """
        with self._lock:
            self._evict_expired()
            existing = self._store.get(request_id)
            if existing is not None and existing[0] is True:
                # already cancelled — keep that state
                self._store.move_to_end(request_id)
                return
            self._store[request_id] = (False, time.time())
            self._store.move_to_end(request_id)
            if len(self._store) > self._max:
                self._store.popitem(last=False)

    def cancel(self, request_id: str) -> bool:
        """Returns True if the request was registered and now marked cancelled."""
        with self._lock:
            entry = self._store.get(request_id)
            if entry is None:
                return False
            self._store[request_id] = (True, entry[1])
            self._store.move_to_end(request_id)
            self._cancellations_total += 1
            return True

    def is_cancelled(self, request_id: Optional[str]) -> bool:
        if not request_id:
            return False
        with self._lock:
            entry = self._store.get(request_id)
            if entry is None:
                return False
            return bool(entry[0])

    def raise_if_cancelled(self, request_id: Optional[str]) -> None:
        if request_id and self.is_cancelled(request_id):
            raise CancelledExecution(request_id)

    def unregister(self, request_id: str) -> None:
        with self._lock:
            self._store.pop(request_id, None)

    def active_count(self) -> int:
        with self._lock:
            self._evict_expired()
            return sum(1 for v in self._store.values() if not v[0])

    def snapshot(self) -> dict:
        with self._lock:
            self._evict_expired()
            return {
                "active":              self.active_count(),
                "total_in_registry":   len(self._store),
                "cancellations_total": self._cancellations_total,
                "max_size":            self._max,
                "ttl_seconds":         self._ttl,
            }

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._cancellations_total = 0

    # ── internal ──
    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, (_, ts) in self._store.items()
                    if now - ts > self._ttl]
        for k in expired:
            del self._store[k]


# ── module singleton ──

_registry = _CancellationRegistry()


def register(request_id: str) -> None:
    _registry.register(request_id)


def cancel(request_id: str) -> bool:
    return _registry.cancel(request_id)


def is_cancelled(request_id: Optional[str]) -> bool:
    return _registry.is_cancelled(request_id)


def raise_if_cancelled(request_id: Optional[str]) -> None:
    _registry.raise_if_cancelled(request_id)


def new_request_id() -> str:
    return _registry.new_request_id()


def unregister(request_id: str) -> None:
    _registry.unregister(request_id)


def active_count() -> int:
    return _registry.active_count()


def snapshot() -> dict:
    return _registry.snapshot()


def reset_for_tests() -> None:
    _registry.reset()
