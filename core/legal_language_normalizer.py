# -*- coding: utf-8 -*-
"""
core/legal_language_normalizer.py — map dialect/colloquial → legal.

WHY THIS EXISTS
===============
Qatari users don't write in formal legal Arabic. A real client walks
into a lawyer's office and says:
  "طفشني صاحب العمل" (he fired me)
  "حرمتي ناشز" (my wife is disobedient)
  "شيك طاير" (a bounced cheque)
  "ودخت فلوسي" (he wasted my money)
  "يبزني" (he is extorting me)

The fact_extractor's LLM handles many of these naturally but retrieval
— which is keyword-based on the DB's formal Arabic — MISSES them.
Result: the user types dialect, the DB is searched with dialect,
nothing matches, retrieval returns random chunks.

CP8 Layer 3 normalizes the user's text BEFORE retrieval to a formal
Arabic equivalent that matches the statute/cassation database.

NORMALIZATION MAP
=================
Hand-curated (plus LLM fallback for unrecognized patterns). Each
entry: {dialect/colloquial → formal legal term}.

Scope:
  • Labor — "طفش / طشر / رفت / فصخ العقد" → "فصل / إنهاء عقد العمل"
  • Family — "حرمتي / المرا" → "الزوجة", "طليقتي / مطلقتي / طلقتها"
            → "المطلقة"
  • Criminal — "شيك طاير" → "شيك بدون رصيد", "سرق أغراضي" → "السرقة",
               "ضربني" → "الاعتداء بالضرب"
  • Commercial — "نصبني" → "الاحتيال", "شركه فلست" → "إشهار الإفلاس"
  • Traffic — "سحبت رخصتي" → "سحب رخصة القيادة"
  • Interrogatives — "وش/ايش" → "ماذا", "كم" stays

The normalizer RETURNS BOTH:
  • normalized text (for retrieval + keyword extraction)
  • original text preserved (for user-facing output — we never
    "correct" the user)

This means: retrieval/keyword search uses formal terms, but the
memo still quotes the user's actual words in الوقائع.

ALSO provides:
  • Synonym sets for legal concept matching (LLM-free)
  • Anti-normalization for formal-to-colloquial translation in
    responses (not used yet, scheduled for CP9)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# Dialect / Colloquial → Formal legal Arabic
# ═══════════════════════════════════════════════════════════════════

# Word-level substitutions. Order matters (longer phrases first).
_DIALECT_MAP: tuple[tuple[str, str], ...] = (
    # ── Labor ────────────────────────────────────────────────
    ("طفشني صاحب العمل",        "فصلني صاحب العمل"),
    ("طفشني",                   "فصلني"),
    ("طفش من الشغل",            "فصل من العمل"),
    ("طشر",                     "فصل"),
    ("رفت",                     "فصل"),
    ("فصخ العقد",               "أنهى العقد"),
    ("طردوني",                  "فصلوني"),
    ("الشغل",                   "العمل"),
    ("الراتب",                  "الأجر"),
    ("صاحب العمل",              "صاحب العمل"),   # keep
    ("صاحب الشغل",              "صاحب العمل"),
    ("شغلت عنده",               "عملت لديه"),

    # ── Family ────────────────────────────────────────────────
    ("حرمتي",                   "زوجتي"),
    ("مرتي",                    "زوجتي"),
    ("المرا",                   "الزوجة"),
    ("طليقتي",                  "مطلقتي"),
    ("طلقتها",                  "طلقت زوجتي"),
    ("وليدي",                   "ابني"),
    ("عيالي",                   "أولادي"),
    ("الجهال",                  "الأطفال"),

    # ── Criminal ──────────────────────────────────────────────
    ("شيك طاير",                "شيك بدون رصيد"),
    ("شيك راجع",                "شيك بدون رصيد"),
    ("شيك ضرب",                 "شيك بدون رصيد"),
    ("شيك ماله رصيد",           "شيك بدون رصيد"),
    ("نصبني",                   "احتال علي"),
    ("ناصبني",                  "احتال علي"),
    ("يبزني",                   "يبتزني"),
    ("ضربني",                   "اعتدى علي بالضرب"),
    ("شتمني",                   "قذفني / سبني"),
    ("سب وقذف",                 "سب وقذف"),
    ("سرق أغراضي",              "سرق ممتلكاتي"),
    ("مخدر",                    "مواد مخدرة"),
    ("حشيش",                    "حشيش (مواد مخدرة)"),
    ("هددني",                   "هددني بالتهديد الإجرامي"),

    # ── Commercial ────────────────────────────────────────────
    ("شركه فلست",               "إشهار إفلاس الشركة"),
    ("فلست الشركه",             "أُشهر إفلاس الشركة"),
    ("دفاتر الشركه",            "السجلات التجارية"),

    # ── Traffic ───────────────────────────────────────────────
    ("سحبت رخصتي",              "سحبت رخصة القيادة"),
    ("رخصه",                    "رخصة"),
    ("غرامه",                   "غرامة"),

    # ── Rental / Real Estate ─────────────────────────────────
    ("مؤجر",                    "المؤجر"),
    ("البناء",                  "العقار"),
    ("بنايه",                   "عقار"),

    # ── Interrogatives & Grammar (commonly used) ─────────────
    ("وش",                      "ماذا"),
    ("ايش",                     "ماذا"),
    ("شنو",                     "ماذا"),
    ("شلون",                    "كيف"),
    ("ليش",                     "لماذا"),
    ("هالشي",                   "هذا الأمر"),
    ("هالموضوع",                "هذا الموضوع"),
)


# Synonym groups for legal concept matching. Each set is a
# synonymy — any member maps to the canonical form.
_LEGAL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "الفصل التعسفي": (
        "فصل تعسفي", "إنهاء تعسفي", "فصل بغير مبرر",
        "إنهاء العقد تعسفياً", "إنهاء غير مشروع",
    ),
    "الخلع": (
        "خلع", "الخلع القضائي", "التفريق بالخلع", "خلع بعوض",
    ),
    "التطليق للضرر": (
        "طلاق للضرر", "تطليق للضرر", "طلاق لوقوع ضرر",
        "فسخ للضرر", "التفريق للضرر",
    ),
    "إسقاط الحضانة": (
        "إسقاط الحضانة", "سقوط الحضانة", "رفع الحضانة",
        "نقل الحضانة", "ضم المحضون", "نزع الحضانة",
    ),
    "شيك بدون رصيد": (
        "شيك بدون رصيد", "شيك بلا رصيد", "شيك مرتجع",
        "إصدار شيك بلا رصيد", "مخالفة شيكية",
    ),
    "الاحتيال": (
        "احتيال", "نصب", "خداع", "غش", "جريمة الاحتيال",
    ),
    "الاعتداء بالضرب": (
        "اعتداء بالضرب", "ضرب", "جريمة الضرب", "إيذاء بدني",
        "ضرب أفضى", "إحداث عاهة",
    ),
    "السرقة": (
        "سرقة", "جريمة السرقة", "اختلاس", "استيلاء",
    ),
    "التزوير": (
        "تزوير", "جريمة التزوير", "تزوير محرر",
        "تزوير محرر رسمي", "تزوير محرر عرفي",
    ),
    "التشهير": (
        "تشهير", "سب", "قذف", "إساءة", "جريمة قذف",
        "جريمة سب", "ذم وقدح",
    ),
    "الابتزاز": (
        "ابتزاز", "تهديد", "جريمة ابتزاز", "التهديد الإجرامي",
    ),
    "النفقة الزوجية": (
        "نفقة زوجة", "نفقة زوجية", "إلزام بالنفقة", "نفقة مستحقة",
    ),
    "نفقة الأولاد": (
        "نفقة أبناء", "نفقة أولاد", "نفقة المحضونين", "نفقة الأطفال",
    ),
    "الإيجار السكني": (
        "إيجار سكني", "إجارة سكنية", "عقد إيجار سكن",
    ),
    "إخلاء العين المؤجرة": (
        "إخلاء مأجور", "إخلاء العين المؤجرة", "إنهاء عقد الإيجار",
    ),
}


@dataclass
class NormalizedQuery:
    """Result of normalizing a user query."""
    original:           str
    normalized:         str
    substitutions_made: list[tuple[str, str]]
    canonical_concepts: list[str]


def normalize_query(query: str) -> NormalizedQuery:
    """Apply dialect→formal substitutions + identify canonical concepts.

    Returns both the original (for display) and normalized (for
    retrieval). Pure function. No side effects.
    """
    if not query:
        return NormalizedQuery(original="", normalized="", substitutions_made=[], canonical_concepts=[])

    normalized = query
    subs: list[tuple[str, str]] = []

    # Apply dialect substitutions (longer first to avoid partial hits)
    ordered = sorted(_DIALECT_MAP, key=lambda p: -len(p[0]))
    for dialect, formal in ordered:
        if dialect in normalized and dialect != formal:
            normalized = normalized.replace(dialect, formal)
            subs.append((dialect, formal))

    # Identify canonical concepts present
    canonical: list[str] = []
    q_lower = normalized.lower()
    for canonical_term, variants in _LEGAL_SYNONYMS.items():
        if any(v in q_lower for v in variants):
            canonical.append(canonical_term)

    return NormalizedQuery(
        original           = query,
        normalized         = normalized,
        substitutions_made = subs,
        canonical_concepts = canonical,
    )


def expand_keywords_with_synonyms(keywords: list[str]) -> list[str]:
    """Given extracted keywords, expand with known synonyms.

    Used to broaden retrieval when the DB uses a different term
    than the user. Deduplicates. Pure function.
    """
    out: list[str] = []
    seen: set[str] = set()
    for k in keywords or []:
        k = k.strip()
        if not k or k in seen:
            continue
        out.append(k)
        seen.add(k)
        # Look up synonyms
        for canonical, variants in _LEGAL_SYNONYMS.items():
            if k in variants or k == canonical:
                for v in (canonical,) + variants:
                    if v not in seen:
                        out.append(v)
                        seen.add(v)
    return out


def get_concept_canonical(term: str) -> Optional[str]:
    """Return the canonical form of a legal concept, or None if unknown."""
    if not term:
        return None
    t = term.strip()
    for canonical, variants in _LEGAL_SYNONYMS.items():
        if t == canonical or t in variants:
            return canonical
    return None


__all__ = [
    "NormalizedQuery",
    "normalize_query",
    "expand_keywords_with_synonyms",
    "get_concept_canonical",
]
