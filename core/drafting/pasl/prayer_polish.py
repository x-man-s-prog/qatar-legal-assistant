# -*- coding: utf-8 -*-
"""
PASL — Prayer Polish.

Opens the prayer section with the standard courtroom register
("لذلك، نلتمس الحكم بـ...") and removes redundant filler.

Rules:
  • Never removes a prayer item
  • Never adds a new prayer item
  • Preserves the primary / alternative / fallback structure
"""
from __future__ import annotations

import re


_PRAYER_OPENER = "لذلك، يلتمس الموكّل من عدالة المحكمة الحكم بما يلي:"


def _starts_with_opener(body: str) -> bool:
    low = (body or "").lstrip()
    return (
        low.startswith("لذلك،")
        or low.startswith("لما تقدَّم،")
        or low.startswith("لهذه الأسباب،")
        or low.startswith("يلتمس الموكّل")
    )


_REDUNDANT_INTRO = re.compile(
    r"^(?:يلتمس|نلتمس|نطلب|نرجو)[^\n]{0,60}(?:الحكم|الفصل)[^\n]{0,40}\n",
    re.MULTILINE,
)


def polish_prayer_block(body: str) -> str:
    """Prepend a standard opener if missing. Preserve everything else."""
    if not body or not body.strip():
        return body

    # Drop a redundant hand-rolled intro ("يلتمس الموكّل الحكم بما يلي") if
    # any, since we're inserting the canonical one.
    stripped = _REDUNDANT_INTRO.sub("", body, count=1)

    if _starts_with_opener(stripped):
        return stripped

    return _PRAYER_OPENER + "\n" + stripped.lstrip()


def count_missing_opener(body: str) -> int:
    if not body or not body.strip():
        return 0
    return 0 if _starts_with_opener(body) else 1
