# -*- coding: utf-8 -*-
"""
Language Perfection Layer — Phase 2 Brain Upgrade
==================================================
Post-processing layer that transforms LLM output from robotic/repetitive
Arabic into natural, native-level expert Arabic.

Operations (in order):
  1. Remove robotic opening phrases
  2. Remove filler/padding sentences
  3. Deduplicate near-identical sentences (>85% word overlap)
  4. Normalize punctuation and whitespace
  5. Fix common Arabic typographic issues
  6. Adaptive opening injection based on user_goal + emotional_state
  7. (Optional) LLM polish pass for expert-level users

Performance impact: ~2-5ms rule-based, ~200-400ms LLM pass (only if use_llm=True)
"""
from __future__ import annotations
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ROBOTIC OPENERS TO REMOVE
# ─────────────────────────────────────────────────────────────────────────────
_ROBOTIC_OPENERS = [
    r"^بناءً على المعلومات المتوفرة[،,]?\s*",
    r"^بناءً على ما تم ذكره[،,]?\s*",
    r"^بناءً على السياق المُقدَّم[،,]?\s*",
    r"^وفقاً للمعلومات المُقدَّمة[،,]?\s*",
    r"^استناداً إلى ما سبق[،,]?\s*",
    r"^في ضوء ما تقدم[،,]?\s*",
    r"^في ضوء المعطيات المُقدَّمة[،,]?\s*",
    r"^بالنظر إلى ما سبق[،,]?\s*",
    r"^يمكنني القول أن\s*",
    r"^يمكن القول إن\s*",
    r"^كمساعد قانوني[،,]?\s*",
    r"^كمستشار قانوني[،,]?\s*",
    r"^أودّ الإشارة إلى أن\s*",
    r"^تجدر الإشارة إلى أن\s*",
    r"^جواباً على سؤالك[،,]?\s*",
    r"^للإجابة على سؤالك[،,]?\s*",
    r"^بخصوص سؤالك[،,]?\s*",
    r"^فيما يتعلق بسؤالك[،,]?\s*",
    r"^سأجيب على سؤالك\s*",
]
_ROBOTIC_OPENER_RE = re.compile(
    "|".join(_ROBOTIC_OPENERS),
    re.IGNORECASE | re.MULTILINE
)

# ─────────────────────────────────────────────────────────────────────────────
# FILLER PHRASES TO REMOVE (mid-text)
# ─────────────────────────────────────────────────────────────────────────────
_FILLER_PHRASES = [
    r"بناءً على ما سبق[،,]?\s*",
    r"كما ذكرنا سابقاً[،,]?\s*",
    r"كما أشرنا آنفاً[،,]?\s*",
    r"كما تجدر الإشارة[،,]?\s*",
    r"وتجدر الإشارة هنا إلى أن\s*",
    r"وخلاصة القول[،,]?\s*",
    r"وفي الختام[،,]?\s*",
    r"وفي نهاية المطاف[،,]?\s*",
    r"ومما سبق يتضح أن\s*",
    r"من خلال ما سبق[،,]?\s*",
    r"من خلال استعراض ما سبق[،,]?\s*",
    r"هذا ويلاحظ أن\s*",
    r"وهكذا يتبيّن أن\s*",
    r"ولذا يمكن القول\s*",
    r"نستخلص مما سبق\s*",
]
_FILLER_RE = re.compile(
    "|".join(_FILLER_PHRASES),
    re.IGNORECASE
)

