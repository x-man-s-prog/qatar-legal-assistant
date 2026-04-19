# -*- coding: utf-8 -*-
"""
DLP — Draft-Upgrade UX Questions.

When the chosen mode is SKELETON_DRAFT or CONDITIONAL_DRAFT, the caller
can append 1-3 pivot-specific questions whose answers would move the
case TO a higher mode (Skeleton → Conditional/Full, Conditional → Full).

Sources used, in order:
  1. MLRE decisive_tests (reuse core.mlre.pivot_questions)
  2. IssueGraph required_proof on the primary issue
  3. Default generic question ("ما أبرز ما تملكه من وثائق بشأن هذه المسألة؟")

Never more than 3 questions. All phrased as concrete yes/no or
"هل يوجد ما يثبت: X؟" so the user can answer tangibly.
"""
from __future__ import annotations

from typing import Optional

from core.domain_pipeline.issue_graph import IssueGraph


def _from_mlre(mlre, max_q: int) -> list[str]:
    if mlre is None or max_q <= 0:
        return []
    try:
        from core.mlre.pivot_questions import questions_from_mlre
        qs = questions_from_mlre(mlre, max_questions=max_q)
        return [q.text for q in qs if getattr(q, "text", "")]
    except Exception:
        return []


def _from_graph(graph: Optional[IssueGraph], max_q: int) -> list[str]:
    if graph is None or not graph.nodes or max_q <= 0:
        return []
    out: list[str] = []
    # Primary issue's required_proof first
    primary = (graph.nodes.get(graph.primary_issue)
                if graph.primary_issue else None)
    if primary and primary.required_proof:
        for pr in primary.required_proof[:max_q]:
            out.append(f"هل يوجد ما يثبت: {pr}؟")
    # Threshold issues next
    if len(out) < max_q:
        for t in list(graph.nodes.values())[:3]:
            if t.required_proof and len(out) < max_q:
                for pr in t.required_proof[:1]:
                    q = f"هل يوجد ما يثبت: {pr}؟"
                    if q not in out:
                        out.append(q)
    return out[:max_q]


def build_draft_upgrade_questions(
    mlre=None,
    graph: Optional[IssueGraph] = None,
    *,
    max_questions: int = 3,
) -> list[str]:
    """Return 0-3 concrete, pivot-aligned questions."""
    out = _from_mlre(mlre, max_questions)
    if len(out) < max_questions:
        remaining = max_questions - len(out)
        for q in _from_graph(graph, remaining):
            if q not in out:
                out.append(q)
    # Final fallback — only if we still have nothing
    if not out:
        out.append("ما أبرز ما تملكه من وثائق أو مراسلات بشأن هذه المسألة؟")
    return out[:max_questions]


def render_upgrade_questions(questions: list[str], mode: str = "") -> str:
    """Render the questions as an appended UX block."""
    if not questions:
        return ""
    header = {
        "skeleton_draft":
            "**أسئلة لاستكمال الصياغة نحو المذكرة النهائية:**",
        "conditional_draft":
            "**أسئلة للانتقال من التكييف المشروط إلى المذكرة الكاملة:**",
        "dual_strategy_draft":
            "**أسئلة لترجيح أحد المسارين على الآخر:**",
    }.get(mode, "**أسئلة قد تساعد في استكمال المذكرة:**")

    lines = [header]
    for i, q in enumerate(questions[:3], 1):
        lines.append(f"{i}. {q}")
    return "\n".join(lines)
