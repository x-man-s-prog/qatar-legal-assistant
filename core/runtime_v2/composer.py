# -*- coding: utf-8 -*-
"""
runtime_v2.composer — THE single author of user-facing text.

Two public functions:
    compose_answer(...)  → the analytical answer text
    compose_memo(...)    → the drafting / memo text

Memo contract (hardened after the quality audit):
  • Prayers are CLIENT-ALIGNED only. Never list the opponent's path as
    an احتياطي prayer. The composer uses `DomainRules.primary_prayers`
    (hand-crafted, client-serving) — never derives prayers from the
    opposing hypothesis.
  • Facts section blends `user_facts` (verbatim, first) + domain
    `facts_template` (legal-language frame). No "تُستكمل الوقائع".
  • Legal-basis section expands every `article_refs` entry into its
    FULL text pulled from the DB via `corpus.get_article_text` (falls
    back to short citation on DB miss).
  • Adds a "السوابق القضائية" section populated from the 11k+ Tameez
    rulings in the DB via `corpus.get_rulings(ruling_pattern)`.
  • Banned phrases (legacy v1 + placeholder register) remain banned:
        "لم تتوفر شروط" / "ما يلزم لاستكمال التحليل" /
        "أقصى ما يمكن قوله الآن" / "تعذّر صياغة" /
        "صياغة أولية" / "يُستكمل لاحقاً" / "هيكل قابل للاستكمال" /
        "تُستكمل الوقائع" / "توثيق العناصر".
"""
from __future__ import annotations

import logging
from typing import Optional

from core.runtime_v2.types import (
    DomainRules, DraftingMode, EvidenceItem, PathHypothesis,
    Pivot, ReasoningMode,
)
from core.runtime_v2.corpus import get_article_text, article_summary, get_rulings

log = logging.getLogger(__name__)

# CP1 · Fix 1.A — structured fact extraction (FINDING #13).
# Gates DomainRules.facts_template and path.markers.supporting_facts
# against what the user actually said. See composer._facts_block and
# composer._defenses_block for usage.
try:
    from core.fact_extractor import (
        extract_user_facts_sync as _fe_extract_sync,
        ExtractedFacts as _ExtractedFacts,
    )
    _FACT_EXTRACTOR_AVAILABLE = True
except Exception as _fe_err:  # pragma: no cover
    _FACT_EXTRACTOR_AVAILABLE = False
    _fe_extract_sync = None  # type: ignore
    _ExtractedFacts = None   # type: ignore

# CP3 · Phase 2 — Precedent Linker integration.
# Imported lazily/defensively so a missing module never breaks memo
# composition. Degrades open: precedent_linker unavailable → we fall
# back to the static-bank behavior preserved in compose_memo_v1.
try:
    from core.precedent_linker import (
        Precedent as _Precedent,
        find_relevant_precedents_augmented as _pl_find,
        verify_precedent_references_in_answer as _pl_verify,
    )
    _PRECEDENT_AVAILABLE = True
except Exception as _pl_err:  # pragma: no cover
    _PRECEDENT_AVAILABLE = False
    _Precedent = None  # type: ignore
    _pl_find = None  # type: ignore
    _pl_verify = None  # type: ignore

# Reuse the background async-loop runner from corpus (already proven —
# used by get_rulings / get_article_text). Lets us call the async
# precedent retrieval from this sync compose_memo without making every
# upstream caller async. We ALSO pull corpus._get_pool so the Precedent
# Linker uses the pool that's bound to corpus_bg's loop (app_state.pool
# belongs to FastAPI's main loop — cross-loop pool use crashes asyncpg
# with "cannot perform operation: another operation is in progress").
try:
    from core.runtime_v2.corpus import _bg as _corpus_bg, _get_pool as _corpus_get_pool
except Exception:  # pragma: no cover
    _corpus_bg = None
    _corpus_get_pool = None  # type: ignore


_BISMILLAH = "بسم الله الرحمن الرحيم"
_CLOSING   = "والله ولي التوفيق،،"


# ═════════════════════════════════════════════════════════════════════
# CP1 · Fix 1.A — fact_extractor integration helpers (FINDING #13)
# ═════════════════════════════════════════════════════════════════════
#
# Three helpers live here because both _facts_block and _defenses_block
# need them, and they are ORTHOGONAL to any particular section's logic.
#
# 1. _split_combined_query  — rehydrates handle_memo_smart's " | "-joined
#    combined query back into (current_query, pseudo_history). The
#    extractor prefers structured history over a flat blob.
#
# 2. _marker_aligned_with_user — decides whether a DomainRules FactMarker
#    (template defense element) is actually supported by what the user
#    stated. Used to FILTER path.markers in _defenses_block — the root
#    fix for hallucination Source B (FINDING #13).
#
# 3. _STOP_WORDS — tokens common to many custody/nafaqa markers
#    ("الحاضن", "المحضون", "المدعى عليها", …) whose presence in user
#    text must NOT count as marker alignment. Without this, every
#    marker in a custody case would match on "الحاضن" alone.


_STOP_WORDS: frozenset[str] = frozenset({
    "الزوج", "الزوجة", "الحاضن", "الحاضنة", "المحضون",
    "الطرف", "الطرفين", "المدعي", "المدعى", "عليه", "عليها",
    "بعد", "قبل", "من", "على", "في", "إلى", "مع", "أو",
    "التي", "الذي", "هذا", "هذه", "ذلك", "تلك",
})


def _split_combined_query(query: str) -> tuple[str, list[dict]]:
    """Rehydrate handle_memo_smart's `" | "`-joined combined query.

    ``handle_memo_smart`` (routers/query_router.py) pre-joins the last
    user messages with ``" | "`` so the downstream sync composer still
    sees the full history via a single ``query`` arg. This helper
    reverses that: it splits on the exact separator and returns
    ``(actual_current_query, pseudo_history)`` in the shape
    ``extract_user_facts_sync`` expects.

    Defensive:
      • Returns ``(query, [])`` when no `` | `` separator present.
      • Returns ``(query, [])`` if the final part (intended
        "current query") is < 3 chars — that means the split was
        malformed / not actually a combined query.
      • Never raises.
    """
    if not query or " | " not in query:
        return query, []

    parts = [p.strip() for p in query.split(" | ") if p.strip()]
    if len(parts) < 2:
        return query, []

    actual_query = parts[-1]
    past_parts   = parts[:-1]

    if len(actual_query) < 3:
        return query, []

    pseudo_history = [
        {"role": "user", "content": p} for p in past_parts
    ]
    return actual_query, pseudo_history


