# -*- coding: utf-8 -*-
"""Parse downloaded Al-Meezan law HTML into structured records.

Reads: data/meezan_laws/{law_id}/{lawview.html, articles/*.html, ...}
Writes: data/meezan_laws/{law_id}/parsed.json

Structure:
{
  "law":     { ... laws_v2 columns ... },
  "articles": [ { ... articles_v2 columns ... }, ... ],
  "attachments": [ ... ],
  "relationships_detected": [ ... ]
}
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import os
import re
import sys
from pathlib import Path

ROOT   = Path(__file__).parent.parent
LAW_DIR = ROOT / "data" / "meezan_laws"


# ── Helpers ──────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(h: str) -> str:
    """Strip HTML tags, decode entities, normalize whitespace."""
    t = _TAG_RE.sub("\n", h)
    t = html_mod.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n+", "\n", t)
    return t.strip()


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _extract_title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split("|")]
    cand = parts[-1] if parts else ""
    return re.sub(r"\s+", " ", cand).strip() or None


# Ordered law type list — match longer, more specific types FIRST
# so "قرار وزير التجارة والصناعة" wins over generic "قرار".
_LAW_TYPES_ORDERED = (
    "قرار رئيس مجلس الوزراء",
    "قرار مجلس الوزراء",
    "قرار مجلس إدارة",
    "قرار مجلس أعلى",
    "قرار رئيس مجلس أعلى",
    "قرار رئيس مجلس ادارة",
    "قرار النائب العام",
    "قرار وزير التجارة والصناعة",
    "قرار وزير العدل",
    "قرار وزير الداخلية",
    "قرار وزير المالية",
    "قرار وزير الصحة",
    "قرار وزير التربية والتعليم",
    "قرار وزاري",
    "قرار أميري",
    "قرار",
    "أمر أميري",
    "مرسوم بقانون",
    "مرسوم",
    "قانون",
    "دستور",
    "نظام أساسي",
    "وثيقة",
    "إعلان",
)


def _parse_title(title: str) -> dict:
    """Extract law_type, number, year from a title.

    Strategy:
      1. Find the FIRST occurrence of any law type at the BEGINNING of
         the title (within first 50 chars) — that's the primary type.
      2. Find the FIRST "رقم (X) لسنة YYYY" pattern AFTER that type —
         that's the law's own number/year. Later matches are
         references to OTHER laws and must be ignored.
      3. Handle دستور / نظام أساسي as special cases.
    """
    out = {"law_type": None, "law_number": None, "law_year": None}
    if not title:
        return out

    head = title[:80]
    # Find primary type
    primary_type = None
    type_pos = None
    for t in _LAW_TYPES_ORDERED:
        idx = head.find(t)
        if idx >= 0 and idx <= 10:  # must start at the very beginning
            primary_type = t
            type_pos = idx + len(t)
            break
    if not primary_type:
        # Fallback: search anywhere in first 80 chars
        for t in _LAW_TYPES_ORDERED:
            idx = head.find(t)
            if idx >= 0:
                primary_type = t
                type_pos = idx + len(t)
                break

    # Special-case constitution / basic system
    if primary_type in ("دستور", "نظام أساسي"):
        out["law_type"] = primary_type
        yr = re.search(r"(\d{4})", title)
        if yr:
            out["law_year"] = int(yr.group(1))
        return out

    if primary_type:
        out["law_type"] = primary_type
        # Search for "رقم (X) لسنة YYYY" starting AFTER the type
        tail = title[type_pos:]
        nm = re.search(r"رقم\s*\(\s*(\d+)\s*\)\s*لسنة\s*(\d{4})", tail)
        if nm:
            out["law_number"] = nm.group(1)
            out["law_year"]   = int(nm.group(2))

    return out


def _detect_status(html: str) -> str:
    if re.search(r"التشريع\s+ملغى|قانون\s+ملغى|مرسوم\s+ملغى|قرار\s+ملغى", html):
        return "canceled"
    if re.search(r"قيد\s+التطبيق", html):
        return "in_force"
    if re.search(r"ملغى", html):
        return "canceled"
    return "unknown"


def _parse_articles_from_lawview(lawview_html: str) -> list[dict]:
    """Parse a flat LawView.aspx HTML into article records."""
    # The LawView page has a flat structure with headers like
    #   المادة (N) followed by the article text.
    # We split by the "المادة" marker and capture text up to the next one.
    # Strip HTML first but preserve newlines around 'المادة'.
    txt = _strip_html(lawview_html)
    articles: list[dict] = []
    # Tokenize by article markers
    pat = re.compile(
        r"\b(?:المادة|مادة)\s*\(?\s*(\d+(?:\s*مكرر\w*)?)\s*\)?\s*:?\s*",
        re.UNICODE,
    )
    matches = list(pat.finditer(txt))
    for i, m in enumerate(matches):
        start = m.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(txt)
        body  = txt[start:end].strip()
        if not body or len(body) < 5:
            continue
        num_raw = m.group(1)
        num_int = None
        num_m = re.match(r"(\d+)", num_raw)
        if num_m:
            num_int = int(num_m.group(1))
        articles.append({
            "article_number":     f"المادة ({num_raw})",
            "article_number_int": num_int,
            "text":               body,
            "position":           i + 1,
            "content_hash":       _sha256_hex(body),
        })
    return articles


def _parse_article_from_page(article_html: str) -> dict:
    """Parse a LawArticles.aspx HTML — typically one section with 1..N articles."""
    txt = _strip_html(article_html)
    # The page has a header with section name + articles below
    header_m = re.search(r"(الباب|الفصل|القسم|الكتاب)\s+([^\n]{2,120})", txt)
    header = header_m.group(0).strip() if header_m else None
    # Capture article bodies (same as LawView)
    pat = re.compile(
        r"\b(?:المادة|مادة)\s*\(?\s*(\d+(?:\s*مكرر\w*)?)\s*\)?\s*:?\s*"
    )
    sections = list(pat.finditer(txt))
    inner = []
    for i, m in enumerate(sections):
        start = m.end()
        end   = sections[i + 1].start() if i + 1 < len(sections) else len(txt)
        body  = txt[start:end].strip()
        if not body:
            continue
        inner.append({
            "article_number":     f"المادة ({m.group(1)})",
            "article_number_int": int(re.match(r"\d+", m.group(1)).group(0)) if re.match(r"\d+", m.group(1)) else None,
            "text":               body,
            "content_hash":       _sha256_hex(body),
        })
    return {"header": header, "articles": inner}


_REF_RE = re.compile(
    r"(?:القانون|قانون|المرسوم|مرسوم|القرار|قرار)\s*(?:الأميري\s+|الوزاري\s+|بقانون\s+|رقم\s+)?\(?\s*(\d+)\s*\)?\s*لسنة\s*(\d{4})",
    re.UNICODE,
)


def _detect_law_references(text: str) -> list[dict]:
    """Scan text for cross-law references (e.g. 'القانون رقم 9 لسنة 1987')."""
    seen = set()
    out = []
    for m in _REF_RE.finditer(text):
        key = (m.group(1), m.group(2))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "law_number": m.group(1),
            "law_year":   int(m.group(2)),
            "span":       [m.start(), m.end()],
            "context":    text[max(0, m.start() - 30): m.end() + 30].strip(),
        })
    return out


def parse_law(law_id: int) -> dict:
    law_dir = LAW_DIR / str(law_id)
    if not (law_dir / "lawpage.html").exists():
        return {"error": f"lawpage.html not found for {law_id}"}

    lawpage = (law_dir / "lawpage.html").read_text(encoding="utf-8", errors="replace")
    title   = _extract_title(lawpage)
    parsed_title = _parse_title(title or "")
    status  = _detect_status(lawpage)

    # Issue date
    issue_date = None
    dm = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", lawpage)
    if dm and 1950 <= int(dm.group(3)) <= 2030:
        issue_date = f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}"

    # Subject
    subject = None
    bc = re.search(
        r'<a[^>]*href="LawsBySubject\.aspx\?entry=(\d+)[^"]*"[^>]*>([^<]+)</a>',
        lawpage,
    )
    if bc:
        subject = {"entry_id": int(bc.group(1)), "name": bc.group(2).strip()}

    # Articles — prefer LawView (flat)
    articles: list[dict] = []
    lv_path = law_dir / "lawview.html"
    if lv_path.exists():
        lv_html = lv_path.read_text(encoding="utf-8", errors="replace")
        articles = _parse_articles_from_lawview(lv_html)

    # Else parse from per-section files
    if not articles:
        arts_dir = law_dir / "articles"
        if arts_dir.exists():
            for f in sorted(arts_dir.glob("*.html")):
                try:
                    h = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                section = _parse_article_from_page(h)
                tree_id = int(f.stem)
                for a in section["articles"]:
                    a["almeezan_tree_id"] = tree_id
                    a["parent_hierarchy"] = section.get("header")
                    articles.append(a)

    # Detect references
    refs_per_article = []
    for a in articles:
        refs = _detect_law_references(a["text"])
        if refs:
            a["referenced_laws"] = refs
            refs_per_article.extend(refs)

    # Summary
    full_text = "\n\n".join(a["text"] for a in articles)
    content_hash = _sha256_hex(full_text) if full_text else None

    # Attachments
    attachments = []
    meta_path = law_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            attachments = meta.get("attachments", [])
        except Exception:
            pass

    record = {
        "law": {
            "almeezan_id":   law_id,
            "law_type":      parsed_title.get("law_type"),
            "law_number":    parsed_title.get("law_number"),
            "law_year":      parsed_title.get("law_year"),
            "law_name":      title,
            "status":        status,
            "issue_date":    issue_date,
            "subject":       subject,
            "source_url":    f"https://www.almeezan.qa/LawPage.aspx?id={law_id}&language=ar",
            "fulltext_url":  f"https://www.almeezan.qa/LawView.aspx?LawID={law_id}&language=ar",
            "content_hash":  content_hash,
            "source":        "almeezan",
        },
        "articles":    articles,
        "attachments": attachments,
        "all_references": refs_per_article,
    }
    (law_dir / "parsed.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="Comma-separated law IDs")
    ap.add_argument("--all-downloaded", action="store_true",
                    help="Parse every law directory under data/meezan_laws/")
    args = ap.parse_args()

    ids: list[int] = []
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.all_downloaded:
        for d in LAW_DIR.iterdir():
            if d.is_dir() and d.name.isdigit():
                ids.append(int(d.name))
        ids.sort()
    else:
        print("ERROR: supply --ids or --all-downloaded", file=sys.stderr)
        return 2

    ok = 0
    for lid in ids:
        r = parse_law(lid)
        if "error" in r:
            print(f"[{lid}] {r['error']}")
        else:
            ok += 1
            n_arts = len(r["articles"])
            title = r["law"].get("law_name") or ""
            print(f"[{lid}] {n_arts} articles — {title[:80]}")
    print(f"\n=== parsed {ok}/{len(ids)} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
