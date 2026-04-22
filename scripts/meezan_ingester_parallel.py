# -*- coding: utf-8 -*-
"""Parallel ingester — same logic as meezan_ingester.py but with
ThreadPoolExecutor workers. Each worker submits its own docker-exec
psql call, so we get N× throughput.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading

# Import everything from the original ingester
sys.path.insert(0, str(Path(__file__).parent))
from meezan_ingester import ingest_law_batch, LAW_DIR  # noqa: E402

_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--all-parsed", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    ids: list[int] = []
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.all_parsed:
        for d in LAW_DIR.iterdir():
            if d.is_dir() and d.name.isdigit() and (d / "parsed.json").exists():
                ids.append(int(d.name))
        ids.sort()
    else:
        print("ERROR: --ids or --all-parsed", file=sys.stderr)
        return 2

    _log(f"Ingesting {len(ids)} laws with {args.workers} workers…")

    ok = 0
    err = 0
    done = 0
    total = len(ids)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(ingest_law_batch, lid): lid for lid in ids}
        for fut in as_completed(futures):
            lid = futures[fut]
            done += 1
            try:
                r = fut.result()
                if r.get("ok"):
                    ok += 1
                    if done % 25 == 0 or done == total:
                        _log(f"[{done}/{total}] {lid}: {r['articles']} articles "
                             f"({ok} ok, {err} err)")
                else:
                    err += 1
                    _log(f"[{done}/{total}] {lid}: ERROR {r.get('error','?')[:150]}")
            except Exception as e:
                err += 1
                _log(f"[{done}/{total}] {lid}: EXC {type(e).__name__}: {str(e)[:150]}")

    _log(f"\n=== ingested ok={ok} err={err} total={total} ===")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
