# -*- coding: utf-8 -*-
"""
Entity Scope Knowledge Pack v1
==============================
Knowledge about which entities Qatar's civil service laws apply to.

Concepts:
  - general government entities
  - civil service applicability
  - entities with special salary systems
  - independent institutions
  - sovereign or special-regime entities
"""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_scope_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        # ── General Government Scope ──────────────────────────
        EvidenceEntry(
            entry_id="scope_001_civil_service_scope",
            statement_ar="يسري قانون الموارد البشرية المدنية على جميع الموظفين المدنيين في الجهات الحكومية، ما لم ينص قانون خاص على خلاف ذلك.",
            domain="scope", topic="civil_service",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية رقم 15 لسنة 2016",
            tags=["نطاق", "موظفون مدنيون", "جهات حكومية"],
        ),
        EvidenceEntry(
            entry_id="scope_002_government_entity_def",
            statement_ar="الجهات الحكومية تشمل الوزارات والأجهزة والهيئات والمؤسسات العامة الخاضعة لقانون الموارد البشرية المدنية.",
            domain="scope", topic="entity_definition",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["وزارات", "هيئات", "مؤسسات عامة"],
        ),

        # ── Exclusions ────────────────────────────────────────
        EvidenceEntry(
            entry_id="scope_010_military_excluded",
            statement_ar="لا يسري قانون الموارد البشرية المدنية على منتسبي القوات المسلحة والشرطة والأمن، حيث لهم قوانين خاصة.",
            domain="scope", topic="exclusions",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["استثناء", "عسكريين", "شرطة"],
        ),
        EvidenceEntry(
            entry_id="scope_011_special_entities",
            statement_ar="بعض الجهات المستقلة والهيئات ذات الطابع الخاص قد يكون لها نظام توظيف وسلم رواتب مستقل.",
            domain="scope", topic="special_entities",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="reasoning",
            confidence_rationale="معروف عملياً أن بعض الجهات لها أنظمة خاصة",
            limitations=["لا تتوفر قائمة شاملة بهذه الجهات في النظام"],
            tags=["جهات مستقلة", "أنظمة خاصة"],
        ),

        # ── Applicability Rules ───────────────────────────────
        EvidenceEntry(
            entry_id="scope_020_salary_table_applicability",
            statement_ar="جدول الدرجات والرواتب الملحق بقانون الموارد البشرية يسري على الجهات الخاضعة للقانون فقط، ولا يسري على الجهات ذات الأنظمة الخاصة.",
            domain="scope", topic="salary_table_scope",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["جدول رواتب", "نطاق تطبيق"],
        ),
        EvidenceEntry(
            entry_id="scope_021_drug_law_scope",
            statement_ar="قانون مكافحة المخدرات والمؤثرات العقلية يسري على جميع الأشخاص في دولة قطر بلا استثناء.",
            domain="scope", topic="drug_law_scope",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["مخدرات", "نطاق عام"],
        ),

        # ── Blocked Claims ────────────────────────────────────
        EvidenceEntry(
            entry_id="scope_030_block_specific_entity_list",
            statement_ar="القائمة الكاملة للجهات المستثناة من قانون الموارد البشرية هي كذا وكذا",
            domain="scope", topic="exclusion_list",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="لا تتوفر قائمة شاملة ومحدثة في النظام",
            tags=["محظور", "قائمة استثناءات"],
        ),
    ]
