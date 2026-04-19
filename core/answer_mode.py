# -*- coding: utf-8 -*-
"""
Answer Mode Controller
======================
1. Classify the appropriate answer mode
2. Build the right prompt instruction (no memo template for simple queries)
3. Detect user style preferences
4. Post-process: strip memo headers from direct answers
5. Persist context/topic across follow-ups
"""
import re, logging
from enum import Enum
from typing import Optional

log = logging.getLogger("answer_mode")


# ══════════════════════════════════════════════════════════════
# Part 1: Answer Mode Classification
# ══════════════════════════════════════════════════════════════

class AnswerMode(str, Enum):
    DIRECT_SHORT = "direct_short"         # كم راتب الدرجة السابعة → one-line answer
    TABLE_ROW = "table_row"               # جدول الرواتب → table output
    STRUCTURED_LIST = "structured_list"   # اذكر الأسماء فوق بعض → numbered list
    LEGAL_ANALYSIS = "legal_analysis"     # ما أثر بطلان القبض → full analysis
    FOLLOWUP_SHORT = "followup_short"     # طيب الدرجة السابعة فقط → continue topic, short


# User signals that demand brevity
_BREVITY_SIGNALS = [
    "فقط", "بس", "على قدر السؤال", "بدون شرح", "لا تشرح",
    "لا أريد شرح", "مختصر", "اختصر", "بدال الفلسفة",
    "جاوب على قدر السؤال", "بشكل مباشر", "مباشرة",
]

# User signals that demand list format
_LIST_SIGNALS = [
    "فوق بعض", "مرتب ومرقم", "بشكل مرتب", "قائمة",
    "اذكر الأسماء", "اذكرها", "عدد لي", "اكتب أسماء",
]

# Signals of a follow-up narrowing the scope
_NARROWING_SIGNALS = [
    "سؤالي محدد", "سألت عن", "فقط الدرجة", "بس الدرجة",
    "أنا سألت", "قلت لك", "نفس الموضوع", "بخصوص نفس",
    "الي سألتك عنه", "اللي سألتك",
]

# Analytical queries that warrant full legal analysis
_ANALYSIS_SIGNALS = [
    "ما أثر", "ما حكم", "هل يحق", "هل يجوز",
    "ما الفرق بين", "قارن بين", "اشرح لي",
    "واحد ضربني", "طليقتي", "فصلوني", "متهم بـ",
    "اكتب مذكرة", "صغ لي", "ارفع دعوى",
]


def classify_answer_mode(query: str, history: list = None,
                          brain_route: str = "", lookup_intent: str = "") -> AnswerMode:
    """Determine the appropriate answer mode based on query and context."""
    q = query.lower().strip()
    has_history = bool(history and len(history) >= 2)

    # Lookup intents → specific modes
    if lookup_intent in ("salary_query", "salary_grade_lookup"):
        if any(s in q for s in _BREVITY_SIGNALS) or any(s in q for s in _NARROWING_SIGNALS):
            return AnswerMode.DIRECT_SHORT
        return AnswerMode.TABLE_ROW

    if lookup_intent in ("drug_table", "table_lookup"):
        if any(s in q for s in _LIST_SIGNALS):
            return AnswerMode.STRUCTURED_LIST
        return AnswerMode.TABLE_ROW

    if lookup_intent == "enumeration_list":
        return AnswerMode.STRUCTURED_LIST

    # Follow-up narrowing → short
    if has_history and any(s in q for s in _NARROWING_SIGNALS):
        log.info("[ANSWER_MODE] FOLLOWUP_SHORT: narrowing detected")
        return AnswerMode.FOLLOWUP_SHORT

    # User demands brevity
    if any(s in q for s in _BREVITY_SIGNALS):
        return AnswerMode.DIRECT_SHORT

    # User demands list format
    if any(s in q for s in _LIST_SIGNALS):
        return AnswerMode.STRUCTURED_LIST

    # Analytical / complex legal queries
    if any(s in q for s in _ANALYSIS_SIGNALS):
        return AnswerMode.LEGAL_ANALYSIS

    # Brain route hints
    if brain_route in ("greeting", "filler", "thanks", "self_info"):
        return AnswerMode.DIRECT_SHORT

    if brain_route in ("knowledge",):
        return AnswerMode.DIRECT_SHORT

    if brain_route in ("consultation", "drafting"):
        return AnswerMode.LEGAL_ANALYSIS

    # Short questions → direct
    if len(q.split()) <= 8:
        return AnswerMode.DIRECT_SHORT

    # Default for legal questions
    return AnswerMode.LEGAL_ANALYSIS


