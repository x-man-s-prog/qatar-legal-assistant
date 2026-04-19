# -*- coding: utf-8 -*-
"""
Knowledge Governance + Production Hardening + Commercial Readiness
==================================================================
1. KnowledgeMemoryGovernor — approve/deprecate/supersede knowledge
2. EvidenceLifecycleManager — track evidence from ingestion to retirement
3. LawUpdateSafetyChecker — detect impact when laws change
4. ProductionSafetyGuard — block unsafe output in production
5. CommercialPolicyGate — control answer wording for different user tiers
"""
from __future__ import annotations
import json, logging, threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger("governance")

_DATA_DIR = Path("/app/data/governance")


# ══════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════

class KnowledgeState(str, Enum):
    APPROVED = "approved"
    PENDING = "pending_review"
    DEPRECATED = "deprecated"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"


class EvidenceState(str, Enum):
    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    CONFLICTED = "conflicted"


class UserTier(str, Enum):
    INTERNAL_DEBUG = "internal_debug"
    PROFESSIONAL = "professional_user"
    PUBLIC = "public_user"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ══════════════════════════════════════════════════════════════
# 1. Knowledge Memory Governor
# ══════════════════════════════════════════════════════════════

@dataclass
class KnowledgeStateRecord:
    knowledge_id: str
    title: str = ""
    domain: str = ""
    source_law: str = ""
    source_article: str = ""
    state: str = KnowledgeState.APPROVED.value
    effective_date: str = ""
    superseded_by: str = ""
    review_status: str = ""
    reviewer_notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class KnowledgeMemoryGovernor:

    def __init__(self):
        self._records: dict[str, KnowledgeStateRecord] = {}
        self._lock = threading.Lock()

    def approve(self, kid: str, title: str = "", domain: str = "",
                source_law: str = "", source_article: str = "") -> KnowledgeStateRecord:
        now = datetime.now(timezone.utc).isoformat()
        rec = KnowledgeStateRecord(
            knowledge_id=kid, title=title, domain=domain,
            source_law=source_law, source_article=source_article,
            state=KnowledgeState.APPROVED.value,
            created_at=now, updated_at=now)
        with self._lock:
            self._records[kid] = rec
        log.info("[GOVERN] approved: %s", kid)
        return rec

    def deprecate(self, kid: str, reason: str = "") -> bool:
        with self._lock:
            rec = self._records.get(kid)
            if not rec:
                return False
            rec.state = KnowledgeState.DEPRECATED.value
            rec.reviewer_notes = reason
            rec.updated_at = datetime.now(timezone.utc).isoformat()
        log.info("[GOVERN] deprecated: %s reason=%s", kid, reason[:40])
        return True

    def mark_disputed(self, kid: str, reason: str = "") -> bool:
        with self._lock:
            rec = self._records.get(kid)
            if not rec:
                return False
            rec.state = KnowledgeState.DISPUTED.value
            rec.reviewer_notes = reason
            rec.updated_at = datetime.now(timezone.utc).isoformat()
        log.info("[GOVERN] disputed: %s", kid)
        return True

    def supersede(self, old_kid: str, new_kid: str) -> bool:
        with self._lock:
            rec = self._records.get(old_kid)
            if not rec:
                return False
            rec.state = KnowledgeState.SUPERSEDED.value
            rec.superseded_by = new_kid
            rec.updated_at = datetime.now(timezone.utc).isoformat()
        log.info("[GOVERN] superseded: %s → %s", old_kid, new_kid)
        return True

    def get_active(self, domain: str = "") -> list[KnowledgeStateRecord]:
        with self._lock:
            recs = [r for r in self._records.values()
                    if r.state == KnowledgeState.APPROVED.value]
            if domain:
                recs = [r for r in recs if r.domain == domain]
        return recs

    def get_history(self, kid: str) -> Optional[KnowledgeStateRecord]:
        return self._records.get(kid)

    def is_usable(self, kid: str) -> bool:
        rec = self._records.get(kid)
        if not rec:
            return True  # Unknown = allowed (not yet governed)
        return rec.state in (KnowledgeState.APPROVED.value, KnowledgeState.PENDING.value)


