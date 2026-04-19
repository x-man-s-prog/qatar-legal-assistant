# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    طبقة الذكاء القانوني المُحسّنة - MAX Edition               ║
║              Enhanced Legal Intelligence Layer - MAX Edition                  ║
║                                                                              ║
║  الميزات المتقدمة:                                                           ║
║  • تكامل مع محرك الفهم اللغوي المتقدم (UltraLinguisticEngine)                ║
║  • تنسيق متجاوب مع اللهجة والقصد (Intent-Aware Formatting)                   ║
║  • كشف وتحذير من الغموض في الإجابات                                         ║
║  • تنسيق قانوني احترافي مع اقتباسات صحيحة                                   ║
║  • دعم متعدد اللهجات (الخليجية، المصرية، الشامية، العراقية)                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

الإصدار: 3.0-MAX
التاريخ: 2024
"""

import json
import re
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

# ═══════════════════════════════════════════════════════════════════════════════
# محاولة استيراد محرك الفهم اللغوي المتقدم
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from ultra_linguistic_engine import UltraLinguisticEngine, MAX_AVAILABLE
    ULTRA_ENGINE_AVAILABLE = MAX_AVAILABLE
except ImportError:
    ULTRA_ENGINE_AVAILABLE = False
    UltraLinguisticEngine = None

# ═══════════════════════════════════════════════════════════════════════════════
# أنواع البيانات والقوائم
# ═══════════════════════════════════════════════════════════════════════════════

class ResponseStyle(Enum):
    """أنماط الإجابة القانونية"""
    FORMAL_LEGAL = "formal_legal"      # أسلوب قانوني رسمي
    SIMPLIFIED = "simplified"          # مبسّط للشرح
    DETAILED = "detailed"              # مفصّل
    QUICK_ANSWER = "quick_answer"      # إجابة سريعة

class IntentCategory(Enum):
    """فئات القصد القانوني"""
    INFORMATION_REQUEST = "طلب_معلومات"
    LEGAL_ADVICE = "استشارة_قانونية"
    PROCEDURAL_GUIDANCE = "إرشاد_إجرائي"
    RIGHTS_INQUIRY = "استفسار_حقوق"
    OBLIGATIONS_INQUIRY = "استفسار_التزامات"
    CASE_ANALYSIS = "تحليل_حالة"
    DOCUMENT_PREPARATION = "إعداد_مستند"
    COMPLAINT = "شكوى"
    GENERAL = "عام"

class DialectType(Enum):
    """أنواع اللهجات المدعومة"""
    GULF = "خليجية"
    EGYPTIAN = "مصرية"
    LEVANTINE = "شامية"
    IRAQI = "عراقية"
    MODERN_STANDARD = "فصحى"

# ═══════════════════════════════════════════════════════════════════════════════
# نماذج البيانات المُحسّنة
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LegalCitation:
    """اقتباس قانوني مُحسّن"""
    law_name: str
    article_number: str
    text: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    confidence: float = 1.0

@dataclass
class IntentAnalysis:
    """تحليل القصد"""
    primary_intent: IntentCategory
    secondary_intents: List[IntentCategory] = field(default_factory=list)
    confidence: float = 0.0
    requires_professional: bool = False
    urgency_level: str = "عادي"
    legal_domain: str = "غير محدد"

@dataclass
class AmbiguityWarning:
    """تحذير غموض"""
    text: str
    location: str
    ambiguity_type: str
    suggestion: str
    severity: str = "متوسط"

@dataclass
class FormattingContext:
    """سياق التنسيق"""
    dialect: DialectType = DialectType.MODERN_STANDARD
    dialect_confidence: float = 0.0
    intent: IntentCategory = IntentCategory.GENERAL
    response_style: ResponseStyle = ResponseStyle.FORMAL_LEGAL
    domain: str = "قانوني عام"
    has_ambiguities: bool = False
    sources_count: int = 0
    confidence: float = 0.0
    session_history_length: int = 0
    user_preference_formal: bool = True

# ═══════════════════════════════════════════════════════════════════════════════
# قاموس المصطلحات القانونية المُوسّع
# ═══════════════════════════════════════════════════════════════════════════════

LEGAL_TERMINOLOGY_MAP = {
    # العقوبات
    "عقوبة": "sanction",
    "سجن": "imprisonment",
    "غرامة": "fine",
    "تعويض": "compensation",
    "تعويضات": "damages",

    # القانون المدني
    "عقد": "contract",
    "اتفاقية": "agreement",
    "التزام": "obligation",
    "حق": "right",
    "واجب": "duty",
    "طرف": "party",
    "أطراف": "parties",

    # القانون الجنائي
    "جريمة": "crime",
    "جنحة": "misdemeanor",
    "مخالفة": "violation",
    "متهم": "defendant",
    "مدان": "convicted",
    "ضحية": "victim",

    # القانون التجاري
    "شركة": "company",
    "تجاري": "commercial",
    "سوق": "market",
    "سهم": "share",
    "سندات": "bonds",

    # قانون الأسرة
    "زواج": "marriage",
    "طلاق": "divorce",
    "حضانة": "custody",
    "نفقة": "alimony",
    "صداق": "dowry",

    # القانون الإداري
    "إدارة": "administration",
    "موظف": "employee",
    "قرارات إدارية": "administrative decisions",
    "طعن": "appeal",
}

# ═══════════════════════════════════════════════════════════════════════════════
# قوالب الأوامر الداخلية المُحسّنة
# ═══════════════════════════════════════════════════════════════════════════════

INTERNAL_MONOLOGUE_TEMPLATES = {
    IntentCategory.INFORMATION_REQUEST: """أنت مستشار قانوني قطري ذكي تقوم بالتفكير内部 перед ответом.
