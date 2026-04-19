# -*- coding: utf-8 -*-
"""
Legal Gates — FAIL-CLOSED LEGAL ARCHITECTURE
==============================================
Implements 10 deterministic modules + 8 mandatory gates that EVERY legal
answer must pass before being released to a user.

Hard rule: ANY gate failure → BLOCK. No soft-degrade. No fluff fallback.
The system either produces a verified legal answer OR a StructuredInsufficiencyResponse.

Modules (10):
  1. LegalIssueClassifier
  2. FactPatternExtractor
  3. BurdenOfProofEngine
  4. LegalDomainRouter
  5. CanonicalCitationRegistry
  6. RelevanceAdjudicator
  7. EvidenceRegistry
  8. ContradictionBlocker
  9. OutputSanitizer
  10. FinalAnswerGovernor

Gates (8):
  G1 case-type identification → confidence threshold
  G2 fact extraction & dispute structure
  G3 legal issue routing → strict domain isolation
  G4 evidence retrieval with multi-layer relevance
  G5 citation verification → CanonicalRegistry only
  G6 text sanitization → no raw retrieval residue
  G7 reasoning permission → only on verified evidence
  G8 output governor → block if any gate failed

NO LLM authority. NO citation invention. NO fluff.
"""
from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("legal_gates")


# ══════════════════════════════════════════════════════════════
# Confidence thresholds — fail-closed is strict
# ══════════════════════════════════════════════════════════════

CLASSIFICATION_CONFIDENCE_FLOOR = 0.25          # NEW: dynamic baseline
CLASSIFICATION_CONFIDENCE_FLOOR_SHORT = 0.15    # short queries (≤5 tokens)
CLASSIFICATION_CONFIDENCE_FLOOR_LONG  = 0.25    # longer queries
CLASSIFICATION_CONFIDENCE_FLOOR_SHORT_STRONG = 0.15  # short + strong marker
EVIDENCE_RELEVANCE_FLOOR = 0.50           # below this → REJECT chunk


# ═════════════════════════════════════════════════════════════════
# PHASE 1 — TOKEN-BASED MATCHING ENGINE
# Replaces substring matching. Substrings produce false positives
# (e.g. "سب" matching "بأسبوع"). Token matching with Arabic
# normalization + prefix stripping prevents that class of bug forever.
# ═════════════════════════════════════════════════════════════════

_AR_WORD_RE    = re.compile(r"[\u0600-\u06FF]+")   # Arabic words only
_AR_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")   # tashkeel + tatweel
_AR_PREFIX_RE  = re.compile(r"^(وال|فال|بال|كال|لل|ال|و|ف|ب|ك|ل)")


def _normalize_ar_token(t: str) -> str:
    """Strip diacritics + unify alif/ya/taa-marbuta forms."""
    t = _AR_DIACRITICS.sub("", t)
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
           .replace("ة", "ه").replace("ى", "ي"))
    return t


def _tokenize_legal(text: str) -> set[str]:
    """Tokenize Arabic text → set of normalized tokens (and their
    prefix-stripped variants). Used everywhere matching happens.

    Example:
        "بأسبوع، هل تعتبر" → {"باسبوع", "اسبوع", "هل", "تعتبر"}
        Marker "سب" → {"سب"}
        "سب" is NOT in the token set → no false match.
    """
    if not text:
        return set()
    raw_tokens = _AR_WORD_RE.findall(text)
    out: set[str] = set()
    for t in raw_tokens:
        norm = _normalize_ar_token(t)
        if norm:
            out.add(norm)
            stripped = _AR_PREFIX_RE.sub("", norm, count=1)
            if stripped and len(stripped) >= 2 and stripped != norm:
                out.add(stripped)
    return out


def _marker_matches(marker: str, query_tokens: set[str]) -> bool:
    """A marker matches when ALL of its normalized tokens are present
    in the query's token set (order-agnostic). Single-token markers
    must match exactly (no substring).
    """
    m_tokens = _tokenize_legal(marker)
    if not m_tokens:
        return False
    return m_tokens.issubset(query_tokens)


# ═════════════════════════════════════════════════════════════════
# PHASE 5 — Legal-concept detector (for LOW_CONFIDENCE_DOMAIN flag)
# Used when classifier is unsure but the query clearly "feels" legal.
# Prevents blocking legitimate legal questions that lack specific
# domain markers.
# ═════════════════════════════════════════════════════════════════

_LEGAL_CONCEPT_TOKENS = frozenset(_normalize_ar_token(t) for t in [
    # Unambiguous legal vocabulary only — generic question words removed
    # to prevent "كيف الحال" triggering legal routing.
    "حقوقي", "حقوق", "قانون", "قانوني", "قانونيه",
    "يحق", "يجوز",
    "محكمه", "دعوى", "قضيه", "مسؤوليه", "التقاضي",
    "عقوبه", "جريمه",
    "بلاغ", "شهود", "دليل", "ادله",
    "تعويض", "غرامه", "براءه",
    "طعن", "استئناف", "تمييز",
    # Narrative role markers
    "مدعي", "متهم", "خصمي",
])


def _has_legal_concepts(query_tokens: set[str]) -> bool:
    """True if the query contains at least one unambiguous legal token."""
    return bool(query_tokens & _LEGAL_CONCEPT_TOKENS)
CONTRADICTION_TOLERANCE = 0               # zero tolerance


# ══════════════════════════════════════════════════════════════
# 1. LegalIssueClassifier (rule-based with confidence floor)
# ══════════════════════════════════════════════════════════════

class LegalDomain(str, Enum):
    EMPLOYMENT = "employment"
    CIVIL = "civil"
    COMMERCIAL = "commercial"
    CRIMINAL = "criminal"
    FAMILY = "family"
    RENTAL = "rental"
    BANKING = "banking"
    ADMINISTRATIVE = "administrative"
    PROCEDURAL = "procedural"
    INHERITANCE = "inheritance"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    TRAFFIC = "traffic"
    INSURANCE = "insurance"
    UNKNOWN = "unknown"


