# -*- coding: utf-8 -*-
"""
core/precedent_linker.py — Phase 2 · Layer 2: Precedent Linker
==============================================================

Links legal queries to relevant Qatari Tamyeez court principles.
11,452 rulings live in `chunks` (no separate table) distinguished by
`law_name ILIKE '%أحكام محكمة التمييز%'`. All have embeddings + domain +
content_tsv, so retrieval is a single vector+FTS+domain query.

Two kinds of rulings in the data:
  1. مبدأ (principle)     — 4,885 chunks — short summaries with structured
                             headers like "مبدأ قضائي — محكمة التمييز —
                             الطعن 270/2013:" — PREFERRED for prompt
                             injection (compact, case-numbered).
  2. حكم نص (ruling text) — 5,482 chunks — long legal prose, case number
                             often absent from the chunk (~54% of all
                             chunks have no detectable case number).
  3. other                — 1,085 chunks — non-standard `article_number`.

Integration points (for rollback):
  • routers/query_router.py :: handle_general — inject _precedent_block
    into system prompt right after _concept_context (~line 1087).
  • core/runtime_v2/composer.py :: compose_memo — replace the static
    rulings bank with find_relevant_precedents() output.

Kill switch (no redeploy):
  Set PRECEDENT_LINKER_ENABLED=false in the environment → every public
  function short-circuits to a no-op / empty list.

Rollback:
  git revert <commit-sha>   (single file additions + two small edits)

Cost budget: MAX_PRECEDENT_TOKENS (default 400) enforced in
build_precedent_block — the block is truncated before it can bloat the
prompt. Rough estimate: 1 token ≈ 3 Arabic chars.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Configuration — env-driven, safe defaults
# ═══════════════════════════════════════════════════════════════════════

PRECEDENT_LINKER_ENABLED = os.getenv(
    "PRECEDENT_LINKER_ENABLED", "true"
).lower() == "true"

PRECEDENT_THRESHOLD = float(os.getenv("PRECEDENT_THRESHOLD", "0.72"))
PRECEDENT_TOP_K = int(os.getenv("PRECEDENT_TOP_K", "3"))
MAX_PRECEDENT_TOKENS = int(os.getenv("MAX_PRECEDENT_TOKENS", "400"))

# D1: principle boost. When >1 precedent sits near the threshold, a
# principle (مبدأ) is preferred over a ruling-text (حكم نص) because
# principles are case-numbered summaries designed for citation.
# +0.03 is enough to break near-ties but small enough not to force a
# lower-quality principle over a clearly-more-relevant ruling text.
PRINCIPLE_BOOST = float(os.getenv("PRECEDENT_PRINCIPLE_BOOST", "0.03"))

# CP3 · H5 — HNSW search beam (ef_search). Higher = better recall at
# cost of latency. Default 200 matches the CP1 sweep (no measurable
# latency impact observed). Clamped to [40, 5000] to guard against
# accidental misconfiguration.
HNSW_EF_SEARCH = max(40, min(5000, int(os.getenv("HNSW_EF_SEARCH", "200"))))

# Logs: every hallucination attempt + every displaced ruling text are
# appended so we can audit the linker's behavior over time.
_LOG_DIR = Path(os.getenv("PRECEDENT_LOG_DIR", "/app/logs"))
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:  # pragma: no cover — logs dir may be read-only in some envs
    pass
_HALLUCINATION_LOG = _LOG_DIR / "precedent_hallucinations.log"
_DISPLACEMENT_LOG = _LOG_DIR / "precedent_displacements.log"
_AUGMENTATION_LOG = _LOG_DIR / "precedent_augmentation.log"
# CP3.3 — per-invocation metrics used by the cost-measurement harness.
# One JSON line per call to find_relevant_precedents_augmented. Kept
# separate from the other logs (which are free-form text) so the
# measurement script can parse cleanly.
_COST_METRICS_LOG = _LOG_DIR / "cost_metrics.jsonl"
# CP3 · G5 — log-only metric. Records cases where the caller-provided
# corpus_domain disagrees with the strong signal inferred from concepts
# + query keywords. We DO NOT override (out of scope this session),
# but this builds a dataset for a future standalone layer.
_DOMAIN_MISMATCH_LOG = _LOG_DIR / "domain_mismatch.log"
# Threshold: only log when the dissenting signal has ≥3 hits.
_DOMAIN_MISMATCH_MIN_SIGNALS = 3


def _feature_flag() -> bool:
    """Kill-switch check — call at the top of every public entry point."""
    return PRECEDENT_LINKER_ENABLED


# ═══════════════════════════════════════════════════════════════════════
# Case-number regex patterns (tested: 42/100 hits, 0 false positives)
# ═══════════════════════════════════════════════════════════════════════

CASE_NUMBER_PATTERNS: List[re.Pattern] = [
    # P1 — most common (38/100 hits): الطعن رقم 127/2013
    re.compile(r"الطعن\s+رقم\s+(\d+)\s*/\s*(\d{4})"),
    # P2 — الطعن 270/2013 (no explicit رقم) — 2/100
    re.compile(r"الطعن\s+(\d+)\s*/\s*(\d{4})"),
    # P3 — الطعن رقم X لسنة Y — 2/100
    re.compile(r"الطعن\s+رقم\s+(\d+)\s+لسنة\s+(\d{4})"),
    # P4 — الطعن X لسنة Y (no رقم) — 0/100 (defensive)
    re.compile(r"الطعن\s+(\d+)\s+لسنة\s+(\d{4})"),
    # P5 — طعن رقم X/Y (no ال prefix) — 0/100 (defensive)
    re.compile(r"(?<!\S)طعن\s+رقم\s+(\d+)\s*/\s*(\d{4})"),
    # P6 — طعن X/Y (no ال prefix) — 0/100 (defensive)
    re.compile(r"(?<!\S)طعن\s+(\d+)\s*/\s*(\d{4})"),
    # P7 — الطعن بالتمييز رقم X/Y — user-added in D2
    re.compile(r"الطعن\s+بالتمييز\s+رقم\s+(\d+)\s*/\s*(\d{4})"),
]

# TODO(future): dual/multi-petition forms — e.g.
#   "الطعنان رقما 123 و 124 لسنة 2020"  (dual)
#   "الطعون أرقام 5 و 6 و 7 لسنة 2021"  (multi)
# These are rare in the sampled 100 chunks; handle when data shows need.

# TODO(future): uncommon phrasings like
#   "قيد تحت رقم 123/2020"
#   "قُبلت تحت الرقم 123/2020"
# Not observed in the 100-chunk FP test; defer until empirically needed.


def _year_valid(y: str) -> bool:
    try:
        return 1970 <= int(y) <= 2030
    except ValueError:
        return False


def _case_num_valid(n: str) -> bool:
    try:
        return 1 <= int(n) <= 99999
    except ValueError:
        return False


def _extract_case_number(content: str) -> Optional[str]:
    """Try each CASE_NUMBER_PATTERNS in order, return first match
    formatted as `"123/2020"`. Returns None if no valid pattern hits."""
    if not content:
        return None
    for pat in CASE_NUMBER_PATTERNS:
        m = pat.search(content)
        if not m:
            continue
        case_num, year = m.group(1), m.group(2)
        if _case_num_valid(case_num) and _year_valid(year):
            return f"{case_num}/{year}"
    return None


# ═══════════════════════════════════════════════════════════════════════
# Precedent dataclass
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Precedent:
    chunk_id: int
    content: str
    domain: str          # 'مدني' | 'جنائي' | 'عام' | other
    kind: str            # 'principle' | 'ruling_text' | 'other'
    similarity_raw: float
    similarity_boosted: float
    case_number: Optional[str]  # "123/2020" or None (~54% are None)
    article_number: str
    # D3: internal_ref — used by the guard to track case-less rulings
    internal_ref: str = field(init=False)

    def __post_init__(self) -> None:
        self.internal_ref = f"chunk:{self.chunk_id}"

    @property
    def display_ref(self) -> str:
        """Human-friendly citation. Falls back to 'مبدأ مستقر لمحكمة التمييز'
        when no case number is extractable (D3)."""
        if self.case_number:
            return f"الطعن رقم {self.case_number}"
        # fallback — keep domain hint so the reader understands the context
        return f"مبدأ مستقر لمحكمة التمييز ({self.domain})"


def _classify_kind(article_number: str) -> str:
    """Map `article_number` to kind category."""
    if not article_number:
        return "other"
    if article_number.startswith("مبدأ-تمييز-"):
        return "principle"
    if article_number.startswith("حكم-تمييز-") and "-نص-" in article_number:
        return "ruling_text"
    return "other"


# ═══════════════════════════════════════════════════════════════════════
# Concept → Domain affinity (D4 support)
# ═══════════════════════════════════════════════════════════════════════
#
# Tamyeez rulings live in only 3 domain buckets: مدني | جنائي | عام.
# When the query's domain is unknown or 'عام', we use the concepts
# detected by legal_concepts to pick the closest bucket.

CONCEPT_DOMAIN_AFFINITY = {
    # Criminal
    "القصد الجنائي":      "جنائي",
    "الشروع":             "جنائي",
    "العود":              "جنائي",
    "رد الاعتبار":        "جنائي",
    "قرينة البراءة":      "جنائي",
    "الاعتراف القضائي":   "جنائي",
    "التقادم الجنائي":    "جنائي",
    "التصالح":            "جنائي",
    # Civil / procedural (Tamyeez treats labor + family as مدني)
    "الدفع الجوهري":      "مدني",
    "الدفع الموضوعي":     "مدني",
    "الدفع الشكلي":       "مدني",
    "الدفع بعدم القبول":  "مدني",
    "السلطة الولائية":    "مدني",
    "السلطة القضائية":    "مدني",
    "حجية الأمر المقضي":  "مدني",
    "الصفة":              "مدني",
    "المصلحة":            "مدني",
    "البطلان الإجرائي":   "مدني",
    "الحضانة":            "مدني",
    "الخلع":              "مدني",
    "الفصل التعسفي":      "مدني",
}


def _closest_domain_from_concepts(concepts: List[str]) -> Optional[str]:
    """Majority-vote the concepts onto {مدني, جنائي}. None if no concept
    has a known affinity."""
    tallies = {"مدني": 0, "جنائي": 0}
    for c in concepts or []:
        aff = CONCEPT_DOMAIN_AFFINITY.get(c)
        if aff in tallies:
            tallies[aff] += 1
    best = max(tallies, key=tallies.get)
    return best if tallies[best] > 0 else None


# ═══════════════════════════════════════════════════════════════════════
# CP2 · E2 — Query augmentation for precedent embedding
# ─────────────────────────────────────────────────────────────────────
# Colloquial queries ("نزاع بين مالك ومستأجر…") embed far from formal
# Tamyeez prose. We build a SEPARATE augmented query string that adds
# 3-5 formal legal terms derived from:
#   (a) detected concepts (from core.legal_concepts) and
#   (b) a small built-in colloquial → legal phrase map.
#
# The augmented string is ONLY used for the precedent embedding — the
# original query is NOT modified and all existing pipelines (search(),
# _expand_legal_query, rule_based_cot) remain untouched (user's E2
# constraint).
# ═══════════════════════════════════════════════════════════════════════

# Concept → formal legal terms to append. Keeps augmentation minimal
# (avoid ballooning the embedding input with repeats of the same vocab).
_CONCEPT_LEGAL_HINTS = {
    "الصفة":              ["الصفة في الدعوى", "انعدام الصفة"],
    "المصلحة":            ["المصلحة في الدعوى", "لا دعوى بغير مصلحة"],
    "الدفع الجوهري":      ["القصور في التسبيب", "الإخلال بحق الدفاع"],
    "الدفع الشكلي":       ["بطلان الصحيفة", "الاختصاص المكاني"],
    "الدفع الموضوعي":     ["أصل الحق", "التقادم المدني"],
    "الدفع بعدم القبول":  ["انتفاء الصفة", "سبق الفصل"],
    "الحضانة":            ["إسقاط الحضانة", "الولاية على المحضون"],
    "الخلع":              ["الطلاق البائن", "بدل الخلع"],
    "الفصل التعسفي":      ["إنهاء عقد العمل", "التعويض عن الفصل"],
    "القصد الجنائي":      ["الأركان المادية والمعنوية", "انتفاء القصد"],
    "الشروع":             ["البدء في التنفيذ", "الجريمة التامة"],
    "العود":              ["تشديد العقوبة للعود", "السوابق"],
    "رد الاعتبار":        ["محو آثار الحكم", "صحيفة السوابق"],
    "حجية الأمر المقضي":  ["قوة الحكم النهائي", "وحدة الخصوم والموضوع"],
    "قرينة البراءة":      ["عبء الإثبات على النيابة", "تفسير الشك"],
    "الاعتراف القضائي":   ["طوعية الاعتراف", "تقدير الدليل"],
    "التقادم الجنائي":    ["انقضاء الدعوى الجنائية", "المادة 14 إجراءات"],
    "التصالح":            ["التنازل عن الحق", "انقضاء الدعوى"],
    "البطلان الإجرائي":   ["بطلان مطلق", "النظام العام"],
    "السلطة الولائية":    ["أوامر الأداء", "التظلم"],
    "السلطة القضائية":    ["الحكم القضائي", "الطعن بالاستئناف"],
}

# Colloquial phrase → formal legal diction. Ordered by specificity
# (longer/more specific matches first to avoid shadowing).
_COLLOQUIAL_LEGAL_MAP = [
    # — إيجار / سكن —
    ("مالك ومستأجر",      "عقد إيجار بين المؤجر والمستأجر"),
    ("تأخر السداد",        "إخلال بأداء الأجرة"),
    ("طلع من البيت",       "دعوى إخلاء المأجور"),
    # — عمل / فصل —
    ("فصلني",              "الفصل التعسفي إنهاء عقد العمل"),
    ("طردني",              "الفصل التعسفي"),
    ("صاحب العمل",         "رب العمل إنهاء العلاقة العمالية"),
    ("ما عطاني راتبي",     "استحقاق الأجر مكافأة نهاية الخدمة"),
    # — أسرة / طلاق / نفقة —
    ("ما ينفق",            "امتناع الزوج عن الإنفاق نفقة زوجية"),
    ("لا ينفق",            "امتناع الزوج عن الإنفاق نفقة زوجية"),
    ("تطلقت",              "فرقة زوجية طلاق عدة نفقة"),
    ("يضربني",             "الضرر الزوجي التطليق للضرر"),
    ("ياخذ الاطفال",       "نزاع الحضانة ضم المحضون"),
    # — جنائي —
    ("سرق",                "جريمة السرقة خيانة الأمانة المادة 354"),
    ("سرقني",              "جريمة السرقة"),
    ("هددني",              "جريمة التهديد الابتزاز"),
    ("نصب علي",            "جريمة الاحتيال النصب"),
    # — مدني عام —
    ("نزاع",               "دعوى قضائية"),
    ("محكمة",              "اختصاص قضائي أحكام المحكمة"),
    ("مبلغ",               "الدين الالتزام المالي"),
]

# Token budget for the augmented string — keep small so embedding
# model doesn't dilute signal. Roughly: original query + up to ~80 chars
# of legal hints.
_AUGMENT_MAX_HINT_CHARS = 140


def _augment_query_for_precedent_embedding(
    query: str,
    concepts: Optional[List[str]] = None,
) -> str:
    """Build an augmented version of the query designed to land closer
    to formal Tamyeez prose in the embedding space.

    Returns the augmented string. If no augmentation signals fire, the
    original query is returned unchanged. The augmented string is used
    ONLY for the precedent embedding — never returned to the user or
    stored in history.
    """
    if not query:
        return query
    q = query.strip()
    hints: List[str] = []
    seen: set = set()

    # (a) concept-based hints
    for c in (concepts or []):
        for h in _CONCEPT_LEGAL_HINTS.get(c, []):
            if h and h not in seen:
                seen.add(h)
                hints.append(h)

    # (b) colloquial-phrase mapping
    q_lc = q  # Arabic has no case; work on the raw form
    for colloquial, formal in _COLLOQUIAL_LEGAL_MAP:
        if colloquial in q_lc and formal not in seen:
            seen.add(formal)
            hints.append(formal)

    if not hints:
        return q

    # Budget: trim hints list to fit _AUGMENT_MAX_HINT_CHARS
    used = 0
    picked: List[str] = []
    for h in hints:
        cost = len(h) + 2  # + "، "
        if used + cost > _AUGMENT_MAX_HINT_CHARS:
            break
        picked.append(h)
        used += cost
    if not picked:
        return q

    augmented = f"{q}  [سياق قانوني: {'، '.join(picked)}]"
    return augmented


def _log_augmentation(
    original: str,
    augmented: str,
    n_before,              # int | None — None means "not measured"
    n_after: int,
) -> None:
    """Append one line per augmented query so we can measure the lift
    quantitatively in Check-point 3. `n_before=None` is allowed — it
    signals that we did NOT incur the double-retrieval cost (the q6
    fix). The log row shows `before=skipped Δ=?` in that case."""
    if original == augmented:
        return  # no-op augmentation — nothing to log
    try:
        import datetime as _dt
        with _AUGMENTATION_LOG.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
            orig_snip = original.replace("\n", " ")[:120]
            aug_snip = augmented.replace("\n", " ")[:200]
            if n_before is None:
                before_txt = "skipped"
                delta_txt = "?"
            else:
                before_txt = str(n_before)
                delta_txt = f"{n_after - n_before:+d}"
            f.write(
                f"{ts}Z  before={before_txt}  after={n_after}  "
                f"Δ={delta_txt}  "
                f"original=«{orig_snip}»  augmented=«{aug_snip}»\n"
            )
    except Exception:  # pragma: no cover
        pass


# ═══════════════════════════════════════════════════════════════════════
# Core retrieval
# ═══════════════════════════════════════════════════════════════════════

async def find_relevant_precedents(
    *,
    query_embedding: List[float],
    domain: Optional[str],
    concepts: Optional[List[str]] = None,
    top_k: int = PRECEDENT_TOP_K,
    threshold: float = PRECEDENT_THRESHOLD,
    pool=None,  # asyncpg pool; if None uses core.app_state.pool
    _timing: Optional[dict] = None,  # CP3.3-INVESTIGATION: layer breakdown
) -> List[Precedent]:
    """
    Retrieve the top-k Tamyeez precedents relevant to the query.

    Arguments:
        query_embedding: 768-dim vector of the user query (caller already
                         has this — we do NOT re-embed).
        domain:          'مدني' | 'جنائي' | 'عام' | None (unknown).
        concepts:        list of concept names (from legal_concepts) —
                         used to pick a bucket when domain is None/'عام'.
        top_k:           max precedents to return (default 3).
        threshold:       minimum RAW similarity before any boost.
        pool:            asyncpg pool; defaults to core.app_state.pool.

    Returns:
        list[Precedent] — sorted by similarity_boosted desc. Empty if
        the feature flag is off, similarity cap not reached, or DB
        unreachable. NEVER raises — caller gets degraded-open behavior.

    D4 semantics:
        domain is None  → scan all 3 buckets, concepts guide re-ranking
        domain == 'عام' → scan 'عام' + closest-domain-by-concepts only
        domain in {مدني, جنائي} → scan that bucket only
    """
    if not _feature_flag():
        return []
    if not query_embedding:
        return []

    # Resolve pool
    if pool is None:
        try:
            from core import app_state as _app_state
            pool = _app_state.pool
        except Exception as e:
            log.warning("precedent_linker: cannot get pool: %s", e)
            return []
    if pool is None:
        log.warning("precedent_linker: pool is None, skipping")
        return []

    concepts = concepts or []
    domain_filter = _resolve_domain_filter(domain, concepts)

    # Build the IN-list fragment safely (domain is whitelist-derived — no SQL injection surface)
    if domain_filter is None:
        domain_where = ""
        domain_args: list = []
        arg_offset = 0
    else:
        placeholders = ", ".join(f"${i + 2}" for i in range(len(domain_filter)))
        domain_where = f"AND domain IN ({placeholders})"
        domain_args = list(domain_filter)
        arg_offset = len(domain_filter)

    fetch_k = top_k * 3  # overfetch → dedup + rerank → return top_k
    limit_param_idx = 2 + arg_offset  # $2, $3... then the limit

    sql = f"""
    SELECT
        id, content, domain, article_number,
        1 - (embedding <=> $1::vector) AS similarity
    FROM chunks
    WHERE is_active = true
      AND law_name ILIKE '%أحكام محكمة التمييز%'
      {domain_where}
    ORDER BY embedding <=> $1::vector
    LIMIT ${limit_param_idx};
    """

    # asyncpg wants embedding as a string like "[0.1,0.2,...]"
    emb_str = "[" + ",".join(f"{float(x):.6f}" for x in query_embedding) + "]"
    params = [emb_str, *domain_args, fetch_k]

    import time as _t_mod
    _t_sql_start = _t_mod.perf_counter()
    try:
        # CP2 · E3: SET LOCAL hnsw.ef_search=200 inside a transaction.
        # Scoped to this one query — doesn't affect other DB users.
        # Costs ~0 but noticeably improves recall for queries that
        # land in sparse regions of the vector index.
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Transaction-scoped — doesn't leak to other queries.
                await conn.execute(
                    f"SET LOCAL hnsw.ef_search = {int(HNSW_EF_SEARCH)};"
                )
                rows = await conn.fetch(sql, *params)
    except Exception as e:
        log.warning("precedent_linker SQL failed: %s", e)
        if _timing is not None:
            _timing.setdefault("sql_ms_list", []).append(
                round((_t_mod.perf_counter() - _t_sql_start) * 1000, 2))
        return []
    if _timing is not None:
        _timing.setdefault("sql_ms_list", []).append(
            round((_t_mod.perf_counter() - _t_sql_start) * 1000, 2))

    # Build Precedents, filter by threshold, dedupe, rank
    _t_postproc_start = _t_mod.perf_counter()
    precedents: List[Precedent] = []
    for row in rows:
        sim = float(row["similarity"])
        if sim < threshold:
            continue
        kind = _classify_kind(row["article_number"] or "")
        boost = PRINCIPLE_BOOST if kind == "principle" else 0.0
        p = Precedent(
            chunk_id=row["id"],
            content=row["content"] or "",
            domain=row["domain"] or "",
            kind=kind,
            similarity_raw=sim,
            similarity_boosted=sim + boost,
            case_number=_extract_case_number(row["content"] or ""),
            article_number=row["article_number"] or "",
        )
        precedents.append(p)

    if not precedents:
        return []

    # Dedup by case_number (keep highest similarity_boosted)
    seen_case: dict = {}
    seen_internal: dict = {}
    for p in precedents:
        key = p.case_number or p.internal_ref
        if key in seen_case:
            if p.similarity_boosted > seen_case[key].similarity_boosted:
                seen_case[key] = p
        else:
            seen_case[key] = p
        seen_internal[p.internal_ref] = p

    # Sort by boosted similarity desc; tie-break on raw similarity
    final = sorted(
        seen_case.values(),
        key=lambda p: (p.similarity_boosted, p.similarity_raw),
        reverse=True,
    )[:top_k]

    # D1 displacement log — when a ruling_text is displaced by a
    # principle with LOWER raw similarity
    try:
        _log_displacements(precedents, final)
    except Exception as e:  # pragma: no cover
        log.debug("precedent displacement logging failed: %s", e)

    if _timing is not None:
        _timing.setdefault("postproc_ms_list", []).append(
            round((_t_mod.perf_counter() - _t_postproc_start) * 1000, 2))
    return final


# ═══════════════════════════════════════════════════════════════════════
# CP2 · F3-defensive — map corpus domains → Tamyeez buckets
# ─────────────────────────────────────────────────────────────────────
# The main corpus (core.nlp_utils.detect_legal_domain) returns a finer
# taxonomy: جنائي/مدني/تجاري/عمالي/أسري/… — but Tamyeez rulings only
# have three buckets: مدني, جنائي, عام. We map here WITHOUT touching
# rule_based_cot or detect_legal_domain (user's F3 constraint).
#
# When the mapping is ambiguous (e.g. "تجاري" could go either way),
# we return None → the caller scans all buckets and re-ranks. This is
# the "defensive domain=None" fallback requested in F3.
# ═══════════════════════════════════════════════════════════════════════

_CORPUS_TO_TAMYEEZ_DOMAIN = {
    # ─── Arabic labels (from our own domain metadata) ───
    "جنائي":    "جنائي",
    "مدني":     "مدني",
    "عمالي":    "مدني",   # labor cases live under civil in Tamyeez
    "أسري":     "مدني",   # family too
    "تجاري":    "مدني",   # commercial too
    "عقاري":    "مدني",
    "مالي":     "مدني",
    "إداري":    "عام",
    "دستوري":   "عام",
    # ─── English codes (from core.nlp_utils._LEGAL_DOMAINS) ───
    # CP3 G2 fix: detect_legal_domain returns English keys, not Arabic.
    # Previously these all fell through to None → 3-bucket spillover.
    "criminal":       "جنائي",
    "civil":          "مدني",
    "family":         "مدني",   # Tamyeez treats family as civil
    "commercial":     "مدني",
    "labor":          "مدني",
    "property":       "مدني",
    "insurance":      "مدني",
    "administrative": "عام",
    "cyber":          "جنائي",  # cyber crimes are penal
    # Intentionally ambiguous — return None (scan all):
    # "procedural"          → could be civil OR criminal procedure
    # "تقني/بحري/جمركي/بيئي/مخدرات" → let caller scan all
}


def map_corpus_domain_to_tamyeez(corpus_domain: Optional[str]) -> Optional[str]:
    """Map a corpus-side domain label (from nlp_utils.detect_legal_domain)
    to one of {'مدني', 'جنائي', 'عام'} used by Tamyeez rulings, or None
    to signal "scan all buckets"."""
    if not corpus_domain:
        return None
    return _CORPUS_TO_TAMYEEZ_DOMAIN.get(corpus_domain)


# ═══════════════════════════════════════════════════════════════════════
# CP3 · G2 defensive override — concept+keyword signal inference
# ─────────────────────────────────────────────────────────────────────
# Runs ONLY when map_corpus_domain_to_tamyeez(...) returns None. Reads
# two independent signals from the query + detected legal concepts:
#
#   (1) Legal-concept affinity: CONCEPT_DOMAIN_AFFINITY tallies
#   (2) Explicit keyword presence in the raw query text
#
# If EITHER signal is strong (≥2 hits in one bucket AND 0 in the other),
# force that bucket. Conservative by design — when the signal is mixed
# or weak, we leave the mapper's None intact and let the full-scan
# fallback run (cost: a few extra candidates, not correctness).
# Every override is logged to /app/logs/precedent_augmentation.log
# with a [domain-override] tag so we can audit it in CP3 telemetry.
# ═══════════════════════════════════════════════════════════════════════

# Strong civil-side query keywords (seen in real rental/labor/family/
# commercial queries). Kept short — each adds only 1 point so we don't
# over-trigger.
_CIVIL_QUERY_KEYWORDS = (
    # عقود/إيجار
    "عقد", "فسخ", "إيجار", "ايجار", "مؤجر", "مستأجر", "مالك",
    "أجرة", "الاجرة", "إخلال بالأجرة", "اخلال بالاجره",
    # عمل
    "فصل تعسفي", "مكافأة", "مكافاه", "إنذار", "رب العمل",
    "نهاية الخدمة",
    # أسرة
    "نفقة", "نفقه", "حضانة", "حضانه", "طلاق", "خلع",
    "مهر", "عدة",
    # مدني عام
    "تعويض مدني", "التزام", "دين", "ملكية", "ميراث", "وصية",
    # شركات/تجاري
    "شركة", "شراكة", "مساهم", "إفلاس", "تصفية",
)

# Strong criminal-side query keywords. Tight selection — avoid generic
# words like "مشكلة" that cross domains.
_CRIMINAL_QUERY_KEYWORDS = (
    "متهم", "جريمة", "جريمه", "عقوبة", "عقوبه",
    "سرقة", "سرق", "قتل", "قتلت",
    "اعتراف", "قصد جنائي", "سوابق", "ظرف مشدد",
    "رشوة", "رشوه", "ابتزاز", "تهديد", "احتيال", "نصب",
    "تزوير", "مخدرات", "حشيش", "تعاطي",
    "اعتداء", "ضرب", "إيذاء", "قذف", "سب",
    "اختلاس", "خيانة أمانة", "خيانة الامانة",
    "النيابة العامة", "الطعن بالنقض",
)


def _count_keyword_hits(text: str, keywords: tuple) -> int:
    """Case-insensitive substring counter for Arabic keywords. Each
    distinct keyword contributes at most 1 point (prevents the same
    word repeated in the query from inflating the score)."""
    if not text:
        return 0
    t = text.lower()
    hits = 0
    for kw in keywords:
        if kw.lower() in t:
            hits += 1
    return hits


def _infer_domain_from_signals(
    query: str,
    concepts: List[str],
) -> Optional[str]:
    """Defensive inference from query + concepts when the direct mapper
    returned None. Returns 'مدني' / 'جنائي' / None (still ambiguous).

    Decision rule (conservative):
        • civil_score  = civil concept hits  + civil keyword hits
        • criminal_score = criminal concept hits + criminal keyword hits
        • If civil_score ≥ 2 AND criminal_score == 0 → 'مدني'
        • If criminal_score ≥ 2 AND civil_score == 0 → 'جنائي'
        • Otherwise → None (leave decision to the full-scan fallback)
    """
    # Concept-side tallies (reuse existing CONCEPT_DOMAIN_AFFINITY)
    civil_from_concepts = 0
    crim_from_concepts = 0
    for c in concepts or []:
        aff = CONCEPT_DOMAIN_AFFINITY.get(c)
        if aff == "مدني":
            civil_from_concepts += 1
        elif aff == "جنائي":
            crim_from_concepts += 1

    # Keyword-side tallies
    civil_from_kw = _count_keyword_hits(query or "", _CIVIL_QUERY_KEYWORDS)
    crim_from_kw = _count_keyword_hits(query or "", _CRIMINAL_QUERY_KEYWORDS)

    civil_score = civil_from_concepts + civil_from_kw
    crim_score = crim_from_concepts + crim_from_kw

    if civil_score >= 2 and crim_score == 0:
        return "مدني"
    if crim_score >= 2 and civil_score == 0:
        return "جنائي"
    return None


# ═══════════════════════════════════════════════════════════════════════
# CP3.3 — Skip the linker entirely for short/definitional questions
# ─────────────────────────────────────────────────────────────────────
# Definitional queries ("ما عقوبة السرقة؟") want the text of the article,
# not case citations. Injecting precedents wastes tokens + latency AND
# risks noise. We skip when ALL of these hold:
#   1. the caller did NOT tell us this is a memo,
#   2. the query has no digits (digits ≈ concrete facts ≈ a case),
#   3. the query has no explicit "case" keywords (موكل/قضية/دعوى/…),
#   4. the query is ≤ 6 words.
# When skipped, the linker returns [] immediately — no SQL, no embed,
# no block, no guard. One log line per skip for auditability.
# ═══════════════════════════════════════════════════════════════════════

# Explicit case-indicating words. Presence of any ONE of these disables
# the skip (the query carries a case frame even if short).
_CASE_KEYWORDS: tuple = (
    "موكل", "موكلي", "موكلتي",
    "قضية", "قضيتي", "قضيه",
    "دعوى", "دعواي", "دعوه",
    "مذكرة", "مذكره",
    "شكوى", "شكواي", "شكوه",
    "اتهام", "متهم", "المتهم",
    "معاملة", "معاملتي",
    "نزاع", "نزاعي",
)

# Skip telemetry — separate log so the cost-measurement harness can
# count how often we avoided an expensive retrieval.
_SKIP_LOG = _LOG_DIR / "precedent_skipped_short_query.log"


# Definitional interrogative prefixes — queries starting with these
# are "what is X / what are the conditions of Y / what is the penalty
# for Z"-style questions. Precedents add noise, not value, to the
# answer. A query that STARTS with one of these skips the linker
# regardless of length (as long as digits + case keywords are absent).
_DEFINITIONAL_PREFIXES = (
    "ما هو", "ما هي", "ما تعريف", "ما المقصود",
    "ما معنى", "ما شروط", "ما هي شروط",
    "ما عقوبة", "ما هي عقوبة", "ما الفرق",
    "ما الأحكام", "ما أحكام",
    "كيف يُعرّف", "كيف تُعرَّف", "كيف يتم تعريف",
)


def _should_skip_linker(
    query: str,
    phase0_class: Optional[str] = None,
    concepts: Optional[List[str]] = None,
) -> bool:
    """Pure function. Returns True iff the linker should short-circuit
    to [] for this query. Designed to be unit-testable in isolation —
    no side effects, no DB, no logs.

    Skip applies when EITHER:
      (A) the query STARTS with a definitional interrogative
          ("ما هو/هي/عقوبة/…") AND has no digits AND no case keyword
          (length doesn't matter — "ما هو التقادم في القانون القطري"
           is still definitional even at 7 words);
      OR (B) ALL of these shorter-form conditions hold:
          • phase0_class != "memo"
          • no formal legal concepts detected
          • no digits in the query
          • no explicit case keyword (موكل/قضية/دعوى/…)
          • word count ≤ 6
    """
    q = (query or "").strip()
    if not q:
        return True
    # ── (M) Memo context → ALWAYS run the linker, regardless of length ──
    if phase0_class == "memo":
        return False
    # ── (D) Facts-ish overrides that NEVER skip ──
    if re.search(r"\d", q):
        return False
    for kw in _CASE_KEYWORDS:
        if kw in q:
            return False
    # ── (A) Definitional-interrogative prefix → skip (any length) ──
    for pfx in _DEFINITIONAL_PREFIXES:
        if q.startswith(pfx):
            return True
    # ── (B) Short-query rule ──
    # Concepts flag was once a skip-disabler, but a short non-definitional
    # query WITH concepts (e.g. "فسخ عقد الإيجار للإخلال بأداء الأجرة")
    # IS a situational query — respect concepts here so p1-style civil
    # scenarios still retrieve precedents.
    if concepts:
        return False
    if len(q.split()) > 6:
        return False
    return True


def _log_skip(query: str, phase0_class: Optional[str]) -> None:
    """Append one line per skipped retrieval. Kept cheap — fire-and-forget."""
    try:
        import datetime as _dt
        with _SKIP_LOG.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
            q_snip = (query or "").replace("\n", " ")[:120]
            f.write(
                f"{ts}Z  phase0_class={phase0_class!r}  "
                f"query=«{q_snip}»\n"
            )
    except Exception:  # pragma: no cover
        pass


def _log_domain_mismatch(
    query: str,
    detected: Optional[str],           # raw from detect_legal_domain
    mapped: Optional[str],             # after map_corpus_domain_to_tamyeez
    concept_suggested: str,            # what signals say it should be
    final_used: Optional[str],         # what we actually used
    civil_score: int,
    crim_score: int,
) -> None:
    """CP3 · G5 metric — LOG ONLY, no action taken. Fires when the
    caller's corpus_domain (after mapping) disagrees with the strong
    concept+keyword signal (≥3 hits in the dissenting bucket). Builds
    evidence for a future standalone layer."""
    try:
        import datetime as _dt
        with _DOMAIN_MISMATCH_LOG.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
            q_snip = (query or "").replace("\n", " ")[:120]
            # Format per user spec: query | detected | concept_suggested | final_used
            f.write(
                f"{ts}Z | q=«{q_snip}» | "
                f"detected={detected!r} | mapped={mapped!r} | "
                f"concept_suggested={concept_suggested!r} | "
                f"final_used={final_used!r} | "
                f"civil={civil_score} crim={crim_score}\n"
            )
    except Exception:  # pragma: no cover
        pass


def _log_domain_override(
    query: str,
    corpus_domain: Optional[str],
    inferred: str,
    civil_score: int,
    crim_score: int,
) -> None:
    """Append a line to the augmentation log whenever the defensive
    override kicks in. Tagged with [domain-override] so CP3 analysis
    can filter."""
    try:
        import datetime as _dt
        with _AUGMENTATION_LOG.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
            q_snip = (query or "").replace("\n", " ")[:100]
            f.write(
                f"{ts}Z  [domain-override]  "
                f"corpus={corpus_domain!r} → tamyeez={inferred!r}  "
                f"civil={civil_score} crim={crim_score}  "
                f"q=«{q_snip}»\n"
            )
    except Exception:  # pragma: no cover
        pass


def _resolve_domain_filter(
    domain: Optional[str],
    concepts: List[str],
) -> Optional[Tuple[str, ...]]:
    """D4 routing → return tuple of domain values to include in SQL, or
    None to disable the domain filter."""
    TAMYEEZ_DOMAINS = {"مدني", "جنائي", "عام"}

    if domain is None:
        # Unknown → scan all three; re-ranking in Python uses concepts implicitly
        return None

    if domain == "عام":
        # D4 — scan 'عام' + closest_domain_by_concepts only
        closest = _closest_domain_from_concepts(concepts)
        if closest in {"مدني", "جنائي"}:
            return ("عام", closest)
        # No concept signal → just 'عام'
        return ("عام",)

    if domain in TAMYEEZ_DOMAINS:
        return (domain,)

    # Unknown legal domain (e.g. 'عمالي', 'أسري' from the main corpus)
    # Tamyeez doesn't subdivide that finely → fallback to مدني (where
    # labor/family live in Tamyeez index).
    fallback = _closest_domain_from_concepts(concepts) or "مدني"
    return (fallback, "عام")


def _log_displacements(all_candidates: List[Precedent],
                       chosen: List[Precedent]) -> None:
    """Record every حكم نص that had a higher raw similarity than a chosen
    principle — so we can audit whether the +0.03 boost is too aggressive."""
    chosen_ids = {p.chunk_id for p in chosen}
    # Top-N raw-similarity candidates that did NOT make the cut
    displaced = [
        p for p in all_candidates
        if p.chunk_id not in chosen_ids and p.kind == "ruling_text"
    ]
    if not displaced:
        return
    principles_chosen = [p for p in chosen if p.kind == "principle"]
    if not principles_chosen:
        return

    # For each principle in chosen, flag any ruling_text in displaced
    # whose raw similarity was strictly higher.
    lines: List[str] = []
    for pr in principles_chosen:
        for rt in displaced:
            if rt.similarity_raw > pr.similarity_raw:
                lines.append(
                    f"chosen_principle_chunk={pr.chunk_id} "
                    f"raw_sim={pr.similarity_raw:.4f} "
                    f"boosted_sim={pr.similarity_boosted:.4f}  "
                    f"displaced_ruling_text_chunk={rt.chunk_id} "
                    f"raw_sim={rt.similarity_raw:.4f}"
                )
    if lines:
        try:
            with _DISPLACEMENT_LOG.open("a", encoding="utf-8") as f:
                for ln in lines:
                    f.write(ln + "\n")
        except Exception:  # pragma: no cover
            pass


# ═══════════════════════════════════════════════════════════════════════
# Prompt-injection block (token-capped)
# ═══════════════════════════════════════════════════════════════════════

def _estimate_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 3 Arabic chars."""
    return max(1, len(text) // 3)


def _summarize_precedent(p: Precedent, max_chars: int = 240) -> str:
    """Collapse whitespace + truncate to max_chars for in-prompt display."""
    txt = re.sub(r"\s+", " ", (p.content or "")).strip()
    if len(txt) > max_chars:
        txt = txt[: max_chars - 1].rstrip() + "…"
    return txt


def build_precedent_block(
    precedents: List[Precedent],
    max_tokens: int = MAX_PRECEDENT_TOKENS,
) -> str:
    """Build the prompt block to inject after _concept_context. Returns
    an empty string if the feature flag is off or no precedents are
    provided. Hard-caps output at max_tokens."""
    if not _feature_flag() or not precedents:
        return ""

    header = "\n\n═══ 📚 أحكام تمييز ذات صلة (التزم بالصياغة الواردة فيها) ═══\n"
    footer = (
        "\n⛔ إذا اقتبستَ من هذه الأحكام فاذكر المرجع حرفياً كما ورد أعلاه. "
        "لا تخترع أرقام طعون غير مذكورة هنا — الحارس سيحذفها.\n"
    )

    lines: List[str] = [header]
    used = _estimate_tokens(header) + _estimate_tokens(footer)
    for i, p in enumerate(precedents, 1):
        entry = (
            f"\n{i}. [{p.display_ref}] (مجال: {p.domain}، تشابه: "
            f"{p.similarity_boosted:.2f})\n"
            f"   {_summarize_precedent(p)}\n"
        )
        cost = _estimate_tokens(entry)
        if used + cost > max_tokens:
            lines.append(
                f"\n(تم اقتطاع {len(precedents) - i + 1} حكم/مبدأ إضافي "
                f"لتجاوز سقف {max_tokens} توكن)\n"
            )
            break
        lines.append(entry)
        used += cost
    lines.append(footer)
    return "".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Hallucination guard — case-number references in LLM answer
# ═══════════════════════════════════════════════════════════════════════

# The guard applies the SAME regex patterns to the LLM answer. Any
# matched case number that is NOT in `provided_precedents` is considered
# hallucinated and rewritten to a safe fallback.

# LLM output is messier than the DB — users/models add Arabic proclitics
# (ل/و/ب/ف…) to "الطعن" producing "للطعن" / "بالطعن" / "والطعن". We allow
# an optional proclitic in group(1) so the replace keeps whatever prefix
# was there and only rewrites the numeric ref.
_ANSWER_PROCLITIC = r"(?:ال|لل|بال|وال|ولل|فال|وبال|فلل|و|ل|ب|ف)?"

_ANSWER_CASE_PATTERNS = [
    # group(1) = full prefix (including proclitic + optional رقم) —
    # group(2) = case number, group(3) = year.
    re.compile(rf"({_ANSWER_PROCLITIC}طعن\s+رقم\s+)(\d+)\s*/\s*(\d{{4}})"),
    re.compile(rf"({_ANSWER_PROCLITIC}طعن\s+)(\d+)\s*/\s*(\d{{4}})"),
    re.compile(rf"({_ANSWER_PROCLITIC}طعن\s+رقم\s+)(\d+)\s+لسنة\s+(\d{{4}})"),
    re.compile(rf"({_ANSWER_PROCLITIC}طعن\s+)(\d+)\s+لسنة\s+(\d{{4}})"),
    re.compile(rf"({_ANSWER_PROCLITIC}طعن\s+بالتمييز\s+رقم\s+)(\d+)\s*/\s*(\d{{4}})"),
]


def extract_case_numbers_from_answer(answer: str) -> List[str]:
    """Extract all case-number refs found in an LLM answer."""
    if not answer:
        return []
    found = []
    seen = set()
    for pat in _ANSWER_CASE_PATTERNS:
        for m in pat.finditer(answer):
            case_num, year = m.group(2), m.group(3)
            if _case_num_valid(case_num) and _year_valid(year):
                key = f"{case_num}/{year}"
                if key not in seen:
                    seen.add(key)
                    found.append(key)
    return found


def verify_precedent_references_in_answer(
    answer: str,
    provided_precedents: List[Precedent],
) -> Tuple[str, List[str]]:
    """
    Hallucination guard. Scans the LLM answer for case-number refs; any
    ref that is NOT in `provided_precedents` is rewritten to the fallback
    display string. Every rewrite is appended to the hallucinations log.

    Returns:
        (cleaned_answer, list_of_hallucinated_refs)

    Does NOT delete — replacement keeps sentence flow intact (the
    original prompt guidance from D3). Valid refs (present in the
    injected context) pass through untouched.
    """
    if not answer or not _feature_flag():
        return answer, []

    valid_refs = {p.case_number for p in provided_precedents if p.case_number}
    hallucinated: List[str] = []

    def _replace(m: re.Match) -> str:
        prefix = m.group(1)
        case_num, year = m.group(2), m.group(3)
        ref = f"{case_num}/{year}"
        # F2 FIX (CP2 E1): any citation-like pattern that is either
        #   (a) out of plausible numeric range, or
        #   (b) not in provided_precedents,
        # is treated as a hallucination and rewritten to the fallback.
        # This closes the leak where "الطعن رقم 99999/1800" used to pass
        # through unchanged because _year_valid rejected it and we then
        # returned m.group(0) verbatim.
        if not (_case_num_valid(case_num) and _year_valid(year)):
            # Out-of-range looks like garbage — the LLM is citation-pretending.
            hallucinated.append(f"{ref} [out-of-range]")
            return "مبدأ مستقر لمحكمة التمييز"
        if ref in valid_refs:
            return m.group(0)
        hallucinated.append(ref)
        return "مبدأ مستقر لمحكمة التمييز"

    cleaned = answer
    for pat in _ANSWER_CASE_PATTERNS:
        cleaned = pat.sub(_replace, cleaned)

    # Dedup while preserving order
    seen: set = set()
    dedup: List[str] = []
    for h in hallucinated:
        if h not in seen:
            seen.add(h)
            dedup.append(h)

    # Audit log
    if dedup:
        try:
            import datetime as _dt
            with _HALLUCINATION_LOG.open("a", encoding="utf-8") as f:
                ts = _dt.datetime.utcnow().isoformat(timespec="seconds")
                valid_str = ",".join(sorted(valid_refs)) or "(none)"
                f.write(
                    f"{ts}Z  hallucinated={dedup}  provided_valid={valid_str}\n"
                )
        except Exception:  # pragma: no cover
            pass

    return cleaned, dedup


# ═══════════════════════════════════════════════════════════════════════
# CP2 · High-level wrapper — augmentation + embed + retrieval in one call
# ─────────────────────────────────────────────────────────────────────
# This is the function the integration in query_router.handle_general
# calls. It handles:
#   1. Domain mapping (corpus → tamyeez buckets, F3-defensive).
#   2. Query augmentation for precedent embedding (E2).
#   3. Embedding via the caller-provided async embed function (so we
#      don't hard-depend on services.llm_service).
#   4. First retrieval on the augmented query.
#   5. Fallback retrieval on the ORIGINAL query if augmented returns
#      nothing (augmentation hints are heuristic — always keep a safety
#      net so a bad hint doesn't silently drop valid results).
#   6. Augmentation logging (before/after counts).
# ═══════════════════════════════════════════════════════════════════════

async def find_relevant_precedents_augmented(
    *,
    query: str,
    corpus_domain: Optional[str],
    concepts: Optional[List[str]] = None,
    embed_fn=None,  # async callable (str) -> list[float]
    top_k: int = PRECEDENT_TOP_K,
    threshold: float = PRECEDENT_THRESHOLD,
    pool=None,
    phase0_class: Optional[str] = None,  # CP3.3: context for skip logic
) -> List[Precedent]:
    """Top-level entry point used by handle_general + compose_memo.

    Degrades open in every failure mode — returns [] instead of raising.

    CP3.3 short-query skip: for definitional queries (≤6 words, no
    digits, no case keywords, not a memo) we return [] immediately —
    no SQL, no embed, no block, no guard. Controlled by the pure
    function `_should_skip_linker(query, phase0_class)`. Each skip is
    logged to /app/logs/precedent_skipped_short_query.log.
    """
    import time as _t
    _t0 = _t.perf_counter()
    _precedents_len = 0
    _avg_sim = 0.0
    _domains: List[str] = []
    _skipped_short = False
    _timing: dict = {}
    try:
        if not _feature_flag() or not query:
            return []
        # CP3.3 skip gate — fires BEFORE any retrieval work so the
        # cost savings (tokens + latency) are immediate.
        if _should_skip_linker(query, phase0_class, concepts):
            _skipped_short = True
            log.info("precedent_skipped_short_query: %r", query[:80])
            _log_skip(query, phase0_class)
            return []
        _result = await _find_relevant_precedents_augmented_impl(
            query=query, corpus_domain=corpus_domain,
            concepts=concepts, embed_fn=embed_fn,
            top_k=top_k, threshold=threshold, pool=pool,
            _timing=_timing,
        )
        _precedents_len = len(_result)
        if _result:
            _avg_sim = sum(p.similarity_boosted for p in _result) / len(_result)
            _domains = [p.domain for p in _result]
        return _result
    finally:
        # Metrics row — one per invocation — for CP3 cost harness.
        try:
            import json as _json, datetime as _dt
            _elapsed_ms = int((_t.perf_counter() - _t0) * 1000)
            # Aggregate layer timings from _timing dict (lists → sum/individual)
            _embed_list = _timing.get("embed_ms_list", []) if _timing else []
            _sql_list = _timing.get("sql_ms_list", []) if _timing else []
            _postproc_list = _timing.get("postproc_ms_list", []) if _timing else []
            _line = {
                "ts": _dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "query": (query or "")[:300],
                "corpus_domain": corpus_domain,
                "concepts": list(concepts or [])[:6],
                "elapsed_ms": _elapsed_ms,
                "precedent_count": _precedents_len,
                "avg_similarity_boosted": round(_avg_sim, 4),
                "domains": _domains,
                "threshold": threshold,
                "top_k": top_k,
                "skipped_short": _skipped_short,
                "phase0_class": phase0_class,
                # CP3.3-INVESTIGATION: per-layer breakdown
                "embed_ms_list": _embed_list,
                "embed_ms_total": round(sum(_embed_list), 2),
                "sql_ms_list": _sql_list,
                "sql_ms_total": round(sum(_sql_list), 2),
                "postproc_ms_list": _postproc_list,
                "postproc_ms_total": round(sum(_postproc_list), 2),
                "n_embed_calls": len(_embed_list),
                "n_sql_calls": len(_sql_list),
                "embed_for_logging_only": bool(
                    _timing.get("embed_original_for_logging")
                ) if _timing else False,
            }
            with _COST_METRICS_LOG.open("a", encoding="utf-8") as _f:
                _f.write(_json.dumps(_line, ensure_ascii=False) + "\n")
        except Exception:  # pragma: no cover — telemetry never blocks
            pass


# ─── Original implementation (renamed) — the public entry point
# delegates to this so we can wrap timing without duplicating the body.
async def _find_relevant_precedents_augmented_impl(
    *,
    query: str,
    corpus_domain: Optional[str],
    concepts: Optional[List[str]] = None,
    embed_fn=None,
    top_k: int = PRECEDENT_TOP_K,
    threshold: float = PRECEDENT_THRESHOLD,
    pool=None,
    _timing: Optional[dict] = None,  # CP3.3-INVESTIGATION: passed in by wrapper
) -> List[Precedent]:
    """CP3.3 — split impl so the public wrapper can time it cleanly."""
    import time as _t_mod
    if not _feature_flag() or not query:
        return []
    if embed_fn is None:
        # Import lazily to avoid module-level coupling to services.*
        try:
            from services.llm_service import embed as _embed
            embed_fn = _embed
        except Exception as e:
            log.warning("precedent_linker: no embed_fn available: %s", e)
            return []

    tamyeez_domain = map_corpus_domain_to_tamyeez(corpus_domain)

    # ── Precompute signal tallies (used by both override + mismatch log) ──
    civil_k = _count_keyword_hits(query, _CIVIL_QUERY_KEYWORDS)
    crim_k = _count_keyword_hits(query, _CRIMINAL_QUERY_KEYWORDS)
    civil_c = sum(1 for c in (concepts or [])
                  if CONCEPT_DOMAIN_AFFINITY.get(c) == "مدني")
    crim_c = sum(1 for c in (concepts or [])
                 if CONCEPT_DOMAIN_AFFINITY.get(c) == "جنائي")
    civil_total = civil_k + civil_c
    crim_total = crim_k + crim_c

    # CP3 · G2 defensive override — only fires when direct mapping
    # returned None. Uses concept+keyword signals to force a bucket
    # when signal is strongly one-sided. Logged with [domain-override]
    # tag so every override is auditable.
    if tamyeez_domain is None:
        inferred = _infer_domain_from_signals(query, concepts or [])
        if inferred:
            _log_domain_override(
                query=query, corpus_domain=corpus_domain,
                inferred=inferred,
                civil_score=civil_total, crim_score=crim_total,
            )
            tamyeez_domain = inferred

    # CP3 · G5 metric — log-only mismatch detection. Fires when
    #   (a) tamyeez_domain is a non-None concrete bucket, AND
    #   (b) the DISSENTING side has ≥_DOMAIN_MISMATCH_MIN_SIGNALS hits,
    #   (c) AND it outnumbers the mapped side by ≥2× (noise-robust).
    # Does NOT change tamyeez_domain — this is data collection for a
    # future standalone second-opinion layer (user's explicit boundary).
    if tamyeez_domain in {"مدني", "جنائي"}:
        signal_suggestion: Optional[str] = None
        if tamyeez_domain == "مدني":
            # Dissenting = criminal side
            if (crim_total >= _DOMAIN_MISMATCH_MIN_SIGNALS
                    and crim_total >= 2 * max(1, civil_total)):
                signal_suggestion = "جنائي"
        else:  # tamyeez_domain == "جنائي"
            if (civil_total >= _DOMAIN_MISMATCH_MIN_SIGNALS
                    and civil_total >= 2 * max(1, crim_total)):
                signal_suggestion = "مدني"

        if signal_suggestion:
            _log_domain_mismatch(
                query=query,
                detected=corpus_domain,
                mapped=tamyeez_domain,
                concept_suggested=signal_suggestion,
                final_used=tamyeez_domain,  # we still use the mapped one
                civil_score=civil_total,
                crim_score=crim_total,
            )

    augmented = _augment_query_for_precedent_embedding(query, concepts or [])

    # First try: augmented query (if it differs from original)
    tried_augmented = augmented != query
    n_before_log = 0  # for log only — number from ORIGINAL query
    results: List[Precedent] = []
    if tried_augmented:
        try:
            _te0 = _t_mod.perf_counter()
            aug_emb = await embed_fn(augmented)
            if _timing is not None:
                _timing.setdefault("embed_ms_list", []).append(
                    round((_t_mod.perf_counter() - _te0) * 1000, 2))
                _timing["embed_augmented"] = True
            if aug_emb:
                results = await find_relevant_precedents(
                    query_embedding=aug_emb,
                    domain=tamyeez_domain,
                    concepts=concepts or [],
                    top_k=top_k, threshold=threshold, pool=pool,
                    _timing=_timing,
                )
        except Exception as e:
            log.warning("precedent_linker augmented retrieval failed: %s", e)

    # Safety fallback: always try original if augmented returned nothing
    # OR if no augmentation was applicable.
    if not results:
        try:
            _te1 = _t_mod.perf_counter()
            orig_emb = await embed_fn(query)
            if _timing is not None:
                _timing.setdefault("embed_ms_list", []).append(
                    round((_t_mod.perf_counter() - _te1) * 1000, 2))
                _timing["embed_original_fallback"] = True
            if orig_emb:
                results = await find_relevant_precedents(
                    query_embedding=orig_emb,
                    domain=tamyeez_domain,
                    concepts=concepts or [],
                    top_k=top_k, threshold=threshold, pool=pool,
                    _timing=_timing,
                )
                n_before_log = len(results)
        except Exception as e:
            log.warning("precedent_linker original retrieval failed: %s", e)

    # CP3.3-FIX (q6 outlier): REMOVED redundant embed+SQL-for-logging.
    # The previous code re-embedded the ORIGINAL query and re-ran the
    # SQL *purely* to populate the `before=N` field in the augmentation
    # log. That doubled the linker latency on every augmented query
    # (measured: 10/10 q6 runs did 2 embeds + 2 SQLs). The n_before
    # metric is useful for post-hoc tuning but does NOT justify a 2×
    # latency cost in the hot path.
    #
    # New behavior:
    #   • `n_before` is recorded ONLY if we already know it for free —
    #     i.e. the fallback path already retrieved on the original query
    #     (augmented returned []). In that case n_before_log > 0.
    #   • Otherwise n_before is logged as "skipped" (None sentinel).
    #     The log now carries Δ=? for those rows — explicit missing data
    #     rather than misleading zeros.
    #
    # If we ever need precise augmentation-lift stats, run the
    # diagnostic script offline on a sample (separate hot path).
    if tried_augmented:
        try:
            # n_before is known only when the fallback ran on the
            # original query (augmented returned empty). Otherwise
            # we pass None to signal "not measured".
            n_before_val = n_before_log if n_before_log > 0 else None
            _log_augmentation(
                original=query, augmented=augmented,
                n_before=n_before_val, n_after=len(results),
            )
        except Exception:  # pragma: no cover
            pass

    return results


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# Test-harness helper (NOT for production use)
# ═══════════════════════════════════════════════════════════════════════

async def _reset_pool_state() -> None:
    """
    Test-only: close and null out ``core.app_state.pool`` so the next call
    to ``_ensure_pool()`` (inside a test) creates a fresh pool bound to
    the CURRENT event loop.

    Why this exists:
    ----------------
    ``pytest-asyncio`` in auto-mode creates a new event loop per test
    function by default. ``app_state.pool`` is a module-level global
    populated once by the first test and reused by the rest — but the
    asyncpg pool internally binds its connections to the event loop that
    created it. When a later test runs in a fresh loop and tries to use
    the already-populated pool, asyncpg raises
    ``Event loop is closed`` / ``another operation is in progress``.

    This helper is invoked by the ``tests/phase2/conftest.py`` autouse
    fixture before and after every test, guaranteeing that each test
    starts with ``app_state.pool is None`` and constructs its own pool.

    Production runtime NEVER calls this — FastAPI's lifespan owns the
    pool for the whole app lifecycle. Test harnesses only.
    """
    from core import app_state
    if app_state.pool is not None:
        try:
            await app_state.pool.close()
        except Exception:
            # The pool may be bound to an already-closed loop (prior test).
            # We cannot await its close() in that case — just drop the
            # reference and let the GC reclaim it.
            pass
        app_state.pool = None


__all__ = [
    "Precedent",
    "PRECEDENT_LINKER_ENABLED",
    "PRECEDENT_THRESHOLD",
    "PRECEDENT_TOP_K",
    "MAX_PRECEDENT_TOKENS",
    "PRINCIPLE_BOOST",
    "HNSW_EF_SEARCH",
    "CASE_NUMBER_PATTERNS",
    "find_relevant_precedents",
    "find_relevant_precedents_augmented",
    "build_precedent_block",
    "extract_case_numbers_from_answer",
    "verify_precedent_references_in_answer",
    "map_corpus_domain_to_tamyeez",
    "_reset_pool_state",
]
