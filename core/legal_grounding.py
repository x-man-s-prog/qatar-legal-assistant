# -*- coding: utf-8 -*-
"""
Legal Grounding Engine — PHASE LEGAL GROUNDING FIX
===================================================
ZERO-HALLUCINATION LAW SYSTEM.

Absolute rule: IF the legal text is not verified → DO NOT mention it.

This engine is the LAST defensive layer before user output.
It scans final text for legal citations (law numbers, article numbers,
law names) and:
  • VERIFIED   → allowed through unchanged
  • PARTIAL    → law name allowed, article number stripped
  • UNVERIFIED → entire citation removed and replaced with safe wording

Deterministic, regex-based, no LLM calls. Cannot invent citations.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("legal_grounding")


# ══════════════════════════════════════════════════════════════
# Citation Confidence
# ══════════════════════════════════════════════════════════════

class CitationConfidence(str, Enum):
    VERIFIED = "verified"          # law + article both verified → allow
    PARTIAL = "partial"            # law verified, article unknown → allow law only
    UNVERIFIED = "unverified"      # law unknown OR article fabricated → BLOCK


# ══════════════════════════════════════════════════════════════
# Verified Qatari Law Database (publicly verifiable on Al-Meezan)
# ══════════════════════════════════════════════════════════════

# Each entry: canonical name → metadata
# Article ranges are conservative; out-of-range citations → UNVERIFIED.
# Aliases capture common phrasing variations.
_VERIFIED_LAWS = {
    "قانون العمل": {
        "number": "14",
        "year": "2004",
        "domain": "employment",
        "max_article": 145,
        "aliases": [
            "قانون العمل القطري",
            "قانون العمل رقم 14",
            "قانون العمل رقم 14 لسنة 2004",
            "قانون العمل لسنة 2004",
        ],
    },
    "قانون العقوبات": {
        "number": "11",
        "year": "2004",
        "domain": "criminal",
        "max_article": 368,
        "aliases": [
            "قانون العقوبات القطري",
            "قانون العقوبات رقم 11",
            "قانون العقوبات رقم 11 لسنة 2004",
        ],
    },
    "قانون الأسرة": {
        "number": "22",
        "year": "2006",
        "domain": "family",
        "max_article": 301,
        "aliases": [
            "قانون الأحوال الشخصية",
            "قانون الأسرة القطري",
            "قانون الأسرة رقم 22",
            "قانون الأسرة رقم 22 لسنة 2006",
        ],
    },
    "القانون المدني": {
        "number": "22",
        "year": "2004",
        "domain": "civil",
        "max_article": 960,
        "aliases": [
            "قانون المعاملات المدنية",
            "القانون المدني القطري",
            "القانون المدني رقم 22",
            "القانون المدني رقم 22 لسنة 2004",
        ],
    },
    "قانون المرافعات المدنية والتجارية": {
        "number": "13",
        "year": "1990",
        "domain": "procedural_civil",
        "max_article": 459,
        "aliases": [
            "قانون المرافعات",
            "قانون المرافعات المدنية",
            "قانون المرافعات رقم 13 لسنة 1990",
        ],
    },
    "قانون الإيجار": {
        "number": "4",
        "year": "2008",
        "domain": "rental",
        "max_article": 78,
        "aliases": [
            "قانون تأجير العقارات",
            "قانون الإيجار القطري",
            "قانون الإيجار رقم 4 لسنة 2008",
        ],
    },
    "قانون الإجراءات الجنائية": {
        "number": "23",
        "year": "2004",
        "domain": "procedural_criminal",
        "max_article": 422,
        "aliases": [
            "قانون الإجراءات والمحاكمات الجزائية",
            "قانون الإجراءات الجزائية",
        ],
    },
    "قانون المعاملات التجارية": {
        "number": "27",
        "year": "2006",
        "domain": "commercial",
        "max_article": 850,
        "aliases": ["قانون التجارة"],
    },
    "قانون المرور": {
        "number": "19",
        "year": "2007",
        "domain": "traffic",
        "max_article": 90,
        "aliases": ["قانون المرور القطري"],
    },
}


# Domain compatibility: which law domains apply to which issue types
_DOMAIN_COMPATIBILITY = {
    "employment": {"employment", "civil"},                  # labor + general civil
    "criminal": {"criminal", "procedural_criminal", "civil"},  # penal + procedure + civil overlap
    "family": {"family", "civil"},
    "rental": {"rental", "civil", "procedural_civil"},
    "debt": {"civil", "commercial", "procedural_civil", "criminal"},  # debt + fraud overlap
    "contract": {"civil", "commercial"},
    "appeal": {"procedural_civil", "procedural_criminal"},
    "enforcement": {"procedural_civil", "procedural_criminal"},
    "administrative": {"civil", "procedural_civil"},
    "traffic": {"traffic", "criminal"},
    "procedural": {"procedural_civil", "procedural_criminal", "civil", "criminal"},
    # PHASE INTELLIGENT DECISION — banking + commercial
    "banking": {"commercial", "civil", "procedural_civil"},
    "commercial": {"commercial", "civil", "procedural_civil"},
    "general": {"civil", "commercial", "procedural_civil"},  # be lenient
}


# ══════════════════════════════════════════════════════════════
# LegalCitation Dataclass
# ══════════════════════════════════════════════════════════════

@dataclass
class LegalCitation:
    raw_text: str = ""              # exact substring as found in answer
    law_name: str = ""              # canonical law name (if matched)
    law_number: str = ""            # extracted law number
    law_year: str = ""              # extracted year
    article_number: str = ""        # extracted article number
    confidence: CitationConfidence = CitationConfidence.UNVERIFIED
    domain: str = ""                # which domain this law belongs to
    is_safe: bool = False           # OK to include in output?
    block_reason: str = ""          # why blocked (if blocked)


@dataclass
class GroundingResult:
    text: str = ""                              # text after grounding filter
    safe_mode_applied: bool = False             # was safe mode triggered?
    citations_found: list[LegalCitation] = field(default_factory=list)
    citations_blocked: list[LegalCitation] = field(default_factory=list)
    citations_downgraded: list[LegalCitation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# LegalDomainValidator
# ══════════════════════════════════════════════════════════════

class LegalDomainValidator:
    """Validates that a law's domain matches the user's issue domain."""

    def domain_of_law(self, law_name: str) -> str:
        """Return the domain of a known law, or empty string if unknown."""
        canonical = _resolve_law_name(law_name)
        if canonical:
            return _VERIFIED_LAWS[canonical]["domain"]
        return ""

    def is_compatible(self, issue_domain: str, law_domain: str) -> bool:
        """True if the law's domain is acceptable for the issue."""
        if not issue_domain or not law_domain:
            return True  # unknown either side → don't block
        compat = _DOMAIN_COMPATIBILITY.get(issue_domain, set())
        return law_domain in compat

    def block_if_mismatch(self, citation: LegalCitation,
                            issue_domain: str) -> bool:
        """True if this citation should be blocked due to domain mismatch."""
        if not citation.law_name or not citation.domain:
            return False
        if not issue_domain:
            return False
        return not self.is_compatible(issue_domain, citation.domain)