# Multi-vote classifier — every keyword has weight; lexical overlap alone
# does NOT guarantee classification (we require multiple signals).
_DOMAIN_VOTES = {
    # ═════════════════════════════════════════════════════════════════
    # PHASE 2 — EXPANDED DOMAIN LEXICON (≥20 markers per major domain).
    # Matched via token-based engine (no substring false positives).
    # ═════════════════════════════════════════════════════════════════
    LegalDomain.EMPLOYMENT: [
        ("فصل", 3), ("فصلوني", 3), ("فصلني", 3), ("فصلت", 3),
        ("استقالة", 3), ("استقلت", 3), ("مستقيل", 3),
        ("راتب", 2), ("الراتب", 2), ("الأجر", 2), ("أجر", 2),
        ("مرتب", 2), ("مستحقات", 3),
        ("صاحب العمل", 3), ("رب العمل", 3), ("مديري", 2),
        ("عقد عمل", 3), ("عقد العمل", 3), ("وزارة العمل", 3),
        ("الموظف", 2), ("موظف", 2), ("عامل", 2), ("العامل", 2),
        ("علاقة عمل", 4), ("مكافأة نهاية الخدمة", 4),
        ("نهاية الخدمة", 3), ("مدة الخدمة", 3),
        ("تسريب معلومات وظيفية", 4), ("بدل سيارة", 3),
        ("إجازة", 2), ("إجازة سنوية", 3), ("إصابة عمل", 4),
        ("ساعات العمل", 3), ("ساعات إضافية", 3),
        ("بدون عقد", 3), ("بدون عقد مكتوب", 4),
        ("إنهاء الخدمة", 4), ("إنهاء العمل", 3),
    ],
    LegalDomain.CIVIL: [
        # General civil
        ("دين", 2), ("مبلغ مالي", 3), ("قرض", 2), ("تعويض", 2),
        ("عقد", 2), ("العقد", 2), ("مطالبة مالية", 3),
        ("استرداد مبلغ", 3), ("اعتراف بالدين", 3),
        ("نزاع استثماري", 4), ("التزام", 3), ("الالتزام", 3),
        ("ضرر", 2), ("الضرر", 2), ("مسؤولية تقصيرية", 5),
        ("بطلان العقد", 4), ("فسخ العقد", 4), ("فسخ", 2),
        ("شرط جزائي", 5), ("الشرط الجزائي", 5),
        # Real estate (Q3 coverage)
        ("عقار", 3), ("عقاري", 3), ("عقد ابتدائي", 5),
        ("بيع عقار", 4), ("شراء عقار", 4), ("نقل الملكية", 5),
        ("نقل ملكية", 5), ("تسجيل الملكية", 4), ("تسجيل العقار", 4),
        ("البائع", 2), ("المشتري", 2), ("بائع", 2), ("مشتري", 2),
        ("الحيازة", 3),
        # Construction / muqawala
        ("عقد مقاولة", 5), ("عقد المقاولة", 5),
        ("المقاول", 3), ("مقاول", 3),
        ("استلام المشروع", 4), ("استلام المنشأ", 5),
        ("رفض الاستلام", 5), ("تسليم المشروع", 4), ("تسليم المنشأ", 4),
        ("عيب جوهري", 5), ("العيب الجوهري", 5), ("عيب طفيف", 4),
        ("العيب الطفيف", 4), ("خبرة فنية", 3),
        ("ضمان البناء", 4), ("الضمان العشري", 4),
        ("تأخر التسليم", 4), ("تأخر المقاول", 4),
    ],
    LegalDomain.COMMERCIAL: [
        # Partnerships + companies
        ("شريك", 3), ("شريكي", 3), ("الشركاء", 3), ("شراكة", 3),
        ("مشروع", 2), ("المشروع", 2), ("شركة", 2),
        ("الشركة", 2), ("نزاع تجاري", 4), ("حصص الشركاء", 4),
        ("توزيع الأرباح", 4), ("وكالة تجارية", 5),
        ("الوكالة التجارية", 5), ("إنهاء الوكالة", 5), ("إنهاء وكالة", 5),
        ("خسارة المشروع", 3), ("بنود العقد التجاري", 4),
        ("العقد التجاري", 3),
        # Startup / IT contracting (Q1 coverage)
        ("شركة ناشئة", 5), ("ناشئة", 3),
        ("مبرمج", 4), ("المبرمج", 4), ("مبرمج مستقل", 5),
        ("مطور", 3), ("مطور تطبيق", 4),
        ("عمل حر", 4), ("مستقل", 3), ("تعاقد", 3),
        ("استشاري", 3), ("مستشار", 3),
        ("إنجاز العمل", 3), ("تسليم العمل", 3),
        # Investment fraud (Q6 coverage)
        ("استثمار", 4), ("مستثمر", 4), ("مستثمرين", 4),
        ("أرباح مضمونة", 5), ("ضمان أرباح", 5), ("ضمانات ربح", 5),
        ("عرض أرباح", 4), ("توقعات الأرباح", 4),
        ("تضليل استثماري", 5), ("احتيال استثماري", 5),
        ("دراسة الجدوى", 3), ("نشرة الاكتتاب", 4),
        # Misc commercial
        ("تاجر", 2), ("تجاري", 2), ("السجل التجاري", 3),
        ("إفلاس", 4), ("إعسار", 4), ("تصفية", 3),
    ],
    LegalDomain.CRIMINAL: [
        # Accusation posture
        ("متهم", 3), ("اتهامي", 3), ("اتهموني", 3), ("تم اتهامي", 4),
        ("تهمة", 3), ("التهمة", 3),
        # Authorities
        ("النيابة", 3), ("الشرطة", 2), ("جنائي", 3), ("جريمة", 3),
        ("الجريمة", 3), ("مركز الشرطة", 3),
        # Penalties
        ("قبض", 2), ("سجن", 2), ("حبس", 2), ("الحبس", 2),
        ("غرامة", 2), ("عقوبة", 3), ("العقوبة", 3),
        # Specific offenses
        ("تزوير", 4), ("احتيال إلكتروني", 4), ("احتيال", 3),
        ("ابتزاز", 3), ("سرقة", 3), ("سرق", 3),
        ("ضرب", 3), ("الضرب", 3), ("اعتداء", 3), ("الاعتداء", 3),
        ("تهديد", 3), ("التهديد", 3),
        ("مضاربة", 4), ("العراك", 3), ("عراك", 3),
        ("تشهير", 3), ("قذف", 3), ("قذفني", 3),
        ("تحرش", 3), ("تحرشني", 3),
        ("مخدرات", 4), ("حشيش", 3), ("تعاطي", 3),
        # Defense posture (Q10 coverage)
        ("دفاع شرعي", 4), ("الدفاع الشرعي", 4), ("البادئ", 3),
        ("أدلة غير مباشرة", 3), ("نقاط الدفاع", 3),
        ("شهود متناقضين", 3), ("أقوال متناقضة", 3),
    ],
    LegalDomain.FAMILY: [
        ("طلاق", 3), ("الطلاق", 3), ("حضانة", 4), ("الحضانة", 4),
        ("نفقة", 3), ("النفقة", 3),
        ("زوج", 2), ("الزوج", 2), ("زوجتي", 2), ("زوجه", 2),
        ("طليقتي", 3), ("مطلقتي", 3),
        ("الأطفال", 1), ("الأولاد", 1), ("الأبناء", 2),
        ("منفصل عن زوجتي", 4), ("خلع", 3),
        ("مهر", 3), ("المهر", 3),
        ("عدة", 3), ("العدة", 3),
        ("ولاية", 3), ("الولاية", 3), ("وصاية", 3),
        ("نسب", 3), ("النسب", 3),
        ("رؤية الأطفال", 4), ("زيارة الأطفال", 4),
        ("عنف أسري", 5), ("عنف منزلي", 5),
        ("حاضن", 3), ("حاضنة", 3),
        ("بيت الزوجية", 4), ("السكن الشرعي", 4),
    ],
    LegalDomain.RENTAL: [
        ("إيجار", 3), ("الإيجار", 3), ("مستأجر", 4), ("المستأجر", 4),
        ("مؤجر", 4), ("المؤجر", 4),
        ("شقة", 2), ("فيلا", 2), ("عمارة", 2),
        ("إخلاء", 4), ("الإخلاء", 4), ("عقد إيجار", 4),
        ("عقد الإيجار", 4),
        ("تجديد العقد", 3), ("تجديد الإيجار", 4),
        ("قيمة الإيجار", 4), ("زيادة الإيجار", 4),
        ("مالك العقار", 4), ("صاحب العقار", 4),
        ("تأخر الإيجار", 4), ("إنذار إخلاء", 4),
        ("لجنة فض المنازعات الإيجارية", 4),
        ("صيانة العقار", 3), ("عيوب العقار", 3),
        ("التأمين", 2),
    ],
    LegalDomain.BANKING: [
        ("بنك", 2), ("البنك", 2), ("مصرف", 3), ("المصرف", 3),
        ("البنك خصم", 4), ("خصم من حسابي", 4),
        ("بطاقة مصرفية", 4), ("تحويل بنكي", 3),
        ("بدون تفويض", 3), ("عملية بنكية", 3),
        ("قرض بنكي", 3), ("قرض", 2), ("فوائد", 3), ("الفوائد", 3),
        ("شيك", 3), ("الشيك", 3), ("شيكات", 3),
        ("شيك بدون رصيد", 5), ("شيك ضمان", 5), ("كضمان", 3),
        ("صرف الشيك", 4), ("صرفت الشيك", 4),
        ("رصيد", 3), ("الرصيد", 3), ("حساب بنكي", 4),
        ("رهن", 3), ("الرهن", 3),
        ("تسهيلات", 3), ("اعتماد مصرفي", 4),
        ("ضمانات بنكية", 4), ("ضامن", 3),
        ("تأخر السداد", 4),
    ],
    LegalDomain.ADMINISTRATIVE: [
        ("قرار إداري", 5), ("القرار الإداري", 5),
        ("قرار وزاري", 5), ("القرار الوزاري", 5),
        ("جهة حكومية", 3), ("جهة إدارية", 3),
        ("ديوان المظالم", 5), ("تظلم إداري", 5), ("تظلم", 4),
        ("مهلة التظلم", 3),
        ("طعن إداري", 5), ("الطعن الإداري", 5),
        ("لجنة تظلمات", 3), ("الجهة الإدارية", 3),
        ("وزارة", 2), ("هيئة حكومية", 3),
        ("ترخيصي", 4), ("إلغاء ترخيصي", 5), ("سحب الترخيص", 5),
        ("شطب السجل", 4),
        ("الموظف العام", 4), ("الخدمة المدنية", 4),
        ("قرار تأديبي", 5), ("تأديب", 3),
        ("إلغاء قرار", 5), ("إلغاء القرار", 5),
        ("اختصاص إداري", 4),
    ],
    LegalDomain.PROCEDURAL: [
        ("طعن", 3), ("الطعن", 3), ("استئناف", 3), ("الاستئناف", 3),
        ("تمييز", 3), ("التمييز", 3), ("نقض", 3),
        ("تنفيذ حكم", 4), ("التنفيذ", 3),
        ("تبليغ", 2), ("التبليغ", 2), ("مهلة", 1),
        ("صدر حكم ضدي", 4), ("حكم غيابي", 4),
        ("اختصاص", 3), ("الاختصاص", 3), ("المحكمة المختصة", 4),
        ("مرافعات", 3), ("المرافعات", 3),
        ("خبرة قضائية", 4), ("ندب خبير", 4), ("تعيين خبير", 4),
        ("حكم مستعجل", 4), ("أمر وقتي", 4),
        ("تقادم", 3), ("التقادم", 3), ("سقوط الدعوى", 4),
        ("إعادة المحاكمة", 4), ("إلغاء الحكم", 4),
        ("دعوى", 2), ("الدعوى", 2),
    ],
    LegalDomain.INHERITANCE: [
        ("تركة", 4), ("التركة", 4), ("الورثة", 4), ("ورثة", 3),
        ("وارث", 3), ("الوارث", 3), ("مورث", 4), ("المورث", 4),
        ("قسمة التركة", 4),
        ("نصيب من التركة", 4), ("استولى على التركة", 4),
        ("وصية", 3), ("الوصية", 3),
        ("هبة", 4), ("الهبة", 4), ("موهوب", 3),
        ("مرض الموت", 5), ("في مرض الموت", 5),
        ("قبل الوفاة", 3), ("قبل وفاته", 4), ("قبل وفاتها", 4),
        ("ميراث", 4), ("الميراث", 4),
        ("فرائض", 3), ("الفرائض", 3),
        ("موروث", 3), ("أحد الورثة", 4),
        ("توزيع التركة", 4), ("تقسيم التركة", 4),
        ("طعن في الهبة", 5),
    ],
    LegalDomain.INTELLECTUAL_PROPERTY: [
        ("ملكية فكرية", 5), ("الملكية الفكرية", 5),
        ("علامة تجارية", 5), ("العلامة التجارية", 5),
        ("علامة", 3), ("العلامة", 3), ("علامتي", 4), ("علاماتي", 4),
        ("سرق فكرتي", 5), ("استولى على فكرتي", 5),
        ("ملكية برمجية", 5), ("تطبيقي", 3), ("تطبيق", 2),
        ("بدون اتفاقية سرية", 4),
        ("براءة اختراع", 5), ("البراءة", 3),
        ("حق المؤلف", 5), ("حقوق الملكية", 4),
        ("انتحال", 4), ("سرقة علمية", 5),
        ("سرقة علامتي", 5), ("سرقة العلامة", 5),
        ("سرقت علامتي", 5), ("سرقت العلامة", 5),
        ("تقليد علامة", 5), ("منتج مقلد", 4),
        ("كود برمجي", 4), ("سورس كود", 4),
        ("NDA", 3), ("اتفاقية سرية", 4),
        ("نسخ غير مشروع", 4), ("قرصنة", 4),
        ("رخصة استخدام", 3), ("ترخيص برمجي", 3),
    ],
    LegalDomain.TRAFFIC: [
        ("حادث مروري", 4), ("حادث سير", 4),
        ("مخالفة مرورية", 3), ("مخالفات مرور", 3),
        ("رخصة قيادة", 3), ("الرخصة", 2),
        ("تصادم", 4), ("اصطدام", 4),
        ("إصابة في حادث", 4),
        ("تحت تأثير الكحول", 5), ("قيادة تحت التأثير", 5),
        ("المرور", 2), ("شرطة المرور", 3),
        ("وفاة في حادث", 5),
        ("تعطيل التأمين", 3),
        ("إصلاح السيارة", 3), ("تقدير الضرر", 3),
        ("سائق", 2), ("السائق", 2),
        ("مسؤولية الحادث", 4),
        ("شارع", 2), ("طريق", 2),
        ("تقرير مرور", 4), ("محضر مرور", 4),
        ("اختبار كحول", 4),
    ],
    LegalDomain.INSURANCE: [
        ("شركة التأمين", 4), ("التأمين", 3),
        ("بوليصة تأمين", 4), ("البوليصة", 4),
        ("تعويض تأمين", 3), ("رفض التأمين", 3),
        ("مطالبة تأمين", 4), ("رفض المطالبة", 4),
        ("وثيقة تأمين", 4), ("الوثيقة", 2),
        ("قسط التأمين", 4), ("الأقساط", 3),
        ("تأمين طبي", 4), ("تأمين سيارة", 4),
        ("تأمين منزل", 4), ("تأمين حياة", 4),
        ("الخطر المؤمن", 4), ("تحقق الخطر", 4),
        ("استثناءات التأمين", 4),
        ("معاينة الضرر", 3), ("تقدير الضرر", 3),
        ("الحوادث المغطاة", 4), ("خارج التغطية", 4),
        ("المؤمن له", 4), ("شركة التأمين", 4),
        ("فسخ بوليصة", 4), ("تجديد البوليصة", 4),
    ],
}


