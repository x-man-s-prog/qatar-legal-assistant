#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/overnight_7h_improve.py
================================
مهمة ليلية 7 ساعات — تحسين ذاتي شامل للمساعد القانوني القطري.
يعمل بشكل مستقل بالكامل بدون تدخل بشري.
يستخدم البيانات الموجودة في قاعدة البيانات لتحسين النظام.

الجدول:
  ساعة 1-2:    المرحلة 1 — توسيع فهرس الربط (مادة <- حكم تمييز)
  ساعة 2-3:    المرحلة 2 — توسيع الإجابات الجاهزة (known_answers)
  ساعة 3-4.5:  المرحلة 3 — بناء قوالب مذكرات محسّنة
  ساعة 4.5-5.5: المرحلة 4 — توسيع خريطة المواضيع
  ساعة 5.5-6.5: المرحلة 5 — اختبار ذاتي شامل (100+ سؤال)
  ساعة 6.5-7:   المرحلة 6 — التقرير النهائي
"""

import os
import sys
import json
import re
import time
import logging
import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# إعدادات
# ═══════════════════════════════════════════════════════════════
TOTAL_HOURS = 7
BASE_DIR = Path(__file__).resolve().parent.parent  # الكود root
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "overnight_results"
LOG_FILE = SCRIPT_DIR / "overnight_7h.log"

# DB — داخل Docker يستخدم 'db'، خارجه يستخدم 'localhost'
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_URL = f"postgresql://raguser:RAGsecret2024!@{DB_HOST}:5432/ragdb"

API_URL = os.environ.get("API_URL", "http://localhost:8000/api/v1/query/")
API_KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Logger — file only (no stdout encoding issues on Windows)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="w"),
    ],
)
# Add a safe stdout handler
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.INFO)
_stdout_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
try:
    _stdout_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
except Exception:
    pass
logging.getLogger().addHandler(_stdout_handler)

log = logging.getLogger("overnight_7h")

START_TIME = datetime.now()
END_TIME = START_TIME + timedelta(hours=TOTAL_HOURS)


def time_remaining():
    return (END_TIME - datetime.now()).total_seconds()


def phase_deadline(hours_from_start):
    return START_TIME + timedelta(hours=hours_from_start)


# ═══════════════════════════════════════════════════════════════
# خريطة تسميات القوانين -> اسم موحّد
# ═══════════════════════════════════════════════════════════════
LAW_NAME_MAP = {
    "العقوبات": "عقوبات_11_2004",
    "عقوبات": "عقوبات_11_2004",
    "قانون العقوبات": "عقوبات_11_2004",
    "العمل": "عمل_14_2004",
    "عمل": "عمل_14_2004",
    "قانون العمل": "عمل_14_2004",
    "المدني": "مدني",
    "مدني": "مدني",
    "القانون المدني": "مدني",
    "الأسرة": "أسرة_22_2006",
    "أسرة": "أسرة_22_2006",
    "قانون الأسرة": "أسرة_22_2006",
    "الأحوال الشخصية": "أسرة_22_2006",
    "التجارة": "تجارة_27_2006",
    "تجارة": "تجارة_27_2006",
    "قانون التجارة": "تجارة_27_2006",
    "الإجراءات الجنائية": "إجراءات_23_2004",
    "إجراءات جنائية": "إجراءات_23_2004",
    "الإجراءات": "إجراءات_23_2004",
    "المرافعات": "مرافعات_13_1990",
    "مرافعات": "مرافعات_13_1990",
    "الشركات": "شركات_11_2015",
    "شركات": "شركات_11_2015",
    "الإيجارات": "إيجارات_4_2008",
    "إيجارات": "إيجارات_4_2008",
    "المرور": "مرور",
    "الجرائم الإلكترونية": "إلكترونية_14_2014",
}

# أنماط استخراج المواد القانونية من نص الأحكام
ARTICLE_PATTERNS = [
    re.compile(
        r'الماد[ةه]\s*[\(\s]*(\d+)\s*[\)\s]*(?:\s*مكرر(?:ا|اً)?)?'
        r'(?:\s*(?:من|في)\s+)?(?:قانون\s+)?([^\n,،.؛:]{3,40}?)'
        r'(?:\s+رقم\s*[\(\s]*(\d+)\s*[\)\s]*)?'
        r'(?:\s+لسنة\s+(\d{4}))?',
        re.UNICODE,
    ),
    re.compile(
        r'بالماد[ةه]\s*[\(\s]*(\d+)\s*[\)\s]*(?:\s*من\s+)?(?:قانون\s+)?([^\n,،.]{3,30})',
        re.UNICODE,
    ),
    re.compile(
        r'وفقا?ً?\s+للماد[ةه]\s*[\(\s]*(\d+)\s*[\)\s]*(?:\s*من\s+)?(?:قانون\s+)?([^\n,،.]{3,30})',
        re.UNICODE,
    ),
    re.compile(
        r'عملا?ً?\s+بالماد[ةه]\s*[\(\s]*(\d+)\s*[\)\s]*(?:\s*من\s+)?(?:قانون\s+)?([^\n,،.]{3,30})',
        re.UNICODE,
    ),
    re.compile(
        r'م[.\s]+(\d+)\s+(?:من\s+)?(?:قانون\s+)?(العقوبات|العمل|المدني|الأسرة|التجارة|الإجراءات|المرافعات|الشركات)',
        re.UNICODE,
    ),
]

RULING_REF_RE = re.compile(r'(?:الطعن|طعن)\s*(?:رقم)?\s*(\d+)\s*/?\s*(\d{4})', re.UNICODE)


# ═══════════════════════════════════════════════════════════════
# المرحلة 1: توسيع فهرس الربط
# ═══════════════════════════════════════════════════════════════
async def phase1_expand_linkage_index(pool, deadline):
    log.info("=" * 70)
    log.info("Phase 1: Expand linkage index (article -> ruling)")
    log.info("=" * 70)

    # 1. اقرأ الفهرس الحالي
    index_path = SCRIPT_DIR / "article_ruling_compact.json"
    current_index = {}
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            current_index = json.load(f)
    old_count = len(current_index)
    old_links = sum(len(v) if isinstance(v, list) else 1 for v in current_index.values())
    log.info(f"  Current index: {old_count} articles, {old_links} links")

    # 2. اسحب كل chunks الأحكام من DB
    async with pool.acquire() as conn:
        ruling_chunks = await conn.fetch(
            """SELECT id, content, law_name FROM chunks
               WHERE is_active = true
               AND (law_name LIKE '%أحكام محكمة التمييز%'
                    OR content LIKE '%محكمة التمييز%'
                    OR content LIKE '%طعن رقم%'
                    OR content LIKE '%مبدأ قضائي%')"""
        )
    log.info(f"  Ruling chunks from DB: {len(ruling_chunks)}")

    # 3. استخرج المراجع
    new_entries = 0
    processed = 0
    for chunk in ruling_chunks:
        if datetime.now() > deadline:
            log.info(f"  Deadline reached after {processed}/{len(ruling_chunks)} chunks")
            break

        content = chunk["content"] or ""
        chunk_id = chunk["id"]

        for pattern in ARTICLE_PATTERNS:
            for match in pattern.finditer(content):
                groups = match.groups()
                article_num = groups[0] if groups else ""
                law_name_raw = groups[1].strip() if len(groups) > 1 and groups[1] else ""

                if not article_num or not article_num.isdigit():
                    continue
                if int(article_num) > 2000:
                    continue  # أرقام غير واقعية

                # وحّد اسم القانون
                law_key = ""
                for alias, canonical in LAW_NAME_MAP.items():
                    if alias in law_name_raw:
                        law_key = canonical
                        break
                if not law_key and law_name_raw:
                    law_key = re.sub(r"\s+", "_", law_name_raw[:20].strip())
                if not law_key:
                    continue

                index_key = f"م{article_num}_{law_key}"

                if index_key not in current_index:
                    current_index[index_key] = []

                # تجنب التكرار
                existing_ids = current_index[index_key]
                if isinstance(existing_ids, list):
                    if chunk_id not in existing_ids:
                        current_index[index_key].append(chunk_id)
                        new_entries += 1
                else:
                    # format قديم (عدد بدل قائمة)
                    current_index[index_key] = [existing_ids, chunk_id]
                    new_entries += 1

        processed += 1
        if processed % 1000 == 0:
            log.info(f"  Processed {processed}/{len(ruling_chunks)} — {new_entries} new entries")

    # 4. احفظ الفهرس المحدّث
    expanded_path = OUTPUT_DIR / "expanded_linkage_index.json"
    with open(expanded_path, "w", encoding="utf-8") as f:
        json.dump(current_index, f, ensure_ascii=False)

    # أيضاً حدّث الأصلي
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(current_index, f, ensure_ascii=False)

    new_count = len(current_index)
    new_links = sum(len(v) if isinstance(v, list) else 1 for v in current_index.values())

    # نسخ لـ Docker
    try:
        import subprocess
        subprocess.run(
            ["docker", "cp", str(index_path), "legal_app:/app/scripts/article_ruling_compact.json"],
            capture_output=True, timeout=10,
        )
        log.info("  Copied to Docker container")
    except Exception as e:
        log.warning(f"  Docker copy failed: {e}")

    result = {
        "processed_chunks": processed,
        "new_entries": new_entries,
        "old_articles": old_count,
        "new_articles": new_count,
        "old_links": old_links,
        "new_links": new_links,
    }
    log.info(f"  Phase 1 DONE: {old_count} -> {new_count} articles, {old_links} -> {new_links} links (+{new_entries} new)")
    return result


# ═══════════════════════════════════════════════════════════════
# المرحلة 2: توسيع الإجابات الجاهزة
# ═══════════════════════════════════════════════════════════════
NEW_TOPICS = [
    {"topic": "تزوير", "keywords": ["تزوير", "زوّر"], "search_regex": "تزوير|زور|محرر.{0,10}مزور", "law_filter": "%عقوبات%"},
    {"topic": "رشوة", "keywords": ["رشوة", "ارتشاء"], "search_regex": "رشوة|ارتشاء|رشا", "law_filter": "%عقوبات%"},
    {"topic": "خيانة_أمانة", "keywords": ["خيانة أمانة"], "search_regex": "خيانة.{0,5}أمانة|بدد|تبديد", "law_filter": "%عقوبات%"},
    {"topic": "حادث_مروري", "keywords": ["حادث مروري", "دهس"], "search_regex": "حادث|مرور|دهس", "law_filter": "%مرور%"},
    {"topic": "جرائم_معلوماتية", "keywords": ["اختراق", "هكر"], "search_regex": "إلكتروني|معلوماتي|اختراق", "law_filter": "%إلكترون%"},
    {"topic": "إصابة_عمل", "keywords": ["إصابة عمل"], "search_regex": "إصابة.{0,5}عمل|حادث.{0,5}عمل", "law_filter": "%عمل%"},
    {"topic": "عقد_عمل_محدد", "keywords": ["عقد محدد المدة"], "search_regex": "محدد.{0,5}المدة|تجديد.{0,5}العقد", "law_filter": "%عمل%"},
    {"topic": "نقل_كفالة", "keywords": ["نقل كفالة"], "search_regex": "نقل.{0,5}كفالة|تغيير.{0,5}صاحب", "law_filter": "%عمل%"},
    {"topic": "عقد_بيع", "keywords": ["عقد بيع"], "search_regex": "بيع|مبيع|ثمن", "law_filter": "%مدني%"},
    {"topic": "كفالة_ضمان", "keywords": ["كفالة", "ضمان"], "search_regex": "كفالة|كفيل|ضامن", "law_filter": "%مدني%"},
    {"topic": "وكالة", "keywords": ["وكالة", "توكيل"], "search_regex": "وكالة|توكيل|وكيل", "law_filter": "%مدني%"},
    {"topic": "مهر_صداق", "keywords": ["مهر", "صداق"], "search_regex": "مهر|صداق", "law_filter": "%أسرة%"},
    {"topic": "عدة", "keywords": ["عدة"], "search_regex": "عدة|اعتداد", "law_filter": "%أسرة%"},
    {"topic": "زواج_أجانب", "keywords": ["زواج أجنبية"], "search_regex": "زواج.{0,10}أجنب|إذن.{0,5}زواج", "law_filter": "%أسرة%"},
    {"topic": "إفلاس", "keywords": ["إفلاس"], "search_regex": "إفلاس|مفلس|تصفية", "law_filter": "%تجار%"},
    {"topic": "علامة_تجارية", "keywords": ["علامة تجارية"], "search_regex": "علامة.{0,5}تجارية|ماركة", "law_filter": "%علامات%"},
    {"topic": "تظلم_إداري", "keywords": ["تظلم", "قرار إداري"], "search_regex": "تظلم|قرار.{0,5}إداري|إلغاء.{0,5}قرار", "law_filter": "%"},
    {"topic": "جنسية", "keywords": ["جنسية", "تجنيس"], "search_regex": "جنسية|تجنيس|سحب.{0,5}جنسية", "law_filter": "%جنسية%"},
    {"topic": "تسجيل_عقاري", "keywords": ["تسجيل عقاري", "ملكية"], "search_regex": "تسجيل.{0,5}عقاري|سند.{0,5}ملكية|صك", "law_filter": "%عقاري%"},
    {"topic": "غش_تجاري", "keywords": ["غش تجاري", "تقليد"], "search_regex": "غش.{0,5}تجاري|تقليد|مغشوش", "law_filter": "%"},
]


async def phase2_expand_known_answers(pool, deadline):
    log.info("=" * 70)
    log.info("Phase 2: Expand known_answers")
    log.info("=" * 70)

    new_answers = {}

    for topic_info in NEW_TOPICS:
        if datetime.now() > deadline:
            log.info("  Deadline reached")
            break

        topic = topic_info["topic"]
        regex = topic_info["search_regex"]
        law_f = topic_info["law_filter"]

        try:
            async with pool.acquire() as conn:
                # ابحث عن مواد قانونية
                rows = await conn.fetch(
                    """SELECT content, law_name FROM chunks
                       WHERE is_active = true
                       AND content ~* $1
                       AND law_name ILIKE $2
                       AND law_name NOT LIKE '%أحكام محكمة التمييز%'
                       ORDER BY length(content) DESC
                       LIMIT 3""",
                    regex, law_f,
                )

                if not rows:
                    log.info(f"  {topic}: not found in DB")
                    continue

                answer_parts = [f"**{topic.replace('_', ' ')}:**\n"]
                for row in rows:
                    txt = row["content"][:400].strip()
                    law = row["law_name"] or ""
                    answer_parts.append(f"**{law}:**\n{txt}\n")

                # ابحث عن أحكام تمييز
                rulings = await conn.fetch(
                    """SELECT content FROM chunks
                       WHERE is_active = true
                       AND law_name LIKE '%أحكام محكمة التمييز%'
                       AND content ~* $1
                       LIMIT 2""",
                    regex,
                )
                if rulings:
                    answer_parts.append("\n**أحكام محكمة التمييز:**")
                    for r in rulings:
                        answer_parts.append(f"  {r['content'][:250]}")

                new_answers[topic] = {
                    "text": "\n".join(answer_parts),
                    "keywords": topic_info["keywords"],
                    "sources": len(rows),
                    "rulings": len(rulings),
                }
                log.info(f"  {topic}: {len(rows)} sources + {len(rulings)} rulings")

        except Exception as e:
            log.warning(f"  {topic}: error — {e}")

    out = OUTPUT_DIR / "new_known_answers.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(new_answers, f, ensure_ascii=False, indent=2)

    log.info(f"  Phase 2 DONE: {len(new_answers)} new answers")
    return {"new_answers": len(new_answers), "topics": list(new_answers.keys())}


# ═══════════════════════════════════════════════════════════════
# المرحلة 3: قوالب مذكرات محسّنة
# ═══════════════════════════════════════════════════════════════
MEMO_TYPES = [
    {"type": "مذكرة_دفاع_سرقة", "articles": ["334", "335"], "law": "%عقوبات%11%2004%",
     "defenses": ["انتفاء القصد الجنائي", "عدم كفاية الأدلة", "بطلان القبض والتفتيش"]},
    {"type": "مذكرة_دفاع_ضرب", "articles": ["304", "308"], "law": "%عقوبات%11%2004%",
     "defenses": ["الدفاع الشرعي", "انتفاء القصد", "المبالغة في وصف الإصابة"]},
    {"type": "مذكرة_دفاع_شيك", "articles": ["357"], "law": "%عقوبات%11%2004%",
     "defenses": ["الشيك كان ضماناً", "انتفاء القصد الجنائي", "الإكراه"]},
    {"type": "مذكرة_دفاع_تشهير", "articles": ["326", "327"], "law": "%عقوبات%11%2004%",
     "defenses": ["حق النقد المباح", "حسن النية", "الواقعة صحيحة"]},
    {"type": "مذكرة_دفاع_احتيال", "articles": ["354", "355"], "law": "%عقوبات%11%2004%",
     "defenses": ["انتفاء الاحتيال", "عدم توافر الركن المادي", "الصفقة مشروعة"]},
    {"type": "لائحة_فصل_تعسفي", "articles": ["49", "54", "61", "62"], "law": "%عمل%14%2004%",
     "defenses": ["عدم وجود سبب مشروع", "عدم الإنذار", "الفصل الانتقامي"]},
    {"type": "مذكرة_طلاق_للضرر", "articles": ["120", "109"], "law": "%أسرة%22%2006%",
     "defenses": ["إثبات الضرر", "استحالة العشرة", "حقوق الزوجة المالية"]},
    {"type": "مذكرة_حضانة", "articles": ["166", "173", "174"], "law": "%أسرة%22%2006%",
     "defenses": ["مصلحة المحضون", "أهلية الحاضن", "استقرار المحضون"]},
    {"type": "لائحة_تعويض", "articles": ["199", "200", "209"], "law": "%مدني%",
     "defenses": ["الخطأ ثابت", "الضرر محقق", "علاقة السببية"]},
    {"type": "مذكرة_إخلاء", "articles": ["590"], "law": "%مدني%",
     "defenses": ["عدم دفع الأجرة", "الإضرار بالعين", "مخالفة شروط العقد"]},
    {"type": "مذكرة_شركات", "articles": ["235", "240"], "law": "%شركات%11%2015%",
     "defenses": ["إساءة استعمال السلطة", "حقوق الأقلية", "عدم توزيع الأرباح"]},
    {"type": "مذكرة_طعن_تمييز", "articles": ["277"], "law": "%إجراءات%",
     "defenses": ["مخالفة القانون", "القصور في التسبيب", "الإخلال بحق الدفاع", "الفساد في الاستدلال"]},
]


async def phase3_memo_templates(pool, deadline):
    log.info("=" * 70)
    log.info("Phase 3: Enhanced memo templates")
    log.info("=" * 70)

    # اقرأ دليل الصياغة
    style_guide = {}
    guide_path = SCRIPT_DIR / "learned_styles" / "drafting_style_guide.json"
    if guide_path.exists():
        with open(guide_path, "r", encoding="utf-8") as f:
            style_guide = json.load(f)
    categories = style_guide.get("categories", {})

    templates = {}
    for memo in MEMO_TYPES:
        if datetime.now() > deadline:
            break

        mt = memo["type"]
        log.info(f"  Building template: {mt}")

        # اسحب نصوص المواد من DB
        articles_text = []
        for art_num in memo["articles"]:
            try:
                async with pool.acquire() as conn:
                    regex = f"المادة[\\s\\n]+{art_num}([^0-9]|$)"
                    row = await conn.fetchrow(
                        """SELECT content, law_name FROM chunks
                           WHERE is_active = true
                           AND law_name ILIKE $2
                           AND content ~ $1
                           ORDER BY length(content) ASC LIMIT 1""",
                        regex, memo["law"],
                    )
                    if row:
                        articles_text.append({
                            "article": art_num,
                            "law": row["law_name"],
                            "text": row["content"][:500],
                        })
            except Exception as e:
                log.debug(f"    Article {art_num}: {e}")

        # اسحب أحكام تمييز
        rulings_text = []
        try:
            async with pool.acquire() as conn:
                for art_num in memo["articles"][:2]:
                    rows = await conn.fetch(
                        """SELECT content FROM chunks
                           WHERE is_active = true
                           AND law_name LIKE '%أحكام محكمة التمييز%'
                           AND content ~ $1
                           LIMIT 1""",
                        f"المادة[\\s\\n(]+{art_num}",
                    )
                    for r in rows:
                        rulings_text.append(r["content"][:350])
        except Exception:
            pass

        templates[mt] = {
            "type": mt,
            "structure": ["بسم الله الرحمن الرحيم", "المقدمة والبيانات", "الوقائع",
                          "الدفوع الشكلية", "الدفوع الموضوعية", "السوابق القضائية", "الطلبات الختامية"],
            "articles": articles_text,
            "rulings": rulings_text,
            "defenses": memo["defenses"],
            "style_phrases": {
                cat: data.get("phrases", [])[:5]
                for cat, data in categories.items()
            },
        }
        log.info(f"    {len(articles_text)} articles, {len(rulings_text)} rulings, {len(memo['defenses'])} defenses")

    out = OUTPUT_DIR / "enhanced_memo_templates.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)

    log.info(f"  Phase 3 DONE: {len(templates)} templates")
    return {"templates_built": len(templates)}


# ═══════════════════════════════════════════════════════════════
# المرحلة 4: توسيع خريطة المواضيع
# ═══════════════════════════════════════════════════════════════
async def phase4_expand_topics(pool, deadline):
    log.info("=" * 70)
    log.info("Phase 4: Expand topic mapping")
    log.info("=" * 70)

    async with pool.acquire() as conn:
        # القوانين الموجودة
        laws = await conn.fetch(
            """SELECT law_name, COUNT(*) as cnt FROM chunks
               WHERE is_active = true AND law_name IS NOT NULL AND law_name != ''
               AND law_name NOT LIKE '%أحكام محكمة التمييز%'
               GROUP BY law_name ORDER BY cnt DESC LIMIT 50"""
        )

    log.info(f"  Laws in DB: {len(laws)}")
    laws_summary = {}
    for law in laws[:30]:
        laws_summary[law["law_name"]] = law["cnt"]
        log.info(f"    {law['law_name']}: {law['cnt']} chunks")

    # تحليل تغطية المواضيع
    topic_keywords = [
        "إيجار", "كفالة", "تأمين", "رهن", "وكالة", "بيع", "مقاولة",
        "حوالة", "صلح", "شفعة", "تقادم", "إفلاس", "مرور", "جمارك",
        "ضريبة", "استئناف", "تمييز", "نقض", "تحكيم", "وساطة",
    ]

    topic_coverage = {}
    for kw in topic_keywords:
        if datetime.now() > deadline:
            break
        try:
            async with pool.acquire() as conn:
                cnt = await conn.fetchval(
                    "SELECT COUNT(*) FROM chunks WHERE is_active = true AND content ILIKE $1",
                    f"%{kw}%",
                )
                topic_coverage[kw] = cnt
                if cnt > 0:
                    log.info(f"    '{kw}': {cnt} chunks")
        except Exception:
            pass

    out = OUTPUT_DIR / "discovered_topics.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"laws": laws_summary, "topics": topic_coverage}, f, ensure_ascii=False, indent=2)

    log.info(f"  Phase 4 DONE: {len(laws_summary)} laws, {len(topic_coverage)} topics analyzed")
    return {"laws_found": len(laws_summary), "topics_analyzed": len(topic_coverage)}


# ═══════════════════════════════════════════════════════════════
# المرحلة 5: اختبار ذاتي شامل
# ═══════════════════════════════════════════════════════════════
TEST_QUESTIONS = [
    # عمالي (20)
    "ما هي حقوق العامل عند الفصل التعسفي؟",
    "كم مدة الإشعار قبل إنهاء عقد العمل؟",
    "كيف تُحسب مكافأة نهاية الخدمة؟",
    "هل يحق لصاحب العمل فصلي بدون سبب؟",
    "كم الإجازة السنوية في قطر؟",
    "الكفيل طفشني من الشغل وش أسوي",
    "ما عطاني راتبي 3 شهور",
    "هل يحق لصاحب العمل حجز جوازي؟",
    "تم تخفيض راتبي بدون موافقتي",
    "كم ساعات العمل القانونية في قطر؟",
    "هل يحق لي الاستقالة فوراً؟",
    "ما حقوق المرأة الحامل في العمل؟",
    "هل يحق لي أجر عن ساعات العمل الإضافية؟",
    "ما إجراءات تقديم شكوى عمالية؟",
    "هل يحق لي نقل الكفالة بدون موافقة الكفيل؟",
    "ما حقوق العامل المنزلي في قطر؟",
    "هل يحق فصل العامل أثناء المرض؟",
    "ما هي حالات إنهاء العقد بدون إشعار؟",
    "كيف أرفع دعوى عمالية في قطر؟",
    "هل فيه فترة تجربة وكم مدتها؟",
    # جنائي (20)
    "ما عقوبة السرقة في قطر؟",
    "ما عقوبة الضرب والإيذاء؟",
    "ما عقوبة شيك بدون رصيد؟",
    "ما عقوبة التشهير؟",
    "ما عقوبة التهديد والابتزاز؟",
    "ما عقوبة السحر والشعوذة؟",
    "ما عقوبة حيازة المخدرات؟",
    "ما عقوبة القتل الخطأ؟",
    "ما عقوبة التزوير؟",
    "ما عقوبة الرشوة؟",
    "واحد ناصبني بـ 100 ألف ريال",
    "واحد هددني بالواتساب",
    "واحد سوى حساب باسمي بالانستقرام",
    "واحد شهّر فيني على تويتر",
    "هل محاولة الانتحار جريمة في قطر؟",
    "متى يسقط الحق في رفع الدعوى الجنائية؟",
    "ما هو الدفاع الشرعي؟",
    "ما عقوبة خيانة الأمانة؟",
    "ما عقوبة الاختلاس؟",
    "كيف أقدم بلاغ جنائي في قطر؟",
    # أسري (15)
    "كيف إجراءات الطلاق في قطر؟",
    "حرمتي تبي خلع وأنا مب موافق",
    "ما حقوق الحضانة بعد الطلاق؟",
    "متى تنتهي حضانة الأم؟",
    "ما هي النفقة الزوجية؟",
    "ما سن الزواج في قطر؟",
    "ما حكم الزواج بأجنبية في قطر؟",
    "كيف يُقسم الميراث شرعياً؟",
    "هل الوصية لوارث جائزة؟",
    "ما حقوق الزوجة عند الطلاق؟",
    "كيف أطلب النفقة من المحكمة؟",
    "ما حقوق الزيارة للأب بعد الطلاق؟",
    "هل يحق للأب منع الأم من السفر بالأطفال؟",
    "ما مؤخر الصداق ومتى يُستحق؟",
    "هل يحق للأم غير المسلمة حضانة أطفالها؟",
    # مدني (15)
    "ما حقوق المستأجر عند الإخلاء؟",
    "صاحب البيت يبي يطلعني من الشقة",
    "هل يحق للمؤجر زيادة الإيجار؟",
    "ما هي مدة التقادم المدني؟",
    "ما هو الشرط الجزائي في العقود؟",
    "كيف أطالب بتعويض عن ضرر؟",
    "ما ضمان العيوب الخفية في البيع؟",
    "كيف أفسخ عقد إيجار؟",
    "ما المسؤولية التقصيرية؟",
    "هل العقد الشفهي ملزم قانوناً؟",
    "ما حكم بيع ملك الغير؟",
    "كيف أسجل ملكية عقار في قطر؟",
    "ما التزامات المؤجر تجاه المستأجر؟",
    "كيف أطالب بدين بدون عقد مكتوب؟",
    "ما هو أمر الأداء؟",
    # تجاري (10)
    "شريكي بالشركة ياخذ فلوس بدون علمي",
    "كيف أؤسس شركة ذات مسؤولية محدودة في قطر؟",
    "ما حقوق الشريك في شركة؟",
    "كيف أصفي شركة؟",
    "ما عقوبة الغش التجاري؟",
    "ما هي الوكالة التجارية؟",
    "كيف أسجل علامة تجارية في قطر؟",
    "ما هو الإفلاس وما شروطه؟",
    "هل يحق لي كأقلية مساهمين الاطلاع على حسابات الشركة؟",
    "ما مسؤولية مدير الشركة تجاه الشركاء؟",
    # عامية صعبة (10)
    "ولدي انضرب بالمدرسة وابي اشتكي",
    "واحد ماخذ فلوسي وما يبي يردهم",
    "الشركة ما عطتني نهاية خدمة ولا شهادة",
    "ريال يبزني بصور خاصة",
    "خويي ضربني وكسر يدي وش أسوي",
    "حرمتي سافرت بالعيال وما ترجع",
    "يدي مات وأخوي ماخذ كل الميراث",
    "مستأجر بمحلي ما يدفع إيجار 6 شهور",
    "صاحب الشغل يطلب مني أشتغل 14 ساعة",
    "تورطت بقضية مخدرات وأبي أعرف العقوبة",
    # صياغة (10)
    "صيغ لي مذكرة دفاع في قضية ضرب",
    "صيغ لي عقد إيجار شقة",
    "صيغ لي عقد عمل",
    "صيغ لي لائحة دعوى فصل تعسفي",
    "صيغ لي عقد شراكة",
    "أبي نموذج شكوى عمالية",
    "صيغ لي مذكرة دفاع شيك بدون رصيد",
    "صيغ لي عقد بيع سيارة",
    "صيغ لي مذكرة طعن بالتمييز",
    "أبي نموذج عقد توظيف مدير تنفيذي",
]


async def phase5_self_test(deadline):
    log.info("=" * 70)
    log.info("Phase 5: Self-test (100+ questions)")
    log.info("=" * 70)

    import urllib.request

    headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}
    results = []
    success = 0
    fail = 0

    for i, question in enumerate(TEST_QUESTIONS):
        if datetime.now() > deadline:
            log.info(f"  Deadline after {i}/{len(TEST_QUESTIONS)} questions")
            break

        try:
            data = json.dumps({"query": question, "model": "openai", "session_id": f"selftest_{i}"}).encode("utf-8")
            req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read().decode("utf-8"))

            answer = result.get("answer", "")
            confidence = result.get("confidence", 0)
            domain = result.get("domain", "")

            is_good = len(answer) > 50 and confidence > 20

            results.append({
                "q_num": i + 1,
                "question": question[:60],
                "confidence": confidence,
                "domain": domain,
                "answer_length": len(answer),
                "is_good": is_good,
            })

            if is_good:
                success += 1
            else:
                fail += 1
                log.warning(f"  WEAK Q{i+1}: conf={confidence} len={len(answer)} — {question[:50]}")

            if (i + 1) % 10 == 0:
                log.info(f"  Progress: {i+1}/{len(TEST_QUESTIONS)} — pass={success} fail={fail}")

            time.sleep(3)

        except Exception as e:
            log.warning(f"  ERROR Q{i+1}: {e}")
            results.append({"q_num": i + 1, "question": question[:60], "confidence": 0, "is_good": False, "error": str(e)})
            fail += 1
            time.sleep(2)

    out = OUTPUT_DIR / "self_test_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    weak_qs = [r for r in results if not r.get("is_good")]
    pct = f"{100*success/max(len(results),1):.0f}%"

    log.info(f"  Phase 5 DONE: {len(results)} tested, {success} pass ({pct}), {fail} fail")
    return {"tested": len(results), "success": success, "fail": fail, "success_rate": pct,
            "weak_count": len(weak_qs), "weak_samples": [w["question"] for w in weak_qs[:10]]}


# ═══════════════════════════════════════════════════════════════
# المرحلة 6: التقرير النهائي
# ═══════════════════════════════════════════════════════════════
async def phase6_report(all_results):
    log.info("=" * 70)
    log.info("Phase 6: Final report")
    log.info("=" * 70)

    duration_h = (datetime.now() - START_TIME).total_seconds() / 3600
    report = {
        "mission": "Overnight 7h self-improvement",
        "started": START_TIME.isoformat(),
        "ended": datetime.now().isoformat(),
        "duration_hours": round(duration_h, 2),
        "phases": all_results,
        "summary": {
            "linkage_articles": all_results.get("phase1", {}).get("new_articles", "N/A"),
            "linkage_links": all_results.get("phase1", {}).get("new_links", "N/A"),
            "new_known_answers": all_results.get("phase2", {}).get("new_answers", "N/A"),
            "memo_templates": all_results.get("phase3", {}).get("templates_built", "N/A"),
            "topics_analyzed": all_results.get("phase4", {}).get("topics_analyzed", "N/A"),
            "test_success_rate": all_results.get("phase5", {}).get("success_rate", "N/A"),
        },
    }

    out = OUTPUT_DIR / "final_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log.info(f"  Duration: {duration_h:.1f} hours")
    for k, v in report["summary"].items():
        log.info(f"  {k}: {v}")
    log.info(f"  Report saved: {out}")
    return report


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════
async def main():
    log.info(f"Started: {START_TIME.isoformat()}")
    log.info(f"Planned end: {END_TIME.isoformat()}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import asyncpg
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)

    all_results = {}

    try:
        if time_remaining() > 0:
            try:
                all_results["phase1"] = await phase1_expand_linkage_index(pool, phase_deadline(2))
            except Exception as e:
                log.error(f"Phase 1 failed: {e}", exc_info=True)
                all_results["phase1"] = {"error": str(e)}

        if time_remaining() > 0:
            try:
                all_results["phase2"] = await phase2_expand_known_answers(pool, phase_deadline(3))
            except Exception as e:
                log.error(f"Phase 2 failed: {e}", exc_info=True)
                all_results["phase2"] = {"error": str(e)}

        if time_remaining() > 0:
            try:
                all_results["phase3"] = await phase3_memo_templates(pool, phase_deadline(4.5))
            except Exception as e:
                log.error(f"Phase 3 failed: {e}", exc_info=True)
                all_results["phase3"] = {"error": str(e)}

        if time_remaining() > 0:
            try:
                all_results["phase4"] = await phase4_expand_topics(pool, phase_deadline(5.5))
            except Exception as e:
                log.error(f"Phase 4 failed: {e}", exc_info=True)
                all_results["phase4"] = {"error": str(e)}

        if time_remaining() > 0:
            try:
                all_results["phase5"] = await phase5_self_test(phase_deadline(6.5))
            except Exception as e:
                log.error(f"Phase 5 failed: {e}", exc_info=True)
                all_results["phase5"] = {"error": str(e)}

        await phase6_report(all_results)

    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
    finally:
        await pool.close()

    log.info(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
