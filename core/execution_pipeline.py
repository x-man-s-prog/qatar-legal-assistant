# -*- coding: utf-8 -*-
"""
Core Execution Pipeline — STABILIZATION REBUILD
=================================================
Deterministic, isolated, grounded execution engine.

Wraps existing reasoning layers (legal_thinking_engine, expert_legal_analysis,
legal_grounding) inside a strict 8-step pipeline with hard isolation,
hard routing, hard grounding, and bounded latency.

Does NOT modify any reasoning engine. Only orchestrates them.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.legal_thinking_engine import (
    LegalThinkingEngine, IssueType, ISSUE_TYPE_AR,
)
from core.expert_legal_analysis import (
    ExpertLegalAnalysisEngine, format_expert_analysis,
)
from core.legal_grounding import (
    LegalGroundingEngine, ground_legal_text,
)
from core.stabilization import (
    resolve_safe_session_id, detect_query_domain,
    domains_compatible, safe_clean,
)
# CONTROLLED REASONING CORE: deterministic-first authority
from core.controlled_reasoning_core import (
    ControlledLegalDecisionCore, LegalDecisionRecord,
    LegalAnswerFormatter, AnswerFidelityGuard, LLMUsageGate,
)
# PHASE INTELLIGENT DECISION: strategic branching (operates on record only)
from core.intelligent_decision_engine import (
    enhance_with_branches as _intelligent_enhance,
)

log = logging.getLogger("execution_pipeline")


# ══════════════════════════════════════════════════════════════
# 1. RequestContext — per-request isolation
# ══════════════════════════════════════════════════════════════

@dataclass
class RequestContext:
    """Isolated per-request state. NO global mutation. NO cross-request reuse."""
    request_id: str = ""
    session_id: str = ""
    raw_query: str = ""
    normalized_query: str = ""
    timestamp: float = 0.0
    isolated_memory: dict = field(default_factory=dict)
    domain: str = ""
    issue_type: str = ""
    pipeline_steps_completed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, query: str,
                session_id: Optional[str] = None,
                request_ip: str = "",
                request_headers: Optional[dict] = None) -> "RequestContext":
        """Build a fresh context. Session-isolated by default."""
        return cls(
            request_id=f"req_{uuid.uuid4().hex[:16]}",
            session_id=resolve_safe_session_id(
                session_id, request_ip=request_ip,
                request_headers=request_headers),
            raw_query=query.strip() if query else "",
            timestamp=time.time(),
        )

    def mark_step(self, name: str) -> None:
        self.pipeline_steps_completed.append(name)


# ══════════════════════════════════════════════════════════════
# 2. HardRouter — first-step classification
# ══════════════════════════════════════════════════════════════

class QueryType(str, Enum):
    LEGAL_CONSULTATION = "legal_consultation"  # personal litigation question
    GENERAL_INFO = "general_info"               # what is the law on X
    PROCEDURAL = "procedural"                   # how do I file/appeal/...
    GREETING = "greeting"
    REJECT = "reject"                            # invalid/empty/abusive


# Compact router signal library — first-step classification only.
# All downstream layers receive the router decision read-only.
_DOMAIN_ROUTER_KEYWORDS = {
    "employment": [
        "فصل", "فصلوني", "طردوني", "استقالة", "راتب", "مكافأة",
        "عقد عمل", "عقدي", "كفيل", "وزارة العمل", "صاحب العمل",
    ],
    "criminal": [
        "متهم", "تهمة", "النيابة", "مخدرات", "سرقة", "جنائي",
        "جريمة", "قبض", "حبس", "ابتزاز", "اعتداء",
        # PHASE INTELLIGENT DECISION — verb forms
        "اتهامي", "اتهموني", "تم اتهامي", "موقوف", "مشتبه",
        "تحقيق معي", "استدعوني", "استجوبوني", "قبض علي",
    ],
    "family": [
        "طلاق", "حضانة", "نفقة", "زوج", "زوجة", "زوجي", "زوجتي",
        "طليقتي", "طليقي", "أطفال", "ميراث", "خلع", "أحوال شخصية",
        # PHASE INTELLIGENT DECISION — inheritance
        "تركة", "الورثة", "قسمة التركة", "نصيب من التركة",
    ],
    "rental": [
        "إيجار", "مستأجر", "مالك", "شقة", "إخلاء", "عقد إيجار",
    ],
    "civil": [
        "دين", "مبلغ", "قرض", "تعويض", "عقد",
    ],
    "commercial": [
        # PHASE INTELLIGENT DECISION — commercial/partnership
        "شراكة", "شريك في مشروع", "الشركاء", "حصص الشركاء",
        "خسارة المشروع", "نزاع تجاري", "توزيع الأرباح",
        "ملكية فكرية", "علامة تجارية",
        "سرق فكرتي", "استولى على فكرتي",
    ],
    "administrative": [
        "قرار إداري", "جهة حكومية", "ديوان المظالم", "تظلم إداري",
        # PHASE INTELLIGENT DECISION — admin timing
        "تاريخ العلم", "تاريخ الإخطار", "مهلة التظلم",
    ],
    "banking": [
        "بنك", "مصرف", "شيك", "حساب بنكي", "ائتمان",
        # PHASE INTELLIGENT DECISION — banking ops
        "البنك خصم", "خصم من حسابي", "بطاقة مصرفية",
        "تحويل بنكي", "بدون تفويض", "عملية بنكية",
    ],
    "procedural": [
        "طعن", "استئناف", "تمييز", "تنفيذ حكم", "تبليغ", "مهلة",
    ],
}

_GREETING_PATTERNS = ["مرحبا", "السلام عليكم", "أهلا", "هاي", "صباح الخير", "مساء الخير"]

_CONSULTATION_TRIGGERS = [
    "نقاط ضعفي", "نقاط قوتي", "موقفي", "وضعي",
    "هل أقدر", "هل يحق", "ما عندي", "ماذا يحتج به",
    "الطرف الآخر", "الطرف الثاني", "صاحب العمل",
    "ما أعرف متى", "تأخرت",
]

_GENERAL_INFO_TRIGGERS = [
    "ما عقوبة", "ما حكم", "ما هي", "كم", "هل يعتبر",
]

_PROCEDURAL_TRIGGERS = [
    "كيف أرفع", "كيف أقدم", "كيف أطعن", "ما الخطوة",
    "إجراءات", "كيف ينفذ",
]

# Disallowed cross-combinations — router rejects these to prevent leakage
_INVALID_COMBINATIONS = {
    # (domain_a, domain_b) when both clearly present without a meta-issue
    # (currently empty — cross-domain handled downstream by cross_domain_reasoner)
}


@dataclass
class RouterResult:
    domain: str = "general"
    query_type: QueryType = QueryType.GENERAL_INFO
    confidence: float = 0.0
    needs_grounding: bool = True
    reject_reason: str = ""
    detected_domains: list[str] = field(default_factory=list)


class HardRouter:
    """First-step classifier. Runs BEFORE anything else. Decision is final."""

    def route(self, query: str) -> RouterResult:
        if not query or not query.strip():
            return RouterResult(query_type=QueryType.REJECT,
                                  reject_reason="empty query",
                                  needs_grounding=False)

        q = query.strip()

        # Greeting check
        if any(q.startswith(g) or g in q[:30] for g in _GREETING_PATTERNS) \
           and len(q.split()) <= 4:
            return RouterResult(domain="general",
                                  query_type=QueryType.GREETING,
                                  confidence=1.0,
                                  needs_grounding=False)

        # Domain detection (multi-vote)
        detected = []
        for domain, kws in _DOMAIN_ROUTER_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in q)
            if score > 0:
                detected.append((domain, score))
        detected.sort(key=lambda x: -x[1])

        primary_domain = detected[0][0] if detected else "general"
        confidence = (detected[0][1] / 6.0) if detected else 0.0
        confidence = min(1.0, confidence)

        # Query-type classification
        if any(t in q for t in _CONSULTATION_TRIGGERS):
            qtype = QueryType.LEGAL_CONSULTATION
        elif any(t in q for t in _PROCEDURAL_TRIGGERS):
            qtype = QueryType.PROCEDURAL
        elif any(t in q for t in _GENERAL_INFO_TRIGGERS):
            qtype = QueryType.GENERAL_INFO
        else:
            qtype = (QueryType.LEGAL_CONSULTATION if primary_domain != "general"
                     else QueryType.GENERAL_INFO)

        result = RouterResult(
            domain=primary_domain,
            query_type=qtype,
            confidence=confidence,
            needs_grounding=(qtype != QueryType.GREETING),
            detected_domains=[d for d, _ in detected],
        )

        log.info("[ROUTER] domain=%s type=%s conf=%.2f detected=%s",
                 result.domain, result.query_type.value,
                 result.confidence, result.detected_domains)
        return result


# ══════════════════════════════════════════════════════════════
# 3. SafeCache — strict scoping, short TTL
# ══════════════════════════════════════════════════════════════

class SafeCache:
    """In-memory cache with strict (query, domain, issue_type) scoping."""

    DEFAULT_TTL = 60.0  # seconds — short by design

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}

    @staticmethod
    def make_key(query: str, domain: str, issue_type: str = "") -> str:
        # Normalize: lowercase + strip + collapse whitespace
        norm = re.sub(r"\s+", " ", query.strip())
        # Domain + issue_type are part of the key — never reuse cross-domain
        raw = f"{domain}|{issue_type}|{norm}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any, ttl: float = DEFAULT_TTL) -> None:
        self._store[key] = (time.time() + ttl, value)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        return len(self._store)

    def is_safe_to_cache(self, ctx: RequestContext,
                          router: RouterResult) -> bool:
        """Refuse to cache when content-quality risk is too high."""
        # Don't cache reject/greeting
        if router.query_type in (QueryType.REJECT, QueryType.GREETING):
            return False
        # Don't cache structured analysis with very low confidence routing
        if router.confidence < 0.3 and router.query_type == QueryType.LEGAL_CONSULTATION:
            return False
        return True


# ══════════════════════════════════════════════════════════════
# 4. ContextGuard — clears unrelated prior context
# ══════════════════════════════════════════════════════════════

class ContextGuard:
    """Decides whether previous-request context can be carried over."""

    SIMILARITY_THRESHOLD = 0.30
    # Followup is only allowed when the new query has explicit followup markers
    _FOLLOWUP_MARKERS = [
        "وبالنسبة", "طيب", "وإذا", "وماذا عن", "ولو", "وبخصوص", "أيضاً",
    ]

    def should_clear(self, prev_domain: str, new_domain: str,
                      similarity: float) -> bool:
        """Clear prior context when domain shifts OR similarity is too low."""
        if not prev_domain or not new_domain:
            return False
        if prev_domain != new_domain and not domains_compatible(prev_domain, new_domain):
            return True
        if similarity < self.SIMILARITY_THRESHOLD:
            return True
        return False

    def is_explicit_followup(self, query: str) -> bool:
        if not query:
            return False
        return any(query.strip().startswith(m) or m in query[:25]
                   for m in self._FOLLOWUP_MARKERS)

    def should_allow_followup(self, query: str,
                                marked_followup: bool = False) -> bool:
        """Only allow followup when explicit marker present or caller marked."""
        return marked_followup or self.is_explicit_followup(query)

    def jaccard_similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        sa = set(a.split())
        sb = set(b.split())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)


# ══════════════════════════════════════════════════════════════
# 5. Output Structure Lock
# ══════════════════════════════════════════════════════════════

@dataclass
class StructuredOutput:
    """All pipeline outputs MUST conform to this shape."""
    request_id: str = ""
    issue_type: str = ""
    issue_type_label: str = ""
    domain: str = ""
    key_facts: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    opposing_arguments: list[str] = field(default_factory=list)
    proof_needed: list[str] = field(default_factory=list)
    next_step: str = ""
    authority_path: str = ""
    formatted_text: str = ""
    pipeline_steps_completed: list[str] = field(default_factory=list)
    fallback_applied: bool = False
    grounding_blocked: int = 0
    elapsed_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 6. SafeExecutionWrapper — error containment
# ══════════════════════════════════════════════════════════════

class SafeExecutionWrapper:
    """Wraps any callable with timeout + try/except + fallback."""

    @staticmethod
    def safe_call(fn: Callable, *args, fallback: Any = None,
                   label: str = "stage", timeout: float = 2.0,
                   **kwargs) -> tuple[Any, bool]:
        """
        Run a SYNC function with a soft timeout (best-effort) and exception
        catch. Returns (result, ok) where ok=False means fallback used.
        """
        start = time.time()
        try:
            result = fn(*args, **kwargs)
            elapsed = time.time() - start
            if elapsed > timeout:
                log.warning("[SAFE_EXEC] %s took %.2fs (over timeout %.2fs)",
                            label, elapsed, timeout)
            return result, True
        except Exception as e:
            log.warning("[SAFE_EXEC] %s failed: %s — using fallback", label, e)
            return fallback, False

    @staticmethod
    async def safe_async_call(coro, fallback: Any = None,
                                label: str = "stage",
                                timeout: float = 2.0) -> tuple[Any, bool]:
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            return result, True
        except asyncio.TimeoutError:
            log.warning("[SAFE_EXEC] %s timeout after %.2fs", label, timeout)
            return fallback, False
        except Exception as e:
            log.warning("[SAFE_EXEC] %s failed: %s", label, e)
            return fallback, False

    @staticmethod
    def fallback_output(ctx: RequestContext, router: RouterResult,
                         reason: str = "") -> StructuredOutput:
        """Safe minimal output when pipeline fails."""
        out = StructuredOutput(
            request_id=ctx.request_id,
            domain=router.domain,
            issue_type="unknown",
            issue_type_label="غير محدد",
            fallback_applied=True,
            pipeline_steps_completed=list(ctx.pipeline_steps_completed),
        )
        if router.query_type == QueryType.GREETING:
            out.formatted_text = "مرحباً، كيف يمكنني مساعدتك في استشارتك القانونية؟"
        elif router.query_type == QueryType.REJECT:
            out.formatted_text = "الرجاء إدخال سؤال قانوني واضح."
        else:
            out.formatted_text = (
                "تعذر إنتاج تحليل مفصّل لهذه المسألة. "
                "يُرجى توضيح المجال القانوني (عمل / مدني / أسرة / إيجار / "
                "إداري / جنائي / إجرائي) وإعادة المحاولة."
            )
        if reason:
            out.notes.append(f"fallback_reason:{reason}")
        return out


# ══════════════════════════════════════════════════════════════
# 7. ExecutionPipeline — strict 8-step orchestrator
# ══════════════════════════════════════════════════════════════

# Per-stage time budget (seconds). Total budget kept under ~10s.
_STAGE_TIMEOUT = 2.0
_PIPELINE_TIMEOUT = 10.0


class ExecutionPipeline:
    """
    Strict 8-step pipeline. NO skipping. NO reordering. NO hidden calls.
      1. RequestContext init
      2. HardRouter classification
      3. Minimal query normalization (no expansion)
      4. LegalThinkingEngine
      5. ExpertAnalysis
      6. LegalGroundingEngine (HARD GATE — must block invalid)
      7. OutputAssembler (StructuredOutput)
      8. ResponseCleaner (final pass)
    """

    def __init__(self, llm_caller=None):
        self._router = HardRouter()
        self._cache = SafeCache()
        self._guard = ContextGuard()
        self._safe = SafeExecutionWrapper()
        # Legacy direct-engine handles (kept for backward compat)
        self._brain = LegalThinkingEngine()
        self._expert = ExpertLegalAnalysisEngine()
        self._grounding = LegalGroundingEngine()
        # CONTROLLED REASONING CORE: new authority layer
        self._controlled_core = ControlledLegalDecisionCore()
        self._formatter = LegalAnswerFormatter(llm_caller=llm_caller)
        self._fidelity = AnswerFidelityGuard()
        self._llm_gate = LLMUsageGate()

    # ── Pipeline cache control (intentionally per-instance, not global) ──
    def clear_cache(self) -> None:
        self._cache.clear()

    def cache_size(self) -> int:
        return self._cache.size()

    # ── Main entry ──

    def execute(self, query: str,
                  session_id: Optional[str] = None,
                  request_ip: str = "",
                  request_headers: Optional[dict] = None,
                  prev_query: str = "",
                  prev_domain: str = "",
                  marked_followup: bool = False) -> StructuredOutput:
        """
        Synchronous strict pipeline. Returns a StructuredOutput in ALL paths.
        Fallback applied silently on any internal failure.
        """
        start = time.time()

        # ─── Step 1: RequestContext init ───
        ctx = RequestContext.create(
            query=query, session_id=session_id,
            request_ip=request_ip, request_headers=request_headers)
        ctx.mark_step("1.context_init")

        # ─── Step 2: HardRouter ───
        router_res, ok = self._safe.safe_call(
            self._router.route, ctx.raw_query,
            fallback=RouterResult(query_type=QueryType.REJECT,
                                    reject_reason="router_failed"),
            label="router", timeout=_STAGE_TIMEOUT)
        ctx.mark_step("2.router")
        ctx.domain = router_res.domain

        # Early exit: greeting / reject
        if router_res.query_type in (QueryType.GREETING, QueryType.REJECT):
            out = self._safe.fallback_output(ctx, router_res,
                                                reason=router_res.reject_reason or "no_consultation")
            out.elapsed_seconds = time.time() - start
            return out

        # ─── Step 2.5: ContextGuard ───
        # Decide whether prior session context can be reused. By default — NO.
        clear_context = True
        if marked_followup or self._guard.is_explicit_followup(ctx.raw_query):
            similarity = self._guard.jaccard_similarity(ctx.raw_query, prev_query)
            clear_context = self._guard.should_clear(
                prev_domain, router_res.domain, similarity)
        if clear_context:
            ctx.notes.append("context_cleared_by_guard")
        ctx.mark_step("2.5.context_guard")

        # ─── Step 2.7: SafeCache lookup ───
        cache_key = SafeCache.make_key(
            ctx.raw_query, router_res.domain, router_res.query_type.value)
        if self._cache.is_safe_to_cache(ctx, router_res):
            cached = self._cache.get(cache_key)
            if cached is not None:
                ctx.mark_step("2.7.cache_hit")
                cached.notes.append("cache_hit")
                cached.elapsed_seconds = time.time() - start
                return cached

        # ─── Step 3: Minimal normalization (NO expansion) ───
        ctx.normalized_query = ctx.raw_query.strip()
        # Collapse multiple spaces, no other transformation
        ctx.normalized_query = re.sub(r"\s+", " ", ctx.normalized_query)
        ctx.mark_step("3.normalization")

        # ─── Step 4: ControlledLegalDecisionCore ───
        # Replaces direct brain+expert calls. Produces a single LegalDecisionRecord
        # that is the SOLE source of truth for downstream formatting.
        record, ok = self._safe.safe_call(
            self._controlled_core.build_decision_record,
            ctx.normalized_query, router_res.domain,
            fallback=None, label="controlled_core", timeout=_STAGE_TIMEOUT)
        ctx.mark_step("4.controlled_core")
        if record is None:
            out = self._safe.fallback_output(
                ctx, router_res, reason="controlled_core_failed")
            out.elapsed_seconds = time.time() - start
            return out
        ctx.issue_type = record.issue_type

        # Early exit: if record is non-substantive and router confidence low
        if not record.is_substantive() and router_res.confidence < 0.3:
            out = self._safe.fallback_output(
                ctx, router_res, reason="non_substantive_low_confidence")
            out.elapsed_seconds = time.time() - start
            return out

        # ─── Step 5: LLMUsageGate + Formatter (template OR LLM) ───
        # The formatter internally uses the gate to decide template vs LLM.
        # Default: deterministic template (no LLM).
        format_res, ok = self._safe.safe_call(
            self._formatter.format, record, ctx.normalized_query,
            fallback=None, label="formatter", timeout=_STAGE_TIMEOUT)
        ctx.mark_step("5.formatter")
        if format_res is None or not format_res.text:
            out = self._safe.fallback_output(
                ctx, router_res, reason="formatter_failed")
            out.elapsed_seconds = time.time() - start
            return out
        rendered = format_res.text

        # ─── Step 6: LegalGroundingEngine (HARD GATE) ───
        ground_result, ok = self._safe.safe_call(
            self._grounding.ground_text, rendered, router_res.domain,
            fallback=None, label="grounding", timeout=_STAGE_TIMEOUT)
        ctx.mark_step("6.grounding")
        if ground_result is None:
            safe_text = self._grounding.convert_to_safe_analysis_mode(rendered)
            grounding_blocked_count = 0
        else:
            safe_text = ground_result.text
            grounding_blocked_count = len(ground_result.citations_blocked)

        # ─── Step 6.5: AnswerFidelityGuard ───
        # Verifies the formatted text preserves the record (catches drift if
        # an LLM was used; passes trivially when template was used).
        is_faithful, fidelity_violations = self._fidelity.verify(record, safe_text)
        if not is_faithful and format_res.used_llm:
            # LLM drifted — discard and fall back to deterministic template
            log.warning("[FIDELITY] LLM output drifted, falling back to template: %s",
                         fidelity_violations)
            from core.controlled_reasoning_core import DeterministicAnswerTemplateEngine
            template = DeterministicAnswerTemplateEngine()
            safe_text = template.render(record)
            # Re-ground the template output
            ground_result, _ = self._safe.safe_call(
                self._grounding.ground_text, safe_text, router_res.domain,
                fallback=None, label="grounding_fallback", timeout=_STAGE_TIMEOUT)
            if ground_result:
                safe_text = ground_result.text
        ctx.mark_step("6.5.fidelity_guard")

        # ─── Step 6.7: IntelligentDecisionEngine (strategic branching) ───
        # Operates on the LegalDecisionRecord (already built). Adds bounded,
        # deterministic strategic branches when activation criteria are met.
        # No new legal substance — only re-frames existing fields.
        _branched = False
        try:
            branched_text, _branch_plan, _branched = _intelligent_enhance(
                safe_text, record, ctx.normalized_query)
            if _branched:
                safe_text = branched_text
        except Exception as _br_err:
            log.debug("intelligent_branching (non-critical): %s", _br_err)
        ctx.mark_step("6.7.intelligent_branching")

        # ─── Step 7: OutputAssembler (StructuredOutput) ───
        ctx.mark_step("7.output_assembler")
        out = StructuredOutput(
            request_id=ctx.request_id,
            issue_type=record.issue_type,
            issue_type_label=record.issue_type_label,
            domain=router_res.domain,
            key_facts=list(record.key_facts),
            strengths=[s.text for s in record.strengths[:4]],
            weaknesses=[w.text for w in record.weaknesses[:4]],
            opposing_arguments=[o.text for o in record.opposing_arguments[:4]],
            proof_needed=[p.text for p in record.proof_needed[:4]],
            next_step=record.next_step,
            authority_path=record.authority_path,
            formatted_text=safe_text,
            pipeline_steps_completed=list(ctx.pipeline_steps_completed),
            grounding_blocked=grounding_blocked_count,
        )
        # Annotate notes with controlled-core observability
        out.notes.append(f"controlled_core_record_id:{record.record_id}")
        out.notes.append(f"controlled_core_fingerprint:{record.fingerprint()}")
        out.notes.append(f"formatter_used_llm:{format_res.used_llm}")
        if _branched:
            out.notes.append("intelligent_branching_applied")
        if not is_faithful:
            out.notes.append(f"fidelity_fallback:{fidelity_violations[:3]}")

        # ─── Step 8: ResponseCleaner ───
        cleaned, ok = self._safe.safe_call(
            safe_clean, out.formatted_text,
            fallback=out.formatted_text, label="response_cleaner",
            timeout=0.5)
        out.formatted_text = cleaned
        out.pipeline_steps_completed.append("8.response_cleaner")
        ctx.mark_step("8.response_cleaner")

        # ─── Cache safe result ───
        if self._cache.is_safe_to_cache(ctx, router_res):
            self._cache.put(cache_key, out)

        out.elapsed_seconds = time.time() - start
        log.info("[PIPELINE] req=%s domain=%s issue=%s steps=%d elapsed=%.2fs",
                 ctx.request_id, router_res.domain, record.issue_type,
                 len(out.pipeline_steps_completed), out.elapsed_seconds)
        return out


# ══════════════════════════════════════════════════════════════
# Module-level singleton + convenience
# ══════════════════════════════════════════════════════════════

_pipeline: Optional[ExecutionPipeline] = None


def get_pipeline() -> ExecutionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ExecutionPipeline()
    return _pipeline


def execute_pipeline(query: str,
                       session_id: Optional[str] = None,
                       **kwargs) -> StructuredOutput:
    """Convenience entry point."""
    return get_pipeline().execute(query, session_id=session_id, **kwargs)
