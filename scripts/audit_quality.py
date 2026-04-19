# -*- coding: utf-8 -*-
"""
سكريبت فحص جودة البيانات القانونية
يتصل بقاعدة البيانات ويفحص كل chunk ويصنّفه
"""
import asyncio
import re
import sys
import json
from collections import defaultdict

# --- DB connection (same as app) ---
DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"

# --- Quality patterns ---
# OCR gibberish: sequences of random Arabic/Latin mixed with numbers and symbols
RE_OCR_GARBAGE = re.compile(
    r"([a-zA-Z]{5,})"           # 5+ consecutive Latin letters
    r"|[\x00-\x08\x0B\x0C\x0E-\x1F]"  # control characters
    r"|[#@$%^&*=]{2,}"          # multiple special chars
    r"|([\u0660-\u0669\d]{10,})" # 10+ consecutive digits (Arabic or Latin)
    r"|(ع[\d@\-]+)"             # Arabic letter + garbage
    r"|(سس\s*=)"                # known OCR pattern
    r"|(للظب[ةا])"              # known OCR corruption
)
RE_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
RE_ARTICLE_NUM = re.compile(r"(الماد[ةه]\s*\(?(\d+)\)?|ماد[ةه]\s*\(?(\d+)\)?)")
RE_LAW_REF = re.compile(r"(قانون|مرسوم|قرار|أمر أميري).*?(رقم|لسنة|\d{4})")


def classify_chunk(content: str, article_number: str | None) -> dict:
    """Classify a chunk's quality."""
    result = {
        "length": len(content),
        "arabic_ratio": 0.0,
        "has_article_num": False,
        "has_law_ref": False,
        "ocr_issues": [],
        "classification": "unknown",  # clean / review / corrupt
    }

    if not content or not content.strip():
        result["classification"] = "corrupt"
        result["ocr_issues"].append("empty_content")
        return result

    # Arabic ratio
    arabic_chars = len(RE_ARABIC.findall(content))
    total_chars = len(content.strip())
    result["arabic_ratio"] = arabic_chars / total_chars if total_chars > 0 else 0

    # Article number
    result["has_article_num"] = bool(article_number and article_number.strip()) or bool(RE_ARTICLE_NUM.search(content))

    # Law reference
    result["has_law_ref"] = bool(RE_LAW_REF.search(content))

    # OCR issues
    for m in RE_OCR_GARBAGE.finditer(content):
        result["ocr_issues"].append(m.group()[:50])

    # Low Arabic ratio
    if result["arabic_ratio"] < 0.2:
        result["ocr_issues"].append(f"low_arabic_ratio={result['arabic_ratio']:.2f}")

    # Classification
    if len(result["ocr_issues"]) >= 3 or result["arabic_ratio"] < 0.15:
        result["classification"] = "corrupt"
    elif len(result["ocr_issues"]) >= 1 or result["length"] < 60 or result["length"] > 5000:
        result["classification"] = "review"
    else:
        result["classification"] = "clean"

    return result


