# -*- coding: utf-8 -*-
"""
Memorandum Quality Engine — Opponent Model Paragraph.

In adversarial contexts, the memo must briefly engage with the
opponent's strongest point — then rebut it. This is NOT a full
alternate argument; it's a short controlled paragraph that shows
the writer anticipated the counter.

Rules:
  • At most 3 lines
  • MUST end with a rebuttal (not a concession)
  • NEVER invents opposition positions not present in MLRE
  • If no MLRE signal and no DEFENSE-kind issues, returns empty string
"""
from __future__ import annotations

from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph, IssueKind
from core.drafting.drafting_engine import ClientSide


_REBUTTAL_OPENERS = [
    "ويُردّ على ذلك بأن",
    "ومردود هذا الدفع بأن",
    "غير أن هذا القول مردود بأن",
    "إلا أن ذلك لا ينهض قانوناً إذ",
]


def _pick_rebuttal(idx: int) -> str:
    return _REBUTTAL_OPENERS[idx % len(_REBUTTAL_OPENERS)]


def _opponent_strongest_from_mlre(mlre) -> str:
    """Extract strongest opponent argument from MLRE reality + adversarial."""
    if mlre is None:
        return ""
    reality = getattr(mlre, "reality", None)
    if reality is None:
        return ""
    # First try: second-path weakest_point (that's OUR weak, THEIR strong)
    paths = getattr(reality, "paths", []) or []
    if len(paths) >= 1:
        # Our weakest point IS the opponent's strongest hook
        wk = getattr(paths[0], "weakest_point", "") or ""
        if wk:
            return wk.strip()
    # Fallback: adversarial worst_opposition
    survivors = getattr(mlre, "survivors", []) or []
    for triple in survivors:
        if len(triple) >= 3:
            atk = triple[2]
            worst = getattr(atk, "worst_opposition", "") or ""
            if worst:
                return worst.strip()
    return ""


def _rebuttal_line(opposing: str, client_side: ClientSide,
                     graph: Optional[IssueGraph], idx: int) -> str:
    """Construct a rebuttal that fits the client's side."""
    opener = _pick_rebuttal(idx)
    # Try to pick a defense node text as the rebuttal anchor
    if graph is not None:
        defenses = graph.by_kind(IssueKind.DEFENSE)
        for d in defenses[:1]:
            q = (d.question or "").rstrip("؟?")
            if q:
                return f"{opener} {q} — وهو ما ينفي الأثر المستنَد إليه."
    # Generic but focused rebuttal
    if client_side in {ClientSide.DEFENDANT, ClientSide.ACCUSED,
                         ClientSide.RESPONDENT}:
        return (f"{opener} عبء الإثبات يقع على خصم الموكّل، وما استند إليه "
                f"لا يرقى إلى الدليل الكافي.")
    return (f"{opener} هذا الدفع لا يستند إلى سند نظامي واضح ويتعارض مع "
            f"الثابت من الأوراق.")


def build_opponent_paragraph(
    mlre=None,
    graph: Optional[IssueGraph] = None,
    client_side: ClientSide = ClientSide.NEUTRAL,
) -> str:
    """Produce a short opponent-model paragraph, or empty string if
    there is no meaningful adversarial signal."""
    strongest = _opponent_strongest_from_mlre(mlre) if mlre else ""

    # If no MLRE signal AND no defense-kind issues in the graph, skip entirely
    if not strongest and graph is not None:
        defenses = graph.by_kind(IssueKind.DEFENSE)
        if not defenses:
            return ""
        # Use a defense-kind question (inverted) as a standin opposing point
        d = defenses[0]
        q = (d.question or "").rstrip("؟?")
        if q:
            strongest = f"قيام العكس من: {q}"

    if not strongest:
        return ""

    lines: list[str] = []
    lines.append(
        f"قد يتمسّك الخصم بأن {strongest}."
    )
    lines.append(_rebuttal_line(strongest, client_side, graph, idx=0))
    return "\n".join(lines)