# ══════════════════════════════════════════════════════════════
# 2. Evidence Lifecycle Manager
# ══════════════════════════════════════════════════════════════

@dataclass
class EvidenceLifecycleRecord:
    evidence_id: str
    state: str = EvidenceState.ACTIVE.value
    superseded_by: str = ""
    deprecation_reason: str = ""
    conflict_details: str = ""
    last_reviewed: str = ""
    created_at: str = ""


class EvidenceLifecycleManager:

    def __init__(self):
        self._records: dict[str, EvidenceLifecycleRecord] = {}

    def activate(self, eid: str) -> EvidenceLifecycleRecord:
        now = datetime.now(timezone.utc).isoformat()
        rec = EvidenceLifecycleRecord(evidence_id=eid, state=EvidenceState.ACTIVE.value, created_at=now)
        self._records[eid] = rec
        return rec

    def deprecate(self, eid: str, reason: str = "") -> bool:
        rec = self._records.get(eid)
        if not rec:
            rec = EvidenceLifecycleRecord(evidence_id=eid)
            self._records[eid] = rec
        rec.state = EvidenceState.DEPRECATED.value
        rec.deprecation_reason = reason
        return True

    def retire(self, eid: str) -> bool:
        rec = self._records.get(eid)
        if rec:
            rec.state = EvidenceState.RETIRED.value
            return True
        return False

    def mark_conflicted(self, eid: str, details: str = "") -> bool:
        rec = self._records.get(eid)
        if not rec:
            rec = EvidenceLifecycleRecord(evidence_id=eid)
            self._records[eid] = rec
        rec.state = EvidenceState.CONFLICTED.value
        rec.conflict_details = details
        return True

    def is_active(self, eid: str) -> bool:
        rec = self._records.get(eid)
        if not rec:
            return True  # Unknown = active by default
        return rec.state == EvidenceState.ACTIVE.value

    def is_deprecated(self, eid: str) -> bool:
        rec = self._records.get(eid)
        return rec is not None and rec.state == EvidenceState.DEPRECATED.value

    def get_state(self, eid: str) -> str:
        rec = self._records.get(eid)
        return rec.state if rec else EvidenceState.ACTIVE.value


# ══════════════════════════════════════════════════════════════
# 3. Law Update Safety Checker
# ══════════════════════════════════════════════════════════════

@dataclass
class LawUpdateImpactReport:
    law_name: str = ""
    law_number: str = ""
    affected_domains: list[str] = field(default_factory=list)
    affected_packs: list[str] = field(default_factory=list)
    affected_evidence_ids: list[str] = field(default_factory=list)
    impacted_topics: list[str] = field(default_factory=list)
    risk_level: str = RiskLevel.LOW.value
    required_actions: list[str] = field(default_factory=list)


class LawUpdateSafetyChecker:

    def __init__(self, registry):
        self._registry = registry

    def simulate_law_change(self, law_name: str, law_number: str = "") -> LawUpdateImpactReport:
        report = LawUpdateImpactReport(law_name=law_name, law_number=law_number)
        entries = list(self._registry._entries.values())

        for e in entries:
            src = (e.source_law or "").lower()
            if law_name.lower()[:20] in src or (law_number and law_number in src):
                report.affected_evidence_ids.append(e.entry_id)
                if e.domain and e.domain not in report.affected_domains:
                    report.affected_domains.append(e.domain)
                if e.topic and e.topic not in report.impacted_topics:
                    report.impacted_topics.append(e.topic)
                if e.source_pack and e.source_pack not in report.affected_packs:
                    report.affected_packs.append(e.source_pack)

        count = len(report.affected_evidence_ids)
        if count >= 10:
            report.risk_level = RiskLevel.HIGH.value
            report.required_actions.append("مراجعة شاملة لجميع المعلومات المتأثرة")
        elif count >= 3:
            report.risk_level = RiskLevel.MEDIUM.value
            report.required_actions.append("مراجعة المعلومات المتأثرة")
        else:
            report.risk_level = RiskLevel.LOW.value

        if count > 0:
            report.required_actions.append("تحديث حزم المعرفة المتأثرة")

        log.info("[LAW_UPDATE] %s: %d entries affected, risk=%s",
                 law_name[:30], count, report.risk_level)
        return report


