# -*- coding: utf-8 -*-
"""
core/case_memory — Phase 2 · Layer 3: Case Memory Smart.

Deterministic, session-scoped case graph stored in Redis. Jaccard
similarity on closed-vocabulary signatures (concepts + entity_tags) —
no embeddings, no GPT in the hot path.

Architecture choice rationale: ``core/FINDINGS.md §8``.

Public API
----------
- ``CaseSignature`` / ``build_case_signature``
- ``CaseMemoryStore`` / ``StoredCase``
- ``should_skip_case_memory``
- ``build_case_memory_block``
- ``generate_case_summary_once``
- ``extract_entity_tags``

Status
------
CP2 complete (Parts A + B + C + D). All eight public symbols are
live and exercised by ``tests/phase3/`` (30 unit tests + 4 redis_client
tests). Integration into ``query_router.handle_general`` is CP3.
"""
from core.case_memory.signature import (
    CaseSignature,
    build_case_signature,
)
from core.case_memory.entity_extractor import extract_entity_tags
from core.case_memory.store import (
    CaseMemoryStore,
    StoredCase,
)
from core.case_memory.summary import generate_case_summary_once
from core.case_memory.skip import should_skip_case_memory
from core.case_memory.block_builder import build_case_memory_block

__all__ = [
    "CaseSignature",
    "build_case_signature",
    "extract_entity_tags",
    "CaseMemoryStore",
    "StoredCase",
    "generate_case_summary_once",
    "should_skip_case_memory",
    "build_case_memory_block",
]