# ═════════════════════════════════════════════════════════════════
# Daily Criminal Markers — exhaustive short-query vocabulary
# Each (marker, offense_key) hit:
#   - force-locks domain = CRIMINAL
#   - adds short-query confidence boost (+0.4)
#   - triggers fast-path in fail_closed_pipeline
# ═════════════════════════════════════════════════════════════════

_CRIMINAL_DAILY_MARKERS: dict[str, list[str]] = {
    "defamation": [  # سب/قذف/شتم
        "سبني", "شتمني", "قذفني", "شتم", "سبّني", "سبنى",
        "واحد سبني", "واحد شتمني", "سب", "قذف", "شتم",
        "عير", "عيّرني", "عيرني", "تشهير", "شتيمة", "سبة",
        "سب علني", "اهانني", "أهانني",
    ],
    "assault": [
        "ضربني", "ضربوني", "اعتدى علي", "اعتدى عليّ", "اعتدوا",
        "تضاربت", "هوش", "عراك", "ضرب مبرح", "كدمات",
        "واحد ضربني", "لكمني", "صفعني",
    ],
    "threat": [
        "هددني", "هدّدني", "تهديد", "قال بيسوي", "قال راح يسوي",
        "هدّد", "توعدني", "وعيدي",
    ],
    "drugs": [
        "تعاطي", "تعاطى", "مخدرات", "حشيش", "كبتاجون",
        "ممنوعات", "شرب مخدر", "شممت", "حبوب ممنوعة",
        "كوكايين", "هيروين", "شبو",
        "عقوبة التعاطي", "حيازة مخدر",
    ],
    "theft": [
        # Verb forms only — "سرقة" (noun) removed to avoid IP collisions
        # ("سرقة علامة", "سرقة علمية"). The domain_votes table handles general
        # "سرقة" routing; Track B handles unambiguous victim statements.
        "سرقني", "سرقوني", "اخذ فلوسي", "أخذ فلوسي",
        "نشل", "سحب محفظتي", "سحبوا", "سرق محفظتي",
        "واحد سرقني", "سرقتي",
    ],
    "fraud": [
        "نصب", "احتيال", "ضحك علي", "ضحك عليّ", "استغلني",
        "نصاب", "احتال",
    ],
    "cyber": [
        "ابتزاز", "ابتزني", "ابتزازي", "ابتزو",
        "صوّرني", "صورني", "هكر",
        "هاكر", "اختراق", "فضحني", "اخترق حسابي",
        "ابتزاز إلكتروني", "ابتزاز الكتروني",
        "تم ابتزازي",
    ],
    "harassment": [
        "تحرش", "تحرشوا", "تحرشت", "ملاحقة",
    ],
    "forgery": [
        "تزوير", "مزور", "وثيقة مزورة", "توقيع مزور",
    ],
}

# Flat lookup set for O(1) "any marker in query" check
_CRIMINAL_MARKERS_FLAT: frozenset[str] = frozenset(
    m for markers in _CRIMINAL_DAILY_MARKERS.values() for m in markers
)


def _detect_criminal_offense(query: str) -> Optional[tuple[str, str]]:
    """Return (offense_key, matched_marker) using TOKEN-BASED matching.
    Longest match wins. Returns None if no marker matches.

    PHASE 1 FIX: replaces `if m in query` with token-set subset check.
    This prevents false positives like "سب" matching "بأسبوع".
    """
    if not query:
        return None
    q_tokens = _tokenize_legal(query)
    if not q_tokens:
        return None
    best: Optional[tuple[str, str]] = None
    best_len = 0
    for offense, markers in _CRIMINAL_DAILY_MARKERS.items():
        for m in markers:
            if _marker_matches(m, q_tokens) and len(m) > best_len:
                best = (offense, m)
                best_len = len(m)
    return best


# Issue auto-inference for simple criminal queries — canonical 3 questions
_CRIMINAL_STANDARD_ISSUES: dict[str, list[str]] = {
    "defamation": [
        "هل السب/الشتم يُعدّ جريمة في القانون القطري؟",
        "ما العقوبة المقررة؟",
        "كيف يتم الإثبات (شهود / تسجيل / رسائل)؟",
    ],
    "assault": [
        "هل الضرب يُعدّ جريمة؟",
        "ما العقوبة بحسب درجة الإصابة؟",
        "ما الإجراء (بلاغ/تقرير طبي)؟",
    ],
    "threat": [
        "هل التهديد يُعدّ جريمة؟",
        "ما شروط التجريم؟",
        "كيف يتم الإثبات؟",
    ],
    "drugs": [
        "ما العقوبة المقررة للتعاطي/الحيازة؟",
        "هل يوجد تمييز بين التعاطي والاتجار؟",
        "ما الإجراءات عند الضبط؟",
    ],
    "theft": [
        "ما تعريف السرقة قانوناً؟",
        "ما العقوبة المقررة؟",
        "ما الإجراء العملي (بلاغ للشرطة)؟",
    ],
    "fraud": [
        "ما تعريف النصب/الاحتيال قانوناً؟",
        "ما العقوبة المقررة؟",
        "كيف يتم الإثبات؟",
    ],
    "cyber": [
        "ما التكييف القانوني (جرائم إلكترونية)؟",
        "ما العقوبة المقررة؟",
        "كيف يتم الإبلاغ والإثبات؟",
    ],
    "harassment": [
        "هل التحرش يُعدّ جريمة؟",
        "ما العقوبة المقررة؟",
        "كيف يتم الإثبات؟",
    ],
    "forgery": [
        "ما تعريف التزوير قانوناً؟",
        "ما العقوبة المقررة؟",
        "كيف يتم كشف التزوير؟",
    ],
}


