# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Legal Argument Spine.

Every argument paragraph in a memo MUST follow the spine:
    claim → legal_basis → evidence_basis → application → consequence

Arguments without all five links are rejected by the quality firewall.
This module constructs valid arguments FROM an IssueGraph + bound evidence,
and renders them in natural Arabic legal prose (not mechanical templates).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph, IssueNode, IssueKind
from core.domain_pipeline.evidence_linker import (
    IssueBoundEvidenceSet, EvidenceLink,
)


# ═════════════════════════════════════════════════════════════════
# Argument contract
# ═════════════════════════════════════════════════════════════════

@dataclass
class LegalArgument:
    """A complete legal argument with all 5 spine elements.

    A memo paragraph built from this argument is *defensibly* linked to:
      - an issue in the graph (issue_id)
      - concrete evidence (evidence_refs)
      - a canonical statute/principle (statute_refs)
    """
    issue_id:         str = ""
    claim:            str = ""
    legal_basis:      list[str] = field(default_factory=list)
    evidence_basis:   list[str] = field(default_factory=list)
    application:      str = ""
    consequence:      str = ""
    statute_refs:     list[str] = field(default_factory=list)
    evidence_refs:    list[str] = field(default_factory=list)
    strength:         float = 0.0          # 0..1
    required_proof:   list[str] = field(default_factory=list)
    is_conditional:   bool = False

    # ── Validation ──
    def is_complete(self) -> bool:
        """Fail-closed: all 5 spine links must be present."""
        return bool(
            self.claim and self.claim.strip()
            and self.legal_basis
            and self.evidence_basis
            and self.application and self.application.strip()
            and self.consequence and self.consequence.strip()
        )

    def is_bound(self) -> bool:
        """The argument is linked to an issue + an evidence + a statute."""
        return bool(
            self.issue_id
            and self.evidence_refs
            and self.statute_refs
        )

    def to_dict(self) -> dict:
        return {
            "issue_id":       self.issue_id,
            "claim":          self.claim,
            "legal_basis":    self.legal_basis[:3],
            "evidence_basis": self.evidence_basis[:3],
            "application":    self.application,
            "consequence":    self.consequence,
            "statute_refs":   self.statute_refs[:3],
            "evidence_refs":  self.evidence_refs[:5],
            "strength":       round(self.strength, 3),
            "is_complete":    self.is_complete(),
            "is_bound":       self.is_bound(),
        }


# ═════════════════════════════════════════════════════════════════
# Natural-language openers (no mechanical "بشأن:" repetition)
# ═════════════════════════════════════════════════════════════════

_CLAIM_OPENERS = [
    "من المستقر أن",
    "من الثابت قانوناً أن",
    "إن القاعدة القانونية تقضي بأن",
    "المقرر في هذا الشأن أن",
    "يستقر الفقه والقضاء على أن",
]

_APPLICATION_OPENERS = [
    "وبتطبيق ما تقدم على وقائع النزاع،",
    "وبإنزال هذه القاعدة على الوقائع الثابتة،",
    "وبإعمال هذا المبدأ على واقعة الحال،",
    "ولمّا كان الثابت من الأوراق أن",
    "ولمّا كان الحال كذلك،",
]

_CONSEQUENCE_OPENERS = [
    "ومؤدى ذلك",
    "ويترتب على ذلك",
    "مما يتعيّن معه",
    "فإنه يلزم من ذلك",
]


def _opener(idx: int, bank: list[str]) -> str:
    """Pick an opener deterministically (rotated) to avoid repetition."""
    if not bank:
        return ""
    return bank[idx % len(bank)]


# ═════════════════════════════════════════════════════════════════
# Argument builder — consumes IssueGraph + bound evidence
# ═════════════════════════════════════════════════════════════════

