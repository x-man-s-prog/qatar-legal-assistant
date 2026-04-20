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

from typing import Optional

from core.runtime_v2.types import (
    DomainRules, DraftingMode, EvidenceItem, PathHypothesis,
    Pivot, ReasoningMode,
)
from core.runtime_v2.corpus import get_article_text, article_summary, get_rulings

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
) -> list[str]:
    """الوقائع section — three layers merged with no duplicates:
       1. User's own reported wording (verbatim, quoted).
       2. Legal-language shaping via the domain's facts_template.
       3. Fact-markers that fired (domain-internal markers).
    """
    out = ["**أولاً: الوقائع**"]
    # Layer 1 — the user's own wording (quoted)
    u = [f.strip() for f in (user_facts or []) if f and len(f.strip()) >= 4]
    for f in u[:4]:
        out.append(f"• أفاد المُستشير بأن: «{f}».")
    # Layer 2 — legal-language frame
    for t in facts_template[:4]:
        out.append(f"• {t}.")
    # Layer 3 — domain markers that actually matched
    marker_hits = [
        m.strip() for m in (established or [])
        if m and m.strip() not in u
    ]
    for m in marker_hits[:3]:
        out.append(f"• {m}.")
    if len(out) == 1:
        # Truly no data — still not a placeholder; state the structural
        # fact that submissions will be filed.
        out.append(
            "• تقدّم المستندات المؤيدة للوقائع عند جلسة المرافعة "
            "وفق ما يُثبته سجل الدعوى."
        )
    out.append("")
    return out


def _legal_basis_block(
    domain: Optional[DomainRules],
    paths:  list[PathHypothesis],
    evidence: list[EvidenceItem],
) -> list[str]:
    """الأسانيد القانونية — expand article_refs into FULL article
    texts via corpus.get_article_text. Fall back to short citations
    on DB miss."""
    out: list[str] = ["**ثالثاً: الأسانيد القانونية**"]

    # 1) Expanded article texts from DB (if domain provides refs)
    refs = (domain.article_refs or ()) if domain else ()
    expanded = 0
    for art_num, law_pat in refs:
        excerpt = article_summary(law_pat, art_num, max_chars=250)
        if excerpt:
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
) -> list[str]:
    """Develops the client-serving defenses. Uses ONLY paths[0]'s
    markers (the path aligned with the client). Opposing-side paths
    are deliberately NOT surfaced in a drafting memo."""
    if not paths:
        return []
    client_path = paths[0]
    out = ["**ثانياً: الدفوع والأسانيد الموضوعية**"]
    for f in client_path.supporting_facts[:6]:
        out.append(f"• يُتمسّك بتحقق عنصر «{f}».")
    out.append("")
    return out


def _prayers_block(domain: Optional[DomainRules]) -> list[str]:
    """Prayers — read straight from domain.primary_prayers.
    If the domain did not supply prayers (older domains), emit a
    conservative single-line closing that asks the court to apply the
    law based on what's proven, WITHOUT inviting the opposing outcome.
    """
    prayers: tuple[str, ...] = tuple()
    if domain and domain.primary_prayers:
        prayers = domain.primary_prayers
    if not prayers:
        prayers = (
            "الحكم بما يقتضيه القانون بناءً على ما ثبت من وقائع "
            "ومستندات.",
            "إلزام الخصم بالمصاريف ومقابل أتعاب المحاماة.",
        )
    out = ["**خامساً: الطلبات**"]
    for i, p in enumerate(prayers, 1):
        out.append(f"{i}. {p}.")
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

    out: list[str] = []
    out.extend(_memo_header(domain_display, drafting_mode, client_role))
    out.extend(_facts_block(user_facts, established, facts_template))
    out.extend(_defenses_block(domain, paths))
    out.extend(_legal_basis_block(domain, paths, evidence))

    # Rulings section: new linker-driven path. When the Precedent Linker
    # is disabled/unavailable AND the caller did not supply precedents,
    # degrade to the legacy static-bank block (compose_memo_v1 behavior).
    if _PRECEDENT_AVAILABLE and (precs or query or precedents is not None):
        out.extend(_rulings_block_from_precedents(precs))
    else:
        out.extend(_rulings_block(domain))

    out.extend(_prayers_block(domain))

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
