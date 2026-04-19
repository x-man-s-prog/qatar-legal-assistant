# -*- coding: utf-8 -*-
"""
Legal Reasoning Engine — Phase 5: Intelligence Consolidation
=============================================================
Merges legal_decision_engine + legal_argumentation_engine into one
coherent module with a single entry point.

Eliminates duplicated logic between the two engines.
Produces one unified output block instead of two separate appended blocks.

Output structure:
  {
    show_block:         bool,
    user_position:      str,
    opponent_position:  str,
    best_action:        str,
    action_steps:       list[str],
    risk_level:         str,       # "منخفض" | "متوسط" | "مرتفع"
    legal_rule:         str,       # IRAC: Rule
    fact_application:   str,       # IRAC: Application
    conclusion:         str,       # IRAC: Conclusion
    counter_argument:   str,       # IRAC: Counter
    proven_elements:    list[str],
    missing_elements:   list[str],
    argument_strength:  int,       # 0-100
    decision_confidence: int,      # 0-100
    warnings:           list[str],
  }

Performance impact:
  - 0ms execution (100% rule-based, zero LLM calls)
  - Replaces 2 separate engine calls with 1 merged call
  - Output is more coherent (no duplication between decision + argumentation blocks)
"""
from __future__ import annotations
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS — Actions
# ─────────────────────────────────────────────────────────────────────────────
ACTION_CRIMINAL    = "تقديم بلاغ جنائي للنيابة العامة"
ACTION_LABOR       = "تقديم شكوى لوزارة العمل والتنمية الاجتماعية"
ACTION_CIVIL       = "رفع دعوى مدنية للتعويض أمام المحكمة المختصة"
ACTION_FAMILY      = "رفع دعوى أمام محكمة الأسرة"
ACTION_COMMERCIAL  = "اللجوء للتحكيم التجاري أو رفع دعوى تجارية"
ACTION_ADMIN       = "تقديم تظلم إداري أو الطعن أمام القضاء الإداري"
ACTION_CONSULT     = "استشارة محامٍ متخصص قبل اتخاذ أي خطوة"
ACTION_EVIDENCE    = "جمع الأدلة والوثائق اللازمة أولاً"
ACTION_NEGOTIATE   = "التفاوض والوصول لتسوية ودية أولاً"

_DOMAIN_ACTION = {
    "criminal":       ACTION_CRIMINAL,
    "labor":          ACTION_LABOR,
    "family":         ACTION_FAMILY,
    "civil":          ACTION_CIVIL,
    "commercial":     ACTION_COMMERCIAL,
    "administrative": ACTION_ADMIN,
    "real_estate":    ACTION_CIVIL,
}

# ─────────────────────────────────────────────────────────────────────────────
# ACTIVATION PATTERNS
# ─────────────────────────────────────────────────────────────────────────────
_DECISION_RE = re.compile(
    r"(ماذا أفعل|ماذا أعمل|كيف أتصرف|ما خياراتي|هل أشتكي|هل أرفع|هل أبلغ|"
    r"أبغى أشتكي|أريد أشتكي|كيف أشتكي|كيف أرفع|هل يحق لي|هل بإمكاني|"
    r"ما الأفضل|ماذا توصي|نصيحتك|ما الخطوات|هل الأفضل)",
    re.UNICODE,
)
_COMPLAINT_RE = re.compile(
    r"(تم فصلي|فصلوني|طردوني|ضربني|اعتدى علي|نصبوا علي|لم يدفعوا|"
    r"ما دفعوا|ظلموني|انتهكوا حقي|خسرت|أضرّ بي|لم يعطوني)",
    re.UNICODE,
)
_WEAK_EVIDENCE_RE = re.compile(
    r"(بدون دليل|ما في دليل|ليس عندي دليل|بدون شهود|ما أقدر أثبت|صعب الإثبات)",
    re.UNICODE,
)
_STRONG_EVIDENCE_RE = re.compile(
    r"(عندي عقد|لدي عقد|عندي وثيقة|عندي إيصال|عندي شاهد|عندي تسجيل|"
    r"عندي رسائل|موثق|مكتوب|مسجل|عقد موقع|عندي دليل|لدي دليل)",
    re.UNICODE,
)