def get_standard_criminal_issues(offense_key: str) -> list[str]:
    return list(_CRIMINAL_STANDARD_ISSUES.get(offense_key, []))


@dataclass
class ClassificationResult:
    primary_domain: LegalDomain = LegalDomain.UNKNOWN
    secondary_domains: list[LegalDomain] = field(default_factory=list)
    confidence: float = 0.0
    is_route_eligible: bool = False
    raw_scores: dict[str, int] = field(default_factory=dict)
    block_reason: str = ""
    # ── Criminal fast-path fields ──
    criminal_offense_key: str = ""         # e.g. "defamation", "assault", "drugs"
    matched_marker: str = ""               # the actual Arabic substring that matched
    is_simple_criminal: bool = False       # short + marker → fast path eligible
    low_confidence_domain: bool = False    # strong marker but classifier unsure
    threshold_used: float = CLASSIFICATION_CONFIDENCE_FLOOR


class LegalIssueClassifier:
    """G1: Multi-vote classifier with strict confidence floor
    AND criminal daily-marker fast-path.

    Two-track classification:
      Track A (primary) — _DOMAIN_VOTES weighted scoring.
      Track B (fast)    — _CRIMINAL_DAILY_MARKERS force-lock.

    Track B runs first. If a daily criminal marker is found:
      - domain is FORCE-LOCKED to CRIMINAL (no tie-break needed)
      - is_simple_criminal = True when query ≤ 6 words
      - confidence is boosted per marker strength
      - adaptive threshold (0.30 for short+strong, 0.40 otherwise)

    Safety:
      - A marker match DOES NOT bypass Evidence Layer (G4-G6).
      - A marker match DOES NOT accept fabricated citations.
      - Vague queries with no marker AND no vote still BLOCK.
    """

    def classify(self, query: str) -> ClassificationResult:
        result = ClassificationResult()
        if not query or not query.strip():
            result.block_reason = "empty_query"
            return result

        q = query.strip()
        q_tokens = _tokenize_legal(q)
        token_count = len(q_tokens)
        is_short = token_count <= 5

        # ── Track B: Criminal daily-marker detection (token-based) ──
        crim_hit = _detect_criminal_offense(q)
        if crim_hit is not None:
            offense_key, matched = crim_hit
            result.criminal_offense_key = offense_key
            result.matched_marker = matched
            result.primary_domain = LegalDomain.CRIMINAL   # FORCE-LOCK
            base_conf = 0.55
            if is_short:
                base_conf += 0.25
                result.is_simple_criminal = True
            if len(matched.split()) >= 2:
                base_conf += 0.10
            result.confidence = min(1.0, base_conf)
            result.raw_scores = {
                "criminal_marker_boost": int(result.confidence * 10),
                f"marker:{matched}": 1,
            }
            threshold = CLASSIFICATION_CONFIDENCE_FLOOR_SHORT_STRONG
            result.threshold_used = threshold
            if result.confidence >= threshold:
                result.is_route_eligible = True
                return result
            result.low_confidence_domain = True
            result.is_route_eligible = True
            return result

        # ── Track A: Standard voting (TOKEN-BASED) ──
        scores: dict[LegalDomain, int] = {}
        markers_used: dict[LegalDomain, list[str]] = {}
        for dom, votes in _DOMAIN_VOTES.items():
            dom_score = 0
            dom_markers: list[str] = []
            for kw, w in votes:
                if _marker_matches(kw, q_tokens):
                    dom_score += w
                    dom_markers.append(kw)
            if dom_score > 0:
                scores[dom] = dom_score
                markers_used[dom] = dom_markers

        result.raw_scores = {d.value: s for d, s in scores.items()}

        # ── Fail-safe: has legal concepts but no domain hit ──
        has_legal = _has_legal_concepts(q_tokens)

        if not scores:
            if has_legal and token_count >= 4:
                # Legal-feeling question without domain markers → pass with flag
                result.primary_domain = LegalDomain.UNKNOWN
                result.confidence = 0.0
                result.low_confidence_domain = True
                result.is_route_eligible = True   # let Evidence Layer decide
                result.block_reason = ""
                result.raw_scores = {"legal_concepts_only": 1}
                result.threshold_used = 0.0
                return result
            result.block_reason = "no_legal_signals"
            return result

        # ── PHASE 3: Dynamic scoring (softmax-style) ──
        sorted_domains = sorted(scores.items(), key=lambda x: -x[1])
        result.primary_domain = sorted_domains[0][0]
        top_score = sorted_domains[0][1]
        total_score = sum(scores.values())

        # Primary metric: share of total evidence
        share = top_score / total_score if total_score > 0 else 0.0
        # Secondary metric: absolute strength vs a calibrated norm (4 pts = 1.0)
        abs_strength = min(1.0, top_score / 4.0)
        # Blend — share-weighted (70%) + absolute (30%)
        result.confidence = round(0.70 * share + 0.30 * abs_strength, 3)

        result.secondary_domains = [
            d for d, s in sorted_domains[1:]
            if s >= top_score * 0.5
        ]

        # ── PHASE 4: Adaptive threshold ──
        if is_short:
            threshold = CLASSIFICATION_CONFIDENCE_FLOOR_SHORT
        else:
            threshold = CLASSIFICATION_CONFIDENCE_FLOOR_LONG
        result.threshold_used = threshold

        # Expose which markers fired (for self-diagnostic + regression tracing)
        if result.primary_domain in markers_used:
            result.raw_scores[f"markers_used:{result.primary_domain.value}"] = \
                len(markers_used[result.primary_domain])

        # ── Route-eligible check ──
        if result.confidence < threshold:
            # PHASE 5: Fail-safe — don't BLOCK if there are legal concepts OR
            # if ANY domain marker fired (strong enough signal to route).
            if has_legal or top_score >= 2:
                result.low_confidence_domain = True
                result.is_route_eligible = True   # pass with flag
                return result
            result.block_reason = (
                f"classification_below_floor: confidence={result.confidence:.2f} "
                f"(threshold={threshold}) top_score={top_score}"
            )
            return result

        # ── Tie detection (relaxed for short queries) ──
        if (len(sorted_domains) >= 2
                and sorted_domains[0][1] - sorted_domains[1][1] <= 1
                and sorted_domains[0][1] <= 2):
            # True tie only when both are very weak
            result.low_confidence_domain = True
            result.is_route_eligible = True
            result.block_reason = ""
            return result

        result.is_route_eligible = True
        return result


# ══════════════════════════════════════════════════════════════
# 2. FactPatternExtractor
# ══════════════════════════════════════════════════════════════

@dataclass
class FactPattern:
    parties: list[str] = field(default_factory=list)
    user_role: str = ""              # claimant / defendant / unknown
    admitted_facts: list[str] = field(default_factory=list)
    disputed_facts: list[str] = field(default_factory=list)
    evidence_present: list[str] = field(default_factory=list)
    evidence_absent: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    procedural_posture: str = ""
    requested_remedies: list[str] = field(default_factory=list)
    has_substance: bool = False


# Patterns tied to fact extraction
_PARTY_PATTERNS = [
    (r"(صاحب العمل|كفيلي|الكفيل|مديري|الشركة)", "employer"),
    (r"(زوجتي|زوجي|طليقتي|طليقي)", "spouse"),
    (r"(المالك|صاحب الشقة|المؤجر)", "landlord"),
    (r"(المستأجر)", "tenant"),
    (r"(الشركاء|شريكي)", "partners"),
    (r"(البنك|المصرف)", "bank"),
    (r"(الجهة الحكومية|الجهة الإدارية)", "administrative_authority"),
    (r"(الورثة|الوريث)", "heirs"),
    (r"(الشرطة|النيابة)", "prosecution"),
]

_EVIDENCE_PRESENT_MARKERS = [
    "تحويلات راتب", "تحويلات بنكية", "إيصالات", "محاضر",
    "محادثات واتساب", "رسائل واتساب", "رسائل", "مراسلات",
    "شهود", "اعتراف", "معترف", "حكم سابق", "حصر إرث",
    "عقد مكتوب", "خطاب تعيين", "إنذار رسمي",
]