# ══════════════════════════════════════════════════════════════
# Part 2: Prompt Instruction Builder
# ══════════════════════════════════════════════════════════════

_INSTRUCTIONS = {
    AnswerMode.DIRECT_SHORT: (
        "تعليمات: أجب بشكل مباشر ومختصر. "
        "لا تستخدم هيكل التكييف/السند/التحليل. "
        "جملة أو جملتين مع ذكر المادة القانونية إن وجدت."
    ),
    AnswerMode.TABLE_ROW: (
        "تعليمات: اعرض البيانات بشكل جدول أو صفوف مرتبة. "
        "لا تضف شرحاً طويلاً. لا تستخدم هيكل التكييف/السند. "
        "اعرض الأرقام والبيانات مباشرة."
    ),
    AnswerMode.STRUCTURED_LIST: (
        "تعليمات: اكتب الإجابة على شكل قائمة مرقمة. "
        "كل عنصر في سطر منفصل. "
        "بدون مقدمات أو شرح إضافي. بدون هيكل التكييف/السند."
    ),
    AnswerMode.FOLLOWUP_SHORT: (
        "تعليمات: المستخدم يطلب توضيحاً محدداً لسؤال سابق. "
        "أجب مباشرة على النقطة المحددة فقط. لا تعيد الإجابة الكاملة. "
        "لا تستخدم هيكل التكييف/السند/التحليل."
    ),
    AnswerMode.LEGAL_ANALYSIS: (
        "تعليمات: اختر النص الأنسب للموضوع (ليس الأحدث). "
        "ابدأ بالإجابة المباشرة ثم السند القانوني ثم التوضيح ثم التوصية العملية. "
        "استخدم الهيكل المرقّم (📋⚖️🔍⚠️✅) فقط للاستشارات الشخصية المفصّلة. "
        "للأسئلة المعرفية البسيطة: فقرة أو فقرتين بأسلوب طبيعي."
    ),
}


def build_prompt_instruction(mode: AnswerMode, query: str = "") -> str:
    """Build the right instruction for the LLM based on answer mode."""
    base = _INSTRUCTIONS.get(mode, _INSTRUCTIONS[AnswerMode.LEGAL_ANALYSIS])

    # Add user-specific formatting constraints
    q = query.lower()
    extras = []
    if "فوق بعض" in q:
        extras.append("اكتب كل عنصر في سطر منفصل.")
    if "مرقم" in q or "مرتب" in q:
        extras.append("رقّم العناصر.")
    if "فقط" in q or "بس" in q:
        extras.append("لا تضف معلومات إضافية.")
    if "بدون شرح" in q or "لا تشرح" in q:
        extras.append("بدون أي شرح.")

    if extras:
        base += "\n" + " ".join(extras)

    log.info("[ANSWER_MODE] mode=%s instruction_len=%d", mode.value, len(base))
    return base


# ══════════════════════════════════════════════════════════════
# Part 3: Post-Processor — Strip Memo Headers from Non-Analysis
# ══════════════════════════════════════════════════════════════

_MEMO_HEADERS = [
    r"📋\s*(?:التكييف|التكييف القانوني)\s*:?\s*\n?",
    r"⚖️\s*(?:السند|السند القانوني|السند النظامي)\s*:?\s*\n?",
    r"🔍\s*(?:التحليل|التحليل القانوني)\s*:?\s*\n?",
    r"⚠️\s*(?:الاستثناءات|التنبيهات|ملاحظات)\s*:?\s*\n?",
    r"✅\s*(?:التوصية|التوصيات)\s*:?\s*\n?",
    r"📊\s*(?:الثقة|مستوى الثقة|درجة الثقة)\s*:?\s*\n?",
]

_FILLER_STARTS = [
    "بناءً على النصوص القانونية المتوفرة",
    "بعد مراجعة النصوص القانونية",
    "وفق أحكام التشريع القطري",
    "استناداً إلى النصوص القانونية",
]


