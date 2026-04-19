# -*- coding: utf-8 -*-
"""
Data-First Answer Builder
=========================
Deterministic, LLM-free answer construction for structured queries.

For salary, drug, table, and list intents, this module takes raw DB data
and produces clean, exact, human-readable output — no LLM involved.

Rules:
- NO memo headers (📋⚖️🔍✅📊)
- NO intro/conclusion/explanation
- NO filler text
- ONLY the requested data
- Direct answer first, source reference at end
"""
import re, logging
from typing import Optional

log = logging.getLogger("answer_builder")


# ══════════════════════════════════════════════════════════════
# Salary Answer Builder
# ══════════════════════════════════════════════════════════════

def build_salary_answer(
    content: str,
    law_name: str = "",
    target_grade: str = "",
    grade_row: str = "",
    scope: str = "unspecified",
) -> str:
    """
    Build a clean salary answer from raw DB content.

    scope:
      - 'basic'       — user asked for مربوط (basic salary). No clarifier needed.
      - 'total'       — user asked for إجمالي/كامل. Add note that table only
                        has basic salary; allowances must be added separately.
      - 'unspecified' — user did not specify; assume basic but add a brief
                        clarifier so they know.
    """
    law = _short_law(law_name)
    note = _build_scope_note(scope)

    if target_grade and grade_row:
        cleaned = _clean_salary_row(grade_row, target_grade)
        source = ""  # Source hidden from user-facing output
        log.info("[BUILD] salary_grade: %s scope=%s", target_grade, scope)
        return f"{cleaned}{note}{source}"

    cleaned = _clean_salary_table(content)
    source = f"\n(المصدر: {law})" if law else ""
    log.info("[BUILD] salary_table: %d chars scope=%s", len(cleaned), scope)
    return f"جدول الدرجات والرواتب:\n{cleaned}{note}{source}"


def _build_scope_note(scope: str) -> str:
    """Return a contextual note about basic vs total salary."""
    if scope == "total":
        return (
            "\n\nهذا المبلغ يمثل الراتب الأساسي (المربوط) فقط. "
            "الإجمالي الشهري عادةً يكون أعلى ويشمل:\n"
            "• بدل السكن\n• العلاوة الاجتماعية\n• بدل النقل\n"
            "• علاوات أخرى حسب الجهة الحكومية.\n"
            "الإجمالي الفعلي يختلف من جهة لأخرى ولا يمكن تحديده من الجدول وحده."
        )
    if scope == "unspecified":
        return "\nهذا هو الراتب الأساسي (المربوط). البدلات والعلاوات تُضاف حسب الجهة."
    return ""


def build_salary_comparison(
    rows: list,
    law_name: str = "",
    missing: list = None,
    grades_requested: list = None,
    scope: str = "unspecified",
) -> str:
    """
    Build a clean side-by-side salary comparison from multiple grade rows.

    Each row is a string like 'الدرجة السادسة | بداية المربوط: 4500 | نهاية المربوط: 6000'.
    Returns a clean, deterministic comparison block.
    """
    missing = missing or []
    grades_requested = grades_requested or []
    law = _short_law(law_name)
    cleaned_lines = []

    for row in rows:
        # Each row was already produced by _extract_grade_row.
        # Extract the grade name from the row prefix and the two numbers.
        parts = row.split("|")
        grade_name = parts[0].strip() if parts else row
        nums = re.findall(r"[\d,]+", row)
        nums = [n for n in nums if len(n.replace(",", "")) >= 3]
        if len(nums) >= 2:
            cleaned_lines.append(f"{grade_name}: {nums[0]} — {nums[1]} ريال")
        elif len(nums) == 1:
            cleaned_lines.append(f"{grade_name}: {nums[0]} ريال")
        else:
            cleaned_lines.append(grade_name)

    header = "مقارنة الدرجات المطلوبة:"
    body = "\n".join(cleaned_lines)

    # Add comparison insight
    insight = _build_comparison_insight(rows)

    note = ""
    if missing:
        note = "\nملاحظة: لم يتم العثور على بيانات للدرجات التالية: " + "، ".join(missing)
    scope_note = _build_scope_note(scope)
    source = f"\n(المصدر: {law})" if law else ""

    log.info("[BUILD] salary_comparison: %d rows, %d missing scope=%s",
             len(rows), len(missing), scope)
    return f"{header}\n{body}{insight}{note}{scope_note}{source}"


