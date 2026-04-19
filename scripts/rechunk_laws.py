# -*- coding: utf-8 -*-
"""
scripts/rechunk_laws.py — إعادة تقطيع القوانين بمعيار "مادة = chunk"

الاستراتيجية:
  • كل مادة قانونية تُصبح chunk مستقلاً
  • الحجم المستهدف: 50–1200 محرف لكل chunk
  • المواد الطويلة (>1200) تُقسَّم على الفقرات
  • التداخل (overlap) = 0 — كل مادة وحدة منطقية مستقلة
  • يُخزَّن article_number مستخرجاً تلقائياً
  • يُخزَّن canonical_name من normalize_law_name

الاستخدام:
  # عرض تجريبي لقانون واحد (بدون تعديل DB):
  python scripts/rechunk_laws.py --law-id 323 --dry-run

  # إعادة تقطيع قانون واحد بالفعل:
  python scripts/rechunk_laws.py --law-id 323

  # إعادة تقطيع مجال كامل:
  python scripts/rechunk_laws.py --domain عمالي

  # إعادة تقطيع الكل (يستغرق وقتاً طويلاً):
  python scripts/rechunk_laws.py --all

  # تقرير جودة فقط:
  python scripts/rechunk_laws.py --report
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg

from core.qatar_legal_knowledge import get_law_domain, normalize_law_name

log = logging.getLogger("rechunk")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ══════════════════════════════════════════════════════════════════════════════
# استراتيجية التقطيع
# ══════════════════════════════════════════════════════════════════════════════

RECHUNK_STRATEGY = {
    "مادة_كاملة": {
        "وصف": "كل مادة قانونية chunk مستقل",
        "أقصى_حجم": 1200,
        "أدنى_حجم": 50,
        "فاصل_مادة": re.compile(
            r"(?:^|\n)\s*[المادة]{4,5}\s*[(\[]?\s*(\d+)\s*[)\]]?\s*[\n:]",
            re.MULTILINE | re.UNICODE,
        ),
        "فاصل_بديل": re.compile(
            r"(?:^|\n)\s*(?:المادة|مادة)\s+[(\[]?\s*(\d+)\s*[)\]]?",
            re.MULTILINE | re.UNICODE,
        ),
    },
    "chunk_overlap": 0,  # المواد لا تحتاج تداخل
}

# نمط استخراج رقم المادة
_ARTICLE_NUM_PAT = re.compile(
    r"المادة\s*[(\[]?\s*(\d+)\s*[)\]]?", re.UNICODE
)


# ══════════════════════════════════════════════════════════════════════════════
# دوال التقطيع
# ══════════════════════════════════════════════════════════════════════════════


def split_by_articles(text: str, max_size: int = 1200, min_size: int = 50) -> list[dict]:
    """
    يُقسِّم نص قانوني إلى قائمة من المواد.
    كل عنصر: {"article_number": str|None, "content": str}
    """
    strategy = RECHUNK_STRATEGY["مادة_كاملة"]
    pattern = strategy["فاصل_مادة"]
    alt_pattern = strategy["فاصل_بديل"]

    # البحث عن مواضع المواد
    matches = list(pattern.finditer(text))
    if not matches:
        matches = list(alt_pattern.finditer(text))

    if not matches:
        # لا مواد واضحة — أعِد النص كـ chunk واحد
        content = text.strip()
        if len(content) >= min_size:
            return [{"article_number": None, "content": content}]
        return []

    chunks = []
    positions = [(m.start(), m.group(1) if m.lastindex else None) for m in matches]

    # نص قبل المادة الأولى (مقدمة)
    preamble = text[: positions[0][0]].strip()
    if len(preamble) >= min_size:
        chunks.append({"article_number": "مقدمة", "content": preamble})

    # كل مادة
    for i, (start, art_num) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        content = text[start:end].strip()

        if len(content) < min_size:
            continue

        if len(content) <= max_size:
            chunks.append({"article_number": art_num, "content": content})
        else:
            # تقسيم المادة الطويلة على الفقرات
            sub_chunks = _split_long_article(content, art_num, max_size, min_size)
            chunks.extend(sub_chunks)

    return chunks


def _split_long_article(
    text: str, art_num: Optional[str], max_size: int, min_size: int
) -> list[dict]:
    """يُقسِّم مادة طويلة على الفقرات."""
    # محاولة التقسيم على الفقرات المُرقَّمة (أ، ب، ج أو 1، 2، 3)
    para_pat = re.compile(
        r"\n\s*(?:[أبتثجحخدذرزسشصضطظعغفقكلمنهوي][\-\.)]\s*|[١٢٣٤٥٦٧٨٩\d]+[\-\.)]\s*)",
        re.UNICODE,
    )
    parts = para_pat.split(text)

    if len(parts) <= 1:
        # تقسيم على السطور
        parts = [p.strip() for p in text.split("\n") if p.strip()]

    current = ""
    result = []
    part_idx = 0

    for part in parts:
        if len(current) + len(part) <= max_size:
            current = (current + "\n" + part).strip() if current else part
        else:
            if len(current) >= min_size:
                result.append({
                    "article_number": f"{art_num}-{part_idx}" if art_num else None,
                    "content": current,
                })
                part_idx += 1
            current = part

    if current and len(current) >= min_size:
        result.append({
            "article_number": f"{art_num}-{part_idx}" if art_num else art_num,
            "content": current,
        })

    # fallback: أعِد النص كاملاً إذا لم ينجح التقسيم
    if not result and len(text) >= min_size:
        result = [{"article_number": art_num, "content": text[:max_size]}]

    return result


# ══════════════════════════════════════════════════════════════════════════════
# تشغيل التقطيع على قانون واحد
# ══════════════════════════════════════════════════════════════════════════════


async def rechunk_law(
    conn: asyncpg.Connection,
    law_id: str,
    dry_run: bool = False,
) -> dict:
    """يُعيد تقطيع قانون واحد بمعرّفه law_id."""

    # جمع كل القطع الحالية لهذا القانون
    rows = await conn.fetch(
        """
        SELECT id, content, law_name, law_number, law_year, source, article_number
        FROM chunks
        WHERE law_id = $1
        ORDER BY id ASC
        """,
        int(law_id),
    )

    if not rows:
        log.warning("لا قطع لـ law_id=%s", law_id)
        return {"law_id": law_id, "old": 0, "new": 0, "skipped": True}

    # دمج كل القطع في نص واحد
    full_text = "\n".join(r["content"] for r in rows if r["content"])
    law_name = rows[0]["law_name"] or ""
    law_number = rows[0]["law_number"] or ""
    law_year = rows[0]["law_year"] or ""
    source = rows[0]["source"] or "txt"

    canonical = normalize_law_name(law_name)
    domain = get_law_domain(canonical)

    # تقطيع
    new_chunks = split_by_articles(
        full_text,
        max_size=RECHUNK_STRATEGY["مادة_كاملة"]["أقصى_حجم"],
        min_size=RECHUNK_STRATEGY["مادة_كاملة"]["أدنى_حجم"],
    )

    stats = {
        "law_id": law_id,
        "law_name": canonical,
        "domain": domain,
        "old": len(rows),
        "new": len(new_chunks),
        "dry_run": dry_run,
    }

    if dry_run:
        log.info(
            "[DRY-RUN] %s | القديم: %d → الجديد: %d | مجال: %s",
            canonical[:50],
            len(rows),
            len(new_chunks),
            domain,
        )
        for i, c in enumerate(new_chunks[:5], 1):
            log.info(
                "  [%d] art=%s len=%d | %s...",
                i,
                c["article_number"],
                len(c["content"]),
                c["content"][:60].replace("\n", " "),
            )
        if len(new_chunks) > 5:
            log.info("  ... و%d قطعة أخرى", len(new_chunks) - 5)
        return stats

    # حذف القطع القديمة (الجدول المرجعي chunks_backup_20260406 يحتوي نسخة احتياطية)
    await conn.execute(
        "DELETE FROM chunks WHERE law_id = $1", int(law_id)
    )

    # إدراج القطع الجديدة (بدون embedding — تحتاج إعادة تضمين لاحقاً)
    insert_rows = []
    for chunk in new_chunks:
        insert_rows.append((
            int(law_id),
            canonical,
            law_number,
            law_year,
            chunk["article_number"],
            chunk["content"],
            source,
            True,   # is_active
            domain,
        ))

    await conn.executemany(
        """
        INSERT INTO chunks
            (law_id, law_name, law_number, law_year, article_number,
             content, source, is_active, domain)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        insert_rows,
    )

    log.info(
        "✅ %s | %d → %d قطعة | مجال: %s",
        canonical[:50], len(rows), len(new_chunks), domain,
    )
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# تقرير الجودة الحالية
# ══════════════════════════════════════════════════════════════════════════════