_PRAYER_STOP_WORDS: frozenset[str] = frozenset({
    # Procedural verbs common to almost every prayer bullet
    "الحكم", "إلزام", "ضم", "تمكين", "تنظيم", "إسقاط", "تثبيت",
    "بإسقاط", "بإلزام", "بضم", "بتمكين", "بتنظيم", "بتثبيت",
    # Party references (appear in ~every prayer)
    "المدعي", "المدعى", "عليه", "عليها", "بوصفه", "المحضون",
    # Law-citation scaffolding
    "المادة", "القانون", "لسنة", "الأسرة", "المحكمة",
    "بموجب", "بالمصاريف", "المحاماة", "أتعاب", "وفق", "وفقاً",
    # Connectors
    "على", "من", "في", "إلى", "مع", "أو", "عن", "بعد", "قبل",
    # Pronouns / determiners
    "التي", "الذي", "هذا", "هذه", "ذلك", "تلك",
    "الزوج", "الزوجة", "الحاضن", "الحاضنة",
    "الطرف", "الطرفين",
})


# Prayer-level red flags. If a prayer ASSERTS one of these substrings,
# it is auto-rejected regardless of label overlap — these are concrete
# factual claims the prayer can't make without user confirmation.
# Keep this list TIGHT; broad phrases will over-filter legitimate
# prayers. Each entry was observed in h1 forensic probe (Source D)
# as a hallucinated assertion.
_PRAYER_POISON_SIGNALS: tuple[str, ...] = (
    "لزواجها",          # "for her marriage" — asserts marriage happened
    "لتزوجها",          # variant spelling
    "من أجنبي",          # "from a foreigner" — asserts foreign spouse
    "من رجل أجنبي",     # same assertion, fuller form
    "تزوجت المدعى",     # "المدعى عليها has married"
    "تزوجت المدعي",     # same, masculine variant
)


# Phase 7 Stretch — standard substantive prayer shape per domain.
# Used ONLY in the fallback path of _prayers_block (when all domain
# primary_prayers were filtered as poison). The hint is ALWAYS wrapped
# in brackets in the output and qualified with "وفق ما يراه المحامي"
# so the lawyer treats it as a shape suggestion, not an asserted request.
#
# Keys are DomainKey.value strings (stable programmatic identifiers,
# NOT display names which are long Arabic phrases). Only domains with
# a clear canonical prayer shape are listed. Missing domains fall
# through to a generic "[يُدرج الطلب الأساسي...]" placeholder.
_PRAYER_DOMAIN_HINTS: dict[str, str] = {
    "family_custody":
        "إسقاط الحضانة عن المُدَّعى عليها وضم المحضون إلى المُدَّعي",
    "family_nafaqa":
        "إلزام المُدَّعى عليه بأداء النفقة الواجبة",
    "divorce_for_harm":
        "التطليق للضرر",
    "unlawful_termination":
        "إلغاء قرار الفصل والتعويض عن الأضرار المادية والمعنوية",
    "bad_check":
        "إدانة المُدَّعى عليه وإلزامه بأداء قيمة الشيك والتعويض",
    "defamation":
        "إدانة المُدَّعى عليه والتعويض عن الضرر الأدبي",
    "theft":
        "إدانة المُدَّعى عليه بالعقوبة المقررة قانوناً",
    "fraud":
        "إدانة المُدَّعى عليه ورد ما استولى عليه والتعويض",
    "fraud_embezzlement":
        "إدانة المُدَّعى عليه ورد المبلغ المختلس والتعويض",
    "blackmail_threat":
        "إدانة المُدَّعى عليه بالعقوبة المقررة قانوناً والتعويض",
    "assault":
        "إدانة المُدَّعى عليه بالعقوبة المقررة قانوناً والتعويض عن الإصابات",
    "forgery":
        "إدانة المُدَّعى عليه والحكم ببطلان المحرر المزور",
    "cyber_crime":
        "إدانة المُدَّعى عليه بالعقوبة المقررة قانوناً",
    "rental":
        "إخلاء العين المؤجرة وإلزام المُدَّعى عليه بالمتأخرات",
}


def _prayer_aligned_with_user(prayer: str, user_text: str) -> bool:
    """Decide whether a ``primary_prayers`` template entry is safe
    to include given the user's stated facts.

    Rules (applied in order):
      1. Auto-reject if the prayer contains any ``_PRAYER_POISON_SIGNALS``
         substring — those are concrete factual assertions we cannot
         justify without user confirmation.
      2. Extract "significant" words from the prayer (len >= 4, NOT
         in ``_PRAYER_STOP_WORDS``). If NONE exist → treat as generic
         procedural prayer (e.g. "الحكم بقبول الدعوى"), ALLOW it.
      3. Otherwise require at least ONE significant word to appear in
         ``user_text``. If yes → aligned. If no → reject.

    More permissive than ``_marker_aligned_with_user`` — prayers are
    procedural requests, so generic-procedural is fine to pass
    through. The signal list is the hard gate.
    """
    if not prayer:
        return False

    prayer_lower = prayer.lower()

    # Rule 1: hard reject on POISON_SIGNALS
    for poison in _PRAYER_POISON_SIGNALS:
        if poison in prayer_lower:
            return False

    # Rule 2: significant words — strip punctuation, length/stop filter
    prayer_words = [
        w.strip("،.()[]،؛:")
        for w in prayer.split()
    ]
    prayer_words = [
        w for w in prayer_words
        if len(w) >= 4 and w not in _PRAYER_STOP_WORDS
    ]

    # Generic procedural — no significant words → allow
    if not prayer_words:
        return True

    # Rule 3: require at least one significant word in user_text
    for word in prayer_words:
        if word in user_text:
            return True

    return False


