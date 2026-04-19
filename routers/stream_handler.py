# -*- coding: utf-8 -*-
"""
routers/stream_handler.py — SSE Streaming Utilities
=====================================================
Event formatting, model selection, stream-with-fallback,
and Chinese character detection for Ollama safety.
"""
import json
import re
import logging
from typing import AsyncIterator
from core import app_state
from core.config import OPENAI_KEY, GEMINI_KEY, ANTHROPIC_KEY, PRIMARY_MODEL
from core.nlp_utils import _CHINESE_RE
from core.prompts import EXPERT_SYSTEM, OLLAMA_EXPERT_SYSTEM
from services.llm_service import (
    stream_openai, stream_gemini, stream_claude, stream_ollama,
)

log = logging.getLogger(__name__)


# ── SSE Event Helpers ──

def sse_event(data: dict) -> str:
    """Format a single SSE event."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_start() -> str:
    return sse_event({"type": "start"})


def sse_chunk(text: str) -> str:
    return sse_event({"type": "chunk", "text": text})


def sse_status(text: str) -> str:
    return sse_event({"type": "status", "text": text})


def sse_done(sources: list = None, confidence: int = 100, log_id: int = 0, **extra) -> str:
    data = {"type": "done", "sources": sources or [], "confidence": confidence, "log_id": log_id}
    data.update(extra)
    return sse_event(data)


def sse_error(text: str) -> str:
    return sse_event({"type": "error", "text": text})


# ── Model Selection ──

def select_stream_generator(model: str, system: str, messages: list, max_tokens: int = 2000):
    """
    Select the appropriate streaming LLM generator based on model preference.
    Returns an async generator.
    """
    eff = model or PRIMARY_MODEL
    if eff == "ollama":
        return stream_ollama(system, messages, max_tokens=max_tokens)
    elif eff == "gemini" and GEMINI_KEY:
        return stream_gemini(system, messages, max_tokens=max_tokens)
    elif eff == "claude" and ANTHROPIC_KEY:
        return stream_claude(system, messages, max_tokens=max_tokens)
    elif OPENAI_KEY:
        return stream_openai(system, messages, max_tokens=max_tokens)
    elif GEMINI_KEY:
        return stream_gemini(system, messages, max_tokens=max_tokens)
    elif ANTHROPIC_KEY:
        return stream_claude(system, messages, max_tokens=max_tokens)
    else:
        return stream_ollama(system, messages, max_tokens=max_tokens)


async def stream_and_collect(gen, stream_filter=None) -> tuple[list[str], str]:
    """
    Consume an async generator, collect chunks.
    Returns (sse_events_list, full_text).
    """
    events = []
    parts = []
    async for chunk in gen:
        if chunk:
            if stream_filter:
                chunk = stream_filter.filter(chunk)
            if chunk:
                parts.append(chunk)
                events.append(sse_chunk(chunk))
    return events, "".join(parts)


async def stream_with_fallback(
    gen,
    q: str,
    is_ollama: bool = False,
    stream_filter=None,
) -> AsyncIterator[str]:
    """
    Stream from primary generator with:
    - Chinese character detection (Ollama safety)
    - Repeat detection (prevent infinite loops)
    - Fallback to Ollama if primary fails

    Yields SSE chunk events.
    """
    _chinese_detected = False
    _full_parts = []
    _last_lines = []
    _chunk_window = []

    def _is_repeating() -> bool:
        """Detect repetitive output patterns."""
        # Line repetition
        if len(_last_lines) >= 5:
            recent = _last_lines[-15:]
            from collections import Counter
            line_counts = Counter(recent)
            if any(c >= 3 for c in line_counts.values()):
                return True
        # Chunk repetition
        if len(_chunk_window) >= 6:
            window = _chunk_window[-20:]
            long_chunks = [c for c in window if len(c) > 25]
            if long_chunks:
                from collections import Counter
                chunk_counts = Counter(long_chunks)
                if any(c >= 3 for c in chunk_counts.values()):
                    return True
        return False

    try:
        async for chunk in gen:
            if not chunk:
                continue

            # Chinese detection
            if _CHINESE_RE.search(chunk):
                _chinese_detected = True
                log.warning("Chinese chars detected in stream — switching to fallback")
                break

            # Track for repeat detection
            _chunk_window.append(chunk)
            for line in chunk.split('\n'):
                line = line.strip()
                if line:
                    _last_lines.append(line)

            if _is_repeating():
                log.warning("Repetition detected — stopping stream")
                break

            _full_parts.append(chunk)
            if stream_filter:
                chunk = stream_filter.filter(chunk)
            if chunk:
                yield sse_chunk(chunk)
    except Exception as e:
        log.warning("Primary stream error: %s", e)
        _chinese_detected = True  # Trigger fallback

    # Fallback
    if _chinese_detected and not _full_parts:
        log.info("Falling back to Ollama for Arabic output")
        try:
            _fb_sys = OLLAMA_EXPERT_SYSTEM
            _fb_msgs = [{"role": "user", "content": f"أجب بالعربية فقط عن: {q[:500]}"}]
            async for chunk in stream_ollama(_fb_sys, _fb_msgs, max_tokens=1500):
                if chunk and not _CHINESE_RE.search(chunk):
                    yield sse_chunk(chunk)
        except Exception as e:
            log.warning("Fallback stream error: %s", e)
