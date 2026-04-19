# -*- coding: utf-8 -*-
"""
PASL — Anti-Pattern Breaker.

Prevents the AI-rhythm signature of every paragraph starting with the
same Arabic opener ("من المستقر أن" × 6). Detects repetition of
paragraph openers in a window and rotates them into a wider bank.

Does NOT rewrite paragraph CONTENT. Only swaps the 1–3 leading
connective words when a repeat is detected within 3 consecutive
paragraphs of the same section.
"""
from __future__ import annotations

import re


# Wider bank of functionally equivalent openers
_OPENER_BANK = [
    "من المستقر أن",
    "ومن المقرر أن",
    "ومن البيِّن قانوناً أن",
    "والثابت أن",
    "ولقد استقر القضاء على أن",
    "ومقتضى ذلك أن",
    "والقاعدة القانونية تقضي بأن",
]


_APPLICATION_OPENERS = [
    "وبتطبيق ما تقدَّم على وقائع النزاع، ",
    "وبإنزال هذه القاعدة على الوقائع الثابتة، ",
    "وبإعمال هذا المبدأ على واقعة الحال، ",
    "ولمّا كان الثابت من الأوراق أن ",
    "وبإنزال ذلك على ما ثبت من الأوراق، ",
]


_CONSEQUENCE_OPENERS = [
    "ومؤدى ذلك",
    "ويترتب على ذلك",
    "ومقتضى ذلك",
    "وعليه فإنه",
    "وينبني على ذلك",
    "فإنه يلزم من ذلك",
]


_ALL_BANKS = [_OPENER_BANK, _APPLICATION_OPENERS, _CONSEQUENCE_OPENERS]


def _find_bank_for(line: str) -> tuple[list[str], str] | None:
    low = line.lstrip()
    for bank in _ALL_BANKS:
        for phrase in bank:
            if low.startswith(phrase.rstrip()):
                return bank, phrase.rstrip()
    return None


def break_opener_patterns(body: str) -> str:
    """Walk paragraph-leading openers; when two neighbors match, rotate
    the second to a different member of the same bank."""
    if not body:
        return ""
    paragraphs = body.split("\n\n")
    # Track the last bank-phrase seen in a NON-structural paragraph
    last_phrase: str | None = None
    last_bank: list[str] | None = None

    # We also track the TRAILING opener inside a paragraph (when argument
    # consequence phrase appears on its own line) — handled below.

    for pi, para in enumerate(paragraphs):
        lines = para.split("\n")
        for li, line in enumerate(lines):
            stripped = line.lstrip()
            # Skip structural lines entirely
            if stripped.startswith(("**", "•", "—", "(")) \
                    or re.match(r"^\d+[\-.)]", stripped):
                continue
            match = _find_bank_for(line)
            if match is None:
                continue
            bank, phrase = match
            if last_bank is bank and phrase == last_phrase:
                # Pick the NEXT phrase in the same bank
                alt_idx = (bank.index(phrase) + 1 + pi) % len(bank)
                alt = bank[alt_idx]
                # Preserve any و/ف prefix on the line and the body
                # (line starts directly with phrase)
                new_line = alt + line[len(phrase):]
                lines[li] = new_line
                phrase = alt
            last_phrase = phrase
            last_bank = bank
        paragraphs[pi] = "\n".join(lines)

    return "\n\n".join(paragraphs)


def count_repeated_openers(body: str) -> int:
    """How many paragraphs open with the SAME phrase as the previous one."""
    if not body:
        return 0
    paragraphs = body.split("\n\n")
    last_phrase: str | None = None
    last_bank: list[str] | None = None
    count = 0
    for para in paragraphs:
        for line in para.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith(("**", "•", "—", "(")) \
                    or re.match(r"^\d+[\-.)]", stripped):
                continue
            match = _find_bank_for(line)
            if match is None:
                continue
            bank, phrase = match
            if last_bank is bank and phrase == last_phrase:
                count += 1
            last_phrase = phrase
            last_bank = bank
            break
    return count
