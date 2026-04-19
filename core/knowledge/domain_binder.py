# -*- coding: utf-8 -*-
"""
Domain Binder — rule-based tagging for domain / subdomain / issue / remedy.

Deterministic and auditable. No model calls. Every tag comes from a
concrete keyword rule that can be inspected and tested.

Design:
  - PRIMARY_DOMAIN_SIGNALS: keyword→domain weight
  - SUBDOMAIN_RULES: per-domain subdomain keywords
  - ISSUE_RULES:    keyword→issue_tag (flat across domains)
  - REMEDY_RULES:   keyword→remedy_tag
  - PROCEDURAL_RULES: keyword→procedural_tag
  - PARTY_ROLE_RULES: keyword→party_role_tag

Binding is called with the canonical_source_id if known (e.g. if the
law is `labor_law`, the primary domain is locked to EMPLOYMENT and
binding adds only subdomain/issue/remedy tags).
"""
from __future__ import annotations

import logging
from typing import Optional

from core.legal_gates import LegalDomain
from core.evidence.canonical_expanded import get_canonical_registry

log = logging.getLogger("domain_binder")


# ═════════════════════════════════════════════════════════════════
# Keyword rules
# ═════════════════════════════════════════════════════════════════

# Primary domain signals — weighted. Max-wins unless locked by canonical.
_DOMAIN_SIGNALS: dict[LegalDomain, list[tuple[str, int]]] = {
    LegalDomain.EMPLOYMENT: [
        ("عمل", 3), ("عامل", 3), ("صاحب العمل", 4), ("عقد العمل", 5),
        ("فصل", 3), ("استقالة", 3), ("راتب", 3), ("مكافأة نهاية الخدمة", 5),
        ("إصابة عمل", 4), ("إجازة", 2), ("ساعات العمل", 4), ("كفيل", 2),
        ("تقاعد", 3), ("معاش", 3),
    ],
    LegalDomain.CRIMINAL: [
        ("عقوبة", 4), ("يعاقب", 4), ("يُعاقب", 4), ("جريمة", 3), ("حبس", 3),
        ("سرقة", 4), ("قتل", 4), ("ضرب", 3), ("تزوير", 4), ("رشوة", 4),
        ("نصب", 3), ("احتيال", 3), ("تشهير", 3), ("ابتزاز", 4), ("تحرش", 3),
        ("مخدرات", 5), ("جرائم إلكترونية", 5), ("غسل الأموال", 5),
        ("حبس احتياطي", 4),
    ],
    LegalDomain.FAMILY: [
        ("زواج", 3), ("طلاق", 3), ("خلع", 4), ("حضانة", 5), ("نفقة", 4),
        ("عدة", 4), ("مهر", 3), ("ولاية", 3), ("وصاية", 3), ("نسب", 3),
        ("رؤية الأطفال", 4), ("زوج", 2), ("زوجة", 2),
    ],
    LegalDomain.CIVIL: [
        ("عقد", 2), ("التزام", 3), ("ضرر", 2), ("تعويض", 3),
        ("مسؤولية تقصيرية", 5), ("بطلان العقد", 4), ("فسخ", 3), ("شرط جزائي", 4),
        ("بيع", 2), ("إيجار", 2), ("ملكية", 2),
        # Construction / muqawala
        ("عقد مقاولة", 5), ("المقاول", 3), ("رب العمل", 4),
        ("استلام المنشأ", 5), ("رفض الاستلام", 5), ("تسليم المشروع", 4),
        ("عيب جوهري", 5), ("عيب طفيف", 4), ("ضمان البناء", 4),
        ("الضمان العشري", 4),
    ],
    LegalDomain.COMMERCIAL: [
        ("شركة", 3), ("شريك", 3), ("مساهم", 4), ("وكالة تجارية", 5),
        ("علامة تجارية", 3), ("إفلاس", 5), ("إعسار", 4), ("تاجر", 2),
        ("سجل تجاري", 4), ("تصفية", 3),
    ],
    LegalDomain.RENTAL: [
        ("إيجار", 3), ("مستأجر", 4), ("مؤجر", 4), ("إخلاء", 5),
        ("قيمة الإيجار", 4), ("تجديد الإيجار", 4),
    ],
    LegalDomain.BANKING: [
        ("بنك", 3), ("مصرف", 4), ("قرض", 3), ("تسهيلات", 3),
        ("حساب بنكي", 4), ("فوائد", 3), ("شيك", 3), ("رهن", 3),
    ],
    LegalDomain.INTELLECTUAL_PROPERTY: [
        ("حق المؤلف", 5), ("علامة تجارية", 4), ("ملكية فكرية", 5),
        ("براءة اختراع", 5), ("نسخ غير مشروع", 4),
    ],
    LegalDomain.TRAFFIC: [
        ("مرور", 3), ("سيارة", 2), ("حادث مروري", 5), ("رخصة قيادة", 4),
        ("مخالفة مرورية", 4),
    ],
    LegalDomain.ADMINISTRATIVE: [
        ("قرار إداري", 5), ("تظلم", 4), ("طعن إداري", 5), ("جهة إدارية", 4),
    ],
    LegalDomain.PROCEDURAL: [
        ("طعن", 3), ("تمييز", 3), ("استئناف", 3), ("مرافعات", 3),
        ("خبرة قضائية", 4), ("دعوى", 2),
    ],
}


