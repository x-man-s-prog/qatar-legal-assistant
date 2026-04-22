# -*- coding: utf-8 -*-
"""Compute diff between Al-Meezan enumerated index and our DB.

Outputs:
  data/meezan_enum/missing_ids.txt     — IDs in Al-Meezan but not in our DB
  data/meezan_enum/missing_report.md   — human-readable list with titles
  data/meezan_enum/status_mismatch.txt — IDs where our status disagrees
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENUM_FP = ROOT / "data" / "meezan_enum" / "meezan_index.jsonl"
OUT_DIR = ROOT / "data" / "meezan_enum"


def _run_sql(sql: str) -> list[tuple]:
    """Run SQL via docker exec psql and return rows."""
    cmd = [
        "docker", "exec", "legal_db",
        "psql", "-U", "raguser", "-d", "ragdb",
        "-t", "-A", "-F", "|", "-c", sql,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    if r.returncode != 0:
        print("SQL error:", r.stderr[:400], file=sys.stderr)
        return []
    rows = []
    for line in r.stdout.strip().split("\n"):
        if "|" in line:
            rows.append(tuple(line.split("|")))
    return rows


def main() -> int:
    if not ENUM_FP.exists():
        print(f"Enumeration file not found: {ENUM_FP}")
        return 1

    print("Loading Al-Meezan index from enum …")
    meezan: dict[int, dict] = {}
    with ENUM_FP.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                meezan[int(obj["almeezan_id"])] = obj
            except Exception:
                continue
    print(f"  Al-Meezan laws indexed: {len(meezan):,}")

    in_force = sum(1 for o in meezan.values() if o.get("status") == "in_force")
    canceled = sum(1 for o in meezan.values() if o.get("status") == "canceled")
    unknown  = sum(1 for o in meezan.values() if o.get("status") not in ("in_force","canceled"))
    print(f"    in_force: {in_force:,}")
    print(f"    canceled: {canceled:,}")
    print(f"    other:    {unknown:,}")

    print("\nLoading our DB (laws where source='almeezan') …")
    rows = _run_sql(
        "SELECT almeezan_id, is_active, law_name, law_number, law_year, law_type "
        "FROM laws WHERE source='almeezan' AND almeezan_id IS NOT NULL "
        "  AND almeezan_id ~ '^[0-9]+$';"
    )
    db: dict[int, dict] = {}
    for r in rows:
        try:
            lid = int(r[0])
            db[lid] = {
                "is_active":  (r[1] == "t"),
                "law_name":   r[2] if len(r) > 2 else None,
                "law_number": r[3] if len(r) > 3 else None,
                "law_year":   r[4] if len(r) > 4 else None,
                "law_type":   r[5] if len(r) > 5 else None,
            }
        except Exception:
            continue
    print(f"  DB laws (almeezan-sourced): {len(db):,}")

    missing_ids  = sorted(set(meezan.keys()) - set(db.keys()))
    extra_ids    = sorted(set(db.keys()) - set(meezan.keys()))
    common_ids   = sorted(set(meezan.keys()) & set(db.keys()))

    # Status mismatch: our is_active vs meezan status
    status_mismatch = []
    for lid in common_ids:
        live_active = meezan[lid].get("status") == "in_force"
        db_active   = db[lid]["is_active"]
        if live_active != db_active:
            status_mismatch.append(lid)

    print(f"\nMISSING from our DB (on site but not local): {len(missing_ids):,}")
    print(f"EXTRA in our DB (local but removed from site): {len(extra_ids):,}")
    print(f"STATUS mismatch (is_active disagrees):         {len(status_mismatch):,}")

    # Breakdown of missing by status & year
    m_inforce = [lid for lid in missing_ids if meezan[lid].get("status") == "in_force"]
    m_canceled = [lid for lid in missing_ids if meezan[lid].get("status") == "canceled"]
    print(f"    of missing, in_force: {len(m_inforce):,}")
    print(f"    of missing, canceled: {len(m_canceled):,}")

    # Write outputs
    (OUT_DIR / "missing_ids.txt").write_text(
        "\n".join(str(i) for i in missing_ids),
        encoding="utf-8",
    )
    (OUT_DIR / "extra_ids.txt").write_text(
        "\n".join(str(i) for i in extra_ids),
        encoding="utf-8",
    )
    (OUT_DIR / "status_mismatch.txt").write_text(
        "\n".join(str(i) for i in status_mismatch),
        encoding="utf-8",
    )

    # Human-readable report
    rep = []
    rep.append(f"# Al-Meezan vs DB Diff Report")
    rep.append(f"")
    rep.append(f"- Al-Meezan total: {len(meezan):,}")
    rep.append(f"- DB (almeezan source) total: {len(db):,}")
    rep.append(f"- Missing from DB: {len(missing_ids):,}")
    rep.append(f"- Extra in DB (not on site): {len(extra_ids):,}")
    rep.append(f"- Status mismatch: {len(status_mismatch):,}")
    rep.append(f"")
    rep.append(f"## Missing — IN FORCE ({len(m_inforce):,})")
    rep.append(f"")
    rep.append(f"| # | ID | Type | Number | Year | Title |")
    rep.append(f"|---|---|---|---|---|---|")
    for i, lid in enumerate(m_inforce, 1):
        o = meezan[lid]
        rep.append(
            f"| {i} | {lid} | {o.get('law_type') or '—'} | "
            f"{o.get('law_number') or '—'} | {o.get('law_year') or '—'} | "
            f"{(o.get('title') or '—').replace('|', '/')[:120]} |"
        )
    rep.append("")
    rep.append(f"## Missing — CANCELED ({len(m_canceled):,})")
    rep.append(f"")
    rep.append(f"| # | ID | Type | Number | Year | Title |")
    rep.append(f"|---|---|---|---|---|---|")
    for i, lid in enumerate(m_canceled, 1):
        o = meezan[lid]
        rep.append(
            f"| {i} | {lid} | {o.get('law_type') or '—'} | "
            f"{o.get('law_number') or '—'} | {o.get('law_year') or '—'} | "
            f"{(o.get('title') or '—').replace('|', '/')[:120]} |"
        )
    (OUT_DIR / "missing_report.md").write_text("\n".join(rep), encoding="utf-8")

    print(f"\nOutputs:")
    print(f"  {OUT_DIR / 'missing_ids.txt'}")
    print(f"  {OUT_DIR / 'extra_ids.txt'}")
    print(f"  {OUT_DIR / 'status_mismatch.txt'}")
    print(f"  {OUT_DIR / 'missing_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
