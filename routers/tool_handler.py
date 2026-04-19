# -*- coding: utf-8 -*-
"""
routers/tool_handler.py — Tool & Direct Data Handlers
=======================================================
Article lookup, table fetch, known answers, greetings, tools,
and all fast-exit paths that bypass the RAG pipeline.
"""
import re
import json
import logging
from core import app_state
from core.nlp_utils import classify_query, _get_instant_response, get_history, add_to_history
from core.qatar_legal_knowledge import match_known_answer, is_non_crime
from core.knowledge_map import find_answer_source, smart_fetch as km_smart_fetch
from core.tools import execute_tool

log = logging.getLogger(__name__)

# ── Greeting sets ──
STREAM_GREETINGS = {
    "السلام عليكم","وعليكم السلام","مرحبا","مرحباً","أهلا","أهلاً","هلا","هلا والله",
    "مساء الخير","صباح الخير","شحالك","شحالكم","علومك","علومكم","شخبارك","شلونك","شلونكم",
    "كيف حالك","كيف الحال","كيفك","عساك طيب","عساكم بخير","هاي","الو","يا هلا","هلو",
    "اخبارك","أخبارك","اشلونك","شو أخبارك","اهلين","مرحبتين","السلام","سلام","تحية",
}

STREAM_FILLERS = {
    "الحمدلله","حمدالله","بخير","تمام","كويس","زين","الحمد لله",
    "بخير الحمدلله","تمام الحمدلله","احتاجك","ساعدني","ابي مساعدة","عندي سؤال",
    "احتاجك تساعدني","عندي موضوع","عندي مشكلة","ابي مساعده","ان شاء الله",
    "إن شاء الله","الله يوفقك","الله يسعدك","بارك الله فيك",
}

STREAM_THANKS = {
    "شكراً","شكرا","مشكور","يعطيك العافية","جزاك الله خير","تسلم","الله يسلمك",
    "شكراً جزيلاً","مشكور وما قصرت","الله يجزاك خير","تمام مشكور",
}

STREAM_CAP = [
    "وش تقدر تسوي","ايش تقدر تسوي","من أنت","من انت","وش مهامك","كيف تساعدني",
    "وش تعرف تسوي","وش المهام","تقدر تكتب مذكرات","قدراتك","ايش تعرف",
]

SELF_PATTERNS = [
    "كم مبدأ","كم حكم","كم قانون","كم مادة","كم عندك","ماذا تعرف","وش عندك من",
    "عدد المبادئ","عدد الأحكام","عدد القوانين","قاعدة بياناتك","ذاكرتك","معلوماتك",
    "أي قوانين عندك","وش القوانين","كم سؤال تقدر","وش حدودك","إحصائيات",
]

REVIEW_WORDS = [
    "قيمها","قيّمها","قيم لي","عطني رايك","رايك فيها",
    "راجعها","راجع لي","حلل لي","حللها","وش رايك فيها","تقييمك",
    "برسلك مذكرة","بأرسلك","ابي تقييم","عطني تقييم","عطني ملاحظات",
    "ابغيك تقيمها","ابيك تراجعها","حلل المذكرة","قيّم المذكرة",
    "نقاط القوة","نقاط الضعف","وين القوة","وين الضعف",
]

MEMO_SIGNS = [
    "عدالة محكمة","عدالة المحكمة","مذكرة دفاع","مقدمة من",
    "المستأنف","المدعي:","المدعى عليه","لائحة دعوى","مقدمة إلى",
    "الموقرة","أَحْمَدُهُ","اما بعد","أولاً","ثانياً","ثالثاً",
    "الطلبات","حافظة مستندات","الدعوى رقم","المحدد لنظرها",
    "بطاقة رقم","استئناف رقم","ابتدائي رقم","مذكرة ورد",
]

# Article request regex
ART_REQUEST_RE = re.compile(
    r'(?:نص|عطني نص|اكتب نص|اعرض|عطني)\s*(?:المادة|الماده|مادة|م\.?\s*)[\(]?\s*(\d{1,3})\s*[\)]?',
    re.UNICODE
)

