# -*- coding: utf-8 -*-
"""
╔════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                    ║
║   🚀 محرك الفهم اللغوي المتقدم للغاية — Ultra Linguistic Understanding Engine        ║
║   الإصدار: 2.0 MAX  |  المساعد القانوني القطري — الجيل التالي                    ║
║                                                                                    ║
║   🎯 القدرات المتقدمة:                                                            ║
║   ┌────────────────────────────────────────────────────────────────────────────┐  ║
║   │                                                                            │  ║
║   │  1. فهم اللهجات العربية المتعددة (Gulf, Egyptian, Levantine, Iraqi)        │  ║
║   │  2. تحليل المشاعر والنوايا (Intent Detection)                               │  ║
║   │  3. استخراج الكيانات القانونية (Legal Entity Extraction)                   │  ║
║   │  4. ربط العلاقات القانونية (Legal Relation Detection)                        │  ║
║   │  5. كشف الغموض والإحالات (Ambiguity & Coreference Resolution)              │  ║
║   │  6. تحليل البنية النحوية العربية (Arabic Morphological Analysis)             │  ║
║   │  7. التوسع الدلالي المتقدم (Advanced Semantic Expansion)                   │  ║
║   │  8. كشف السياق والم谈话 (Context & Discourse Analysis)                       │  ║
║   │  9. معالجة الأخطاء الإملائية والتحريفات (Fuzzy Matching)                  │  ║
║   │  10. فهم الاستفهام والتعجب (Question & Exclamation Analysis)              │  ║
║   │                                                                            │  ║
║   └────────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                    ║
╚════════════════════════════════════════════════════════════════════════════════════╝
"""

import re
import json
import time
import asyncio
import logging
from typing import Optional, List, Dict, Tuple, Set, Any
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════════════
# (§1) الثوابت والأنماط الأساسية
# ═════════════════════════════════════════════════════════════════════════════════════

# حروف عربية فقط
AR_LETTERS_PATTERN = re.compile(r'[\u0600-\u06FF]+')

# تطبيع الألف
ALIF_VARIANTS = 'أإآٱؤئ'
ALIF_NORMALIZED = 'اااويا'

# حروف الشدة والحركات
DIACRITICS_PATTERN = re.compile(r'[\u064B-\u065F\u0610-\u061A\u06D6-\u06E4\u06E7\u06E8\u06EA-\u06ED\u0670\u0640]')

# رموز التحويل للأنماط
CHAR_MAP = str.maketrans(ALIF_VARIANTS + 'ة', ALIF_NORMALIZED + 'ه')


class Dialect(Enum):
    """لهجات عربية مدعومة"""
    GULF = "خليجي"           # قطر، السعودية، الإمارات، الكويت، البحرين
    EGYPTIAN = "مصري"         # مصر
    LEVANTINE = "شامي"        # سوريا، لبنان، الأردن، فلسطين
    IRAQI = "عراقي"           # العراق
    STANDARD_ARABIC = "فصحى"  # العربية الفصحى


class Intent(Enum):
    """نوايا المستخدمين"""
    QUESTION = "استفسار"              # سؤال عام
    LEGAL_ADVICE = "استشارة قانونية"    # طلب مشورة قانونية
    COMPLAINT = "شكوى"                # تقديم شكوى
    INQUIRY = "استعلام"               # استعلام عن حالة
    COMPLAINT_ACTION = "إجراء"         # طلب اتخاذ إجراء
    INFORMATION = "معلومة"            # طلب معلومات
    VERIFICATION = "تحقق"             # التحقق من معلومة
    COMPARISON = "مقارنة"             # مقارنة بين قوانين
    PROCEDURE = "إجراء رسمي"          # استفسار عن إجراءات


class EntityType(Enum):
    """أنواع الكيانات القانونية"""
    PERSON = "شخص"                    # شخص (مدعي، مدعى عليه، متهم، محامي)
    ORGANIZATION = "منظمة"            # شركة، مؤسسة، جهة حكومية
    LAW = "قانون"                     # قانون أو لائحة
    ARTICLE = "مادة"                 # مادة قانونية
    COURT = "محكمة"                  # محكمة أو جهة قضائية
    LOCATION = "موقع"                # مكان (دائرة، مكتب، محكمة)
    DATE = "تاريخ"                   # تاريخ
    MONEY = "مبلغ"                   # مبلغ مالي
    CONTRACT = "عقد"                 # عقد أو اتفاقية
    CRIME = "جريمة"                 # جريمة


# ═════════════════════════════════════════════════════════════════════════════════════
# (§2) قاموس التحويل الشامل للغة العامية (النسخة MAX)
# ═════════════════════════════════════════════════════════════════════════════════════

