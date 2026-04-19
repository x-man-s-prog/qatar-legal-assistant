# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              Intent Intelligence Layer v2.0 — المساعد القانوني               ║
║         فهم عميق للنية + إطار دلالي + تعزيز المجال + نقد الإجابة            ║
╚══════════════════════════════════════════════════════════════════════════════╝

المراحل:
  1  — Deep Intent Classification   : 6 فئات + فهم النبرة والسياق
  2  — Mode Router                  : توجيه ذكي
  3  — Linguistic Normalization      : تحويل العامي → قانوني
  2b — Semantic Frame Extraction    : استخراج الإطار القانوني الكامل
  5  — Structured Context Injection : PRIMARY / SUPPORTING / LOW PRIORITY
  5b — Domain Boost / Relevance Override : تعزيز القانون الصحيح
  7  — Conversation Prompt
  8  — Legal Writing Prompt (مُقيَّد بصرامة)
  9  — Fail-Safe Prompt
  +  — Answer Self-Critique Layer   : مراجعة وتحسين الإجابة
"""

from __future__ import annotations
import re
import json
import logging
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

# استيراد رد قدرات النظام من قاعدة المعرفة القطرية
try:
    from core.qatar_legal_knowledge import SYSTEM_CAPABILITY_RESPONSE
except ImportError:
    SYSTEM_CAPABILITY_RESPONSE = "أنا مساعد قانوني متخصص في القانون القطري."

# ══════════════════════════════════════════════════════════════════════════════
# المرحلة 1: تصنيفات النية (6 فئات — أكثر دقة)
# ══════════════════════════════════════════════════════════════════════════════

class Intent(str, Enum):
    CONVERSATION           = "conversation"
    LEGAL_QUESTION_CLEAR   = "legal_question_clear"
    LEGAL_QUESTION_IMPLICIT= "legal_question_implicit"   # عامي / غير مباشر
    LEGAL_WRITING          = "legal_writing_request"
    EMOTIONAL_LEGAL        = "emotional_with_legal_intent"
    EMOTIONAL_NON_LEGAL    = "emotional_non_legal"

    # توافق مع الإصدار السابق
    @classmethod
    def LEGAL_QUESTION(cls):  return cls.LEGAL_QUESTION_CLEAR
    @classmethod
    def LEGAL_QUESTION_SLANG(cls): return cls.LEGAL_QUESTION_IMPLICIT
    @classmethod
    def EMOTIONAL_COMPLAINT(cls): return cls.EMOTIONAL_LEGAL

# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 1: برومبت التصنيف العميق (يفهم النبرة والسياق)
# ══════════════════════════════════════════════════════════════════════════════

INTENT_CLASSIFIER_PROMPT = """You are an expert Arabic intent detection engine.

Your job is to deeply understand user intent, not just classify keywords.

Consider:
- tone (sarcasm, anger, confusion, urgency)
- slang and dialect (Gulf, Egyptian, Levantine)
- implicit legal meaning behind emotional expressions
- conversation context

Classify into ONE of these labels:

1. conversation               — greeting, casual talk, thanks, non-legal questions
2. legal_question_clear       — clear legal question in formal or semi-formal Arabic
3. legal_question_implicit    — legal question expressed in slang, indirectly, or ambiguously
4. legal_writing_request      — request to draft a document: complaint, contract, appeal, memo
5. emotional_with_legal_intent — emotional expression that contains a legal issue (anger, injustice, loss)
6. emotional_non_legal        — pure emotional expression with NO legal dimension

Return ONLY the label. Nothing else.

Input: {user_input}"""

# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 2: برومبت Semantic Frame (الإطار الدلالي القانوني)
# ══════════════════════════════════════════════════════════════════════════════

SEMANTIC_FRAME_PROMPT = """Extract the full legal meaning from this Arabic input.

Understand the EVENT, not just the words.

Return JSON only:
{{
  "legal_issue": "the core legal problem in formal Arabic",
  "action": "what happened or what needs to happen",
  "actors": "who is involved (victim, perpetrator, party A, party B)",
  "legal_domain": "criminal | civil | labor | family | commercial | administrative | real_estate | electronic",
  "severity": "low | medium | high | critical",
  "possible_crimes_or_claims": ["claim/crime 1", "claim/crime 2"],
  "relevant_laws": ["likely applicable law 1", "likely applicable law 2"],
  "urgency": "immediate | soon | not_urgent"
}}

Input: "{user_input}"
"""

# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 3: حقن استراتيجية الإجابة داخل Reasoning Prompt
# ══════════════════════════════════════════════════════════════════════════════

ANSWER_STRATEGY_HINT = """
══ استراتيجية الإجابة (قرر قبل أن تكتب) ══

قبل الإجابة، حدد نوع الطلب:
• معلوماتي (يريد معرفة حكم أو قانون)      → أجب بالنص + التفسير
• استشاري (يريد رأياً في موقفه)             → أجب بالحكم + التطبيق على حالته
• إجرائي (يريد خطوات عملية للتصرف)         → أجب بقائمة خطوات مرتبة + الجهات المختصة

اختر الأسلوب الأنسب وطبّقه في الإجابة كاملاً.
"""

# ══════════════════════════════════════════════════════════════════════════════
# برومبت التطبيع اللغوي (المرحلة 3)
# ══════════════════════════════════════════════════════════════════════════════

LINGUISTIC_NORMALIZATION_PROMPT = """حوّل النص التالي إلى استعلام قانوني رسمي دقيق باللغة العربية.

التعليمات:
- افهم الحدث والمعنى الحقيقي خلف الكلمات العامية أو العاطفية
- وسّع المعنى وحدد الإطار القانوني المناسب
- اجعل الاستعلام مناسباً للبحث في قاعدة بيانات قانونية

أمثلة:
النص: "واحد ضربني وابغى اشتكي عليه"
الاستعلام: "ما هي الإجراءات القانونية لتقديم شكوى في جريمة الاعتداء الجسدي وفق قانون العقوبات القطري؟"

النص: "مديري ما يصرف راتبي من شهرين"
الاستعلام: "ما هي حقوق العامل عند تأخر صاحب العمل عن صرف الراتب وفق قانون العمل القطري؟"