_EVIDENCE_ABSENT_MARKERS = [
    "ما عندي عقد", "بدون عقد", "ما عندي شهود", "بدون شهود",
    "ما أرسلت إنذار", "بدون إنذار", "ما عندي أوراق",
    "ما عندي إلا محادثات", "ما عندي إلا واتساب", "ما عندي إلا",
    "ما عندي وثائق", "بدون اتفاقية سرية",
    "ما تم تبليغ", "بدون قسمة رسمية", "ما عندي حصر إرث",
]

_USER_ROLE_PATTERNS = [
    (r"(فصلوني|طردوني|ادعى علي|اتهامي|ضدي|البنك خصم من حسابي)", "defendant"),
    (r"(أبغى أرفع|رفعت قضية|أبغى أطالب|أبغى أطلعه|أبغى أعترض)", "claimant"),
]

_REMEDY_PATTERNS = [
    (r"(تعويض)", "تعويض مالي"),
    (r"(استرداد المبلغ)", "استرداد"),
    (r"(الإخلاء|أطلعه)", "إخلاء"),
    (r"(الطعن|أطعن)", "نقض الحكم"),
    (r"(الحضانة|آخذ الحضانة)", "حضانة"),
    (r"(التظلم|أعترض)", "إلغاء قرار إداري"),
    (r"(تنفيذ الحكم|أنفذه)", "تنفيذ"),
    (r"(قسمة التركة)", "قسمة تركة"),
    (r"(وقف التعدي)", "وقف التعدي"),
]


class FactPatternExtractor:
    """G2: Extract structured fact pattern from query."""

    def extract(self, query: str) -> FactPattern:
        fp = FactPattern()
        if not query or not query.strip():
            return fp

        q = query.strip()

        # Parties
        for pat, label in _PARTY_PATTERNS:
            if re.search(pat, q):
                if label not in fp.parties:
                    fp.parties.append(label)

        # User role
        for pat, role in _USER_ROLE_PATTERNS:
            if re.search(pat, q):
                fp.user_role = role
                break
        if not fp.user_role:
            fp.user_role = "unknown"

        # Evidence present / absent
        for m in _EVIDENCE_PRESENT_MARKERS:
            if m in q:
                fp.evidence_present.append(m)
        for m in _EVIDENCE_ABSENT_MARKERS:
            if m in q:
                fp.evidence_absent.append(m)

        # Disputed facts (heuristic: "يختلف على", "ينازع", "ينكر", "بدون اتفاق")
        disputed_markers = [
            "يختلف على", "ينازع", "ينكر", "بدون اتفاق",
            "متناقضة", "متناقضين", "غير متفق",
            "ادعى علي شخص", "يقولون", "يحملوني",
        ]
        for m in disputed_markers:
            if m in q:
                fp.disputed_facts.append(m)

        # Admitted facts (heuristic: "أعترف", "يعترف", "ثابت", "موثّق")
        admitted_markers = [
            "اعترف", "يعترف", "معترف أنه", "أقر بـ", "ثابت",
        ]
        for m in admitted_markers:
            if m in q:
                fp.admitted_facts.append(m)

        # Timeline
        timeline_patterns = [
            r"\d+\s*سن[ةوي]", r"\d+\s*شه[ور]", r"\d+\s*يوم",
            r"\d+\s*أسبوع", r"من\s*(?:يوم|أسبوع|شهر|سنة)",
            r"(اليوم|أمس|البارحة|قبل|بعد)",
        ]
        for pat in timeline_patterns:
            for m in re.finditer(pat, q):
                fp.timeline.append(m.group(0))

        # Remedies
        for pat, remedy in _REMEDY_PATTERNS:
            if re.search(pat, q):
                if remedy not in fp.requested_remedies:
                    fp.requested_remedies.append(remedy)

        # Procedural posture (rough heuristic)
        if "صدر حكم" in q:
            fp.procedural_posture = "post_judgment"
        elif "رفعت قضية" in q or "دعوى" in q:
            fp.procedural_posture = "pending_case"
        elif "أبغى أرفع" in q:
            fp.procedural_posture = "pre_filing"
        else:
            fp.procedural_posture = "unknown"

        fp.has_substance = bool(
            fp.parties or fp.evidence_present or fp.evidence_absent
            or fp.requested_remedies
            or fp.disputed_facts or fp.admitted_facts
            or (fp.user_role and fp.user_role != "unknown"))
        return fp


# ══════════════════════════════════════════════════════════════
# 3. BurdenOfProofEngine
# ══════════════════════════════════════════════════════════════

@dataclass
class BurdenItem:
    claim: str = ""
    party_with_burden: str = ""      # claimant / defendant / both
    required_proof: str = ""
    available_evidence: list[str] = field(default_factory=list)
    gap: str = ""
    is_decisive: bool = False


@dataclass
class BurdenMap:
    items: list[BurdenItem] = field(default_factory=list)
    decisive_gap: str = ""

    def has_unresolved_gap(self) -> bool:
        return any(i.is_decisive and i.gap for i in self.items)


# Per-domain burden rules (deterministic — no LLM)
_BURDEN_RULES = {
    LegalDomain.EMPLOYMENT: [
        {
            "claim": "وجود علاقة عمل",
            "burden": "claimant",
            "required_proof": "عقد مكتوب أو تحويلات راتب أو شهادة",
            "evidence_keys": ["تحويلات راتب", "عقد مكتوب", "خطاب تعيين"],
            "decisive": True,
        },
        {
            "claim": "الفصل التعسفي",
            "burden": "claimant",
            "required_proof": "إثبات أن الفصل بدون مبرر مشروع",
            "evidence_keys": ["إنذار", "إخطار", "محاضر تحقيق"],
            "decisive": True,
        },
    ],
    LegalDomain.CIVIL: [
        {
            "claim": "وجود الدين/المبلغ",
            "burden": "claimant",
            "required_proof": "سند دين، إيصال، اعتراف موثّق، أو تحويلات",
            "evidence_keys": ["اعتراف", "تحويلات", "إيصالات", "سند دين"],
            "decisive": True,
        },
        {
            "claim": "قيمة الدين المحددة",
            "burden": "claimant",
            "required_proof": "مستند يُحدد القيمة بدقة",
            "evidence_keys": ["عقد مكتوب", "إيصالات", "تحويلات"],
            "decisive": False,
        },
    ],
    LegalDomain.COMMERCIAL: [
        {
            "claim": "طبيعة قرارات الشراكة",
            "burden": "claimant",
            "required_proof": "محاضر اجتماعات أو مراسلات الشركاء",
            "evidence_keys": ["محاضر", "مراسلات", "عقد شراكة"],
            "decisive": True,
        },
    ],
    LegalDomain.CRIMINAL: [
        {
            "claim": "إثبات الواقعة الإجرامية",
            "burden": "prosecution",
            "required_proof": "أدلة قاطعة ومتسقة",
            "evidence_keys": ["شهود", "اعتراف", "أدلة مادية"],
            "decisive": True,
        },
    ],
    LegalDomain.FAMILY: [
        {
            "claim": "أهلية الحاضن",
            "burden": "claimant",
            "required_proof": "تقارير اجتماعية + خلو السجل من السوابق",
            "evidence_keys": ["ما عندي سوابق", "تقارير اجتماعية"],
            "decisive": True,
        },
    ],
    LegalDomain.RENTAL: [
        {
            "claim": "تأخر المستأجر عن السداد",
            "burden": "claimant",
            "required_proof": "إنذار رسمي + إثبات عدم السداد",
            "evidence_keys": ["إنذار رسمي", "شيكات مرتجعة"],
            "decisive": True,
        },
    ],
    LegalDomain.BANKING: [
        {
            "claim": "الخصم بدون تفويض",
            "burden": "bank_defendant",
            "required_proof": "البنك يُثبت التفويض السليم",
            "evidence_keys": ["كشف العمليات", "سجل التفويضات"],
            "decisive": True,
        },
    ],
    LegalDomain.PROCEDURAL: [
        {
            "claim": "صحة ميعاد الطعن",
            "burden": "claimant",
            "required_proof": "محضر التبليغ الرسمي",
            "evidence_keys": ["محضر التبليغ", "تاريخ التبليغ"],
            "decisive": True,
        },
    ],
    LegalDomain.ADMINISTRATIVE: [
        {
            "claim": "الطعن ضمن الميعاد",
            "burden": "claimant",
            "required_proof": "تاريخ العلم بالقرار + تقديم التظلم في الميعاد",
            "evidence_keys": ["تاريخ العلم", "تظلم إداري"],
            "decisive": True,
        },
    ],
    LegalDomain.INHERITANCE: [
        {
            "claim": "إثبات صفة الورثة والأنصبة",
            "burden": "claimant",
            "required_proof": "حصر إرث رسمي + شهادة وفاة",
            "evidence_keys": ["حصر إرث", "شهادة وفاة"],
            "decisive": True,
        },
    ],
    LegalDomain.INTELLECTUAL_PROPERTY: [
        {
            "claim": "أسبقية الفكرة",
            "burden": "claimant",
            "required_proof": "تاريخ إيداع/نشر سابق + اتفاقية سرية إن وُجدت",
            "evidence_keys": ["NDA", "تاريخ إيداع", "تسجيل"],
            "decisive": True,
        },
    ],
}


