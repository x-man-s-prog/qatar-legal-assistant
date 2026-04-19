# -*- coding: utf-8 -*-
"""
Post-Processing Pipeline
المستوى 1: فلترة فورية (أثناء streaming)
المستوى 2: تقييم بعد الاكتمال (للتسجيل)
"""
import re, logging
log = logging.getLogger(__name__)


class StreamFilter:
    """فلتر فوري — يعمل على كل chunk أثناء streaming"""

    BANNED_WORDS_NON_ENV = ["ديزل"]

    HEIKAL_ICONS = re.compile(
        r"(📋\s*(?:التكييف|التكييف القانوني)\s*:?\s*\n?"
        r"|⚖️\s*(?:السند|السند القانوني|السند النظامي)\s*:?\s*\n?"
        r"|🔍\s*(?:التحليل|التحليل القانوني)\s*:?\s*\n?"
        r"|⚠️\s*(?:الاستثناءات|التنبيهات|ملاحظات)\s*:?\s*\n?"
        r"|✅\s*(?:التوصية|التوصيات)\s*:?\s*\n?"
        r"|📊\s*(?:الثقة|مستوى الثقة|درجة الثقة)\s*:?\s*\n?)"
    )

    SIMPLE_ROUTES = frozenset([
        "knowledge", "greeting", "self_info", "article_text",
        "table", "filler", "thanks",
    ])

    def __init__(self, route: str = "", topic: str = "", answer_mode: str = ""):
        self.route = route
        self.topic = topic or ""
        self.answer_mode = answer_mode  # from core.answer_mode
        self.total_text = ""
        # Should strip memo structure?
        self._strip_memo = (
            route in self.SIMPLE_ROUTES
            or answer_mode in ("direct_short", "table_row", "structured_list", "followup_short")
        )

    def filter_chunk(self, text: str):
        if not text:
            return None

        # حذف كلمات ملوّثة (ديزل) خارج سياق البيئة/النقل
        if self.topic not in ("بيئة", "نقل"):
            for w in self.BANNED_WORDS_NON_ENV:
                if w in text:
                    text = text.replace(w, "")
                    log.info("[PostProc] removed %s", w)

        # حذف هيكل في أسئلة بسيطة أو أوضاع غير تحليلية
        if self._strip_memo:
            text = self.HEIKAL_ICONS.sub("", text)

        self.total_text += text
        return text if text.strip() else None


class PostEvaluator:
    """تقييم بعد اكتمال الرد"""

    def evaluate(self, full_text, query="", route="", topic="", user_facts=None):
        issues = []
        score = 100
        words = len(full_text.split())

        if route == "greeting" and words > 50:
            issues.append("تحية طويلة (%d كلمة)" % words); score -= 10
        if route == "knowledge" and words > 250:
            issues.append("سؤال معرفي طويل (%d كلمة)" % words); score -= 10
        if route == "drafting" and words < 200:
            issues.append("مذكرة قصيرة (%d كلمة)" % words); score -= 20

        if route in ("knowledge", "greeting", "self_info"):
            if "📋 التكييف" in full_text or "📋التكييف" in full_text:
                issues.append("هيكل في سؤال بسيط"); score -= 15

        if "ديزل" in full_text.lower() and topic not in ("بيئة", "نقل"):
            issues.append("ديزل في غير سياقه"); score -= 25

        if user_facts:
            confirmed = str(user_facts.get("confirmed", []))
            if "يعترف بالحيازة" in confirmed and "لم يكن يعلم" in full_text:
                issues.append("تناقض مع اعتراف الموكّل"); score -= 30

        return {"score": max(0, score), "issues": issues,
                "words": words, "route": route, "passed": score >= 60}
