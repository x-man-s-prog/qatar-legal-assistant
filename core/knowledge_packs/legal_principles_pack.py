# -*- coding: utf-8 -*-
"""Legal Principles Pack — fundamental principles of Qatari law."""
from core.evidence_registry import EvidenceEntry, SupportLevel


def get_legal_principles_entries() -> list[EvidenceEntry]:
    S = SupportLevel
    return [
        EvidenceEntry(
            entry_id="lp_001_presumption_innocence",
            statement_ar="المتهم بريء حتى تثبت إدانته بحكم قضائي بات.",
            domain="legal_principles", topic="criminal",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="constitutional", source_law="الدستور القطري",
            source_article="المادة 39",
            tags=["قرينة البراءة", "جنائي"],
        ),
        EvidenceEntry(
            entry_id="lp_002_no_crime_without_law",
            statement_ar="لا جريمة ولا عقوبة إلا بنص قانوني.",
            domain="legal_principles", topic="criminal",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="constitutional", source_law="الدستور القطري",
            source_article="المادة 36",
            tags=["شرعية الجرائم", "نص قانوني"],
        ),
        EvidenceEntry(
            entry_id="lp_003_doubt_favors_accused",
            statement_ar="الشك يُفسّر لمصلحة المتهم.",
            domain="legal_principles", topic="criminal",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="judicial_principle",
            tags=["الشك لمصلحة المتهم"],
        ),
        EvidenceEntry(
            entry_id="lp_004_right_to_defense",
            statement_ar="حق الدفاع مكفول في جميع مراحل التحقيق والمحاكمة.",
            domain="legal_principles", topic="criminal",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="constitutional", source_law="الدستور القطري",
            source_article="المادة 39",
            tags=["حق الدفاع"],
        ),
        EvidenceEntry(
            entry_id="lp_005_non_retroactivity",
            statement_ar="لا تسري أحكام القوانين إلا على ما يقع من تاريخ العمل بها، ولا يترتب عليها أثر فيما وقع قبلها.",
            domain="legal_principles", topic="general",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="constitutional",
            tags=["عدم رجعية القوانين"],
        ),
        EvidenceEntry(
            entry_id="lp_006_equality",
            statement_ar="الناس متساوون أمام القانون، لا تمييز بينهم بسبب الجنس أو الأصل أو اللغة أو الدين.",
            domain="legal_principles", topic="general",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="constitutional", source_law="الدستور القطري",
            source_article="المادة 35",
            tags=["المساواة"],
        ),
        EvidenceEntry(
            entry_id="lp_007_legal_hierarchy",
            statement_ar="تدرج القواعد القانونية: الدستور أعلى من القانون، والقانون أعلى من المرسوم، والمرسوم أعلى من القرار الوزاري.",
            domain="legal_principles", topic="hierarchy",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="constitutional",
            tags=["التدرج القانوني", "هرمية"],
        ),
        EvidenceEntry(
            entry_id="lp_008_special_overrides_general",
            statement_ar="القانون الخاص يُقدَّم على القانون العام عند التعارض في نفس المرتبة.",
            domain="legal_principles", topic="hierarchy",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="legal_principle",
            tags=["الخاص يقيد العام"],
        ),
        EvidenceEntry(
            entry_id="lp_009_later_overrides_earlier",
            statement_ar="القانون اللاحق يُلغي القانون السابق في حالة التعارض إذا كانا في نفس المرتبة والنطاق.",
            domain="legal_principles", topic="hierarchy",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="legal_principle",
            tags=["اللاحق يلغي السابق"],
        ),
        EvidenceEntry(
            entry_id="lp_010_contract_binding",
            statement_ar="العقد شريعة المتعاقدين — لا يجوز نقضه أو تعديله إلا باتفاق الطرفين أو للأسباب التي يقرها القانون.",
            domain="legal_principles", topic="civil",
            support_level=S.DIRECT_EVIDENCE.value,
            source_type="law_text", source_law="القانون المدني رقم 22 لسنة 2004",
            tags=["العقد شريعة المتعاقدين", "مدني"],
        ),
    ]
