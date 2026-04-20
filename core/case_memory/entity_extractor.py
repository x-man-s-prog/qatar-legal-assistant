# -*- coding: utf-8 -*-
"""
core/case_memory/entity_extractor.py — closed-vocabulary entity tagging.

Extracts three tag families from a raw query string:

  • role_*    — actor roles (موظف, زوج, مستأجر, …)
  • action_*  — action verbs (اعترف, فصل, طلّق, …)
  • money_*   — money amount bucket (small / medium / large / huge)

Design rules (strict)
---------------------
- **Closed vocabularies only.** No fuzzy matching, no ML, no regex that
  invents tags. If the text doesn't hit a vocab entry, it doesn't
  produce a tag.
- Extraction is a pure function of the query string.
- Returned list is **sorted and de-duplicated** so that downstream
  ``CaseSignature.hash`` is deterministic regardless of match order.
- Empty input or no matches → empty list (not None).

Arabic-aware word boundaries
----------------------------
``phrase in text`` is WRONG — "موظف" would match the prefix of
"الموظفين". We use ``_match_word`` which anchors on non-Arabic-letter
boundaries (start-of-string, punctuation, ASCII, space).

Vocabulary expansion is out-of-scope for this session. Adding terms to
the ROLE/ACTION vocab requires a separate FINDING + commit.

Status: CP2 · Part B. Implementation live; cm7-cm10 exercise it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


# ─────────────────────────────────────────────────────────────────
# ROLE vocabulary — who is the user/client/subject?
# ─────────────────────────────────────────────────────────────────
# Matching rules:
#   • normalised (see _normalize_ar) before comparison
#   • whole-word match via _match_word — "موظف" matches "موظف"
#     but NOT "موظفين"
#   • first match wins if multiple phrases overlap

_ROLE_VOCAB: Dict[str, str] = {
    # Employment
    "موظف": "role_employee",
    "موظفة": "role_employee",
    "عامل": "role_worker",
    "عاملة": "role_worker",
    "صاحب الشركة": "role_employer",
    "صاحب العمل": "role_employer",
    "رب العمل": "role_employer",

    # Self-reference
    "موكلي": "role_self_client",
    "موكلتي": "role_self_client",
    "موكّلي": "role_self_client",

    # Family
    "زوجة": "role_wife",
    "زوجتي": "role_wife",
    "زوج": "role_husband",
    "زوجي": "role_husband",
    "أب": "role_father",
    "والد": "role_father",
    "أم": "role_mother",
    "والدة": "role_mother",
    "ابن": "role_son",
    "ابنة": "role_daughter",
    "طفل": "role_child",
    "طفلة": "role_child",

    # Real estate
    "مستأجر": "role_tenant",
    "مستأجرة": "role_tenant",
    "مؤجر": "role_landlord",
    "مالك العقار": "role_landlord",

    # Commerce
    "بائع": "role_seller",
    "مشتري": "role_buyer",
    "المشتري": "role_buyer",

    # Crime
    "متهم": "role_accused",
    "المتهم": "role_accused",
    "مجني عليه": "role_victim",
    "الضحية": "role_victim",
    "شاهد": "role_witness",
}


# ─────────────────────────────────────────────────────────────────
# ACTION vocabulary — what happened?
# ─────────────────────────────────────────────────────────────────

_ACTION_VOCAB: Dict[str, str] = {
    # Theft / fraud
    "سرق": "action_theft",
    "سرقت": "action_theft",
    "سرقوا": "action_theft",
    "احتال": "action_fraud",
    "اختلس": "action_embezzlement",
    "اختلست": "action_embezzlement",

    # Confession / denial
    "اعترف": "action_confession",
    "اعترفت": "action_confession",
    "أقرّ": "action_confession",
    "أنكر": "action_denial",
    "أنكرت": "action_denial",

    # Employment
    "فصل": "action_termination",
    "فُصل": "action_termination",
    "فصلت": "action_termination",
    "استقال": "action_resignation",
    "استقالت": "action_resignation",

    # Family
    "طلّق": "action_divorce",
    "طلق": "action_divorce",
    "طلقها": "action_divorce",
    "تزوج": "action_marriage",

    # Contracts
    "فسخ": "action_contract_cancellation",
    "فسخت": "action_contract_cancellation",
    "أخلّ": "action_breach",
    "أخل": "action_breach",

    # Physical / violent
    "اعتدى": "action_assault",
    "ضرب": "action_assault",
    "قتل": "action_homicide",
    "جرح": "action_injury",

    # Prior record
    "سابقة": "action_prior_record",
    "سوابق": "action_prior_record",
    "عاد": "action_recidivism",
    "عاود": "action_recidivism",
}


# ─────────────────────────────────────────────────────────────────
# MONEY extraction — regex + bucketing
# ─────────────────────────────────────────────────────────────────

_MONEY_PATTERN: re.Pattern = re.compile(
    r"(\d+(?:[\.,]\d+)?)\s*(ألف|آلاف|مليون|ملايين|ريال|دينار|درهم|ل\.س|د\.ك)?",
    re.UNICODE,
)

_MULTIPLIERS: Dict[str, int] = {
    "ألف": 1_000,
    "آلاف": 1_000,
    "مليون": 1_000_000,
    "ملايين": 1_000_000,
}

_MONEY_BUCKETS: List[Tuple[Tuple[float, float], str]] = [
    ((0, 10_000), "money_small"),
    ((10_000, 100_000), "money_medium"),
    ((100_000, 1_000_000), "money_large"),
    ((1_000_000, float("inf")), "money_huge"),
]


# ─────────────────────────────────────────────────────────────────
# Arabic normalisation & whole-word matching
# ─────────────────────────────────────────────────────────────────

_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")  # tashkeel
_ALEF_VARIANTS = re.compile(r"[أإآٱ]")
_YA_VARIANTS = re.compile(r"[ىئ]")


def _normalize_ar(text: str) -> str:
    """Remove tashkeel, unify alef/ya variants. Idempotent."""
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _ALEF_VARIANTS.sub("ا", text)
    text = _YA_VARIANTS.sub("ي", text)
    return text


def _match_word(phrase: str, text: str) -> bool:
    """Whole-word match with Arabic-aware boundaries.

    Matches ``phrase`` only when bounded by non-Arabic-letter characters
    (start-of-string, end-of-string, space, ASCII punctuation, digits).

    An **optional Arabic definite article** (``ال``) is permitted between
    the boundary and the phrase — so ``موظف`` in the vocab matches both
    ``موظف`` and ``الموظف`` in the text. This is safe: vocab entries that
    already include ``ال`` (e.g. ``المتهم``) still match as before, because
    the ``(?:ال)?`` group is optional, and we never have substring-only
    entries that could be confused by adjacent letters (lookahead still
    requires a non-Arabic-letter after the phrase).

    Rationale lives here instead of duplicating ``ال``-prefixed copies in
    the vocab — that would have doubled the vocab size for zero semantic
    gain, and ``user prompt rule #1`` forbade adding vocabulary entries.

    Both inputs are expected pre-normalised.
    """
    pattern = (
        rf"(?:^|[^\u0600-\u06FF])"
        rf"(?:ال)?"
        rf"{re.escape(phrase)}"
        rf"(?=$|[^\u0600-\u06FF])"
    )
    return re.search(pattern, text) is not None


# ─────────────────────────────────────────────────────────────────
# Money extraction
# ─────────────────────────────────────────────────────────────────

def _extract_money_tags(text: str) -> Set[str]:
    """Scan ``text`` for money amounts and return their bucket tags.

    Uses the **original** (un-normalised) text — digits are untouched
    by normalisation, and we want to preserve unit words verbatim.
    """
    tags: Set[str] = set()

    for match in _MONEY_PATTERN.finditer(text):
        raw_num = match.group(1).replace(",", "").replace(".", "")
        try:
            amount = float(raw_num)
        except ValueError:
            continue

        unit = (match.group(2) or "").strip()
        multiplier = _MULTIPLIERS.get(unit, 1)
        total = amount * multiplier

        for (lo, hi), tag in _MONEY_BUCKETS:
            if lo <= total < hi:
                tags.add(tag)
                break

    return tags


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def extract_entity_tags(text: str) -> List[str]:
    """Extract a sorted, de-duplicated list of entity tags from ``text``.

    Returns
    -------
    list[str]
        Sorted (ASCII lex order) and unique. Empty if no matches.
    """
    if not text:
        return []

    normalised = _normalize_ar(text)
    tags: Set[str] = set()

    for phrase, tag in _ROLE_VOCAB.items():
        norm_phrase = _normalize_ar(phrase)
        if _match_word(norm_phrase, normalised):
            tags.add(tag)

    for phrase, tag in _ACTION_VOCAB.items():
        norm_phrase = _normalize_ar(phrase)
        if _match_word(norm_phrase, normalised):
            tags.add(tag)

    # Money extracted from ORIGINAL text (digits immune to normalisation).
    tags.update(_extract_money_tags(text))

    return sorted(tags)


__all__ = ["extract_entity_tags"]