def _build_comparison_insight(rows: list) -> str:
    """Generate insight about grade differences."""
    if len(rows) < 2:
        return ""
    # Extract start salaries for comparison
    grade_salaries = []
    for row in rows:
        parts = row.split("|")
        grade_name = parts[0].strip() if parts else ""
        nums = re.findall(r"[\d,]+", row)
        nums = [n for n in nums if len(n.replace(",", "")) >= 3]
        if nums:
            try:
                val = int(nums[0].replace(",", ""))
                grade_salaries.append((grade_name, val))
            except ValueError:
                pass
    if len(grade_salaries) >= 2:
        highest = max(grade_salaries, key=lambda x: x[1])
        lowest = min(grade_salaries, key=lambda x: x[1])
        diff = highest[1] - lowest[1]
        return f"\n{highest[0]} أعلى من {lowest[0]} بفارق {diff:,} ريال تقريباً."
    return ""


def _clean_salary_row(grade_row: str, grade: str) -> str:
    """Extract a clean single-line salary from a grade row."""
    lines = [l.strip() for l in grade_row.split('\n') if l.strip()]

    # Try to extract numbers from the row
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", " ".join(lines))
    numbers = [n for n in numbers if len(n.replace(",", "").replace(".", "")) >= 3]

    if len(numbers) >= 2:
        return f"مربوط الدرجة {grade}: بداية {numbers[0]} ريال — نهاية {numbers[1]} ريال"
    elif len(numbers) == 1:
        return f"مربوط الدرجة {grade}: {numbers[0]} ريال"
    else:
        return f"الدرجة {grade}:\n" + "\n".join(lines)


def _clean_salary_table(content: str) -> str:
    """Clean a full salary table, keeping only data rows."""
    lines = content.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip pure header/decoration lines
        if stripped.startswith("📋") or stripped.startswith("---"):
            continue
        if stripped.startswith("جدول الدرجات") and "من" in stripped:
            continue  # old format header
        # Keep lines that have grade info or numbers
        has_grade = bool(re.search(
            r"(?:الدرجة|درجة|الممتازة|الخاصة|الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة)",
            stripped
        ))
        has_numbers = bool(re.search(r"\d{2,}", stripped))
        if has_grade or has_numbers or "|" in stripped:
            result.append(stripped)

    if result:
        return "\n".join(result)
    # Fallback: strip forbidden markers from raw content
    fallback = content[:2000]
    for marker in ["📋", "⚖️", "🔍", "✅", "📊"]:
        fallback = fallback.replace(marker, "")
    return fallback.strip()


# ══════════════════════════════════════════════════════════════
# Drug Answer Builder
# ══════════════════════════════════════════════════════════════

