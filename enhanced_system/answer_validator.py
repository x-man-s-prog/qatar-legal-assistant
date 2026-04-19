# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                    ║
║              🚀 محرك التحقق من الإجابات القانونية - MAX Edition                    ║
║              Advanced Answer Validator Engine - MAX Edition                         ║
║                                                                                    ║
║  الميزات المتقدمة:                                                                 ║
║  • التحقق من اكتمال الإجابة                                                       ║
║  • التحقق من دقة المعلومات القانونية                                              ║
║  • التحقق من تناسق المصادر                                                       ║
║  • كشف المعلومات المفقودة                                                         ║
║  • تقييم جودة الإجابة الشاملة                                                     ║
║                                                                                    ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

الإصدار: 2.0-MAX
التاريخ: 2024
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════════════
# أنواع البيانات
# ═══════════════════════════════════════════════════════════════════════════════════════

class ValidationStatus(Enum):
    """حالة التحقق"""
    PASSED = "passed"           # نجح التحقق
    FAILED = "failed"           # فشل التحقق
    WARNING = "warning"         # تحذير
    NEEDS_IMPROVEMENT = "needs_improvement"  # يحتاج تحسين

class ValidationType(Enum):
    """أنواع التحقق"""
    COMPLETENESS = "اكتمال"
    ACCURACY = "دقة"
    CONSISTENCY = "اتساق"
    RELEVANCE = "ملاءمة"
    CITATION = "اقتباس"
    CLARITY = "وضوح"

# ═══════════════════════════════════════════════════════════════════════════════════════
# نماذج البيانات
# ═══════════════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    """نتيجة التحقق"""
    validation_type: ValidationType
    status: ValidationStatus
    score: float  # 0.0 - 1.0
    message: str
    details: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

@dataclass
class AnswerValidationReport:
    """تقرير التحقق الكامل"""
    overall_status: ValidationStatus
    overall_score: float
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    warning_checks: int = 0
    validation_results: List[ValidationResult] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    timestamp: str = ""

@dataclass
class SourceValidation:
    """تحقق المصدر"""
    source_id: int
    title: str
    is_relevant: bool
    relevance_score: float
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════════════════════════════
# أنماط التحقق
# ═══════════════════════════════════════════════════════════════════════════════════════

REQUIRED_ELEMENTS = {
    "legal_answer": [
        "legal_basis",      # الأساس القانوني
        "citation",          # الاقتباس القانوني
        "explanation"        # التوضيح
    ],
    "procedural_answer": [
        "steps",             # الخطوات
        "documents",         # المستندات
        "timeline"           # الجدول الزمني
    ],
    "rights_answer": [
        "rights",            # الحقوق
        "obligations",       # الالتزامات
        "conditions"         # الشروط
    ]
}

PATTERN_CHECKS = {
    "has_citation": r'(?:المادة|قانون|رقم\s*\d+|مرسوم)',
    "has_law_reference": r'(?:قانون رقم|مرسوم بقانون|قرار)',
    "has_procedure": r'(?:خطوة|إجراء|مرحلة|عملية)',
    "has_timeframe": r'(?:يوم|أسبوع|شهر|سنة|خلال)',
    "has_condition": r'(?:إذا|حيث|بشرط|يشترط)',
    "has_rights": r'(?:حق|استحقاق|حقوق|امتياز)',
    "has_obligations": r'(?:يجب|يلزم|التزام|واجب)',
    "has_warning": r'(?:تنبيه|تحذير|تنبيه|احتياط)',
}

# ═══════════════════════════════════════════════════════════════════════════════════════
# محرك التحقق من الإجابات
# ═══════════════════════════════════════════════════════════════════════════════════════

