# -*- coding: utf-8 -*-
"""
core/chunk_overlap.py — Chunk Overlap & Context Window Expansion
=================================================================
When a relevant chunk is found, fetches its neighboring chunks
to provide broader legal context. This prevents cutting off
important content at chunk boundaries.

Architecture:
    chunk_id → DB lookup (prev/next chunks) → merged context
"""
import logging
from typing import Optional

log = logging.getLogger(__name__)


async def expand_chunk_context(
    chunk: dict,
    pool,
    window: int = 1,
) -> dict:
    """
    Expand a single chunk by fetching its neighbors.

    Args:
        chunk: Original chunk dict with law_name, article_number, chunk_index
        pool: asyncpg pool
        window: Number of neighbors to fetch (1 = prev + next)

    Returns:
        Chunk with expanded content field
    """
    if not pool or not chunk:
        return chunk

    law_name = chunk.get("law_name", "")
    chunk_idx = chunk.get("chunk_index")
    article_num = chunk.get("article_number", "")

    if chunk_idx is None or not law_name:
        return chunk

    try:
        async with pool.acquire() as conn:
            # Fetch neighboring chunks from same law
            rows = await conn.fetch(
                """
                SELECT content, chunk_index, article_number
                FROM legal_chunks
                WHERE law_name = $1
                  AND chunk_index BETWEEN $2 AND $3
                ORDER BY chunk_index
                """,
                law_name,
                max(0, chunk_idx - window),
                chunk_idx + window,
            )

            if len(rows) <= 1:
                return chunk

            # Merge content with markers
            parts = []
            for row in rows:
                idx = row["chunk_index"]
                content = row["content"]
                if idx == chunk_idx:
                    parts.append(content)
                else:
                    # Neighbor content — add as supplementary
                    parts.append(f"[سياق مجاور] {content}")

            expanded = "\n".join(parts)
            chunk["original_content"] = chunk.get("content", "")
            chunk["content"] = expanded
            chunk["expanded"] = True
            chunk["neighbor_count"] = len(rows) - 1

    except Exception as e:
        log.debug("chunk_expand (non-critical): %s", e)

    return chunk


async def expand_relevant_chunks(
    chunks: list,
    pool,
    top_n: int = 3,
    window: int = 1,
) -> list:
    """
    Expand the top N most relevant chunks with neighboring context.

    Only expands the top chunks to avoid excessive DB queries.

    Args:
        chunks: Sorted list of relevant chunks
        pool: asyncpg pool
        top_n: Number of top chunks to expand
        window: Neighbor window size

    Returns:
        Chunks with top ones expanded
    """
    if not pool or not chunks:
        return chunks

    expanded_count = 0
    for i, chunk in enumerate(chunks[:top_n]):
        try:
            chunks[i] = await expand_chunk_context(chunk, pool, window)
            if chunks[i].get("expanded"):
                expanded_count += 1
        except Exception as e:
            log.debug("chunk_expand[%d] (non-critical): %s", i, e)

    if expanded_count:
        log.info("chunk_overlap: expanded %d/%d top chunks", expanded_count, min(top_n, len(chunks)))

    return chunks
