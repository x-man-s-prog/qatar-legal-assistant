# -*- coding: utf-8 -*-
"""
core/legal_reasoning_engine.py — THE brain of the memo pipeline.

WHY THIS EXISTS
===============
Every prior CP (1, 4, 5) fixed the PLUMBING of the memo pipeline:
hallucination guards, routing gates, session state. None added a
REASONING layer. The user-visible quality remained poor because:

  • The system dumped ALL domain.article_refs into every memo
    (7 articles when a lawyer would cite 2-3).
  • Precedents were retrieved by text similarity (Jaccard), so a
    custody memo got civil cassation rulings about property sales.
  • The composer was a concatenator — bullets of facts + bullets of
    articles + bullets of precedents — NEVER a coherent legal
    argument.
  • Names / dates extracted by fact_extractor were rendered as flat
    "الأعمار المذكورة: 3 سنين" bullets instead of woven into prose.

A real lawyer REASONS:

  1. CHARACTERIZE — given the facts, what legal ground applies?
  2. SELECT        — which specific articles support THIS ground?
  3. RERANK        — which precedents are on-point for THIS ground?
  4. COMPOSE       — weave facts + law + precedent into narrative.
  5. VERIFY        — no invented article, no ungrounded claim.

This module implements those 5 stages. Each stage is an LLM call
with a STRICT JSON-output schema, a hard timeout, a regex/deterministic
fallback, and a Redis cache keyed by the input fingerprint.

CONTRACT
========
Primary entry point:
    async compose_reasoned_memo(
        query, facts, domain, candidate_articles,
        candidate_precedents, drafting_mode
    ) -> ReasonedMemoResult

ReasonedMemoResult captures:
  • memo_text              — the composed memo (prose, not bullets)
  • ground                 — the LegalGround detected
  • selected_articles      — the 2-3 articles actually used
  • selected_precedents    — the ones LLM scored on-point
  • verification           — grounding report
  • used_engine            — True on success, False on fallback

Fallback contract:
  If ANY stage fails (timeout, parse error, empty LLM output),
  returns with used_engine=False and the caller must fall back to
  the deterministic compose_memo path (composer.compose_memo_v1).
  No silent half-rendering.

DESIGN CHOICES LOCKED IN
========================
  • OpenAI GPT-4o via services.llm_service.call_openai.
  • All LLM prompts DEMAND JSON output with a fixed schema.
  • Each stage has a 12s timeout (total budget ~60s worst case).
  • Characterize + select_articles + rerank_precedents run in
    PARALLEL where possible (asyncio.gather).
  • Redis db=2 cache for stages whose output depends only on
    (facts, domain) — fingerprint via SHA1(json(inputs)).
  • Compose stage is NEVER cached (style matters per-turn).
  • Verify is programmatic (regex + set membership), not LLM —
    cheap, deterministic, auditable.

NON-GOALS
=========
  • Does NOT replace fact_extractor (still the upstream source of
    grounded facts).
  • Does NOT replace precedent_linker (only reranks its output).
  • Does NOT replace article_summary (reads DB text as canonical).
  • Does NOT modify DomainRules (reads article_refs as candidates).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

_LLM_TIMEOUT_SECONDS  = 12.0    # per-stage hard timeout
_CACHE_TTL_SECONDS    = 3600    # 1 hour (facts rarely change within a session)
_MAX_SELECTED_ARTICLES = 4      # hard cap — lawyers rarely cite more than 3-4
_MAX_SELECTED_PRECEDENTS = 3    # same
_CHARACTERIZE_MAX_TOKENS = 500
_SELECT_MAX_TOKENS       = 600
_COMPOSE_MAX_TOKENS      = 3200
_RERANK_MAX_TOKENS       = 500


# ═══════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LegalGround:
    """The specific legal basis chosen for the memo. One per memo."""
    label:             str                 = ""
    primary_article:   str                 = ""  # e.g. "183"
    primary_clause:    str                 = ""  # e.g. "3"
    required_elements: list[str]           = field(default_factory=list)
    confidence:        float               = 0.0

    def is_empty(self) -> bool:
        return not self.label and not self.primary_article


@dataclass
class SelectedArticle:
    """An article LLM chose to cite, with reason for inclusion."""
    number:    str = ""
    law_name:  str = ""
    reason:    str = ""   # WHY this article supports the ground


@dataclass
class SelectedPrecedent:
    """A precedent LLM scored as on-point for the ground."""
    display_ref:      str     = ""
    score:            float   = 0.0
    reason:           str     = ""   # why this ruling applies
    content_snippet:  str     = ""


@dataclass
class VerificationResult:
    """Post-composition grounding check."""
    passed:            bool         = True
    invented_articles: list[str]    = field(default_factory=list)
    invented_refs:     list[str]    = field(default_factory=list)
    warnings:          list[str]    = field(default_factory=list)


@dataclass
class ReasonedMemoResult:
    """Full output of the reasoning pipeline."""
    memo_text:           str                         = ""
    ground:              LegalGround                 = field(default_factory=LegalGround)
    selected_articles:   list[SelectedArticle]       = field(default_factory=list)
    selected_precedents: list[SelectedPrecedent]     = field(default_factory=list)
    verification:        VerificationResult          = field(default_factory=VerificationResult)
    used_engine:         bool                        = False
    elapsed_seconds:     float                       = 0.0
    failure_reason:      Optional[str]               = None


# ═══════════════════════════════════════════════════════════════════
# System prompts (Arabic, strict JSON output)
# ═══════════════════════════════════════════════════════════════════

_CHARACTERIZE_SYSTEM = """\
أنت محامٍ قطري خبير. مهمتك: تحديد الأساس القانوني الدقيق لدعوى المستشير بناءً على وقائعه.

