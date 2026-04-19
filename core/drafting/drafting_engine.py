# -*- coding: utf-8 -*-
"""
Drafting Engine — memo/pleading generation with hard safety.

Rules:
  - No LLM free generation.
  - No templates reused across unrelated cases.
  - No fabricated article numbers.
  - Safety modes: draftable | draftable_with_assumptions | not_draftable_yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph, IssueKind, IssueNode
from core.domain_pipeline.evidence_linker import IssueBoundEvidenceSet, EvidenceLink
from core.evidence.contract import EvidenceRecord


# ═════════════════════════════════════════════════════════════════
# Drafting contract types
# ═════════════════════════════════════════════════════════════════

class DocumentType(str, Enum):
    DEFENSE_MEMO          = "defense_memo"           # مذكرة دفاع
    REPLY_MEMO            = "reply_memo"             # مذكرة رد
    EXPLANATORY_MEMO      = "explanatory_memo"       # مذكرة شارحة
    PETITION_MEMO         = "petition_memo"          # مذكرة بطلب
    CLAIM_BRIEF           = "claim_brief"            # صحيفة دعوى مختصرة
    PLEADING_POINTS       = "pleading_points"        # نقاط مرافعة
    DEFENSE_CHECKLIST     = "defense_checklist"      # قائمة دفوع
    CASE_SUMMARY          = "case_summary"           # تلخيص ملف قضية


class ClientSide(str, Enum):
    CLAIMANT     = "claimant"      # مدعي
    DEFENDANT    = "defendant"     # مدعى عليه
    APPELLANT    = "appellant"     # مستأنف
    RESPONDENT   = "respondent"    # مستأنف ضده
    ACCUSED      = "accused"       # متهم
    VICTIM       = "victim"        # مجني عليه
    NEUTRAL      = "neutral"


class DraftingSafetyMode(str, Enum):
    DRAFTABLE                 = "draftable"
    DRAFTABLE_WITH_ASSUMPTIONS = "draftable_with_assumptions"
    NOT_DRAFTABLE_YET         = "not_draftable_yet"


@dataclass
class DraftingRequest:
    document_type:   DocumentType       = DocumentType.DEFENSE_MEMO
    client_side:     ClientSide         = ClientSide.NEUTRAL
    domain:          str                = ""
    subdomain:       str                = ""
    facts:           list[str]          = field(default_factory=list)
    explicit_requests: list[str]        = field(default_factory=list)


@dataclass
class DraftingResult:
    safety_mode:     DraftingSafetyMode = DraftingSafetyMode.NOT_DRAFTABLE_YET
    document_type:   str                = ""
    text:            str                = ""
    missing_inputs:  list[str]          = field(default_factory=list)
    assumptions:     list[str]          = field(default_factory=list)
    cited_laws:      list[str]          = field(default_factory=list)
    notes:           list[str]          = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "safety_mode":    self.safety_mode.value,
            "document_type":  self.document_type,
            "text_length":    len(self.text),
            "missing_inputs": self.missing_inputs,
            "assumptions":    self.assumptions,
            "cited_laws":     self.cited_laws,
            "notes":          self.notes,
        }


# ═════════════════════════════════════════════════════════════════
# Drafting intent detection (replaces the old blanket rejection)
# ═════════════════════════════════════════════════════════════════

class DraftingIntent(str, Enum):
    NONE                = "none"
    WRITE_DEFENSE_MEMO  = "write_defense_memo"
    WRITE_REPLY_MEMO    = "write_reply_memo"
    WRITE_CLAIM_BRIEF   = "write_claim_brief"
    WRITE_PLEADING      = "write_pleading"
    CONVERT_TO_MEMO     = "convert_to_memo"
    WRITE_GENERIC_MEMO  = "write_generic_memo"
    DEFENSE_CHECKLIST   = "defense_checklist"


_INTENT_PATTERNS = [
    (DraftingIntent.WRITE_DEFENSE_MEMO, [
        "اكتب لي مذكرة دفاع", "اكتب مذكرة دفاع",
        "صيغ لي مذكرة دفاع", "مذكرة دفاع",
    ]),
    (DraftingIntent.WRITE_REPLY_MEMO, [
        "اكتب لي مذكرة رد", "مذكرة رد",
    ]),
    (DraftingIntent.WRITE_CLAIM_BRIEF, [
        "صحيفة دعوى", "لائحة دعوى",
    ]),
    (DraftingIntent.CONVERT_TO_MEMO, [
        "حول الكلام إلى مذكرة", "حوّل الكلام إلى مذكرة",
        "حول هذا إلى مذكرة", "اكتبها بصيغة مذكرة",
    ]),
    (DraftingIntent.WRITE_PLEADING, [
        "نقاط مرافعة", "ترافع",
    ]),
    (DraftingIntent.DEFENSE_CHECKLIST, [
        "قائمة دفوع", "ما الدفوع الممكنة", "الدفوع المحتملة",
    ]),
    (DraftingIntent.WRITE_GENERIC_MEMO, [
        "اكتب لي مذكرة", "صيغ لي مذكرة", "اكتب مذكرة",
        "حرر لي مذكرة", "جهز لي مذكرة",
    ]),
]


def detect_drafting_intent(query: str) -> DraftingIntent:
    q = (query or "").strip()
    for intent, patterns in _INTENT_PATTERNS:
        for p in patterns:
            if p in q:
                return intent
    return DraftingIntent.NONE


def _intent_to_doc_type(intent: DraftingIntent) -> DocumentType:
    return {
        DraftingIntent.WRITE_DEFENSE_MEMO: DocumentType.DEFENSE_MEMO,
        DraftingIntent.WRITE_REPLY_MEMO:   DocumentType.REPLY_MEMO,
        DraftingIntent.WRITE_CLAIM_BRIEF:  DocumentType.CLAIM_BRIEF,
        DraftingIntent.WRITE_PLEADING:     DocumentType.PLEADING_POINTS,
        DraftingIntent.CONVERT_TO_MEMO:    DocumentType.EXPLANATORY_MEMO,
        DraftingIntent.DEFENSE_CHECKLIST:  DocumentType.DEFENSE_CHECKLIST,
        DraftingIntent.WRITE_GENERIC_MEMO: DocumentType.DEFENSE_MEMO,
    }.get(intent, DocumentType.DEFENSE_MEMO)


# ═════════════════════════════════════════════════════════════════
# Draftability assessment
# ═════════════════════════════════════════════════════════════════

def _assess_draftability(
    graph: Optional[IssueGraph],
    bound: Optional[IssueBoundEvidenceSet],
    facts_count: int,
    doc_type: DocumentType,
) -> tuple[DraftingSafetyMode, list[str]]:
    """Return (safety_mode, missing_inputs)."""
    missing: list[str] = []

    if graph is None or not graph.nodes:
        missing.append("issue_graph_unavailable")
    elif not graph.primary_issue:
        missing.append("no_primary_issue")

    if bound is None or not bound.links:
        missing.append("no_bound_evidence")
    elif graph and bound:
        coverage = bound.coverage_ratio(graph)
        if coverage < 0.30:
            missing.append(f"low_issue_coverage:{coverage:.2f}")

    if facts_count < 1:
        missing.append("insufficient_facts")

    # Memo type-specific requirements
    if doc_type == DocumentType.CLAIM_BRIEF and facts_count < 3:
        missing.append("claim_brief_needs_detailed_facts")

    # Decide safety mode
    hard_missing = [m for m in missing if m in (
        "issue_graph_unavailable", "no_primary_issue", "insufficient_facts")]
    if hard_missing:
        return (DraftingSafetyMode.NOT_DRAFTABLE_YET, missing)
    if missing:
        return (DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS, missing)
    return (DraftingSafetyMode.DRAFTABLE, missing)


# ═════════════════════════════════════════════════════════════════
# Memo composition (deterministic structure)
# ═════════════════════════════════════════════════════════════════

_DOC_TYPE_LABEL = {
    DocumentType.DEFENSE_MEMO:      "مذكرة دفاع",
    DocumentType.REPLY_MEMO:        "مذكرة رد",
    DocumentType.EXPLANATORY_MEMO:  "مذكرة شارحة",
    DocumentType.PETITION_MEMO:     "مذكرة بطلب",
    DocumentType.CLAIM_BRIEF:       "صحيفة دعوى",
    DocumentType.PLEADING_POINTS:   "نقاط مرافعة",
    DocumentType.DEFENSE_CHECKLIST: "قائمة الدفوع",
    DocumentType.CASE_SUMMARY:      "تلخيص ملف القضية",
}


from core.runtime.unified_entry import sealed_legacy as _sealed_legacy


@_sealed_legacy(
    reason="Legacy memo composer — replaced by MQE + PASL via DLP. "
           "Any call is a split-execution bug."
)
def _build_memo_text(
    request: DraftingRequest,
    graph: IssueGraph,
    bound: IssueBoundEvidenceSet,
    safety_mode: DraftingSafetyMode,
    missing: list[str],
) -> tuple[str, list[str]]:
    """Compose the Arabic memo text. Returns (text, cited_laws)."""
    doc_label = _DOC_TYPE_LABEL.get(request.document_type, "مذكرة قانونية")
    parts: list[str] = []
    cited_laws: list[str] = []

    # 1. Header
    parts.append(f"**{doc_label}**")
    parts.append("")
    if safety_mode == DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS:
        parts.append("> ⚠️ هذه الصياغة مبنية على افتراضات مذكورة أدناه. "
                     "ينبغي مراجعتها مع محامٍ قبل الإيداع.")
        parts.append("")

    # 2. Facts section (only from explicit facts provided)
    if request.facts:
        parts.append("**أولاً — الوقائع الثابتة:**")
        for i, fact in enumerate(request.facts[:8], 1):
            parts.append(f"{i}. {fact}")
        parts.append("")

    # 3. Legal issues (from the issue graph — NOT a generic template)
    primary = graph.nodes.get(graph.primary_issue) if graph.primary_issue else None
    secondary = graph.by_kind(IssueKind.SECONDARY)
    threshold = graph.by_kind(IssueKind.THRESHOLD)

    parts.append("**ثانياً — المسائل القانونية المطروحة:**")
    if primary:
        parts.append(f"• (جوهرية) {primary.question}")
    for t in threshold[:2]:
        parts.append(f"• (تمهيدية) {t.question}")
    for s in secondary[:2]:
        parts.append(f"• (فرعية) {s.question}")
    parts.append("")

    # 4. Applicable law (ONLY from bound evidence — canonical verified)
    parts.append("**ثالثاً — السند القانوني:**")
    direct_links = [L for L in bound.links if L.evidence_role == "direct"]
    seen_citations: set = set()
    for link in direct_links[:5]:
        cite = link.record.public_citation()
        if cite and cite not in seen_citations:
            seen_citations.add(cite)
            cited_laws.append(cite)
            parts.append(f"• {cite}")
    if not direct_links:
        parts.append("• لم يُعثر على سند نظامي مباشر بدرجة كافية. "
                     "يُوصى بإرفاق السند عند توفره.")
    parts.append("")

    # 5. Application (issue-by-issue, using linked evidence)
    parts.append("**رابعاً — التطبيق على الوقائع:**")
    for iid, node in graph.nodes.items():
        issue_links = bound.links_for(iid)
        if not issue_links:
            continue
        # Short paragraph per issue
        parts.append(f"**بشأن: {node.question}**")
        for link in issue_links[:2]:
            cite = link.record.public_citation()
            parts.append(f"يُستند إلى {cite} ({link.evidence_role}).")
        if node.required_proof:
            parts.append(
                f"عناصر الإثبات المطلوبة: {'، '.join(node.required_proof[:3])}."
            )
        parts.append("")

    # 6. Requests (based on client side + document type)
    parts.append("**خامساً — الطلبات:**")
    side_phrases = _requests_by_side(request.client_side, request.document_type,
                                         graph)
    for req in side_phrases:
        parts.append(f"• {req}")
    if request.explicit_requests:
        for req in request.explicit_requests[:3]:
            parts.append(f"• {req}")
    parts.append("")

    # 7. Assumptions list (only when with-assumptions mode)
    if safety_mode == DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS and missing:
        parts.append("**ملاحق — افتراضات الصياغة:**")
        for m in missing[:5]:
            parts.append(f"• {m}")

    return ("\n".join(parts), cited_laws)


def _requests_by_side(side: ClientSide, doc_type: DocumentType,
                       graph: IssueGraph) -> list[str]:
    remedies = graph.by_kind(IssueKind.REMEDY)
    remedy_question = remedies[0].question if remedies else ""
    if doc_type == DocumentType.DEFENSE_MEMO:
        return [
            "رفض الدعوى شكلاً وموضوعاً.",
            "إلزام الطرف الآخر بالمصاريف والرسوم.",
        ]
    if doc_type == DocumentType.CLAIM_BRIEF:
        reqs = ["قبول الدعوى شكلاً."]
        if remedy_question:
            reqs.append(f"الفصل في: {remedy_question}")
        reqs.append("إلزام المدعى عليه بالمصاريف والأتعاب.")
        return reqs
    if doc_type == DocumentType.REPLY_MEMO:
        return [
            "رد ادعاءات الخصم لعدم قيامها على سند صحيح.",
            "التمسك بما جاء في المذكرة السابقة.",
        ]
    if doc_type == DocumentType.DEFENSE_CHECKLIST:
        defenses = graph.by_kind(IssueKind.DEFENSE)
        if defenses:
            return [d.question for d in defenses[:3]]
        return ["انتفاء الركن المادي.", "انتفاء القصد.", "ضعف الإثبات."]
    return ["الفصل في المسألة المطروحة وفق النصوص المذكورة."]


# ═════════════════════════════════════════════════════════════════
# Public entry — build memo
# ═════════════════════════════════════════════════════════════════

def build_memo(
    request: DraftingRequest,
    graph: Optional[IssueGraph] = None,
    bound_evidence: Optional[IssueBoundEvidenceSet] = None,
    mlre=None,
    is_conditional_context: bool = False,
) -> DraftingResult:
    """Deterministic memo composition. NO LLM.

    The Drafting Liberation Protocol (DLP) selects the mode
    (FULL / CONDITIONAL / DUAL / SKELETON / NOT_DRAFTABLE); MQE composes
    draftable memos; PASL polishes. A legacy fallback remains only if
    MQE import fails (defensive).
    """
    # Compute the legacy gaps for trace, but they no longer HARD-BLOCK:
    safety_legacy, missing = _assess_draftability(
        graph=graph,
        bound=bound_evidence,
        facts_count=len(request.facts or []),
        doc_type=request.document_type,
    )

    result = DraftingResult(
        safety_mode=safety_legacy,
        document_type=request.document_type.value,
        missing_inputs=missing,
    )

    # ── DLP mode selection (replaces the binary gate) ──
    dlp_mode_value = ""
    _pending_upgrade_block = ""
    safety = safety_legacy
    try:
        from core.drafting.dlp import (
            compose_draft as _dlp_compose,
            DraftingMode as _DLP_Mode,
        )
        dlp = _dlp_compose(
            request=request,
            graph=graph, bound=bound_evidence, mlre=mlre,
            raw_gaps=list(missing or []),
            append_upgrade_questions=True,
        )
        dlp_mode_value = dlp.mode.value
        result.notes.append(
            f"dlp:mode={dlp_mode_value} "
            f"rule={dlp.decision.rule_fired if dlp.decision else ''}"
        )
        # SKELETON and NOT_DRAFTABLE are handled by DLP itself (not MQE).
        if dlp.mode in (_DLP_Mode.SKELETON_DRAFT,
                          _DLP_Mode.NOT_DRAFTABLE_YET):
            result.text = dlp.text
            result.safety_mode = dlp.safety_mode
            result.cited_laws = list(dlp.cited_laws)
            result.assumptions = list(dlp.assumptions)
            # Skeleton is NEVER a refusal; expose it as a proper memo.
            result.notes.append(
                f"dlp_questions:{len(dlp.upgrade_questions)}"
            )
            return result
        # For FULL / CONDITIONAL / DUAL we hand control to MQE below.
        # DLP already stored upgrade questions — remember them for attach.
        if dlp.upgrade_questions:
            from core.drafting.dlp import render_upgrade_questions
            _pending_upgrade_block = render_upgrade_questions(
                dlp.upgrade_questions, mode=dlp_mode_value,
            )
        # Override safety downward of the legacy gate's verdict only when
        # DLP is more permissive: if legacy said NOT_DRAFTABLE but DLP
        # says FULL/CONDITIONAL/DUAL, promote to DRAFTABLE_WITH_ASSUMPTIONS.
        if safety == DraftingSafetyMode.NOT_DRAFTABLE_YET:
            safety = DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS
            result.notes.append("dlp_promoted:not_draftable->with_assumptions")
    except Exception as _dlp_err:
        import logging
        logging.getLogger("drafting_engine").warning(
            "DLP path failed (falling through to MQE): %s", _dlp_err
        )

    # ── Memorandum Quality Engine (composer for FULL/CONDITIONAL/DUAL) ──
    try:
        from core.drafting.mqe import compose_memo as _mqe_compose
        mqe_result = _mqe_compose(
            request=request,
            graph=graph,
            bound=bound_evidence,
            safety_mode=safety,
            missing=missing,
            mlre=mlre,
            is_conditional_context=is_conditional_context,
        )
        result.text = mqe_result.text
        result.cited_laws = list(mqe_result.cited_laws)
        result.assumptions = list(mqe_result.assumptions)
        # MQE may have downgraded safety on low quality
        result.safety_mode = mqe_result.safety_mode
        result.notes.append(
            f"mqe:arg={len(mqe_result.arguments)} "
            f"cite={len(mqe_result.cited_laws)} "
            f"score={mqe_result.score.overall if mqe_result.score else 0}"
        )
        if mqe_result.firewall:
            result.notes.append(
                f"mqe_firewall:removed={mqe_result.firewall.removed_paragraphs}"
            )
        # If MQE downgraded to NOT_DRAFTABLE on quality, fall back to
        # DLP skeleton instead of a bare refusal — the user still gets a
        # useful document.
        if result.safety_mode == DraftingSafetyMode.NOT_DRAFTABLE_YET:
            try:
                from core.drafting.dlp import (
                    build_skeleton as _dlp_skeleton,
                )
                sk = _dlp_skeleton(
                    doc_type=request.document_type,
                    client_side=request.client_side,
                    facts=list(request.facts or []),
                    graph=graph, bound=bound_evidence, mlre=mlre,
                    raw_gaps=list(missing or [])
                            + [f"mqe_quality_downgrade"],
                )
                result.text = sk.text
                result.safety_mode = DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS
                result.cited_laws = list(sk.cited_laws)
                result.assumptions = list(sk.missing)
                result.notes.append("dlp_rescue:mqe_downgrade->skeleton")
                return result
            except Exception as _rescue_err:
                import logging
                logging.getLogger("drafting_engine").debug(
                    "DLP rescue failed: %s", _rescue_err
                )
        # ── Professional Advocate Style Layer (PASL) — applied AFTER MQE ──
        # Only polish when MQE produced a draftable memo (not NOT_DRAFTABLE).
        if result.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET and result.text:
            try:
                from core.drafting.pasl import polish as _pasl_polish
                client_val = (request.client_side.value
                              if hasattr(request.client_side, "value")
                              else str(request.client_side))
                pasl = _pasl_polish(
                    result.text,
                    is_conditional_context=is_conditional_context,
                    client_side=client_val,
                )
                # Only adopt the polished text if it was not rolled back
                if not pasl.rolled_back and pasl.text:
                    result.text = pasl.text
                sb = pasl.style_before.overall if pasl.style_before else 0
                sa = pasl.style_after.overall if pasl.style_after else 0
                result.notes.append(
                    f"pasl:passes={len(pasl.applied_passes)} "
                    f"style={sb:.2f}->{sa:.2f} "
                    f"rollback={pasl.rolled_back}"
                )
            except Exception as _pasl_err:
                import logging
                logging.getLogger("drafting_engine").debug(
                    "PASL polish failed (non-critical): %s", _pasl_err
                )
        # Attach DLP upgrade questions as a final block (after polish).
        try:
            if (_pending_upgrade_block
                    and result.safety_mode != DraftingSafetyMode.NOT_DRAFTABLE_YET
                    and _pending_upgrade_block not in result.text):
                result.text = (
                    result.text.rstrip() + "\n\n" + _pending_upgrade_block + "\n"
                )
                result.notes.append("dlp_questions_attached")
        except Exception:
            pass
        result.notes.append(f"issue_count:{len(graph.nodes) if graph else 0}")
        result.notes.append(
            f"bound_evidence:{len(bound_evidence.links) if bound_evidence else 0}"
        )
        return result
    except Exception as _mqe_err:
        import logging
        logging.getLogger("drafting_engine").warning(
            "MQE path failed — emitting DLP skeleton (NO legacy fallback): %s",
            _mqe_err,
        )
        # ── REUP: NO legacy fallback. MQE failure → DLP skeleton. ──
        try:
            from core.drafting.dlp import build_skeleton as _dlp_skel
            sk = _dlp_skel(
                doc_type=request.document_type,
                client_side=request.client_side,
                facts=list(request.facts or []),
                graph=graph, bound=bound_evidence, mlre=mlre,
                raw_gaps=list(missing or []) + ["mqe_runtime_exception"],
            )
            result.text = sk.text
            result.cited_laws = list(sk.cited_laws)
            result.assumptions = list(sk.missing)
            result.safety_mode = DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS
            result.notes.append("reup_skeleton_rescue:mqe_exception")
            return result
        except Exception as _skel_err:
            # Even the skeleton path failed — surface a structured
            # NOT_DRAFTABLE with DLP's humanized message, never the
            # legacy "تعذّر" shell.
            from core.drafting.dlp import build_final_not_draftable_message
            result.text = build_final_not_draftable_message(
                request.document_type,
                raw_gaps=list(missing or [])
                        + ["mqe_runtime_exception", "skeleton_runtime_exception"],
                mlre=mlre,
            )
            result.safety_mode = DraftingSafetyMode.NOT_DRAFTABLE_YET
            result.notes.append("reup_hard_stop:skeleton_exception")
            return result


@_sealed_legacy(
    reason="Legacy NOT_DRAFTABLE composer — replaced by DLP "
           "build_not_draftable_message + build_final_not_draftable_message."
)
def _build_not_draftable_message(doc_type: DocumentType,
                                   missing: list[str]) -> str:
    label = _DOC_TYPE_LABEL.get(doc_type, "مذكرة قانونية")
    parts = [
        f"**تعذّر صياغة {label} في الوقت الحالي**",
        "",
        "الصياغة القانونية المسؤولة تتطلب عناصر محددة قبل البدء.",
        "العناصر الناقصة:",
    ]
    for m in missing:
        parts.append(f"• {_humanize_missing(m)}")
    parts.append("")
    parts.append("يُرجى تقديم هذه العناصر — أو إعادة صياغة سؤالك لنحلل "
                  "القضية أولاً قبل الصياغة.")
    return "\n".join(parts)


def _humanize_missing(code: str) -> str:
    return {
        "issue_graph_unavailable":  "لم يُحدَّد المجال القانوني والمسائل بدقة.",
        "no_primary_issue":         "لم تتضح المسألة الجوهرية في القضية.",
        "no_bound_evidence":        "لا يوجد سند قانوني موثَّق مربوط بالمسائل.",
        "insufficient_facts":       "الوقائع غير كافية لصياغة مذكرة مسؤولة.",
        "claim_brief_needs_detailed_facts":
            "صحيفة الدعوى تتطلب وقائع تفصيلية (أطراف + تاريخ + محل النزاع).",
    }.get(code, code)
