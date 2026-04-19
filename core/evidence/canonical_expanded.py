# -*- coding: utf-8 -*-
"""
Expanded Canonical Citation Registry.
=====================================

Wraps the minimal _REGISTRY in core.legal_gates and adds the Qatari laws
that the minimal registry doesn't cover but that real queries touch.

Every law here is manually curated. Adding a law here is the ONLY way
to make citations for that law verifiable in the new evidence layer.

Design:
  - Strict: citations outside this registry are REJECTED, not "partially verified".
  - Domain-locked: each law has a canonical domain. A citation in the wrong
    domain is rejected even if the law exists.
  - Article-range: each law has a max article number. Articles outside
    the range are rejected as fabricated.
  - In-force status: explicit per-law. Repealed laws block citation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.legal_gates import (
    CanonicalLaw, LegalDomain, CitationVerification,
    CanonicalCitationRegistry as _BaseRegistry,
)


# ═════════════════════════════════════════════════════════════════
# Additional laws — beyond the 9 in legal_gates._REGISTRY
# ═════════════════════════════════════════════════════════════════

_ADDITIONAL_LAWS: dict[str, CanonicalLaw] = {
    # ── Employment / labor subsidiaries ──
    "social_security_law": CanonicalLaw(
        law_id="social_security_law",
        title="قانون التقاعد والمعاشات",
        number="24", year="2002", domain=LegalDomain.EMPLOYMENT,
        article_min=1, article_max=100,
        aliases=["قانون التقاعد", "قانون المعاشات", "التقاعد والمعاشات"],
    ),
    "civil_servants_law": CanonicalLaw(
        law_id="civil_servants_law",
        title="قانون الموارد البشرية المدنية",
        number="15", year="2016", domain=LegalDomain.EMPLOYMENT,
        article_min=1, article_max=180,
        aliases=["قانون الموارد البشرية", "الموارد البشرية المدنية"],
    ),

    # ── Criminal subsidiaries ──
    "cyber_crimes_law": CanonicalLaw(
        law_id="cyber_crimes_law",
        title="قانون مكافحة الجرائم الإلكترونية",
        number="14", year="2014", domain=LegalDomain.CRIMINAL,
        article_min=1, article_max=52,
        aliases=["قانون الجرائم الإلكترونية", "مكافحة الجرائم المعلوماتية",
                  "قانون الجرائم المعلوماتية"],
    ),
    "drug_law": CanonicalLaw(
        law_id="drug_law",
        title="قانون مكافحة المخدرات والمؤثرات العقلية",
        number="9", year="1987", domain=LegalDomain.CRIMINAL,
        article_min=1, article_max=80,
        aliases=["قانون المخدرات", "قانون مكافحة المخدرات"],
    ),
    "money_laundering_law": CanonicalLaw(
        law_id="money_laundering_law",
        title="قانون مكافحة غسل الأموال وتمويل الإرهاب",
        number="20", year="2019", domain=LegalDomain.CRIMINAL,
        article_min=1, article_max=75,
        aliases=["قانون غسل الأموال", "مكافحة غسل الأموال"],
    ),

    # ── Commercial / corporate ──
    "companies_law": CanonicalLaw(
        law_id="companies_law",
        title="قانون الشركات التجارية",
        number="11", year="2015", domain=LegalDomain.COMMERCIAL,
        article_min=1, article_max=350,
        aliases=["قانون الشركات", "الشركات التجارية"],
    ),
    "commercial_agencies_law": CanonicalLaw(
        law_id="commercial_agencies_law",
        title="قانون الوكلاء التجاريين",
        number="8", year="2002", domain=LegalDomain.COMMERCIAL,
        article_min=1, article_max=30,
        aliases=["قانون الوكلاء التجاريين", "الوكالة التجارية"],
    ),
    "bankruptcy_law": CanonicalLaw(
        law_id="bankruptcy_law",
        title="قانون الإفلاس",
        number="8", year="2015", domain=LegalDomain.COMMERCIAL,
        article_min=1, article_max=235,
        aliases=["قانون الإفلاس"],
    ),

    # ── Financial ──
    "central_bank_law": CanonicalLaw(
        law_id="central_bank_law",
        title="قانون مصرف قطر المركزي وتنظيم المؤسسات المالية",
        number="13", year="2012", domain=LegalDomain.BANKING,
        article_min=1, article_max=236,
        aliases=["قانون مصرف قطر المركزي", "قانون البنك المركزي",
                  "قانون تنظيم المؤسسات المالية"],
    ),

    # ── Intellectual property ──
    "copyright_law": CanonicalLaw(
        law_id="copyright_law",
        title="قانون حماية حق المؤلف والحقوق المجاورة",
        number="7", year="2002", domain=LegalDomain.INTELLECTUAL_PROPERTY,
        article_min=1, article_max=55,
        aliases=["قانون حق المؤلف", "قانون الملكية الفكرية", "حق المؤلف"],
    ),
    "trademarks_law": CanonicalLaw(
        law_id="trademarks_law",
        title="قانون العلامات التجارية",
        number="9", year="2002", domain=LegalDomain.INTELLECTUAL_PROPERTY,
        article_min=1, article_max=45,
        aliases=["قانون العلامات التجارية"],
    ),

    # ── Real estate — mapped to CIVIL since LegalDomain has no REAL_ESTATE ──
    "real_estate_registration_law": CanonicalLaw(
        law_id="real_estate_registration_law",
        title="قانون تنظيم تسجيل العقارات",
        number="14", year="1964", domain=LegalDomain.CIVIL,
        article_min=1, article_max=55,
        aliases=["قانون تسجيل العقارات", "تسجيل العقارات"],
    ),

    # ── Administrative / public ──
    "administrative_judiciary_law": CanonicalLaw(
        law_id="administrative_judiciary_law",
        title="قانون الفصل في المنازعات الإدارية",
        number="7", year="2007", domain=LegalDomain.ADMINISTRATIVE,
        article_min=1, article_max=25,
        aliases=["قانون المنازعات الإدارية", "الفصل في المنازعات الإدارية"],
    ),

    # ── Family subsidiaries ──
    "nationality_law": CanonicalLaw(
        law_id="nationality_law",
        title="قانون الجنسية القطرية",
        number="38", year="2005", domain=LegalDomain.FAMILY,
        article_min=1, article_max=29,
        aliases=["قانون الجنسية"],
    ),
}


# ═════════════════════════════════════════════════════════════════
# Domain → allowed canonical law ids (used by G4/G6)
# ═════════════════════════════════════════════════════════════════

_DOMAIN_TO_ALLOWED_IDS: dict[LegalDomain, set[str]] = {
    LegalDomain.EMPLOYMENT: {
        "labor_law", "social_security_law", "civil_servants_law",
    },
    LegalDomain.CRIMINAL: {
        "penal_code", "criminal_procedure",
        "cyber_crimes_law", "drug_law", "money_laundering_law",
    },
    LegalDomain.FAMILY: {
        "family_law", "nationality_law",
    },
    LegalDomain.CIVIL: {
        "civil_code", "civil_procedure",
    },
    LegalDomain.COMMERCIAL: {
        "commercial_law", "companies_law", "commercial_agencies_law",
        "bankruptcy_law",
    },
    LegalDomain.RENTAL: {
        "rental_law", "civil_code",
    },
    LegalDomain.BANKING: {
        "central_bank_law", "civil_code", "commercial_law",
    },
    LegalDomain.INTELLECTUAL_PROPERTY: {
        "copyright_law", "trademarks_law",
    },
    LegalDomain.ADMINISTRATIVE: {
        "administrative_judiciary_law",
    },
    LegalDomain.TRAFFIC: {
        "traffic_law",
    },
    LegalDomain.PROCEDURAL: {
        "civil_procedure", "criminal_procedure",
    },
}


# ═════════════════════════════════════════════════════════════════
# Expanded registry class
# ═════════════════════════════════════════════════════════════════

class ExpandedCanonicalRegistry:
    """Strict canonical registry — expanded over the minimal one in legal_gates.

    API mirrors CanonicalCitationRegistry so call sites can be swapped freely.
    """

    def __init__(self):
        self._base = _BaseRegistry()
        # Pull the base's private _REGISTRY and merge our additions
        from core.legal_gates import _REGISTRY as _BASE_REG
        self._laws: dict[str, CanonicalLaw] = dict(_BASE_REG)
        self._laws.update(_ADDITIONAL_LAWS)

        # Build alias index (longest alias first for specific match)
        self._alias_to_law: dict[str, str] = {}
        for law_id, law in self._laws.items():
            for alias in [law.title] + law.aliases:
                self._alias_to_law[alias] = law_id

    # ── public api ──

    def all_law_ids(self) -> list[str]:
        return list(self._laws.keys())

    def get_law(self, law_id: str) -> Optional[CanonicalLaw]:
        return self._laws.get(law_id)

    def domain_corpora(self, domain: LegalDomain) -> set[str]:
        """Return set of law_ids eligible for the given domain."""
        return set(_DOMAIN_TO_ALLOWED_IDS.get(domain, set()))

    def resolve_law(self, raw_law_text: str) -> Optional[CanonicalLaw]:
        """Longest-match alias → CanonicalLaw, or None."""
        if not raw_law_text:
            return None
        # Longest alias first
        for alias in sorted(self._alias_to_law.keys(), key=len, reverse=True):
            if alias in raw_law_text or raw_law_text in alias:
                return self._laws[self._alias_to_law[alias]]
        return None

    def verify(self, law_text: str, article_number: Optional[int],
                expected_domain: Optional[LegalDomain] = None
                ) -> CitationVerification:
        """Verify a citation against the canonical registry.

        Returns CitationVerification with confidence in
        {verified, partial, unverified}. The new evidence layer treats
        anything != 'verified' as REJECTED for statute citations.
        """
        v = CitationVerification(cited_text=law_text)
        law = self.resolve_law(law_text)
        if not law:
            v.confidence = "unverified"
            v.block_reason = "law_not_in_canonical_registry"
            return v

        v.matched_law_id = law.law_id

        # In-force check
        if law.status != "in_force":
            v.confidence = "unverified"
            v.block_reason = f"law_not_in_force:{law.status}"
            return v

        # Domain check
        if expected_domain and expected_domain != LegalDomain.UNKNOWN:
            allowed = self.domain_corpora(expected_domain)
            v.domain_match = law.law_id in allowed
            if not v.domain_match:
                v.confidence = "unverified"
                v.block_reason = (
                    f"domain_mismatch: law={law.law_id} "
                    f"expected={expected_domain.value}"
                )
                return v
        else:
            v.domain_match = True

        # Article check
        if article_number is not None:
            v.matched_article = article_number
            if law.article_min <= article_number <= law.article_max:
                v.confidence = "verified"
            else:
                v.confidence = "unverified"
                v.block_reason = (
                    f"article_out_of_range: {article_number} not in "
                    f"[{law.article_min},{law.article_max}] for {law.law_id}"
                )
        else:
            v.confidence = "partial"  # law OK but no article specified

        return v

    def is_law_in_force(self, law_id: str) -> bool:
        law = self._laws.get(law_id)
        return law is not None and law.status == "in_force"

    def coverage_stats(self) -> dict:
        """Self-report: how many laws per domain."""
        counts: dict[str, int] = {}
        for d in LegalDomain:
            if d == LegalDomain.UNKNOWN:
                continue
            counts[d.value] = len(self.domain_corpora(d))
        return {
            "total_laws": len(self._laws),
            "per_domain": counts,
        }


# ── module singleton ──

_registry: Optional[ExpandedCanonicalRegistry] = None


def get_canonical_registry() -> ExpandedCanonicalRegistry:
    global _registry
    if _registry is None:
        _registry = ExpandedCanonicalRegistry()
    return _registry
