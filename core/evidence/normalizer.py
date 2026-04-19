# -*- coding: utf-8 -*-
"""
Evidence Normalizer — mandatory cleanup layer.
==============================================

Every raw source (DB row, JSON record, chunk) must pass through the
normalizer before it can become an EvidenceRecord. The normalizer:

  1. Strips OCR noise patterns
  2. Detects fragmented / truncated chunks
  3. Resolves law titles to canonical aliases
  4. Normalizes article numbering (Arabic/Latin digits)
  5. Measures language cleanliness (Arabic char ratio)
  6. Assigns TextQuality
  7. Detects duplicate versions

If the normalizer CANNOT produce a clean record, it returns None with a
rejection reason — NEVER a polluted record.
"""
from __future__ import annotations

import re
import hashlib
from typing import Optional

from core.evidence.contract import (
    EvidenceRecord, SourceType, VerificationStatus, AuthorityRank, TextQuality,
)
from core.evidence.canonical_expanded import get_canonical_registry


# ═════════════════════════════════════════════════════════════════
# Patterns — built once, reused
# ═════════════════════════════════════════════════════════════════

_AR_CHAR = re.compile(r"[\u0600-\u06FF]")
_LATIN_DIGIT = re.compile(r"\d")
_ARABIC_DIGIT = re.compile(r"[\u0660-\u0669]")

_OCR_NOISE_PATTERNS = [
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"),  # control chars
    re.compile(r"[\ufe70-\ufeff]"),                # Arabic presentation forms (noise)
    re.compile(r"\s{4,}"),                          # runaway whitespace
    re.compile(r"\.{5,}"),                          # dots noise
    re.compile(r"[-=]{4,}"),                        # dividers
]

_NAV_NOISE = (
    "إبحث في مواد التشريع", "ملفات متعلقة", "اتصل بنا", "إتصل بنا",
    "almeezan@", "الميزان | البوابة", "الميزان | التشريعات",
)

_LATIN_TO_ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_ARABIC_TO_LATIN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


# ═════════════════════════════════════════════════════════════════
# Article number normalization
# ═════════════════════════════════════════════════════════════════

