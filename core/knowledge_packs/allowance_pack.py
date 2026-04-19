# -*- coding: utf-8 -*-
"""Allowance Knowledge Pack — government employee allowances and benefits."""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_allowance_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        EvidenceEntry(
            entry_id="alw_001_housing_married",
            statement_ar="يُمنح الموظف القطري المتزوج الذكر سكناً حكومياً أو بدل سكن وفقاً للفئات المحددة في اللائحة.",
            domain="allowance", topic="housing",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="اللائحة التنفيذية لقانون الخدمة المدنية",
            source_article="المادة 26",
            tags=["بدل سكن", "متزوج"],
        ),
        EvidenceEntry(
            entry_id="alw_002_housing_non_qatari",
            statement_ar="يستحق الموظف غير القطري الذي لا يُخصص له سكن حكومي علاوة بدل سكن شهرية حسب فئات محددة.",
            domain="allowance", topic="housing",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="اللائحة التنفيذية لقانون الخدمة المدنية",
            source_article="المادة 28",
            tags=["بدل سكن", "غير قطري"],
        ),
        EvidenceEntry(
            entry_id="alw_003_social_allowance",
            statement_ar="العلاوة الاجتماعية تُمنح للموظف المتزوج أو من يعول أبناء، وتختلف حسب الحالة الاجتماعية.",
            domain="allowance", topic="social",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="legal_inference",
            source_law="قانون الموارد البشرية المدنية",
            confidence_rationale="مفهوم عام في نظام الخدمة المدنية",
            tags=["علاوة اجتماعية", "متزوج"],
        ),
        EvidenceEntry(
            entry_id="alw_004_transport",
            statement_ar="بدل النقل يُمنح للموظف لتغطية تكاليف التنقل من وإلى مقر العمل.",
            domain="allowance", topic="transport",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="legal_inference",
            tags=["بدل نقل"],
        ),
        EvidenceEntry(
            entry_id="alw_005_recruitment_retention",
            statement_ar="يجوز منح الموظف القطري علاوة استقطاب واستبقاء على ألا يتجاوز الراتب الأساسي والعلاوة نهاية المربوط.",
            domain="allowance", topic="recruitment",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون الموارد البشرية المدنية",
            source_article="المادة 26 مكرراً",
            tags=["علاوة استقطاب", "استبقاء"],
        ),
        EvidenceEntry(
            entry_id="alw_006_travel_class",
            statement_ar="تذاكر السفر للموفدين: الدرجة الأولى لمن راتبه يفوق حداً معيناً، والدرجة السياحية لبقية الموظفين.",
            domain="allowance", topic="travel",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="اللائحة التنفيذية لقانون الخدمة المدنية",
            source_article="المادة 33",
            tags=["تذاكر سفر", "درجة أولى"],
        ),
        EvidenceEntry(
            entry_id="alw_007_overtime",
            statement_ar="الحد الأقصى لساعات العمل الإضافية: 3 ساعات في أيام العمل العادية و8 ساعات في العطلات.",
            domain="allowance", topic="overtime",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="اللائحة التنفيذية لقانون الخدمة المدنية",
            source_article="المادة 38",
            tags=["عمل إضافي", "ساعات"],
        ),
        EvidenceEntry(
            entry_id="alw_008_total_blocked",
            statement_ar="لا يمكن تحديد إجمالي الراتب الشامل من الجدول وحده لأن البدلات تختلف حسب الجهة والحالة الاجتماعية والجنسية.",
            domain="allowance", topic="total_salary",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            source_type="limitation",
            tags=["إجمالي الراتب", "محدودية"],
        ),
        EvidenceEntry(
            entry_id="alw_009_excellence_bonus",
            statement_ar="يجوز منح مكافأة تميز وظيفي للموظف الذي ساهم في حصول جهته على جائزة التميز الحكومي.",
            domain="allowance", topic="bonus",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="اللائحة التنفيذية لقانون الموارد البشرية",
            source_article="المادة 45 مكرراً",
            tags=["مكافأة تميز"],
        ),
        EvidenceEntry(
            entry_id="alw_010_specialization",
            statement_ar="يجوز منح بدل تخصص للوظائف التي تتطلب مؤهلات متخصصة نادرة.",
            domain="allowance", topic="specialization",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="legal_inference",
            confidence_rationale="مذكور في قرارات خاصة بالجهات",
            tags=["بدل تخصص"],
        ),
    ]