def _marker_aligned_with_user(marker, user_text: str) -> bool:
    """Check whether a ``FactMarker`` is supported by user's stated text.

    Matching precedence:
      1. ``marker.keywords`` — most reliable. ANY keyword present in
         ``user_text`` → aligned.
      2. Fallback: split ``marker.label``, keep significant words
         (len >= 4, not in ``_STOP_WORDS``). ANY such word in
         ``user_text`` → aligned.

    Conservative — requires at least one match. Empty marker → False.
    """
    kws = getattr(marker, "keywords", None) or ()
    for kw in kws:
        if kw and kw.lower() in user_text:
            return True

    label = getattr(marker, "label", "") or ""
    if not label:
        return False

    label_words = [
        w for w in label.split()
        if len(w) >= 4 and w not in _STOP_WORDS
    ]
    for word in label_words:
        if word in user_text:
            return True

    return False


def _extract_for_composer(query: Optional[str]):
    """Small internal wrapper — runs fact_extractor on a composer-style
    query (may be pipe-joined combined query), handling all error paths.

    Returns an ``ExtractedFacts`` (possibly empty). NEVER raises.
    """
    if not query or not _FACT_EXTRACTOR_AVAILABLE or _fe_extract_sync is None:
        # Return a safe empty stand-in. Even if ExtractedFacts class
        # is unavailable (dependency missing), the callers only check
        # .is_empty() and iterate a few fields — None is handled.
        return _ExtractedFacts() if _ExtractedFacts is not None else None

    try:
        actual_query, pseudo_history = _split_combined_query(query)
        result = _fe_extract_sync(
            query=actual_query,
            history=pseudo_history if pseudo_history else None,
            use_cache=True,
        )
        return result
    except Exception as e:
        log.warning("composer: fact_extractor sync failed: %s", e)
        return _ExtractedFacts() if _ExtractedFacts is not None else None


# ═════════════════════════════════════════════════════════════════════
# Analytical answer (unchanged)
# ═════════════════════════════════════════════════════════════════════

def compose_answer(
    *,
    domain_display: str,
    reasoning_mode: ReasoningMode,
    paths:          list[PathHypothesis],
    pivots:         list[Pivot],
    evidence:       list[EvidenceItem],
    established:    list[str],
    missing:        list[str],
) -> str:
    """Emit the ONE analytical answer text for the given reasoning mode."""
    out: list[str] = []
    out.append(f"**المسألة محل النظر:** {domain_display}")

    if reasoning_mode == ReasoningMode.SKELETON:
        out.append("")
        out.append("**البناء المبدئي للمسألة:**")
        if missing:
            out.append("")
            out.append("**عناصر يُستحسن توثيقها لترجيح مسار على آخر:**")
            for f in missing[:6]:
                out.append(f"• {f}")
        if evidence:
            out.append("")
            out.append("**الإطار القانوني العام:**")
            for e in evidence[:3]:
                out.append(f"• {e.citation} — {e.summary}")
        return "\n".join(out).strip()

    if reasoning_mode == ReasoningMode.SINGLE_PATH:
        top = paths[0]
        out.append("")
        out.append(f"**التكييف المرجَّح:** {top.label} "
                    f"(وزن {int(top.weight * 100)}%).")
        out.append("")
        out.append("**الأسانيد:**")
        for a in top.articles:
            out.append(f"• {a}")
        if established:
            out.append("")
            out.append("**العناصر الثابتة من العرض تدعم هذا التكييف:**")
            for f in established[:6]:
                out.append(f"• {f}")
        if missing:
            out.append("")
            out.append("**عناصر لو تحققت تُعزّز الترجيح:**")
            for f in missing[:4]:
                out.append(f"• {f}")

    elif reasoning_mode == ReasoningMode.MULTI_PATH:
        out.append("")
        out.append("**المسارات القانونية المحتملة بحسب الوقائع المطروحة:**")
        for i, p in enumerate(paths, 1):
            out.append("")
            out.append(f"**{i}. {p.label}** — وزن تقديري "
                        f"{int(p.weight * 100)}%")
            for a in p.articles[:2]:
                out.append(f"• {a}")
        if pivots:
            out.append("")
            out.append("**ما قد يرجّح مسارًا على آخر:**")
            for i, piv in enumerate(pivots[:3], 1):
                out.append(f"{i}. {piv.question}")

    elif reasoning_mode == ReasoningMode.CONDITIONAL:
        out.append("")
        out.append("**التكييف مشروط بعناصر فاصلة — يختلف المسار بحسب "
                    "الإجابة عليها:**")
        for i, p in enumerate(paths, 1):
            out.append("")
            out.append(f"**المسار ({i}): {p.label}** — وزن تقديري "
                        f"{int(p.weight * 100)}%")
            for a in p.articles[:2]:
                out.append(f"• {a}")
        if pivots:
            out.append("")
            out.append("**الأسئلة الحاسمة التي تُرجّح مسارًا على آخر:**")
            for i, piv in enumerate(pivots[:4], 1):
                out.append(
                    f"{i}. {piv.question}  "
                    f"(إذا تحققت ← يُرجَّح «{piv.if_yes_path}»؛ "
                    f"وإلا يُرجَّح «{piv.if_no_path}»)."
                )

    if evidence:
        out.append("")
        out.append("**السند القانوني:**")
        for e in evidence[:3]:
            out.append(f"• {e.citation}")

    if established:
        out.append("")
        out.append(
            "**العناصر الثابتة من العرض:** "
            + "، ".join(established[:5])
        )

    return "\n".join(out).strip()


# ═════════════════════════════════════════════════════════════════════
# Memo — Qatari-form legal document
# ═════════════════════════════════════════════════════════════════════

_MEMO_TITLE = {
    DraftingMode.SINGLE_DRAFT:      "مذكرة قانونية",
    DraftingMode.CONDITIONAL_DRAFT: "مذكرة قانونية بطلبات أصلية واحتياطية",
    DraftingMode.DUAL_DRAFT:        "مذكرة قانونية بطلبات مزدوجة",
    DraftingMode.SKELETON_DRAFT:    "مذكرة قانونية بطلبات أصلية واحتياطية",
}