def normalize_article_number(raw) -> Optional[int]:
    """Convert raw article number (str/int, possibly Arabic digits) to int.

    Returns None if the input is not a valid article number.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    s = str(raw).strip()
    if not s:
        return None
    # Arabic → Latin digits
    s = s.translate(_ARABIC_TO_LATIN_DIGITS)
    # Extract leading digits
    m = re.match(r"^(\d+)", s)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    return None


# ═════════════════════════════════════════════════════════════════
# Text quality assessment
# ═════════════════════════════════════════════════════════════════

def _count_arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    ar = len(_AR_CHAR.findall(text))
    return ar / max(len(text), 1)


def _detect_ocr_noise(text: str) -> bool:
    for pat in _OCR_NOISE_PATTERNS:
        if pat.search(text):
            return True
    return False


def _detect_nav_noise(text: str) -> bool:
    return any(marker in text for marker in _NAV_NOISE)


def _detect_fragmentation(text: str) -> bool:
    """True if text looks truncated / fragmented."""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 40:
        return True
    # Ends mid-sentence without terminal punctuation
    if stripped[-1] not in ".؟!،؛:":
        # Acceptable if ends with Arabic letter + "…" or follows with paragraph
        if len(stripped) < 120 and not stripped.endswith("…"):
            return True
    return False


def assess_text_quality(text: str) -> tuple[TextQuality, float, bool, bool]:
    """
    Return (quality, arabic_ratio, is_fragmented, has_ocr_noise).
    """
    if not text or len(text.strip()) < 20:
        return TextQuality.CORRUPTED, 0.0, True, False

    if _detect_nav_noise(text):
        return TextQuality.CORRUPTED, 0.0, True, True

    ar_ratio = _count_arabic_ratio(text)
    has_ocr = _detect_ocr_noise(text)
    is_frag = _detect_fragmentation(text)

    if ar_ratio < 0.20:
        # mostly non-Arabic content — reject as irrelevant to Arabic legal corpus
        return TextQuality.CORRUPTED, ar_ratio, is_frag, has_ocr

    if has_ocr and ar_ratio < 0.50:
        return TextQuality.NOISY, ar_ratio, is_frag, has_ocr

    if is_frag:
        return TextQuality.MINOR, ar_ratio, True, has_ocr

    if ar_ratio > 0.60 and not has_ocr:
        return TextQuality.CLEAN, ar_ratio, False, False

    return TextQuality.MINOR, ar_ratio, is_frag, has_ocr


# ═════════════════════════════════════════════════════════════════
# Text cleaning (non-destructive — removes only residue)
# ═════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Strip nav noise markers
    for marker in _NAV_NOISE:
        text = text.replace(marker, " ")
    # Collapse runaway whitespace / dots
    for pat in _OCR_NOISE_PATTERNS:
        text = pat.sub(" ", text)
    # Normalize spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ═════════════════════════════════════════════════════════════════
# The normalizer
# ═════════════════════════════════════════════════════════════════

class EvidenceNormalizer:
    """Converts raw inputs into EvidenceRecord, or rejects them."""

    def __init__(self):
        self._registry = get_canonical_registry()

    # ── entry points ──

    def from_db_chunk(self, row: dict) -> tuple[Optional[EvidenceRecord], str]:
        """Normalize a row from the `chunks` table.

        Returns (record, rejection_reason). If record is None, reason
        explains why.
        """
        if not isinstance(row, dict):
            return None, "not_a_dict"

        raw_content = (row.get("content") or "").strip()
        if not raw_content:
            return None, "empty_content"

        # Clean text + assess quality
        content = clean_text(raw_content)
        quality, ar_ratio, is_frag, has_ocr = assess_text_quality(content)
        if quality == TextQuality.CORRUPTED:
            return None, f"text_quality_corrupted:ar_ratio={ar_ratio:.2f}"

        # Resolve law → canonical
        law_title_raw = (row.get("law_name") or "").strip()
        canonical = self._registry.resolve_law(law_title_raw)
        law_title     = canonical.title if canonical else law_title_raw
        canonical_id  = canonical.law_id if canonical else ""
        law_number    = (row.get("law_number") or (canonical.number if canonical else "")).strip() or ""
        law_year      = (row.get("law_year") or (canonical.year if canonical else "")).strip() or ""
        domain        = (row.get("domain") or (canonical.domain.value if canonical else "")).strip() or ""

        # Article number
        article_num = normalize_article_number(row.get("article_number"))

        # Source type inference
        source_label = (row.get("source") or "").strip().lower()
        if source_label in ("attachment", "table"):
            src_type = SourceType.STRUCTURED_TABLE
            authority = AuthorityRank.STRUCTURED_TABLE
        elif canonical is not None:
            src_type = SourceType.STATUTE
            authority = AuthorityRank.STATUTE_IN_FORCE
        else:
            src_type = SourceType.UNKNOWN
            authority = AuthorityRank.UNKNOWN

        # In-force
        in_force = "in_force" if (canonical and canonical.status == "in_force") else "unknown"

        # Verification status will be set by the registry verify step later;
        # here we tentatively mark partial if we matched the law.
        if canonical:
            v_status = VerificationStatus.PARTIAL if article_num is None \
                        else VerificationStatus.VERIFIED \
                        if canonical.article_min <= article_num <= canonical.article_max \
                        else VerificationStatus.UNVERIFIED
        else:
            v_status = VerificationStatus.UNVERIFIED

        # Fingerprint — stable hash for dedup
        fp_src = f"{canonical_id or law_title}|{law_number}|{law_year}|{article_num}|{content[:80]}"
        fingerprint = hashlib.sha1(fp_src.encode("utf-8")).hexdigest()[:16]

        rec = EvidenceRecord(
            source_type         = src_type,
            law_title           = law_title,
            law_number          = law_number,
            law_year            = law_year,
            article_number      = article_num,
            article_text        = content,
            snippet_text        = content[:280],
            domain              = domain,
            canonical_id        = canonical_id,
            authority_rank      = authority,
            verification_status = v_status,
            text_quality        = quality,
            in_force_status     = in_force,
            is_fragmented       = is_frag,
            has_ocr_noise       = has_ocr,
            language_cleanliness = round(ar_ratio, 3),
            source_fingerprint  = fingerprint,
            chunk_id            = row.get("id"),
            full_document_id    = str(row.get("law_id") or ""),
        )
        return rec, ""

    def from_verified_article(self, topic: str, law_title: str,
                                article_num, article_text: str) -> tuple[Optional[EvidenceRecord], str]:
        """Normalize a record from scripts/verified_articles.json.

        These are manually curated and inherently high-trust — but we
        still run the same validations to keep a single code path.
        """
        if not article_text or not article_text.strip():
            return None, "empty_article_text"

        content = clean_text(article_text)
        quality, ar_ratio, is_frag, has_ocr = assess_text_quality(content)
        if quality == TextQuality.CORRUPTED:
            return None, "verified_article_corrupted"

        canonical = self._registry.resolve_law(law_title)
        article_n = normalize_article_number(article_num)

        if canonical is None:
            return None, f"canonical_law_not_found:{law_title[:40]}"

        # Verify article range
        if article_n is not None \
           and not (canonical.article_min <= article_n <= canonical.article_max):
            return None, f"article_out_of_range:{article_n}"

        fp_src = f"{canonical.law_id}|{article_n}|{content[:80]}"
        fingerprint = hashlib.sha1(fp_src.encode("utf-8")).hexdigest()[:16]

        rec = EvidenceRecord(
            source_type         = SourceType.STATUTE,
            law_title           = canonical.title,
            law_number          = canonical.number,
            law_year            = canonical.year,
            article_number      = article_n,
            article_text        = content,
            snippet_text        = content[:280],
            domain              = canonical.domain.value,
            issue_tags          = [topic] if topic else [],
            canonical_id        = canonical.law_id,
            authority_rank      = AuthorityRank.STATUTE_IN_FORCE,
            verification_status = VerificationStatus.VERIFIED,
            text_quality        = quality,
            in_force_status     = "in_force",
            is_fragmented       = is_frag,
            has_ocr_noise       = has_ocr,
            language_cleanliness = round(ar_ratio, 3),
            source_fingerprint  = fingerprint,
            full_document_id    = canonical.law_id,
        )
        return rec, ""

    def from_principle(self, topic: str, principle: dict) -> tuple[Optional[EvidenceRecord], str]:
        """Normalize a record from scripts/principles_index.json."""
        text = (principle.get("text") or "").strip()
        if not text or len(text) < 30:
            return None, "principle_too_short"

        content = clean_text(text)
        quality, ar_ratio, is_frag, has_ocr = assess_text_quality(content)
        if quality == TextQuality.CORRUPTED:
            return None, "principle_corrupted"

        fp_src = f"principle|{topic}|{content[:80]}"
        fingerprint = hashlib.sha1(fp_src.encode("utf-8")).hexdigest()[:16]

        rec = EvidenceRecord(
            source_type         = SourceType.LEGAL_PRINCIPLE,
            law_title           = "مبدأ قضائي مستخلص",
            article_text        = content,
            snippet_text        = content[:280],
            issue_tags          = [topic] if topic else [],
            authority_rank      = AuthorityRank.LEGAL_PRINCIPLE,
            verification_status = VerificationStatus.NOT_REQUIRED,
            text_quality        = quality,
            in_force_status     = "in_force",
            is_fragmented       = is_frag,
            has_ocr_noise       = has_ocr,
            language_cleanliness = round(ar_ratio, 3),
            source_fingerprint  = fingerprint,
        )
        return rec, ""


# ═════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════

_normalizer: Optional[EvidenceNormalizer] = None


def get_normalizer() -> EvidenceNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = EvidenceNormalizer()
    return _normalizer