# ─────────────────────────────────────────────────────────────────────────────
# ADAPTIVE OPENINGS by user_goal + emotional_state
# ─────────────────────────────────────────────────────────────────────────────
_GOAL_OPENINGS = {
    ("معلومة",    "محايد"):   "بناءً على القانون القطري،",
    ("معلومة",    "خائف"):    "القانون واضح في هذا الأمر، وهو يحميك:",
    ("توجيه",     "محايد"):   "في هذه الحالة، الموقف القانوني هو:",
    ("توجيه",     "غاضب"):    "حقك القانوني واضح. إليك ما يجب معرفته:",
    ("توجيه",     "خائف"):    "لا تقلق — القانون في صفّك:",
    ("توجيه",     "يائس"):    "رغم صعوبة الموقف، القانون يتيح لك:",
    ("إجراء",     "محايد"):   "للتصرف قانونياً في هذه الحالة:",
    ("إجراء",     "عاجل"):    "الخطوة الفورية المطلوبة:",
    ("إجراء",     "غاضب"):    "لتحصيل حقك القانوني، اتّبع هذه الخطوات:",
    ("كتابة وثيقة", "محايد"): "الصيغة القانونية المطلوبة:",
    ("تفريغ عاطفي", "غاضب"):  "أتفهم غضبك، وهذا ما يقوله القانون:",
    ("تفريغ عاطفي", "محبط"):  "وضعك يستحق حلاً — وهذا ما يوفره القانون:",
    ("تفريغ عاطفي", "يائس"):  "الوضع صعب، لكن القانون يتيح لك خيارات:",
}
_DEFAULT_OPENING = "بناءً على القانون القطري،"


# ─────────────────────────────────────────────────────────────────────────────
# LLM POLISH PROMPT (for expert-level users)
# ─────────────────────────────────────────────────────────────────────────────
LLM_POLISH_PROMPT = """\
أنت محرر لغوي قانوني متخصص. مهمتك: تحسين الإجابة القانونية التالية مع الحفاظ على محتواها الكامل.

التحسينات المطلوبة:
1. حوّل أي أسلوب آلي أو روبوتي إلى أسلوب إنساني طبيعي
2. أزل التكرار في المعنى (وليس في المصطلحات القانونية الضرورية)
3. اجعل الانتقال بين الأقسام سلساً
4. حافظ على كل المعلومات القانونية — لا تحذف أي مادة أو رقم
5. تأكد من أن اللغة بمستوى خبير قانوني قطري

السؤال الأصلي: {question}

الإجابة للتحسين:
{answer}

الإجابة المحسّنة (حافظ على نفس الهيكل والأقسام):"""


# ─────────────────────────────────────────────────────────────────────────────
# SENTENCE DEDUPLICATION
# ─────────────────────────────────────────────────────────────────────────────
def _dedup_sentences(text: str, threshold: float = 0.85) -> str:
    """
    Remove near-duplicate sentences (>85% word overlap).
    Preserves first occurrence, removes subsequent near-duplicates.
    """
    # Split on Arabic sentence boundaries
    sentences = re.split(r'(?<=[.؟!])\s+', text)
    if len(sentences) <= 2:
        return text

    kept = []
    kept_word_sets = []

    for sent in sentences:
        if len(sent.strip()) < 20:   # skip very short fragments
            kept.append(sent)
            continue
        words = set(re.findall(r'[\u0621-\u064A]{3,}', sent))
        if not words:
            kept.append(sent)
            continue
        is_dup = False
        for prev_words in kept_word_sets:
            if not prev_words:
                continue
            overlap = len(words & prev_words) / max(len(words), 1)
            if overlap >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(sent)
            kept_word_sets.append(words)

    return " ".join(kept)


# ─────────────────────────────────────────────────────────────────────────────
# ARABIC TYPOGRAPHY FIXES
# ─────────────────────────────────────────────────────────────────────────────
def _fix_typography(text: str) -> str:
    """Fix common Arabic typography issues from LLM output."""
    # Fix double spaces
    text = re.sub(r'  +', ' ', text)
    # Fix space before punctuation
    text = re.sub(r'\s+([.،؟!:؛])', r'\1', text)
    # Fix missing space after punctuation (not for numbers like 2004)
    text = re.sub(r'([.،؟!:؛])([^\s\d\n])', r'\1 \2', text)
    # Fix " )" → ")" and "( " → "("
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    # Normalize Arabic quotes
    text = text.replace('"', '\"').replace('"', '\"')
    # Remove trailing spaces from lines
    text = re.sub(r' +\n', '\n', text)
    # Normalize multiple newlines (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RULE-BASED PERFECTION (always runs, ~2-5ms)
