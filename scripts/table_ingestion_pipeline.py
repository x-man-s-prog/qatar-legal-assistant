#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Legal Table Ingestion Pipeline
==============================
1. Audit corpus for missing tables/schedules/appendices
2. Fetch from Al Meezan
3. Parse and normalize
4. Store in structured legal_tables table
5. Also insert as chunks for RAG retrieval
6. Generate diagnostic report

Usage: python3 scripts/table_ingestion_pipeline.py [--audit-only] [--law-ids 62,499]
"""
import asyncio, asyncpg, hashlib, json, logging, re, sys, time
from datetime import datetime
from typing import Optional
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("table_pipeline")

DB_DSN = "postgresql://raguser:RAGsecret2024!@db:5432/ragdb"
BASE_URL = "https://www.almeezan.qa"
LAW_PAGE = f"{BASE_URL}/LawPage.aspx"
ATTACH_PAGE = f"{BASE_URL}/LawOtherAttachments.aspx"
TIMEOUT = 45

# ══════════════════════════════════════════════════════════════
# Schema Setup
# ══════════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS legal_tables (
    id SERIAL PRIMARY KEY,
    parent_law_name TEXT NOT NULL,
    parent_law_number TEXT,
    parent_law_year TEXT,
    law_id INTEGER,
    law_url TEXT,
    source TEXT DEFAULT 'almeezan',
    source_type TEXT DEFAULT 'statute_table',
    table_number TEXT,
    appendix_number TEXT,
    schedule_number TEXT,
    band_number TEXT,
    item_number TEXT,
    row_order INTEGER DEFAULT 0,
    item_title TEXT,
    item_text TEXT,
    raw_text TEXT,
    normalized_text TEXT,
    content_hash TEXT UNIQUE,
    fetch_status TEXT DEFAULT 'pending',
    completeness_status TEXT DEFAULT 'unknown',
    is_amendment BOOLEAN DEFAULT FALSE,
    amending_law_name TEXT,
    fetched_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lt_law ON legal_tables(parent_law_number, parent_law_year);
CREATE INDEX IF NOT EXISTS idx_lt_type ON legal_tables(source_type);
CREATE INDEX IF NOT EXISTS idx_lt_status ON legal_tables(fetch_status);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='chunks' AND column_name='source_type') THEN
        ALTER TABLE chunks ADD COLUMN source_type TEXT DEFAULT 'statute_text';
    END IF;
END $$;
"""

TABLE_REF_PATTERNS = [
    r"الجدول\s*(?:رقم)?\s*\(?\s*(\d+)",
    r"جدول\s+(?:الدرجات|الرواتب|المخدرات|المواد|الوظائف)",
    r"الملحق\s*(?:رقم)?\s*\(?\s*(\d+)",
    r"المرفق\s+بهذا\s+القانون",
    r"الجدول\s+المرفق",
    r"الجداول\s+الملحقة",
    r"وفقاً?\s+للجدول",
    r"جدول\s+الدرجات\s+والرواتب",
    r"سلم\s+الرواتب",
]


# ══════════════════════════════════════════════════════════════
# Phase 1: Audit
# ══════════════════════════════════════════════════════════════

async def audit_corpus(pool) -> list[dict]:
    """Scan all laws, detect table references, classify as present/missing."""
    log.info("[AUDIT] Starting full corpus scan...")
    async with pool.acquire() as conn:
        laws = await conn.fetch("""
            SELECT DISTINCT law_name, law_number, law_year,
                   MIN(law_id) as law_id, COUNT(*) as chunk_count
            FROM chunks WHERE is_active=true
            AND law_name NOT ILIKE '%أحكام محكمة التمييز%'
            GROUP BY law_name, law_number, law_year
            ORDER BY chunk_count DESC
        """)

    results = []
    for law in laws:
        lname = law["law_name"] or ""
        async with pool.acquire() as conn:
            chunks = await conn.fetch(
                "SELECT content, article_number FROM chunks "
                "WHERE is_active=true AND law_name=$1 AND law_number=$2",
                lname, law["law_number"]
            )

        all_text = " ".join(c["content"] for c in chunks)
        refs = []
        for pat in TABLE_REF_PATTERNS:
            if re.search(pat, all_text):
                refs.append(pat[:30])

        if not refs:
            continue

        has_attachment = any(
            c["article_number"] and str(c["article_number"]).startswith("مرفق")
            for c in chunks
        )
        has_table_content = any(
            len(re.findall(r"\d+[\s\-\.]+[^\d\n]{5,}", c["content"])) >= 3
            for c in chunks
        )

        if has_attachment and has_table_content:
            status = "PRESENT_COMPLETE"
        elif has_attachment or has_table_content:
            status = "PRESENT_PARTIAL"
        else:
            status = "MISSING"

        results.append({
            "law_name": lname, "law_number": law["law_number"],
            "law_year": law["law_year"], "law_id": law["law_id"],
            "chunks": law["chunk_count"], "refs": len(refs),
            "has_attachment": has_attachment,
            "has_table_content": has_table_content,
            "status": status,
        })

    missing = sum(1 for r in results if r["status"] == "MISSING")
    present = sum(1 for r in results if r["status"] != "MISSING")
    log.info("[AUDIT] %d laws with table refs: %d present, %d missing", len(results), present, missing)
    return results


