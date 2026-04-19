# -*- coding: utf-8 -*-
"""
Phase 0 Router — smart shunt BEFORE runtime_v2.

Routes every user query to the right handler:
    safety_refusal   → direct refusal
    greeting         → direct short greeting
    self_info        → direct self-description
    article_text     → DB article fetch
    table            → DB table fetch
    calculator       → deterministic math
    review           → direct invitation to paste the memo
    continuation     → LLM-driven follow-up
    memo             → smart memo (asks for gaps, else runtime_v2)
    general          → LLM + RAG (retrieval-augmented)

Runtime_v2 keeps serving ONLY explicit memo requests. Everything else
is handled in-router by specialized handlers.

Public API:
    route_query(query, history) → dict with {route, direct, payload?, response?}
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ═════════════════════════════════════════════════════════════════════
# 1. SAFETY REFUSAL
# ═════════════════════════════════════════════════════════════════════

_HARMFUL_PATTERNS = [
    r'كيف\s+أ?قت(?:ل|له|لها|لهم|لني)',
    r'كيف\s+أ?(?:ذبح|أذي|اذي|ضر|أضر|اضر)',
    r'طريق[ةه]\s+(?:لقتل|لإيذاء|للانتقام|لإبادة|للتخلص)',
    r'أبي\s+أ?قتل',
    r'ودي\s+أ?قتل',
    r'كيف\s+أ?تخلص\s+من\s+(?:شخص|واحد|عدو)',
    r'كيف\s+أ?خفي\s+(?:جث[ةه]|دليل|جريم[ةه]|جناي[ةه])',
    r'كيف\s+أ?هرب\s+من\s+(?:الشرط[ةه]|الجريم[ةه]|العدال[ةه])',
    r'بدون\s+ما\s+يكتشفوني',
    r'دون\s+أن\s+يكتشفوني',
    r'كيف\s+أ?صنع\s+(?:سلاح|قنبل[ةه]|متفجر|سم)',
    r'كيف\s+أ?نتحر',
    r'طريق[ةه]\s+للانتحار',
    r'أريد\s+(?:أن\s+)?(?:أقتل|انتحر)',
    r'(?:اغتصب|اغتصاب)\s+(?:شخص|طفل|امرأة)',
]

_SAFETY_RESPONSE = (
    "عذراً، لا أستطيع المساعدة في هذا النوع من الطلبات.\n\n"
    "إذا كنت تمر بضائقة نفسية، تواصل مع خط الدعم النفسي في قطر: "
    "**16000** (خدمة الدعم الصحي النفسي).\n\n"
    "إذا كان لديك سؤال قانوني مشروع — سواء استشارة أو صياغة مذكرة "
    "أو فهم مادة قانونية — أنا في خدمتك."
)


def check_safety(query: str) -> Optional[str]:
    q = (query or "").strip()
    if not q:
        return None
    for pat in _HARMFUL_PATTERNS:
        if re.search(pat, q):
            return _SAFETY_RESPONSE
    return None


# ═════════════════════════════════════════════════════════════════════
# 2. GREETINGS
# ═════════════════════════════════════════════════════════════════════

_GREETINGS: tuple[tuple[str, str], ...] = (
    ("السلام عليكم",  "وعليكم السلام ورحمة الله وبركاته — أهلاً بك! أنا ميزان، مستشارك القانوني القطري. كيف أقدر أساعدك؟"),
    ("وعليكم السلام", "أهلاً بك! كيف أقدر أخدمك اليوم؟"),
    ("مرحبا",         "أهلاً وسهلاً! أنا ميزان — مستشارك القانوني القطري. تفضل بسؤالك."),
    ("مرحبتين",       "أهلين! تفضل."),
    ("أهلا",          "أهلاً وسهلاً! كيف أقدر أساعدك؟"),
    ("اهلا",          "أهلاً وسهلاً! كيف أقدر أساعدك؟"),
    ("هلا",           "هلا والله! تفضل بسؤالك."),
    ("شحالك",         "الحمد لله بخير — تفضل كيف أقدر أساعدك؟"),
    ("كيفك",          "بخير والحمد لله — وأنت؟ كيف أقدر أخدمك؟"),
    ("صباح الخير",    "صباح النور والسرور — تفضل بسؤالك."),
    ("مساء الخير",    "مساء النور — كيف أقدر أساعدك؟"),
    ("شكرا",          "العفو — في خدمتك دائماً."),
    ("شكراً",         "العفو — في خدمتك دائماً."),
    ("مشكور",         "حياك الله."),
    ("تسلم",          "الله يسلمك."),
    ("مع السلامه",    "في أمان الله."),
    ("مع السلامة",    "في أمان الله."),
    ("سلام",          "وعليكم السلام."),
    ("باي",           "مع السلامة."),
    ("تمام",          "تمام — تحتاج شي ثاني؟"),
    ("اوكي",          "اوكي — تفضل."),
    ("اوك",           "اوكي — تفضل."),
)


def check_greeting(query: str) -> Optional[str]:
    q = re.sub(r"[^\w\s]", "", (query or "").strip()).strip().lower()
    if not q or len(q.split()) > 5:
        return None
    for key, resp in _GREETINGS:
        k = key.lower()
        if q == k or q.startswith(k + " "):
            return resp
    return None


# ═════════════════════════════════════════════════════════════════════
# 3. SELF INFO
# ═════════════════════════════════════════════════════════════════════

_SELF_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?:من\s+أنت|من\s+انت|وش\s+أنت|وش\s+انت|عرفني\s+على\s+نفسك|عرفني\s+(?:عليك|بك))",
        "أنا **ميزان** — مساعد قانوني ذكي متخصص في القانون القطري.\n\n"
        "أقدر أساعدك في:\n"
        "• صياغة المذكرات والدعاوى القانونية.\n"
        "• شرح القوانين وتفسير المواد.\n"
        "• البحث في أحكام محكمة التمييز (11,452 حكم).\n"
        "• حساب المستحقات (نهاية خدمة، تعويض فصل).\n"
        "• الاستشارات القانونية بناءً على 48,895 نص قانوني.\n\n"
        "تفضل بسؤالك!"
    ),
    (
        r"(?:وش\s+تقدر\s+تسوي|ماذا\s+تفعل|ماذا\s+تستطيع|قدراتك|إش\s+تسوي|وش\s+تعرف)",
        "أقدر أساعدك في:\n"
        "• **الصياغة القانونية:** مذكرات دفاع، دعاوى ابتدائية، طعون، عقود.\n"
        "• **الشرح والتفسير:** شرح المواد والقوانين القطرية.\n"
        "• **البحث القانوني:** 11,452 حكم تمييز + 48,895 نص قانوني.\n"
        "• **الحاسبات:** مكافأة نهاية الخدمة، تعويض الفصل التعسفي.\n"
        "• **الجداول المرجعية:** جدول المخدرات، المخالفات المرورية، وغيرها.\n\n"
        "تفضل بسؤالك!"
    ),
    (
        r"كم\s+(?:مبدأ|حكم|مادة)\s+(?:قانوني\s+)?(?:عندك|لديك)",
        "عندي:\n"
        "• **663 مبدأ قانوني** مستخلص من أحكام محكمة التمييز.\n"
        "• **48,895 نص قانوني** من القوانين القطرية النافذة.\n"
        "• **11,452 حكم تمييز** مفصّل.\n\n"
        "تبي أبحث لك في موضوع معيّن؟"
    ),
)


def check_self_info(query: str) -> Optional[str]:
    q = (query or "").strip().lower()
    if not q or len(q.split()) > 10:
        return None
    for pat, resp in _SELF_PATTERNS:
        if re.search(pat, q):
            return resp
    return None


# ═════════════════════════════════════════════════════════════════════
# 4. ARTICLE TEXT LOOKUP
# ═════════════════════════════════════════════════════════════════════

_LAW_HINT_MAP = (
    ("عقوبات",            "%قانون العقوبات رقم 11%"),
    ("الأسرة",             "%قانون الأسرة رقم 22%"),
    ("أسرة",               "%قانون الأسرة رقم 22%"),
    ("الاسره",             "%قانون الأسرة رقم 22%"),
    ("العمل",              "%قانون العمل رقم 14%"),
    ("عمل",                "%قانون العمل رقم 14%"),
    ("مخدرات",             "%مكافحة المخدرات%"),
    ("المخدرات",           "%مكافحة المخدرات%"),
    ("إيجار",              "%إيجار%العقارات%"),
    ("ايجار",              "%إيجار%العقارات%"),
    ("التجارة",            "%قانون التجارة%"),
    ("تجارة",              "%قانون التجارة%"),
    ("المدني",             "%القانون المدني%"),
    ("مدني",               "%القانون المدني%"),
    ("الإجراءات الجنائية", "%الإجراءات الجنائية%"),
    ("اجراءات",            "%الإجراءات الجنائية%"),
    ("الجرائم الإلكترونية","%مكافحة الجرائم الإلكترونية%"),
    ("الجرائم الالكترونية","%مكافحة الجرائم الإلكترونية%"),
    ("إلكترونية",          "%مكافحة الجرائم الإلكترونية%"),
)


def detect_article(query: str) -> Optional[Dict[str, Any]]:
    if not query:
        return None
    q = query.strip()
    # Normalized form for matching law hints
    q_norm = q.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")

    patterns = (
        r"نص\s+ال?مادة\s+\(?(\d+)\)?\s+(?:من\s+)?(?:ال)?قانون\s+([\w\s\u0621-\u064a]+?)(?:\s*[؟?!\n]|\s*$)",
        r"ال?مادة\s+\(?(\d+)\)?\s+من\s+(?:ال)?قانون\s+([\w\s\u0621-\u064a]+?)(?:\s*[؟?!\n]|\s*$)",
        r"ال?مادة\s+\(?(\d+)\)?\s+(عقوبات|[اأ]سرة|عمل|مخدرات|[اإ]يجار|تجارة|مدني)",
        r"نص\s+ال?مادة\s+\(?(\d+)\)?",
        r"ماد[ةه]\s+\(?(\d+)\)?\s+(عقوبات|[اأ]سرة|عمل|مخدرات|[اإ]يجار)",
    )
    for pat in patterns:
        m = re.search(pat, q_norm)
        if m:
            art = m.group(1)
            hint = m.group(2) if len(m.groups()) >= 2 else None
            law_pat: Optional[str] = None
            if hint:
                hint_norm = hint.strip()
                for key, pattern in _LAW_HINT_MAP:
                    if key in hint_norm:
                        law_pat = pattern
                        break
            return {
                "article_number": art,
                "law_pattern": law_pat,
                "law_hint": hint,
            }
    return None


# ═════════════════════════════════════════════════════════════════════
# 5. TABLE LOOKUP
# ═════════════════════════════════════════════════════════════════════

_TABLE_PATTERNS = (
    (r"جدول\s+ال?(?:مواد\s+)?(?:ال)?مخدر",            "drugs"),
    (r"(?:جدول|قائمة)\s+ال?(?:مواد\s+)?(?:ال)?محظور", "drugs"),
    (r"اعرض\s+(?:لي\s+)?جدول\s+(?:ال)?مخدر",          "drugs"),
    (r"جدول\s+(?:ال)?(?:درجات|رواتب|سلم)",             "salaries"),
    (r"جدول\s+(?:ال)?مخالف(?:ات)?\s+(?:ال)?مرور",     "traffic"),
    (r"جدول\s+(?:ال)?عقوب(?:ات)?",                      "penalties"),
)


def detect_table(query: str) -> Optional[str]:
    q = (query or "").strip().lower()
    for pat, tbl in _TABLE_PATTERNS:
        if re.search(pat, q):
            return tbl
    return None


# ═════════════════════════════════════════════════════════════════════
# 6. CALCULATOR
# ═════════════════════════════════════════════════════════════════════

def detect_calculator(query: str) -> Optional[Dict[str, Any]]:
    q = (query or "").strip().lower()

    # Disambiguators — if the query is asking for LEGAL ANALYSIS (not
    # just a calculation), do NOT route to calculator. These phrases
    # mean the user wants advice, counsel, or a full case review.
    _ANALYTICAL_MARKERS = (
        "ما حقوقي", "ماحقوقي", "حقوقي القانونية",
        "ماذا أفعل", "وش اسوي", "ما هي الخطوات", "ما الخطوات",
        "فصلني", "فصلوني", "طردني", "طردوني", "سرحني",
        "صاحب العمل", "لم يعطني", "ما أعطاني", "ما اعطاني",
        "شهادة خبرة", "شهادة الخبرة", "بدون سبب", "بدون انذار",
        "هل يحق", "هل يجوز", "هل استحق",
    )
    if any(m in q for m in _ANALYTICAL_MARKERS):
        return None

    calc_type: Optional[str] = None
    # End-of-service: catch "احسب / كيف تحسب / كيف أحسب / حساب" + مكافأة
    if re.search(
        r"(?:احسب|حساب|كيف\s+(?:ا|ت|ن)?حسب|كم)\s+(?:لي\s+)?(?:كم\s+)?(?:ال)?(?:مكافأة|مكافاه)",
        q,
    ):
        calc_type = "end_of_service"
    # مكافأة نهاية الخدمة + أرقام، فقط إذا ليس فيه أي analytical marker
    elif re.search(
        r"(?:مكافأة|مكافاه)\s+نهاي[ةه]\s+(?:ال)?خدم[ةه]", q,
    ) and re.search(r"\d", q) and (
        q.startswith("احسب") or q.startswith("كم ") or q.startswith("احسبلي")
    ):
        calc_type = "end_of_service"
    # Unfair-dismissal compensation — explicit احسب تعويض
    elif re.search(
        r"(?:احسب|حساب|كيف\s+(?:ا|ت|ن)?حسب)\s+(?:لي\s+)?تعويض", q,
    ):
        calc_type = "unfair_dismissal"
    if not calc_type:
        return None

    salary: Optional[int] = None
    years: Optional[int] = None

    m = re.search(r"(?:راتب(?:ي)?|الراتب|معاش(?:ي)?)\s+(\d[\d,]*)", q)
    if m:
        salary = int(m.group(1).replace(",", ""))
    if salary is None:
        m = re.search(r"(\d[\d,]*)\s*(?:ألف|الف)", q)
        if m:
            salary = int(m.group(1).replace(",", "")) * 1000
    if salary is None:
        # raw number 4+ digits
        m = re.search(r"\b(\d{4,6})\b", q)
        if m:
            salary = int(m.group(1))

    m = re.search(r"(\d+)\s*(?:سنة|سنوات|سنه|عام|أعوام|اعوام)", q)
    if m:
        years = int(m.group(1))

    return {"type": calc_type, "salary": salary, "years": years}


# ═════════════════════════════════════════════════════════════════════
# 7. MEMO REQUEST
# ═════════════════════════════════════════════════════════════════════

_MEMO_TRIGGERS = (
    "اكتب مذكرة", "اكتب لي مذكرة", "اكتبلي مذكرة",
    "صيغ مذكرة", "صيغ لي مذكرة", "صغ لي مذكرة", "صغ مذكرة",
    "حرر مذكرة", "حرر لي مذكرة",
    "أريد مذكرة", "اريد مذكرة", "ابي مذكرة", "أبي مذكرة", "أبغي مذكرة", "ابغى مذكرة",
    "احتاج مذكرة", "محتاج مذكرة",
    "جهز مذكرة", "جهز لي مذكرة",
    "اعمل مذكرة", "سوي مذكرة", "سوي لي مذكرة", "اعمل لي مذكرة",
    "مذكرة دفاع", "مذكرة ادعاء", "مذكرة رد", "مذكرة قانونية",
    "لائحة دعوى", "اكتب لائحة", "صحيفة دعوى",
    "اكتب عقد", "صيغ عقد", "عريضة",
)


def is_memo_request(query: str) -> bool:
    q = (query or "").strip().lower()
    return any(t in q for t in _MEMO_TRIGGERS)


# ═════════════════════════════════════════════════════════════════════
# 8. REVIEW REQUEST
# ═════════════════════════════════════════════════════════════════════

_REVIEW_PATTERNS = (
    r"راجع\s+(?:لي\s+)?(?:ال)?مذكرة",
    r"قيّ?م\s+(?:لي\s+)?(?:ال)?مذكرة",
    r"ب?أرسل\s+لك\s+مذكرة",
    r"برسل\s+لك\s+مذكرة",
    r"عدل\s+(?:لي\s+)?(?:ال)?مذكرة",
)


def is_review_request(query: str) -> bool:
    q = (query or "").strip().lower()
    return any(re.search(p, q) for p in _REVIEW_PATTERNS)


# ═════════════════════════════════════════════════════════════════════
# 9. CONTINUATION
# ═════════════════════════════════════════════════════════════════════

_CONT_MARKERS: tuple[tuple[str, str], ...] = (
    ("كمّل",         "continue"),
    ("كمل",          "continue"),
    ("اكمل",         "continue"),
    ("أكمل",         "continue"),
    ("تابع",         "continue"),
    ("اختصر",        "shorten"),
    ("قصّر",         "shorten"),
    ("قصر",          "shorten"),
    ("وضح",          "expand"),
    ("وضح أكثر",     "expand"),
    ("فصّل",         "expand"),
    ("فصل",          "expand"),
    ("اشرح أكثر",    "expand"),
    ("اشرح اكثر",    "expand"),
    ("مش كذا",       "rephrase"),
    ("غلط",          "rephrase"),
    ("أعد",          "rephrase"),
    ("اعد الصياغة",  "rephrase"),
)


def detect_continuation(query: str, has_history: bool) -> Optional[str]:
    if not has_history:
        return None
    q = (query or "").strip().lower()
    if not q or len(q.split()) > 4:
        return None
    for marker, action in _CONT_MARKERS:
        m = marker.lower()
        if q == m or q.startswith(m + " "):
            return action
    return None


# ═════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ═════════════════════════════════════════════════════════════════════

def route_query(
    query: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Dispatch the query to one of the 10 routes.

    Returns:
        dict with:
          route    — str (safety_refusal|greeting|self_info|article_text|
                     table|calculator|memo|review|continuation|general)
          direct   — bool (True → ready-to-stream response attached)
          response — str (only when direct=True)
          payload  — dict (handler-specific context)
    """
    has_hist = bool(history)

    # 1. SAFETY — highest priority
    refusal = check_safety(query)
    if refusal:
        return {"route": "safety_refusal", "response": refusal, "direct": True}

    # 2. Greeting
    greeting = check_greeting(query)
    if greeting:
        return {"route": "greeting", "response": greeting, "direct": True}

    # 3. Self info
    self_info = check_self_info(query)
    if self_info:
        return {"route": "self_info", "response": self_info, "direct": True}

    # 4. Article text
    article = detect_article(query)
    if article:
        return {"route": "article_text", "payload": article, "direct": False}

    # 5. Table
    table = detect_table(query)
    if table:
        return {"route": "table", "payload": {"table_type": table}, "direct": False}

    # 6. Calculator
    calc = detect_calculator(query)
    if calc:
        return {"route": "calculator", "payload": calc, "direct": False}

    # 7. Memo
    if is_memo_request(query):
        return {"route": "memo", "direct": False}

    # 8. Review
    if is_review_request(query):
        return {
            "route": "review",
            "response": (
                "تفضل أرسل نص المذكرة — سأراجعها من حيث:\n"
                "• صحة المواد والقوانين المستشهَد بها.\n"
                "• منطق الدفوع وترتيبها من الأقوى للأضعف.\n"
                "• ملاءمة الطلبات للتكييف القانوني.\n"
                "• الأسلوب الإقناعي والصياغة القضائية."
            ),
            "direct": True,
        }

    # 9. Continuation
    cont = detect_continuation(query, has_hist)
    if cont:
        return {
            "route": "continuation",
            "payload": {"action": cont},
            "direct": False,
        }

    # 10. General — falls back to LLM + RAG
    return {"route": "general", "direct": False}