COLLOQUIAL_TO_LEGAL_MAX: Dict[str, List[Tuple[str, float, Dialect]]] = {
    # ─────────────────────────────────────────────────────────────────────────
    # (§2.1) اللهجة الخليجية — قطر، السعودية، الإمارات، الكويت، البحرين
    # ─────────────────────────────────────────────────────────────────────────

    # فعل الطرد والفصل
    "طردوني": [("فصل تعسفي", 0.95, Dialect.GULF), ("إنهاء عقد العمل", 0.90, Dialect.GULF),
               ("فسخ العقد", 0.85, Dialect.GULF), ("إقالة", 0.80, Dialect.GULF)],
    "طردني": [("فصل تعسفي", 0.95, Dialect.GULF), ("إنهاء عقد العمل", 0.90, Dialect.GULF)],
    "شقالني": [("فصل تعسفي", 0.95, Dialect.GULF), ("إنهاء عقد العمل", 0.90, Dialect.GULF)],
    "عزلوني": [("فصل تعسفي", 0.95, Dialect.GULF), ("عزل من المنصب", 0.90, Dialect.GULF)],

    # رواتب وأجور
    "راتبي": [("أجر", 0.95, Dialect.GULF), ("مرتب", 0.90, Dialect.GULF), ("أجور مستحقة", 0.85, Dialect.GULF)],
    "فلوسي": [("مبلغ مالي مستحق", 0.95, Dialect.GULF), ("أجور", 0.90, Dialect.GULF)],
    "حقوقي": [("مستحقات مالية", 0.95, Dialect.GULF), ("أجور", 0.85, Dialect.GULF)],
    "لم يصرف": [("عدم صرف الأجر", 0.95, Dialect.GULF), ("تأخر في الدفع", 0.85, Dialect.GULF)],

    # جريمة السرقة
    "سرقني": [("سرقة", 0.95, Dialect.GULF), ("اختلاس", 0.85, Dialect.GULF),
              ("خيانة أمانة", 0.80, Dialect.GULF)],
    "يسرق": [("سرقة", 0.95, Dialect.GULF), ("مرتكب جريمة", 0.85, Dialect.GULF)],
    "لص": [("سارق", 0.95, Dialect.GULF), ("مرتكب جريمة السرقة", 0.90, Dialect.GULF)],
    "حرامي": [("سارق", 0.95, Dialect.GULF), ("مرتكب جريمة", 0.85, Dialect.GULF)],

    # سرقة الكهرباء والمياه
    "سرق الكهرباء": [("سرقة التيار الكهربائي", 0.95, Dialect.GULF),
                     ("سرقة خدمات مرافق", 0.90, Dialect.GULF)],
    "سرق المية": [("سرقة المياه", 0.95, Dialect.GULF), ("سرقة خدمات مرافق", 0.90, Dialect.GULF)],
    "يشبك على الكهرباء": [("تلاعب بخدمات المرافق", 0.95, Dialect.GULF)],

    # جرائم الإيذاء
    "ضربني": [("إيذاء جسدي", 0.95, Dialect.GULF), ("اعتداء", 0.90, Dialect.GULF),
              ("ضرب وجرح", 0.85, Dialect.GULF)],
    "اعتدى علي": [("اعتداء", 0.95, Dialect.GULF), ("إيذاء", 0.90, Dialect.GULF)],
    "شتمني": [("قذف", 0.95, Dialect.GULF), ("سب وشتم", 0.90, Dialect.GULF),
              ("إهانة", 0.85, Dialect.GULF)],
    "سبني": [("قذف", 0.95, Dialect.GULF), ("سب", 0.90, Dialect.GULF)],

    # الاحتيال والنصب
    "نصب علي": [("احتيال", 0.95, Dialect.GULF), ("نصب", 0.90, Dialect.GULF),
                ("تدليس", 0.85, Dialect.GULF)],
    "غشني": [("غش تجاري", 0.95, Dialect.GULF), ("تدليس", 0.90, Dialect.GULF)],
    "احتال علي": [("احتيال", 0.95, Dialect.GULF), ("نصب", 0.90, Dialect.GULF)],
    "خانني": [("احتيال", 0.90, Dialect.GULF), ("خيانة أمانة", 0.85, Dialect.GULF)],

    # القانون الجنائي
    "حبسوه": [("سجن", 0.95, Dialect.GULF), ("توقيف", 0.90, Dialect.GULF),
              ("حبس احتياطي", 0.85, Dialect.GULF)],
    "اعتقلوه": [("اعتقال", 0.95, Dialect.GULF), ("قبض", 0.90, Dialect.GULF)],
    "مضبوط": [("متهم", 0.90, Dialect.GULF), ("موقوف", 0.85, Dialect.GULF)],

    # جرائم المخدرات
    "مخدرات": [("تعاطي مخدرات", 0.95, Dialect.GULF), ("حيازة مخدرات", 0.90, Dialect.GULF),
               ("تهريب مخدرات", 0.85, Dialect.GULF)],
    "حشي": [("تهريب مخدرات", 0.95, Dialect.GULF), ("حيازة بقصد الاتجار", 0.90, Dialect.GULF)],
    "ترويج": [("ترويج مخدرات", 0.95, Dialect.GULF), ("اتجار", 0.85, Dialect.GULF)],

    # الإقامة والتأشيرات
    "إقامتي": [("تصريح إقامة", 0.95, Dialect.GULF), ("تجديد إقامة", 0.90, Dialect.GULF),
              ("قانون الإقامة", 0.85, Dialect.GULF)],
    "انتهت إقامتي": [("مخالفة الإقامة", 0.95, Dialect.GULF), ("عقوبة الإقامة المنتهية", 0.90, Dialect.GULF)],
    "بدون إقامة": [("مخالفة الإقامة", 0.95, Dialect.GULF), ("جريمة البقاء غير القانوني", 0.85, Dialect.GULF)],
    "فيزة": [("تأشيرة", 0.95, Dialect.GULF), ("تأشيرة دخول", 0.90, Dialect.GULF)],
    "سعودة": [("سياسة سعودة الوظائف", 0.95, Dialect.GULF), ("استبدال العمالة", 0.80, Dialect.GULF)],

    # الترحيل والإبعاد
    "ترحيل": [("ترحيل الأجانب", 0.95, Dialect.GULF), ("إبعاد", 0.90, Dialect.GULF),
             ("إنهاء الإقامة", 0.85, Dialect.GULF)],
    "ابعاده": [("إبعاد", 0.95, Dialect.GULF), ("ترحيل", 0.90, Dialect.GULF)],

    # الأسرة والزواج
    "طلاق": [("طلاق", 0.95, Dialect.GULF), ("فراق", 0.90, Dialect.GULF),
            ("طلاق قضائي", 0.85, Dialect.GULF)],
    "خلع": [("طلاق الخلع", 0.95, Dialect.GULF), ("فدية الخلع", 0.90, Dialect.GULF)],
    "زواج ثاني": [("تعدد الزوجات", 0.95, Dialect.GULF), ("شروط التعدد", 0.90, Dialect.GULF)],

    # الحضانة والنفقة
    "حضانة": [("حضانة الأطفال", 0.95, Dialect.GULF), ("ولاية", 0.90, Dialect.GULF)],
    "ولدي": [("حضانة", 0.90, Dialect.GULF), ("ولاية الأطفال", 0.85, Dialect.GULF)],
    "نفقة": [("نفقة زوجية", 0.95, Dialect.GULF), ("نفقة أولاد", 0.90, Dialect.GULF),
            ("مؤونة", 0.85, Dialect.GULF)],
    "مؤونتي": [("نفقة زوجية", 0.95, Dialect.GULF)],

    # الميراث
    "ميراث": [("إرث", 0.95, Dialect.GULF), ("تركة", 0.90, Dialect.GULF),
             ("أحكام الإرث", 0.85, Dialect.GULF)],
    "توفي": [("وفاة", 0.95, Dialect.GULF), ("ميراث", 0.90, Dialect.GULF)],
    "توزيع إرث": [("تقسيم التركة", 0.95, Dialect.GULF), ("أنصبة الورثة", 0.90, Dialect.GULF)],

    # الجرائم الإلكترونية
    "هاكر": [("جريمة إلكترونية", 0.95, Dialect.GULF), ("اختراق", 0.90, Dialect.GULF)],
    "اخترق": [("اختراق أنظمة", 0.95, Dialect.GULF), ("جريمة إلكترونية", 0.90, Dialect.GULF)],
    "يبتزني": [("ابتزاز إلكتروني", 0.95, Dialect.GULF), ("تهديد", 0.90, Dialect.GULF),
              ("إكراه", 0.85, Dialect.GULF)],
    "صوري": [("انتهاك خصوصية", 0.95, Dialect.GULF), ("جريمة إلكترونية", 0.90, Dialect.GULF),
            ("نشر صور خاصة", 0.85, Dialect.GULF)],
    "نشر صور": [("ابتزاز إلكتروني", 0.95, Dialect.GULF), ("انتهاك خصوصية", 0.90, Dialect.GULF)],
    "تهديد إلكتروني": [("ابتزاز إلكتروني", 0.95, Dialect.GULF), ("تهديد", 0.90, Dialect.GULF)],

    # الشيكات
    "شيك": [("شيك بدون رصيد", 0.95, Dialect.GULF), ("شيك مرتجع", 0.90, Dialect.GULF)],
    "بدون رصيد": [("شيك بدون رصيد", 0.95, Dialect.GULF), ("رصيد غير كافٍ", 0.90, Dialect.GULF)],
    "مرتجع": [("شيك مرتجع", 0.95, Dialect.GULF), ("صك بلا رصيد", 0.90, Dialect.GULF)],

    # التعويضات
    "مكافأة": [("مكافأة نهاية الخدمة", 0.95, Dialect.GULF), ("تعويض", 0.90, Dialect.GULF)],
    "نهاية الخدمة": [("مكافأة نهاية الخدمة", 0.95, Dialect.GULF), ("مستحقات نهاية الخدمة", 0.90, Dialect.GULF)],
    "تعويض": [("تعويض", 0.95, Dialect.GULF), ("دية", 0.85, Dialect.GULF)],

    # التأمين
    "تأمين": [("تأمين", 0.95, Dialect.GULF), ("بوليصة تأمين", 0.85, Dialect.GULF)],
    "تأمين صحي": [("تأمين صحي", 0.95, Dialect.GULF), ("تغطية طبية", 0.85, Dialect.GULF)],

    # ─────────────────────────────────────────────────────────────────────────
    # (§2.2) اللهجة المصرية
    # ─────────────────────────────────────────────────────────────────────────

    "طردنى": [("فصل تعسفي", 0.95, Dialect.EGYPTIAN), ("إنهاء عقد العمل", 0.90, Dialect.EGYPTIAN)],
    "فلوسى": [("أجور مستحقة", 0.95, Dialect.EGYPTIAN), ("مبلغ مالي", 0.85, Dialect.EGYPTIAN)],
    "سرقنى": [("سرقة", 0.95, Dialect.EGYPTIAN), ("خيانة أمانة", 0.85, Dialect.EGYPTIAN)],
    "ضربنى": [("إيذاء جسدي", 0.95, Dialect.EGYPTIAN), ("اعتداء", 0.90, Dialect.EGYPTIAN)],
    "سبنى": [("قذف", 0.95, Dialect.EGYPTIAN), ("سب وشتم", 0.90, Dialect.EGYPTIAN)],
    "نصب عليا": [("احتيال", 0.95, Dialect.EGYPTIAN), ("نصب", 0.90, Dialect.EGYPTIAN)],
    "خدعنى": [("احتيال", 0.95, Dialect.EGYPTIAN), ("تدليس", 0.90, Dialect.EGYPTIAN)],
    "مخدرات": [("تعاطي مخدرات", 0.95, Dialect.EGYPTIAN), ("حيازة مخدرات", 0.90, Dialect.EGYPTIAN)],
    "حبسوه": [("سجن", 0.95, Dialect.EGYPTIAN), ("توقيف", 0.90, Dialect.EGYPTIAN)],
    "إقامتى": [("تصريح إقامة", 0.95, Dialect.EGYPTIAN), ("تجديد إقامة", 0.90, Dialect.EGYPTIAN)],
    "طلاق": [("طلاق", 0.95, Dialect.EGYPTIAN), ("فراق", 0.90, Dialect.EGYPTIAN)],
    "حضانة": [("حضانة الأطفال", 0.95, Dialect.EGYPTIAN), ("ولاية", 0.85, Dialect.EGYPTIAN)],
    "نفقة": [("نفقة زوجية", 0.95, Dialect.EGYPTIAN), ("نفقة أولاد", 0.90, Dialect.EGYPTIAN)],
    "إرث": [("ميراث", 0.95, Dialect.EGYPTIAN), ("تركة", 0.90, Dialect.EGYPTIAN)],
    "هاكر": [("جريمة إلكترونية", 0.95, Dialect.EGYPTIAN), ("اختراق", 0.90, Dialect.EGYPTIAN)],
    "ابتزاز": [("ابتزاز إلكتروني", 0.95, Dialect.EGYPTIAN), ("تهديد", 0.85, Dialect.EGYPTIAN)],
    "شيك": [("شيك بدون رصيد", 0.95, Dialect.EGYPTIAN), ("شيك مرتجع", 0.90, Dialect.EGYPTIAN)],

    # ─────────────────────────────────────────────────────────────────────────
    # (§2.3) اللهجة الشامية (سوريا، لبنان، الأردن، فلسطين)
    # ─────────────────────────────────────────────────────────────────────────

    "طردوني": [("فصل تعسفي", 0.95, Dialect.LEVANTINE), ("إنهاء عقد العمل", 0.90, Dialect.LEVANTINE)],
    "فلوسي": [("أجور مستحقة", 0.95, Dialect.LEVANTINE), ("مبلغ مالي", 0.85, Dialect.LEVANTINE)],
    "سرقني": [("سرقة", 0.95, Dialect.LEVANTINE), ("خيانة أمانة", 0.85, Dialect.LEVANTINE)],
    "ضلني": [("احتيال", 0.95, Dialect.LEVANTINE), ("نصب", 0.90, Dialect.LEVANTINE)],
    "مشuate": [("إيذاء جسدي", 0.95, Dialect.LEVANTINE), ("اعتداء", 0.90, Dialect.LEVANTINE)],
    "حاطيني": [("اعتقال", 0.95, Dialect.LEVANTINE), ("قبض", 0.90, Dialect.LEVANTINE)],
    "مخيّن": [("حيازة مخدرات", 0.95, Dialect.LEVANTINE), ("تعاطي مخدرات", 0.90, Dialect.LEVANTINE)],
    "طليقة": [("طلاق", 0.95, Dialect.LEVANTINE), ("فراق", 0.90, Dialect.LEVANTINE)],
    "حارس": [("حضانة الأطفال", 0.95, Dialect.LEVANTINE), ("ولاية", 0.85, Dialect.LEVANTINE)],
    "نفسية": [("نفقة زوجية", 0.95, Dialect.LEVANTINE), ("مؤونة", 0.85, Dialect.LEVANTINE)],
    "ميراث": [("إرث", 0.95, Dialect.LEVANTINE), ("تركة", 0.90, Dialect.LEVANTINE)],
    "هاكر": [("جريمة إلكترونية", 0.95, Dialect.LEVANTINE), ("اختراق", 0.90, Dialect.LEVANTINE)],

    # ─────────────────────────────────────────────────────────────────────────
    # (§2.4) اللهجة العراقية
    # ─────────────────────────────────────────────────────────────────────────

    "طردوني": [("فصل تعسفي", 0.95, Dialect.IRAQI), ("إنهاء عقد العمل", 0.90, Dialect.IRAQI)],
    "سرقني": [("سرقة", 0.95, Dialect.IRAQI), ("خيانة أمانة", 0.85, Dialect.IRAQI)],
    "ناچ": [("احتيال", 0.95, Dialect.IRAQI), ("نصب", 0.90, Dialect.IRAQI)],
    "ضربني": [("إيذاء جسدي", 0.95, Dialect.IRAQI), ("اعتداء", 0.90, Dialect.IRAQI)],
    "ماخص": [("حيازة مخدرات", 0.95, Dialect.IRAQI), ("تعاطي مخدرات", 0.90, Dialect.IRAQI)],
    "حچي": [("اعتقال", 0.95, Dialect.IRAQI), ("قبض", 0.90, Dialect.IRAQI)],
    "طلاق": [("طلاق", 0.95, Dialect.IRAQI), ("فراق", 0.90, Dialect.IRAQI)],
    "حضانة": [("حضانة الأطفال", 0.95, Dialect.IRAQI), ("ولاية", 0.85, Dialect.IRAQI)],
    "ميراث": [("إرث", 0.95, Dialect.IRAQI), ("تركة", 0.90, Dialect.IRAQI)],

    # ─────────────────────────────────────────────────────────────────────────
    # (§2.5) مصطلحات قانونية عامة مشتركة
    # ─────────────────────────────────────────────────────────────────────────

    "محامي": [("محامٍ", 0.95, Dialect.STANDARD_ARABIC), ("محامٍ متخصص", 0.85, Dialect.STANDARD_ARABIC)],
    "قاضي": [("قاضٍ", 0.95, Dialect.STANDARD_ARABIC), ("هيئة قضائية", 0.80, Dialect.STANDARD_ARABIC)],
    "محكمة": [("محكمة", 0.95, Dialect.STANDARD_ARABIC), ("هيئة قضائية", 0.85, Dialect.STANDARD_ARABIC)],
    "نيابة": [("نيابة", 0.95, Dialect.STANDARD_ARABIC), ("ادعاء عام", 0.80, Dialect.STANDARD_ARABIC)],
    "عقوبة": [("عقوبة", 0.95, Dialect.STANDARD_ARABIC), ("جزاء", 0.90, Dialect.STANDARD_ARABIC)],
    "مادة": [("مادة قانونية", 0.95, Dialect.STANDARD_ARABIC), ("نص قانوني", 0.85, Dialect.STANDARD_ARABIC)],
    "حق": [("حق قانوني", 0.95, Dialect.STANDARD_ARABIC), ("حقوق", 0.90, Dialect.STANDARD_ARABIC)],
    "واجب": [("التزام", 0.95, Dialect.STANDARD_ARABIC), ("واجب قانوني", 0.90, Dialect.STANDARD_ARABIC)],
    "عقد": [("عقد", 0.95, Dialect.STANDARD_ARABIC), ("اتفاقية", 0.85, Dialect.STANDARD_ARABIC)],
    "إثبات": [("إثبات", 0.95, Dialect.STANDARD_ARABIC), ("دليل", 0.85, Dialect.STANDARD_ARABIC)],
    "دعوى": [("دعوى", 0.95, Dialect.STANDARD_ARABIC), ("شكوى", 0.85, Dialect.STANDARD_ARABIC)],
    "حكم": [("حكم", 0.95, Dialect.STANDARD_ARABIC), ("قرار قضائي", 0.85, Dialect.STANDARD_ARABIC)],
    "التمس": [("التمس", 0.95, Dialect.STANDARD_ARABIC), ("طلب", 0.85, Dialect.STANDARD_ARABIC)],
}


