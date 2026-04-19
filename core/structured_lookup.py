# -*- coding: utf-8 -*-
"""
Structured Legal Lookup V3 — Strict Routing + Answer Enforcement
================================================================
1. Classify query intent precisely
2. Route to EXACT source type (no cross-contamination)
3. Enforce answer contains expected structure
4. Refuse if wrong data would be returned
"""
import re, logging
from typing import Optional
from enum import Enum

log = logging.getLogger("lookup")


# ══════════════════════════════════════════════════════════════
# Step 1: Query Classification
# ══════════════════════════════════════════════════════════════

class QueryIntent(str, Enum):
    SALARY_QUERY = "salary_query"
    DRUG_TABLE = "drug_table"
    TABLE_LOOKUP = "table_lookup"
    ENUMERATION_LIST = "enumeration_list"
    ARTICLE_LOOKUP = "article_lookup"
    GENERAL_LEGAL = "general_legal"


# Classification rules — ORDER MATTERS (most specific first)
_SALARY_SIGNALS = [
    "سلم الرواتب", "سلم رواتب", "جدول الرواتب", "جدول الدرجات",
    "جدول الدرجات والرواتب", "مربوط", "راتب درجة", "كم راتب",
    "درجة سابعة", "درجة سابعه", "راتب موظف", "الدرجة المالية",
    "رواتب الموظفين", "كم الراتب",
    # Follow-up variants — "الدرجة السابعة فقط", "الدرجة الأولى", etc.
    "الدرجة السابعة", "الدرجة الأولى", "الدرجة الثانية", "الدرجة الثالثة",
    "الدرجة الرابعة", "الدرجة الخامسة", "الدرجة السادسة",
    "الدرجة الممتازة", "الدرجة الخاصة",
    "راتب الدرجة",
]
_DRUG_SIGNALS = [
    "جدول المخدرات", "المواد المخدرة", "المؤثرات العقلية",
    "اسماء المخدرات", "أسماء المخدرات", "قائمة المخدرات",
    "الجدول الملحق بقانون المخدرات",
    # Follow-up / rephrased forms
    "أسماء المواد المخدرة", "اسماء المواد المخدرة",
    "المخدرات فقط", "مواد مخدرة",
]
_ENUM_SIGNALS = [
    "اذكر اسماء", "اذكر أسماء", "عدد لي", "اذكر لي",
    "المواد المحظورة", "المواد الكيميائية", "ما هي المواد",
    "قائمة المواد", "أسماء المواد", "اسماء المواد",
    # Chemical / precursor / explosives lists
    "المواد الكيميائية المحظورة", "الكيميائية المحضورة",
    "مكونات المتفجرات", "المركبات المتفجرة",
    "الخاصة بالمتفجرات", "المتفجرات",
]
_TABLE_SIGNALS = [
    "جدول رقم", "الجدول رقم", "الجدول الملحق", "جدول المواد",
    "ملحق رقم", "الملحق رقم", "البند رقم", "البند",
]
_ARTICLE_SIGNALS = ["نص المادة", "نص الماده", "عطني نص", "اكتب نص"]


def classify_query(query: str) -> QueryIntent:
    """Strict query classification. Most specific intent wins."""
    q = query.lower().strip()

    # Article lookup (handled elsewhere)
    if any(s in q for s in _ARTICLE_SIGNALS):
        return QueryIntent.ARTICLE_LOOKUP

    # Salary — BEFORE generic table (so "جدول الرواتب" → SALARY not TABLE)
    if any(s in q for s in _SALARY_SIGNALS):
        log.info("[CLASSIFICATION] SALARY_QUERY: %s", q[:50])
        return QueryIntent.SALARY_QUERY

    # Drug table
    if any(s in q for s in _DRUG_SIGNALS):
        log.info("[CLASSIFICATION] DRUG_TABLE: %s", q[:50])
        return QueryIntent.DRUG_TABLE

    # Enumeration / list
    if any(s in q for s in _ENUM_SIGNALS):
        # Check if it's actually a drug enum
        if "مخدر" in q or "مؤثر" in q:
            log.info("[CLASSIFICATION] DRUG_TABLE (via enum): %s", q[:50])
            return QueryIntent.DRUG_TABLE
        log.info("[CLASSIFICATION] ENUMERATION_LIST: %s", q[:50])
        return QueryIntent.ENUMERATION_LIST

    # Generic table
    if any(s in q for s in _TABLE_SIGNALS):
        log.info("[CLASSIFICATION] TABLE_LOOKUP: %s", q[:50])
        return QueryIntent.TABLE_LOOKUP

    return QueryIntent.GENERAL_LEGAL


