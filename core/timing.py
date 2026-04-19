# -*- coding: utf-8 -*-
"""
core/timing.py — Request timing utilities
==========================================
- TimingCollector: thread-safe per-request timing store
- record(label, ms): record a timing sample
- get_stats(): return aggregated stats (avg, p95, p99, min, max)
- timing_context(label): async context manager for timing a block
"""
import asyncio
import time
import logging
import statistics
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Dict, List

log = logging.getLogger(__name__)

# Per-label rolling window (last 1000 samples)
_WINDOW = 1000
_samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_WINDOW))


def record(label: str, ms: float) -> None:
    """Record a timing sample for label."""
    _samples[label].append(ms)
    if ms > 1000:
        log.warning("SLOW %s: %.0fms", label, ms)


def get_stats() -> dict:
    """Return aggregated stats for all labels."""
    result = {}
    for label, window in _samples.items():
        if not window:
            continue
        data = list(window)
        data_sorted = sorted(data)
        n = len(data_sorted)
        result[label] = {
            "count": n,
            "avg_ms":  round(statistics.mean(data), 1),
            "min_ms":  round(data_sorted[0], 1),
            "max_ms":  round(data_sorted[-1], 1),
            "p95_ms":  round(data_sorted[int(n * 0.95)], 1) if n >= 20 else None,
            "p99_ms":  round(data_sorted[int(n * 0.99)], 1) if n >= 100 else None,
        }
    return result


def reset() -> None:
    """Clear all samples (for testing)."""
    _samples.clear()


@asynccontextmanager
async def timing_context(label: str):
    """
    Async context manager that records execution time.

    Usage:
        async with timing_context("embed"):
            embeddings = await embed(query)
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000
        record(label, ms)
        log.debug("TIMING %s: %.1fms", label, ms)