# ═════════════════════════════════════════════════════════════════════════════════════
# (§3) قاموس المرادفات القانونية المتقدم
# ═════════════════════════════════════════════════════════════════════════════════════

LEGAL_SYNONYMS: Dict[str, List[Tuple[str, float]]] = {
    # العقوبة والجزاء
    "عقوبة": [("جزاء", 0.95), ("حكم", 0.90), ("إجراء عقابي", 0.85)],
    "سجن": [("حبس", 0.95), ("توقيف", 0.85), ("اعتقال", 0.80)],
    "غرامة": [("مبلغ مالي", 0.85), ("تعويض مالي", 0.80)],
    "إعدام": [("عقوبة الإعدام", 0.95), ("أقصى العقوبة", 0.85)],

    # الجرائم
    "سرقة": [("اختلاس", 0.85), ("خيانة أمانة", 0.80), ("نهب", 0.75)],
    "احتيال": [("نصب", 0.90), ("تدليس", 0.85), ("احتيال مالي", 0.80)],
    "اعتداء": [("إيذاء", 0.90), ("ضرب", 0.85), ("هجوم", 0.75)],
    "ابتزاز": [("تهديد", 0.85), ("إكراه", 0.80), ("انتزاع", 0.75)],

    # القانون
    "قانون": [("تشريع", 0.90), ("لائحة", 0.85), ("نظام", 0.80)],
    "مادة": [("نص", 0.85), ("بند", 0.80), ("فقرة", 0.75)],

    # الأشخاص
    "مدعي": [("شاكٍ", 0.85), ("مُدَّع", 0.80)],
    "مدعى عليه": [("متهم", 0.90), ("مُتَّهم", 0.85)],
    "شاهد": [("بشاهد", 0.85), ("مُدَّلِس", 0.80)],

    # الإجراءات
    "استئناف": [("طعن", 0.85), ("تمييز", 0.80), ("مراجعة", 0.75)],
    "محاكمة": [("محاكمة", 0.90), ("محاكمة جنائية", 0.85), ("جلسة", 0.75)],

    # الأسرة
    "طلاق": [("فراق", 0.90), ("تطليق", 0.85), ("فسخ نكاح", 0.80)],
    "حضانة": [("ولاية", 0.85), ("رعاية", 0.80), ("حفظ", 0.75)],
    "نفقة": [("مؤونة", 0.85), ("إنفاق", 0.80), ("مصروف", 0.75)],

    # العقود
    "عقد": [("اتفاق", 0.85), ("ميثاق", 0.80), ("تعاقد", 0.75)],
    "فسخ": [("إنهاء", 0.85), ("إلغاء", 0.80), ("بطلان", 0.75)],
    "تعديل": [("تغيير", 0.80), ("إصلاح", 0.75)],
}


