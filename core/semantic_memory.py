# -*- coding: utf-8 -*-
"""
Semantic Memory Engine
=======================
Maintains structured semantic context across conversation turns.
Extracts facts, entities, timeline markers, and risk signals from user queries.
Provides safe context retrieval for follow-up understanding.

Internal only — never exposed to the user.
Evidence-bound — never invents facts.
Reversible — facts can be retracted or overridden.
"""
from __future__ import annotations
import re, logging, time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("semantic_memory")


# ══════════════════════════════════════════════════════════════
# Fact Confidence Model
# ══════════════════════════════════════════════════════════════

class FactType(str, Enum):
    USER_STATED_CONFIRMED = "user_stated_confirmed"
    USER_STATED_AMBIGUOUS = "user_stated_ambiguous"
    SYSTEM_INFERRED_LOW = "system_inferred_low"
    SYSTEM_INFERRED_CONTROLLED = "system_inferred_controlled"
    UNRESOLVED = "unresolved"


@dataclass
class FactRecord:
    fact_id: str = ""
    text: str = ""
    fact_type: FactType = FactType.UNRESOLVED
    domain: str = ""
    entity_refs: list[str] = field(default_factory=list)
    source_turn: int = 0
    confidence: float = 0.0
    can_be_used_for_answer: bool = False
    requires_reconfirmation: bool = False
    superseded_by: str = ""  # fact_id of newer conflicting fact
    created_at: float = field(default_factory=time.time)

    def is_usable(self) -> bool:
        return (self.can_be_used_for_answer
                and not self.superseded_by
                and self.fact_type in (
                    FactType.USER_STATED_CONFIRMED,
                    FactType.SYSTEM_INFERRED_CONTROLLED))


# ══════════════════════════════════════════════════════════════
# Semantic Memory State
# ══════════════════════════════════════════════════════════════

@dataclass
class SemanticMemoryState:
    session_id: str = ""
    turn_count: int = 0
    active_domain: str = ""
    active_subdomain: str = ""
    active_entities: dict[str, str] = field(default_factory=dict)
    established_facts: list[FactRecord] = field(default_factory=list)
    pending_unknowns: list[str] = field(default_factory=list)
    active_timeline_markers: list[str] = field(default_factory=list)
    active_risk_markers: list[str] = field(default_factory=list)
    prior_guidance_state: str = ""
    prior_guardrail_state: str = ""
    last_user_goal: str = ""
    confidence: float = 0.0
    domain_history: list[str] = field(default_factory=list)
    notes_internal: list[str] = field(default_factory=list)

    def usable_facts(self) -> list[FactRecord]:
        return [f for f in self.established_facts if f.is_usable()]

    def facts_for_domain(self, domain: str) -> list[FactRecord]:
        return [f for f in self.usable_facts() if f.domain == domain or f.domain == ""]


# ══════════════════════════════════════════════════════════════
# Entity / Fact Extraction (Deterministic)
# ══════════════════════════════════════════════════════════════

_DOMAIN_KEYWORDS = {
    "employment": [
        "فصل", "فصلوني", "طردوني", "استقالة", "عقد عمل", "عقدي", "راتب",
        "مكافأة", "شغل", "وظيفة", "كفيل", "شركة", "مديري", "الدوام",
        "إذن خروج", "نقل كفالة", "استقلت", "تفصلني",
    ],
    "criminal": [
        "متهم", "تهمة", "شرطة", "نيابة", "مخدرات", "سرقة", "ضرب",
        "حكم", "سجن", "ابتزاز", "قضية", "غيابي", "جريمة", "حشيش",
    ],
    "family": [
        "طلاق", "حضانة", "نفقة", "زوج", "زوجتي", "زوجي", "ميراث",
        "عيال", "ولدي", "بنتي", "طليقتي", "خلع", "عدة",
    ],
    "rental": [
        "إيجار", "مستأجر", "مالك", "شقة", "إخلاء", "عقد إيجار",
        "التأمين", "السكن",
    ],
    "deadline": [
        "طعن", "اعتراض", "مهلة", "تقادم", "مدة", "صدر حكم",
    ],
}

