# -*- coding: utf-8 -*-
"""
Advanced Legal Reasoning — Phase 4 Extension
=============================================
Extends the existing LegalReasoningEngine with:
  1. MultiStepReasoner — breaks complex queries into reasoning steps
  2. EvidenceWeighter — weights evidence by source authority
  3. LegalHierarchyResolver — resolves conflicts by legal hierarchy
  4. ConflictDetector — detects contradictions in evidence
  5. validate_reasoning_output — safety gate before final answer

DOES NOT replace existing engine. Integrates via ReasoningResult extension.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from core.evidence_registry import EvidenceEntry, SupportLevel, get_registry

log = logging.getLogger("advanced_reasoning")


# ══════════════════════════════════════════════════════════════
# Extended ReasoningResult fields (mixin, added to existing)
# ══════════════════════════════════════════════════════════════

@dataclass
class AdvancedReasoningData:
    """Extension fields for ReasoningResult — attached as .advanced"""
    reasoning_chain: list[str] = field(default_factory=list)
    weighted_evidence: list[dict] = field(default_factory=list)
    conflict_flags: list[dict] = field(default_factory=list)
    hierarchy_applied: bool = False
    hierarchy_resolution: str = ""
    reasoning_depth_score: float = 0.0   # 0-1: how deep the reasoning went
    cross_domain_links: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 1. Multi-Step Reasoner
# ══════════════════════════════════════════════════════════════

_LEGAL_HIERARCHY = [
    "دستور",         # Constitution — highest authority
    "قانون",          # Law / statute
    "مرسوم بقانون",  # Decree-law
    "مرسوم",         # Decree
    "قرار أميري",    # Amiri decision
    "قرار مجلس",     # Cabinet decision
    "قرار وزاري",    # Ministerial decision
    "لائحة تنفيذية", # Executive regulation
    "تعميم",         # Circular
]


class MultiStepReasoner:
    """Breaks complex queries into ordered reasoning steps."""

    def plan_steps(self, query: str, domain: str, topic: str,
                   evidence: list[EvidenceEntry]) -> list[str]:
        """Produce an ordered reasoning chain for the query."""
        q = query.lower()
        steps = []

        # Step 1: Identify the applicable legal framework
        laws = set(e.source_law for e in evidence if e.source_law)
        if laws:
            steps.append("تحديد الإطار القانوني: %s" % "، ".join(list(laws)[:3]))

        # Step 2: Cross-domain detection
        domains_touched = set(e.domain for e in evidence if e.domain)
        if len(domains_touched) > 1:
            steps.append("ربط متعدد المجالات: %s" % "، ".join(domains_touched))

        # Step 3: Domain-specific reasoning
        if domain == "salary":
            if "إجمالي" in q or "بدلات" in q:
                steps.append("تحديد مكونات الراتب: أساسي + بدلات")
                steps.append("تقييم: هل البدلات متوفرة في الجدول؟")
            if "ترقية" in q or "علاوة" in q:
                steps.append("تحديد شروط الترقية والعلاوة الدورية")

        if domain == "drug":
            if "تصنيف" in q:
                steps.append("تحديد الجدول الذي تندرج تحته المادة")
                steps.append("استنتاج التصنيف من موقع الإدراج")
            if "عقوبة" in q or "حكم" in q:
                steps.append("تحديد نوع الفعل المجرّم")
                steps.append("مطابقة العقوبة من نصوص القانون")

        # Step 4: Evidence sufficiency check
        direct_count = sum(1 for e in evidence
                           if e.support_level == SupportLevel.DIRECT_EVIDENCE.value)
        if direct_count == 0:
            steps.append("تنبيه: لا يوجد دليل مباشر — الإجابة ستكون محدودة")
        else:
            steps.append("تأكيد: %d مصدر مباشر متوفر" % direct_count)

        log.info("[MULTI_STEP] %d steps for: %s", len(steps), q[:40])
        return steps


# ══════════════════════════════════════════════════════════════
# 2. Evidence Weighter
# ══════════════════════════════════════════════════════════════

class EvidenceWeighter:
    """Weights evidence by source authority and relevance."""

    def weight(self, evidence: list[EvidenceEntry], query: str) -> list[dict]:
        """Score each evidence entry. Higher = more authoritative."""
        q = query.lower()
        weighted = []

        for e in evidence:
            score = 0.0

            # Support level weight
            if e.support_level == SupportLevel.DIRECT_EVIDENCE.value:
                score += 0.5
            elif e.support_level == SupportLevel.CONTROLLED_INFERENCE.value:
                score += 0.2

            # Source authority weight (legal hierarchy)
            source = (e.source_law or "").lower()
            for rank, name in enumerate(_LEGAL_HIERARCHY):
                if name in source:
                    score += 0.3 * (1.0 - rank / len(_LEGAL_HIERARCHY))
                    break

            # Topical relevance
            statement_words = set(re.findall(r"[\u0600-\u06FF]{3,}", e.statement_ar.lower()))
            query_words = set(re.findall(r"[\u0600-\u06FF]{3,}", q))
            if query_words:
                overlap = len(statement_words & query_words) / len(query_words)
                score += 0.2 * overlap

            weighted.append({
                "entry_id": e.entry_id,
                "statement": e.statement_ar[:80],
                "support_level": e.support_level,
                "weight": round(score, 3),
                "source": e.source_law[:50] if e.source_law else "",
            })

        weighted.sort(key=lambda x: x["weight"], reverse=True)
        return weighted


# ══════════════════════════════════════════════════════════════
# 3. Legal Hierarchy Resolver
# ══════════════════════════════════════════════════════════════

class LegalHierarchyResolver:
    """Resolves conflicts by applying legal source hierarchy."""

    def resolve(self, evidence: list[EvidenceEntry]) -> tuple[list[EvidenceEntry], str]:
        """
        If evidence items conflict, prefer the higher-authority source.
        Returns (resolved_evidence, resolution_note).
        """
        if len(evidence) < 2:
            return evidence, ""

        # Group by source rank
        ranked = []
        for e in evidence:
            rank = self._get_rank(e.source_law or "")
            ranked.append((rank, e))

        ranked.sort(key=lambda x: x[0])

        # Check for conflicting statements between different ranks
        top_rank = ranked[0][0]
        top_entries = [e for r, e in ranked if r == top_rank]
        lower_entries = [e for r, e in ranked if r > top_rank]

        if lower_entries:
            resolution = "تم تطبيق التدرج القانوني: %s أولى من %s" % (
                (top_entries[0].source_law or "")[:30],
                (lower_entries[0].source_law or "")[:30],
            )
            log.info("[HIERARCHY] %s", resolution)
            return top_entries + lower_entries, resolution

        return evidence, ""

    def _get_rank(self, source_law: str) -> int:
        s = source_law.lower()
        for i, name in enumerate(_LEGAL_HIERARCHY):
            if name in s:
                return i
        return len(_LEGAL_HIERARCHY)


# ══════════════════════════════════════════════════════════════
# 4. Conflict Detector
# ══════════════════════════════════════════════════════════════

_NEGATION_PAIRS = [
    ("يحق", "لا يحق"), ("يجوز", "لا يجوز"), ("يشمل", "لا يشمل"),
    ("يستحق", "لا يستحق"), ("ينطبق", "لا ينطبق"),
    ("يسري", "لا يسري"), ("ملزم", "غير ملزم"),
]


class ConflictDetector:
    """Detects contradictions between evidence entries."""

    def detect(self, evidence: list[EvidenceEntry]) -> list[dict]:
        """Find conflicting evidence pairs."""
        conflicts = []
        for i, a in enumerate(evidence):
            for b in evidence[i + 1:]:
                if a.domain != b.domain:
                    continue
                conflict = self._check_conflict(a, b)
                if conflict:
                    conflicts.append(conflict)
        if conflicts:
            log.warning("[CONFLICT] %d conflicts detected", len(conflicts))
        return conflicts

    def _check_conflict(self, a: EvidenceEntry, b: EvidenceEntry) -> Optional[dict]:
        sa = a.statement_ar.lower()
        sb = b.statement_ar.lower()

        for pos, neg in _NEGATION_PAIRS:
            if (pos in sa and neg in sb) or (neg in sa and pos in sb):
                return {
                    "type": "negation",
                    "entry_a": a.entry_id,
                    "entry_b": b.entry_id,
                    "statement_a": a.statement_ar[:60],
                    "statement_b": b.statement_ar[:60],
                    "severity": "major",
                }
        return None


# ══════════════════════════════════════════════════════════════
# 5. Safety Validation Gate
# ══════════════════════════════════════════════════════════════

def validate_reasoning_output(result) -> list[str]:
    """
    Final safety check on reasoning output before it reaches answer construction.
    Returns list of issues (empty = safe).
    """
    issues = []

    # Check: no unsupported claims leaked into direct evidence
    if hasattr(result, "blocked_unsupported_claims") and result.blocked_unsupported_claims:
        for blocked in result.blocked_unsupported_claims:
            statement = blocked.statement_ar if hasattr(blocked, "statement_ar") else str(blocked)
            # Check if blocked claim somehow appears in the answer plan
            for step in getattr(result, "answer_plan", []):
                if isinstance(step, str) and statement[:20] in step:
                    issues.append("blocked claim leaked into plan: %s" % statement[:40])

    # Check: conflicts exist but no resolution
    adv = getattr(result, "advanced", None)
    if adv and adv.conflict_flags and not adv.hierarchy_applied:
        issues.append("unresolved conflicts in evidence (%d)" % len(adv.conflict_flags))

    # Check: zero evidence but non-refusal mode
    if (not getattr(result, "direct_evidence", [])
            and not getattr(result, "controlled_inferences", [])
            and getattr(result, "final_answer_mode", "") not in ("refusal", "deterministic")):
        issues.append("no evidence but answer mode is not refusal")

    if issues:
        log.warning("[VALIDATE] %d issues: %s", len(issues), issues[:3])
    return issues


# ══════════════════════════════════════════════════════════════
# 6. Integration Function — enhances existing ReasoningResult
# ══════════════════════════════════════════════════════════════

def enhance_reasoning(result, query: str = "") -> None:
    """
    Run advanced reasoning on an existing ReasoningResult object.
    Adds .advanced field with extended analysis.
    Modifies in place.
    """
    adv = AdvancedReasoningData()

    # Collect all EvidenceEntry objects
    all_evidence = []
    for e in getattr(result, "direct_evidence", []):
        if isinstance(e, EvidenceEntry):
            all_evidence.append(e)
    for e in getattr(result, "controlled_inferences", []):
        if isinstance(e, EvidenceEntry):
            all_evidence.append(e)
    for e in getattr(result, "blocked_unsupported_claims", []):
        if isinstance(e, EvidenceEntry):
            all_evidence.append(e)

    # 1. Multi-step reasoning
    reasoner = MultiStepReasoner()
    adv.reasoning_chain = reasoner.plan_steps(
        query, getattr(result, "domain", ""),
        getattr(result, "topic", ""), all_evidence,
    )

    # 2. Evidence weighting
    weighter = EvidenceWeighter()
    adv.weighted_evidence = weighter.weight(all_evidence, query)

    # 3. Conflict detection
    detector = ConflictDetector()
    adv.conflict_flags = detector.detect(all_evidence)

    # 4. Hierarchy resolution (if conflicts exist)
    if adv.conflict_flags:
        resolver = LegalHierarchyResolver()
        resolved, resolution = resolver.resolve(all_evidence)
        if resolution:
            adv.hierarchy_applied = True
            adv.hierarchy_resolution = resolution

    # 5. Depth score
    depth = 0.0
    if adv.reasoning_chain:
        depth += min(len(adv.reasoning_chain) / 5, 0.4)
    if adv.weighted_evidence:
        depth += min(len(adv.weighted_evidence) / 10, 0.3)
    if adv.hierarchy_applied:
        depth += 0.2
    if not adv.conflict_flags:
        depth += 0.1
    adv.reasoning_depth_score = round(min(depth, 1.0), 2)

    # 6. Cross-domain links
    domains = set(e.domain for e in all_evidence if hasattr(e, "domain") and e.domain)
    if len(domains) > 1:
        adv.cross_domain_links = list(domains)

    # Attach to result
    result.advanced = adv

    # 7. Safety validation
    issues = validate_reasoning_output(result)
    if issues:
        result.warnings = getattr(result, "warnings", []) + issues

    log.info("[ADV_REASON] depth=%.2f chain=%d conflicts=%d hierarchy=%s",
             adv.reasoning_depth_score, len(adv.reasoning_chain),
             len(adv.conflict_flags), adv.hierarchy_applied)