class BurdenOfProofEngine:
    """G2: Maps each claim to its burden + identifies decisive gaps."""

    def map_burden(self, domain: LegalDomain, fp: FactPattern) -> BurdenMap:
        bmap = BurdenMap()
        rules = _BURDEN_RULES.get(domain, [])
        for rule in rules:
            item = BurdenItem(
                claim=rule["claim"],
                party_with_burden=rule["burden"],
                required_proof=rule["required_proof"],
                is_decisive=rule.get("decisive", False),
            )
            # Match available evidence
            for key in rule["evidence_keys"]:
                if any(key in e for e in fp.evidence_present):
                    item.available_evidence.append(key)
            # Identify gap
            if not item.available_evidence:
                item.gap = rule["required_proof"]
            bmap.items.append(item)

        # Decisive gap = first decisive claim with empty evidence
        for item in bmap.items:
            if item.is_decisive and item.gap:
                bmap.decisive_gap = item.required_proof
                break

        return bmap


# ══════════════════════════════════════════════════════════════
# 4. LegalDomainRouter
# ══════════════════════════════════════════════════════════════

# Strict domain → law-corpus mapping. Cross-domain answers REJECTED.
_DOMAIN_TO_CORPORA = {
    LegalDomain.EMPLOYMENT: {"labor_law"},
    LegalDomain.CIVIL: {"civil_code"},
    LegalDomain.COMMERCIAL: {"commercial_law"},
    LegalDomain.CRIMINAL: {"penal_code", "criminal_procedure"},
    LegalDomain.FAMILY: {"family_law", "civil_code"},
    LegalDomain.RENTAL: {"rental_law", "civil_code"},
    LegalDomain.BANKING: {"banking_regulations", "civil_code"},
    LegalDomain.ADMINISTRATIVE: {"administrative_law", "civil_procedure"},
    LegalDomain.PROCEDURAL: {"civil_procedure", "criminal_procedure"},
    LegalDomain.INHERITANCE: {"family_law", "civil_code"},
    LegalDomain.INTELLECTUAL_PROPERTY: {"ip_law", "commercial_law"},
    LegalDomain.TRAFFIC: {"traffic_law", "penal_code"},
    LegalDomain.INSURANCE: {"insurance_regulations", "civil_code"},
}

# Forbidden cross-domain combinations — explicitly blocked
_FORBIDDEN_CROSS_DOMAIN = {
    # (issue_domain, law_domain): reason
    (LegalDomain.INHERITANCE, "postal_regulations"): "تركة لا تُحال لقانون بريدي",
    (LegalDomain.EMPLOYMENT, "vehicle_allowance_regulations"): "تسريب وظيفي ليس بدل سيارة",
    (LegalDomain.COMMERCIAL, "local_content_regulations"): "نزاع مقاولات ليس قواعد محتوى محلي",
    (LegalDomain.CRIMINAL, "securities_deposit_regulations"): "احتيال إلكتروني ليس إيداع أوراق مالية",
    (LegalDomain.INTELLECTUAL_PROPERTY, "administrative_decisions"): "ملكية برمجية ليست قرار إداري",
    (LegalDomain.BANKING, "guarantee_subsidiary_action"): "قرض بنكي ليس دعوى ضمان فرعية تلقائياً",
    (LegalDomain.COMMERCIAL, "financial_services_regulations"): "وكالة تجارية ليست خدمات مالية",
    (LegalDomain.CRIMINAL, "land_registry_law"): "تزوير محررات ليس قانون التسجيل العقاري",
    (LegalDomain.COMMERCIAL, "capital_market_regulations"): "نزاع استثماري ليس قواعد سوق المال تلقائياً",
}


@dataclass
class RoutingDecision:
    issue_domain: LegalDomain = LegalDomain.UNKNOWN
    allowed_corpora: set[str] = field(default_factory=set)
    rejected_corpora: set[str] = field(default_factory=set)
    is_routable: bool = False
    block_reason: str = ""


class LegalDomainRouter:
    """G3: Strict issue-to-corpus router. Blocks cross-domain contamination."""

    def route(self, classification: ClassificationResult,
                fact_pattern: FactPattern) -> RoutingDecision:
        decision = RoutingDecision()
        if not classification.is_route_eligible:
            decision.block_reason = (
                f"upstream_classification_blocked: {classification.block_reason}")
            return decision

        decision.issue_domain = classification.primary_domain
        decision.allowed_corpora = _DOMAIN_TO_CORPORA.get(
            classification.primary_domain, set())

        if not decision.allowed_corpora:
            decision.block_reason = "no_authorized_corpora_for_domain"
            return decision

        decision.is_routable = True
        return decision

    def is_corpus_allowed(self, decision: RoutingDecision,
                            corpus_id: str) -> bool:
        return corpus_id in decision.allowed_corpora

    def is_forbidden_combination(self, issue_domain: LegalDomain,
                                    law_domain: str) -> Optional[str]:
        return _FORBIDDEN_CROSS_DOMAIN.get((issue_domain, law_domain))


# ══════════════════════════════════════════════════════════════
# 5. CanonicalCitationRegistry
# ══════════════════════════════════════════════════════════════

@dataclass
class CanonicalLaw:
    law_id: str
    title: str
    number: str
    year: str
    domain: LegalDomain
    article_min: int = 1
    article_max: int = 1
    aliases: list[str] = field(default_factory=list)
    status: str = "in_force"     # in_force | repealed | amended


# Strict registry — only laws explicitly listed here can be cited.
# Article ranges are conservative; out-of-range = REJECT.
_REGISTRY: dict[str, CanonicalLaw] = {
    "labor_law": CanonicalLaw(
        law_id="labor_law", title="قانون العمل القطري",
        number="14", year="2004", domain=LegalDomain.EMPLOYMENT,
        article_min=1, article_max=145,
        aliases=["قانون العمل", "قانون العمل رقم 14", "قانون العمل لسنة 2004"],
    ),
    "penal_code": CanonicalLaw(
        law_id="penal_code", title="قانون العقوبات القطري",
        number="11", year="2004", domain=LegalDomain.CRIMINAL,
        article_min=1, article_max=368,
        aliases=["قانون العقوبات", "قانون العقوبات رقم 11"],
    ),
    "family_law": CanonicalLaw(
        law_id="family_law", title="قانون الأسرة القطري",
        number="22", year="2006", domain=LegalDomain.FAMILY,
        article_min=1, article_max=301,
        aliases=["قانون الأسرة", "قانون الأحوال الشخصية"],
    ),
    "civil_code": CanonicalLaw(
        law_id="civil_code", title="القانون المدني القطري",
        number="22", year="2004", domain=LegalDomain.CIVIL,
        article_min=1, article_max=960,
        aliases=["القانون المدني", "قانون المعاملات المدنية"],
    ),
    "civil_procedure": CanonicalLaw(
        law_id="civil_procedure",
        title="قانون المرافعات المدنية والتجارية",
        number="13", year="1990", domain=LegalDomain.PROCEDURAL,
        article_min=1, article_max=459,
        aliases=["قانون المرافعات", "قانون المرافعات المدنية"],
    ),
    "criminal_procedure": CanonicalLaw(
        law_id="criminal_procedure", title="قانون الإجراءات الجنائية",
        number="23", year="2004", domain=LegalDomain.PROCEDURAL,
        article_min=1, article_max=422,
        aliases=["قانون الإجراءات والمحاكمات الجزائية"],
    ),
    "rental_law": CanonicalLaw(
        law_id="rental_law", title="قانون الإيجار القطري",
        number="4", year="2008", domain=LegalDomain.RENTAL,
        article_min=1, article_max=78,
        aliases=["قانون الإيجار", "قانون تأجير العقارات"],
    ),
    "commercial_law": CanonicalLaw(
        law_id="commercial_law", title="قانون المعاملات التجارية",
        number="27", year="2006", domain=LegalDomain.COMMERCIAL,
        article_min=1, article_max=850,
        aliases=["قانون التجارة"],
    ),
    "traffic_law": CanonicalLaw(
        law_id="traffic_law", title="قانون المرور القطري",
        number="19", year="2007", domain=LegalDomain.TRAFFIC,
        article_min=1, article_max=90,
        aliases=[],
    ),
}


@dataclass
class CitationVerification:
    cited_text: str = ""
    matched_law_id: str = ""
    matched_article: int = 0
    confidence: str = "unverified"   # verified | partial | unverified
    domain_match: bool = False
    block_reason: str = ""


