# -*- coding: utf-8 -*-
"""
build_article_ruling_index.py — بناء فهرس الربط بين المواد القانونية وأحكام التمييز
يمر على كل أحكام التمييز ويستخرج المواد المذكورة فيها
"""
import asyncio, json, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"

# أنماط استخراج المواد القانونية
PATTERNS = [
    # المادة (رقم) من قانون X
    re.compile(r'(?:الماد[ةه]|المواد)\s*\(?\s*(\d+)\s*\)?\s*(?:من\s+)?(?:قانون|القانون)\s+(\S+(?:\s+\S+)?)', re.UNICODE),
    # المادة (رقم) من القانون رقم X لسنة Y
    re.compile(r'(?:الماد[ةه])\s*\(?\s*(\d+)\s*\)?\s*من\s+القانون\s+رقم\s*\(?\s*(\d+)\s*\)?\s*لسنة\s*(\d{4})', re.UNICODE),
    # المادة رقم + عقوبات/عمل/مدني
    re.compile(r'(?:الماد[ةه])\s*\(?\s*(\d+)\s*\)?\s*(عقوبات|عمل|مدني|أسرة|تجارة|إجراءات|مرافعات|إيجار|شركات|مرور|جرائم)', re.UNICODE),
    # م. رقم
    re.compile(r'م\.\s*(\d+)\s+(عقوبات|عمل|مدني|أسرة|تجارة|إجراءات)', re.UNICODE),
    # المواد (X-Y) من قانون
    re.compile(r'المواد\s*\(?\s*(\d+)\s*[-–]\s*(\d+)\s*\)?\s*(?:من\s+)?(?:قانون\s+)?(\S+)', re.UNICODE),
]

# خريطة أسماء القوانين المختصرة
LAW_NAME_MAP = {
    'العقوبات': ('قانون العقوبات', '11', '2004'),
    'عقوبات': ('قانون العقوبات', '11', '2004'),
    'العمل': ('قانون العمل', '14', '2004'),
    'عمل': ('قانون العمل', '14', '2004'),
    'المدني': ('القانون المدني', '22', '2004'),
    'مدني': ('القانون المدني', '22', '2004'),
    'الأسرة': ('قانون الأسرة', '22', '2006'),
    'أسرة': ('قانون الأسرة', '22', '2006'),
    'التجارة': ('قانون التجارة', '27', '2006'),
    'تجارة': ('قانون التجارة', '27', '2006'),
    'الإجراءات': ('قانون الإجراءات الجنائية', '23', '2004'),
    'إجراءات': ('قانون الإجراءات الجنائية', '23', '2004'),
    'المرافعات': ('قانون المرافعات', '13', '1990'),
    'مرافعات': ('قانون المرافعات', '13', '1990'),
    'الشركات': ('قانون الشركات', '11', '2015'),
    'شركات': ('قانون الشركات', '11', '2015'),
    'المرور': ('قانون المرور', '19', '2007'),
    'مرور': ('قانون المرور', '19', '2007'),
    'جرائم': ('قانون الجرائم الإلكترونية', '14', '2014'),
    'إيجار': ('قانون الإيجارات', '4', '2008'),
}


def extract_refs(text):
    """يستخرج كل مراجع المواد القانونية من النص"""
    refs = []
    for pat in PATTERNS:
        for m in pat.finditer(text):
            groups = m.groups()
            if len(groups) >= 2:
                art_num = groups[0]
                law_short = groups[1].strip()

                # Resolve short name
                if law_short in LAW_NAME_MAP:
                    law_name, law_num, law_year = LAW_NAME_MAP[law_short]
                else:
                    law_name = law_short
                    law_num = groups[2] if len(groups) > 2 else ''
                    law_year = groups[3] if len(groups) > 3 else ''

                refs.append({
                    "article": art_num,
                    "law_name": law_name,
                    "law_number": law_num or '',
                    "law_year": law_year or '',
                })

    # Deduplicate
    seen = set()
    unique = []
    for r in refs:
        key = f"{r['article']}_{r['law_name']}"
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


async def main():
    import asyncpg
    conn = await asyncpg.connect(DB_DSN)

    # Fetch all ruling/principle chunks
    rows = await conn.fetch("""
        SELECT id, article_number, law_name, law_number, law_year, content
        FROM chunks
        WHERE is_active = true
          AND (article_number LIKE '%تمييز%' OR article_number LIKE '%sjc%'
               OR law_name LIKE '%أحكام محكمة التمييز%' OR law_name LIKE '%مبادئ قضائية%')
        ORDER BY id
    """)
    print(f"Ruling/principle chunks: {len(rows)}")

    # Build index
    index = {}  # key: "م{art}_{law_name}" → list of ruling refs
    total_links = 0
    chunks_with_refs = 0

    for row in rows:
        content = row['content'] or ''
        refs = extract_refs(content)

        if refs:
            chunks_with_refs += 1

        for ref in refs:
            key = f"م{ref['article']}_{ref['law_name']}"
            if key not in index:
                index[key] = []

            # Extract ruling number from article_number
            ruling_id_match = re.search(r'تمييز-(\d+)', row['article_number'] or '')
            ruling_id = ruling_id_match.group(1) if ruling_id_match else ''

            index[key].append({
                "chunk_id": row['id'],
                "ruling_id": ruling_id,
                "ruling_law_name": row['law_name'] or '',
                "ruling_number": row['law_number'] or '',
                "ruling_year": row['law_year'] or '',
                "snippet": content[:200],
            })
            total_links += 1

    print(f"\nIndex built:")
    print(f"  Unique article keys: {len(index)}")
    print(f"  Total links: {total_links}")
    print(f"  Chunks with refs: {chunks_with_refs}/{len(rows)}")

    # Top 20 most-referenced articles
    top = sorted(index.items(), key=lambda x: -len(x[1]))[:20]
    print(f"\n  Top 20 most-referenced articles:")
    for key, rulings in top:
        print(f"    {key}: {len(rulings)} rulings")

    # Save index
    # Convert for JSON (chunk IDs to int)
    json_index = {}
    for key, rulings in index.items():
        json_index[key] = [{"chunk_id": r["chunk_id"], "ruling_id": r["ruling_id"],
                            "snippet": r["snippet"][:150]} for r in rulings]

    out_path = "scripts/article_ruling_index.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(json_index, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved to {out_path} ({len(json_index)} keys)")

    # Also save a compact version for loading into memory
    compact = {}
    for key, rulings in index.items():
        compact[key] = [r["chunk_id"] for r in rulings]

    compact_path = "scripts/article_ruling_compact.json"
    with open(compact_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False)
    print(f"  Compact saved to {compact_path}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
