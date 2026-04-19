# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Orchestrator.

Composes the final memo from:
  • structure.py        → section plan per document type
  • argument.py         → claim→basis→evidence→application→consequence
  • prayer.py           → precise requests
  • opponent.py         → opponent model paragraph
  • conditional_frame.py → conditional / dual wrapping
  • firewall.py         → post-composition quality firewall
  • style.py            → Arabic legal style refiner
  • scorer.py           → 7-axis quality score
  • not_draftable.py    → structured NOT_DRAFTABLE message

Public entry points:
  compose_memo(request, graph, bound, safety_mode, missing, mlre=None,
               client_side=..., explicit_requests=...)
    → MQEComposeResult

  compose_memo_conditional(primary_memo, fallback_theory, pivot_conditions)
    → str

  compose_memo_dual(primary_memo, secondary_memo) → str
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.drafting.drafting_engine import (
    DraftingRequest, DraftingSafetyMode, DocumentType, ClientSide,
)
from core.domain_pipeline.issue_graph import IssueGraph, IssueKind, IssueNode
from core.domain_pipeline.evidence_linker import IssueBoundEvidenceSet

from core.drafting.mqe.argument import (
    LegalArgument, build_arguments, render_arguments_block,
)
from core.drafting.mqe.structure import (
    MemoSection, section_order, section_title,
    format_section_header, parties_line,
)
from core.drafting.mqe.prayer import (
    Prayer, build_prayer, render_prayer,
)
from core.drafting.mqe.opponent import build_opponent_paragraph
from core.drafting.mqe.conditional_frame import (
    wrap_conditional, wrap_dual,
)
from core.drafting.mqe.firewall import audit_memo, FirewallReport
from core.drafting.mqe.style import refine
from core.drafting.mqe.scorer import (
    MemoQualityScore, score_memo, QUALITY_FLOOR, STRONG_QUALITY_FLOOR,
)
from core.drafting.mqe.not_draftable import build_not_draftable_message


_ASSUMPTION_PHRASES = {
    "no_bound_evidence":
        "النص القانوني المشار إليه سيُضاف عند توفره.",
    "low_issue_coverage":
        "اعتماد السند المتوفر مع إمكان تعزيزه بنصوص إضافية عند ورودها.",
    "issue_graph_unavailable":
        "اعتماد التكييف الأقوى المبني على طبيعة الواقعة كما وصفها الموكّل.",
    "no_primary_issue":
        "تحديد المسألة المحورية وفق الوقائع المتاحة.",
    "insufficient_facts":
        "إضافة تفاصيل الأطراف والتواريخ عند ورودها في ملف القضية.",
    "claim_brief_needs_detailed_facts":
        "تكميل بيانات الصحيفة (المبلغ/التاريخ/الأطراف) قبل الإيداع.",
    "memo_quality_score":
        "اعتماد الصياغة الحالية مع توصية بمراجعتها قبل الإيداع.",
    "mlre_no_surviving_hypothesis":
        "اعتماد التكييف الأرجح بعد تعذّر حسم المسار عبر التحليل المتعدد.",
}


def _humanize_assumption(code: str) -> str:
    """Turn a raw missing-code into a user-safe Arabic assumption phrase."""
    if not code:
        return ""
    key = code.split(":", 1)[0] if ":" in code else code
    return _ASSUMPTION_PHRASES.get(key, f"اعتماد المعطيات الحالية بشأن: {code}")


_DOC_TITLE = {
    DocumentType.DEFENSE_MEMO:      "مذكرة دفاع",
    DocumentType.REPLY_MEMO:        "مذكرة رد",
    DocumentType.EXPLANATORY_MEMO:  "مذكرة شارحة",
    DocumentType.PETITION_MEMO:     "مذكرة بطلب",
    DocumentType.CLAIM_BRIEF:       "صحيفة دعوى",
    DocumentType.PLEADING_POINTS:   "نقاط مرافعة",
    DocumentType.DEFENSE_CHECKLIST: "قائمة الدفوع",
    DocumentType.CASE_SUMMARY:      "تلخيص ملف القضية",
}


# ═════════════════════════════════════════════════════════════════
# Result type
# ═════════════════════════════════════════════════════════════════

@dataclass
class MQEComposeResult:
    text:              str = ""
    safety_mode:       DraftingSafetyMode = DraftingSafetyMode.NOT_DRAFTABLE_YET
    document_type:     str = ""
    cited_laws:        list[str] = field(default_factory=list)
    assumptions:       list[str] = field(default_factory=list)
    arguments:         list[LegalArgument] = field(default_factory=list)
    prayer:            Optional[Prayer] = None
    firewall:          Optional[FirewallReport] = None
    score:             Optional[MemoQualityScore] = None
    notes:             list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text_length":     len(self.text),
            "safety_mode":     self.safety_mode.value,
            "document_type":   self.document_type,
            "cited_laws":      self.cited_laws[:5],
            "assumptions":     self.assumptions[:5],
            "arg_count":       len(self.arguments),
            "firewall":        self.firewall.to_dict() if self.firewall else {},
            "score":           self.score.to_dict() if self.score else {},
            "notes":           self.notes[:5],
        }


