# -*- coding: utf-8 -*-
"""Penalty Knowledge Pack — criminal and regulatory penalties in Qatari law."""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_penalty_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        # ── Drug Penalties (Law 9/1987) ──
        EvidenceEntry(
            entry_id="pen_001_drug_trafficking",
            statement_ar="عقوبة الاتجار بالمخدرات والتهريب: الإعدام أو السجن المؤبد وغرامة لا تزيد على 500,000 ريال.",
            domain="penalty", topic="drug_trafficking",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون مكافحة المخدرات رقم 9 لسنة 1987",
            source_article="المادة 34",
            tags=["اتجار", "مخدرات", "إعدام", "مؤبد"],
        ),
        EvidenceEntry(
            entry_id="pen_002_drug_possession_trafficking",
            statement_ar="عقوبة حيازة المخدرات بقصد الاتجار: الحبس مدة لا تقل عن 7 سنوات ولا تزيد على 15 سنة.",
            domain="penalty", topic="drug_possession",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون مكافحة المخدرات رقم 9 لسنة 1987",
            source_article="المادة 34",
            tags=["حيازة", "اتجار", "مخدرات"],
        ),
        EvidenceEntry(
            entry_id="pen_003_drug_use",
            statement_ar="عقوبة تعاطي المخدرات: الحبس مدة لا تقل عن سنة ولا تزيد على 3 سنوات.",
            domain="penalty", topic="drug_use",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون مكافحة المخدرات رقم 9 لسنة 1987",
            source_article="المادة 35",
            tags=["تعاطي", "مخدرات"],
        ),
        EvidenceEntry(
            entry_id="pen_004_drug_personal",
            statement_ar="عقوبة حيازة المخدرات للاستعمال الشخصي: الحبس مدة لا تقل عن 6 أشهر.",
            domain="penalty", topic="drug_possession",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون مكافحة المخدرات رقم 9 لسنة 1987",
            tags=["حيازة", "استعمال شخصي"],
        ),
        # ── Criminal Penalties (Law 11/2004) ──
        EvidenceEntry(
            entry_id="pen_005_murder",
            statement_ar="عقوبة القتل العمد مع سبق الإصرار والترصد: الإعدام.",
            domain="penalty", topic="murder",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العقوبات رقم 11 لسنة 2004",
            source_article="المادة 300",
            tags=["قتل عمد", "إعدام"],
        ),
        EvidenceEntry(
            entry_id="pen_006_theft_simple",
            statement_ar="عقوبة السرقة البسيطة: الحبس مدة لا تتجاوز 3 سنوات.",
            domain="penalty", topic="theft",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العقوبات رقم 11 لسنة 2004",
            source_article="المادة 310",
            tags=["سرقة", "حبس"],
        ),
        EvidenceEntry(
            entry_id="pen_007_theft_aggravated",
            statement_ar="عقوبة السرقة المشددة (بالإكراه أو ليلاً أو بالسلاح): الحبس مدة لا تتجاوز 7 سنوات.",
            domain="penalty", topic="theft",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العقوبات رقم 11 لسنة 2004",
            source_article="المواد 311-320",
            tags=["سرقة مشددة", "إكراه"],
        ),
        EvidenceEntry(
            entry_id="pen_008_assault",
            statement_ar="عقوبة الإيذاء العمد: الحبس مدة لا تتجاوز 3 سنوات أو الغرامة.",
            domain="penalty", topic="assault",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العقوبات رقم 11 لسنة 2004",
            tags=["إيذاء", "ضرب"],
        ),
        EvidenceEntry(
            entry_id="pen_009_fraud",
            statement_ar="عقوبة النصب والاحتيال: الحبس مدة لا تتجاوز 5 سنوات.",
            domain="penalty", topic="fraud",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العقوبات رقم 11 لسنة 2004",
            tags=["نصب", "احتيال"],
        ),
        EvidenceEntry(
            entry_id="pen_010_bounced_check",
            statement_ar="عقوبة إصدار شيك بدون رصيد: الحبس مدة لا تتجاوز 3 سنوات أو الغرامة.",
            domain="penalty", topic="check_fraud",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العقوبات رقم 11 لسنة 2004",
            source_article="المادة 357",
            tags=["شيك بدون رصيد"],
        ),
        # ── Labor Penalties (Law 14/2004) ──
        EvidenceEntry(
            entry_id="pen_011_unfair_dismissal",
            statement_ar="تعويض الفصل التعسفي: لا يقل عن أجر شهرين (المادة 49 من قانون العمل).",
            domain="penalty", topic="unfair_dismissal",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العمل رقم 14 لسنة 2004",
            source_article="المادة 49",
            tags=["فصل تعسفي", "تعويض"],
        ),
        EvidenceEntry(
            entry_id="pen_012_end_of_service",
            statement_ar="مكافأة نهاية الخدمة: 3 أسابيع أجر عن كل سنة خدمة (المادة 54).",
            domain="penalty", topic="end_of_service",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="قانون العمل رقم 14 لسنة 2004",
            source_article="المادة 54",
            tags=["مكافأة نهاية الخدمة"],
        ),
        # ── Controlled Inferences ──
        EvidenceEntry(
            entry_id="pen_013_penalty_graduation",
            statement_ar="العقوبات في قانون المخدرات تتدرج حسب خطورة الفعل: الاتجار أشد من الحيازة، والحيازة أشد من التعاطي.",
            domain="penalty", topic="penalty_structure",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="legal_inference",
            confidence_rationale="مستنتج من ترتيب المواد 34-37 وتدرج العقوبات",
            tags=["تدرج العقوبات"],
        ),
        EvidenceEntry(
            entry_id="pen_014_aggravating_factors",
            statement_ar="الظروف المشددة (كالبيع بالقرب من المدارس أو لقاصر) قد ترفع العقوبة. الظروف المخففة (كالتسليم الطوعي) قد تخففها.",
            domain="penalty", topic="sentencing",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="legal_inference",
            confidence_rationale="مبدأ عام في القانون الجنائي القطري",
            tags=["ظروف مشددة", "ظروف مخففة"],
        ),
        # ── Blocked ──
        EvidenceEntry(
            entry_id="pen_015_exact_sentences_blocked",
            statement_ar="لا يمكن تحديد العقوبة الدقيقة لكل قضية من النص القانوني وحده — تعتمد على ظروف القضية وتقدير المحكمة.",
            domain="penalty", topic="sentencing",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            source_type="limitation",
            tags=["تقدير المحكمة"],
        ),
    ]