class AnswerValidator:
    """
    محرك التحقق من الإجابات القانونية - MAX Edition

    الميزات:
    - التحقق من اكتمال الإجابة
    - التحقق من دقة المعلومات
    - التحقق من تناسق المصادر
    - كشف المعلومات المفقودة
    - تقييم جودة الإجابة الشاملة
    """

    def __init__(self):
        """تهيئة محرك التحقق"""
        self.required_elements = REQUIRED_ELEMENTS
        self.pattern_checks = PATTERN_CHECKS
        self.validation_cache = {}

    def validate(
        self,
        answer: str,
        query: str,
        sources: List[Dict],
        context: Optional[Dict] = None
    ) -> AnswerValidationReport:
        """
        التحقق من الإجابة القانونية

        Args:
            answer: الإجابة المُولّدة
            query: السؤال الأصلي
            sources: المصادر القانونية
            context: سياق إضافي

        Returns:
            AnswerValidationReport: تقرير التحقق الكامل
        """
        context = context or {}
        report = AnswerValidationReport(
            overall_status=ValidationStatus.PASSED,
            overall_score=0.0,
            timestamp=datetime.now().isoformat()
        )

        # 1. التحقق من الاكتمال
        completeness_result = self._check_completeness(answer, query, sources)
        report.validation_results.append(completeness_result)

        # 2. التحقق من الدقة
        accuracy_result = self._check_accuracy(answer, sources)
        report.validation_results.append(accuracy_result)

        # 3. التحقق من الاتساق
        consistency_result = self._check_consistency(answer, sources)
        report.validation_results.append(consistency_result)

        # 4. التحقق من الملاءمة
        relevance_result = self._check_relevance(answer, query, sources)
        report.validation_results.append(relevance_result)

        # 5. التحقق من الاقتباسات
        citation_result = self._check_citations(answer, sources)
        report.validation_results.append(citation_result)

        # 6. التحقق من الوضوح
        clarity_result = self._check_clarity(answer)
        report.validation_results.append(clarity_result)

        # حساب النتائج الإجمالية
        self._calculate_overall_status(report)

        # كشف المعلومات المفقودة
        report.missing_information = self._detect_missing_info(answer, query, sources)

        # تحديد نقاط القوة
        report.strengths = self._identify_strengths(answer, sources, report.validation_results)

        # توليد التوصيات
        report.recommendations = self._generate_recommendations(report)

        return report

    def _check_completeness(
        self,
        answer: str,
        query: str,
        sources: List[Dict]
    ) -> ValidationResult:
        """التحقق من اكتمال الإجابة"""
        result = ValidationResult(
            validation_type=ValidationType.COMPLETENESS,
            status=ValidationStatus.PASSED,
            score=1.0,
            message="اكتمال الإجابة"
        )

        # التحقق من طول الإجابة
        min_length = 100
        if len(answer) < min_length:
            result.status = ValidationStatus.WARNING
            result.score = len(answer) / min_length
            result.message = f"الإجابة قصيرة جداً ({len(answer)} حرف)"
            result.suggestions.append("قدم إجابة أكثر تفصيلاً")

        # التحقق من وجود عناصر أساسية
        query_type = self._identify_query_type(query)

        if query_type in self.required_elements:
            required = self.required_elements[query_type]
            missing = []

            for element in required:
                if not self._has_element(answer, element):
                    missing.append(element)

            if missing:
                result.status = ValidationStatus.NEEDS_IMPROVEMENT
                result.score = 1.0 - (len(missing) * 0.2)
                result.message = f"عناصر مفقودة: {', '.join(missing)}"
                result.details.append(f"النوع المتوقع: {query_type}")

                for elem in missing:
                    result.suggestions.append(f"أضف معلومات حول: {self._get_element_description(elem)}")

        # التحقق من وجود مصادر
        if not sources and len(answer) > 200:
            result.status = ValidationStatus.WARNING
            result.score *= 0.8
            result.message += " - بدون مصادر قانونية"
            result.suggestions.append("أضف مصادر قانونية موثوقة")

        return result

    def _check_accuracy(
        self,
        answer: str,
        sources: List[Dict]
    ) -> ValidationResult:
        """التحقق من دقة المعلومات"""
        result = ValidationResult(
            validation_type=ValidationType.ACCURACY,
            status=ValidationStatus.PASSED,
            score=1.0,
            message="دقة المعلومات"
        )

        # استخراج المعلومات القانونية من المصادر
        source_legal_info = self._extract_legal_info(sources)

        # البحث عن تناقضات محتملة
        contradictions = []

        # التحقق من الأرقام والتواريخ
        answer_dates = re.findall(r'\d{4}', answer)
        source_dates = set()
        for source in sources:
            content = source.get("content", "")
            source_dates.update(re.findall(r'\d{4}', content))

        # التحقق من المبالغ المالية
        answer_amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(?:ريال|دولار|دينار)', answer, re.IGNORECASE)
        source_amounts = set()
        for source in sources:
            content = source.get("content", "")
            source_amounts.update(re.findall(r'(\d+(?:\.\d+)?)\s*(?:ريال|دولار|دينار)', content, re.IGNORECASE))

        # التحقق من المصطلحات القانونية
        legal_terms_in_answer = self._find_legal_terms(answer)
        legal_terms_in_sources = set()
        for source in sources:
            content = source.get("content", "")
            legal_terms_in_sources.update(self._find_legal_terms(content))

        # تحديد المصطلحات غير الموجودة في المصادر
        unfamiliar_terms = legal_terms_in_answer - legal_terms_in_sources

        if unfamiliar_terms and len(unfamiliar_terms) > 3:
            result.status = ValidationStatus.WARNING
            result.score = 0.85
            result.message = f"مصطلحات قانونية غير موجودة في المصادر: {len(unfamiliar_terms)}"
            result.details.append(f"أمثلة: {', '.join(list(unfamiliar_terms)[:3])}")

        # التحقق من عبارات عدم اليقين المفرطة
        uncertain_phrases = ["ربما", "قد", "يمكن", "غير واضح", "غير متأكد"]
        uncertain_count = sum(1 for phrase in uncertain_phrases if phrase in answer.lower())

        if uncertain_count > 5:
            result.status = ValidationStatus.WARNING
            result.score = max(0.7, 1.0 - (uncertain_count * 0.05))
            result.message = f"استخدام مفرط لعبارات عدم اليقين ({uncertain_count})"
            result.suggestions.append("قدم معلومات أكثر يقيناً حيثما أمكن")

        return result

    def _check_consistency(
        self,
        answer: str,
        sources: List[Dict]
    ) -> ValidationResult:
        """التحقق من الاتساق"""
        result = ValidationResult(
            validation_type=ValidationType.CONSISTENCY,
            status=ValidationStatus.PASSED,
            score=1.0,
            message="اتساق الإجابة"
        )

        # جمع القوانين والمواد المذكورة
        mentioned_laws = self._extract_mentioned_laws(answer)
        source_laws = set(s.get("law", "") for s in sources if s.get("law"))

        # التحقق من ذكر قوانين غير موجودة في المصادر
        unsupported_laws = mentioned_laws - source_laws
        if unsupported_laws:
            result.status = ValidationStatus.WARNING
            result.score = 0.8
            result.message = f"قوانين مذكورة بدون مصادر: {len(unsupported_laws)}"
            result.details.extend([f"- {law}" for law in list(unsupported_laws)[:3]])
            result.suggestions.append("تحقق من صحة القوانين المذكورة")

        # التحقق من تناسق المصطلحات
        term_variations = self._check_term_variations(answer)
        if term_variations:
            result.status = ValidationStatus.WARNING
            result.score = 0.9
            result.message = "استخدام غير متسق للمصطلحات"
            result.details.extend(term_variations)

        # التحقق من عدم التناقض في الإجابة نفسها
        contradiction_indicators = self._find_internal_contradictions(answer)
        if contradiction_indicators:
            result.status = ValidationStatus.NEEDS_IMPROVEMENT
            result.score = 0.7
            result.message = f"تناقضات محتملة في الإجابة: {len(contradiction_indicators)}"
            result.details.extend(contradiction_indicators)

        return result

    def _check_relevance(
        self,
        answer: str,
        query: str,
        sources: List[Dict]
    ) -> ValidationResult:
        """التحقق من ملاءمة الإجابة للسؤال"""
        result = ValidationResult(
            validation_type=ValidationType.RELEVANCE,
            status=ValidationStatus.PASSED,
            score=1.0,
            message="ملاءمة الإجابة"
        )

        # استخراج الكلمات المفتاحية من السؤال
        query_keywords = self._extract_keywords(query)
        answer_lower = answer.lower()

        # حساب نسبة الكلمات المفتاحية الموجودة
        keywords_found = sum(1 for kw in query_keywords if kw in answer_lower)
        keyword_ratio = keywords_found / max(len(query_keywords), 1)

        if keyword_ratio < 0.3:
            result.status = ValidationStatus.FAILED
            result.score = keyword_ratio
            result.message = "الإجابة لا تجيب على السؤال"
            result.suggestions.append("ركّز على موضوع السؤال مباشرة")
        elif keyword_ratio < 0.5:
            result.status = ValidationStatus.WARNING
            result.score = keyword_ratio
            result.message = "العلاقة بين السؤال والإجابة ضعيفة"
            result.suggestions.append("أكثر من ربط الإجابة بموضوع السؤال")

        # التحقق من المصادر ذات الصلة
        relevant_sources = sum(1 for s in sources if self._is_source_relevant(s, query))
        if sources and relevant_sources == 0:
            result.status = ValidationStatus.WARNING
            result.score *= 0.7
            result.message += " - المصادر غير ذات صلة"
            result.suggestions.append("استخدم مصادر أكثر ملاءمة للسؤال")

        return result

    def _check_citations(
        self,
        answer: str,
        sources: List[Dict]
    ) -> ValidationResult:
        """التحقق من الاقتباسات القانونية"""
        result = ValidationResult(
            validation_type=ValidationType.CITATION,
            status=ValidationStatus.PASSED,
            score=1.0,
            message="الاقتباسات القانونية"
        )

        # البحث عن الاقتباسات في الإجابة
        citation_pattern = r'(?:المادة|مواد)\s*(\d+)'
        citations_found = re.findall(citation_pattern, answer)

        if not citations_found:
            if sources:
                result.status = ValidationStatus.WARNING
                result.score = 0.8
                result.message = "لا توجد اقتباسات قانونية صريحة"
                result.suggestions.append("أضف رقم المادة والقانون صراحةً")
        else:
            # التحقق من صحة الاقتباسات
            source_articles = set()
            for source in sources:
                article = source.get("article", "")
                if article:
                    source_articles.add(str(article))

            invalid_citations = []
            for citation in citations_found:
                if citation not in source_articles:
                    invalid_citations.append(citation)

            if invalid_citations:
                result.status = ValidationStatus.WARNING
                result.score = 0.85
                result.message = f"اقتباسات غير موجودة في المصادر: {len(invalid_citations)}"
                result.suggestions.append("تحقق من صحة أرقام المواد المذكورة")

        # التحقق من ذكر القانون
        if not re.search(self.pattern_checks["has_law_reference"], answer):
            result.status = ValidationStatus.WARNING
            result.score = min(result.score, 0.75)
            result.suggestions.append("اذكر القانون الذي تستند إليه")

        return result

    def _check_clarity(
        self,
        answer: str
    ) -> ValidationResult:
        """التحقق من وضوح الإجابة"""
        result = ValidationResult(
            validation_type=ValidationType.CLARITY,
            status=ValidationStatus.PASSED,
            score=1.0,
            message="وضوح الإجابة"
        )

        # كشف المصطلحات الغامضة
        vague_terms = ["شيء", "شخص", "مكان", "بعض", "أي", "غير محدد"]
        vague_count = sum(1 for term in vague_terms if f"أي {term}" in answer or f"بعض {term}" in answer)

        if vague_count > 3:
            result.status = ValidationStatus.WARNING
            result.score = 0.85
            result.message = f"استخدام مفرط للمصطلحات الغامضة ({vague_count})"
            result.suggestions.append("حدد المصطلحات الغامضة بشكل أوضح")

        # كشف الجمل غير المكتملة
        incomplete_patterns = [
            r'(?:يجب|يمكن|يلزم)\s+[^\.]*$',
            r'\.\.\.$'
        ]
        incomplete_count = 0
        for pattern in incomplete_patterns:
            incomplete_count += len(re.findall(pattern, answer))

        if incomplete_count > 0:
            result.status = ValidationStatus.NEEDS_IMPROVEMENT
            result.score = 0.8
            result.message = f"جمل غير مكتملة: {incomplete_count}"
            result.suggestions.append("أتمم جميع الجمل")

        # التحقق من البنية
        paragraphs = answer.split('\n\n')
        if len(paragraphs) < 2 and len(answer) > 500:
            result.status = ValidationStatus.WARNING
            result.score = 0.9
            result.message = "الإجابة تفتقر للتنظيم"
            result.suggestions.append("قسم الإجابة إلى فقرات واضحة")

        return result

    def _calculate_overall_status(self, report: AnswerValidationReport):
        """حساب الحالة الإجمالية"""
        report.total_checks = len(report.validation_results)
        report.passed_checks = sum(
            1 for r in report.validation_results if r.status == ValidationStatus.PASSED
        )
        report.failed_checks = sum(
            1 for r in report.validation_results if r.status == ValidationStatus.FAILED
        )
        report.warning_checks = sum(
            1 for r in report.validation_results if r.status in [
                ValidationStatus.WARNING,
                ValidationStatus.NEEDS_IMPROVEMENT
            ]
        )

        # حساب الدرجة الإجمالية
        report.overall_score = sum(r.score for r in report.validation_results) / max(report.total_checks, 1)

        # تحديد الحالة الإجمالية
        if report.failed_checks > 0:
            report.overall_status = ValidationStatus.FAILED
        elif report.warning_checks > 2:
            report.overall_status = ValidationStatus.NEEDS_IMPROVEMENT
        elif report.warning_checks > 0:
            report.overall_status = ValidationStatus.WARNING
        else:
            report.overall_status = ValidationStatus.PASSED

    def _identify_query_type(self, query: str) -> str:
        """تحديد نوع السؤال"""
        query_lower = query.lower()

        if any(word in query_lower for word in ["كيف", "خطوات", "إجراء", "طريقة", "أقدم"]):
            return "procedural_answer"
        elif any(word in query_lower for word in ["هل لي", "هل أستحق", "حقي", "حقوقي"]):
            return "rights_answer"
        else:
            return "legal_answer"

    def _has_element(self, answer: str, element: str) -> bool:
        """التحقق من وجود عنصر"""
        patterns = {
            "legal_basis": [r'(?:مادة|قانون|نص)', r'(?:أساس|استناد)'],
            "citation": [r'(?:المادة|مواد)\s*\d+', r'(?:فقرة|باب|فصل)'],
            "explanation": [r'(?:أي\s*أن|يعني|هذا\s* означает|بمعنى)'],
            "steps": [r'(?:خطوة|مرحلة|إجراء)', r'(?:أولاً|ثانياً|ثالثاً)'],
            "documents": [r'(?:مستند|أوراق|وثيقة|شهادة)', r'(?:إرفاق|تقديم)'],
            "timeline": [r'(?:يوم|أسبوع|شهر|سنة)', r'(?:خلال|خلال\s*مدة)'],
            "rights": [r'(?:حق|استحقاق|امتياز)', r'(?:لك\s*الحق|يحق\s*لك)'],
            "obligations": [r'(?:يجب|يلزم|التزام|واجب)', r'(?:عليك|يلزم\s*عليك)'],
            "conditions": [r'(?:بشرط|يشترط|إذا|حيث)', r'(?:شروط|متطلبات)']
        }

        element_patterns = patterns.get(element, [])
        return any(re.search(pattern, answer) for pattern in element_patterns)

    def _get_element_description(self, element: str) -> str:
        """الحصول على وصف العنصر"""
        descriptions = {
            "legal_basis": "الأساس القانوني (القانون والمادة)",
            "citation": "الاقتباس القانوني (رقم المادة)",
            "explanation": "توضيح المعنى",
            "steps": "الخطوات الإجرائية",
            "documents": "المستندات المطلوبة",
            "timeline": "الجدول الزمني",
            "rights": "الحقوق المترتبة",
            "obligations": "الالتزامات المطلوبة",
            "conditions": "الشروط اللازمة"
        }
        return descriptions.get(element, element)

    def _extract_legal_info(self, sources: List[Dict]) -> Dict:
        """استخراج المعلومات القانونية من المصادر"""
        info = {
            "laws": set(),
            "articles": set(),
            "terms": set()
        }

        for source in sources:
            if source.get("law"):
                info["laws"].add(source["law"])
            if source.get("article"):
                info["articles"].add(str(source["article"]))
            content = source.get("content", "")
            info["terms"].update(self._find_legal_terms(content))

        return info

    def _find_legal_terms(self, text: str) -> set:
        """البحث عن المصطلحات القانونية"""
        terms = {
            "عقد", "اتفاق", "التزام", "حق", "واجب", "طرف",
            "جريمة", "عقوبة", "سجن", "غرامة", "تعويض",
            "طلاق", "زواج", "حضانة", "نفقة", "ولاية",
            "شركة", "تجاري", "سهم", "سند",
            "محكمة", "قاضي", "نيابة", "دعوى", "طعن"
        }

        found = set()
        for term in terms:
            if term in text:
                found.add(term)

        return found

    def _extract_mentioned_laws(self, text: str) -> set:
        """استخراج القوانين المذكورة"""
        laws = set()

        # نماذج ذكر القانون
        law_patterns = [
            r'قانون\s+(?:رقم\s+)?(\d+)',
            r'(?:قانون|مرسوم)\s+(?:رقم\s+)?(\d+)',
            r'قانون\s+(.+?)(?:\s+مادة|\s+رقم|\s+لسنة|$)'
        ]

        for pattern in law_patterns:
            matches = re.findall(pattern, text)
            laws.update(matches)

        return laws

    def _check_term_variations(self, text: str) -> List[str]:
        """التحقق من تنوع المصطلحات"""
        variations = []
        term_groups = {
            "النفقة/المصروفات": ["نفقة", "مصروفات"],
            "الحضانة/الولاية": ["حضانة", "ولاية"],
            "التعويض/البدل": ["تعويض", "بدل"],
            "العقد/الاتفاق": ["عقد", "اتفاقية"]
        }

        for name, terms in term_groups.items():
            found = [t for t in terms if t in text]
            if len(found) > 1:
                variations.append(f"{name}: {' و '.join(found)}")

        return variations

    def _find_internal_contradictions(self, text: str) -> List[str]:
        """البحث عن التناقضات الداخلية"""
        contradictions = []

        # عبارات متناقضة محتملة
        positive_negative = [
            ("يمكن", "لا يمكن"),
            ("مسموح", "ممنوع"),
            ("يجب", "لا يجب"),
            ("ضروري", "اختياري")
        ]

        for pos, neg in positive_negative:
            if pos in text.lower() and neg in text.lower():
                contradictions.append(f"تناقض محتمل: '{pos}' و '{neg}'")

        return contradictions

    def _extract_keywords(self, text: str) -> List[str]:
        """استخراج الكلمات المفتاحية"""
        # كلمات شائعة يتم تجاهلها
        stop_words = {
            "ما", "هو", "هي", "عن", "من", "في", "على", "إلى", "عن",
            "مع", "هذا", "هذه", "ذلك", "تلك", "أو", "و", "لكن", "إذا"
        }

        words = re.findall(r'[\u0600-\u06FF]+', text)
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        return keywords

    def _is_source_relevant(self, source: Dict, query: str) -> bool:
        """التحقق من ملاءمة المصدر"""
        query_keywords = set(self._extract_keywords(query))
        source_content = (source.get("title", "") + " " + source.get("content", "")).lower()

        source_keywords = set(re.findall(r'[\u0600-\u06FF]+', source_content))
        source_keywords = {w for w in source_keywords if len(w) > 2}

        overlap = query_keywords & source_keywords
        return len(overlap) >= min(2, len(query_keywords) * 0.3)

    def _detect_missing_info(
        self,
        answer: str,
        query: str,
        sources: List[Dict]
    ) -> List[str]:
        """كشف المعلومات المفقودة"""
        missing = []

        # التحقق من وجود إطار زمني
        if not re.search(self.pattern_checks["has_timeframe"], answer):
            if any(word in query.lower() for word in ["متى", "بعد", "قبل", "خلال"]):
                missing.append("إطار زمني")

        # التحقق من وجود شروط
        if not re.search(self.pattern_checks["has_condition"], answer):
            if any(word in query.lower() for word in ["شروط", "إذا", "بشرط"]):
                missing.append("شروط")

        # التحقق من وجود تحذيرات
        if not re.search(self.pattern_checks["has_warning"], answer):
            if len(answer) > 500:
                missing.append("تحذيرات وتنبيهات")

        # التحقق من وجود مصادر
        if not sources:
            missing.append("مصادر قانونية")

        return missing

    def _identify_strengths(
        self,
        answer: str,
        sources: List[Dict],
        validations: List[ValidationResult]
    ) -> List[str]:
        """تحديد نقاط القوة"""
        strengths = []

        # نقاط القوة من نتائج التحقق
        for validation in validations:
            if validation.status == ValidationStatus.PASSED:
                strengths.append(f"✓ {validation.message}")

        # نقاط القوة الإضافية
        if len(answer) > 500:
            strengths.append("✓ إجابة مفصلة")

        if sources:
            strengths.append(f"✓ {len(sources)} مصادر قانونية")

        if re.search(self.pattern_checks["has_citation"], answer):
            strengths.append("✓ اقتباسات قانونية صريحة")

        if re.search(self.pattern_checks["has_procedure"], answer):
            strengths.append("✓ خطوات إجرائية واضحة")

        return strengths

    def _generate_recommendations(self, report: AnswerValidationReport) -> List[str]:
        """توليد التوصيات"""
        recommendations = []

        # توصيات بناءً على النتائج
        if report.overall_status == ValidationStatus.FAILED:
            recommendations.append("⚠️ تحتاج الإجابة إلى مراجعة شاملة قبل الاستخدام")

        if report.warning_checks > 0:
            recommendations.append("💡 يمكن تحسين الإجابة بالتوصيات التالية:")

        for validation in report.validation_results:
            if validation.suggestions:
                recommendations.extend([f"  - {s}" for s in validation.suggestions])

        if report.overall_score >= 0.9:
            recommendations.append("✅ جودة الإجابة ممتازة")

        return recommendations

    def validate_sources(
        self,
        sources: List[Dict],
        query: str
    ) -> List[SourceValidation]:
        """التحقق من المصادر"""
        validations = []

        for i, source in enumerate(sources):
            validation = SourceValidation(
                source_id=i,
                title=source.get("title", f"مصدر {i+1}"),
                is_relevant=self._is_source_relevant(source, query),
                relevance_score=0.0,
                issues=[],
                suggestions=[]
            )

            # حساب درجة الملاءمة
            query_keywords = set(self._extract_keywords(query))
            source_content = (source.get("title", "") + " " + source.get("content", "")).lower()
            source_keywords = set(re.findall(r'[\u0600-\u06FF]+', source_content))
            source_keywords = {w for w in source_keywords if len(w) > 2}

            overlap = query_keywords & source_keywords
            if query_keywords:
                validation.relevance_score = len(overlap) / len(query_keywords)

            # كشف المشاكل
            if not source.get("content"):
                validation.issues.append("محتوى فارغ")
                validation.suggestions.append("أضف محتوى للمصدر")

            if not source.get("law"):
                validation.issues.append("بدون مرجع قانوني")

            if not validation.is_relevant:
                validation.issues.append("غير ذي صلة بالاستعلام")

            validations.append(validation)

        return validations

    def generate_validation_summary(self, report: AnswerValidationReport) -> str:
        """توليد ملخص التحقق"""

        summary = "## 📊 تقرير التحقق من الإجابة\n\n"

        # الحالة الإجمالية
        status_icons = {
            ValidationStatus.PASSED: "✅",
            ValidationStatus.FAILED: "❌",
            ValidationStatus.WARNING: "⚠️",
            ValidationStatus.NEEDS_IMPROVEMENT: "🔧"
        }

        summary += f"### الحالة الإجمالية\n"
        summary += f"{status_icons.get(report.overall_status, '')} **{report.overall_status.value}**\n"
        summary += f"**الدرجة:** {report.overall_score:.0%}\n"
        summary += f"**الفحوصات:** {report.passed_checks}/{report.total_checks} ناجحة\n\n"

        # نقاط القوة
        if report.strengths:
            summary += f"### نقاط القوة\n"
            for strength in report.strengths:
                summary += f"- {strength}\n"
            summary += "\n"

        # المعلومات المفقودة
        if report.missing_information:
            summary += f"### معلومات مفقودة\n"
            for info in report.missing_information:
                summary += f"- ❌ {info}\n"
            summary += "\n"

        # التوصيات
        if report.recommendations:
            summary += f"### التوصيات\n"
            for rec in report.recommendations:
                summary += f"- {rec}\n"

        return summary

# ═══════════════════════════════════════════════════════════════════════════════════════
# مُصدِّر المحرك
# ═══════════════════════════════════════════════════════════════════════════════════════

__all__ = [
    'AnswerValidator',
    'AnswerValidationReport',
    'ValidationResult',
    'ValidationStatus',
    'ValidationType',
    'SourceValidation',
]