# ═════════════════════════════════════════════════════════════════
# Body-part builders (one per section key)
# ═════════════════════════════════════════════════════════════════

def _build_facts_summary(request: DraftingRequest) -> str:
    facts = [f for f in (request.facts or []) if f and f.strip()]
    if not facts:
        return ""
    lines: list[str] = []
    for i, f in enumerate(facts[:6], 1):
        short = f.strip()
        # Keep each fact under ~240 chars for readability
        if len(short) > 240:
            short = short[:240].rstrip() + "…"
        lines.append(f"({i}) {short}")
    return "\n".join(lines)


def _build_issues_block(graph: Optional[IssueGraph]) -> str:
    if graph is None or not graph.nodes:
        return ""
    primary = (graph.nodes.get(graph.primary_issue)
                if graph.primary_issue else None)
    threshold = graph.by_kind(IssueKind.THRESHOLD)
    secondary = graph.by_kind(IssueKind.SECONDARY)
    proof = graph.by_kind(IssueKind.PROOF)
    lines: list[str] = []
    if primary:
        lines.append(f"(1) (جوهرية) {primary.question}")
    idx = 2
    for t in threshold[:2]:
        lines.append(f"({idx}) (تمهيدية) {t.question}")
        idx += 1
    for s in secondary[:2]:
        lines.append(f"({idx}) (فرعية) {s.question}")
        idx += 1
    for p in proof[:1]:
        lines.append(f"({idx}) (إثبات) {p.question}")
        idx += 1
    return "\n".join(lines)


def _build_statute_basis(arguments: list[LegalArgument],
                             bound: Optional[IssueBoundEvidenceSet]) -> tuple[str, list[str]]:
    """Statute basis is ONLY from the bound evidence used in arguments.
    Returns (text, cited_laws)."""
    cited: list[str] = []
    # First: whatever arguments referenced
    for arg in arguments:
        for s in arg.statute_refs:
            if s and s not in cited:
                cited.append(s)
    # If arguments didn't cover all direct links, pull from bound
    if bound is not None and len(cited) < 3:
        for L in bound.links:
            if L.evidence_role != "direct":
                continue
            c = L.record.public_citation()
            if c and c not in cited:
                cited.append(c)
            if len(cited) >= 5:
                break

    if not cited:
        # Do NOT fabricate — explicitly note the gap (will be caught by score)
        return ("", [])

    lines = [f"• {c}" for c in cited[:5]]
    return ("\n".join(lines), cited[:5])


def _build_proof_burden(request: DraftingRequest,
                           arguments: list[LegalArgument]) -> str:
    if not arguments:
        return ""
    client = request.client_side
    if client in {ClientSide.ACCUSED, ClientSide.DEFENDANT,
                    ClientSide.RESPONDENT}:
        return (
            "الأصل أن عبء إثبات ادعاء الخصم يقع على عاتقه وحده، "
            "وما دام الدليل القاطع على ذلك لم يقم، فإن المحكمة تحكم "
            "لصالح الموكّل إعمالاً لقرينة الأصل."
        )
    if client in {ClientSide.CLAIMANT, ClientSide.APPELLANT}:
        return (
            "أعباء الإثبات الموضوعية التي يستلزمها النص القانوني قد "
            "أوفى بها الموكّل، ويتبيَّن ذلك من السند والأوراق المرفقة."
        )
    return (
        "تطبيق قواعد الإثبات على الوقائع الثابتة يؤدي إلى المآل القانوني "
        "المبيَّن أعلاه."
    )


def _build_conclusion(request: DraftingRequest,
                         arguments: list[LegalArgument]) -> str:
    if not arguments:
        return ""
    client = request.client_side
    if client in {ClientSide.ACCUSED, ClientSide.DEFENDANT,
                    ClientSide.RESPONDENT}:
        return (
            "يتبيّن مما تقدَّم أن ادعاء الخصم لا ينهض على سند صحيح، "
            "لا من حيث النص ولا من حيث الإثبات، ومن ثم يلزم رفضه."
        )
    if client in {ClientSide.CLAIMANT, ClientSide.APPELLANT}:
        return (
            "يتّضح مما تقدَّم أن طلبات الموكّل قائمة على سند قانوني صريح، "
            "ومؤيّدة بواقع ثابت من الأوراق، ومتناسبة مع نوع النزاع."
        )
    return (
        "يُستخلص مما تقدَّم أن المسألة على النحو المبيَّن أعلاه، وهو "
        "المقتضى الذي يطلب الموكّل إعماله."
    )