# ══════════════════════════════════════════════════════════════
# Step 1.5: Grade Extraction for Salary Queries
# ══════════════════════════════════════════════════════════════

_GRADE_MAP = {
    "ممتازة": "الممتازة", "الممتازة": "الممتازة",
    "خاصة": "الخاصة", "الخاصة": "الخاصة",
    "أولى": "الأولى", "الأولى": "الأولى", "1": "الأولى",
    "ثانية": "الثانية", "الثانية": "الثانية", "2": "الثانية",
    "ثالثة": "الثالثة", "الثالثة": "الثالثة", "3": "الثالثة",
    "رابعة": "الرابعة", "الرابعة": "الرابعة", "4": "الرابعة",
    "خامسة": "الخامسة", "الخامسة": "الخامسة", "5": "الخامسة",
    "سادسة": "السادسة", "السادسة": "السادسة", "6": "السادسة",
    "سابعة": "السابعة", "السابعة": "السابعة", "سابعه": "السابعة", "7": "السابعة",
    # Grades 8-10 (may not exist in table — triggers refusal if not found)
    "ثامنة": "الثامنة", "الثامنة": "الثامنة", "8": "الثامنة",
    "تاسعة": "التاسعة", "التاسعة": "التاسعة", "9": "التاسعة",
    "عاشرة": "العاشرة", "العاشرة": "العاشرة", "10": "العاشرة",
}


_MULTIWORD_GRADES = [
    ("الحادية عشرة", "الحادية عشرة"), ("حادية عشرة", "الحادية عشرة"),
    ("الحادية عشر", "الحادية عشرة"),  ("حادية عشر", "الحادية عشرة"),
    ("الثانية عشرة", "الثانية عشرة"), ("ثانية عشرة", "الثانية عشرة"),
    ("الثانية عشر", "الثانية عشرة"),  ("ثانية عشر", "الثانية عشرة"),
    ("الثالثة عشرة", "الثالثة عشرة"), ("ثالثة عشرة", "الثالثة عشرة"),
    ("الثالثة عشر", "الثالثة عشرة"),  ("ثالثة عشر", "الثالثة عشرة"),
]


def _extract_grade(query: str) -> Optional[str]:
    """Extract the specific grade name from a salary query.
    Returns the FIRST grade found. For multi-grade (comparison),
    use _extract_multiple_grades() instead."""
    q = query.lower().strip()

    # Multi-word ordinals first (prefer longest match)
    for pattern, canonical in _MULTIWORD_GRADES:
        if re.search(r'(?:الدرجة|درجة)\s*' + re.escape(pattern), q):
            return canonical

    m = re.search(
        r'(?:الدرجة|درجة)\s*(?:ال)?(ممتازة|الممتازة|خاصة|الخاصة|'
        r'أولى|الأولى|ثانية|الثانية|ثالثة|الثالثة|رابعة|الرابعة|'
        r'خامسة|الخامسة|سادسة|السادسة|سابعة|السابعة|سابعه|'
        r'ثامنة|الثامنة|تاسعة|التاسعة|عاشرة|العاشرة|\d+)',
        q
    )
    if m:
        return _GRADE_MAP.get(m.group(1), m.group(1))

    # Fallback: any "الدرجة X" where X is an unrecognized Arabic word.
    # This treats the query as grade-specific so we refuse instead of
    # dumping the full table.
    fallback = re.search(r'(?:الدرجة|درجة)\s+([^\s،,؟?\.]{2,30})', q)
    if fallback:
        return fallback.group(1).strip()

    return None


def _extract_multiple_grades(query: str) -> list[str]:
    """Extract ALL grade names from a query. Used for comparison queries.

    Handles two patterns:
      1. 'الدرجة X والدرجة Y' (full prefix on both)
      2. 'الدرجة X و(ال)Y'    (prefix only on first; second is bare)
    """
    q = query.lower().strip()
    grade_alt = (
        r'(?:ممتازة|الممتازة|خاصة|الخاصة|'
        r'أولى|الأولى|ثانية|الثانية|ثالثة|الثالثة|رابعة|الرابعة|'
        r'خامسة|الخامسة|سادسة|السادسة|سابعة|السابعة|سابعه|'
        r'ثامنة|الثامنة|تاسعة|التاسعة|عاشرة|العاشرة|\d+)'
    )
    grades: list[str] = []

    # Pass 1: explicit "الدرجة X" / "درجة X"
    pattern_explicit = r'(?:الدرجة|درجة)\s*(?:ال)?(' + grade_alt + r')'
    for m in re.findall(pattern_explicit, q):
        g = _GRADE_MAP.get(m, m)
        if g not in grades:
            grades.append(g)

    # Pass 2: bare grade words connected with "و" or commas — only meaningful
    # when at least one explicit "الدرجة" was already found in this query.
    if "الدرجة" in q or "درجة" in q:
        pattern_bare = r'(?:^|\s|و|،|,)(?:ال)?(' + grade_alt + r')(?:\s|$|،|,|\?|؟)'
        for m in re.findall(pattern_bare, q):
            g = _GRADE_MAP.get(m, m)
            if g not in grades:
                grades.append(g)

    return grades