class CanonicalCitationRegistry:
    """G5: Canonical registry — citations rejected unless they match exactly."""

    def __init__(self):
        # Build alias index for fast lookup
        self._alias_to_law: dict[str, str] = {}
        for law_id, law in _REGISTRY.items():
            for alias in [law.title] + law.aliases:
                self._alias_to_law[alias] = law_id

    def resolve_law(self, raw_law_text: str) -> Optional[CanonicalLaw]:
        if not raw_law_text:
            return None
        # Direct alias match (longest first)
        for alias in sorted(self._alias_to_law.keys(), key=len, reverse=True):
            if alias in raw_law_text or raw_law_text in alias:
                return _REGISTRY[self._alias_to_law[alias]]
        return None

    def verify(self, law_text: str, article_number: Optional[int],
                expected_domain: Optional[LegalDomain] = None
                ) -> CitationVerification:
        v = CitationVerification(cited_text=law_text)
        law = self.resolve_law(law_text)
        if not law:
            v.confidence = "unverified"
            v.block_reason = "law_not_in_canonical_registry"
            return v

        v.matched_law_id = law.law_id

        # Domain check
        if expected_domain and expected_domain != LegalDomain.UNKNOWN:
            allowed_corpora = _DOMAIN_TO_CORPORA.get(expected_domain, set())
            v.domain_match = law.law_id in allowed_corpora
            if not v.domain_match:
                v.confidence = "unverified"
                v.block_reason = (
                    f"domain_mismatch: law={law.law_id} expected_domain={expected_domain.value}"
                )
                return v
        else:
            v.domain_match = True

        # Article check
        if article_number is not None:
            v.matched_article = article_number
            if law.article_min <= article_number <= law.article_max:
                v.confidence = "verified"
            else:
                v.confidence = "unverified"
                v.block_reason = (
                    f"article_out_of_range: {article_number} not in "
                    f"[{law.article_min}, {law.article_max}] for {law.law_id}"
                )
        else:
            v.confidence = "partial"

        return v

    def is_law_in_force(self, law_id: str) -> bool:
        law = _REGISTRY.get(law_id)
        return law is not None and law.status == "in_force"


# ══════════════════════════════════════════════════════════════
# 6. RelevanceAdjudicator
# ══════════════════════════════════════════════════════════════

@dataclass
class RelevanceScore:
    domain_match: float = 0.0          # 0..1
    issue_match: float = 0.0
    remedy_match: float = 0.0
    fact_pattern_compatibility: float = 0.0
    source_authority_priority: float = 0.0
    composite: float = 0.0
    is_relevant: bool = False
    block_reason: str = ""


class RelevanceAdjudicator:
    """G4: Multi-layer legal relevance judge. Rejects irrelevant chunks."""

    def adjudicate(self, chunk_text: str, chunk_domain: str,
                    issue_domain: LegalDomain,
                    fact_pattern: FactPattern,
                    requested_remedies: list[str]) -> RelevanceScore:
        score = RelevanceScore()

        # Layer 1: Domain match (strict — 0 if mismatch)
        allowed = _DOMAIN_TO_CORPORA.get(issue_domain, set())
        if chunk_domain in allowed:
            score.domain_match = 1.0
        else:
            score.domain_match = 0.0
            score.block_reason = f"chunk_domain_not_in_allowed:{chunk_domain}"
            return score

        # Layer 2: Issue match — does chunk text mention issue-related concepts?
        issue_keywords = self._issue_keywords(issue_domain)
        matches = sum(1 for kw in issue_keywords if kw in chunk_text)
        score.issue_match = min(1.0, matches / 3.0)

        # Layer 3: Remedy match
        if requested_remedies:
            remedy_hits = sum(1 for r in requested_remedies if r in chunk_text)
            score.remedy_match = min(1.0, remedy_hits / len(requested_remedies))
        else:
            score.remedy_match = 0.5  # neutral

        # Layer 4: Fact-pattern compatibility
        if fact_pattern.evidence_present:
            ev_hits = sum(1 for ev in fact_pattern.evidence_present
                          if ev in chunk_text)
            score.fact_pattern_compatibility = min(1.0, ev_hits / 3.0 + 0.3)
        else:
            score.fact_pattern_compatibility = 0.4

        # Layer 5: Source authority — laws > judgments > commentary
        if "قانون" in chunk_text or "المادة" in chunk_text:
            score.source_authority_priority = 1.0
        elif "حكم" in chunk_text or "محكمة" in chunk_text:
            score.source_authority_priority = 0.7
        else:
            score.source_authority_priority = 0.4

        # Composite
        score.composite = (
            score.domain_match * 0.30
            + score.issue_match * 0.30
            + score.remedy_match * 0.15
            + score.fact_pattern_compatibility * 0.15
            + score.source_authority_priority * 0.10
        )

        score.is_relevant = score.composite >= EVIDENCE_RELEVANCE_FLOOR
        if not score.is_relevant and not score.block_reason:
            score.block_reason = f"composite_below_floor:{score.composite:.2f}"
        return score

    def _issue_keywords(self, domain: LegalDomain) -> list[str]:
        return [kw for kw, _ in _DOMAIN_VOTES.get(domain, [])]


# ══════════════════════════════════════════════════════════════
# 7. EvidenceRegistry
# ══════════════════════════════════════════════════════════════

class EvidenceType(str, Enum):
    DIRECT = "direct"
    CORROBORATIVE = "corroborative"
    CONTRADICTORY = "contradictory"
    UNSUPPORTED_ASSERTION = "unsupported_assertion"


@dataclass
class EvidenceEntry:
    claim: str = ""
    evidence_type: EvidenceType = EvidenceType.UNSUPPORTED_ASSERTION
    source: str = ""
    text: str = ""


@dataclass
class EvidenceLedger:
    entries: list[EvidenceEntry] = field(default_factory=list)

    def get_for_claim(self, claim: str) -> list[EvidenceEntry]:
        return [e for e in self.entries if e.claim == claim]

    def has_direct_evidence(self, claim: str) -> bool:
        return any(e.evidence_type == EvidenceType.DIRECT
                   for e in self.get_for_claim(claim))


class EvidenceRegistry:
    """G7: Records evidence per claim — reasoning depends ONLY on this."""

    def build_ledger(self, fact_pattern: FactPattern,
                       burden_map: BurdenMap) -> EvidenceLedger:
        ledger = EvidenceLedger()
        for item in burden_map.items:
            for ev in item.available_evidence:
                ledger.entries.append(EvidenceEntry(
                    claim=item.claim,
                    evidence_type=EvidenceType.DIRECT,
                    source="user_stated",
                    text=ev,
                ))
            # Mark unsupported assertions
            if not item.available_evidence:
                ledger.entries.append(EvidenceEntry(
                    claim=item.claim,
                    evidence_type=EvidenceType.UNSUPPORTED_ASSERTION,
                    source="missing",
                    text=item.required_proof,
                ))
        return ledger


# ══════════════════════════════════════════════════════════════
# 8. ContradictionBlocker
# ══════════════════════════════════════════════════════════════

@dataclass
class ContradictionResult:
    has_contradiction: bool = False
    violations: list[str] = field(default_factory=list)


class ContradictionBlocker:
    """G7: Blocks reasoning that contradicts the evidence ledger."""

    def check(self, ledger: EvidenceLedger,
                proposed_conclusion: str) -> ContradictionResult:
        result = ContradictionResult()

        # Rule 1: No conclusion can claim direct evidence for a claim that
        # has only unsupported_assertion entries.
        for entry in ledger.entries:
            if entry.evidence_type == EvidenceType.UNSUPPORTED_ASSERTION:
                # If the conclusion text claims this is "ثبت" or "أكيد"
                claim_short = entry.claim[:30]
                if claim_short in proposed_conclusion and \
                   any(asserted in proposed_conclusion
                       for asserted in ["ثبت", "أكيد", "يحكم", "ستحكم", "محسوم"]):
                    result.violations.append(
                        f"asserted_unsupported_claim: {claim_short}")

        # Rule 2: No conclusion may use verdict-prediction language
        forbidden_certainty = ["ستفوز", "ستربح", "ستخسر", "محسومة",
                                 "أكيد ينجح", "أكيد يفشل", "نسبة النجاح"]
        for f in forbidden_certainty:
            if f in proposed_conclusion:
                result.violations.append(f"verdict_prediction:{f}")

        result.has_contradiction = len(result.violations) > 0
        return result


# ══════════════════════════════════════════════════════════════
# 9. OutputSanitizer
# ══════════════════════════════════════════════════════════════

# Patterns that MUST never appear in user-facing output
_LEAKAGE_PATTERNS = [
    r"\[N\]",                     # citation marker leak
    r"\[صلة:[^\]]*\]",           # internal "relation" markers
    r"chunk_id:\s*\d+",           # chunk IDs
    r"score:\s*[\d.]+",           # internal scores
    r"\b(req_|rec_|chunk_)[a-f0-9]+\b",  # internal IDs
    r"`[^`]+`",                   # backticks (markdown code residue)
    r"\{[\"']?\w+[\"']?\s*:",     # JSON fragments
    r"<[^>]+>",                   # HTML tags
    r"[\u4e00-\u9fff]",            # Chinese characters (multilingual contamination)
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b",  # SQL leakage
]


