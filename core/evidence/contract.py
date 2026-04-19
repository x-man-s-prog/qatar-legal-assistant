# -*- coding: utf-8 -*-
"""
Evidence Contract — the single truth about what legal evidence looks like.

Every piece of information that enters the reasoning pipeline MUST be
expressible as a validated EvidenceRecord. Raw DB rows / raw JSON /
ad-hoc dicts are NOT acceptable. The normalizer converts inputs into
this shape or rejects them.

Design rule: if a retrieval result cannot be turned into a clean
EvidenceRecord, it never reaches reasoning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# Enums — type-safe classification
# ═════════════════════════════════════════════════════════════════

class SourceType(str, Enum):
    """What kind of legal source this is."""
    STATUTE              = "statute"                # قانون / مادة
    REGULATION           = "regulation"             # قرار / لائحة
    CASE_LAW             = "case_law"               # حكم تمييز
    LEGAL_PRINCIPLE      = "legal_principle"        # مبدأ قضائي مستخلص
    OFFICIAL_EXPLANATION = "official_explanation"   # تفسير رسمي / مذكرة إيضاحية
    STRUCTURED_TABLE     = "structured_table"       # جدول / مرفق رقمي
    UNKNOWN              = "unknown"


class VerificationStatus(str, Enum):
    """Result of canonical verification."""
    VERIFIED        = "verified"         # law + article + domain all match
    PARTIAL         = "partial"          # law matches, article not verified
    UNVERIFIED      = "unverified"       # failed canonical match
    REJECTED        = "rejected"         # failed validation — cannot be used
    NOT_REQUIRED    = "not_required"     # e.g. structured_table needs no article check


class AuthorityRank(int, Enum):
    """Numerical priority — higher wins in relevance tie-breaks.

    STATUTE_IN_FORCE  = 100  (top authority — cited as positive law)
    REGULATION        = 80   (subordinate to statute but binding)
    CASE_LAW_TAMYIZ   = 70   (binding interpretation)
    LEGAL_PRINCIPLE   = 55   (extracted from rulings — supportive)
    OFFICIAL_EXPLAIN  = 40   (explanatory, non-binding)
    STRUCTURED_TABLE  = 30   (reference data only)
    UNKNOWN           = 10
    """
    STATUTE_IN_FORCE  = 100
    REGULATION        = 80
    CASE_LAW_TAMYIZ   = 70
    LEGAL_PRINCIPLE   = 55
    OFFICIAL_EXPLAIN  = 40
    STRUCTURED_TABLE  = 30
    UNKNOWN           = 10


class TextQuality(str, Enum):
    """Text-integrity classification."""
    CLEAN      = "clean"         # no OCR noise, no fragments
    MINOR      = "minor"         # minor whitespace/Unicode issues
    NOISY      = "noisy"         # OCR artefacts but readable
    CORRUPTED  = "corrupted"     # unreadable — must be rejected


# ═════════════════════════════════════════════════════════════════
# Core record
# ═════════════════════════════════════════════════════════════════

@dataclass
class EvidenceRecord:
    """A single piece of verified legal evidence.

    Fields grouped by purpose:
      - identity: source_type, law_title, law_number, law_year, article_number
      - content: article_text, snippet_text
      - routing: domain, subdomain, issue_tags, remedy_tags, procedural_tags
      - trust:   canonical_id, authority_rank, verification_status,
                 text_quality, in_force_status, is_fragmented, has_ocr_noise
      - scoring: relevance_score, score_breakdown
      - internal: chunk_id, full_document_id, version_info
    """

    # ── identity ──
    source_type:    SourceType          = SourceType.UNKNOWN
    law_title:      str                 = ""
    law_number:     str                 = ""
    law_year:       str                 = ""
    article_number: Optional[int]       = None

    # ── content ──
    article_text:   str                 = ""
    snippet_text:   str                 = ""   # shorter formatted version for UI

    # ── routing / labels ──
    domain:              str            = ""
    subdomain:           str            = ""
    issue_tags:          list[str]      = field(default_factory=list)
    remedy_tags:         list[str]      = field(default_factory=list)
    procedural_tags:     list[str]      = field(default_factory=list)

    # ── trust / verification ──
    canonical_id:        str            = ""
    authority_rank:      AuthorityRank  = AuthorityRank.UNKNOWN
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    text_quality:        TextQuality    = TextQuality.CLEAN
    in_force_status:     str            = "unknown"    # in_force | amended | repealed | unknown
    is_fragmented:       bool           = False
    has_ocr_noise:       bool           = False
    language_cleanliness: float         = 1.0          # 0..1, Arabic ratio after cleaning

    # ── scoring (set by adjudicator) ──
    relevance_score:     float          = 0.0
    score_breakdown:     dict           = field(default_factory=dict)
    rejection_reason:    str            = ""

    # ── source traceability ──
    source_url:          str            = ""
    source_fingerprint:  str            = ""    # hash or unique identifier

    # ── internal ids (NEVER leaked to user) ──
    chunk_id:            Optional[int]  = None
    full_document_id:    str            = ""
    version_info:        str            = ""

    # ── temporal ──
    date_if_relevant:    str            = ""

    # ── case law identity (for CASE_LAW / LEGAL_PRINCIPLE records) ──
    ruling_id:           str            = ""
    chamber:             str            = ""
    principle_topic:     str            = ""

    # ── constraints ──
    def is_usable(self) -> bool:
        """True if this record can participate in reasoning."""
        if self.verification_status in (VerificationStatus.REJECTED,
                                          VerificationStatus.UNVERIFIED):
            return False
        if self.text_quality == TextQuality.CORRUPTED:
            return False
        if not self.article_text and not self.snippet_text:
            return False
        return True

    def is_statute(self) -> bool:
        return self.source_type == SourceType.STATUTE

    def public_citation(self) -> str:
        """Safe user-facing citation string — never includes internal ids."""
        parts = []
        if self.law_title:
            parts.append(self.law_title)
        if self.law_number and self.law_year:
            parts.append(f"رقم {self.law_number} لسنة {self.law_year}")
        if self.article_number is not None:
            parts.append(f"المادة {self.article_number}")
        # Case law / principle branch — when there's no statute identity
        if not parts:
            if self.source_type == SourceType.CASE_LAW:
                parts.append("حكم قضائي" + (f" — {self.ruling_id}" if self.ruling_id else ""))
                if self.chamber:
                    parts.append(f"({self.chamber})")
            elif self.source_type == SourceType.LEGAL_PRINCIPLE:
                parts.append("مبدأ قضائي")
                if self.principle_topic:
                    parts.append(f"({self.principle_topic})")
        return " — ".join(parts) if parts else "مصدر قانوني قطري"

    def public_snippet(self, max_chars: int = 280) -> str:
        """Safe user-facing excerpt — never includes raw retrieval residue."""
        text = (self.snippet_text or self.article_text or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        return text

    def to_public_dict(self) -> dict:
        """Safe dict for HTTP responses — internal fields stripped."""
        return {
            "source_type":     self.source_type.value,
            "citation":        self.public_citation(),
            "snippet":         self.public_snippet(),
            "domain":          self.domain,
            "authority_rank":  int(self.authority_rank),
            "verified":        self.verification_status == VerificationStatus.VERIFIED,
            "in_force":        self.in_force_status == "in_force",
        }


# ═════════════════════════════════════════════════════════════════
# Evidence set — grouped, scored, de-duplicated
# ═════════════════════════════════════════════════════════════════

@dataclass
class EvidenceSet:
    """Outcome of retrieval + adjudication for a single query."""
    records:            list[EvidenceRecord] = field(default_factory=list)
    rejected_count:     int                  = 0
    rejection_reasons:  list[str]            = field(default_factory=list)
    retrieval_trace:    dict                 = field(default_factory=dict)
    query_domain:       str                  = ""
    query_issues:       list[str]            = field(default_factory=list)

    # ── stage counts (for observability) ──
    stage_a_candidates: int = 0   # before any filter
    stage_b_retrieved:  int = 0   # after corpus filter
    stage_c_adjudicated: int = 0  # survived relevance
    stage_d_verified:   int = 0   # survived canonical verification
    stage_e_selected:   int = 0   # final set

    def has_evidence(self) -> bool:
        return any(r.is_usable() for r in self.records)

    def has_direct_statute(self) -> bool:
        """True if at least one VERIFIED statute article in the set."""
        return any(
            r.source_type == SourceType.STATUTE
            and r.verification_status == VerificationStatus.VERIFIED
            and r.is_usable()
            for r in self.records
        )

    def top_authority(self) -> Optional[EvidenceRecord]:
        """Return highest-authority usable record (for primary citation)."""
        usable = [r for r in self.records if r.is_usable()]
        if not usable:
            return None
        return max(usable, key=lambda r: (int(r.authority_rank), r.relevance_score))

    def by_source_type(self, st: SourceType) -> list[EvidenceRecord]:
        return [r for r in self.records
                if r.source_type == st and r.is_usable()]

    def to_public_list(self, max_items: int = 5) -> list[dict]:
        """Top N records as safe public dicts."""
        usable = sorted(
            [r for r in self.records if r.is_usable()],
            key=lambda r: (int(r.authority_rank), r.relevance_score),
            reverse=True,
        )
        return [r.to_public_dict() for r in usable[:max_items]]

    def trace_summary(self) -> dict:
        """Observability: what happened at each stage."""
        summary = {
            "stage_a_candidates":  self.stage_a_candidates,
            "stage_b_retrieved":   self.stage_b_retrieved,
            "stage_c_adjudicated": self.stage_c_adjudicated,
            "stage_d_verified":    self.stage_d_verified,
            "stage_e_selected":    self.stage_e_selected,
            "rejected_count":      self.rejected_count,
            "final_count":         len([r for r in self.records if r.is_usable()]),
            "has_direct_statute":  self.has_direct_statute(),
            "query_domain":        self.query_domain,
            "query_issues":        list(self.query_issues),
        }
        # Merge source-type breakdown captured during retrieval
        for k, v in (self.retrieval_trace or {}).items():
            if k not in summary:
                summary[k] = v
        return summary
