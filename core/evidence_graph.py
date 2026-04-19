# -*- coding: utf-8 -*-
"""
Evidence Graph + Cross-Domain Resolver
======================================
Adds semantic relationships between evidence entries and enables
cross-domain reasoning (e.g. salary + scope + special entities).
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
from core.evidence_registry import EvidenceEntry, EvidenceRegistry, SupportLevel, get_registry

log = logging.getLogger("evidence_graph")


# ══════════════════════════════════════════════════════════════
# Evidence Graph
# ══════════════════════════════════════════════════════════════

@dataclass
class EvidenceEdge:
    source_id: str
    target_id: str
    relation: str  # "supports", "contradicts", "refines", "requires"


class EvidenceGraph:
    """Graph of relationships between evidence entries."""

    def __init__(self, registry: EvidenceRegistry):
        self._registry = registry
        self._edges: list[EvidenceEdge] = []
        self._build_edges()

    def _build_edges(self):
        """Auto-discover relationships from tags and domains."""
        entries = list(self._registry._entries.values())
        for i, a in enumerate(entries):
            for b in entries[i + 1:]:
                rel = self._detect_relation(a, b)
                if rel:
                    self._edges.append(EvidenceEdge(a.entry_id, b.entry_id, rel))

    def _detect_relation(self, a: EvidenceEntry, b: EvidenceEntry) -> Optional[str]:
        a_tags = set(getattr(a, "tags", []) or [])
        b_tags = set(getattr(b, "tags", []) or [])
        overlap = a_tags & b_tags

        if not overlap:
            return None

        # Same topic, different support levels → refines
        if a.topic == b.topic and a.support_level != b.support_level:
            return "refines"

        # One is BLOCKED, other is DIRECT → contradicts (blocked claim vs stated fact)
        if (a.support_level == SupportLevel.UNSUPPORTED_BLOCKED.value and
                b.support_level == SupportLevel.DIRECT_EVIDENCE.value):
            return "contradicts"

        # Same domain, overlapping tags → supports
        if a.domain == b.domain and len(overlap) >= 1:
            return "supports"

        # Cross-domain with shared tags → requires (dependency)
        if a.domain != b.domain and len(overlap) >= 1:
            return "requires"

        return None

    def get_related(self, entry_id: str, max_results: int = 10) -> list[tuple[str, str]]:
        """Get related entries: list of (related_id, relation_type)."""
        results = []
        for edge in self._edges:
            if edge.source_id == entry_id:
                results.append((edge.target_id, edge.relation))
            elif edge.target_id == entry_id:
                results.append((edge.source_id, edge.relation))
        return results[:max_results]

    def find_strongest(self, topic: str) -> list[EvidenceEntry]:
        """Find the strongest evidence entries for a topic."""
        candidates = self._registry.get_by_topic(topic)
        # Sort: DIRECT first, then CONTROLLED, then BLOCKED
        order = {SupportLevel.DIRECT_EVIDENCE.value: 0,
                 SupportLevel.CONTROLLED_INFERENCE.value: 1,
                 SupportLevel.UNSUPPORTED_BLOCKED.value: 2}
        candidates.sort(key=lambda e: order.get(e.support_level, 3))
        return candidates

    def stats(self) -> dict:
        rels = {}
        for e in self._edges:
            rels[e.relation] = rels.get(e.relation, 0) + 1
        return {"edges": len(self._edges), "relations": rels}


# ══════════════════════════════════════════════════════════════
# Cross-Domain Resolver
# ══════════════════════════════════════════════════════════════

class CrossDomainResolver:
    """Resolves queries that span multiple domains."""

    def __init__(self, registry: EvidenceRegistry):
        self._registry = registry

    def detect_domains(self, query: str) -> list[str]:
        """Detect all domains a query touches."""
        q = query.lower()
        domains = []

        domain_signals = {
            "salary": ["راتب", "مربوط", "درجة", "رواتب", "جدول"],
            "allowance": ["بدل", "بدلات", "علاوة", "سكن", "نقل", "إجمالي"],
            "scope": ["جهة", "حكومي", "قطاع", "ينطبق", "يشمل", "نطاق"],
            "drug": ["مخدر", "مؤثر", "عقلي", "حشيش", "تعاطي"],
            "penalty": ["عقوبة", "حبس", "سجن", "غرامة", "إعدام", "جريمة"],
            "legal_principles": ["مبدأ", "قرينة", "براءة", "حق", "دستور"],
        }

        for domain, signals in domain_signals.items():
            if any(s in q for s in signals):
                domains.append(domain)

        return domains

    def gather_cross_domain(self, query: str) -> list[EvidenceEntry]:
        """Gather evidence from all relevant domains."""
        domains = self.detect_domains(query)
        all_evidence = []
        seen = set()

        for domain in domains:
            entries = self._registry.get_by_domain(domain)
            for e in entries:
                if e.entry_id not in seen:
                    seen.add(e.entry_id)
                    all_evidence.append(e)

        log.info("[CROSS_DOMAIN] domains=%s evidence=%d", domains, len(all_evidence))
        return all_evidence

    def merge_reasoning(self, evidence: list[EvidenceEntry], query: str) -> dict:
        """Merge evidence from multiple domains into a coherent reasoning summary."""
        domains = set(e.domain for e in evidence)
        direct = [e for e in evidence if e.support_level == SupportLevel.DIRECT_EVIDENCE.value]
        inferred = [e for e in evidence if e.support_level == SupportLevel.CONTROLLED_INFERENCE.value]
        blocked = [e for e in evidence if e.support_level == SupportLevel.UNSUPPORTED_BLOCKED.value]

        return {
            "domains_covered": sorted(domains),
            "total_evidence": len(evidence),
            "direct_count": len(direct),
            "inference_count": len(inferred),
            "blocked_count": len(blocked),
            "is_cross_domain": len(domains) > 1,
            "limitations": [b.statement_ar[:60] for b in blocked[:3]],
        }


# ══════════════════════════════════════════════════════════════
# Singleton access
# ══════════════════════════════════════════════════════════════

_graph: Optional[EvidenceGraph] = None
_resolver: Optional[CrossDomainResolver] = None


def get_graph() -> EvidenceGraph:
    global _graph
    if _graph is None:
        _graph = EvidenceGraph(get_registry())
    return _graph


def get_resolver() -> CrossDomainResolver:
    global _resolver
    if _resolver is None:
        _resolver = CrossDomainResolver(get_registry())
    return _resolver
