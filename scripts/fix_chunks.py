# -*- coding: utf-8 -*-
"""
scripts/fix_chunks.py — تنظيف قاعدة بيانات الـ chunks وإعادة بناء الفهرس.
=========================================================================
يقوم بـ:
1. قراءة جميع الـ chunks من PostgreSQL
2. تصفية وحذف الـ chunks غير الصالحة:
   - أقل من 50 حرف
   - لا تحتوي أحرف عربية
   - بيانات ثنائية (binary artifacts)
   - أكثر من 80% أرقام
3. إعادة بناء فهرس HNSW للبحث المتجهي
4. طباعة تقرير: قبل / بعد / عدد المحذوف

الاستخدام:
    python scripts/fix_chunks.py
    python scripts/fix_chunks.py --dry-run   (تقرير بدون حذف)
    python scripts/fix_chunks.py --rebuild-index   (إعادة بناء الفهرس فقط)
"""
import asyncio
import asyncpg
import os
import re
import sys
import argparse
import logging
from pathlib import Path

# ── Add project root to path ──
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Load config ──
from core.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


# ══════════════════════════════════════════════════════════════
# Chunk quality filters
# ══════════════════════════════════════════════════════════════

def _has_arabic(text: str) -> bool:
    """يحتوي على حروف عربية."""
    return bool(re.search(r'[\u0600-\u06FF]', text))


def _is_mostly_numbers(text: str) -> bool:
    """أكثر من 80% من الأحرف غير المسافات أرقام."""
    stripped = text.replace(" ", "").replace("\n", "")
    if not stripped:
        return True
    digits = sum(1 for c in stripped if c.isdigit())
    return digits / len(stripped) > 0.8


def _has_binary_artifacts(text: str) -> bool:
    """يحتوي بيانات ثنائية (non-printable chars > 5%)."""
    if not text:
        return False
    non_printable = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
    return len(text) > 0 and non_printable / len(text) > 0.05


def is_valid_chunk(content: str) -> tuple[bool, str]:
    """
    Returns (is_valid, reason).
    reason is '' when valid, or a description of why it was rejected.
    """
    if not content or len(content.strip()) < 50:
        return False, f"too_short ({len(content.strip() if content else '')} chars)"
    if not _has_arabic(content):
        return False, "no_arabic"
    if _is_mostly_numbers(content):
        return False, "mostly_numbers"
    if _has_binary_artifacts(content):
        return False, "binary_artifacts"
    return True, ""


# ══════════════════════════════════════════════════════════════
# Main logic
# ══════════════════════════════════════════════════════════════

async def run(dry_run: bool = False, rebuild_index_only: bool = False):
    log.info("الاتصال بـ PostgreSQL...")
    pool = await asyncpg.create_pool(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        min_size=1, max_size=3, ssl=False,
    )

    try:
        if rebuild_index_only:
            await _rebuild_hnsw_index(pool)
            return

        # ── 1. Count before ──
        total_before = await pool.fetchval("SELECT COUNT(*) FROM chunks")
        log.info("إجمالي الـ chunks قبل التنظيف: %d", total_before)

        # ── 2. Scan all chunks ──
        log.info("قراءة الـ chunks...")
        rows = await pool.fetch("SELECT id, content FROM chunks ORDER BY id")

        to_delete: list[int] = []
        reasons: dict[str, int] = {}

        for row in rows:
            valid, reason = is_valid_chunk(row["content"] or "")
            if not valid:
                to_delete.append(row["id"])
                reasons[reason] = reasons.get(reason, 0) + 1

        # ── 3. Report ──
        log.info("Chunks للحذف: %d / %d", len(to_delete), total_before)
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            log.info("  %-25s : %d", reason, count)

        if dry_run:
            log.info("[DRY RUN] لم يُحذف شيء.")
            return

        # ── 4. Delete ──
        if to_delete:
            # Delete in batches of 1000 to avoid huge query
            batch_size = 1000
            deleted = 0
            for i in range(0, len(to_delete), batch_size):
                batch = to_delete[i:i + batch_size]
                await pool.execute(
                    "DELETE FROM chunks WHERE id = ANY($1::int[])", batch
                )
                deleted += len(batch)
                log.info("  حُذف: %d / %d", deleted, len(to_delete))
        else:
            log.info("لا توجد chunks تحتاج للحذف.")

        # ── 5. Count after ──
        total_after = await pool.fetchval("SELECT COUNT(*) FROM chunks")
        log.info("الـ chunks بعد التنظيف: %d (حُذف: %d)", total_after, total_before - total_after)

        # ── 6. Rebuild HNSW index ──
        await _rebuild_hnsw_index(pool)

    finally:
        await pool.close()


async def _rebuild_hnsw_index(pool: asyncpg.Pool):
    """Drop + recreate HNSW index for cosine similarity search."""
    log.info("إعادة بناء فهرس HNSW...")

    # Drop existing index if present
    try:
        await pool.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")
        log.info("  حُذف الفهرس القديم")
    except Exception as e:
        log.warning("  تعذّر حذف الفهرس: %s", e)

    # Rebuild — CONCURRENTLY not supported inside transaction, use direct connection
    async with pool.acquire() as conn:
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
                ON chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """)
            log.info("  تم بناء فهرس HNSW (m=16, ef_construction=64)")
        except Exception as e:
            log.warning("  تعذّر بناء فهرس HNSW (قد لا تكون pgvector مثبتة): %s", e)
            # Fallback: try IVFFlat
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS chunks_embedding_ivfflat_idx
                    ON chunks USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
                log.info("  تم بناء فهرس IVFFlat (fallback)")
            except Exception as e2:
                log.warning("  IVFFlat fallback فشل: %s", e2)

    # Vacuum analyze for fresh stats
    try:
        async with pool.acquire() as conn:
            await conn.execute("VACUUM ANALYZE chunks")
            log.info("  VACUUM ANALYZE مكتمل")
    except Exception as e:
        log.warning("  VACUUM ANALYZE: %s", e)

    log.info("إعادة بناء الفهرس مكتملة.")


# ══════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="تنظيف chunks وإعادة بناء الفهرس")
    parser.add_argument("--dry-run", action="store_true",
                        help="تقرير بدون حذف")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="إعادة بناء الفهرس فقط بدون تنظيف")
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, rebuild_index_only=args.rebuild_index))
    log.info("Done.")


if __name__ == "__main__":
    main()
