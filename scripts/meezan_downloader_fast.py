# -*- coding: utf-8 -*-
"""Al-Meezan FAST downloader — concurrent + minimal-requests.

Design deltas vs meezan_downloader.py:
  • ThreadPoolExecutor with N workers (default 6) for concurrency.
  • Each law fetches ONLY: LawPage + LawView + LawOtherAttachments
    (3 requests). Per-section LawArticles is skipped — if LawView
    returns an empty shell (some very old canceled laws) we record
    it with a marker rather than retry 80+ section pages.
  • Owner + PDF viewer pages skipped (not needed for corpus).
  • Resumable — meta.json acts as completion marker.

Usage:
    python scripts/meezan_downloader_fast.py --ids-file <file>
                                              [--workers 6]
                                              [--sleep 0.1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading

BASE    = "https://www.almeezan.qa"
UA      = "Mozilla/5.0 (meezan-downloader-fast)"
TIMEOUT = 30
ROOT    = Path(__file__).parent.parent
OUT_DIR = ROOT / "data" / "meezan_laws"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _fetch(url: str, timeout: int = TIMEOUT) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "")
            return r.status, body, ctype
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body, ""
    except Exception as e:
        return 0, f"__EXC__:{type(e).__name__}:{e}".encode(), ""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _extract_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split("|")]
    cand = parts[-1] if parts else ""
    cand = re.sub(r"\s+", " ", cand).strip()
    return cand or None


def _find_attachments(html: str) -> list[dict]:
    atts: list[dict] = []
    for m in re.finditer(
        r'href=["\']([^"\'\s]+?\.(?:pdf|doc|docx|xls|xlsx|zip|rar))["\']',
        html, re.I,
    ):
        atts.append({"url": m.group(1), "kind": "file"})
    for m in re.finditer(r'<img[^>]*src=["\']([^"\'\s]+\.(?:png|jpg|jpeg|gif))["\']', html, re.I):
        src = m.group(1).lower()
        if any(k in src for k in ("logo", "icon", "favicon", "mada", "hukoomi", "app_png", "pr1", "loading", "wcag", "flag")):
            continue
        atts.append({"url": m.group(1), "kind": "image"})
    return atts


def download_one(law_id: int, *, skip_existing: bool = True, sleep: float = 0.1) -> dict:
    law_dir  = OUT_DIR / str(law_id)
    files_dir = law_dir / "files"
    meta_fp  = law_dir / "meta.json"

    if skip_existing and meta_fp.exists():
        try:
            cached = json.loads(meta_fp.read_text(encoding="utf-8"))
            cached["skipped"] = True
            return cached
        except Exception:
            pass

    law_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(exist_ok=True)

    summary: dict = {
        "law_id":      law_id,
        "fetched_at":  int(time.time()),
        "urls":        {},
        "hashes":      {},
        "attachments": [],
        "tree_ids":    [],
        "errors":      [],
    }

    # 1) LawPage
    url = f"{BASE}/LawPage.aspx?id={law_id}&language=ar"
    status, body, _ = _fetch(url)
    if status != 200 or len(body) < 1000:
        summary["errors"].append(f"LawPage {status}")
        return summary
    lp = body.decode("utf-8", errors="replace")
    summary["urls"]["lawpage"] = url
    (law_dir / "lawpage.html").write_bytes(body)
    summary["hashes"]["lawpage"] = _sha(body)
    summary["title"] = _extract_title(lp)
    summary["tree_ids"] = sorted(set(int(m) for m in re.findall(r"LawTreeSectionID=(\d+)", lp)))
    time.sleep(sleep)

    # 2) LawView
    url = f"{BASE}/LawView.aspx?LawID={law_id}&language=ar"
    status, body, _ = _fetch(url)
    if status == 200 and len(body) > 500:
        summary["urls"]["lawview"] = url
        (law_dir / "lawview.html").write_bytes(body)
        summary["hashes"]["lawview"] = _sha(body)
        text = body.decode("utf-8", errors="replace")
        summary["lawview_has_content"] = bool(
            re.search(r"(?:المادة|مادة)\s*\(?\s*\d+", text)
        )
    else:
        summary["errors"].append(f"LawView {status}")
        summary["lawview_has_content"] = False
    time.sleep(sleep)

    # 3) LawOtherAttachments (optional — for file discovery)
    url = f"{BASE}/LawOtherAttachments.aspx?id={law_id}&language=ar"
    status, body, _ = _fetch(url)
    if status == 200 and len(body) > 500:
        summary["urls"]["attachments"] = url
        (law_dir / "attachments.html").write_bytes(body)
        att_html = body.decode("utf-8", errors="replace")
        summary["attachments"] = _find_attachments(att_html)
    time.sleep(sleep)

    # 4) Download actual attachment files (if any)
    for att in summary["attachments"]:
        att_url = att["url"]
        if not att_url.startswith("http"):
            att_url = urllib.parse.urljoin(BASE + "/", att_url)
        ps, pb, pc = _fetch(att_url, timeout=45)
        if ps == 200 and len(pb) > 0:
            name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(att_url).path))
            if not name or len(name) > 120:
                name = f"{_sha(pb)[:12]}.bin"
            (files_dir / name).write_bytes(pb)
            att["local_path"] = str((files_dir / name).relative_to(ROOT))
            att["size"] = len(pb)
            att["hash"] = _sha(pb)
            att["mime"] = pc
        time.sleep(sleep)

    # Write meta
    meta_fp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sleep",   type=float, default=0.1)
    args = ap.parse_args()

    ids = [int(l.strip()) for l in open(args.ids_file) if l.strip().isdigit()]
    _log(f"Downloading {len(ids)} laws with {args.workers} workers; sleep={args.sleep}s/req")

    ok = 0
    skipped = 0
    err = 0
    done = 0
    total = len(ids)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(download_one, lid, sleep=args.sleep): lid
            for lid in ids
        }
        for fut in as_completed(futures):
            lid = futures[fut]
            done += 1
            try:
                s = fut.result()
                if s.get("skipped"):
                    skipped += 1
                    _log(f"[{done}/{total}] {lid} SKIP (already done)")
                elif s.get("errors"):
                    err += 1
                    _log(f"[{done}/{total}] {lid} ERR {s['errors']}")
                else:
                    ok += 1
                    title = (s.get("title") or "—")[:60]
                    n_att = len(s.get("attachments", []))
                    has_content = "✓" if s.get("lawview_has_content") else "·"
                    _log(f"[{done}/{total}] {lid} {has_content} {n_att}att — {title}")
            except Exception as e:
                err += 1
                _log(f"[{done}/{total}] {lid} EXC {type(e).__name__}: {e}")

    _log(f"\n=== DONE: ok={ok} skipped={skipped} err={err} total={total} ===")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
