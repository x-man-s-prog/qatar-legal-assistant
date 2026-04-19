# -*- coding: utf-8 -*-
"""
Adversarial Self-Attack + Survival Filter.

Each hypothesis is challenged with 4 attack angles:
  1. How can it be dismissed procedurally?
  2. What's the strongest counter-classification?
  3. Worst opposing interpretation?
  4. Can it be re-classified into a different domain?

If a hypothesis collapses too easily → excluded.
Survivors: top 2-3 DISTINCT paths (no redundancy).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.mlre.hypothesis import Hypothesis, HypothesisType
from core.mlre.scoring import ScoreBreakdown


@dataclass
class AdversarialAttack:
    hypothesis_id:        str
    dismissal_paths:      list[str] = field(default_factory=list)
    counter_classifications: list[str] = field(default_factory=list)
    worst_opposition:     str = ""
    reclassification_risk: float = 0.0   # 0..1
    collapse_score:       float = 0.0    # how easily this hypothesis falls
    survives:             bool = True
    collapse_reasons:     list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hypothesis_id":        self.hypothesis_id,
            "dismissal_paths":      self.dismissal_paths[:3],
            "counter_classifications": self.counter_classifications[:3],
            "worst_opposition":     self.worst_opposition,
            "reclassification_risk": round(self.reclassification_risk, 3),
            "collapse_score":       round(self.collapse_score, 3),
            "survives":             self.survives,
            "collapse_reasons":     self.collapse_reasons,
        }


# ═════════════════════════════════════════════════════════════════
# Attack knowledge base — per-domain dismissal paths
# ═════════════════════════════════════════════════════════════════

_DISMISSAL_PATHS: dict[str, list[str]] = {
    "criminal": [
        "انتفاء الركن المعنوي (القصد الجنائي)",
        "بطلان إجراءات القبض أو التفتيش",
        "تناقض شهادات الشهود",
        "سقوط الدعوى بمضي المدة (تقادم)",
    ],
    "civil": [
        "سقوط الحق بالتقادم",
        "عدم قبول الدعوى لانتفاء المصلحة",
        "بطلان الإجراءات الشكلية",
        "انعدام العلاقة السببية بين الفعل والضرر",
    ],
    "commercial": [
        "اختصاص التحكيم التجاري يحل محل القضاء",
        "سقوط الدعوى بالتقادم التجاري",
        "عدم قيد النزاع في السجل التجاري",
    ],
    "banking": [
        "انتفاء عيوب الإرادة عند توقيع العقود المصرفية",
        "حجية الدفاتر التجارية ضد العميل",
    ],
    "family": [
        "حجية الأمر المقضي في نزاعات سابقة",
        "اختصاص محكمة أخرى",
    ],
    "inheritance": [
        "عدم ثبوت مرض الموت",
        "إجازة باقي الورثة لاحقاً",
    ],
    "employment": [
        "سقوط الدعوى العمالية بمضي المدة",
        "اختصاص لجنة فض المنازعات العمالية أولاً",
    ],
    "rental": [
        "بطلان الإنذار الموجه",
        "اختصاص لجنة فض المنازعات الإيجارية",
    ],
}

_COUNTER_CLASSIFICATIONS: dict[str, list[str]] = {
    "criminal":  ["مسؤولية مدنية فقط", "شبهة تفسَّر لصالح المتهم"],
    "civil":     ["تكييف تجاري بدلاً من مدني", "مسألة إدارية وليست مدنية"],
    "commercial": ["نزاع مدني بسيط وليس تجاري", "علاقة عمل وليست شراكة"],
    "banking":   ["التزام مدني عادي وليس مصرفي"],
    "family":    ["نزاع مدني/مالي وليس أسري"],
    "inheritance": ["هبة صحيحة في الصحة لا وصية في مرض الموت"],
    "employment": ["عقد خدمات/مقاولة وليس علاقة عمل"],
    "rental":    ["عقد ملكية وليس إيجار"],
}


# ═════════════════════════════════════════════════════════════════
# Core attack logic
# ═════════════════════════════════════════════════════════════════

def _compute_collapse_score(h: Hypothesis,
                              score: ScoreBreakdown) -> float:
    """Higher = more collapsible."""
    collapse = 0.0
    # Weak evidence feasibility → easy to collapse
    if h.high_risk_missing_evidence:
        collapse += 0.35
    elif h.weak_evidence_only:
        collapse += 0.20
    # High contradiction risk
    collapse += 0.30 * h.contradiction_risk
    # Low fact consistency
    if score.fact_consistency < 0.30:
        collapse += 0.25
    # Low legal plausibility
    if score.legal_plausibility < 0.30:
        collapse += 0.20
    # Edge-case hypotheses are inherently fragile
    if h.hypothesis_type == HypothesisType.EDGE_CASE:
        collapse += 0.15
    return min(1.0, collapse)


def attack_hypotheses(
    scored: list[tuple[Hypothesis, ScoreBreakdown]],
    collapse_threshold: float = 0.60,
) -> list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]]:
    """For each (hypothesis, score), build an attack record.
    Returns triples with adversarial result."""
    out: list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]] = []

    for h, score in scored:
        atk = AdversarialAttack(hypothesis_id=h.hypothesis_id)

        # 1. Dismissal paths from domain knowledge
        atk.dismissal_paths = list(_DISMISSAL_PATHS.get(h.domain, []))[:3]

        # 2. Counter-classifications
        atk.counter_classifications = list(
            _COUNTER_CLASSIFICATIONS.get(h.domain, [])
        )[:2]

        # 3. Worst opposition
        if h.hypothesis_type == HypothesisType.PRIMARY_EXPECTED:
            atk.worst_opposition = (
                "إعادة تكييف القضية بالكامل لصالح الطرف الآخر + "
                "إسقاط الأركان المطلوبة"
            )
        elif h.hypothesis_type == HypothesisType.AGGRESSIVE:
            atk.worst_opposition = (
                "انتفاء القصد + تفسير الشك لصالح المتهم → براءة"
            )
        elif h.hypothesis_type == HypothesisType.DEFENSIVE:
            atk.worst_opposition = (
                "إثبات النية الجنائية بأدلة قاطعة → تشديد العقوبة"
            )
        else:
            atk.worst_opposition = (
                f"إعادة التكييف خارج مجال {h.domain} بناءً على وقائع مستجدة"
            )

        # 4. Reclassification risk (how easy to move this to another domain)
        atk.reclassification_risk = min(1.0,
            h.contradiction_risk * 0.6 + (
                0.3 if h.hypothesis_type == HypothesisType.HYBRID_CROSS_DOMAIN
                else 0.1
            )
        )

        # 5. Collapse score
        atk.collapse_score = _compute_collapse_score(h, score)

        # 6. Survival decision
        if atk.collapse_score >= collapse_threshold:
            atk.survives = False
            atk.collapse_reasons.append(
                f"collapse_score:{atk.collapse_score:.2f}_above_{collapse_threshold}"
            )
        if score.legal_plausibility < 0.20:
            atk.survives = False
            atk.collapse_reasons.append("legal_plausibility_too_low")
        if score.composite < 0.30:
            atk.survives = False
            atk.collapse_reasons.append("composite_too_low")

        out.append((h, score, atk))
    return out


# ═════════════════════════════════════════════════════════════════
# Survival filter — keep top 2-3 DISTINCT paths
# ═════════════════════════════════════════════════════════════════

def select_survivors(
    attacked: list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]],
    max_survivors: int = 3,
) -> list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]]:
    """Pick the top N while enforcing diversity (no two survivors of the
    same domain+subdomain)."""
    # First filter: only those that survived adversarial attack
    alive = [t for t in attacked if t[2].survives]

    # Sort by composite descending
    alive.sort(key=lambda t: -t[1].composite)

    # Always include WORST_CASE_EXPOSURE if present + survived (explicit exposure)
    worst_case_survivors = [
        t for t in alive
        if t[0].hypothesis_type == HypothesisType.WORST_CASE_EXPOSURE
    ]

    survivors: list[tuple[Hypothesis, ScoreBreakdown, AdversarialAttack]] = []
    seen_domains: set[tuple[str, str]] = set()

    for triple in alive:
        h = triple[0]
        key = (h.domain, h.subdomain)
        if key in seen_domains:
            continue
        survivors.append(triple)
        seen_domains.add(key)
        if len(survivors) >= max_survivors:
            break

    # If no worst-case in survivors and we still have slot + distinct domain,
    # inject one as an explicit exposure warning.
    if (worst_case_survivors
            and not any(s[0].hypothesis_type == HypothesisType.WORST_CASE_EXPOSURE
                         for s in survivors)
            and len(survivors) < max_survivors):
        wc = worst_case_survivors[0]
        wc_key = (wc[0].domain, wc[0].subdomain)
        if wc_key not in seen_domains:
            survivors.append(wc)
            seen_domains.add(wc_key)

    return survivors
