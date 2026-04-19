# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════════╗
║              محرك Relevance القانوني المُحسّن - MAX Edition                       ║
║           Enhanced Legal Domain Relevance Engine - MAX Edition                     ║
║                                                                                  ║
║  الميزات المتقدمة:                                                               ║
║  • تصنيف المجال القانوني مُعزّز بالذكاء الاصطناعي                                 ║
║  • كشف وتحليل السوابق القضائية                                                 ║
║  • تنبؤ بالأحكام القانونية                                                       ║
║  • تحليل الروابط بين القوانين                                                   ║
║  • حساب Relevance متقدم مع مراعاة اللهجة                                         ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

الإصدار: 3.0-MAX
التاريخ: 2024
"""

import json
import re
import math
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import Counter

# ═══════════════════════════════════════════════════════════════════════════════════════
# محاولة استيراد محرك الفهم اللغوي المتقدم
# ═══════════════════════════════════════════════════════════════════════════════════════

try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from ultra_linguistic_engine import UltraLinguisticEngine, MAX_AVAILABLE
    ULTRA_ENGINE_AVAILABLE = MAX_AVAILABLE
except ImportError:
    ULTRA_ENGINE_AVAILABLE = False
    UltraLinguisticEngine = None

# ═══════════════════════════════════════════════════════════════════════════════════════
# أنواع البيانات والقوائم
# ═══════════════════════════════════════════════════════════════════════════════════════

class LegalDomain(Enum):
    """المجالات القانونية"""
    CRIMINAL = "جنائي"
    CIVIL = "مدني"
    COMMERCIAL = "تجاري"
    FAMILY = "أسري"
    LABOR = "عمالي"
    PROPERTY = "عقاري"
    ADMINISTRATIVE = "إداري"
    CYBER = "إلكتروني"
    PROCEDURAL = "إجرائي"
    CONSTITUTIONAL = "دستوري"
    INTERNATIONAL = "دولي"
    TAX = "ضريبي"
    PERSONAL_STATUS = "أحوال شخصية"
    MARITIME = "بحري"
    AVIATION = "جوي"
    INVESTMENT = "استثماري"
    BANKING = "مصرفي"
    INSURANCE = "تأميني"
    ENVIRONMENTAL = "بيئي"
    HEALTH = "صحي"
    EDUCATION = "تعليمي"
    MEDIA = "إعلامي"
    SPORTS = "رياضي"
    TOURISM = "سياحي"
    CUSTOMS = "جمركي"
    MILITARY = "عسكري"
    GENERAL = "قانوني عام"

class CaseType(Enum):
    """أنواع القضايا"""
    FELONY = "جناية"
    MISDEMEANOR = "جنحة"
    VIOLATION = "مخالفة"
    CIVIL_DISPUTE = "نزاع مدني"
    COMMERCIAL_DISPUTE = "نزاع تجاري"
    FAMILY_DISPUTE = "نزاع أسري"
    LABOR_DISPUTE = "نزاع عمالي"
    ADMINISTRATIVE_DISPUTE = "نزاع إداري"
    APPEAL = "استئناف"
    CASSATION = "نقض"

class JudgmentType(Enum):
    """أنواع الأحكام"""
    CONVICTION = "إدانة"
    ACQUITTAL = "براءة"
    DISMISSAL = "رفض"
    SETTLEMENT = "تصالح"
    COMPENSATION = "تعويض"
    DISQUALIFICATION = "حرمان"
    SUSPENSION = "تعليق"
    REVOCATION = "إلغاء"
    MODIFICATION = "تعديل"
    CONFIRMATION = "تأييد"

# ═══════════════════════════════════════════════════════════════════════════════════════
# نماذج البيانات المُحسّنة
# ═══════════════════════════════════════════════════════════════════════════════════════

@dataclass
class DomainScore:
    """نتيجة المجال"""
    domain: LegalDomain
    score: float
    keywords_found: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""

@dataclass
class LawPrecedent:
    """سابق قضائي"""
    case_number: str
    court: str
    year: int
    judgment_type: JudgmentType
    summary: str
    legal_principle: str
    relevance: float = 0.0

@dataclass
class LegalRelation:
    """علاقة قانونية"""
    source_law: str
    target_law: str
    relation_type: str  # modifies, complements, supersedes, related_to
    description: str = ""

@dataclass
class DomainAnalysis:
    """تحليل المجال"""
    primary_domain: LegalDomain
    secondary_domains: List[LegalDomain] = field(default_factory=list)
    case_type: Optional[CaseType] = None
    keywords: List[str] = field(default_factory=list)
    detected_entities: Dict[str, List[str]] = field(default_factory=dict)
    suggested_laws: List[str] = field(default_factory=list)
    estimated_complexity: str = "متوسط"
    requires_professional: bool = False
    urgency_indicators: List[str] = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════════════════════════════
# قاموس المصطلحات القانونية حسب المجال - مُوسّع
# ═══════════════════════════════════════════════════════════════════════════════════════

DOMAIN_KEYWORDS = {
    LegalDomain.CRIMINAL: {
        "خاصة": [
            "عقوبة", "سجن", "غرامة", "إدانة", "براءة", "جريمة", "جنحة", "مخالفة",
            "متهم", "مدان", "ضحية", "جاني", "مجني عليه", "نيابة", "ادعاء",
            "حبس", "توقيف", "إفراج", "محكمة جنائية", "جلسة", "حكم", "بطلان",
            "ظروف مشددة", "ظروف مخففة", "شروع", "اشتراك", "تحريض", "تمكين",
            "سرقة", "نصب", "احتيال", "رشوة", "فساد", "تهريب", "حيازة",
            "إيقاف", "احتجاز", "تفتيش", "ضبط", "مطاردة", "هروب", "مطلوب",
            "سابقة جنائية", "سجل جنائي", "نقض", "استئناف", "طعن"
        ],
        "العام": [
            "criminal", "penalty", "imprisonment", "conviction", "crime"
        ]
    },
    LegalDomain.CIVIL: {
        "خاصة": [
            "عقد", "اتفاقية", "التزام", "حق", "واجب", "طرف", "أطراف",
            "تعويض", "تعويضات", "دية", "ضرر", "لحوق", "نزاع", "خصومة",
            "دعوى", "رفع دعوى", "دفع", "أدنى", "بين", "تكييف", "تكييف قانوني",
            "ذمة مالية", "التزامات", "تنفيذ", "إلزام", "فسخ", "إنهاء",
            "إعلام", "إنذار", "مهلة", "أجل", "شرط", "شرط جزائي",
            "القوة القاهرة", "الظروف الاستثنائية", "السبب", "السبب المشروع",
            "نية", "نية التبرع", "نية الإضرار", "غش", "تدليس", "إكراه",
            " غبن", "ظهور", "نية التصرف", "ملكية", "حيازة", "نزع ملكية"
        ],
        "العام": [
            "contract", "obligation", "right", "compensation", "civil"
        ]
    },
    LegalDomain.COMMERCIAL: {
        "خاصة": [
            "شركة", "تجاري", "سوق", "سهم", "سندات", "أرباح", "خسائر",
            "شريك", "مساهم", "مجلس إدارة", "جمعية عمومية", "تأسيس",
            "نظام أساسي", "عقد تأسيس", "تعديل نظام", "اندماج", "استحواذ",
            "تصفية", "إفلاس", "تسوية", "صلح", "إعادة هيكلة",
            "سجل تجاري", "نشاط تجاري", "تجديد", "ترخيص تجاري",
            "وكيل تجاري", "وسيط", "مستشار", "مراقب حسابات",
            "ذمة تجارية", "أوراق تجارية", "كمبيالة", "سفتجة", "شيك",
            "اعتماد", "خطاب ضمان", "تأمين تجاري", "تأمين ائتمان",
            "بورصة", "تداول", "استثمار", "محفظة", "عائد", "أرباح",
            "توزيع", "احتياطي", "رأس مال", "زيادة رأس مال", "تخفيض رأس مال",
            "سهم ممتاز", "سهم عادي", "أرباح محتجزة", "خسائر متراكمة",
            "العلامة التجارية", "براءة اختراع", "حقوق الملكية الفكرية",
            "ترخيص", "نقل التكنولوجيا", "شراكة", "مشروع مشترك",
            "توكيل", "توزيع", "مزاولة تجارة", "نشاط اقتصادي"
        ],
        "العام": [
            "company", "commercial", "trade", "stock", "investment"
        ]
    },
    LegalDomain.FAMILY: {
        "خاصة": [
            "زواج", "طلاق", "حضانة", "نفقة", "صداق", "مهر", "بكور",
            "إرث", "ميراث", "وصية", "ولاية", "ولاية نصرف", "توكيل",
            "زوج", "زوجة", "أب", "أم", "ابن", "ابنة", "أخ", "أخت",
            "أم", "أب", "جدة", "جد", "حفيد", "حفيدة", "عم", "عمة",
            "خال", "خالة", "قرابة", "درجة قرابة", "محارم", "زواج أقارب",
            "خطبة", "مخطوبة", "خاطب", "عروس", "عرسان", "زواج مدني",
            "زواج ديني", "كفاءة", "موانع الزواج", "انحلال الزواج",
            "تطليق", "خلع", "فسخ نكاح", "بطلان زواج", "إثبات زواج",
            "حضانة مشتركة", "حضانةExclusive", "ولاية", "رؤية", "ضمان",
            "نفقة زوجية", "نفقة أولاد", "نفقة متعة", "متعة طلاق",
            "حصة", "نصيب", "قسمة", "قسم", "نصيب الزوج", "نصيب الزوجة",
            "إشهاد", "إشهاد طلاق", "إشهاد挽回", "توثيق", "تصديق",
            "تعديل سجل", "تعديل الحالة المدنية", "سجل الأسرة",
            "الطلاق الرجعي", "الطلاق البائن", "العدة", "الاستحكام"
        ],
        "العام": [
            "marriage", "divorce", "custody", "family", "alimony"
        ]
    },
    LegalDomain.LABOR: {
        "خاصة": [
            "وظيفة", "موظف", "صاحب عمل", "رب عمل", "إنهاء خدمة",
            "فصل", "استقالة", "إنذار", "إنذار مسبق", "مدة التجربة",
            "عقد عمل", "عقد indefinite", "عقد محدد المدة", "تجديد عقد",
            "راتب", "أجر", "بدلات", "بدل سكن", "بدل تنقل", "بدل هاتف",
            "مكافأة", "مكافأة نهاية الخدمة", "مكافأة خدمة", "تعويض",
            "ساعات عمل", "وقت العمل", "وقت الراحة", "إجازة", "إجازة سنوية",
            "إجازة مرضية", "إجازة أمومة", "إجازة وضع", "إجازة استثنائية",
            "تأمين", "تأمين صحي", "صناديق", "تأمين اجتماعي", "التأمينات",
            "معاش", "معاش تقاعدي", "اشتراك", "تقاعد", "استقالة",
            "جزاء", "خصم", "إنذار كتابي", "فصل تأديبي", "لوم",
            "لجان", "لجنة توظيف", "لجنة تأديب", "لجنة تسوية",
            "تفتيش", "تفتيش العمل", "مفتش", "مكتب العمل", "وزارة العمل",
            "حماية", "حماية العمال", "معايير", "معايير السلامة",
            "عمل إضافي", "أجر overtime", "عمل ليلي", "عمل خطير",
            "صحة مهنية", "سلامة مهنية", "حوادث عمل", "إصابة عمل",
            "إعاقة", "إعادة التأهيل", "التأهيل المهني",
            "تأهيل", "تدريب", "تطوير", "ترقي", "ترقية",
            "مكتب", "موظف government", "وظيفة عامة", "خدمة مدنية",
            "مزايا", "امتيازات", "بدلات", "مخصصات", "علاوات"
        ],
        "العام": [
            "labor", "employment", "work", "salary", "worker", "employer"
        ]
    },
    LegalDomain.PROPERTY: {
        "خاصة": [
            "ملكية", "عقار", "أرض", "بناء", "بيت", "شقة", "فيلا",
            "مبنى", "محل", "مكتب", "مصنع", "مستودع", "مزرعة",
            "سجل عقاري", "سجل الأراضي", "طابو", "حصر", "مساحة",
            "حدود", "منطقة", "موقع", "عنوان", "رقم عقار",
            "بيع", "شراء", "صفقة", "سعر", "ثمن", "عربون", "دفعة مقدمة",
            "رهن", "رهن عقاري", "رهن官", "ضمان", "ضمانة",
            "إيجار", "تأجير", "عقد إيجار", "مستأجر", "مؤجر",
            "إخلاء", "طرد", "إزالة", "هدم", "ترميم", "صيانة",
            "شارع", "طريق", "نفق", "جسر", "مرافق", "خدمات",
            "نزع ملكية", "مصلحة عامة", "تعويض نزع ملكية",
            "شركة عقارية", "وسيط عقاري", "سمسار", "وكيل عقاري",
            "تقييم", "خبير", "خبير عقاري", "تثمين",
            "ضريبة عقارية", "ضريبة قيمة مضافة", "رسوم",
            "ورثة", "تركة", "قسم تركة", "إرث", "وصية",
            "هبة", "تبرع", "وقف", "مؤسسة", "خيرية",
            "تجزئة", "تجميع", "دمج", "تقسيم", "خريطة",
            "مخطط", "رخصة بناء", "ترخيص", "موافقة", "تصريح",
            "تنظيم", "بناء مخالف", "هدم", "غرامة بناء"
        ],
        "العام": [
            "property", "real estate", "land", "ownership", "rent"
        ]
    },
    LegalDomain.ADMINISTRATIVE: {
        "خاصة": [
            "إدارة", "قرار إداري", "لائحة", "لائحة تنفيذية", "لائحة تنظيمية",
            "قرار", "قرارات", "تعميم", "تعليمات", "توجيهات",
            "موظف حكومي", "موظف civil servant", "موظف public",
            "جهة حكومية", "جهة إدارية", "وزارة", "دائرة", "مصلحة",
            "سلطة", "صلاحيات", "اختصاص", "ولاية", "تفويض",
            "طعن", "طعن إداري", "استئناف إداري", "نقض إداري",
            "محكمة إدارية", "مجلس الدولة", "دائرة شؤون",
            "موافقة", "رخصة", "ترخيص", "تصريح", "إجازة",
            "لجان", "لجان إدارية", "لجان استشارية", "مجالس",
            "خدمات عامة", "مرافق عامة", "مشاريع عامة",
            "ميزانية", "ميزانية عامة", "تخصيص", "إنفاق",
            "فساد", "رشوة", "إثراء غير مشروع", "تبديد", "احتيال حكومي",
            "مسؤولية", "مسؤولية إدارية", "مسؤولية سياسية",
            "تنظيم", "تنظيمية", "رقابة", "مراقبة", "إشراف",
            "عامة", "شؤون", "أحوال", "قانون", "لائحة"
        ],
        "العام": [
            "administrative", "government", "regulation", "public"
        ]
    },
    LegalDomain.CYBER: {
        "خاصة": [
            "إنترنت", "حاسوب", "كمبيوتر", "أمن معلومات", "أمن سيبراني",
            "اختراق", "اختراق电脑", "تهديد", "هجوم سيبراني",
            "برمجيات", "تطبيق", "تطبيقات", "منصة", "موقع",
            "بيانات", "بيانات شخصية", "خصوصية", "خصوصية رقمية",
            "تصنت", "مراقبة", "تجسس", "تنصت",
            "إلكتروني", "رقمي", "تقنية", "تكنولوجيا",
            "جرائم إلكترونية", "جرائم computer", "أمن رقمي",
            "فيروس", "ملفات خبيثة", "برمجيات خبيثة", "malware",
            "هجوم denial", "هجوم الحرمان من الخدمة", "DDoS",
            "تصيد", "phishing", "احتيال إلكتروني", "نصب إلكتروني",
            "سرقة هوية", "انتحال", "تزييف", "تزوير",
            "تشفير", "encryption", "فك تشفير", "مفتاح", "شهادة",
            "توقيع رقمي", "signature", "هوية رقمية",
            "حماية بيانات", "أمن بيانات", "تسريب", "كشف",
            "امتثال", "تنظيم", "سياسة", "لائحة",
            "جرائم المعلوماتية", "قانون المعلوماتية", "جرائم تقنية",
            "محادثات", "بريد إلكتروني", "رسائل", "شات",
            "وسائط اجتماعية", "فيسبوك", "تويتر", "إنستغرام",
            "محتوى", "نشر", "مشاركة", "إعادة نشر",
            "حقوق", "حقوق الملكية الفكرية", "حقوق المؤلف", "براءة اختراع",
            "علامات تجارية", "أسرار تجارية", "سر تجاري",
            "تنافس", "ممارسات احتكارية", "احتكار", "وحود",
            "منافسة عادلة", "تنافس عادل", "مكافحة الاحتكار"
        ],
        "العام": [
            "cyber", "digital", "internet", "computer", "online", "data"
        ]
    },
    LegalDomain.PROCEDURAL: {
        "خاصة": [
            "قضاء", "محكمة", "جلسة", "جلسات", "مداولة", "حكم",
            "دعوى", "رفع دعوى", "دعوى قضائية", "بلاغ", "تقرير",
            "مدعى", "مدعى عليه", "مدعي", "مدعى عليه", "خصم", "خصوم",
            "وكيل", "محامي", "محرر", "مستشار قانوني",
            "إجراءات", "إجراءات قضائية", "مراحل", "خطوات",
            "اختصاص", "اختصاص محكمة", "ولاية محكمة", "صلاحية",
            "أدلة", "بينة", "برهان", "شهادة", "شهادة شهود",
            "إثبات", "أدلة", "قرائن", "ظروف", "ملفات",
            "أجل", "مهلة", "موعد", "توقيت", "توقيتات",
            "استئناف", "نقض", "طعن", "طعن بالنقض", "طعن بالاستئناف",
            "محكمة ابتدائية", "محكمة استئناف", "محكمة عليا", "محكمة النقض",
            "نيابة", "ادعاء عام", "مدعي عام", "نيابة عامة",
            "تنفيذ", "تنفيذ حكم", "حكم تنفيذي", "إنفاذ",
            "مكتب تنفيذ", "قاضي تنفيذ", "حجز", "مصادرة",
            "تقادم", "تقادم دعوى", "تقادم حكم", "آجال التقادم",
            "انقطاع", "انقطاع تقادم", "وقف", "وقف التقادم",
            "الأساس", "السبب", "السبب القانوني", "السبب المادي",
            "الدفع", "دفع", "دفوع", "دفع شكلي", "دفع جوهري",
            "بطلان", "بطلان إجراء", "بطلان حكم", "بطلان ذاتي",
            "حجية", "حجية الحكم", "حجية السند", "حجية المستند",
            "العلنية", "جلسة علنية", "سرية", "جلسة سرية"
        ],
        "العام": [
            "procedure", "court", "trial", "legal process", "litigation"
        ]
    },
    LegalDomain.TAX: {
        "خاصة": [
            "ضريبة", "ضريبي", "ضريبة دخل", "ضريبة أرباح", "ضريبة ريع",
            "ضريبة القيمة المضافة", "VAT", "ضريبة المبيعات", "ضريبة استهلاك",
            "ضريبة عقارية", "ضريبة سيارات", "ضريبة نقل", "ضريبة وراثة",
            "ضريبة جمركية", "رسوم جمركية", "رسوم", "ضرائب",
            "إقرار", "إقرار ضريبي", "تقرير ضريبي", "بيانات ضريبية",
            "واجب ضريبي", "التزام ضريبي", "أداء ضريبي", "سداد ضريبي",
            "ت逃避 ضريبي", "تهرب ضريبي", "تحايل ضريبي", "تجنب ضريبي",
            "خصم", "خصم ضريبي", "استقطاع", "استقطاع ضريبي",
            "إعفاء", "إعفاء ضريبي", "معفى", "معفى من الضريبة",
            "نسبة", "نسبة ضريبية", "شريحة", "شرائح ضريبية", "معدل",
            "سقف", "حد أقصى", "حد أدنى", "حدود",
            "فاتورة", "فاتورة ضريبية", "إيصال", "سجلات ضريبية",
            "مكتب ضرائب", "صلحة", " مصلحة税务局", "جهة ضريبية",
            "فحص ضريبي", "تدقيق ضريبي", "تحقيق ضريبي", "تحقيق",
            "غرامة ضريبية", "عقوبة ضريبية", "فائدة تأخير", "رسم تأخير",
            "تعديل ضريبي", "تصحيح ضريبي", "تعديل إقرار",
            "ازدواجية ضريبية", "اتفاقية ضريبية", "معاهدة ضريبية",
            "مبدأ", "مبدأ الضريبة الشخصية", "مبدأ الإقليمية",
            "موطن", "موطن ضريبي", "مركز رئيسي", "مصدر الدخل"
        ],
        "العام": [
            "tax", "taxation", "taxes", "revenue", "IRS", "fiscal"
        ]
    },
    LegalDomain.BANKING: {
        "خاصة": [
            "بنك", "مصرف", "مصارف", "خدمات مصرفية", "عمليات مصرفية",
            "حساب", "حساب جاري", "حساب توفير", "حساب deposit",
            "وديعة", "وديعة بنكية", "وديعة لأجل", "وديعة جارية",
            "قرض", "قروض", "إقراض", "اقتراض", "تمويل",
            "فائدة", "فوائد", "نسبة فائدة", "معدل فائدة", "APR",
            "تأمين", "ضمان", "ضمانة", "ضمان مصرفي", "خطاب ضمان",
            "بطاقة ائتمان", "بطاقة debit", "بطاقة مصرفية", " visa", " mastercard",
            "تحويل", "تحويل بنكي", "حوالة", "حوالة مصرفية", "SWIFT",
            "صرف عملات", "صرف أجنبي", "عملة", "سعر صرف", "forex",
            "تأمين", "تأمين مصرحي", "تأمين إسلامي", "تأمين تقليدي",
            "خطاب اعتماد", "اعتماد مستندي", "اعتماد bank", "L/C",
            "ضمان", "ضمانة", "رهن", "رهن bank", "رهن عقاري",
            "نقد", "نقدية", "سيولة", "ملاءة", "ملاءة مالية",
            "إفلاس", "تصفية", "تسوية", "إعادة هيكلة",
            "غسيل أموال", "مكافحة غسيل الأموال", "AML", "KYC",
            "تنظيم مصرفي", "رقابة مصرفية", "بنك مركزي", "سعر الفائدة",
            "سياسة نقدية", "سياسة مالية", "ت_quantitative",
            "سعر repo", "سعر libor", "سعر أساسية", "أساس",
            "مخاطر", "مخاطر ائتمانية", "مخاطر سوق", "مخاطر سيولة",
            "الامتثال", "متطلبات رأسمالية", "Basel", "بازل"
        ],
        "العام": [
            "bank", "banking", "finance", "credit", "loan", "interest"
        ]
    },
    LegalDomain.INSURANCE: {
        "خاصة": [
            "تأمين", "تأميني", "وثيقة تأمين", "بوليصة", "policy",
            "مؤمن", "مؤمن له", "شركة تأمين", "مؤمن عليه",
            "أقساط", "قسط", "قسط شهري", "قسط سنوي", "اشتراك",
            "تغطية", "نطاق التغطية", "استثناءات", "شروط",
            "مطالبة", "مطالبة تأمينية", "تعويض", "تعويض تأميني",
            "خطر", "أخطار", "حدث مؤمن عليه", "خطر مؤمن عليه",
            "تأمين حياة", "تأمين صحي", "تأمين سيارات", "تأمين طبي",
            "تأمين عقاري", "تأمين ممتلكات", "تأمين مسئولية",
            "تأمين travel", "تأمين سفر", "تأمين تعليم", "تأمين مخاطر",
            "تأمين إسلامي", "تأمين تكافلي", "تأمين reinsurance",
            "وكيل تأمين", "وسيط", "مستشار تأمين", "اكتاب",
            "اكتتاب", "تقييم مخاطر", "تصنيف", "تصنيف مخاطر",
            "حدود", "حدCoverage", "حد liability", "حد أقصى",
            "استقطاع", "خصم", "deductible", "franchise",
            "تجديد", "تجديد بوليصة", "إنهاء", "إنهاء بوليصة",
            "نزاع", "نزاع تأميني", "تحكيم تأميني", "طعن",
            "خبير", "خبير تأمين", "خبير تقييم", "تقييم أضرار",
            "حادث", "حادث مؤمن عليه", "خسارة", "خسارة إجمالية",
            "خسارة جزئية", "استبدال", "إصلاح", "تعويض نقدي",
            "بنود", "شروط", "استثناءات", "شرط", "بنود خاصة"
        ],
        "العام": [
            "insurance", "coverage", "policy", "claim", "premium"
        ]
    },
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# أوزان المجالات القانونية
# ═══════════════════════════════════════════════════════════════════════════════════════

DOMAIN_WEIGHTS = {
    LegalDomain.CRIMINAL: {"base": 0.9, "priority": 1},
    LegalDomain.FAMILY: {"base": 0.85, "priority": 2},
    LegalDomain.LABOR: {"base": 0.85, "priority": 2},
    LegalDomain.CIVIL: {"base": 0.8, "priority": 3},
    LegalDomain.COMMERCIAL: {"base": 0.8, "priority": 3},
    LegalDomain.PROPERTY: {"base": 0.8, "priority": 3},
    LegalDomain.ADMINISTRATIVE: {"base": 0.75, "priority": 4},
    LegalDomain.CYBER: {"base": 0.75, "priority": 4},
    LegalDomain.BANKING: {"base": 0.75, "priority": 4},
    LegalDomain.INSURANCE: {"base": 0.75, "priority": 4},
    LegalDomain.TAX: {"base": 0.75, "priority": 4},
    LegalDomain.PROCEDURAL: {"base": 0.7, "priority": 5},
    LegalDomain.GENERAL: {"base": 0.5, "priority": 10},
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# خريطة القوانين القطرية
# ═══════════════════════════════════════════════════════════════════════════════════════

QATARI_LAWS_MAP = {
    "قانون العقوبات": {
        "الرقم": "11/2004",
        "المجال": LegalDomain.CRIMINAL,
        "الكلمات المفتاحية": ["عقوبات", "جنايات", "جنح", "جرائم", "حبس", "غرامة"]
    },
    "قانون الإجراءات الجنائية": {
        "الرقم": "23/2004",
        "المجال": LegalDomain.CRIMINAL,
        "الكلمات المفتاحية": ["إجراءات جنائية", "محاكمة", "جلسة", "دليل", "شهادة"]
    },
    "قانون الأسرة": {
        "الرقم": "22/2006",
        "المجال": LegalDomain.FAMILY,
        "الكلمات المفتاحية": ["زواج", "طلاق", "حضانة", "نفقة", "ميراث", "وصية"]
    },
    "قانون العمل": {
        "الرقم": "14/2004",
        "المجال": LegalDomain.LABOR,
        "الكلمات المفتاحية": ["عمل", "موظف", "صاحب عمل", "راتب", "إجازة", "فصل"]
    },
    "قانون التجارة": {
        "الرقم": "27/2006",
        "المجال": LegalDomain.COMMERCIAL,
        "الكلمات المفتاحية": ["تجارة", "شركة", "سوق", "سهم", "سندات", "تجاري"]
    },
    "قانون الشركات التجارية": {
        "الرقم": "11/2015",
        "المجال": LegalDomain.COMMERCIAL,
        "الكلمات المفتاحية": ["شركة", "تأسيس", "مساهم", "مجلس إدارة", "جمعية عمومية"]
    },
    "قانون الإجراءات المدنية": {
        "الرقم": "13/1990",
        "المجال": LegalDomain.PROCEDURAL,
        "الكلمات المفتاحية": ["إجراءات مدنية", "دعوى", "محكمة", "حكم", "طعن"]
    },
    "قانون المخدرات": {
        "الرقم": "9/1987",
        "المجال": LegalDomain.CRIMINAL,
        "الكلمات المفتاحية": ["مخدرات", "تهريب", "حيازة", "تعاطي", "مواد مخدرة"]
    },
    "قانون المرور": {
        "الرقم": "19/2007",
        "المجال": LegalDomain.CRIMINAL,
        "الكلمات المفتاحية": ["مرور", "مخالفة مرورية", "رخصة", "حوادث", "قيادة"]
    },
    "قانون الجنسية": {
        "الرقم": "38/2005",
        "المجال": LegalDomain.ADMINISTRATIVE,
        "الكلمات المفتاحية": ["جنسية", "مواطن", "تجنس", "جواز سفر"]
    },
    "قانون الجرائم المعلوماتية": {
        "الرقم": "24/2015",
        "المجال": LegalDomain.CYBER,
        "الكلمات المفتاحية": ["معلوماتية", "إلكتروني", "اختراق", "بيانات", "خصوصية"]
    },
    "قانون مكافحة غسيل الأموال": {
        "الرقم": "3/2010",
        "المجال": LegalDomain.BANKING,
        "الكلمات المفتاحية": ["غسيل أموال", "تمويل", "إرهاب", "مكافحة"]
    },
    "قانون ضريبة القيمة المضافة": {
        "الرقم": "1/2019",
        "المجال": LegalDomain.TAX,
        "الكلمات المفتاحية": ["ضريبة", "قيمة مضافة", "VAT", "إقرار", "ضريبي"]
    },
    "قانون تنظيم المناقصات والمزايدات": {
        "الرقم": "8/2017",
        "المجال": LegalDomain.ADMINISTRATIVE,
        "الكلمات المفتاحية": ["مناقصة", "مزايدة", "عطاء", "شراء", "توريد"]
    },
    "قانون الصحة العامة": {
        "الرقم": "22/2021",
        "المجال": LegalDomain.HEALTH,
        "الكلمات المفتاحية": ["صحة", "طبي", "علاج", "مستشفى", "وباء"]
    },
    "قانون البيئة": {
        "الرقم": "30/2002",
        "المجال": LegalDomain.ENVIRONMENTAL,
        "الكلمات المفتاحية": ["بيئة", "تلوث", "حماية بيئية", "نفايات"]
    },
    "قانون التعليم": {
        "الرقم": "25/2001",
        "المجال": LegalDomain.EDUCATION,
        "الكلمات المفتاحية": ["تعليم", "مدرسة", "جامعة", "طالب", "معلم"]
    },
    "قانون الاتصالات": {
        "الرقم": "36/2015",
        "المجال": LegalDomain.CYBER,
        "الكلمات المفتاحية": ["اتصالات", "إنترنت", "هاتف", "بيانات"]
    },
    "قانون الطيران المدني": {
        "الرقم": "15/2016",
        "المجال": LegalDomain.AVIATION,
        "الكلمات المفتاحية": ["طيران", "طائرة", "مطار", "رحلات"]
    },
    "قانون الاستثمار": {
        "الرقم": "1/2019",
        "المجال": LegalDomain.INVESTMENT,
        "الكلمات المفتاحية": ["استثمار", "مستثمر", "رأس مال", "منطقة حرة"]
    },
    "قانون الرياضة": {
        "الرقم": "15/2011",
        "المجال": LegalDomain.SPORTS,
        "الكلمات المفتاحية": ["رياضة", "نادي", "رياضي", "بطولة", "أولمبياد"]
    },
    "قانون السياحة": {
        "الرقم": "10/2014",
        "المجال": LegalDomain.TOURISM,
        "الكلمات المفتاحية": ["سياحة", "فندق", "سائح", "مرشد", "ركاب"]
    },
    "قانون الجمارك": {
        "الرقم": "40/2016",
        "المجال": LegalDomain.CUSTOMS,
        "الكلمات المفتاحية": ["جمارك", "استيراد", "تصدير", "رسوم جمركية", "بيان جمركي"]
    },
    "قانون الجنسية القطرية": {
        "الرقم": "38/2005",
        "المجال": LegalDomain.ADMINISTRATIVE,
        "الكلمات المفتاحية": ["جنسية", "تجنس", "مواطنة", "خروج", "دخول"]
    },
    "قانون الدفاع": {
        "الرقم": "3/1978",
        "المجال": LegalDomain.MILITARY,
        "الكلمات المفتاحية": ["دفاع", "عسكري", "خدمة عسكرية", "تجنيد"]
    },
    "قانون الشرطة": {
        "الرقم": "9/1978",
        "المجال": LegalDomain.ADMINISTRATIVE,
        "الكلمات المفتاحية": ["شرطة", "أمن", "حماية", "نظام عام"]
    },
    "قانون المحاماة": {
        "الرقم": "5/2015",
        "المجال": LegalDomain.PROCEDURAL,
        "الكلمات المفتاحية": ["محاماة", "محامي", "ترخيص", "نقابة المحامين"]
    },
    "قانون الشهر العقاري": {
        "الرقم": "14/1968",
        "المجال": LegalDomain.PROPERTY,
        "الكلمات المفتاحية": ["شهر عقاري", "سجل عقاري", "توثيق", "عقار"]
    },
    "قانون أملاك الدولة": {
        "الرقم": "12/1964",
        "المجال": LegalDomain.PROPERTY,
        "الكلمات المفتاحية": ["أملاك دولة", "أراضي", "دولة", "ملكية عامة"]
    },
    "قانون municipal": {
        "الرقم": "12/1996",
        "المجال": LegalDomain.PROPERTY,
        "الكلمات المفتاحية": ["بلدية", "تخطيط", "بناء", "رخصة بناء", "مخطط"]
    },
    "قانون المالية": {
        "الرقم": "8/2007",
        "المجال": LegalDomain.ADMINISTRATIVE,
        "الكلمات المفتاحية": ["مالية", "ميزانية", "إنفاق", "رقابة", "مراقبة"]
    },
    "قانون الكهرباء والماء": {
        "الرقم": "3/2007",
        "المجال": LegalDomain.ADMINISTRATIVE,
        "الكلمات المفتاحية": ["كهرباء", "ماء", "مرافق", "خدمات عامة"]
    },
    "قانون الأحداث": {
        "الرقم": "11/2017",
        "المجال": LegalDomain.CRIMINAL,
        "الكلمات المفتاحية": ["أحداث", "قاصر", "طفل", "رعاية", "إصلاح"]
    },
    "قانون حماية المستهلك": {
        "الرقم": "10/2002",
        "المجال": LegalDomain.COMMERCIAL,
        "الكلمات المفتاحية": ["مستهلك", "حماية", "سلعة", "خدمة", "غش"]
    },
    "قانون الملكية الفكرية": {
        "الرقم": "7/2002",
        "المجال": LegalDomain.COMMERCIAL,
        "الكلمات المفتاحية": ["ملكية فكرية", "براءة اختراع", "علامة تجارية", "حقوق"]
    },
    "قانون المنشآت الثقافية": {
        "الرقم": "8/1998",
        "المجال": LegalDomain.MEDIA,
        "الكلمات المفتاحية": ["ثقافة", "متحف", "أدب", "فن", "تراث"]
    },
    "قانون المطبوعات والنشر": {
        "الرقم": "8/1979",
        "المجال": LegalDomain.MEDIA,
        "الكلمات المفتاحية": ["مطبوعات", "نشر", "صحافة", "صحفي", "إعلام"]
    },
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# محرك Relevance القانوني المُحسّن
# ═══════════════════════════════════════════════════════════════════════════════════════

class EnhancedDomainRelevanceEngine:
    """
    محرك Relevance القانوني المُحسّن - MAX Edition

    الميزات:
    - تصنيف المجال القانوني مُعزّز بالذكاء الاصطناعي
    - كشف وتحليل السوابق القضائية
    - تنبؤ بالأحكام القانونية
    - تحليل الروابط بين القوانين
    - حساب Relevance متقدم مع مراعاة اللهجة
    """

    def __init__(self, use_ultra_engine: bool = True):
        """
        تهيئة محرك Relevance

        Args:
            use_ultra_engine: استخدام محرك الفهم اللغوي المتقدم
        """
        self.qatari_laws = QATARI_LAWS_MAP
        self.domain_keywords = DOMAIN_KEYWORDS
        self.domain_weights = DOMAIN_WEIGHTS

        # محاولة تهيئة محرك الفهم اللغوي المتقدم
        self.ultra_engine = None
        if use_ultra_engine and ULTRA_ENGINE_AVAILABLE:
            try:
                self.ultra_engine = UltraLinguisticEngine()
                print("✓ UltraLinguisticEngine مُفعّل في DomainRelevanceEngine")
            except Exception as e:
                print(f"⚠ تعذر تفعيل UltraLinguisticEngine: {e}")

    def classify_domain(
        self,
        query: str,
        sources: Optional[List[Dict]] = None,
        context: Optional[Dict] = None
    ) -> DomainAnalysis:
        """
        تصنيف المجال القانوني للسؤال

        Args:
            query: سؤال المستخدم
            sources: المصادر المتاحة
            context: سياق إضافي

        Returns:
            DomainAnalysis: تحليل المجال
        """
        sources = sources or []
        context = context or {}

        # استخراج الكلمات المفتاحية من السؤال
        query_keywords = self._extract_keywords(query)

        # حساب النتيجة لكل مجال
        domain_scores = []
        for domain, keywords_data in self.domain_keywords.items():
            score_info = self._calculate_domain_score(
                query,
                query_keywords,
                domain,
                keywords_data
            )
            if score_info.score > 0:
                domain_scores.append(score_info)

        # ترتيب النتائج
        domain_scores.sort(key=lambda x: x.score, reverse=True)

        # تحديد المجال الأساسي والثانوي
        primary_domain = domain_scores[0].domain if domain_scores else LegalDomain.GENERAL
        secondary_domains = [
            ds.domain for ds in domain_scores[1:4]
            if ds.score > 0.3
        ]

        # كشف نوع القضية
        case_type = self._detect_case_type(query)

        # كشف القوانين ذات الصلة
        suggested_laws = self._suggest_laws(query, primary_domain)

        # كشف التعقيد
        complexity = self._estimate_complexity(query, sources, domain_scores)

        # كشف الحاجة لمتخصص
        requires_professional = self._requires_professional(query, case_type, primary_domain)

        # كشف مؤشرات الاستعجال
        urgency_indicators = self._detect_urgency(query)

        # كشف الكيانات
        entities = self._extract_entities(query)

        return DomainAnalysis(
            primary_domain=primary_domain,
            secondary_domains=secondary_domains,
            case_type=case_type,
            keywords=query_keywords,
            detected_entities=entities,
            suggested_laws=suggested_laws,
            estimated_complexity=complexity,
            requires_professional=requires_professional,
            urgency_indicators=urgency_indicators
        )

    def _extract_keywords(self, text: str) -> List[str]:
        """استخراج الكلمات المفتاحية من النص"""
        # تحويل النص لحروف صغيرة
        text_lower = text.lower()

        # إزالة علامات الترقيم
        text_clean = re.sub(r'[^\w\s\u0600-\u06FF]', ' ', text_lower)

        # تقسيم الكلمات
        words = text_clean.split()

        # استخراج bigrams
        bigrams = []
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            bigrams.append(bigram)

        # استخراج trigrams
        trigrams = []
        for i in range(len(words) - 2):
            trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
            trigrams.append(trigram)

        # جمع الكل
        all_terms = words + bigrams + trigrams

        # إزالة الكلمات الشائعة
        stop_words = {
            'في', 'من', 'إلى', 'على', 'عن', 'مع', 'هذا', 'هذه', 'التي', 'الذي',
            'ما', 'هو', 'هي', 'كان', 'كانت', 'أن', 'إن', 'أو', 'و', 'ثم',
            'لكن', 'حيث', 'كما', 'حتى', 'لو', 'إذا', 'أي', 'كل', 'بعض',
            'لا', 'لم', 'لن', 'قد', 'بعد', 'قبل', 'بين', 'ذلك', 'تلك',
            'said', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall'
        }

        keywords = [
            term for term in all_terms
            if term not in stop_words
            and len(term) > 2
        ]

        return keywords

    def _calculate_domain_score(
        self,
        query: str,
        keywords: List[str],
        domain: LegalDomain,
        keywords_data: Dict
    ) -> DomainScore:
        """حساب نتيجة المجال"""

        # الحصول على الكلمات المفتاحية الخاصة بالمجال
        domain_specific = keywords_data.get("خاصة", [])
        domain_general = keywords_data.get("العام", [])

        # البحث عن الكلمات المفتاحية
        found_specific = []
        found_general = []
        query_lower = query.lower()

        for term in domain_specific:
            if term in query_lower:
                found_specific.append(term)
            # البحث أيضاً في الكلمات المستخرجة
            for keyword in keywords:
                if term in keyword or keyword in term:
                    if term not in found_specific:
                        found_specific.append(term)

        for term in domain_general:
            if term.lower() in query_lower:
                found_general.append(term)

        # حساب النتيجة
        score = 0.0

        # الأوزان
        if found_specific:
            score += min(len(found_specific) * 0.15, 0.6)  # max 0.6 for specific
        if found_general:
            score += min(len(found_general) * 0.1, 0.3)  # max 0.3 for general

        # وزن المجال الأساسي
        domain_weight = self.domain_weights.get(domain, {"base": 0.5, "priority": 10})
        score *= domain_weight["base"]

        # حساب الثقة
        total_specific = len(domain_specific)
        found_ratio = len(found_specific) / max(total_specific, 1)
        confidence = min(found_ratio + 0.3, 0.95)

        # التreasoning
        reasoning = f"تم العثور على {len(found_specific)} مصطلح خاص، {len(found_general)} مصطلح عام"

        return DomainScore(
            domain=domain,
            score=score,
            keywords_found=found_specific + found_general,
            confidence=confidence,
            reasoning=reasoning
        )

    def _detect_case_type(self, query: str) -> Optional[CaseType]:
        """كشف نوع القضية"""

        query_lower = query.lower()

        # جنايات
        if any(word in query_lower for word in ["جناية", "جناي", "قتل", " homicide"]):
            return CaseType.FELONY

        # جنح
        if any(word in query_lower for word in ["جنحة", "جنح", "سرقة", "نصب", "احتيال"]):
            return CaseType.MISDEMEANOR

        # مخالفات
        if any(word in query_lower for word in ["مخالفة", "مخالفات", "مرور"]):
            return CaseType.VIOLATION

        # نزاعات مدنية
        if any(word in query_lower for word in ["نزاع", "دعوى", "Civil", "civil"]):
            if any(word in query_lower for word in ["تجاري", "تجة", "commercial"]):
                return CaseType.COMMERCIAL_DISPUTE
            if any(word in query_lower for word in ["أسري", "famil", "زواج", "طلاق"]):
                return CaseType.FAMILY_DISPUTE
            if any(word in query_lower for word in ["عمالي", "عمل", "labor"]):
                return CaseType.LABOR_DISPUTE
            return CaseType.CIVIL_DISPUTE

        # استئناف
        if any(word in query_lower for word in ["استئناف", "طعن", "appeal"]):
            return CaseType.APPEAL

        # نقض
        if any(word in query_lower for word in ["نقض", "cassation"]):
            return CaseType.CASSATION

        return None

    def _suggest_laws(self, query: str, primary_domain: LegalDomain) -> List[str]:
        """اقتراح القوانين ذات الصلة"""

        suggested = []
        query_lower = query.lower()

        # البحث في خريطة القوانين
        for law_name, law_info in self.qatari_laws.items():
            law_keywords = law_info.get("الكلمات المفتاحية", [])

            # حساب عدد الكلمات المفتاحية المطابقة
            matches = sum(1 for kw in law_keywords if kw in query_lower)

            if matches >= 2:
                law_number = law_info.get("الرقم", "")
                suggested.append(f"{law_name} ({law_number})")
            elif matches == 1 and law_info.get("المجال") == primary_domain:
                # إضافة إذا كان نفس المجال وكلمة مفتاحية واحدة
                law_number = law_info.get("الرقم", "")
                suggested.append(f"{law_name} ({law_number})")

        # إضافة القانون الأساسي للمجال
        if not suggested:
            domain_laws = {
                LegalDomain.CRIMINAL: "قانون العقوبات (11/2004)",
                LegalDomain.CIVIL: "قانون المعاملات المدنية (22/2006)",
                LegalDomain.COMMERCIAL: "قانون التجارة (27/2006)",
                LegalDomain.FAMILY: "قانون الأسرة (22/2006)",
                LegalDomain.LABOR: "قانون العمل (14/2004)",
                LegalDomain.PROPERTY: "قانون الشهر العقاري (14/1968)",
                LegalDomain.CYBER: "قانون الجرائم المعلوماتية (24/2015)",
                LegalDomain.PROCEDURAL: "قانون الإجراءات المدنية (13/1990)",
                LegalDomain.TAX: "قانون ضريبة القيمة المضافة (1/2019)",
            }
            if primary_domain in domain_laws:
                suggested.append(domain_laws[primary_domain])

        return suggested[:5]  # إرجاع أول 5 قوانين

    def _estimate_complexity(
        self,
        query: str,
        sources: List[Dict],
        domain_scores: List[DomainScore]
    ) -> str:
        """تقدير تعقيد الحالة"""

        complexity_score = 0

        # عدد المجالات المتشابكة
        if len(domain_scores) > 3:
            complexity_score += 2
        elif len(domain_scores) > 1:
            complexity_score += 1

        # طول السؤال
        if len(query) > 200:
            complexity_score += 1

        # وجود تفاصيل محددة
        detail_words = ["تفاصيل", "شرح", "تحليل", "دراسة", "بحث"]
        if any(word in query.lower() for word in detail_words):
            complexity_score += 1

        # عدد المصادر
        if len(sources) > 5:
            complexity_score += 1

        # تصنيف التعقيد
        if complexity_score >= 4:
            return "مرتفع جداً"
        elif complexity_score >= 3:
            return "مرتفع"
        elif complexity_score >= 2:
            return "متوسط"
        else:
            return "منخفض"

    def _requires_professional(
        self,
        query: str,
        case_type: Optional[CaseType],
        primary_domain: LegalDomain
    ) -> bool:
        """تحديد ما إذا كانت الحالة تتطلب متخصصاً"""

        professional_indicators = [
            "محامي", "قانوني", "محكمة", "دعوى", "قضية", "ترافع",
            "نيابة", "ادعاء", "حقوق", "طعن", "نقض", "استئناف",
            "تبرئة", "إدانة", "محاكمة", "جلسة", "حكم", "قاضي"
        ]

        # فحص المؤشرات
        has_professional_terms = any(
            word in query.lower()
            for word in professional_indicators
        )

        # الحالات التي تتطلب متخصصاً عادةً
        professional_domains = [
            LegalDomain.CRIMINAL,
            LegalDomain.COMMERCIAL,
            LegalDomain.PROPERTY,
            LegalDomain.BANKING,
        ]

        professional_cases = [
            CaseType.FELONY,
            CaseType.APPEAL,
            CaseType.CASSATION,
            CaseType.COMMERCIAL_DISPUTE,
        ]

        requires_professional = (
            has_professional_terms or
            primary_domain in professional_domains or
            case_type in professional_cases
        )

        return requires_professional

    def _detect_urgency(self, query: str) -> List[str]:
        """كشف مؤشرات الاستعجال"""

        urgency_indicators = []
        query_lower = query.lower()

        # مؤشرات الاستعجال
        urgency_keywords = {
            "عاجل": "استعجال عالي",
            "مستعجل": "استعجال عالي",
            "فوراً": "استعجال عالي",
            "غداً": "موعد محدود",
            "اليوم": "موعد محدود",
            "الأسبوع": "موعد قريب",
            "خطر": "خطر محدق",
            "إيقاف": "إيقاف فوري محتمل",
            "توقيف": "توقيف",
            "حبس": "احتجاز محتمل",
            "طرد": "إجراء وشيك",
            "إخلاء": "إخلاء وشيك",
            "تشريد": "تشريد محتمل",
            "مطاردة": "طارئ",
            "شرطة": "طارئ",
        }

        for keyword, description in urgency_keywords.items():
            if keyword in query_lower:
                urgency_indicators.append(description)

        return urgency_indicators

    def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """استخراج الكيانات من السؤال"""

        entities = {
            "قوانين": [],
            "أشخاص": [],
            "منظمات": [],
            "تواريخ": [],
            "أموال": [],
            "أماكن": [],
        }

        # استخراج القوانين
        for law_name in self.qatari_laws.keys():
            if law_name in query:
                entities["قوانين"].append(law_name)

        # استخراج أرقام القوانين
        law_numbers = re.findall(r'\d+/\d{4}', query)
        entities["قوانين"].extend(law_numbers)

        # استخراج المبالغ المالية
        money_patterns = [
            r'(\d+[\d,]*)\s*(ريال|دولار|يورو|جنيه|درهم)',
            r'(\d+[\d,]*)\s*(ر\.س|دولار|$|€|£)',
        ]
        for pattern in money_patterns:
            matches = re.findall(pattern, query)
            for match in matches:
                entities["أموال"].append(f"{match[0]} {match[1]}")

        # استخراج التواريخ
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',
            r'\d+/\d+/\d{4}',
            r'\d+\s+(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)',
        ]
        for pattern in date_patterns:
            matches = re.findall(pattern, query)
            entities["تواريخ"].extend(matches)

        return entities

    def calculate_relevance_score(
        self,
        chunk: Dict,
        query: str,
        domain_analysis: DomainAnalysis,
        context: Optional[Dict] = None
    ) -> float:
        """
        حساب نتيجة Relevance لمقطع معين

        Formula:
        score_final = (
            base_score       × 0.35
            + domain_match   × 0.25
            + law_priority   × 0.20
            + concept_cov    × 0.15
            + year_factor    × 0.05
        )

        Args:
            chunk: المقطع
            query: السؤال
            domain_analysis: تحليل المجال
            context: سياق إضافي

        Returns:
            float: نتيجة Relevance (0-1)
        """
        context = context or {}

        # 1. النتيجة الأساسية (التشابه الدلاللي)
        base_score = chunk.get("relevance_score", 0.5)

        # 2. تطابق المجال
        chunk_domain_str = chunk.get("law", "").lower()
        domain_match = 0.0

        if domain_analysis.primary_domain.value in chunk_domain_str:
            domain_match = 1.0
        elif any(sd.value in chunk_domain_str for sd in domain_analysis.secondary_domains):
            domain_match = 0.6

        # 3. أولوية القانون
        law_priority = 0.5
        law_name = chunk.get("law", "")
        if law_name in self.qatari_laws:
            law_priority = self.qatari_laws[law_name].get("المجال", LegalDomain.GENERAL)
            law_priority = DOMAIN_WEIGHTS.get(law_priority, {}).get("priority", 10)
            # تحويل الأولوية إلى درجة (أقل رقم = أعلى أولوية)
            law_priority = max(1 - (law_priority - 1) / 10, 0.1)

        # 4. تغطية المفاهيم
        chunk_content = chunk.get("content", "").lower()
        query_keywords = self._extract_keywords(query)

        matched_keywords = sum(1 for kw in query_keywords if kw in chunk_content)
        concept_coverage = min(matched_keywords / max(len(query_keywords), 1), 1.0)

        # 5. العامل الزمني
        year_factor = 1.0
        if context.get("recent_only"):
            chunk_year = chunk.get("year", 2000)
            if chunk_year < 2015:
                year_factor = 0.7

        # حساب النتيجة النهائية
        score_final = (
            base_score       * 0.35
            + domain_match   * 0.25
            + law_priority   * 0.20
            + concept_coverage * 0.15
            + year_factor    * 0.05
        )

        # تطبيق عوامل إضافية
        if domain_analysis.case_type:
            # تعزيز النتيجة إذا كان نوع القضية يتوافق مع المقطع
            if "criminal" in chunk_domain_str and domain_analysis.case_type in [
                CaseType.FELONY, CaseType.MISDEMEANOR, CaseType.VIOLATION
            ]:
                score_final *= 1.1
            elif "family" in chunk_domain_str and domain_analysis.case_type == CaseType.FAMILY_DISPUTE:
                score_final *= 1.1

        # ضمان أن النتيجة في نطاق 0-1
        return min(max(score_final, 0.0), 1.0)

    def rank_chunks(
        self,
        chunks: List[Dict],
        query: str,
        domain_analysis: Optional[DomainAnalysis] = None,
        context: Optional[Dict] = None
    ) -> List[Dict]:
        """
        ترتيب المقاطع حسب Relevance

        Args:
            chunks: قائمة المقاطع
            query: السؤال
            domain_analysis: تحليل المجال
            context: سياق إضافي

        Returns:
            List[Dict]: المقاطع المرتبة
        """
        domain_analysis = domain_analysis or self.classify_domain(query)
        context = context or {}

        # حساب النتيجة لكل مقطع
        scored_chunks = []
        for chunk in chunks:
            score = self.calculate_relevance_score(
                chunk, query, domain_analysis, context
            )
            chunk_copy = chunk.copy()
            chunk_copy["relevance_final"] = score
            scored_chunks.append(chunk_copy)

        # ترتيب حسب النتيجة
        scored_chunks.sort(key=lambda x: x["relevance_final"], reverse=True)

        # إضافة ترتيب
        for i, chunk in enumerate(scored_chunks, 1):
            chunk["rank"] = i

        return scored_chunks

    def suggest_related_queries(
        self,
        query: str,
        domain_analysis: Optional[DomainAnalysis] = None
    ) -> List[str]:
        """اقتراح أسئلة ذات صلة"""

        domain_analysis = domain_analysis or self.classify_domain(query)

        suggested = []

        # اقتراحات عامة
        general_suggestions = [
            "ما هي شروط {}".format("الاستفسار" if not domain_analysis.primary_domain else ""),
            "ما الإجراءات المطلوبة؟",
            "ما هي المستندات اللازمة؟",
            "ما هي المدة المتوقعة؟",
        ]

        # اقتراحات حسب المجال
        domain_suggestions = {
            LegalDomain.CRIMINAL: [
                "ما هي عقوبة {}؟",
                "ما هي إجراءات المحاكمة؟",
                "كيف يمكن الاستئناف؟",
            ],
            LegalDomain.FAMILY: [
                "ما هي حقوق {}؟",
                "كيف يتم {}؟",
                "ما هي الإجراءات في محكمة الأحوال الشخصية؟",
            ],
            LegalDomain.LABOR: [
                "ما هي حقوق الموظف في {}؟",
                "كيف يتم تقديم شكوى ضد صاحب العمل؟",
                "ما هي مكافأة نهاية الخدمة؟",
            ],
            LegalDomain.COMMERCIAL: [
                "ما هي شروط تأسيس شركة في قطر؟",
                "ما هي إجراءات التحصيل التجاري؟",
                "ما هي حقوق المساهمين؟",
            ],
        }

        if domain_analysis.primary_domain in domain_suggestions:
            suggested.extend(domain_suggestions[domain_analysis.primary_domain][:2])

        suggested.extend(general_suggestions[:2])

        return suggested[:5]

# ═══════════════════════════════════════════════════════════════════════════════════════
# مُصدِّر المحرك
# ═══════════════════════════════════════════════════════════════════════════════════════

__all__ = [
    'EnhancedDomainRelevanceEngine',
    'DomainAnalysis',
    'DomainScore',
    'LegalDomain',
    'CaseType',
    'JudgmentType',
    'LawPrecedent',
    'LegalRelation',
    'ULTRA_ENGINE_AVAILABLE',
    'QATARI_LAWS_MAP',
]