# ══════════════════════════════════════════════════════════════
# 4. Production Safety Guard
# ══════════════════════════════════════════════════════════════

@dataclass
class ProductionSafetyResult:
    safe: bool = True
    violations: list[str] = field(default_factory=list)
    blocked: bool = False


class ProductionSafetyGuard:

    def __init__(self, lifecycle: EvidenceLifecycleManager = None):
        self._lifecycle = lifecycle or EvidenceLifecycleManager()

    def check(self, reasoning_result, answer: str, audit=None) -> ProductionSafetyResult:
        result = ProductionSafetyResult()

        # Rule 1: No deprecated evidence used as direct basis
        for e in getattr(reasoning_result, "direct_evidence", []):
            eid = e.entry_id if hasattr(e, "entry_id") else ""
            if self._lifecycle.is_deprecated(eid):
                result.violations.append(f"deprecated evidence used: {eid}")

        # Rule 2: No blocked claims leaked
        blocked = getattr(reasoning_result, "blocked_unsupported_claims", [])
        for b in blocked:
            stmt = b.statement_ar[:30] if hasattr(b, "statement_ar") else str(b)[:30]
            if stmt in answer:
                result.violations.append(f"blocked claim in answer: {stmt}")

        # Rule 3: Disputed evidence must have qualification
        for e in getattr(reasoning_result, "direct_evidence", []):
            eid = e.entry_id if hasattr(e, "entry_id") else ""
            if self._lifecycle.get_state(eid) == EvidenceState.CONFLICTED.value:
                if "تعارض" not in answer and "لا يمكن الجزم" not in answer:
                    result.violations.append(f"conflicted evidence without qualification: {eid}")

        # Rule 4: Audit trail must exist
        if audit is None:
            result.violations.append("no audit trail attached")

        result.safe = len(result.violations) == 0
        result.blocked = any("blocked claim" in v for v in result.violations)

        if not result.safe:
            log.warning("[PROD_SAFETY] %d violations: %s", len(result.violations), result.violations[:3])
        return result


# ══════════════════════════════════════════════════════════════
# 5. Commercial Policy Gate
# ══════════════════════════════════════════════════════════════

_CERTAINTY_SOFTENERS = {
    "بالتأكيد": "بناءً على النصوص المتاحة",
    "حتماً": "على الأرجح",
    "قطعاً": "وفقاً للمصادر المتوفرة",
}


class CommercialPolicyGate:

    def apply(self, answer: str, decision_result, mode: UserTier) -> str:
        if mode == UserTier.INTERNAL_DEBUG:
            return answer  # Full answer with all metadata

        if mode == UserTier.PUBLIC:
            # Strip all certainty language, add general disclaimer
            for old, new in _CERTAINTY_SOFTENERS.items():
                answer = answer.replace(old, new)
            # Auto-downgrade high-risk for public
            if hasattr(decision_result, "confidence") and decision_result.confidence.final_score < 0.5:
                answer = answer.rstrip() + "\n\nهذه معلومات عامة وليست استشارة قانونية. يُنصح بمراجعة محامٍ مختص."

        elif mode == UserTier.PROFESSIONAL:
            # Qualified professional wording — keep detail but soften absolutes
            for old, new in _CERTAINTY_SOFTENERS.items():
                answer = answer.replace(old, new)

        return answer


# ══════════════════════════════════════════════════════════════
# Singletons
# ══════════════════════════════════════════════════════════════

_governor: Optional[KnowledgeMemoryGovernor] = None
_lifecycle: Optional[EvidenceLifecycleManager] = None


def get_governor() -> KnowledgeMemoryGovernor:
    global _governor
    if _governor is None:
        _governor = KnowledgeMemoryGovernor()
    return _governor


def get_lifecycle() -> EvidenceLifecycleManager:
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = EvidenceLifecycleManager()
    return _lifecycle
