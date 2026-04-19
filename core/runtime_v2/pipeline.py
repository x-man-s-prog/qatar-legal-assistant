# -*- coding: utf-8 -*-
"""
runtime_v2.pipeline — the ONE entry point and the stages it runs.

Flow (strict, linear, no branches back to any legacy runtime):

    Input
      → Intent / Domain Resolution
      → Issue Graph (implicit in DomainRules.issues)
      → Evidence Retrieval
      → Canonical Verification
      → Reasoning Mode Selection
      → Final Response Object
      → Final Text Builder (single author)

Public API:
    from core.runtime_v2.pipeline import answer
    resp = answer("…")
    resp.to_dict()

This module takes NO dependency on any pre-v2 runtime or composer.
The contract is enforced by tests/test_runtime_v2.py (isolation tests).
"""
from __future__ import annotations

from core.runtime_v2.types import (
    DomainKey, DomainRules, DraftingMode, EvidenceItem, Intent,
    PathHypothesis, ReasoningMode, Response,
)
from core.runtime_v2.domains import (
    DOMAIN_REGISTRY, ar_norm, resolve_domain,
)
from core.runtime_v2.evidence import retrieve_evidence, verify_canonical
from core.runtime_v2.composer import compose_answer, compose_memo


# ═════════════════════════════════════════════════════════════════════
# Stage 1 — Intent detection (drafting vs analytical)
# ═════════════════════════════════════════════════════════════════════
#
# The detector works on the NORMALIZED query (ar_norm) so natural
# variations like "اكتب لي مذكرة" / "اكتبلي مذكرة" / "صيغ لي صحيفة"
# all resolve to drafting intent. Triggers are short substrings; any
# hit is sufficient.
#
# ⚠ MEMO DETECTION SOURCE-OF-TRUTH GUARDRAIL — see:
#   1. core/phase0_router.py     :: _MEMO_TRIGGERS
#   2. routers/query_router.py   :: memo_continuation block +
#                                    _MEMO_TOPIC_MAP + _MEMO_GAPS
#   3. core/runtime_v2/pipeline.py :: _DRAFT_TRIGGERS   ← (this file)
# Any change to memo phrasing must be mirrored in all three places.

_DRAFT_TRIGGERS = (
    # Memo / brief
    "اكتب مذكره", "اكتب لي مذكره", "اكتبلي مذكره",
    "صغ مذكره", "صغ لي مذكره",
    "صيغ مذكره", "صيغ لي مذكره",
    "حرر مذكره", "حرر لي مذكره",
    "اعد لي مذكره", "اعد مذكره",
    "اعداد مذكره", "اعداد لي مذكره",
    "اريد مذكره", "ابي مذكره", "احتاج مذكره",
    "مذكره دفاع", "مذكره رد", "مذكره قانونيه", "مذكره بطلب",
    "مذكرة دفاع", "مذكرة قانونية",  # diacritic-preserving variants
    # Claim / statement of claim
    "اكتب صحيفه", "اكتب لي صحيفه", "صغ صحيفه",
    "صحيفه دعوي", "صحيفه الدعوي",
    # Petition / grievance
    "اكتب عريضه", "اكتب تظلم", "صغ تظلم", "اكتب شكوي",
    # Legal reply
    "اكتب رد قانوني", "اكتب لي رد",
)


def detect_intent(query: str) -> Intent:
    """Drafting intent is detected on the NORMALIZED Arabic form so
    diacritics and "لي / لنا" insertions do not break recognition."""
    q_norm = ar_norm(query or "")
    for trig in _DRAFT_TRIGGERS:
        if ar_norm(trig) in q_norm:
            return Intent.DRAFTING
    return Intent.ANALYTICAL


# ═════════════════════════════════════════════════════════════════════
# Stage 1b — User-fact extraction (what the user reported, verbatim)
# ═════════════════════════════════════════════════════════════════════
#
# Strips drafting-trigger phrases and meta-words from the query, then
# splits on sentence delimiters. The resulting sentences are the
# "reported facts" that the memo composer uses as the الوقائع section.
# This is how the composer avoids saying "تُستكمل الوقائع من الملف".

import re as _re