_ENTITY_PATTERNS = {
    "employer": [r"(الشركة|صاحب العمل|الكفيل|المدير|كفيلي|مديري|شركتي)"],
    "spouse": [r"(زوجي|زوجتي|طليقتي|طليقي)"],
    "child": [r"(ولدي|بنتي|عيالي|أولادي|الأطفال)"],
    "landlord": [r"(المالك|صاحب الشقة|المؤجر)"],
    "court": [r"(المحكمة|القاضي|الجلسة)"],
    "contract": [r"(العقد|عقدي|عقد عمل|عقد إيجار)"],
    "judgment": [r"(الحكم|حكم|حكموا|صدر حكم)"],
    "notice": [r"(الإشعار|إشعار|إنذار|وصلني|جاني)"],
}

_TIMELINE_PATTERNS = [
    (r"(\d+)\s*سن[وةي]", "duration_years"),
    (r"(\d+)\s*شه[ور]", "duration_months"),
    (r"(\d+)\s*أسبوع", "duration_weeks"),
    (r"(\d+)\s*يوم", "duration_days"),
    (r"من\s*(أسبوع|شهر|سنة|يوم)", "relative_time"),
    (r"(اليوم|أمس|البارحة|الحين)", "recent"),
    (r"(قبل|بعد)\s*\d+", "relative_offset"),
]

_RISK_SIGNALS = [
    "ضرب", "تهديد", "ابتزاز", "مخدرات", "حبس", "سجن",
    "فصل", "إخلاء", "حكم غيابي", "يضيع حقي", "فوراً",
]

_SUBDOMAIN_MAP = {
    "employment": {
        "فصل": "termination", "استقالة": "resignation", "راتب": "salary",
        "مكافأة": "gratuity", "عقد": "contract", "إذن خروج": "exit_permit",
        "نقل كفالة": "sponsorship_transfer",
    },
    "criminal": {
        "مخدرات": "drugs", "حشيش": "drugs", "سرقة": "theft",
        "ضرب": "assault", "ابتزاز": "blackmail", "حكم غيابي": "default_judgment",
    },
    "family": {
        "طلاق": "divorce", "حضانة": "custody", "نفقة": "alimony",
        "ميراث": "inheritance", "خلع": "khula", "عدة": "iddah",
    },
    "rental": {
        "إخلاء": "eviction", "إيجار": "rent", "التأمين": "deposit",
    },
}

_GOAL_PATTERNS = [
    (r"(أبي|أبغى|أريد)\s+(.{3,30})", "want"),
    (r"(وش أسوي|ايش اسوي|ماذا أفعل|كيف أتصرف)", "seeking_guidance"),
    (r"(هل يحق|هل أقدر|هل يجوز)", "checking_rights"),
    (r"(كم|ما مقدار|ما هي)", "seeking_info"),
    (r"(ساعدني|محتاج مساعدة)", "help_request"),
]


def _detect_domain(query: str) -> str:
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(kw in query for kw in keywords):
            return domain
    return ""


def _detect_subdomain(query: str, domain: str) -> str:
    if domain not in _SUBDOMAIN_MAP:
        return ""
    for keyword, subdomain in _SUBDOMAIN_MAP[domain].items():
        if keyword in query:
            return subdomain
    return ""


def _extract_entities(query: str) -> dict[str, str]:
    entities = {}
    for entity_type, patterns in _ENTITY_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, query)
            if m:
                entities[entity_type] = m.group(1)
                break
    return entities


def _extract_timeline(query: str) -> list[str]:
    markers = []
    for pat, label in _TIMELINE_PATTERNS:
        m = re.search(pat, query)
        if m:
            markers.append(f"{label}:{m.group(0)}")
    return markers


def _extract_risk_signals(query: str) -> list[str]:
    return [s for s in _RISK_SIGNALS if s in query]


def _detect_user_goal(query: str) -> str:
    for pat, goal_type in _GOAL_PATTERNS:
        if re.search(pat, query):
            return goal_type
    return ""


_NEGATION_PREFIXES = ["مو ", "مش ", "ما ", "ليس ", "مو", "مش"]


def _is_negated(query: str, match_start: int) -> bool:
    """Check if the match position is preceded by a negation word."""
    prefix = query[:match_start].rstrip()
    for neg in _NEGATION_PREFIXES:
        if prefix.endswith(neg.strip()):
            return True
    return False


