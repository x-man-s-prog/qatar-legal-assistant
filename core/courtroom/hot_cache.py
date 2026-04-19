# -*- coding: utf-8 -*-
"""
Hot Cache — version-aware in-memory cache for hot reads.

Caches:
  - complexity classification (per query string)
  - domain corpora subsets (per domain string)
  - canonical law resolutions (per raw text)

Each entry carries a version stamp. On version bump (when KnowledgeStore
is reloaded or registry changes), all entries are invalidated. NO stale
data ever leaks to the runtime.

Bounded LRU — max_size enforced.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Optional


class HotCache:
    """Single shared cache. Sub-namespaces by string prefix."""

    def __init__(self, max_size: int = 2048):
        self._store: OrderedDict[str, tuple[int, Any]] = OrderedDict()
        self._max = max_size
        self._version = 0
        self._hits = 0
        self._misses = 0

    def bump_version(self) -> int:
        """Invalidate everything. Called after KnowledgeStore changes."""
        self._version += 1
        self._store.clear()
        return self._version

    @property
    def version(self) -> int:
        return self._version

    def get(self, namespace: str, key: str) -> Optional[Any]:
        full_key = f"{namespace}:{key}"
        item = self._store.get(full_key)
        if item is None:
            self._misses += 1
            return None
        ver, val = item
        if ver != self._version:
            del self._store[full_key]
            self._misses += 1
            return None
        # LRU touch
        self._store.move_to_end(full_key)
        self._hits += 1
        return val

    def put(self, namespace: str, key: str, value: Any) -> None:
        full_key = f"{namespace}:{key}"
        self._store[full_key] = (self._version, value)
        self._store.move_to_end(full_key)
        if len(self._store) > self._max:
            self._store.popitem(last=False)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "version":  self._version,
            "size":     len(self._store),
            "max":      self._max,
            "hits":     self._hits,
            "misses":   self._misses,
            "hit_rate": round(self._hits / max(total, 1), 3),
        }

    def reset_metrics(self) -> None:
        self._hits = 0
        self._misses = 0


_cache: Optional[HotCache] = None


def get_hot_cache() -> HotCache:
    global _cache
    if _cache is None:
        _cache = HotCache()
    return _cache
