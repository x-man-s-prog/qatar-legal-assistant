# -*- coding: utf-8 -*-
"""
core/legal_knowledge_graph.py — multi-hop article reasoning.

WHY THIS EXISTS
===============
A real lawyer reasons across a NETWORK of articles:
  Article 183 (grounds for custody loss) → refers to conditions in
  Article 167 (guardian eligibility) → refers to condition about
  spouse in Article 168 → procedural article 182 (who may file
  the action).

Pre-CP8 engines had NO notion of this network. They dumped every
article in ``domain.article_refs`` or picked by LLM without
understanding relationships.

This module gives the engine multi-hop expansion:

    expand_article_network(primary="183", candidate_pool=[...])
      → ArticleNetwork {
          primary: 183,
          referenced_by_primary: [167, 168],   # articles 183 cites
          references_primary: [182],           # articles that cite 183
          same_topic: [170, 186],              # same chapter/topic
          reasoning_chain: "183 → 167 (conditions) → 168 (spouse)"
      }

The engines then include the NETWORK in the composer prompt, not
just the primary article. Output cites the chain coherently:
"استناداً للمادة 183 فقرة 3 التي تشير إلى شروط الحضانة في
المادة 167، مع مراعاة المادة 168 بشأن الزواج الجديد..."

DESIGN
======
LLM-powered extraction, Redis-cached. No pre-compute of the entire
legal code — that's expensive and the corpus is vast. Instead:
  • At query time, LLM reads the primary article's text + candidate
    pool texts and identifies relationships.
  • Result cached by (primary_article_num, pool_fingerprint).
  • TTL 24 hours (legal text is stable, rulings change slowly).
  • If LLM fails → return empty ArticleNetwork. Caller proceeds
    with primary only — no regression on failure.

NON-GOALS
=========
  • Does NOT replace article_summary (still the source of truth).
  • Does NOT build a global graph of ALL Qatari law — only the
    domain-scoped local neighborhood for each query.
  • Does NOT reorder the candidate pool — only annotates relationships.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

_LLM_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS   = 24 * 3600  # 24h — articles are stable
_MAX_REFS            = 6
_EXTRACT_MAX_TOKENS  = 400


@dataclass
class ArticleNetwork:
    """The local neighborhood around a primary article."""
    primary:                str                = ""
    referenced_by_primary:  list[str]          = field(default_factory=list)
    references_primary:     list[str]          = field(default_factory=list)
    same_topic:             list[str]          = field(default_factory=list)
    reasoning_chain:        str                = ""

    def is_empty(self) -> bool:
        return not (
            self.referenced_by_primary
            or self.references_primary
            or self.same_topic
        )

    def all_related(self) -> list[str]:
        """All related article numbers, deduplicated, excluding primary."""
        s = set()
        for lst in (self.referenced_by_primary,
                    self.references_primary,
                    self.same_topic):
            s.update(lst)
        s.discard(self.primary)
        return sorted(s, key=lambda x: int(x) if x.isdigit() else 9999)


_EXPAND_NETWORK_SYSTEM = """\
أنت محامٍ قطري خبير تحلل العلاقات بين مواد القانون.

لديك:
- مادة أساسية (primary).
- قائمة من المواد المرشحة في نفس المجال.

مهمتك: حدد العلاقات الفعلية بينها، بناءً على قراءة نصوصها.

قواعد:
1. "referenced_by_primary" = المواد التي تُشير إليها المادة الأساسية
   صراحةً في نصها (مثلاً "وفق شروط المادة 167").
2. "references_primary" = المواد التي تُشير إلى المادة الأساسية في
   نصها (مثلاً المادة 182 تذكر شروط المادة 183).
3. "same_topic" = المواد في نفس الفصل/الباب/الموضوع (حضانة، طلاق،
   عمل، شيكات، ...) ولكن بلا إشارة مباشرة.
4. لا تُخمّن إشارات غير موجودة — فقط ما يظهر في النص.
5. "reasoning_chain" = جملة واحدة (بالعربية) تصف كيف تترابط هذه
   المواد في سياق الأساس القانوني.

