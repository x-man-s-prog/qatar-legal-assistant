# -*- coding: utf-8 -*-
"""
Claim Extractor — deterministic extraction of legal claims from draft answer.
Uses regex patterns, not LLM, to extract article refs, penalties, rulings.
"""
import re, logging
from .schemas import (
    ExtractedClaim, ClaimExtractionResult, ClaimType,
)

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Regex patterns for Arabic legal text
# ══════════════════════════════════════════════════════════════

# المادة 173 من قانون الأسرة | م.173 | المادة (173)
_ARTICLE_RE = re.compile(
    r"(?:المادة|الماده|م\.?\s*)\s*\(?(\d{1,4})\)?"
    r"(?:\s*(?:من|في|ب)\s+(?:قانون|القانون|نظام)\s+"
    r"((?:[\u0600-\u06FF]+\s*){1,6}?(?:رقم\s*\d+\s*(?:لسنة\s*\d+)?)?)"
    r")?",
    re.UNICODE
)

# طعن رقم 123/2020 | الطعن 45 لسنة 2019
_RULING_RE = re.compile(
    r"(?:طعن|الطعن|حكم|قرار)\s*(?:رقم)?\s*(\d{1,5})\s*[/ل]\s*(?:سنة\s*)?(\d{4})",
    re.UNICODE
)

# عقوبة الحبس X سنوات | السجن X أشهر | غرامة X ريال
_PENALTY_RE = re.compile(
    r"(?:عقوبة\s+)?(?:الحبس|السجن|الإعدام|الغرامة|غرامة)"
    r"(?:\s+(?:مدة\s+)?(?:لا\s+تقل|لا\s+تزيد|لا\s+تجاوز)?\s*(?:عن\s+)?\s*"
    r"(\d[\d٬,\.]*)\s*(?:سن[وة]ات?|أشهر?|شهور|ريال|دينار))?",
    re.UNICODE
)

# يحق لك | لا يحق | يجب عليك | ملزم | مستحق
_CONCLUSION_RE = re.compile(
    r"((?:يحق|لا\s+يحق|يجوز|لا\s+يجوز|يجب|ملزم|مستحق|يستحق|لا\s+يستحق|تسقط|لا\s+تسقط)"
    r"[^\n\.،]{10,100})",
    re.UNICODE
)

# خلال 30 يوم | مدة X أشهر | قبل انقضاء
_PROCEDURAL_RE = re.compile(
    r"(?:خلال|مدة|قبل\s+انقضاء|في\s+غضون|لا\s+يتجاوز)"
    r"\s*(\d+)\s*(?:يوم|أيام|شهر|أشهر|سنة|سنوات)",
    re.UNICODE
)

# صدر سنة 2004 | رقم 14 لسنة 2004
_FACTUAL_RE = re.compile(
    r"(?:رقم|صدر|لسنة|سنة)\s*\(?(\d{4})\)?",
    re.UNICODE
)


def extract_claims(answer: str) -> ClaimExtractionResult:
    """
    Extract all verifiable legal claims from the answer text.
    Purely deterministic — no LLM calls.
    """
    claims: list[ExtractedClaim] = []
    seen_texts: set[str] = set()

    def _add(text: str, ctype: ClaimType, article: str = None,
             law: str = None, decisive: bool = False):
        text = text.strip()
        if len(text) < 8 or text in seen_texts:
            return
        seen_texts.add(text)
        claims.append(ExtractedClaim(
            text=text, claim_type=ctype,
            article_number=article, law_name=law,
            is_decisive=decisive,
        ))

    # 1. Article references
    for m in _ARTICLE_RE.finditer(answer):
        art_num = m.group(1)
        law_name = (m.group(2) or "").strip()
        _add(m.group(0), ClaimType.ARTICLE_REF,
             article=art_num, law=law_name, decisive=True)

    # 2. Ruling/appeal references
    for m in _RULING_RE.finditer(answer):
        _add(m.group(0), ClaimType.RULING_REF, decisive=True)

    # 3. Penalties
    for m in _PENALTY_RE.finditer(answer):
        _add(m.group(0), ClaimType.PENALTY, decisive=True)

    # 4. Legal conclusions
    for m in _CONCLUSION_RE.finditer(answer):
        _add(m.group(1), ClaimType.LEGAL_CONCLUSION, decisive=True)

    # 5. Procedural claims (deadlines, time limits)
    for m in _PROCEDURAL_RE.finditer(answer):
        _add(m.group(0), ClaimType.PROCEDURAL)

    decisive_count = sum(1 for c in claims if c.is_decisive)
    return ClaimExtractionResult(
        claims=claims,
        total_claims=len(claims),
        decisive_claims=decisive_count,
    )