def _memo_header(
    domain_display: str,
    drafting_mode:  DraftingMode,
    client_role:    str,
) -> list[str]:
    title = _MEMO_TITLE.get(drafting_mode, "مذكرة قانونية")
    lines: list[str] = [
        _BISMILLAH,
        "",
        f"**{title}**",
        "",
        "السادة / قضاة المحكمة الموقّرة",
        "تحية طيبة وبعد،",
        "",
        f"**الموضوع:** {domain_display}.",
    ]
    if client_role:
        lines += ["", f"**صفة مقدم المذكرة:** {client_role}."]
    lines.append("")
    return lines


def _facts_block(
    user_facts:     list[str] | None,
    established:    list[str],
    facts_template: tuple[str, ...],
    query:          str | None = None,  # NEW — CP1 · Fix 1.A
) -> list[str]:
    """Build 'أولاً: الوقائع' — FINDING #13 Source A fix.

    Priority order for fact lines (ONE layer wins, no mixing):
      A. If ``query`` provided AND fact_extractor finds non-empty user
         claims → use ONLY those. facts_template is NOT emitted
         (otherwise domain templates contaminate user facts — that was
         the h1 / real-user regression).
      B. Legacy fallback: if ``user_facts`` list was passed in by a
         caller that doesn't yet supply ``query``, honor it as before.
      C. Neither A nor B → emit facts_template entries as explicit
         bracketed placeholders. The user then visually sees they need
         to fill each slot — never as invented assertions.

    ``established`` (domain-derived system markers, NOT user claims) is
    always appended at the end — it's not a hallucination risk.
    """
    out = ["**أولاً: الوقائع**"]

    extracted = _extract_for_composer(query)
    # A1: gate on `facts_lines` instead of `is_empty()`. The extractor
    # may return amounts/requests without claims — in that case
    # `is_empty()` is False but `as_facts_lines()` is []. Using
    # `facts_lines` as the gate guarantees Path A only fires when it
    # actually has content to render, letting Path B / C handle the
    # "claims empty" cases that previously fell into the structural
    # safety-net bullet alone.
    facts_lines = extracted.as_facts_lines() if extracted is not None else []

    # ── Path A: extractor produced concrete claims ─────────────
    if facts_lines:
        for claim in facts_lines:
            out.append(f"• أفاد المُستشير بأن: «{claim}».")

        # Gap 1 (Phase 6) — surface structured fields (names, ages,
        # amounts, dates) that the extractor captured but `claims`
        # missed. The LLM often condenses multi-item user input into
        # 2-3 claim sentences and drops specifics into structured
        # fields. Without this block those specifics never reach the
        # memo. Emitted as labelled bullets so they read naturally
        # alongside the narrative claims.
        enrichment_lines: list[str] = []
        if extracted is not None:
            if extracted.names:
                enrichment_lines.append(
                    "الأطراف المذكورون: "
                    + "، ".join(extracted.names[:3])
                )
            if extracted.ages:
                enrichment_lines.append(
                    "الأعمار المذكورة: "
                    + "، ".join(extracted.ages[:3])
                )
            if extracted.amounts:
                enrichment_lines.append(
                    "المبالغ المذكورة: "
                    + "، ".join(extracted.amounts[:3])
                )
            if extracted.dates:
                enrichment_lines.append(
                    "التواريخ المذكورة: "
                    + "، ".join(extracted.dates[:3])
                )
        for e in enrichment_lines:
            out.append(f"• {e}.")

        # A2: explicit placeholder bullet so the user sees that any
        # unstated details (dates/names/documents) are intentionally
        # left open. Without this, Path A skips facts_template entirely
        # and the memo loses the "still-missing" visual signal.
        out.append(
            "• [يُدرج ما لم يذكره الموكل من تفاصيل إضافية "
            "كالأسماء الكاملة والتواريخ الدقيقة والمستندات الداعمة]."
        )
    # ── Path B: legacy user_facts — no extractor data available ───
    elif user_facts:
        u = [f.strip() for f in user_facts if f and len(f.strip()) >= 4]
        for f in u[:4]:
            out.append(f"• أفاد المُستشير بأن: «{f}».")
        # Mirror of Path A's guidance placeholder — same rationale:
        # the user sees that unstated details are intentionally open.
        out.append(
            "• [يُدرج ما لم يذكره الموكل من تفاصيل إضافية "
            "كالأسماء الكاملة والتواريخ الدقيقة والمستندات الداعمة]."
        )
    # ── Path C: nothing from user — template items as placeholders ─
    else:
        for t in facts_template[:4]:
            out.append(f"• [{t}]")

    # Established markers (system-derived, safe) — always appended.
    # De-dupe against anything already rendered as a user claim.
    rendered = " ".join(out)
    for m in (established or [])[:3]:
        m_clean = (m or "").strip()
        if m_clean and m_clean not in rendered:
            out.append(f"• {m_clean}.")

    # Structural safety: never return an empty الوقائع section.
    if len(out) == 1:
        out.append(
            "• تقدّم المستندات المؤيدة للوقائع عند جلسة المرافعة "
            "وفق ما يُثبته سجل الدعوى."
        )
    out.append("")
    return out