# Subdomain rules — per primary domain
_SUBDOMAIN_RULES: dict[LegalDomain, dict[str, list[str]]] = {
    LegalDomain.EMPLOYMENT: {
        "termination":     ["فصل", "إقالة", "إنهاء", "استقالة"],
        "end_of_service":  ["مكافأة نهاية الخدمة", "تعويض الخدمة"],
        "wages":           ["راتب", "أجر", "مستحقات", "علاوة"],
        "work_injury":     ["إصابة عمل", "ضرر مهني"],
        "leave":           ["إجازة", "إجازة مرضية", "إجازة سنوية"],
        "working_hours":   ["ساعات العمل", "ساعات إضافية"],
    },
    LegalDomain.CRIMINAL: {
        "theft":           ["سرقة", "سرق"],
        "assault":         ["ضرب", "إيذاء", "اعتداء"],
        "forgery":         ["تزوير", "مزور"],
        "bribery":         ["رشوة", "ارتشاء"],
        "fraud":           ["احتيال", "نصب", "خداع"],
        "defamation":      ["تشهير", "سب", "قذف"],
        "cyber":           ["جرائم إلكترونية", "ابتزاز إلكتروني"],
        "drug":            ["مخدرات", "حيازة مخدر"],
    },
    LegalDomain.FAMILY: {
        "custody":         ["حضانة", "حاضن"],
        "divorce":         ["طلاق", "خلع"],
        "alimony":         ["نفقة"],
        "guardianship":    ["ولاية", "وصاية"],
        "visitation":      ["رؤية الأطفال", "زيارة الأطفال"],
    },
    LegalDomain.CIVIL: {
        "contract_breach": ["إخلال بالعقد", "فسخ العقد", "بطلان"],
        "tort":            ["مسؤولية تقصيرية", "ضرر"],
        "compensation":    ["تعويض"],
        "construction_acceptance": ["استلام المنشأ", "رفض الاستلام",
                                       "تسليم المشروع", "عيب جوهري",
                                       "عيب طفيف", "عقد مقاولة"],
        "construction_warranty":   ["ضمان البناء", "الضمان العشري"],
    },
    LegalDomain.COMMERCIAL: {
        "agency":          ["وكالة تجارية"],
        "company_dispute": ["شركة", "شريك", "مساهم"],
        "bankruptcy":      ["إفلاس", "إعسار", "تصفية"],
    },
    LegalDomain.RENTAL: {
        "eviction":        ["إخلاء"],
        "rent_increase":   ["تجديد الإيجار", "قيمة الإيجار"],
    },
}


# Cross-domain issue tags
_ISSUE_RULES: dict[str, list[str]] = {
    "wrongful_termination":  ["فصل تعسفي", "فصل بغير سبب"],
    "unpaid_wages":          ["أجور متأخرة", "مستحقات غير مدفوعة"],
    "bounced_cheque":        ["شيك بدون رصيد", "لا يقابله رصيد"],
    "negligence_death":      ["إهمال", "قتل خطأ"],
    "domestic_violence":     ["عنف أسري", "ضرب الزوجة"],
    "residency":             ["إقامة", "ترحيل"],
    "substantial_defect":    ["عيب جوهري", "العيب الجوهري"],
    "minor_defect":          ["عيب طفيف", "العيب الطفيف"],
    "acceptance_refusal":    ["رفض الاستلام", "رفض استلام", "عدم الاستلام"],
    "expert_opinion_needed": ["تقرير فني", "خبرة فنية", "ندب خبير"],
}


