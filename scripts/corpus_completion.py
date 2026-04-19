#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Corpus Completion Pipeline — Full End-to-End
=============================================
Phase 1: Audit entire corpus for missing tables/schedules/appendices
Phase 2: Ensure DB schema ready
Phase 3: Fetch missing content from Al Meezan (HTML + PDF)
Phase 4: Parse tables/schedules from fetched content
Phase 5: Ingest into legal_tables + chunks with proper source_type
Phase 6: Generate diagnostic report

Usage:
  python3 scripts/corpus_completion.py                   # Full run
  python3 scripts/corpus_completion.py --audit-only      # Audit only
  python3 scripts/corpus_completion.py --top=20           # Process top 20 missing
  python3 scripts/corpus_completion.py --ids=3989,7102    # Specific Al Meezan IDs
"""
import asyncio, asyncpg, hashlib, json, logging, re, sys, time, io
from datetime import datetime
from typing import Optional
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("corpus")

DB_DSN = "postgresql://raguser:RAGsecret2024!@db:5432/ragdb"
BASE = "https://www.almeezan.qa"
TIMEOUT = 45
RATE_DELAY = 1.5  # seconds between requests

# ══════════════════════════════════════════════════════════════
# Phase 2: Schema
# ══════════════════════════════════════════════════════════════

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_lt_hash ON legal_tables(content_hash);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='chunks' AND column_name='source_type') THEN
        ALTER TABLE chunks ADD COLUMN source_type TEXT DEFAULT 'statute_text';
    END IF;
END $$;
"""

# ══════════════════════════════════════════════════════════════
# Phase 1: Audit
# ══════════════════════════════════════════════════════════════

TABLE_PATTERNS = [
    r"الجدول\s*(?:رقم)?\s*\(?\s*\d+",
    r"جدول\s+(?:الدرجات|الرواتب|المخدرات|المواد|الوظائف)",
    r"الملحق\s*(?:رقم)?\s*\(?\s*\d+",
    r"المرفق\s+بهذا\s+القانون",
    r"الجدول\s+المرفق",
    r"الجداول\s+الملحقة",
    r"وفقاً?\s+للجدول",
    r"جدول\s+الدرجات\s+والرواتب",
    r"سلم\s+الرواتب",
    r"البند\s*(?:رقم)?\s*\(",
    r"قائمة\s+المواد",
]


async def audit_corpus(pool) -> list[dict]:
    log.info("[AUDIT] Scanning entire corpus...")
    async with pool.acquire() as conn:
        laws = await conn.fetch("""
            SELECT DISTINCT law_name, law_number, law_year,
                   MIN(law_id) as law_id, COUNT(*) as chunks
            FROM chunks WHERE is_active=true
            AND law_name NOT ILIKE '%%أحكام محكمة التمييز%%'
            GROUP BY law_name, law_number, law_year
        """)

    results = []
    for law in laws:
        lname = law["law_name"] or ""
        async with pool.acquire() as conn:
            chunks = await conn.fetch(
                "SELECT content, article_number, source_type FROM chunks "
                "WHERE is_active=true AND law_name=$1 AND law_number=$2",
                lname, law["law_number"])

        all_text = " ".join(c["content"] for c in chunks)
        refs = sum(1 for p in TABLE_PATTERNS if re.search(p, all_text))
        if refs == 0:
            continue

        has_attachment = any(str(c["article_number"] or "").startswith("مرفق") for c in chunks)
        has_statute_table = any(c.get("source_type") == "statute_table" for c in chunks)
        has_table_content = any(
            len(re.findall(r"\d+[\s\-\.]+[^\d\n]{5,}", c["content"])) >= 3 for c in chunks)

        if has_statute_table:
            status = "PRESENT_COMPLETE"
        elif has_attachment and has_table_content:
            status = "PRESENT_COMPLETE"
        elif has_attachment or has_table_content:
            status = "PRESENT_PARTIAL"
        else:
            status = "MISSING"

        results.append({
            "law_name": lname, "law_number": law["law_number"],
            "law_year": law["law_year"], "law_id": law["law_id"],
            "chunks": law["chunks"], "refs": refs, "status": status,
        })

    missing = sum(1 for r in results if r["status"] == "MISSING")
    partial = sum(1 for r in results if r["status"] == "PRESENT_PARTIAL")
    complete = sum(1 for r in results if "COMPLETE" in r["status"])
    log.info("[AUDIT] %d laws with table refs: %d complete, %d partial, %d missing",
             len(results), complete, partial, missing)
    return results