async def print_quality_report(conn: asyncpg.Connection) -> None:
    """يطبع تقرير جودة التقطيع الحالي."""
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE LENGTH(content)<100) as tiny,
            COUNT(*) FILTER (WHERE LENGTH(content) BETWEEN 100 AND 400) as small_med,
            COUNT(*) FILTER (WHERE LENGTH(content) BETWEEN 400 AND 800) as ideal,
            COUNT(*) FILTER (WHERE LENGTH(content)>800) as large,
            ROUND(AVG(LENGTH(content))) as avg_len,
            MIN(LENGTH(content)) as min_len,
            MAX(LENGTH(content)) as max_len
        FROM chunks WHERE is_active=TRUE
        """
    )
    total = row["total"]
    print("\n══════════════════════════════")
    print("  تقرير جودة التقطيع الحالي")
    print("══════════════════════════════")
    print(f"  إجمالي نشطة   : {total:,}")
    print(f"  صغيرة  (<100) : {row['tiny']:,} ({row['tiny']/total*100:.1f}%)")
    print(f"  متوسطة (100-400): {row['small_med']:,} ({row['small_med']/total*100:.1f}%)")
    print(f"  مثالية (400-800): {row['ideal']:,} ({row['ideal']/total*100:.1f}%)")
    print(f"  كبيرة  (>800)  : {row['large']:,} ({row['large']/total*100:.1f}%)")
    print(f"  متوسط الطول   : {row['avg_len']} محرف")
    print(f"  أقل / أعلى    : {row['min_len']} / {row['max_len']}")
    print("══════════════════════════════")

    # توزيع domain
    domain_rows = await conn.fetch(
        "SELECT domain, COUNT(*) as cnt FROM chunks WHERE is_active=TRUE GROUP BY domain ORDER BY cnt DESC"
    )
    print("\n  توزيع المجالات:")
    for r in domain_rows:
        print(f"    {(r['domain'] or 'NULL'):12s}: {r['cnt']:,}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# نقطة الدخول
# ══════════════════════════════════════════════════════════════════════════════


async def main(args: argparse.Namespace) -> None:
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "legal_db"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "legal_db"),
        user=os.getenv("DB_USER", "legal_user"),
        password=os.getenv("DB_PASSWORD", "legal_pass"),
    )

    try:
        if args.report:
            await print_quality_report(conn)
            return

        if args.law_id:
            await rechunk_law(conn, args.law_id, dry_run=args.dry_run)

        elif args.domain:
            # جلب law_ids لهذا المجال
            rows = await conn.fetch(
                """
                SELECT DISTINCT law_id
                FROM chunks
                WHERE domain = $1 AND is_active=TRUE
                ORDER BY law_id
                """,
                args.domain,
            )
            law_ids = [r["law_id"] for r in rows]
            log.info("مجال '%s' → %d قانون", args.domain, len(law_ids))

            stats_all = []
            for lid in law_ids:
                s = await rechunk_law(conn, lid, dry_run=args.dry_run)
                stats_all.append(s)

            old_total = sum(s["old"] for s in stats_all)
            new_total = sum(s["new"] for s in stats_all)
            log.info(
                "المجموع: %d قانون | %d → %d قطعة",
                len(stats_all), old_total, new_total,
            )

        elif args.all:
            # جلب كل law_ids المميزة
            rows = await conn.fetch(
                "SELECT DISTINCT law_id FROM chunks WHERE is_active=TRUE ORDER BY law_id"
            )
            law_ids = [r["law_id"] for r in rows]
            log.info("إجمالي القوانين: %d", len(law_ids))

            stats_all = []
            for i, lid in enumerate(law_ids, 1):
                if i % 100 == 0:
                    log.info("تقدم: %d/%d", i, len(law_ids))
                s = await rechunk_law(conn, lid, dry_run=args.dry_run)
                stats_all.append(s)

            old_total = sum(s["old"] for s in stats_all)
            new_total = sum(s["new"] for s in stats_all)
            log.info(
                "اكتمل: %d قانون | %d → %d قطعة",
                len(stats_all), old_total, new_total,
            )

            if not args.dry_run:
                await conn.execute("VACUUM ANALYZE chunks")
                log.info("VACUUM ANALYZE اكتمل")
        else:
            # بدون وسائط — طباعة التقرير
            await print_quality_report(conn)

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="إعادة تقطيع القوانين بمعيار: مادة = chunk"
    )
    parser.add_argument("--law-id", type=str, help="إعادة تقطيع قانون واحد بـ law_id")
    parser.add_argument("--domain", type=str, help="إعادة تقطيع مجال كامل (عمالي|جنائي|...)")
    parser.add_argument("--all", action="store_true", help="إعادة تقطيع كل القوانين")
    parser.add_argument("--dry-run", action="store_true", help="عرض فقط — لا تعديل على DB")
    parser.add_argument("--report", action="store_true", help="عرض تقرير جودة التقطيع الحالي")
    args = parser.parse_args()

    asyncio.run(main(args))
