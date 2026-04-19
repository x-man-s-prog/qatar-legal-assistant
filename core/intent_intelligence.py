# -*- coding: utf-8 -*-
"""
Intent Intelligence Layer
=========================
Determines WHAT the user wants (data, yes/no, analysis, comparison, followup)
and routes to the correct local handler. No LLM calls.
"""
import re, logging
from typing import Optional

log = logging.getLogger("intent_intel")


# ══════════════════════════════════════════════════════════════
# Intent Types
# ══════════════════════════════════════════════════════════════

class FollowUpIntent:
    DATA_REQUEST = "data_request"
    YES_NO = "yes_no"
    ANALYTICAL = "analytical"
    COMPARISON = "comparison"
    FOLLOWUP_CLARIFY = "followup_clarify"
    NONE = "none"


# ══════════════════════════════════════════════════════════════
# Intent Detection
# ══════════════════════════════════════════════════════════════

_DATA_SIGNALS = [
    "اذكر", "اعطني", "اذكر جميع", "عدد لي", "اكتب", "قائمة",
    "جدول", "اسماء", "أسماء", "كم مربوط", "كم راتب",
]

_YES_NO_SIGNALS = [
    "هل تشمل", "هل يشمل", "هل هذا", "هل هذه", "هل هو",
    "هل فيه", "هل يوجد", "هل يحق", "هل يجوز",
    "هل ينطبق", "هل تنطبق", "هل المادة",
]

_ANALYTICAL_SIGNALS = [
    "كيف يتم", "كيف يمكن", "لماذا", "ما هي الفروق",
    "تصنيف", "ما الفرق", "ما سبب", "اشرح", "وضح",
    "كيف تصنف", "ما هو التصنيف", "ما مدى", "خطورة",
]

_COMPARISON_SIGNALS = [
    "الفرق بين", "مقارنة", "أيهما", "ايهما", "قارن",
]


def detect_followup_intent(query: str, previous_topic: str = "") -> str:
    """Classify what the user wants from a follow-up question."""
    q = query.lower().strip()

    if any(s in q for s in _DATA_SIGNALS):
        return FollowUpIntent.DATA_REQUEST

    if any(q.startswith(s) or s in q for s in _YES_NO_SIGNALS):
        return FollowUpIntent.YES_NO

    if any(s in q for s in _COMPARISON_SIGNALS):
        return FollowUpIntent.COMPARISON

    if any(s in q for s in _ANALYTICAL_SIGNALS):
        return FollowUpIntent.ANALYTICAL

    # Short follow-up with history context
    if len(q.split()) <= 8 and previous_topic:
        return FollowUpIntent.FOLLOWUP_CLARIFY

    return FollowUpIntent.NONE


# ══════════════════════════════════════════════════════════════
# Topic Detection
# ══════════════════════════════════════════════════════════════

def detect_topic(query: str, history: list = None) -> str:
    """Detect current topic from query + history. Sticky: inherits from recent history."""
    q = query.lower()

    # Direct topic signals in query
    if any(w in q for w in ["مخدر", "مؤثر", "عقلي", "أدوية"]):
        return "drugs"
    if any(w in q for w in ["راتب", "مربوط", "درجة", "رواتب", "بدل"]):
        return "salary"

    # Contextual signals — query refers to "these" / "this" with analytical intent
    has_reference = any(w in q for w in [
        "هذه المواد", "هذه الأدوية", "هذا الجدول", "هذا المبلغ",
        "هذه القائمة", "المواد", "الأدوية", "خطورة", "تصنيف",
        "استخدام", "الفرق بين",
    ])

    # Check history for sticky topic
    if history:
        for msg in reversed(history[-6:]):
            c = (msg.get("content", "") or "").lower()
            if any(w in c for w in ["مخدر", "مؤثر", "اسيتورفين", "مورفين", "كوكايين", "حشيش", "فنتانيل"]):
                if has_reference or any(w in q for w in ["مواد", "أدوية", "خطورة", "تصنيف", "استخدام", "طبي"]):
                    return "drugs"
                return "drugs"  # Sticky: any follow-up after drug context stays in drugs
            if any(w in c for w in ["راتب", "مربوط", "درجة", "6,000", "8,000"]):
                if has_reference or any(w in q for w in ["بدلات", "إجمالي", "جهات", "ترقية"]):
                    return "salary"

    return ""