السياق:
- اللهجة المكتشفة: {dialect}
- مستوى الثقة: {confidence}%
- المجال القانوني: {domain}

المهمة: قدم معلومات قانونية دقيقة بناءً على المصادر المقدمة.

مصادر البحث:
{sources}

الآن فكر في الإجابة:
1. ما هي النقاط القانونية الرئيسية؟
2. هل هناك تناقضات في المصادر؟
3. ما هي النقاط التي تحتاج توضيحاً؟
4. هل الإجابة واضحة وموثوقة؟

الإجابة الأولية:""",

    IntentCategory.LEGAL_ADVICE: """أنت مستشار قانوني قطري ذكي تقوم بالتفكير内部 перед ответом.
تحليل القصد: استشارة قانونية
اللهجة: {dialect}
ثقة اللهجة: {confidence}%
المجال: {domain}

المستخدم يطلب مشورة قانونية. تذكر:
1. أنت لست محامياً، قدم معلومات عامة
2. اشرح الخيارات القانونية المتاحة
3. وجّه للاستشارة المتخصصة إذا لزم الأمر

المصادر:
{sources}

التفكير القانوني:
1. تحديد المشكلة القانونية بدقة
2. استعراض الحلول الممكنة
3. تقييم المخاطر والفوائد
4. التوصية بمسار العمل

الإجابة:""",

    IntentCategory.PROCEDURAL_GUIDANCE: """أنت مستشار قانوني قطري ذكي تقوم بالتفكير内部 перед ответом.
القصد: إرشاد إجرائي
اللهجة: {dialect}

المهمة: تقديم إرشادات إجرائية قانونية واضحة.

المصادر:
{sources}

الخطوات الإجرائية:
1. تحديد المرحلة الحالية
2. listing required steps
3. تحديد المستندات المطلوبة
4. تقدير الوقت المتوقع

الإجابة:""",

    IntentCategory.GENERAL: """أنت مستشار قانوني قطري ذكي تقوم بالتفكير内部 перед ответом.
اللهجة: {dialect}
المصادر: {sources_count}