# Remedy tags
_REMEDY_RULES: dict[str, list[str]] = {
    "compensation":       ["تعويض"],
    "imprisonment":       ["حبس", "سجن"],
    "fine":               ["غرامة"],
    "contract_rescission": ["فسخ العقد"],
    "specific_performance": ["تنفيذ عيني"],
    "custody_transfer":   ["نقل الحضانة"],
    "eviction_order":     ["أمر إخلاء"],
}


# Procedural tags
_PROCEDURAL_RULES: dict[str, list[str]] = {
    "appeal":        ["استئناف", "طعن"],
    "cassation":     ["تمييز", "نقض"],
    "interim_relief": ["أمر وقتي", "حكم مستعجل"],
    "enforcement":   ["تنفيذ حكم"],
}


# Party role tags
_PARTY_ROLE_RULES: dict[str, list[str]] = {
    "employee":    ["عامل", "موظف"],
    "employer":    ["صاحب العمل", "الشركة"],
    "landlord":    ["مؤجر", "مالك العقار"],
    "tenant":      ["مستأجر"],
    "spouse":      ["زوج", "زوجة"],
    "parent":      ["أب", "أم", "والد", "والدة"],
    "creditor":    ["دائن"],
    "debtor":      ["مدين"],
    "consumer":    ["مستهلك"],
}


# ═════════════════════════════════════════════════════════════════
# Binder
# ═════════════════════════════════════════════════════════════════

class BindingResult:
    __slots__ = ("domain", "subdomain", "issue_tags", "remedy_tags",
                 "procedural_tags", "party_role_tags", "confidence",
                 "locked_by_canonical")

    def __init__(self):
        self.domain: LegalDomain         = LegalDomain.UNKNOWN
        self.subdomain: str              = ""
        self.issue_tags: list[str]       = []
        self.remedy_tags: list[str]      = []
        self.procedural_tags: list[str]  = []
        self.party_role_tags: list[str]  = []
        self.confidence: float           = 0.0
        self.locked_by_canonical: bool   = False

    def to_dict(self) -> dict:
        return {
            "domain":          self.domain.value,
            "subdomain":       self.subdomain,
            "issue_tags":      self.issue_tags,
            "remedy_tags":     self.remedy_tags,
            "procedural_tags": self.procedural_tags,
            "party_role_tags": self.party_role_tags,
            "confidence":      round(self.confidence, 3),
            "locked_by_canonical": self.locked_by_canonical,
        }


class DomainBinder:
    def __init__(self):
        self._registry = get_canonical_registry()

    def bind(self, text: str, canonical_source_id: Optional[str] = None) -> BindingResult:
        result = BindingResult()
        if not text:
            return result

        # ── Rule 1: canonical-id lock ──
        if canonical_source_id:
            law = self._registry.get_law(canonical_source_id)
            if law is not None:
                result.domain = law.domain
                result.locked_by_canonical = True
                result.confidence = 1.0

        # ── Rule 2: keyword vote (if not locked) ──
        if not result.locked_by_canonical:
            scores: dict[LegalDomain, int] = {}
            for domain, signals in _DOMAIN_SIGNALS.items():
                total = sum(weight for kw, weight in signals if kw in text)
                if total > 0:
                    scores[domain] = total
            if scores:
                top = max(scores.items(), key=lambda kv: kv[1])
                result.domain = top[0]
                total_all = sum(scores.values())
                result.confidence = top[1] / total_all if total_all else 0.0
            else:
                result.domain = LegalDomain.UNKNOWN
                result.confidence = 0.0

        # ── Subdomain (within primary domain) ──
        if result.domain != LegalDomain.UNKNOWN:
            rules = _SUBDOMAIN_RULES.get(result.domain, {})
            for sub, kws in rules.items():
                if any(kw in text for kw in kws):
                    result.subdomain = sub
                    break

        # ── Issue tags ──
        for tag, kws in _ISSUE_RULES.items():
            if any(kw in text for kw in kws):
                result.issue_tags.append(tag)

        # ── Remedy tags ──
        for tag, kws in _REMEDY_RULES.items():
            if any(kw in text for kw in kws):
                result.remedy_tags.append(tag)

        # ── Procedural tags ──
        for tag, kws in _PROCEDURAL_RULES.items():
            if any(kw in text for kw in kws):
                result.procedural_tags.append(tag)

        # ── Party role tags ──
        for tag, kws in _PARTY_ROLE_RULES.items():
            if any(kw in text for kw in kws):
                result.party_role_tags.append(tag)

        return result


_binder: Optional[DomainBinder] = None


def get_binder() -> DomainBinder:
    global _binder
    if _binder is None:
        _binder = DomainBinder()
    return _binder