# Law keyword map for article lookup
LAW_KW_MAP = {
    "%أسرة%": ["أسرة","اسرة","الأسرة","الاسرة","حضانة","طلاق","نفقة","زواج","خلع"],
    "%عقوبات%11%": ["عقوبات","العقوبات"],
    "%14%لسنة%2004%": ["عمل","العمل"],
    "%مخدر%": ["مخدر","مخدرات","المخدرات"],
    "%مرافعات%": ["مرافعات","المرافعات"],
    "%إجراءات%جنائ%": ["إجراءات","جنائية","الإجراءات الجنائية"],
    "%مدن%": ["مدني","المدني","القانون المدني"],
    "%تجار%": ["تجاري","التجاري","شركات"],
}

# Table triggers
TABLE_TRIGGERS = [
    "جدول رقم","الجدول الملحق","ملحق رقم","عدد لي","اذكر لي",
    "المواد المحظورة","المواد الكيميائية","سلم الرواتب","جدول المخدرات",
    "جدول الرواتب","درجة مالية","جدول الدرجات","المواد المدرجة",
    "كم راتب","راتب موظف","راتب درجة","كم الراتب",
    "رواتب الموظفين","راتب الدرجة","الدرجة المالية",
    "سلم الدرجات","كم يكون الراتب","رواتب الدرجات",
]

# Drafting keywords
STREAM_DRAFT = (
    'صيغ لي','صيغ ','صياغة','اكتب لي','اكتب مذكرة','مذكرة دفاع','مذكرة','لائحة',
    'أبي مذكرة','ابي مذكرة','ابغي مذكرة','عطني مذكرة','عطني نموذج','نموذج عقد',
    'عقد إيجار','عقد عمل','عقد شراكة','مذكرة قانونية','صحيفة دعوى',
)

PERSONAL_MARKERS = [
    "أنا","عندي","معي","صار لي","حصل لي","موقفي","قضيتي",
    "وقفتني","فتشتني","ضربني","فصلتني","طردني","طفشني",
    "زوجي","زوجتي","حرمتي","طليقتي","مسكوني","ودوني",
    "صار علي","صار عليّ","ولدي","بنتي","أخوي","خويي",
]

FOLLOWUP_MARKERS = [
    "بس ","لكن ","وليش","وكيف","يعني ","ليش ما","وبالنسبة",
    "ارجع ل","بخصوص","المواد الي","النقطة الي","ما قلت","ما ذكرت",
    "ادعم","قوّي","فصّل","وضّح","اشرح اكثر","زد على","كمّل","أكمل",
]


def is_greeting(q: str) -> bool:
    """Check if query is a greeting."""
    qs = q.strip()
    return qs in STREAM_GREETINGS or any(
        qs.startswith(g) and len(qs) < len(g) + 15 for g in STREAM_GREETINGS
    )


def is_filler(q: str, history: list) -> bool:
    """Check if query is a filler/acknowledgement."""
    qs = q.strip()
    return qs in STREAM_FILLERS or (
        qs in {"طيب","اوكي","ماشي","خلاص","اها","اي","نعم","ايه","صح"} and len(history) < 2
    )


def is_thanks(q: str) -> bool:
    """Check if query is a thank you/goodbye."""
    qs = q.strip()
    return qs in STREAM_THANKS or any(t in qs for t in STREAM_THANKS)


def is_capability_question(q: str) -> bool:
    """Check if query asks about system capabilities."""
    qs = q.strip()
    return any(c in qs for c in STREAM_CAP)


def is_self_question(q: str) -> bool:
    """Check if query asks about system stats."""
    qs = q.strip()
    return any(p in qs for p in SELF_PATTERNS)


def detect_drafting(q: str) -> bool:
    """Check if query is a drafting request."""
    return any(kw in q for kw in STREAM_DRAFT)


def detect_personal(q: str) -> bool:
    """Check if query contains personal markers."""
    return len(q.split()) > 20 or any(m in q for m in PERSONAL_MARKERS)


def detect_followup(q: str, history: list) -> bool:
    """Check if query is a follow-up."""
    return any(q.startswith(m) or m in q for m in FOLLOWUP_MARKERS) and len(history) >= 2


def detect_review(q: str, history: list) -> tuple[bool, bool, bool]:
    """
    Detect memo review request.
    Returns (is_review, has_review_kw, is_submitted_memo).
    """
    has_review_kw = any(rw in q for rw in REVIEW_WORDS)
    memo_sign_count = sum(1 for s in MEMO_SIGNS if s in q[:1000])
    is_submitted = (len(q) > 500 and memo_sign_count >= 2) or (len(q) > 1500 and memo_sign_count >= 1)
    prev_was_wait = any("أراجعها" in str(h.get("content","")) for h in history[-3:] if h.get("role") == "assistant")
    is_review = is_submitted or (has_review_kw and len(q) > 500) or (prev_was_wait and len(q) > 300)
    return is_review, has_review_kw, is_submitted