أخرج JSON فقط بالبنية:
{
  "referenced_by_primary": ["رقم1", "رقم2", ...],
  "references_primary": ["رقم3", ...],
  "same_topic": ["رقم4", "رقم5", ...],
  "reasoning_chain": "..."
}
لا نص خارج JSON.
"""


async def expand_article_network(
    primary_article:  str,
    primary_text:     str,
    candidate_pool:   list[dict],   # [{number, law_name, text}]
    domain_key:       Optional[str] = None,
) -> ArticleNetwork:
    """Build the local article network for the primary article.

    Returns empty ``ArticleNetwork`` on any failure. Never raises.
    """
    net = ArticleNetwork(primary=str(primary_article or ""))
    if not primary_article or not candidate_pool:
        return net

    # Cache by fingerprint
    pool_nums = sorted(str(c.get("number", "")) for c in candidate_pool)
    cache_key = _fingerprint({
        "stage":  "article_network",
        "primary": primary_article,
        "pool":    pool_nums,
        "domain":  domain_key or "",
    })
    cached = await _cache_get(cache_key)
    if cached:
        try:
            return ArticleNetwork(
                primary               = str(primary_article),
                referenced_by_primary = list(cached.get("referenced_by_primary", []))[:_MAX_REFS],
                references_primary    = list(cached.get("references_primary", []))[:_MAX_REFS],
                same_topic            = list(cached.get("same_topic", []))[:_MAX_REFS],
                reasoning_chain       = str(cached.get("reasoning_chain", "")),
            )
        except Exception:
            pass

    # Build user message for LLM
    pool_text = "\n".join(
        f"المادة ({c.get('number', '?')}): {(c.get('text') or '')[:200]}..."
        for c in candidate_pool[:10]
    )
    user_msg = (
        f"المادة الأساسية: ({primary_article})\n"
        f"نصها: {(primary_text or '')[:500]}\n\n"
        f"المواد المرشحة في المجال:\n{pool_text}\n\n"
        f"حدد العلاقات."
    )

    raw = await _llm_json_call(_EXPAND_NETWORK_SYSTEM, user_msg, _EXTRACT_MAX_TOKENS)
    if not raw:
        return net

    try:
        net.referenced_by_primary = [
            str(x) for x in raw.get("referenced_by_primary", [])
        ][:_MAX_REFS]
        net.references_primary = [
            str(x) for x in raw.get("references_primary", [])
        ][:_MAX_REFS]
        net.same_topic = [
            str(x) for x in raw.get("same_topic", [])
        ][:_MAX_REFS]
        net.reasoning_chain = str(raw.get("reasoning_chain", ""))[:500]
    except Exception as e:
        log.warning("article_network: parse failed: %s", e)
        return ArticleNetwork(primary=str(primary_article))

    await _cache_set(cache_key, {
        "referenced_by_primary": net.referenced_by_primary,
        "references_primary":    net.references_primary,
        "same_topic":            net.same_topic,
        "reasoning_chain":       net.reasoning_chain,
    })
    return net


# ═══════════════════════════════════════════════════════════════════
# LLM + cache helpers
# ═══════════════════════════════════════════════════════════════════

async def _llm_json_call(
    system:       str,
    user_message: str,
    max_tokens:   int,
) -> Optional[dict]:
    try:
        from services.llm_service import call_openai
    except ImportError:
        return None
    try:
        resp = await asyncio.wait_for(
            call_openai(
                system=system,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=max_tokens,
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None

    if not resp or not isinstance(resp, str) or resp.strip().startswith("خطأ"):
        return None
    cleaned = resp.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:])
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _fingerprint(obj: Any) -> str:
    try:
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:24]


async def _cache_get(key: str) -> Optional[Any]:
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        raw = await client.get(f"kg:{key}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None


async def _cache_set(key: str, value: Any) -> None:
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        await client.set(
            f"kg:{key}",
            json.dumps(value, ensure_ascii=False),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass


__all__ = ["ArticleNetwork", "expand_article_network"]