# ══════════════════════════════════════════════════════════════
# Drug Knowledge Base — local deterministic answers
# ══════════════════════════════════════════════════════════════

_DRUG_FOLLOWUPS = {
    "مؤثرات": (
        "نعم. قانون المخدرات رقم 9 لسنة 1987 يُنظّم كلاً من المواد المخدرة والمؤثرات العقلية "
        "في جداول منفصلة:\n\n"
        "• الجدول (1): المواد المخدرة — وتشمل المواد الأفيونية كالمورفين والهيروين\n"
        "• الجدول (2): المؤثرات العقلية الخطرة — وتشمل المنشطات كالأمفيتامين\n"
        "• الجدول (3): مستحضرات صيدلانية تحتوي مواد مخدرة بتراكيز محددة\n\n"
        "الفصل بين الجداول له دلالة قانونية مهمة: فالعقوبات والإجراءات قد تختلف بحسب "
        "الجدول الذي تندرج تحته المادة، وإن كان القانون يتعامل مع الجميع بصرامة."
    ),
    "تصنيف": (
        # DIRECT_EVIDENCE: schedule structure from law 9/1987
        # CONTROLLED_INFERENCE: category grouping from schedule placement
        "المواد المدرجة في الجداول الملحقة بالقانون يمكن تصنيفها حسب طبيعتها:\n\n"
        "• أفيونية (مثبطات): المورفين، الهيروين، الكودايين، الفنتانيل — مدرجة في الجدول رقم (1)\n"
        "• منشطات: الأمفيتامين، الميثامفيتامين، الكوكايين — مدرجة في الجدولين (1) و(2)\n"
        "• مهلوسات: الحشيش (القنب) — مدرج في الجدول رقم (1)\n"
        "• مهدئات: الباربيتال، الديازيبام — مدرجة في الجدول رقم (2)\n\n"
        "ملاحظة: هذا التصنيف مبني على ترتيب المواد في الجداول الرسمية. "
        "القانون لا يُصنّفها صراحةً بهذه الفئات، لكن الجداول تعكس هذا التقسيم ضمنياً."
    ),
    "طبي": (
        # DIRECT_EVIDENCE: law 9/1987 articles 15-25 regulate medical use
        "القانون يُفرّق بين الاستخدام الطبي المشروع والحيازة غير المشروعة.\n\n"
        "وفقاً للمواد 15 إلى 25 من قانون المخدرات، يُسمح بحيازة وصرف بعض المواد المخدرة "
        "طبياً بشروط صارمة، منها:\n"
        "• وصفة طبية صادرة من طبيب مرخّص\n"
        "• صرف من صيدلية مرخّصة\n"
        "• كميات محددة لا تتجاوز الحد المقرر\n\n"
        "من المواد التي لها استخدام طبي مقنّن: المورفين والكودايين والفنتانيل.\n\n"
        "أي حيازة خارج هذا الإطار القانوني تُعد جريمة بصرف النظر عن الغرض المزعوم."
    ),
    "عقوبات": (
        "المشرّع القطري تعامل مع جرائم المخدرات بتدرّج يعكس خطورة الفعل:\n\n"
        "• الاتجار والتهريب: الإعدام أو السجن المؤبد — وهي أقسى عقوبة لأن الاتجار "
        "يُعد تهديداً للمجتمع بأكمله\n"
        "• الحيازة بقصد الاتجار: سجن لا يقل عن 7 سنوات — يُستدل على القصد من الكمية "
        "والتغليف وظروف الضبط\n"
        "• التعاطي: سجن لا يقل عن سنة — مع إمكانية الإحالة للعلاج في بعض الحالات\n"
        "• الحيازة للاستعمال الشخصي: سجن لا يقل عن 6 أشهر\n\n"
        "ملاحظة: المحكمة تنظر في كل قضية على حدة، والظروف المشددة (كالبيع بالقرب من "
        "المدارس) أو المخففة (كالتسليم الطوعي) تؤثر في تحديد العقوبة."
    ),
    "خطورة": (
        # DIRECT_EVIDENCE: penalty levels from law 9/1987
        # CONTROLLED_INFERENCE: severity implied by penalty structure
        "يمكن استنتاج درجة الخطورة من تدرّج العقوبات في القانون:\n\n"
        "• المواد ذات العقوبات الأشد (الإعدام/المؤبد عند الاتجار): الهيروين، الكوكايين، "
        "الفنتانيل — وهذا يعكس تقدير المشرّع لخطورتها\n"
        "• المواد المدرجة في الجدول (2): المؤثرات العقلية — عقوباتها قد تكون أخف نسبياً "
        "في بعض الحالات\n\n"
        "ملاحظة: تقييم الخطورة الطبية والصحية يخرج عن نطاق النصوص القانونية المتوفرة. "
        "ما يمكن الجزم به هو أن القانون يتعامل مع جميع هذه المواد بصرامة بصرف النظر عن نوعها."
    ),
}

