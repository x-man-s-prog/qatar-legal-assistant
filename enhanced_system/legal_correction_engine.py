# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                    ║
║         🚀 محرك التصحيح القانوني المتقدم - MAX Edition                            ║
║         Advanced Legal Correction Engine - MAX Edition                             ║
║                                                                                    ║
║  الميزات المتقدمة:                                                                 ║
║  • التحقق من اتساق الإجابات القانونية                                              ║
║  • كشف وتحذير من المعلومات غير الدقيقة                                           ║
║  • التحقق من صحة الاقتباسات القانونية                                             ║
║  • كشف الغموض والتناقضات                                                          ║
║  • تصحيح الأخطاء الأسلوبية واللغوية                                              ║
║                                                                                    ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

الإصدار: 2.0-MAX
التاريخ: 2024
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════════════
# أنواع البيانات والقوائم
# ═══════════════════════════════════════════════════════════════════════════════════════

class CorrectionType(Enum):
    """أنواع التصحيح"""
    ACCURACY = "دقة"                    # تصحيح دقة المعلومات
    CONSISTENCY = "اتساق"                # تصحيح الاتساق الداخلي
    CITATION = "اقتباس"                  # تصحيح الاقتباسات القانونية
    CLARITY = "وضوح"                     # تصحيح الوضوح والغموض
    TERMINOLOGY = "مصطلحات"              # تصحيح المصطلحات القانونية
    GRAMMAR = "لغة"                      # تصحيح اللغة والأسلوب
    COMPLETENESS = "اكتمال"              # تصحيح الاكتمال

class SeverityLevel(Enum):
    """مستويات الخطورة"""
    CRITICAL = "حرج"      # خطأ جسيم قد يؤدي إلى معلومات خاطئة
    HIGH = "عالي"         # خطأ مهم يجب تصحيحه
    MEDIUM = "متوسط"      # تصحيح مستحسن
    LOW = "منخفض"         # تحسين طفيف

class ConfidenceLevel(Enum):
    """مستويات الثقة"""
    HIGH = "عالي"         # > 0.8
    MEDIUM = "متوسط"      # 0.5 - 0.8
    LOW = "منخفض"         # < 0.5

# ═══════════════════════════════════════════════════════════════════════════════════════
# نماذج البيانات
# ═══════════════════════════════════════════════════════════════════════════════════════

@dataclass
class LegalReference:
    """مرجع قانوني"""
    law_name: str
    article_number: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    text_snippet: Optional[str] = None
    confidence: float = 0.0

@dataclass
class CorrectionItem:
    """عنصر تصحيح"""
    correction_type: CorrectionType
    severity: SeverityLevel
    original_text: str
    corrected_text: str
    reason: str
    location: str
    confidence: float = 0.0
    suggestion: str = ""
    requires_verification: bool = False

@dataclass
class CorrectionReport:
    """تقرير التصحيح"""
    total_issues: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    corrections: List[CorrectionItem] = field(default_factory=list)
    overall_quality_score: float = 0.0
    needs_verification: bool = False
    recommendations: List[str] = field(default_factory=list)
    timestamp: str = ""

@dataclass
class VerificationResult:
    """نتيجة التحقق"""
    is_verified: bool
    confidence: float
    source_matches: List[str] = field(default_factory=list)
    mismatches: List[str] = field(default_factory=list)
    notes: str = ""

# ═══════════════════════════════════════════════════════════════════════════════════════
# قاموس المصطلحات القانونية القطرية
# ═══════════════════════════════════════════════════════════════════════════════════════