_TOTAL_SIGNALS = [
    "إجمالي", "اجمالي", "الإجمالي", "الاجمالي",
    "كامل الراتب", "الراتب الكامل", "الراتب الإجمالي", "الراتب الاجمالي",
    "بالعلاوات", "مع العلاوات", "شامل العلاوات", "شامل الإضافات",
    "صافي الراتب",
]
_BASIC_SIGNALS = [
    "مربوط", "المربوط", "أساسي", "الأساسي", "أساسية",
    "بداية المربوط", "نهاية المربوط",
]


def _classify_salary_scope(query: str) -> str:
    """Determine whether the user wants 'basic' (مربوط) or 'total' (إجمالي).

    Returns: 'total' | 'basic' | 'unspecified'
    """
    q = query.lower().strip()
    has_total = any(s in q for s in _TOTAL_SIGNALS)
    has_basic = any(s in q for s in _BASIC_SIGNALS)
    if has_total and not has_basic:
        return "total"
    if has_basic:
        return "basic"
    return "unspecified"


def _is_comparison_query(query: str) -> bool:
    """Detect if the query is asking to compare two or more grades."""
    q = query.lower().strip()
    comparison_signals = ["قارن", "مقارنة", "الفرق بين", "فرق بين", "بين"]
    has_signal = any(s in q for s in comparison_signals)
    has_multiple_grades = len(_extract_multiple_grades(q)) >= 2
    return has_signal and has_multiple_grades


_ALL_GRADE_NAMES = [
    "الممتازة", "الخاصة", "الأولى", "الثانية", "الثالثة", "الرابعة",
    "الخامسة", "السادسة", "السابعة", "الثامنة", "التاسعة", "العاشرة",
    "الحادية عشر", "الثانية عشر", "الثالثة عشر",
]


def _parse_salary_table(content: str) -> list[dict]:
    """Parse flat salary table text into structured rows.
    Handles both multi-line and single-line formats."""
    rows = []
    # Build a regex that splits on grade names
    grade_pattern = "|".join(re.escape(g) for g in _ALL_GRADE_NAMES)
    # Find all grade entries: grade_name followed by numbers
    matches = re.finditer(
        rf"({grade_pattern})\s*\|?\s*([\d,]+)\s*\|?\s*([\d,]+)",
        content
    )
    for m in matches:
        rows.append({
            "grade": m.group(1).strip(),
            "start": m.group(2).strip(),
            "end": m.group(3).strip(),
        })
    if rows:
        log.info("[TABLE_PARSE] parsed %d salary rows", len(rows))
    return rows


def _extract_grade_row(content: str, grade: str) -> Optional[str]:
    """Extract a specific grade's row from salary table content."""
    rows = _parse_salary_table(content)
    for row in rows:
        if row["grade"] == grade or grade in row["grade"]:
            return f"{row['grade']} | بداية المربوط: {row['start']} | نهاية المربوط: {row['end']}"
    # Try without "ال" prefix
    grade_bare = grade.replace("ال", "")
    for row in rows:
        if grade_bare in row["grade"]:
            return f"{row['grade']} | بداية المربوط: {row['start']} | نهاية المربوط: {row['end']}"

    # Fallback: line-based single-number extraction
    # Some chunks have "الدرجة السابعة: 25,000" without start/end pair
    for line in content.split('\n'):
        if grade in line or grade_bare in line:
            nums = re.findall(r"[\d,]+", line)
            nums = [n for n in nums if len(n.replace(",", "")) >= 3]
            if nums:
                return f"الدرجة {grade}: {nums[0]}" + (f" — {nums[1]}" if len(nums) > 1 else "")
    return None


# ══════════════════════════════════════════════════════════════
# Step 2: Source-Type-Strict Resolvers
# ══════════════════════════════════════════════════════════════

_JUDGMENT_SUPPRESS = (
    "law_name NOT ILIKE '%أحكام محكمة التمييز%' "
    "AND law_name NOT ILIKE '%قرار وزار%' "
    "AND law_name NOT ILIKE '%أمر أميري%'"
)