def is_salary_query(q: str) -> bool:
    """Check if query is about salary/grades."""
    qs = q.strip()
    if any(t in qs for t in TABLE_TRIGGERS):
        return True
    return bool(re.search(r'(كم|راتب|رواتب|سلم).{0,15}(درجة|موظف|سلم|رواتب|راتب)', qs))


async def fetch_article(q: str, pool) -> dict | None:
    """
    Attempt direct article fetch from DB.
    Returns {"text": str} if found, None if not.
    """
    match = ART_REQUEST_RE.search(q)
    if not match or not pool:
        return None
    if any(w in q for w in ["مذكرة","لائحة","صيغ"]):
        return None

    req_num = match.group(1)
    law_kw = None
    for lk, words in LAW_KW_MAP.items():
        if any(w in q for w in words):
            law_kw = lk
            break

    try:
        async with pool.acquire() as conn:
            if law_kw:
                row = await conn.fetchrow(
                    "SELECT content, law_name FROM chunks "
                    "WHERE is_active=true AND article_number = $1 AND law_name ILIKE $2 "
                    "AND law_name NOT ILIKE '%أحكام محكمة التمييز%' "
                    "AND length(content) > 50 ORDER BY length(content) DESC LIMIT 1",
                    req_num, law_kw
                )
            else:
                row = await conn.fetchrow(
                    "SELECT content, law_name FROM chunks "
                    "WHERE is_active=true AND article_number = $1 "
                    "AND law_name NOT ILIKE '%أحكام محكمة التمييز%' "
                    "AND law_name NOT ILIKE '%قرار%' "
                    "AND law_name NOT ILIKE '%أمر أميري%' "
                    "AND length(content) > 50 ORDER BY length(content) DESC LIMIT 1",
                    req_num
                )
        if row:
            return {"text": f"📜 المادة {req_num} من {row['law_name']}:\n\n{row['content'][:1500]}", "found": True}
        else:
            not_found = f"⚠️ لم أجد المادة {req_num}" + (f" في {law_kw.replace('%','').strip()}" if law_kw else "") + " في قاعدة البيانات."
            return {"text": not_found, "found": False}
    except Exception as e:
        log.warning("article request failed: %s", e)
        return None


async def fetch_table(q: str, pool) -> dict | None:
    """
    Attempt direct table fetch (salary, drugs, chemicals).
    Returns {"text": str, "table_type": str} or None.
    """
    if not pool:
        return None

    source = find_answer_source(q)
    if source["type"] != "table":
        return None

    try:
        result = await km_smart_fetch(pool, source)
        if result and "لم أجد" not in result:
            return {"text": result, "table_type": source.get("table_type", "عام")}
    except Exception as e:
        log.warning("table fetch failed: %s", e)
    return None


async def get_system_stats(pool) -> str:
    """Get system statistics text."""
    try:
        tc = await pool.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true") if pool else 48895
        tr = await pool.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true AND law_name ILIKE '%أحكام محكمة التمييز%'") if pool else 11452
        tl = await pool.fetchval("SELECT COUNT(DISTINCT law_name) FROM chunks WHERE is_active=true AND law_name NOT ILIKE '%أحكام محكمة التمييز%'") if pool else 150
    except Exception:
        tc, tr, tl = 48895, 11452, 150

    return f"""أنا ميزان — مستشارك القانوني. عندي في ذاكرتي:

📚 القوانين والتشريعات:
• {tl}+ قانون وتشريع قطري
• {tc:,} وحدة معرفية إجمالية

⚖️ أحكام محكمة التمييز:
• {tr:,}+ حكم من محكمة التمييز القطرية
• 663 مبدأ قضائي مستخلص ومصنّف
• 342 سابقة قضائية مربوطة بالمواضيع

🧠 القدرات:
• صياغة مذكرات دفاع ولوائح دعاوى بمواد صحيحة من قاعدة البيانات
• تحليل المواقف القانونية بنسب نجاح حقيقية من أحكام التمييز
• 12 موضوع قانوني بخرائط مواد متحقق منها
• فهم اللهجة القطرية والخليجية

اسألني أي سؤال قانوني وأنا جاهز ⚖️"""