# OCR-form Arabic letters (presentation-forms) we want to normalize back
# to canonical Arabic. This avoids losing matches due to ﺍﺴﻴﺘﻭﺭﻓﻴﻥ vs اسيتورفين.
_OCR_NORMALIZE_MAP = str.maketrans({
    "ﺍ": "ا", "ﺎ": "ا", "ﺁ": "آ", "ﺂ": "آ", "ﺃ": "أ", "ﺄ": "أ",
    "ﺇ": "إ", "ﺈ": "إ", "ﺐ": "ب", "ﺑ": "ب", "ﺒ": "ب", "ﺏ": "ب",
    "ﺕ": "ت", "ﺖ": "ت", "ﺗ": "ت", "ﺘ": "ت",
    "ﺙ": "ث", "ﺚ": "ث", "ﺛ": "ث", "ﺜ": "ث",
    "ﺝ": "ج", "ﺞ": "ج", "ﺟ": "ج", "ﺠ": "ج",
    "ﺡ": "ح", "ﺢ": "ح", "ﺣ": "ح", "ﺤ": "ح",
    "ﺥ": "خ", "ﺦ": "خ", "ﺧ": "خ", "ﺨ": "خ",
    "ﺩ": "د", "ﺪ": "د", "ﺫ": "ذ", "ﺬ": "ذ",
    "ﺭ": "ر", "ﺮ": "ر", "ﺯ": "ز", "ﺰ": "ز",
    "ﺱ": "س", "ﺲ": "س", "ﺳ": "س", "ﺴ": "س",
    "ﺵ": "ش", "ﺶ": "ش", "ﺷ": "ش", "ﺸ": "ش",
    "ﺹ": "ص", "ﺺ": "ص", "ﺻ": "ص", "ﺼ": "ص",
    "ﺽ": "ض", "ﺾ": "ض", "ﺿ": "ض", "ﻀ": "ض",
    "ﻁ": "ط", "ﻂ": "ط", "ﻃ": "ط", "ﻄ": "ط",
    "ﻅ": "ظ", "ﻆ": "ظ", "ﻇ": "ظ", "ﻈ": "ظ",
    "ﻉ": "ع", "ﻊ": "ع", "ﻋ": "ع", "ﻌ": "ع",
    "ﻍ": "غ", "ﻎ": "غ", "ﻏ": "غ", "ﻐ": "غ",
    "ﻑ": "ف", "ﻒ": "ف", "ﻓ": "ف", "ﻔ": "ف",
    "ﻕ": "ق", "ﻖ": "ق", "ﻗ": "ق", "ﻘ": "ق",
    "ﻙ": "ك", "ﻚ": "ك", "ﻛ": "ك", "ﻜ": "ك",
    "ﻝ": "ل", "ﻞ": "ل", "ﻟ": "ل", "ﻠ": "ل",
    "ﻡ": "م", "ﻢ": "م", "ﻣ": "م", "ﻤ": "م",
    "ﻥ": "ن", "ﻦ": "ن", "ﻧ": "ن", "ﻨ": "ن",
    "ﻩ": "ه", "ﻪ": "ه", "ﻫ": "ه", "ﻬ": "ه",
    "ﻭ": "و", "ﻮ": "و", "ﻱ": "ي", "ﻲ": "ي", "ﻳ": "ي", "ﻴ": "ي",
    "ﻯ": "ى", "ﻰ": "ى", "ﺓ": "ة", "ﺔ": "ة", "ﺀ": "ء",
    "ﺋ": "ئ", "ﺌ": "ئ", "ﺉ": "ئ", "ﺊ": "ئ",
    "ﺅ": "ؤ", "ﺆ": "ؤ",
    # Non-breaking & odd whitespace
    "\u00A0": " ", "\u200E": "", "\u200F": "", "\u202B": "", "\u202C": "",
})


def _normalize_ocr(text: str) -> str:
    """Normalize OCR Arabic presentation-form letters into canonical Arabic."""
    if not text:
        return text
    return text.translate(_OCR_NORMALIZE_MAP)


# Lines that look like OCR garbage (mostly punctuation, page numbers,
# isolated digits, or chemical-formula fragments)
_GARBAGE_PATTERNS = [
    re.compile(r"^[\(\)\[\]\{\}\d\s\-\.,;:_\|]+$"),
    re.compile(r"^[Α-Ωα-ωΑ-Ωа-яА-Я]+$"),  # Greek/Cyrillic noise
    re.compile(r"^[A-Z]{1,2}\s*\d+\s*$"),  # e.g. "C 12"
    re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ\s\.]+$"),  # Roman numerals only
]


