# -*- coding: utf-8 -*-
"""Counts Al-Meezan legislations with status=قيد التطبيق (2445).

Approach:
  1. GET https://www.almeezan.qa/LawsBySubject.aspx
  2. Extract __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION.
  3. POST with ddlStatus=2445 + btnSearch trigger.
  4. Parse results.
"""
from __future__ import annotations

import re
import sys
import ssl
import urllib.request
import urllib.parse
import urllib.error

URL = "https://www.almeezan.qa/LawsBySubject.aspx"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def _fetch(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace")


def _extract_state(html: str) -> dict:
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(rf'id="{name}"\s+value="([^"]*)"', html)
        if m:
            out[name] = m.group(1)
    return out


def main() -> int:
    print("Fetching form page …", flush=True)
    html = _fetch(URL)
    state = _extract_state(html)
    if not state.get("__VIEWSTATE"):
        print("FATAL: no VIEWSTATE found on form page", file=sys.stderr)
        return 1
    print(f"  state keys: {list(state.keys())}")
    print(f"  __VIEWSTATE len: {len(state['__VIEWSTATE'])}")

    # Find button name
    btn_match = re.search(r'<[^>]*name="([^"]*btnSearch[^"]*)"', html, re.I)
    btn_name = btn_match.group(1) if btn_match else "btnSearch"
    print(f"  button: {btn_name}")

    # Try POST with ddlStatus=2445 (قيد التطبيق) + empty other filters
    data = {
        "__VIEWSTATE":          state.get("__VIEWSTATE", ""),
        "__VIEWSTATEGENERATOR": state.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION":    state.get("__EVENTVALIDATION", ""),
        "ddlStatus":            "2445",
        "ddlKind":              "0",   # all types
        btn_name:               "بحث",
    }

    encoded = urllib.parse.urlencode(data).encode("utf-8")
    hdr = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent":   "Mozilla/5.0 meezan-count-script",
        "Accept-Language": "ar",
    }
    print("POSTing with ddlStatus=2445 …", flush=True)
    resp = _fetch(URL, data=encoded, headers=hdr)
    print(f"  response size: {len(resp)}")

    # Count LawPage links in response
    law_ids = set(re.findall(r"LawPage\.aspx\?(?:id|ID)=([0-9]+)", resp, re.I))
    print(f"  unique LawPage ids in response: {len(law_ids)}")

    # Look for any total count label
    totals = re.findall(
        r"(?:إجمالي|عدد|total|count|found)\D*([0-9]{2,6})",
        resp, flags=re.I,
    )
    if totals:
        print(f"  potential totals: {totals[:10]}")

    # Write response for manual inspection
    import os, tempfile
    out_path = os.path.join(tempfile.gettempdir(), "meezan_status_posted.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(resp)
    print(f"  wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
