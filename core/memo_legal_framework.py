#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memo_legal_framework.py — فصل القانون عن السرد
=================================================
النظام (Python/DB) يبني الهيكل القانوني بمواد صحيحة 100%.
النموذج (LLM) يكتب فقط الوقائع والتحليل والإقناع.
"""
import re, logging
from typing import Optional

log = logging.getLogger("memo_framework")

# ════════════════════════════════════════════════════════════
# 1. خريطة المواضيع → المواد الصحيحة
# ════════════════════════════════════════════════════════════

TOPIC_LEGAL_MAP = {
    "حضانة": {
        "law_name": "قانون الأسرة رقم 22 لسنة 2006",
        "law_kw": "%أسرة%",
        "court": "محكمة الأسرة",
        "articles": [
            {"num": "168", "title": "شروط الحاضنة — زواج من أجنبي", "priority": 1,
             "keywords": ["سقوط","تسقط","زواج","تزوجت","إسقاط","أجنبي","محرم"],
             "why": "ألا تكون الحاضنة متزوجة من زوج أجنبي عن المحضون دخل بها — أقوى سند لإسقاط الحضانة بسبب الزواج"},
            {"num": "183", "title": "حالات سقوط الحضانة", "priority": 2,
             "keywords": ["سقوط","تسقط","إسقاط","تخلف شرط"],
             "why": "تسقط الحضانة إذا تخلف شرط من شروط م167/168 أو سكنى مع من سقطت حضانتها"},
            {"num": "182", "title": "دعوى إسقاط الحضانة", "priority": 3,
             "keywords": ["إسقاط","دعوى","إهمال","مهملة"],
             "why": "للعصبة رفع دعوى إسقاط إذا كانت الحاضنة مهملة أو سيئة السلوك"},
            {"num": "166", "title": "الحضانة واجب الأبوين — الأم أولى", "priority": 4,
             "keywords": ["حضانة","أولى","أبوين","واجب"],
             "why": "الحضانة واجب الأبوين — الأم أولى ما لم يقدر القاضي خلاف ذلك"},
            {"num": "165", "title": "تعريف الحضانة", "priority": 5,
             "keywords": ["تعريف","حفظ","تربية"],
             "why": "الحضانة هي حفظ الولد وتربيته وتقويمه ورعايته"},
            {"num": "173", "title": "مدة الحضانة — سن الانتهاء", "priority": 6,
             "keywords": ["سن","عمر","13","15","انتهاء"],
             "why": "تنتهي حضانة النساء: الذكر 13 سنة والأنثى 15 سنة"},
            {"num": "170", "title": "معايير مصلحة المحضون", "priority": 7,
             "keywords": ["مصلحة","بيئة","تربية","تعليم"],
             "why": "يراعي القاضي الشفقة والأمانة والقدرة على التربية"},
            {"num": "169", "title": "ترتيب الحاضنين", "priority": 8,
             "keywords": ["ترتيب","أحق"],
             "why": "الأم ثم الأب ثم أمهات الأب..."},
        ],
    },
    "طلاق": {
        "law_name": "قانون الأسرة رقم 22 لسنة 2006",
        "law_kw": "%أسرة%",
        "court": "محكمة الأسرة",
        "articles": [
            {"num": "101", "title": "أنواع الفرقة", "priority": 1, "keywords": ["طلاق","فرقة"], "why": ""},
            {"num": "109", "title": "الطلاق الرجعي والبائن", "priority": 2, "keywords": ["رجعي","بائن"], "why": ""},
            {"num": "113", "title": "إجراءات الطلاق", "priority": 3, "keywords": ["إجراءات"], "why": ""},
            {"num": "120", "title": "الخلع", "priority": 4, "keywords": ["خلع"], "why": ""},
            {"num": "122", "title": "التطليق للضرر", "priority": 5, "keywords": ["ضرر","يضربني"], "why": ""},
        ],
    },
    "نفقة": {
        "law_name": "قانون الأسرة رقم 22 لسنة 2006",
        "law_kw": "%أسرة%",
        "court": "محكمة الأسرة",
        "articles": [
            {"num": "57", "title": "حقوق الزوجة — النفقة الشرعية", "priority": 1, "keywords": ["نفقة"], "why": "النفقة الشرعية حق للزوجة على زوجها"},
            {"num": "59", "title": "حصر عناصر النفقة", "priority": 2, "keywords": ["عناصر","مقدار","تقدير"], "why": "يلزم القاضي المدعي بحصر عناصر النفقة شاملة جميع طلباته"},
            {"num": "78", "title": "نفقة الأولاد", "priority": 3, "keywords": ["أولاد","عيال"], "why": ""},
        ],
    },
    "فصل_عمل": {
        "law_name": "قانون العمل رقم 14 لسنة 2004 وتعديلاته",
        "law_kw": "%عمل%",
        "court": "المحكمة العمالية",
        "articles": [
            {"num": "1", "title": "أحكام الفصل والإنهاء (قانون العمل المعدّل)", "priority": 1,
             "keywords": ["فصل","إنهاء","فصلوني","تعسفي","مكافأة","إنذار"],
             "why": "يتضمن نصوص المواد 39/43/49/115/144/145 المعدّلة لقانون العمل"},
            {"num": "2", "title": "إضافات — لجان فض المنازعات العمالية", "priority": 2,
             "keywords": ["لجنة","فض","منازعات"],
             "why": "إذا صدر قرار نهائي من لجنة فض المنازعات لصالح العامل"},
            {"num": "145", "title": "العقوبات — حقوق العمال", "priority": 3,
             "keywords": ["عقوبة","حبس","غرامة"],
             "why": "عقوبة صاحب العمل المخالف"},
        ],
    },
    "ضرب": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "308", "title": "الإيذاء البسيط", "priority": 1, "keywords": ["ضرب","إيذاء","اعتداء"], "why": "عقوبة من اعتدى على سلامة جسم غيره — حبس لا يجاوز سنتين"},
            {"num": "306", "title": "الإيذاء الجسيم", "priority": 2, "keywords": ["جسيم","خطير","عاهة","عجز"], "why": "اعتداء عمداً على سلامة جسم — حبس لا يجاوز 10 سنوات"},
            {"num": "309", "title": "الإيذاء الخفيف", "priority": 3, "keywords": ["خفيف","بسيط"], "why": "إيذاء لم يبلغ درجة الجسامة"},
            {"num": "315", "title": "الاعتداء على حامل", "priority": 4, "keywords": ["حامل","حبلى","إجهاض"], "why": ""},
        ],
    },
    "سرقة": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "334", "title": "السرقة البسيطة", "priority": 1, "keywords": ["سرقة","سرق"], "why": ""},
            {"num": "335", "title": "السرقة بظروف مشددة", "priority": 2, "keywords": ["ليل","إكراه"], "why": ""},
        ],
    },
    "شيك": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "357", "title": "إصدار شيك بدون رصيد", "priority": 1, "keywords": ["شيك","رصيد"], "why": "يعاقب كل من أعطى شيكاً لا يقابله رصيد قائم"},
            {"num": "359", "title": "تظهير الشيك مع العلم", "priority": 2, "keywords": ["تظهير"], "why": ""},
        ],
    },
    "مخدرات": {
        "law_name": "قانون مكافحة المخدرات والمؤثرات العقلية",
        "law_kw": "%مخدر%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "41", "title": "عقوبة التعاطي", "priority": 1, "keywords": ["تعاطي","حيازة"], "why": "يعاقب بالحبس لا تجاوز 3 سنوات كل من تعاطى مواد مخدرة"},
            {"num": "2", "title": "عقوبة الحيازة/الاتجار (م37 معدّلة)", "priority": 2, "keywords": ["اتجار","بيع","ترويج","حيازة"], "why": "يعاقب بالحبس لا تجاوز 3 سنوات ولا تقل عن 6 أشهر"},
        ],
    },
    "تشهير": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "326", "title": "القذف", "priority": 1, "keywords": ["قذف","تشهير"], "why": "إسناد واقعة تستوجب عقاب من أسندت إليه"},
            {"num": "327", "title": "السب", "priority": 2, "keywords": ["سب","إهانة"], "why": "رمي الغير بما يخدش شرفه أو كرامته"},
        ],
    },
    "ابتزاز": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "325", "title": "التهديد بإلحاق الضرر", "priority": 1, "keywords": ["ابتزاز","تهديد","هدد"], "why": "يعاقب كل من هدد غيره بإلحاق الضرر بنفسه أو سمعته أو ماله"},
        ],
    },
    "احتيال": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "354", "title": "النصب والاحتيال", "priority": 1, "keywords": ["نصب","احتيال"], "why": "التوصل بطريقة احتيالية إلى الاستيلاء على مال الغير"},
            {"num": "362", "title": "خيانة الأمانة", "priority": 2, "keywords": ["خيانة","أمانة","اختلاس","بدد"], "why": "اختلاس أو استعمال أو تبديد مال سُلّم على وجه الأمانة"},
        ],
    },
    "تزوير": {
        "law_name": "قانون العقوبات رقم 11 لسنة 2004",
        "law_kw": "%عقوبات%11%2004%",
        "court": "المحكمة الجنائية",
        "articles": [
            {"num": "204", "title": "تعريف التزوير وطرقه", "priority": 1, "keywords": ["تزوير","تغيير الحقيقة"], "why": "تزوير المحرر هو تغيير الحقيقة فيه بنية استعماله كمحرر صحيح"},
            {"num": "206", "title": "التزوير في محرر رسمي", "priority": 2, "keywords": ["رسمي","موظف"], "why": "حبس لا يجاوز 10 سنوات إذا وقع من موظف عام"},
            {"num": "210", "title": "استعمال محرر مزور", "priority": 3, "keywords": ["استعمال","استخدم","مزور"], "why": "يعاقب بعقوبة التزوير كل من استعمل محرراً مزوراً مع علمه"},
        ],
    },
}


# ════════════════════════════════════════════════════════════
# 2. كشف الموضوع
# ════════════════════════════════════════════════════════════

_TOPIC_KW = {
    "حضانة": ["حضانة","حاضن","محضون","عيال","أطفال","بنتي","ولدي","اسقاط حضان"],
    "طلاق": ["طلاق","خلع","تطليق","طليقتي","انفصال","ناشز"],
    "نفقة": ["نفقة","نفقه","إعالة"],
    "فصل_عمل": ["فصل","طفشني","طردني","فصلتني","تعسفي","نهاية خدمة","شالني","فصلوني"],
    "مخدرات": ["مخدرات","مخدر","حيازة","تعاطي","حشيش"],
    "ضرب": ["ضرب","ضربني","إيذاء","اعتداء","انضرب","ضربوني"],
    "سرقة": ["سرقة","سرق","سرقني","نشل"],
    "شيك": ["شيك","شيكات","بدون رصيد","طاير","مرتجع"],
    "تشهير": ["تشهير","سب","قذف","سمعة","شهّر","يسبني"],
    "ابتزاز": ["ابتزاز","يبتزني","يهددني","صور خاصة"],
    "احتيال": ["احتيال","نصب","ناصبني","خيانة أمانة","يختلس"],
    "تزوير": ["تزوير","مزور","زوّر"],
}


def detect_memo_topic(query: str) -> Optional[str]:
    q = (query or "").lower()
    best, best_c = None, 0
    for topic, kws in _TOPIC_KW.items():
        c = sum(1 for kw in kws if kw in q)
        if c > best_c:
            best_c, best = c, topic
    return best


def detect_memo_kind(query: str) -> str:
    q = (query or "").lower()
    if any(w in q for w in ["طعن بالتمييز","طعن تمييز","نقض","طعن بالنقض"]):
        return "cassation"
    if any(w in q for w in ["مذكرة دفاع","دفاع عن","أنا متهم","انا متهم","متهم بـ","متهم ب","متهم بت"]):
        return "defense"
    return "plaintiff"


# ════════════════════════════════════════════════════════════
# 3. اختيار المواد الأكثر صلة
# ════════════════════════════════════════════════════════════

def select_relevant_articles(topic: str, query: str, max_arts: int = 4) -> list:
    if topic not in TOPIC_LEGAL_MAP:
        return []
    articles = TOPIC_LEGAL_MAP[topic]["articles"]
    q = (query or "").lower()
    scored = []
    for art in articles:
        score = 10 - art["priority"]
        score += sum(3 for kw in art.get("keywords", []) if kw in q)
        scored.append((score, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [art for _, art in scored[:max_arts]]


# ════════════════════════════════════════════════════════════
# 4. سحب نصوص المواد من DB
# ════════════════════════════════════════════════════════════

async def fetch_article_text(pool, art_num: str, law_kw: str) -> Optional[str]:
    try:
        async with pool.acquire() as conn:
            # أولاً: بحث بـ article_number (الأدق)
            row = await conn.fetchrow(
                "SELECT content FROM chunks "
                "WHERE is_active=true AND article_number = $1 "
                "AND law_name ILIKE $2 "
                "AND law_name NOT ILIKE '%أحكام محكمة التمييز%' "
                "AND length(content) > 50 "
                "ORDER BY length(content) DESC LIMIT 1",
                art_num, law_kw
            )
            if not row:
                # ثانياً: بحث بـ regex في المحتوى (يكتشف "المادة 41" و "مادة (41 مكررا)")
                row = await conn.fetchrow(
                    "SELECT content FROM chunks "
                    "WHERE is_active=true "
                    "AND content ~ $1 AND law_name ILIKE $2 "
                    "AND law_name NOT ILIKE '%أحكام محكمة التمييز%' "
                    "AND length(content) > 50 "
                    "ORDER BY length(content) DESC LIMIT 1",
                    f"(?:المادة|مادة)[\\s(]+{art_num}", law_kw
                )
        if row and row['content']:
            return re.sub(r'\s+', ' ', row['content']).strip()[:600]
    except Exception as e:
        log.warning("fetch_article_text(%s): %s", art_num, e)
    return None


# ════════════════════════════════════════════════════════════
# 5. بناء القسم القانوني (من النظام — لا يُخطئ)
# ════════════════════════════════════════════════════════════

# كلمات التحقق: النص المسحوب يجب أن يحتوي واحدة من must ولا يحتوي أي من reject
_TOPIC_VALIDATORS = {
    "حضانة": {"must": ["حضانة","حاضن","محضون","حفظ الولد"], "reject": ["أجرة الحضانة","تقدير الأجرة"]},
    "طلاق": {"must": ["طلاق","تطليق","فرقة","خلع"], "reject": []},
    "نفقة": {"must": ["نفقة","إعالة","إنفاق","حقوق الزوج"], "reject": []},
    "فصل_عمل": {"must": ["عمل","عامل","فصل","إنهاء","أجر","مكافأة","خدمة","إنذار"], "reject": []},
    "مخدرات": {"must": ["يعاقب","حبس","غرامة","تعاطي","حيازة بقصد"], "reject": ["ترخيص","رخصة","زراعة","بحوث","مصانع","سجلات"]},
    "ضرب": {"must": ["اعتدى","إيذاء","سلامة جسم","ضرب","جرح","عاهة"], "reject": ["انتحار"]},
    "سرقة": {"must": ["سرقة","سرق","أخذ","اختلس"], "reject": []},
    "شيك": {"must": ["شيك","رصيد"], "reject": []},
    "تشهير": {"must": ["قذف","سب","إهانة","شرف","كرامة"], "reject": []},
    "ابتزاز": {"must": ["تهديد","هدد","ابتزاز"], "reject": ["خطف","حجز"]},
    "احتيال": {"must": ["احتيال","نصب","توصل","خيانة","أمانة","اختلس","بدد"], "reject": []},
    "تزوير": {"must": ["تزوير","زور","محرر","تغيير الحقيقة"], "reject": ["إتلاف","خرب","طريق"]},
}


async def build_legal_section(pool, topic: str, query: str) -> tuple:
    """
    يبني القسم القانوني مع تحقق ذاتي:
    يسحب نص المادة من DB → يتحقق أنه فعلاً عن الموضوع → يتخطى غير الصالح
    """
    if topic not in TOPIC_LEGAL_MAP:
        return "", ""

    td = TOPIC_LEGAL_MAP[topic]
    law_name = td["law_name"]
    law_kw = td["law_kw"]
    selected = select_relevant_articles(topic, query)
    validator = _TOPIC_VALIDATORS.get(topic, {"must": [], "reject": []})

    sec = f"\nثانياً — الأساس القانوني:\n\nتستند هذه الدعوى إلى أحكام {law_name}، وتحديداً:\n\n"
    summary_parts = []
    art_idx = 0

    for art in selected:
        full = await fetch_article_text(pool, art["num"], law_kw) if pool else None

        if full:
            # ═══ تحقق ذاتي صارم: must + reject ═══
            text_lower = full.lower()
            must_words = validator.get("must", [])
            reject_words = validator.get("reject", [])
            has_required = not must_words or any(w in text_lower for w in must_words)
            has_forbidden = reject_words and any(w in text_lower for w in reject_words)

            if not has_required or has_forbidden:
                log.warning("SKIP م%s for %s — must=%s reject=%s: %s", art["num"], topic, has_required, has_forbidden, full[:80])
                continue

        art_idx += 1
        sec += f"{art_idx}. المادة {art['num']} من {law_name} — {art['title']}:\n"
        if full:
            sec += f'   نص المادة: "{full}"\n'
            summary_parts.append(f"المادة {art['num']} ({art['title']}): {full[:300]}")
        if art.get("why"):
            sec += f"   وجه الاستدلال: {art['why']}\n"
        sec += "\n"

    return sec, "\n".join(summary_parts)


# ════════════════════════════════════════════════════════════
# 6. بناء الهيكل + البرومبت المنفصل للنموذج
# ════════════════════════════════════════════════════════════

def build_llm_narrative_prompt(topic: str, query: str, memo_kind: str, articles_summary: str) -> str:
    """
    يبني prompt للنموذج يطلب منه كتابة الأجزاء السردية فقط.
    مصمم ليكون ودوداً مع النموذج ولا يرفضه.
    """
    td = TOPIC_LEGAL_MAP.get(topic, {})
    law_name = td.get("law_name", "القانون القطري")

    if memo_kind == "plaintiff":
        role_label = "المدعي"
        sections = (
            "أولاً — الوقائع:\n"
            "اسرد ما حدث بالتفصيل والتسلسل الزمني — اذكر الأثر الإنساني على المدعي — 200 كلمة على الأقل.\n\n"
            "ثالثاً — التحليل والربط:\n"
            "اشرح كيف تنطبق المواد القانونية أدناه على وقائع الدعوى — اربط كل مادة بواقعة محددة — 200 كلمة على الأقل.\n\n"
            "رابعاً — الطلبات:\n"
            "اكتب ما يطلبه المدعي من المحكمة بشكل محدد وواضح.\n"
        )
    elif memo_kind == "defense":
        role_label = "المتهم"
        sections = (
            "أولاً — ملخص الاتهام:\n"
            "لخّص ما نُسب للمتهم.\n\n"
            "ثالثاً — الدفوع:\n"
            "اكتب 3 دفوع على الأقل — لكل دفع عنوان وشرح مفصّل مع ربط بالمواد أدناه — 200 كلمة لكل دفع.\n\n"
            "رابعاً — الطلبات:\n"
            "اطلب البراءة مع بيان السند.\n"
        )
    else:
        role_label = "الطاعن"
        sections = (
            "أولاً — بيانات الحكم المطعون فيه:\n"
            "صف الحكم وتاريخه.\n\n"
            "ثالثاً — أسباب الطعن:\n"
            "اكتب 3 أسباب طعن (قصور تسبيب / إخلال بحق الدفاع / مخالفة القانون).\n\n"
            "رابعاً — الطلبات:\n"
            "نقض الحكم والإعادة.\n"
        )

    prompt = (
        f"الموكل يقول: {query}\n\n"
        f"اكتب الأقسام التالية بأسلوب محامي قطري محترف:\n\n"
        f"{sections}\n"
        f"القانون المطبق: {law_name}\n"
        f"دور الموكل: {role_label}\n\n"
        f"المواد القانونية المتاحة للاستشهاد بها:\n{articles_summary}\n\n"
        "تعليمات:\n"
        "- لا تكتب عنوان المذكرة ولا البسملة (جاهزان).\n"
        "- لا تكتب قسم الأساس القانوني (جاهز وسيُدمج تلقائياً).\n"
        "- يمكنك الإشارة للمواد المذكورة أعلاه فقط.\n"
        "- اكتب بأسلوب إنساني مؤثر مع عبارات قانونية رصينة.\n"
        f"- {'استخدم الطاعن والحكم المطعون فيه.' if memo_kind == 'cassation' else 'لا تستخدم الطاعن — استخدم ' + role_label + '.'}\n"
        "- الحد الأدنى 500 كلمة.\n"
    )
    return prompt


def build_memo_header(topic: str, memo_kind: str) -> str:
    td = TOPIC_LEGAL_MAP.get(topic, {})
    court = td.get("court", "المحكمة المختصة")

    if memo_kind == "plaintiff":
        return f"""بسم الله الرحمن الرحيم