def _build_reply_points(request: DraftingRequest,
                           arguments: list[LegalArgument]) -> str:
    """For REPLY_MEMO: each argument becomes a numbered rebuttal."""
    if not arguments:
        return ""
    lines: list[str] = []
    for i, arg in enumerate(arguments[:5], 1):
        # Claim becomes the rebuttal point
        lines.append(f"**({i}) في الرد على دفع الخصم بشأن:** "
                     f"{arg.claim.rstrip('.')}")
        lines.append(arg.application)
        lines.append(arg.consequence)
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _build_opposing_summary(mlre) -> str:
    if mlre is None:
        return ""
    reality = getattr(mlre, "reality", None)
    if reality is None or not getattr(reality, "paths", []):
        return ""
    # Provide a compact "what they argue" summary
    paths = reality.paths
    bits: list[str] = []
    if len(paths) >= 1:
        p = paths[0]
        wk = getattr(p, "weakest_point", "") or ""
        if wk:
            bits.append(f"• قد يتمسك الخصم بـ: {wk}")
    if len(paths) >= 2:
        alt = paths[1]
        theory = getattr(alt, "legal_theory", "") or ""
        if theory:
            bits.append(f"• أو يدفع بالتكييف البديل: {theory}")
    return "\n".join(bits)


def _build_checklist_sections(graph: Optional[IssueGraph]
                                     ) -> tuple[str, str, str]:
    """Return (procedural, substantive, evidence) bullet blocks."""
    if graph is None:
        return ("", "", "")
    procedural = graph.by_kind(IssueKind.PROCEDURAL)
    threshold = graph.by_kind(IssueKind.THRESHOLD)
    defenses = graph.by_kind(IssueKind.DEFENSE)
    proof = graph.by_kind(IssueKind.PROOF)

    proc_lines = [f"• {n.question.rstrip('؟?')}."
                    for n in (procedural + threshold)[:4]]
    sub_lines  = [f"• {n.question.rstrip('؟?')}." for n in defenses[:5]]
    ev_lines   = [f"• {n.question.rstrip('؟?')}." for n in proof[:3]]

    return ("\n".join(proc_lines),
            "\n".join(sub_lines),
            "\n".join(ev_lines))


# ═════════════════════════════════════════════════════════════════
# Main composer
# ═════════════════════════════════════════════════════════════════

