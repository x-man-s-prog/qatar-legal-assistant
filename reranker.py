# -*- coding: utf-8 -*-
"""
reranker.py — إعادة ترتيب نتائج البحث بـ LLM
==============================================
بعد hybrid_search يُقيّم كل chunk مقابل السؤال (0-10)
ويُعيد أفضل top_k chunks فقط للـ LLM النهائي.

Fallback: إذا لم يتوفر LLM يستخدم heuristic score (كلمات مشتركة).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

_svc: Optional["Reranker"] = None


def init_reranker(llm_fn=None) -> "Reranker":
    global _svc
    _svc = Reranker(llm_fn)
    return _svc


def get_reranker() -> Optional["Reranker"]:
    return _svc


# ══════════════════════════════════════════════════════════════
class Reranker:
    """
    Cross-encoder بسيط — يُقيّم كل chunk بالسؤال ويُعيد الأفضل.
    بدون LLM: يتراجع لـ heuristic score (أسرع، دقة أقل).
    """

    def __init__(self, llm_fn=None):
        self._llm_fn = llm_fn   # async fn(prompt: str) -> str

    async def score_chunk(self, query: str, chunk_text: str) -> float:
        """يُقيّم مدى صلة chunk بالسؤال من 0 إلى 10."""
        if not chunk_text or not chunk_text.strip():
            return 0.0
        if not self._llm_fn:
            return _heuristic_score(query, chunk_text)
        try:
            raw = await self._llm_fn(_build_score_prompt(query, chunk_text))
            return _parse_score(raw)
        except Exception as e:
            log.debug("score_chunk LLM error: %s — fallback to heuristic", e)
            return _heuristic_score(query, chunk_text)

    async def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_k: int = 3,
    ) -> list[dict]:
        """
        يُعيد ترتيب chunks ويُعيد أفضل top_k.
        إذا كان عدد chunks ≤ top_k يُعيدها كما هي.
        """
        if not chunks:
            return []
        if len(chunks) <= top_k:
            return chunks

        # score all chunks concurrently
        tasks  = [self.score_chunk(query, c.get("content", "")) for c in chunks]
        scores = await asyncio.gather(*tasks, return_exceptions=True)

        scored: list[dict] = []
        for chunk, score in zip(chunks, scores):
            s = float(score) if isinstance(score, (int, float)) else 5.0
            scored.append({**chunk, "_rerank_score": round(s, 2)})

        scored.sort(key=lambda x: x["_rerank_score"], reverse=True)
        return scored[:top_k]


# ══════════════════════════════════════════════════════════════
# Pure helpers — testable without DB or LLM
# ══════════════════════════════════════════════════════════════

def _build_score_prompt(query: str, chunk_text: str) -> str:
    """يبني prompt تقييم الصلة للـ LLM."""
    return (
        f"سؤال: {query}\n\n"
        f"نص قانوني:\n{chunk_text[:350]}\n\n"
        "هل هذا النص يُجيب على السؤال أعلاه؟\n"
        "أجب بـ رقم واحد فقط من 0 إلى 10:\n"
        "0 = غير ذي صلة تماماً | 10 = إجابة مباشرة وشاملة\n"
        "الرقم:"
    )


def _parse_score(raw: str) -> float:
    """يستخرج الرقم من رد اللم ويُعيده في نطاق [0, 10]."""
    if not raw:
        return 5.0
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", raw.strip())
    if m:
        val = float(m.group(1))
        return max(0.0, min(10.0, val))
    return 5.0


def _heuristic_score(query: str, text: str) -> float:
    """
    نقاط بسيطة بناءً على الكلمات العربية المشتركة.
    دقة معقولة بدون LLM — O(n) سريع جداً.
    """
    q_words = set(re.findall(r"[\u0600-\u06FF]{3,}", query))
    t_words = set(re.findall(r"[\u0600-\u06FF]{3,}", text or ""))
    if not q_words:
        return 5.0
    common = q_words & t_words
    ratio  = len(common) / len(q_words)
    return round(min(10.0, 2.0 + ratio * 8.0), 2)
