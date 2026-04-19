# -*- coding: utf-8 -*-
"""
Courtroom Intelligence — adaptive depth + decisive evidence + opponent
modeling, all bounded by strict reasoning budgets and integrated into
the unified fail_closed runtime (no parallel orchestrator).
"""
from core.courtroom.complexity_gate import (
    ComplexityTier, classify_complexity, ComplexityVerdict,
)
from core.courtroom.decisive_evidence import (
    DecisiveEvidenceDetector, score_decisiveness,
)
from core.courtroom.opponent_model import (
    OpponentModel, build_opponent_model,
)
from core.courtroom.outcome_framing import (
    OutcomeFraming, build_conditional_framing,
)
from core.courtroom.domain_packs import (
    get_domain_pack, DomainPack,
)
from core.courtroom.hot_cache import (
    HotCache, get_hot_cache,
)
from core.courtroom.tiered_reasoner import (
    TieredReasoner, get_tiered_reasoner, TieredOutput,
)

__all__ = [
    "ComplexityTier", "classify_complexity", "ComplexityVerdict",
    "DecisiveEvidenceDetector", "score_decisiveness",
    "OpponentModel", "build_opponent_model",
    "OutcomeFraming", "build_conditional_framing",
    "get_domain_pack", "DomainPack",
    "HotCache", "get_hot_cache",
    "TieredReasoner", "get_tiered_reasoner", "TieredOutput",
]