def _claim_for_issue(issue: IssueNode, client_side: str,
                       subdomain: str) -> str:
    """Generate a claim (not a question) for this issue.

    The question form ('هل تحقق X؟') becomes an assertion the memo
    proves ('تحققت X لـ...' or 'لم تتحقق X').
    """
    q = (issue.question or "").strip()
    core_q = q.rstrip("؟?").strip()
    # Defense side: typically DENIES the claim
    deny = client_side.lower() in {"defendant", "accused", "respondent"}

    # ── Disjunctive questions ("X أم Y؟") → natural assertion ──
    if " أم " in core_q:
        # Split into alternatives
        first, _, second = core_q.partition(" أم ")
        first = first.strip()
        second = second.strip()
        if first.startswith("هل "):
            first = first[3:].strip()
        # Convention: the FIRST alternative is usually the defense-favorable
        # interpretation (e.g. "ضمان" in "ضمان أم أداة وفاء"), because drafters
        # typically phrase the innocent framing first.
        if deny:
            return f"الراجح أن {first} لا {second}"
        return f"الراجح أن {second} لا {first}"

    # ── Standard هل/ما question patterns ──
    if core_q.startswith("هل "):
        body = core_q[3:].strip()
        if deny:
            # Use "لم يتحقق" if body starts with a verb-like, else "انتفاء"
            if body.startswith(("تحقق", "توافر", "ثبت", "قام", "استقر")):
                return f"لم يتحقق {body[len(body.split()[0]):].strip()}" \
                    if len(body.split()) > 1 else f"لم يتحقق هذا الركن"
            return f"انتفاء {body}"
        return f"ثبوت {body}"

    if core_q.startswith("ما "):
        body = core_q[3:].strip()
        return f"يتبيَّن {body}"

    if core_q.startswith("كيف "):
        body = core_q[4:].strip()
        return f"يظهر من الوقائع كيف {body}"

    if core_q.startswith("متى "):
        body = core_q[4:].strip()
        return f"يتحدّد متى {body}"

    # ── Fallback: prefix with ثبوت / انتفاء ──
    if deny:
        return f"انتفاء {core_q}"
    return f"ثبوت {core_q}"


def _application_sentence(issue: IssueNode,
                            evidence_links: list[EvidenceLink],
                            facts: list[str],
                            opener: str) -> str:
    """Build the application paragraph — NOT a bullet dump."""
    fact_snip = ""
    if facts:
        # Pick the fact most aligned with the issue's required_proof keywords
        best = facts[0]
        for f in facts:
            low = f.lower()
            if any(kw and kw in low for kw in issue.required_proof):
                best = f
                break
        fact_snip = best[:200].rstrip(".")

    cites = []
    for L in evidence_links[:2]:
        c = L.record.public_citation()
        if c and c not in cites:
            cites.append(c)
    cite_phrase = ""
    if cites:
        cite_phrase = "، وهو ما يؤيده " + " و".join(cites)

    if fact_snip:
        return (f"{opener} {fact_snip}{cite_phrase}.")
    if cite_phrase:
        return f"{opener} ذلك ثابت بمقتضى {' و'.join(cites)}."
    return f"{opener} ما سبق يرشّح تحقق هذه المسألة."


def _consequence_sentence(issue: IssueNode, client_side: str,
                             opener: str, is_primary: bool) -> str:
    """Short consequence line — concrete, not waffle."""
    deny = client_side.lower() in {"defendant", "accused", "respondent"}
    if issue.kind == IssueKind.PROOF:
        return f"{opener} عدم اكتمال عناصر الإثبات المطلوبة." if deny else \
               f"{opener} توافر الدليل الكافي على تحقق هذه المسألة."
    if issue.kind == IssueKind.PROCEDURAL:
        return f"{opener} تحقق شرط الاختصاص/القبول المطلوب."
    if issue.kind == IssueKind.THRESHOLD:
        return f"{opener} انتفاء الشرط التمهيدي لقيام الدعوى." if deny else \
               f"{opener} تحقق الشرط التمهيدي."
    if issue.kind == IssueKind.DEFENSE:
        return f"{opener} قيام هذا الدفع ووجوب إعماله."
    # PRIMARY / SECONDARY / REMEDY
    if is_primary:
        return f"{opener} انتفاء أركان ادعاء الخصم في هذه النقطة." if deny \
            else f"{opener} ثبوت ادعاء الموكّل في هذه النقطة."
    return f"{opener} ترجيح الرأي المتقدم على ما يخالفه."


def _strength_from_links(links: list[EvidenceLink]) -> float:
    if not links:
        return 0.0
    direct = sum(1 for L in links if L.evidence_role == "direct")
    corro = sum(1 for L in links if L.evidence_role == "corroborative")
    base = 0.30 + 0.25 * direct + 0.12 * corro
    return round(min(1.0, base), 3)


