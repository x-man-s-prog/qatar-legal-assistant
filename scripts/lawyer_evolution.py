# -*- coding: utf-8 -*-
"""
scripts/lawyer_evolution.py
============================
Path A: Learn from internet legal sources
Path B: Build lawyer thinking system (done in prompts.py)
"""
import os, sys, json, re, time, logging
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

BASE = Path(__file__).resolve().parent
OUT = BASE / "learned_knowledge"
OUT.mkdir(parents=True, exist_ok=True)
LOG = BASE / "lawyer_evolution.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.FileHandler(str(LOG), encoding="utf-8", mode="w")])
log = logging.getLogger("evolution")
try:
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except Exception:
    pass


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []; self._skip = False
    def handle_starttag(self, t, a):
        if t in ("script","style","noscript"): self._skip = True
    def handle_endtag(self, t):
        if t in ("script","style","noscript"): self._skip = False
    def handle_data(self, d):
        if not self._skip: self._parts.append(d)
    def text(self): return " ".join(self._parts)


def fetch(url, timeout=15):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        for enc in ("utf-8","windows-1256","iso-8859-6"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8", errors="ignore")


def html_to_text(html):
    p = _TextExtractor(); p.feed(html); return p.text()


def is_qatar_legal(text):
    q = any(m in text for m in ["قطر","القطري","الدوحة","Qatar","Qatari"])
    l = any(m in text for m in ["قانون","مادة","محكمة","تشريع","law","regulation"])
    return q and l


NON_QATAR = ["المصري","الكويتي","الإماراتي","السعودي","البحريني"]

PROC_RE = [
    re.compile(r'(?:الخطوة|الإجراء|أولاً|ثانياً|ثالثاً)[^.]{20,300}\.', re.UNICODE),
    re.compile(r'(?:يجب|يتعين|ينبغي)\s+(?:على\s+)?[^.]{20,300}\.', re.UNICODE),
]
DEADLINE_RE = [re.compile(r'(?:خلال|مدة|أجل|ميعاد|مهلة)\s+\d+\s+(?:يوم|أيام|شهر|أشهر|سنة|سنوات)[^.]{10,200}\.', re.UNICODE)]
UPDATE_RE = [re.compile(r'(?:تعديل|تعدّل|عُدّل|أُضيف|صدر)\s+[^.]*(?:202[3-6])[^.]{10,300}\.', re.UNICODE)]
ADVICE_RE = [re.compile(r'(?:يُنصح|يُوصى|من المهم|تجدر الإشارة|يُفضّل)[^.]{20,300}\.', re.UNICODE)]
INTERP_RE = [re.compile(r'(?:يُقصد\s+بـ|المقصود\s+من|يعني\s+ذلك|بمعنى\s+أن)[^.]{20,300}\.', re.UNICODE)]


def extract(text, source):
    items = []
    for pat in PROC_RE:
        for m in pat.finditer(text):
            t = m.group(0).strip()
            if 20 < len(t) < 400 and not any(n in t for n in NON_QATAR):
                items.append({"type": "procedure", "text": t, "source": source})
    for pat in DEADLINE_RE:
        for m in pat.finditer(text):
            t = m.group(0).strip()
            if 20 < len(t) < 300 and not any(n in t for n in NON_QATAR):
                items.append({"type": "deadline", "text": t, "source": source})
    for pat in UPDATE_RE:
        for m in pat.finditer(text):
            t = m.group(0).strip()
            if 20 < len(t) < 400:
                items.append({"type": "update", "text": t, "source": source})
    for pat in ADVICE_RE:
        for m in pat.finditer(text):
            t = m.group(0).strip()
            if 20 < len(t) < 400 and not any(n in t for n in NON_QATAR):
                items.append({"type": "advice", "text": t, "source": source})
    for pat in INTERP_RE:
        for m in pat.finditer(text):
            t = m.group(0).strip()
            if 20 < len(t) < 400:
                items.append({"type": "interpretation", "text": t, "source": source})
    return items


SEARCH_QUERIES = [
    "شرح قانون العمل القطري إجراءات",
    "شرح قانون العقوبات القطري",
    "إجراءات التقاضي في قطر خطوات",
    "قانون الأسرة القطري شرح",
    "حقوق العمال في قطر 2024",
    "تعديلات القوانين القطرية 2024 2025",
    "Qatar labor law procedures",
    "Qatar legal system guide",
]

DIRECT_URLS = [
    "https://www.tamimi.com/law-update-modules/?country=qatar",
    "https://www.dentons.com/en/insights?region=middle-east&country=qatar",
]


def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    all_items = []

    # Search Google
    for query in SEARCH_QUERIES:
        try:
            url = f"https://www.google.com/search?q={quote_plus(query)}&hl=ar&num=3"
            log.info(f"Searching: {query[:40]}...")
            html = fetch(url, timeout=10)
            urls = re.findall(r'href="(https?://[^"]+)"', html)
            legal_urls = [u for u in urls if any(s in u for s in ["tamimi","dentons","clyde","simmons","law","legal","gov.qa"])][:2]
            for lu in legal_urls:
                try:
                    page = fetch(lu)
                    text = html_to_text(page)
                    if len(text) > 500 and is_qatar_legal(text):
                        items = extract(text, lu[:60])
                        all_items.extend(items)
                        log.info(f"  {len(items)} items from {lu[:50]}")
                    time.sleep(3)
                except Exception as e:
                    log.debug(f"  Skip: {e}")
            time.sleep(3)
        except Exception as e:
            log.warning(f"  Search failed: {e}")

    # Direct URLs
    for url in DIRECT_URLS:
        try:
            html = fetch(url, timeout=10)
            text = html_to_text(html)
            if len(text) > 500:
                items = extract(text, url[:60])
                all_items.extend(items)
                log.info(f"  {len(items)} items from {url[:50]}")
            time.sleep(3)
        except Exception as e:
            log.warning(f"  Direct failed: {e}")

    # Deduplicate
    seen = set(); unique = []
    for item in all_items:
        key = item["text"][:60]
        if key not in seen:
            seen.add(key); unique.append(item)

    # Save by type
    by_type = {}
    for item in unique:
        by_type.setdefault(item["type"], []).append(item)

    for t, items in by_type.items():
        with open(OUT / f"{t}s.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        log.info(f"  {t}: {len(items)} unique items saved")

    # Summary
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_raw": len(all_items),
        "total_unique": len(unique),
        "by_type": {t: len(v) for t, v in by_type.items()},
    }
    with open(OUT / "learning_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log.info(f"DONE: {len(unique)} unique items from {len(all_items)} raw")
    log.info(f"Finished: {datetime.now().isoformat()}")
    return report


if __name__ == "__main__":
    main()