def _strip_article_metadata(text: str) -> str:
    """Remove DB-layer metadata that leaks into article citations.

    The DB stores article text prefixed with a row-metadata marker
    ``"تاريخ بدء العمل : DD/MM/YYYY"`` — a legitimate column in the
    source table but never something a legal memo should display.
    Without this strip the memo renders e.g.
    ``«المادة 168 تاريخ بدء العمل : 28/08/2006 ...»``.

    Fix 1.D — Qatar CP1 commit #2. Conservative regex: only the
    exact DB marker pattern is stripped. Legal content is preserved.

    Known patterns (extend as discovered):
      • "تاريخ بدء العمل : DD/MM/YYYY"  (common form)
      • "تاريخ بدء العمل: DD/MM/YYYY"   (no space before colon)
    """
    import re
    if not text:
        return text
    cleaned = re.sub(
        r"\s*تاريخ\s+بدء\s+العمل\s*:\s*\d{1,2}/\d{1,2}/\d{4}\s*",
        " ",
        text,
    )
    # Collapse multiple spaces introduced by the substitution
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _legal_basis_block(
    domain: Optional[DomainRules],
    paths:  list[PathHypothesis],
    evidence: list[EvidenceItem],
) -> list[str]:
    """الأسانيد القانونية — expand article_refs into FULL article
    texts via corpus.get_article_text. Fall back to short citations
    on DB miss.

    CP1 Fix 1.D: each DB excerpt passes through
    ``_strip_article_metadata`` before being wrapped in quotes so
    that row-metadata ("تاريخ بدء العمل : DD/MM/YYYY") never appears
    inside the legal citation.
    """
    out: list[str] = ["**ثالثاً: الأسانيد القانونية**"]

    # 1) Expanded article texts from DB (if domain provides refs)
    refs = (domain.article_refs or ()) if domain else ()
    expanded = 0
    for art_num, law_pat in refs:
        excerpt = article_summary(law_pat, art_num, max_chars=250)
        if excerpt:
            excerpt = _strip_article_metadata(excerpt)  # Fix 1.D
            out.append(f"• **المادة ({art_num})** — والتي تنص على:")
            out.append(f"  «{excerpt}»")
            expanded += 1
    # 2) Short citations for path articles (always include — as a
    #    consolidated list even when DB expansion succeeded)
    if paths and paths[0].articles:
        out.append("• الأسانيد المؤيّدة:")
        for a in paths[0].articles[:3]:
            out.append(f"  — {a}.")
    # 3) Evidence bank (concise)
    if evidence:
        out.append("• المراجع القانونية العامة:")
        for e in evidence[:3]:
            out.append(f"  — {e.citation}.")
    if expanded == 0 and not paths and not evidence:
        # Degrade gracefully, still not a placeholder
        out.append(
            "• النصوص القانونية المنطبقة وفق ما يستقر عليه التحقيق "
            "أمام المحكمة الموقّرة."
        )
    out.append("")
    return out


def _rulings_block(domain: Optional[DomainRules]) -> list[str]:
    """السوابق القضائية — pull 1-2 Tameez rulings via corpus (LEGACY /
    static-bank path). Kept unchanged: compose_memo_v1 still uses it
    exactly as-is, and the new compose_memo falls back to it when the
    Precedent Linker is unavailable."""
    if not domain or not domain.ruling_pattern:
        return []
    rulings = get_rulings(domain.ruling_pattern, limit=2) or ()
    if not rulings:
        return []
    out = ["**رابعاً: السوابق القضائية ذات الصلة**"]
    for i, txt in enumerate(rulings, 1):
        snippet = " ".join(txt.split())[:420]
        out.append(f"• حكم تمييز ({i}): «{snippet}…»")
    out.append("")
    return out


# ═════════════════════════════════════════════════════════════════════
# CP3 — Precedent Linker rulings block (replaces static bank)
# ═════════════════════════════════════════════════════════════════════

_RULINGS_FALLBACK_TEXT = (
    "لم يُعثر على أحكام تمييز ذات صلة مباشرة بهذه القضية في قاعدة "
    "البيانات. تُستكمل السوابق القضائية يدوياً عند المرافعة إن لزم."
)


async def _run_linker_with_corpus_pool(
    query: str,
    corpus_domain: Optional[str],
    concepts: Optional[list[str]],
):
    """Runs on corpus_bg's loop. Acquires the pool that ALSO lives on
    that loop (via corpus._get_pool), then passes it explicitly to
    find_relevant_precedents_augmented so the linker never accidentally
    reaches for app_state.pool (which belongs to FastAPI's loop).

    CP3.3: passes phase0_class="memo" so the short-query skip-gate
    NEVER fires for a memo — memos always deserve precedents even
    when the user's query is short (e.g. "اكتب مذكرة سرقة")."""
    pool = None
    if _corpus_get_pool is not None:
        try:
            pool = await _corpus_get_pool()
        except Exception:
            pool = None
    if _pl_find is None:
        return []
    return await _pl_find(
        query=query,
        corpus_domain=corpus_domain,
        concepts=concepts or [],
        pool=pool,
        phase0_class="memo",  # memo context: disables the skip gate
    )


def _precedents_via_linker(
    query: Optional[str],
    corpus_domain: Optional[str],
    concepts: Optional[list[str]],
) -> list:
    """Sync wrapper around find_relevant_precedents_augmented. Uses the
    corpus module's background loop thread (same pattern as get_rulings).
    Returns [] on any failure (linker unavailable, DB down, etc.)."""
    if not _PRECEDENT_AVAILABLE or _pl_find is None or _corpus_bg is None:
        return []
    if not query:
        return []
    try:
        return _corpus_bg.run(
            _run_linker_with_corpus_pool(query, corpus_domain, concepts)
        ) or []
    except Exception:
        return []


def _rulings_block_from_precedents(
    precedents: list,
) -> list[str]:
    """Build the السوابق القضائية section from a Precedent list.
    Unlike the legacy static-bank version, this ALWAYS emits the section
    header — when `precedents` is empty we emit an honest fallback line
    instead of hiding the section, as requested in CP3 spec."""
    out: list[str] = ["**رابعاً: السوابق القضائية ذات الصلة**"]
    if not precedents:
        out.append(f"• {_RULINGS_FALLBACK_TEXT}")
        out.append("")
        return out
    for i, p in enumerate(precedents, 1):
        # Prefer the structured display_ref (case number when we have
        # one, else "مبدأ مستقر لمحكمة التمييز ({domain})" fallback).
        ref = getattr(p, "display_ref", "") or "حكم تمييز"
        snippet = " ".join((getattr(p, "content", "") or "").split())[:420]
        dom = getattr(p, "domain", "") or ""
        sim = getattr(p, "similarity_boosted", 0.0) or 0.0
        header = f"• [{ref}] (مجال: {dom}، تشابه: {sim:.2f})"
        out.append(header)
        if snippet:
            out.append(f"   «{snippet}…»")
    out.append("")
    return out