def build_arguments(
    graph: IssueGraph,
    bound: IssueBoundEvidenceSet,
    facts: list[str],
    client_side: str = "neutral",
    max_arguments: int = 6,
) -> list[LegalArgument]:
    """Construct complete LegalArgument objects — one per issue with evidence.

    Issues that cannot be bound to ANY evidence are NOT silently padded —
    they are skipped entirely. The firewall enforces this downstream too.
    """
    if graph is None or bound is None:
        return []

    args: list[LegalArgument] = []

    # Order: primary → threshold → secondary → proof → defense → procedural → remedy
    kind_order = [
        IssueKind.PRIMARY, IssueKind.THRESHOLD, IssueKind.SECONDARY,
        IssueKind.PROOF, IssueKind.DEFENSE, IssueKind.PROCEDURAL,
        IssueKind.REMEDY,
    ]
    ordered_ids: list[str] = []
    seen: set[str] = set()
    if graph.primary_issue and graph.primary_issue in graph.nodes:
        ordered_ids.append(graph.primary_issue)
        seen.add(graph.primary_issue)
    for kind in kind_order:
        for node in graph.by_kind(kind):
            if node.issue_id not in seen:
                ordered_ids.append(node.issue_id)
                seen.add(node.issue_id)
    for iid in graph.nodes:
        if iid not in seen:
            ordered_ids.append(iid)

    for idx, iid in enumerate(ordered_ids):
        if len(args) >= max_arguments:
            break
        node = graph.nodes.get(iid)
        if node is None:
            continue
        links = bound.links_for(iid)
        # HARD RULE: no evidence → no argument
        if not links:
            continue
        # Pick the strongest links
        links = sorted(links, key=lambda L: -L.directness)

        statute_refs = []
        for L in links:
            cite = L.record.public_citation()
            if cite and cite not in statute_refs:
                statute_refs.append(cite)

        evidence_refs = [L.record.public_citation() for L in links[:3]]

        claim_text = _claim_for_issue(node, client_side, node.subdomain or "")
        legal_basis = statute_refs[:2]
        evidence_basis_texts = []
        for L in links[:2]:
            snippet = L.record.public_snippet(180)
            if snippet:
                evidence_basis_texts.append(snippet)
        if not evidence_basis_texts:
            evidence_basis_texts = statute_refs[:1]

        app = _application_sentence(
            node, links, facts,
            opener=_opener(idx, _APPLICATION_OPENERS),
        )
        cons = _consequence_sentence(
            node, client_side,
            opener=_opener(idx, _CONSEQUENCE_OPENERS),
            is_primary=(iid == graph.primary_issue),
        )

        arg = LegalArgument(
            issue_id=iid,
            claim=claim_text,
            legal_basis=legal_basis,
            evidence_basis=evidence_basis_texts,
            application=app,
            consequence=cons,
            statute_refs=statute_refs[:3],
            evidence_refs=evidence_refs,
            strength=_strength_from_links(links),
            required_proof=list(node.required_proof)[:3],
        )
        # HARD RULE: only complete+bound arguments ship
        if arg.is_complete() and arg.is_bound():
            args.append(arg)

    return args


# ═════════════════════════════════════════════════════════════════
# Renderer — turns a LegalArgument into natural Arabic prose
# ═════════════════════════════════════════════════════════════════

def render_argument(arg: LegalArgument, heading: str = "",
                      idx: int = 0) -> str:
    """Render one argument as a short, dense paragraph.

    Format:
        <heading>
        <claim + legal_basis>
        <application>
        <consequence>
    """
    if not arg.is_complete():
        return ""
    lines: list[str] = []
    if heading:
        lines.append(f"**{heading}**")

    opener = _opener(idx, _CLAIM_OPENERS)
    basis_phrase = ""
    if arg.legal_basis:
        basis_phrase = " بمقتضى " + " و".join(arg.legal_basis[:2])
    lines.append(f"{opener} {arg.claim}{basis_phrase}.")
    lines.append(arg.application)
    lines.append(arg.consequence)
    return "\n".join(lines)


def render_arguments_block(arguments: list[LegalArgument],
                             title: str = "التطبيق على الوقائع") -> str:
    """Render a list of arguments as a single coherent block."""
    if not arguments:
        return ""
    out: list[str] = [f"**رابعاً — {title}:**"]
    for i, arg in enumerate(arguments, 1):
        heading = f"({i}) بشأن: {_issue_heading(arg)}"
        rendered = render_argument(arg, heading=heading, idx=i)
        if rendered:
            out.append(rendered)
            out.append("")
    # Trim trailing empty line
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _issue_heading(arg: LegalArgument) -> str:
    """Short label for this argument's issue — derived from claim."""
    claim = (arg.claim or "").strip()
    # Keep the first 90 chars, without trailing punctuation
    if len(claim) > 90:
        return claim[:90].rstrip(".") + "…"
    return claim.rstrip(".")