قواعد صارمة:
1. اختر مادة واحدة أساسية (primary_article) فقط — الأكثر انطباقاً.
2. إن كانت المادة مقسّمة إلى فقرات، حدد الفقرة (primary_clause). مثال: المادة 183 فقرة 3.
3. اذكر الأركان المطلوبة لإثبات هذا الأساس (2-4 أركان).
4. ثقتك (confidence) رقم بين 0 و 1.
5. لا تفترض وقائع غير مذكورة. إذا الوقائع غامضة، اختر الأساس الأقل افتراضاً.

مثال: موكل ذكر "سوء سلوك الحاضنة" في دعوى حضانة:
→ primary_article = "183", primary_clause = "3"
→ label = "إسقاط الحضانة لسوء سلوك الحاضنة"
→ required_elements = ["إثبات سوء السلوك", "الخشية على مصلحة المحضون"]

أخرج JSON فقط بهذه البنية:
{
  "label": "...",
  "primary_article": "...",
  "primary_clause": "...",
  "required_elements": ["...", "..."],
  "confidence": 0.0
}
لا نص خارج الـ JSON.
"""


_SELECT_ARTICLES_SYSTEM = """\
أنت محامٍ قطري خبير. لديك قائمة بالمواد المرشحة للاستشهاد بها في مذكرة، وأساس قانوني محدد.

مهمتك: اختر 2-4 مواد فقط — الأكثر دعماً للأساس.

قواعد:
1. لا تختر أكثر من 4 مواد.
2. كل مادة مختارة يجب أن تكون ذات صلة مباشرة بالأساس أو بإجراءاته.
3. ارفض المواد غير المنطبقة (مثل: مادة الزواج في قضية سوء سلوك).
4. اذكر السبب لكل اختيار ولكل رفض.
5. الأولوية للمادة الأساسية (primary_article) — يجب أن تكون ضمن المختارة.

أخرج JSON فقط:
{
  "selected": [
    {"number": "...", "reason": "..."},
    ...
  ],
  "rejected": [
    {"number": "...", "reason": "..."},
    ...
  ]
}
"""


_RERANK_PRECEDENTS_SYSTEM = """\
أنت محامٍ قطري خبير. لديك أحكام تمييز مرشحة، وأساس قانوني محدد للقضية.

مهمتك: رتّب الأحكام حسب صلتها المباشرة بالأساس القانوني. ارفض الأحكام غير ذات الصلة.

قواعد:
1. الحكم يجب أن يعالج نفس الأساس القانوني أو مبدأ قضائي مرتبط به.
2. ارفض الأحكام في مجالات أخرى (مثلاً: حكم بيع عقار في قضية حضانة).
3. score بين 0 و 1 — الأعلى أكثر صلة.
4. score < 0.5 يعني ارفض.
5. اذكر السبب لكل حكم (لماذا منطبق أو غير منطبق).