التفكير:""",
}

# ═══════════════════════════════════════════════════════════════════════════════
# قوالب تنسيق الإجابات القانونية المُحسّنة
# ═══════════════════════════════════════════════════════════════════════════════

RESPONSE_TEMPLATES = {
    ResponseStyle.FORMAL_LEGAL: """# 📜 الإجابة القانونية الرسمية

## ملخص الاستشارة
{summary}

## التفاصيل القانونية
{content}

## الأساس القانوني
{legal_basis}

## التوصيات
{recommendations}

## تحذيرات
{warnings}

---
*تم إعداد هذه الإجابة بواسطة المساعد القانوني القطري - MAX Edition*
*التاريخ: {timestamp}*
""",

    ResponseStyle.SIMPLIFIED: """# 💡 شرح مبسّط

## ما تحتاج معرفته
{summary_simple}

## الشرح المبسّط
{simplified_explanation}

## مثال عملي
{practical_example}

##خلاصة
{quick_summary}
""",

    ResponseStyle.DETAILED: """# 📖 إجابة مفصّلة

## أولاً: السياق القانوني
{context}

## ثانياً: الإجابة الكاملة
{detailed_content}

## ثالثاً: التحليل القانوني
{legal_analysis}

## رابعاً: السوابق القضائية ذات الصلة
{precedents}

## خامساً: التوصيات والخطوات التالية
{detailed_recommendations}

## سادساً: تحذيرات مهمة
{detailed_warnings}

## المصادر القانونية
{sources_list}

---
*نظام المساعد القانوني القطري - MAX Edition*
""",

    ResponseStyle.QUICK_ANSWER: """# ⚡ إجابة سريعة

**السؤال:** {question}

**الإجابة:** {quick_answer}