# ─────────────────────────────────────────────────────────────────────────────
def perfect_answer_rules(
    answer: str,
    user_goal: str = "معلومة",
    emotional_state: str = "محايد",
) -> str:
    """
    Rule-based language perfection — always applied.
    Performance impact: ~2-5ms

    Steps:
      1. Strip robotic openers
      2. Remove filler phrases
      3. Deduplicate sentences
      4. Fix typography
      5. Inject adaptive opening
    """
    if len(answer.strip()) < 50:
        return answer

    # Step 1: Remove robotic opener from start of answer
    cleaned = _ROBOTIC_OPENER_RE.sub("", answer, count=1).strip()

    # Step 2: Remove filler phrases (mid-text)
    if len(cleaned) > 400:   # Only for longer answers
        cleaned = _FILLER_RE.sub("", cleaned)

    # Step 3: Deduplicate sentences
    if len(cleaned) > 300:
        cleaned = _dedup_sentences(cleaned)

    # Step 4: Fix typography
    cleaned = _fix_typography(cleaned)

    # Step 5: Inject adaptive opening if answer lost its opener
    # Only if the answer doesn't already start with a header (** or emoji)
    if cleaned and not re.match(r'^(\*\*|📋|⚖️|🔍|⚠️|✅|📊|#)', cleaned):
        opener = _GOAL_OPENINGS.get(
            (user_goal, emotional_state),
            _GOAL_OPENINGS.get((user_goal, "محايد"), _DEFAULT_OPENING)
        )
        # Only prepend if the answer doesn't already start with something similar
        if not any(cleaned.startswith(o[:8]) for o in _GOAL_OPENINGS.values()):
            pass  # Skip — the deep reasoning system prompt handles the opening

    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# LLM POLISH PASS (optional, only for expert users with long answers)
# ─────────────────────────────────────────────────────────────────────────────
async def perfect_answer_llm(
    answer: str,
    question: str,
    llm_caller=None,
    user_level: str = "beginner",
) -> str:
    """
    Optional LLM polish pass — only for expert users with answers > 800 chars.
    Performance impact: ~200-400ms (Haiku), skipped for beginner/intermediate.
    """
    if llm_caller is None:
        return answer
    if user_level not in ("expert",):
        return answer
    if len(answer) < 800:
        return answer

    try:
        prompt = LLM_POLISH_PROMPT.format(question=question[:200], answer=answer[:2000])
        polished = await llm_caller("", [{"role": "user", "content": prompt}])
        if polished and len(polished.strip()) > len(answer) * 0.6:
            return polished.strip()
    except Exception as e:
        log.debug("language_perfection LLM pass skipped: %s", e)

    return answer


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
async def perfect_answer(
    answer: str,
    analysis: dict,
    question: str,
    llm_caller=None,
) -> str:
    """
    Full language perfection pipeline.

    Args:
        answer:     Raw LLM output
        analysis:   Output of analyze_user_input()
        question:   Original user question
        llm_caller: Optional LLM caller for polish pass

    Returns:
        Perfected answer string

    Performance impact: 2-5ms rule-based + 0-400ms optional LLM
    """
    user_goal      = analysis.get("user_goal",      "معلومة")
    emotional_state = analysis.get("emotional_state", "محايد")
    user_level     = analysis.get("user_level",     "beginner")

    # Always: rule-based pass
    result = perfect_answer_rules(answer, user_goal, emotional_state)

    # Optional: LLM polish for experts
    result = await perfect_answer_llm(result, question, llm_caller, user_level)

    return result
