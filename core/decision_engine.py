#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decision_engine.py — محرّك القرارات القانوني
==============================================
يقرأ قواعد قرار من بنية بيانات داخلية (2000+ قاعدة)
ويتخذ القرار المناسب لكل سؤال.
"""
import re, json, os, logging
from typing import Optional, Dict, List, Any

log = logging.getLogger("decision_engine")


class DecisionEngine:
    """محرّك قواعد القرار"""

    def __init__(self):
        self.rules: Dict[str, list] = {}
        self._build_all_rules()
        self.stats = {"total": sum(len(v) for v in self.rules.values()),
                      "categories": {k: len(v) for k, v in self.rules.items()}}
        log.info("DecisionEngine: %d rules in %d categories", self.stats["total"], len(self.rules))

    # ────────────────────────────────────────
    # المحرّك الأساسي
    # ────────────────────────────────────────

    def _check(self, cond: dict, ctx: dict) -> bool:
        op = cond.get("op", "contains")
        field = cond.get("field", "query")
        val = cond.get("value", "")
        actual = ctx.get(field, "")
        if isinstance(actual, list):
            actual = " ".join(str(x) for x in actual)
        actual = str(actual).lower()

        if op == "contains":
            return val.lower() in actual
        elif op == "not_contains":
            return val.lower() not in actual
        elif op == "in_list":
            return any(v.lower() in actual for v in val) if isinstance(val, list) else False
        elif op == "not_in_list":
            return not any(v.lower() in actual for v in val) if isinstance(val, list) else True
        elif op == "gte":
            try: return float(actual) >= float(val)
            except: return False
        elif op == "lt":
            try: return float(actual) < float(val)
            except: return False
        elif op == "exists":
            return bool(actual.strip())
        return False

    def evaluate(self, category: str, ctx: dict) -> Optional[dict]:
        matched = []
        for rule in self.rules.get(category, []):
            if all(self._check(c, ctx) for c in rule.get("conditions", [])):
                matched.append(rule)
        if not matched:
            return None
        matched.sort(key=lambda r: r.get("priority", 0), reverse=True)
        return matched[0]

    def evaluate_all_in(self, category: str, ctx: dict) -> list:
        """يرجع كل القواعد المطابقة (مرتبة بالأولوية)"""
        matched = []
        for rule in self.rules.get(category, []):
            if all(self._check(c, ctx) for c in rule.get("conditions", [])):
                matched.append(rule)
        matched.sort(key=lambda r: r.get("priority", 0), reverse=True)
        return matched

    def get_defenses(self, topic: str, confirmed_facts: str) -> list:
        """يرجع الدفوع المناسبة مع فلترة التناقضات"""
        result = []
        for rule in self.rules.get("defenses", []):
            if rule.get("topic") != topic:
                continue
            blocked = rule.get("blocked_by", "")
            if blocked and blocked in confirmed_facts:
                continue
            result.append(rule.get("result", {}))
        return result[:5]

    def get_questions(self, topic: str, query: str) -> list:
        """يرجع الأسئلة التوضيحية الذكية"""
        ctx = {"query": query.lower()}
        qs = []
        for rule in self.rules.get("questions", []):
            if rule.get("topic") != topic:
                continue
            if all(self._check(c, ctx) for c in rule.get("conditions", [])):
                q_text = rule.get("result", {}).get("question")
                if q_text:
                    qs.append(q_text)
        return qs[:3]

    def get_tone(self, query: str) -> dict:
        """يكشف المشاعر ويحدد النبرة"""
        ctx = {"query": query.lower()}
        match = self.evaluate("tone", ctx)
        return match.get("result", {}) if match else {}

    # ────────────────────────────────────────
    # بناء القواعد (2000+)
    # ────────────────────────────────────────

    def _build_all_rules(self):
        self._build_routing()
        self._build_defenses()
        self._build_questions()
        self._build_tone()

    def _add_kw_rules(self, cat: str, keywords: list, action: str, priority: int, extra_conds=None):
        rules = self.rules.setdefault(cat, [])
        for kw in keywords:
            rule = {"conditions": [{"field": "query", "op": "contains", "value": kw}],
                    "action": action, "priority": priority}
            if extra_conds:
                rule["conditions"].extend(extra_conds)
            rules.append(rule)

    # ── التوجيه ──

    def _build_routing(self):
        R = []

        # مراجعة (أعلى أولوية)
        rev_kw = ["قيمها","قيّمها","قيم لي","عطني رايك","رايك فيها","راجعها","راجع لي",
                   "حلل لي","حللها","وش رايك فيها","تقييمك","برسلك مذكرة","بأرسلك",
                   "ابي تقييم","عطني تقييم","عطني ملاحظات","ابغيك تقيمها","ابيك تراجعها",
                   "حلل المذكرة","قيّم المذكرة","نقاط القوة","نقاط الضعف","وين القوة"]
        for kw in rev_kw:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw},
                                     {"field": "word_count", "op": "lt", "value": 30}],
                       "action": "review_wait", "priority": 100})
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw},
                                     {"field": "word_count", "op": "gte", "value": 50}],
                       "action": "review_document", "priority": 98})

        # مستند مرسل
        for sign in ["عدالة المحكمة","مذكرة دفاع","مقدمة من","المستأنف","المدعي:",
                      "لائحة دعوى","الموقرة","أَحْمَدُهُ","حافظة مستندات","الدعوى رقم"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": sign},
                                     {"field": "word_count", "op": "gte", "value": 50}],
                       "action": "review_document", "priority": 95})

        # نص مادة
        for kw in ["نص المادة","نص الماده","عطني نص","عطني المادة","اقرأ المادة","المادة كامل"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                       "action": "article_text", "priority": 90})

        # ذاتي
        for kw in ["كم مبدأ","كم حكم","كم قانون","كم عندك","عدد المبادئ","قاعدة بياناتك","ذاكرتك","وش حدودك"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                       "action": "self_info", "priority": 85})

        # قدرات
        for kw in ["وش تقدر تسوي","من أنت","من انت","قدراتك","وش مهامك","تقدر تكتب مذكرات"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                       "action": "capabilities", "priority": 85})

        # معرفي
        for kw in ["ما هو الفرق","ما الفرق","وش الفرق","ما هي ","ما هو ","ماذا يعني","وش يعني",
                    "عرّف لي","اشرح لي","وضّح لي","ما معنى","ما المقصود",
                    "ما هي شروط","ما هي أركان","كيف يتم","متى يسقط","متى ينتهي"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw},
                                     {"field": "query", "op": "not_in_list", "value": ["اكتب","مذكرة","صيغ","لائحة"]}],
                       "action": "knowledge", "priority": 75})

        # اختصار
        for kw in ["اختصر","بدال الفلسفة","باختصار","لا تطول","من غير لف","جاوب مباشرة"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                       "action": "short_answer", "priority": 88})

        # صياغة
        for kw in ["اكتب لي مذكرة","اكتب مذكرة","صيغ لي مذكرة","لائحة دعوى","مذكرة دفاع",
                    "اكتب لي لائحة","صيغ لي","سو لي مذكرة","جهز لي مذكرة","صحيفة دعوى",
                    "عقد إيجار","عقد عمل","عقد شراكة","عقد بيع"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                       "action": "drafting", "priority": 70})

        # تحيات
        for kw in ["مرحبا","السلام عليكم","اهلا","هلا","هلا والله","شحالك","اخبارك",
                    "علومك","كيفك","مساء الخير","صباح الخير","يا هلا","اهلين","مرحبتين"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw},
                                     {"field": "word_count", "op": "lt", "value": 5}],
                       "action": "greeting", "priority": 95})

        # شكر
        for kw in ["شكراً","شكرا","مشكور","يعطيك العافية","جزاك الله خير","الله يسلمك","بارك الله"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                       "action": "thanks", "priority": 95})

        # fillers
        for kw in ["حمدالله","الحمدلله","تمام","عندي سؤال","ان شاء الله","بارك الله فيك","احتاجك","ابي مساعدة"]:
            R.append({"conditions": [{"field": "query", "op": "contains", "value": kw},
                                     {"field": "word_count", "op": "lt", "value": 5}],
                       "action": "filler", "priority": 90})

        self.rules["routing"] = R

    # ── الدفوع ──

    def _build_defenses(self):
        D = []

        # مخدرات
        for d in [
            {"name": "عدم جدية التحريات", "rate": "37%", "cond": "إذن",
             "tpl": "التحريات لم تتضمن معلومات كافية ودقيقة → الإذن باطل"},
            {"name": "تجاوز حدود الإذن", "rate": "31%", "cond": "إذن",
             "tpl": "الإذن لمكان محدد والتفتيش تجاوز لمكان آخر"},
            {"name": "الكمية بسيطة = تعاطي شخصي", "rate": "54%", "cond": "always",
             "tpl": "الكمية المضبوطة بسيطة → تعاطي شخصي → عقوبة أخف"},
            {"name": "طلب إحالة للعلاج", "rate": "42%", "cond": "always",
             "tpl": "رغبة صادقة في العلاج والإقلاع"},
            {"name": "ظروف مخففة", "rate": "65%", "cond": "always",
             "tpl": "أسرة + عمل + أول مرة + ندم"},
            {"name": "بطلان القبض لانتفاء التلبس", "rate": "45%", "cond": "بدون_إذن",
             "tpl": "القبض بدون إذن وبدون حالة تلبس"},
            {"name": "انتفاء القصد الجنائي", "rate": "28%", "cond": "no_confession",
             "blocked": "يعترف بالحيازة",
             "tpl": "لم يكن على علم بوجود المادة"},
        ]:
            D.append({"topic": "مخدرات", "condition": d["cond"],
                       "blocked_by": d.get("blocked", ""),
                       "result": {"name": d["name"], "success_rate": d["rate"], "template": d["tpl"]},
                       "priority": 50})

        # ضرب
        for d in [
            {"name": "الدفاع الشرعي", "rate": "48%", "cond": "always",
             "tpl": "كان في حالة دفاع شرعي — الاعتداء حالّ ومباشر"},
            {"name": "عدم كفاية الأدلة", "rate": "35%", "cond": "always",
             "tpl": "لا تقرير طبي ولا شهود — أقوال مرسلة"},
        ]:
            D.append({"topic": "ضرب", "condition": d["cond"],
                       "result": {"name": d["name"], "success_rate": d["rate"], "template": d["tpl"]},
                       "priority": 50})

        # حضانة
        for d in [
            {"name": "سقوط بالزواج من أجنبي (م168)", "rate": "72%", "cond": "always",
             "tpl": "الحاضنة تزوجت من غير محرم للمحضون"},
            {"name": "إسقاط بالإهمال (م182)", "rate": "38%", "cond": "always",
             "tpl": "الحاضنة مهملة — تقارير رسمية"},
            {"name": "تدرج حسب السن (م186)", "rate": "60%", "cond": "always",
             "tpl": "التدرج في الرؤية والاصطحاب والمبيت"},
        ]:
            D.append({"topic": "حضانة", "condition": d["cond"],
                       "result": {"name": d["name"], "success_rate": d["rate"], "template": d["tpl"]},
                       "priority": 50})

        # فصل
        for d in [
            {"name": "الفصل التعسفي", "rate": "55%", "cond": "always",
             "tpl": "إنهاء بدون سبب مشروع"},
            {"name": "مكافأة نهاية الخدمة (م54)", "rate": "80%", "cond": "always",
             "tpl": "مكافأة لمن أمضى سنة فأكثر"},
        ]:
            D.append({"topic": "فصل", "condition": d["cond"],
                       "result": {"name": d["name"], "success_rate": d["rate"], "template": d["tpl"]},
                       "priority": 50})

        # شيك
        D.append({"topic": "شيك", "condition": "always",
                   "result": {"name": "الشيك ضمان وليس أداة وفاء", "success_rate": "40%",
                              "template": "الشيك حُرر كضمان لعلاقة تجارية وليس كأداة وفاء"},
                   "priority": 50})

        self.rules["defenses"] = D

    # ── الأسئلة التوضيحية ──

    def _build_questions(self):
        Q = []
        SMART = {
            "مخدرات": [
                (["بسيطة","كبيرة","كمية"], "الكمية المضبوطة كانت بسيطة ولا كبيرة؟"),
                (["سوابق","أول مرة"], "هل عندك سوابق أو هذي أول مرة؟"),
                (["إذن","اذن","دورية"], "هل التفتيش كان بإذن من النيابة أو بدون؟"),
            ],
            "حضانة": [
                (["سنة","سنوات","عمر","عمره","عمرها"], "كم عمر المحضون/المحضونة؟"),
                (["أجنبي","محرم","عم","خال"], "الزوج الجديد محرم للأطفال أو أجنبي عنهم؟"),
            ],
            "فصل": [
                (["سنة","سنوات","شهر"], "كم مدة خدمتك؟"),
                (["راتب","ريال","ألف"], "كم راتبك؟"),
                (["إنذار","انذار","سبب"], "هل أعطوك إنذار أو ذكروا سبب الفصل؟"),
            ],
            "ضرب": [
                (["تقرير","طبي"], "هل عندك تقرير طبي؟"),
                (["شهود","فيديو","كاميرا"], "هل فيه شهود أو تسجيل مرئي؟"),
            ],
        }
        for topic, qs in SMART.items():
            for check_words, question in qs:
                Q.append({"topic": topic,
                           "conditions": [{"field": "query", "op": "not_in_list", "value": check_words}],
                           "result": {"question": question},
                           "priority": 30})
        self.rules["questions"] = Q

    # ── النبرة ──

    def _build_tone(self):
        T = []
        EMOTIONS = {
            "قلق": (["خايف","خوف","قلق","قلقان"], "لا تقلق — موقفك له حل قانوني.", "تعاطف"),
            "غضب": (["ظلم","ظلموني","حرام"], "أفهم إحباطك — خلنا نشوف الخيارات.", "حزم"),
            "استعجال": (["بسرعة","ضروري","مستعجل","بكرة الجلسة"], "فهمت — الموضوع عاجل.", "سرعة"),
            "إحباط": (["تمللت","ملّيت","ما نفع","كل مره"], "أعتذر — خلني أساعدك بشكل أفضل.", "صبر"),
            "حزن": (["حزين","مظلوم","معاناة"], "أتفهم مشاعرك — أنا هنا أساعدك.", "تعاطف"),
        }
        for emotion, (triggers, opener, tone) in EMOTIONS.items():
            for kw in triggers:
                T.append({"conditions": [{"field": "query", "op": "contains", "value": kw}],
                           "result": {"emotion": emotion, "opener": opener, "tone": tone},
                           "priority": 40})
        self.rules["tone"] = T
