# -*- coding: utf-8 -*-
"""
db_fix_layer1.py — إصلاح قاعدة البيانات القانونية (الطبقة الأولى)
المحور 1: إنشاء embeddings المفقودة
المحور 2: تنظيف التالفة + المكررة
المحور 3: دمج chunks القصيرة (الديباجات)
"""
import asyncio
import json
import re
import sys
import time
import urllib.request
from collections import defaultdict

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
BATCH_COMMIT = 50
LOG_EVERY = 100

RE_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
RE_OCR_HARD = re.compile(
    r"(ع[\d@\-]{2,})"
    r"|(سس\s*[=\-])"
    r"|(للظب[ةا])"
    r"|(لررسا\s*=)"
    r"|(رذ\s+انخدة)"
    r"|(لندمة\s+بر)"
    r"|(لنارة\s+بلمائك)"
    r"|(عدأعشو)"
    r"|(دإ\s+عط\s+شس)"
)
RE_PREAMBLE = re.compile(
    r"(الوزراء|مشروع المرسوم|اقتراح وزير|مجلس الشورى|"
    r"مشروع القانون المقدم|وعلى مشروع|أخذ رأي مجلس|"
    r"نزع الملكية.*المواد|بشأن قرارات مجلس)"
)


def arabic_ratio(text: str) -> float:
    if not text or not text.strip():
        return 0.0
    return len(RE_ARABIC.findall(text)) / len(text.strip())


def get_embedding(text: str) -> list[float] | None:
    """Call Ollama embedding API synchronously."""
    data = json.dumps({"model": EMBED_MODEL, "prompt": text[:2000]}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data,
                                headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        emb = result.get("embedding", [])
        return emb if len(emb) > 0 else None
    except Exception as e:
        print(f"  [WARN] embedding failed: {e}")
        return None


def emb_to_pgvector(emb: list[float]) -> str:
    """Convert embedding list to pgvector string format."""
    return "[" + ",".join(f"{x:.8f}" for x in emb) + "]"


# ====================================================================
# Step 0: Backup
# ====================================================================
async def create_backup(conn) -> dict:
    print("=" * 60)
    print("  Step 0: Creating backup...")
    print("=" * 60)

    existing = await conn.fetchval(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_name = 'chunks_backup_pre_fix'"
    )
    if existing > 0:
        print("  Backup table already exists. Dropping and recreating...")
        await conn.execute("DROP TABLE chunks_backup_pre_fix")

    await conn.execute("CREATE TABLE chunks_backup_pre_fix AS SELECT * FROM chunks")
    cnt = await conn.fetchval("SELECT count(*) FROM chunks_backup_pre_fix")
    print(f"  Backup created: {cnt:,} rows")
    return {"backup_rows": cnt}


# ====================================================================
# Step 1: Fix missing embeddings
# ====================================================================
async def fix_missing_embeddings(conn) -> dict:
    print("\n" + "=" * 60)
    print("  Step 1: Fixing missing embeddings")
    print("=" * 60)

    rows = await conn.fetch("""
        SELECT id, content, law_name
        FROM chunks
        WHERE is_active = true AND embedding IS NULL
        ORDER BY id
    """)
    print(f"  Found {len(rows):,} chunks without embedding")

    stats = {"total": len(rows), "embedded": 0, "skipped": 0, "errors": 0}
    start = time.time()

    for i, row in enumerate(rows):
        content = row["content"] or ""
        # Skip invalid content
        if len(content) < 30 or arabic_ratio(content) < 0.10:
            stats["skipped"] += 1
            continue

        emb = get_embedding(content)
        if emb:
            emb_str = emb_to_pgvector(emb)
            await conn.execute(
                "UPDATE chunks SET embedding = $1::vector WHERE id = $2",
                emb_str, row["id"]
            )
            stats["embedded"] += 1
        else:
            stats["errors"] += 1

        if (i + 1) % LOG_EVERY == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            remaining = (len(rows) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{len(rows)}] embedded={stats['embedded']} "
                  f"skip={stats['skipped']} err={stats['errors']} "
                  f"({rate:.0f}/s, ~{remaining:.0f}s left)")

    elapsed = time.time() - start
    print(f"\n  Done in {elapsed:.1f}s")
    print(f"  Embedded: {stats['embedded']:,}")
    print(f"  Skipped:  {stats['skipped']:,}")
    print(f"  Errors:   {stats['errors']:,}")

    # Verify
    remaining_null = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE is_active=true AND embedding IS NULL"
    )
    print(f"  Remaining without embedding: {remaining_null}")
    stats["remaining_null"] = remaining_null
    return stats