async def _resolve_salary(pool, query: str = "") -> tuple[Optional[dict], int]:
    """SALARY_QUERY: ONLY search salary_table/statute_table with salary numbers.
    NEVER return statute_text. NEVER return unrelated tables.
    If a specific grade is requested, extract only that grade's row.
    Returns dict with raw data for answer_builder."""
    target_grade = _extract_grade(query) if query else None
    scope = _classify_salary_scope(query) if query else "unspecified"
    if target_grade:
        log.info("[ROUTER] salary: target_grade=%s scope=%s", target_grade, scope)

    def _make_result(content, law_name, grade=None, grade_row_text=None):
        return {
            "raw_content": content, "law_name": law_name,
            "target_grade": grade or "", "grade_row": grade_row_text or "",
            "scope": scope,
        }

    # Track whether we found table data (for grade-miss refusal)
    _found_table_but_grade_missing = False

    async with pool.acquire() as conn:
        # Strategy 1: Chunks with source_type salary_table (highest priority)
        rows = await conn.fetch("""
            SELECT content, law_name FROM chunks
            WHERE is_active=true AND source_type='salary_table'
            ORDER BY length(content) DESC LIMIT 3
        """)
        for r in rows:
            if _enforce_salary(r["content"]):
                log.info("[ROUTER] salary: found salary_table source")
                if target_grade:
                    gr = _extract_grade_row(r["content"], target_grade)
                    if gr:
                        return _make_result(r["content"], r["law_name"], target_grade, gr), 98
                    # Grade requested but NOT found in this chunk — DON'T return full table
                    log.info("[ROUTER] salary: grade '%s' NOT in salary_table chunk", target_grade)
                    _found_table_but_grade_missing = True
                    continue  # Try next chunk
                return _make_result(r["content"], r["law_name"]), 95

        # Strategy 2: statute_table chunks from HR laws with salary numbers
        rows2 = await conn.fetch(f"""
            SELECT content, law_name FROM chunks
            WHERE is_active=true AND source_type='statute_table'
            AND (law_name ILIKE '%موارد بشرية%' OR law_name ILIKE '%البشرية المدنية%'
                 OR law_name ILIKE '%الخدمة المدنية%')
            AND content ILIKE '%المربوط%'
            AND {_JUDGMENT_SUPPRESS}
            ORDER BY length(content) DESC LIMIT 5
        """)
        for r in rows2:
            if _enforce_salary(r["content"]):
                log.info("[ROUTER] salary: found statute_table with salary data")
                if target_grade:
                    gr = _extract_grade_row(r["content"], target_grade)
                    if gr:
                        return _make_result(r["content"], r["law_name"], target_grade, gr), 95
                    log.info("[ROUTER] salary: grade '%s' NOT in statute_table chunk", target_grade)
                    _found_table_but_grade_missing = True
                    continue
                return _make_result(r["content"], r["law_name"]), 90

        # Strategy 3: ANY chunk with actual salary numbers (broadest)
        rows3 = await conn.fetch(f"""
            SELECT content, law_name FROM chunks
            WHERE is_active=true
            AND content ILIKE '%المربوط%' AND content ILIKE '%الدرجة%'
            AND content ~ '[0-9]{{2,3}},[0-9]{{3}}'
            AND {_JUDGMENT_SUPPRESS}
            ORDER BY
                CASE WHEN source_type IN ('salary_table','statute_table') THEN 0 ELSE 1 END,
                length(content) DESC
            LIMIT 3
        """)
        for r in rows3:
            if _enforce_salary(r["content"]):
                log.info("[ROUTER] salary: found via broad search")
                if target_grade:
                    gr = _extract_grade_row(r["content"], target_grade)
                    if gr:
                        return _make_result(r["content"], r["law_name"], target_grade, gr), 90
                    _found_table_but_grade_missing = True
                    continue
                return _make_result(r["content"], r["law_name"]), 85

    # ── CRITICAL: If a specific grade was requested but never found in any chunk,
    # return None → triggers refusal. NEVER dump the full table as a "fallback". ──
    if _found_table_but_grade_missing:
        log.info("[LOOKUP_REFUSE] salary: grade '%s' not found in any table — REFUSAL (no full-table dump)", target_grade)
    else:
        log.info("[LOOKUP_REFUSE] salary: no data with grade+amount rows")
    return None, 0