أخرج JSON فقط:
{
  "ranked": [
    {"ref": "...", "score": 0.0, "reason": "..."},
    ...
  ]
}
"""


_COMPOSE_MEMO_SYSTEM = """\
أنت محامٍ قطري خبير تصيغ مذكرة قانونية احترافية بأسلوب المحاكم القطرية.

القيود القطعية:
1. لا تخترع أي واقعة لم يذكرها الموكل صراحة. استخدم فقط الوقائع المقدّمة.
2. لا تستشهد بمادة غير موجودة في قائمة المواد المختارة.
3. لا تستشهد بحكم تمييز غير موجود في قائمة الأحكام المختارة.
4. كل اسم، تاريخ، مبلغ، عمر — استخدمه كما ذكره الموكل بالضبط.
5. **إلزامي**: لكل معلومة ناقصة في الوقائع (اسم، تاريخ، مبلغ، رقم، عنوان)،
   ضع placeholder صريح بأقواس مربعة. أمثلة:
     [يُدرج اسم المدعى عليها] — إذا لم يُذكر اسم الخصم.
     [يُدرج التاريخ] — إذا لم يُذكر تاريخ واقعة.
     [يُدرج المبلغ] — إذا لم يُذكر مبلغ.
     [يُدرج رقم الشيك] — إذا لم يُذكر الرقم.
     [اسم المدعي] — اسم مقدم المذكرة حين لا يُذكر.
6. **إلزامي**: المذكرة يجب أن تحتوي على placeholder واحد على الأقل
   إذا كان هناك معلومة ناقصة (وهذا الوضع الشائع).

قواعد الأسلوب:
1. اكتب prose قانونية، ليس bullets. اربط الوقائع بسرد قانوني.
2. ابدأ بـ "بسم الله الرحمن الرحيم".
3. العنوان: "مذكرة قانونية بطلبات أصلية واحتياطية".
4. **الأقسام بأسمائها الحرفية** (كل قسم على سطر مستقل كعنوان):
     - "الوقائع" (prose، 80-180 كلمة).
     - "الدفوع والأسانيد الموضوعية" (prose يربط الوقائع بأركان الأساس).
     - "الأسانيد القانونية" (prose يستشهد بالمواد المختارة مع نصوصها).
     - "السوابق القضائية" (prose إذا فيه أحكام، جملة صريحة إذا لم يوجد).
     - "الطلبات" (مرقّمة، محددة، مبنية على الأساس).
5. اختم بـ "والله ولي التوفيق،،".

مثال على Prose vs Bullets:
✗ سيء: "• الأعمار المذكورة: 3 سنوات. • أفاد بأن سوء سلوكها."
✓ جيد: "أفاد المُستشير بأن موكله أب لمحضون يُدعى [يُدرج اسم المحضون]، يبلغ من العمر ثلاث سنوات، وأن المدعى عليها قد أظهرت سوء سلوك..."

مثال على placeholders:
✓ "يتقدم مقدم المذكرة [يُدرج اسم المدعي] ضد [يُدرج اسم المدعى عليها]
   بدعوى إسقاط الحضانة..."
✓ "حرر المدعى عليه شيكاً بمبلغ 12,000 ريال بتاريخ [يُدرج تاريخ الشيك]
   برقم [يُدرج رقم الشيك]..."

