# -*- coding: utf-8 -*-
"""
Query Planner — يقسم الأسئلة المعقدة لأسئلة فرعية.
يعمل قبل الـ search لضمان تغطية كل جوانب السؤال.
"""
import re, logging
from typing import List, Dict

log = logging.getLogger(__name__)

# أنماط الأسئلة المركبة
_COMPOUND_PATTERNS = [
    # "و" تربط موضوعين مختلفين
    re.compile(r"(.+?)\s+(?:و|وكمان|وبعد|وهل|وش)\s+(.+)", re.DOTALL),
    # أسئلة متعددة بعلامات استفهام
    re.compile(r"(.+?\?)\s+(.+?\?)", re.DOTALL),
]

# كلمات تدل على تعقيد
_COMPLEXITY_MARKERS = [
    "وش حقوقي", "وش أسوي", "كيف أقدر", "ما هي الإجراءات",
    "ما هي الخطوات", "اشرح لي", "فصّل لي", "وضّح لي",
    "ما الفرق", "قارن بين", "متى يسقط", "متى ينتهي",
]

# مواضيع متعددة في سؤال واحد
_MULTI_TOPIC_KEYWORDS = {
    "حضانة": ["حضانة", "حضانه", "حاضن", "محضون", "اسقط حضانت", "اسقاط حضان"],
    "نفقة": ["نفقة", "نفقه", "إنفاق", "نفقتها", "نفقتهم", "ابي نفق"],
    "طلاق": ["طلاق", "تطليق", "خلع"],
    "فصل": ["فصل", "فصل تعسفي", "إنهاء عقد"],
    "مكافأة": ["مكافأة", "مكافاة", "نهاية خدمة"],
    "تعويض": ["تعويض", "ضرر"],
    "سرقة": ["سرقة", "اختلاس"],
    "مخدرات": ["مخدرات", "حشيش", "تعاطي"],
    "إيجار": ["إيجار", "إخلاء", "مستأجر"],
    "شركات": ["شركة", "شريك", "أسهم"],
}


def analyze(query: str) -> Dict:
    """
    يحلل السؤال ويقرر إذا يحتاج تقسيم.
    Returns: {needs_planning, sub_queries, topics, complexity}
    """
    q = query.strip()
    words = q.split()
    word_count = len(words)

    # أسئلة قصيرة لا تحتاج تخطيط
    if word_count <= 8:
        return {"needs_planning": False, "sub_queries": [q],
                "topics": [], "complexity": "بسيط"}

    # كشف المواضيع المتعددة
    detected_topics = []
    q_lower = q.lower()
    for topic, keywords in _MULTI_TOPIC_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            detected_topics.append(topic)

    # إذا أكثر من موضوع → يحتاج تقسيم
    if len(detected_topics) >= 2:
        sub_queries = _decompose_multi_topic(q, detected_topics)
        return {"needs_planning": True, "sub_queries": sub_queries,
                "topics": detected_topics, "complexity": "معقد"}

    # إذا فيه "و" تربط موضوعين
    for pattern in _COMPOUND_PATTERNS:
        m = pattern.match(q)
        if m and len(m.group(1).split()) >= 4 and len(m.group(2).split()) >= 4:
            return {"needs_planning": True,
                    "sub_queries": [m.group(1).strip(), m.group(2).strip()],
                    "topics": detected_topics, "complexity": "مركب"}

    # سؤال طويل (>25 كلمة) مع markers تعقيد
    if word_count > 25 and any(m in q_lower for m in _COMPLEXITY_MARKERS):
        sub_queries = _decompose_long_query(q)
        if len(sub_queries) > 1:
            return {"needs_planning": True, "sub_queries": sub_queries,
                    "topics": detected_topics, "complexity": "مفصّل"}

    return {"needs_planning": False, "sub_queries": [q],
            "topics": detected_topics, "complexity": "بسيط"}


def _decompose_multi_topic(query: str, topics: List[str]) -> List[str]:
    """يقسم سؤال يحتوي مواضيع متعددة"""
    sub_queries = []
    for topic in topics:
        # أنشئ سؤال فرعي لكل موضوع
        keywords = _MULTI_TOPIC_KEYWORDS.get(topic, [])
        # ابحث عن الجملة المتعلقة بهذا الموضوع
        for kw in keywords:
            if kw in query:
                # خذ السياق حول الكلمة
                idx = query.lower().index(kw.lower())
                start = max(0, query.rfind(" ", 0, max(0, idx - 30)))
                end = min(len(query), query.find(" ", idx + 30) if query.find(" ", idx + 30) > 0 else len(query))
                sub = query[start:end].strip()
                if len(sub.split()) >= 3:
                    sub_queries.append(sub)
                break

    # إذا ما لقى أجزاء كافية → رجّع السؤال كامل
    if len(sub_queries) < 2:
        return [query]
    return sub_queries


def _decompose_long_query(query: str) -> List[str]:
    """يقسم سؤال طويل لأجزاء"""
    # قسّم على الفواصل والنقاط
    parts = re.split("[,،.]", query)
    parts = [p.strip() for p in parts if len(p.strip().split()) >= 3]

    if len(parts) >= 2:
        return parts[:4]  # أقصى 4 أجزاء
    return [query]
