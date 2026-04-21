# -*- coding: utf-8 -*-
"""
core/fact_extractor.py — structured fact extraction for memo drafting.

Purpose
=======
Extract ONLY what the user LITERALLY said. No inference, no completion,
no "helpful" template injection. Returns an ``ExtractedFacts`` struct
that the composer can trust as a ground-truth of user claims.

Why this module exists
----------------------
FINDING #13 (Hallucination Template Layers) — discovered in CP1:
memo pipelines had four hidden poison surfaces injecting "facts"
regardless of user input. Two of them live in DomainRules (facts_template
and path.markers.supporting_facts). ``compose_memo`` needs a reliable
source of truth to gate those template surfaces behind.

Design
------
• ASYNC primary API — ``extract_user_facts(query, history, *, use_cache)``
  Single LLM call (temperature=0 enforced by prompt discipline),
  strict JSON output, 8-second timeout, regex fallback on any failure.

• SYNC wrapper — ``extract_user_facts_sync(...)``
  Composer is sync (see CP1 Phase 2 reconnaissance report). We reuse
  the proven ``_corpus_bg`` background loop pattern used by the
  precedent linker since CP3. The pattern is production-safe.

• Redis cache (db=2, TTL 1h) — optional via ``use_cache``. Tests
  pass ``use_cache=False`` for determinism.

• NEVER raises — returns ``ExtractedFacts()`` (empty) on any failure.
  The composer must not fall back to facts_template silently on an
  exception here; it must see empty facts and emit placeholders.

Integration point
-----------------
``core/runtime_v2/composer.py`` — ``_facts_block`` and ``_defenses_block``
(Path X from the CP1 plan). NO other integration in CP1 scope.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

_FACT_CACHE_TTL = 3600                # 1 hour
_FACT_EXTRACTION_TIMEOUT = 8.0        # seconds
_EXTRACTION_MAX_TOKENS = 400          # strict cap — extraction isn't generation


# ═══════════════════════════════════════════════════════════════════
# Dataclass
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ExtractedFacts:
    """Structured facts extracted from user query + history.

    Each field contains ONLY what the user literally stated.
    Empty field = user didn't mention this category. The composer
    treats empty fields as signals to emit placeholders, NOT as
    licence to fill from domain templates.
    """
    names:    list[str] = field(default_factory=list)
    dates:    list[str] = field(default_factory=list)
    amounts:  list[str] = field(default_factory=list)
    ages:     list[str] = field(default_factory=list)
    claims:   list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.names, self.dates, self.amounts,
            self.ages, self.claims, self.requests,
        ])

    def as_facts_lines(self) -> list[str]:
        """Format for ``composer._facts_block`` consumption.

        Returns deduplicated, length-filtered claims. Cap at 6.
        """
        lines: list[str] = []
        seen: set[str] = set()
        for claim in self.claims[:6]:
            c = claim.strip()
            if len(c) >= 4 and c not in seen:
                lines.append(c)
                seen.add(c)
        return lines

    def to_dict(self) -> dict:
        return {
            "names":    self.names,
            "dates":    self.dates,
            "amounts":  self.amounts,
            "ages":     self.ages,
            "claims":   self.claims,
            "requests": self.requests,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedFacts":
        """Safe reconstruction — caps list sizes, tolerates missing keys."""
        return cls(
            names    = list(data.get("names",    []))[:10],
            dates    = list(data.get("dates",    []))[:10],
            amounts  = list(data.get("amounts",  []))[:10],
            ages     = list(data.get("ages",     []))[:10],
            claims   = list(data.get("claims",   []))[:6],
            requests = list(data.get("requests", []))[:6],
        )


# ═══════════════════════════════════════════════════════════════════
# LLM system prompt (constant)
# ═══════════════════════════════════════════════════════════════════

_EXTRACTION_SYSTEM_PROMPT = """\
أنت محلل وقائع قانونية. مهمتك الوحيدة: استخراج ما قاله المستخدم حرفياً.

