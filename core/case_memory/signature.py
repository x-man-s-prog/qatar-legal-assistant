# -*- coding: utf-8 -*-
"""
core/case_memory/signature.py — deterministic per-case fingerprint.

CaseSignature
-------------
Immutable triple: ``(domain, primary_concepts, entity_tags)``.

- ``hash``: SHA-1 over a canonical ``repr`` of the sorted tuple. Stable
  across sessions, independent of construction order. 16-char prefix
  (sufficient for session-local uniqueness; collision odds 1 in 2^64).
- ``similarity``: Jaccard on the union of ``primary_concepts ∪
  entity_tags``. Domain is used as a hard filter by the store, **not**
  as a similarity input.

build_case_signature
--------------------
Pure function: ``(query, concepts, domain) → CaseSignature``. No I/O,
no randomness, no clock. Same arguments always produce the same
signature.

Status: CP2 · Part B. Implementation live; cm1-cm6 exercise it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Optional

from core.case_memory.entity_extractor import extract_entity_tags


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

# How many top concepts to include in signature.
# Rationale: > 3 makes signatures too specific (low recall),
#            < 3 makes them too generic (false positives).
_CONCEPTS_IN_SIGNATURE: int = 3


# ─────────────────────────────────────────────────────────────────
# Dataclass
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CaseSignature:
    """Immutable per-case fingerprint used for memory keying & similarity.

    Attributes
    ----------
    domain : str
        One of ``{"مدني", "جنائي", "عام", "unknown"}``.
    primary_concepts : tuple[str, ...]
        Top-N concepts from ``legal_concepts.extract()``, sorted
        lexicographically and de-duplicated for determinism.
    entity_tags : tuple[str, ...]
        Sorted tuple of entity tags from
        ``entity_extractor.extract_entity_tags``.

    Equality
    --------
    Two signatures are equal iff all three fields are equal. Hash
    (via ``.hash`` property, not Python's built-in ``__hash__``) is
    SHA-1 of canonical repr.
    """

    domain: str
    primary_concepts: tuple[str, ...]
    entity_tags: tuple[str, ...]

    def __post_init__(self):
        # Validation — fail loud on malformed input. These invariants
        # are maintained by build_case_signature; direct instantiation
        # must respect them too.
        if not isinstance(self.domain, str):
            raise TypeError(f"domain must be str, got {type(self.domain).__name__}")
        if not isinstance(self.primary_concepts, tuple):
            raise TypeError("primary_concepts must be tuple[str, ...]")
        if not isinstance(self.entity_tags, tuple):
            raise TypeError("entity_tags must be tuple[str, ...]")

        if list(self.primary_concepts) != sorted(set(self.primary_concepts)):
            raise ValueError("primary_concepts must be sorted and unique")
        if list(self.entity_tags) != sorted(set(self.entity_tags)):
            raise ValueError("entity_tags must be sorted and unique")

    @property
    def hash(self) -> str:
        """SHA-1 hex digest (first 16 chars) of canonical representation.

        Used as the Redis key suffix. Same (domain, concepts, tags) →
        same hash every time, regardless of process or session.
        """
        canonical = f"{self.domain}|{self.primary_concepts}|{self.entity_tags}"
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]

    def similarity(self, other: "CaseSignature") -> float:
        """Jaccard index on the union of concepts ∪ entity_tags.

        Returns a float in ``[0.0, 1.0]``. Identical signatures → 1.0.
        Disjoint → 0.0.

        Domain is **not** included — it is a hard filter applied by the
        store (same-domain cases only), not a similarity feature.

        Edge case: when both signatures have empty concept+tag unions
        the similarity is defined as ``0.0`` (not 1.0 / not NaN) — we
        cannot distinguish "identical empties" from "disjoint empties",
        so we pick the conservative value.
        """
        if not isinstance(other, CaseSignature):
            raise TypeError("Cannot compare CaseSignature with non-CaseSignature")

        set_a = set(self.primary_concepts) | set(self.entity_tags)
        set_b = set(other.primary_concepts) | set(other.entity_tags)

        if not set_a and not set_b:
            return 0.0

        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union


# ─────────────────────────────────────────────────────────────────
# Public factory
# ─────────────────────────────────────────────────────────────────

def build_case_signature(
    query: str,
    concepts: List[str],
    domain: Optional[str] = None,
) -> CaseSignature:
    """Build a deterministic signature from raw inputs.

    Pipeline:
      1. Domain: default ``"unknown"`` if ``None`` or empty-after-strip.
      2. Concepts: dedupe → sort ASCII-lex → truncate to
         ``_CONCEPTS_IN_SIGNATURE``.
      3. Entity tags: extracted from ``query`` via closed vocab.
      4. Assemble ``CaseSignature`` (frozen dataclass validates).

    Parameters
    ----------
    query : str
        The user query text (used for entity-tag extraction).
    concepts : list[str]
        Legal concepts detected upstream. Order does not matter.
    domain : Optional[str]
        Legal domain. Falsy / whitespace-only → ``"unknown"``.

    Returns
    -------
    CaseSignature
        Frozen, hashable, comparable.
    """
    clean_domain = (domain or "unknown").strip() or "unknown"

    unique_sorted = sorted(set(concepts or []))
    top_concepts = tuple(unique_sorted[:_CONCEPTS_IN_SIGNATURE])

    tags = extract_entity_tags(query)
    entity_tags = tuple(tags)  # already sorted + unique from extractor

    return CaseSignature(
        domain=clean_domain,
        primary_concepts=top_concepts,
        entity_tags=entity_tags,
    )


__all__ = ["CaseSignature", "build_case_signature"]
