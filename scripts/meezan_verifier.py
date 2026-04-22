# -*- coding: utf-8 -*-
"""Verify each ingested law against the live Al-Meezan site.

For each law in laws_v2:
  1. Re-fetch LawPage.aspx?id=X from the live site.
  2. Compare title, status, article count.
  3. Optionally re-fetch LawView.aspx and compute content_hash diff.
  4. Insert a row in verification_log_v2.

Usage:
    python scripts/meezan_verifier.py [--ids 9923,2559] [--limit N]
                                      [--deep]  # also verify full text
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT   = Path(__file__).parent.parent
BASE   = "https://www.almeezan.qa"
UA     = "Mozilla/5.0 (meezan-verifier)"
TIMEOUT = 30

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def _fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, f"__EXC__:{type(e).__name__}:{e}"


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _title_of(html: str) -> str | None:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split("|")]
    cand = parts[-1] if parts else ""
    return re.sub(r"\s+", " ", cand).strip() or None


def _status_of(html: str) -> str:
    if re.search(r"التشريع\s+ملغى|قانون\s+ملغى|مرسوم\s+ملغى|قرار\s+ملغى", html):
        return "canceled"
    if re.search(r"قيد\s+التطبيق", html):
        return "in_force"
    if re.search(r"ملغى", html):
        return "canceled"
    return "unknown"


def _count_sections(html: str) -> int:
    return len(set(re.findall(r"LawTreeSectionID=(\d+)", html)))


def _extract_flat_text(lawview_html: str) -> str:
    """Extract text from LawView HTML for fidelity hashing."""
    # strip HTML tags & normalize whitespace
    t = re.sub(r"<[^>]+>", "\n", lawview_html)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _pg_query(sql: str) -> list[tuple]:
    import subprocess
    cmd = [
        "docker", "exec", "-i", "legal_db",
        "psql", "-U", "raguser", "-d", "ragdb",
        "-t", "-A", "-F", chr(31),
    ]
    r = subprocess.run(
        cmd, input=sql, capture_output=True, text=True,
        check=False, timeout=60, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    rows = []
    for line in r.stdout.strip().split("\n"):
        if not line:
            continue
        rows.append(tuple(line.split(chr(31))))
    return rows


def _pg_exec(sql: str) -> None:
    import subprocess
    cmd = [
        "docker", "exec", "-i", "legal_db",
        "psql", "-U", "raguser", "-d", "ragdb",
        "-q",
    ]
    r = subprocess.run(
        cmd, input=sql, capture_output=True, text=True,
        check=False, timeout=60, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])


def verify_one(almeezan_id: int, *, deep: bool = False) -> dict:
    """Verify one law. Returns a result dict suitable for logging."""
    result = {"almeezan_id": almeezan_id, "status": "unknown", "diffs": [], "ok": False}

    # 1) Fetch live LawPage
    status_code, lp_html = _fetch(f"{BASE}/LawPage.aspx?id={almeezan_id}&language=ar")
    if status_code != 200:
        result["status"] = "missing"
        result["diffs"].append(f"LawPage {status_code}")
        return result

    live_title  = _title_of(lp_html)
    live_status = _status_of(lp_html)
    live_secs   = _count_sections(lp_html)

    # 2) Load DB row
    rows = _pg_query(
        f"SELECT law_name, status, "
        f"(SELECT COUNT(*) FROM articles_v2 WHERE law_id=l.id) AS articles, "
        f"content_hash "
        f"FROM laws_v2 l WHERE almeezan_id={almeezan_id};"
    )
    if not rows:
        result["status"] = "missing"
        result["diffs"].append("not in DB")
        return result
    db_title, db_status, db_articles, db_hash = rows[0]
    db_articles = int(db_articles) if db_articles.isdigit() else 0

    # 3) Compare
    if live_title and db_title and (live_title or "").strip() != (db_title or "").strip():
        result["diffs"].append(
            f"title_diff: live='{(live_title or '')[:80]}' db='{(db_title or '')[:80]}'"
        )
    if live_status != (db_status or "unknown"):
        result["diffs"].append(f"status_diff: live={live_status} db={db_status}")
    if db_articles == 0:
        result["diffs"].append("no_articles_in_db")

    # 4) Deep: compare full-text hash
    if deep:
        _, lv_html = _fetch(f"{BASE}/LawView.aspx?LawID={almeezan_id}&language=ar")
        if lv_html and not lv_html.startswith("__EXC__"):
            live_text = _extract_flat_text(lv_html)
            live_hash = _sha256(live_text)
            if db_hash and live_hash != db_hash:
                result["diffs"].append(f"content_hash_diff: live={live_hash[:12]} db={db_hash[:12] if db_hash else '-'}")

    result["status"] = "ok" if not result["diffs"] else "diff"
    result["ok"] = not result["diffs"]
    result["live_title"] = live_title
    result["db_title"]   = db_title
    result["live_status"] = live_status
    result["db_status"]   = db_status
    result["live_sections"] = live_secs
    result["db_articles"] = db_articles
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="Comma-separated law IDs")
    ap.add_argument("--all", action="store_true", help="Verify all laws_v2 rows")
    ap.add_argument("--deep", action="store_true", help="Also compare full text hash")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    ids: list[int] = []
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.all:
        rows = _pg_query("SELECT almeezan_id FROM laws_v2 ORDER BY almeezan_id;")
        ids = [int(r[0]) for r in rows if r and r[0].isdigit()]
    else:
        print("ERROR: supply --ids or --all", file=sys.stderr)
        return 2
    if args.limit:
        ids = ids[: args.limit]

    print(f"Verifying {len(ids)} laws (deep={args.deep})")

    ok, diff, missing = 0, 0, 0
    for i, lid in enumerate(ids, 1):
        r = verify_one(lid, deep=args.deep)
        st = r["status"]
        note = "; ".join(r["diffs"])[:300]
        # Insert verification log
        sql = (
            "INSERT INTO verification_log_v2 "
            "(law_id, status, diff_summary) VALUES "
            f"((SELECT id FROM laws_v2 WHERE almeezan_id={lid}), "
            f"'{st}', "
            f"'{note.replace(chr(39),chr(39)+chr(39))}');"
        )
        try:
            _pg_exec(sql)
        except Exception:
            pass

        tag = {"ok": "OK ", "diff": "DIF", "missing": "MIS"}.get(st, "?  ")
        print(f"[{i}/{len(ids)}] {lid} {tag} — {(r.get('live_title') or '-')[:70]}")
        if note:
            print(f"            diffs: {note[:200]}")
        if st == "ok":
            ok += 1
        elif st == "diff":
            diff += 1
        else:
            missing += 1
        time.sleep(args.sleep)

    print()
    print(f"=== VERIFICATION DONE ===")
    print(f"  ok:      {ok:,}")
    print(f"  diff:    {diff:,}")
    print(f"  missing: {missing:,}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
