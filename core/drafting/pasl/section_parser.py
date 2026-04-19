# -*- coding: utf-8 -*-
"""
PASL — Section Parser.

Splits an MQE memo into typed sections so each PASL pass can target the
right segment without mangling others.

A section is defined by an Arabic-ordinal header like:
    **أولاً — موجز الوقائع ذات الصلة:**

The parser returns:
    header_block  — everything before the first ordinal (document title, meta)
    sections      — list of MemoSegment, each with kind + title + body
    tail_block    — anything after the last section (rarely used)

A kind is inferred from the section title (keyword match). Unknown
sections become kind="unknown" and are passed through untouched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ═════════════════════════════════════════════════════════════════
# Section kinds
# ═════════════════════════════════════════════════════════════════

KIND_PARTIES       = "parties"
KIND_FACTS         = "facts"
KIND_ISSUES        = "issues"
KIND_STATUTE       = "statute"
KIND_APPLICATION   = "application"
KIND_OPPONENT      = "opponent"
KIND_PROOF_BURDEN  = "proof_burden"
KIND_CONCLUSION    = "conclusion"
KIND_PRAYER        = "prayer"
KIND_CONDITIONAL   = "conditional"
KIND_ASSUMPTIONS   = "assumptions"
KIND_REPLY_POINTS  = "reply_points"
KIND_OPPOSING_SUM  = "opposing_summary"
KIND_PROC_DEF      = "procedural_defenses"
KIND_SUBST_DEF     = "substantive_defenses"
KIND_EVID_DEF      = "evidence_defenses"
KIND_UNKNOWN       = "unknown"


_TITLE_KIND_KEYWORDS: list[tuple[str, str]] = [
    ("الأطراف والصفة",              KIND_PARTIES),
    ("موجز الوقائع",                KIND_FACTS),
    ("المسائل القانونية",           KIND_ISSUES),
    ("السند القانوني",              KIND_STATUTE),
    ("التطبيق على الوقائع",         KIND_APPLICATION),
    ("الرد على الدفع المتوقَّع",     KIND_OPPONENT),
    ("الرد على الدفع المتوقع",       KIND_OPPONENT),
    ("عبء الإثبات",                KIND_PROOF_BURDEN),
    ("الخلاصة القانونية",          KIND_CONCLUSION),
    ("الطلبات",                    KIND_PRAYER),
    ("المسار البديل",              KIND_CONDITIONAL),
    ("على سبيل الاحتياط — المسار",  KIND_CONDITIONAL),
    ("افتراضات الصياغة",           KIND_ASSUMPTIONS),
    ("الرد التفصيلي",              KIND_REPLY_POINTS),
    ("موجز دفوع الخصم",            KIND_OPPOSING_SUM),
    ("دفوع إجرائية",               KIND_PROC_DEF),
    ("دفوع موضوعية",               KIND_SUBST_DEF),
    ("دفوع الإثبات",               KIND_EVID_DEF),
]


# Arabic ordinal set — matches the ones MQE emits
_ARABIC_ORDINALS = (
    "أولاً", "ثانياً", "ثالثاً", "رابعاً", "خامساً",
    "سادساً", "سابعاً", "ثامناً", "تاسعاً", "عاشراً",
    "حادي عشر", "ثاني عشر",
)

_HEADER_RE = re.compile(
    r"^\*\*(?:" + "|".join(re.escape(o) for o in _ARABIC_ORDINALS) +
    r")\s*—\s*([^*]+?):\*\*\s*$",
    re.MULTILINE,
)


# ═════════════════════════════════════════════════════════════════
# Data type
# ═════════════════════════════════════════════════════════════════

@dataclass
class MemoSegment:
    kind:     str
    title:    str = ""      # raw Arabic title without ordinal
    header:   str = ""      # the full header line as it was (or "")
    body:     str = ""
    index:    int = 0       # 0-based position inside the memo

    def to_dict(self) -> dict:
        return {
            "kind":  self.kind,
            "title": self.title,
            "index": self.index,
            "body_chars": len(self.body),
        }


@dataclass
class ParsedMemo:
    header_block: str = ""                   # text before first ordinal
    segments:     list[MemoSegment] = field(default_factory=list)
    tail_block:   str = ""                   # text after last section
    original:     str = ""

    def get(self, kind: str) -> MemoSegment | None:
        for seg in self.segments:
            if seg.kind == kind:
                return seg
        return None

    def all_kinds(self) -> list[str]:
        return [s.kind for s in self.segments]

    def body_by_kind(self, kind: str) -> str:
        seg = self.get(kind)
        return seg.body if seg else ""


def _kind_from_title(title: str) -> str:
    title_clean = title.strip().strip("*").strip()
    for kw, kind in _TITLE_KIND_KEYWORDS:
        if kw in title_clean:
            return kind
    return KIND_UNKNOWN


def parse_memo(text: str) -> ParsedMemo:
    """Parse an MQE-composed memo into typed segments."""
    if not text or not text.strip():
        return ParsedMemo(original=text or "")

    headers = list(_HEADER_RE.finditer(text))
    if not headers:
        # No Arabic-ordinal headers found — treat the whole thing as one UNKNOWN.
        return ParsedMemo(
            original=text,
            header_block=text,
            segments=[],
        )

    parsed = ParsedMemo(original=text)

    # Header block = everything before the first ordinal header
    parsed.header_block = text[: headers[0].start()].rstrip()

    for i, match in enumerate(headers):
        title = match.group(1).strip()
        start_body = match.end()
        end_body = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start_body:end_body].strip("\n")
        seg = MemoSegment(
            kind=_kind_from_title(title),
            title=title,
            header=text[match.start():match.end()],
            body=body.rstrip(),
            index=i,
        )
        parsed.segments.append(seg)

    return parsed


def rebuild_memo(parsed: ParsedMemo) -> str:
    """Re-assemble a ParsedMemo back into a string — preserves original order.

    Format convention: one blank line BETWEEN sections; a single newline
    between a header and its body.
    """
    blocks: list[str] = []
    if parsed.header_block and parsed.header_block.strip():
        blocks.append(parsed.header_block.rstrip())
    for seg in parsed.segments:
        body = (seg.body or "").strip("\n")
        if seg.header and body:
            # Header + body as ONE block (single \n between them)
            blocks.append(seg.header.rstrip() + "\n\n" + body)
        elif seg.header:
            blocks.append(seg.header.rstrip())
        elif body:
            blocks.append(body)
    if parsed.tail_block and parsed.tail_block.strip():
        blocks.append(parsed.tail_block.rstrip())
    return ("\n\n".join(blocks)).rstrip() + "\n"


# ═════════════════════════════════════════════════════════════════
# Invariant checkers — used before/after every PASL pass
# ═════════════════════════════════════════════════════════════════

def section_count(text: str) -> int:
    return len(_HEADER_RE.findall(text))


def citation_count(text: str) -> int:
    """Rough count of citation markers (preserving them is a hard invariant)."""
    return (
        len(re.findall(r"حكم قضائي", text))
        + len(re.findall(r"المادة\s*\d+", text))
        + len(re.findall(r"مبدأ قضائي", text))
    )


def fact_bullet_count(text: str) -> int:
    """Count '(n)' numbered facts to make sure none are dropped."""
    return len(re.findall(r"(?:^|\n)\s*\(\d+\)", text))