def _is_garbage_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if len(s) < 3:
        return True
    for p in _GARBAGE_PATTERNS:
        if p.match(s):
            return True
    return False


def build_drug_answer(chunks: list) -> str:
    """Build a clean drug substance list using the dedicated extractor."""
    from core.drug_extractor import build_clean_drug_list
    source_law = ""
    for chunk in chunks[:6]:
        law = chunk.get("law_name", "") if isinstance(chunk, dict) else ""
        if law and not source_law:
            source_law = _short_law(law)
            break
    return build_clean_drug_list(chunks, source_law)


# ══════════════════════════════════════════════════════════════
# Table Answer Builder
# ══════════════════════════════════════════════════════════════

def build_table_answer(chunks: list) -> str:
    """
    Build a clean table from raw DB chunks.

    Returns formatted rows only — no explanations.
    """
    parts = []
    seen_laws = set()

    for chunk in chunks[:3]:
        content = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
        law = chunk.get("law_name", "") if isinstance(chunk, dict) else ""
        law_short = _short_law(law)

        cleaned = _clean_table_content(content)
        if not cleaned:
            continue

        # Add source header only if multiple laws
        if law_short and law_short not in seen_laws:
            seen_laws.add(law_short)
            if len(chunks) > 1:
                parts.append(f"من {law_short}:")
        parts.append(cleaned)

    if not parts:
        return ""

    result = "\n\n".join(parts)
    log.info("[BUILD] table: %d chars from %d chunks", len(result), len(chunks))
    return result


def _clean_table_content(content: str) -> str:
    """Clean table content, keeping only structured data."""
    content = _normalize_ocr(content)
    lines = content.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("📋") or stripped.startswith("---"):
            continue
        if _is_garbage_line(stripped):
            continue
        has_item = bool(re.match(r"^\s*\d+[\.\-\)ـ]", stripped))
        has_pipe = "|" in stripped
        has_bullet = bool(re.match(r"^\s*[-•●▪]", stripped))
        has_letter = bool(re.match(r"^\s*(?:أ|ب|ج|د|هـ)\s*[\-\.ـ\)]", stripped))
        is_short = len(stripped) < 120

        if has_item or has_pipe or has_bullet or has_letter:
            result.append(stripped)
        elif is_short and re.search(r"\d", stripped):
            result.append(stripped)

    if result:
        return "\n".join(result)
    fallback = content[:2000]
    for marker in ["📋", "⚖️", "🔍", "✅", "📊"]:
        fallback = fallback.replace(marker, "")
    return fallback.strip()


# ══════════════════════════════════════════════════════════════
# List Answer Builder
# ══════════════════════════════════════════════════════════════

def build_list_answer(chunks: list) -> str:
    """
    Build a clean numbered list from raw DB chunks.

    Returns one item per line, numbered — no explanations.
    """
    all_items = []
    source_law = ""

    for chunk in chunks[:5]:
        content = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
        law = chunk.get("law_name", "") if isinstance(chunk, dict) else ""
        if law and not source_law:
            source_law = _short_law(law)

        # Extract numbered/lettered items
        items = re.findall(r"(?:^\s*\d+[\.\-\)ـ]\s*|^\s*[-•●]\s*)([^\n]{4,120})", content, re.MULTILINE)
        for item in items:
            cleaned = item.strip().rstrip(".")
            if cleaned and cleaned not in all_items:
                all_items.append(cleaned)

    if not all_items:
        # Fallback: split content into lines and number them
        raw = chunks[0].get("content", "") if chunks else ""
        lines = [l.strip() for l in raw.split('\n') if l.strip() and len(l.strip()) > 3]
        all_items = lines[:30]

    # Build numbered list
    numbered = []
    for i, item in enumerate(all_items, 1):
        numbered.append(f"{i}- {item}")

    source = ""  # Source hidden from user-facing output
    log.info("[BUILD] list: %d items", len(all_items))
    return "\n".join(numbered) + source