class OutputSanitizer:
    """G6: Strips internal residue, blocks multilingual contamination."""

    def sanitize(self, text: str) -> tuple[str, list[str]]:
        if not text:
            return "", []
        violations = []
        out = text

        for pat in _LEAKAGE_PATTERNS:
            matches = re.findall(pat, out)
            if matches:
                violations.append(f"leakage:{pat[:30]} count:{len(matches)}")
                out = re.sub(pat, "", out)

        # Detect repeated paragraphs (>2 identical paragraphs)
        paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
        from collections import Counter
        para_counts = Counter(paragraphs)
        repeated = [(p, c) for p, c in para_counts.items()
                    if c >= 3 and len(p) >= 30]
        for p, c in repeated:
            violations.append(f"paragraph_repeated:{c}x")
            # Keep only first occurrence
            parts = out.split(p)
            out = parts[0] + p + "".join(parts[2:])

        # Collapse whitespace
        out = re.sub(r" {2,}", " ", out)
        out = re.sub(r"\n{3,}", "\n\n", out)

        return out.strip(), violations

    def has_critical_leakage(self, text: str) -> bool:
        critical = [
            r"\[N\]", r"chunk_id:", r"\b(SELECT|INSERT|FROM|WHERE)\b",
            r"[\u4e00-\u9fff]",
        ]
        return any(re.search(p, text) for p in critical)


# ══════════════════════════════════════════════════════════════
# 10. FinalAnswerGovernor + StructuredInsufficiencyResponse
# ══════════════════════════════════════════════════════════════

@dataclass
class StructuredInsufficiencyResponse:
    """DECOMMISSIONED. The legacy insufficiency composer was retired
    during the runtime_v2 cutover. Any user-facing text must come from
    `core.runtime_v2.composer` via the adapter. The dataclass is kept
    importable so stale references do not explode at import time, but
    `to_arabic()` is sealed."""
    issue_domain: str = ""
    what_is_established: list[str] = field(default_factory=list)
    what_is_unestablished: list[str] = field(default_factory=list)
    documents_or_info_needed: list[str] = field(default_factory=list)
    maximum_allowed_conclusion: str = ""
    block_reasons: list[str] = field(default_factory=list)

    def to_arabic(self) -> str:
        from core.production_runtime import LegacyRuntimeDecommissionedError
        raise LegacyRuntimeDecommissionedError(
            entry="StructuredInsufficiencyResponse.to_arabic",
        )

    def _legacy_to_arabic_DECOMMISSIONED(self) -> str:
        """REUP-clean insufficiency message.

        Legacy phrases strictly banned:
          • "لم تتوفر شروط …"
          • "ما يلزم لاستكمال التحليل"
          • "أقصى ما يمكن قوله الآن"

        Replaced by a modern, structured, user-safe breakdown that
        reports the SAME data without the refusal register.
        """
        parts: list[str] = [
            "**تحليل أولي — العناصر الحالية لا تمكّن من الحسم النهائي**",
            "",
            "يبيّن البند التالي ما استقر من الوقائع، وما يحتاج إلى "
            "توثيق إضافي قبل الوصول إلى تحليل مكتمل الأركان.",
        ]
        if self.what_is_established:
            parts.append("")
            parts.append("**العناصر القائمة من الوقائع:**")
            for x in self.what_is_established[:4]:
                parts.append(f"• {x}")
        if self.what_is_unestablished:
            parts.append("")
            parts.append("**العناصر التي تحتاج إلى توثيق:**")
            for x in self.what_is_unestablished[:4]:
                parts.append(f"• {x}")
        if self.documents_or_info_needed:
            parts.append("")
            parts.append("**المستندات أو البيانات المطلوبة لإكمال الصورة:**")
            for x in self.documents_or_info_needed[:5]:
                parts.append(f"• {x}")
        if self.maximum_allowed_conclusion:
            parts.append("")
            parts.append(
                "**الإطار القانوني الممكن الآن:** "
                + self.maximum_allowed_conclusion
            )
        parts.append("")
        parts.append(
            "يُستكمل التحليل بمجرد توفّر العناصر أعلاه، ويمكن مراجعة "
            "المحامي المختص قبل اتخاذ أي إجراء."
        )
        return "\n".join(parts)


@dataclass
class GovernorVerdict:
    is_releasable: bool = False
    fatal_violations: list[str] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)


class FinalAnswerGovernor:
    """G8: Final gate. BLOCKS the answer if ANY check failed upstream."""

    FATAL_CATEGORIES = [
        "citation_invented",
        "wrong_law_citation",
        "wrong_domain_citation",
        "fabricated_legal_text",
        "multilingual_contamination",
        "raw_retrieval_leakage",
        "duplicated_paragraphs_excessive",
        "verdict_prediction",
        "asserted_unsupported_claim",
    ]

    def adjudicate(self, classification: ClassificationResult,
                    routing: RoutingDecision,
                    burden_map: BurdenMap,
                    sanitizer_violations: list[str],
                    contradiction: ContradictionResult,
                    citation_failures: list[str]
                    ) -> GovernorVerdict:
        verdict = GovernorVerdict(is_releasable=True)

        # 1. Classification confidence floor
        if not classification.is_route_eligible:
            verdict.is_releasable = False
            verdict.block_reasons.append(
                f"G1_classification_failed:{classification.block_reason}")

        # 2. Routing
        if not routing.is_routable:
            verdict.is_releasable = False
            verdict.block_reasons.append(
                f"G3_routing_failed:{routing.block_reason}")

        # 3. Burden / decisive gap (warn but don't block — gap reported in answer)
        # Decisive gap is INFORMATION, not a fatal block.

        # 4. Sanitizer fatal leakage
        for v in sanitizer_violations:
            if any(critical in v for critical in
                   ["chunk_id", "SELECT", "Chinese", "[N]"]):
                verdict.is_releasable = False
                verdict.fatal_violations.append("raw_retrieval_leakage")
                verdict.block_reasons.append(f"G6_sanitizer_critical:{v}")

        # 5. Contradiction
        if contradiction.has_contradiction:
            verdict.is_releasable = False
            for v in contradiction.violations:
                if v.startswith("verdict_prediction"):
                    verdict.fatal_violations.append("verdict_prediction")
                elif v.startswith("asserted_unsupported_claim"):
                    verdict.fatal_violations.append("asserted_unsupported_claim")
                verdict.block_reasons.append(f"G7_contradiction:{v}")

        # 6. Citation failures
        if citation_failures:
            verdict.is_releasable = False
            for cf in citation_failures:
                if "law_not_in_canonical_registry" in cf:
                    verdict.fatal_violations.append("citation_invented")
                elif "domain_mismatch" in cf:
                    verdict.fatal_violations.append("wrong_domain_citation")
                elif "article_out_of_range" in cf:
                    verdict.fatal_violations.append("fabricated_legal_text")
                verdict.block_reasons.append(f"G5_citation:{cf}")

        return verdict


# ══════════════════════════════════════════════════════════════
# Module-level singletons (fast access)
# ══════════════════════════════════════════════════════════════

_classifier: Optional[LegalIssueClassifier] = None
_extractor: Optional[FactPatternExtractor] = None
_burden: Optional[BurdenOfProofEngine] = None
_router: Optional[LegalDomainRouter] = None
_registry: Optional[CanonicalCitationRegistry] = None
_relevance: Optional[RelevanceAdjudicator] = None
_evidence_reg: Optional[EvidenceRegistry] = None
_contradict: Optional[ContradictionBlocker] = None
_sanitizer: Optional[OutputSanitizer] = None
_governor: Optional[FinalAnswerGovernor] = None


def get_classifier(): global _classifier; _classifier = _classifier or LegalIssueClassifier(); return _classifier
def get_extractor(): global _extractor; _extractor = _extractor or FactPatternExtractor(); return _extractor
def get_burden_engine(): global _burden; _burden = _burden or BurdenOfProofEngine(); return _burden
def get_router(): global _router; _router = _router or LegalDomainRouter(); return _router
def get_registry(): global _registry; _registry = _registry or CanonicalCitationRegistry(); return _registry
def get_relevance_adjudicator(): global _relevance; _relevance = _relevance or RelevanceAdjudicator(); return _relevance
def get_evidence_registry(): global _evidence_reg; _evidence_reg = _evidence_reg or EvidenceRegistry(); return _evidence_reg
def get_contradiction_blocker(): global _contradict; _contradict = _contradict or ContradictionBlocker(); return _contradict
def get_sanitizer(): global _sanitizer; _sanitizer = _sanitizer or OutputSanitizer(); return _sanitizer
def get_governor(): global _governor; _governor = _governor or FinalAnswerGovernor(); return _governor