# ====================================================================
# Step 2: Cleanup corrupt + duplicates
# ====================================================================
async def cleanup_corrupt_and_duplicates(conn) -> dict:
    print("\n" + "=" * 60)
    print("  Step 2: Cleaning corrupt + duplicate chunks")
    print("=" * 60)

    stats = {"corrupt_deactivated": 0, "corrupt_legitimate": 0,
             "duplicates_deactivated": 0, "duplicate_groups": 0}

    # --- 2a: Corrupt chunks ---
    print("\n  --- 2a: Corrupt OCR chunks ---")
    rows = await conn.fetch("""
        SELECT id, content, law_name, article_number
        FROM chunks WHERE is_active = true
    """)

    truly_corrupt_ids = []
    legitimate_foreign = 0

    for row in rows:
        content = row["content"] or ""
        # Check for hard OCR patterns
        if RE_OCR_HARD.search(content):
            truly_corrupt_ids.append(row["id"])
        elif arabic_ratio(content) < 0.10 and len(content) > 50:
            truly_corrupt_ids.append(row["id"])

    # Also check for English-only chunks (articles that are entirely in English)
    for row in rows:
        content = row["content"] or ""
        ar = arabic_ratio(content)
        if ar < 0.15 and len(content) > 100:
            # Check if it's scientific terms (legitimate) or pure garbage
            has_real_arabic = bool(re.search(r"(المادة|القانون|قرار|مرسوم)", content))
            if not has_real_arabic and row["id"] not in truly_corrupt_ids:
                truly_corrupt_ids.append(row["id"])

    truly_corrupt_ids = list(set(truly_corrupt_ids))

    if truly_corrupt_ids:
        await conn.execute(
            "UPDATE chunks SET is_active = false WHERE id = ANY($1::int[])",
            truly_corrupt_ids
        )
    stats["corrupt_deactivated"] = len(truly_corrupt_ids)
    print(f"  Deactivated {len(truly_corrupt_ids)} truly corrupt chunks")

    # --- 2b: Duplicates ---
    print("\n  --- 2b: Duplicate chunks ---")
    dup_rows = await conn.fetch("""
        WITH dups AS (
            SELECT content, array_agg(id ORDER BY id DESC) as ids, count(*) as cnt
            FROM chunks
            WHERE is_active = true
            GROUP BY content
            HAVING count(*) > 1
        )
        SELECT ids, cnt FROM dups
    """)

    dup_ids_to_remove = []
    for row in dup_rows:
        ids = row["ids"]
        # Keep the first (highest id = most recent), remove the rest
        dup_ids_to_remove.extend(ids[1:])
        stats["duplicate_groups"] += 1

    if dup_ids_to_remove:
        # Process in batches
        for i in range(0, len(dup_ids_to_remove), 1000):
            batch = dup_ids_to_remove[i:i+1000]
            await conn.execute(
                "UPDATE chunks SET is_active = false WHERE id = ANY($1::int[])",
                batch
            )
    stats["duplicates_deactivated"] = len(dup_ids_to_remove)
    print(f"  Found {stats['duplicate_groups']} duplicate groups")
    print(f"  Deactivated {len(dup_ids_to_remove):,} duplicate chunks")

    return stats


# ====================================================================
# Step 3: Merge short preamble chunks
# ====================================================================
async def merge_short_chunks(conn) -> dict:
    print("\n" + "=" * 60)
    print("  Step 3: Merging short preamble chunks")
    print("=" * 60)

    stats = {"preambles_merged": 0, "preambles_deactivated": 0,
             "new_merged_chunks": 0, "short_kept": 0}

    # Fetch short preamble chunks grouped by law
    preamble_rows = await conn.fetch("""
        SELECT id, law_name, law_number, law_year, article_number,
               content, domain, source
        FROM chunks
        WHERE is_active = true
          AND length(content) < 200
          AND content ~ '(الوزراء|مشروع المرسوم|اقتراح وزير|مجلس الشورى|مشروع القانون|وعلى مشروع|أخذ رأي|نزع الملكية.*المواد|بشأن قرارات)'
        ORDER BY law_name, law_number, law_year, id
    """)
    print(f"  Found {len(preamble_rows):,} short preamble chunks")

    # Group by law
    law_groups = defaultdict(list)
    for row in preamble_rows:
        key = (row["law_name"], row["law_number"], row["law_year"])
        law_groups[key].append(row)

    merged_count = 0
    deactivated_ids = []
    new_chunks_data = []

    for law_key, chunks in law_groups.items():
        if len(chunks) < 2:
            stats["short_kept"] += 1
            continue

        # Merge all preamble chunks for this law into one
        merged_content = "\n---\n".join(c["content"] for c in chunks)

        # Enforce max 2000 chars
        if len(merged_content) > 2000:
            merged_content = merged_content[:2000]

        # Keep first chunk's metadata, update content
        first = chunks[0]
        new_chunks_data.append({
            "law_name": first["law_name"],
            "law_number": first["law_number"],
            "law_year": first["law_year"],
            "article_number": "مقدمة",
            "content": merged_content,
            "domain": first["domain"],
            "source": first["source"],
        })

        # Deactivate all original chunks
        for c in chunks:
            deactivated_ids.append(c["id"])
        merged_count += len(chunks)

    # Deactivate old preamble chunks
    if deactivated_ids:
        for i in range(0, len(deactivated_ids), 1000):
            batch = deactivated_ids[i:i+1000]
            await conn.execute(
                "UPDATE chunks SET is_active = false WHERE id = ANY($1::int[])",
                batch
            )

    # Insert new merged chunks with embeddings
    inserted = 0
    for nc in new_chunks_data:
        emb = get_embedding(nc["content"])
        emb_str = emb_to_pgvector(emb) if emb else None

        # Use unique article_number to avoid constraint violation
        art_num = f"مقدمة-مدمج-{inserted+1}"
        if emb_str:
            await conn.execute("""
                INSERT INTO chunks
                    (law_name, law_number, law_year, article_number,
                     content, embedding, domain, source, is_active)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8, true)
            """, nc["law_name"], nc["law_number"], nc["law_year"],
                art_num, nc["content"], emb_str,
                nc["domain"], nc["source"])
        else:
            await conn.execute("""
                INSERT INTO chunks
                    (law_name, law_number, law_year, article_number,
                     content, domain, source, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, $7, true)
            """, nc["law_name"], nc["law_number"], nc["law_year"],
                art_num, nc["content"],
                nc["domain"], nc["source"])
        inserted += 1

    stats["preambles_merged"] = merged_count
    stats["preambles_deactivated"] = len(deactivated_ids)
    stats["new_merged_chunks"] = inserted
    print(f"  Merged {merged_count} preamble chunks into {inserted} new chunks")
    print(f"  Deactivated {len(deactivated_ids)} old preamble chunks")

    return stats