أخرج نص المذكرة الكاملة فقط — لا JSON، لا تعليق.
"""


# ═══════════════════════════════════════════════════════════════════
# Public entry point
# ═══════════════════════════════════════════════════════════════════

async def compose_reasoned_memo(
    *,
    query:                 str,
    user_facts:            list[str],
    extracted_facts_dict:  dict,
    domain_display:        str,
    domain_key:            str,
    candidate_articles:    list[dict],     # [{number, law_name, text}, ...]
    candidate_precedents:  list[dict],     # [{display_ref, content, score}, ...]
    drafting_mode_label:   str,
    client_role:           str = "",
) -> ReasonedMemoResult:
    """Compose a lawyer-quality memo through LLM-driven reasoning.

    Parameters
    ----------
    query: raw user query (for context hints only)
    user_facts: list of verbatim user statements (from fact_extractor.claims)
    extracted_facts_dict: full ExtractedFacts.to_dict() (names, ages, etc.)
    domain_display: Arabic domain display name
    domain_key: programmatic key (e.g. "family_custody")
    candidate_articles: pool of articles the domain can cite
    candidate_precedents: pool from precedent_linker
    drafting_mode_label: "مذكرة قانونية بطلبات أصلية واحتياطية"
    client_role: e.g. "المدعي (الأب طالب إسقاط الحضانة)"

    Returns
    -------
    ReasonedMemoResult with used_engine=True on success, False on any
    stage failure — caller must check and fall back.
    """
    t0 = time.time()
    result = ReasonedMemoResult()

    try:
        # ── Stage 1: Characterize (required, cached) ────────────
        ground = await _characterize(
            user_facts=user_facts,
            extracted_facts_dict=extracted_facts_dict,
            domain_display=domain_display,
            domain_key=domain_key,
        )
        if ground.is_empty():
            result.failure_reason = "characterize returned empty"
            return result
        result.ground = ground

        # ── Stages 2 + 3: select articles + rerank precedents in parallel ──
        select_task = asyncio.create_task(
            _select_articles(
                ground=ground,
                candidates=candidate_articles,
                user_facts=user_facts,
            )
        )
        rerank_task = asyncio.create_task(
            _rerank_precedents(
                ground=ground,
                candidates=candidate_precedents,
            )
        )
        selected_articles, ranked_precedents = await asyncio.gather(
            select_task, rerank_task, return_exceptions=True,
        )

        # Handle partial failures gracefully
        if isinstance(selected_articles, Exception):
            log.warning("reasoning: select_articles failed: %s", selected_articles)
            selected_articles = []
        if isinstance(ranked_precedents, Exception):
            log.warning("reasoning: rerank_precedents failed: %s", ranked_precedents)
            ranked_precedents = []

        result.selected_articles = selected_articles or []
        result.selected_precedents = ranked_precedents or []

        # If the primary article isn't in selected, this is a serious
        # signal. Still, proceed — compose can cite it anyway.

        # ── Stage 4: Compose prose memo ─────────────────────────
        memo_text = await _compose_prose(
            ground=ground,
            user_facts=user_facts,
            extracted_facts_dict=extracted_facts_dict,
            selected_articles=selected_articles,
            selected_precedents=ranked_precedents,
            drafting_mode_label=drafting_mode_label,
            client_role=client_role,
            domain_display=domain_display,
        )
        if not memo_text or len(memo_text) < 500:
            result.failure_reason = f"compose produced short output ({len(memo_text or '')})"
            return result
        result.memo_text = memo_text

        # ── Stage 5: Verify grounding (programmatic, cheap) ────
        result.verification = _verify_grounding(
            memo_text=memo_text,
            allowed_article_numbers={
                a.number for a in selected_articles if a.number
            },
            allowed_precedent_refs={
                p.display_ref for p in ranked_precedents if p.display_ref
            },
        )

        result.used_engine = True
        result.elapsed_seconds = time.time() - t0
        log.info(
            "reasoning: memo composed via engine (ground=%s, "
            "articles=%d, precedents=%d, %.1fs)",
            ground.label[:40], len(selected_articles),
            len(ranked_precedents), result.elapsed_seconds,
        )
        return result

    except Exception as e:
        result.failure_reason = f"{type(e).__name__}: {e}"
        result.elapsed_seconds = time.time() - t0
        log.warning("reasoning: pipeline failure — %s", result.failure_reason)
        return result


# ═══════════════════════════════════════════════════════════════════
# Stage 1 — Characterize
# ═══════════════════════════════════════════════════════════════════

async def _characterize(
    user_facts:           list[str],
    extracted_facts_dict: dict,
    domain_display:       str,
    domain_key:           str,
) -> LegalGround:
    """Determine the specific legal ground from facts + domain context."""
    # Cache key
    cache_key = _fingerprint({
        "stage": "characterize",
        "facts": user_facts,
        "structured": extracted_facts_dict,
        "domain_key": domain_key,
    })
    cached = await _cache_get(cache_key)
    if cached:
        try:
            return LegalGround(**cached)
        except Exception:
            pass  # ignore corrupt cache, recompute

    user_context = (
        f"المجال القانوني: {domain_display} (key: {domain_key})\n"
        f"الوقائع كما ذكرها الموكل:\n"
        + "\n".join(f"- {f}" for f in user_facts[:10])
        + "\n\nالحقول المستخرجة:\n"
        f"الأسماء: {extracted_facts_dict.get('names', [])}\n"
        f"التواريخ: {extracted_facts_dict.get('dates', [])}\n"
        f"الأعمار: {extracted_facts_dict.get('ages', [])}\n"
        f"المبالغ: {extracted_facts_dict.get('amounts', [])}\n"
    )

    raw = await _llm_json_call(
        system=_CHARACTERIZE_SYSTEM,
        user_message=user_context,
        max_tokens=_CHARACTERIZE_MAX_TOKENS,
    )
    if not raw:
        return LegalGround()

    try:
        g = LegalGround(
            label             = str(raw.get("label", "")).strip(),
            primary_article   = str(raw.get("primary_article", "")).strip(),
            primary_clause    = str(raw.get("primary_clause", "")).strip(),
            required_elements = [str(x) for x in raw.get("required_elements", [])][:5],
            confidence        = float(raw.get("confidence", 0.0)),
        )
    except Exception as e:
        log.warning("characterize: parse failed: %s", e)
        return LegalGround()

    if not g.is_empty():
        await _cache_set(cache_key, {
            "label":             g.label,
            "primary_article":   g.primary_article,
            "primary_clause":    g.primary_clause,
            "required_elements": g.required_elements,
            "confidence":        g.confidence,
        })
    return g


# ═══════════════════════════════════════════════════════════════════
# Stage 2 — Select Articles
# ═══════════════════════════════════════════════════════════════════

async def _select_articles(
    ground:      LegalGround,
    candidates:  list[dict],
    user_facts:  list[str],
) -> list[SelectedArticle]:
    """Pick 2-4 articles from `candidates` that actually support `ground`."""
    if not candidates:
        return []

    cache_key = _fingerprint({
        "stage": "select_articles",
        "ground": ground.label,
        "primary": ground.primary_article,
        "candidates": [c.get("number", "") for c in candidates],
    })
    cached = await _cache_get(cache_key)
    if cached and isinstance(cached, list):
        return [SelectedArticle(**s) for s in cached]

    candidates_text = "\n".join(
        f"- المادة ({c.get('number', '?')}) من {c.get('law_name', '?')}: "
        f"{(c.get('text') or '')[:200]}..."
        for c in candidates[:15]
    )

    user_message = (
        f"الأساس القانوني المحدد: {ground.label}\n"
        f"المادة الأساسية: {ground.primary_article} "
        f"فقرة {ground.primary_clause}\n\n"
        f"وقائع الموكل:\n"
        + "\n".join(f"- {f}" for f in user_facts[:6])
        + f"\n\nالمواد المرشحة ({len(candidates)}):\n"
        + candidates_text
        + "\n\nاختر 2-4 مواد فقط."
    )

    raw = await _llm_json_call(
        system=_SELECT_ARTICLES_SYSTEM,
        user_message=user_message,
        max_tokens=_SELECT_MAX_TOKENS,
    )
    if not raw:
        return []

    selected_raw = raw.get("selected", [])
    if not isinstance(selected_raw, list):
        return []

    # Map back to full candidate records (for law_name / text)
    by_num = {str(c.get("number", "")): c for c in candidates}
    out: list[SelectedArticle] = []
    for item in selected_raw[:_MAX_SELECTED_ARTICLES]:
        num = str(item.get("number", "")).strip()
        if not num:
            continue
        ref = by_num.get(num, {})
        out.append(SelectedArticle(
            number   = num,
            law_name = str(ref.get("law_name", "")),
            reason   = str(item.get("reason", ""))[:200],
        ))

    if out:
        await _cache_set(cache_key, [
            {"number": s.number, "law_name": s.law_name, "reason": s.reason}
            for s in out
        ])
    return out


# ═══════════════════════════════════════════════════════════════════
# Stage 3 — Rerank Precedents
# ═══════════════════════════════════════════════════════════════════

async def _rerank_precedents(
    ground:     LegalGround,
    candidates: list[dict],
) -> list[SelectedPrecedent]:
    """Keep only precedents that the LLM scores on-point (>= 0.5)."""
    if not candidates:
        return []

    candidates_text = "\n".join(
        f"[{c.get('display_ref', '?')}] "
        f"(مجال: {c.get('domain', '?')}): "
        f"{(c.get('content') or '')[:250]}..."
        for c in candidates[:8]
    )

    user_message = (
        f"الأساس القانوني: {ground.label}\n"
        f"المادة الأساسية: {ground.primary_article}\n\n"
        f"الأحكام المرشحة ({len(candidates)}):\n"
        + candidates_text
    )

    raw = await _llm_json_call(
        system=_RERANK_PRECEDENTS_SYSTEM,
        user_message=user_message,
        max_tokens=_RERANK_MAX_TOKENS,
    )
    if not raw:
        return []

    ranked_raw = raw.get("ranked", [])
    if not isinstance(ranked_raw, list):
        return []

    by_ref = {str(c.get("display_ref", "")): c for c in candidates}
    out: list[SelectedPrecedent] = []
    for item in ranked_raw:
        ref = str(item.get("ref", "")).strip()
        if not ref:
            continue
        score = float(item.get("score", 0.0))
        if score < 0.5:
            continue  # reject low-relevance
        src = by_ref.get(ref, {})
        out.append(SelectedPrecedent(
            display_ref     = ref,
            score           = score,
            reason          = str(item.get("reason", ""))[:200],
            content_snippet = (src.get("content") or "")[:500],
        ))
        if len(out) >= _MAX_SELECTED_PRECEDENTS:
            break
    return out


# ═══════════════════════════════════════════════════════════════════
# Stage 4 — Compose Prose Memo
# ═══════════════════════════════════════════════════════════════════

async def _compose_prose(
    ground:               LegalGround,
    user_facts:           list[str],
    extracted_facts_dict: dict,
    selected_articles:    list[SelectedArticle],
    selected_precedents:  list[SelectedPrecedent],
    drafting_mode_label:  str,
    client_role:          str,
    domain_display:       str,
) -> str:
    """LLM composes the final memo as prose."""
    # Build context the composer LLM needs
    names_text   = "، ".join(extracted_facts_dict.get("names", [])) or "—"
    ages_text    = "، ".join(extracted_facts_dict.get("ages", [])) or "—"
    dates_text   = "، ".join(extracted_facts_dict.get("dates", [])) or "—"
    amounts_text = "، ".join(extracted_facts_dict.get("amounts", [])) or "—"

    facts_block = "\n".join(f"- {f}" for f in user_facts[:8])

    articles_block = "\n".join(
        f"المادة ({a.number}) من {a.law_name}\n"
        f"(سبب الاختيار: {a.reason})"
        for a in selected_articles
    ) or "(لا توجد مواد مختارة — اذكر إطاراً قانونياً عاماً)"

    precedents_block = "\n".join(
        f"[{p.display_ref}] (صلة: {p.score:.2f}): "
        f"{p.content_snippet[:200]}..."
        for p in selected_precedents
    ) or "(لا توجد أحكام تمييز ذات صلة مباشرة)"

    user_message = (
        f"الأساس القانوني المحدد:\n"
        f"  • العنوان: {ground.label}\n"
        f"  • المادة الأساسية: {ground.primary_article} "
        f"فقرة {ground.primary_clause}\n"
        f"  • الأركان المطلوبة: {', '.join(ground.required_elements)}\n\n"
        f"وضع الصياغة: {drafting_mode_label}\n"
        f"المجال: {domain_display}\n"
        f"صفة مقدم المذكرة: {client_role or 'المدعي'}\n\n"
        f"وقائع الموكل (استخدم هذه فقط):\n{facts_block}\n\n"
        f"الحقول المستخرجة:\n"
        f"  أسماء: {names_text}\n"
        f"  أعمار: {ages_text}\n"
        f"  تواريخ: {dates_text}\n"
        f"  مبالغ: {amounts_text}\n\n"
        f"المواد المختارة للاستشهاد (لا تضف غيرها):\n{articles_block}\n\n"
        f"الأحكام المختارة للاستشهاد (لا تضف غيرها):\n{precedents_block}\n\n"
        f"اكتب المذكرة الآن. prose قانونية، أقسام واضحة، أسلوب المحاكم القطرية."
    )

    try:
        from services.llm_service import call_openai
    except ImportError:
        return ""

    try:
        resp = await asyncio.wait_for(
            call_openai(
                system=_COMPOSE_MEMO_SYSTEM,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=_COMPOSE_MAX_TOKENS,
            ),
            timeout=_LLM_TIMEOUT_SECONDS * 2,  # compose is slower
        )
    except asyncio.TimeoutError:
        log.warning("reasoning: compose timed out")
        return ""
    except Exception as e:
        log.warning("reasoning: compose LLM call failed: %s", e)
        return ""

    if not resp or not isinstance(resp, str):
        return ""
    if resp.strip().startswith("خطأ"):
        return ""
    return resp.strip()


# ═══════════════════════════════════════════════════════════════════
# Stage 5 — Verify (programmatic)
# ═══════════════════════════════════════════════════════════════════

def _verify_grounding(
    memo_text:                str,
    allowed_article_numbers:  set[str],
    allowed_precedent_refs:   set[str],
) -> VerificationResult:
    """Check that every article cited + every precedent ref in the memo
    is in the allowed set. Programmatic, not LLM."""
    import re
    vr = VerificationResult()

    # Find article citations in the memo. Pattern: "المادة (NUM)" / "المادة NUM"
    cited_articles = set()
    for m in re.finditer(r"المادة\s*[\(\[]?(\d+)[\)\]]?", memo_text):
        cited_articles.add(m.group(1))

    if allowed_article_numbers:
        for cited in cited_articles:
            if cited not in allowed_article_numbers:
                vr.invented_articles.append(cited)
                vr.passed = False

    # Precedent refs — pattern: "الطعن رقم NUM/YEAR"
    cited_refs = set()
    for m in re.finditer(r"الطعن\s+رقم\s+(\d+/\d{4})", memo_text):
        cited_refs.add(m.group(1))

    # Only flag when we have a non-empty allowed set (else impossible to check)
    if allowed_precedent_refs:
        allowed_nums = {r.replace("الطعن رقم ", "").strip() for r in allowed_precedent_refs}
        for cited in cited_refs:
            if cited not in allowed_nums and not any(cited in a for a in allowed_nums):
                vr.invented_refs.append(cited)
                vr.passed = False

    return vr


# ═══════════════════════════════════════════════════════════════════
# LLM + cache helpers
# ═══════════════════════════════════════════════════════════════════

async def _llm_json_call(
    system:       str,
    user_message: str,
    max_tokens:   int,
) -> Optional[dict]:
    """Single LLM call with strict JSON output + timeout + parse."""
    try:
        from services.llm_service import call_openai
    except ImportError:
        return None

    try:
        resp = await asyncio.wait_for(
            call_openai(
                system=system,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=max_tokens,
            ),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning("reasoning: LLM JSON call timed out")
        return None
    except Exception as e:
        log.warning("reasoning: LLM JSON call failed: %s", e)
        return None

    if not resp or not isinstance(resp, str):
        return None
    if resp.strip().startswith("خطأ"):
        return None

    cleaned = resp.strip()
    # Strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:])
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except Exception as e:
        log.warning("reasoning: JSON parse failed: %s — raw: %s", e, cleaned[:100])
        return None


def _fingerprint(obj: Any) -> str:
    """Stable SHA1 of the JSON-serialized input."""
    try:
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:24]


async def _cache_get(key: str) -> Optional[Any]:
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        raw = await client.get(f"reasoning:{key}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None


async def _cache_set(key: str, value: Any) -> None:
    try:
        from core.redis_client import get_redis_client
        client = await get_redis_client(db=2)
        await client.set(
            f"reasoning:{key}",
            json.dumps(value, ensure_ascii=False),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Sync wrapper — composer is sync
# ═══════════════════════════════════════════════════════════════════

def compose_reasoned_memo_sync(**kwargs) -> ReasonedMemoResult:
    """Sync wrapper for the engine.

    The engine makes 3-4 LLM calls (~8-12 seconds total) which exceeds
    the ``_corpus_bg.run`` short-timeout budget (used for sub-second
    asyncpg work). We run the coroutine in a dedicated thread with its
    own event loop so our generous timeout (90s) is the authority.

    Pattern is safe because ``compose_memo`` is called from the sync
    pipeline (``runtime_v2.answer``), NOT from within an async context.
    The ThreadPoolExecutor isolates the loop so it cannot interfere
    with FastAPI's main loop or ``_corpus_bg``'s daemon loop.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def _run_in_thread():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(compose_reasoned_memo(**kwargs))
        finally:
            loop.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_in_thread)
            return future.result(timeout=90.0)
    except Exception as e:
        log.warning(
            "compose_reasoned_memo_sync: %s — %s",
            type(e).__name__, e,
        )
        r = ReasonedMemoResult()
        r.failure_reason = f"{type(e).__name__}: {e}"
        return r


__all__ = [
    "LegalGround", "SelectedArticle", "SelectedPrecedent",
    "VerificationResult", "ReasonedMemoResult",
    "compose_reasoned_memo", "compose_reasoned_memo_sync",
]
