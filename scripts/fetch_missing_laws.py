# -*- coding: utf-8 -*-
"""
fetch_missing_laws.py — سحب القوانين المفقودة والضعيفة من الميزان
"""
import asyncio
import json
import re
import ssl
import time
import html as html_mod
import urllib.request

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

# SSL context for almeezan (self-signed cert)
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# Target laws to fetch
TARGET_LAWS = [
    # Missing completely
    {"id": "307",  "name": "قانون رقم (40) لسنة 2004 بشأن الولاية على أموال القاصرين", "number": "40", "year": "2004", "domain": "أسري"},
    # Weak coverage - قانون التجارة (only 6 chunks)
    {"id": "2572", "name": "قانون رقم (27) لسنة 2006 بإصدار قانون التجارة", "number": "27", "year": "2006", "domain": "تجاري"},
    # Weak - العمالة المنزلية (1 chunk)
    {"id": "7312", "name": "قانون رقم (15) لسنة 2017 بشأن المستخدمين في المنازل", "number": "15", "year": "2017", "domain": "عمالي"},
    # Medical profession
    {"id": "137",  "name": "قانون رقم (19) لسنة 2005 بتنظيم مزاولة المهن الصحية", "number": "19", "year": "2005", "domain": "عام"},
    # Healthcare regulation update
    {"id": "7250", "name": "قانون رقم (8) لسنة 2017 بإصدار نظام الرعاية الصحية", "number": "8", "year": "2017", "domain": "عام"},
]


def fetch_url(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp = urllib.request.urlopen(req, context=CTX, timeout=30)
    return resp.read()


def download_law_word(law_id):
    """Download law as Word (HTML) document from almeezan."""
    url = f"https://www.almeezan.qa/LawViewWord.aspx?LawID={law_id}&mode=DOC&language=ar"
    return fetch_url(url)


def extract_articles(data):
    """Parse HTML Word doc into individual articles."""
    try:
        text = data.decode("utf-8")
    except:
        text = data.decode("utf-8", errors="replace")

    # Clean HTML
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<td[^>]*>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"<tr[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +", " ", text)

    # Split by article markers
    parts = re.split(r"(?=(?:مادة|المادة)\s*\(?\s*\d+\s*\)?)", text)

    articles = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(?:مادة|المادة)\s*\(?\s*(\d+)\s*\)?", part)
        if m:
            art_num = m.group(1)
            content = part.strip()
            if len(content) > 30:
                # Enforce max chunk size
                if len(content) > 2000:
                    # Split long articles
                    chunks = []
                    while len(content) > 2000:
                        split_point = content.rfind("\n", 0, 2000)
                        if split_point < 500:
                            split_point = 2000
                        chunks.append(content[:split_point])
                        content = content[split_point:].strip()
                    if content:
                        chunks.append(content)
                    for i, chunk in enumerate(chunks):
                        suffix = f"-{i+1}" if len(chunks) > 1 else ""
                        articles.append({"number": f"{art_num}{suffix}", "content": chunk})
                else:
                    articles.append({"number": art_num, "content": content})

    return articles


def get_embedding(text):
    data = json.dumps({"model": EMBED_MODEL, "prompt": text[:2000]}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data,
                                headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        emb = json.loads(resp.read()).get("embedding", [])
        return emb if len(emb) > 0 else None
    except Exception as e:
        print(f"  [WARN] embedding error: {e}")
        return None


def emb_to_pg(emb):
    return "[" + ",".join(f"{x:.8f}" for x in emb) + "]"


async def process_law(conn, law):
    """Download, parse, embed, and insert a single law."""
    lid = law["id"]
    name = law["name"]
    number = law["number"]
    year = law["year"]
    domain = law["domain"]

    print(f"\n  Downloading law ID={lid}: {name[:60]}...")

    try:
        data = download_law_word(lid)
    except Exception as e:
        print(f"  ERROR downloading: {e}")
        return {"law": name, "status": "download_failed", "error": str(e)}

    articles = extract_articles(data)
    print(f"  Extracted {len(articles)} articles")

    if not articles:
        return {"law": name, "status": "no_articles", "articles": 0}

    inserted = 0
    skipped = 0
    errors = 0

    for art in articles:
        art_num = art["number"]
        content = art["content"]

        # Check if already exists
        existing = await conn.fetchval("""
            SELECT count(*) FROM chunks
            WHERE law_name = $1 AND law_number = $2 AND law_year = $3
              AND article_number = $4 AND is_active = true
        """, name, number, year, art_num)

        if existing > 0:
            skipped += 1
            continue

        # Generate embedding
        emb = get_embedding(content)
        emb_str = emb_to_pg(emb) if emb else None

        try:
            if emb_str:
                await conn.execute("""
                    INSERT INTO chunks
                        (law_name, law_number, law_year, article_number,
                         content, embedding, domain, source, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6::vector, $7, 'almeezan', true)
                """, name, number, year, art_num, content, emb_str, domain)
            else:
                await conn.execute("""
                    INSERT INTO chunks
                        (law_name, law_number, law_year, article_number,
                         content, domain, source, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, 'almeezan', true)
                """, name, number, year, art_num, content, domain)
            inserted += 1
        except Exception as e:
            errors += 1
            if "unique" not in str(e).lower():
                print(f"  ERROR inserting art {art_num}: {e}")

    result = {
        "law": name[:60],
        "law_id": lid,
        "articles_found": len(articles),
        "inserted": inserted,
        "skipped_existing": skipped,
        "errors": errors,
    }
    print(f"  Result: {inserted} inserted, {skipped} skipped, {errors} errors")
    return result


async def main():
    import asyncpg
    conn = await asyncpg.connect(DB_DSN)
    print("Connected to database.\n")

    # Pre-stats
    pre_total = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    print(f"BEFORE: {pre_total:,} active chunks\n")

    results = []
    for law in TARGET_LAWS:
        r = await process_law(conn, law)
        results.append(r)
        time.sleep(1)  # Rate limit

    # Post-stats
    post_total = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    post_null = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE is_active=true AND embedding IS NULL"
    )

    print("\n" + "=" * 60)
    print("  FETCH RESULTS")
    print("=" * 60)
    total_inserted = sum(r.get("inserted", 0) for r in results)
    print(f"\n  Laws processed: {len(results)}")
    print(f"  Total articles inserted: {total_inserted}")
    print(f"  BEFORE: {pre_total:,} | AFTER: {post_total:,}")
    print(f"  Without embedding: {post_null}")

    for r in results:
        status = "OK" if r.get("inserted", 0) > 0 else "SKIP" if r.get("skipped_existing", 0) > 0 else "FAIL"
        print(f"  [{status}] {r.get('law', '?')[:50]} -> +{r.get('inserted', 0)} arts")

    # Save report
    report = {
        "pre_total": pre_total,
        "post_total": post_total,
        "post_null_emb": post_null,
        "total_inserted": total_inserted,
        "laws": results,
    }
    with open("scripts/fetch_missing_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  Report saved: scripts/fetch_missing_report.json")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
