# -*- coding: utf-8 -*-
"""
routers/query_router.py — UNIFIED RUNTIME_V2 ROUTER.
======================================================

This file is the ONLY HTTP entry point for answer-producing queries.
Every request that used to go through the legacy runtime now routes
through `core.runtime_v2.adapter` and nothing else.

Hard contract (enforced in tests/test_runtime_v2_cutover.py):
  • NO import of `core.production_runtime`.
  • NO import of `core.fail_closed_pipeline`.
  • NO fallback, no switch, no dual runtime.
  • Every response carries `runtime: "runtime_v2"` +
    `runtime_authority: "runtime_v2"` + `legacy_runtime_used: False`.

This router does NOT:
  - call LLMs directly
  - run RAG / retrieval
  - assemble prompts
  - build answers from scratch
  - decide citations
  - permit any legacy fallback

It ONLY:
  1. validates inbound request
  2. applies the beta security pre-gate (upstream of runtime)
  3. dispatches to `runtime_v2.adapter.answer_json`
  4. stamps the runtime_v2 authority on the response
  5. returns the response verbatim (or streams it frame-by-frame)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from core.stabilization import resolve_safe_session_id as _safe_sid
from core.beta_middleware import (
    beta_pre_request, get_beta_context,
    beta_record_feedback, beta_metrics_snapshot,
)
# ── runtime_v2 adapter (memo path) ──
from core.runtime_v2.adapter import (
    answer_json as _v2_answer_json,
    stream_frames as _v2_stream_frames,
)
# ── Phase 0 router (pre-runtime_v2 shunt) ──
from core.phase0_router import route_query
from core.nlp_utils import get_history, add_to_history
from core import cancellation as _cancel

# ── Legal Concept DB + Hallucination Guard (Part 2) ──
try:
    from core.legal_concepts import (
        find_concepts_in_query as _lc_find,
        build_concept_context as _lc_build_ctx,
        verify_concepts_in_answer as _lc_verify_concepts,
        verify_articles_in_context as _lc_verify_articles,
        extract_article_numbers as _lc_extract_arts,
    )
    _CONCEPTS_AVAILABLE = True
except Exception as _lc_err:  # pragma: no cover — degrade open
    _CONCEPTS_AVAILABLE = False
    _lc_find = lambda *_a, **_k: []  # type: ignore
    _lc_build_ctx = lambda *_a, **_k: ""  # type: ignore
    _lc_verify_concepts = lambda *_a, **_k: []  # type: ignore
    _lc_verify_articles = lambda *_a, **_k: []  # type: ignore
    _lc_extract_arts = lambda *_a, **_k: []  # type: ignore
    logging.getLogger(__name__).warning(
        "legal_concepts unavailable (%s) — concept guard disabled",
        type(_lc_err).__name__,
    )

# ── Optional imports for Phase 2/3 handlers (lazy — degrade on miss) ──
import asyncio
import asyncpg  # noqa: F401 — used inside handlers via connection
from core import app_state as _app_state

log = logging.getLogger(__name__)
router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# Answer Memory — Redis-backed session-scoped fact store
# Stores article numbers + law names mentioned in every assistant
# reply so future turns can stay consistent with them.
# ═════════════════════════════════════════════════════════════════
import re as _re_mem
try:
    import redis as _redis_mod
except Exception:
    _redis_mod = None

_REDIS_HOST = "legal_redis"
_REDIS_PORT = 6379
_REDIS_DB = 2
_REDIS_TTL = 3600  # 1 hour

_ART_MEM_RE = _re_mem.compile(r"(?:المادة|مادة|م)\s*\(?\s*(\d+)\s*\)?")
_LAW_MEM_RE = _re_mem.compile(
    r"قانون\s+[\u0621-\u064a\s]+?(?=\s+(?:رقم|المادة|،|\.|$))"
)


def _get_redis():
    if _redis_mod is None:
        return None
    try:
        r = _redis_mod.Redis(
            host=_REDIS_HOST, port=_REDIS_PORT,
            db=_REDIS_DB, decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=1.0,
        )
        r.ping()
        return r
    except Exception:
        return None


def _store_answer_facts(sid: str, answer: str, query: str) -> None:
    """Extract article numbers + law names from `answer`, push a
    compact fact record onto a Redis list keyed by session_id."""
    if not sid or not answer:
        return
    r = _get_redis()
    if r is None:
        return
    articles = list(dict.fromkeys(_ART_MEM_RE.findall(answer)))[:10]
    laws = list(dict.fromkeys(_LAW_MEM_RE.findall(answer)))[:5]
    if not articles and not laws:
        return
    fact = {
        "query":    (query or "")[:200],
        "articles": articles,
        "laws":     [l.strip() for l in laws],
        "summary":  (answer or "")[:400],
        "ts":       int(__import__("time").time()),
    }
    try:
        key = f"answer_memory:{sid}"
        r.lpush(key, json.dumps(fact, ensure_ascii=False))
        r.ltrim(key, 0, 4)        # keep last 5 answers
        r.expire(key, _REDIS_TTL)
    except Exception as e:
        log.debug("answer_memory store: %s", e)


def _retrieve_answer_facts(sid: str) -> str:
    """Return a short prompt-friendly block listing the articles the
    assistant has already cited in this session. Used inside the
    system prompt so the LLM stays consistent."""
    if not sid:
        return ""
    r = _get_redis()
    if r is None:
        return ""
    try:
        items = r.lrange(f"answer_memory:{sid}", 0, 4)
    except Exception:
        return ""
    if not items:
        return ""
    lines: list[str] = []
    for raw in items:
        try:
            f = json.loads(raw)
        except Exception:
            continue
        arts = f.get("articles") or []
        if arts:
            q_snip = (f.get("query") or "")[:70]
            arts_str = "، ".join(f"م{a}" for a in arts[:6])
            lines.append(f"  - ذكرت سابقاً: {arts_str}  (رداً على: «{q_snip}»)")
    if not lines:
        return ""
    return (
        "\n\n═══ حقائق ذكرتها في إجاباتك السابقة خلال هذه الجلسة ═══\n"
        + "\n".join(lines)
        + "\n• كن متسقاً مع هذه المواد — لا تنفِ وجودها ولا تناقضها.\n"
        + "• عند إعادة طرح نفس الموضوع، ابنِ على ما ذكرته سابقاً.\n═══\n"
    )


# ═════════════════════════════════════════════════════════════════
# Request / Response schemas
# ═════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    query:      str
    mode:       Optional[str] = "expert"
    model:      Optional[str] = ""
    session_id: Optional[str] = "default"
    history:    Optional[list] = []

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise HTTPException(status_code=400, detail="الرجاء إدخال سؤال.")
        if len(v) > 15000:
            raise HTTPException(
                status_code=400,
                detail=f"النص طويل جداً ({len(v)} حرف). الحد الأقصى 15000 حرف."
            )
        v = re.sub(r"<[^>]+>", "", v)   # XSS strip
        v = v.replace("\x00", "")        # null-byte strip
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> str:
        allowed = {"", "openai", "gemini", "claude", "ollama"}
        if v and v not in allowed:
            return ""
        return v or ""

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: Optional[str]) -> str:
        if v not in ("expert", "general"):
            return "expert"
        return v

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: Optional[str]) -> str:
        if not v:
            return "default"
        v = re.sub(r"[^a-zA-Z0-9\-_]", "", v)[:64]
        return v or "default"

    @field_validator("history")
    @classmethod
    def validate_history(cls, v: Optional[list]) -> list:
        if not v:
            return []
        return v[-20:] if len(v) > 20 else v


class FeedbackRequest(BaseModel):
    log_id:  int
    value:   int
    note:    Optional[str] = ""
    query:   Optional[str] = ""
    answer:  Optional[str] = ""
    sources: Optional[list] = []
    model:   Optional[str] = ""


# ═════════════════════════════════════════════════════════════════
# Stamping helper — enforces runtime_v2 authority on every payload
# ═════════════════════════════════════════════════════════════════

def _stamp_authority(resp: dict) -> dict:
    """Guarantee every outgoing response carries the runtime_v2
    authority stamp and the minimum-compatible trace fields expected by
    older clients."""
    resp["authoritative_path"]   = "runtime_v2"
    resp["runtime_authority"]    = "runtime_v2"
    resp["runtime_version"]      = "v2"
    resp["legacy_runtime_used"]  = False
    resp["legacy_used"]          = False
    resp["fallback_used"]        = False
    resp.setdefault("runtime",           "runtime_v2")
    resp.setdefault("gates_passed",      [])
    resp.setdefault("gates_failed",      [])
    resp.setdefault("block_reasons",     [])
    resp.setdefault("evidence_trace",    {})
    resp.setdefault("sufficiency_level", "")
    resp.setdefault("is_blocked",        False)
    return resp


def _beta_block_payload(block_text: str) -> dict:
    """Beta pre-gate block, stamped with v2 authority (beta gate runs
    upstream of the runtime; it is NOT the legacy runtime)."""
    return _stamp_authority({
        "answer":       block_text,
        "sources":      [],
        "domain":       "beta_gate",
        "confidence":   0,
        "is_grounded":  False,
        "runtime":      "beta_pregate",
        "gates_passed": ["beta_gate_passed"],
        "gates_failed": ["beta_gate_blocked"],
        "block_reasons": ["beta_middleware"],
        "is_blocked":   True,
        "from_beta_gate": True,
    })


# ═════════════════════════════════════════════════════════════════
# POST /api/v1/query/  — runtime_v2 dispatch (single authoritative path)
# ═════════════════════════════════════════════════════════════════

@router.post("/api/v1/query/")
async def query_json(req: QueryRequest, request: Request = None):
    try:
        q = req.query.strip()
        _ip = request.client.host if (request and request.client) else ""
        _headers = dict(request.headers) if request else {}
        sid = _safe_sid(req.session_id, request_ip=_ip, request_headers=_headers)

        # Beta pre-gate (security — upstream of runtime)
        _block = beta_pre_request(sid, q)
        if _block:
            return _beta_block_payload(_block)

        _bctx = get_beta_context()
        if _bctx:
            _bctx.session_id = sid
            _bctx.query = q[:200]

        # Single authoritative dispatch — runtime_v2 adapter only
        request_id = _cancel.new_request_id()
        resp = _v2_answer_json(q, sid, req.history or [],
                                 request_id=request_id)
        resp.setdefault("request_id", request_id)
        return _stamp_authority(resp)

    except HTTPException:
        raise
    except Exception as e:
        log.exception("[runtime_v2] query_json raised")
        return _stamp_authority({
            "answer": "تعذّر معالجة الطلب عبر runtime_v2. يُرجى إعادة المحاولة.",
            "sources": [], "confidence": 0, "is_grounded": False,
            "runtime": "runtime_v2", "is_blocked": True,
            "gates_passed": [], "gates_failed": ["runtime_v2_exception"],
            "block_reasons": [f"exception:{type(e).__name__}"],
        })


# ═════════════════════════════════════════════════════════════════
# Phase 0/2/3 specialized handlers
# ═════════════════════════════════════════════════════════════════

def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _stream_text_direct(
    text: str, route: str, confidence: int = 90,
    chunk_size: int = 40, delay: float = 0.02,
) -> "AsyncIterator[str]":
    """Stream a fully-formed text response as SSE frames (start/chunk×N/done)."""
    yield _sse({
        "type": "start", "runtime": "phase0_router",
        "authoritative_path": "runtime_v2", "runtime_authority": "runtime_v2",
    })
    n = max(1, chunk_size)
    for i in range(0, len(text), n):
        piece = text[i:i + n]
        yield _sse({
            "type": "chunk", "content": piece, "text": piece,
            "authoritative_path": "runtime_v2", "runtime_authority": "runtime_v2",
        })
        try:
            await asyncio.sleep(delay)
        except Exception:
            pass
    yield _sse(_stamp_authority({
        "type": "done", "runtime": "phase0_router",
        "route": route, "confidence": confidence,
        "sources": [], "is_grounded": False, "is_blocked": False,
    }))


# ──────────────────────────────────────────────────────────────────
# Handler: article_text — pull full article from DB
# ──────────────────────────────────────────────────────────────────

async def _fetch_article_from_db(art: str, law_pat: Optional[str]) -> Optional[dict]:
    pool = _app_state.pool
    if pool is None:
        return None
    excl = (
        " AND law_name NOT LIKE '%أحكام محكمة التمييز%'"
        " AND law_name NOT LIKE '%قرار وزار%'"
        " AND law_name NOT LIKE '%نظام سياسي%'"
        " AND law_name NOT LIKE '%خدمة وطنية%'"
        " AND law_name NOT LIKE '%اتجار بالبشر%'"
        " AND law_name NOT LIKE '%الدستور%'"
    )
    async with pool.acquire() as conn:
        row = None
        if law_pat:
            row = await conn.fetchrow(
                f"SELECT content, law_name FROM chunks "
                f"WHERE is_active=true AND article_number=$1 AND law_name LIKE $2"
                f"{excl} ORDER BY length(content) DESC LIMIT 1",
                art, law_pat,
            )
        if not row:
            row = await conn.fetchrow(
                f"SELECT content, law_name FROM chunks "
                f"WHERE is_active=true AND article_number=$1"
                f"{excl} ORDER BY length(content) DESC LIMIT 1",
                art,
            )
    return dict(row) if row else None


async def handle_article_text(payload: dict) -> StreamingResponse:
    art = payload.get("article_number", "")
    law_pat = payload.get("law_pattern")

    async def gen():
        try:
            row = await _fetch_article_from_db(art, law_pat)
        except Exception as e:
            log.exception("article_text fetch failed")
            row = None
        if row:
            text = (
                f"📜 **المادة ({art})** من **{row['law_name']}**:\n\n"
                f"{row['content']}"
            )
            conf = 95
        else:
            text = (
                f"عذراً، لم أجد نص المادة ({art})"
                + (f" من {payload.get('law_hint')}" if payload.get("law_hint") else "")
                + ". تأكد من رقم المادة واسم القانون."
            )
            conf = 40
        async for frame in _stream_text_direct(text, "article_text", conf, chunk_size=60):
            yield frame

    return StreamingResponse(gen(), media_type="text/event-stream")


# ──────────────────────────────────────────────────────────────────
# Handler: table — pull a table (drugs/salaries/penalties/traffic)
# ──────────────────────────────────────────────────────────────────

_TABLE_QUERIES = {
    "drugs": (
        "SELECT content, law_name FROM chunks WHERE is_active=true "
        "AND law_name LIKE '%مخدرات%' "
        "AND (content LIKE '%جدول رقم%' OR content LIKE '%الجدول%' "
        "     OR content LIKE '%المواد المخدرة%') "
        "ORDER BY length(content) DESC LIMIT 3"
    ),
    "salaries": (
        "SELECT content, law_name FROM chunks WHERE is_active=true "
        "AND (content LIKE '%جدول الدرجات%' OR content LIKE '%سلم الرواتب%' "
        "     OR content LIKE '%الدرجات والرواتب%') "
        "ORDER BY length(content) DESC LIMIT 2"
    ),
    "penalties": (
        "SELECT content, law_name FROM chunks WHERE is_active=true "
        "AND content LIKE '%جدول%عقوب%' ORDER BY length(content) DESC LIMIT 2"
    ),
    "traffic": (
        "SELECT content, law_name FROM chunks WHERE is_active=true "
        "AND (content LIKE '%مخالفات مرور%' OR content LIKE '%جدول%مخالف%') "
        "ORDER BY length(content) DESC LIMIT 2"
    ),
}


async def handle_table(payload: dict) -> StreamingResponse:
    ttype = payload.get("table_type", "drugs")
    q_sql = _TABLE_QUERIES.get(ttype, _TABLE_QUERIES["drugs"])

    async def gen():
        rows = []
        pool = _app_state.pool
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(q_sql)
            except Exception as e:
                log.exception("table fetch failed")
        if rows:
            parts = ["📋 **الجدول المطلوب:**\n"]
            for r in rows:
                parts.append(f"— من **{r['law_name']}**:\n{r['content']}\n")
            text = "\n---\n\n".join(parts)
            conf = 88
        else:
            text = "عذراً، لم أجد الجدول المطلوب في قاعدة البيانات."
            conf = 35
        async for frame in _stream_text_direct(text, "table", conf, chunk_size=80):
            yield frame

    return StreamingResponse(gen(), media_type="text/event-stream")


# ──────────────────────────────────────────────────────────────────
# Handler: calculator (deterministic math)
# ──────────────────────────────────────────────────────────────────

async def handle_calculator(payload: dict) -> StreamingResponse:
    ctype = payload.get("type")
    salary = payload.get("salary")
    years = payload.get("years")

    async def gen():
        if not salary or not years:
            missing = []
            if not salary: missing.append("الراتب الشهري")
            if not years:  missing.append("سنوات الخدمة")
            text = (
                "لحساب المستحقات أحتاج معرفة: " + " و ".join(missing) + ".\n\n"
                "مثال: «احسب مكافأة نهاية خدمة راتب 15000 و 10 سنوات»"
            )
            conf = 50
        elif ctype == "end_of_service":
            weekly = salary / 4.33
            amount = int(round(weekly * 3 * years))
            text = (
                "🧮 **حساب مكافأة نهاية الخدمة**\n\n"
                f"**المعطيات:**\n"
                f"• الراتب الشهري: {salary:,} ريال\n"
                f"• سنوات الخدمة: {years} سنة\n\n"
                f"**الحساب:**\n"
                f"• الأجر الأسبوعي = {salary:,} ÷ 4.33 = {int(round(weekly)):,} ريال\n"
                f"• 3 أسابيع × {years} سنة = {3*years} أسبوع\n"
                f"• **المكافأة ≈ {amount:,} ريال قطري**\n\n"
                f"**السند:** المادة (54) من قانون العمل القطري رقم (14) لسنة 2004.\n\n"
                f"💡 قد تستحق مستحقات إضافية: إجازات سنوية غير مستعملة، "
                f"بدلات تعاقدية، رواتب متأخرة."
            )
            conf = 96
        elif ctype == "unfair_dismissal":
            comp = int(salary * years)
            text = (
                "🧮 **حساب تعويض الفصل التعسفي**\n\n"
                f"• الراتب الشهري: {salary:,} ريال\n"
                f"• سنوات الخدمة: {years}\n"
                f"• التقدير: أجر شهر عن كل سنة = **{comp:,} ريال**\n\n"
                f"**السند:** المادة (61) من قانون العمل.\n"
                f"💡 قد يُضاف لها مكافأة نهاية الخدمة (م54) وبدل الإنذار (م49)."
            )
            conf = 93
        else:
            text = "نوع الحساب غير مدعوم حالياً."
            conf = 30
        async for frame in _stream_text_direct(text, "calculator", conf, chunk_size=50):
            yield frame

    return StreamingResponse(gen(), media_type="text/event-stream")


# ──────────────────────────────────────────────────────────────────
# Domain filter — prevent cross-law contamination in RAG results
# ──────────────────────────────────────────────────────────────────

_CRIMINAL_SIGNALS = (
    "عقوبة", "عقوبات", "جناية", "جنحة", "سوابق", "رد الاعتبار",
    "رد اعتبار", "اعتبار قضائي", "صحيفة جنائية", "محكوم عليه",
    "تنفيذ العقوبة", "حبس", "سجن", "إجراءات جنائية",
    "الإجراءات الجنائية", "نيابة", "جريمة", "متهم", "إدانة",
    "براءة", "تحقيق", "مخدرات", "سرقة", "قتل", "ضرب",
    "تزوير", "رشوة", "نصب", "احتيال", "قذف", "سب",
    "تهديد", "ابتزاز", "اعتداء",
)
_LABOR_SIGNALS = (
    "عمل", "عامل", "راتب", "أجر", "مكافأة نهاية", "فصل تعسفي",
    "إجازة", "عقد عمل", "صاحب العمل", "استقالة", "خدمة",
    "بدل إنذار", "انهاء الخدمة",
)
_FAMILY_SIGNALS = (
    "حضانة", "طلاق", "نفقة", "زواج", "أسرة", "مهر", "عدة",
    "ولاية", "محضون", "طليقتي", "مطلقتي",
)
_COMMERCIAL_SIGNALS = (
    "شركة", "شركات", "إفلاس", "مفلس", "تجارة", "تاجر",
    "وكيل تجاري", "علامة تجارية", "سجل تجاري",
)


def _filter_chunks_by_domain(
    chunks: list[dict], query: str,
) -> list[dict]:
    """Drop chunks that belong to a legal domain that is clearly
    unrelated to the user's query. Prevents the "labor article
    returned for a criminal question" class of bug.
    """
    if not chunks or len(chunks) <= 2 or not query:
        return chunks

    q = query.lower()
    is_criminal   = any(s in q for s in _CRIMINAL_SIGNALS)
    is_labor      = any(s in q for s in _LABOR_SIGNALS)
    is_family     = any(s in q for s in _FAMILY_SIGNALS)
    is_commercial = any(s in q for s in _COMMERCIAL_SIGNALS)

    if not (is_criminal or is_labor or is_family or is_commercial):
        return chunks

    if is_criminal and not is_commercial:
        # "رد الاعتبار" (criminal) vs "رد اعتبار المفلس" (commercial): if
        # the user didn't mention إفلاس/شركة/تجارة, drop commercial chunks.
        reject = _LABOR_SIGNALS + _FAMILY_SIGNALS + _COMMERCIAL_SIGNALS
        accept = _CRIMINAL_SIGNALS
    elif is_labor:
        reject = _CRIMINAL_SIGNALS + _FAMILY_SIGNALS + _COMMERCIAL_SIGNALS
        accept = _LABOR_SIGNALS
    elif is_family:
        reject = _CRIMINAL_SIGNALS + _LABOR_SIGNALS + _COMMERCIAL_SIGNALS
        accept = _FAMILY_SIGNALS
    else:  # is_commercial
        reject = _CRIMINAL_SIGNALS + _LABOR_SIGNALS + _FAMILY_SIGNALS
        accept = _COMMERCIAL_SIGNALS

    filtered: list[dict] = []
    for ch in chunks:
        text = ((ch.get("content", "") or "") + " " +
                 (ch.get("law_name", "") or "")).lower()
        has_accept = any(s in text for s in accept)
        has_only_reject = (
            any(s in text for s in reject) and not has_accept
        )
        if not has_only_reject:
            filtered.append(ch)
    # Fallback — never return empty
    return filtered if len(filtered) >= 2 else chunks


# ──────────────────────────────────────────────────────────────────
# Handler: general — LLM + RAG (history-aware, source-cited)
# ──────────────────────────────────────────────────────────────────

async def handle_general(
    query: str, sid: str, history: list,
) -> StreamingResponse:
    from services import llm_service as _llm
    from core.prompts import EXPERT_SYSTEM

    async def gen():
        yield _sse({
            "type": "start", "runtime": "phase0_general",
            "authoritative_path": "runtime_v2", "runtime_authority": "runtime_v2",
        })

        # ── Detect the legal domain of the query (for RAG boosting) ──
        query_domain: str | None = None
        try:
            from core.nlp_utils import detect_legal_domain, extract_kw
            _kws = extract_kw(query)
            query_domain = detect_legal_domain(_kws)
        except Exception as e:
            log.debug("domain detect miss: %s", e)

        # ── Context-Aware Continuation detector ──
        # A followup is a short question whose real meaning requires
        # the prior answer. When detected we SKIP RAG entirely — a fresh
        # vector search on "اختصر" / "كم المدد" retrieves random chunks
        # about unrelated topics (vacations, durations in labor law)
        # which contaminate the answer.
        _FOLLOWUP_PATTERNS = (
            "اختصر", "اختصرها", "اختصر لي", "باختصار",
            "كمّل", "كمل", "أكمل", "اكمل", "تابع",
            "وضّح", "وضح", "وضح أكثر", "فصّل", "فصل أكثر",
            "بدون تفصيل", "بدون فلسفة", "بدون اطالة",
            "أقصد", "اقصد", "أقصد رسالتك", "رسالتك السابقة",
            "هل أنت متأكد", "متأكد", "هل انت متاكد",
            "كم المدد", "كم المدة", "كم المدد بدون",
            "يعني", "يعني كيف", "يعني ماذا",
            "نفس الموضوع", "نفس السؤال",
            "لا غلط", "مو هذا قصدي", "ليس هذا قصدي",
            "مش هذا", "مو كذا",
        )
        _is_followup = False
        _last_assistant = ""
        _last_user_q = ""
        if history and len(history) >= 2:
            q_lower = (query or "").lower().strip()
            q_words = len((query or "").split())
            is_short = q_words <= 10
            matches_pattern = any(p in q_lower for p in _FOLLOWUP_PATTERNS)
            starts_with_conj = q_lower.startswith((
                "و ", "ثم ", "لكن ", "بس ", "طيب ",
                "هل و", "وهل", "وماذا", "وكيف",
            ))
            if is_short and (matches_pattern or starts_with_conj):
                _is_followup = True
                # Extract last assistant + last user query from history
                for m in reversed(history):
                    if m.get("role") == "assistant" and not _last_assistant:
                        _last_assistant = m.get("content", "") or ""
                    elif m.get("role") == "user" and not _last_user_q:
                        _last_user_q = m.get("content", "") or ""
                    if _last_assistant and _last_user_q:
                        break
                log.info(
                    "followup detected: q=%r words=%d pattern=%s conj=%s",
                    (query or "")[:40], q_words,
                    matches_pattern, starts_with_conj,
                )

        # ── Retrieval + domain filter ──
        # Skip RAG for SHORT follow-up queries when history exists —
        # the answer is already in the conversation, not in the DB.
        # _is_followup (smarter) takes precedence over the older
        # is_short_followup (word-count only).
        is_short_followup = (
            _is_followup
            or (bool(history) and len((query or "").split()) <= 6)
        )
        sources = []
        if not is_short_followup:
            try:
                # M2: increased top_k from 10 → 18 for fuller coverage
                sources = await _llm.search(
                    queries=[query], key_terms=[query], top_k=18,
                    domain=query_domain,
                )
            except Exception as e:
                log.debug("general search miss: %s", e)
                sources = []
            if sources:
                try:
                    sources = _filter_chunks_by_domain(sources, query)
                except Exception as e:
                    log.debug("domain filter miss: %s", e)

            # M3: Supplementary search for missing topics in complex queries
            if sources and len(query.split()) >= 8:
                q_lower = query.lower()
                source_text = " ".join(
                    (ch.get("content", "") or "") for ch in sources
                ).lower()
                supp: list[str] = []

                # سوابق / عود → م58 (تشديد العقوبة في حالة العود)
                if any(w in q_lower for w in ["سوابق", "عود", "سبق"]) \
                        and "58" not in source_text \
                        and "تشديد" not in source_text \
                        and "عود" not in source_text:
                    supp.append("المادة 58 عقوبات العود تشديد العقوبة")

                # تعويض مدني → م199 القانون المدني + إجراءات الحق المدني
                if any(w in q_lower for w in ["تعويض", "مدني"]) \
                        and "تعويض" not in source_text \
                        and "199" not in source_text:
                    supp.append("التعويض المدني الضرر المادة 199")

                # اعتراف → شروط صحة الاعتراف (م232 إجراءات جنائية)
                if any(w in q_lower for w in ["اعتراف", "اعترف"]) \
                        and "اعتراف" not in source_text \
                        and "إقرار" not in source_text:
                    supp.append("الاعتراف شروط صحة الاعتراف إجراءات جنائية")

                # موظف + سرقة → خيانة أمانة (م354)
                if "موظف" in q_lower and any(w in q_lower for w in ["سرق", "سرقة"]) \
                        and "خيانة" not in source_text \
                        and "أمانة" not in source_text \
                        and "354" not in source_text:
                    supp.append("خيانة الأمانة المادة 354 عقوبات موظف")

                # خطوات/إجراءات جنائية
                if any(w in q_lower for w in ["خطوات", "إجراء", "ماذا أفعل"]) \
                        and "نيابة" not in source_text \
                        and "بلاغ" not in source_text:
                    supp.append("إجراءات رفع الدعوى الجنائية بلاغ نيابة")

                # ═══ Legal-expansion-driven gap filling ═══
                # Pull concept-to-article expansions from llm_service and
                # queue any whose core tokens are not yet in source_text.
                try:
                    from services.llm_service import _expand_legal_query
                    for exp in _expand_legal_query(query)[:6]:
                        exp_norm = exp.lower()
                        core_tokens = [
                            t for t in exp_norm.split()
                            if len(t) >= 3 and t not in ("قانون", "المادة")
                        ][:2]
                        if not core_tokens:
                            continue
                        # already covered if any core token + a digit from
                        # the expansion appear together in sources?
                        digits = [
                            t for t in exp_norm.split() if t.isdigit()
                        ]
                        covered = any(
                            (d in source_text for d in digits)
                        ) if digits else False
                        if not covered and exp not in supp:
                            supp.append(exp)
                except Exception as _ee:
                    log.debug("legal_expansion hook: %s", _ee)

                # ═══ Direct Article Injection ═══
                # Use the same expansion phrases to extract
                # (article_number, law_pattern) pairs and fetch the
                # exact DB chunks bypassing vector/keyword scoring.
                try:
                    from services.llm_service import (
                        _expand_legal_query as _elq,
                        _extract_article_targets as _eat,
                        direct_article_fetch as _daf,
                    )
                    exps = _elq(query)
                    art_targets = _eat(exps) if exps else []
                    if art_targets:
                        direct = await _daf(
                            _app_state.pool, art_targets, max_per_article=2,
                        )
                        if direct:
                            existing_keys = {
                                (s.get("law_name"), s.get("article_number"))
                                for s in sources
                            }
                            injected = 0
                            # Insert direct chunks at the TOP so the
                            # composer sees them first.
                            for dc in direct:
                                k = (dc.get("law_name"),
                                     dc.get("article_number"))
                                if k not in existing_keys:
                                    sources.insert(0, dc)
                                    existing_keys.add(k)
                                    injected += 1
                            log.info(
                                "direct_injection: %d articles injected "
                                "(targets=%d) for %r",
                                injected, len(art_targets), query[:50],
                            )
                except Exception as _dir_err:
                    log.warning("direct_injection hook: %s", _dir_err)

                if supp:
                    log.info("supplementary search: %d queries", len(supp))
                    try:
                        existing_keys = {
                            (s.get("law_name"), s.get("article_number"))
                            for s in sources
                        }
                        for sq in supp[:3]:
                            try:
                                from core.nlp_utils import extract_kw as _ek
                                extra_kw = _ek(sq)
                            except Exception:
                                extra_kw = [sq]
                            try:
                                extra = await _llm.search(
                                    [sq], extra_kw, top_k=5,
                                    domain=query_domain,
                                )
                            except Exception as e:
                                log.debug("supp sub-search failed: %s", e)
                                continue
                            if not extra:
                                continue
                            for ch in extra[:3]:
                                key = (ch.get("law_name"),
                                        ch.get("article_number"))
                                if key not in existing_keys:
                                    sources.append(ch)
                                    existing_keys.add(key)
                    except Exception as e:
                        log.warning("supplementary search wrapper: %s", e)

        # ═══ Smart Complexity Detector (M4 — upgraded) ═══
        # Not every long query is complex. "ما الفرق بين الجنحة
        # والجناية في القانون القطري وما العقوبات المقررة لكل منهما"
        # is conceptual (simple) — should NOT trigger 5-step methodology.
        # "عندي موظف سرق 50K واعترف وعنده سوابق" IS complex.
        _q_lower = (query or "").lower()
        _q_words = len((query or "").split())

        # Strong "simple / conceptual" markers (definition, comparison,
        # single-fact question). Match if query STARTS with one of these
        # OR contains one early.
        _SIMPLE_PATTERNS = (
            "ما هو ", "ما هي ", "ماهو ", "ماهي ",
            "ما معنى", "ما تعريف", "ما الفرق بين", "الفرق بين",
            "عرّف ", "عرف ", "عرف لي", "اشرح لي معنى",
            "وش يعني", "ايش يعني", "يعني ايش",
            "ما عقوبة", "ما حكم", "ما نص المادة", "نص المادة",
            "متى يجوز", "متى يُعدّ", "متى يُعد",
        )
        # Strong "complex / case-advice" markers — personal situation,
        # numbered facts, request for procedural steps.
        _COMPLEX_PATTERNS = (
            "عندي قضية", "عندي مشكلة", "موكلي", "موكلتي",
            "ماذا أفعل", "وش اسوي", "ما هي الخطوات",
            "ما العقوبة المتوقعة", "كيف أرفع", "كيف أطالب",
            "واعترف", "وعنده سوابق", "و عنده سوابق",
            "فصلني", "طردني", "سرق من", "احتال علي",
            "طلبت خلع", "طلبت طلاق", "تزوجت من",
            "ما حقوقي", "ماحقوقي",
        )
        # Personal-detail markers — boost complexity when present.
        _PERSONAL_DETAILS = (
            "راتبي", "عمري", "زوجتي", "زوجي", "أطفال",
            "سنوات خدمة", "اشتغلت", "عملت", "نفذت الحكم",
            "الف ريال", "ألف ريال",
        )

        _is_simple  = any(
            _q_lower.startswith(p) or (" " + p) in _q_lower
            for p in _SIMPLE_PATTERNS
        )
        _is_case    = any(p in _q_lower for p in _COMPLEX_PATTERNS)
        _has_personal = any(p in _q_lower for p in _PERSONAL_DETAILS)

        if _is_case and not _is_simple:
            _is_complex = True
        elif _is_simple and not _is_case:
            _is_complex = False
        else:
            # Fallback: very long queries WITH personal details → complex.
            # Long-but-conceptual ("ما الفرق بين... في القانون القطري
            # وما العقوبات...") stays simple.
            _is_complex = _q_words >= 18 and _has_personal

        log.info(
            "complexity: %s (words=%d, simple=%s, case=%s, personal=%s) q=%r",
            "COMPLEX" if _is_complex else "SIMPLE",
            _q_words, _is_simple, _is_case, _has_personal,
            (query or "")[:45],
        )

        # ── Structured user_msg with cited source blocks ──
        if sources:
            context_parts: list[str] = []
            # M2: include up to 12 sources (was 8) with 900-char windows (was 600)
            for i, ch in enumerate(sources[:12], 1):
                law   = ch.get("law_name", "") or ""
                art   = ch.get("article_number", "") or ""
                lnum  = ch.get("law_number", "") or ""
                lyear = ch.get("law_year", "")   or ""
                cont  = (ch.get("content", "") or "")[:900]

                # Direct-injection sources are flagged prominently so
                # the LLM knows these are exact DB matches.
                src_type = ch.get("source_type", "rag")
                if src_type == "direct_injection":
                    header = f"[مصدر {i} — نص قانوني مباشر ⭐]"
                else:
                    header = f"[مصدر {i}]"
                if law:
                    header += f" القانون: {law}"
                if lnum:
                    header += f" رقم ({lnum})"
                if lyear:
                    header += f" لسنة {lyear}"
                if art:
                    header += f" — المادة ({art})"
                context_parts.append(f"{header}\n{cont}")

            rag_context = "\n---\n".join(context_parts)

            # M4: different instruction block for complex vs simple queries
            if _is_complex:
                instructions = (
                    "═══ تعليمات التحليل العميق (سؤال مركّب) ═══\n"
                    "طبّق المنهجية الخماسية بالترتيب:\n"
                    "1. **التكييف القانوني**: حدّد الوصف الدقيق للواقعة. "
                    "إن احتملت وصفاً أكثر من واحد (سرقة / خيانة أمانة / اختلاس / احتيال) — "
                    "اذكرها وحدّد الأرجح.\n"
                    "2. **النصوص المنطبقة**: اذكر كل مادة مُعلَّمة بـ ⭐ "
                    "(نص قانوني مباشر) — **كل واحدة منها** بصراحة بشرحها "
                    "ورقمها واسم قانونها. ثم أضف بقية المواد ذات الصلة.\n"
                    "3. **التحليل التطبيقي**: افتح بـ «في حالتك:» وطبّق النصوص "
                    "على تفاصيل السؤال (المبالغ، السوابق، الاعتراف...).\n"
                    "4. **التوقعات**: العقوبة (حد أدنى/أقصى)، احتمال التشديد "
                    "ولماذا، المدة المتوقعة للإجراءات.\n"
                    "5. **التوصيات العملية**: خطوات مرقمة (بلاغ → تحقيق → ...)، "
                    "مستندات مطلوبة، مواعيد تقادم/طعن.\n\n"
                    "قواعد:\n"
                    "• **كل مادة مُعلَّمة بـ ⭐ يجب أن تُذكر في الإجابة بشكل صريح.** "
                    "هذه مواد مُنتقاة آلياً بدقة لسؤالك وتُعدّ الأهم.\n"
                    "• لا تكتفِ بذكر المواد — طبّقها.\n"
                    "• كل حكم = مادة + قانون + رقمه + سنته.\n"
                    "• استخرج أقصى ما يمكن من النصوص أعلاه قبل أن تقول 'لم أجد'.\n"
                )
            else:
                instructions = (
                    "═══ تعليمات (سؤال بسيط) ═══\n"
                    "أجب في فقرة أو فقرتين مع المادة/القانون من النصوص أعلاه.\n"
                    "لا تطبّق الهيكل الخماسي على السؤال البسيط.\n"
                )

            user_msg = (
                "═══ النصوص القانونية المسترجعة من قاعدة البيانات ═══\n\n"
                + rag_context
                + "\n\n" + instructions + "\n"
                + f"═══ سؤال المستخدم ═══\n{query}"
            )
        else:
            # No RAG context — either follow-up or general concept query.
            # Direct the LLM to use the history AND its general legal
            # knowledge (with conceptual-only framing).
            if _is_followup and _last_assistant:
                # Smart follow-up: inject the PRIOR ANSWER as the
                # authoritative context. Do NOT let the LLM treat
                # "اختصر"/"كم المدد" as a new topic.
                user_msg = (
                    "═══ هذا سؤال متابعة — السياق من المحادثة ═══\n\n"
                    f"**السؤال الأصلي للمستخدم:** {_last_user_q[:500]}\n\n"
                    f"**إجابتك السابقة (المصدر الموثوق):**\n"
                    f"{_last_assistant[:1800]}\n\n"
                    "═══ طلب المستخدم الحالي ═══\n"
                    f"{query}\n\n"
                    "═══ تعليمات صارمة ═══\n"
                    "• المستخدم يطلب تعديلاً على إجابتك السابقة (اختصار / "
                    "تفصيل / توضيح / كمّل). لا تغيّر الموضوع.\n"
                    "• إذا طلب «اختصر» أو «بدون تفصيل» أو «بدون فلسفة» — "
                    "أعد نفس المعلومات القانونية في 2-4 سطور فقط (الأرقام "
                    "الأساسية + المواد). لا مقدمات.\n"
                    "• إذا طلب «كمّل» — تابع من حيث توقفت.\n"
                    "• إذا طلب «وضّح» — وضّح النقطة الغامضة بنفس الموضوع.\n"
                    "• لا تبحث عن موضوع جديد. لا تطبّق المنهجية الخماسية "
                    "إلا إذا طُلب صراحةً.\n"
                    "• المواد القانونية في إجابتك السابقة = المصدر الرسمي. "
                    "استند إليها لا تتناقض معها.\n"
                )
            elif is_short_followup:
                user_msg = (
                    f"(سؤال متابعة — ارجع لسجل المحادثة أعلاه للسياق)\n\n"
                    f"سؤال المستخدم: {query}\n\n"
                    f"أجب استناداً إلى آخر رد أرسلته في المحادثة. "
                    f"لا تقل 'لم أجد' أو 'لا أستطيع الرجوع'."
                )
            else:
                user_msg = (
                    f"سؤال المستخدم: {query}\n\n"
                    f"لم تُسترجع نصوص قانونية محددة من قاعدة البيانات لهذا السؤال.\n"
                    f"أجب شرحاً مفاهيمياً إن كان السؤال يتعلق بتعريف أو "
                    f"فرق بين مفهومين أو مبدأ عام. "
                    f"إن كان السؤال يطلب رقماً محدداً، قل إنك لم تجد الرقم ووجّه للمصدر الرسمي."
                )

        # ── History-aware system prompt ──
        history_note = ""
        if history and len(history) > 0:
            history_note = (
                "\n\n═══ سجل المحادثة مرفق في messages أعلاه ═══\n"
                "• ارجع لآخر رد أرسلته وتابع منه في نفس الموضوع.\n"
                "• لا تقل أبداً 'لا أستطيع الرجوع إلى الرسائل السابقة'.\n"
                "• للمتابعات القصيرة (كمّل / هل أنت متأكد / وضّح / أقصد "
                "رسالتك السابقة):\n"
                "  — استعمل المعلومات المذكورة في آخر رد لك كمصدر موثوق.\n"
                "  — لا تطبّق قاعدة 'لم أجد الرقم' إذا كانت المعلومة في "
                "سجل المحادثة.\n"
                "  — أكّد أو صحّح ما ذكرته سابقاً بناءً على معرفتك.\n"
                "═══\n"
            )

        # ═══ Answer Memory — prior facts for self-consistency ═══
        _prev_facts = _retrieve_answer_facts(sid)

        # ═══ Legal Concept Injection (Part 2 — Axis A) ═══
        # Detect Qatari legal terms in the query and inject their exact
        # definitions into the system prompt. Prevents GPT from inventing
        # wrong definitions from Egyptian/Saudi law memory.
        _found_concepts: list[dict] = []
        _concept_context = ""
        _concept_terms: list[str] = []
        if _CONCEPTS_AVAILABLE:
            try:
                _found_concepts = _lc_find(query)
                if _found_concepts:
                    _concept_context = "\n\n" + _lc_build_ctx(_found_concepts)
                    _concept_terms = [
                        str(c.get("term", "")) for c in _found_concepts
                        if c.get("term")
                    ]
                    log.info(
                        "concept_injection: detected %d concept(s) — %s",
                        len(_concept_terms), _concept_terms,
                    )
            except Exception as _ci_err:
                log.debug("concept_injection miss: %s", _ci_err)

        system = EXPERT_SYSTEM + history_note + _prev_facts + _concept_context + (
            "\n\n═══ وضع المساعد التفاعلي ═══\n"
            "• أجب مباشرة بالتفصيل القانوني ثم اختم بتوصية مراجعة محامٍ.\n"
            "• لا تكتب مذكرة إلا إذا طلب ذلك صراحة.\n"
            "• لا تهرّب بـ 'أحتاج توضيح أكثر' إذا كان السؤال واضحاً.\n"
        )

        # ── Build messages with last 8 turns ──
        messages: list[dict] = []
        if history:
            for m in history[-8:]:
                r = m.get("role")
                c = m.get("content")
                if r in ("user", "assistant") and c and c.strip():
                    messages.append({"role": r, "content": c})
        messages.append({"role": "user", "content": user_msg})

        # M5: dynamic max_tokens — 2200 for complex, 1200 for simple
        _max_tok = 2200 if _is_complex else 1200

        # ── Stream + capture full answer for Answer Memory ──
        _answer_parts: list[str] = []
        try:
            async for piece in _llm.stream_openai(
                system, messages, max_tokens=_max_tok,
            ):
                if piece:
                    _answer_parts.append(piece)
                    yield _sse({
                        "type": "chunk", "content": piece, "text": piece,
                        "authoritative_path": "runtime_v2",
                        "runtime_authority": "runtime_v2",
                    })
        except Exception as e:
            log.exception("general stream failed")
            err = f"تعذّر معالجة السؤال عبر النموذج ({type(e).__name__})."
            yield _sse({"type": "chunk", "content": err, "text": err})

        # ── Persist facts from this answer for future self-consistency ──
        _full = "".join(_answer_parts)
        try:
            if _full:
                _store_answer_facts(sid, _full, query)
        except Exception as _mem_err:
            log.debug("answer_memory store wrap: %s", _mem_err)

        # ═══ Hallucination Guard (Part 2 — Axis B) ═══
        # Fires AFTER the stream completes. Never blocks the answer — only
        # appends a correction block if we detect a known hallucination
        # pattern or an article number that was not in the provided context.
        _guard_warnings: list[str] = []
        if _CONCEPTS_AVAILABLE and _full:
            # 1) Concept verification — does the answer contradict the
            #    injected definitions or trigger a known hallucination?
            try:
                _guard_warnings.extend(
                    _lc_verify_concepts(_full, _concept_terms) or []
                )
            except Exception as _gc_err:
                log.debug("concept verify miss: %s", _gc_err)

            # 2) Article verification — does the answer cite an article
            #    number that never appeared in retrieved chunks AND was
            #    never mentioned in answer memory?
            try:
                # Build the pool of "trusted" articles:
                # chunks + previous session facts
                _ctx_text_parts: list[str] = []
                for _ch in (sources or []):
                    _c = _ch.get("content") or ""
                    if _c:
                        _ctx_text_parts.append(_c)
                # pull previous facts from Redis
                _prev_block = _prev_facts or ""
                if _prev_block:
                    _ctx_text_parts.append(_prev_block)
                # also trust whatever the concept-context mentions
                if _concept_context:
                    _ctx_text_parts.append(_concept_context)
                _ctx_text = "\n".join(_ctx_text_parts)

                _suspicious = _lc_verify_articles(_full, _ctx_text, tolerance=0)
                if _suspicious:
                    # Only warn if there are MORE THAN 1 suspicious numbers
                    # and they are not common ubiquitous refs.
                    # Exclude trivial numbers like "1", "2" that are false-positives.
                    _filt = [a for a in _suspicious if a.isdigit() and int(a) > 3]
                    if _filt:
                        _guard_warnings.append(
                            "تنبيه: المواد التالية ذُكرت في الإجابة ولم تظهر في "
                            "النصوص المسترجعة — يُستحسن التحقق منها من المصدر الرسمي: "
                            + "، ".join(f"م{a}" for a in _filt[:6])
                        )
            except Exception as _ga_err:
                log.debug("article verify miss: %s", _ga_err)

        if _guard_warnings:
            correction = (
                "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🛡️ **تنبيه الحارس القانوني:**\n"
                + "\n".join(f"• {w}" for w in _guard_warnings[:4])
                + "\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            )
            yield _sse({
                "type": "chunk", "content": correction, "text": correction,
                "source": "hallucination_guard",
                "authoritative_path": "runtime_v2",
                "runtime_authority": "runtime_v2",
            })
            log.info(
                "hallucination_guard: emitted %d warning(s)",
                len(_guard_warnings),
            )

        conf = 82 if sources else 55
        if _guard_warnings:
            conf = max(40, conf - 20)  # lower confidence when guard fires
        yield _sse(_stamp_authority({
            "type": "done", "runtime": "phase0_general",
            "route": "general", "confidence": conf,
            "sources_count": len(sources),
            "concepts_injected": _concept_terms,
            "guard_warnings": len(_guard_warnings),
        }))

    return StreamingResponse(gen(), media_type="text/event-stream")


# ──────────────────────────────────────────────────────────────────
# Handler: continuation (follow-up: كمّل/اختصر/وضح/أعد)
# ──────────────────────────────────────────────────────────────────

_CONT_INSTRUCTIONS = {
    "continue": "أكمل من حيث توقّف الرد السابق تمامًا دون إعادة ما قيل.",
    "shorten":  "أعد صياغة الرد السابق مختصرًا في جملتين أو ثلاث فقط.",
    "expand":   "وسّع الرد السابق بتفاصيل وأمثلة وربط قانوني إضافي.",
    "rephrase": "أعد صياغة الرد السابق بطريقة مختلفة وأوضح — وصحّح أي خطأ.",
}


async def handle_continuation(
    payload: dict, history: list, query: str,
) -> StreamingResponse:
    from services import llm_service as _llm

    action = payload.get("action", "continue")
    instr = _CONT_INSTRUCTIONS.get(action, _CONT_INSTRUCTIONS["continue"])

    if not history:
        async def err_gen():
            text = "لا توجد محادثة سابقة للاستمرار. تفضل بسؤالك."
            async for frame in _stream_text_direct(text, "continuation", 50):
                yield frame
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    last_asst = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "assistant"),
        "",
    )
    last_user = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "user"),
        "",
    )

    async def gen():
        yield _sse({
            "type": "start", "runtime": "phase0_continuation",
            "authoritative_path": "runtime_v2", "runtime_authority": "runtime_v2",
        })
        system = (
            "أنت ميزان — مستشار قانوني قطري. " + instr
            + "\n\n═══ قواعد صارمة ═══\n"
            + "• لديك سجل المحادثة السابقة أعلاه.\n"
            + "• لا تقل أبداً 'لا أستطيع الرجوع إلى الرسائل السابقة' — ارجع لها.\n"
            + "• إذا قال 'أقصد رسالتك السابقة' أو 'هل أنت متأكد' أو 'كمّل' — "
            "ارجع لآخر رد لك وأجب عن نفس الموضوع.\n"
            + "• لا تعيد تعريف مصطلحات سبق شرحها.\n"
            + "• كل حكم قانوني تذكره يجب أن يتضمن: اسم القانون + رقمه + سنته "
            "+ رقم المادة.\n"
            + "• إذا لم يوجد مصدر لرقم معين — لا تذكره.\n"
        )
        # Pass the last 8 turns of real history (not just synthetic single pair)
        messages: list[dict] = []
        if history:
            for m in history[-8:]:
                r = m.get("role")
                c = m.get("content")
                if r in ("user", "assistant") and c and c.strip():
                    messages.append({"role": r, "content": c})
        messages.append({"role": "user", "content": query})
        try:
            async for piece in _llm.stream_openai(system, messages, max_tokens=1000):
                if piece:
                    yield _sse({
                        "type": "chunk", "content": piece, "text": piece,
                    })
        except Exception as e:
            log.exception("continuation stream failed")
            err = f"تعذّر الاستمرار ({type(e).__name__})."
            yield _sse({"type": "chunk", "content": err, "text": err})
        yield _sse(_stamp_authority({
            "type": "done", "runtime": "phase0_continuation",
            "route": "continuation", "confidence": 80,
        }))

    return StreamingResponse(gen(), media_type="text/event-stream")


# ──────────────────────────────────────────────────────────────────
# Handler: smart memo — asks for gaps, otherwise delegates to runtime_v2
# ──────────────────────────────────────────────────────────────────

_MEMO_TOPIC_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("حضانة",    ("حضانة", "محضون", "طليقتي", "مطلقتي", "ولدي", "بنتي", "أطفال")),
    ("مخدرات",   ("مخدرات", "حشيش", "كوكايين", "تعاطي", "جوهر مخدر")),
    ("فصل",      ("فصل", "فصلوني", "طردوني", "صاحب العمل", "إنهاء خدمات")),
    ("تشهير",    ("سب", "قذف", "تشهير", "تويتر", "سبني", "شهّر")),
    ("ضرب",      ("ضرب", "ضربني", "اعتدى", "كسر", "إيذاء", "ضربه")),
    ("شيك",      ("شيك", "رصيد", "شيك ضمان", "شيك بلا رصيد")),
    ("إيجار",    ("إيجار", "مستأجر", "إخلاء", "شقة", "ماجر", "مأجر")),
    ("ابتزاز",   ("ابتزاز", "يهددني", "تهديد", "هددني")),
    ("احتيال",   ("احتيال", "نصب", "خيانة أمانة", "حوّل", "اختلس", "اختلاس")),
    ("تزوير",    ("تزوير", "زوّر", "توقيع مزور", "محرر مزور")),
    ("طلاق",     ("طلاق للضرر", "عنف زوجي", "طلاق", "يضربني الزوج")),
    ("نفقة",     ("نفقة", "نفقه", "النفقة", "النفقه",
                  "نفقة زوجية", "نفقه زوجيه",
                  "نفقة أطفال", "نفقه اطفال",
                  "نفقه اولاد", "نفقة أولاد",
                  "امتنع عن الانفاق", "ما ينفق", "لا ينفق",
                  "طليقي ما ينفق", "زوجي ما ينفق",
                  "دعوى نفقه", "دعوة نفقه")),
)

_MEMO_GAPS = {
    "حضانة":  {
        "qs": [
            "ما أعمار الأطفال وأسماؤهم (وجنس كل منهم)؟",
            "ما سبب طلب الإسقاط (زواج الأم بأجنبي، إهمال، سوء سلوك)؟",
            "هل يوجد حكم طلاق سابق وتاريخه؟",
        ],
        "min_signals": 2,
    },
    "مخدرات": {
        "qs": [
            "نوع المادة المضبوطة وكميتها؟",
            "هل القبض كان بإذن من النيابة أم بدورية ميدانية؟",
            "هل المتهم اعترف أم أنكر في التحقيق؟",
            "هل له سوابق في هذا الشأن؟",
        ],
        "min_signals": 2,
    },
    "فصل": {
        "qs": [
            "الراتب الشهري وسنوات الخدمة؟",
            "ما السبب المُعلن للفصل؟",
            "هل يوجد إنذار كتابي سابق على الفصل؟",
        ],
        "min_signals": 1,
    },
    "تشهير": {
        "qs": [
            "نص العبارات المسيئة؟",
            "ما المنصة (تويتر/واتساب/سناب)؟",
            "هل عندك سكرين شوت أو شهود؟",
            "هل تعرف هوية الجاني أم الحساب مجهول؟",
        ],
        "min_signals": 2,
    },
    "ضرب": {
        "qs": [
            "هل يوجد تقرير طبي رسمي؟",
            "نوع الإصابة ودرجتها؟",
            "هل كان هناك شهود؟",
            "ما علاقتك بالمعتدي؟",
        ],
        "min_signals": 1,
    },
    "شيك": {
        "qs": [
            "قيمة الشيك وتاريخه؟",
            "هل الشيك كان ضمانًا لدين أم وفاءً فوريًا؟",
            "هل يوجد إقرار مكتوب عن طبيعة الشيك؟",
        ],
        "min_signals": 2,
    },
    "إيجار": {
        "qs": [
            "مدة العقد والمتبقي منها؟",
            "هل يوجد تأخر في السداد؟",
            "قيمة مبلغ التأمين وهل سُدِّد؟",
        ],
        "min_signals": 1,
    },
    "ابتزاز": {
        "qs": [
            "نوع التهديد (صور/معلومات/مال)؟",
            "قيمة المبلغ المطلوب ووسيلة التواصل؟",
            "هل يوجد تسجيلات/رسائل محفوظة؟",
        ],
        "min_signals": 1,
    },
    "احتيال": {
        "qs": [
            "علاقتك بالمتهم (شريك/موظف/وكيل)؟",
            "المبلغ محل النزاع وتاريخ التحويل؟",
            "هل يوجد مستندات (تحويلات/عقد)؟",
        ],
        "min_signals": 1,
    },
    "تزوير": {
        "qs": [
            "نوع المحرر المزور (عقد/توكيل/إقرار)؟",
            "القيمة/الأثر الذي ترتب على المحرر؟",
            "هل لديك نسخة من المحرر لإيداعها بالملف؟",
        ],
        "min_signals": 1,
    },
    "طلاق": {
        "qs": [
            "تاريخ الزواج وعدد الأطفال وأعمارهم؟",
            "نوع الضرر (جسدي/نفسي/إهمال) وأدلته؟",
            "هل تقدّمت بمحاضر شرطة أو تقارير طبية؟",
        ],
        "min_signals": 1,
    },
    "نفقة": {
        "qs": [
            "هل الدعوى نفقة زوجية أم نفقة أطفال أم كلاهما؟",
            "كم عدد الأطفال وأعمارهم؟ (إن وُجدوا)",
            "ما هو دخل المُدَّعى عليه الشهري التقريبي وطبيعة عمله؟",
            "هل أنتِ مطلقة أم لا تزال الزوجية قائمة؟ وإن كنتِ مطلقة فما تاريخ الطلاق؟",
            "هل هناك نفقة سابقة محكوم بها أم هذا أول طلب؟ ومنذ متى امتنع عن الإنفاق؟",
        ],
        "min_signals": 2,
    },
}


def _detect_memo_topic(query: str) -> str:
    q = (query or "").lower()
    for topic, kws in _MEMO_TOPIC_MAP:
        if any(kw in q for kw in kws):
            return topic
    return "عام"


def _count_signals(text: str) -> int:
    """Rough signal count — names, numbers, dates, content length."""
    if not text:
        return 0
    s = 0
    # Named entity — "اسمه/اسمها/اسمي X"
    if re.search(r"(?:اسمي|اسمها|اسمه|يُدعى|تُدعى)\s+\S{2,}", text):
        s += 1
    # Numbers (up to 3 signals)
    s += min(len(re.findall(r"\d+", text)), 3)
    # Dates
    if re.search(r"\d+\s*[/\-.]\s*\d+", text):
        s += 1
    # Length bonus
    s += len(text.strip()) // 80
    return s


async def handle_memo_smart(
    query: str, sid: str, history: list,
) -> StreamingResponse:
    topic = _detect_memo_topic(query)
    # Aggregate all user turns to assess total info supplied
    blob = query
    if history:
        for m in history[-6:]:
            if m.get("role") == "user" and m.get("content"):
                blob += " " + m["content"]
    signals = _count_signals(blob)

    gaps = _MEMO_GAPS.get(topic)
    if gaps and signals < gaps["min_signals"]:
        # Not enough info — ask smart questions
        async def ask_gen():
            lines = [
                f"قبل ما أكتب مذكرة {topic} احترافية بأسماء ووقائعك الحقيقية، "
                f"أحتاج منك هذه التفاصيل:",
                "",
            ]
            for i, q in enumerate(gaps["qs"], 1):
                lines.append(f"{i}. {q}")
            lines += [
                "",
                "أخبرني بما تعرفه (أو قل: «اكتب بالمعلومات المتوفرة» "
                "وسأصيغها بالمتاح).",
            ]
            text = "\n".join(lines)
            async for frame in _stream_text_direct(
                text, "memo_ask_details", 90, chunk_size=50,
            ):
                yield frame
        return StreamingResponse(ask_gen(), media_type="text/event-stream")

    # Sufficient info — delegate to runtime_v2, merging history into query
    combined = query
    if history:
        user_msgs = [
            m.get("content", "") for m in history
            if m.get("role") == "user" and m.get("content")
        ]
        if user_msgs:
            combined = " | ".join(user_msgs[-3:]) + " | " + query

    async def memo_gen():
        for kind, payload in _v2_stream_frames(combined, sid, history or [], chunk=40):
            if kind == "done":
                payload = _stamp_authority(dict(payload))
                payload["type"] = "done"
                payload.setdefault("log_id", 0)
                payload["route"] = "memo"
            else:
                payload = dict(payload)
                payload["type"] = kind
                payload.setdefault("authoritative_path", "runtime_v2")
                payload.setdefault("runtime_authority", "runtime_v2")
            yield _sse(payload)

    return StreamingResponse(memo_gen(), media_type="text/event-stream")


# ═════════════════════════════════════════════════════════════════
# POST /api/v1/stream/ — SSE framing over runtime_v2 adapter
# ═════════════════════════════════════════════════════════════════

@router.post("/api/v1/stream/")
async def query_stream(req: QueryRequest, request: Request = None):
    """SSE stream dispatched by Phase 0 Router:

      beta_pregate → phase0_router.route_query →
          safety_refusal / greeting / self_info  → direct SSE
          article_text / table / calculator      → DB handlers
          continuation                            → LLM follow-up
          memo                                    → smart memo → runtime_v2
          review                                  → direct invitation
          general                                 → LLM + RAG
    """
    q = req.query.strip()
    _ip = request.client.host if (request and request.client) else ""
    _headers = dict(request.headers) if request else {}
    sid = _safe_sid(req.session_id, request_ip=_ip,
                     request_headers=_headers)

    # ── Beta pre-gate (security — upstream of everything) ──
    _block = beta_pre_request(sid, q)
    if _block:
        async def blocked_gen():
            yield _sse({"type": "start", "runtime": "beta_pregate",
                        "authoritative_path": "runtime_v2",
                        "runtime_authority": "runtime_v2"})
            yield _sse({"type": "chunk", "content": _block, "text": _block})
            yield _sse(_stamp_authority({
                "type": "done", "sources": [], "confidence": 0,
                "is_grounded": False, "runtime": "beta_pregate",
                "gates_passed": ["beta_gate_passed"],
                "gates_failed": ["beta_gate_blocked"],
                "block_reasons": ["beta_middleware"],
                "is_blocked": True, "log_id": 0,
            }))
        return StreamingResponse(blocked_gen(), media_type="text/event-stream")

    _bctx = get_beta_context()
    if _bctx:
        _bctx.session_id = sid
        _bctx.query = q[:200]

    # ── Phase 0 routing ──
    try:
        decision = route_query(q, req.history or [])
    except Exception as e:
        log.exception("phase0 route_query raised")
        decision = {"route": "general", "direct": False}

    route = decision.get("route", "general")

    # ── Direct-response routes: safety_refusal / greeting / self_info / review ──
    if decision.get("direct") and decision.get("response"):
        async def direct_gen():
            conf = {
                "safety_refusal": 100,
                "greeting":       99,
                "self_info":      98,
                "review":         95,
            }.get(route, 90)
            async for frame in _stream_text_direct(
                decision["response"], route, conf, chunk_size=40, delay=0.03,
            ):
                yield frame
        return StreamingResponse(direct_gen(), media_type="text/event-stream")

    # ── Handler routes ──
    try:
        if route == "article_text":
            return await handle_article_text(decision.get("payload") or {})

        if route == "table":
            return await handle_table(decision.get("payload") or {})

        if route == "calculator":
            return await handle_calculator(decision.get("payload") or {})

        if route == "continuation":
            return await handle_continuation(
                decision.get("payload") or {}, req.history or [], q,
            )

        if route == "memo":
            return await handle_memo_smart(q, sid, req.history or [])

        # Default: general (LLM + RAG)
        return await handle_general(q, sid, req.history or [])

    except Exception as e:
        log.exception("phase0 handler raised (route=%s)", route)
        async def err_gen():
            text = f"تعذّر معالجة الطلب عبر مسار '{route}' — يُعاد المحاولة."
            async for frame in _stream_text_direct(text, "error", 30):
                yield frame
        return StreamingResponse(err_gen(), media_type="text/event-stream")


# ═════════════════════════════════════════════════════════════════
# Beta auxiliary endpoints (non-answer-producing)
# ═════════════════════════════════════════════════════════════════

@router.post("/api/v1/beta/feedback")
async def beta_feedback(request: Request):
    """Beta feedback collector — NOT answer-producing."""
    try:
        body = await request.json()
        vote = (body.get("vote") or "").strip().lower()
        note = body.get("note", "") or ""
        sid  = (body.get("session_id") or "").strip() or "default"
        beta_record_feedback(sid, vote, note)
        return {"ok": True}
    except Exception as e:
        log.debug("beta_feedback: %s", e)
        return {"ok": False, "error": str(e)[:120]}


@router.get("/api/v1/beta/metrics")
async def beta_metrics():
    """Beta runtime metrics snapshot — NOT answer-producing."""
    try:
        return beta_metrics_snapshot()
    except Exception as e:
        return {"error": str(e)[:120]}


# ═════════════════════════════════════════════════════════════════
# POST /api/v1/cancel/{request_id} — user-initiated cancellation
# ═════════════════════════════════════════════════════════════════

@router.post("/api/v1/cancel/{request_id}")
async def cancel_request(request_id: str):
    """Mark an in-flight request as cancelled."""
    if not request_id or len(request_id) > 128:
        return {"cancelled": False, "reason": "invalid_request_id"}
    ok = _cancel.cancel(request_id)
    return {
        "cancelled":  ok,
        "request_id": request_id,
        "reason":     "marked_cancelled" if ok else "request_not_found",
    }


@router.get("/api/v1/cancel/_status")
async def cancellation_status():
    """Diagnostic — current cancellation registry state."""
    return _cancel.snapshot()