# ══════════════════════════════════════════════════════════════
# Phase 2: Fetch from Al Meezan
# ══════════════════════════════════════════════════════════════

async def fetch_law_page(client: httpx.AsyncClient, law_id: int) -> Optional[str]:
    """Fetch the full law page from Al Meezan."""
    try:
        url = f"{LAW_PAGE}?id={law_id}&language=ar"
        r = await client.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            log.info("[ALMEEZAN_FETCH] law_id=%d page fetched (%d bytes)", law_id, len(r.text))
            return r.text
        log.warning("[ALMEEZAN_FETCH] law_id=%d status=%d", law_id, r.status_code)
    except Exception as e:
        log.error("[ALMEEZAN_FETCH] law_id=%d error: %s", law_id, e)
    return None


async def fetch_attachments_page(client: httpx.AsyncClient, law_id: int) -> Optional[str]:
    """Fetch the attachments/schedules page."""
    try:
        url = f"{ATTACH_PAGE}?id={law_id}&language=ar"
        r = await client.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            log.info("[ALMEEZAN_FETCH] law_id=%d attachments page fetched (%d bytes)", law_id, len(r.text))
            return r.text
        log.warning("[ALMEEZAN_FETCH] law_id=%d attachments status=%d", law_id, r.status_code)
    except Exception as e:
        log.error("[ALMEEZAN_FETCH] law_id=%d attachments error: %s", law_id, e)
    return None


# ══════════════════════════════════════════════════════════════
# Phase 3: Parse Tables from HTML
# ══════════════════════════════════════════════════════════════