# ══════════════════════════════════════════════════════════════
# Helpers — name resolution + extraction
# ══════════════════════════════════════════════════════════════

def _resolve_law_name(raw_name: str) -> str:
    """Return canonical law name if recognized, else empty string."""
    if not raw_name:
        return ""
    raw = raw_name.strip()
    # Direct match
    if raw in _VERIFIED_LAWS:
        return raw
    # Alias match (longest first)
    for canonical, meta in _VERIFIED_LAWS.items():
        for alias in sorted(meta["aliases"], key=len, reverse=True):
            if alias in raw or raw in alias:
                return canonical
    # Substring match against canonical names (for noisy text)
    for canonical in sorted(_VERIFIED_LAWS.keys(), key=len, reverse=True):
        if canonical in raw or raw in canonical:
            return canonical
    return ""


# Citation extraction patterns
# Each captures: full match + relevant fields
_PATTERN_LAW_FULL = re.compile(
    r"(قانون[\s\S]{1,40}?رقم\s*\(?\s*(\d+)\s*\)?\s*لسنة\s*(\d{4}))",
    re.UNICODE,
)
_PATTERN_ARTICLE = re.compile(
    r"((?:ال)?مادة\s*\(?\s*(\d+)\s*\)?(?:\s*مكرر)?)",
    re.UNICODE,
)
_PATTERN_LAW_NAME_ONLY = re.compile(
    r"(قانون\s+(?:العمل|العقوبات|الأسرة|الأحوال\s*الشخصية|الإيجار|"
    r"المرافعات(?:\s+المدنية(?:\s+والتجارية)?)?|الإجراءات\s+(?:الجنائية|الجزائية)|"
    r"المعاملات\s+(?:التجارية|المدنية)|المرور|التجارة))",
    re.UNICODE,
)
_PATTERN_CIVIL_LAW = re.compile(
    r"(القانون\s+المدني(?:\s+القطري)?)",
    re.UNICODE,
)
# Generic catch-all for "قانون X" / "لقانون X" — flags unknown laws as UNVERIFIED.
# The "X" is captured separately and validated against a stopword list.
_LAW_STOPWORDS = {"أو", "و", "في", "من", "عن", "على", "إلى", "مع",
                   "بعد", "قبل", "أن", "إن", "لا", "ما", "هل",
                   "محددة", "محدد", "معين", "معينة", "جديد", "جديدة",
                   "كذا", "كذلك", "أيضاً", "ذلك", "هذا", "هذه"}
