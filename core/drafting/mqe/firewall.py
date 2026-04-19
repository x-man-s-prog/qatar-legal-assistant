# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Quality Firewall.

Blocks low-quality paragraphs from reaching the final memo:
  • generic fluff ("ينبغي النظر في الأمر", "يجب تحقيق العدالة")
  • unlinked sentences (no issue + no evidence + no statute)
  • statute dumps with no application
  • vague prayers (handled in prayer.is_vague_prayer, referenced here)
  • inherited blocks from unrelated cases (keywords defined below)
  • raw retrieval residue (scores, chunk_ids, ruling_ids)
  • lecturing tone ("ينبغي على المحكمة أن تعلم...", "من المعلوم لكم...")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.drafting.mqe.prayer import is_vague_prayer


# ═════════════════════════════════════════════════════════════════
# Violation taxonomy
# ═════════════════════════════════════════════════════════════════

VIO_GENERIC_FLUFF            = "generic_fluff"
VIO_UNLINKED_PARAGRAPH       = "unlinked_paragraph"
VIO_STATUTE_DUMP_NO_APP      = "statute_dump_without_application"
VIO_VAGUE_PRAYER             = "vague_prayer"
VIO_INHERITED_BLOCK          = "inherited_cross_case_block"
VIO_RETRIEVAL_RESIDUE        = "retrieval_residue"
VIO_LECTURING_TONE           = "lecturing_tone"
VIO_PREACHY_TONE             = "preachy_tone"
VIO_EMPTY_BULLET             = "empty_bullet"
VIO_DUP_PARAGRAPH            = "duplicate_paragraph"


# ═════════════════════════════════════════════════════════════════
# Pattern banks
# ═════════════════════════════════════════════════════════════════

_FLUFF_PATTERNS = [
    re.compile(r"ينبغي النظر في الأمر"),
    re.compile(r"يجب تحقيق العدالة"),
    re.compile(r"من باب الحرص"),
    re.compile(r"من أجل الصالح العام"),
    re.compile(r"وللعلم فإن"),
    re.compile(r"وتجدر الإشارة إلى أن"),  # only flagged if paragraph is <50 chars
    re.compile(r"كما هو معلوم للجميع"),
]

_LECTURING_PATTERNS = [
    re.compile(r"ينبغي على المحكمة أن تعلم"),
    re.compile(r"من المعلوم لكم"),
    re.compile(r"يجب على المحكمة"),
    re.compile(r"نلفت نظر المحكمة"),
]

_PREACHY_PATTERNS = [
    re.compile(r"إن العدل قيمة سامية"),
    re.compile(r"والعدالة تقتضي"),
    re.compile(r"في هذا الزمان الذي"),
    re.compile(r"انتشار هذه الظاهرة"),
]

_RETRIEVAL_RESIDUE = [
    re.compile(r"chunk_id\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"ruling_id\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"score\s*[:=]\s*[\d.]+", re.IGNORECASE),
    re.compile(r"composite\s*[:=]\s*[\d.]+", re.IGNORECASE),
    re.compile(r"\[TRACE[:].*?\]"),
]

_INHERITED_BLOCKS = [
    "محاضر اجتماعات الشركاء",
    "أقوى ما يدعمك:",
    "أبرز نقطة ضعف لديك:",
    "المسار المتوقع للطرف الآخر:",
    "⚖️ التحليل القضائي:",
    "📊 السيناريوهات المحتملة:",
    "🎯 الدليل الحاسم الذي قد يغيّر القضية:",
]


# ═════════════════════════════════════════════════════════════════
# Report type
# ═════════════════════════════════════════════════════════════════

@dataclass
class FirewallReport:
    violations:          list[str] = field(default_factory=list)
    removed_paragraphs:  int = 0
    flagged_paragraphs:  int = 0
    cleaned_text:        str = ""
    details:             list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "violations":         sorted(set(self.violations))[:10],
            "removed_paragraphs": self.removed_paragraphs,
            "flagged_paragraphs": self.flagged_paragraphs,
            "details":            self.details[:8],
        }


# ═════════════════════════════════════════════════════════════════
# Per-paragraph audit
# ═════════════════════════════════════════════════════════════════

def _is_generic_fluff(para: str) -> bool:
    low = para.strip()
    if len(low) < 30:
        return False
    for pat in _FLUFF_PATTERNS:
        if pat.search(low):
            # Flag only if there's no concrete legal content after it
            if not re.search(r"المادة\s*\d+|قانون|حكم|دليل", low):
                return True
    return False


_NUMBERED_LIST_RE = re.compile(r"^\s*\(\d+\)|\s*\d+[-.)]", re.MULTILINE)

_LEGAL_ANCHORS = (
    "المادة", "قانون", "حكم", "مبدأ", "الثابت", "الوقائع",
    "التكييف", "الدفع", "البينة", "الإثبات", "الاختصاص",
    "الركن", "القصد", "العقد", "الشيك", "العقوبة",
    "الدعوى", "المحكمة", "الطلب", "الاستدلال", "الافتراض",
    "مقدَّمة", "موجز", "المدّعي", "المدّعى عليه", "المتّهم",
    "المستأنف", "المجنيّ", "التقادم", "البطلان", "الصرف",
    "الوفاء", "الضمان", "الركنان", "المسائل", "المسألة",
    "بسبب", "بناءً على",
)