**الثقة:** {confidence}%
**المصادر:** {sources_count}
""",
}

# ═══════════════════════════════════════════════════════════════════════════════
# محسّن التنسيق القانوني
# ═══════════════════════════════════════════════════════════════════════════════

class LegalFormatter:
    """محسّن التنسيق القانوني"""

    # أنماط اللهجات
    DIALECT_ADAPTATIONS = {
        DialectType.GULF: {
            "greeting": "هلا والله، ",
            "formal_intro": "بخصوص سؤالك عن ",
            "clarification": "خلني أوضّح لك ",
            "conclusion": "هذا اللي قدرت أفيدك فيه، ",
            "recommendation": "أنصحك بـ ",
        },
        DialectType.EGYPTIAN: {
            "greeting": "أهلاً وسهلاً، ",
            "formal_intro": "بخصوص ",
            "clarification": "خلّيني أوضّحلك ",
            "conclusion": "هذا اللي قدرت أساعدك بيه، ",
            "recommendation": "بنصحك بـ ",
        },
        DialectType.LEVANTINE: {
            "greeting": "أهلاً، ",
            "formal_intro": "بخصوص سؤالك ",
            "clarification": "خلّيني وضّحلك ",
            "conclusion": "هاد اللي قدرت مساعدك فيه، ",
            "recommendation": "بنصحك ",
        },
        DialectType.IRAQI: {
            "greeting": "أهلاً بيك، ",
            "formal_intro": "بخصوص سؤالك ",
            "clarification": "خلّيني أوضّحلك ",
            "conclusion": "هاي المساعدة اللي قدرت أقدمها، ",
            "recommendation": "بنصحك ",
        },
        DialectType.MODERN_STANDARD: {
            "greeting": "السلام عليكم، ",
            "formal_intro": "بناءً على استفساركم بشأن ",
            "clarification": "نودّ توضيح ",
            "conclusion": "نأمل أن تكون هذه الإجابة مفيدة، ",
            "recommendation": "نوصي بـ ",
        },
    }

    @staticmethod
    def format_legal_reference(law_name: str, article: str, text: str) -> str:
        """تنسيق مرجع قانوني"""
        # Try to create proper legal citation format
        if law_name and article:
            return f"**{law_name} - المادة {article}**\n> {text}"
        elif law_name:
            return f"**{law_name}**\n> {text}"
        else:
            return f"> {text}"

    @staticmethod
    def format_citation(source: Dict) -> str:
        """تنسيق اقتباس مصدر"""
        title = source.get("title", "مصدر")
        content = source.get("content", "")[:200]
        law = source.get("law", "")
        article = source.get("article", "")

        citation = f"**{title}**"
        if law:
            citation += f" ({law}"
            if article:
                citation += f" - مادة {article}"
            citation += ")"

        if content:
            citation += f"\n> {content}..."

        return citation

    @staticmethod
    def adapt_for_dialect(text: str, dialect: DialectType) -> str:
        """تكييف النص للهجة معينة"""
        if dialect == DialectType.MODERN_STANDARD:
            return text

        adaptations = LegalFormatter.DIALECT_ADAPTATIONS.get(dialect, {})

        # استبدال العبارات الرسمية بالفصحى
        formal_phrases = {
            "بناءً على": "بخصوص",
            "نوصي": "بنصحك",
            "نأمل": "نتمنى",
            "نودّ": "خلّيني",
            "إجابة": "رد",
            "استفسار": "سؤال",
            "مساعدة": "فائدة",
        }

        result = text
        for formal, colloquial in formal_phrases.items():
            # تطبيق خفيف حسب اللهجة
            if dialect in [DialectType.GULF, DialectType.EGYPTIAN]:
                result = result.replace(formal, colloquial)

        return result

    @staticmethod
    def highlight_legal_terms(text: str) -> str:
        """تمييز المصطلحات القانونية"""
        highlighted = text

        for term, english in LEGAL_TERMINOLOGY_MAP.items():
            # Use ** for bold highlighting
            pattern = rf'\b({re.escape(term)})\b'
            highlighted = re.sub(pattern, r'**\1**', highlighted)

        return highlighted

    @staticmethod
    def format_confidence_indicator(confidence: float) -> str:
        """تنسيق مؤشر الثقة"""
        if confidence >= 0.9:
            return "🔵 عالية جداً"
        elif confidence >= 0.7:
            return "🟢 عالية"
        elif confidence >= 0.5:
            return "🟡 متوسطة"
        elif confidence >= 0.3:
            return "🟠 منخفضة"
        else:
            return "🔴 منخفضة جداً"

# ═══════════════════════════════════════════════════════════════════════════════
# طبقة الذكاء القانوني المُحسّنة
# ═══════════════════════════════════════════════════════════════════════════════

class EnhancedIntelligenceLayer:
    """
    طبقة الذكاء القانوني المُحسّنة - MAX Edition

    الميزات:
    - تكامل مع UltraLinguisticEngine لاستخراج القصد والسياق
    - تنسيق متجاوب مع اللهجة والقصد
    - كشف وتحذير من الغموض
    - تنسيق قانوني احترافي
    """

    def __init__(self, use_ultra_engine: bool = True):
        """
        تهيئة الطبقة الذكية

        Args:
            use_ultra_engine: استخدام محرك الفهم اللغوي المتقدم
        """
        self.formatter = LegalFormatter()

        # محاولة تهيئة محرك الفهم اللغوي المتقدم
        self.ultra_engine = None
        if use_ultra_engine and ULTRA_ENGINE_AVAILABLE:
            try:
                self.ultra_engine = UltraLinguisticEngine()
                print("✓ تم تفعيل UltraLinguisticEngine")
            except Exception as e:
                print(f"⚠ تعذر تفعيل UltraLinguisticEngine: {e}")
                self.ultra_engine = None

    def analyze_intent_from_query(self, query: str, context: Optional[Dict] = None) -> IntentAnalysis:
        """
        تحليل قصد المستخدم من السؤال

        Args:
            query: سؤال المستخدم
            context: سياق إضافي

        Returns:
            IntentAnalysis: تحليل القصد
        """
        query_lower = query.lower()
        context = context or {}

        # قواعد استخراج القصد
        intent_indicators = {
            IntentCategory.INFORMATION_REQUEST: [
                "ما هو", "ما هي", "ما حكم", "ما عقوبة", "ما شروط",
                "كيف", "متى", "أين", "هل يمكن", "هل يجوز"
            ],
            IntentCategory.LEGAL_ADVICE: [
                "ماذا أفعل", "أنصحني", "ما الأفضل", "ما الخيار",
                "كيف أتصرف", "ما الخطوات", "أفيدني", "ساعدني"
            ],
            IntentCategory.PROCEDURAL_GUIDANCE: [
                "كيف أقدم", "ما المستندات", "أين أذهب", "متى يكون",
                "ما الإجراءات", "خطوات", "إجراءات", "طريقة"
            ],
            IntentCategory.RIGHTS_INQUIRY: [
                "هل لي الحق", "هل أستحق", "هل لدي", "ما حقي",
                "هل أطالب", "استحقاقي", "حقوقي"
            ],
            IntentCategory.OBLIGATIONS_INQUIRY: [
                "هل يجب", "هل يلزمني", "ما واجبي", "يجب علي",
                "التزاماتي", "مسؤوليتي"
            ],
            IntentCategory.CASE_ANALYSIS: [
                "حالتي", "وضعي", "مشروعي", "قضيتي",
                "نزاعي", "مشكلة", "نزاع"
            ],
            IntentCategory.DOCUMENT_PREPARATION: [
                "كيف أكتب", "نموذج", "صيغة", "عقد",
                "إعداد", "كتابة"
            ],
            IntentCategory.COMPLAINT: [
                "أشكو", "مظلوم", "تظلم", "شكوى",
                "إبلاغ", "بلاغ"
            ],
        }

        # تحديد القصد الأساسي
        primary_intent = IntentCategory.GENERAL
        max_score = 0

        for intent, indicators in intent_indicators.items():
            score = sum(1 for ind in indicators if ind in query_lower)
            if score > max_score:
                max_score = score
                primary_intent = intent

        # تحديد القصد الثانوي
        secondary_intents = []
        for intent, indicators in intent_indicators.items():
            if intent != primary_intent:
                score = sum(1 for ind in indicators if ind in query_lower)
                if score > 0:
                    secondary_intents.append(intent)

        # تحليل إضافية
        requires_professional = any(word in query_lower for word in [
            "محامي", "استشارة متخصصة", "قضية في المحكمة", "دعوى",
            "طعن", "استئناف", "محكمة"
        ])

        urgency_keywords = {
            "عاجل": "عاجل",
            "مستعجل": "عاجل",
            "فوراً": "عاجل",
            "غداً": "عاجل",
            "اليوم": "عاجل",
            "خطر": "عاجل",
        }
        urgency = "عادي"
        for keyword, level in urgency_keywords.items():
            if keyword in query_lower:
                urgency = level
                break

        return IntentAnalysis(
            primary_intent=primary_intent,
            secondary_intents=secondary_intents[:2],
            confidence=min(0.5 + max_score * 0.1, 0.95),
            requires_professional=requires_professional,
            urgency_level=urgency,
            legal_domain=context.get("domain", "غير محدد")
        )

    def detect_ambiguities(self, query: str, answer: str, sources: List[Dict]) -> List[AmbiguityWarning]:
        """
        كشف الغموض في السؤال أو الإجابة

        Args:
            query: سؤال المستخدم
            answer: الإجابة المُولّدة
            sources: المصادر المستخدمة

        Returns:
            List[AmbiguityWarning]: قائمة تحذيرات الغموض
        """
        warnings = []
        query_lower = query.lower()

        # كشف الغموض في السؤال
        vague_terms = ["شيء", "شخص", "مكان", "زمن", "سبب"]
        for term in vague_terms:
            if f"أي {term}" in query_lower or f"بعض {term}" in query_lower:
                warnings.append(AmbiguityWarning(
                    text=f"استخدام غير محدد لـ '{term}'",
                    location="question",
                    ambiguity_type="vague_reference",
                    suggestion=f"حدد '{term}' بشكل أوضح للحصول على إجابة أدق",
                    severity="متوسط"
                ))

        # كشف عدم وجود مصادر
        if not sources:
            warnings.append(AmbiguityWarning(
                text="لا توجد مصادر قانونية موثوقة",
                location="answer",
                ambiguity_type="no_sources",
                suggestion="تحقق من مصدر المعلومات أو اطلب توضيحاً إضافياً",
                severity="عالي"
            ))

        # كشف تناقض المصادر
        if len(sources) > 1:
            law_names = set(s.get("law", "") for s in sources if s.get("law"))
            if len(law_names) > 2:
                warnings.append(AmbiguityWarning(
                    text=f"استخدام {len(law_names)} قوانين مختلفة",
                    location="answer",
                    ambiguity_type="source_complexity",
                    suggestion="قد يكون من المفيد التركيز على قانون واحد",
                    severity="منخفض"
                ))

        # كشف إجابة قصيرة جداً
        if len(answer) < 100 and sources:
            warnings.append(AmbiguityWarning(
                text="الإجابة قصيرة جداً",
                location="answer",
                ambiguity_type="short_answer",
                suggestion="يمكن تقديم إجابة أكثر تفصيلاً",
                severity="منخفض"
            ))

        return warnings

    def format_response(
        self,
        answer: str,
        sources: List[Dict],
        formatting_context: FormattingContext,
        query_analysis: Optional[Dict] = None
    ) -> str:
        """
        تنسيق الإجابة النهائية

        Args:
            answer: الإجابة الخام
            sources: المصادر القانونية
            formatting_context: سياق التنسيق
            query_analysis: تحليل السؤال (اختياري)

        Returns:
            str: الإجابة المنسّقة
        """
        # استخراج معلومات من السياق
        dialect = formatting_context.dialect
        intent = formatting_context.intent
        style = formatting_context.response_style
        confidence = formatting_context.confidence

        # كشف الغموض
        ambiguities = self.detect_ambiguities(
            query_analysis.get("query", "") if query_analysis else "",
            answer,
            sources
        )
        has_ambiguities = len(ambiguities) > 0

        # اختيار القالب المناسب
        if style == ResponseStyle.QUICK_ANSWER:
            return self._format_quick_response(answer, sources, formatting_context)

        # تنسيق المصادر
        formatted_sources = []
        for i, source in enumerate(sources[:5], 1):
            formatted_sources.append(f"{i}. {self.formatter.format_citation(source)}")

        sources_text = "\n".join(formatted_sources) if formatted_sources else "لا توجد مصادر متاحة"

        # تنسيق التحذيرات
        warnings_text = ""
        if has_ambiguities:
            warning_lines = []
            for w in ambiguities[:3]:
                emoji = "⚠️" if w.severity in ["متوسط", "عالي"] else "ℹ️"
                warning_lines.append(f"{emoji} {w.text}: {w.suggestion}")
            warnings_text = "\n".join(warning_lines)

        # تكييف الإجابة للهجة
        adapted_answer = self.formatter.adapt_for_dialect(answer, dialect)

        # تمييز المصطلحات القانونية
        highlighted_answer = self.formatter.highlight_legal_terms(adapted_answer)

        # بناء الإجابة النهائية
        final_response = self._build_formatted_response(
            highlighted_answer,
            sources_text,
            warnings_text,
            formatting_context,
            query_analysis
        )

        # إضافة تنسيقات خاصة
        if has_ambiguities:
            final_response = self._add_ambiguity_notice(final_response, ambiguities)

        # إضافة مؤشر الثقة
        final_response = self._add_confidence_indicator(
            final_response,
            formatting_context
        )

        return final_response

    def _format_quick_response(
        self,
        answer: str,
        sources: List[Dict],
        context: FormattingContext
    ) -> str:
        """تنسيق إجابة سريعة"""
        # استخراج الإجابة المختصرة
        short_answer = answer[:500] + "..." if len(answer) > 500 else answer

        # إزالة تنسيق Markdown للسرعة
        clean_answer = re.sub(r'\*+', '', short_answer)
        clean_answer = re.sub(r'#{1,6}\s*', '', clean_answer)

        return f"""# الإجابة