async def _resolve_salary_comparison(pool, query: str) -> tuple[Optional[dict], int]:
    """SALARY_QUERY (comparison): Extract rows for ALL grades mentioned in query.
    Used when query asks to compare 2+ grades, e.g.,
    'قارن بين مربوط الدرجة السادسة والسابعة'.
    Returns dict with comparison_rows: list of formatted grade rows."""
    target_grades = _extract_multiple_grades(query)
    if len(target_grades) < 2:
        # Not really a comparison — fall back to single
        return await _resolve_salary(pool, query)

    log.info("[ROUTER] salary_comparison: target_grades=%s", target_grades)

    found_rows: list[str] = []  # formatted grade rows
    missing_grades: list[str] = []
    source_law = ""
    base_content = ""

    async with pool.acquire() as conn:
        # Use the same 3-strategy search; gather rows from EACH chunk
        rows = await conn.fetch("""
            SELECT content, law_name FROM chunks
            WHERE is_active=true AND source_type='salary_table'
            ORDER BY length(content) DESC LIMIT 3
        """)
        rows2 = await conn.fetch(f"""
            SELECT content, law_name FROM chunks
            WHERE is_active=true AND source_type='statute_table'
            AND (law_name ILIKE '%موارد بشرية%' OR law_name ILIKE '%البشرية المدنية%'
                 OR law_name ILIKE '%الخدمة المدنية%')
            AND content ILIKE '%المربوط%'
            AND {_JUDGMENT_SUPPRESS}
            ORDER BY length(content) DESC LIMIT 5
        """)
        rows3 = await conn.fetch(f"""
            SELECT content, law_name FROM chunks
            WHERE is_active=true
            AND content ILIKE '%المربوط%' AND content ILIKE '%الدرجة%'
            AND content ~ '[0-9]{{2,3}},[0-9]{{3}}'
            AND {_JUDGMENT_SUPPRESS}
            ORDER BY
                CASE WHEN source_type IN ('salary_table','statute_table') THEN 0 ELSE 1 END,
                length(content) DESC
            LIMIT 3
        """)
        all_chunks = list(rows) + list(rows2) + list(rows3)

        # Deduplicate chunks by content prefix
        seen_prefixes = set()
        unique_chunks = []
        for r in all_chunks:
            prefix = r["content"][:120]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            unique_chunks.append(r)

        # Search each grade across all chunks
        for grade in target_grades:
            row_text = None
            for r in unique_chunks:
                if not _enforce_salary(r["content"]):
                    continue
                gr = _extract_grade_row(r["content"], grade)
                if gr:
                    row_text = gr
                    if not source_law:
                        source_law = r["law_name"] or ""
                        base_content = r["content"]
                    break
            if row_text:
                found_rows.append(row_text)
            else:
                missing_grades.append(grade)

    if not found_rows:
        log.info("[LOOKUP_REFUSE] salary_comparison: no grades found")
        return None, 0

    log.info("[ROUTER] salary_comparison: found %d/%d grades, missing=%s",
             len(found_rows), len(target_grades), missing_grades)
    return {
        "raw_content": base_content,
        "law_name": source_law,
        "target_grade": "",
        "grade_row": "",
        "comparison_rows": found_rows,
        "comparison_missing": missing_grades,
        "comparison_grades": target_grades,
    }, 96


async def _resolve_drug(pool) -> tuple[Optional[dict], int]:
    """DRUG_TABLE: Return actual substance names from statute_table.
    NEVER return amendment-only text. NEVER return penalties.
    Returns dict with raw_chunks for answer_builder."""
    async with pool.acquire() as conn:
        # ONLY statute_table chunks from drug law
        rows = await conn.fetch("""
            SELECT content, law_name, article_number FROM chunks
            WHERE is_active=true AND source_type='statute_table'
            AND (law_name ILIKE '%مكافحة المخدرات%' OR law_name ILIKE '%مخدرات%مؤثرات%')
            ORDER BY
                CASE WHEN content ~ '[A-Z]{3,}' THEN 0 ELSE 1 END,
                length(content) DESC
            LIMIT 10
        """)
        if rows:
            good = [r for r in rows if _enforce_drug_content(r["content"])]
            if good:
                raw_chunks = [{"content": r["content"][:2000], "law_name": r["law_name"] or ""} for r in good[:6]]
                log.info("[ROUTER] drug: %d/%d chunks pass enforcement", len(good), len(rows))
                return {"raw_chunks": raw_chunks, "raw_content": raw_chunks[0]["content"],
                        "law_name": raw_chunks[0]["law_name"]}, 95

    log.info("[LOOKUP_REFUSE] drug: no chunks with actual substance names")
    return None, 0


