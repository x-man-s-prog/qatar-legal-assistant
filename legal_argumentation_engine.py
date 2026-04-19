# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║     Legal Argumentation Engine — المساعد القانوني القطري                     ║
║     يبني حجة قانونية قابلة للدفاع وفق بنية IRAC المُبسَّطة                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

البنية: Rule → Application → Conclusion  (IRAC)

المدخلات (كلها موجودة بالفعل في الـ pipeline — لا LLM إضافي):
  question       : سؤال المستخدم
  semantic_frame : الإطار الدلالي (legal_issue, action, actors, relevant_laws…)
  chunks         : قطع RAG المسترجعة (تحتوي نص القانون الفعلي)
  domain         : المجال (criminal / labor / family / civil …)
  cot            : نتيجة Chain-of-Thought (legal_characterization, primary_law)
  legal_decision : نتيجة Legal Decision Engine (risk_level, best_action…)

المخرجات:
  {
    "show_argumentation" : bool,
    "legal_rule"         : str,   — النص أو المبدأ الحاكم
    "fact_application"   : str,   — ربط الوقائع بالعناصر القانونية
    "conclusion"         : str,   — النتيجة القانونية المنطقية
    "counter_argument"   : str,   — الحجة المقابلة المحتملة
    "proven_elements"    : list,  — عناصر مُثبَتة ✔
    "missing_elements"   : list,  — عناصر تحتاج إثباتاً ✗
    "argument_strength"  : float, — 0-100
  }