# ═════════════════════════════════════════════════════════════════════════════════════
# (§4) أنماط كشف النية والاستعلام
# ═════════════════════════════════════════════════════════════════════════════════════

INTENT_PATTERNS: Dict[Intent, List[Tuple[re.Pattern, float]]] = {
    Intent.QUESTION: [
        (re.compile(r'(ما|إيش|ايش|شو|كيف)\s*(هو|هي|في|عن|حول)', re.UNICODE), 0.95),
        (re.compile(r'(هل|هَل|أ\s)', re.UNICODE), 0.85),
        (re.compile(r'(ليش|وش|ايش|إيش)\s*(الحكم|العقوبة|الحق|كيف)', re.UNICODE), 0.90),
        (re.compile(r'(ايش|ما)\s*(تسمى|تكون|يعني)', re.UNICODE), 0.85),
    ],
    Intent.LEGAL_ADVICE: [
        (re.compile(r'(أبي|أريد|أريد|أريد|اريد)\s*(معلومة|استشارة|مساعدة)\s*(قانونية|legal)', re.UNICODE), 0.95),
        (re.compile(r'(وش|ما)\s*(أسوي|أعمل|أفعل)', re.UNICODE), 0.90),
        (re.compile(r'(كيف|وش)\s*(يكون|يصير)\s*(الحال|الأمر)', re.UNICODE), 0.85),
        (re.compile(r'(نصيحتك|نصيحة|ارشدني|أرشدني)', re.UNICODE), 0.90),
    ],
    Intent.COMPLAINT: [
        (re.compile(r'(شاكي|شاكية|أشتكي|اشتكي)\s*(من|عن)', re.UNICODE), 0.95),
        (re.compile(r'(ضدي|عليَّ|عليَّ)\s*(إجراء|حق)', re.UNICODE), 0.90),
        (re.compile(r'(محتاج|أحتاج)\s*(حقوقي|قانوني)', re.UNICODE), 0.85),
        (re.compile(r'(صاحب|صاحبة)\s*(حق|حقوق)', re.UNICODE), 0.85),
    ],
    Intent.INQUIRY: [
        (re.compile(r'(وش|ما)\s*(حكم|عقوبة|قانون)\s*(سرقة|طلاق|إيجار)', re.UNICODE), 0.95),
        (re.compile(r'(ايش|ما)\s*(ينطبق|يتعلق|يتعلق)', re.UNICODE), 0.90),
        (re.compile(r'(هل|هَل)\s*(من\s+)?(حق|حقوق)', re.UNICODE), 0.85),
    ],
    Intent.PROCEDURE: [
        (re.compile(r'(كيف|وش)\s*(أقدم|أعمل|أسوي)\s*(على|في)', re.UNICODE), 0.95),
        (re.compile(r'(خطوات?|طريقة|كيفية)\s*(التقديم|الإجراء)', re.UNICODE), 0.95),
        (re.compile(r'(وش|ما)\s*(المستندات|الأوراق|الشروط)', re.UNICODE), 0.90),
    ],
}


