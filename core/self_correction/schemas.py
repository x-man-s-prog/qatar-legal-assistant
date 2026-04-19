# -*- coding: utf-8 -*-
"""
Pydantic models for every stage of the self-correction pipeline.
All data flows through typed structures — no raw dicts between stages.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════

class EvidenceLevel(str, Enum):
    """How strongly a claim is backed by retrieved evidence."""
    EXPLICIT = "explicit"        # Direct text from a law article
    INFERRED = "inferred"        # Reasonable legal inference
    UNSUPPORTED = "unsupported"  # Nothing in context supports it
    CONTRADICTED = "contradicted" # Context says the opposite


class GateVerdict(str, Enum):
    """Final decision by the gate."""
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    REPAIR = "repair"
    REPAIR_AGAIN = "repair_again"     # Second repair round
    REFUSE = "refuse"


class QueryComplexity(str, Enum):
    SIMPLE = "simple"            # greeting, known answer
    LEGAL_SINGLE = "legal_single"  # single legal question
    LEGAL_MULTI = "legal_multi"    # compound legal question
    TOOL_REQUIRED = "tool_required"
    COMPLEX = "complex"            # multi-step: tools + RAG + reasoning


class ClaimType(str, Enum):
    ARTICLE_REF = "article_ref"         # "المادة 173 من قانون الأسرة"
    PENALTY = "penalty"                 # "عقوبة الحبس 3 سنوات"
    RULING_REF = "ruling_ref"           # "طعن رقم 123/2020"
    LEGAL_CONCLUSION = "legal_conclusion"  # "يحق لك التعويض"
    PROCEDURAL = "procedural"           # "يجب رفع الدعوى خلال 30 يوم"
    FACTUAL = "factual"                 # "القانون صدر سنة 2004"


# ══════════════════════════════════════════════════════════════
# Claim Extraction
# ══════════════════════════════════════════════════════════════

class ExtractedClaim(BaseModel):
    """A single legal claim extracted from the draft answer."""
    text: str = Field(..., description="The claim text as it appears")
    claim_type: ClaimType
    article_number: Optional[str] = None
    law_name: Optional[str] = None
    is_decisive: bool = Field(False, description="Is this a key conclusion?")


class ClaimExtractionResult(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)
    total_claims: int = 0
    decisive_claims: int = 0


# ══════════════════════════════════════════════════════════════
# Citation Verification
# ══════════════════════════════════════════════════════════════

class CitationCheck(BaseModel):
    """Result of verifying one citation against the database."""
    claim: ExtractedClaim
    found_in_context: bool = False
    found_in_db: bool = False
    actual_content: Optional[str] = None
    mismatch_detail: Optional[str] = None
    verified: bool = False


class CitationVerificationResult(BaseModel):
    checks: list[CitationCheck] = Field(default_factory=list)
    total: int = 0
    verified: int = 0
    failed: int = 0
    fabricated: list[str] = Field(default_factory=list,
                                  description="Article refs not found anywhere")


# ══════════════════════════════════════════════════════════════
# Grounding Verification
# ══════════════════════════════════════════════════════════════

class GroundingCheck(BaseModel):
    """Whether a non-citation claim is grounded in retrieved evidence."""
    claim: ExtractedClaim
    evidence_level: EvidenceLevel
    supporting_chunk_idx: Optional[int] = None
    explanation: str = ""


class GroundingResult(BaseModel):
    checks: list[GroundingCheck] = Field(default_factory=list)
    total: int = 0
    grounded: int = 0
    unsupported: int = 0
    unsupported_decisive: int = 0


# ══════════════════════════════════════════════════════════════
# Contradiction Detection
# ══════════════════════════════════════════════════════════════

class Contradiction(BaseModel):
    """A contradiction between the answer and retrieved evidence."""
    answer_segment: str
    evidence_segment: str
    source_law: str = ""
    severity: str = "major"   # "major" | "minor"
    explanation: str = ""


class ContradictionResult(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)
    has_major: bool = False
    count: int = 0


# ══════════════════════════════════════════════════════════════
# Coverage Check
# ══════════════════════════════════════════════════════════════

class CoverageResult(BaseModel):
    """Does the answer actually address the user's question?"""
    covers_main_question: bool = True
    missing_aspects: list[str] = Field(default_factory=list)
    coverage_pct: float = 100.0
    partial: bool = False


# ══════════════════════════════════════════════════════════════
# Risk Scoring
# ══════════════════════════════════════════════════════════════

class QueryContext(BaseModel):
    """Context for adaptive risk scoring."""
    complexity: QueryComplexity = QueryComplexity.LEGAL_SINGLE
    is_legal: bool = True
    has_tools: bool = False
    retrieval_confidence: float = 0.0  # top retrieval score
    brain_route: str = ""


class RiskScore(BaseModel):
    """Aggregated risk assessment across all checks."""
    citation_risk: float = Field(0.0, ge=0, le=1)
    grounding_risk: float = Field(0.0, ge=0, le=1)
    contradiction_risk: float = Field(0.0, ge=0, le=1)
    coverage_risk: float = Field(0.0, ge=0, le=1)
    overall_risk: float = Field(0.0, ge=0, le=1)
    risk_factors: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# Repair
# ══════════════════════════════════════════════════════════════

class RepairAction(BaseModel):
    action: str             # "remove_fabricated", "add_disclaimer", "rewrite_claim", "full_rewrite"
    target: str = ""        # Which part of the answer to fix
    instruction: str = ""   # What to tell the LLM if rewrite needed
    applied: bool = False


class RepairResult(BaseModel):
    actions_taken: list[RepairAction] = Field(default_factory=list)
    rounds_used: int = 0
    original_answer: str = ""
    repaired_answer: str = ""


# ══════════════════════════════════════════════════════════════
# Final Gate Decision
# ══════════════════════════════════════════════════════════════

class GateDecision(BaseModel):
    """The final verdict — what happens to the answer."""
    verdict: GateVerdict
    final_answer: str = ""
    confidence_adjustment: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    risk: Optional[RiskScore] = None
    citation_result: Optional[CitationVerificationResult] = None
    grounding_result: Optional[GroundingResult] = None
    contradiction_result: Optional[ContradictionResult] = None
    coverage_result: Optional[CoverageResult] = None
    repair_result: Optional[RepairResult] = None
    refused_reason: str = ""
    latency_ms: int = 0
