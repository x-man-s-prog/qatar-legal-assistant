# -*- coding: utf-8 -*-
"""
Final Output Firewall — last-line defense.

Scans the user-facing text and removes:
  1. Legacy-style blocks (partner minutes, debt instruments, strategic
     boilerplate that leaks across cases)
  2. Raw technical telemetry (low_issue_coverage:0.25, chunk_id, scores, etc.)
  3. Internal reason codes
  4. Raw hypothesis-type enum values

Runs AFTER the MLRE composer, before the response goes to the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# Technical telemetry patterns that must NEVER reach the user
# ═════════════════════════════════════════════════════════════════

_TECHNICAL_PATTERNS = [
    # Reason codes like "low_issue_coverage:0.25"
    re.compile(r"\b(low_issue_coverage|no_bound_evidence|issue_graph_unavailable|"
                 r"no_primary_issue|insufficient_facts|claim_brief_needs_detailed_facts|"
                 r"engine_exception|fact_pattern_lacks_substance|"
                 r"classification_below_floor|no_legal_signals|domain_tie_low_confidence|"
                 r"evidence_insufficient|stage_e=\d+|rejected=\d+|composite=[\d.]+)\b"),
    # Raw hypothesis enum values
    re.compile(r"\b(primary_expected|closest_alternative|hybrid_cross_domain|"
                 r"defensive|aggressive|minimalist_civil|worst_case_exposure|"
                 r"edge_case)\b"),
    # Bare raw scores inline (like "composite: 0.123")
    re.compile(r"\b(score|composite|confidence)\s*[:=]\s*[\d.]+"),
    # Internal trace formats
    re.compile(r"\[TRACE[:].*?\]"),
    re.compile(r"\b(chunk_id|ruling_id)\s*[:=]\s*\d+", re.IGNORECASE),
    # MLRE trace bleed
    re.compile(r"\bMLRE\b[^.\n]*"),
    re.compile(r"\bHYPOTHESIS\b[^.\n]*", re.IGNORECASE),
]

# ═════════════════════════════════════════════════════════════════
# Legacy boilerplate blocks that appear out-of-context
# ═════════════════════════════════════════════════════════════════

_LEGACY_BOILERPLATE_BLOCKS = [
    # Strategic reasoning engine generic blocks
    "أقوى ما يدعمك:",
    "أبرز نقطة ضعف لديك:",
    "المسار المتوقع للطرف الآخر:",
    "الزوايا التي قد يستخدمها ضدك:",
    "محاضر اجتماعات الشركاء",
    "الاعتراف الكتابي + التحويلات البنكية",
    "سند دين موقّع",
    # Blocks that leak technical state
    "⚖️ التحليل القضائي:",
    "📊 السيناريوهات المحتملة:",
    "🎯 الدليل الحاسم الذي قد يغيّر القضية:",
    "🧭 التوصية الاستراتيجية:",
]

# Surface-phrase replacements (technical → user-safe)
_PHRASE_REPLACEMENTS = {
    "low_issue_coverage":      "الوقائع الحالية لا تكفي لحسم المسألة على نحو مسؤول",
    "no_bound_evidence":       "لا يوجد حتى الآن سند قانوني موثَّق يكفي لبناء تحليل دقيق",
    "insufficient_facts":      "الوقائع المذكورة غير كافية لتحليل قانوني مسؤول",
    "issue_graph_unavailable": "لم يتضح المجال القانوني للمسألة بدقة كافية",
}


@dataclass
class FirewallReport:
    cleaned_text:     str = ""
    removed_blocks:   int = 0
    scrubbed_telemetry: int = 0
    replaced_phrases: int = 0
    details:          list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "removed_blocks":     self.removed_blocks,
            "scrubbed_telemetry": self.scrubbed_telemetry,
            "replaced_phrases":   self.replaced_phrases,
            "details":            self.details[:5],
        }


def _strip_legacy_paragraphs(text: str, report: FirewallReport) -> str:
    """Remove paragraphs containing legacy boilerplate."""
    parts = text.split("\n\n")
    kept: list[str] = []
    for p in parts:
        found_legacy = False
        for marker in _LEGACY_BOILERPLATE_BLOCKS:
            if marker in p:
                report.removed_blocks += 1
                report.details.append(f"removed_block:{marker[:30]}")
                found_legacy = True
                break
        if not found_legacy:
            kept.append(p)
    return "\n\n".join(kept)


def _scrub_telemetry(text: str, report: FirewallReport) -> str:
    """Remove raw technical patterns."""
    cleaned = text
    for pat in _TECHNICAL_PATTERNS:
        matches = pat.findall(cleaned)
        if matches:
            report.scrubbed_telemetry += len(matches)
            cleaned = pat.sub("", cleaned)
    # Collapse whitespace created by removal
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _replace_phrases(text: str, report: FirewallReport) -> str:
    """Turn technical codes into user-safe Arabic."""
    out = text
    for code, phrase in _PHRASE_REPLACEMENTS.items():
        if code in out:
            out = out.replace(code, phrase)
            report.replaced_phrases += 1
    return out


def sanitize_user_output(text: str) -> FirewallReport:
    """Main entry: scrub output for the end user."""
    report = FirewallReport(cleaned_text=text or "")
    if not text:
        return report
    t = _replace_phrases(text, report)
    t = _strip_legacy_paragraphs(t, report)
    t = _scrub_telemetry(t, report)
    report.cleaned_text = t.strip()
    return report