_STRIP_PHRASES = (
    # Drafting triggers
    "اكتب لي مذكره قانونيه", "اكتب لي مذكره دفاع", "اكتب لي مذكره رد",
    "اكتب لي مذكره",       "اكتبلي مذكره",
    "اكتب مذكره قانونيه",  "اكتب مذكره دفاع", "اكتب مذكره رد", "اكتب مذكره",
    "صغ لي مذكره",         "صغ مذكره",
    "صيغ لي مذكره",        "صيغ مذكره",
    "حرر لي مذكره",        "حرر مذكره",
    "اعد لي مذكره",        "اعد مذكره",
    "اعداد مذكره",         "اعداد لي مذكره",
    "اريد مذكره", "ابي مذكره", "احتاج مذكره",
    "مذكره قانونيه", "مذكره دفاع", "مذكره رد", "مذكره بطلب",
    "اكتب صحيفه دعوي", "اكتب صحيفه", "صغ صحيفه", "صحيفه دعوي",
    "اكتب عريضه", "اكتب تظلم", "صغ تظلم", "اكتب شكوي",
    "اكتب رد قانوني", "اكتب لي رد", "اكتب لي",
    "مذكره", "صحيفه", "عريضه",
    # Meta-words
    "من فضلك", "لو سمحت", "ياريت", "يرجى",
)


def extract_user_facts(query: str) -> list[str]:
    """Extract factual sentences from the user's query, stripping
    drafting-trigger phrases and splitting on sentence delimiters.
    Returns up to 6 fact sentences (as the user wrote them)."""
    if not query:
        return []
    original = query
    remaining = ar_norm(query)
    # Blank out every normalized trigger occurrence inside `remaining`,
    # and mirror the same span-blanking in `original` so we preserve
    # the user's own wording for whatever survives.
    for ph in _STRIP_PHRASES:
        p_norm = ar_norm(ph)
        idx = 0
        while True:
            pos = remaining.find(p_norm, idx)
            if pos < 0:
                break
            span = len(p_norm)
            remaining = remaining[:pos] + " " * span + remaining[pos + span:]
            # Blank the same span in the original (string lengths match
            # because ar_norm is a 1:1 character mapping, not lossy).
            original = original[:pos] + " " * span + original[pos + span:]
            idx = pos + span
    # Split on sentence delimiters
    parts: list[str] = []
    for p in _re.split(r"[،,.؟!\n]|\s{3,}", original):
        p = p.strip(" .,،!؟\t\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652")
        if len(p) >= 4:
            parts.append(p)
    return parts[:6]


# ═════════════════════════════════════════════════════════════════════
# Stage 2 — Fact extraction (normalized keyword matching)
# ═════════════════════════════════════════════════════════════════════

def extract_facts(
    query: str, domain: DomainRules,
) -> tuple[list[str], list[str]]:
    """Match each path's markers against the normalized query.
    Returns (established_facts, missing_facts).

    A marker is 'established' when ANY of its keywords appears in the
    normalized query. Duplicates across paths are de-duplicated by
    label so the two lists are clean.
    """
    q_norm = ar_norm(query or "")
    established: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for path in domain.paths:
        for marker in path.markers:
            if marker.label in seen:
                continue
            seen.add(marker.label)
            hit = any(ar_norm(kw) in q_norm for kw in marker.keywords)
            (established if hit else missing).append(marker.label)
    return established, missing


# ═════════════════════════════════════════════════════════════════════
# Stage 3 — Path weighting
# ═════════════════════════════════════════════════════════════════════

def weigh_paths(
    domain: DomainRules, established: list[str],
) -> list[PathHypothesis]:
    """Re-weight every path by the fraction of its markers present in
    the established-fact set. Range: 0.30 (no hits) .. 1.00 (all hits).
    Returns the paths sorted descending by weight."""
    est_set = set(established)
    out: list[PathHypothesis] = []
    for path in domain.paths:
        total  = max(1, len(path.markers))
        hits   = sum(1 for m in path.markers if m.label in est_set)
        weight = round(0.30 + 0.70 * (hits / total), 3)
        out.append(PathHypothesis(
            label    = path.label,
            articles = tuple(path.articles),
            markers  = tuple(path.markers),
            weight   = weight,
        ))
    out.sort(key=lambda p: -p.weight)
    return out


# ═════════════════════════════════════════════════════════════════════
# Stage 4 — Reasoning + drafting mode selection
# ═════════════════════════════════════════════════════════════════════

