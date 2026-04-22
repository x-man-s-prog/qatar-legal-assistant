# -*- coding: utf-8 -*-
"""Al-Meezan legislations counter v2 — try AllLegislationsSearch with ddlStatus pivot."""
from __future__ import annotations

import os
import re
import ssl
import sys
import tempfile
import urllib.request
import urllib.parse


URLS = [
    "https://www.almeezan.qa/AllLegislationsSearch.aspx",
    "https://www.almeezan.qa/LawsBySubject.aspx",
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def _fetch(url: str, data: bytes | None = None, cookies: str = "") -> tuple[str, str]:
    hdr = {
        "User-Agent":      "Mozilla/5.0",
        "Accept-Language": "ar",
    }
    if cookies:
        hdr["Cookie"] = cookies
    if data:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdr)
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=60)
        body = resp.read().decode("utf-8", errors="replace")
        cookies_hdr = "; ".join(
            c.split(";")[0] for c in resp.headers.get_all("Set-Cookie") or []
        )
        return body, cookies_hdr
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace"), ""


def _extract_state(html: str) -> dict:
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(rf'id="{name}"\s+value="([^"]*)"', html)
        if m:
            out[name] = m.group(1)
    return out


def _find_fields(html: str) -> list[str]:
    return sorted(set(re.findall(r"ctl00\$ContentPlaceHolder1\$[A-Za-z0-9_]+", html)))


def _find_status_options(html: str) -> list[tuple[str, str]]:
    """Return [(value, label), ...] where label contains 'قيد' or 'ملغ'."""
    opts = re.findall(
        r'<option value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>',
        html,
    )
    return [(v, lbl) for v, lbl in opts if "قيد" in lbl or "ملغ" in lbl or "الساري" in lbl]


def analyze_url(url: str) -> None:
    print(f"\n=== {url} ===", flush=True)
    html, cookies = _fetch(url)
    print(f"  size: {len(html)}")
    state = _extract_state(html)
    print(f"  state keys: {list(state.keys())}")
    fields = _find_fields(html)
    print(f"  total ctl00 fields: {len(fields)}")
    for f in fields[:25]:
        print(f"    {f}")
    opts = _find_status_options(html)
    print(f"  status-like options: {opts}")
    law_ids = set(re.findall(r"LawPage\.aspx\?(?:id|ID)=([0-9]+)", html, re.I))
    print(f"  LawPage ids (unfiltered GET): {len(law_ids)}")

    if state.get("__VIEWSTATE") and opts:
        # Post with the found status value(s)
        for val, lbl in opts:
            if "قيد" in lbl:
                status_val = val
                status_label = lbl
                break
        else:
            return

        print(f"\n  POSTing with status={status_val} ({status_label}) …")
        # Use AndOrValue, SubjectsID, YearsID — from form
        btn_name = next(
            (f for f in fields if "btnsearch" in f.lower() or "btnSearch" in f),
            "ctl00$ContentPlaceHolder1$btnsearch",
        )
        ddl_status = next(
            (f for f in fields if "ddlstatus" in f.lower() or "status" in f.lower()),
            None,
        )
        if not ddl_status:
            print("  no ddlStatus field found; skip POST")
            return

        data = {
            "__VIEWSTATE":          state.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": state.get("__VIEWSTATEGENERATOR", ""),
            "__EVENTVALIDATION":    state.get("__EVENTVALIDATION", ""),
            ddl_status:             status_val,
            btn_name:               "بحث",
        }
        body = urllib.parse.urlencode(data).encode("utf-8")
        resp, _ = _fetch(url, data=body, cookies=cookies)
        print(f"  response size: {len(resp)}")

        law_ids = set(re.findall(r"LawPage\.aspx\?(?:id|ID)=([0-9]+)", resp, re.I))
        print(f"  filtered LawPage ids: {len(law_ids)}")
        # Look for explicit total
        totals = re.findall(
            r"(?:إجمالي|عدد|مجموع|found|total|results?)\D{0,10}([0-9]{2,6})",
            resp, flags=re.I,
        )
        if totals:
            print(f"  potential totals: {totals[:10]}")

        out_path = os.path.join(tempfile.gettempdir(), f"meezan_{url.rstrip('.aspx').split('/')[-1]}_posted.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(resp)
        print(f"  wrote {out_path}")


def main() -> int:
    for u in URLS:
        analyze_url(u)
    return 0


if __name__ == "__main__":
    sys.exit(main())