def _defenses_block(
    domain: Optional[DomainRules],
    paths:  list[PathHypothesis],
    query:  str | None = None,  # NEW — CP1 · Fix 1.A
) -> list[str]:
    """Build 'ثانياً: الدفوع' — FINDING #13 Source B fix.

    Historically this emitted ALL ``path.markers`` (via
    ``supporting_facts``) verbatim as defense elements — regardless
    of whether the user's facts supported them. That leaked template
    claims like ``«زواج الأم الحاضنة بعد الطلاق»`` into custody
    memos whose user had only said "سوء سلوك".

    New behavior:
      • If fact_extractor produced non-empty claims, keep ONLY
        markers that align with them (``_marker_aligned_with_user``).
      • If no markers align, fall back to building defenses directly
        from the user's own claims (no template injection).
      • If the extractor returned empty (no query, no facts), emit
        the markers as bracketed placeholders so the user sees them
        as "fill-in" rather than stated facts.
    """
    out = ["**ثانياً: الدفوع والأسانيد الموضوعية**"]

    if not paths:
        out.append("• [تُحرَّر الدفوع بناءً على ما يُفيده الموكل].")
        out.append("")
        return out

    top_path = paths[0]
    all_markers = top_path.markers or ()

    extracted = _extract_for_composer(query)

    # No user signal → markers as explicit placeholders
    if extracted is None or extracted.is_empty():
        for marker in all_markers[:4]:
            out.append(f"• [عنصر محتمل: {marker.label}]")
        out.append("")
        return out

    # Build a normalised user_text blob for marker matching
    user_text_parts: list[str] = []
    user_text_parts.extend(extracted.claims)
    user_text_parts.extend(extracted.requests)
    user_text = " ".join(user_text_parts).lower()

    aligned = [
        m for m in all_markers
        if _marker_aligned_with_user(m, user_text)
    ]

    # Phase 7 Stretch — 3-layer defenses for substantive but clean
    # output. Single-layer output (post-Fix-1.A markers-only) left
    # custody memos with 1 bullet when all markers were poison-filtered.
    #
    #   Layer 1 — aligned markers (domain legal elements, filtered)
    #   Layer 2 — user claims as defensive statements (ALWAYS added)
    #   Layer 3 — generic legal defenses (ONLY when Layer 1 empty)
    #
    # Layer 3 stays off when Layer 1 has content to avoid noise —
    # aligned legal elements are already carrying the legal weight.
    # Layer 2 runs alongside either — facts + law is richer than
    # either alone, and never invents.

    # Layer 1
    if aligned:
        for marker in aligned[:4]:
            out.append(f"• يُتمسّك بتحقق عنصر «{marker.label}».")

    # Layer 2 — user claims (always, even alongside markers)
    for claim in extracted.claims[:3]:
        c = (claim or "").strip()
        if len(c) >= 8:
            out.append(f"• يُتمسّك بما أفاد به المُستشير: «{c}».")

    # Layer 3 — generic legal defenses (only when Layer 1 empty)
    if not aligned:
        domain_display = (
            getattr(domain, "display_name", "") or "الدعوى"
        )
        out.append(
            f"• يُتمسّك بما تقرّره نصوص قانون {domain_display} "
            f"المنطبقة على الوقائع المذكورة."
        )
        out.append(
            "• يُتمسّك بأن مصلحة [المحضون/المدعي/المُوكّل] "
            "هي المعيار الحاكم في الفصل."
        )

    # Structural safety: don't return a header-only block.
    if len(out) == 1:
        out.append("• [تُحرَّر الدفوع بناءً على ما يُفيده الموكل].")

    out.append("")
    return out


def _prayers_block(
    domain: Optional[DomainRules],
    query:  str | None = None,  # CP1 · Fix 1.A — FINDING #13 Source D
) -> list[str]:
    """Build 'خامساً: الطلبات' — FINDING #13 Source D fix.

    Historically this emitted ``domain.primary_prayers`` verbatim. That
    leaked template-level factual assertions into the prayers section
    (e.g. ``"الحكم بإسقاط حضانتها لزواجها من رجل أجنبي عن المحضون"``)
    even when the user's actual ground was unrelated (e.g. سوء سلوك).

    New behavior:
      • If ``query`` provided AND fact_extractor finds user facts →
        filter prayers via ``_prayer_aligned_with_user``. Aligned
        prayers are emitted verbatim. If none align, fall back to
        ``extracted.requests`` if any, else a generic placeholder.
      • If the extractor returned empty (no query or no user signal)
        → emit prayers as explicit ``[طلب محتمل: ...]`` placeholders
        so the user sees them as "fill-in" rather than made requests.
      • Missing / empty ``primary_prayers`` → the existing safe
        default prayer pair (bottom of function) still applies.
    """
    default_prayers: tuple[str, ...] = (
        "الحكم بما يقتضيه القانون بناءً على ما ثبت من وقائع ومستندات.",
        "إلزام الخصم بالمصاريف ومقابل أتعاب المحاماة.",
    )

    prayers: tuple[str, ...] = tuple()
    if domain and domain.primary_prayers:
        prayers = domain.primary_prayers
    if not prayers:
        prayers = default_prayers

    out = ["**خامساً: الطلبات**"]

    extracted = _extract_for_composer(query)

    # No user facts — prayers as explicit placeholders.
    if extracted is None or extracted.is_empty():
        for i, p in enumerate(prayers[:5], 1):
            out.append(f"{i}. [طلب محتمل: {p}]")
        out.append("")
        out.append(_CLOSING)
        return out

    # Build user_text blob for prayer alignment
    user_text_parts: list[str] = []
    user_text_parts.extend(extracted.claims)
    user_text_parts.extend(extracted.requests)
    user_text = " ".join(user_text_parts).lower()

    aligned = [p for p in prayers if _prayer_aligned_with_user(p, user_text)]

    if aligned:
        for i, p in enumerate(aligned[:5], 1):
            out.append(f"{i}. {p}.")
    else:
        # Phase 6 Gap 2 — NEVER echo user's meta-request ("اكتب مذكرة")
        # as a legal prayer. Historically the fallback used
        # ``extracted.requests`` verbatim, which produced quality
        # defects like ``1. اكتب مذكرة اسقاط حضانه ضد طليقتي`` in
        # the Prayers section.
        #
        # Phase 7 Stretch — when the filter rejected every domain
        # prayer, we still emit a generic 3-part legal scaffold BUT
        # the substantive slot (#2) is filled with a domain-specific
        # hint when available. The hint is WRAPPED IN BRACKETS and
        # the "وفق ما يراه المحامي" postscript keeps it a suggestion,
        # not a certainty. No facts asserted — only the standard
        # prayer shape for the registered domain.
        domain_label = (
            getattr(domain, "display_name", "")
            or "القضية"
        )
        # Key by DomainKey.value (stable, programmatic).
        domain_key_val = ""
        if domain is not None:
            _k = getattr(domain, "key", None)
            if _k is not None:
                domain_key_val = getattr(_k, "value", "") or str(_k)
        domain_hint = _PRAYER_DOMAIN_HINTS.get(domain_key_val, "")

        out.append("1. الحكم بقبول الدعوى شكلاً وموضوعاً.")
        if domain_hint:
            out.append(
                f"2. الحكم بـ[{domain_hint} وفق ما يراه المحامي "
                f"المتابع للقضية بناءً على الوقائع المذكورة]."
            )
        else:
            out.append(
                f"2. [يُدرج الطلب الأساسي في {domain_label} بناءً على "
                f"الوقائع المذكورة وما يراه المحامي المتابع للقضية]."
            )
        out.append(
            "3. إلزام المُدَّعى عليها بالمصاريف ومقابل أتعاب المحاماة."
        )

    out.append("")
    out.append(_CLOSING)
    return out