# ─────────────────────────────────────────────────────────────────────────────
# ACTION STEPS PER DOMAIN
# ─────────────────────────────────────────────────────────────────────────────
_STEPS: dict[str, list[str]] = {
    "labor": [
        "اجمع عقد العمل وكشوف الراتب وأي مراسلات رسمية مع صاحب العمل",
        "أرسل إنذاراً رسمياً كتابياً لصاحب العمل بمطالبته بحقوقك",
        "تقدّم بشكوى إلى وزارة العمل والتنمية الاجتماعية إلكترونياً أو حضورياً",
        "إذا لم يُحسم الأمر خلال 30 يوماً، ارفع دعوى أمام المحكمة العمالية",
    ],
    "criminal": [
        "اذهب فوراً إلى أقرب مركز شرطة لتقديم بلاغ رسمي",
        "احتفظ بكل الأدلة (صور، رسائل، شهود) وسلّمها للتحقيق",
        "اطلب صورة من محضر البلاغ لمتابعة القضية",
        "تواصل مع محامٍ أو النيابة العامة لمعرفة سير الإجراءات",
    ],
    "family": [
        "احضر وثائق الزواج والوثائق الرسمية ذات الصلة",
        "حاول التسوية الودية عبر الوساطة العائلية أولاً إن أمكن",
        "تقدّم بطلب للمحكمة الشرعية أو محكمة الأسرة المختصة",
        "استعن بمحامٍ متخصص في أحوال الأسرة لمرافقتك في الإجراءات",
    ],
    "civil": [
        "وثّق الضرر الواقع بصور وتقارير وأي إثباتات متاحة",
        "أرسل إنذاراً رسمياً للطرف الآخر بالمطالبة بالتعويض",
        "اللجأ للوساطة أو التسوية الودية قبل القضاء إن أمكن",
        "ارفع دعوى مدنية أمام المحكمة المختصة مع تحديد التعويض المطلوب",
    ],
    "commercial": [
        "راجع بنود العقد التجاري وبند التحكيم إن وُجد",
        "أرسل إخطاراً رسمياً بالإخلال بالالتزامات التعاقدية",
        "اللجأ للتحكيم التجاري إن كان منصوصاً عليه في العقد",
        "ارفع دعوى تجارية أمام المحكمة الابتدائية إذا تعذّر التسوية",
    ],
    "administrative": [
        "قدّم تظلماً إدارياً رسمياً للجهة مصدرة القرار خلال المهلة القانونية",
        "انتظر الرد خلال 60 يوماً (الصمت الإداري يُعدّ رفضاً ضمنياً)",
        "إذا رُفض التظلم، تقدّم للطعن أمام المحكمة الإدارية",
        "استعن بمحامٍ متخصص في القانون الإداري لصياغة لائحة الطعن",
    ],
    "real_estate": [
        "احضر عقد الإيجار أو الملكية والوثائق العقارية الرسمية",
        "أرسل إنذاراً رسمياً بالتوثيق عبر كاتب العدل إن لزم",
        "تقدّم للجهة المختصة: هيئة التسجيل العقاري أو المحكمة المدنية",
        "استشر محامياً عقارياً لتقييم قوة موقفك قبل المضي في الإجراءات",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# IRAC TEMPLATES PER DOMAIN
# ─────────────────────────────────────────────────────────────────────────────
_IRAC = {
    "labor": {
        "rule":    "يُلزم قانون العمل القطري (رقم 14 لسنة 2004) صاحب العمل بعدم إنهاء العقد إلا لأسباب مشروعة صريحة، وإلا اعتُبر الفصل تعسفياً يُوجب التعويض",
        "counter": "قد يدّعي صاحب العمل وجود سبب مشروع للفصل كالإخلال بالالتزامات أو الغياب المتكرر أو إساءة السلوك",
    },
    "criminal": {
        "rule":    "يُجرّم قانون العقوبات القطري الفعل المرتكب ويُحدد عقوبته؛ والمتضرر يملك حق تقديم البلاغ والمطالبة بالتعويض المدني عبر الدعوى الجنائية",
        "counter": "قد يدفع المتهم بانتفاء القصد الجنائي أو بوجود سبب مبيح أو بضعف الأدلة",
    },
    "family": {
        "rule":    "يُنظّم قانون الأسرة القطري (رقم 22 لسنة 2006) حقوق وواجبات الأطراف ويُعلي مصلحة الأطفال في أي نزاع",
        "counter": "قد يطعن الطرف الآخر في الأسباب المستند إليها أو يطالب بحقوق مقابلة",
    },
    "civil": {
        "rule":    "يُقرّر القانون المدني القطري حق التعويض عند ثبوت الخطأ والضرر وعلاقة السببية بينهما وفق مبدأ المسؤولية التقصيرية أو التعاقدية",
        "counter": "قد يدفع المدّعى عليه بانتفاء الخطأ أو بوجود قوة قاهرة أو بمساهمة المدّعي في الضرر",
    },
    "commercial": {
        "rule":    "يُلزم قانون التجارة القطري الأطراف بالوفاء بالتزاماتهم التعاقدية، والإخلال يُوجب التعويض أو الفسخ",
        "counter": "قد يدفع الطرف الآخر بأن الإخلال كان بسبب ظروف استثنائية أو بتفسير مغاير لبنود العقد",
    },
    "administrative": {
        "rule":    "يخضع القرار الإداري لمبدأ المشروعية ومبدأ عدم الانحراف بالسلطة؛ وللمتضرر الطعن فيه أمام القضاء الإداري",
        "counter": "قد تدفع الجهة الإدارية بصحة الإجراء ومشروعيته في إطار صلاحياتها التقديرية",
    },
}
_IRAC_DEFAULT = {
    "rule":    "يُرتّب القانون القطري على هذه الوقائع حقوقاً والتزامات محددة وفقاً للمبادئ القانونية العامة",
    "counter": "قد يطعن الطرف الآخر في الوقائع أو يقدّم تفسيراً مغايراً للوضع القانوني",
}

# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE MATRIX PER DOMAIN
# ─────────────────────────────────────────────────────────────────────────────
_EVIDENCE_MATRIX: dict[str, list[dict]] = {
    "labor": [
        {"element": "عقد العمل أو ما يُثبت العلاقة التعاقدية",
         "signals": ("عقد", "خطاب تعيين", "عمل", "موظف", "العلاقة العمالية")},
        {"element": "واقعة الفصل أو إنهاء الخدمة",
         "signals": ("فصل", "فصلوني", "أُنهي", "طردوني", "انتهى عقدي")},
        {"element": "غياب السبب المشروع للفصل",
         "signals": ("بدون سبب", "تعسفي", "ما في سبب", "بدون مبرر")},
        {"element": "دليل على الراتب أو المستحقات",
         "signals": ("راتب", "مستحقات", "مكافأة", "بدل", "أجر")},
    ],
    "criminal": [
        {"element": "الواقعة الجنائية (الفعل المكوّن للجريمة)",
         "signals": ("ضرب", "سرقة", "احتيال", "تهديد", "اعتداء", "جريمة")},
        {"element": "الضرر الناتج عن الجريمة",
         "signals": ("أذى", "ضرر", "خسارة", "جرح", "إصابة")},
        {"element": "علاقة السببية بين الفعل والضرر",
         "signals": ("بسببه", "بسببهم", "أدى إلى", "تسبب في")},
        {"element": "الركن المعنوي (القصد الجنائي)",
         "signals": ("عمداً", "قصداً", "متعمد", "عن سبق إصرار")},
    ],
    "family": [
        {"element": "وثيقة الزواج الرسمية",
         "signals": ("عقد الزواج", "وثيقة زواج", "متزوج", "زوج", "زوجة")},
        {"element": "سبب النزاع (طلاق أو حضانة أو نفقة)",
         "signals": ("طلاق", "حضانة", "نفقة", "خلع", "انفصال", "فراق")},
        {"element": "مصلحة الأطفال (إن وُجدوا)",
         "signals": ("أطفال", "أولاد", "ابن", "بنت", "طفل", "القاصر")},
        {"element": "الوضع المالي وسداد الالتزامات",
         "signals": ("نفقة", "مهر", "مؤخر", "مؤجل", "مستحق")},
    ],
    "civil": [
        {"element": "الالتزام التعاقدي أو القانوني",
         "signals": ("عقد", "التزام", "اتفاقية", "تعهد")},
        {"element": "الإخلال بالالتزام",
         "signals": ("إخلال", "لم يُنفّذ", "خالف", "رفض", "امتنع")},
        {"element": "الضرر الفعلي الناتج",
         "signals": ("ضرر", "خسارة", "أذى", "تلف", "ضياع")},
        {"element": "علاقة السببية",
         "signals": ("بسببه", "أدى إلى", "تسبب", "نتيجة")},
    ],
    "commercial": [
        {"element": "العقد التجاري وبنوده",
         "signals": ("عقد", "اتفاقية", "صفقة", "بنود")},
        {"element": "الإخلال بالالتزام التجاري",
         "signals": ("لم يُسلّم", "لم يدفع", "أخلّ", "خالف")},
        {"element": "الضرر التجاري",
         "signals": ("خسارة تجارية", "فقدان عملاء", "تعطل أعمال")},
        {"element": "الإشعار بالإخلال",
         "signals": ("إنذار", "إخطار", "تنبيه", "مطالبة رسمية")},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _detect_risk(domain: str, question: str, answer: str, chunks: list[dict]) -> str:
    domain_base = {
        "criminal": 0.65, "family": 0.55, "labor": 0.40,
        "civil": 0.35, "commercial": 0.30, "administrative": 0.35,
        "real_estate": 0.30,
    }.get(domain, 0.35)

    risk = domain_base
    combined = (question + " " + answer).lower()

    if any(w in combined for w in ("سجن", "اعتقال", "احتجاز", "إعدام")):
        risk += 0.20
    if any(w in combined for w in ("جريمة", "جنائي", "عقوبة")):
        risk += 0.10

    top_score = max((float(c.get("score", 0)) for c in chunks), default=0.0)
    if top_score > 0.85:
        risk -= 0.10
    elif top_score < 0.60:
        risk += 0.10

    if _WEAK_EVIDENCE_RE.search(question):
        risk += 0.15

    risk = max(0.0, min(1.0, risk))
    if risk < 0.40:   return "منخفض"
    if risk < 0.65:   return "متوسط"
    return "مرتفع"


def _build_positions(domain: str, analysis: dict, question: str) -> tuple[str, str]:
    """Build (user_position, opponent_position) from domain + analysis."""
    legal_issue = analysis.get("legal_issue", "")
    actors      = analysis.get("actors", "")

    # User position
    if domain == "labor":
        user_pos = "يحق لك المطالبة بحقوقك العمالية كاملةً بما فيها التعويض عن الفصل التعسفي إن ثبت"
    elif domain == "criminal":
        user_pos = "يحق لك تقديم بلاغ جنائي والمطالبة بالتعويض المدني عن الأضرار اللاحقة بك"
    elif domain == "family":
        user_pos = "يكفل لك القانون حقوقك الأسرية كاملةً بما فيها النفقة والحضانة والمتعة"
    elif domain == "civil":
        user_pos = "يحق لك المطالبة بالتعويض الكامل عن الضرر الذي لحق بك جراء إخلال الطرف الآخر"
    elif domain == "commercial":
        user_pos = "يحق لك المطالبة بتنفيذ العقد أو فسخه مع التعويض الكامل عن خسائرك التجارية"
    else:
        user_pos = "يحق لك المطالبة بحقوقك القانونية وفق الإطار التشريعي القطري المنطبق"

    if legal_issue and legal_issue not in ("", "unknown", "غير محدد"):
        user_pos = f"{user_pos} — ولا سيما فيما يخص: {legal_issue}"

    # Opponent position
    irac_domain = _IRAC.get(domain, _IRAC_DEFAULT)
    opp_pos = irac_domain.get("counter", _IRAC_DEFAULT["counter"])

    return user_pos, opp_pos


def _assess_evidence(domain: str, question: str, chunks: list[dict]) -> tuple[list[str], list[str]]:
    """Return (proven_elements, missing_elements) based on keyword signals."""
    matrix = _EVIDENCE_MATRIX.get(domain, [])
    if not matrix:
        return [], []

    all_text = question.lower() + " " + " ".join(
        c.get("content", "")[:200] for c in chunks[:5]
    ).lower()

    proven:  list[str] = []
    missing: list[str] = []

    for item in matrix:
        if any(sig in all_text for sig in item["signals"]):
            proven.append(item["element"])
        else:
            missing.append(item["element"])

    return proven, missing


def _calc_argument_strength(
    proven: list[str],
    missing: list[str],
    risk: str,
    chunks: list[dict],
    complexity: str,
) -> int:
    base = 55
    base += len(proven) * 12
    base -= len(missing) * 10

    top_score = max((float(c.get("score", 0)) for c in chunks), default=0.0)
    if top_score > 0.80:  base += 8
    elif top_score < 0.60: base -= 5
    if len(chunks) >= 3:   base += 5

    risk_adj = {"منخفض": 5, "متوسط": 0, "مرتفع": -8}.get(risk, 0)
    base += risk_adj

    if complexity == "بسيط": base += 5

    return max(10, min(95, base))


def _calc_decision_confidence(
    domain: str,
    risk: str,
    chunks: list[dict],
    analysis: dict,
) -> int:
    conf = 70
    if domain not in ("unknown", ""):
        conf += 10
    top_score = max((float(c.get("score", 0)) for c in chunks), default=0.0)
    if top_score > 0.80:
        conf += 8
    if analysis.get("ambiguity_score", 1.0) < 0.35:
        conf += 5
    if risk == "مرتفع":
        conf -= 15
    elif risk == "متوسط":
        conf -= 5
    if domain == "unknown":
        conf -= 10
    return max(20, min(95, conf))


def _build_irac(domain: str, analysis: dict, proven: list[str]) -> tuple[str, str, str]:
    """Build (legal_rule, fact_application, conclusion)."""
    irac      = _IRAC.get(domain, _IRAC_DEFAULT)
    legal_rule = irac["rule"]

    action_str  = analysis.get("action", "الفعل المذكور")
    actors_str  = analysis.get("actors", "الطرف المعني")
    issue_str   = analysis.get("legal_issue", "المسألة القانونية")

    # Clean "unknown" values
    if action_str in ("", "unknown", "غير محدد"):
        action_str = "الفعل الموصوف في الوقائع"
    if actors_str in ("", "unknown", "غير محدد"):
        actors_str = "الطرف المعني"
    if issue_str in ("", "unknown", "غير محدد"):
        issue_str = "المسألة المطروحة"

    fact_app = f"بما أن {actors_str} قام بـ {action_str}، فإن ذلك يُكيَّف قانوناً باعتباره {issue_str}"

    if proven:
        fact_app += f"، وقد توافرت عناصر: {', '.join(proven[:2])}"

    conclusion_map = {
        "labor":     "يُرتّب ذلك للعامل حقاً في التعويض عن الفصل التعسفي ومستحقات نهاية الخدمة وفق القانون القطري",
        "criminal":  "يُرتّب ذلك مسؤولية جنائية للفاعل مع حق الضحية في التعويض المدني",
        "family":    "يُرتّب ذلك حقوقاً أسرية للطرف المتضرر تشمل النفقة والتعويض وفق قانون الأسرة",
        "civil":     "يُرتّب ذلك حق المتضرر في التعويض الكامل عن الأضرار المادية والمعنوية",
        "commercial":"يُرتّب ذلك للطرف المتضرر حق فسخ العقد مع التعويض أو إلزام الطرف الآخر بالتنفيذ",
    }
    conclusion = conclusion_map.get(
        domain,
        "يُرتّب ذلك حقوقاً قانونية للطرف المتضرر وفق الإطار التشريعي القطري المنطبق"
    )

    return legal_rule, fact_app, conclusion


def _build_warnings(domain: str, risk: str, question: str, analysis: dict) -> list[str]:
    warnings: list[str] = []

    if risk == "مرتفع":
        warnings.append("⚠️ الوضع يحمل مخاطر قانونية عالية — استشر محامياً قبل اتخاذ أي إجراء")
    if _WEAK_EVIDENCE_RE.search(question):
        warnings.append("📋 ضعف الأدلة يضعف موقفك — جمع الأدلة الكافية أولوية قصوى")
    if analysis.get("urgency") == "immediate":
        warnings.append("⏰ الأمر عاجل — بعض الإجراءات القانونية لها مهل زمنية قصيرة")
    if domain in ("criminal",) and risk != "منخفض":
        warnings.append("⚖️ القضايا الجنائية تستوجب تمثيلاً قانونياً متخصصاً")

    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def build_legal_reasoning(
    question: str,
    answer:   str,
    analysis: dict,
    chunks:   list[dict],
    mode:     str = "legal_pipeline",
) -> dict:
    """
    Single entry point replacing both build_legal_position() and
    build_legal_argumentation().

    Args:
        question: Original user question
        answer:   Generated LLM answer
        analysis: Output of analyze_user_input()
        chunks:   Retrieved RAG chunks
        mode:     Pipeline mode string

    Returns:
        Unified reasoning dict (see module docstring)

    Performance impact: ~0ms (100% rule-based, zero LLM calls)
    """
    domain     = analysis.get("domain", "unknown")
    complexity = analysis.get("complexity", "متوسط")

    # Only activate for decision-seeking questions in legal modes
    if mode not in ("legal_pipeline", "emotional_legal"):
        return {"show_block": False}
    if not (_DECISION_RE.search(question) or _COMPLAINT_RE.search(question)):
        return {"show_block": False}
    if not answer:
        return {"show_block": False}

    # Risk assessment
    risk = _detect_risk(domain, question, answer, chunks)

    # Positions
    user_pos, opp_pos = _build_positions(domain, analysis, question)

    # Best action
    if risk == "مرتفع" and domain not in ("labor", "criminal"):
        best_action = ACTION_CONSULT
    elif _WEAK_EVIDENCE_RE.search(question) and not _STRONG_EVIDENCE_RE.search(question):
        best_action = ACTION_EVIDENCE
    else:
        best_action = _DOMAIN_ACTION.get(domain, ACTION_CONSULT)

    # Action steps
    steps = _STEPS.get(domain, [
        "وثّق وقائع القضية بالكامل",
        "استشر محامياً متخصصاً لتقييم موقفك",
        "تقدّم للجهة القانونية المختصة بطلبك",
        "تابع القضية حتى صدور قرار نهائي",
    ])

    # Evidence assessment
    proven, missing = _assess_evidence(domain, question, chunks)

    # IRAC
    legal_rule, fact_app, conclusion = _build_irac(domain, analysis, proven)
    irac       = _IRAC.get(domain, _IRAC_DEFAULT)
    counter    = irac.get("counter", _IRAC_DEFAULT["counter"])

    # Scores
    arg_strength = _calc_argument_strength(proven, missing, risk, chunks, complexity)
    confidence   = _calc_decision_confidence(domain, risk, chunks, analysis)

    # Warnings
    warnings = _build_warnings(domain, risk, question, analysis)

    return {
        "show_block":         True,
        "user_position":      user_pos,
        "opponent_position":  opp_pos,
        "best_action":        best_action,
        "action_steps":       steps,
        "risk_level":         risk,
        "legal_rule":         legal_rule,
        "fact_application":   fact_app,
        "conclusion":         conclusion,
        "counter_argument":   counter,
        "proven_elements":    proven,
        "missing_elements":   missing,
        "argument_strength":  arg_strength,
        "decision_confidence": confidence,
        "warnings":           warnings,
    }


def format_reasoning_block(reasoning: dict) -> str:
    """
    Format the unified reasoning dict into a human-readable Arabic block.
    Appended to the generated answer in main.py.
    """
    if not reasoning.get("show_block"):
        return ""

    risk        = reasoning["risk_level"]
    strength    = reasoning["argument_strength"]
    confidence  = reasoning["decision_confidence"]
    proven      = reasoning.get("proven_elements", [])
    missing     = reasoning.get("missing_elements", [])
    warnings    = reasoning.get("warnings", [])

    # Risk emoji
    risk_icon = {"منخفض": "🟢", "متوسط": "🟡", "مرتفع": "🔴"}.get(risk, "🟡")

    # Argument strength label
    if strength >= 80:
        strength_label = "قوي جداً"
    elif strength >= 60:
        strength_label = "متوسط–قوي"
    elif strength >= 40:
        strength_label = "متوسط"
    else:
        strength_label = "ضعيف — يحتاج دعماً"

    lines = [
        "",
        "---",
        "## ⚖️ التحليل الاستراتيجي والتكييف القانوني",
        "",
        f"**موقفك القانوني:** {reasoning['user_position']}",
        f"**الموقف المضاد المتوقع:** {reasoning['opponent_position']}",
        "",
        f"**{risk_icon} مستوى المخاطرة:** {risk}",
        f"**الإجراء الأمثل:** {reasoning['best_action']}",
        "",
        "**الخطوات العملية:**",
    ]
    for i, step in enumerate(reasoning["action_steps"], 1):
        lines.append(f"{i}. {step}")

    lines += [
        "",
        "### 🧠 التكييف القانوني (IRAC)",
        f"**القاعدة القانونية:** {reasoning['legal_rule']}",
        f"**تطبيق الوقائع:** {reasoning['fact_application']}",
        f"**الاستنتاج:** {reasoning['conclusion']}",
        f"**الحجة المضادة المتوقعة:** {reasoning['counter_argument']}",
    ]

    if proven or missing:
        lines.append("")
        lines.append("**📋 تقييم الأدلة:**")
        for el in proven:
            lines.append(f"  ✅ {el}")
        for el in missing:
            lines.append(f"  ❌ {el} *(غير مؤكد)*")

    lines += [
        "",
        f"**قوة الحجة القانونية:** {strength}/100 — {strength_label}",
        f"**ثقة التحليل:** {confidence}%",
    ]

    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(w)

    return "\n".join(lines)


def apply_reasoning_to_answer(answer: str, reasoning: dict) -> str:
    """
    Append the formatted reasoning block to the generated answer.
    Drop-in replacement for apply_decision_to_answer + apply_argumentation_to_answer.
    """
    if not reasoning.get("show_block"):
        return answer
    block = format_reasoning_block(reasoning)
    if not block:
        return answer
    return answer + block