def _extract_facts_from_query(query: str, turn: int, domain: str) -> list[FactRecord]:
    """Extract explicit facts from a user query. Conservative — only confirmed statements."""
    facts = []

    # Personal status facts (user directly states something)
    personal_patterns = [
        (r"(فصلوني|طردوني|فصلني)", "user was terminated", "employment"),
        (r"(استقلت|استقال)", "user resigned", "employment"),
        (r"(عقدي انتهى|العقد انتهى)", "contract expired", "employment"),
        (r"(حكموا علي|صدر حكم ضدي)", "judgment issued against user", "criminal"),
        (r"(انمسك|مسكوني|قبضوا)", "user was arrested/caught", "criminal"),
        (r"(طلقني|طلقت)", "user divorced/was divorced", "family"),
        (r"(زوجتي طلعت|زوجي طلع)", "spouse left", "family"),
        (r"(جاني إشعار|وصلني إشعار)", "user received notice", "deadline"),
        (r"(صدر حكم غيابي)", "default judgment issued", "deadline"),
        (r"(المالك رفع الإيجار)", "landlord raised rent", "rental"),
        (r"(قفل علي|منعني أدخل)", "locked out by landlord", "rental"),
        (r"(عندي عقد|عقد مكتوب)", "user has written contract", ""),
        (r"(ما عندي عقد|بدون عقد)", "user has no written contract", ""),
        (r"(متزوج|متزوجة)", "user is married", "family"),
        (r"(مطلق|مطلقة)", "user is divorced", "family"),
        (r"(عندي أطفال|عندي عيال)", "user has children", "family"),
    ]

    for pat, fact_text, fact_domain in personal_patterns:
        m = re.search(pat, query)
        if m and not _is_negated(query, m.start()):
            facts.append(FactRecord(
                fact_id=f"f_{turn}_{len(facts)}",
                text=fact_text,
                fact_type=FactType.USER_STATED_CONFIRMED,
                domain=fact_domain or domain,
                source_turn=turn,
                confidence=0.9,
                can_be_used_for_answer=True,
            ))

    # Conditional facts (user says "if" — hypothetical)
    conditional_patterns = [
        (r"(إذا كان|لو كان|إذا عندي|لو عندي|إذا ما)", True),
        (r"(في حالة|حالة إن)", True),
    ]
    for pat, is_conditional in conditional_patterns:
        if re.search(pat, query):
            facts.append(FactRecord(
                fact_id=f"f_{turn}_cond_{len(facts)}",
                text=f"conditional: {query[:50]}",
                fact_type=FactType.USER_STATED_AMBIGUOUS,
                domain=domain,
                source_turn=turn,
                confidence=0.5,
                can_be_used_for_answer=False,
                requires_reconfirmation=True,
            ))
            break

    # Duration/timeline as facts
    for pat, label in _TIMELINE_PATTERNS:
        m = re.search(pat, query)
        if m:
            facts.append(FactRecord(
                fact_id=f"f_{turn}_time_{len(facts)}",
                text=f"{label}: {m.group(0)}",
                fact_type=FactType.USER_STATED_CONFIRMED,
                domain=domain,
                source_turn=turn,
                confidence=0.85,
                can_be_used_for_answer=True,
            ))

    return facts


# ══════════════════════════════════════════════════════════════
# Semantic Memory Policy
# ══════════════════════════════════════════════════════════════