def post_process_answer(answer: str, mode: AnswerMode) -> str:
    """Clean up the answer to match the requested style."""
    if mode == AnswerMode.LEGAL_ANALYSIS:
        return answer  # Keep full structure for analysis mode

    result = answer

    # Strip memo section headers
    for pattern in _MEMO_HEADERS:
        result = re.sub(pattern, "", result)

    # For DIRECT_SHORT and FOLLOWUP_SHORT: strip filler openings
    if mode in (AnswerMode.DIRECT_SHORT, AnswerMode.FOLLOWUP_SHORT):
        for filler in _FILLER_STARTS:
            if result.strip().startswith(filler):
                idx = result.find("،", len(filler))
                if idx > 0 and idx < len(filler) + 30:
                    result = result[idx + 1:].strip()

    # For STRUCTURED_LIST: ensure line-by-line format
    if mode == AnswerMode.STRUCTURED_LIST:
        # Clean up OCR noise in list items
        result = re.sub(r"\n{3,}", "\n\n", result)

    # Clean up double whitespace
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r" {2,}", " ", result)

    if result != answer:
        log.info("[STYLE_ENFORCE] post-processed: removed %d chars", len(answer) - len(result))

    return result.strip()


# ══════════════════════════════════════════════════════════════
# Part 4: Follow-Up Context Persistence
# ══════════════════════════════════════════════════════════════

class ConversationContext:
    """Tracks the current topic and resolved entities across turns."""

    def __init__(self):
        self.topic: str = ""             # e.g. "salary", "drug_law", "custody"
        self.resolved_entity: str = ""    # e.g. "الدرجة السابعة", "القطاع الحكومي"
        self.answer_target: str = ""      # e.g. "exact grade seven salary"
        self.user_prefs: list[str] = []   # e.g. ["direct_only", "no_explanation"]
        self.last_lookup_intent: str = ""
        self.turns: int = 0

    def update(self, query: str, lookup_intent: str = "", answer_mode: str = ""):
        q = query.lower()
        self.turns += 1

        # Detect topic
        if lookup_intent in ("salary_query", "salary_grade_lookup"):
            self.topic = "salary"
        elif lookup_intent in ("drug_table",):
            self.topic = "drug_schedule"
        elif "حضانة" in q or "طلاق" in q:
            self.topic = "family"
        elif "عقوبة" in q or "جريمة" in q:
            self.topic = "criminal"

        if lookup_intent:
            self.last_lookup_intent = lookup_intent

        # Detect resolved entities
        grade_match = re.search(r"(?:الدرجة|درجة)\s*(?:ال)?(أولى|ثانية|ثالثة|رابعة|خامسة|سادسة|سابعة|سابعه|ممتازة|خاصة|الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الممتازة|الخاصة|\d+)", q)
        if grade_match:
            self.resolved_entity = "الدرجة " + grade_match.group(1)

        if "حكومي" in q or "القطاع الحكومي" in q or "جهة حكومية" in q:
            self.resolved_entity += " (قطاع حكومي)"

        # Detect user preferences
        if any(s in q for s in _BREVITY_SIGNALS):
            if "direct_only" not in self.user_prefs:
                self.user_prefs.append("direct_only")
        if any(s in q for s in _LIST_SIGNALS):
            if "list_format" not in self.user_prefs:
                self.user_prefs.append("list_format")

        log.info("[CONTEXT_LOCK] topic=%s entity=%s prefs=%s turns=%d",
                 self.topic, self.resolved_entity, self.user_prefs, self.turns)

    def should_stay_on_topic(self, query: str) -> bool:
        """Check if this follow-up should stay on the current topic."""
        q = query.lower()
        if self.turns < 2:
            return False
        if any(s in q for s in _NARROWING_SIGNALS):
            return True
        if self.topic == "salary" and any(s in q for s in ["درجة", "راتب", "مربوط", "إجمالي"]):
            return True
        if self.topic == "drug_schedule" and any(s in q for s in ["مخدر", "مواد", "اسماء"]):
            return True
        return False

    def get_context_hint(self) -> str:
        """Build context hint for the LLM."""
        parts = []
        if self.topic:
            parts.append(f"الموضوع الحالي: {self.topic}")
        if self.resolved_entity:
            parts.append(f"الكيان المحدد: {self.resolved_entity}")
        if "direct_only" in self.user_prefs:
            parts.append("المستخدم يريد إجابة مباشرة فقط")
        if parts:
            return "[سياق المحادثة: " + " | ".join(parts) + "]\n"
        return ""


# Session-level context storage (keyed by session_id)
_contexts: dict[str, ConversationContext] = {}


def get_context(session_id: str) -> ConversationContext:
    if session_id not in _contexts:
        _contexts[session_id] = ConversationContext()
    return _contexts[session_id]