# ═════════════════════════════════════════════════════════════════════
# Public memo builder
# ═════════════════════════════════════════════════════════════════════

def compose_memo_v1(
    *,
    domain_display: str,
    drafting_mode:  DraftingMode,
    paths:          list[PathHypothesis],
    pivots:         list[Pivot],
    evidence:       list[EvidenceItem],
    established:    list[str],
    missing:        list[str],
    user_facts:     list[str] | None = None,
    domain:         Optional[DomainRules] = None,
) -> str:
    """Backup pre-Phase2 — rollback target only. DO NOT call in production.

    Exact behavioural snapshot of the composer as it existed before the
    Precedent Linker integration (CP3). Uses the static `get_rulings()`
    bank for the السوابق section. Kept as a safety net so we can
    side-by-side compare outputs if a regression surfaces without having
    to check out the pre-CP3 commit.
    """
    client_role = (domain.client_role if domain else "") or ""
    facts_template = (
        (domain.facts_template if domain else ()) or ()
    )

    out: list[str] = []
    out.extend(_memo_header(domain_display, drafting_mode, client_role))
    out.extend(_facts_block(user_facts, established, facts_template))
    out.extend(_defenses_block(domain, paths))
    out.extend(_legal_basis_block(domain, paths, evidence))
    out.extend(_rulings_block(domain))  # legacy static bank
    out.extend(_prayers_block(domain))

    return "\n".join(out).strip()


