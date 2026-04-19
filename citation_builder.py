# -*- coding: utf-8 -*-
"""
citation_builder.py — بناء الاستشهادات القانونية
==================================================
يُعالج الإجابة المُولَّدة ومصادرها (chunks) ليُنتج:
  {
    "answer"          : النص الأصلي للإجابة,
    "citations"       : [{"number":1,"source":"...","article":"...","text":"...","url":"..."}],
    "answer_with_refs": نفس الإجابة مع [1][2][3] مضمَّنة
  }

الاستخدام:
    from citation_builder import build_citations, CitationResult

    result = build_citations(answer, chunks)
    print(result["answer_with_refs"])
    print(result["citations"])
"""

from __future__ import annotations

import re
import logging
from typing import TypedDict

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# أنماط الاستشهاد
# ══════════════════════════════════════════════════════════════

# يكتشف [1] [2] [3] أو [1,2] أو [1][2] في نص الإجابة
_REF_RE = re.compile(r"\[(\d+)\]", re.UNICODE)

# يستخرج رقم المادة من حقل article_number أو من content
_ARTICLE_IN_CONTENT_RE = re.compile(
    r"(?:المادة|مادة|م\.?)\s*\(?\s*(\d+)\s*\)?",
    re.UNICODE,
)

# يستخرج رقم القانون + سنته من اسم القانون أو الـ source
_LAW_NUM_YEAR_RE = re.compile(
    r"(?:رقم|قانون)\s*\(?\s*(\d+)\s*\)?\s*(?:لسنة|عام|سنة)\s*\(?\s*(\d{4})\s*\)?",
    re.UNICODE,
)