def compose_memo(
    request: DraftingRequest,
    graph: Optional[IssueGraph],
    bound: Optional[IssueBoundEvidenceSet],
    safety_mode: DraftingSafetyMode,
    missing: list[str],
    mlre=None,
    is_conditional_context: bool = False,
) -> MQEComposeResult:
    """Compose a high-quality memo. Returns MQEComposeResult with score."""
    doc_type = request.document_type
    client = request.client_side

    result = MQEComposeResult(
        safety_mode=safety_mode,
        document_type=doc_type.value,
    )

    # ── NOT_DRAFTABLE path ──
    if safety_mode == DraftingSafetyMode.NOT_DRAFTABLE_YET \
            or graph is None or bound is None:
        result.text = build_not_draftable_message(doc_type, missing)
        result.assumptions = list(missing or [])
        result.notes.append("mqe:not_draftable")
        return result

    # ── Build arguments (the spine) ──
    arguments = build_arguments(
        graph=graph, bound=bound,
        facts=list(request.facts or []),
        client_side=client.value if hasattr(client, "value") else str(client),
        max_arguments=6,
    )
    result.arguments = arguments

    # ── Build prayer (precise requests) ──
    mlre_survivors = 0
    if mlre is not None:
        mlre_survivors = len(getattr(mlre, "survivors", []) or [])
    prayer = build_prayer(
        doc_type=doc_type,
        client_side=client,
        graph=graph,
        explicit_requests=list(request.explicit_requests or []),
        mlre_survivors=mlre_survivors,
    )
    result.prayer = prayer

    # ── Build section bodies ──
    order = section_order(doc_type)
    section_bodies: dict[str, str] = {}

    section_bodies["parties"] = parties_line(client)
    section_bodies["facts_summary"] = _build_facts_summary(request)
    section_bodies["issues"] = _build_issues_block(graph)

    statute_text, cited_laws = _build_statute_basis(arguments, bound)
    section_bodies["statute_basis"] = statute_text
    result.cited_laws = cited_laws

    section_bodies["application"] = render_arguments_block(
        arguments, title="التطبيق على الوقائع"
    )
    # Strip the built-in heading since the renderer formats its own
    if section_bodies["application"].startswith("**رابعاً"):
        section_bodies["application"] = "\n".join(
            section_bodies["application"].split("\n")[1:]
        ).lstrip()

    section_bodies["opponent_model"] = build_opponent_paragraph(
        mlre=mlre, graph=graph, client_side=client,
    )
    section_bodies["proof_burden"] = _build_proof_burden(request, arguments)
    section_bodies["conclusion"] = _build_conclusion(request, arguments)
    section_bodies["prayer"] = render_prayer(prayer)
    section_bodies["point_by_point_reply"] = _build_reply_points(
        request, arguments,
    )
    section_bodies["opposing_points_summary"] = _build_opposing_summary(mlre)

    (proc_block, sub_block, ev_block) = _build_checklist_sections(graph)
    section_bodies["procedural_defenses"] = proc_block
    section_bodies["substantive_defenses"] = sub_block
    section_bodies["evidence_defenses"] = ev_block

    # Assumptions section (humanized — no raw reason codes)
    if safety_mode == DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS and missing:
        assum_lines = []
        for m in (missing or [])[:5]:
            assum_lines.append(f"• {_humanize_assumption(m)}")
        section_bodies["assumptions"] = "\n".join(assum_lines)
        result.assumptions = list(missing or [])

    # ── Assemble in order, skipping empty sections ──
    lines: list[str] = []
    # Header
    title = _DOC_TITLE.get(doc_type, "مذكرة قانونية")
    lines.append(f"**{title}**")
    if safety_mode == DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS:
        lines.append("")
        lines.append(
            "> هذه الصياغة مبنية على افتراضات مذكورة في نهاية المذكرة. "
            "ينبغي مراجعتها مع محامٍ قبل الإيداع."
        )
    lines.append("")

    idx_nonheader = 0
    for key in order:
        if key == "header":
            continue
        body = (section_bodies.get(key) or "").strip()
        if not body:
            continue
        title_ar = section_title(key)
        if title_ar:
            lines.append(format_section_header(idx_nonheader, title_ar))
            lines.append("")
            idx_nonheader += 1
        lines.append(body)
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    composed = "\n".join(lines)

    # ── Firewall: strip low-quality paragraphs ──
    fw = audit_memo(composed)
    cleaned = fw.cleaned_text or composed
    result.firewall = fw

    # ── Style refinement ──
    refined = refine(cleaned, preserve_conditional=is_conditional_context)

    # ── Score ──
    score = score_memo(
        text=refined,
        doc_type=doc_type,
        arguments=arguments,
        prayer=prayer,
        cited_laws=cited_laws,
        issue_count=len(graph.nodes) if graph else 0,
        is_conditional_context=is_conditional_context,
    )
    result.score = score

    # ── Safety downgrade on weak quality ──
    if safety_mode == DraftingSafetyMode.DRAFTABLE \
            and score.overall < STRONG_QUALITY_FLOOR:
        safety_mode = DraftingSafetyMode.DRAFTABLE_WITH_ASSUMPTIONS
        result.notes.append(f"safety_downgraded:overall={score.overall}")
    if score.overall < QUALITY_FLOOR:
        safety_mode = DraftingSafetyMode.NOT_DRAFTABLE_YET
        result.notes.append(f"safety_blocked:overall={score.overall}")
        # Replace text with a NOT_DRAFTABLE explanation
        refined = build_not_draftable_message(
            doc_type,
            (missing or []) + [f"memo_quality_score:{score.overall}"],
        )

    result.text = refined
    result.safety_mode = safety_mode
    result.notes.append(f"mqe:ok arg={len(arguments)} cited={len(cited_laws)}")
    return result


# ═════════════════════════════════════════════════════════════════
# Conditional / dual helpers
# ═════════════════════════════════════════════════════════════════

def compose_memo_conditional(
    primary_text: str,
    fallback_theory: str,
    pivot_conditions: Optional[list[str]] = None,
    fallback_body: str = "",
) -> str:
    """Wrap a primary memo with a clean conditional fallback frame."""
    return wrap_conditional(
        primary_text=primary_text,
        fallback_theory=fallback_theory,
        pivot_conditions=list(pivot_conditions or []),
        fallback_body=fallback_body,
    )


def compose_memo_dual(
    primary_text: str,
    secondary_text: str,
    primary_label: str = "المسار الأقوى",
    secondary_label: str = "المسار البديل",
) -> str:
    """Wrap two parallel memos in a single dual-strategy document."""
    return wrap_dual(
        primary_text=primary_text,
        secondary_text=secondary_text,
        primary_label=primary_label,
        secondary_label=secondary_label,
    )