def select_reasoning_mode(
    domain: DomainRules,
    paths: list[PathHypothesis],
    established: list[str],
) -> ReasoningMode:
    """Pick the correct reasoning mode.

    Rules (deterministic, in order):
      1. No established facts at all         → SKELETON
      2. Only one path                        → SINGLE_PATH
      3. Dominant path (top ≥ 0.75, gap ≥ 0.30) → SINGLE_PATH
      4. Tied paths (|gap| < 0.20) + pivots   → CONDITIONAL
      5. Otherwise                            → domain.default_mode
    """
    if not established or not paths:
        return ReasoningMode.SKELETON
    if len(paths) == 1:
        return ReasoningMode.SINGLE_PATH
    top, second = paths[0], paths[1]
    gap = top.weight - second.weight
    if top.weight >= 0.75 and gap >= 0.30:
        return ReasoningMode.SINGLE_PATH
    if domain.pivots and abs(gap) < 0.20:
        return ReasoningMode.CONDITIONAL
    return domain.default_mode


def select_drafting_mode(reasoning: ReasoningMode) -> DraftingMode:
    """Maps the reasoning mode onto a drafting mode.

    NOTE: When reasoning is SKELETON but the user asked for a memo,
    we coerce to CONDITIONAL_DRAFT so the composer still emits a
    FULL memo (all paths listed as alternative defenses, all pivots
    as conditional questions, every article cited). A user asking
    for a memo must never receive a placeholder-shaped skeleton.
    """
    return {
        ReasoningMode.SINGLE_PATH: DraftingMode.SINGLE_DRAFT,
        ReasoningMode.MULTI_PATH:  DraftingMode.DUAL_DRAFT,
        ReasoningMode.CONDITIONAL: DraftingMode.CONDITIONAL_DRAFT,
        ReasoningMode.SKELETON:    DraftingMode.CONDITIONAL_DRAFT,
    }[reasoning]


# ═════════════════════════════════════════════════════════════════════
# Generic skeleton for queries outside the four pilot domains
# ═════════════════════════════════════════════════════════════════════

# Lightweight cue library — tells us which general legal family the
# user is probably in, even when none of the pilot domains matches.
# Cues are matched against the normalized query. This is NOT a
# domain router — it only helps us ask smarter follow-up questions.

_GENERIC_CUES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (family_label, trigger_keywords, fact_gaps_to_ask_about)
    (
        "شبهة مسألة جنائية",
        ("سب", "شتم", "قذف", "تهديد", "اعتداء", "سرقه", "تزوير",
         "اختلاس", "رشوه", "بلاغ كاذب", "تحرش"),
        ("محضر الشرطة أو رقم البلاغ",
         "تاريخ ومكان الواقعة",
         "صفة المتهم والمجني عليه وصلتهما ببعض",
         "الأدلة المتوفرة: شهود، تسجيلات، مراسلات"),
    ),
    (
        "شبهة مسألة أسرية",
        ("طلاق", "خلع", "نفقه", "حضانه", "نسب", "عده", "زواج",
         "مهر", "ولايه"),
        ("عقد الزواج وتاريخه",
         "وجود أطفال وأعمارهم",
         "مكان إقامة الأسرة الحالي",
         "وجود اتفاقات سابقة أو أحكام قضائية بين الطرفين"),
    ),
    (
        "شبهة مسألة إيجارية / عقارية",
        ("ايجار", "مؤجر", "مستأجر", "اخلاء", "عقد ايجار", "تملك",
         "عقار", "بيع عقار", "رهن عقاري"),
        ("العقد المكتوب ومدته وقيمة الأجرة/الثمن",
         "نوع العقار (سكني/تجاري) وموقعه",
         "الإخلالات المدّعى بها مفصّلة",
         "الإنذارات/المراسلات السابقة بين الطرفين"),
    ),
    (
        "شبهة مسألة مصرفية",
        ("بنك", "حساب", "قرض", "تحويل", "ضمان بنكي", "فائده ربويه",
         "رسوم بنكيه", "بطاقه ائتمان"),
        ("كشف الحساب ومستنداته",
         "اتفاقية القرض أو الحساب",
         "تاريخ وطبيعة الواقعة محل النزاع",
         "المراسلات مع البنك والإنذارات"),
    ),
    (
        "شبهة مسألة إدارية / حكومية",
        ("وزاره", "جهة حكوميه", "قرار اداري", "تظلم اداري", "ترخيص",
         "اقامه", "تاشيره"),
        ("القرار الإداري المحل للطعن وتاريخه",
         "تاريخ العلم بالقرار",
         "التظلم المسبق إن وُجد",
         "المستندات التي تُثبت الصفة والمصلحة"),
    ),
    (
        "شبهة مسألة تجارية / شركات",
        ("شركه", "سجل تجاري", "علامه تجاريه", "عقد تجاري", "افلاس",
         "تصفيه شركه", "منافسه"),
        ("السجل التجاري والعقد التأسيسي",
         "الأطراف وحصصهم",
         "المراسلات والاتفاقات المتعلقة بمحل النزاع",
         "القرارات الإدارية للشركة إن وُجدت"),
    ),
)