# ══════════════════════════════════════════════════════════════
# Phase 3: Al Meezan Fetcher
# ══════════════════════════════════════════════════════════════

async def find_almeezan_id(law_name: str, law_number: str, law_year: str,
                            all_laws: list[dict]) -> Optional[str]:
    """Find Al Meezan ID from local index."""
    lname_lower = (law_name or "").lower()[:40]
    for entry in all_laws:
        ename = (entry.get("name") or "").lower()
        enum = entry.get("number", "")
        eyear = entry.get("year", "")
        if law_number and enum == law_number and eyear == law_year:
            return entry["id"]
        if lname_lower and lname_lower[:25] in ename:
            return entry["id"]
    return None


async def fetch_attachment_links(client: httpx.AsyncClient, almeezan_id: str) -> list[dict]:
    """Fetch attachment/schedule/table links from Al Meezan."""
    from bs4 import BeautifulSoup
    links = []
    try:
        url = f"{BASE}/LawOtherAttachments.aspx?id={almeezan_id}&language=ar"
        r = await client.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return links
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)[:100]
            if "Clarif" in href and any(
                kw in text for kw in ["جدول", "ملحق", "مرفق", "درجات", "رواتب", "قائمة", "نسخة"]):
                cid_match = re.search(r"id=(\d+)", href)
                if cid_match:
                    links.append({
                        "clarif_id": int(cid_match.group(1)),
                        "title": text,
                        "url": f"{BASE}/{href}" if not href.startswith("http") else href,
                    })
        log.info("[ALMEEZAN_FETCH] id=%s found %d attachment links", almeezan_id, len(links))
    except Exception as e:
        log.warning("[ALMEEZAN_FETCH] id=%s error: %s", almeezan_id, e)
    return links


async def fetch_clarif_content(client: httpx.AsyncClient, clarif_id: int) -> tuple[Optional[bytes], str]:
    """Fetch a clarification/attachment page. Returns (content_bytes, content_type)."""
    try:
        url = f"{BASE}/ClarificationsNoteDetails.aspx?id={clarif_id}&language=ar"
        r = await client.get(url, timeout=60)
        if r.status_code != 200:
            return None, "error"
        content = r.content
        if content[:4] == b"%PDF":
            return content, "pdf"
        return content, "html"
    except Exception as e:
        log.warning("[ALMEEZAN_FETCH] clarif=%d error: %s", clarif_id, e)
        return None, "error"


# ══════════════════════════════════════════════════════════════
# Phase 4: Parsing
# ══════════════════════════════════════════════════════════════

def parse_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """Extract text from PDF. Falls back to OCR for scanned pages.
    Returns (text, method) where method is 'pdf_text' or 'ocr'."""
    from ocr_extractor import extract_pdf_with_ocr_fallback
    return extract_pdf_with_ocr_fallback(pdf_bytes)


def parse_html_tables(html_bytes: bytes) -> str:
    """Extract table/schedule content from HTML. Handles large/corrupt pages."""
    from bs4 import BeautifulSoup
    # Limit size to prevent memory issues
    html_str = html_bytes[:500_000].decode("utf-8", errors="replace")
    # Remove null bytes
    html_str = html_str.replace("\x00", "")

    soup = BeautifulSoup(html_str, "html.parser")
    parts = []

    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if len(rows) >= 2:
            for tr in rows:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells and any(len(c) > 2 for c in cells):
                    parts.append(" | ".join(cells))

    if not parts:
        text = soup.get_text(separator="\n", strip=True)
        if 100 < len(text) < 50_000:
            parts.append(text[:30_000])

    result = "\n".join(parts)[:30_000]
    log.info("[TABLE_PARSE] HTML extracted %d chars", len(result))
    return result


def normalize(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:30_000]


def chash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════
# Phase 5+6: Ingest
# ══════════════════════════════════════════════════════════════