# ═════════════════════════════════════════════════════════════════════════════════════
# (§5) أنماط كشف الكيانات القانونية
# ═════════════════════════════════════════════════════════════════════════════════════

ENTITY_PATTERNS: Dict[EntityType, List[re.Pattern]] = {
    EntityType.PERSON: [
        re.compile(r'(مدعي|مدعى عليها?|شاكي|شاكية|متهم|متهمة|محامي|شاهد)', re.UNICODE),
        re.compile(r'(زوج|زوجة|أب|أم|ابن|ابنة|أخ|أخت|ولي)', re.UNICODE),
    ],
    EntityType.LAW: [
        re.compile(r'قانون\s+(\w+)', re.UNICODE),
        re.compile(r'(مدني|جنائي|عمالي|أسرة|تجاري|إداري)\s*(قانون|مجلة)', re.UNICODE),
    ],
    EntityType.ARTICLE: [
        re.compile(r'مادة\s*\(?\s*(\d+)', re.UNICODE),
        re.compile(r'(المادة|الفقرة)\s*(\d+)', re.UNICODE),
    ],
    EntityType.MONEY: [
        re.compile(r'(\d+)\s*(ريال|دولار|يورو|دينار)', re.UNICODE),
        re.compile(r'(مبلغ|قيمة|ثمن)\s+(\d+)', re.UNICODE),
    ],
    EntityType.DATE: [
        re.compile(r'(سنة|عام)\s*(\d{4})', re.UNICODE),
        re.compile(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', re.UNICODE),
    ],
}


# ═════════════════════════════════════════════════════════════════════════════════════
# (§6) قاموس الكلمات النمطية للتمييز (Stop Words)
# ═════════════════════════════════════════════════════════════════════════════════════

STOP_WORDS: Set[str] = {
    # أدوات نحوية
    "في", "من", "إلى", "على", "عن", "مع", "هذا", "هذه", "ذلك", "تلك",
    "ما", "من", "هو", "هي", "أن", "إن", "كان", "كانت", "يكون", "تكون",
    # كلمات استفهامية شائعة
    "كيف", "لماذا", "متى", "أين", "كم", "هل", "أي", "أيه",
    # أدوات ربط
    "و", "أو", "ثم", "لكن", "إذا", "لو", "حتى", "بل",
    # ضمائر
    "أنا", "أنت", "أنتما", "أنتم", "أنتن", "هو", "هي", "هما", "هم", "هن",
    # حروف جر
    "ب", "ل", "ك", "ف", "س",
    # أدوات النفي
    "لا", "لم", "لن", "ما", "غير",
    # التحيات
    "السلام", "عليكم", "مرحبا", "أهلا", "هلا", "كيف", "حالك",
    # تعبيرات شائعة
    "لو", "سمحت", "الله", "سبحان", "الحمد", "شكرا", "ممكن", "أبي", "أريد",
}


# ═════════════════════════════════════════════════════════════════════════════════════
# (§7) أنماط كشف السياق والمحادثة
# ═════════════════════════════════════════════════════════════════════════════════════

CONTEXT_PATTERNS = {
    "follow_up": re.compile(r'(و|ثم|بعدين|بعدها|كمان|أيضاً)\s*(ذا|هذي|ذاك)', re.UNICODE),
    "clarification": re.compile(r'(قصدك|تقصد|أقصد|وضح|اشرح)\s*(لي|ليَّ)', re.UNICODE),
    "contrast": re.compile(r'(لكن|غير|خلاف|على\s+عكس|بينما)', re.UNICODE),
    "cause": re.compile(r'(بسبب|لأن|نتيجة|إثر|حيث)', re.UNICODE),
    "result": re.compile(r'(因此|النتيجة|يؤدي|ينتج|يترتب)', re.UNICODE),
}


# ═════════════════════════════════════════════════════════════════════════════════════
# (§8) هياكل البيانات المتقدمة
# ═════════════════════════════════════════════════════════════════════════════════════

@dataclass
class LegalEntity:
    """كيان قانوني مستخرج"""
    text: str
    type: EntityType
    normalized: str
    confidence: float
    start_pos: int
    end_pos: int


@dataclass
class IntentResult:
    """نتيجة تحليل النية"""
    intent: Intent
    confidence: float
    reasoning: str
    context_keywords: List[str]


@dataclass
class LinguisticAnalysisResult:
    """نتيجة التحليل اللغوي الشاملة"""
    # النص الأصلي والمُحوَّل
    original_text: str
    normalized_text: str
    dialect: Dialect
    confidence_dialect: float

    # استخراج الكيانات
    entities: List[LegalEntity]

    # تحليل النية
    primary_intent: Intent
    all_intents: List[IntentResult]

    # المصطلحات القانونية
    legal_terms: List[Tuple[str, float, Dialect]]

    # المجالات القانونية
    domains: List[Tuple[str, float]]
    primary_domain: str

    # استعلامات البحث الموسعة
    search_queries: List[Tuple[str, float]]

    # كشف الإبهام
    is_ambiguous: bool
    ambiguity_type: Optional[str]
    clarification_question: Optional[str]

    # معالجة الأخطاء الإملائية
    spelling_corrections: Dict[str, str]

    # الإحصائيات
    word_count: int
    arabic_ratio: float
    processing_time_ms: float


# ═════════════════════════════════════════════════════════════════════════════════════
# (§9) محرك التحليل اللغوي الرئيسي
# ═════════════════════════════════════════════════════════════════════════════════════

class UltraLinguisticEngine:
    """
    🚀 محرك الفهم اللغوي المتقدم للغاية

    القدرات:
    1. فهم اللهجات العربية المتعددة
    2. تحليل النية والاستفسار
    3. استخراج الكيانات القانونية
    4. كشف الغموض والإحالات
    5. التوسع الدلالي المتقدم
    6. معالجة الأخطاء الإملائية

    الاستخدام:
        engine = UltraLinguisticEngine()
        result = await engine.analyze("جاري يسرق الكهرباء ايش الحكم؟")
    """

    def __init__(self):
        # كاشف اللهجة
        self._dialect_signatures = self._build_dialect_signatures()

        # كاشف اللهجة المحسّن
        self._dialect_patterns = self._build_dialect_patterns()

        # قاموس الأخطاء الإملائية الشائعة
        self._spelling_corrections = self._build_spelling_dict()

        log.info("✅ UltraLinguisticEngine initialized with MAX capabilities")

    def _normalize(self, text: str) -> str:
        """
        تطبيع النص العربي الشامل
        1. حذف التشكيل
        2. توحيد الألف
        3. توحيد الهاء المربوطة
        4. حذف المسافات الزائدة
        """
        # حذف التشكيل
        text = DIACRITICS_PATTERN.sub('', text)

        # تطبيع الحروف
        text = text.translate(CHAR_MAP)

        # توحيد ال
        text = re.sub(r'^ال', '', text)  # في البداية
        text = re.sub(r'\s+ال', ' ', text)  # في الوسط

        # حذف الهمزات المتعددة
        text = re.sub(r'[أإآٱ]', 'ا', text)

        # حذف المسافات الزائدة
        text = re.sub(r'\s+', ' ', text).strip()

        return text.lower()

    def _build_dialect_signatures(self) -> Dict[Dialect, Dict[str, int]]:
        """بناء بصمات اللهجات"""
        return {
            Dialect.GULF: {
                "نا": 10, " انا": 8, "ابي": 15, "تبي": 12, " وش": 10,
                "ايش": 15, "هذي": 10, "ذاك": 8, "خلاص": 7, " الحين": 8,
                "برا": 5, "يبي": 12, "عسى": 5, "فوق": 3, "تحت": 3,
            },
            Dialect.EGYPTIAN: {
                "بقى": 10, "خالص": 8, "اه": 10, "ايه": 15, "مصر": 10,
                "فين": 12, "ازاي": 15, "امتى": 12, "بتاع": 10, "اللي": 8,
            },
            Dialect.LEVANTINE: {
                "شو": 15, "كيفك": 10, "هلق": 8, "بكرا": 5, "هلأ": 8,
                "كتير": 10, "منيح": 8, "هيك": 10, "روع": 5,
            },
            Dialect.IRAQI: {
                "منو": 15, "شنو": 15, "اكو": 10, "هلا": 8, "بيك": 10,
                "مو": 8, "لا": 5, "بعد": 3, "گ": 10, "چ": 12,
            },
        }

    def _build_dialect_patterns(self) -> Dict[Dialect, List[Tuple[re.Pattern, int]]]:
        """بناء أنماط كشف اللهجة"""
        return {
            Dialect.GULF: [
                (re.compile(r'(ابي|أبي)\s+(أن|أ)', re.UNICODE), 15),
                (re.compile(r'(تبي|تبغي)\s+(أن|أ)', re.UNICODE), 15),
                (re.compile(r'ايش|إيش|وش', re.UNICODE), 12),
                (re.compile(r'هذي|هذي', re.UNICODE), 10),
                (re.compile(r'خلاص|خلاص', re.UNICODE), 8),
            ],
            Dialect.EGYPTIAN: [
                (re.compile(r'ايه|أيوه|آه', re.UNICODE), 15),
                (re.compile(r'(فين|إزين|ازاي|امتى)', re.UNICODE), 15),
                (re.compile(r'(بتاع|بتوع)', re.UNICODE), 12),
            ],
            Dialect.LEVANTINE: [
                (re.compile(r'(شو|شو)', re.UNICODE), 15),
                (re.compile(r'(كيفك|كيفك)', re.UNICODE), 12),
                (re.compile(r'(هلق|هلق)', re.UNICODE), 10),
            ],
            Dialect.IRAQI: [
                (re.compile(r'(منو|شنو|اكو)', re.UNICODE), 18),
                (re.compile(r'(گ|چ|پ)', re.UNICODE), 12),
            ],
        }

    def _build_spelling_dict(self) -> Dict[str, List[str]]:
        """بناء قاموس تصحيح الأخطاء الإملائية"""
        return {
            # أخطاء شائعة في اللهجة الخليجية
            "سرقه": ["سرقة", "السرقة"],
            "حضانه": ["حضانة", "الحضانة"],
            "طلاق": ["طلاق", "الطلاق"],
            "نفقه": ["نفقة", "النفقة"],
            "عقوبه": ["عقوبة", "العقوبة"],
            "حقوق": ["حقوق", "الحقوق"],
            "محامي": ["محامٍ", "المحامي"],
            "قانون": ["قانون", "القانون"],
            "محكمه": ["محكمة", "المحكمة"],
            "حق": ["حق", "الحق"],
            "واجب": ["واجب", "الواجب"],
            "دعوي": ["دعوى", "الدعوى"],
            "عقد": ["عقد", "العقد"],
            "بيع": ["بيع", "البيع"],
            "شراء": ["شراء", "الشراء"],
            "ايجار": ["إيجار", "الإيجار"],
            "اجازه": ["إجازة", "الإجازة"],
            "راتب": ["راتب", "المرتب"],
            "اجر": ["أجر", "الأجر"],
            "خدمه": ["خدمة", "الخدمة"],
            "توصيف": ["تأشيرة", "تأشيرة"],
            "فيزا": ["تأشيرة", "تأشيرة الدخول"],

            # أخطاء في الفصحى
            "إقامه": ["إقامة", "الإقامة"],
            "إبتزاز": ["ابتزاز", "الابتزاز"],
            "إختناق": ["اختناق", ""],
            "إعتقال": ["اعتقال", "الاعتقال"],

            # أخطاء في المصطلحات القانونية
            "ميراث": ["إرث", "الميراث"],
            "توزيع تركه": ["تقسيم التركة", "توزيع التركة"],
            "رد اعتبار": ["رد الاعتبار", "إعادة الاعتبار"],
            "إنهاء عقد": ["إنهاء عقد العمل", "فسخ العقد"],
        }

    def detect_dialect(self, text: str) -> Tuple[Dialect, float]:
        """
        كشف اللهجة مع درجة الثقة
        العودة: (لهجة, درجة_الثقة)
        """
        text_lower = text.lower()
        scores: Dict[Dialect, float] = {d: 0.0 for d in Dialect}

        # الطريقة 1: بصمات الكلمات
        for dialect, signatures in self._dialect_signatures.items():
            for word, weight in signatures.items():
                if word in text_lower:
                    scores[dialect] += weight

        # الطريقة 2: أنماط regexp
        for dialect, patterns in self._dialect_patterns.items():
            for pattern, weight in patterns:
                if pattern.search(text):
                    scores[dialect] += weight

        # الطريقة 3: أحرف خاصة
        if 'گ' in text or 'چ' in text or 'پ' in text:
            scores[Dialect.IRAQI] += 20

        if 'ش' in text and ('ۋ' in text or 'ٱ' in text):
            scores[Dialect.LEVANTINE] += 15

        # حساب الدرجة النسبية
        total = sum(scores.values())
        if total == 0:
            return Dialect.STANDARD_ARABIC, 0.5

        # أفضل لهجة
        best_dialect = max(scores, key=scores.get)
        best_score = scores[best_dialect]

        # درجة الثقة
        confidence = min(best_score / max(total, 1), 0.99)

        # إذا كانت الثقة منخفضة جداً، اعتبرها فصحى
        if confidence < 0.15:
            return Dialect.STANDARD_ARABIC, 0.6

        return best_dialect, confidence

    def extract_entities(self, text: str) -> List[LegalEntity]:
        """
        استخراج الكيانات القانونية من النص
        """
        entities = []
        text_lower = text.lower()

        for entity_type, patterns in ENTITY_PATTERNS.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    entity_text = match.group(0)
                    entity_norm = self._normalize(entity_text)

                    entities.append(LegalEntity(
                        text=entity_text,
                        type=entity_type,
                        normalized=entity_norm,
                        confidence=0.85,
                        start_pos=match.start(),
                        end_pos=match.end()
                    ))

        return entities

    def detect_intent(self, text: str) -> Tuple[Intent, List[IntentResult]]:
        """
        كشف نية المستخدم مع درجة الثقة
        """
        text_norm = self._normalize(text)
        results = []

        for intent, patterns in INTENT_PATTERNS.items():
            for pattern, weight in patterns:
                if pattern.search(text):
                    results.append(IntentResult(
                        intent=intent,
                        confidence=weight,
                        reasoning=f"نمط متطابق: {pattern.pattern}",
                        context_keywords=[]
                    ))

        if not results:
            # إذا لم يتم كشف أي نية، افترض نية السؤال
            return Intent.QUESTION, [
                IntentResult(
                    intent=Intent.QUESTION,
                    confidence=0.6,
                    reasoning="لا نمط محدد - افتراض سؤال",
                    context_keywords=[]
                )
            ]

        # ترتيب حسب الثقة
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[0].intent, results

    def expand_query_semantic(
        self,
        text: str,
        dialect: Dialect,
        legal_terms: List[Tuple[str, float, Dialect]]
    ) -> List[Tuple[str, float]]:
        """
        توسيع الاستعلام دلالياً

        يرجع: قائمة من (استعلام, درجة_الثقة)
        """
        queries = []
        seen = set()

        # 1. الاستعلام الأصلي
        queries.append((text, 1.0))
        seen.add(self._normalize(text))

        # 2. الاستعلامات من التحويل العامي
        for term, confidence, term_dialect in legal_terms:
            if term_dialect == dialect or term_dialect == Dialect.STANDARD_ARABIC:
                # بديل عن الكلمة العامية
                for colloquial, expansions in COLLOQUIAL_TO_LEGAL_MAX.items():
                    for legal_term, conf, d in expansions:
                        if d == dialect or d == Dialect.STANDARD_ARABIC:
                            if legal_term in text or any(t in text for t in [colloquial]):
                                expanded = text.replace(colloquial, legal_term)
                                if self._normalize(expanded) not in seen:
                                    queries.append((expanded, confidence * conf * 0.9))
                                    seen.add(self._normalize(expanded))

        # 3. إضافة المرادفات القانونية
        for term, confidence, _ in legal_terms:
            synonyms = LEGAL_SYNONYMS.get(term, [])
            for synonym, syn_conf in synonyms:
                expanded = text.replace(term, synonym)
                if self._normalize(expanded) not in seen:
                    queries.append((expanded, confidence * syn_conf * 0.8))
                    seen.add(self._normalize(expanded))

        # 4. إضافة المصطلح القانوني فقط (للدقة)
        legal_only = ' '.join([t[0] for t in legal_terms[:3]])
        if legal_only and self._normalize(legal_only) not in seen:
            queries.append((legal_only, 0.85))
            seen.add(self._normalize(legal_only))

        # ترتيب حسب الثقة
        queries.sort(key=lambda x: x[1], reverse=True)

        # إرجاع أفضل 8 استعلام
        return queries[:8]

    def detect_ambiguity(
        self,
        text: str,
        entities: List[LegalEntity],
        legal_terms: List[Tuple[str, float, Dialect]]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        كشف الغموض في النص

        العودة: (غامض, نوع_الغموض, سؤال_التوضيح)
        """
        text_norm = self._normalize(text)
        word_count = len(text_norm.split())

        # 1. سؤال قصير جداً بدون سياق
        if word_count <= 3:
            # إذا كان يحتوي على كلمات غامضة
            ambiguous_words = {"حكم", "حق", "موقف", "شخص", "شي", "حد"}
            if any(w in text_norm for w in ambiguous_words):
                return True, "سؤال_قصير_غامض", (
                    "سؤالك عام جداً — هل يمكنك تحديد الموضوع؟ "
                    "مثلاً: 'ما عقوبة السرقة في قطر؟' بدلاً من 'ما الحكم؟'"
                )

        # 2. استخدام ضمائر بدون مرجع
        pronouns = {"هو", "هي", "ذاك", "تلك", "هذا", "هذه"}
        if any(p in text_norm for p in pronouns):
            if len(entities) == 0:  # لا يوجد مرجع صريح
                return True, "ضمير_بدون_مرجع", (
                    "يبدو أنك تشير لشخص أو موقف محدد — "
                    "هل يمكنك توضيح من الشخص أو ما الموضوع؟"
                )

        # 3. استخدام "ما حكم" بدون تحديد الجريمة
        if "حكم" in text_norm and len(legal_terms) == 0:
            return True, "موضوع_غير_محدد", (
                "هل يمكنك تحديد الموضوع؟ "
                "مثلاً: 'ما حكم النصب؟' أو 'ما عقوبة السرقة؟'"
            )

        # 4. نفي وممكنات متعددة
        negation_words = {"ما", "لا", "مش", "مو"}
        if any(n in text_norm for n in negation_words):
            if "وش" in text_norm or "ايش" in text_norm or "كيف" in text_norm:
                return True, "سؤال_معقد", (
                    "يبدو أن سؤالك يحتوي عدة احتمالات — "
                    "هل يمكنك تبسيطه أو تقسيمه؟"
                )

        return False, None, None

    def detect_spelling_errors(self, text: str) -> Dict[str, str]:
        """
        كشف وتصحيح الأخطاء الإملائية

        العودة: {خطأ: تصحيح}
        """
        corrections = {}
        text_norm = self._normalize(text)

        for wrong, correct_options in self._spelling_corrections.items():
            if wrong in text_norm:
                # استخدم أول تصحيح (الأقرب)
                corrections[wrong] = correct_options[0]

        return corrections

    def detect_legal_domain(
        self,
        text: str,
        legal_terms: List[Tuple[str, float, Dialect]]
    ) -> List[Tuple[str, float]]:
        """
        كشف المجال القانوني مع درجة الثقة
        """
        text_norm = self._normalize(text)

        # المجالات القانونية مع كلماتها المفتاحية
        domain_keywords = {
            "criminal": {
                "weight": 1.0,
                "words": {
                    "سرقة", "قتل", "ضرب", "اعتدى", "حبس", "عقوبة", "جريمة",
                    "غرامة", "اتهام", "إهمال", "وفاة", "سجن", "اعتقال",
                    "مخدرات", "ابتزاز", "احتيال", "نصب", "رشوة", "فساد"
                }
            },
            "labor": {
                "weight": 1.0,
                "words": {
                    "عمل", "راتب", "فصل", "أجر", "موظف", "عامل", "إجازة",
                    "توظيف", "خدمة", "مكافأة", "إنهاء", "تأمين", "تقاعد"
                }
            },
            "family": {
                "weight": 1.0,
                "words": {
                    "طلاق", "زواج", "حضانة", "نفقة", "ميراث", "وصية",
                    "خلع", "مهر", "نسب", "تعدد", "ولادة", "تبني"
                }
            },
            "civil": {
                "weight": 0.9,
                "words": {
                    "عقد", "تعويض", "فسخ", "ضمان", "التزام", "شيك",
                    "إثبات", "دعوى", "تقادم", "دين", "ضرر", "حق"
                }
            },
            "commercial": {
                "weight": 0.9,
                "words": {
                    "شركة", "تجارة", "عطاء", "مناقصة", "أسهم", "إفلاس",
                    "شيك", "براءة", "علامة", "ملكية", "منافسة"
                }
            },
            "administrative": {
                "weight": 1.0,
                "words": {
                    "تعيين", "ترقية", "نقل", "إقالة", "تأديب", "مظالم",
                    "جنسية", "إقامة", "ترحيل", "تقاعد", "وظيفة"
                }
            },
            "cyber": {
                "weight": 0.95,
                "words": {
                    "إلكتروني", "اختراق", "ابتزاز", "تهديد", "صور",
                    "خصوصية", "بيانات", "إنترنت", "فيسبوك", "تويتر"
                }
            },
            "property": {
                "weight": 0.9,
                "words": {
                    "عقار", "ملكية", "إيجار", "بيع", "شراء", "رهن",
                    "هبة", "وقف", "بناء", "أرض", "سكن"
                }
            }
        }

        # حساب الدرجات
        domain_scores = {}
        for domain, info in domain_keywords.items():
            score = 0
            for word in info["words"]:
                if word in text_norm:
                    # إذا كانت الكلمة في المصطلحات القانونية المستخرجة
                    for term, conf, _ in legal_terms:
                        if word in term or term in word:
                            score += conf * info["weight"]
                        elif word in text_norm:
                            score += 1.0 * info["weight"]

            if score > 0:
                domain_scores[domain] = score

        # ترتيب المجالات
        sorted_domains = sorted(
            domain_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_domains[:3]

    async def analyze(self, text: str) -> LinguisticAnalysisResult:
        """
        🎯 التحليل اللغوي الشامل

        يرجع: LinguisticAnalysisResult مع جميع المعلومات المستخرجة
        """
        start_time = time.time()

        # 1. التطبيع
        normalized = self._normalize(text)

        # 2. كشف اللهجة
        dialect, dialect_conf = self.detect_dialect(text)

        # 3. كشف وتصحيح الأخطاء الإملائية
        spelling_corrections = self.detect_spelling_errors(text)

        # 4. استخراج المصطلحات القانونية
        legal_terms = []
        text_lower = text.lower()
        for colloquial, expansions in COLLOQUIAL_TO_LEGAL_MAX.items():
            if colloquial in text_lower:
                for legal_term, conf, d in expansions:
                    if d == dialect or d == Dialect.STANDARD_ARABIC:
                        legal_terms.append((legal_term, conf * 0.9, d))

        # إضافة المصطلحات المشتركة
        for colloquial, expansions in COLLOQUIAL_TO_LEGAL_MAX.items():
            if colloquial in text_lower:
                for legal_term, conf, d in expansions:
                    if d == Dialect.STANDARD_ARABIC and (legal_term, conf, d) not in legal_terms:
                        legal_terms.append((legal_term, conf * 0.8, d))

        # إزالة التكرارات والترتيب
        seen_terms = set()
        unique_terms = []
        for term, conf, d in legal_terms:
            if term not in seen_terms:
                seen_terms.add(term)
                unique_terms.append((term, conf, d))

        unique_terms.sort(key=lambda x: x[1], reverse=True)

        # 5. استخراج الكيانات
        entities = self.extract_entities(text)

        # 6. كشف النية
        primary_intent, all_intents = self.detect_intent(text)

        # 7. كشف المجال القانوني
        domains = self.detect_legal_domain(text, unique_terms)
        primary_domain = domains[0][0] if domains else "غير محدد"

        # 8. توسيع الاستعلامات
        search_queries = self.expand_query_semantic(text, dialect, unique_terms)

        # 9. كشف الغموض
        is_ambiguous, ambiguity_type, clarification_q = self.detect_ambiguity(
            text, entities, unique_terms
        )

        # 10. إحصائيات
        word_count = len(text.split())
        arabic_chars = len(re.findall(r'[\u0600-\u06FF]', text))
        total_chars = len(text)
        arabic_ratio = arabic_chars / max(total_chars, 1)

        processing_time = (time.time() - start_time) * 1000

        return LinguisticAnalysisResult(
            original_text=text,
            normalized_text=normalized,
            dialect=dialect,
            confidence_dialect=dialect_conf,
            entities=entities,
            primary_intent=primary_intent,
            all_intents=all_intents,
            legal_terms=unique_terms,
            domains=domains,
            primary_domain=primary_domain,
            search_queries=search_queries,
            is_ambiguous=is_ambiguous,
            ambiguity_type=ambiguity_type,
            clarification_question=clarification_q,
            spelling_corrections=spelling_corrections,
            word_count=word_count,
            arabic_ratio=arabic_ratio,
            processing_time_ms=processing_time
        )


# ═════════════════════════════════════════════════════════════════════════════════════
# (§10) مثيل مشترك (Singleton)
# ═════════════════════════════════════════════════════════════════════════════════════

ultra_linguistic_engine = UltraLinguisticEngine()


# ═════════════════════════════════════════════════════════════════════════════════════
# (§11) امثلة الاستخدام
# ═════════════════════════════════════════════════════════════════════════════════════

async def demo():
    """مثال على الاستخدام"""
    engine = UltraLinguisticEngine()

    test_cases = [
        "جاري يسرق الكهرباء ايش الحكم؟",
        "طردوني من الشغل بدون سبب",
        "زوجتي تبي طلاق",
        "عندي نزاع مع جاري",
        "ايش حقوقي لو فصلوني؟",
        "كيف أقدم على مساعدة قانونية؟",
    ]

    for test in test_cases:
        print(f"\n{'='*60}")
        print(f"السؤال: {test}")
        print('='*60)

        result = await engine.analyze(test)

        print(f"\n📊 اللهجة: {result.dialect.value} ({result.confidence_dialect:.1%})")
        print(f"📊 النية: {result.primary_intent.value}")
        print(f"📊 المجال: {result.primary_domain}")

        print(f"\n📝 المصطلحات القانونية:")
        for term, conf, dialect in result.legal_terms[:5]:
            print(f"  • {term} ({conf:.1%})")

        print(f"\n🔍 استعلامات البحث:")
        for query, conf in result.search_queries[:3]:
            print(f"  • [{conf:.1%}] {query}")

        if result.is_ambiguous:
            print(f"\n⚠️ غموض: {result.ambiguity_type}")
            print(f"   سؤال التوضيح: {result.clarification_question}")


if __name__ == "__main__":
    asyncio.run(demo())
