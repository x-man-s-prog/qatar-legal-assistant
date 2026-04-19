# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       Legal Decision Engine — المساعد القانوني القطري                        ║
║       يحوّل النظام من مُخبر قانوني إلى مستشار يتخذ قرارات                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

المهمة الوحيدة:
    decision = build_legal_position(question, answer, semantic_frame, chunks, domain)
    block    = format_decision_block(decision)
    answer  += block  # يُلحق بالإجابة

التصميم:
  • 100% rule-based — صفر latency إضافية
  • لا LLM calls — يعتمد على semantic_frame + question patterns
  • Non-intrusive — يُضاف بعد الإجابة كقسم مستقل
  • يعمل فقط عند وجود حاجة قرارية (decision-seeking questions)
"""
from __future__ import annotations

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# ثوابت الإجراءات القانونية — Actions
# ══════════════════════════════════════════════════════════════════════════════

ACTION_CRIMINAL_COMPLAINT  = "تقديم بلاغ جنائي للنيابة العامة"
ACTION_LABOR_COMPLAINT     = "تقديم شكوى لوزارة العمل والتنمية الاجتماعية"
ACTION_CIVIL_LAWSUIT       = "رفع دعوى مدنية للتعويض أمام المحكمة المختصة"
ACTION_FAMILY_COURT        = "رفع دعوى أمام محكمة الأسرة"
ACTION_COMMERCIAL_ARB      = "اللجوء للتحكيم التجاري أو رفع دعوى تجارية"
ACTION_ADMINISTRATIVE      = "تقديم تظلم إداري أو الطعن أمام القضاء الإداري"
ACTION_NEGOTIATE           = "التفاوض والوصول لتسوية ودية أولاً"
ACTION_CONSULT             = "استشارة محامٍ متخصص قبل اتخاذ أي خطوة"
ACTION_WAIT_EVIDENCE       = "جمع الأدلة والوثائق اللازمة قبل المضي في الإجراءات"

# خريطة المجال → الإجراء الافتراضي
_DOMAIN_DEFAULT_ACTION: dict[str, str] = {
    "criminal":      ACTION_CRIMINAL_COMPLAINT,
    "labor":         ACTION_LABOR_COMPLAINT,
    "family":        ACTION_FAMILY_COURT,
    "civil":         ACTION_CIVIL_LAWSUIT,
    "commercial":    ACTION_COMMERCIAL_ARB,
    "administrative": ACTION_ADMINISTRATIVE,
    "real_estate":   ACTION_CIVIL_LAWSUIT,
    "traffic":       ACTION_CRIMINAL_COMPLAINT,
}

# ══════════════════════════════════════════════════════════════════════════════
# إشارات اكتشاف نوع السؤال
# ══════════════════════════════════════════════════════════════════════════════

# أسئلة تبحث عن قرار (decision-seeking)
_DECISION_PATTERNS = re.compile(
    r"(ماذا أفعل|ماذا أعمل|ماذا علي|هل أرفع|هل أشتكي|هل أبلغ|هل أتقدم|"
    r"أبغى أشتكي|أريد أشتكي|ابغى اشتكي|كيف أشتكي|كيف أرفع|كيف أتصرف|"
    r"ماذا يجب|ما الذي يجب|ما الخطوة|ما الخطوات|هل يحق لي|هل بإمكاني|"
    r"ما الأفضل|ما هو الأفضل|هل الأفضل|نصيحتك|ماذا توصي|ما رأيك)",
    re.UNICODE,
)

# مواقف الشكوى/الضرر الواضحة
_COMPLAINT_SITUATION = re.compile(
    r"(تم فصلي|فُصلت|طردوني|سرقوني|ضربني|اعتدى علي|نصبوا علي|غشوني|"
    r"أخذوا مالي|لم يدفعوا|ما دفعوا|تأخر راتبي|لم يعطوني|ما أعطوني|"
    r"رفضوا طلبي|أضرّ بي|أضروا بي|ظلموني|انتهكوا حقي|خسرت بسببه)",
    re.UNICODE,
)

# إشارات ضعف الأدلة
_WEAK_EVIDENCE = re.compile(
    r"(ليس عندي دليل|ما عندي دليل|بدون إثبات|لا يوجد دليل|"
    r"شك في الأدلة|فيه شك|ما في دليل|بدون شهود|ما في شهود|"
    r"ما أقدر أثبت|لا أستطيع الإثبات|صعب الإثبات)",
    re.UNICODE,
)

# إشارات قوة الأدلة
_STRONG_EVIDENCE = re.compile(
    r"(عندي عقد|لدي عقد|عندي وثيقة|عندي إيصال|عندي شاهد|"
    r"عندي تسجيل|عندي رسائل|عندي صور|موثق|مكتوب|مسجل|"
    r"عقد موقع|عندي دليل|لدي دليل)",
    re.UNICODE,
)

# إشارات سوء الفهم أو التضليل الذاتي
_MISCONCEPTION_PATTERNS = re.compile(
    r"(سمعت إن|قيل لي إن|أظن إن|يقولون إن|شايف إن|ظاهر إن)",
    re.UNICODE,
)

# ══════════════════════════════════════════════════════════════════════════════
# الخطوات العملية لكل مجال
# ══════════════════════════════════════════════════════════════════════════════

_ACTION_STEPS: dict[str, list[str]] = {
    "criminal": [
        "اجمع الأدلة: صور، رسائل، شهود",
        "توجّه لأقرب مركز شرطة أو النيابة العامة",
        "قدّم بلاغاً رسمياً مع توثيق جميع التفاصيل",
        "احتفظ بنسخة من البلاغ ورقم القضية",
    ],
    "labor": [
        "اجمع عقد العمل وآخر مسيرات الراتب",
        "أرسل إنذاراً خطياً لصاحب العمل أولاً",
        "تقدّم بشكوى لوزارة العمل (منصة أمان أو حضورياً)",
        "إذا لم يُحسم: ارفع دعوى أمام المحكمة العمالية",
    ],
    "family": [
        "اجمع وثائق الزواج والمستندات ذات الصلة",
        "استشِر محامياً متخصصاً في قانون الأسرة",
        "تقدّم بطلب أمام محكمة الأسرة",
        "اطلب وساطة إذا كان النزاع قابلاً للحل وديًّا",
    ],
    "civil": [
        "وثّق الضرر والخسائر بدقة",
        "أرسل إنذاراً رسمياً للطرف المقابل",
        "استشِر محامياً لتقييم فرص النجاح",
        "ارفع دعوى تعويض أمام المحكمة المدنية",
    ],
    "commercial": [
        "راجع بنود العقد التجاري وشرط التحكيم",
        "أرسل إخطاراً رسمياً بالمطالبة",
        "الجأ للتحكيم التجاري إذا وُجد شرط",
        "إذا لا → ارفع دعوى أمام المحكمة التجارية",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# الدوال المساعدة — Internal Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _is_decision_seeking(question: str, mode: str) -> bool:
    """هل المستخدم يبحث عن قرار/إجراء؟"""
    return bool(
        _DECISION_PATTERNS.search(question)
        or _COMPLAINT_SITUATION.search(question)
        or mode == "emotional_legal"
    )


def _detect_risk_level(
    question: str,
    semantic_frame: dict,
    chunks: list[dict],
) -> str:
    """يُحدد مستوى الخطر: low / medium / high"""
    risk = 0

    # أدلة ضعيفة → خطر مرتفع
    if _WEAK_EVIDENCE.search(question):
        risk += 3

    # أدلة قوية → خطر منخفض
    if _STRONG_EVIDENCE.search(question):
        risk -= 2

    # severity من semantic_frame
    severity = (semantic_frame.get("severity") or "").lower()
    if severity in ("high", "critical", "عالية", "بالغة"):
        risk += 2
    elif severity in ("low", "minor", "منخفضة"):
        risk -= 1

    # قضايا جنائية بدون أدلة واضحة → خطر أعلى
    domain = (semantic_frame.get("legal_domain") or "").lower()
    if domain == "criminal" and not _STRONG_EVIDENCE.search(question):
        risk += 1

    # جودة الاسترجاع
    if chunks:
        top_score = float(chunks[0].get("score", 0))
        if top_score < 0.65:
            risk += 1
        elif top_score >= 0.85:
            risk -= 1

    if risk >= 3:
        return "high"
    if risk >= 1:
        return "medium"
    return "low"


def _detect_warnings(
    question: str,
    answer: str,
    semantic_frame: dict,
) -> list[str]:
    """يكتشف التحذيرات المهمة للمستخدم"""
    warnings = []

    # ضعف الأدلة
    if _WEAK_EVIDENCE.search(question):
        warnings.append("⚠️ الأدلة المتاحة قد تكون غير كافية — اجمع المزيد قبل المضي قُدماً")

    # سوء فهم محتمل
    if _MISCONCEPTION_PATTERNS.search(question):
        warnings.append("ℹ️ تأكد من صحة المعلومات المسموعة — القانون قد يختلف عما قيل لك")

    # urgency من semantic_frame
    urgency = (semantic_frame.get("urgency") or "").lower()
    if urgency in ("urgent", "عاجل", "critical"):
        warnings.append("🚨 الحالة تستدعي التصرف الفوري — لا تتأخر في اتخاذ الإجراء")

    # قضية معقدة بدون محامٍ
    possible_claims = semantic_frame.get("possible_crimes_or_claims") or []
    if len(possible_claims) >= 2:
        warnings.append("💼 تعدد المطالبات يستلزم الاستعانة بمحامٍ متخصص")

    return warnings


def _get_best_action(
    domain: str,
    question: str,
    semantic_frame: dict,
) -> str:
    """يُحدد أفضل إجراء قانوني بناءً على المجال والسياق"""
    q = question.lower()

    # طلب تفاوض صريح؟
    if any(w in q for w in ("تسوية", "مصالحة", "أتفاوض", "تفاهم", "حل ودي")):
        return ACTION_NEGOTIATE

    # أدلة ضعيفة → اجمع أولاً
    if _WEAK_EVIDENCE.search(question):
        return ACTION_WAIT_EVIDENCE

    # المجال له أولوية قصوى — لا يُتجاوز بالـ claims
    domain_action = _DOMAIN_DEFAULT_ACTION.get(domain)
    if domain_action:
        return domain_action

    # fallback: استنتج من الـ claims إذا لم يُعرَّف المجال
    claims = semantic_frame.get("possible_crimes_or_claims") or []
    if claims:
        first_claim = str(claims[0]).lower()
        if any(w in first_claim for w in ("فصل", "راتب", "عمل")):
            return ACTION_LABOR_COMPLAINT
        if any(w in first_claim for w in ("تعويض", "ضرر", "خسارة")):
            return ACTION_CIVIL_LAWSUIT

    return ACTION_CONSULT


def _build_user_position(
    question: str,
    semantic_frame: dict,
    domain: str,
) -> str:
    """يُنشئ صياغة موقف المستخدم القانوني"""
    legal_issue = (semantic_frame.get("legal_issue") or "").strip()
    action      = (semantic_frame.get("action") or "").strip()

    if legal_issue and legal_issue not in ("unknown", "غير محدد"):
        return f"يحق لك المطالبة بـ {legal_issue}"

    if action:
        return f"تعرضت لـ '{action}' وهو يُرتّب حقوقاً قانونية لك"

    domain_positions = {
        "criminal": "تعرضت لفعل يُعدّ جريمة يُعاقب عليها القانون",
        "labor":    "حقوقك العمالية مكفولة بموجب قانون العمل القطري",
        "family":   "حقوقك الأسرية محمية بموجب قانون الأسرة القطري",
        "civil":    "يحق لك المطالبة بالتعويض عن الضرر اللاحق بك",
        "commercial": "حقوقك التجارية مكفولة بموجب العقد والقانون التجاري",
    }
    return domain_positions.get(domain, "يحق لك اتخاذ الإجراءات القانونية المناسبة")


def _build_opponent_position(domain: str, risk_level: str) -> str:
    """يُنشئ صياغة الموقف المقابل المحتمل"""
    if risk_level == "high":
        return "قد يطعن الطرف الآخر في غياب الأدلة أو يطلب حفظ القضية"
    if domain == "labor":
        return "قد يدّعي صاحب العمل وجود مبرر قانوني للإجراء المتخذ"
    if domain == "criminal":
        return "قد ينفي الطرف الآخر التهمة أو يقدم رواية مخالفة"
    if domain == "family":
        return "قد يكون للطرف الآخر حقوق مشتركة تؤثر على مسار القضية"
    return "قد يتمسك الطرف الآخر بدفوع شكلية أو موضوعية"


def _calc_decision_confidence(
    domain: str,
    chunks: list[dict],
    semantic_frame: dict,
    risk_level: str,
) -> float:
    """
    يحسب درجة ثقة القرار (0-95).
    منفصلة عن answer_confidence.
    """
    conf = 70.0

    # مجال واضح → +10
    if domain and domain != "unknown":
        conf += 10.0

    # أدلة استرجاع قوية → +10
    if chunks and float(chunks[0].get("score", 0)) >= 0.80:
        conf += 10.0
    elif not chunks:
        conf -= 20.0

    # legal_issue محدد في semantic_frame → +5
    if (semantic_frame.get("legal_issue") or "").strip() not in ("", "unknown", "غير محدد"):
        conf += 5.0

    # خطر مرتفع → خصم
    if risk_level == "high":
        conf -= 20.0
    elif risk_level == "medium":
        conf -= 10.0

    return round(max(20.0, min(95.0, conf)), 1)


# ══════════════════════════════════════════════════════════════════════════════
# الدالة الرئيسية — Core Function
# ══════════════════════════════════════════════════════════════════════════════

def build_legal_position(
    question:       str,
    answer:         str,
    semantic_frame: dict,
    chunks:         list[dict],
    domain:         str,
    mode:           str = "legal_pipeline",
    answer_confidence: float = 75.0,
) -> dict:
    """
    ينشئ موقفاً قانونياً كاملاً للمستخدم.

    يعمل فقط عند وجود حاجة قرارية — لا يضيف ضوضاء للأسئلة الإعلامية البسيطة.

    Returns
    -------
    dict:
        show_decision      : bool   — هل يجب عرض القسم؟
        user_position      : str
        opponent_position  : str
        best_action        : str
        action_steps       : list[str]
        risk_level         : str    — low/medium/high
        decision_confidence: float  — 0-95
        warnings           : list[str]
    """
    _empty = {
        "show_decision": False,
        "user_position": "",
        "opponent_position": "",
        "best_action": "",
        "action_steps": [],
        "risk_level": "medium",
        "decision_confidence": 0.0,
        "warnings": [],
    }

    if not question or not answer:
        return _empty

    # لا تعمل للوضع الإعلامي البسيط
    if not _is_decision_seeking(question, mode):
        return _empty

    # تحليل المكونات
    risk_level          = _detect_risk_level(question, semantic_frame, chunks)
    warnings            = _detect_warnings(question, answer, semantic_frame)
    best_action         = _get_best_action(domain, question, semantic_frame)
    user_position       = _build_user_position(question, semantic_frame, domain)
    opponent_position   = _build_opponent_position(domain, risk_level)
    decision_confidence = _calc_decision_confidence(domain, chunks, semantic_frame, risk_level)
    action_steps        = _ACTION_STEPS.get(domain, [])

    # إذا كانت الثقة منخفضة جداً → لا نعطي توصيات حازمة
    if decision_confidence < 40:
        return _empty

    # تليين الإجراءات عند الخطر المرتفع
    if risk_level == "high" and best_action not in (ACTION_WAIT_EVIDENCE, ACTION_CONSULT):
        best_action  = ACTION_CONSULT
        action_steps = [
            "استشِر محامياً لتقييم وضعك بدقة",
            "اجمع كل الأدلة والوثائق المتاحة",
            "لا تتصرف منفرداً في هذه المرحلة",
        ]

    log.info(
        "legal_decision: domain=%s risk=%s action='%s' conf=%.1f",
        domain, risk_level, best_action[:40], decision_confidence,
    )

    return {
        "show_decision":       True,
        "user_position":       user_position,
        "opponent_position":   opponent_position,
        "best_action":         best_action,
        "action_steps":        action_steps,
        "risk_level":          risk_level,
        "decision_confidence": decision_confidence,
        "warnings":            warnings,
    }


# ══════════════════════════════════════════════════════════════════════════════
# مُنسّق النص — Format for Answer
# ══════════════════════════════════════════════════════════════════════════════

_RISK_DISPLAY = {
    "low":    "🟢 منخفض",
    "medium": "🟡 متوسط",
    "high":   "🔴 مرتفع",
}


def format_decision_block(decision: dict) -> str:
    """
    يُنشئ قسم القرار القانوني الذي يُلحق بنهاية الإجابة.
    واضح، مركّز، عملي.
    """
    if not decision.get("show_decision"):
        return ""

    conf  = decision["decision_confidence"]
    risk  = decision["risk_level"]
    lines = ["\n\n---", "⚖️ **الموقف القانوني والإجراء الأنسب**\n"]

    # موقف المستخدم
    lines.append(f"📌 **موقفك**: {decision['user_position']}")

    # الإجراء الأنسب
    lines.append(f"\n🎯 **الإجراء الأنسب**: {decision['best_action']}")

    # مستوى الخطر
    lines.append(f"⚠️ **مستوى الخطر**: {_RISK_DISPLAY.get(risk, risk)}")

    # الموقف المقابل (فقط عند الخطر المتوسط أو المرتفع)
    if risk in ("medium", "high"):
        lines.append(f"🔄 **الموقف المقابل المحتمل**: {decision['opponent_position']}")

    # خطوات عملية (إذا وُجدت)
    steps = decision.get("action_steps") or []
    if steps:
        lines.append("\n📋 **الخطوات العملية**:")
        for i, step in enumerate(steps[:4], 1):
            lines.append(f"  {i}. {step}")

    # تحذيرات
    warnings = decision.get("warnings") or []
    if warnings:
        lines.append("")
        for w in warnings[:3]:
            lines.append(w)

    # تنبيه عند الثقة المتوسطة
    if conf < 70:
        lines.append(
            "\n> 💡 **ملاحظة**: هذا التقييم مبدئي — الاستشارة مع محامٍ متخصص ستُعطيك تقييماً أدق لحالتك."
        )

    return "\n".join(lines)


def apply_decision_to_answer(answer: str, decision: dict) -> str:
    """
    يُلحق قسم القرار بنهاية الإجابة.
    نقطة دخول موحّدة للتكامل في main.py.
    """
    block = format_decision_block(decision)
    if block:
        return answer + block
    return answer
