# -*- coding: utf-8 -*-
"""
Response Cleaner V2
====================
Final text cleaner applied AFTER final_decision validation.

Goals:
1. Remove ALL residual memo markers (التكييف/السند/التحليل/التوصية/الثقة)
2. Remove filler openings
3. Compress whitespace
4. Keep natural conversational tone
5. Enforce style based on answer_mode

This replaces the basic post_process_answer from answer_mode.py for
the final cleaning pass.
"""
import re, logging

log = logging.getLogger("response_cleaner")


# ══════════════════════════════════════════════════════════════
# Patterns to strip
# ══════════════════════════════════════════════════════════════

# Memo section headers — all known variants
_MEMO_HEADERS_RE = re.compile(
    r"(?:📋\s*)?(?:التكييف|التكييف القانوني)\s*:?\s*\n?"
    r"|(?:⚖️\s*)?(?:السند|السند القانوني|السند النظامي)\s*:?\s*\n?"
    r"|(?:🔍\s*)?(?:التحليل|التحليل القانوني)\s*:?\s*\n?"
    r"|(?:⚠️\s*)?(?:الاستثناءات|التنبيهات|ملاحظات مهمة)\s*:?\s*\n?"
    r"|(?:✅\s*)?(?:التوصية|التوصيات|التوصية العملية)\s*:?\s*\n?"
    r"|(?:📊\s*)?(?:الثقة|مستوى الثقة|درجة الثقة)\s*:?\s*\d*%?\s*\n?"
)

# Confidence lines (e.g. "📊 الثقة: 85%" or "مستوى الثقة: عالي")
_CONFIDENCE_LINE_RE = re.compile(
    r"(?:📊\s*)?(?:الثقة|مستوى الثقة|درجة الثقة)\s*:?\s*(?:\d{1,3}%?|عالي|متوسط|منخفض)\s*\.?\s*\n?",
    re.MULTILINE
)

# Filler openings that add nothing
_FILLER_STARTS = [
    "بناءً على النصوص القانونية المتوفرة",
    "بعد مراجعة النصوص القانونية",
    "وفق أحكام التشريع القطري",
    "استناداً إلى النصوص القانونية",
    "بحسب النصوص القانونية",
    "حسب ما ورد في النصوص",
    "بالرجوع إلى النصوص القانونية",
    "وفقاً لما ورد في",
    "بناءً على ما تقدم",
]

# Empty section stubs left after stripping headers
_EMPTY_SECTION_RE = re.compile(r"^\s*[-—ـ]+\s*$", re.MULTILINE)


# ══════════════════════════════════════════════════════════════
# Main cleaner
# ══════════════════════════════════════════════════════════════

def clean_response(answer: str, answer_mode: str = "", intent: str = "") -> str:
    """
    Final cleaning pass. Removes memo markers, filler, compresses whitespace.

    For LEGAL_ANALYSIS mode: only removes confidence lines and compresses whitespace.
    For all other modes: aggressive cleaning of memo structure.
    """
    if not answer or not answer.strip():
        return answer

    result = answer

    # ── Always strip confidence lines ──
    result = _CONFIDENCE_LINE_RE.sub("", result)

    # ── For non-analysis modes: strip memo headers ──
    if answer_mode != "legal_analysis":
        result = _MEMO_HEADERS_RE.sub("", result)

        # Strip ALL standalone emoji markers (📋⚖️🔍✅📊) at start of lines
        result = re.sub(r"^\s*[📋⚖️🔍✅📊]\s*", "", result, flags=re.MULTILINE)
        # Strip 📋 prefix when followed by any text (e.g. "📋 من القانون:")
        result = re.sub(r"📋\s*", "", result)

        # Strip filler openings
        stripped = result.lstrip()
        for filler in _FILLER_STARTS:
            if stripped.startswith(filler):
                # Find first comma or period after the filler
                after = stripped[len(filler):]
                cut = -1
                for delim in ("،", ",", ":"):
                    idx = after.find(delim)
                    if 0 <= idx < 40:
                        cut = idx
                        break
                if cut >= 0:
                    result = after[cut + 1:].lstrip()
                    log.info("[CLEAN] stripped filler: '%s'", filler[:30])
                break  # only strip one

    # ── For direct/followup: extra compression ──
    if answer_mode in ("direct_short", "followup_short"):
        # Remove standalone emoji lines
        result = re.sub(r"^\s*[📋⚖️🔍⚠️✅📊]\s*$", "", result, flags=re.MULTILINE)
        # Remove horizontal rules
        result = re.sub(r"^\s*[-═─]{3,}\s*$", "", result, flags=re.MULTILINE)

    # ── For structured_list: ensure clean list format ──
    if answer_mode == "structured_list":
        # Remove paragraphs between list items
        lines = result.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line:
                cleaned_lines.append("")
                continue
            # Keep numbered items and short context
            if re.match(r"^\d+[\.\-\)ـ]", stripped_line):
                cleaned_lines.append(stripped_line)
            elif re.match(r"^[-•●▪]", stripped_line):
                cleaned_lines.append(stripped_line)
            elif re.match(r"^من ", stripped_line) and not stripped_line.startswith("📋"):
                cleaned_lines.append(stripped_line)  # source headers (📋 headers are stripped)
            elif len(stripped_line) < 80:
                cleaned_lines.append(stripped_line)  # short context lines
            # Drop long paragraphs in list mode
        result = "\n".join(cleaned_lines)

    # ── Universal cleanup ──
    result = _EMPTY_SECTION_RE.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r" {2,}", " ", result)
    result = result.strip()

    if result != answer:
        removed = len(answer) - len(result)
        log.info("[CLEAN] removed %d chars, mode=%s intent=%s", removed, answer_mode, intent)

    return result


def clean_for_streaming(chunk: str, answer_mode: str = "") -> str:
    """
    Lightweight per-chunk cleaner for streaming path.
    Only strips memo headers and confidence inline.
    """
    if not chunk:
        return chunk

    if answer_mode in ("direct_short", "table_row", "structured_list", "followup_short"):
        chunk = _MEMO_HEADERS_RE.sub("", chunk)

    # Always strip inline confidence
    chunk = _CONFIDENCE_LINE_RE.sub("", chunk)

    return chunk if chunk.strip() else None
