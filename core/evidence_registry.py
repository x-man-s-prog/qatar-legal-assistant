# -*- coding: utf-8 -*-
"""
Evidence Registry — Central Trust Layer
========================================
Tracks every reusable knowledge statement with metadata including:
- source type, support level, originating law/table/article
- whether it is direct evidence or controlled inference
- confidence rationale, update status

Support Levels:
  DIRECT_EVIDENCE      — explicitly present in law text / schedule / verified data
  CONTROLLED_INFERENCE — reasonable interpretation, concise, safe, clearly limited
  UNSUPPORTED_BLOCKED  — not strong enough to state; must be blocked or softened

The registry acts as a trust layer: legal answers draw from it,
reused reasoning is traceable, unsupported claims are blocked.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("evidence_registry")


# ══════════════════════════════════════════════════════════════
# Support Level Enum
# ══════════════════════════════════════════════════════════════

class SupportLevel(str, Enum):
    DIRECT_EVIDENCE = "direct_evidence"
    CONTROLLED_INFERENCE = "controlled_inference"
    UNSUPPORTED_BLOCKED = "unsupported_blocked"


# ══════════════════════════════════════════════════════════════
# Evidence Entry
# ══════════════════════════════════════════════════════════════

@dataclass
class EvidenceEntry:
    """A single reusable knowledge statement with full provenance."""
    entry_id: str                          # unique stable ID
    statement_ar: str                      # Arabic text of the statement
    statement_en: str = ""                 # Optional English translation
    domain: str = ""                       # "salary", "drug", "scope", "penalty", ...
    topic: str = ""                        # sub-topic within domain
    support_level: str = SupportLevel.DIRECT_EVIDENCE.value
    source_type: str = ""                  # "law_text", "salary_table", "schedule", "regulation", ...
    source_law: str = ""                   # originating law name
    source_article: str = ""               # article/section reference
    source_table: str = ""                 # table reference if applicable
    source_pack: str = ""                  # knowledge pack that contributed this
    confidence_rationale: str = ""         # why we believe this
    conditions: list = field(default_factory=list)   # when this applies
    limitations: list = field(default_factory=list)  # when this does NOT apply
    related_entries: list = field(default_factory=list)  # IDs of related evidence
    tags: list = field(default_factory=list)
    version: str = "1.0"
    created_at: str = ""
    updated_at: str = ""
    verified: bool = True

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def is_direct(self) -> bool:
        return self.support_level == SupportLevel.DIRECT_EVIDENCE.value

    def is_inference(self) -> bool:
        return self.support_level == SupportLevel.CONTROLLED_INFERENCE.value

    def is_blocked(self) -> bool:
        return self.support_level == SupportLevel.UNSUPPORTED_BLOCKED.value

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════
# Evidence Registry
# ══════════════════════════════════════════════════════════════

class EvidenceRegistry:
    """
    Central registry of verified knowledge statements.

    Thread-safe, in-memory with optional persistence.
    Acts as the trust backbone for the reasoning engine.
    """

    def __init__(self):
        self._entries: dict[str, EvidenceEntry] = {}
        self._domain_index: dict[str, list[str]] = {}  # domain → [entry_ids]
        self._topic_index: dict[str, list[str]] = {}    # topic → [entry_ids]
        self._tag_index: dict[str, list[str]] = {}      # tag → [entry_ids]
        self._lock = threading.Lock()
        self._loaded_packs: set[str] = set()

    # ── Registration ──────────────────────────────────────────

    def register(self, entry: EvidenceEntry) -> None:
        """Register or update an evidence entry."""
        with self._lock:
            self._entries[entry.entry_id] = entry
            # Index by domain
            self._domain_index.setdefault(entry.domain, [])
            if entry.entry_id not in self._domain_index[entry.domain]:
                self._domain_index[entry.domain].append(entry.entry_id)
            # Index by topic
            if entry.topic:
                self._topic_index.setdefault(entry.topic, [])
                if entry.entry_id not in self._topic_index[entry.topic]:
                    self._topic_index[entry.topic].append(entry.entry_id)
            # Index by tags
            for tag in entry.tags:
                self._tag_index.setdefault(tag, [])
                if entry.entry_id not in self._tag_index[tag]:
                    self._tag_index[tag].append(entry.entry_id)

    def register_many(self, entries: list[EvidenceEntry]) -> int:
        """Register multiple entries. Returns count registered."""
        for e in entries:
            self.register(e)
        return len(entries)

    # ── Lookup ────────────────────────────────────────────────

    def get(self, entry_id: str) -> Optional[EvidenceEntry]:
        """Get entry by ID."""
        return self._entries.get(entry_id)

    def get_by_domain(self, domain: str) -> list[EvidenceEntry]:
        """Get all entries for a domain."""
        ids = self._domain_index.get(domain, [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    def get_by_topic(self, topic: str) -> list[EvidenceEntry]:
        """Get all entries for a topic."""
        ids = self._topic_index.get(topic, [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    def get_by_tag(self, tag: str) -> list[EvidenceEntry]:
        """Get all entries with a specific tag."""
        ids = self._tag_index.get(tag, [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    def get_direct_evidence(self, domain: str = "", topic: str = "") -> list[EvidenceEntry]:
        """Get only DIRECT_EVIDENCE entries, optionally filtered."""
        candidates = self._entries.values()
        if domain:
            candidates = [e for e in candidates if e.domain == domain]
        if topic:
            candidates = [e for e in candidates if e.topic == topic]
        return [e for e in candidates if e.is_direct()]

    def get_inferences(self, domain: str = "", topic: str = "") -> list[EvidenceEntry]:
        """Get only CONTROLLED_INFERENCE entries."""
        candidates = self._entries.values()
        if domain:
            candidates = [e for e in candidates if e.domain == domain]
        if topic:
            candidates = [e for e in candidates if e.topic == topic]
        return [e for e in candidates if e.is_inference()]

    def get_blocked(self, domain: str = "") -> list[EvidenceEntry]:
        """Get UNSUPPORTED_BLOCKED entries — claims that must NOT be stated."""
        candidates = self._entries.values()
        if domain:
            candidates = [e for e in candidates if e.domain == domain]
        return [e for e in candidates if e.is_blocked()]

    def search(self, query: str, domain: str = "", max_results: int = 20) -> list[EvidenceEntry]:
        """Simple keyword search over statement text."""
        q = query.lower().strip()
        results = []
        for e in self._entries.values():
            if domain and e.domain != domain:
                continue
            text = (e.statement_ar + " " + e.statement_en + " " + " ".join(e.tags)).lower()
            if q in text:
                results.append(e)
                if len(results) >= max_results:
                    break
        return results

    # ── Verification ──────────────────────────────────────────

    def is_claim_supported(self, claim_text: str, domain: str = "") -> tuple[bool, Optional[EvidenceEntry]]:
        """
        Check if a claim is supported by registry evidence.
        Returns (is_supported, matching_entry_or_None).
        """
        q = claim_text.lower().strip()
        for e in self._entries.values():
            if domain and e.domain != domain:
                continue
            if e.is_blocked():
                # Check if claim matches a blocked statement
                if q in e.statement_ar.lower() or e.statement_ar.lower() in q:
                    return False, e
            if e.is_direct() or e.is_inference():
                if q in e.statement_ar.lower() or e.statement_ar.lower() in q:
                    return True, e
        return False, None

    def is_claim_blocked(self, claim_text: str, domain: str = "") -> tuple[bool, Optional[EvidenceEntry]]:
        """Check if a claim is explicitly blocked."""
        q = claim_text.lower().strip()
        for e in self.get_blocked(domain):
            if q in e.statement_ar.lower() or e.statement_ar.lower() in q:
                return True, e
        return False, None

    # ── Pack Management ───────────────────────────────────────

    def load_pack(self, pack_name: str, entries: list[EvidenceEntry]) -> int:
        """Load entries from a named knowledge pack. Returns count."""
        if pack_name in self._loaded_packs:
            log.info("[REGISTRY] pack '%s' already loaded, skipping", pack_name)
            return 0
        for e in entries:
            e.source_pack = pack_name
            self.register(e)
        self._loaded_packs.add(pack_name)
        log.info("[REGISTRY] loaded pack '%s': %d entries", pack_name, len(entries))
        return len(entries)

    def loaded_packs(self) -> list[str]:
        return sorted(self._loaded_packs)

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return registry statistics."""
        by_support = {}
        by_domain = {}
        for e in self._entries.values():
            by_support[e.support_level] = by_support.get(e.support_level, 0) + 1
            by_domain[e.domain] = by_domain.get(e.domain, 0) + 1
        return {
            "total_entries": len(self._entries),
            "by_support_level": by_support,
            "by_domain": by_domain,
            "loaded_packs": sorted(self._loaded_packs),
            "domains": sorted(self._domain_index.keys()),
            "topics": sorted(self._topic_index.keys()),
        }

    # ── Persistence ───────────────────────────────────────────

    def export_json(self, path: str) -> int:
        """Export all entries to JSON file."""
        data = [e.to_dict() for e in self._entries.values()]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return len(data)

    def import_json(self, path: str) -> int:
        """Import entries from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for d in data:
            try:
                entry = EvidenceEntry(**d)
                self.register(entry)
                count += 1
            except Exception as ex:
                log.warning("[REGISTRY] skip bad entry: %s", ex)
        return count


# ══════════════════════════════════════════════════════════════
# Global singleton
# ══════════════════════════════════════════════════════════════

_REGISTRY: Optional[EvidenceRegistry] = None
_INIT_LOCK = threading.Lock()


def get_registry() -> EvidenceRegistry:
    """Get or create the global evidence registry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        with _INIT_LOCK:
            if _REGISTRY is None:
                _REGISTRY = EvidenceRegistry()
                _bootstrap_registry(_REGISTRY)
    return _REGISTRY


