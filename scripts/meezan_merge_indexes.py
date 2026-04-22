# -*- coding: utf-8 -*-
"""Merge all enumerator index files into a single consolidated one.

The full enumeration runs in parallel via multiple range-specific
enumerator scripts, each writing to its own index_*.jsonl. This tool
merges them into data/meezan_enum/meezan_index_all.jsonl (deduplicated
by almeezan_id; latest fetched_at wins).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent
ENUM_DIR = ROOT / "data" / "meezan_enum"


def main() -> int:
    by_id: dict[int, dict] = {}
    for fp in ENUM_DIR.glob("meezan_index*.jsonl"):
        if fp.name == "meezan_index_all.jsonl":
            continue
        with fp.open(encoding="utf-8") as f:
            n = 0
            for line in f:
                try:
                    o = json.loads(line)
                    lid = int(o["almeezan_id"])
                    cur = by_id.get(lid)
                    if cur is None or (o.get("fetched_at", 0) > cur.get("fetched_at", 0)):
                        by_id[lid] = o
                    n += 1
                except Exception:
                    continue
        print(f"  {fp.name}: {n:,} lines")

    all_fp = ENUM_DIR / "meezan_index_all.jsonl"
    with all_fp.open("w", encoding="utf-8") as f:
        for lid in sorted(by_id.keys()):
            f.write(json.dumps(by_id[lid], ensure_ascii=False) + "\n")

    # Summary stats
    status_c = Counter((o.get("status") or "unknown") for o in by_id.values())
    year_c   = Counter(o.get("law_year") for o in by_id.values() if o.get("law_year"))
    type_c   = Counter(o.get("law_type") for o in by_id.values() if o.get("law_type"))

    print(f"\n=== MERGED ===")
    print(f"  total unique laws: {len(by_id):,}")
    print(f"  by status:")
    for s, c in status_c.most_common():
        print(f"    {s:<12} {c:,}")
    print(f"  top law types:")
    for t, c in type_c.most_common(8):
        print(f"    {t:<25} {c:,}")
    print(f"  recent years:")
    for y in sorted(year_c.keys(), reverse=True)[:8]:
        print(f"    {y}: {year_c[y]:,}")
    print(f"\nWrote: {all_fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
