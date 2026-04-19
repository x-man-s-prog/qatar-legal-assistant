# -*- coding: utf-8 -*-
"""
runtime_v2.types — the ONLY data shapes runtime_v2 produces.

No legacy dataclasses. No inherited enums. No reuse from core.legal_gates
or core.production_runtime or any other pre-v2 module.

Everything the UI/adapter ever sees passes through `Response` and
`Response.to_dict()`. There is no other output shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ═════════════════════════════════════════════════════════════════════
# Enumerations — small, closed vocabularies
# ═════════════════════════════════════════════════════════════════════

class DomainKey(str, Enum):
    """Pilot domains. UNKNOWN = out of scope of runtime_v2."""
    EMPLOYMENT_VS_PARTNERSHIP  = "employment_vs_partnership"
    GUARANTEE_CHEQUE           = "guarantee_cheque"
    DEATH_ILLNESS_VS_DEBT      = "death_illness_vs_debt"
    CODE_OWNERSHIP_PRIOR_LIBS  = "code_ownership_prior_libs"
    # Memo-heavy domains (added after cutover — Qatari law)
    FAMILY_CUSTODY             = "family_custody"
    CRIMINAL_DRUG_DEFENSE      = "criminal_drug_defense"
    UNLAWFUL_TERMINATION       = "unlawful_termination"
    # Memo-heavy criminal domains (second expansion — Qatari penal code)
    DEFAMATION                 = "defamation"
    ASSAULT                    = "assault"
    BLACKMAIL_THREAT           = "blackmail_threat"
    THEFT                      = "theft"
    FRAUD                      = "fraud"
    CYBER_CRIME                = "cyber_crime"
    # Memo-heavy domains (third expansion — post-quality-audit)
    RENTAL                     = "rental"
    FRAUD_EMBEZZLEMENT         = "fraud_embezzlement"
    FORGERY                    = "forgery"
    BAD_CHECK                  = "bad_check"
    DIVORCE_FOR_HARM           = "divorce_for_harm"
    # Memo-heavy domains (fourth expansion — family maintenance)
    FAMILY_NAFAQA              = "family_nafaqa"
    UNKNOWN                    = "unknown"


class Intent(str, Enum):
    ANALYTICAL = "analytical"
    DRAFTING   = "drafting"


class ReasoningMode(str, Enum):
    SINGLE_PATH  = "single_path"
    MULTI_PATH   = "multi_path"
    CONDITIONAL  = "conditional"
    SKELETON     = "skeleton"


class DraftingMode(str, Enum):
    SINGLE_DRAFT      = "single_draft"
    CONDITIONAL_DRAFT = "conditional_draft"
    DUAL_DRAFT        = "dual_draft"
    SKELETON_DRAFT    = "skeleton_draft"


# ═════════════════════════════════════════════════════════════════════
# Core building blocks
# ═════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FactMarker:
    """A recognizable fact with the keywords that prove it appears in the
    user's query. Keywords are matched against the normalized Arabic
    form of the query (diacritics stripped, ة→ه, ى→ي, أإآ→ا)."""
    label:    str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PathHypothesis:
    """One legal characterization the query might fit."""
    label:    str
    articles: tuple[str, ...]
    markers:  tuple[FactMarker, ...]
    weight:   float = 0.5

    @property
    def supporting_facts(self) -> tuple[str, ...]:
        return tuple(m.label for m in self.markers)


@dataclass(frozen=True)
class Pivot:
    """A decisive factual question that moves weight between paths."""
    question:     str
    if_yes_path:  str     # label of the hypothesis this strengthens
    if_no_path:   str     # label of the hypothesis it weakens
    importance:   int = 1  # 1 .. 3 (higher = more decisive)


@dataclass(frozen=True)
class Issue:
    """Node in the issue graph bound to a domain."""
    key:                 str
    title:               str
    governing_articles:  tuple[str, ...]


@dataclass(frozen=True)
class EvidenceItem:
    """A canonical, pre-verified citation + its short summary."""
    citation:    str
    summary:     str
    is_verified: bool = True


@dataclass(frozen=True)
class DomainRules:
    """Static, self-contained rule set for a single domain."""
    key:          DomainKey
    display_name: str
    keywords:     tuple[str, ...]
    issues:       tuple[Issue, ...]
    paths:        tuple[PathHypothesis, ...]
    pivots:       tuple[Pivot, ...]
    default_mode: ReasoningMode

    # ─── Memo-quality fields (added after quality audit) ────────────
    # Who the memo is written FOR — drives prayer shape (plaintiff vs
    # accused vs worker etc.). Example: "المدعي (طالب ضم الحضانة)".
    client_role:       str = ""

    # Legal-language facts skeleton. Each entry is a sentence that the
    # composer weaves with the user's raw facts to produce a proper
    # الوقائع section. Supports square-bracket placeholders like
    # [يُدرج التاريخ] that the user can fill.
    facts_template:    tuple[str, ...] = ()

    # The Prayers section — hand-crafted for the CLIENT only. Never
    # derived from opposing hypotheses. Used verbatim by the composer.
    primary_prayers:   tuple[str, ...] = ()

    # SQL LIKE pattern used by corpus.get_rulings() to pull relevant
    # Tameez rulings into the memo's "السوابق القضائية" section.
    ruling_pattern:    str = ""

    # (article_number, law_pattern) pairs the composer will expand into
    # full article text via corpus.get_article_text(). Order controls
    # citation order inside the "الأسانيد القانونية" section.
    article_refs:      tuple[tuple[str, str], ...] = ()


# ═════════════════════════════════════════════════════════════════════
# The ONE and ONLY response object
# ═════════════════════════════════════════════════════════════════════

@dataclass
class Response:
    """Single output shape of runtime_v2. No alternative exists."""
    answer_text:       str
    domain:            str
    intent:            Intent
    reasoning_mode:    ReasoningMode
    drafting_mode:     Optional[DraftingMode] = None
    paths:             list[PathHypothesis]   = field(default_factory=list)
    pivots:            list[Pivot]            = field(default_factory=list)
    evidence:          list[EvidenceItem]     = field(default_factory=list)
    established_facts: list[str]              = field(default_factory=list)
    missing_facts:     list[str]              = field(default_factory=list)
    is_skeleton:       bool                   = False
    memo_text:         Optional[str]          = None

    def to_dict(self) -> dict:
        return {
            "runtime":            "runtime_v2",
            "author":             "runtime_v2_composer",
            "answer":             self.answer_text,
            "memo":               self.memo_text,
            "domain":             self.domain,
            "intent":             self.intent.value,
            "reasoning_mode":     self.reasoning_mode.value,
            "drafting_mode":
                self.drafting_mode.value if self.drafting_mode else None,
            "paths": [
                {"label": p.label,
                 "articles": list(p.articles),
                 "weight": p.weight,
                 "supporting_facts": list(p.supporting_facts)}
                for p in self.paths
            ],
            "pivots": [
                {"question": p.question,
                 "if_yes": p.if_yes_path,
                 "if_no":  p.if_no_path,
                 "importance": p.importance}
                for p in self.pivots
            ],
            "evidence": [
                {"citation": e.citation,
                 "summary":  e.summary,
                 "is_verified": e.is_verified}
                for e in self.evidence
            ],
            "established_facts": list(self.established_facts),
            "missing_facts":     list(self.missing_facts),
            "is_skeleton":       self.is_skeleton,
        }