_SALARY_FOLLOWUPS = {
    "بدلات": (
        # DIRECT_EVIDENCE: table column names confirm "مربوط" = basic salary
        # CONTROLLED_INFERENCE: allowance types from HR law articles
        "المبالغ في جدول الدرجات هي الراتب الأساسي فقط (المربوط).\n\n"
        "الراتب الإجمالي يتكوّن عادةً من عدة مكونات ينص عليها قانون الموارد البشرية المدنية:\n"
        "• الراتب الأساسي (حسب الجدول)\n"
        "• بدل السكن — تنظمه المادة 26 من اللائحة التنفيذية\n"
        "• العلاوة الاجتماعية — للمتزوجين ومن يعولون\n"
        "• بدل النقل\n"
        "• بدلات خاصة بالجهة\n\n"
        "لا يمكن تحديد الإجمالي الدقيق من الجدول وحده لأن البدلات تختلف بحسب "
        "الجهة الحكومية والحالة الاجتماعية للموظف."
    ),
    "جهات": (
        "جدول الدرجات والرواتب (قانون الموارد البشرية المدنية رقم 15/2016) "
        "ينطبق على الجهات الحكومية المدنية في قطر.\n\n"
        "لكن هناك استثناءات مهمة:\n"
        "• الجهات السيادية والعسكرية لها أنظمة رواتب خاصة\n"
        "• المؤسسات شبه الحكومية (مثل قطر للبترول) لها جداول مختلفة\n"
        "• بعض الهيئات المستقلة قد تمنح علاوات إضافية فوق الجدول\n\n"
        "القاعدة العامة: إذا كانت الجهة تخضع لقانون الموارد البشرية المدنية، "
        "فالجدول ينطبق عليها."
    ),
    "خاص": (
        "جدول الدرجات والرواتب الحكومي لا ينطبق على القطاع الخاص.\n\n"
        "في القطاع الخاص، يُحدد الراتب بالاتفاق بين الطرفين وفقاً لقانون العمل "
        "رقم 14/2004، مع الالتزام بالحد الأدنى للأجور إن وُجد.\n\n"
        "الفرق الجوهري: الموظف الحكومي يتدرّج في سلم ثابت بعلاوات دورية، "
        "بينما في القطاع الخاص يعتمد الأمر على التفاوض والأداء."
    ),
    "ترقية": (
        "الترقية في السلم الحكومي تتم وفقاً لقانون الموارد البشرية:\n\n"
        "• الموظف يبدأ ببداية مربوط درجته\n"
        "• يحصل على علاوة دورية سنوية (إذا استوفى شروط الأداء)\n"
        "• الترقية للدرجة الأعلى تتطلب شغل الدرجة الحالية مدة محددة + تقييم أداء جيد\n"
        "• لا يمكن تجاوز نهاية المربوط إلا بالترقية للدرجة الأعلى"
    ),
}