النص: "ماتعرف ترد؟"
الاستعلام: "تقييم مستوى الخدمة أو الأداء المهني — استفسار عام"

النص: {user_input}
الاستعلام:"""

# ══════════════════════════════════════════════════════════════════════════════
# المرحلة 7: Conversation Mode
# ══════════════════════════════════════════════════════════════════════════════

CONVERSATION_SYSTEM = """أنت مساعد عربي طبيعي ودود.

- رُدّ كالإنسان بدون أي قالب قانوني
- اجعل اللغة دافئة وطبيعية تناسب لهجة المستخدم
- إذا لاحظت أن السؤال فيه بُعد قانوني ولو خفي، اعرض مساعدتك القانونية بشكل طبيعي
- لا تستخدم أقساماً أو تنسيق رسمي
- إذا كان المستخدم يسأل عن قدراتك أو هويتك، أجب بصدق وبشكل مختصر"""

# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 4: Legal Writing Mode المُقيَّد بصرامة
# ══════════════════════════════════════════════════════════════════════════════

LEGAL_WRITING_SYSTEM = """You are a professional Qatari lawyer writing court-level legal documents.

STRICT RULES — NO EXCEPTIONS:
- Use formal legal Arabic ONLY
- NO explanations or commentary
- NO conversational tone
- NO summaries or notes outside the document structure
- Write as if submitting directly to a judge or official authority

MANDATORY STRUCTURE (adapt based on document type):

For complaints and petitions (شكاوى وعرائض):
أولاً: الوقائع
[سرد الأحداث بصيغة قانونية رسمية مرتبة زمنياً]

ثانياً: الأساس القانوني
[المواد القانونية المنطبقة مع أرقامها وسنواتها]

ثالثاً: الدفوع
[الحجج القانونية المدعومة بالنصوص]

رابعاً: الطلبات
[الطلبات المحددة والواضحة للجهة المختصة]

For contracts (عقود):
[أطراف العقد — محل العقد — الشروط والأحكام — التوقيعات]

For appeals and memos (استئنافات ومذكرات):
[الوقائع — أسباب الطعن — الأسانيد — الطلبات]

Failure to follow this structure is unacceptable."""

# ══════════════════════════════════════════════════════════════════════════════
# المرحلة 9: Fail-Safe
# ══════════════════════════════════════════════════════════════════════════════

FALLBACK_REASONING_SYSTEM = """أنت مستشار قانوني قطري خبير.

لم يُعثر على نص قانوني مباشر في قاعدة البيانات، لكن يجب أن تُجيب بكفاءة.

قواعد الاستنتاج:
1. حدد الفئة القانونية (جنائي، مدني، عمالي، أسرة، تجاري...)
2. طبّق المبادئ القانونية العامة المعروفة في القانون القطري
3. استرشد بروح القانون والفقه المقارن إن لزم
4. لا تقل أبداً "لم أجد نتائج" — قدّم إجابة مفيدة دائماً

هيكل الإجابة:
**التكييف القانوني:** [تصنيف الموضوع والمجال]
**الإطار القانوني العام:** [المبادئ والقواعد المنطبقة]
**التحليل:** [تطبيق المبادئ على الحالة]
**التوصية العملية:** [ماذا يفعل الشخص خطوة بخطوة؟]
**ملاحظة:** مبني على المبادئ القانونية العامة — للتأكيد: بوابة الميزان (almeezan.qa) أو مستشار قانوني."""

# ══════════════════════════════════════════════════════════════════════════════
# الإضافة الذهبية: Answer Self-Critique Layer
# ══════════════════════════════════════════════════════════════════════════════

SELF_CRITIQUE_PROMPT = """أنت محكّم قانوني متخصص. راجع هذه الإجابة القانونية وحسّنها.

تحقق من:
1. صحة القانون المذكور (هل المادة صحيحة وذات صلة؟)
2. الصلة بالسؤال (هل الإجابة تجيب على ما سُئل فعلاً؟)
3. الوضوح (هل يستطيع غير المختص فهمها؟)
4. العمق (هل تناولت الاستثناءات والحالات الخاصة؟)

إذا كانت الإجابة ضعيفة في أي نقطة → أعد كتابة النسخة المحسّنة كاملاً.
إذا كانت جيدة → أعدها كما هي بدون تعديل.

السؤال الأصلي: {question}

الإجابة للمراجعة:
{answer}