def _is_unlinked(para: str) -> bool:
    """A body paragraph must contain SOME legal or structural anchor."""
    low = para.strip()
    if len(low) < 80:
        return False
    # Headings, lists, and short labels are exempt
    if low.startswith("**") or low.startswith("—") or low.startswith("•"):
        return False
    # Numbered list paragraphs — these are structured blocks
    if _NUMBERED_LIST_RE.search(low):
        return False
    # Any legal anchor present → not unlinked
    if any(anchor in low for anchor in _LEGAL_ANCHORS):
        return False
    # Content without any legal or structural anchor
    return True


def _is_statute_dump(para: str) -> bool:
    """A paragraph that ONLY lists statute refs without applying them."""
    low = para.strip()
    article_hits = len(re.findall(r"المادة\s*\d+", low))
    if article_hits < 2:
        return False
    # If there's application language, it's ok
    if any(t in low for t in ["بتطبيق", "وبإنزال", "ومؤدى ذلك",
                                  "يتبيّن", "ويترتب", "الثابت من",
                                  "بإعمال"]):
        return False
    return True


def _has_retrieval_residue(para: str) -> bool:
    return any(pat.search(para) for pat in _RETRIEVAL_RESIDUE)


def _is_lecturing(para: str) -> bool:
    return any(pat.search(para) for pat in _LECTURING_PATTERNS)


def _is_preachy(para: str) -> bool:
    return any(pat.search(para) for pat in _PREACHY_PATTERNS)


def _has_inherited_block(para: str) -> bool:
    return any(marker in para for marker in _INHERITED_BLOCKS)


def _is_empty_bullet(para: str) -> bool:
    stripped = para.strip()
    return stripped in {"•", "• ", "-", "— ", "*"}


# ═════════════════════════════════════════════════════════════════
# Public audit
# ═════════════════════════════════════════════════════════════════

def audit_memo(text: str) -> FirewallReport:
    """Scan a rendered memo and strip low-quality paragraphs.

    The memo is split by blank-line paragraphs. Each paragraph is tested
    against the rules. Failing paragraphs are removed (and logged).
    """
    report = FirewallReport(cleaned_text=text or "")
    if not text or not text.strip():
        return report

    paras = text.split("\n\n")
    kept: list[str] = []
    seen_signatures: set[str] = set()

    for para in paras:
        p = para.rstrip()
        if not p.strip():
            continue

        # Empty bullet
        if _is_empty_bullet(p):
            report.removed_paragraphs += 1
            report.violations.append(VIO_EMPTY_BULLET)
            continue

        # Duplicate paragraph
        sig = p.strip()[:80]
        if sig and sig in seen_signatures:
            report.removed_paragraphs += 1
            report.violations.append(VIO_DUP_PARAGRAPH)
            continue
        seen_signatures.add(sig)

        # Inherited cross-case boilerplate
        if _has_inherited_block(p):
            report.removed_paragraphs += 1
            report.violations.append(VIO_INHERITED_BLOCK)
            report.details.append(f"inherited:{p[:40]}")
            continue

        # Retrieval residue
        if _has_retrieval_residue(p):
            # Strip the residue tokens but keep the paragraph
            cleaned = p
            for pat in _RETRIEVAL_RESIDUE:
                cleaned = pat.sub("", cleaned)
            cleaned = re.sub(r"  +", " ", cleaned).strip()
            if cleaned:
                kept.append(cleaned)
            report.flagged_paragraphs += 1
            report.violations.append(VIO_RETRIEVAL_RESIDUE)
            continue

        # Generic fluff (only when paragraph has no legal content)
        if _is_generic_fluff(p):
            report.removed_paragraphs += 1
            report.violations.append(VIO_GENERIC_FLUFF)
            continue

        # Lecturing / preachy tone
        if _is_lecturing(p):
            report.flagged_paragraphs += 1
            report.violations.append(VIO_LECTURING_TONE)
            # Rewrite the problematic opener
            p = _LECTURING_PATTERNS[0].sub("نشير إلى أن", p)
            kept.append(p)
            continue
        if _is_preachy(p):
            report.removed_paragraphs += 1
            report.violations.append(VIO_PREACHY_TONE)
            continue

        # Unlinked body paragraph (no legal anchor)
        if _is_unlinked(p):
            report.removed_paragraphs += 1
            report.violations.append(VIO_UNLINKED_PARAGRAPH)
            report.details.append(f"unlinked:{p[:40]}")
            continue

        # Statute dump with no application
        if _is_statute_dump(p):
            report.flagged_paragraphs += 1
            report.violations.append(VIO_STATUTE_DUMP_NO_APP)
            # Keep it but it will cost score
            kept.append(p)
            continue

        # Vague prayer bullets nested inside a bullet list
        if p.lstrip().startswith("•") and is_vague_prayer(p.lstrip("• ").strip()):
            report.removed_paragraphs += 1
            report.violations.append(VIO_VAGUE_PRAYER)
            continue

        kept.append(p)

    cleaned = "\n\n".join(kept).strip()
    report.cleaned_text = cleaned
    return report