async def _resolve_table(pool, query: str) -> tuple[Optional[dict], int]:
    """TABLE_LOOKUP: Return statute_table/appendix content, not statute_text.
    Returns dict with raw_chunks for answer_builder."""
    q = query.lower()
    terms = [t for t in re.findall(r"[\u0600-\u06FF]{3,}", q)
             if t not in ("جدول", "الجدول", "ملحق", "رقم", "من", "في")][:3]

    async with pool.acquire() as conn:
        if terms:
            content_filter = " AND ".join(f"content ILIKE '%{t}%'" for t in terms[:2])
            rows = await conn.fetch(f"""
                SELECT content, law_name, article_number FROM chunks
                WHERE is_active=true
                AND source_type IN ('statute_table','appendix','schedule')
                AND ({content_filter})
                AND {_JUDGMENT_SUPPRESS}
                ORDER BY length(content) DESC LIMIT 5
            """)
        else:
            rows = []

        if rows:
            raw_chunks = [{"content": r["content"][:2000], "law_name": r["law_name"] or ""} for r in rows[:3]]
            return {"raw_chunks": raw_chunks, "raw_content": raw_chunks[0]["content"],
                    "law_name": raw_chunks[0]["law_name"]}, 90

        if terms:
            rows2 = await conn.fetch(f"""
                SELECT content, law_name FROM chunks
                WHERE is_active=true
                AND (content ILIKE '%جدول%' OR content ILIKE '%ملحق%')
                AND ({content_filter})
                AND {_JUDGMENT_SUPPRESS}
                AND length(content) > 200
                ORDER BY
                    CASE WHEN source_type IN ('statute_table','appendix') THEN 0 ELSE 1 END,
                    length(content) DESC
                LIMIT 3
            """)
            good = [r for r in rows2 if _enforce_table_content(r["content"])]
            if good:
                raw_chunks = [{"content": r["content"][:2000], "law_name": r["law_name"] or ""} for r in good[:3]]
                return {"raw_chunks": raw_chunks, "raw_content": raw_chunks[0]["content"],
                        "law_name": raw_chunks[0]["law_name"]}, 80

    return None, 0