لائحة دعوى
مقدمة إلى: {court}

المدعي: ___
المدعى عليه/عليها: ___

"""
    elif memo_kind == "defense":
        return f"""بسم الله الرحمن الرحيم

مذكرة دفاع
مقدمة إلى: {court}

المتهم / المدعى عليه: ___

"""
    else:
        return """بسم الله الرحمن الرحيم

صحيفة طعن بالتمييز
مقدمة إلى: محكمة التمييز

الطاعن: ___
المطعون ضده: ___

"""


MEMO_FOOTER = "\n\nوالله ولي التوفيق،،،\n\n[اسم المحامي وتوقيعه]"


# ════════════════════════════════════════════════════════════
# 8. محلل وقائع المستخدم — يقرأ كلامه ويستخرج الحقائق
# ════════════════════════════════════════════════════════════

def analyze_user_facts(query: str, topic: str) -> dict:
    """يقرأ كلام المستخدم ويصنّف الحقائق: مؤكدة / قابلة للطعن / ناقصة."""
    q = (query or "").lower()
    facts = {"confirmed": [], "challengeable": [], "missing": []}

    if topic == "مخدرات":
        if any(w in q for w in ["عندي حشيش","لقوا عندي","ولقوا","ولقت","معي مخدر","معي حشيش"]):
            facts["confirmed"].append("الموكّل يعترف بالحيازة — لا تدفع بانتفاء العلم!")
        if any(w in q for w in ["إذن","اذن","أمر"]):
            facts["confirmed"].append("يوجد إذن تفتيش — لا تنكر وجوده")
            facts["challengeable"].append("ابحث عن عيوب التحريات / تجاوز حدود الإذن / صلاحية الإذن")
        if any(w in q for w in ["دورية","وقفتني"]):
            facts["challengeable"].append("التوقيف بدورية — هل كانت حالة تلبس تبرر التفتيش؟")
        if any(w in q for w in ["بسيطة","قليلة","شوية"]):
            facts["confirmed"].append("الكمية بسيطة → دليل على التعاطي الشخصي")
        if any(w in q for w in ["داهموني","مداهمة"]):
            facts["confirmed"].append("تمت مداهمة رسمية")
            facts["challengeable"].append("هل المداهمة في نفس المكان المذكور بالإذن؟")
        if any(w in q for w in ["أول مرة","اول مره"]):
            facts["confirmed"].append("أول مرة — يدعم طلب الإعفاء أو العلاج")
        if not any(w in q for w in ["إذن","اذن","دورية","وقفتني","داهموني"]):
            facts["missing"].append("كيف تم القبض — دورية أم مداهمة أم بلاغ؟")
        if not any(w in q for w in ["بسيطة","كمية","قليلة","كبيرة"]):
            facts["missing"].append("هل الكمية بسيطة أم كبيرة؟")

    elif topic == "ضرب":
        if any(w in q for w in ["دافعت","دفاع","هو بدأ","هو اللي"]):
            facts["confirmed"].append("الموكّل يعترف بالضرب كدفاع عن النفس")
        if any(w in q for w in ["تقرير","طبي"]):
            facts["confirmed"].append("يوجد تقرير طبي")
        elif any(w in q for w in ["ما فيه تقرير","بدون تقرير"]):
            facts["confirmed"].append("لا يوجد تقرير طبي — نقطة قوة للدفاع")
        if any(w in q for w in ["فيديو","كاميرا"]):
            facts["confirmed"].append("يوجد تسجيل مرئي")
        if any(w in q for w in ["شهود","شاهد"]):
            facts["confirmed"].append("يوجد شهود")

    elif topic == "حضانة":
        if any(w in q for w in ["تزوجت","متزوجة"]):
            facts["confirmed"].append("الأم تزوجت — سند لإسقاط الحضانة")
            if any(w in q for w in ["أجنبي","غريب","غير محرم","مش محرم"]):
                facts["confirmed"].append("الزوج أجنبي عن المحضون — م168 تنطبق مباشرة")
        if any(w in q for w in ["مهملة","إهمال","ما تهتم"]):
            facts["confirmed"].append("إهمال الأم ثابت — م182 تنطبق")
        if any(w in q for w in ["سافرت","انتقلت"]):
            facts["confirmed"].append("الأم انتقلت/سافرت بالأطفال")

    elif topic in ["فصل_عمل", "فصل"]:
        if any(w in q for w in ["بدون سبب","بلا سبب"]):
            facts["confirmed"].append("الفصل بدون سبب مشروع — تعسفي")
        if any(w in q for w in ["بدون إنذار","بلا إنذار","بدون اشعار"]):
            facts["confirmed"].append("بدون إنذار مسبق — مخالفة إجرائية")

    return facts


def build_facts_context(facts: dict) -> str:
    """يبني سياق تحليل الوقائع لحقنه في prompt النموذج."""
    parts = []
    if facts["confirmed"]:
        parts.append("✅ حقائق مؤكدة (لا تناقضها!):")
        for f in facts["confirmed"]:
            parts.append(f"  • {f}")
    if facts["challengeable"]:
        parts.append("🔍 نقاط قابلة للطعن (ابنِ دفوعك عليها):")
        for f in facts["challengeable"]:
            parts.append(f"  • {f}")
    if not parts:
        return ""
    return "\n═══ تحليل وقائع الموكّل ═══\n" + "\n".join(parts) + "\n⛔ لا تدفع بعكس ما أكده الموكّل.\n"


# ════════════════════════════════════════════════════════════
# 9. أسئلة توضيحية ذكية v2
# ════════════════════════════════════════════════════════════

def get_smart_questions(query: str, topic: str) -> list:
    """يحدد الأسئلة الناقصة المهمة التي تغيّر استراتيجية الدفاع."""
    q = (query or "").lower()
    wc = len(q.split())
    if wc > 35:
        return []
    missing = []

    if topic == "مخدرات":
        if any(w in q for w in ["إذن","اذن"]) and not any(w in q for w in ["تحريات","تحري"]):
            missing.append("هل تعرف إذا التحريات قبل الإذن ذكرت اسمك بالتحديد؟")
        if any(w in q for w in ["إذن","اذن"]) and not any(w in q for w in ["نفس المكان","تجاوز"]):
            missing.append("هل التفتيش كان في نفس المكان المذكور في الإذن؟")
        if not any(w in q for w in ["بسيطة","كمية","قليلة","كبيرة"]):
            missing.append("الكمية المضبوطة كانت بسيطة ولا كبيرة؟")
        if not any(w in q for w in ["أول مرة","سوابق","سبق"]):
            missing.append("هل عندك سوابق أو هذي أول مرة؟")
    elif topic == "حضانة":
        if not any(w in q for w in ["عمر","سنة","سنوات"]):
            missing.append("كم عمر الأطفال؟ (ذكور/إناث)")
        if any(w in q for w in ["تزوجت"]) and not any(w in q for w in ["أجنبي","محرم","غريب"]):
            missing.append("الزوج الجديد محرم للأطفال (عمهم مثلاً) أو أجنبي عنهم؟")
    elif topic in ["فصل_عمل","فصل"]:
        if not any(w in q for w in ["سنة","سنوات","شهر"]): missing.append("كم مدة خدمتك؟")
        if not any(w in q for w in ["راتب","ريال","ألف"]): missing.append("كم راتبك؟")
        if not any(w in q for w in ["إنذار","انذار","سبب"]): missing.append("هل أعطوك إنذار أو ذكروا سبب الفصل؟")
    elif topic == "ضرب":
        if not any(w in q for w in ["تقرير","طبي"]): missing.append("هل عندك تقرير طبي؟")
        if not any(w in q for w in ["شهود","فيديو","كاميرا"]): missing.append("هل فيه شهود أو تسجيل مرئي؟")

    return missing[:3]