def extract_tables_from_html(html: str, law_name: str, law_number: str,
                              law_year: str, law_id: int) -> list[dict]:
    """Extract table/schedule/appendix content from Al Meezan HTML."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.error("[TABLE_PARSE] BeautifulSoup not available")
        return []

    soup = BeautifulSoup(html, "html.parser")
    tables = []

    # Strategy 1: Find <table> elements
    for i, tbl in enumerate(soup.find_all("table")):
        rows = tbl.find_all("tr")
        if len(rows) < 2:
            continue

        row_data = []
        for j, tr in enumerate(rows):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells and any(len(c) > 2 for c in cells):
                row_data.append({
                    "row_order": j,
                    "cells": cells,
                    "raw": " | ".join(cells),
                })

        if len(row_data) >= 2:
            full_text = "\n".join(r["raw"] for r in row_data)
            tables.append({
                "table_number": str(i + 1),
                "source_type": "statute_table",
                "rows": row_data,
                "full_text": full_text,
                "row_count": len(row_data),
            })
            log.info("[TABLE_PARSE] HTML table %d: %d rows", i + 1, len(row_data))

    # Strategy 2: Find div/section with schedule content
    for div in soup.find_all(["div", "section"], class_=re.compile(r"schedule|table|appendix|ملحق|جدول", re.I)):
        text = div.get_text(separator="\n", strip=True)
        if len(text) > 50:
            tables.append({
                "table_number": "div",
                "source_type": "appendix",
                "rows": [],
                "full_text": text[:5000],
                "row_count": 0,
            })

    # Strategy 3: Find embedded text patterns (for inline tables)
    body = soup.get_text(separator="\n")
    # Look for schedule sections
    schedule_matches = re.finditer(
        r"(?:الجدول|جدول|ملحق|الملحق)\s*(?:رقم)?\s*\(?\s*(\d*)\)?\s*\n((?:.+\n){3,})",
        body
    )
    for m in schedule_matches:
        num = m.group(1) or "1"
        content = m.group(2).strip()
        if len(content) > 50:
            tables.append({
                "table_number": num,
                "source_type": "schedule",
                "rows": [],
                "full_text": content[:5000],
                "row_count": 0,
            })
            log.info("[TABLE_PARSE] inline schedule %s: %d chars", num, len(content))

    return tables


# ══════════════════════════════════════════════════════════════
# Phase 4: Normalize and Ingest
# ══════════════════════════════════════════════════════════════

def normalize_text(text: str) -> str:
    """Normalize Arabic text for consistency."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)  # Zero-width chars
    return text.strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def ingest_tables(pool, tables: list[dict], law_info: dict) -> int:
    """Store extracted tables in legal_tables + chunks."""
    ingested = 0
    law_name = law_info["law_name"]
    law_number = law_info.get("law_number", "")
    law_year = law_info.get("law_year", "")
    law_id = law_info.get("law_id", 0)
    now = datetime.utcnow()

    async with pool.acquire() as conn:
        for tbl in tables:
            full = tbl["full_text"]
            if len(full) < 20:
                continue

            chash = content_hash(full)

            # Check duplicate
            exists = await conn.fetchval(
                "SELECT id FROM legal_tables WHERE content_hash=$1", chash
            )
            if exists:
                log.info("[INGEST] skip duplicate hash=%s", chash)
                continue

            # Insert into legal_tables
            try:
                await conn.execute("""
                    INSERT INTO legal_tables
                    (parent_law_name, parent_law_number, parent_law_year, law_id,
                     source_type, table_number, raw_text, normalized_text,
                     content_hash, fetch_status, completeness_status, fetched_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'fetched',
                            CASE WHEN length($7) > 200 THEN 'complete' ELSE 'partial' END, $10)
                """,
                    law_name, law_number, law_year, law_id,
                    tbl["source_type"], tbl.get("table_number", ""),
                    full, normalize_text(full), chash, now
                )
                log.info("[INGEST] legal_tables: %s table=%s len=%d",
                         law_name[:40], tbl.get("table_number"), len(full))
            except Exception as e:
                log.warning("[INGEST] legal_tables error: %s", e)
                continue

            # Also insert as chunk for RAG retrieval
            try:
                # Generate embedding
                try:
                    async with httpx.AsyncClient(timeout=30) as emb_client:
                        emb_r = await emb_client.post(
                            "http://ollama:11434/api/embeddings",
                            json={"model": "nomic-embed-text", "prompt": normalize_text(full)[:2000]}
                        )
                        embedding = emb_r.json().get("embedding")
                except Exception:
                    embedding = None

                art_num = "جدول-%s" % tbl.get("table_number", "1")
                emb_str = "[" + ",".join(map(str, embedding)) + "]" if embedding else None

                await conn.execute("""
                    INSERT INTO chunks
                    (law_name, law_number, law_year, law_id, article_number,
                     content, source, source_type, is_active, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, 'almeezan', $7, true,
                            $8::vector)
                """,
                    law_name, law_number, law_year, law_id, art_num,
                    normalize_text(full)[:4000], tbl["source_type"],
                    emb_str
                )
                log.info("[INGEST] chunk: %s art=%s len=%d embedded=%s",
                         law_name[:30], art_num, len(full), embedding is not None)
                ingested += 1
            except Exception as e:
                log.warning("[INGEST] chunk error: %s", e)

            # Insert individual rows if available
            for row in tbl.get("rows", []):
                row_text = row.get("raw", "")
                if len(row_text) < 5:
                    continue
                rhash = content_hash(f"{chash}:{row['row_order']}")
                try:
                    await conn.execute("""
                        INSERT INTO legal_tables
                        (parent_law_name, parent_law_number, parent_law_year, law_id,
                         source_type, table_number, row_order, item_text,
                         raw_text, normalized_text, content_hash,
                         fetch_status, completeness_status, fetched_at)
                        VALUES ($1, $2, $3, $4, 'table_row', $5, $6, $7, $7, $8, $9,
                                'fetched', 'complete', $10)
                        ON CONFLICT (content_hash) DO NOTHING
                    """,
                        law_name, law_number, law_year, law_id,
                        tbl.get("table_number", ""), row["row_order"],
                        row_text, normalize_text(row_text), rhash, now
                    )
                except Exception:
                    pass

    return ingested