async def _resolve_enum(pool, query: str) -> tuple[Optional[dict], int]:
    """ENUMERATION_LIST: Return row/item entries only, no explanations.
    Returns dict with raw_chunks for answer_builder."""
    q = query.lower()
    search_terms = []
    if "كيميائ" in q or ("محظور" in q and "مواد" in q):
        search_terms = ["%كيميائ%", "%محظور%"]
    else:
        words = [w for w in re.findall(r"[\u0600-\u06FF]{4,}", q)
                 if w not in ("اذكر", "اسماء", "أسماء", "قائمة", "المواد")]
        search_terms = [f"%{w}%" for w in words[:3]]

    if not search_terms:
        return None, 0

    content_filter = " OR ".join(f"content ILIKE '{t}'" for t in search_terms)
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT content, law_name FROM chunks
            WHERE is_active=true
            AND source_type IN ('statute_table','appendix','schedule')
            AND ({content_filter})
            AND {_JUDGMENT_SUPPRESS}
            ORDER BY length(content) DESC LIMIT 5
        """)
        good = [r for r in rows if _enforce_table_content(r["content"])]
        if good:
            raw_chunks = [{"content": r["content"][:2000], "law_name": r["law_name"] or ""} for r in good[:3]]
            return {"raw_chunks": raw_chunks, "raw_content": raw_chunks[0]["content"],
                    "law_name": raw_chunks[0]["law_name"]}, 85

    return None, 0


# ══════════════════════════════════════════════════════════════
# Step 3: Answer Enforcement
# ══════════════════════════════════════════════════════════════

def _enforce_salary(content: str) -> bool:
    """SALARY: Must have grade names + salary numbers."""
    grade_words = re.findall(
        r"(?:الدرجة|درجة|الممتازة|الخاصة|الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة)",
        content
    )
    salary_nums = re.findall(r"\d{2,3},\d{3}|\d{4,6}", content)
    ok = len(grade_words) >= 2 and len(salary_nums) >= 2
    if not ok:
        log.info("[ENFORCEMENT_REJECT] salary: grades=%d nums=%d", len(grade_words), len(salary_nums))
    return ok


def _enforce_drug_content(content: str) -> bool:
    """DRUG: Must have actual substance names (Arabic or English)."""
    has_english_names = bool(re.search(r"[A-Z]{3,}", content))
    has_arabic_substances = any(s in content for s in [
        "اسيتورفين", "مورفين", "كوكايين", "حشيش", "هيروين", "أفيون",
        "ﺍﺴﻴﺘﻭﺭﻓﻴﻥ", "ﻤﻭﺭﻓﻴﻥ", "ﺍﻟﻜﻭﻜﺎﻴﻴﻥ", "ﻫﻴﺭﻭﻴﻥ",
    ])
    has_numbered_items = len(re.findall(r"\d+\s*[\-ـ]\s*[^\d\n]{5,}", content)) >= 3
    ok = has_english_names or has_arabic_substances or has_numbered_items
    if not ok:
        log.info("[ENFORCEMENT_REJECT] drug: eng=%s ara=%s items=%s",
                 has_english_names, has_arabic_substances, has_numbered_items)
    return ok


def _enforce_table_content(content: str) -> bool:
    """TABLE: Must have structured rows, not just references."""
    # Must NOT be reference-only
    ref_signals = ["وفقاً للجدول", "وفقًا للجدول", "المرفق بهذا القانون",
                    "الجدول المرفق", "الجداول الملحقة"]
    is_ref_only = any(s in content for s in ref_signals) and \
                  len(re.findall(r"\d+[\s\-\.]+[^\d\n]{5,}", content)) < 3
    if is_ref_only:
        log.info("[ENFORCEMENT_REJECT] table: reference-only content")
        return False

    # Must have some structure
    has_items = len(re.findall(r"\d+[\s\-\.]+[^\d\n]{5,}", content)) >= 2
    has_pipe = "|" in content
    has_numbered = bool(re.search(r"(?:أ|ب|ج|1|2|3)\s*[\-\.ـ]\s*\S", content))
    return has_items or has_pipe or has_numbered


# Legacy _format_salary / _format_salary_grade REMOVED
# All salary formatting now handled by core/answer_builder.py


# ══════════════════════════════════════════════════════════════
# Refusal Messages — delegated to refusal_engine
# ══════════════════════════════════════════════════════════════
# Legacy _REFUSALS dict REMOVED. All refusals now generated by
# core/refusal_engine.py → generate_refusal(intent, query)
# This ensures: deterministic, style-clean, context-aware refusals.


# ══════════════════════════════════════════════════════════════
# Main Entry Point
# ══════════════════════════════════════════════════════════════

# Keep old name for backward compatibility
LookupIntent = QueryIntent


def detect_lookup_intent(query: str) -> QueryIntent:
    """Backward-compatible wrapper."""
    return classify_query(query)


async def resolve_lookup(query: str, pool) -> Optional[dict]:
    """Main entry. Returns result dict or None if not a lookup query.

    The result dict includes:
    - intent: query intent string
    - result: final built answer text (from answer_builder)
    - raw_data: dict with raw DB content for further processing
    - is_refusal: True if no data found
    - confidence: 0-100
    """
    from core.answer_builder import build_structured_answer

    intent = classify_query(query)

    if intent in (QueryIntent.GENERAL_LEGAL, QueryIntent.ARTICLE_LOOKUP):
        return None
    if not pool:
        return None

    log.info("[ROUTER] intent=%s query=%s", intent.value, query[:50])

    raw_data, conf = None, 0

    if intent == QueryIntent.SALARY_QUERY:
        # ── Check for comparison query (two+ grades) ──
        if _is_comparison_query(query):
            raw_data, conf = await _resolve_salary_comparison(pool, query)
        else:
            raw_data, conf = await _resolve_salary(pool, query)

    elif intent == QueryIntent.DRUG_TABLE:
        raw_data, conf = await _resolve_drug(pool)

    elif intent == QueryIntent.TABLE_LOOKUP:
        raw_data, conf = await _resolve_table(pool, query)

    elif intent == QueryIntent.ENUMERATION_LIST:
        raw_data, conf = await _resolve_enum(pool, query)

    if raw_data and conf > 0:
        # Build clean answer from raw data — NO LLM involved
        built = build_structured_answer(
            intent=intent.value,
            raw_content=raw_data.get("raw_content", ""),
            law_name=raw_data.get("law_name", ""),
            target_grade=raw_data.get("target_grade", ""),
            grade_row=raw_data.get("grade_row", ""),
            chunks=raw_data.get("raw_chunks"),
            comparison_rows=raw_data.get("comparison_rows"),
            comparison_missing=raw_data.get("comparison_missing"),
            comparison_grades=raw_data.get("comparison_grades"),
            scope=raw_data.get("scope", "unspecified"),
        )
        result_text = built if built else raw_data.get("raw_content", "")[:2000]

        # ── Hard assertion guard: verify clean output before returning ──
        _FORBIDDEN_MARKERS = ["📋", "⚖️", "🔍", "✅", "📊"]
        for marker in _FORBIDDEN_MARKERS:
            if marker in result_text:
                log.error("[DATA_FIRST_GUARD] FORBIDDEN marker '%s' in built answer! Stripping.", marker)
                result_text = result_text.replace(marker, "")

        from core.refusal_engine import assert_refusal_clean
        return {
            "intent": intent.value,
            "result": result_text.strip(),
            "raw_data": raw_data,
            "is_refusal": False,
            "confidence": conf,
            "from_structured_lookup": True,
        }

    # ── No data found → refusal ──
    from core.refusal_engine import generate_refusal, assert_refusal_clean
    refusal = generate_refusal(intent.value, query)
    assert_refusal_clean(refusal, intent.value)
    log.info("[REFUSAL] %s → %s", intent.value, refusal[:60])

    # Record this refusal for self-improvement analysis
    try:
        from core.failure_logger import log_failure, FailureType
        log_failure(
            failure_type=FailureType.REFUSAL,
            query=query,
            intent=intent.value,
            confidence=0,
            refusal_text=refusal,
        )
    except Exception:  # noqa: BLE001
        pass  # Never let logging break the request

    return {
        "intent": intent.value,
        "result": refusal,
        "raw_data": None,
        "is_refusal": True,
        "confidence": 0,
        "from_structured_lookup": True,
    }


# ══════════════════════════════════════════════════════════════
# Intelligent Follow-Up Handler
# ══════════════════════════════════════════════════════════════

_SALARY_FU_PATTERNS = [
    "هل هذا المبلغ يشمل", "هل يشمل البدلات", "هل يشمل هذا",
    "هل هذا الراتب", "هل هذا المربوط", "هل هذا الأساسي",
    "هل يشمل هذا الجدول", "هل الجدول يشمل", "هل ينطبق",
    "الأساسي فقط", "يشمل البدلات", "الإجمالي",
    "بدون البدلات", "قبل البدلات", "بعد البدلات",
    "جميع الجهات", "كل الجهات الحكومية", "القطاع الخاص",
    "هل هذا صافي", "هل فيه خصم", "بدل سكن", "علاوة",
]


def handle_salary_followup(query: str) -> Optional[str]:
    """Handle salary-related follow-up questions locally. No LLM needed."""
    q = query.lower()
    if not any(p in q for p in _SALARY_FU_PATTERNS):
        return None

    if any(w in q for w in ["بدلات", "الأساسي", "الإجمالي", "المبلغ يشمل", "صافي", "خصم"]):
        log.info("[FOLLOWUP] salary: بدلات/أساسي — local answer")
        return (
            "المبالغ الواردة في جدول الدرجات والرواتب هي الراتب الأساسي فقط "
            "(بداية ونهاية المربوط).\n\n"
            "الإجمالي الشهري عادةً يكون أعلى ويشمل بدلات وعلاوات مثل:\n"
            "• بدل السكن\n• العلاوة الاجتماعية\n• بدل النقل\n• بدلات خاصة بالجهة\n\n"
            "المبالغ النهائية تختلف من جهة حكومية لأخرى."
        )

    if any(w in q for w in ["بدل سكن", "علاوة"]):
        log.info("[FOLLOWUP] salary: بدل سكن/علاوة — local answer")
        return (
            "بدل السكن والعلاوات تُحدد حسب الجهة الحكومية والقرارات الخاصة بها. "
            "جدول الدرجات والرواتب لا يتضمن تفاصيل البدلات — فقط المربوط الأساسي."
        )

    if any(w in q for w in ["جميع الجهات", "كل الجهات", "ينطبق", "يشمل هذا الجدول"]):
        log.info("[FOLLOWUP] salary: جهات — local answer")
        return (
            "جدول الدرجات والرواتب الصادر بقانون الموارد البشرية المدنية رقم 15 لسنة 2016 "
            "ينطبق على موظفي الجهات الحكومية المدنية في دولة قطر.\n\n"
            "بعض الجهات الخاصة (مثل الجهات السيادية أو المؤسسات المستقلة) "
            "قد يكون لها جداول رواتب مختلفة."
        )

    if any(w in q for w in ["القطاع الخاص"]):
        log.info("[FOLLOWUP] salary: قطاع خاص — local answer")
        return (
            "جدول الدرجات والرواتب ينطبق على القطاع الحكومي فقط. "
            "رواتب القطاع الخاص تُحدد بالاتفاق بين صاحب العمل والموظف "
            "وفقاً لقانون العمل رقم 14 لسنة 2004."
        )

    return None