QATARI_LEGAL_TERMS = {
    # قانون الإجراءات الجنائية
    "نيابة عامة": ["النيابة العامة", "المدعي العام", "النيابه العامه"],
    "محكمة": ["المحكمة", "محكمه", "ال محكمة"],
    "قاض": ["القاضي", "القاضي", "ال قاض"],
    "جلسة": ["الجلسة", "جلسة", "الجلسه"],
    "حكم": ["الحكم", "احكام", "ال حكم"],
    "طعن": ["الطعن", "طعن", "التطعين"],

    # القانون المدني
    "عقد": ["العقد", "عقد", "الاتفاق"],
    "طرف": ["الطرف", "اطراف", "الاطراف"],
    "التزام": ["الالتزام", "التزامات", "التزام"],
    "حق": ["الحق", "حقوق", "ال حق"],
    "التزام": ["الالتزام", "التزامات", "التزام"],
    "تعويض": ["التعويض", "تعويضات", "تعويض"],
    "نفقة": ["النفقة", "نفقه", "النفقه"],

    # القانون التجاري
    "شركة": ["الشركة", "شركه", "ال شركة"],
    "تجاري": ["التجاري", "تجاري", "التجاريه"],
    "سوق": ["السوق", "سوق", "ال سوق"],
    "سهم": ["السهم", "سهم", "ال سهم"],

    # قانون العمل
    "موظف": ["الموظف", "موظف", "ال موظف"],
    "صاحب عمل": ["صاحب العمل", "صاحب عمل", "اصحاب العمل"],
    "إجازة": ["الإجازة", "اجازه", "الاجازه"],
    "إنهاء": ["الإنهاء", "انهاء", "الانهاء"],

    # قانون الأسرة
    "زواج": ["الزواج", "زواج", "الزواج"],
    "طلاق": ["الطلاق", "طلاق", "الطلاق"],
    "حضانة": ["الحضانة", "حضانه", "الحضانه"],
    "ولاية": ["الولاية", "ولايه", "الولايه"],

    # المصطلحات القانونية العامة
    "مستند": ["المستند", "مستند", "ال مستند"],
    "إثبات": ["الإثبات", "اثبات", "الاثبات"],
    "دليل": ["الدليل", "دليل", "ال دليل"],
    "شهادة": ["الشهادة", "شهاده", "الشهاده"],
    "يمين": ["اليمين", "يمين", "اليمين"],
    "إقرار": ["الإقرار", "اقرار", "الاقرار"],
    "مهلة": ["المهلة", "مهله", "المهله"],
    "أجل": ["الأجل", "اجل", "الاجل"],
    "فسخ": ["الفسخ", "فسخ", "الفسخ"],
    "إلغاء": ["الإلغاء", "الغاء", "الالغاء"],
    "تعديل": ["التعديل", "تعديل", "التعديل"],
    "مخالفة": ["المخالفة", "مخالفه", "المخالفه"],
    "جنحة": ["الجنحة", "جنحه", "الجنحه"],
    "جريمة": ["الجريمة", "جريمه", "الجريمه"],
    "عقوبة": ["العقوبة", "عقوبه", "العقوبه"],
    "سجن": ["السجن", "سجن", "السجن"],
    "غرامة": ["الغرامة", "غرامه", "الغرامه"],
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# قاموس الكلمات المتضاربة
# ═══════════════════════════════════════════════════════════════════════════════════════

CONTRADICTORY_PAIRS = {
    ("مسموح", "ممنوع"): ["يُسمح", "يُرجى", "يُنصح"],
    ("مسموح", "غير مسموح"): ["يُسمح", "غير مسموح", "ممنوع"],
    (" legal", "illegal"): ["قانوني", "غير قانوني", "مشروع", "غير مشروع"],
    ("دائماً", "أحياناً"): ["دائماً", "أحياناً", "نادراً", " دائماً"],
    ("يجب", "يمكن"): ["يجب", "يجب علي", "يلزم", "يمكن", "مسموح"],
    ("قبل", "بعد"): ["قبل", "بعد", "أثناء", "خلال"],
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# أنماط الاقتباسات القانونية
# ═══════════════════════════════════════════════════════════════════════════════════════

CITATION_PATTERNS = [
    # المادة X من القانون Y
    r'(?:المادة|مواد|مادة)\s*(\d+)\s*(?:من|في)\s*(?:قانون|القانون)?\s*([^\n,\d]{3,50})',
    # قانون رقم X
    r'(?:قانون|لقانون)\s*(?:رقم\s*)?(\d+)\s*(?:لسنة|لكتاب)?\s*(\d{4})?',
    # المرسوم بقانون رقم X
    r'(?:مرسوم\s*بقانون)\s*(?:رقم\s*)?(\d+)\s*(?:لسنة)?\s*(\d{4})?',
    # القرار رقم X
    r'(?:قرار|لقرار)\s*(?:رقم\s*)?(\d+)\s*(?:لسنة)?\s*(\d{4})?',
    # الباب/الفصل
    r'(?:الباب|الفصل|القسم)\s*([\dؤأ-]+)\s*(?:من|في)',
    # القانون رقم ...
    r'(?:القانون)\s*(?:رقم)?\s*(\d+)',
]

# ═══════════════════════════════════════════════════════════════════════════════════════
# محرك التصحيح القانوني المتقدم
# ═══════════════════════════════════════════════════════════════════════════════════════

class LegalCorrectionEngine:
    """
    محرك التصحيح القانوني المتقدم - MAX Edition

    الميزات:
    - التحقق من دقة المعلومات القانونية
    - كشف الاقتباسات القانونية الخاطئة
    - التحقق من الاتساق الداخلي
    - كشف الغموض والتناقضات
    - تصحيح المصطلحات القانونية
    - تقييم جودة الإجابة القانونية
    """

    def __init__(self):
        """تهيئة محرك التصحيح"""
        self.legal_terms = QATARI_LEGAL_TERMS
        self.citation_patterns = CITATION_PATTERNS
        self.correction_cache = {}

        # تهيئة قوائم الكلمات المتضاربة
        self.contradiction_pairs = CONTRADICTORY_PAIRS

    def correct(
        self,
        response: str,
        query: str,
        sources: List[Dict],
        context: Optional[Dict] = None
    ) -> Tuple[str, CorrectionReport]:
        """
        تصحيح الإجابة القانونية

        Args:
            response: الإجابة المُولّدة
            query: السؤال الأصلي
            sources: المصادر القانونية
            context: سياق إضافي

        Returns:
            Tuple[str, CorrectionReport]: الإجابة المُصحّحة وتقرير التصحيح
        """
        context = context or {}
        report = CorrectionReport(timestamp=datetime.now().isoformat())

        # تحليل الإجابة
        issues = []

        # 1. التحقق من الدقة
        accuracy_issues = self._check_accuracy(response, sources)
        issues.extend(accuracy_issues)

        # 2. التحقق من الاتساق
        consistency_issues = self._check_consistency(response)
        issues.extend(consistency_issues)

        # 3. التحقق من الاقتباسات القانونية
        citation_issues = self._check_citations(response, sources)
        issues.extend(citation_issues)

        # 4. التحقق من الوضوح
        clarity_issues = self._check_clarity(response)
        issues.extend(clarity_issues)

        # 5. التحقق من المصطلحات القانونية
        terminology_issues = self._check_terminology(response)
        issues.extend(terminology_issues)

        # 6. التحقق من الاكتمال
        completeness_issues = self._check_completeness(response, query, sources)
        issues.extend(completeness_issues)

        # ترتيب التصحيحات حسب الخطورة
        issues.sort(key=lambda x: self._severity_to_int(x.severity), reverse=True)

        # إنشاء تقرير التصحيح
        report.corrections = issues
        report.total_issues = len(issues)
        report.critical_count = sum(1 for i in issues if i.severity == SeverityLevel.CRITICAL)
        report.high_count = sum(1 for i in issues if i.severity == SeverityLevel.HIGH)
        report.medium_count = sum(1 for i in issues if i.severity == SeverityLevel.MEDIUM)
        report.low_count = sum(1 for i in issues if i.severity == SeverityLevel.LOW)
        report.needs_verification = any(c.requires_verification for c in issues)

        # حساب درجة الجودة
        report.overall_quality_score = self._calculate_quality_score(report)

        # توليد التوصيات
        report.recommendations = self._generate_recommendations(report, context)

        # تطبيق التصحيحات
        corrected_response = self._apply_corrections(response, issues)

        return corrected_response, report

    def _severity_to_int(self, severity: SeverityLevel) -> int:
        """تحويل مستوى الخطورة إلى رقم للترتيب"""
        mapping = {
            SeverityLevel.CRITICAL: 4,
            SeverityLevel.HIGH: 3,
            SeverityLevel.MEDIUM: 2,
            SeverityLevel.LOW: 1,
        }
        return mapping.get(severity, 0)

    def _check_accuracy(
        self,
        response: str,
        sources: List[Dict]
    ) -> List[CorrectionItem]:
        """التحقق من دقة المعلومات"""
        issues = []

        # استخراج المعلومات من المصادر
        source_texts = self._extract_source_texts(sources)

        # البحث عن معلومات قد تكون غير دقيقة
        for source in sources:
            source_text = source.get("content", "")
            source_law = source.get("law", "")
            source_article = source.get("article", "")

            # التحقق من وجود تناقض مع المصدر
            if source_text:
                # البحث عن عبارات تناقض
                contradictions = self._find_contradictions(response, source_text)
                for contradiction in contradictions:
                    issues.append(CorrectionItem(
                        correction_type=CorrectionType.ACCURACY,
                        severity=SeverityLevel.HIGH,
                        original_text=contradiction["text"],
                        corrected_text=contradiction["suggested"],
                        reason=f"يتناقض مع {source_law} - مادة {source_article}",
                        location=contradiction["location"],
                        confidence=0.85,
                        suggestion="راجع المصدر القانوني للتأكد من الدقة",
                        requires_verification=True
                    ))

        return issues

    def _extract_source_texts(self, sources: List[Dict]) -> List[str]:
        """استخراج النصوص من المصادر"""
        texts = []
        for source in sources:
            content = source.get("content", "")
            if content:
                texts.append(content)
        return texts

    def _find_contradictions(
        self,
        response: str,
        source_text: str
    ) -> List[Dict]:
        """البحث عن التناقضات"""
        contradictions = []

        # البحث عن عبارات مثل "لا يمكن" بينما المصدر يقول "يمكن"
        negative_patterns = [
            (r'لا\s+يمكن', r'يمكن'),
            (r'ممنوع', r'مسموح'),
            (r'غير\s+قانوني', r'قانوني'),
            (r'لا\s+يجب', r'يجب'),
        ]

        for neg_pattern, pos_pattern in negative_patterns:
            if re.search(neg_pattern, response) and re.search(pos_pattern, source_text):
                match = re.search(neg_pattern, response)
                if match:
                    contradictions.append({
                        "text": match.group(0),
                        "suggested": pos_pattern,
                        "location": f"حرف {match.start()}",
                        "type": "contradiction"
                    })

        return contradictions

    def _check_consistency(self, response: str) -> List[CorrectionItem]:
        """التحقق من الاتساق الداخلي"""
        issues = []

        # التحقق من استخدام المصطلحات بشكل متسق
        # جمع جميع المصطلحات القانونية المستخدمة
        used_terms = {}
        for term, variants in self.legal_terms.items():
            for variant in variants:
                if variant in response:
                    if term not in used_terms:
                        used_terms[term] = []
                    used_terms[term].append(variant)

        # التحقق من عدم استخدام مصطلحات متناقضة
        # مثل استخدام "النفقة" و "المصروفات" بشكل متبادل
        for term, variants in self.legal_terms.items():
            used_variants = [v for v in variants if v in response]
            if len(used_variants) > 1:
                # استخدام أكثر من متغير لنفس المصطلح
                issues.append(CorrectionItem(
                    correction_type=CorrectionType.CONSISTENCY,
                    severity=SeverityLevel.MEDIUM,
                    original_text=", ".join(used_variants[:2]),
                    corrected_text=variants[0],  # استخدام المتغير الأساسي
                    reason="استخدام غير متسق للمصطلح القانوني",
                    location="استخدام المصطلحات",
                    confidence=0.75,
                    suggestion=f"استخدم '{variants[0]}' بشكل متسق"
                ))

        # التحقق من الاتساق في الأرقام والتواريخ
        date_pattern = r'\d{4}'
        dates = re.findall(date_pattern, response)
        if len(dates) > 1:
            # التحقق من عدم وجود تواريخ متناقضة
            if "2024" in dates and "2025" in dates:
                # قد يكون هذا تناقضاً
                issues.append(CorrectionItem(
                    correction_type=CorrectionType.CONSISTENCY,
                    severity=SeverityLevel.LOW,
                    original_text="تواريخ متفاوتة",
                    corrected_text="توحيد التاريخ",
                    reason="توجد تواريخ مختلفة في الإجابة",
                    location="التواريخ",
                    confidence=0.6,
                    suggestion="تأكد من اتساق التواريخ"
                ))

        return issues

    def _check_citations(
        self,
        response: str,
        sources: List[Dict]
    ) -> List[CorrectionItem]:
        """التحقق من الاقتباسات القانونية"""
        issues = []

        # استخراج جميع الاقتباسات من الإجابة
        citations_in_response = self._extract_citations(response)

        # التحقق من وجود كل اقتباس في المصادر
        source_laws = set(s.get("law", "") for s in sources if s.get("law"))
        source_articles = set(s.get("article", "") for s in sources if s.get("article"))

        for citation in citations_in_response:
            # التحقق من القانون
            if citation.get("law"):
                citation_law = citation["law"]
                if citation_law not in source_laws:
                    issues.append(CorrectionItem(
                        correction_type=CorrectionType.CITATION,
                        severity=SeverityLevel.HIGH,
                        original_text=f"{citation_law}",
                        corrected_text="",
                        reason="القانون المذكور غير موجود في المصادر",
                        location=citation.get("location", ""),
                        confidence=0.8,
                        suggestion="تحقق من صحة القانون المذكور",
                        requires_verification=True
                    ))

            # التحقق من المادة
            if citation.get("article"):
                citation_article = citation["article"]
                if citation_article not in source_articles:
                    issues.append(CorrectionItem(
                        correction_type=CorrectionType.CITATION,
                        severity=SeverityLevel.MEDIUM,
                        original_text=f"مادة {citation_article}",
                        corrected_text="",
                        reason="المادة المذكورة غير موجودة في المصادر",
                        location=citation.get("location", ""),
                        confidence=0.7,
                        suggestion="تحقق من صحة رقم المادة",
                        requires_verification=True
                    ))

        # التحقق من صحة تنسيق الاقتباسات
        citation_text = " ".join([c.get("text", "") for c in citations_in_response])
        if citation_text:
            # التحقق من عدم وجود اقتباسات فارغة
            empty_citations = [c for c in citations_in_response if not c.get("text")]
            if empty_citations:
                issues.append(CorrectionItem(
                    correction_type=CorrectionType.CITATION,
                    severity=SeverityLevel.MEDIUM,
                    original_text="اقتباسات بدون نص",
                    corrected_text="",
                    reason="يوجد اقتباسات بدون نص مرجعي",
                    location="الاقتباسات",
                    confidence=0.6,
                    suggestion="أضف نص الاقتباس المرجعي"
                ))

        return issues

    def _extract_citations(self, text: str) -> List[Dict]:
        """استخراج الاقتباسات من النص"""
        citations = []

        for pattern in self.citation_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                citation = {
                    "law": "",
                    "article": "",
                    "text": "",
                    "location": f"حرف {match.start()}"
                }

                groups = match.groups()
                if len(groups) >= 1:
                    # قد يكون رقم المادة أو القانون
                    if "مادة" in match.group(0).lower():
                        citation["article"] = groups[0]
                    else:
                        citation["law"] = groups[0]

                if len(groups) >= 2:
                    citation["law"] = groups[1] if not citation.get("law") else citation["law"]

                citations.append(citation)

        # البحث عن أنماط إضافية
        article_pattern = r'(?:المادة|مواد)\s*(\d+)'
        article_matches = re.finditer(article_pattern, text)
        for match in article_matches:
            existing = False
            for c in citations:
                if c.get("article") == match.group(1):
                    existing = True
                    break
            if not existing:
                citations.append({
                    "article": match.group(1),
                    "law": "",
                    "text": "",
                    "location": f"حرف {match.start()}"
                })

        return citations

    def _check_clarity(self, response: str) -> List[CorrectionItem]:
        """التحقق من الوضوح"""
        issues = []

        # كشف الغموض
        vague_terms = [
            "شيء", "شخص", "مكان", "زمن", "سبب",
            "بعض", "أي", "قد", "ربما", "يمكن",
            "ربما", "يبدو", "غير واضح"
        ]

        for term in vague_terms:
            pattern = rf'\b{re.escape(term)}\b'
            matches = list(re.finditer(pattern, response))
            if len(matches) > 2:
                # استخدام مفرط للمصطلح الغامض
                issues.append(CorrectionItem(
                    correction_type=CorrectionType.CLARITY,
                    severity=SeverityLevel.MEDIUM,
                    original_text=term,
                    corrected_text="",
                    reason=f"استخدام مفرط للمصطلح الغامض '{term}'",
                    location=f"تكرار {len(matches)} مرات",
                    confidence=0.7,
                    suggestion=f"حدد '{term}' بشكل أوضح أو استخدم مصطلحاً أكثر دقة"
                ))

        # كشف المعلومات الناقصة
        incomplete_patterns = [
            r'(?:يجب|يلزم|يمكن|يُرجى)\s+[^\.]*$',  # جمل غير مكتملة
            r'\.\.\.$',  # نقط في النهاية
        ]

        for pattern in incomplete_patterns:
            matches = list(re.finditer(pattern, response))
            if matches:
                issues.append(CorrectionItem(
                    correction_type=CorrectionType.COMPLETENESS,
                    severity=SeverityLevel.LOW,
                    original_text="جمل غير مكتملة",
                    corrected_text="",
                    reason="يوجد جمل غير مكتملة في الإجابة",
                    location=f"{len(matches)} جملة",
                    confidence=0.6,
                    suggestion="أتمم الجمل الناقصة"
                ))

        return issues

    def _check_terminology(self, response: str) -> List[CorrectionItem]:
        """التحقق من المصطلحات القانونية"""
        issues = []

        # المصطلحات الشائعة الخاطئة في السياق القطري
        incorrect_terms = {
            "محكمة": ["المحكمه", "محكمه"],  # خطأ إملائي
            "مستندات": ["مستندات", "المستندات"],  # حالة الكلمة
            "الإثبات": ["الاثبات", "اثبات"],  # التشكيل
            "القانون": ["القانن", "القانون"],  # خطأ في التهجئة
            "المادة": ["الماده", "ماده"],  # التشكيل
        }

        for correct_term, incorrect_versions in incorrect_terms.items():
            for incorrect in incorrect_versions:
                if incorrect in response:
                    issues.append(CorrectionItem(
                        correction_type=CorrectionType.TERMINOLOGY,
                        severity=SeverityLevel.LOW,
                        original_text=incorrect,
                        corrected_text=correct_term,
                        reason=f"استخدام غير صحيح للمصطلح '{incorrect}'",
                        location="المصطلحات القانونية",
                        confidence=0.8,
                        suggestion=f"الصيغة الصحيحة: '{correct_term}'"
                    ))

        # التحقق من استخدام المصطلحات العامية بدلاً من القانونية
        colloquial_terms = {
            "فلوس": "أموال",
            "شغل": "عمل",
            "حرامي": "مجرم",
            "شرطيات": "قوات أمنية",
            "قضاية": "قضاء",
            "حقو": "حقوق",
            "لازم": "يجب",
        }

        for colloquial, formal in colloquial_terms.items():
            if colloquial in response:
                issues.append(CorrectionItem(
                    correction_type=CorrectionType.TERMINOLOGY,
                    severity=SeverityLevel.MEDIUM,
                    original_text=colloquial,
                    corrected_text=formal,
                    reason=f"استخدام مصطلح عامي '{colloquial}' في سياق قانوني",
                    location="المصطلحات",
                    confidence=0.85,
                    suggestion=f"استخدم المصطلح القانوني '{formal}'"
                ))

        return issues

    def _check_completeness(
        self,
        response: str,
        query: str,
        sources: List[Dict]
    ) -> List[CorrectionItem]:
        """التحقق من الاكتمال"""
        issues = []

        # التحقق من وجود مصادر
        if not sources and len(response) > 200:
            issues.append(CorrectionItem(
                correction_type=CorrectionType.COMPLETENESS,
                severity=SeverityLevel.HIGH,
                original_text="بدون مصادر",
                corrected_text="",
                reason="إجابة طويلة بدون مصادر قانونية",
                location="المصادر",
                confidence=0.9,
                suggestion="أضف مصادر قانونية موثوقة لدعم المعلومات",
                requires_verification=True
            ))

        # التحقق من طول الإجابة مقارنة بتعقيد السؤال
        query_complexity = self._estimate_query_complexity(query)
        response_length = len(response)

        if query_complexity == "high" and response_length < 500:
            issues.append(CorrectionItem(
                correction_type=CorrectionType.COMPLETENESS,
                severity=SeverityLevel.MEDIUM,
                original_text=f"إجابة قصيرة ({response_length} حرف)",
                corrected_text="",
                reason="السؤال معقد والإجابة قصيرة جداً",
                location="الطول",
                confidence=0.75,
                suggestion="قدم إجابة أكثر تفصيلاً"
            ))

        # التحقق من وجود معلومات أساسية
        required_info = ["المادة", "القانون", "حق", "واجب"]
        missing_info = [info for info in required_info if info not in response]
        if missing_info and sources:
            issues.append(CorrectionItem(
                correction_type=CorrectionType.COMPLETENESS,
                severity=SeverityLevel.LOW,
                original_text=", ".join(missing_info),
                corrected_text="",
                reason="معلومات قانونية أساسية مفقودة",
                location="المحتوى",
                confidence=0.6,
                suggestion="أضف معلومات قانونية أساسية (المادة، القانون، إلخ)"
            ))

        return issues

    def _estimate_query_complexity(self, query: str) -> str:
        """تقدير تعقيد السؤال"""
        complexity_indicators = {
            "high": ["تحليل", "شرح", "تفصيل", "مقارنة", "بين"],
            "medium": ["ما هو", "ما هي", "كيف", "متى"],
            "low": ["نعم", "لا", "هل"]
        }

        query_lower = query.lower()
        scores = {}

        for level, indicators in complexity_indicators.items():
            scores[level] = sum(1 for ind in indicators if ind in query_lower)

        max_score = max(scores.values())
        if max_score == 0:
            return "low"

        for level, score in scores.items():
            if score == max_score:
                return level

        return "low"

    def _calculate_quality_score(self, report: CorrectionReport) -> float:
        """حساب درجة الجودة"""
        if report.total_issues == 0:
            return 1.0

        # وزن التصحيحات حسب الخطورة
        weights = {
            SeverityLevel.CRITICAL: 0.4,
            SeverityLevel.HIGH: 0.25,
            SeverityLevel.MEDIUM: 0.15,
            SeverityLevel.LOW: 0.05,
        }

        total_weight = 0
        weighted_sum = 0

        for correction in report.corrections:
            weight = weights.get(correction.severity, 0.1)
            total_weight += weight
            weighted_sum += weight * (1 - correction.confidence)

        if total_weight == 0:
            return 1.0

        score = 1.0 - (weighted_sum / total_weight)
        return max(0.0, min(1.0, score))

    def _generate_recommendations(
        self,
        report: CorrectionReport,
        context: Dict
    ) -> List[str]:
        """توليد التوصيات"""
        recommendations = []

        if report.critical_count > 0:
            recommendations.append(
                f"⚠️ يوجد {report.critical_count} خطأ جسيم - يرجى المراجعة قبل الإرسال"
            )

        if report.high_count > 0:
            recommendations.append(
                f"🔴 يوجد {report.high_count} خطأ مهم يجب تصحيحه"
            )

        if report.needs_verification:
            recommendations.append(
                "✓ بعض المعلومات تحتاج تحقق من المصادر القانونية"
            )

        if report.overall_quality_score >= 0.8:
            recommendations.append(
                "✅ جودة الإجابة جيدة - يمكن الاعتماد عليها"
            )
        elif report.overall_quality_score >= 0.5:
            recommendations.append(
                "⚡ جودة الإجابة متوسطة - يُنصح بالمراجعة"
            )
        else:
            recommendations.append(
                "❌ جودة الإجابة منخفضة - يرجى إعادة الصياغة"
            )

        if report.medium_count > report.high_count:
            recommendations.append(
                "💡 يمكن تحسين الإجابة بتوضيح بعض النقاط"
            )

        return recommendations

    def _apply_corrections(
        self,
        response: str,
        corrections: List[CorrectionItem]
    ) -> str:
        """تطبيق التصحيحات على الإجابة"""
        corrected = response

        # ترتيب التصحيحات حسب الموقع (عكسياً للتطبيق الصحيح)
        #，这样才能正确替换
        sorted_corrections = sorted(
            corrections,
            key=lambda x: int(x.location.split()[1]) if x.location.startswith("حرف") else 0,
            reverse=True
        )

        for correction in sorted_corrections:
            # تطبيق فقط التصحيحات ذات الثقة العالية
            if correction.confidence >= 0.8 and correction.corrected_text:
                # البحث عن النص الأصلي واستبداله
                if correction.original_text in corrected:
                    corrected = corrected.replace(
                        correction.original_text,
                        correction.corrected_text,
                        1
                    )

        return corrected

    def verify_citation(
        self,
        law_name: str,
        article_number: str,
        sources: List[Dict]
    ) -> VerificationResult:
        """التحقق من صحة اقتباس قانوني"""

        # البحث عن المصدر المطابق
        matching_sources = []
        mismatches = []

        for source in sources:
            source_law = source.get("law", "")
            source_article = source.get("article", "")

            if law_name and article_number:
                # التحقق من التطابق الكامل
                if (law_name in source_law or source_law in law_name) and \
                   (article_number == source_article or
                    f"مادة {article_number}" in source.get("content", "")):
                    matching_sources.append(source.get("title", ""))
                else:
                    if source_law or source_article:
                        mismatches.append(f"{source_law} - {source_article}")

            elif law_name:
                if law_name in source_law or source_law in law_name:
                    matching_sources.append(source.get("title", ""))

            elif article_number:
                if article_number == source_article or \
                   f"مادة {article_number}" in source.get("content", ""):
                    matching_sources.append(source.get("title", ""))

        # تحديد نتيجة التحقق
        is_verified = len(matching_sources) > 0
        confidence = len(matching_sources) / max(len(sources), 1) if sources else 0.0

        notes = ""
        if is_verified:
            notes = f"تم العثور على {len(matching_sources)} مصادر مطابقة"
        else:
            notes = "لم يتم العثور على مصادر مطابقة - يرجى التحقق من صحة الاقتباس"

        return VerificationResult(
            is_verified=is_verified,
            confidence=confidence,
            source_matches=matching_sources,
            mismatches=mismatches,
            notes=notes
        )

    def generate_correction_summary(self, report: CorrectionReport) -> str:
        """توليد ملخص التصحيحات"""

        summary = "## 📋 تقرير التصحيح القانوني\n\n"

        # الملخص العام
        summary += f"### الملخص العام\n"
        summary += f"- **إجمالي المشكلات:** {report.total_issues}\n"
        summary += f"- **درجة الجودة:** {report.overall_quality_score:.0%}\n"
        summary += f"- **تحتاج تحقق:** {'نعم' if report.needs_verification else 'لا'}\n\n"

        # توزيع المشكلات حسب الخطورة
        summary += f"### توزيع المشكلات\n"
        summary += f"- 🔴 حرجة: {report.critical_count}\n"
        summary += f"- 🟠 عالية: {report.high_count}\n"
        summary += f"- 🟡 متوسطة: {report.medium_count}\n"
        summary += f"- ⚪ منخفضة: {report.low_count}\n\n"

        # التوصيات
        if report.recommendations:
            summary += f"### التوصيات\n"
            for rec in report.recommendations:
                summary += f"- {rec}\n"

        # التصحيحات التفصيلية
        if report.corrections:
            summary += f"\n### التصحيحات التفصيلية\n"
            for i, correction in enumerate(report.corrections[:10], 1):
                summary += f"\n**{i}. {correction.correction_type.value}** ({correction.severity.value})\n"
                summary += f"- **النص الأصلي:** {correction.original_text}\n"
                if correction.corrected_text:
                    summary += f"- **النص المُصحّح:** {correction.corrected_text}\n"
                summary += f"- **السبب:** {correction.reason}\n"
                summary += f"- **الموقع:** {correction.location}\n"

        return summary

# ═══════════════════════════════════════════════════════════════════════════════════════
# مُصدِّر المحرك
# ═══════════════════════════════════════════════════════════════════════════════════════

__all__ = [
    'LegalCorrectionEngine',
    'CorrectionItem',
    'CorrectionReport',
    'VerificationResult',
    'CorrectionType',
    'SeverityLevel',
    'ConfidenceLevel',
    'LegalReference',
]