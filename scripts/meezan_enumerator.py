# -*- coding: utf-8 -*-
"""Al-Meezan complete enumerator.

Iterates all possible LawPage.aspx?id=N IDs, extracts metadata for
each valid law, and writes a rolling JSONL index to disk.

WHY THIS EXISTS
================
Al-Meezan does not expose a public listing/search API. The
AllLegislationsSearch.aspx page requires a postback flow that
bypasses status filtering. The cleanest, most reliable enumeration
is sequential by integer ID.

CHECKPOINTING
=============
Writes one JSON line per valid law to meezan_index.jsonl. Also
maintains meezan_enum_state.json with the last-visited ID so
restarts resume from where it left off.

RATE LIMITING
=============
Default 0.3s sleep between requests. Respects the site and
avoids triggering WAF rules. ~12k IDs * 0.3s = ~1 hour best case.

Usage:
    python scripts/meezan_enumerator.py [--start N] [--end M] [--sleep S]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE      = "https://www.almeezan.qa"
UA        = "Mozilla/5.0 (meezan-enumerator research)"
TIMEOUT   = 25
OUT_DIR   = Path(__file__).parent.parent / "data" / "meezan_enum"
INDEX_FP  = OUT_DIR / "meezan_index.jsonl"
STATE_FP  = OUT_DIR / "meezan_enum_state.json"
RAW_DIR   = OUT_DIR / "raw_lawpage"

OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


# ── Metadata extraction ──────────────────────────────────────────

_LAW_NUM_YR_RE = re.compile(r"(قانون|مرسوم(?:\s+بقانون)?|قرار\s+(?:أميري|وزاري|مجلس\s+الوزراء|رئيس\s+مجلس\s+الوزراء|النائب\s+العام|مجلس(?:\s+إدارة)?)?|أمر\s+أميري|دستور|وثيقة|إعلان)[^\(]{0,30}?\(\s*(\d+)\s*\)\s*لسنة\s*(\d{4})")

_TITLE_RE_HTML = re.compile(
    r"<(?:h[1-3]|span|div)[^>]*id=\"[^\"]*(?:lblLawName|lblTitle|HeaderTitle)[^\"]*\"[^>]*>"
    r"([^<]+(?:<[^/][^>]*>[^<]*</[^>]+>[^<]*)?)</"
)

_TITLE_TEXT_RE = re.compile(
    r"(?:قانون|مرسوم(?:\s+بقانون)?|قرار\s+(?:أميري|وزاري|مجلس\s+الوزراء|رئيس\s+مجلس\s+الوزراء|النائب\s+العام|مجلس(?:\s+إدارة)?)?|أمر\s+أميري|دستور|وثيقة|إعلان)\s*رقم\s*\(\d+\)\s*لسنة\s*\d{4}[^\n<]{0,300}"
)

_STATUS_RE = re.compile(r"(قيد\s*التطبيق|ملغى|معدل|ساري)")


def _fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return 0, f"__EXC__:{type(e).__name__}:{e}"


def _extract_meta(html: str, law_id: int) -> dict | None:
    """Return metadata dict or None if not a valid law page."""
    # 404 shortcut
    if "The resource cannot be found" in html or "HTTP 404" in html:
        return None
    if "صفحة غير موجودة" in html or "لم يتم العثور" in html:
        return None
    # Empty / tiny response
    if len(html) < 5_000:
        return None

    # 1) <title> tag — last pipe-separated segment is the law name.
    title = None
    m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if m:
        parts = [p.strip() for p in m.group(1).split("|")]
        if parts:
            cand = parts[-1]
            # Clean whitespace + drop newlines inside
            cand = re.sub(r"\s+", " ", cand).strip()
            if cand and len(cand) >= 4:
                title = cand

    # 2) Fallback: pattern-match in page body
    if not title:
        m2 = _TITLE_TEXT_RE.search(html)
        if m2:
            title = re.sub(r"\s+", " ", m2.group(0)).strip()

    if not title:
        # Not a law page
        return None

    # Skip UI default titles that clearly aren't a law
    if title in ("البوابة القانونية القطرية", "الميزان", "التشريعات"):
        return None

    # Extract law_type, number, year from title
    law_type, law_number, law_year = None, None, None
    mnum = _LAW_NUM_YR_RE.search(title)
    if mnum:
        law_type = mnum.group(1).strip()
        law_number = mnum.group(2)
        law_year = mnum.group(3)

    # Dastour / constitution special case
    if not law_number and "دستور" in title[:20]:
        law_type = "دستور"
        # year from title
        yrm = re.search(r"(\d{4})", title)
        if yrm:
            law_year = yrm.group(1)

    # Status (from page body) — Al-Meezan uses two states:
    #   قيد التطبيق (in force)
    #   ملغى        (canceled)
    # Priority: canceled marker wins if present anywhere clearly.
    status = "unknown"
    if re.search(r"التشريع\s+ملغى|قانون\s+ملغى|مرسوم\s+ملغى|قرار\s+ملغى", html):
        status = "canceled"
    elif re.search(r"قيد\s+التطبيق", html):
        status = "in_force"
    elif re.search(r"ملغى", html):
        status = "canceled"

    # TOC sections (number of articles/chapters)
    toc_count = len(set(re.findall(r"LawTreeSectionID=(\d+)", html)))

    # Attachments presence (LawOtherAttachments link exists)
    has_attachments_page = bool(
        re.search(r"LawOtherAttachments\.aspx\?id=\d+", html)
    )

    # Subject from breadcrumb
    subject = None
    bc = re.search(
        r"<a[^>]*href=\"LawsBySubject\.aspx\?entry=(\d+)[^\"]*\"[^>]*>([^<]+)</a>",
        html,
    )
    if bc:
        subject = {"id": bc.group(1), "name": bc.group(2).strip()}

    # Issue date
    issue_date = None
    dm = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", html)
    if dm and int(dm.group(3)) > 1950:
        issue_date = f"{dm.group(3)}-{dm.group(2):0>2}-{dm.group(1):0>2}"

    return {
        "almeezan_id":          law_id,
        "title":                title[:500],
        "law_type":             law_type,
        "law_number":           law_number,
        "law_year":             law_year,
        "status":               status,
        "toc_sections":         toc_count,
        "has_attachments_page": has_attachments_page,
        "subject":              subject,
        "issue_date":           issue_date,
        "lawpage_size":         len(html),
        "fetched_at":           int(time.time()),
    }


def _load_state() -> dict:
    if STATE_FP.exists():
        try:
            return json.loads(STATE_FP.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_visited_id": 0, "valid_count": 0, "invalid_streak": 0}


def _save_state(state: dict) -> None:
    STATE_FP.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_visited_ids() -> set[int]:
    if not INDEX_FP.exists():
        return set()
    ids = set()
    with INDEX_FP.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                ids.add(obj["almeezan_id"])
            except Exception:
                continue
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end",   type=int, default=15000)
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--resume", action="store_true", default=True,
                    help="Resume from meezan_enum_state.json")
    ap.add_argument("--save-raw", action="store_true",
                    help="Save raw HTML for each valid law")
    args = ap.parse_args()

    state = _load_state() if args.resume else {"last_visited_id": 0, "valid_count": 0, "invalid_streak": 0}
    visited = _load_visited_ids()

    start_id = max(args.start, state.get("last_visited_id", 0) + 1)
    if args.resume and start_id > args.start:
        print(f"RESUME from ID {start_id} (state file)")
    end_id = args.end

    print(f"Enumerating Al-Meezan IDs {start_id}..{end_id}")
    print(f"  already visited: {len(visited)} laws")
    print(f"  state: {state}")
    print(f"  output: {INDEX_FP}")

    index_f = INDEX_FP.open("a", encoding="utf-8")
    ok, bad, err, already = 0, 0, 0, 0
    try:
        for law_id in range(start_id, end_id + 1):
            if law_id in visited:
                already += 1
                continue
            url = f"{BASE}/LawPage.aspx?id={law_id}&language=ar"
            status_code, html = _fetch(url)
            if html.startswith("__EXC__:"):
                err += 1
                print(f"  [{law_id}] ERR {html[:80]}")
                state["last_visited_id"] = law_id
                time.sleep(args.sleep * 2)
                continue
            if status_code != 200:
                bad += 1
                state["last_visited_id"] = law_id
                time.sleep(args.sleep)
                continue

            meta = _extract_meta(html, law_id)
            if not meta:
                bad += 1
            else:
                ok += 1
                index_f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                index_f.flush()
                if args.save_raw:
                    (RAW_DIR / f"{law_id}.html").write_text(html, encoding="utf-8")
                print(
                    f"  [{law_id:>5}] {meta.get('law_type') or '-':<15} "
                    f"{meta.get('law_number') or '-':<5}/"
                    f"{meta.get('law_year') or '-':<4} "
                    f"{meta.get('status') or '?':<10} "
                    f"toc={meta.get('toc_sections'):<4} "
                    f"{(meta.get('title') or '')[:60]}"
                )

            state["last_visited_id"] = law_id
            state["valid_count"] = state.get("valid_count", 0) + (1 if meta else 0)
            state["invalid_streak"] = 0 if meta else state.get("invalid_streak", 0) + 1

            # Flush state every 50 IDs
            if law_id % 50 == 0:
                _save_state(state)

            # Heuristic: if 500 invalid in a row AND we're past id=11500,
            # assume we've covered everything and stop early.
            if (
                state["invalid_streak"] >= 500
                and law_id > 11500
            ):
                print(f"  500 invalid streak at {law_id} — stopping early")
                break

            time.sleep(args.sleep)
    finally:
        index_f.close()
        _save_state(state)

    print()
    print(f"=== DONE ===")
    print(f"  valid:   {ok:,}")
    print(f"  invalid: {bad:,}")
    print(f"  errors:  {err:,}")
    print(f"  skipped: {already:,}")
    print(f"  total in index: {state.get('valid_count', 0):,}")
    print(f"  index:   {INDEX_FP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
