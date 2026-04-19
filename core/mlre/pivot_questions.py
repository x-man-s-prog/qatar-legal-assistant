# -*- coding: utf-8 -*-
"""
Convert MLRE pivots + decisive_tests into UX questions.

Replaces generic "what are the facts?" with questions that FORCE a
distinction between surviving hypotheses.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from core.mlre.orchestrator import MLREResult
from core.ux.question_generator import LegalQuestion


def _qid(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def questions_from_mlre(mlre: MLREResult,
                          max_questions: int = 3) -> list[LegalQuestion]:
    """Extract pivot-based questions from MLRE decisive_tests.

    Each question is tied to a specific fact that FORCES a choice between
    the primary and secondary hypothesis.
    """
    out: list[LegalQuestion] = []
    if not mlre.reality or not mlre.reality.decisive_tests:
        return out

    reality = mlre.reality
    primary_path = reality.paths[0] if reality.paths else None
    primary_issue_id = "primary"
    if primary_path and primary_path.hypothesis_id:
        # Find the hypothesis's graph primary issue
        for (h, _, _) in mlre.survivors:
            if h.hypothesis_id == primary_path.hypothesis_id:
                if h.issue_graph and h.issue_graph.primary_issue:
                    primary_issue_id = h.issue_graph.primary_issue
                break

    # Turn each decisive test into a concrete pivot question
    for test in reality.decisive_tests[:max_questions]:
        # A decisive test looks like "إثبات: X" — turn it into a real question
        q_text = _pivot_to_question(test, primary_path)
        out.append(LegalQuestion(
            question_id=_qid(q_text),
            text=q_text,
            issue_id=primary_issue_id,
            serves_gap="pivot_decisive",
            criticality="high",
            expected_type="yes_no",
        ))

    return out


def _pivot_to_question(test: str, primary_path) -> str:
    """Rewrite a decisive test as an Arabic yes/no question."""
    test_clean = test.replace("إثبات:", "").replace("إثبات عكسي:", "").strip()
    if not test_clean:
        return "ما الدليل المتوفر لديك لترجيح مسار على آخر؟"

    # If it reads like a fact to prove ("وجود العقد")
    return f"هل يوجد ما يثبت: {test_clean}؟"


def pivot_explanation_text(mlre: MLREResult) -> str:
    """Build a short Arabic paragraph explaining WHY these questions matter."""
    if not mlre.reality or not mlre.reality.paths:
        return ""
    if len(mlre.reality.paths) < 2:
        return ""
    p1 = mlre.reality.paths[0]
    p2 = mlre.reality.paths[1]
    return (
        f"هذه الأسئلة تحدِّد فيما إذا كان المسار الأقوى هو "
        f"«{p1.legal_theory}» أم «{p2.legal_theory}»."
    )