# ══════════════════════════════════════════════════════════════
# Main Entry Point — route to correct builder
# ══════════════════════════════════════════════════════════════

_FORBIDDEN = ["📋", "⚖️", "🔍", "✅", "📊", "التكييف القانوني:", "السند النظامي:", "التحليل القانوني:"]


def build_structured_answer(
    intent: str,
    raw_content: str,
    law_name: str = "",
    target_grade: str = "",
    grade_row: str = "",
    chunks: list = None,
    comparison_rows: list = None,
    comparison_missing: list = None,
    comparison_grades: list = None,
    scope: str = "unspecified",
) -> Optional[str]:
    """
    Main entry. Routes to the correct builder based on intent.

    Returns cleaned, deterministic answer string, or None if can't build.
    ENFORCES hard output contract — no forbidden markers, no raw OCR paragraphs.
    """
    result = None

    if intent == "salary_query":
        # ── Comparison path: 2+ grades ──
        if comparison_rows:
            result = build_salary_comparison(
                rows=comparison_rows,
                law_name=law_name,
                missing=comparison_missing or [],
                grades_requested=comparison_grades or [],
                scope=scope,
            )
        else:
            result = build_salary_answer(
                content=raw_content, law_name=law_name,
                target_grade=target_grade, grade_row=grade_row,
                scope=scope,
            )

    elif intent == "drug_table":
        if chunks:
            result = build_drug_answer(chunks)
        else:
            result = build_drug_answer([{"content": raw_content, "law_name": law_name}])

    elif intent == "table_lookup":
        if chunks:
            result = build_table_answer(chunks)
        else:
            result = build_table_answer([{"content": raw_content, "law_name": law_name}])

    elif intent == "enumeration_list":
        if chunks:
            result = build_list_answer(chunks)
        else:
            result = build_list_answer([{"content": raw_content, "law_name": law_name}])

    else:
        return None  # Not a structured intent

    # ════════════════════════════════════════════════════════════
    # HARD OUTPUT CONTRACT — enforced on EVERY structured answer
    # ════════════════════════════════════════════════════════════
    if result:
        result = _enforce_output_contract(result, intent)

    return result


def _enforce_output_contract(text: str, intent: str) -> str:
    """
    Final hard gate. Strips ALL forbidden markers and blocks raw OCR leaks.
    This runs on every structured answer before it leaves the builder.
    """
    # 1. Strip ALL forbidden markers
    for marker in _FORBIDDEN:
        if marker in text:
            log.warning("[CONTRACT] stripping forbidden marker '%s' from %s answer", marker, intent)
            text = text.replace(marker, "").strip()

    # 2. OCR containment — no single paragraph > 200 chars
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        # Keep source reference lines always
        if stripped.startswith("(المصدر:"):
            cleaned_lines.append(stripped)
            continue
        # Block individual lines > 200 chars (raw OCR paragraphs)
        if len(stripped) > 200:
            log.warning("[CONTRACT] OCR block: line %d chars in %s answer, truncating", len(stripped), intent)
            stripped = stripped[:200].rsplit(" ", 1)[0] + "…"
        cleaned_lines.append(stripped)
    text = "\n".join(cleaned_lines)

    # 3. Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _short_law(law_name: str) -> str:
    """Shorten a law name for source references."""
    if not law_name:
        return ""
    name = law_name.strip()[:80]
    # Remove common prefixes
    for prefix in ["قانون رقم", "القانون رقم", "مرسوم بقانون رقم"]:
        if name.startswith(prefix):
            break
    return name


def _clean_raw_content(content: str, law_name: str = "") -> str:
    """Last resort: clean raw content minimally."""
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    # Drop header-like lines
    lines = [l for l in lines if not l.startswith("📋") and not l.startswith("---")]
    result = "\n".join(lines[:50])
    source = ""  # Source hidden from user-facing output
    return result + source
