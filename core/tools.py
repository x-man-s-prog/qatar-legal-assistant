# -*- coding: utf-8 -*-
"""
Legal Tools — أدوات حسابية وبحث مباشر.
"""
import re, logging
from typing import Optional, Dict

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# حاسبة مكافأة نهاية الخدمة (قانون العمل رقم 14 لسنة 2004)
# ════════════════════════════════════════════════════════════

def calc_end_of_service(salary: float, years: float) -> Dict:
    """
    يحسب مكافأة نهاية الخدمة حسب قانون العمل القطري.
    المادة 54: 3 أسابيع عن كل سنة خدمة.
    """
    if salary <= 0 or years <= 0:
        return {"error": "الراتب وسنوات الخدمة يجب أن تكون أكبر من صفر"}

    weekly_salary = salary / 4.33  # تقريباً 4.33 أسبوع بالشهر
    reward = weekly_salary * 3 * years  # 3 أسابيع × عدد السنوات

    return {
        "salary": salary,
        "years": years,
        "weekly_salary": round(weekly_salary, 2),
        "reward": round(reward, 2),
        "formula": "3 أسابيع × %d سنة = %.0f ريال" % (int(years), reward),
        "legal_basis": "المادة 54 من قانون العمل رقم 14 لسنة 2004",
        "note": "هذا الحساب تقريبي. المبلغ النهائي يعتمد على تفاصيل العقد.",
    }


# ════════════════════════════════════════════════════════════
# حاسبة تعويض الفصل التعسفي
# ════════════════════════════════════════════════════════════

def calc_unfair_dismissal(salary: float, years: float, notice_period_months: int = 1) -> Dict:
    """
    يحسب تعويض الفصل التعسفي.
    المادة 49: تعويض لا يقل عن أجر شهرين.
    + مكافأة نهاية الخدمة + بدل إنذار.
    """
    if salary <= 0 or years <= 0:
        return {"error": "الراتب وسنوات الخدمة يجب أن تكون أكبر من صفر"}

    # 1. تعويض الفصل التعسفي (المادة 49): لا يقل عن أجر شهرين
    dismissal_comp = max(salary * 2, salary * years * 0.5)

    # 2. بدل الإنذار (المادة 47)
    notice_comp = salary * notice_period_months

    # 3. مكافأة نهاية الخدمة
    eos = calc_end_of_service(salary, years)
    eos_reward = eos.get("reward", 0)

    total = dismissal_comp + notice_comp + eos_reward

    return {
        "salary": salary,
        "years": years,
        "dismissal_compensation": round(dismissal_comp, 2),
        "notice_compensation": round(notice_comp, 2),
        "end_of_service": round(eos_reward, 2),
        "total": round(total, 2),
        "breakdown": (
            "1. تعويض فصل تعسفي: %.0f ريال (المادة 49)\n"
            "2. بدل إنذار: %.0f ريال (المادة 47)\n"
            "3. مكافأة نهاية خدمة: %.0f ريال (المادة 54)\n"
            "المجموع: %.0f ريال"
        ) % (dismissal_comp, notice_comp, eos_reward, total),
        "legal_basis": "المواد 47، 49، 54 من قانون العمل رقم 14 لسنة 2004",
    }


# ════════════════════════════════════════════════════════════
# كاشف طلبات الحساب من النص
# ════════════════════════════════════════════════════════════

_SALARY_RE = re.compile(
    r"(?:راتب|راتبي|أتقاضى|معاش|أجر)\s*(?:الشهري|الأساسي)?\s*(\d[\d,\.]*)",
    re.IGNORECASE
)
_YEARS_RE = re.compile(
    r"(\d+)\s*(?:سن[وة]ات?|سنه|أعوام|عام)",
    re.IGNORECASE
)

def detect_calculation_request(query: str) -> Optional[Dict]:
    """
    يكتشف إذا المستخدم يطلب حساب ويستخرج الأرقام.
    Returns: {type, salary, years} or None
    """
    q = query.lower()

    # كشف طلب حساب
    calc_keywords = ["احسب", "حاسب", "كم مكافأة", "كم مكافاة", "كم تعويض",
                     "كم يطلع", "كم يصير", "كم استحق", "كم أستحق",
                     "مكافأة نهاية", "مكافاة نهاية", "نهاية خدمة",
                     "فصل تعسفي", "تعويض الفصل"]

    if not any(kw in q for kw in calc_keywords):
        return None

    # استخراج الراتب
    salary_match = _SALARY_RE.search(query)
    salary = 0
    if salary_match:
        salary = float(salary_match.group(1).replace(",", ""))
    else:
        # حاول الأرقام الكبيرة (> 1000 = راتب)
        nums = re.findall(r"(\d[\d,\.]*)", query)
        for n in nums:
            val = float(n.replace(",", ""))
            if 1000 <= val <= 200000:
                salary = val
                break

    # استخراج السنوات
    years_match = _YEARS_RE.search(query)
    years = 0
    if years_match:
        years = float(years_match.group(1))
    else:
        nums = re.findall(r"(\d+)", query)
        for n in nums:
            val = int(n)
            if 1 <= val <= 50 and val != salary:
                years = val
                break

    if salary <= 0 or years <= 0:
        return {"type": "incomplete", "salary": salary, "years": years,
                "missing": "salary" if salary <= 0 else "years"}

    # حدد نوع الحساب
    if "فصل تعسفي" in q or "تعويض الفصل" in q:
        calc_type = "unfair_dismissal"
    else:
        calc_type = "end_of_service"

    return {"type": calc_type, "salary": salary, "years": years}


def execute_tool(query: str) -> Optional[str]:
    """
    يكتشف وينفّذ الأداة المناسبة.
    Returns: نص الإجابة أو None.
    """
    req = detect_calculation_request(query)
    if not req:
        return None

    if req["type"] == "incomplete":
        missing = "الراتب الشهري" if req["missing"] == "salary" else "عدد سنوات الخدمة"
        return "لحساب المكافأة أحتاج منك %s. ممكن تعطيني الرقم؟" % missing

    if req["type"] == "end_of_service":
        result = calc_end_of_service(req["salary"], req["years"])
        return (
            "🧮 **حساب مكافأة نهاية الخدمة:**\n\n"
            "• الراتب الشهري: {:,.0f} ريال\n"
            "• مدة الخدمة: {} سنة\n"
            "• الراتب الأسبوعي: {:,.0f} ريال\n\n"
            "**المكافأة المستحقة: {:,.0f} ريال**\n\n"
            "📎 الأساس: {}\n"
            "⚠️ {}"
        ).format(result["salary"], int(result["years"]),
                 result["weekly_salary"], result["reward"],
                 result["legal_basis"], result["note"])

    if req["type"] == "unfair_dismissal":
        result = calc_unfair_dismissal(req["salary"], req["years"])
        return (
            "🧮 **حساب تعويض الفصل التعسفي:**\n\n"
            "{}\n\n"
            "📎 الأساس: {}"
        ).format(result["breakdown"], result["legal_basis"])

    return None
