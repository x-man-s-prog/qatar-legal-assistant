# -*- coding: utf-8 -*-
"""Step 3 only: merge short preamble chunks (re-run after fix)"""
import asyncio
import json
import re
import urllib.request
from collections import defaultdict

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"
OLLAMA_URL = "http://localhost:11434/api/embeddings"

RE_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")


def get_embedding(text):
    data = json.dumps({"model": "nomic-embed-text", "prompt": text[:2000]}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        emb = json.loads(resp.read()).get("embedding", [])
        return emb if len(emb) > 0 else None
    except:
        return None


def emb_to_pg(emb):
    return "[" + ",".join(f"{x:.8f}" for x in emb) + "]"


async def main():
    import asyncpg
    conn = await asyncpg.connect(DB_DSN)

    preamble_rows = await conn.fetch("""
        SELECT id, law_name, law_number, law_year, article_number,
               content, domain, source
        FROM chunks
        WHERE is_active = true
          AND length(content) < 200
          AND content ~ '(الوزراء|مشروع المرسوم|اقتراح وزير|مجلس الشورى|مشروع القانون|وعلى مشروع|أخذ رأي|نزع الملكية.*المواد|بشأن قرارات)'
        ORDER BY law_name, law_number, law_year, id
    """)
    print(f"Found {len(preamble_rows)} short preamble chunks")

    law_groups = defaultdict(list)
    for row in preamble_rows:
        key = (row["law_name"], row["law_number"], row["law_year"])
        law_groups[key].append(row)

    deactivated_ids = []
    inserted = 0

    for law_key, chunks in law_groups.items():
        if len(chunks) < 2:
            continue

        merged_content = "\n---\n".join(c["content"] for c in chunks)
        if len(merged_content) > 2000:
            merged_content = merged_content[:2000]

        first = chunks[0]
        art_num = f"مقدمة-مدمج-{inserted+1}"

        emb = get_embedding(merged_content)
        emb_str = emb_to_pg(emb) if emb else None

        try:
            if emb_str:
                await conn.execute("""
                    INSERT INTO chunks
                        (law_name, law_number, law_year, article_number,
                         content, embedding, domain, source, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8, true)
                """, first["law_name"], first["law_number"], first["law_year"],
                    art_num, merged_content, emb_str,
                    first["domain"], first["source"])
            else:
                await conn.execute("""
                    INSERT INTO chunks
                        (law_name, law_number, law_year, article_number,
                         content, domain, source, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, true)
                """, first["law_name"], first["law_number"], first["law_year"],
                    art_num, merged_content,
                    first["domain"], first["source"])
            inserted += 1
            for c in chunks:
                deactivated_ids.append(c["id"])
        except Exception as e:
            print(f"  Skip {law_key}: {e}")

    # Deactivate old preambles
    if deactivated_ids:
        for i in range(0, len(deactivated_ids), 1000):
            batch = deactivated_ids[i:i+1000]
            await conn.execute(
                "UPDATE chunks SET is_active = false WHERE id = ANY($1::int[])", batch
            )

    # Stats
    post_total = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    post_null = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true AND embedding IS NULL")

    print(f"\nMerged {len(deactivated_ids)} preambles -> {inserted} new chunks")
    print(f"Final: {post_total:,} active | {post_null} no-embedding")

    # Size distribution
    rows = await conn.fetch("""
        SELECT CASE
            WHEN length(content) < 200 THEN 'small'
            WHEN length(content) < 500 THEN 'medium'
            WHEN length(content) < 1000 THEN 'good'
            ELSE 'large+'
        END as sz, count(*) FROM chunks WHERE is_active=true GROUP BY 1
    """)
    for r in rows:
        pct = 100 * r["count"] / post_total
        print(f"  {r['sz']:>8s}: {r['count']:>6,} ({pct:.1f}%)")

    # Save report
    report = {
        "preambles_deactivated": len(deactivated_ids),
        "new_merged": inserted,
        "post_total": post_total,
        "post_null_emb": post_null,
        "coverage_pct": round(100 * (post_total - post_null) / post_total, 1) if post_total else 0
    }
    with open("scripts/db_fix_layer1_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved: scripts/db_fix_layer1_report.json")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
