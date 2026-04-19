# -*- coding: utf-8 -*-
"""
Quarantine Store — the explicit ledger of rejected raw corpus.

Every raw input that CANNOT become a clean KnowledgeRecord lands here
with a machine-readable reason_code. Quarantined records are NEVER
exposed via retrieval, but are inspectable for ops.

No silent drops: anything not runtime-eligible MUST reach the quarantine
ledger with a reason.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter
from typing import Optional

from core.knowledge.contract import QuarantineRecord, QUARANTINE_REASONS

log = logging.getLogger("knowledge_quarantine")


class QuarantineStore:
    """Append-only, in-memory. Mirrors the design of the KnowledgeStore
    but rejected records."""

    def __init__(self):
        self._records: list[QuarantineRecord] = []
        self._by_reason: Counter = Counter()
        self._by_stage: Counter = Counter()

    def add(self, source_path: str, snippet: str, reason_code: str,
             reason_detail: str = "", stage: str = "") -> QuarantineRecord:
        if reason_code not in QUARANTINE_REASONS:
            # Surface drift — but still record it
            log.warning("unknown quarantine reason_code: %s", reason_code)
        qid = hashlib.sha1(
            f"{source_path}|{snippet[:64]}|{reason_code}|{len(self._records)}"
            .encode("utf-8")
        ).hexdigest()[:16]
        rec = QuarantineRecord(
            quarantine_id=qid,
            source_path=source_path,
            original_snippet=(snippet or "")[:120],
            reason_code=reason_code,
            reason_detail=reason_detail,
            detected_at_stage=stage,
        )
        self._records.append(rec)
        self._by_reason[reason_code] += 1
        self._by_stage[stage or "unknown"] += 1
        return rec

    def count(self) -> int:
        return len(self._records)

    def reasons_breakdown(self) -> dict[str, int]:
        return dict(self._by_reason)

    def stages_breakdown(self) -> dict[str, int]:
        return dict(self._by_stage)

    def sample(self, limit: int = 10) -> list[dict]:
        return [r.to_public_dict() for r in self._records[-limit:]]

    def reset(self) -> None:
        self._records.clear()
        self._by_reason.clear()
        self._by_stage.clear()


_store: Optional[QuarantineStore] = None


def get_quarantine() -> QuarantineStore:
    global _store
    if _store is None:
        _store = QuarantineStore()
    return _store
