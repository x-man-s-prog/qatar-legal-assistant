# -*- coding: utf-8 -*-
"""
Legal Reasoning Concepts Pack v1
================================
Meta-knowledge about how to reason over legal information.

Concepts:
  - direct evidence vs controlled inference vs unsupported claim
  - scope limitation
  - applicability
  - interpretation boundary
  - evidence quality markers
"""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_reasoning_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        # ── Evidence Quality Concepts ─────────────────────────
        EvidenceEntry(
            entry_id="reason_001_direct_evidence",
            statement_ar="الدليل المباشر هو ما ورد صراحة في نص القانون أو الجدول أو البيانات الموثقة.",
            domain="reasoning", topic="evidence_quality",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["دليل مباشر", "تعريف"],
        ),
        EvidenceEntry(
            entry_id="reason_002_controlled_inference",
            statement_ar="الاستنتاج المضبوط هو تفسير معقول مبني على أدلة متاحة، ويُقدم بصورة محددة وحذرة ومحدودة النطاق.",
            domain="reasoning", topic="evidence_quality",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["استنتاج مضبوط", "تعريف"],
        ),
        EvidenceEntry(
            entry_id="reason_003_unsupported_claim",
            statement_ar="الادعاء غير المدعوم هو أي تصريح لا يوجد له سند كاف في البيانات المتاحة، ويجب حظره أو تخفيفه إلى محدودية.",
            domain="reasoning", topic="evidence_quality",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["ادعاء غير مدعوم", "حظر"],
        ),

        # ── Reasoning Boundaries ──────────────────────────────
        EvidenceEntry(
            entry_id="reason_010_scope_limitation",
            statement_ar="عند عدم وجود بيانات كافية، يجب الإشارة بوضوح إلى حدود المعلومات المتاحة بدلاً من تقديم إجابة غير مؤكدة.",
            domain="reasoning", topic="limitations",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["محدودية", "نطاق المعلومات"],
        ),
        EvidenceEntry(
            entry_id="reason_011_applicability_check",
            statement_ar="قبل تقديم أي إجابة، يجب التحقق من أن القانون أو الجدول المعني ينطبق فعلاً على الحالة المسؤول عنها.",
            domain="reasoning", topic="applicability",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["قابلية التطبيق", "تحقق"],
        ),
        EvidenceEntry(
            entry_id="reason_012_interpretation_boundary",
            statement_ar="التفسير القانوني يجب أن يبقى ضمن ما يدعمه النص الصريح والسياق القانوني، دون التوسع في الافتراضات.",
            domain="reasoning", topic="interpretation",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["تفسير", "حدود"],
        ),

        # ── Answer Strategy Concepts ──────────────────────────
        EvidenceEntry(
            entry_id="reason_020_answer_pattern",
            statement_ar="الإجابة المثلى تتضمن: (1) إجابة مباشرة، (2) شرح موجز مسنود، (3) توضيح عملي اختياري، (4) بيان محدودية إذا لزم.",
            domain="reasoning", topic="answer_strategy",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["نمط إجابة", "استراتيجية"],
        ),
        EvidenceEntry(
            entry_id="reason_021_fact_vs_inference",
            statement_ar="يجب التمييز الواضح بين ما هو مذكور صراحة (حقيقة) وما هو مستنتج (تفسير)، مع الإشارة الصريحة عند الانتقال من أحدهما إلى الآخر.",
            domain="reasoning", topic="fact_vs_inference",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="meta_knowledge",
            tags=["حقيقة", "استنتاج", "تمييز"],
        ),

        # ── Blocked Reasoning Patterns ────────────────────────
        EvidenceEntry(
            entry_id="reason_030_block_speculation",
            statement_ar="من المحتمل أن يكون القانون سيتغير قريباً",
            domain="reasoning", topic="blocked_patterns",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="التكهن بالمستقبل التشريعي خارج نطاق النظام",
            tags=["محظور", "تكهن"],
        ),
        EvidenceEntry(
            entry_id="reason_031_block_personal_opinion",
            statement_ar="في رأيي هذا القانون غير عادل",
            domain="reasoning", topic="blocked_patterns",
            support_level=S.UNSUPPORTED_BLOCKED.value,
            confidence_rationale="النظام لا يقدم آراء شخصية حول العدالة التشريعية",
            tags=["محظور", "رأي شخصي"],
        ),
    ]
