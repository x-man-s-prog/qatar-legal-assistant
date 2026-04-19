# -*- coding: utf-8 -*-
"""
Template Contamination Firewall.

Detects generic reused blocks that leak across unrelated cases:
  - "محاضر اجتماعات الشركاء" in non-partnership cases
  - "سند دين موقّع" in non-debt cases
  - "الاعتراف الكتابي + التحويلات البنكية" as generic catch-all
  - "أبرز نقطة ضعف لديك" in cases where no opponent analysis applies

Blocks contamination BEFORE output is returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# Contamination patterns — each with the domain(s) where it IS valid
# ═════════════════════════════════════════════════════════════════

@dataclass
class _ContaminationRule:
    name:            str           # rule id
    pattern:         str           # substring/regex to detect
    valid_domains:   set           # where this block is ALLOWED
    required_issue_tags: set = field(default_factory=set)   # must have these
    is_regex:        bool = False


_RULES: list[_ContaminationRule] = [
    _ContaminationRule(
        name="partner_minutes",
        pattern="محاضر اجتماعات الشركاء",
        valid_domains={"commercial"},
        required_issue_tags={"company_dispute", "partnership"},
    ),
    _ContaminationRule(
        name="debt_instrument",
        pattern="سند دين موقّع",
        valid_domains={"civil", "banking", "commercial"},
        required_issue_tags={"debt", "contract_breach"},
    ),
    _ContaminationRule(
        name="generic_witness_strength",
        pattern="الاعتراف الكتابي + التحويلات البنكية",
        valid_domains=set(),   # generic, never appropriate — always contamination
    ),
    _ContaminationRule(
        name="insult_in_non_criminal",
        pattern="شتمني في مكان عام",
        valid_domains={"criminal"},
    ),
    _ContaminationRule(
        name="insult_article_203_in_wrong_domain",
        pattern="المادة 203 من قانون العقوبات",
        valid_domains={"criminal"},
    ),
    _ContaminationRule(
        name="cheque_bank_auth",
        pattern="كشف حركة الحساب البنكي",
        valid_domains={"banking"},
        required_issue_tags={"bank_authorization", "unauthorized_transaction"},
    ),
    _ContaminationRule(
        name="rental_template_in_sale",
        pattern="إنذار إخلاء",
        valid_domains={"rental"},
    ),
    _ContaminationRule(
        name="inheritance_block_in_non_inheritance",
        pattern="نصيب من التركة",
        valid_domains={"inheritance", "family"},
    ),
]


@dataclass
class ContaminationReport:
    safe:               bool = True
    violations:         list[dict] = field(default_factory=list)
    cleaned_text:       str = ""
    removed_blocks:     int = 0

    def to_dict(self) -> dict:
        return {
            "safe":            self.safe,
            "violations":      self.violations[:5],
            "removed_blocks":  self.removed_blocks,
        }


class TemplateFirewall:
    """Scans text output against known contamination patterns."""

    def scan(self, text: str, domain: str, issue_tags: Optional[list[str]] = None
              ) -> ContaminationReport:
        report = ContaminationReport(cleaned_text=text)
        if not text:
            return report
        issue_tags_set = set(issue_tags or [])

        for rule in _RULES:
            if rule.is_regex:
                match = re.search(rule.pattern, text)
                found = bool(match)
            else:
                found = rule.pattern in text
            if not found:
                continue

            # Check if it IS allowed in this context
            domain_ok = (domain in rule.valid_domains) if rule.valid_domains else False
            tags_ok = (
                not rule.required_issue_tags
                or bool(rule.required_issue_tags & issue_tags_set)
            )
            if domain_ok and tags_ok:
                continue   # this usage is legitimate

            # CONTAMINATION detected
            report.safe = False
            report.violations.append({
                "rule":   rule.name,
                "pattern": rule.pattern[:40],
                "domain_ok": domain_ok,
                "tags_ok":   tags_ok,
                "this_domain": domain,
            })
            # Remove the offending block (paragraph-level)
            report.cleaned_text = self._strip_paragraph(
                report.cleaned_text, rule.pattern)
            report.removed_blocks += 1

        return report

    def _strip_paragraph(self, text: str, pattern: str) -> str:
        """Remove the paragraph containing the pattern."""
        parts = text.split("\n\n")
        cleaned = [p for p in parts if pattern not in p]
        return "\n\n".join(cleaned)


_firewall: Optional[TemplateFirewall] = None


def get_firewall() -> TemplateFirewall:
    global _firewall
    if _firewall is None:
        _firewall = TemplateFirewall()
    return _firewall


def scan_for_contamination(text: str, domain: str,
                             issue_tags: Optional[list[str]] = None
                             ) -> ContaminationReport:
    return get_firewall().scan(text, domain, issue_tags)
