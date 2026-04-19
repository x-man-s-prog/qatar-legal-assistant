# -*- coding: utf-8 -*-
"""
Drug / Schedule Knowledge Pack v1
=================================
Curated knowledge about Qatar's controlled substances law.

Concepts:
  - جدول 1, 2, 3 (schedule classification)
  - narcotics vs psychotropics vs pharmaceutical preparations
  - relationship between schedule placement and legal severity
  - medical vs illicit use distinction
"""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_drug_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        # ── Schedule Structure ─────────────────────────────────
        EvidenceEntry(
            entry_id="drug_001_three_schedules",
            statement_ar="يتضمن قانون مكافحة المخدرات والمؤثرات العقلية ثلاثة جداول ملحقة تصنف المواد الخاضعة للرقابة.",
            domain="drug", topic="schedule_structure",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية رقم 9 لسنة 1987",
            tags=["جداول", "تصنيف", "مواد خاضعة"],
        ),
        EvidenceEntry(
            entry_id="drug_002_schedule_1",
            statement_ar="الجدول الأول يتضمن المواد المخدرة، وهي الأشد خطورة من حيث التصنيف القانوني والعقوبات المترتبة.",
            domain="drug", topic="schedule_1",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["جدول أول", "مخدرات", "عقوبات شديدة"],
        ),
        EvidenceEntry(
            entry_id="drug_003_schedule_2",
            statement_ar="الجدول الثاني يتضمن المؤثرات العقلية الخاضعة للرقابة.",
            domain="drug", topic="schedule_2",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["جدول ثاني", "مؤثرات عقلية"],
        ),
        EvidenceEntry(
            entry_id="drug_004_schedule_3",
            statement_ar="الجدول الثالث يتضمن المستحضرات الصيدلانية التي تحتوي على مواد مخدرة أو مؤثرات عقلية بنسب محددة.",
            domain="drug", topic="schedule_3",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["جدول ثالث", "مستحضرات صيدلانية"],
        ),

        # ── Classification Concepts ───────────────────────────
        EvidenceEntry(
            entry_id="drug_010_narcotics_def",
            statement_ar="المواد المخدرة هي المواد الطبيعية أو الاصطناعية المدرجة في الجدول الأول الملحق بقانون مكافحة المخدرات.",
            domain="drug", topic="classification",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["مخدرات", "تعريف"],
        ),
        EvidenceEntry(
            entry_id="drug_011_psychotropics_def",
            statement_ar="المؤثرات العقلية هي المواد الطبيعية أو الاصطناعية المدرجة في الجدول الثاني والتي تؤثر على الوظائف العقلية والنفسية.",
            domain="drug", topic="classification",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["مؤثرات عقلية", "تعريف"],
        ),
        EvidenceEntry(
            entry_id="drug_012_pharma_preparations",
            statement_ar="المستحضرات الصيدلانية المدرجة في الجدول الثالث هي تركيبات دوائية تحتوي على نسب محددة من مواد مخدرة أو مؤثرة، وتخضع لرقابة مختلفة.",
            domain="drug", topic="classification",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["مستحضرات", "تركيبات دوائية"],
        ),

        # ── Severity & Penalties ──────────────────────────────
        EvidenceEntry(
            entry_id="drug_020_severity_link",
            statement_ar="تصنيف المادة في الجدول يؤثر مباشرة على شدة العقوبة: مواد الجدول الأول تستوجب عقوبات أشد من الجدول الثاني والثالث.",
            domain="drug", topic="severity",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="reasoning",
            confidence_rationale="العقوبات في القانون مرتبطة بالجدول المذكور في المادة",
            tags=["عقوبات", "شدة", "تصنيف"],
        ),

        # ── Medical vs Illicit ────────────────────────────────
        EvidenceEntry(
            entry_id="drug_030_medical_use",
            statement_ar="يجوز استخدام بعض المواد المدرجة في الجداول لأغراض طبية وعلمية مرخصة وفقاً للشروط والضوابط المنصوص عليها في القانون.",
            domain="drug", topic="medical_use",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["استخدام طبي", "ترخيص", "أغراض علمية"],
        ),
        EvidenceEntry(
            entry_id="drug_031_illicit_use",
            statement_ar="أي حيازة أو تعاطي أو اتجار بالمواد المدرجة خارج الإطار الطبي المرخص يعد جريمة يعاقب عليها القانون.",
            domain="drug", topic="illicit_use",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text",
            source_law="قانون مكافحة المخدرات والمؤثرات العقلية",
            tags=["حيازة", "تعاطي", "اتجار", "جريمة"],
        ),
        EvidenceEntry(
            entry_id="drug_032_medical_distinction",
            statement_ar="الفرق الجوهري بين الاستخدام الطبي وغير المشروع يكمن في: وجود وصفة طبية من طبيب مرخص، والحصول على المادة من مصدر مرخص، والالتزام بالجرعات المحددة.",
            domain="drug", topic="medical_vs_illicit",
            support_level=S.CONTROLLED_INFERENCE.value,
            source_type="reasoning",
            confidence_rationale="استنتاج من نصوص القانون حول الترخيص والضوابط",
            tags=["فرق طبي", "استخدام مشروع"],
        ),

        # ── Blocked Claims ────────────────────────────────────
        EvidenceEntry(
            entry_id="drug_040_block_danger_claims",
            statement_ar="هذه المواد قاتلة وتؤدي حتماً إلى الوفاة",
            domain="drug", topic="danger",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="تصريح طبي يتجاوز نطاق النظام القانوني — يحتاج مصادر طبية موثقة",
            tags=["محظور", "خطورة طبية"],
        ),
        EvidenceEntry(
            entry_id="drug_041_block_medical_advice",
            statement_ar="يمكن استخدام هذه المادة بأمان بجرعة كذا",
            domain="drug", topic="medical_advice",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="النظام قانوني وليس طبياً — لا يقدم نصائح علاجية",
            tags=["محظور", "نصيحة طبية"],
        ),
    ]
