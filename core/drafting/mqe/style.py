# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Arabic Legal Style Refiner.

Removes:
  • robotic repetition ("يُستند إلى X (direct).")
  • role-leakage ("(direct)", "(corroborative)", "(contextual)")
  • double-bullets / empty list items
  • back-to-back identical opening phrases
  • weak hedges ("ربما", "يبدو", "قد يكون") outside conditional scope
  • whitespace rot (triple blank lines, trailing spaces)

Adds:
  • consistent section breaks
  • natural transitions when a hard ". " follows another argument
  • short-sentence pacing (breaks 200+ char sentences at comma joints
    when the clause is genuinely independent)
"""
from __future__ import annotations

import re


# ═════════════════════════════════════════════════════════════════
# Leak scrub patterns
# ═════════════════════════════════════════════════════════════════

_ROLE_LEAKS = [
    re.compile(r"\s*\(\s*direct\s*\)"),
    re.compile(r"\s*\(\s*corroborative\s*\)"),
    re.compile(r"\s*\(\s*contextual\s*\)"),
    re.compile(r"\s*\(\s*supporting\s*\)"),
]

_ROBOTIC_STEMS = [
    re.compile(r"يُستند إلى\s+([^.]+?)\s*\(\s*direct\s*\)"),
    re.compile(r"يُستند إلى\s+([^.]+?)\s*\(\s*corroborative\s*\)"),
    re.compile(r"يُستند إلى\s+([^.]+?)\s*\(\s*contextual\s*\)"),
]

# Arabic word-boundary: Python's \b treats و/ف/ل as word chars, so "ويبدو"
# never triggers \bيبدو\b. Build a custom boundary that allows the common
# Arabic prefixes (و / ف / ل / ب / ك / س) to precede the stem — the prefix
# is captured and preserved in the replacement.
_AR = r"[\u0621-\u064A]"
_PREFIX = r"([وفلبكس]?)"

_WEAK_WORDS = [
    (re.compile(rf"(?<!{_AR}){_PREFIX}ربما(?!{_AR})"),
        r"\1يظهر من الأوراق أن"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}يبدو(?!{_AR})"),
        r"\1يتبيّن"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}قد يكون(?!{_AR})"),
        r"\1يستفاد من الأوراق أنه"),
    (re.compile(rf"(?<!{_AR}){_PREFIX}يمكن أن(?!{_AR})"),
        r"\1يجوز أن"),
]

# Stock phrase de-duplication windows
_OPENER_ECHOES = [
    "من المستقر أن",
    "من الثابت قانوناً أن",
    "ولمّا كان",
    "وبتطبيق ما تقدم",
    "ومؤدى ذلك",
    "ويترتب على ذلك",
]


# ═════════════════════════════════════════════════════════════════
# Core refinement passes
# ═════════════════════════════════════════════════════════════════

def _scrub_role_leaks(text: str) -> str:
    out = text
    # Replace the full "يُستند إلى X (role)." with a natural phrase first
    for pat in _ROBOTIC_STEMS:
        out = pat.sub(r"ويؤيد ذلك \1", out)
    for pat in _ROLE_LEAKS:
        out = pat.sub("", out)
    return out


def _replace_weak_words(text: str, preserve_conditional: bool) -> str:
    """Replace hedge words with firmer phrasing.

    Conditional/alternative paragraphs (detected by markers) are exempt.
    """
    if preserve_conditional and any(
        marker in text
        for marker in ("على سبيل الاحتياط", "احتياطياً", "المسار البديل")
    ):
        return text
    out = text
    for pat, repl in _WEAK_WORDS:
        out = pat.sub(repl, out)
    return out


def _drop_echo_openers(text: str) -> str:
    """When the same opener appears in consecutive paragraphs, vary it."""
    lines = text.split("\n")
    last_opener_seen: dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        for opener in _OPENER_ECHOES:
            if stripped.startswith(opener):
                prev = last_opener_seen.get(opener, -5)
                if i - prev <= 1:
                    # Replace with a softer alternative
                    replacement = {
                        "من المستقر أن":     "ومن المقرر أن",
                        "من الثابت قانوناً أن": "ومن البيّن قانوناً أن",
                        "ولمّا كان":          "وحيث إن",
                        "وبتطبيق ما تقدم":    "وبإنزال ذلك على الوقائع،",
                        "ومؤدى ذلك":         "وينبني على ذلك",
                        "ويترتب على ذلك":    "ومقتضى ذلك",
                    }.get(opener, opener)
                    lines[i] = line.replace(opener, replacement, 1)
                last_opener_seen[opener] = i
    return "\n".join(lines)


_DUPE_SENT_RE = re.compile(r"(?:^|\n)([^\n]{30,})\n\1", re.MULTILINE)


def _dedupe_adjacent_sentences(text: str) -> str:
    """Remove a sentence that is immediately repeated verbatim on the next
    line (a common accidental artifact when multiple issues share text)."""
    prev = None
    iters = 0
    while iters < 3:
        new = _DUPE_SENT_RE.sub(r"\n\1", text)
        if new == text:
            break
        text = new
        iters += 1
    return text


_DUPE_BULLET_RE = re.compile(r"(•\s*[^\n]{5,})\n•\s*\1", re.MULTILINE)


def _dedupe_adjacent_bullets(text: str) -> str:
    for _ in range(3):
        new = _DUPE_BULLET_RE.sub(r"\1", text)
        if new == text:
            return text
        text = new
    return text


def _normalize_whitespace(text: str) -> str:
    # Triple+ newlines → double
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trailing spaces on each line
    text = re.sub(r"[ \t]+(\n|$)", r"\1", text)
    # Multiple spaces mid-line
    text = re.sub(r"  +", " ", text)
    # Arabic punctuation spacing
    text = re.sub(r"\s+([،؛.!؟])", r"\1", text)
    return text.strip()


def _break_overlong_sentences(text: str, max_chars: int = 280) -> str:
    """Soft-break a very long sentence at a natural clause joint."""
    lines = text.split("\n")
    out_lines: list[str] = []
    for line in lines:
        if len(line) <= max_chars:
            out_lines.append(line)
            continue
        # Try to split at a comma + 'و' joint past half-point
        half = len(line) // 2
        idx = line.find("، و", half)
        if idx > 0 and idx < len(line) - 20:
            out_lines.append(line[:idx + 1].rstrip())
            out_lines.append(line[idx + 2:].lstrip())
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


# ═════════════════════════════════════════════════════════════════
# Public entry
# ═════════════════════════════════════════════════════════════════

def refine(text: str, preserve_conditional: bool = True) -> str:
    """Run all style-refinement passes in order."""
    if not text:
        return ""
    t = text
    t = _scrub_role_leaks(t)
    t = _replace_weak_words(t, preserve_conditional=preserve_conditional)
    t = _drop_echo_openers(t)
    t = _dedupe_adjacent_bullets(t)
    t = _dedupe_adjacent_sentences(t)
    t = _break_overlong_sentences(t)
    t = _normalize_whitespace(t)
    return t


# ═════════════════════════════════════════════════════════════════
# Lightweight metrics used by the firewall and scorer
# ═════════════════════════════════════════════════════════════════

def count_weak_words(text: str) -> int:
    return sum(len(pat.findall(text)) for pat, _ in _WEAK_WORDS)


def count_role_leaks(text: str) -> int:
    return sum(len(pat.findall(text)) for pat in _ROLE_LEAKS)


def count_repeated_openers(text: str) -> int:
    count = 0
    prev: str = ""
    for line in text.split("\n"):
        line = line.strip()
        for opener in _OPENER_ECHOES:
            if line.startswith(opener):
                if opener == prev:
                    count += 1
                prev = opener
                break
        else:
            prev = ""
    return count