def _bootstrap_registry(registry: EvidenceRegistry) -> None:
    """Load all knowledge packs into the registry at startup."""
    try:
        from core.knowledge_packs.salary_pack import get_salary_entries
        registry.load_pack("salary_v1", get_salary_entries())
    except Exception as ex:
        log.warning("[REGISTRY] salary pack load failed: %s", ex)

    try:
        from core.knowledge_packs.drug_pack import get_drug_entries
        registry.load_pack("drug_v1", get_drug_entries())
    except Exception as ex:
        log.warning("[REGISTRY] drug pack load failed: %s", ex)

    try:
        from core.knowledge_packs.scope_pack import get_scope_entries
        registry.load_pack("scope_v1", get_scope_entries())
    except Exception as ex:
        log.warning("[REGISTRY] scope pack load failed: %s", ex)

    try:
        from core.knowledge_packs.reasoning_pack import get_reasoning_entries
        registry.load_pack("reasoning_v1", get_reasoning_entries())
    except Exception as ex:
        log.warning("[REGISTRY] reasoning pack load failed: %s", ex)


    try:
        from core.knowledge_packs.penalty_pack import get_penalty_entries
        registry.load_pack("penalty_v1", get_penalty_entries())
    except Exception as ex:
        log.warning("[REGISTRY] penalty pack load failed: %s", ex)

    try:
        from core.knowledge_packs.allowance_pack import get_allowance_entries
        registry.load_pack("allowance_v1", get_allowance_entries())
    except Exception as ex:
        log.warning("[REGISTRY] allowance pack load failed: %s", ex)

    try:
        from core.knowledge_packs.legal_principles_pack import get_legal_principles_entries
        registry.load_pack("legal_principles_v1", get_legal_principles_entries())
    except Exception as ex:
        log.warning("[REGISTRY] legal_principles pack load failed: %s", ex)

    log.info("[REGISTRY] bootstrap complete: %s", registry.stats())