def _detect_generic_family(
    query_norm: str,
) -> tuple[str, tuple[str, ...]]:
    """Return (family_label, fact_gaps) for the strongest generic
    match, or ("", ()) when nothing lines up."""
    best_label = ""
    best_gaps: tuple[str, ...] = ()
    best_hits = 0
    for label, triggers, gaps in _GENERIC_CUES:
        hits = sum(
            1 for kw in triggers if ar_norm(kw) in query_norm
        )
        if hits > best_hits:
            best_hits = hits
            best_label = label
            best_gaps  = gaps
    return best_label, best_gaps


_SUPPORTED_DOMAINS_LIST = (
    "• تكييف العلاقة: علاقة عمل أم شراكة.",
    "• طبيعة الشيك: أداة وفاء أم شيك ضمان.",
    "• التصرف في مرض الموت في مقابل وفاء دين.",
    "• ملكية الكود ومكتبات المطور السابقة.",
)


def _build_generic_skeleton(
    query: str,
    intent: Intent,
    user_facts: list[str],
) -> Response:
    """Build a Response for queries outside the registered pilot
    domains. Provides real analytical value, never a rigid refusal —
    and when the user asks for a memo, produces a FULL memo using
    the user's own facts as the الوقائع section.
    """
    q_norm = ar_norm(query)
    family_label, family_gaps = _detect_generic_family(q_norm)

    # Universal gaps that apply to any legal file
    universal_gaps = (
        "الأطراف وصفاتهم",
        "الوقائع محل النزاع بالترتيب الزمني",
        "المستندات والأدلة المتوفرة حاليًا",
        "الطلب القانوني الذي يسعى إليه المُستشير",
    )
    missing = list(universal_gaps) + list(family_gaps)

    # Answer text for analytical intent
    lines: list[str] = []
    lines.append(
        f"**تحليل أولي — {family_label}.**" if family_label
        else "**تحليل أولي — المسألة القانونية.**"
    )
    lines.append("")
    if user_facts:
        lines.append("**الوقائع كما أفاد المُستشير:**")
        for f in user_facts[:5]:
            lines.append(f"• {f}.")
        lines.append("")
    lines.append("**ما يلزم استيضاحه لاستكمال التحليل:**")
    for g in missing[:7]:
        lines.append(f"• {g}")
    lines.append("")
    lines.append("**المسائل ذات المحرك التحليلي المتقدم حاليًا:**")
    for line in _SUPPORTED_DOMAINS_LIST:
        lines.append(line)
    answer_text = "\n".join(lines).strip()

    # Drafting output — build a FULL memo via compose_memo so the user
    # gets a real document (bismillah, court addressing, facts, defenses,
    # legal basis, requests, closing) — not a placeholder skeleton.
    memo = None
    drafting_mode = None
    if intent == Intent.DRAFTING:
        # ═══ إصلاح جذري: بدل مذكرة فارغة، اسأل عن التفاصيل ═══
        # إذا المستخدم أعطى أقل من 3 حقائق معنوية، لا تنتج مذكرة —
        # اسأله أسئلة ذكية. هذا يمنع «يُتمسّك بتحقق عنصر اقدمها للمحكمة»
        # وأمثاله من الكوارث.
        meaningful_facts = [
            f for f in (user_facts or [])
            if f and len(f.strip()) >= 8
        ]
        if len(meaningful_facts) < 3:
            ask_lines: list[str] = []
            if family_label:
                ask_lines.append(
                    f"**لصياغة مذكرة {family_label} بشكل احترافي، "
                    f"أحتاج منك التفاصيل التالية:**"
                )
            else:
                ask_lines.append(
                    "**لصياغة مذكرة قانونية احترافية، أحتاج منك "
                    "التفاصيل التالية:**"
                )
            ask_lines.append("")
            for g in missing[:6]:
                ask_lines.append(f"• {g}")
            ask_lines.append("")
            if meaningful_facts:
                ask_lines.append("**وقائع أَفَدتَ بها حتى الآن:**")
                for f in meaningful_facts:
                    ask_lines.append(f"  - {f}.")
                ask_lines.append("")
            ask_lines.append(
                "أرسل لي هذه التفاصيل في رسالتك التالية وسأصيغ "
                "المذكرة كاملة بمواد القانون القطري ذات الصلة وطلبات محددة."
            )
            # لا ننتج مذكرة — نستعمل answer_text ليحمل السؤال
            answer_text = "\n".join(ask_lines)
            memo = None
            drafting_mode = None
        else:
            # المستخدم أعطى تفاصيل كافية — أنتج مذكرة حقيقية
            from core.runtime_v2.types import (
                PathHypothesis as _PathH, FactMarker as _FM,
            )
            # Synthetic path built from the family cue so the composer
            # can render defenses and articles coherently.
            synthetic_path = _PathH(
                label=family_label or "المسألة محل النظر",
                articles=(
                    "القانون القطري المنظِّم للمسألة (تُحدَّد تطبيقاته بحسب "
                    "الوقائع عند التحقيق)",
                ),
                markers=tuple(
                    _FM(label=f, keywords=())
                    for f in (meaningful_facts[:4] or user_facts[:4] or ["—"])
                ),
                weight=0.5,
            )
            drafting_mode = DraftingMode.CONDITIONAL_DRAFT
            memo = compose_memo(
                domain_display = family_label or "المسألة القانونية",
                drafting_mode  = drafting_mode,
                paths          = [synthetic_path],
                pivots         = [],
                evidence       = [],
                established    = meaningful_facts[:4] or user_facts[:4],
                missing        = missing,
                user_facts     = user_facts,
            )

    return Response(
        answer_text       = answer_text,
        domain            = "general_skeleton",
        intent            = intent,
        reasoning_mode    = ReasoningMode.SKELETON,
        drafting_mode     = drafting_mode,
        is_skeleton       = True,
        missing_facts     = missing,
        memo_text         = memo,
        established_facts = user_facts,
    )


