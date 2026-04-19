# -*- coding: utf-8 -*-
"""
Knowledge Store persistence — disk snapshot + version header.
===============================================================

A KnowledgeStore snapshot is a binary file containing:
  - header dict: {version, created_at, ingestor_git_rev?, source_mix, row_count}
  - records list: [KnowledgeRecord, ...]

Version tag is bumped when the KnowledgeRecord dataclass changes.
Loading a mismatched version → refuses (returns None) so corrupt
snapshots never contaminate runtime.
"""
from __future__ import annotations

import logging
import os
import pickle
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("knowledge_persistence")


# Bump this ONLY when KnowledgeRecord / KnowledgeStore layout changes
SNAPSHOT_VERSION = "v1.0"


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_SNAPSHOT_DIR = _PROJECT_ROOT / ".knowledge_snapshots"
_DEFAULT_SNAPSHOT_DIR.mkdir(exist_ok=True)
_DEFAULT_PATH = _DEFAULT_SNAPSHOT_DIR / "store_v1.pkl"


def snapshot_path() -> Path:
    """Env-overridable path. Default: .knowledge_snapshots/store_v1.pkl"""
    raw = os.getenv("DB_KNOWLEDGE_SNAPSHOT_PATH")
    if raw:
        return Path(raw)
    return _DEFAULT_PATH


def save_snapshot(store, source_mix: dict, ingestor_tag: str = "",
                   path: Optional[Path] = None) -> dict:
    """Persist the KnowledgeStore to disk. Returns {ok, bytes, path}."""
    p = path or snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "version":      SNAPSHOT_VERSION,
        "created_at":   time.time(),
        "row_count":    store.count(),
        "eligible":     store.runtime_eligible_count(),
        "source_mix":   dict(source_mix or {}),
        "ingestor_tag": ingestor_tag,
    }
    payload = {"header": header, "records": store.all()}
    try:
        with p.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        size = p.stat().st_size
        log.info("[persistence] saved snapshot %s bytes=%d records=%d",
                 p.name, size, header["row_count"])
        return {"ok": True, "bytes": size, "path": str(p), "header": header}
    except Exception as e:
        log.exception("[persistence] save failed")
        return {"ok": False, "error": str(e), "path": str(p)}


def load_snapshot(path: Optional[Path] = None) -> Optional[dict]:
    """Load snapshot. Returns {header, records} or None on any failure.

    Refuses to return data if version mismatch is detected.
    """
    p = path or snapshot_path()
    if not p.exists():
        return None
    try:
        with p.open("rb") as f:
            payload = pickle.load(f)
        header = payload.get("header", {})
        if header.get("version") != SNAPSHOT_VERSION:
            log.warning("[persistence] version mismatch: snapshot=%s current=%s → ignored",
                         header.get("version"), SNAPSHOT_VERSION)
            return None
        log.info("[persistence] loaded snapshot: records=%d created_at=%s",
                 header.get("row_count", 0), header.get("created_at", 0))
        return payload
    except Exception as e:
        log.warning("[persistence] load failed: %s", e)
        return None


def snapshot_info() -> dict:
    """Report whether a snapshot exists and its metadata (no load)."""
    p = snapshot_path()
    if not p.exists():
        return {"exists": False, "path": str(p)}
    try:
        with p.open("rb") as f:
            payload = pickle.load(f)
        return {
            "exists": True,
            "path": str(p),
            "bytes": p.stat().st_size,
            "header": payload.get("header", {}),
        }
    except Exception as e:
        return {"exists": True, "path": str(p), "error": str(e)}