الإجابة المحسّنة:"""

# ══════════════════════════════════════════════════════════════════════════════
# خريطة المجال → القانون الرئيسي (الإصلاح 5: Domain Boost)
# ══════════════════════════════════════════════════════════════════════════════

_DOMAIN_PRIMARY_LAWS = {
    "criminal":       ["قانون العقوبات", "قانون الإجراءات الجنائية", "عقوبات"],
    "labor":          ["قانون العمل", "عمل", "علاقات عمل"],
    "family":         ["قانون الأسرة", "أحوال شخصية", "أسرة"],
    "civil":          ["القانون المدني", "مدني", "التزامات"],
    "commercial":     ["قانون التجارة", "تجاري", "شركات"],
    "administrative": ["قانون الإجراءات الإدارية", "إداري"],
    "real_estate":    ["قانون التسجيل العقاري", "عقارات", "إيجار"],
    "electronic":     ["قانون مكافحة الجرائم الإلكترونية", "جرائم إلكترونية", "معلوماتية"],
}

# ══════════════════════════════════════════════════════════════════════════════
# كلمات تصنيف (Rule-based fallback)
# ══════════════════════════════════════════════════════════════════════════════

_SLANG_MARKERS = {
    'وش', 'ايش', 'شو', 'ليش', 'بش', 'شلون', 'وين', 'منو',
    'ابغى', 'بغيت', 'ودي', 'حاب', 'بدي', 'عايز', 'عاوز',
    'والله', 'يخوي', 'يبعد', 'زين', 'مرة', 'بس', 'اكو',
    'واحد', 'ضربني', 'شتمني', 'يسوي', 'اشتكي', 'اشكو',
    'اطالب', 'اجيب', 'اروح', 'امشي', 'جار', 'بيت',
    'مدير', 'كفيل', 'صاحبي', 'خوي',
}

_WRITING_MARKERS = {
    'اكتب', 'صيغ', 'صياغة', 'عريضة', 'مذكرة',
    'رسالة رسمية', 'طلب رسمي',
    'وثيقة', 'استدعاء', 'بلاغ رسمي',
    'draft', 'formulate', 'compose',
}

# هذه الكلمات تشير للكتابة فقط إذا اقترنت بفعل صياغة
_WRITING_NOUNS_CONDITIONAL = {
    'عقد', 'اتفاقية', 'استئناف', 'إخطار', 'إنذار', 'عريضة دعوى',
}

_WRITING_VERBS = {'اكتب', 'اكتبي', 'صيغ', 'صغ', 'صغي', 'اصغ', 'صياغة', 'حرر', 'حرري', 'أعد', 'أعدي', 'ضع', 'ضعي'}

# شكوى بدون كتابة مصنّفة emotional
_COMPLAINT_FILING = {'شكوى', 'تقديم شكوى', 'رفع شكوى'}

_EMOTIONAL_MARKERS = {
    'ظلمني', 'ظالم', 'أظلم', 'حقي ضاع', 'خسرت', 'سرقوا',
    'ما أنصفوني', 'ما عطوني', 'حقوقي', 'غلط عليّ',
    'فصلوني', 'طردوني', 'ما دفعوا', 'ما ردوا', 'خانني',
    'أبكي', 'محتاج مساعدة', 'خايف', 'تعبت', 'ماتعرف',
    'ماعرف', 'ما عندي', 'والله ظلموني',
}

_CONVERSATION_MARKERS = {
    'السلام عليكم', 'وعليكم السلام', 'مرحبا', 'هلا والله',
    'يسلمو', 'شكراً', 'شكرا', 'أحسنت', 'بارك الله',
    'هاي', 'كيف حالك', 'من أنت', 'ما اسمك', 'كيف تعمل',
    'وداعاً', 'مع السلامة', 'باي', 'هل أنت',
    # أسئلة القدرات والهوية (بالعربية الفصحى)
    'يمكنك', 'قدراتك', 'مهامك', 'وظيفتك', 'تستطيع أن تفعل',
    'ماذا تستطيع', 'ما أنت', 'ما هو دورك', 'تساعدني في',
    'ماذا يمكنك', 'ما الذي تقدر', 'ما المهام',
}


def classify_intent_rule_based(text: str) -> Intent:
    """تصنيف سريع بالقواعد — يُستخدم كـ fallback عند غياب LLM."""
    t = text.strip().lower()
    words = set(re.findall(r'\w+', t))

    # كتابة رسمية (تتقدم على الشكوى العاطفية)
    _has_writing_verb = any(v in t for v in _WRITING_VERBS)
    for marker in _WRITING_MARKERS:
        if marker in t:
            return Intent.LEGAL_WRITING
    # الأسماء المشروطة: تحتاج فعل صياغة
    for noun in _WRITING_NOUNS_CONDITIONAL:
        if noun in t and _has_writing_verb:
            return Intent.LEGAL_WRITING
    for marker in _COMPLAINT_FILING:
        if marker in t and _has_writing_verb:
            return Intent.LEGAL_WRITING

    # محادثة
    for marker in _CONVERSATION_MARKERS:
        if marker in t:
            return Intent.CONVERSATION

    # عاطفي قانوني
    emotional_hits = sum(1 for m in _EMOTIONAL_MARKERS if m in t)
    if emotional_hits >= 1:
        return Intent.EMOTIONAL_LEGAL

    # عامي قانوني
    slang_hits = sum(1 for m in _SLANG_MARKERS if m in words)
    if slang_hits >= 1:
        return Intent.LEGAL_QUESTION_IMPLICIT

    return Intent.LEGAL_QUESTION_CLEAR


async def classify_intent(
    text: str,
    llm_caller=None,
    history: list = None,
) -> Intent:
    """
    المرحلة 1: تصنيف النية العميق (6 فئات).
    يستخدم LLM إن توفر، وإلا يرجع للقواعد.
    """
    if not text or not text.strip():
        return Intent.CONVERSATION

    if llm_caller:
        try:
            # PRECISION 3: inject short-term memory (last 3 user messages)
            _ctx_snippet = ""
            if history:
                _recent_user = [
                    m["content"][:120]
                    for m in history[-6:]
                    if m.get("role") == "user"
                ][-3:]
                if _recent_user:
                    _ctx_snippet = "\n\nسياق المحادثة السابقة (آخر 3 رسائل):\n" + "\n".join(
                        f"- {t}" for t in _recent_user
                    )
            prompt = INTENT_CLASSIFIER_PROMPT.format(user_input=text.strip() + _ctx_snippet)
            msgs = [{"role": "user", "content": prompt}]
            raw = await llm_caller("", msgs)
            raw = raw.strip().lower().replace('"', '').replace("'", "").strip()

            mapping = {
                "conversation":                Intent.CONVERSATION,
                "legal_question_clear":        Intent.LEGAL_QUESTION_CLEAR,
                "legal_question_implicit":     Intent.LEGAL_QUESTION_IMPLICIT,
                "legal_writing_request":       Intent.LEGAL_WRITING,
                "emotional_with_legal_intent": Intent.EMOTIONAL_LEGAL,
                "emotional_non_legal":         Intent.EMOTIONAL_NON_LEGAL,
                # توافق مع الإصدار القديم
                "legal_question_slang":        Intent.LEGAL_QUESTION_IMPLICIT,
                "emotional_or_complaint":      Intent.EMOTIONAL_LEGAL,
                # أرقام احتياطية
                "1": Intent.CONVERSATION,
                "2": Intent.LEGAL_QUESTION_CLEAR,
                "3": Intent.LEGAL_QUESTION_IMPLICIT,
                "4": Intent.LEGAL_WRITING,
                "5": Intent.EMOTIONAL_LEGAL,
                "6": Intent.EMOTIONAL_NON_LEGAL,
            }
            for key, intent in mapping.items():
                if key in raw:
                    log.info("intent_router [LLM]: %s", intent.value)
                    return intent

        except Exception as e:
            log.debug("intent_router LLM fallback: %s", e)

    result = classify_intent_rule_based(text)
    log.info("intent_router [rules]: %s", result.value)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# المرحلة 2: Mode Router
# ══════════════════════════════════════════════════════════════════════════════

def route_mode(intent: Intent) -> str:
    """
    يحدد وضع التنفيذ.
    Returns: "conversation" | "legal_pipeline" | "legal_writing" | "emotional_legal"
    """
    if intent in (Intent.CONVERSATION, Intent.EMOTIONAL_NON_LEGAL):
        return "conversation"
    elif intent in (Intent.LEGAL_QUESTION_CLEAR, Intent.LEGAL_QUESTION_IMPLICIT):
        return "legal_pipeline"
    elif intent == Intent.LEGAL_WRITING:
        return "legal_writing"
    elif intent == Intent.EMOTIONAL_LEGAL:
        return "emotional_legal"
    return "legal_pipeline"


# ══════════════════════════════════════════════════════════════════════════════
# المرحلة 3: Linguistic Normalization
# ══════════════════════════════════════════════════════════════════════════════

async def normalize_to_legal_query(text: str, llm_caller=None) -> str:
    """يحوّل العامي/العاطفي → استعلام قانوني رسمي قبل RAG."""
    if not llm_caller or not text.strip():
        return text
    try:
        prompt = LINGUISTIC_NORMALIZATION_PROMPT.format(user_input=text.strip())
        msgs = [{"role": "user", "content": prompt}]
        normalized = (await llm_caller("", msgs)).strip()
        if len(normalized) >= 15 and normalized != text.strip():
            log.info("normalize: '%s' → '%s'", text[:40], normalized[:60])
            return normalized
    except Exception as e:
        log.debug("normalize error: %s", e)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 2: Semantic Frame Extraction
# ══════════════════════════════════════════════════════════════════════════════

async def extract_legal_meaning(text: str, llm_caller=None, history: list = None) -> dict:
    """
    يستخرج الإطار الدلالي القانوني الكامل من نص المستخدم.

    Returns
    -------
    dict مع مفاتيح: legal_issue, action, actors, legal_domain,
                    severity, possible_crimes_or_claims, relevant_laws, urgency
    """
    _empty = {
        "legal_issue": text, "action": "", "actors": "",
        "legal_domain": "unknown", "severity": "medium",
        "possible_crimes_or_claims": [], "relevant_laws": [], "urgency": "not_urgent",
    }
    if not llm_caller or not text.strip():
        return _empty

    try:
        # PRECISION 3: inject short-term memory context
        _ctx_hint = ""
        if history:
            _recent = [
                m["content"][:100]
                for m in history[-6:]
                if m.get("role") == "user"
            ][-3:]
            if _recent:
                _ctx_hint = "\n\nسياق سابق: " + " | ".join(_recent)
        prompt = SEMANTIC_FRAME_PROMPT.format(user_input=text.strip() + _ctx_hint)
        msgs = [{"role": "user", "content": prompt}]
        raw = (await llm_caller("", msgs)).strip()

        # استخرج JSON من الرد
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            frame = json.loads(json_match.group())
            log.info("semantic_frame: domain=%s severity=%s",
                     frame.get("legal_domain","?"), frame.get("severity","?"))
            return frame
    except Exception as e:
        log.debug("extract_legal_meaning error: %s", e)

    return _empty


# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 5: Domain Boost / Relevance Override
# ══════════════════════════════════════════════════════════════════════════════

def apply_domain_boost(chunks: list[dict], legal_domain: str) -> list[dict]:
    """
    يعيد ترتيب النصوص بتعزيز القوانين الأنسب للمجال المكتشف.

    مثال: domain=criminal → قانون العقوبات يحصل على تعزيز إضافي.

    Parameters
    ----------
    chunks       : النصوص المسترجعة
    legal_domain : المجال من extract_legal_meaning أو CoT

    Returns
    -------
    list مرتبة بعد تطبيق boost
    """
    if not legal_domain or legal_domain == "unknown" or not chunks:
        return chunks

    primary_laws = _DOMAIN_PRIMARY_LAWS.get(legal_domain.lower(), [])
    if not primary_laws:
        # حاول تطابق جزئي
        for domain_key, laws in _DOMAIN_PRIMARY_LAWS.items():
            if domain_key in legal_domain.lower() or legal_domain.lower() in domain_key:
                primary_laws = laws
                break

    if not primary_laws:
        return chunks

    def _boost_score(chunk: dict) -> float:
        base = float(chunk.get("dre_score") or chunk.get("score") or 0)
        law_name = (chunk.get("law_name") or "").lower()
        for law_hint in primary_laws:
            if law_hint.lower() in law_name:
                boosted = base + 0.20
                log.info("domain_boost: +0.20 → %s (domain=%s)", law_name[:40], legal_domain)
                return boosted
        return base

    return sorted(chunks, key=_boost_score, reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# المرحلة 5: Structured Context Injection
# ══════════════════════════════════════════════════════════════════════════════

def build_structured_context(
    chunks: list[dict],
    max_content: int = 700,
    top_k: int = 5,
) -> str:
    """يبني السياق بثلاث طبقات: [PRIMARY] / [SUPPORTING] / [LOW PRIORITY]."""
    chunks = chunks[:top_k]
    if not chunks:
        return ""

    scores  = [float(c.get("dre_score") or c.get("score") or 0) for c in chunks]
    max_s   = max(scores) if scores else 1.0
    primary, supporting, low = [], [], []

    for chunk, score in zip(chunks, scores):
        ratio = score / max_s if max_s > 0 else 0
        entry = _format_chunk(chunk, max_content)
        if ratio >= 0.75:
            primary.append(entry)
        elif ratio >= 0.45:
            supporting.append(entry)
        else:
            low.append(entry)

    parts = []
    if primary:
        parts.append("[PRIMARY — النصوص الأكثر صلة]\n" + "\n\n".join(primary))
    if supporting:
        parts.append("[SUPPORTING — نصوص داعمة]\n" + "\n\n".join(supporting))
    if low:
        parts.append("[LOW PRIORITY — صلة محدودة]\n" + "\n\n".join(low))

    return ("\n\n" + "─" * 50 + "\n\n").join(parts)


def _format_chunk(chunk: dict, max_content: int) -> str:
    law_name   = chunk.get("law_name", "")
    law_number = chunk.get("law_number", "")
    law_year   = chunk.get("law_year", "")
    article    = chunk.get("article_number", "")
    content    = (chunk.get("content") or "")[:max_content]
    score      = round(float(chunk.get("dre_score") or chunk.get("score") or 0), 3)

    header = f"▶▶ {law_name}"
    if law_number: header += f" — القانون رقم {law_number}"
    if law_year:   header += f" لسنة {law_year}"
    if article:    header += f" | المادة {article}"
    header += f" [صلة: {score}]"
    return f"{header}\n{content}"


# ══════════════════════════════════════════════════════════════════════════════
# الإضافة الذهبية: Answer Self-Critique
# ══════════════════════════════════════════════════════════════════════════════

async def self_critique_answer(
    question: str,
    answer: str,
    llm_caller=None,
    max_tokens: int = 2000,
) -> str:
    """
    يراجع الإجابة القانونية ويحسّنها إذا كانت ضعيفة.

    يُستخدم فقط مع الأسئلة القانونية المعقدة (complexity != بسيط).
    لا يُستخدم مع المحادثة أو الكتابة القانونية.
    """
    if not llm_caller or not answer.strip() or len(answer) < 100:
        return answer

    # لا نُشغّل النقد على إجابات قصيرة جداً أو رسائل الخطأ
    if any(phrase in answer for phrase in ["لم أجد", "لم أتمكن", "خطأ", "error"]):
        return answer

    try:
        prompt = SELF_CRITIQUE_PROMPT.format(
            question=question.strip(),
            answer=answer.strip()
        )
        msgs = [{"role": "user", "content": prompt}]
        improved = (await llm_caller("", msgs)).strip()

        if improved and len(improved) >= len(answer) * 0.5:
            log.info("self_critique: improved answer (len %d → %d)", len(answer), len(improved))
            return improved
    except Exception as e:
        log.debug("self_critique error: %s", e)

    return answer


# ══════════════════════════════════════════════════════════════════════════════
# دوال مساعدة للـ Prompts
# ══════════════════════════════════════════════════════════════════════════════

def get_mode_system_prompt(mode: str, base_expert_system: str) -> str:
    """يعيد system prompt المناسب + حقن استراتيجية الإجابة للأوضاع القانونية."""
    if mode == "conversation":
        return CONVERSATION_SYSTEM
    elif mode == "legal_writing":
        return LEGAL_WRITING_SYSTEM
    else:
        # حقن استراتيجية الإجابة في الـ system prompt القانوني
        return base_expert_system + ANSWER_STRATEGY_HINT


def get_fallback_system() -> str:
    return FALLBACK_REASONING_SYSTEM


def build_legal_writing_prompt(user_request: str, context: str = "") -> str:
    msg = f"الطلب: {user_request}\n\n"
    if context:
        msg += f"الأسانيد القانونية المتاحة:\n{context}\n\n"
    msg += "صِغ الوثيقة وفق الهيكل الإلزامي المحدد. لا شرح ولا تعليق."
    return msg


def build_emotional_to_legal_prompt(user_input: str, normalized_query: str, semantic_frame: dict = None) -> str:
    """يبني prompt يفهم الموقف العاطفي ثم يُجيب قانونياً بدفء."""
    frame_info = ""
    if semantic_frame and semantic_frame.get("legal_issue"):
        frame_info = (
            f"\nالتحليل التلقائي للموقف:"
            f"\n• المسألة القانونية: {semantic_frame.get('legal_issue','')}"
            f"\n• المجال: {semantic_frame.get('legal_domain','')}"
            f"\n• الخطورة: {semantic_frame.get('severity','')}"
        )

    return (
        f"الموقف كما وصفه الشخص:\n\"{user_input}\"\n"
        f"{frame_info}\n\n"
        f"الاستعلام القانوني المكافئ:\n\"{normalized_query}\"\n\n"
        f"تعليمات الإجابة:\n"
        f"• ابدأ بجملة واحدة دافئة تُظهر الفهم والتعاطف\n"
        f"• ثم وضّح الحقوق القانونية المنطبقة بوضوح\n"
        f"• ثم قدّم الخطوات العملية للمطالبة بهذه الحقوق\n"
        f"• اذكر الجهة المختصة للتقديم"
    )


# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 1: Source Trust Control — التحقق من مصداقية المصادر
# ══════════════════════════════════════════════════════════════════════════════

# الخريطة الإلزامية: المجال → القوانين المسموح بها فقط كمصادر رئيسية
_DOMAIN_ALLOWED_LAWS: dict[str, list[str]] = {
    "criminal":       ["قانون العقوبات", "الإجراءات الجنائية", "الإجراءات الجزائية",
                       "مكافحة الجرائم", "قانون الأحداث"],
    "labor":          ["قانون العمل", "علاقات العمل", "العمالة المنزلية",
                       "الخدمة المدنية", "الضمان الاجتماعي"],
    "family":         ["قانون الأسرة", "الأحوال الشخصية", "الولاية", "الميراث",
                       "الأحداث", "النسب"],
    "civil":          ["القانون المدني", "الالتزامات والعقود", "الإثبات",
                       "التنفيذ القضائي"],
    "commercial":     ["قانون التجارة", "الشركات التجارية", "الإفلاس",
                       "السجل التجاري", "الوساطة التجارية"],
    "administrative": ["الإجراءات الإدارية", "مجلس الدولة", "التظلمات",
                       "الخدمة المدنية", "المناقصات والمزايدات"],
    "real_estate":    ["التسجيل العقاري", "الإيجار", "الملكية", "تنظيم المدن",
                       "البناء والتشييد"],
    "electronic":     ["مكافحة الجرائم الإلكترونية", "المعاملات الإلكترونية",
                       "حماية البيانات", "الاتصالات"],
}

# نصوص "مرتبطة شكلياً" تُشير إلى قوانين إجرائية/عامة — تُخفَّض أولويتها
_PROCEDURAL_LAW_MARKERS = [
    "الإجراءات الجنائية", "الإجراءات المدنية", "الإجراءات الإدارية",
    "التجارية", "اللوائح", "المراسيم", "القرارات الوزارية",
]


def validate_primary_source(
    chunks: list[dict],
    domain: str,
    strict: bool = False,
) -> list[dict]:
    """
    Source Trust Control: يُصفّي ويُعيد ترتيب المصادر حسب ملاءمتها للمجال.

    المنطق:
    - القوانين المطابقة للمجال → تحتفظ بدرجتها أو تُعزَّز
    - القوانين الإجرائية/العامة → تُخفَّض درجتها
    - وضع strict=True → يُزيل ما لا صلة له كلياً

    Parameters
    ----------
    chunks  : النصوص بعد DRE وDomain Boost
    domain  : المجال القانوني (من semantic_frame أو CoT)
    strict  : إذا True يُزيل النصوص غير المطابقة (للمسائل الجنائية والعمالية)
    """
    if not domain or domain == "unknown" or not chunks:
        return chunks

    allowed = _DOMAIN_ALLOWED_LAWS.get(domain.lower(), [])
    if not allowed:
        # بحث بالتطابق الجزئي
        for dk, laws in _DOMAIN_ALLOWED_LAWS.items():
            if dk in domain.lower() or domain.lower() in dk:
                allowed = laws
                break

    if not allowed:
        return chunks

    scored = []
    for chunk in chunks:
        law_name = (chunk.get("law_name") or "").lower()
        base     = float(chunk.get("dre_score") or chunk.get("score") or 0)

        # هل ينتمي لمجال آخر واضح؟
        is_mismatch = False
        for other_domain, other_laws in _DOMAIN_ALLOWED_LAWS.items():
            if other_domain == domain.lower():
                continue
            if any(law.lower() in law_name for law in other_laws[:3]):
                is_mismatch = True
                break

        # هل من القوانين المسموح بها؟
        is_allowed = any(law.lower() in law_name for law in allowed)

        # هل قانون إجرائي؟
        is_procedural = any(m.lower() in law_name for m in _PROCEDURAL_LAW_MARKERS)

        if strict and is_mismatch and not is_allowed:
            log.info("source_trust: حذف '%s' (domain=%s)", law_name[:40], domain)
            continue

        # تعديل الدرجة
        if is_allowed and not is_procedural:
            adjusted = base + 0.15
        elif is_procedural and not is_allowed:
            adjusted = base - 0.10
        elif is_mismatch:
            adjusted = base - 0.20
        else:
            adjusted = base

        chunk = dict(chunk)  # نسخة لتجنب التعديل في المكان
        chunk["_trust_score"] = round(adjusted, 3)
        scored.append(chunk)

    # إذا strict أزال كل شيء → أعد الأصلي
    if not scored:
        log.warning("source_trust strict: لم يبق شيء — نعيد الأصلي")
        return chunks

    return sorted(scored, key=lambda c: c.get("_trust_score", 0), reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 2: Contradiction Detection — كشف التناقض بين الاستشهاد والاستنتاج
# ══════════════════════════════════════════════════════════════════════════════

ALIGNMENT_CHECK_PROMPT = """تحقق أن الاستنتاج القانوني في هذه الإجابة مدعوم فعلاً بالنصوص القانونية المستشهد بها.