# ═════════════════════════════════════════════════════════════════════
# Stage 5 — Orchestrator (the public entry point)
# ═════════════════════════════════════════════════════════════════════

def answer(query: str) -> Response:
    """The single public entry point of runtime_v2.

    Returns a Response. Never raises for empty / out-of-scope queries.
    No fallback to any legacy runtime under any condition.
    """
    q = query or ""
    intent = detect_intent(q)
    domain_key = resolve_domain(q)

    # User-reported facts — extracted from the raw query (regardless of
    # domain). Used as the الوقائع section so we NEVER say
    # "تُستكمل الوقائع من الملف".
    user_facts = extract_user_facts(q)

    # ── Out-of-scope — build a real memo (never a rigid refusal) ──
    if domain_key == DomainKey.UNKNOWN:
        return _build_generic_skeleton(q, intent, user_facts)

    domain = DOMAIN_REGISTRY[domain_key]

    # Evidence retrieval → canonical verification
    evidence: list[EvidenceItem] = verify_canonical(retrieve_evidence(domain))

    # Fact extraction → path weighting → mode selection
    established, missing = extract_facts(q, domain)
    paths = weigh_paths(domain, established)
    reasoning = select_reasoning_mode(domain, paths, established)

    # Final text (analytical) — ONE author, ONE builder
    answer_text = compose_answer(
        domain_display = domain.display_name,
        reasoning_mode = reasoning,
        paths          = paths,
        pivots         = list(domain.pivots),
        evidence       = evidence,
        established    = established,
        missing        = missing,
    )

    # Drafting output — ONE memo builder, triggered only by intent
    drafting_mode: DraftingMode | None = None
    memo_text: str | None = None
    if intent == Intent.DRAFTING:
        drafting_mode = select_drafting_mode(reasoning)
        memo_text = compose_memo(
            domain_display = domain.display_name,
            drafting_mode  = drafting_mode,
            paths          = paths,
            pivots         = list(domain.pivots),
            evidence       = evidence,
            established    = established,
            missing        = missing,
            user_facts     = user_facts,
            domain         = domain,
        )

    return Response(
        answer_text       = answer_text,
        domain            = domain.key.value,
        intent            = intent,
        reasoning_mode    = reasoning,
        drafting_mode     = drafting_mode,
        paths             = paths,
        pivots            = list(domain.pivots),
        evidence          = evidence,
        established_facts = established,
        missing_facts     = missing,
        is_skeleton       = (reasoning == ReasoningMode.SKELETON),
        memo_text         = memo_text,
    )
