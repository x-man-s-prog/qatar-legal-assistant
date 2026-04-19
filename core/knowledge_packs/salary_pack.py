# -*- coding: utf-8 -*-
"""
Salary Knowledge Pack v1
========================
Curated knowledge about Qatar civil service salary structure.

Concepts covered:
  - basic salary (المربوط الأساسي)
  - beginning/end of bound (بداية/نهاية المربوط)
  - allowances (البدلات والعلاوات)
  - social allowance, housing, transport
  - total compensation limitations
  - government-wide table vs special-entity regime
  - periodic increment (العلاوة الدورية)
"""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_salary_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        # ── Basic Salary Concepts ──────────────────────────────
        EvidenceEntry(
            entry_id="sal_001_marbout_definition",
            statement_ar="المربوط هو الراتب الأساسي الشهري المحدد لكل درجة وظيفية في جدول الدرجات والرواتب، وله حد أدنى (بداية المربوط) وحد أقصى (نهاية المربوط).",
            domain="salary", topic="basic_salary",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية رقم 15 لسنة 2016",
            confidence_rationale="تعريف صريح في القانون",
            tags=["مربوط", "راتب أساسي", "تعريف"],
        ),
        EvidenceEntry(
            entry_id="sal_002_start_end_bound",
            statement_ar="بداية المربوط هي أقل راتب أساسي للدرجة، ونهاية المربوط هي أعلى راتب أساسي يمكن الوصول إليه في تلك الدرجة.",
            domain="salary", topic="basic_salary",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="salary_table",
            source_law="قانون الموارد البشرية المدنية",
            tags=["بداية المربوط", "نهاية المربوط"],
        ),
        EvidenceEntry(
            entry_id="sal_003_periodic_increment",
            statement_ar="العلاوة الدورية هي زيادة سنوية تُضاف إلى الراتب الأساسي للموظف حتى بلوغ نهاية مربوط درجته.",
            domain="salary", topic="periodic_increment",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["علاوة دورية", "زيادة سنوية"],
        ),
        EvidenceEntry(
            entry_id="sal_004_grade_structure",
            statement_ar="يتضمن جدول الدرجات والرواتب درجات من الممتازة والخاصة وصولاً إلى الدرجة السابعة، ولكل درجة بداية ونهاية مربوط محددتان.",
            domain="salary", topic="grade_structure",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="salary_table",
            source_law="قانون الموارد البشرية المدنية",
            tags=["هيكل الدرجات", "جدول الرواتب"],
        ),

        # ── Allowances ────────────────────────────────────────
        EvidenceEntry(
            entry_id="sal_010_allowances_exist",
            statement_ar="يستحق الموظف بدلات وعلاوات إضافة إلى الراتب الأساسي، تشمل: بدل السكن، البدل الاجتماعي، بدل النقل، وبدلات أخرى تحددها الجهة.",
            domain="salary", topic="allowances",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["بدلات", "علاوات", "سكن", "اجتماعي", "نقل"],
        ),
        EvidenceEntry(
            entry_id="sal_011_allowances_vary",
            statement_ar="تختلف قيمة البدلات والعلاوات بحسب الدرجة الوظيفية والحالة الاجتماعية والجهة الحكومية.",
            domain="salary", topic="allowances",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["بدلات متغيرة", "حالة اجتماعية"],
        ),
        EvidenceEntry(
            entry_id="sal_012_social_allowance",
            statement_ar="البدل الاجتماعي يختلف بحسب الحالة الاجتماعية للموظف (أعزب، متزوج، لديه أبناء).",
            domain="salary", topic="social_allowance",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["بدل اجتماعي", "متزوج", "أعزب"],
        ),

        # ── Total Compensation ────────────────────────────────
        EvidenceEntry(
            entry_id="sal_020_total_not_in_table",
            statement_ar="جدول الدرجات والرواتب يعرض المربوط الأساسي فقط، ولا يتضمن إجمالي الراتب الشامل للبدلات والعلاوات.",
            domain="salary", topic="total_compensation",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="salary_table",
            source_law="قانون الموارد البشرية المدنية",
            confidence_rationale="الجدول يحتوي فقط على أعمدة بداية/نهاية المربوط",
            tags=["إجمالي", "راتب شامل", "بدلات"],
        ),
        EvidenceEntry(
            entry_id="sal_021_total_cannot_be_exact",
            statement_ar="لا يمكن تحديد الراتب الإجمالي الدقيق من جدول المربوط وحده، لأن البدلات تختلف بحسب الجهة والحالة الاجتماعية وسنوات الخدمة.",
            domain="salary", topic="total_compensation",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="reasoning",
            confidence_rationale="استنتاج منطقي من غياب بيانات البدلات في الجدول",
            limitations=["لا يمكن تقديم رقم دقيق للإجمالي"],
            tags=["إجمالي", "تقدير", "محدودية"],
        ),
        EvidenceEntry(
            entry_id="sal_022_block_exact_total",
            statement_ar="قد يصل إجمالي الراتب إلى ضعف المربوط أو أكثر",
            domain="salary", topic="total_compensation",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="لا يوجد دليل موثق يحدد نسبة الإجمالي إلى المربوط",
            tags=["محظور", "ضعف المربوط"],
        ),

        # ── Special Entity Regimes ────────────────────────────
        EvidenceEntry(
            entry_id="sal_030_general_table_scope",
            statement_ar="جدول الدرجات والرواتب في قانون الموارد البشرية المدنية يسري على موظفي الجهات الحكومية الخاضعة للقانون.",
            domain="salary", topic="applicability",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون الموارد البشرية المدنية",
            tags=["نطاق التطبيق", "جهات حكومية"],
        ),
        EvidenceEntry(
            entry_id="sal_031_special_entities",
            statement_ar="بعض الجهات لها أنظمة رواتب خاصة قد تختلف عن الجدول العام، مثل: قطر للبترول، المصرف المركزي، بعض الهيئات المستقلة.",
            domain="salary", topic="special_regimes",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="reasoning",
            confidence_rationale="معروف أن بعض الجهات لها أنظمة خاصة، لكن التفاصيل غير متوفرة في النظام",
            limitations=["لا تتوفر تفاصيل جداول الرواتب الخاصة"],
            tags=["جهات خاصة", "أنظمة خاصة"],
        ),
        EvidenceEntry(
            entry_id="sal_032_block_specific_entity_salary",
            statement_ar="راتب موظفي قطر للبترول يبلغ كذا",
            domain="salary", topic="special_regimes",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="لا توجد بيانات موثقة عن رواتب الجهات ذات الأنظمة الخاصة",
            tags=["محظور", "جهات خاصة"],
        ),
    ]