تحقق من:
1. هل القانون المذكور يدعم فعلاً الاستنتاج المذكور؟
2. هل رقم المادة مستخدم بشكل صحيح؟
3. هل هناك فجوة منطقية بين نص القانون والاستنتاج؟

إذا وجدت تناقضاً:
- أصلح الاستدلال ليتوافق مع القانون
- أو استبدل الاستنتاج غير المدعوم بعبارة حذرة
- لا تخترع مراجع قانونية جديدة

إذا كانت الإجابة صحيحة:
- أعدها كما هي بدون تعديل

قواعد إلزامية:
- أجب بالعربية فقط — لا تستخدم أي كلمة إنجليزية مطلقاً
- لا تبدأ بعبارات مثل "The provided answer" أو أي جملة إنجليزية
- أعد الإجابة كنص عربي كامل جاهز للعرض على المستخدم

الإجابة للتحقق:
{answer}

النصوص القانونية المسترجعة (المرجع):
{context}

الإجابة المُدققة:"""


async def check_alignment(
    answer: str,
    chunks: list[dict],
    question: str,
    llm_caller=None,
    max_tokens: int = 2500,
) -> str:
    """
    يتحقق أن الاستنتاج القانوني مدعوم فعلاً بنصوص المصادر.
    يُصلح التناقضات تلقائياً.
    """
    if not llm_caller or not answer.strip() or not chunks:
        return answer

    # بناء ملخص مختصر للنصوص (لتجنب overflow)
    context_summary = "\n\n".join(
        f"[{c.get('law_name','')} | م.{c.get('article_number','')}]: "
        f"{(c.get('content') or '')[:300]}"
        for c in chunks[:5]
    )

    try:
        prompt = ALIGNMENT_CHECK_PROMPT.format(
            answer=answer.strip(),
            context=context_summary,
        )
        msgs = [{"role": "user", "content": prompt}]
        fixed = (await llm_caller("", msgs)).strip()

        if fixed and len(fixed) >= len(answer) * 0.4:
            log.info("alignment_check: answer verified/fixed (len %d→%d)", len(answer), len(fixed))
            return fixed
    except Exception as e:
        log.debug("check_alignment error: %s", e)

    return answer


# ══════════════════════════════════════════════════════════════════════════════
# الإصلاح 3: User Awareness Layer — تكيّف الإجابة مع مستوى المستخدم
# ══════════════════════════════════════════════════════════════════════════════

USER_LEVEL_PROMPT = """Detect the user's legal knowledge level from this Arabic text.

