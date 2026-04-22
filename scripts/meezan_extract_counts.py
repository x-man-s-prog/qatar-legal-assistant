# -*- coding: utf-8 -*-
"""Extract per-year law counts from the LawsByYear.aspx VIEWSTATE blob."""
from __future__ import annotations

import base64
import re
import ssl
import sys
import urllib.request

URL_UNFILTERED = "https://www.almeezan.qa/LawsByYear.aspx?year=2024"
URL_FILTERED   = "https://www.almeezan.qa/LawsByYear.aspx?year=2024&status=2445"
URL_CANCELLED  = "https://www.almeezan.qa/CancelledLaws.aspx?status=2443&kind=0&language=ar"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _get_viewstate_bytes(html: str) -> bytes:
    m = re.search(r'id="__VIEWSTATE"\s+value="([^"]+)"', html)
    if not m:
        return b""
    return base64.b64decode(m.group(1))


def _extract_year_counts(vs: bytes) -> dict[int, int]:
    """Parse year→count pairs from the VIEWSTATE binary blob.

    Observed byte pattern:
      year=YYYY&language=ar[\\x1f\\x04\\x05\\x06active]\\x16\\x02f\\x0f\\x15\\x02\\x04YYYY\\x0L<COUNT>d

    where \\x0L is a length-prefix byte for the count string.
    """
    out: dict[int, int] = {}
    pat = re.compile(
        rb"year=(\d{4})&language=ar(?:\x1f\x04\x05\x06active)?\x16\x02f\x0f\x15\x02\x04\1[\x02\x03\x04\x05](\d{1,4})d"
    )
    for year_b, cnt_b in pat.findall(vs):
        year = int(year_b.decode("ascii"))
        cnt  = int(cnt_b.decode("ascii"))
        out[year] = cnt
    return out


def _extract_cancelled_year_counts(vs: bytes) -> dict[int, int]:
    """Parse the CancelledLaws.aspx VIEWSTATE.

    Observed rendered pattern: ``fYYYYYYYYarYYYY<count>dd``
    with unprintable ASP.NET control bytes scattered between.  We
    first strip all bytes < 0x20, then regex on the resulting text.
    """
    # Strip control bytes (< 0x20) then decode as utf-8
    cleaned_bytes = bytes(b for b in vs if b >= 0x20 or b in (0x0A, 0x0D))
    txt = cleaned_bytes.decode("utf-8", errors="replace")
    out: dict[int, int] = {}
    # YYYY YYYY ar YYYY count
    pat = re.compile(r"(\d{4})\1ar\1(\d{1,4})dd")
    for year_s, cnt_s in pat.findall(txt):
        out[int(year_s)] = int(cnt_s)
    # Fallback: simpler `YYYY ar YYYY COUNT`
    if not out:
        pat2 = re.compile(r"(\d{4})ar\1(\d{1,4})dd")
        for year_s, cnt_s in pat2.findall(txt):
            out[int(year_s)] = int(cnt_s)
    return out


def main() -> int:
    print("Fetching UNFILTERED LawsByYear (2024) …", flush=True)
    html = _fetch(URL_UNFILTERED)
    vs = _get_viewstate_bytes(html)
    unfiltered = _extract_year_counts(vs)
    print(f"  extracted {len(unfiltered)} year entries")
    total_u = sum(unfiltered.values())
    print(f"  UNFILTERED total: {total_u}")
    for y in sorted(unfiltered.keys(), reverse=True)[:8]:
        print(f"    {y}: {unfiltered[y]}")

    print("\nFetching FILTERED (status=2445 قيد التطبيق) …", flush=True)
    html_f = _fetch(URL_FILTERED)
    vs_f = _get_viewstate_bytes(html_f)
    filtered = _extract_year_counts(vs_f)
    print(f"  extracted {len(filtered)} year entries")
    total_f = sum(filtered.values())
    print(f"  FILTERED total: {total_f}")
    for y in sorted(filtered.keys(), reverse=True)[:8]:
        print(f"    {y}: {filtered[y]}")

    print("\nFetching CancelledLaws …", flush=True)
    html_c = _fetch(URL_CANCELLED)
    vs_c = _get_viewstate_bytes(html_c)
    cancelled = _extract_cancelled_year_counts(vs_c)
    print(f"  extracted {len(cancelled)} year entries")
    total_c = sum(cancelled.values())
    print(f"  CANCELLED total: {total_c}")
    for y in sorted(cancelled.keys(), reverse=True)[:8]:
        print(f"    {y}: {cancelled[y]}")

    print("\n=== SUMMARY ===")
    print(f"Al-Meezan ALL legislations (LawsByYear):         {total_u:>8,}")
    print(f"Al-Meezan CANCELLED (ملغى / status=2443):        {total_c:>8,}")
    print(f"Al-Meezan IN FORCE = ALL − CANCELLED:            {total_u - total_c:>8,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