# ══════════════════════════════════════════════════════════════
# Phase 5: Main Pipeline
# ══════════════════════════════════════════════════════════════

async def run_pipeline(law_ids: list[int] = None, audit_only: bool = False):
    pool = await asyncpg.create_pool(DB_DSN)

    # Create schema
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    log.info("[AUDIT] Schema ready")

    # Phase 1: Audit
    audit_results = await audit_corpus(pool)
    missing = [r for r in audit_results if r["status"] == "MISSING"]

    if audit_only:
        print(json.dumps(audit_results, ensure_ascii=False, indent=2))
        await pool.close()
        return

    # Phase 2-4: Fetch and ingest
    if law_ids:
        targets = [r for r in audit_results if r.get("law_id") in law_ids]
        # Also add direct law_id targets
        for lid in law_ids:
            if not any(r.get("law_id") == lid for r in targets):
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT law_name, law_number, law_year FROM chunks "
                        "WHERE law_id=$1 AND is_active=true LIMIT 1", lid
                    )
                if row:
                    targets.append({
                        "law_name": row["law_name"], "law_number": row["law_number"],
                        "law_year": row["law_year"], "law_id": lid,
                        "status": "MISSING",
                    })
    else:
        # Process all missing + partial
        targets = [r for r in audit_results
                    if r["status"] in ("MISSING", "PRESENT_PARTIAL")]

    log.info("[PIPELINE] Processing %d laws", len(targets))
    total_ingested = 0
    fetch_results = []

    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        for i, law in enumerate(targets):
            lid = law.get("law_id")
            if not lid:
                fetch_results.append({"law": law["law_name"][:50], "status": "NO_ID"})
                continue

            log.info("[PIPELINE] [%d/%d] law_id=%d %s",
                     i + 1, len(targets), lid, law["law_name"][:50])

            # Fetch main page
            html = await fetch_law_page(client, lid)
            tables = []
            if html:
                tables = extract_tables_from_html(
                    html, law["law_name"], law.get("law_number", ""),
                    law.get("law_year", ""), lid
                )

            # Fetch attachments page
            att_html = await fetch_attachments_page(client, lid)
            if att_html:
                att_tables = extract_tables_from_html(
                    att_html, law["law_name"], law.get("law_number", ""),
                    law.get("law_year", ""), lid
                )
                tables.extend(att_tables)

            if tables:
                count = await ingest_tables(pool, tables, law)
                total_ingested += count
                fetch_results.append({
                    "law": law["law_name"][:50], "law_id": lid,
                    "tables_found": len(tables), "ingested": count,
                    "status": "INGESTED",
                })
            else:
                fetch_results.append({
                    "law": law["law_name"][:50], "law_id": lid,
                    "status": "NO_TABLES_FOUND",
                })

            # Rate limiting
            await asyncio.sleep(2)

    # Phase 5: Report
    log.info("[PIPELINE] Complete: %d tables ingested from %d laws", total_ingested, len(targets))

    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_laws_scanned": len(audit_results),
        "laws_with_table_refs": len(audit_results),
        "missing_before": len(missing),
        "laws_processed": len(targets),
        "total_tables_ingested": total_ingested,
        "fetch_results": fetch_results,
        "status_summary": {
            "INGESTED": sum(1 for r in fetch_results if r["status"] == "INGESTED"),
            "NO_TABLES_FOUND": sum(1 for r in fetch_results if r["status"] == "NO_TABLES_FOUND"),
            "NO_ID": sum(1 for r in fetch_results if r["status"] == "NO_ID"),
            "FETCH_FAILED": sum(1 for r in fetch_results if r["status"] == "FETCH_FAILED"),
        },
    }

    with open("/app/logs/table_ingestion_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info("[DIAG] Report saved to /app/logs/table_ingestion_report.json")

    # Print summary
    print("\n" + "=" * 60)
    print("TABLE INGESTION REPORT")
    print("=" * 60)
    for k, v in report["status_summary"].items():
        print("  %s: %d" % (k, v))
    print("  Total ingested: %d" % total_ingested)

    await pool.close()


if __name__ == "__main__":
    audit_only = "--audit-only" in sys.argv
    law_ids = None

    for arg in sys.argv:
        if arg.startswith("--law-ids="):
            law_ids = [int(x) for x in arg.split("=")[1].split(",")]

    asyncio.run(run_pipeline(law_ids=law_ids, audit_only=audit_only))
