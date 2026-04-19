# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║        Answer Compressor — المساعد القانوني القطري                           ║
║        يُزيل التكرار ويُشدّد اللغة القانونية مع الحفاظ على المعنى            ║
╚══════════════════════════════════════════════════════════════════════════════╝

compress_answer(answer, llm_caller=None) → str (مضغوط ومنظَّف)

مراحل المعالجة:
  1. إزالة الجمل المكررة بالقاعدة
  2. إزالة جمل الحشو القانوني
  3. اختياري: LLM pass لتكثيف الصياغة
"""
from __future__ import annotations

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── الحد الأدنى لتشغيل الضغط (بالحروف) ─────────────────────────────────────
MIN_LENGTH_TO_COMPRESS = 400

# ── جمل الحشو الشائعة في الإجابات القانونية ─────────────────────────────────
_FILLER_PATTERNS = [
    re.compile(r"وفيما يتعلق بسؤالك[،,]?\s*", re.UNICODE),
    re.compile(r"بناءً على ما سبق[،,]?\s*", re.UNICODE),
    re.compile(r"خلاصة القول[،,]?\s*", re.UNICODE),
    re.compile(r"في ضوء ما تقدم[،,]?\s*", re.UNICODE),
    re.compile(r"وتجدر الإشارة إلى أنه[،,]?\s*", re.UNICODE),
    re.compile(r"يُلاحظ في هذا الصدد أن\s*", re.UNICODE),
    re.compile(r"وقد نصت المادة.*على أنه\s*", re.UNICODE),   # تكرار تقديمي
    re.compile(r"وعليه[،,]?\s*وبناءً على ما سبق[،,]?\s*", re.UNICODE),
    re.compile(r"هذا وقد\s*", re.UNICODE),
    re.compile(r"كما ذكرنا سابقاً[،,]?\s*", re.UNICODE),
    re.compile(r"كما أشرنا[،,]?\s*", re.UNICODE),
    re.compile(r"وكما هو معلوم[،,]?\s*", re.UNICODE),
    re.compile(r"ومن المعروف أن\s*", re.UNICODE),
]

# ── LLM prompt للضغط ─────────────────────────────────────────────────────────
_COMPRESS_PROMPT = """أنت محرر قانوني محترف.

المهمة: اضغط الإجابة التالية بحذف التكرار وجمل الحشو مع الحفاظ على:
- جميع المواد والقوانين المستشهد بها
- الهيكل الأساسي (التكييف، السند، التحليل، التوصية)
- كل معلومة قانونية جوهرية

القاعدة: الإجابة المضغوطة لا تقل عن 60% من الأصل ولا تزيد عن 80%.

الإجابة الأصلية:
{answer}

الإجابة المضغوطة (مباشرة، بدون تعليق):"""


def _remove_filler(text: str) -> str:
    """يُزيل جمل الحشو المُعرَّفة."""
    for pattern in _FILLER_PATTERNS:
        text = pattern.sub("", text)
    return text


def _deduplicate_sentences(text: str) -> str:
    """
    يُزيل الجمل المكررة مع الحفاظ على الترتيب.
    يُعدّ الجملتان مكررتان إذا تشابهتا بنسبة > 85%.
    """
    # قسّم بالفواصل المنقوطة والنقاط مع الحفاظ على الفواصل
    sentences = re.split(r'(?<=[.؟!\n])\s+', text)
    seen: list[str] = []
    result: list[str] = []

    for sentence in sentences:
        s = sentence.strip()
        if len(s) < 20:
            result.append(sentence)
            continue

        # تحقق من التشابه مع الجمل السابقة
        normalized = re.sub(r'\s+', ' ', s).lower()
        is_dup = False
        for prev in seen[-8:]:   # تحقق من آخر 8 جمل فقط
            prev_n = re.sub(r'\s+', ' ', prev).lower()
            # نسبة التشابه البسيطة: عدد الكلمات المشتركة
            if len(normalized) > 0 and len(prev_n) > 0:
                words_a = set(normalized.split())
                words_b = set(prev_n.split())
                if len(words_a) > 0:
                    overlap = len(words_a & words_b) / len(words_a)
                    if overlap > 0.85:
                        is_dup = True
                        break

        if not is_dup:
            seen.append(s)
            result.append(sentence)

    return " ".join(result)


def compress_answer_rules(answer: str) -> str:
    """
    ضغط بالقواعد فقط (سريع، بدون LLM).
    مناسب للإجابات البسيطة والـ Ollama.
    """
    if not answer or len(answer) < MIN_LENGTH_TO_COMPRESS:
        return answer

    cleaned = _remove_filler(answer)
    cleaned = _deduplicate_sentences(cleaned)

    # تنظيف المسافات الزائدة
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned)

    log.info(
        "compress_rules: %d → %d chars (%.0f%%)",
        len(answer), len(cleaned),
        len(cleaned) / max(len(answer), 1) * 100
    )
    return cleaned.strip()


async def compress_answer(
    answer: str,
    llm_caller=None,
    use_llm: bool = False,
) -> str:
    """
    نقطة الدخول الرئيسية للضغط.

    الخطوات:
    1. دائماً: ضغط بالقواعد
    2. إذا use_llm=True وllm_caller متاح: ضغط إضافي بـ LLM

    Parameters
    ----------
    answer     : الإجابة الأصلية
    llm_caller : async callable (system, messages) → str
    use_llm    : تفعيل LLM pass (أبطأ لكن أفضل جودةً)
    """
    if not answer or not answer.strip():
        return answer

    # المرحلة 1: ضغط بالقواعد
    compressed = compress_answer_rules(answer)

    # المرحلة 2: LLM (اختياري — للإجابات الطويلة فقط)
    if use_llm and llm_caller and len(compressed) > 800:
        try:
            prompt = _COMPRESS_PROMPT.format(answer=compressed)
            msgs   = [{"role": "user", "content": prompt}]
            result = (await llm_caller("", msgs)).strip()
            # لا تقبل إجابة أقصر من 50% من الأصل (يعني LLM حذف معلومات مهمة)
            if result and len(result) >= len(compressed) * 0.50:
                log.info(
                    "compress_llm: %d → %d chars",
                    len(compressed), len(result)
                )
                return result
            else:
                log.warning("compress_llm: نتيجة قصيرة جداً — نتجاهل LLM")
        except Exception as e:
            log.debug("compress_answer LLM error: %s", e)

    return compressed