async def ingest_table_text(pool, text: str, law_info: dict, title: str,
                             source_type: str = "statute_table") -> int:
    """Store table text in legal_tables + create chunks for retrieval."""
    text = text.replace("\x00", "")[:30_000]  # Safety: strip nulls, cap size
    if len(text.strip()) < 50:
        return 0

    h = chash(text)
    now = datetime.utcnow()
    ingested = 0

    async with pool.acquire() as conn:
        # Check duplicate
        exists = await conn.fetchval("SELECT id FROM legal_tables WHERE content_hash=$1", h)
        if exists:
            log.info("[INGEST] skip duplicate hash=%s", h)
            return 0

        # Insert into legal_tables
        await conn.execute("""
            INSERT INTO legal_tables
            (parent_law_name, parent_law_number, parent_law_year, law_id,
             source_type, item_title, raw_text, normalized_text, content_hash,
             fetch_status, completeness_status, fetched_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'fetched',
                    CASE WHEN length($7)>500 THEN 'complete' ELSE 'partial' END, $10)
        """,
            law_info.get("law_name",""), law_info.get("law_number",""),
            law_info.get("law_year",""), law_info.get("law_id",0),
            source_type, title, text, normalize(text), h, now)

        # Create chunks for RAG retrieval
        normalized = normalize(text)
        chunk_size = 1800
        for ci in range(0, len(normalized), chunk_size):
            chunk_text = normalized[ci:ci+chunk_size]
            if len(chunk_text) < 50:
                continue

            # Generate embedding
            emb_str = None
            try:
                async with httpx.AsyncClient(timeout=30) as ec:
                    er = await ec.post("http://ollama:11434/api/embeddings",
                                       json={"model":"nomic-embed-text","prompt":chunk_text[:2000]})
                    emb = er.json().get("embedding")
                    if emb:
                        emb_str = "[" + ",".join(map(str, emb)) + "]"
            except Exception:
                pass

            art_num = "جدول-ملحق-%d" % (ci // chunk_size + 1)
            try:
                await conn.execute("""
                    INSERT INTO chunks
                    (law_name, law_number, law_year, law_id, article_number,
                     content, source, source_type, is_active, embedding)
                    VALUES ($1,$2,$3,$4,$5,$6,'almeezan',$7,true,$8::vector)
                """,
                    law_info.get("law_name",""), law_info.get("law_number",""),
                    law_info.get("law_year",""), law_info.get("law_id",0),
                    art_num, chunk_text, source_type, emb_str)
                ingested += 1
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    log.warning("[INGEST] chunk error: %s", str(e)[:80])

    log.info("[INGEST] %s: %d chunks stored", title[:40], ingested)
    return ingested


# ══════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════

async def run(audit_only=False, top_n=None, target_ids=None):
    pool = await asyncpg.create_pool(DB_DSN)

    # Schema
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    log.info("[AUDIT] Schema ready")

    # Load Al Meezan index
    with open("/app/full_reindex_progress.json") as f:
        all_laws = json.load(f).get("all_laws", [])
    log.info("[AUDIT] Al Meezan index: %d laws", len(all_laws))

    # Phase 1: Audit
    audit = await audit_corpus(pool)
    missing = [r for r in audit if r["status"] == "MISSING"]
    partial = [r for r in audit if r["status"] == "PRESENT_PARTIAL"]

    if audit_only:
        with open("/app/logs/corpus_audit.json", "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)
        log.info("[AUDIT] Saved to /app/logs/corpus_audit.json")
        await pool.close()
        return

    # Determine targets
    if target_ids:
        # Find laws by Al Meezan ID
        targets = []
        for tid in target_ids:
            for law in all_laws:
                if law["id"] == str(tid):
                    targets.append({
                        "law_name": law["name"], "law_number": law.get("number",""),
                        "law_year": law.get("year",""), "almeezan_id": law["id"],
                        "law_id": int(law["id"]),
                    })
                    break
    else:
        # Process missing + partial, sorted by chunk count (most important first)
        candidates = missing + partial
        candidates.sort(key=lambda x: x["chunks"], reverse=True)
        if top_n:
            candidates = candidates[:top_n]

        targets = []
        for c in candidates:
            amid = await find_almeezan_id(c["law_name"], c["law_number"] or "",
                                           c["law_year"] or "", all_laws)
            if amid:
                targets.append({**c, "almeezan_id": amid})

    log.info("[PIPELINE] Processing %d laws", len(targets))

    total_ingested = 0
    results = []

    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        for i, law in enumerate(targets):
            amid = law.get("almeezan_id", "")
            lname = law.get("law_name", "")[:60]
            log.info("[PIPELINE] [%d/%d] id=%s %s", i+1, len(targets), amid, lname)

            # Fetch attachment links
            links = await fetch_attachment_links(client, amid)
            await asyncio.sleep(RATE_DELAY)

            if not links:
                results.append({"law": lname, "id": amid, "status": "NO_ATTACHMENTS"})
                continue

            law_ingested = 0
            for link in links:
                cid = link["clarif_id"]
                title = link["title"]

                content, ctype = await fetch_clarif_content(client, cid)
                await asyncio.sleep(RATE_DELAY)

                if content is None:
                    log.warning("[ALMEEZAN_FETCH] clarif=%d failed", cid)
                    continue

                # Parse
                extraction_method = "unknown"
                if ctype == "pdf":
                    try:
                        text, extraction_method = parse_pdf(content)
                    except Exception as e:
                        log.error("[PDF_PARSE] clarif=%d error: %s", cid, e)
                        continue
                elif ctype == "html":
                    text = parse_html_tables(content)
                    extraction_method = "html"
                else:
                    continue

                if len(text.strip()) < 50:
                    log.info("[TABLE_PARSE] clarif=%d: too short (%d chars, method=%s)", cid, len(text), extraction_method)
                    continue
                log.info("[TABLE_PARSE] clarif=%d: %d chars via %s", cid, len(text), extraction_method)

                # Determine source_type from title
                st = "statute_table"
                t_lower = title.lower()
                if "رواتب" in t_lower or "درجات" in t_lower or "مربوط" in t_lower:
                    st = "salary_table"
                elif "ملحق" in t_lower:
                    st = "appendix"

                # Ingest
                law_info = {
                    "law_name": law.get("law_name", ""),
                    "law_number": law.get("law_number", ""),
                    "law_year": law.get("law_year", ""),
                    "law_id": int(amid) if amid.isdigit() else 0,
                }
                count = await ingest_table_text(pool, text, law_info, title, st)
                law_ingested += count
                total_ingested += count

            status = "INGESTED" if law_ingested > 0 else "NO_TABLE_CONTENT"
            results.append({"law": lname, "id": amid, "status": status,
                            "attachments": len(links), "ingested": law_ingested})

    # Phase 10: Report
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_laws_scanned": len(audit),
        "with_table_refs": len(audit),
        "complete_before": sum(1 for r in audit if "COMPLETE" in r["status"]),
        "partial_before": sum(1 for r in audit if r["status"] == "PRESENT_PARTIAL"),
        "missing_before": len(missing),
        "laws_processed": len(targets),
        "total_chunks_ingested": total_ingested,
        "results": results,
        "summary": {
            "INGESTED": sum(1 for r in results if r.get("status") == "INGESTED"),
            "NO_TABLE_CONTENT": sum(1 for r in results if r.get("status") == "NO_TABLE_CONTENT"),
            "NO_ATTACHMENTS": sum(1 for r in results if r.get("status") == "NO_ATTACHMENTS"),
        },
    }

    with open("/app/logs/corpus_completion_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("CORPUS COMPLETION REPORT")
    print("=" * 60)
    print("  Laws scanned: %d" % report["total_laws_scanned"])
    print("  With table refs: %d" % report["with_table_refs"])
    print("  Complete before: %d" % report["complete_before"])
    print("  Missing before: %d" % report["missing_before"])
    print("  Laws processed: %d" % report["laws_processed"])
    print("  Chunks ingested: %d" % report["total_chunks_ingested"])
    for k, v in report["summary"].items():
        print("    %s: %d" % (k, v))

    # Show key results
    print("\n  Key results:")
    for r in results:
        if r.get("ingested", 0) > 0:
            print("    ✅ %s (id=%s): %d chunks" % (r["law"], r["id"], r["ingested"]))
    for r in results:
        if r.get("status") == "NO_ATTACHMENTS":
            print("    ❌ %s (id=%s): no attachments found" % (r["law"], r["id"]))

    await pool.close()


if __name__ == "__main__":
    audit_only = "--audit-only" in sys.argv
    top_n = None
    target_ids = None

    for arg in sys.argv:
        if arg.startswith("--top="):
            top_n = int(arg.split("=")[1])
        elif arg.startswith("--ids="):
            target_ids = [int(x) for x in arg.split("=")[1].split(",")]

    asyncio.run(run(audit_only=audit_only, top_n=top_n, target_ids=target_ids))
