# -*- coding: utf-8 -*-
"""Al-Meezan complete law downloader.

For each law_id in an input list, downloads:
  • LawPage.aspx?id=X           — overview page (metadata + TOC)
  • LawView.aspx?LawID=X        — flat full-text view
  • LawOtherAttachments.aspx?id=X — attachments landing
  • LawArticles.aspx?LawTreeSectionID=Y&lawId=X — per-section article pages
  • LocalPdfLaw.aspx?Target=X   — PDF viewer HTML (then locate real PDF url)
  • All actual attachment files (PDF, DOC, XLS, images)

Output layout:
  data/meezan_laws/{law_id}/
    meta.json          — parsed metadata summary
    lawpage.html       — raw LawPage
    lawview.html       — raw LawView
    attachments.html   — raw LawOtherAttachments
    articles/
      {tree_id}.html   — each LawArticles page
    files/
      {name}           — downloaded attachments
    owner.html         — raw LawOwner

Runs with rate limiting (default 0.3s).

Usage:
    python scripts/meezan_downloader.py [--ids 2284,2559,9813]
    python scripts/meezan_downloader.py [--ids-file missing_ids.txt]
    python scripts/meezan_downloader.py [--ids-from-jsonl data/meezan_enum/meezan_index.jsonl]
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
from pathlib import Path

BASE    = "https://www.almeezan.qa"
UA      = "Mozilla/5.0 (meezan-downloader research)"
TIMEOUT = 40
ROOT    = Path(__file__).parent.parent
OUT_DIR = ROOT / "data" / "meezan_laws"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


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


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _save(path: Path, body: bytes) -> int:
    path.write_bytes(body)
    return len(body)


def _find_attachments_in_page(html: str) -> list[dict]:
    """Scan for file attachments (PDF/DOC/XLS/images) linked from the page."""
    atts = []
    # hrefs with file extensions
    for m in re.finditer(
        r'href=["\']([^"\'\s]+?\.(?:pdf|doc|docx|xls|xlsx|zip|rar|png|jpg|jpeg|gif))["\']',
        html,
        re.I,
    ):
        atts.append({"url": m.group(1), "kind": "file"})
    # Special routes
    for m in re.finditer(
        r'href=["\']([^"\'\s]*(?:ShowAttach|GetFile|DownloadFile|/Files/|/Attach/)[^"\'\s]*)["\']',
        html,
    ):
        atts.append({"url": m.group(1), "kind": "file"})
    # Image references
    for m in re.finditer(r'<img[^>]*src=["\']([^"\'\s]+\.(?:png|jpg|jpeg|gif))["\']', html, re.I):
        src = m.group(1)
        # Skip UI icons
        if any(k in src.lower() for k in ("logo", "icon", "flag", "favicon", "mada", "wcag", "loading")):
            continue
        atts.append({"url": src, "kind": "image"})
    return atts


def _extract_tree_ids(html: str) -> list[int]:
    ids = sorted(set(int(m) for m in re.findall(r"LawTreeSectionID=(\d+)", html)))
    return ids


def _extract_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split("|")]
    cand = parts[-1] if parts else ""
    cand = re.sub(r"\s+", " ", cand).strip()
    return cand or None


def download_law(law_id: int, *, sleep: float = 0.3, skip_existing: bool = True) -> dict:
    """Download everything for one law. Returns summary dict."""
    law_dir = OUT_DIR / str(law_id)
    articles_dir = law_dir / "articles"
    files_dir = law_dir / "files"

    # Skip if already fully downloaded (meta.json is the completion marker)
    meta_path = law_dir / "meta.json"
    if skip_existing and meta_path.exists():
        try:
            cached = json.loads(meta_path.read_text(encoding="utf-8"))
            cached["skipped"] = True
            return cached
        except Exception:
            pass  # fall through to re-download

    _ensure_dir(law_dir)
    _ensure_dir(articles_dir)
    _ensure_dir(files_dir)

    summary: dict = {
        "law_id":       law_id,
        "fetched_at":   int(time.time()),
        "urls":         {},
        "file_sizes":   {},
        "hashes":       {},
        "attachments":  [],
        "tree_ids":     [],
        "articles":     [],
        "errors":       [],
    }

    # ── 1. LawPage
    url = f"{BASE}/LawPage.aspx?id={law_id}&language=ar"
    status, body, ctype = _fetch(url)
    if status != 200 or len(body) < 1000:
        summary["errors"].append(f"LawPage {status} bytes={len(body)}")
        return summary
    lawpage_html = body.decode("utf-8", errors="replace")
    summary["urls"]["lawpage"] = url
    summary["file_sizes"]["lawpage"] = _save(law_dir / "lawpage.html", body)
    summary["hashes"]["lawpage"] = _sha256_hex(body)
    summary["title"] = _extract_title(lawpage_html)
    time.sleep(sleep)

    # ── 2. LawView (full-text)
    url = f"{BASE}/LawView.aspx?LawID={law_id}&language=ar"
    status, body, _ = _fetch(url)
    lawview_has_content = False
    if status == 200 and len(body) > 500:
        summary["urls"]["lawview"] = url
        summary["file_sizes"]["lawview"] = _save(law_dir / "lawview.html", body)
        summary["hashes"]["lawview"] = _sha256_hex(body)
        # LawView sometimes returns 200 with an empty shell — detect and
        # force fallback to per-section pages when no article markers
        # appear in the flat HTML.
        text = body.decode("utf-8", errors="replace")
        if re.search(r"(?:المادة|مادة)\s*\(?\s*\d+", text):
            lawview_has_content = True
    else:
        summary["errors"].append(f"LawView {status}")
    summary["lawview_has_content"] = lawview_has_content
    time.sleep(sleep)

    # ── 3. LawOtherAttachments
    url = f"{BASE}/LawOtherAttachments.aspx?id={law_id}&language=ar"
    status, body, _ = _fetch(url)
    if status == 200 and len(body) > 500:
        att_html = body.decode("utf-8", errors="replace")
        summary["urls"]["attachments"] = url
        summary["file_sizes"]["attachments"] = _save(law_dir / "attachments.html", body)
        summary["hashes"]["attachments"] = _sha256_hex(body)
        # Look for actual files referenced
        atts = _find_attachments_in_page(att_html)
        summary["attachments"] = atts
    time.sleep(sleep)

    # ── 4. LawOwner
    url = f"{BASE}/LawOwner.aspx?id={law_id}&language=ar"
    status, body, _ = _fetch(url)
    if status == 200 and len(body) > 500:
        summary["urls"]["owner"] = url
        summary["file_sizes"]["owner"] = _save(law_dir / "owner.html", body)
    time.sleep(sleep)

    # ── 5. Per-section article pages.  Skipped when LawView *has
    # content* (real article markers). For small/cancelled laws,
    # LawView often returns an empty shell — then we MUST fetch per
    # section.
    tree_ids = _extract_tree_ids(lawpage_html)
    summary["tree_ids"] = tree_ids
    if not summary.get("lawview_has_content", False):
        for tid in tree_ids:
            art_url = f"{BASE}/LawArticles.aspx?LawTreeSectionID={tid}&lawId={law_id}&language=ar"
            status, body, _ = _fetch(art_url)
            if status == 200 and len(body) > 500:
                fn = articles_dir / f"{tid}.html"
                _save(fn, body)
                summary["articles"].append({
                    "tree_id": tid,
                    "size":    len(body),
                    "hash":    _sha256_hex(body),
                    "url":     art_url,
                })
            time.sleep(sleep)

    # ── 6. Download each attachment file referenced
    for att in summary["attachments"]:
        att_url = att["url"]
        if not att_url.startswith("http"):
            att_url = urllib.parse.urljoin(BASE + "/", att_url)
        status, body, ctype = _fetch(att_url, timeout=60)
        if status == 200 and len(body) > 0:
            # Derive filename
            name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(att_url).path))
            if not name or len(name) > 120:
                name = f"{_sha256_hex(body)[:12]}.bin"
            target = files_dir / name
            _save(target, body)
            att["local_path"] = str(target.relative_to(ROOT))
            att["size"] = len(body)
            att["hash"] = _sha256_hex(body)
            att["mime"] = ctype
        time.sleep(sleep)

    # ── 7. PDF viewer page (may lead to real PDF)
    url = f"{BASE}/LocalPdfLaw.aspx?Target={law_id}&language=ar"
    status, body, _ = _fetch(url)
    if status == 200 and len(body) > 500:
        summary["urls"]["pdf_viewer"] = url
        _save(law_dir / "pdf_viewer.html", body)
        # scan for real PDF url
        viewer_html = body.decode("utf-8", errors="replace")
        for m in re.finditer(r'href=["\']([^"\'\s]+\.pdf)["\']', viewer_html, re.I):
            pdf_url = m.group(1)
            if not pdf_url.startswith("http"):
                pdf_url = urllib.parse.urljoin(BASE + "/", pdf_url)
            ps, pb, pc = _fetch(pdf_url, timeout=120)
            if ps == 200 and len(pb) > 0 and pc.lower().startswith("application/pdf"):
                pdf_name = os.path.basename(urllib.parse.urlparse(pdf_url).path) or f"law_{law_id}.pdf"
                _save(files_dir / pdf_name, pb)
                summary.setdefault("pdf_files", []).append({
                    "url":  pdf_url,
                    "name": pdf_name,
                    "size": len(pb),
                    "hash": _sha256_hex(pb),
                })

    # ── Write meta.json
    (law_dir / "meta.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="Comma-separated law IDs")
    ap.add_argument("--ids-file", help="File with one ID per line")
    ap.add_argument("--ids-from-jsonl", help="JSONL file with almeezan_id field")
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=0, help="Download at most N ids")
    args = ap.parse_args()

    ids: list[int] = []
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.ids_file:
        ids = [int(l.strip()) for l in open(args.ids_file) if l.strip().isdigit()]
    elif args.ids_from_jsonl:
        with open(args.ids_from_jsonl, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    ids.append(obj["almeezan_id"])
                except Exception:
                    continue
    else:
        print("ERROR: supply --ids or --ids-file or --ids-from-jsonl", file=sys.stderr)
        return 2

    if args.limit:
        ids = ids[: args.limit]
    print(f"Downloading {len(ids)} laws; sleep={args.sleep}s")

    ok = 0
    for i, lid in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}] law {lid} …", flush=True)
        try:
            s = download_law(lid, sleep=args.sleep)
            if not s.get("errors"):
                ok += 1
                print(
                    f"  ok  title={(s.get('title') or '')[:80]}  "
                    f"sections={len(s.get('tree_ids', []))}  "
                    f"attachments={len(s.get('attachments', []))}"
                )
            else:
                print(f"  ERR {s['errors']}")
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")

    print(f"\n=== DONE: {ok}/{len(ids)} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