{clean_answer}

---
**الثقة:** {self.formatter.format_confidence_indicator(context.confidence)}
**المصادر:** {len(sources)}
"""

    def _build_formatted_response(
        self,
        answer: str,
        sources: str,
        warnings: str,
        context: FormattingContext,
        query_analysis: Optional[Dict]
    ) -> str:
        """بناء الإجابة المنسّقة"""

        # ملخص تنفيذي
        summary = answer.split('\n')[0] if '\n' in answer else answer[:200]

        # الأساس القانوني
        legal_basis = sources if sources else "لا يوجد أساس قانوني محدد في المصادر"

        # التوصيات
        recommendations = ""
        if context.intent == IntentCategory.LEGAL_ADVICE:
            recommendations = "⚠️ يُنصح باستشارة محامٍ متخصص للحصول على رأي قانوني دقيق."
        elif context.intent == IntentCategory.PROCEDURAL_GUIDANCE:
            recommendations = "📋 اتبع الإجراءات المذكورة أعلاه بدقة."
        elif context.requires_professional:
            recommendations = "⚠️ نظراً لطبيعة استفسارك، يُنصح بمراجعة محامٍ متخصص."
        else:
            recommendations = "✅ للمزيد من التفاصيل، يمكنك طرح أسئلة إضافية."

        # تنسيق حسب الأسلوب
        if context.response_style == ResponseStyle.FORMAL_LEGAL:
            return f"""# 📜 الإجابة القانونية