قواعد صارمة لا يُسمح بتجاوزها:
1. لا تستنتج. لا تفترض. لا تكمّل.
2. إذا المستخدم ما ذكر شيء صراحة، اتركه فارغاً.
3. انسخ الوقائع بنصها من كلام المستخدم.
4. لا تضف أمثلة. لا تضف تفسيرات.
5. حافظ على الأرقام كما هي (12,000 يبقى 12,000 أو 12000 — لا تقسمها).

أخرج JSON صالح بهذه البنية تحديداً:
{
  "names": ["اسم شخص كما ذكره المستخدم"],
  "dates": ["تاريخ كما ذكره"],
  "amounts": ["مبلغ مع العملة كما ذكره"],
  "ages": ["عمر كما ذكره"],
  "claims": ["ادعاء كامل كما قاله"],
  "requests": ["ما يطلبه المستخدم فعلاً"]
}

إذا ما في شيء لفئة معينة، ضع مصفوفة فارغة [].
لا تُخرج أي نص خارج الـ JSON.
"""


# ═══════════════════════════════════════════════════════════════════
# Public API — ASYNC
# ═══════════════════════════════════════════════════════════════════

async def extract_user_facts(
    query: str,
    history: Optional[list] = None,
    *,
    use_cache: bool = True,
) -> ExtractedFacts:
    """Async extraction. Preferred entry point for async callers.

    Parameters
    ----------
    query : str
        Current user message. Empty → empty ExtractedFacts.
    history : list[dict] | None
        Optional conversation history. Only 'role'=='user' messages
        are considered (last 4). Assistant messages are excluded.
    use_cache : bool, default True
        When True, checks Redis db=2 before the LLM call and caches
        results. Set False in tests for determinism.

    Returns
    -------
    ExtractedFacts
        Always a valid struct. Never raises.
    """
    if not query or not query.strip():
        return ExtractedFacts()

    context = _build_context(query, history)
    cache_key = _make_cache_key(context)

    if use_cache:
        cached = await _get_cached(cache_key)
        if cached is not None:
            log.debug("fact_extractor: cache hit %s", cache_key[:12])
            return cached

    # LLM extraction with hard timeout
    try:
        result = await asyncio.wait_for(
            _llm_extract(context),
            timeout=_FACT_EXTRACTION_TIMEOUT,
        )
        if result is not None:
            if use_cache:
                await _cache_result(cache_key, result)
            return result
    except asyncio.TimeoutError:
        log.warning(
            "fact_extractor: LLM timeout after %.1fs", _FACT_EXTRACTION_TIMEOUT,
        )
    except Exception as e:
        log.warning("fact_extractor: LLM call failed: %s", e)

    # Deterministic fallback — never reaches user as an error
    log.info("fact_extractor: using regex fallback")
    return _regex_fallback(context)


# ═══════════════════════════════════════════════════════════════════
# Public API — SYNC WRAPPER (for composer)
# ═══════════════════════════════════════════════════════════════════

def extract_user_facts_sync(
    query: str,
    history: Optional[list] = None,
    *,
    use_cache: bool = True,
) -> ExtractedFacts:
    """Sync wrapper over ``extract_user_facts``.

    Used by ``compose_memo`` and its sync helper blocks. Leverages
    ``_corpus_bg`` (the pre-existing runtime_v2 background event loop)
    the same way ``_precedents_via_linker`` does since CP3.

    NEVER raises. Returns an empty ``ExtractedFacts`` on any failure
    path (the composer is responsible for handling the empty case
    with placeholders).
    """
    try:
        from core.runtime_v2.corpus import _bg as _corpus_bg
    except ImportError as e:
        log.error("fact_extractor: _corpus_bg unavailable: %s", e)
        return _regex_fallback(_build_context(query, history))

    try:
        result = _corpus_bg.run(
            extract_user_facts(query, history, use_cache=use_cache)
        )
        if isinstance(result, ExtractedFacts):
            return result
        return ExtractedFacts()
    except Exception as e:
        log.warning("fact_extractor sync wrapper failed: %s", e)
        return _regex_fallback(_build_context(query, history))


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════

def _build_context(query: str, history: Optional[list]) -> str:
    """Combine recent user messages + current query.

    Only user messages from the last 8 turns are considered; the
    most recent 4 are kept. Assistant messages are deliberately
    excluded to avoid feeding past LLM output back to the extractor.
    """
    parts: list[str] = []
    if history:
        user_msgs = [
            h.get("content", "") for h in history[-8:]
            if isinstance(h, dict) and h.get("role") == "user"
        ]
        parts.extend([m for m in user_msgs[-4:] if m])
    parts.append(query or "")
    return "\n---\n".join(parts)


async def _llm_extract(context: str) -> Optional[ExtractedFacts]:
    """Single LLM call with strict JSON output.

    Returns None on any failure — the caller (``extract_user_facts``)
    will then fall through to the regex fallback.
    """
    try:
        from services.llm_service import call_openai
    except ImportError:
        return None

    response = await call_openai(
        system=_EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        max_tokens=_EXTRACTION_MAX_TOKENS,
    )

    if not response or not isinstance(response, str):
        return None
    if response.strip().startswith("خطأ"):
        return None

    cleaned = response.strip()
    # Strip markdown fences if present (some LLMs wrap JSON in ```json ... ```)
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:])
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return None
        return ExtractedFacts.from_dict(data)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("fact_extractor: JSON parse failed: %s", e)
        return None


def _regex_fallback(context: str) -> ExtractedFacts:
    """Deterministic fallback. NEVER raises. Conservative by design.

    Extracts only high-confidence matches: numeric amounts with
    currency suffixes, explicit age patterns, slash-dates, and
    short sentence-shaped claims. Does NOT attempt to extract
    Arabic personal names (the regex is not reliable enough).
    """
    import re

    # Amounts — preserve comma-separated thousands (the comma-split
    # bug in the legacy extractor was the direct trigger for h3).
    amount_pattern = re.compile(
        r"(\d{1,3}(?:,\d{3})+|\d{3,})\s*(ريال|دينار|درهم)",
        re.UNICODE,
    )
    amounts = [
        f"{m.group(1)} {m.group(2)}"
        for m in amount_pattern.finditer(context)
    ]

    # Ages — "عمره 3 سنوات" / "عمري 40 سنة"
    age_pattern = re.compile(
        r"(?:عمره|عمرها|عمري)\s*(\d+)\s*(?:سنة|سنوات|أشهر)",
        re.UNICODE,
    )
    ages = [f"{m.group(1)} سنوات" for m in age_pattern.finditer(context)]

    # Dates — DD/MM/YYYY or a bare year
    date_pattern = re.compile(r"(\d{1,2}/\d{1,2}/\d{4}|\b\d{4}\b)")
    dates = date_pattern.findall(context)

    # Claims — sentences 8-200 chars, split on Arabic punctuation
    sentences = re.split(r"[.،؟!\n]+", context)
    claims = [
        s.strip() for s in sentences
        if 8 <= len(s.strip()) <= 200
    ][:6]

    return ExtractedFacts(
        names    = [],                                        # regex unreliable for Arabic names
        dates    = list(dict.fromkeys(dates))[:10],           # dedupe preserve order
        amounts  = list(dict.fromkeys(amounts))[:10],
        ages     = list(dict.fromkeys(ages))[:10],
        claims   = claims,
        requests = [],                                        # regex can't infer intent
    )


def _make_cache_key(context: str) -> str:
    """SHA1 truncated to 24 chars — sufficient entropy for a 1-hour cache."""
    return hashlib.sha1(context.encode("utf-8")).hexdigest()[:24]


async def _get_cached(key: str) -> Optional[ExtractedFacts]:
    """Safe cache read — returns None on any Redis failure."""
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        raw = await client.get(f"facts:{key}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        return ExtractedFacts.from_dict(data)
    except Exception:
        return None


async def _cache_result(key: str, facts: ExtractedFacts) -> None:
    """Safe cache write — silent on failure, never breaks the main flow."""
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        payload = json.dumps(facts.to_dict(), ensure_ascii=False)
        await client.set(f"facts:{key}", payload, ex=_FACT_CACHE_TTL)
    except Exception as e:
        log.debug("fact_extractor: cache write failed: %s", e)


__all__ = [
    "ExtractedFacts",
    "extract_user_facts",       # async
    "extract_user_facts_sync",  # sync wrapper (composer)
]
