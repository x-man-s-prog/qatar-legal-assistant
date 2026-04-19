# -*- coding: utf-8 -*-
"""
Hypothesis generation — 6-8 competing legal interpretations per query.

Not every hypothesis applies to every query. The generator picks the
relevant types based on:
  • classifier scores (primary + closest alternative)
  • cross-domain overlap rules
  • facts that hint at criminal vs civil framing
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.legal_gates import LegalDomain, LegalIssueClassifier
from core.domain_pipeline.issue_graph import (
    IssueGraph, build_issue_graph,
)


class HypothesisType(str, Enum):
    PRIMARY_EXPECTED     = "primary_expected"
    CLOSEST_ALTERNATIVE  = "closest_alternative"
    HYBRID_CROSS_DOMAIN  = "hybrid_cross_domain"
    DEFENSIVE            = "defensive"
    AGGRESSIVE           = "aggressive"
    MINIMALIST_CIVIL     = "minimalist_civil"
    WORST_CASE_EXPOSURE  = "worst_case_exposure"
    EDGE_CASE            = "edge_case"


@dataclass
class Hypothesis:
    hypothesis_id:        str
    hypothesis_type:      HypothesisType
    domain:               str
    subdomain:            str = ""
    legal_theory:         str = ""
    issue_graph:          Optional[IssueGraph] = None
    supporting_facts:     list[str] = field(default_factory=list)
    contradicting_facts:  list[str] = field(default_factory=list)
    required_evidence:    list[str] = field(default_factory=list)
    legal_risk_level:     str = "medium"     # low | medium | high | critical
    plausibility_initial: float = 0.0        # 0..1 — before scoring

    # Evidence simulation
    strong_evidence_possible:    bool = False
    weak_evidence_only:          bool = False
    high_risk_missing_evidence:  bool = False
    contradiction_risk:          float = 0.0   # 0..1

    def to_dict(self) -> dict:
        return {
            "hypothesis_id":      self.hypothesis_id,
            "type":               self.hypothesis_type.value,
            "domain":             self.domain,
            "subdomain":          self.subdomain,
            "legal_theory":       self.legal_theory,
            "legal_risk_level":   self.legal_risk_level,
            "plausibility_initial": round(self.plausibility_initial, 3),
            "supporting_facts":   self.supporting_facts[:3],
            "contradicting_facts": self.contradicting_facts[:3],
            "required_evidence":  self.required_evidence[:3],
            "evidence_sim": {
                "strong_possible":      self.strong_evidence_possible,
                "weak_only":            self.weak_evidence_only,
                "high_risk_missing":    self.high_risk_missing_evidence,
                "contradiction_risk":   round(self.contradiction_risk, 3),
            },
        }


@dataclass
class HypothesisBundle:
    query:        str
    hypotheses:   list[Hypothesis] = field(default_factory=list)
    generation_trace: list[str] = field(default_factory=list)

    def by_type(self, t: HypothesisType) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.hypothesis_type == t]


# ═════════════════════════════════════════════════════════════════
# Cross-domain overlap rules — when two domains compete
# ═════════════════════════════════════════════════════════════════

_CROSS_DOMAIN_PAIRS: list[tuple[str, str, str]] = [
    # (domain_a, domain_b, hybrid_theory)
    ("criminal", "civil",     "جريمة + مسؤولية مدنية موازية"),
    ("commercial", "criminal", "نزاع تجاري مع شبهة احتيال/تدليس"),
    ("banking", "criminal",   "نزاع مصرفي مع شبهة إساءة أو تزوير"),
    ("family", "inheritance", "قضية أسرية مرتبطة بتركة"),
    ("civil", "commercial",   "عقد مدني ذو طابع تجاري"),
    ("criminal", "cyber",     "جريمة كلاسيكية عبر وسيلة إلكترونية"),
    ("civil", "criminal",     "نزاع مدني مع إمكانية تكييف جنائي (تدليس/احتيال)"),
    ("employment", "criminal", "علاقة عمل مع ادعاء جريمة (تسريب/سرقة وظيفية)"),
]


# ═════════════════════════════════════════════════════════════════
# Theory templates per domain — short Arabic labels
# ═════════════════════════════════════════════════════════════════

_DOMAIN_THEORY: dict[str, str] = {
    "criminal":    "مسؤولية جنائية",
    "civil":       "مسؤولية مدنية / التزام تعاقدي",
    "commercial":  "نزاع تجاري / عقد تجاري",
    "banking":     "نزاع مصرفي / أدوات ائتمان",
    "family":      "علاقة أسرية / قانون الأحوال الشخصية",
    "inheritance": "تصرف متعلق بالتركة",
    "rental":      "عقد إيجار / إخلاء",
    "employment":  "علاقة عمل / إنهاء",
    "traffic":     "حادث مروري",
    "administrative": "قرار إداري / اختصاص إداري",
    "intellectual_property": "ملكية فكرية",
    "insurance":   "تأمين / تعويض",
}


# ═════════════════════════════════════════════════════════════════
# Fact-pattern hints for aggressive/defensive framings
# ═════════════════════════════════════════════════════════════════

_AGGRESSIVE_MARKERS = (
    "تزوير", "احتيال", "نصب", "تدليس", "سرقة", "اختلاس",
    "تواطؤ", "خداع", "زوَّر", "خدعني",
)

_DEFENSIVE_MARKERS = (
    "لم أقصد", "بحسن نية", "دون علم", "اضطررت",
    "بلا قصد", "خطأ عابر",
)


def _fingerprint(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _make_hypothesis(
    htype: HypothesisType,
    domain: str,
    subdomain: str = "",
    legal_theory: str = "",
    risk: str = "medium",
    plausibility: float = 0.5,
    query: str = "",
) -> Hypothesis:
    theory = legal_theory or _DOMAIN_THEORY.get(domain, "")
    graph = build_issue_graph(domain, subdomain, query) if domain else None
    return Hypothesis(
        hypothesis_id=_fingerprint([htype.value, domain, subdomain, query[:30]]),
        hypothesis_type=htype,
        domain=domain,
        subdomain=subdomain,
        legal_theory=theory,
        issue_graph=graph,
        legal_risk_level=risk,
        plausibility_initial=plausibility,
    )


# ═════════════════════════════════════════════════════════════════
# Evidence simulation — quick heuristic per hypothesis
# ═════════════════════════════════════════════════════════════════

def _simulate_evidence(h: Hypothesis, query: str, facts: list[str]) -> None:
    """Populate h.strong/weak/high_risk flags based on query + facts."""
    q = (query or "") + " " + " ".join(facts or [])
    has_witnesses    = any(w in q for w in ("شهود", "شاهد"))
    has_documents    = any(w in q for w in ("عقد", "وثيقة", "إيصال", "كشف"))
    has_digital      = any(w in q for w in ("واتساب", "رسائل", "سكرين",
                                              "تسجيل", "لقطة"))
    has_official_doc = any(w in q for w in ("تقرير طبي", "محضر رسمي",
                                              "شهادة وفاة", "سجل تجاري"))

    if has_documents or has_official_doc:
        h.strong_evidence_possible = True
    elif has_digital or has_witnesses:
        h.weak_evidence_only = True
    else:
        h.high_risk_missing_evidence = True

    # Contradicting facts (defensive markers in aggressive hypothesis, etc.)
    if h.hypothesis_type == HypothesisType.AGGRESSIVE:
        if any(m in q for m in _DEFENSIVE_MARKERS):
            h.contradiction_risk = 0.65
    elif h.hypothesis_type == HypothesisType.DEFENSIVE:
        if any(m in q for m in _AGGRESSIVE_MARKERS):
            h.contradiction_risk = 0.55
    else:
        h.contradiction_risk = 0.20


# ═════════════════════════════════════════════════════════════════
# Main generator
# ═════════════════════════════════════════════════════════════════

def generate_hypotheses(query: str,
                          facts: Optional[list[str]] = None,
                          max_hypotheses: int = 8,
                          ) -> HypothesisBundle:
    """Produce a competing set of 6-8 hypotheses for the query.

    Does NOT rank them (that's scoring's job). Only generates candidates.
    """
    facts = facts or []
    bundle = HypothesisBundle(query=query)

    # Step 1: Classify the query
    classifier_result = LegalIssueClassifier().classify(query)
    primary_domain = classifier_result.primary_domain.value

    bundle.generation_trace.append(
        f"classifier:{primary_domain}@{classifier_result.confidence:.2f}"
    )

    # ── HYPOTHESIS 1: Primary expected ──
    if primary_domain and primary_domain != "unknown":
        h1 = _make_hypothesis(
            HypothesisType.PRIMARY_EXPECTED,
            domain=primary_domain,
            plausibility=classifier_result.confidence,
            query=query,
        )
        bundle.hypotheses.append(h1)

    # ── HYPOTHESIS 2: Closest alternative (secondary domain) ──
    if classifier_result.secondary_domains:
        alt = classifier_result.secondary_domains[0].value
        h2 = _make_hypothesis(
            HypothesisType.CLOSEST_ALTERNATIVE,
            domain=alt,
            plausibility=0.55,
            query=query,
        )
        bundle.hypotheses.append(h2)
        bundle.generation_trace.append(f"alt:{alt}")

    # ── HYPOTHESIS 3: Hybrid cross-domain ──
    for (a, b, theory) in _CROSS_DOMAIN_PAIRS:
        if primary_domain == a:
            # Check if the query has any markers of `b`
            b_raw_score = classifier_result.raw_scores.get(b, 0)
            if b_raw_score > 0 or _has_cross_markers(query, b):
                h3 = _make_hypothesis(
                    HypothesisType.HYBRID_CROSS_DOMAIN,
                    domain=a,   # keep primary, just add hybrid theory
                    legal_theory=theory,
                    risk="high",
                    plausibility=0.45,
                    query=query,
                )
                bundle.hypotheses.append(h3)
                bundle.generation_trace.append(f"hybrid:{a}+{b}")
                break

    # ── HYPOTHESIS 4: Defensive interpretation ──
    if primary_domain == "criminal":
        h4 = _make_hypothesis(
            HypothesisType.DEFENSIVE,
            domain="criminal",
            legal_theory="انتفاء الركن المعنوي / قيام سبب إباحة",
            risk="low",
            plausibility=0.35,
            query=query,
        )
        bundle.hypotheses.append(h4)

    # ── HYPOTHESIS 5: Aggressive interpretation ──
    if any(m in query for m in _AGGRESSIVE_MARKERS):
        h5 = _make_hypothesis(
            HypothesisType.AGGRESSIVE,
            domain="criminal",
            legal_theory="تكييف جنائي صارم (احتيال/تزوير)",
            risk="critical",
            plausibility=0.50,
            query=query,
        )
        bundle.hypotheses.append(h5)

    # ── HYPOTHESIS 6: Minimalist civil ──
    if primary_domain in ("criminal", "commercial", "banking"):
        h6 = _make_hypothesis(
            HypothesisType.MINIMALIST_CIVIL,
            domain="civil",
            legal_theory="مسؤولية مدنية / مطالبة استرداد — دون تكييف جنائي",
            risk="low",
            plausibility=0.40,
            query=query,
        )
        bundle.hypotheses.append(h6)
        bundle.generation_trace.append("minimalist_civil")

    # ── HYPOTHESIS 7: Worst-case exposure ──
    if primary_domain:
        worst_domain = "criminal" if primary_domain != "criminal" else primary_domain
        h7 = _make_hypothesis(
            HypothesisType.WORST_CASE_EXPOSURE,
            domain=worst_domain,
            legal_theory=f"أسوأ تكييف ممكن ({_DOMAIN_THEORY.get(worst_domain,'')})",
            risk="critical",
            plausibility=0.30,
            query=query,
        )
        bundle.hypotheses.append(h7)

    # ── HYPOTHESIS 8: Edge case ──
    edge_domain = _pick_edge_case(primary_domain, query)
    if edge_domain:
        h8 = _make_hypothesis(
            HypothesisType.EDGE_CASE,
            domain=edge_domain,
            legal_theory=f"تكييف نادر لكن ممكن ({_DOMAIN_THEORY.get(edge_domain,'')})",
            risk="low",
            plausibility=0.20,
            query=query,
        )
        bundle.hypotheses.append(h8)

    # Simulate evidence for each
    for h in bundle.hypotheses:
        _simulate_evidence(h, query, facts)

    # Cap and dedup by (type, domain)
    seen: set = set()
    out: list[Hypothesis] = []
    for h in bundle.hypotheses:
        k = (h.hypothesis_type, h.domain, h.subdomain)
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
        if len(out) >= max_hypotheses:
            break
    bundle.hypotheses = out
    return bundle


def _has_cross_markers(query: str, domain: str) -> bool:
    """Quick lexical check for a cross-domain hint."""
    hints = {
        "criminal":  ("تزوير", "احتيال", "جريمة", "نصب", "سرقة"),
        "cyber":     ("إلكتروني", "تويتر", "واتساب", "سكرين"),
        "civil":     ("تعويض", "مطالبة", "التزام", "عقد"),
        "commercial": ("شركة", "شريك", "استثمار"),
        "banking":   ("شيك", "بنك", "حساب"),
        "inheritance": ("ورثة", "تركة", "وفاة"),
    }.get(domain, ())
    return any(h in query for h in hints)


def _pick_edge_case(primary: str, query: str) -> str:
    """Pick a rare but plausible edge-case domain."""
    edges = {
        "criminal":  "administrative",
        "civil":     "commercial",
        "commercial": "civil",
        "banking":   "civil",
        "family":    "inheritance",
        "rental":    "civil",
        "employment": "administrative",
    }
    return edges.get(primary, "")
