# -*- coding: utf-8 -*-
"""
Knowledge Contract — canonical shape for every piece of legal knowledge
that enters the runtime.

Two tiers:
  KnowledgeRecord   — normalized, domain-bound, admissibility-classified.
                      Persisted in the in-memory KnowledgeStore.
  QuarantineRecord  — unusable raw input + reason code. Never retrieved.

Contract design rule:
  Anything that can't be turned into a clean KnowledgeRecord becomes a
  QuarantineRecord. There is NO third path. Raw dicts never travel the
  runtime beyond the ingestion boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.evidence.contract import (
    SourceType as _EvidenceSourceType,
    AuthorityRank, TextQuality, VerificationStatus,
)


# ═════════════════════════════════════════════════════════════════
# Enums
# ═════════════════════════════════════════════════════════════════

class KnowledgeSourceType(str, Enum):
    """A richer taxonomy than EvidenceSourceType — covers every kind of
    raw input we ingest."""
    STATUTE               = "statute"
    REGULATION            = "regulation"
    EXECUTIVE_BYLAW       = "executive_bylaw"
    MINISTERIAL_DECISION  = "ministerial_decision"
    COURT_RULING          = "court_ruling"
    LEGAL_PRINCIPLE       = "legal_principle"
    OFFICIAL_EXPLANATION  = "official_explanation"
    STRUCTURED_TABLE      = "structured_table"
    ADMINISTRATIVE_REF    = "administrative_ref"
    DERIVED_SUMMARY       = "derived_summary"
    DB_CHUNK              = "db_chunk"         # pre-classification raw chunk
    UNKNOWN               = "unknown"

    def to_evidence_source_type(self) -> _EvidenceSourceType:
        mapping = {
            KnowledgeSourceType.STATUTE:              _EvidenceSourceType.STATUTE,
            KnowledgeSourceType.REGULATION:           _EvidenceSourceType.REGULATION,
            KnowledgeSourceType.EXECUTIVE_BYLAW:      _EvidenceSourceType.REGULATION,
            KnowledgeSourceType.MINISTERIAL_DECISION: _EvidenceSourceType.REGULATION,
            KnowledgeSourceType.COURT_RULING:         _EvidenceSourceType.CASE_LAW,
            KnowledgeSourceType.LEGAL_PRINCIPLE:      _EvidenceSourceType.LEGAL_PRINCIPLE,
            KnowledgeSourceType.OFFICIAL_EXPLANATION: _EvidenceSourceType.OFFICIAL_EXPLANATION,
            KnowledgeSourceType.STRUCTURED_TABLE:     _EvidenceSourceType.STRUCTURED_TABLE,
        }
        return mapping.get(self, _EvidenceSourceType.UNKNOWN)


class AdmissibilityStatus(str, Enum):
    """Is this record usable in runtime reasoning?"""
    RUNTIME_ELIGIBLE = "runtime_eligible"      # verified, bound, clean
    SUPPORT_ONLY     = "support_only"          # can enrich but not ground
    UNBOUND          = "unbound"               # no canonical / domain binding
    QUARANTINED      = "quarantined"           # rejected upstream


class SufficiencyLevel(str, Enum):
    """Set by the pipeline when evaluating an EvidenceSet against a query.

    Consumed by fail_closed_pipeline's evidence-sufficiency gate.
    """
    NONE                = "none"                  # 0 records
    UNVERIFIED_ONLY     = "unverified_only"       # records exist but none verified
    WEAK                = "weak"                  # verified but single / low-score
    SUFFICIENT_LIMITED  = "sufficient_limited"    # enough for scoped answer
    SUFFICIENT_DIRECT   = "sufficient_direct"     # direct statute + evidence
    CONTRADICTORY       = "contradictory"         # internal contradictions detected

    def allows_reasoning(self) -> bool:
        return self in (SufficiencyLevel.SUFFICIENT_LIMITED,
                        SufficiencyLevel.SUFFICIENT_DIRECT)


# ═════════════════════════════════════════════════════════════════
# KnowledgeRecord — the normalized, domain-bound unit
# ═════════════════════════════════════════════════════════════════

@dataclass
class KnowledgeRecord:
    """The canonical shape of normalized legal knowledge.

    Superset of EvidenceRecord. Every EvidenceRecord can be derived
    from a KnowledgeRecord via `.to_evidence_record()`.
    """

    # ── identity ──
    knowledge_id:        str               = ""
    source_type:         KnowledgeSourceType = KnowledgeSourceType.UNKNOWN
    canonical_source_id: str               = ""   # canonical law_id or "" for non-statute

    # ── statute identity (when applicable) ──
    law_title:     str           = ""
    law_number:    str           = ""
    law_year:      str           = ""
    article_number: Optional[int] = None

    # ── case law identity (when applicable) ──
    ruling_id:     str = ""
    chamber:       str = ""
    ruling_date:   str = ""

    # ── principle identity (when applicable) ──
    principle_id:  str = ""
    principle_topic: str = ""

    # ── provenance ──
    source_url:         str = ""
    source_fingerprint: str = ""
    document_id:        str = ""
    version_info:       str = ""
    chunk_origin:       str = ""     # "db:chunks:id" | "json:file_name" | "..."
    duplicate_group_id: str = ""     # set when this record duplicates another

    # ── lifecycle ──
    in_force_status: str = "unknown"   # in_force | amended | repealed | unknown
    effective_date:  str = ""
    repeal_status:   str = ""

    # ── classification ──
    domain:          str       = ""
    subdomain:       str       = ""
    issue_tags:      list[str] = field(default_factory=list)
    remedy_tags:     list[str] = field(default_factory=list)
    procedural_tags: list[str] = field(default_factory=list)
    party_role_tags: list[str] = field(default_factory=list)

    # ── text ──
    text_body:   str = ""        # raw text
    clean_text:  str = ""        # normalized version

    # ── quality ──
    text_quality_score:   float        = 1.0
    text_quality:         TextQuality  = TextQuality.CLEAN
    language_cleanliness: float        = 1.0
    has_ocr_noise:        bool         = False
    is_fragmented:        bool         = False

    # ── authority ──
    authority_rank:     AuthorityRank      = AuthorityRank.UNKNOWN
    provenance_status:  str                = "known"    # known | partial | unknown
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    admissibility:      AdmissibilityStatus = AdmissibilityStatus.UNBOUND

    # ── retrieval scoring (runtime, set by adjudicator) ──
    relevance_score: float = 0.0

    def is_runtime_eligible(self) -> bool:
        """Can this record participate in retrieval + reasoning?"""
        if self.admissibility != AdmissibilityStatus.RUNTIME_ELIGIBLE:
            return False
        if self.text_quality == TextQuality.CORRUPTED:
            return False
        if not (self.clean_text or self.text_body):
            return False
        return True

    def is_statute(self) -> bool:
        return self.source_type in (
            KnowledgeSourceType.STATUTE,
            KnowledgeSourceType.REGULATION,
            KnowledgeSourceType.EXECUTIVE_BYLAW,
        )

    def is_case_law(self) -> bool:
        return self.source_type in (
            KnowledgeSourceType.COURT_RULING,
            KnowledgeSourceType.LEGAL_PRINCIPLE,
        )

    def public_citation(self) -> str:
        """Firewall-safe user-visible citation."""
        parts = []
        if self.law_title:
            parts.append(self.law_title)
        if self.law_number and self.law_year:
            parts.append(f"رقم {self.law_number} لسنة {self.law_year}")
        if self.article_number is not None:
            parts.append(f"المادة {self.article_number}")
        if self.ruling_id and not parts:
            parts.append(f"حكم {self.ruling_id}")
        if self.chamber and self.ruling_id:
            parts.append(f"({self.chamber})")
        return " — ".join(parts) if parts else "مصدر قانوني قطري"

    def public_snippet(self, max_chars: int = 280) -> str:
        text = (self.clean_text or self.text_body or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        return text

    def to_evidence_record(self):
        """Convert to EvidenceRecord for the retriever."""
        from core.evidence.contract import EvidenceRecord
        return EvidenceRecord(
            source_type         = self.source_type.to_evidence_source_type(),
            law_title           = self.law_title,
            law_number          = self.law_number,
            law_year            = self.law_year,
            article_number      = self.article_number,
            article_text        = self.clean_text or self.text_body,
            snippet_text        = self.public_snippet(),
            domain              = self.domain,
            subdomain           = self.subdomain,
            issue_tags          = list(self.issue_tags),
            remedy_tags         = list(self.remedy_tags),
            procedural_tags     = list(self.procedural_tags),
            canonical_id        = self.canonical_source_id,
            authority_rank      = self.authority_rank,
            verification_status = self.verification_status,
            text_quality        = self.text_quality,
            in_force_status     = self.in_force_status,
            is_fragmented       = self.is_fragmented,
            has_ocr_noise       = self.has_ocr_noise,
            language_cleanliness = self.language_cleanliness,
            source_url          = self.source_url,
            source_fingerprint  = self.source_fingerprint,
            full_document_id    = self.document_id,
            version_info        = self.version_info,
            # Case-law / principle identity (firewall-safe public citation)
            ruling_id           = self.ruling_id,
            chamber             = self.chamber,
            principle_topic     = self.principle_topic,
        )


# ═════════════════════════════════════════════════════════════════
# QuarantineRecord — the "why we rejected this" ledger
# ═════════════════════════════════════════════════════════════════

# Canonical quarantine reason codes — used by tests and observability
QUARANTINE_REASONS = frozenset({
    "missing_canonical_identity",
    "unknown_source",
    "corrupted_text",
    "fragmented_beyond_repair",
    "duplicate_shadow",
    "missing_domain",
    "low_text_quality",
    "unverifiable_article",
    "unverifiable_ruling",
    "legacy_noise",
    "incomplete_metadata",
    "empty_content",
    "non_arabic_content",
    "article_out_of_range",
    "law_not_in_registry",
    "ingestor_exception",
})


@dataclass
class QuarantineRecord:
    quarantine_id:    str = ""
    source_path:      str = ""           # where it came from
    original_snippet: str = ""           # first 120 chars of raw text
    reason_code:      str = "unknown_source"
    reason_detail:    str = ""
    detected_at_stage: str = ""          # normalizer | binder | registry | ingestor

    def to_public_dict(self) -> dict:
        return {
            "source_path":  self.source_path,
            "reason_code":  self.reason_code,
            "reason_detail": self.reason_detail[:200],
            "stage":        self.detected_at_stage,
            "snippet":      self.original_snippet[:120],
        }