Base your judgment on:
- vocabulary sophistication
- question depth and specificity
- use of legal terminology
- whether they cite laws or articles

Return ONE label only:
- beginner    (عامي، لغة بسيطة، لا مصطلحات)
- intermediate (يفهم بعض القانون، لغة معتدلة)
- expert      (محامٍ، قاضٍ، طالب قانون، يستخدم مصطلحات دقيقة)

Input: {user_input}"""

# أنماط سريعة للكشف بدون LLM
_EXPERT_MARKERS = {
    'المادة', 'القانون رقم', 'الفقرة', 'البند', 'لسنة', 'المشرع',
    'التكييف', 'الاستئناف', 'التمييز', 'محكمة', 'النيابة',
    'الدعوى', 'المدعي', 'المدعى عليه', 'الحكم الابتدائي',
    'السند القانوني', 'الاجتهاد القضائي',
}
_INTERMEDIATE_MARKERS = {
    'حق', 'حقوقي', 'قانوني', 'قانون', 'شكوى', 'محكمة',
    'عقوبة', 'غرامة', 'عقد', 'اتفاقية', 'طلاق', 'نفقة',
    'توثيق', 'مستشار', 'محامي',
}


def detect_user_level_rule_based(text: str) -> str:
    """كشف سريع لمستوى المستخدم بالقواعد."""
    t = text.strip()
    words = set(re.findall(r'\w+', t))
    word_count = len(t.split())

    expert_hits     = sum(1 for m in _EXPERT_MARKERS if m in t)
    intermediate_hits = sum(1 for m in _INTERMEDIATE_MARKERS if m in words)

    if expert_hits >= 2:
        return "expert"
    if intermediate_hits >= 2 or (word_count >= 20 and intermediate_hits >= 1):
        return "intermediate"
    return "beginner"


async def detect_user_level(text: str, llm_caller=None) -> str:
    """
    يكشف مستوى المستخدم القانوني: beginner | intermediate | expert
    """
    if llm_caller:
        try:
            prompt = USER_LEVEL_PROMPT.format(user_input=text.strip())
            msgs = [{"role": "user", "content": prompt}]
            raw = (await llm_caller("", msgs)).strip().lower()
            for level in ("expert", "intermediate", "beginner"):
                if level in raw:
                    log.info("user_level [LLM]: %s", level)
                    return level
        except Exception as e:
            log.debug("detect_user_level error: %s", e)

    level = detect_user_level_rule_based(text)
    log.info("user_level [rules]: %s", level)
    return level


def get_user_aware_instruction(level: str) -> str:
    """
    يُعيد تعليمة مُدمجة في user_msg تُخبر النموذج بكيفية تكييف الإجابة.
    """
    if level == "expert":
        return (
            "\n[مستوى المستخدم: خبير قانوني]\n"
            "اختصر الشرح الأساسي، عمّق التحليل، استخدم المصطلحات القانونية الدقيقة، "
            "ناقش الاستثناءات والاجتهادات القضائية إن وُجدت.\n"
        )
    elif level == "intermediate":
        return (
            "\n[مستوى المستخدم: متوسط]\n"
            "اشرح المصطلحات القانونية عند ذكرها لأول مرة، "
            "وازن بين الدقة القانونية والوضوح العملي.\n"
        )
    else:  # beginner
        return (
            "\n[مستوى المستخدم: عامي]\n"
            "استخدم لغة بسيطة واضحة، تجنب المصطلحات المعقدة أو اشرحها فوراً، "
            "ركّز على الخطوات العملية وماذا يفعل الشخص.\n"
        )


# ══════════════════════════════════════════════════════════════════════════════
# الإضافة الذهبية: Multi-Query Reasoning — استعلامات متعددة من semantic_frame
# ══════════════════════════════════════════════════════════════════════════════

def build_multi_queries(
    normalized_q: str,
    semantic_frame: dict,
    cot_queries: list[str],
) -> list[str]:
    """
    يبني قائمة استعلامات متنوعة من مصادر مختلفة للحصول على تغطية أشمل.

    المصادر:
    1. normalized_q            — الاستعلام المطبَّع
    2. semantic_frame.legal_issue — المسألة القانونية المستخرجة
    3. semantic_frame.action      — الفعل/الحدث
    4. semantic_frame.possible_crimes_or_claims — الجرائم/المطالبات المحتملة
    5. cot_queries             — استعلامات CoT

    Returns
    -------
    list[str]: استعلامات مدمجة ومُزالة التكرار (max 8)
    """
    queries = []

    # 1. الاستعلام المطبَّع أولاً
    if normalized_q and normalized_q.strip():
        queries.append(normalized_q.strip())

    # 2. المسألة القانونية من semantic_frame
    legal_issue = (semantic_frame.get("legal_issue") or "").strip()
    if legal_issue and legal_issue != normalized_q:
        queries.append(legal_issue)

    # 3. الفعل/الحدث
    action = (semantic_frame.get("action") or "").strip()
    if action and len(action) > 5:
        queries.append(action)

    # 4. الجرائم أو المطالبات المحتملة
    claims = semantic_frame.get("possible_crimes_or_claims") or []
    for claim in claims[:2]:
        if claim and claim.strip():
            queries.append(claim.strip())

    # 5. استعلامات CoT
    for q in (cot_queries or []):
        if q and q.strip():
            queries.append(q.strip())

    # إزالة التكرار مع الحفاظ على الترتيب، max 8
    seen = set()
    unique = []
    for q in queries:
        key = q[:60].lower()
        if key not in seen and len(q) > 3:
            seen.add(key)
            unique.append(q)
        if len(unique) >= 8:
            break

    log.info("multi_queries: %d استعلام من normalized+frame+cot", len(unique))
    return unique


# ══════════════════════════════════════════════════════════════════════════════
# PRECISION 1: Pre-Generation Risk Control
# يُحدد استراتيجية التوليد بناءً على مستوى الخطر
# ══════════════════════════════════════════════════════════════════════════════

def adjust_generation_strategy(
    semantic_frame: dict,
    complexity: str = "بسيط",
    ambiguity_score: float = 0.0,
    confidence_score: float = 100.0,
) -> dict:
    """
    يُحلل عوامل الخطر ويُعيد استراتيجية التوليد المثلى.

    Returns
    -------
    dict:
        temperature  : float — درجة حرارة التوليد (أقل = أكثر تحفظاً)
        strict_mode  : bool  — أضف تعليمات صرامة للـ prompt
        max_tokens_cap: int | None — قيّد الإجابة إذا كان الخطر مرتفعاً
        conservative_note: str — نص تحذير يُحقن في user_msg
    """
    strategy = {
        "temperature": 0.3,
        "strict_mode": False,
        "max_tokens_cap": None,
        "conservative_note": "",
    }

    risk_score = 0.0

    # عامل 1: تعقيد السؤال
    if complexity == "معقد":
        risk_score += 0.3
    elif complexity == "متوسط":
        risk_score += 0.15

    # عامل 2: غموض المدخل
    if ambiguity_score > 0.5:
        risk_score += 0.25
    elif ambiguity_score > 0.3:
        risk_score += 0.10

    # عامل 3: ثقة الاسترجاع منخفضة
    if confidence_score < 60:
        risk_score += 0.30
    elif confidence_score < 75:
        risk_score += 0.15

    # عامل 4: مجال حساس (جنائي/أسرة) يتطلب دقة أعلى
    domain = (semantic_frame.get("legal_domain") or "").lower()
    if domain in ("criminal", "family"):
        risk_score += 0.20

    # عامل 5: لا يوجد قانون محدد في الإطار
    if not (semantic_frame.get("relevant_laws") or semantic_frame.get("legal_issue")):
        risk_score += 0.15

    # ── تطبيق الاستراتيجية بناءً على مجموع الخطر ──
    if risk_score >= 0.65:
        strategy["temperature"]    = 0.1
        strategy["strict_mode"]    = True
        strategy["max_tokens_cap"] = 2000
        strategy["conservative_note"] = (
            "\n[تعليمة صارمة: هذا السؤال يحمل خطر تفسير مرتفع. "
            "لا تتجاوز النص القانوني الصريح. إذا لم يوجد نص واضح → قل ذلك صراحةً.]\n"
        )
    elif risk_score >= 0.40:
        strategy["temperature"]    = 0.2
        strategy["strict_mode"]    = True
        strategy["conservative_note"] = (
            "\n[تعليمة: التزم بالنصوص القانونية الصريحة. "
            "تجنب التفسير الموسّع. أشِر للاستثناءات إن وُجدت.]\n"
        )
    # risk < 0.40 → temperature=0.3, strict_mode=False (الافتراضي)

    log.info(
        "generation_strategy: risk=%.2f temp=%.1f strict=%s",
        risk_score, strategy["temperature"], strategy["strict_mode"]
    )
    return strategy


# ══════════════════════════════════════════════════════════════════════════════
# PRECISION 4: Response Opening Intelligence
# يُضيف افتتاحية طبيعية ذكية بناءً على نوع الإجابة
# ══════════════════════════════════════════════════════════════════════════════

# الافتتاحيات حسب نوع الطلب
_OPENINGS = {
    "informational": [
        "بناءً على القانون القطري، ",
        "وفق أحكام التشريع القطري، ",
        "بحسب النصوص القانونية النافذة في قطر، ",
    ],
    "advisory": [
        "في مثل هذه الحالة، ",
        "من الناحية القانونية في وضعك، ",
        "بتقييم حالتك قانونياً، ",
    ],
    "procedural": [
        "للتصرف قانونياً في هذا الشأن، ",
        "الخطوات القانونية المطلوبة هي: ",
        "لحماية حقوقك قانونياً، ",
    ],
    "emotional_legal": [
        "يُؤكد القانون القطري حقك في هذا الأمر. ",
        "وضعك القانوني واضح، ",
        "من حقك قانوناً أن تعرف: ",
    ],
}

# كلمات مفتاحية للكشف عن نوع الطلب من الإجابة
_PROCEDURAL_SIGNALS = re.compile(
    r"(الخطوة|أولاً|ثانياً|ثالثاً|الإجراء|قدّم طلباً|توجّه إلى|يجب عليك أن)",
    re.UNICODE,
)
_ADVISORY_SIGNALS = re.compile(
    r"(في حالتك|يُنصح|ينبغي|يحق لك|من حقك|يُمكنك)",
    re.UNICODE,
)


def get_answer_opening(
    semantic_frame: dict,
    complexity: str,
    mode: str,
    answer_preview: str = "",
) -> str:
    """
    يُعيد افتتاحية طبيعية قصيرة (جملة واحدة) بناءً على:
    - نوع الطلب (إجرائي / استشاري / إعلامي / عاطفي-قانوني)
    - مجال القانون
    - معاينة أول 200 حرف من الإجابة

    يُعيد "" إذا كانت الإجابة تبدأ بافتتاحية مناسبة بالفعل.
    """
    if not answer_preview:
        return ""

    # لا تُضِف افتتاحية إذا بدأت الإجابة بها بالفعل
    first_50 = answer_preview[:50].strip()
    _already_opened = any(
        first_50.startswith(p.strip())
        for group in _OPENINGS.values()
        for p in group
    )
    if _already_opened:
        return ""

    # لا تُضِف للكتابة القانونية
    if mode == "legal_writing":
        return ""

    # اختر النوع
    import random as _random
    if mode == "emotional_legal":
        group = _OPENINGS["emotional_legal"]
    elif _PROCEDURAL_SIGNALS.search(answer_preview[:300]):
        group = _OPENINGS["procedural"]
    elif _ADVISORY_SIGNALS.search(answer_preview[:300]):
        group = _OPENINGS["advisory"]
    else:
        group = _OPENINGS["informational"]

    # اختر افتتاحية بشكل شبه ثابت (hash السؤال) — لا تكرار في نفس الجلسة
    idx = hash(answer_preview[:20]) % len(group)
    opening = group[idx]

    log.info("answer_opening: '%s'", opening[:40])
    return opening