_PATTERN_LAW_GENERIC = re.compile(
    r"((?:ل)?قانون\s+([^\s،.]{2,}(?:\s+[^\s،.]+){0,2}))",
    re.UNICODE,
)


# ══════════════════════════════════════════════════════════════
# LegalGroundingEngine
# ══════════════════════════════════════════════════════════════

class LegalGroundingEngine:
    """Main grounding engine — verifies, downgrades, or blocks legal citations."""

    def __init__(self):
        self._validator = LegalDomainValidator()

    # ── Verification API ──

    def verify_law_exists(self, law_name: str) -> bool:
        return bool(_resolve_law_name(law_name))

    def verify_article_exists(self, law_name: str,
                                article_number: str) -> bool:
        canonical = _resolve_law_name(law_name)
        if not canonical:
            return False
        try:
            num = int(article_number)
        except (ValueError, TypeError):
            return False
        if num < 1:
            return False
        max_art = _VERIFIED_LAWS[canonical]["max_article"]
        return num <= max_art

    def validate_domain_match(self, issue_type: str, law_domain: str) -> bool:
        return self._validator.is_compatible(issue_type, law_domain)

    def is_verified_reference(self, raw_text: str,
                                article_number: str = "") -> CitationConfidence:
        """Classify a single reference."""
        canonical = _resolve_law_name(raw_text)
        if not canonical:
            return CitationConfidence.UNVERIFIED
        if not article_number:
            return CitationConfidence.PARTIAL
        if self.verify_article_exists(canonical, article_number):
            return CitationConfidence.VERIFIED
        return CitationConfidence.UNVERIFIED

    # ── Citation extraction ──

    def extract_citations(self, text: str) -> list[LegalCitation]:
        """Find all citations in text and classify each."""
        if not text:
            return []
        out: list[LegalCitation] = []
        seen_spans: set[tuple[int, int]] = set()

        # 1. Full law citations: "قانون ... رقم X لسنة Y"
        for m in _PATTERN_LAW_FULL.finditer(text):
            span = m.span()
            if span in seen_spans:
                continue
            seen_spans.add(span)
            full = m.group(1)
            num = m.group(2)
            year = m.group(3)
            canonical = _resolve_law_name(full)
            cite = LegalCitation(
                raw_text=full,
                law_name=canonical,
                law_number=num,
                law_year=year,
            )
            if canonical:
                meta = _VERIFIED_LAWS[canonical]
                cite.domain = meta["domain"]
                # Verify number + year match
                if meta["number"] == num and meta["year"] == year:
                    cite.confidence = CitationConfidence.PARTIAL
                    cite.is_safe = True
                else:
                    cite.confidence = CitationConfidence.UNVERIFIED
                    cite.block_reason = (
                        f"law number/year mismatch: stated {num}/{year}, "
                        f"verified {meta['number']}/{meta['year']}"
                    )
            else:
                cite.confidence = CitationConfidence.UNVERIFIED
                cite.block_reason = "law name not in verified database"
            out.append(cite)

        # 2. Law name only (no rقم/سنة) — known patterns first
        for pat in (_PATTERN_LAW_NAME_ONLY, _PATTERN_CIVIL_LAW):
            for m in pat.finditer(text):
                span = m.span()
                if any(s[0] <= span[0] and span[1] <= s[1] for s in seen_spans):
                    continue
                seen_spans.add(span)
                full = m.group(1)
                canonical = _resolve_law_name(full)
                cite = LegalCitation(raw_text=full, law_name=canonical)
                if canonical:
                    meta = _VERIFIED_LAWS[canonical]
                    cite.domain = meta["domain"]
                    cite.confidence = CitationConfidence.PARTIAL
                    cite.is_safe = True
                else:
                    cite.confidence = CitationConfidence.UNVERIFIED
                    cite.block_reason = "law name not in verified database"
                out.append(cite)

        # 2b. Generic "قانون X" — catches unknown/fake laws not matched above
        for m in _PATTERN_LAW_GENERIC.finditer(text):
            span = m.span()
            # Skip if this span OVERLAPS any already-captured span (any overlap,
            # not just containment, to avoid duplicate replacements).
            if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in seen_spans):
                continue
            full = m.group(1)
            tail = m.group(2)  # the "X" part after قانون
            # Reject false positives: if X starts with a stopword, it's not a law
            first_word = tail.split()[0] if tail else ""
            if first_word in _LAW_STOPWORDS:
                continue
            seen_spans.add(span)
            canonical = _resolve_law_name(full)
            cite = LegalCitation(raw_text=full, law_name=canonical)
            if canonical:
                meta = _VERIFIED_LAWS[canonical]
                cite.domain = meta["domain"]
                cite.confidence = CitationConfidence.PARTIAL
                cite.is_safe = True
            else:
                cite.confidence = CitationConfidence.UNVERIFIED
                cite.block_reason = "law name not in verified database"
            out.append(cite)

        # 3. Article references: "المادة (X)" — verify against nearest law
        for m in _PATTERN_ARTICLE.finditer(text):
            span = m.span()
            if span in seen_spans:
                continue
            seen_spans.add(span)
            full = m.group(1)
            article_num = m.group(2)

            # Look at surrounding text (±150 chars) for a law context
            start, end = span
            context = text[max(0, start - 150):min(len(text), end + 150)]
            law_in_context = ""
            for c in out:
                if c.law_name and c.raw_text in context:
                    law_in_context = c.law_name
                    break

            cite = LegalCitation(
                raw_text=full,
                article_number=article_num,
                law_name=law_in_context,
            )
            if not law_in_context:
                # Article number with no surrounding law context → UNVERIFIED
                cite.confidence = CitationConfidence.UNVERIFIED
                cite.block_reason = "article cited without verifiable law context"
            elif self.verify_article_exists(law_in_context, article_num):
                cite.confidence = CitationConfidence.VERIFIED
                cite.is_safe = True
                cite.domain = _VERIFIED_LAWS[law_in_context]["domain"]
            else:
                cite.confidence = CitationConfidence.UNVERIFIED
                max_a = _VERIFIED_LAWS.get(law_in_context, {}).get("max_article", "?")
                cite.block_reason = (
                    f"article {article_num} out of verified range "
                    f"(max ≈ {max_a} for {law_in_context})"
                )
            out.append(cite)

        return out

    # ── Filtering API ──

    def block_if_unverified(self, text: str,
                              issue_domain: str = "") -> GroundingResult:
        """
        Strip unverified citations from text. Verified/partial pass through.
        Cross-domain mismatches are also blocked.
        """
        result = GroundingResult(text=text)
        if not text:
            return result

        citations = self.extract_citations(text)
        result.citations_found = citations

        # Build a list of (start, end, replacement) edits
        edits: list[tuple[int, int, str]] = []

        for cite in citations:
            # Find this citation in text (first occurrence)
            idx = text.find(cite.raw_text)
            if idx < 0:
                continue
            span = (idx, idx + len(cite.raw_text))

            # Domain mismatch check
            if issue_domain and cite.domain and \
               self._validator.block_if_mismatch(cite, issue_domain):
                edits.append((span[0], span[1], " النص القانوني المنظِّم في المجال المختص "))
                cite.is_safe = False
                cite.block_reason = (
                    f"domain mismatch: {cite.domain} law cited in "
                    f"{issue_domain} issue"
                )
                result.citations_blocked.append(cite)
                continue

            if cite.confidence == CitationConfidence.UNVERIFIED:
                # Replace with cleaner safe wording (PHASE INTELLIGENT DECISION).
                # Surround with spaces to avoid joining with adjacent words.
                if cite.article_number:
                    edits.append((span[0], span[1], " النص القانوني المنظِّم "))
                else:
                    edits.append((span[0], span[1], " القانون المختص "))
                result.citations_blocked.append(cite)
            elif cite.confidence == CitationConfidence.PARTIAL:
                if cite.article_number and not cite.law_name:
                    edits.append((span[0], span[1], " النص القانوني المنظِّم "))
                    result.citations_downgraded.append(cite)
            # VERIFIED: allow

        # Apply edits in reverse order to preserve indexes
        edits.sort(key=lambda e: e[0], reverse=True)
        new_text = text
        for start, end, replacement in edits:
            new_text = new_text[:start] + replacement + new_text[end:]

        # Clean up any double-spaces / dangling punctuation after replacements
        new_text = re.sub(r" {2,}", " ", new_text)
        new_text = re.sub(r"\(\s*\[", "[", new_text)
        new_text = re.sub(r"\]\s*\)", "]", new_text)

        result.text = new_text
        if result.citations_blocked:
            result.notes.append(
                f"blocked {len(result.citations_blocked)} unverified citation(s)"
            )
        return result

    def convert_to_safe_analysis_mode(self, text: str) -> str:
        """
        Aggressive safe mode: strip ALL article references and unverified law
        names. Used when a query is in a domain with no verifiable laws or
        when the text fails grounding checks.
        """
        if not text:
            return text
        # Strip all article references
        out = _PATTERN_ARTICLE.sub("[مرجع موضوعي عام]", text)
        # Strip law-with-number refs that don't resolve
        def _law_full_filter(m):
            full = m.group(1)
            return full if _resolve_law_name(full) else "[قانون متخصص]"
        out = _PATTERN_LAW_FULL.sub(_law_full_filter, out)
        # Clean up double-spaces
        out = re.sub(r" {2,}", " ", out)
        return out

    def ground_text(self, text: str,
                      issue_domain: str = "") -> GroundingResult:
        """Main entry point — full filtering pipeline."""
        return self.block_if_unverified(text, issue_domain)


# ══════════════════════════════════════════════════════════════
# Module-level convenience functions
# ══════════════════════════════════════════════════════════════

_engine: Optional[LegalGroundingEngine] = None


def get_grounding_engine() -> LegalGroundingEngine:
    global _engine
    if _engine is None:
        _engine = LegalGroundingEngine()
    return _engine


def ground_legal_text(text: str, issue_domain: str = "") -> GroundingResult:
    """Convenience: scan + filter unverified citations."""
    return get_grounding_engine().ground_text(text, issue_domain)


def safe_filter(text: str, issue_domain: str = "") -> str:
    """Convenience: returns just the cleaned text, dropping the metadata."""
    return ground_legal_text(text, issue_domain).text
