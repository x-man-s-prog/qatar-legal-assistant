# -*- coding: utf-8 -*-
"""
Domain Packs — precomputed fast-path bundles per legal domain.

Each pack contains: top authoritative laws, common burdens, decisive
evidence patterns, common opponent moves. Used to seed reasoning for
Tier 1+ without re-deriving these per request.

Static data, loaded once at import. Backed by canonical registry IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DomainPack:
    domain:                str
    top_canonical_laws:    list[str] = field(default_factory=list)
    common_articles:       list[int] = field(default_factory=list)
    typical_issue_tags:    list[str] = field(default_factory=list)
    common_burdens:        list[str] = field(default_factory=list)
    decisive_patterns:     list[str] = field(default_factory=list)
    fast_path_rules:       list[str] = field(default_factory=list)


_PACKS: dict[str, DomainPack] = {
    "employment": DomainPack(
        domain="employment",
        top_canonical_laws=["labor_law", "social_security_law"],
        common_articles=[20, 36, 49, 51, 54, 55, 61, 122, 123],
        typical_issue_tags=["wrongful_termination", "unpaid_wages",
                              "end_of_service", "work_injury"],
        common_burdens=[
            "إثبات وجود علاقة عمل (عقد / كشف رواتب / إقرار).",
            "إثبات سبب الفصل من جانب صاحب العمل.",
            "إثبات مدة الخدمة المتصلة لحساب المستحقات.",
        ],
        decisive_patterns=[
            "إنذار خطّي قبل الفصل = شرط لصحة الفصل التأديبي.",
            "مكافأة نهاية الخدمة تحسب وفق آخر أجر شامل.",
        ],
        fast_path_rules=[
            "إذا الفصل بدون إنذار + بدون سبب موثق → المسار يرجح بطلان الفصل.",
        ],
    ),
    "family": DomainPack(
        domain="family",
        top_canonical_laws=["family_law"],
        common_articles=[66, 76, 114, 165, 166, 173, 174, 178],
        typical_issue_tags=["custody", "divorce", "alimony", "guardianship"],
        common_burdens=[
            "إثبات الزواج / النسب (وثيقة رسمية).",
            "إثبات أهلية الحاضن / الزوج (سلوك / استقرار).",
            "إثبات الدخل لتقدير النفقة.",
        ],
        decisive_patterns=[
            "حضانة الصغير حق للأم ما لم يثبت ما يُسقطه.",
            "النفقة تُقدَّر بحسب يسار المنفِق وحاجة المنفَق عليه.",
        ],
        fast_path_rules=[
            "إذا الطفل دون السن المحدد + الأم أهل → يرجح بقاء الحضانة لها.",
        ],
    ),
    "criminal": DomainPack(
        domain="criminal",
        top_canonical_laws=["penal_code", "criminal_procedure",
                             "cyber_crimes_law"],
        common_articles=[203, 245, 306, 311, 357, 379],
        typical_issue_tags=["theft", "forgery", "fraud", "assault"],
        common_burdens=[
            "إثبات الركن المادي للجريمة.",
            "إثبات القصد الجنائي.",
            "إثبات نسبة الفعل للمتهم بأدلة مادية أو شهود.",
        ],
        decisive_patterns=[
            "الشك يُفسَّر لمصلحة المتهم.",
            "الاعتراف المنتزع تحت إكراه باطل.",
        ],
        fast_path_rules=[
            "إذا الأدلة ظرفية + متناقضة → المسار يرجح البراءة.",
        ],
    ),
    "civil": DomainPack(
        domain="civil",
        top_canonical_laws=["civil_code"],
        common_articles=[171, 199, 215, 256, 386,
                          # Construction (muqawala) — Civil Code articles range 682+
                          682, 685, 688, 689, 690, 691, 696, 711],
        typical_issue_tags=["contract_breach", "tort", "compensation",
                              "construction_acceptance", "construction_warranty",
                              "substantial_defect", "minor_defect",
                              "acceptance_refusal", "expert_opinion_needed"],
        common_burdens=[
            "إثبات وجود الالتزام (العقد / المصدر).",
            "إثبات الإخلال.",
            "إثبات الضرر والعلاقة السببية.",
            "في المقاولة: إثبات وجود العيب يقع على رب العمل، وإثبات تنفيذ العمل وفق المواصفات على المقاول.",
        ],
        decisive_patterns=[
            "العقد شريعة المتعاقدين.",
            "التعويض يجبر الضرر المباشر المتوقع.",
            "في المقاولة: العيب الجوهري يبيح رفض الاستلام؛ العيب الطفيف لا يبيحه.",
            "تقرير الخبير المُعيَّن من المحكمة هو أقوى دليل في النزاعات الفنية.",
        ],
        fast_path_rules=[
            "إذا العقد مكتوب + الإخلال موثق + الضرر مقدَّر → المسار يرجح التعويض.",
            "إذا غاب التقرير الفني المتفق عليه في نزاع مقاولة → الخطوة الأولى ندب خبير من المحكمة.",
            "إذا تسلَّم رب العمل المنشأ فعلاً واستعمله ثم احتج بعيب ظاهر → يسقط حقه في الاحتجاج.",
        ],
    ),
    "commercial": DomainPack(
        domain="commercial",
        top_canonical_laws=["commercial_law", "companies_law",
                             "commercial_agencies_law"],
        common_articles=[],
        typical_issue_tags=["agency", "company_dispute", "bankruptcy"],
        common_burdens=[
            "إثبات الصفة التجارية.",
            "إثبات قيد العقد التجاري في السجل.",
        ],
        decisive_patterns=[
            "إنهاء الوكالة التجارية بدون مبرر يستوجب التعويض.",
        ],
        fast_path_rules=[],
    ),
    "rental": DomainPack(
        domain="rental",
        top_canonical_laws=["rental_law"],
        common_articles=[],
        typical_issue_tags=["eviction", "rent_increase"],
        common_burdens=[
            "إثبات وجود عقد إيجار صحيح.",
            "إثبات سبب الإخلاء (تأخر / تعدي / حاجة).",
        ],
        decisive_patterns=[
            "الإنذار الكتابي شرط في معظم حالات الإخلاء.",
        ],
        fast_path_rules=[],
    ),
    "banking": DomainPack(
        domain="banking",
        top_canonical_laws=["central_bank_law", "civil_code",
                             "commercial_law"],
        common_articles=[],
        typical_issue_tags=["loan_dispute", "interest_dispute"],
        common_burdens=[
            "إثبات وجود عقد القرض.",
            "إثبات قيمة المبلغ الفعلي والفائدة المتفق عليها.",
        ],
        decisive_patterns=[
            "الفائدة المركبة محظورة في حالات محددة.",
        ],
        fast_path_rules=[],
    ),
}


def get_domain_pack(domain_value: str) -> Optional[DomainPack]:
    return _PACKS.get(domain_value)


def all_pack_domains() -> list[str]:
    return list(_PACKS.keys())
