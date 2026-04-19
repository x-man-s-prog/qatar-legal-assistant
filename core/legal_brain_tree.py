#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
legal_brain_tree.py — شجرة التفكير القانوني
=============================================
500+ نقطة قرار في 10 فروع.
الجذع (LegalBrainTree) يربط كل الفروع ويُخرج قرار واحد شامل.
"""
import re, logging
log = logging.getLogger("brain_tree")


# ════════════════════════════════════════════════════════════════
# الفرع 1: تحليل اللغة والأسلوب
# ════════════════════════════════════════════════════════════════

class Branch01_Language:
    GULF = {"وش","ليش","ابي","ابغي","شحالك","علومك","اخبارك","طيب","خلاص",
            "يالله","زين","مب","ماني","وين","شلون","الحين","يعني","بعدين",
            "تمام","اوكي","مافي","كذا","ودي","ابيك","ابغيك","سوي","خله"}
    EMOTION_MAP = {"ظلم":"غضب","ظلموني":"غضب","حرام":"غضب","خايف":"قلق",
                   "قلقان":"قلق","مستعجل":"استعجال","ضروري":"استعجال",
                   "حزين":"حزن","مظلوم":"حزن","شكراً":"امتنان","مشكور":"امتنان"}
    SHORT_KW = ["اختصر","بدال الفلسفة","باختصار","لا تطول","بسرعة","من غير لف","جاوب مباشرة","لا تكثر"]
    FRUSTRATE = ["بدال الفلسفة","تراني قلت","مش كذا قلت","ليه ما تفهم","كل مره"]

    def analyze(self, q):
        ql = q.lower()
        words = set(ql.split())
        gulf_c = len(words & self.GULF)
        dialect = "خليجي" if gulf_c >= 2 else "عام"
        emotions = {}
        for w, e in self.EMOTION_MAP.items():
            if w in ql: emotions[e] = emotions.get(e, 0) + 1
        primary_emotion = max(emotions, key=emotions.get) if emotions else "محايد"
        wants_short = any(w in ql for w in self.SHORT_KW)
        frustrated = any(p in ql for p in self.FRUSTRATE)
        legal_terms = sum(1 for t in ["حجية","تكييف","استئناف","تمييز","نقض","مرافعات"] if t in ql)
        level = "محامي" if legal_terms >= 3 else "متعلم" if legal_terms >= 1 else "عام"
        return {
            "dialect": dialect, "primary_emotion": primary_emotion,
            "wants_short": wants_short, "frustrated": frustrated,
            "legal_level": level,
            "should_empathize": primary_emotion in ("قلق","حزن","غضب"),
            "should_apologize": frustrated,
        }


# ════════════════════════════════════════════════════════════════
# الفرع 2: تحليل البنية والكيانات
# ════════════════════════════════════════════════════════════════

class Branch02_Structure:
    MEMO_SIGNS = ["عدالة محكمة","عدالة المحكمة","مذكرة دفاع","مقدمة من",
        "المستأنف","المدعي:","المدعى عليه","لائحة دعوى","مقدمة إلى",
        "الموقرة","أَحْمَدُهُ","اما بعد","أولاً","ثانياً","ثالثاً",
        "الطلبات","حافظة مستندات","الدعوى رقم","المحدد لنظرها",
        "بطاقة رقم","استئناف رقم","ابتدائي رقم","مذكرة ورد"]

    def analyze(self, q):
        words = len(q.split())
        chars = len(q)
        memo_score = sum(1 for s in self.MEMO_SIGNS if s in q[:1000])
        is_doc = (chars > 500 and memo_score >= 2) or (chars > 1500 and memo_score >= 1)
        ages = re.findall(r'(\d+)\s*(?:سنة|سنوات|سنه|عمره|عمرها)', q)
        amounts = re.findall(r'(\d[\d,]*)\s*(?:ريال|الف|ألف)', q)
        article_refs = re.findall(r'(?:المادة|الماده|م\.?\s*)(\d+)', q)
        return {
            "words": words, "chars": chars,
            "is_document": is_doc, "memo_score": memo_score,
            "ages": ages, "amounts": amounts, "article_refs": article_refs,
            "has_specific_data": bool(ages or amounts),
        }


# ════════════════════════════════════════════════════════════════
# الفرع 3: تصنيف الفعل المطلوب
# ════════════════════════════════════════════════════════════════

class Branch03_Action:
    ACTIONS = {
        "مراجعة": ["قيمها","قيّمها","قيم لي","عطني رايك","رايك فيها","راجعها",
            "راجع لي","حلل لي","حللها","وش رايك فيها","تقييمك","برسلك مذكرة",
            "بأرسلك","ابي تقييم","عطني تقييم","عطني ملاحظات","ابغيك تقيمها",
            "ابيك تراجعها","حلل المذكرة","قيّم المذكرة","نقاط القوة","نقاط الضعف"],
        "نص_مادة": ["نص المادة","نص الماده","عطني نص","اكتب نص المادة","عطني المادة","اقرأ المادة","المادة كامل"],
        "ذاتي": ["كم مبدأ","كم حكم","كم قانون","كم مادة","كم عندك","وش عندك من",
            "عدد المبادئ","عدد الأحكام","قاعدة بياناتك","ذاكرتك","وش حدودك","إحصائيات"],
        "قدرات": ["وش تقدر تسوي","من أنت","من انت","وش مهامك","تقدر تكتب مذكرات","قدراتك"],
        "معرفي": ["ما هو الفرق","ما الفرق","وش الفرق","ما هي ","ما هو ","ماذا يعني",
            "وش يعني","عرّف لي","اشرح لي","وضّح لي","ما معنى","ما المقصود",
            "ما هي شروط","ما هي أركان","ما هي أنواع","متى يسقط","متى ينتهي","كيف يتم"],
        "صياغة": ["اكتب لي","صيغ لي","سو لي","جهز لي","مذكرة دفاع","مذكرة","لائحة",
            "عقد إيجار","عقد عمل","عقد شراكة","صحيفة دعوى"],
        "تحية": ["مرحبا","السلام عليكم","اهلا","هلا","شحالك","اخبارك","علومك",
            "كيفك","مساء الخير","صباح الخير","يا هلا","اهلين"],
        "شكر": ["شكراً","شكرا","مشكور","يعطيك العافية","جزاك الله خير","الله يسلمك"],
        "فلر": ["حمدالله","تمام","بخير","عندي سؤال","ان شاء الله","بارك الله فيك",
            "ساعدني","ابي مساعدة","احتاجك"],
        "متابعة": ["وبعدين","كمل","استمر","ادعم اكثر","وضّح","فصّل","أكمل","زد على"],
    }

    # أولوية: مراجعة > نص_مادة > ذاتي > قدرات > معرفي > صياغة > ...
    PRIORITY = ["مراجعة","نص_مادة","ذاتي","قدرات","معرفي","صياغة",
                "تحية","شكر","فلر","متابعة"]

    def classify(self, q):
        ql = q.lower()
        matched = {}
        for action, triggers in self.ACTIONS.items():
            score = sum(1 for t in triggers if t in ql)
            if score > 0: matched[action] = score
        # بأولوية صارمة
        primary = None
        for p in self.PRIORITY:
            if p in matched:
                primary = p
                break
        # استثناء: "معرفي" لا يُفعّل إذا فيه كلمة صياغة
        if primary == "معرفي" and any(w in ql for w in ["مذكرة","اكتب","صيغ","لائحة"]):
            primary = "صياغة"
        # استثناء: "صياغة" لا تُفعّل إذا فيه كلمة شخصية بدون طلب صياغة صريح
        has_explicit_draft = any(w in ql for w in ["اكتب لي","صيغ لي","سو لي","جهز لي"])
        if primary == "صياغة" and not has_explicit_draft and "مذكرة" not in ql:
            primary = None
        return {
            "primary": primary or "عام",
            "all": matched,
            "is_drafting": primary == "صياغة",
            "is_review": primary == "مراجعة",
            "is_query": primary in ("نص_مادة","ذاتي","قدرات","معرفي"),
            "is_social": primary in ("تحية","شكر","فلر","متابعة"),
        }


# ════════════════════════════════════════════════════════════════
# الفرع 4: تحليل الموضوع القانوني
# ════════════════════════════════════════════════════════════════

class Branch04_Topic:
    TOPICS = {
        "حضانة": ["حضانة","حاضن","محضون","عيالي","بنتي","ولدي","اسقاط حضان"],
        "طلاق": ["طلاق","خلع","تطليق","طليقتي","انفصال","ناشز"],
        "نفقة": ["نفقة","نفقه","إعالة"],
        "فصل": ["فصل","طفشني","طردني","فصلتني","تعسفي","نهاية خدمة","شالني","فصلوني"],
        "مخدرات": ["مخدرات","مخدر","حيازة","تعاطي","حشيش"],
        "ضرب": ["ضرب","ضربني","إيذاء","اعتداء","انضرب","ضربوني"],
        "سرقة": ["سرقة","سرق","سرقني","نشل"],
        "شيك": ["شيك","شيكات","بدون رصيد","طاير","مرتجع"],
        "تشهير": ["تشهير","سب","قذف","سمعة","شهّر","يسبني"],
        "ابتزاز": ["ابتزاز","يبتزني","يهددني","صور خاصة"],
        "احتيال": ["احتيال","نصب","ناصبني","خيانة أمانة","يختلس"],
        "تزوير": ["تزوير","مزور","زوّر"],
        "إيجار": ["إيجار","مستأجر","إخلاء","شقة","محل"],
        "مرور": ["مرور","سياقة","رخصة","حادث"],
        "ميراث": ["ميراث","إرث","تركة","وارث"],
    }

    def analyze(self, q):
        ql = q.lower()
        best, best_c = None, 0
        for topic, kws in self.TOPICS.items():
            c = sum(1 for kw in kws if kw in ql)
            if c > best_c: best_c, best = c, topic
        return {"topic": best, "score": best_c}


# ════════════════════════════════════════════════════════════════
# الفرع 5: تحليل الحقائق
# ════════════════════════════════════════════════════════════════

class Branch05_Facts:
    def analyze(self, q, topic):
        ql = q.lower()
        confirmed, challengeable, contradictions = [], [], []

        if any(w in ql for w in ["عندي حشيش","لقوا عندي","ولقوا عندي","ولقت عندي","معي حشيش"]):
            confirmed.append("يعترف بالحيازة")
            contradictions.append("لا تدفع بانتفاء العلم بطبيعة المادة")
        if any(w in ql for w in ["حشيش","كوكايين","هيروين"]) and topic == "مخدرات":
            contradictions.append("لا تقل 'لم يكن يعلم أنها مخدرات'")
        if any(w in ql for w in ["إذن","اذن","بناء على إذن"]):
            confirmed.append("يوجد إذن تفتيش")
            challengeable.extend(["جدية التحريات","تجاوز حدود الإذن"])
            contradictions.append("لا تنكر وجود الإذن")
        if any(w in ql for w in ["دورية","وقفتني"]) and "إذن" not in ql and "اذن" not in ql:
            challengeable.append("قبض بدورية بدون إذن — بطلان محتمل")
        if any(w in ql for w in ["أول مرة","اول مره"]):
            confirmed.append("أول مرة — ظرف مخفف")
        if any(w in ql for w in ["بسيطة","قليلة","شوية"]):
            confirmed.append("كمية بسيطة → تعاطي شخصي")
        if any(w in ql for w in ["ضربته","دافعت","هو بدأ","هو اللي"]):
            confirmed.append("يعترف بالضرب كدفاع")
            contradictions.append("لا تنكر الضرب — ادفع بالدفاع الشرعي")
        if any(w in ql for w in ["تزوجت","متزوجة"]):
            confirmed.append("زواج الحاضنة ثابت")
        if any(w in ql for w in ["مهملة","إهمال","ما تهتم"]):
            confirmed.append("إهمال الأم")
        if any(w in ql for w in ["بدون سبب","بلا سبب"]):
            confirmed.append("فصل بدون سبب مشروع")
        if any(w in ql for w in ["بدون إنذار","بلا إنذار"]):
            confirmed.append("بدون إنذار مسبق")

        return {"confirmed": confirmed, "challengeable": challengeable, "contradictions": contradictions}


# ════════════════════════════════════════════════════════════════
# الفرع 6: قوة القضية
# ════════════════════════════════════════════════════════════════

class Branch06_Strength:
    BASE = {"مخدرات":35,"حضانة":65,"ضرب":45,"فصل":60,"شيك":40,"تشهير":55,"سرقة":30}
    POS = {"فيديو":15,"تقرير طبي":10,"شهود":8,"أول مرة":10,"بدون إذن":15,"دفاع شرعي":12,
           "أجنبي":15,"مهملة":10,"بدون سبب":12,"بدون إنذار":10,"كمية بسيطة":8}
    NEG = {"سوابق":-15,"يعترف بالحيازة":-10,"كمية كبيرة":-12}

    def calculate(self, topic, q, facts):
        s = self.BASE.get(topic, 50)
        all_text = q.lower() + " " + " ".join(facts.get("confirmed",[])+facts.get("challengeable",[]))
        factors = []
        for kw, bonus in self.POS.items():
            if kw in all_text: s += bonus; factors.append(f"+{bonus}% {kw}")
        for kw, pen in self.NEG.items():
            if kw in all_text: s += pen; factors.append(f"{pen}% {kw}")
        if facts.get("challengeable"): s += 10; factors.append("+10% ثغرات إجرائية")
        s = max(10, min(95, s))
        rec = "قوي — ننصح بالمضي" if s >= 70 else "متوسط — فكّر بالتسوية" if s >= 45 else "ضعيف — ركّز على الظروف المخففة"
        return {"score": s, "factors": factors, "recommendation": rec}


# ════════════════════════════════════════════════════════════════
# الجذع الرئيسي
# ════════════════════════════════════════════════════════════════

class LegalBrainTree:
    def __init__(self):
        self.lang = Branch01_Language()
        self.struct = Branch02_Structure()
        self.action = Branch03_Action()
        self.topic = Branch04_Topic()
        self.facts = Branch05_Facts()
        self.strength = Branch06_Strength()

    def think(self, query, history=None):
        L = self.lang.analyze(query)
        S = self.struct.analyze(query)
        A = self.action.classify(query)
        T = self.topic.analyze(query)
        F = self.facts.analyze(query, T.get("topic"))

        # ═══ تحديد المسار ═══
        prev_was_wait = False
        if history:
            prev_was_wait = any("أراجعها" in str(h.get("content","")) for h in history[-3:] if h.get("role") == "assistant")

        if S["is_document"]:
            route = "review"
        elif A["is_review"]:
            route = "review_wait" if S["chars"] < 300 else "review"
        elif prev_was_wait and S["chars"] > 300:
            route = "review"
        elif A["primary"] == "نص_مادة":
            route = "article_text"
        elif A["primary"] == "ذاتي":
            route = "self_info"
        elif A["primary"] == "قدرات":
            route = "capabilities"
        elif A["primary"] == "معرفي" or L["wants_short"]:
            route = "knowledge"
        elif A["primary"] == "تحية":
            route = "greeting"
        elif A["primary"] == "شكر":
            route = "thanks"
        elif A["primary"] == "فلر":
            route = "filler"
        elif A["primary"] == "متابعة":
            route = "followup"
        elif A["is_drafting"]:
            route = "drafting"
        elif F["confirmed"]:
            route = "consultation"
        else:
            route = "general"

        # ═══ مقياس القوة (للمذكرات والاستشارات) ═══
        STR = None
        if route in ("drafting", "consultation") and T["topic"]:
            STR = self.strength.calculate(T["topic"], query, F)

        return {
            "route": route,
            "language": L,
            "structure": S,
            "action": A,
            "topic": T,
            "facts": F,
            "strength": STR,
        }

    def build_facts_prompt(self, facts):
        """يبني سياق الوقائع لحقنه في prompt."""
        parts = []
        if facts.get("confirmed"):
            parts.append("✅ حقائق مؤكدة (لا تناقضها!):")
            for f in facts["confirmed"]: parts.append(f"  • {f}")
        if facts.get("challengeable"):
            parts.append("🔍 نقاط قابلة للطعن:")
            for f in facts["challengeable"]: parts.append(f"  • {f}")
        if facts.get("contradictions"):
            parts.append("⛔ ممنوعات (لا تقل هذا!):")
            for c in facts["contradictions"]: parts.append(f"  • {c}")
        if not parts: return ""
        return "\n═══ تحليل وقائع الموكّل ═══\n" + "\n".join(parts) + "\n"