## الملخص
{summary}

---

## الإجابة التفصيلية
{answer}

---

## المصادر القانونية
{sources}

---

## التوصيات
{recommendations}

{warnings if warnings else ''}

---
*نظام المساعد القانوني القطري - MAX Edition*
*التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M') if hasattr(datetime, 'now') else 'غير محدد'}*
"""

        elif context.response_style == ResponseStyle.SIMPLIFIED:
            return f"""# 💡 شرح مبسّط

## ما تحتاج معرفته
{summary}

---

## الشرح
{answer}

---

## ملخص المصادر
{sources}

{warnings if warnings else ''}
"""

        else:  # DETAILED
            return f"""# 📖 إجابة مفصّلة

## السياق
{datetime.now().strftime('%Y-%m-%d') if hasattr(datetime, 'now') else ''}
**القصد المكتشف:** {context.intent.value}
**اللهجة:** {context.dialect.value}

---

## الإجابة الكاملة
{answer}

---

## المصادر القانونية
{sources}

---

## التوصيات
{recommendations}

{warnings if warnings else ''}

---
*نظام المساعد القانوني القطري - MAX Edition*
"""

    def _add_ambiguity_notice(self, response: str, ambiguities: List[AmbiguityWarning]) -> str:
        """إضافة إشعار الغموض"""
        if not ambiguities:
            return response

        notice = "\n\n---\n\n## ⚠️ ملاحظات على دقة الإجابة\n\n"
        for i, amb in enumerate(ambiguities, 1):
            severity_icon = "🔴" if amb.severity == "عالي" else "⚠️"
            notice += f"{i}. {severity_icon} **{amb.text}**: {amb.suggestion}\n"

        return response + notice

    def _add_confidence_indicator(self, response: str, context: FormattingContext) -> str:
        """إضافة مؤشر الثقة"""
        confidence_text = f"\n\n---\n\n**مؤشر الثقة:** {self.formatter.format_confidence_indicator(context.confidence)}"

        if context.has_ambiguities:
            confidence_text += " (قد تكون الإجابة غير دقيقة بسبب غموض في السؤال)"

        return response + confidence_text

    def generate_monologue(
        self,
        query: str,
        sources: List[Dict],
        formatting_context: FormattingContext,
        query_analysis: Optional[Dict] = None
    ) -> str:
        """
        توليد monologue داخلي للتفكير

        Args:
            query: سؤال المستخدم
            sources: المصادر
            formatting_context: سياق التنسيق
            query_analysis: تحليل السؤال

        Returns:
            str: monologue الداخلي
        """
        intent = formatting_context.intent
        dialect = formatting_context.dialect

        # اختيار قالب monologue المناسب
        template = INTERNAL_MONOLOGUE_TEMPLATES.get(
            intent,
            INTERNAL_MONOLOGUE_TEMPLATES[IntentCategory.GENERAL]
        )

        # تحضير المصادر
        sources_text = "\n".join([
            f"- {s.get('title', 'مصدر')} ({s.get('law', '')} - مادة {s.get('article', '')})"
            for s in sources[:5]
        ]) if sources else "لا توجد مصادر"

        # استبدال المتغيرات
        monologue = template.format(
            dialect=dialect.value,
            confidence=int(formatting_context.confidence * 100),
            domain=formatting_context.domain,
            sources=sources_text,
            sources_count=len(sources)
        )

        return monologue

    async def enhance_with_ultra_engine(
        self,
        query: str,
        response: str,
        sources: List[Dict],
        formatting_context: FormattingContext
    ) -> Tuple[str, FormattingContext]:
        """
        تحسين الإجابة باستخدام محرك الفهم اللغوي المتقدم

        Args:
            query: السؤال
            response: الإجابة
            sources: المصادر
            formatting_context: سياق التنسيق

        Returns:
            Tuple[str, FormattingContext]: الإجابة المُحسّنة والسياق المُحدّث
        """
        if not self.ultra_engine:
            return response, formatting_context

        try:
            # تحليل السؤال باستخدام المحرك المتقدم
            analysis = self.ultra_engine.analyze_legal_query(query)

            # تحديث سياق التنسيق
            dialect_mapping = {
                "خليجية": DialectType.GULF,
                "مصرية": DialectType.EGYPTIAN,
                "شامية": DialectType.LEVANTINE,
                "عراقية": DialectType.IRAQI,
                "فصحى": DialectType.MODERN_STANDARD,
            }
            formatting_context.dialect = dialect_mapping.get(
                analysis.dialect,
                DialectType.MODERN_STANDARD
            )
            formatting_context.dialect_confidence = analysis.dialect_confidence

            # تحسين جودة الإجابة
            if analysis.intent in ["استفسار", "سؤال"]:
                formatting_context.intent = IntentCategory.INFORMATION_REQUEST
            elif analysis.intent in ["استشارة", "نصيحة"]:
                formatting_context.intent = IntentCategory.LEGAL_ADVICE
            else:
                formatting_context.intent = IntentCategory.GENERAL

            formatting_context.has_ambiguities = analysis.has_ambiguity

            # إعادة تنسيق الإجابة
            enhanced_response = self.format_response(
                response,
                sources,
                formatting_context,
                query_analysis={"query": query, "ultra_analysis": analysis}
            )

            return enhanced_response, formatting_context

        except Exception as e:
            print(f"⚠ خطأ في UltraLinguisticEngine: {e}")
            return response, formatting_context

# ═══════════════════════════════════════════════════════════════════════════════
# مُصدِّر الطبقة
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    'EnhancedIntelligenceLayer',
    'LegalFormatter',
    'FormattingContext',
    'IntentAnalysis',
    'AmbiguityWarning',
    'LegalCitation',
    'IntentCategory',
    'DialectType',
    'ResponseStyle',
    'ULTRA_ENGINE_AVAILABLE',
]