class SemanticMemoryPolicy:
    """Controls what context may be safely reused."""

    MAX_STALE_TURNS = 8  # facts older than 8 turns are stale
    MAX_FACTS = 30       # cap on stored facts

    def is_fact_reusable(self, fact: FactRecord, current_turn: int,
                         current_domain: str) -> bool:
        if fact.superseded_by:
            return False
        if not fact.can_be_used_for_answer:
            return False
        if fact.fact_type == FactType.UNRESOLVED:
            return False
        if fact.fact_type == FactType.SYSTEM_INFERRED_LOW:
            return False
        age = current_turn - fact.source_turn
        if age > self.MAX_STALE_TURNS:
            return False
        # Cross-domain: only reuse domain-neutral facts or same-domain
        if fact.domain and fact.domain != current_domain and current_domain:
            return False
        return True

    def rank_relevant_facts(self, facts: list[FactRecord],
                             current_turn: int, current_domain: str) -> list[FactRecord]:
        reusable = [f for f in facts if self.is_fact_reusable(f, current_turn, current_domain)]
        # Sort by: confirmed > inferred, recent > old, same-domain > neutral
        def sort_key(f: FactRecord):
            type_score = {
                FactType.USER_STATED_CONFIRMED: 3,
                FactType.SYSTEM_INFERRED_CONTROLLED: 2,
                FactType.USER_STATED_AMBIGUOUS: 1,
            }.get(f.fact_type, 0)
            recency = 1.0 / max(1, current_turn - f.source_turn)
            domain_match = 1.0 if (f.domain == current_domain or not f.domain) else 0.5
            return -(type_score * 10 + recency * 5 + domain_match * 3)
        return sorted(reusable, key=sort_key)

    def resolve_fact_priority(self, old: FactRecord, new: FactRecord) -> FactRecord:
        """When two facts conflict, return the winner."""
        # Newer confirmed always wins over older
        if new.fact_type == FactType.USER_STATED_CONFIRMED:
            return new
        # Old confirmed wins over new inferred
        if old.fact_type == FactType.USER_STATED_CONFIRMED and \
           new.fact_type in (FactType.SYSTEM_INFERRED_LOW, FactType.SYSTEM_INFERRED_CONTROLLED):
            return old
        # Default: newer wins
        return new

    def filter_context_for_query(self, state: SemanticMemoryState,
                                  query: str, domain: str) -> list[FactRecord]:
        return self.rank_relevant_facts(
            state.established_facts, state.turn_count, domain)[:10]


# ══════════════════════════════════════════════════════════════
# Memory Safety Guard
# ══════════════════════════════════════════════════════════════

class MemorySafetyGuard:
    """Prevents unsafe memory reuse."""

    def detect_context_leak(self, state: SemanticMemoryState,
                             new_domain: str) -> bool:
        """True if switching to a new domain would leak prior context."""
        if not state.active_domain:
            return False
        if state.active_domain == new_domain:
            return False
        # Check if there are high-risk facts from previous domain
        prior_risk_facts = [
            f for f in state.established_facts
            if f.domain == state.active_domain
            and any(r in f.text for r in ["criminal", "drugs", "arrested", "judgment"])
        ]
        return len(prior_risk_facts) > 0

    def detect_fact_conflict(self, existing: list[FactRecord],
                              new_fact: FactRecord) -> Optional[FactRecord]:
        """Returns the conflicting fact if one exists."""
        conflict_pairs = {
            "user was terminated": "user resigned",
            "user resigned": "user was terminated",
            "user has written contract": "user has no written contract",
            "user has no written contract": "user has written contract",
            "user is married": "user is divorced",
            "user is divorced": "user is married",
        }
        for ef in existing:
            if ef.superseded_by:
                continue
            if ef.text in conflict_pairs and conflict_pairs[ef.text] == new_fact.text:
                return ef
        return None

    def enforce_safe_memory_use(self, state: SemanticMemoryState,
                                 query: str, domain: str) -> SemanticMemoryState:
        """Returns a cleaned state safe for use with the current query."""
        if not domain:
            return state

        # If domain changed, quarantine old domain's risk-sensitive facts
        if state.active_domain and state.active_domain != domain:
            for fact in state.established_facts:
                if fact.domain == state.active_domain and \
                   fact.domain not in ("", domain):
                    # Don't allow cross-domain facts to influence answers
                    fact.can_be_used_for_answer = False
                    fact.requires_reconfirmation = True

        # Mark very old facts as needing reconfirmation
        for fact in state.established_facts:
            age = state.turn_count - fact.source_turn
            if age > 6 and fact.fact_type != FactType.USER_STATED_CONFIRMED:
                fact.requires_reconfirmation = True
                fact.can_be_used_for_answer = False

        return state


# ══════════════════════════════════════════════════════════════
# Semantic Memory Engine
# ══════════════════════════════════════════════════════════════

# In-memory store keyed by session_id
_memory_store: dict[str, SemanticMemoryState] = {}