# يكتشف إذا كان اسم الملف يُشير لقانون من ميزان
_MIZAN_SOURCE_RE = re.compile(r"^(?:law_|qlaw_|ql_|laws/)(\d+)", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════
# TypedDict
# ══════════════════════════════════════════════════════════════
class Citation(TypedDict):
    number  : int
    source  : str    # اسم القانون
    article : str    # رقم المادة
    text    : str    # مقتطف النص
    url     : str    # رابط الميزان (أو "")


class CitationResult(TypedDict):
    answer          : str
    citations       : list[Citation]
    answer_with_refs: str


# ══════════════════════════════════════════════════════════════
# الدالة الرئيسية
# ══════════════════════════════════════════════════════════════
def build_citations(answer: str, chunks: list[dict]) -> CitationResult:
    """
    يبني قائمة الاستشهادات ويُضمّنها في نص الإجابة.

    Parameters
    ----------
    answer : نص الإجابة المُولَّدة (قد تحتوي [1][2][3] أو لا)
    chunks : list[dict] — نتائج RAG من قاعدة البيانات

    Returns
    -------
    CitationResult مع:
      - answer          : النص الأصلي بدون تغيير
      - citations       : قائمة مُرقَّمة من 1..N
      - answer_with_refs: الإجابة مع [1][2]..  مُضمَّنة عند الاستشهادات
    """
    if not chunks:
        return CitationResult(answer=answer, citations=[], answer_with_refs=answer)

    # بناء قائمة الاستشهادات من الـ chunks
    citations: list[Citation] = []
    for i, chunk in enumerate(chunks, start=1):
        citation = _build_citation_from_chunk(i, chunk)
        citations.append(citation)

    # إذا كانت الإجابة لا تحتوي مراجع [1][2]... → نُضيفها تلقائياً
    if _REF_RE.search(answer):
        answer_with_refs = _normalize_existing_refs(answer, citations)
    else:
        answer_with_refs = _inject_references(answer, citations)

    return CitationResult(
        answer          = answer,
        citations       = citations,
        answer_with_refs= answer_with_refs,
    )


# ══════════════════════════════════════════════════════════════
# بناء كيان الاستشهاد من chunk
# ══════════════════════════════════════════════════════════════
def _build_citation_from_chunk(number: int, chunk: dict) -> Citation:
    """يُنشئ Citation من بيانات chunk الواحد."""

    # ── اسم المصدر (القانون) ──
    source = chunk.get("law_name") or chunk.get("source") or ""
    source = source.strip()

    # إذا كان المصدر اسم ملف → استخرج اسماً مقروءاً
    if source and "/" in source or source.endswith(".pdf") or source.endswith(".txt"):
        source = _humanize_source(source)

    # ── رقم المادة ──
    article = str(chunk.get("article_number") or "").strip()
    if not article:
        # حاول استخراجه من المحتوى
        m = _ARTICLE_IN_CONTENT_RE.search(chunk.get("content", ""))
        article = m.group(1) if m else ""

    # ── مقتطف النص ──
    content = chunk.get("content") or ""
    text    = content[:300].strip()
    if len(content) > 300:
        text += "..."

    # ── رابط الميزان ──
    url = _build_mizan_url(chunk)

    return Citation(
        number  = number,
        source  = source,
        article = article,
        text    = text,
        url     = url,
    )


def _humanize_source(source: str) -> str:
    """يُحوّل اسم الملف إلى نص مقروء."""
    # أزل المسار والامتداد
    name = source.split("/")[-1].split("\\")[-1]
    name = re.sub(r"\.(pdf|txt|docx?)$", "", name, flags=re.IGNORECASE)
    # أزل البادئات التقنية
    name = re.sub(r"^(law_|qlaw_|ql_)", "", name, flags=re.IGNORECASE)
    # استبدل الشرطات السفلية بمسافات
    name = name.replace("_", " ").replace("-", " ").strip()
    return name or source


def _build_mizan_url(chunk: dict) -> str:
    """
    يبني رابط الميزان.
    النمط: https://www.almeezan.qa/LawPage.aspx?id={law_id}
    """
    law_id = chunk.get("law_id")
    if law_id:
        return f"https://www.almeezan.qa/LawPage.aspx?id={law_id}"

    # محاولة استخراج law_id من اسم الملف
    source = str(chunk.get("source") or "")
    m = _MIZAN_SOURCE_RE.match(source.split("/")[-1])
    if m:
        return f"https://www.almeezan.qa/LawPage.aspx?id={m.group(1)}"

    # رابط بحث عام بالرقم والسنة
    law_number = chunk.get("law_number") or ""
    law_year   = chunk.get("law_year")   or ""
    if law_number and law_year:
        return (
            f"https://www.almeezan.qa/LawSearchPage.aspx"
            f"?LawNo={law_number}&Year={law_year}"
        )

    return ""


# ══════════════════════════════════════════════════════════════
# حقن / تطبيع المراجع في نص الإجابة
# ══════════════════════════════════════════════════════════════
def _normalize_existing_refs(answer: str, citations: list[Citation]) -> str:
    """
    إذا كانت الإجابة تحتوي [1][2][3]، نتحقق أن جميع الأرقام ضمن النطاق
    ونُزيل أي مرجع خارج النطاق (e.g. [15] بينما لدينا 5 مصادر فقط).
    """
    max_ref = len(citations)

    def _filter_ref(m: re.Match) -> str:
        n = int(m.group(1))
        return f"[{n}]" if 1 <= n <= max_ref else ""

    return _REF_RE.sub(_filter_ref, answer)


def _inject_references(answer: str, citations: list[Citation]) -> str:
    """
    إذا لم تحتوِ الإجابة على مراجع رقمية، يُضيف [1][2]... بعد الجمل
    التي تستشهد بمواد قانونية صريحة.

    استراتيجية:
      - تقسيم الإجابة إلى جمل
      - إذا ذكرت الجملة مادة / قانون → ابحث عن chunk مطابق → أضف [n]
      - إذا لم يوجد → أضف [1] بعد أول جملة كإشارة عامة
    """
    if not citations:
        return answer

    sentences = _split_sentences(answer)
    result_parts: list[str] = []
    _used_general_ref = False

    for sent in sentences:
        sent_clean = sent.rstrip()

        # ابحث عن رقم مادة مذكور في الجملة
        art_match = _ARTICLE_IN_CONTENT_RE.search(sent)
        if art_match:
            art_num = art_match.group(1)
            # ابحث عن citation يطابق هذه المادة
            ref_num = _find_citation_by_article(art_num, citations)
            if ref_num:
                sent_clean = sent_clean + f" [{ref_num}]"
                result_parts.append(sent_clean)
                continue

        # الجملة الأولى ذات محتوى قانوني → أضف [1] عاماً
        if (not _used_general_ref and len(sent_clean) > 30
                and _looks_legal(sent_clean)):
            sent_clean = sent_clean + " [1]"
            _used_general_ref = True

        result_parts.append(sent_clean)

    return "".join(result_parts)


def _split_sentences(text: str) -> list[str]:
    """يُقسّم النص إلى جمل بسيطة مع الاحتفاظ بالفواصل."""
    # تقسيم على: . أو ؟ أو ! مع مسافة لاحقة، أو سطر جديد
    parts = re.split(r"(?<=[.!؟\n])\s*", text)
    return [p for p in parts if p]


def _find_citation_by_article(article_num: str, citations: list[Citation]) -> Optional[int]:
    """يبحث عن رقم استشهاد يطابق رقم المادة المُعطاة."""
    for c in citations:
        if c["article"] == article_num:
            return c["number"]
    return None


def _looks_legal(sentence: str) -> bool:
    """يتحقق إذا كانت الجملة تبدو قانونية (تحتوي مصطلحاً قانونياً)."""
    _LEGAL_MARKERS = (
        "قانون", "مادة", "عقوبة", "يُعاقب", "حكم", "نص",
        "استناداً", "وفقاً", "يشترط", "يحق", "يُلزم",
    )
    return any(m in sentence for m in _LEGAL_MARKERS)


# حل مشكلة Optional قبل Python 3.10
from typing import Optional