def compose_memo(
    *,
    domain_display: str,
    drafting_mode:  DraftingMode,
    paths:          list[PathHypothesis],
    pivots:         list[Pivot],
    evidence:       list[EvidenceItem],
    established:    list[str],
    missing:        list[str],
    user_facts:     list[str] | None = None,
    domain:         Optional[DomainRules] = None,
    # ─── CP3 · Phase 2 Layer 2 additions (all optional for back-compat) ───
    query:          Optional[str] = None,
    corpus_domain:  Optional[str] = None,
    concepts:       Optional[list[str]] = None,
    precedents:     Optional[list] = None,  # caller-supplied override
) -> str:
    """Emit the Qatari-form memo for the given drafting mode.

    Client-aligned structure (fixed across modes):
      بسم الله → court addressing → subject → (client role) →
      أولاً: الوقائع          (user facts + legal-language frame)
      ثانياً: الدفوع الموضوعية (paths[0] markers — client side only)
      ثالثاً: الأسانيد القانونية (full article texts from DB)
      رابعاً: السوابق القضائية (Precedent Linker — CP3)
      خامساً: الطلبات          (domain.primary_prayers — client-aligned)
      الختام: والله ولي التوفيق

    CP3 changes (non-breaking):
      • The السوابق section now comes from find_relevant_precedents_augmented
        (real Tamyeez retrieval against the 11.4k rulings), not the
        domain.ruling_pattern static bank.
      • If no precedents are found → honest fallback line, NOT a hidden
        section.
      • After assembly, verify_precedent_references_in_answer scrubs any
        case-number hallucinated into the body (defensive second pass —
        primary defense is that the body rarely cites case numbers since
        only the السوابق section does).
      • All new parameters are optional; passing only the legacy args
        reproduces v1 behavior via the compose_memo_v1 fallback path
        (when Precedent Linker is unavailable).
    """
    client_role = (domain.client_role if domain else "") or ""
    facts_template = (
        (domain.facts_template if domain else ()) or ()
    )

    # ─── Retrieve precedents (CP3) ─────────────────────────────────────
    # Priority: caller-supplied > linker retrieval > empty → fallback line.
    precs: list = []
    if precedents is not None:
        precs = list(precedents)
    elif _PRECEDENT_AVAILABLE and query:
        precs = _precedents_via_linker(
            query=query, corpus_domain=corpus_domain, concepts=concepts,
        )

    # ═══════════════════════════════════════════════════════════════
    # CP6 — Legal Reasoning Engine (primary path)
    # ─────────────────────────────────────────────────────────────────
    # Before falling through to the deterministic template assembler,
    # try to produce a lawyer-composed memo via the reasoning engine.
    # The engine:
    #   1. Characterizes the specific legal ground from user facts.
    #   2. Selects 2-4 articles (out of all domain.article_refs) that
    #      actually support THAT ground.
    #   3. Reranks precedents by LLM-scored ground match.
    #   4. Composes a prose memo via a lawyer-prompt LLM.
    #   5. Verifies grounding programmatically.
    # On success → return the engine's memo.
    # On any failure → fall through to the deterministic path below,
    # which remains a reliable safety net.
    # ═══════════════════════════════════════════════════════════════
    try:
        from core.legal_reasoning_engine import compose_reasoned_memo_sync
        from core.fact_extractor import extract_user_facts_sync
        _ENGINE_AVAILABLE = True
    except Exception:
        _ENGINE_AVAILABLE = False
        compose_reasoned_memo_sync = None  # type: ignore
        extract_user_facts_sync = None  # type: ignore

    if _ENGINE_AVAILABLE and query:
        try:
            # 1) Get grounded facts via fact_extractor (same source as
            #    _facts_block uses internally — but we need the full
            #    ExtractedFacts dict, not just claims-as-bullets).
            actual_q, pseudo_hist = _split_combined_query(query)
            extracted = extract_user_facts_sync(
                query=actual_q,
                history=pseudo_hist if pseudo_hist else None,
                use_cache=True,
            )
            facts_list = list((user_facts or []))
            if extracted is not None:
                # Merge extracted claims into user_facts (dedupe).
                for c in extracted.claims:
                    if c and c.strip() and c not in facts_list:
                        facts_list.append(c.strip())

            # 2) Build candidate articles with text (fetched from DB).
            candidate_articles = []
            refs = (domain.article_refs or ()) if domain else ()
            for art_num, law_pat in refs:
                text = article_summary(law_pat, art_num, max_chars=250) or ""
                text = _strip_article_metadata(text)
                candidate_articles.append({
                    "number":   str(art_num),
                    "law_name": str(law_pat).replace("%", "").strip() or "قانون قطري",
                    "text":     text,
                })

            # 3) Candidate precedents — from `precs`.
            candidate_precedents = []
            for p in precs or []:
                candidate_precedents.append({
                    "display_ref": getattr(p, "display_ref", "") or "",
                    "content":     getattr(p, "content", "") or "",
                    "domain":      getattr(p, "domain", "") or "",
                    "score":       float(getattr(p, "similarity_boosted", 0.0) or 0.0),
                })

            # 4) Determine domain_key programmatic value
            domain_key_val = ""
            if domain is not None:
                _k = getattr(domain, "key", None)
                if _k is not None:
                    domain_key_val = getattr(_k, "value", "") or str(_k)

            # 5) Drafting mode display label
            drafting_mode_label = _MEMO_TITLE.get(drafting_mode, "مذكرة قانونية")

            # 6) Invoke the engine (sync wrapper runs through _corpus_bg)
            ext_dict = extracted.to_dict() if extracted is not None else {
                "names": [], "dates": [], "amounts": [], "ages": [],
                "claims": [], "requests": [],
            }
            engine_result = compose_reasoned_memo_sync(
                query                 = actual_q,
                user_facts            = facts_list,
                extracted_facts_dict  = ext_dict,
                domain_display        = domain_display,
                domain_key            = domain_key_val,
                candidate_articles    = candidate_articles,
                candidate_precedents  = candidate_precedents,
                drafting_mode_label   = drafting_mode_label,
                client_role           = client_role,
            )

            if (
                engine_result is not None
                and engine_result.used_engine
                and engine_result.memo_text
                and len(engine_result.memo_text) >= 500
            ):
                memo_text = engine_result.memo_text
                log.info(
                    "compose_memo: engine succeeded (len=%d, articles=%d, "
                    "precs=%d, %.1fs, grounded=%s)",
                    len(memo_text),
                    len(engine_result.selected_articles),
                    len(engine_result.selected_precedents),
                    engine_result.elapsed_seconds,
                    engine_result.verification.passed,
                )
                # Apply existing hallucination guard on case-number refs
                if _PRECEDENT_AVAILABLE and _pl_verify is not None:
                    try:
                        memo_text, _halluc = _pl_verify(memo_text, precs)
                    except Exception:
                        pass
                return memo_text
            else:
                reason = (
                    engine_result.failure_reason
                    if engine_result is not None
                    else "engine returned None"
                )
                log.info("compose_memo: engine fallback — %s", reason)
        except Exception as _engine_err:
            log.warning("compose_memo: engine error → fallback: %s", _engine_err)
        # Fall through to deterministic path below.

    # ═══════════════════════════════════════════════════════════════
    # DETERMINISTIC FALLBACK (pre-CP6 behaviour)
    # ═══════════════════════════════════════════════════════════════
    out: list[str] = []
    out.extend(_memo_header(domain_display, drafting_mode, client_role))
    # CP1 · Fix 1.A — pass ``query`` so _facts_block / _defenses_block
    # can run the fact_extractor and gate DomainRules templates against
    # user-stated content. ``query`` is already a compose_memo arg
    # (passed by pipeline.answer / _build_generic_skeleton), so no
    # upstream signature churn is required.
    out.extend(_facts_block(user_facts, established, facts_template, query=query))
    out.extend(_defenses_block(domain, paths, query=query))
    out.extend(_legal_basis_block(domain, paths, evidence))

    # Rulings section: new linker-driven path. When the Precedent Linker
    # is disabled/unavailable AND the caller did not supply precedents,
    # degrade to the legacy static-bank block (compose_memo_v1 behavior).
    if _PRECEDENT_AVAILABLE and (precs or query or precedents is not None):
        out.extend(_rulings_block_from_precedents(precs))
    else:
        out.extend(_rulings_block(domain))

    # CP1 · Fix 1.A Source D — prayers gated against user-stated facts.
    out.extend(_prayers_block(domain, query=query))

    memo = "\n".join(out).strip()

    # ─── CP3 · hallucination guard on the final memo text ──────────────
    # Scans the whole memo for case-number citations and rewrites any
    # that aren't in the provided precedents. Mirrors the guard step in
    # handle_general so memos don't get away with an unverified cite.
    if _PRECEDENT_AVAILABLE and _pl_verify is not None and memo:
        try:
            cleaned, _halluc = _pl_verify(memo, precs)
            memo = cleaned
        except Exception:
            pass  # guard failure never blocks the memo

    return memo