class SemanticMemoryEngine:
    """
    Main engine. Maintains and retrieves semantic context per session.
    """

    def __init__(self):
        self._policy = SemanticMemoryPolicy()
        self._safety = MemorySafetyGuard()

    # ── State Management ──

    def get_or_create_state(self, session_id: str) -> SemanticMemoryState:
        if session_id not in _memory_store:
            _memory_store[session_id] = SemanticMemoryState(session_id=session_id)
        return _memory_store[session_id]

    def build_memory_state(self, session_id: str, query: str,
                            domain: str = "", subdomain: str = "") -> SemanticMemoryState:
        """Build or retrieve the current memory state for a session."""
        state = self.get_or_create_state(session_id)

        if not domain:
            domain = _detect_domain(query)
        if not subdomain and domain:
            subdomain = _detect_subdomain(query, domain)

        state.turn_count += 1
        if domain:
            state.active_domain = domain
            if domain not in state.domain_history:
                state.domain_history.append(domain)
        if subdomain:
            state.active_subdomain = subdomain

        return state

    def update_memory_state(self, state: SemanticMemoryState,
                             query: str, response_status: str = "",
                             guidance_applied: bool = False,
                             guardrail_applied: bool = False) -> SemanticMemoryState:
        """Update state after processing a query."""
        domain = state.active_domain

        # Extract entities
        new_entities = _extract_entities(query)
        state.active_entities.update(new_entities)

        # Extract timeline
        timeline = _extract_timeline(query)
        for t in timeline:
            if t not in state.active_timeline_markers:
                state.active_timeline_markers.append(t)

        # Extract risk signals
        risks = _extract_risk_signals(query)
        for r in risks:
            if r not in state.active_risk_markers:
                state.active_risk_markers.append(r)

        # Extract and merge facts
        new_facts = _extract_facts_from_query(query, state.turn_count, domain)
        self.merge_new_facts(state, new_facts)

        # Detect user goal
        goal = _detect_user_goal(query)
        if goal:
            state.last_user_goal = goal

        # Update pipeline state
        if guidance_applied:
            state.prior_guidance_state = "guided"
        if guardrail_applied:
            state.prior_guardrail_state = "guarded"

        # Apply safety enforcement
        self._safety.enforce_safe_memory_use(state, query, domain)

        # Update confidence
        confirmed = sum(1 for f in state.established_facts if f.is_usable())
        state.confidence = min(1.0, confirmed * 0.15)

        log.info("[MEMORY] session=%s turn=%d domain=%s entities=%d facts=%d",
                 state.session_id, state.turn_count, domain,
                 len(state.active_entities), len(state.established_facts))
        return state

    def merge_new_facts(self, state: SemanticMemoryState,
                         new_facts: list[FactRecord]) -> None:
        """Merge new facts, resolving conflicts."""
        for new_fact in new_facts:
            conflict = self._safety.detect_fact_conflict(
                state.established_facts, new_fact)
            if conflict:
                winner = self._policy.resolve_fact_priority(conflict, new_fact)
                if winner is new_fact:
                    conflict.superseded_by = new_fact.fact_id
                    state.established_facts.append(new_fact)
                    state.notes_internal.append(
                        f"fact conflict: '{conflict.text}' superseded by '{new_fact.text}'")
                # else: keep old fact, discard new
            else:
                # No conflict — check for duplicates
                existing_texts = {f.text for f in state.established_facts if not f.superseded_by}
                if new_fact.text not in existing_texts:
                    state.established_facts.append(new_fact)

        # Enforce cap
        if len(state.established_facts) > self._policy.MAX_FACTS:
            # Remove oldest superseded facts
            active = [f for f in state.established_facts if not f.superseded_by]
            superseded = [f for f in state.established_facts if f.superseded_by]
            state.established_facts = active + superseded[-(self._policy.MAX_FACTS - len(active)):]

    def detect_fact_conflicts(self, state: SemanticMemoryState) -> list[tuple[FactRecord, FactRecord]]:
        """Return pairs of conflicting facts."""
        conflicts = []
        active = [f for f in state.established_facts if not f.superseded_by]
        for i, a in enumerate(active):
            for b in active[i+1:]:
                conflict = self._safety.detect_fact_conflict([a], b)
                if conflict:
                    conflicts.append((a, b))
        return conflicts

    def get_relevant_context(self, session_id: str,
                              query: str, domain: str = "") -> dict:
        """
        Main retrieval method. Returns a context dict safe for use in
        follow-up enrichment and pipeline decisions.
        """
        state = self.get_or_create_state(session_id)
        if not domain:
            domain = _detect_domain(query) or state.active_domain

        relevant_facts = self._policy.filter_context_for_query(state, query, domain)

        return {
            "session_id": session_id,
            "active_domain": state.active_domain,
            "active_subdomain": state.active_subdomain,
            "entities": dict(state.active_entities),
            "facts": [{"text": f.text, "type": f.fact_type.value, "confidence": f.confidence}
                      for f in relevant_facts],
            "timeline": list(state.active_timeline_markers),
            "risk_markers": list(state.active_risk_markers),
            "last_goal": state.last_user_goal,
            "turn_count": state.turn_count,
            "confidence": state.confidence,
            "has_context": (len(relevant_facts) > 0
                           or bool(state.active_domain)
                           or bool(state.active_entities)),
        }

    def clear_irrelevant_context(self, session_id: str,
                                   new_domain: str) -> None:
        """Clear context that is no longer relevant after a topic shift."""
        state = self.get_or_create_state(session_id)
        if self._safety.detect_context_leak(state, new_domain):
            # Quarantine old facts
            for fact in state.established_facts:
                if fact.domain and fact.domain != new_domain:
                    fact.can_be_used_for_answer = False
            state.notes_internal.append(
                f"context cleared: domain shift {state.active_domain} -> {new_domain}")
            log.info("[MEMORY] context leak detected, quarantined old facts")

    def clear_session(self, session_id: str) -> None:
        """Fully clear a session's memory."""
        _memory_store.pop(session_id, None)

    # ── Follow-up Enrichment ──

    def enrich_followup_query(self, session_id: str,
                                query: str, domain: str = "") -> str:
        """
        Enrich a follow-up query with relevant prior context.
        Returns an enriched query string for better retrieval/response.
        Does NOT invent facts — only appends confirmed prior context.
        """
        ctx = self.get_relevant_context(session_id, query, domain)
        if not ctx["has_context"]:
            return query

        # Only enrich short follow-up queries
        if len(query.split()) > 12:
            return query

        enrichment_parts = []

        # Add domain context if the follow-up doesn't specify one
        if ctx["active_domain"] and not _detect_domain(query):
            domain_labels = {
                "employment": "عمل", "criminal": "جنائي",
                "family": "أحوال شخصية", "rental": "إيجار",
                "deadline": "مواعيد قانونية",
            }
            label = domain_labels.get(ctx["active_domain"], "")
            if label:
                enrichment_parts.append(f"[سياق: {label}]")

        # Add key entity context
        for entity_type, value in list(ctx["entities"].items())[:3]:
            enrichment_parts.append(f"[{value}]")

        # Add confirmed facts (max 2, short)
        confirmed = [f for f in ctx["facts"]
                     if f["type"] == FactType.USER_STATED_CONFIRMED.value]
        for f in confirmed[:2]:
            enrichment_parts.append(f"[{f['text']}]")

        if not enrichment_parts:
            return query

        enriched = query + " " + " ".join(enrichment_parts)
        log.info("[MEMORY] enriched follow-up: '%s' -> '%s'",
                 query[:40], enriched[:80])
        return enriched


# ══════════════════════════════════════════════════════════════
# Module-level Singleton
# ══════════════════════════════════════════════════════════════

_engine: Optional[SemanticMemoryEngine] = None


def get_semantic_memory() -> SemanticMemoryEngine:
    global _engine
    if _engine is None:
        _engine = SemanticMemoryEngine()
    return _engine


def get_memory_context(session_id: str, query: str,
                        domain: str = "") -> dict:
    """Convenience function for retrieving context."""
    return get_semantic_memory().get_relevant_context(session_id, query, domain)


def update_memory(session_id: str, query: str,
                   domain: str = "", guidance: bool = False,
                   guardrail: bool = False) -> SemanticMemoryState:
    """Convenience function for updating memory after a turn."""
    engine = get_semantic_memory()
    state = engine.build_memory_state(session_id, query, domain)
    return engine.update_memory_state(state, query,
                                       guidance_applied=guidance,
                                       guardrail_applied=guardrail)


def enrich_followup(session_id: str, query: str,
                      domain: str = "") -> str:
    """Convenience function for follow-up enrichment."""
    return get_semantic_memory().enrich_followup_query(session_id, query, domain)
