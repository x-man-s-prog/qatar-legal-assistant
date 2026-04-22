# -*- coding: utf-8 -*-
"""Purge canceled laws from both laws (v1) and laws_v2 tables.

Steps:
  1. Reconcile status mismatches using Al-Meezan as authority.
     (Our DB has 192 status mismatches where Al-Meezan says
     canceled but we have is_active=true, or vice versa.)
  2. Delete all rows with is_active=false (v1) / status='canceled' (v2).
     CASCADE wipes articles_v2, attachments_v2, and chunks.
  3. Report final counts.

Running this is DESTRUCTIVE — it wipes canceled laws permanently from
the DB. The original HTML is still on disk under data/meezan_laws/
for future re-ingestion if needed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENUM_FP = ROOT / "data" / "meezan_enum" / "meezan_index_all.jsonl"


def _sql(script: str) -> str:
    cmd = [
        "docker", "exec", "-i", "legal_db",
        "psql", "-U", "raguser", "-d", "ragdb",
        "-v", "ON_ERROR_STOP=1",
    ]
    r = subprocess.run(
        cmd, input=script, capture_output=True, text=True,
        check=False, timeout=120, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:500])
    return r.stdout


def main() -> int:
    print("=" * 60)
    print("Al-Meezan status reconciliation + canceled purge")
    print("=" * 60)

    # ── 1. Load Al-Meezan authoritative status ─────────────────
    if not ENUM_FP.exists():
        print(f"FATAL: {ENUM_FP} not found", file=sys.stderr)
        return 1
    meezan: dict[int, str] = {}
    with ENUM_FP.open(encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
                meezan[int(o["almeezan_id"])] = o.get("status", "unknown")
            except Exception:
                continue
    print(f"\n[1] Loaded Al-Meezan authority: {len(meezan):,} laws")

    canceled_ids = {lid for lid, st in meezan.items() if st == "canceled"}
    in_force_ids = {lid for lid, st in meezan.items() if st == "in_force"}
    print(f"    canceled: {len(canceled_ids):,}   in_force: {len(in_force_ids):,}")

    # ── 2. Reconcile status in laws (v1) ──────────────────────
    # For each almeezan_id in our DB, set is_active per Al-Meezan.
    print("\n[2] Reconciling laws (v1) status with Al-Meezan authority…")
    canc_ids_list = ",".join(str(i) for i in sorted(canceled_ids))
    inf_ids_list  = ",".join(str(i) for i in sorted(in_force_ids))

    if canc_ids_list:
        out = _sql(
            f"""
            UPDATE laws SET is_active=false
            WHERE source='almeezan'
              AND almeezan_id::int IN ({canc_ids_list})
              AND is_active = true
              AND almeezan_id ~ '^[0-9]+$';
            """
        )
        print(f"    v1 mismatch fix (now canceled): {out.strip()}")

    if inf_ids_list:
        out = _sql(
            f"""
            UPDATE laws SET is_active=true
            WHERE source='almeezan'
              AND almeezan_id::int IN ({inf_ids_list})
              AND is_active = false
              AND almeezan_id ~ '^[0-9]+$';
            """
        )
        print(f"    v1 mismatch fix (now in_force): {out.strip()}")

    # ── 3. Reconcile status in laws_v2 ─────────────────────────
    print("\n[3] Reconciling laws_v2 status…")
    if canc_ids_list:
        out = _sql(
            f"UPDATE laws_v2 SET status='canceled' "
            f"WHERE almeezan_id IN ({canc_ids_list}) AND status<>'canceled';"
        )
        print(f"    v2 mismatch fix (now canceled): {out.strip()}")
    if inf_ids_list:
        out = _sql(
            f"UPDATE laws_v2 SET status='in_force' "
            f"WHERE almeezan_id IN ({inf_ids_list}) AND status<>'in_force';"
        )
        print(f"    v2 mismatch fix (now in_force): {out.strip()}")

    # Also handle 'unknown' status in v2 as in_force (safe default)
    out = _sql("UPDATE laws_v2 SET status='in_force' WHERE status='unknown';")
    print(f"    v2 unknown→in_force: {out.strip()}")

    # ── 4. Show pre-purge counts ───────────────────────────────
    print("\n[4] Pre-purge counts:")
    print(_sql(
        """
        SELECT 'laws (v1)' AS tbl,
               SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS in_force,
               SUM(CASE WHEN NOT is_active THEN 1 ELSE 0 END) AS canceled
        FROM laws
        UNION ALL
        SELECT 'laws_v2',
               SUM(CASE WHEN status='in_force' THEN 1 ELSE 0 END),
               SUM(CASE WHEN status='canceled' THEN 1 ELSE 0 END)
        FROM laws_v2;
        """
    ))

    # ── 5. Purge canceled from v1 (CASCADE → chunks, precedents, etc.) ──
    print("\n[5] Purging canceled laws from v1 (laws + chunks)…")
    out = _sql(
        """
        BEGIN;
        DELETE FROM chunks WHERE law_id IN
          (SELECT id FROM laws WHERE is_active=false);
        DELETE FROM laws WHERE is_active=false;
        COMMIT;
        """
    )
    print(f"    v1 purge: {out.strip()}")

    # ── 6. Purge canceled from v2 (CASCADE) ───────────────────
    print("\n[6] Purging canceled laws from v2 (CASCADE)…")
    out = _sql(
        """
        BEGIN;
        -- CASCADE handles articles_v2, attachments_v2, relationships, etc.
        DELETE FROM laws_v2 WHERE status='canceled';
        COMMIT;
        """
    )
    print(f"    v2 purge: {out.strip()}")

    # ── 7. Final counts ──────────────────────────────────────
    print("\n[7] Final counts:")
    print(_sql(
        """
        SELECT 'laws (v1)' AS tbl,
               COUNT(*) AS total,
               SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS in_force
        FROM laws
        UNION ALL
        SELECT 'laws_v2',
               COUNT(*),
               SUM(CASE WHEN status='in_force' THEN 1 ELSE 0 END)
        FROM laws_v2
        UNION ALL
        SELECT 'articles_v2', COUNT(*), NULL FROM articles_v2
        UNION ALL
        SELECT 'chunks (v1)', COUNT(*), NULL FROM chunks;
        """
    ))

    print("\n=== PURGE COMPLETE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