# ══════════════════════════════════════════════════════════════
# Main Handler
# ══════════════════════════════════════════════════════════════

def handle_contextual_followup(query: str, history: list = None) -> Optional[str]:
    """
    Handle follow-up questions locally. No LLM.
    Returns answer text or None if not a recognized follow-up.
    """
    q = query.lower().strip()
    topic = detect_topic(query, history)
    intent = detect_followup_intent(query, topic)

    log.info("[INTENT] topic=%s intent=%s q=%s", topic, intent, q[:50])

    # Data requests → return None (let structured lookup handle)
    if intent == FollowUpIntent.DATA_REQUEST:
        return None

    # Drug topic follow-ups
    if topic == "drugs":
        if intent == FollowUpIntent.YES_NO:
            if any(w in q for w in ["مؤثر", "عقلي", "تشمل"]):
                return _DRUG_FOLLOWUPS["مؤثرات"]

        if intent == FollowUpIntent.ANALYTICAL:
            if any(w in q for w in ["تصنيف", "تصنف", "فئات", "أنواع", "تقسيم"]):
                return _DRUG_FOLLOWUPS["تصنيف"]
            if any(w in q for w in ["طبي", "استخدام", "علاج", "قانوني", "مشروع"]):
                return _DRUG_FOLLOWUPS["طبي"]
            if any(w in q for w in ["عقوبة", "عقوبات", "حكم", "سجن", "جزاء"]):
                return _DRUG_FOLLOWUPS["عقوبات"]
            if any(w in q for w in ["خطورة", "خطر", "إدمان", "أشد", "أخطر"]):
                return _DRUG_FOLLOWUPS["خطورة"]

        if intent == FollowUpIntent.COMPARISON:
            if any(w in q for w in ["طبي", "قانوني", "مشروع", "غير مشروع"]):
                return _DRUG_FOLLOWUPS["طبي"]
            if any(w in q for w in ["خطورة", "أشد", "أخطر"]):
                return _DRUG_FOLLOWUPS["خطورة"]

        if intent == FollowUpIntent.FOLLOWUP_CLARIFY:
            if any(w in q for w in ["مؤثر", "عقلي"]):
                return _DRUG_FOLLOWUPS["مؤثرات"]
            if any(w in q for w in ["خطر", "خطورة", "إدمان", "أخطر"]):
                return _DRUG_FOLLOWUPS["خطورة"]
            if any(w in q for w in ["طبي", "استخدام", "علاج", "قانوني", "فرق", "مشروع"]):
                return _DRUG_FOLLOWUPS["طبي"]
            if any(w in q for w in ["عقوبة", "عقوبات", "حكم", "سجن"]):
                return _DRUG_FOLLOWUPS["عقوبات"]
            if any(w in q for w in ["تصنيف", "أنواع", "فئات"]):
                return _DRUG_FOLLOWUPS["تصنيف"]
            # Generic drug-context follow-up with "هذه المواد" / "هذه الأدوية"
            if any(w in q for w in ["هذه المواد", "هذه الأدوية", "هذا الجدول"]):
                return _DRUG_FOLLOWUPS["تصنيف"]

    # Salary topic follow-ups
    if topic == "salary":
        if any(w in q for w in ["بدلات", "الأساسي", "الإجمالي", "يشمل", "صافي", "خصم"]):
            return _SALARY_FOLLOWUPS["بدلات"]
        if any(w in q for w in ["جميع الجهات", "كل الجهات", "ينطبق", "يشمل هذا الجدول"]):
            return _SALARY_FOLLOWUPS["جهات"]
        if any(w in q for w in ["القطاع الخاص", "خاص"]):
            return _SALARY_FOLLOWUPS["خاص"]
        if any(w in q for w in ["ترقية", "علاوة دورية", "يتدرج", "سنوية"]):
            return _SALARY_FOLLOWUPS["ترقية"]

    return None