"""
from __future__ import annotations

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# عناصر الإثبات المطلوبة لكل مجال — Evidence Matrix
# ══════════════════════════════════════════════════════════════════════════════

_EVIDENCE_MATRIX: dict[str, list[dict]] = {
    "labor": [
        {"element": "عقد العمل أو ما يُثبت العلاقة التعاقدية",
         "signals": ("عقد", "عقد عمل", "خطاب تعيين", "موظف", "عامل")},
        {"element": "واقعة الفصل أو إنهاء الخدمة",
         "signals": ("فصل", "فُصلت", "أُنهيت خدمتي", "طردوني", "إنهاء عقد")},
        {"element": "غياب السبب المشروع للفصل",
         "signals": ("بدون سبب", "بدون مبرر", "ظلماً", "تعسفياً", "فجأة", "بدون إشعار")},
        {"element": "دليل على الراتب أو المستحقات المطالب بها",
         "signals": ("راتب", "مسيرة راتب", "إيصال", "بنك", "مستحقات")},
    ],
    "criminal": [
        {"element": "وقوع الفعل الجُرمي",
         "signals": ("ضربني", "اعتدى", "سرق", "أخذ", "تحرش", "هدد", "ابتز")},
        {"element": "تحديد هوية الجاني أو معرفته",
         "signals": ("أعرفه", "جاري", "زميلي", "اسمه", "صاحبي", "يعرفني")},
        {"element": "دليل مادي أو شهادة شاهد",
         "signals": ("شاهد", "تسجيل", "صورة", "كاميرا", "تقرير طبي", "إفادة", "رسائل")},
        {"element": "الضرر الواقع (جسدي أو مادي أو معنوي)",
         "signals": ("أذى", "ضرر", "جرح", "خسارة", "ألم", "خوف", "تأثر")},
    ],
    "family": [
        {"element": "وثيقة الزواج الرسمية",
         "signals": ("عقد زواج", "وثيقة زواج", "متزوج", "زوجتي", "زوجي")},
        {"element": "واقعة النزاع أو سبب الدعوى",
         "signals": ("طلاق", "نفقة", "حضانة", "ميراث", "بيت الزوجية", "هجر")},
        {"element": "الوضع المالي أو الوقائع المادية",
         "signals": ("راتب", "ممتلكات", "عقار", "مال", "دخل", "ثروة")},
    ],
    "civil": [
        {"element": "العقد أو الاتفاق المبرم",
         "signals": ("عقد", "اتفاق", "اتفاقية", "تعاقد", "وثيقة")},
        {"element": "الإخلال بالالتزام التعاقدي",
         "signals": ("لم يُنفِّذ", "أخل", "لم يدفع", "رفض", "خالف")},
        {"element": "الضرر الفعلي الناجم",
         "signals": ("خسارة", "ضرر", "أضرار", "تضرر", "خسرت")},
        {"element": "العلاقة السببية بين الفعل والضرر",
         "signals": ("بسببه", "نتيجة", "أدى إلى", "تسبب في")},
    ],
    "commercial": [
        {"element": "العقد التجاري أو الصفقة",
         "signals": ("عقد", "صفقة", "اتفاق تجاري", "شراكة", "استثمار")},
        {"element": "الالتزام المُخَل به",
         "signals": ("لم يُسلّم", "لم يدفع", "أخل بالشرط", "غش", "خدع")},
        {"element": "الدليل التجاري (فاتورة / شيك / مراسلات)",
         "signals": ("فاتورة", "شيك", "مراسلات", "بريد إلكتروني", "إيصال")},
    ],
}

# ══════════════════════════════════════════════════════════════════════════════
# قوالب IRAC للمجالات المختلفة
# ══════════════════════════════════════════════════════════════════════════════

_IRAC_TEMPLATES: dict[str, dict] = {
    "labor": {
        "rule_prefix":    "يُلزم قانون العمل القطري صاحب العمل بعدم الفصل إلا لأسباب مشروعة",
        "app_template":   "بما أن {actors} قام بـ {action}، فإن ذلك يُكيَّف قانوناً كـ {legal_issue}",
        "conclusion_tpl": "يُرتّب هذا التكييف حق العامل في التعويض عن الفصل التعسفي ومستحقاته كاملة",
        "counter_tpl":    "قد يدّعي صاحب العمل وجود مبرر مشروع لإنهاء الخدمة أو أن الفصل جاء لأسباب تأديبية",
    },
    "criminal": {
        "rule_prefix":    "يُجرّم قانون العقوبات القطري الاعتداء بجميع صوره ويُقرر له عقوبات صارمة",
        "app_template":   "بما أن {actors} قام بـ {action} مما أوقع ضرراً موصوفاً، فهذا يُكيَّف كـ {legal_issue}",
        "conclusion_tpl": "يُحق للمتضرر تقديم بلاغ جنائي والمطالبة بالتعويض المدني بالتبعية",
        "counter_tpl":    "قد يدّعي الطرف الآخر دفع النفي التام أو الدفع بعدم كفاية الأدلة",
    },
    "family": {
        "rule_prefix":    "يُنظّم قانون الأسرة القطري الحقوق والالتزامات بين الزوجين والأسرة",
        "app_template":   "بما أن الوضع يتعلق بـ {legal_issue} في إطار علاقة {actors}، فتسري أحكام قانون الأسرة",
        "conclusion_tpl": "يُخوّل القانون صاحب الحق رفع دعوى أمام محكمة الأسرة للمطالبة بحقوقه",
        "counter_tpl":    "قد يتمسك الطرف المقابل بأن الالتزامات سقطت بالتقادم أو لعذر قانوني",
    },
    "civil": {
        "rule_prefix":    "تُوجب قواعد المسؤولية المدنية التعويض عن كل ضرر ثابت ناجم عن فعل غير مشروع",
        "app_template":   "بما أن {actors} أخلّ بـ {legal_issue} مُلحِقاً ضرراً موثقاً، يتحقق أساس المسؤولية",
        "conclusion_tpl": "يحق للمتضرر المطالبة بالتعويض الكامل أمام المحكمة المدنية المختصة",
        "counter_tpl":    "قد يدفع الطرف المقابل بأن الضرر غير ثابت أو أن العلاقة السببية منقطعة",
    },
    "commercial": {
        "rule_prefix":    "يُلزم القانون التجاري القطري بالوفاء بالالتزامات التعاقدية وإلا أُعمل التعويض",
        "app_template":   "بما أن {actors} أخلّ بالتزاماته في {legal_issue}، تتحقق المسؤولية التعاقدية",
        "conclusion_tpl": "يحق المطالبة بالتنفيذ الجبري أو التعويض وفق شروط العقد والقانون التجاري",
        "counter_tpl":    "قد يتمسك الطرف المقابل بقوة قاهرة أو بأن الالتزام سقط بالتقادم التجاري",
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# إشارات الأدلة من النص
# ══════════════════════════════════════════════════════════════════════════════

_STRONG_EVIDENCE_RE = re.compile(
    r"(عندي عقد|لدي عقد|عندي وثيقة|عندي إيصال|عندي شاهد|عندي تسجيل|"
    r"عندي صور|موثق|مكتوب|مسجل|عقد موقع|عندي دليل|لدي دليل|"
    r"عندي رسائل|في الواتس|ايميل|بريد إلكتروني)", re.UNICODE,
)

_WEAK_EVIDENCE_RE = re.compile(
    r"(ليس عندي دليل|ما عندي دليل|بدون إثبات|لا يوجد دليل|"
    r"شك في الأدلة|فيه شك|ما في دليل|بدون شهود|ما في شهود|"
    r"ما أقدر أثبت|لا أستطيع الإثبات|صعب الإثبات)", re.UNICODE,
)


# ══════════════════════════════════════════════════════════════════════════════
# دوال مساعدة
# ══════════════════════════════════════════════════════════════════════════════

def _check_evidence_elements(
    question: str,
    domain: str,
) -> tuple[list[str], list[str]]:
    """
    يفحص السؤال ويُعيد (proven_elements, missing_elements).
    يبحث عن كل عنصر من مصفوفة الإثبات.
    """
    matrix = _EVIDENCE_MATRIX.get(domain, [])
    proven:  list[str] = []
    missing: list[str] = []
    q_lower = question.lower()

    for item in matrix:
        found = any(sig in q_lower for sig in item["signals"])
        if found:
            proven.append(item["element"])
        else:
            missing.append(item["element"])

    return proven, missing


def _extract_law_rule(
    chunks: list[dict],
    cot:    dict,
    semantic_frame: dict,
) -> str:
    """
    يستخرج النص القانوني الحاكم من:
    1. CoT (primary_law + legal_characterization)
    2. أول قطعة مسترجعة (top chunk)
    3. semantic_frame.relevant_laws
    """
    # من CoT
    primary_law   = (cot.get("primary_law") or "").strip()
    legal_char    = (cot.get("legal_characterization") or "").strip()

    if primary_law and legal_char:
        return f"{primary_law} — {legal_char}"
    if primary_law:
        return primary_law

    # من top chunk
    if chunks:
        top   = chunks[0]
        lname = top.get("law_name", "")
        lnum  = top.get("law_number", "")
        lyear = top.get("law_year", "")
        art   = top.get("article_number", "")
        if lname and art:
            ref = f"المادة ({art})"
            if lnum and lyear:
                ref += f" من {lname} رقم ({lnum}) لسنة {lyear}"
            else:
                ref += f" من {lname}"
            # أضف مقتطفاً قصيراً من النص
            snippet = top.get("content", "")[:120].strip()
            if snippet:
                return f"{ref}: «{snippet}…»"
            return ref

    # من semantic_frame
    laws = semantic_frame.get("relevant_laws") or []
    if laws:
        return "، ".join(str(l) for l in laws[:2])

    return ""


def _build_fact_application(
    semantic_frame: dict,
    domain:         str,
    templates:      dict,
) -> str:
    """يبني جملة ربط الوقائع بالنص القانوني."""
    tpl = templates.get("app_template", "")
    if not tpl:
        return ""

    action      = (semantic_frame.get("action") or "الفعل المذكور").strip()
    actors      = (semantic_frame.get("actors") or "الطرف المقابل").strip()
    legal_issue = (semantic_frame.get("legal_issue") or "المسألة المطروحة").strip()

    # تنظيف قيم "unknown"
    if action      in ("", "unknown"):  action      = "الفعل المذكور"
    if actors      in ("", "unknown"):  actors      = "الطرف المقابل"
    if legal_issue in ("", "unknown"):  legal_issue = "المسألة القانونية"

    return tpl.format(action=action, actors=actors, legal_issue=legal_issue)


def _calc_argument_strength(
    proven:       list[str],
    missing:      list[str],
    chunks:       list[dict],
    question:     str,
    risk_level:   str,
    cot:          dict,
) -> float:
    """
    يحسب قوة الحجة القانونية من 0 إلى 100.

    المكوّنات:
      عناصر إثبات مكتملة : +12 لكل عنصر (max 48)
      عناصر مفقودة       : -10 لكل عنصر (max -40)
      جودة الاسترجاع     : +15 إذا top_score >= 0.80
      أدلة قوية مذكورة  : +15
      أدلة ضعيفة مذكورة : -20
      مستوى الخطر        : high=-15, medium=-8, low=+5
      CoT يحدد القانون   : +10
    """
    strength = 55.0   # base

    # عناصر الإثبات
    strength += min(len(proven) * 12.0, 48.0)
    strength -= min(len(missing) * 10.0, 40.0)

    # جودة RAG
    if chunks:
        top_score = float(chunks[0].get("score", 0))
        if top_score >= 0.80:
            strength += 15.0
        elif top_score < 0.60:
            strength -= 10.0

    # إشارات الأدلة في النص
    if _STRONG_EVIDENCE_RE.search(question):
        strength += 15.0
    if _WEAK_EVIDENCE_RE.search(question):
        strength -= 20.0

    # مستوى الخطر من decision engine
    if risk_level == "high":
        strength -= 15.0
    elif risk_level == "medium":
        strength -= 8.0
    else:
        strength += 5.0

    # CoT يحدد القانون الرئيسي
    if cot.get("primary_law") or cot.get("legal_characterization"):
        strength += 10.0

    return round(max(10.0, min(95.0, strength)), 1)


def _get_strength_label(strength: float) -> str:
    """يُعيد وصفاً نصياً لقوة الحجة"""
    if strength >= 80:
        return "🟢 قوية — الحجة راسخة قانونياً"
    if strength >= 60:
        return "🟡 متوسطة — الحجة مقبولة مع توافر الأدلة"
    if strength >= 40:
        return "🟠 ضعيفة — تحتاج تعزيزاً بالأدلة"
    return "🔴 هشّة — الأدلة غير كافية لحجة قوية"


# ══════════════════════════════════════════════════════════════════════════════
# الدالة الرئيسية — Core Function
# ══════════════════════════════════════════════════════════════════════════════

def build_legal_argumentation(
    question:       str,
    semantic_frame: dict,
    chunks:         list[dict],
    domain:         str,
    cot:            dict,
    legal_decision: dict,
) -> dict:
    """
    يبني حجة قانونية كاملة وفق بنية IRAC المُبسَّطة.

    يعمل فقط عندما:
    - legal_decision["show_decision"] = True
    - domain في قائمة المجالات المدعومة
    - توفر بيانات كافية في semantic_frame / chunks

    لا يستدعي LLM — يُعيد مُخرجاً في أقل من 1ms.
    """
    _empty = {
        "show_argumentation": False,
        "legal_rule":         "",
        "fact_application":   "",
        "conclusion":         "",
        "counter_argument":   "",
        "proven_elements":    [],
        "missing_elements":   [],
        "argument_strength":  0.0,
    }

    # لا تعمل إلا عند وجود قرار
    if not legal_decision.get("show_decision"):
        return _empty

    # لا تعمل للمجالات غير المُعرَّفة
    templates = _IRAC_TEMPLATES.get(domain)
    if not templates:
        return _empty

    # ── استخراج المكونات ──────────────────────────────────────────────────────
    risk_level  = legal_decision.get("risk_level", "medium")
    legal_rule  = _extract_law_rule(chunks, cot, semantic_frame)
    fact_app    = _build_fact_application(semantic_frame, domain, templates)
    proven, missing = _check_evidence_elements(question, domain)
    strength    = _calc_argument_strength(proven, missing, chunks, question, risk_level, cot)

    # النتيجة والحجة المقابلة
    conclusion     = templates.get("conclusion_tpl", "")
    counter_arg    = templates.get("counter_tpl", "")
    rule_prefix    = templates.get("rule_prefix", "")

    # أكمل legal_rule بـ rule_prefix إذا كان فارغاً
    if not legal_rule:
        legal_rule = rule_prefix

    # إذا لا يوجد fact_application → لا نعرض
    if not fact_app or not legal_rule:
        return _empty

    # إضافة rule_prefix كسياق إذا كان legal_rule محدداً جداً
    full_rule = legal_rule
    if rule_prefix and rule_prefix not in legal_rule:
        full_rule = f"{rule_prefix}. {legal_rule}"

    log.info(
        "argumentation: domain=%s strength=%.1f proven=%d missing=%d",
        domain, strength, len(proven), len(missing),
    )

    return {
        "show_argumentation": True,
        "legal_rule":         full_rule,
        "fact_application":   fact_app,
        "conclusion":         conclusion,
        "counter_argument":   counter_arg  if risk_level in ("medium", "high") else "",
        "proven_elements":    proven,
        "missing_elements":   missing,
        "argument_strength":  strength,
    }


# ══════════════════════════════════════════════════════════════════════════════
# مُنسّق النص — Format Block
# ══════════════════════════════════════════════════════════════════════════════

def format_argumentation_block(arg: dict) -> str:
    """
    يُنشئ قسم التكييف القانوني المتقدم.
    مركّز، عميق، غير مكرر مع قسم القرار.
    """
    if not arg.get("show_argumentation"):
        return ""

    strength = arg["argument_strength"]
    lines    = ["\n\n---", "🧠 **التكييف القانوني المتقدم**\n"]

    # ── IRAC ──────────────────────────────────────────────────────────────────
    lines.append(f"⚖️ **النص الحاكم**: {arg['legal_rule']}")
    lines.append(f"\n🔗 **تطبيقه على حالتك**: {arg['fact_application']}")
    lines.append(f"\n✅ **النتيجة القانونية**: {arg['conclusion']}")

    # الحجة المقابلة
    if arg.get("counter_argument"):
        lines.append(f"\n🔄 **الحجة المقابلة المحتملة**: {arg['counter_argument']}")

    # ── قوة الحجة ──────────────────────────────────────────────────────────────
    lines.append(f"\n📊 **قوة الحجة القانونية**: {strength:.0f}/100 — {_get_strength_label(strength)}")

    # ── مصفوفة الإثبات ────────────────────────────────────────────────────────
    proven  = arg.get("proven_elements") or []
    missing = arg.get("missing_elements") or []

    if proven or missing:
        lines.append("\n🔍 **عناصر الإثبات**:")
        for e in proven[:3]:
            lines.append(f"  ✔️ {e}")
        for e in missing[:3]:
            lines.append(f"  ❌ {e} *(يحتاج إثباتاً)*")

    # تنبيه خاص عند الهشاشة
    if strength < 50 and missing:
        lines.append(
            f"\n> 💡 لتعزيز حجتك: ركّز على إثبات «{missing[0]}» — فهو العنصر الأهم في قضيتك."
        )

    return "\n".join(lines)


def apply_argumentation_to_answer(answer: str, arg: dict) -> str:
    """نقطة دخول موحّدة للتكامل في main.py"""
    block = format_argumentation_block(arg)
    if block:
        return answer + block
    return answer