# ====================================================================
# Main
# ====================================================================
async def main():
    try:
        import asyncpg
    except ImportError:
        print("ERROR: pip install asyncpg")
        sys.exit(1)

    conn = await asyncpg.connect(DB_DSN)
    print("Connected to database.\n")

    # Pre-stats
    pre_total = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    pre_null_emb = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE is_active=true AND embedding IS NULL"
    )
    print(f"BEFORE: {pre_total:,} active chunks | {pre_null_emb:,} without embedding\n")

    all_stats = {"pre_total": pre_total, "pre_null_emb": pre_null_emb}

    # Step 0: Backup
    s0 = await create_backup(conn)
    all_stats["backup"] = s0

    # Step 1: Embeddings
    s1 = await fix_missing_embeddings(conn)
    all_stats["embeddings"] = s1

    # Step 2: Cleanup
    s2 = await cleanup_corrupt_and_duplicates(conn)
    all_stats["cleanup"] = s2

    # Step 3: Merge
    s3 = await merge_short_chunks(conn)
    all_stats["merge"] = s3

    # Post-stats
    post_total = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    post_null_emb = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE is_active=true AND embedding IS NULL"
    )
    post_with_emb = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE is_active=true AND embedding IS NOT NULL"
    )
    all_stats["post_total"] = post_total
    all_stats["post_null_emb"] = post_null_emb
    all_stats["post_with_emb"] = post_with_emb
    all_stats["coverage_pct"] = round(100 * post_with_emb / post_total, 1) if post_total > 0 else 0

    # Size distribution after
    size_dist = await conn.fetch("""
        SELECT
          CASE
            WHEN length(content) < 50 THEN 'tiny'
            WHEN length(content) < 200 THEN 'small'
            WHEN length(content) < 500 THEN 'medium'
            WHEN length(content) < 1000 THEN 'good'
            WHEN length(content) < 2000 THEN 'large'
            ELSE 'huge'
          END as sz, count(*) as cnt
        FROM chunks WHERE is_active=true
        GROUP BY 1 ORDER BY min(length(content))
    """)
    all_stats["post_size_distribution"] = {r["sz"]: r["cnt"] for r in size_dist}

    await conn.close()

    # Print final report
    print("\n" + "=" * 60)
    print("  FINAL REPORT")
    print("=" * 60)
    print(f"  BEFORE: {pre_total:,} active | {pre_null_emb:,} no-embedding")
    print(f"  AFTER:  {post_total:,} active | {post_null_emb:,} no-embedding")
    print(f"  Embedding coverage: {all_stats['coverage_pct']}%")
    print(f"\n  Embeddings created:     {s1['embedded']:,}")
    print(f"  Corrupt deactivated:    {s2['corrupt_deactivated']:,}")
    print(f"  Duplicates deactivated: {s2['duplicates_deactivated']:,}")
    print(f"  Preambles merged:       {s3['preambles_merged']:,} -> {s3['new_merged_chunks']:,}")
    print(f"\n  Size distribution (after):")
    for sz, cnt in all_stats.get("post_size_distribution", {}).items():
        pct = 100 * cnt / post_total if post_total > 0 else 0
        print(f"    {sz:>8s}: {cnt:>6,} ({pct:.1f}%)")

    # Save JSON report
    out = "scripts/db_fix_layer1_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)
    print(f"\n  Report saved: {out}")


if __name__ == "__main__":
    asyncio.run(main())