async def main():
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Run: pip install asyncpg")
        sys.exit(1)

    conn = await asyncpg.connect(DB_DSN)
    print("Connected to database.")

    # Fetch all active chunks
    rows = await conn.fetch("""
        SELECT id, law_name, law_number, law_year, article_number,
               content, domain, source, embedding IS NOT NULL as has_embedding
        FROM chunks
        WHERE is_active = true
        ORDER BY id
    """)
    print(f"Fetched {len(rows)} active chunks.\n")

    stats = {
        "total": len(rows),
        "clean": 0, "review": 0, "corrupt": 0,
        "no_embedding": 0,
        "by_domain": defaultdict(int),
        "by_source": defaultdict(int),
        "by_classification_domain": defaultdict(lambda: defaultdict(int)),
        "corrupt_examples": [],
        "review_examples": [],
        "size_distribution": defaultdict(int),
        "laws_coverage": defaultdict(lambda: {"chunks": 0, "clean": 0, "corrupt": 0, "review": 0}),
    }

    for row in rows:
        content = row["content"] or ""
        article = row["article_number"]
        q = classify_chunk(content, article)

        stats[q["classification"]] += 1
        stats["by_domain"][row["domain"] or "unknown"] += 1
        stats["by_source"][row["source"] or "unknown"] += 1
        stats["by_classification_domain"][(row["domain"] or "unknown")][q["classification"]] += 1

        if not row["has_embedding"]:
            stats["no_embedding"] += 1

        # Size distribution
        L = q["length"]
        if L < 50:
            stats["size_distribution"]["tiny (<50)"] += 1
        elif L < 200:
            stats["size_distribution"]["small (50-200)"] += 1
        elif L < 500:
            stats["size_distribution"]["medium (200-500)"] += 1
        elif L < 1000:
            stats["size_distribution"]["good (500-1000)"] += 1
        elif L < 2000:
            stats["size_distribution"]["large (1000-2000)"] += 1
        else:
            stats["size_distribution"]["huge (2000+)"] += 1

        # Law coverage
        law_key = f"{row['law_name'] or 'unknown'} ({row['law_number'] or '?'}/{row['law_year'] or '?'})"
        stats["laws_coverage"][law_key]["chunks"] += 1
        stats["laws_coverage"][law_key][q["classification"]] += 1

        # Examples
        if q["classification"] == "corrupt" and len(stats["corrupt_examples"]) < 20:
            stats["corrupt_examples"].append({
                "id": row["id"],
                "law": row["law_name"],
                "article": article,
                "issues": q["ocr_issues"],
                "sample": content[:150],
            })
        elif q["classification"] == "review" and len(stats["review_examples"]) < 20:
            stats["review_examples"].append({
                "id": row["id"],
                "law": row["law_name"],
                "article": article,
                "issues": q["ocr_issues"],
                "sample": content[:150],
                "length": q["length"],
            })

    await conn.close()

    # --- Print Report ---
    print("=" * 70)
    print("  QUALITY AUDIT REPORT")
    print("=" * 70)

    total = stats["total"]
    print(f"\nTotal active chunks: {total:,}")
    print(f"  Clean:   {stats['clean']:>6,}  ({100*stats['clean']/total:.1f}%)")
    print(f"  Review:  {stats['review']:>6,}  ({100*stats['review']/total:.1f}%)")
    print(f"  Corrupt: {stats['corrupt']:>6,}  ({100*stats['corrupt']/total:.1f}%)")
    print(f"  No embedding: {stats['no_embedding']:>6,}  ({100*stats['no_embedding']/total:.1f}%)")

    print("\n--- Size Distribution ---")
    for k in ["tiny (<50)", "small (50-200)", "medium (200-500)",
              "good (500-1000)", "large (1000-2000)", "huge (2000+)"]:
        c = stats["size_distribution"].get(k, 0)
        print(f"  {k:>20s}: {c:>6,}  ({100*c/total:.1f}%)")

    print("\n--- By Domain ---")
    for d, c in sorted(stats["by_domain"].items(), key=lambda x: -x[1]):
        corr = stats["by_classification_domain"][d].get("corrupt", 0)
        print(f"  {d:>15s}: {c:>5,} chunks  ({corr} corrupt)")

    print("\n--- By Source ---")
    for s, c in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
        print(f"  {s:>15s}: {c:>6,}")

    # Save JSON report (do this BEFORE printing examples that may fail on Windows encoding)
    out_path = "scripts/audit_quality_results.json"
    # Convert defaultdicts for JSON
    json_stats = {
        "total": stats["total"],
        "clean": stats["clean"],
        "review": stats["review"],
        "corrupt": stats["corrupt"],
        "no_embedding": stats["no_embedding"],
        "clean_pct": round(100 * stats["clean"] / total, 1),
        "corrupt_pct": round(100 * stats["corrupt"] / total, 1),
        "size_distribution": dict(stats["size_distribution"]),
        "by_domain": dict(stats["by_domain"]),
        "by_source": dict(stats["by_source"]),
        "corrupt_examples": stats["corrupt_examples"][:20],
        "review_examples": stats["review_examples"][:20],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(json_stats, f, ensure_ascii=False, indent=2)
    print(f"\nJSON report saved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
