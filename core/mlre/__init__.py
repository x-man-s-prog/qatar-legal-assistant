# -*- coding: utf-8 -*-
"""
Multi-Legal Reality Engine v2 (MLRE++).

Generates 6-8 competing legal hypotheses, builds independent issue graphs,
simulates evidence, scores on 5 dimensions, runs adversarial self-attacks,
keeps 2-3 surviving interpretations, and synthesizes a structured
Legal Reality Output.

Public API:
    from core.mlre import (
        Hypothesis, HypothesisType,
        generate_hypotheses, score_hypotheses,
        attack_hypotheses, select_survivors,
        ContextLockMatrix, build_context_lock,
        LegalReality, synthesize_reality,
        run_mlre,
    )
"""
from core.mlre.hypothesis import (
    Hypothesis, HypothesisType, HypothesisBundle,
    generate_hypotheses,
)
from core.mlre.scoring import (
    ScoreBreakdown, score_hypothesis, score_hypotheses,
)
from core.mlre.adversarial import (
    AdversarialAttack, attack_hypotheses, select_survivors,
)
from core.mlre.context_lock import (
    ContextLockMatrix, build_context_lock,
)
from core.mlre.synthesis import (
    LegalReality, synthesize_reality,
)
from core.mlre.orchestrator import (
    MLREResult, run_mlre, DraftingV2Mode,
)
# ── NEW v2 output authority modules ──
from core.mlre.output_composer import (
    ComposedOutput, OutputMode, compose_output,
)
from core.mlre.output_firewall import (
    FirewallReport, sanitize_user_output,
)
from core.mlre.pivot_questions import (
    questions_from_mlre, pivot_explanation_text,
)
from core.mlre.mlre_drafting import (
    build_memo_from_mlre,
)

__all__ = [
    "Hypothesis", "HypothesisType", "HypothesisBundle",
    "generate_hypotheses",
    "ScoreBreakdown", "score_hypothesis", "score_hypotheses",
    "AdversarialAttack", "attack_hypotheses", "select_survivors",
    "ContextLockMatrix", "build_context_lock",
    "LegalReality", "synthesize_reality",
    "MLREResult", "run_mlre", "DraftingV2Mode",
    # v2 output authority
    "ComposedOutput", "OutputMode", "compose_output",
    "FirewallReport", "sanitize_user_output",
    "questions_from_mlre", "pivot_explanation_text",
    "build_memo_from_mlre",
]
