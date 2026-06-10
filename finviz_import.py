"""
finviz_import.py — Pull tickers from a Finviz screener into the watchlist.

Two access paths, matching how Finviz actually works:

  1. Elite export API (paid): https://elite.finviz.com/export.ashx?...&auth=TOKEN
     returns clean CSV with Ticker/Company/Sector/Industry columns.
  2. Public screener scrape:  https://finviz.com/screener.ashx?v=111&f=...
     parsed from the HTML table (ticker links to quote.ashx).  Finviz rate-limits
     and occasionally blocks datacenter IPs — degrade gracefully.

Only the screener *filters* are taken from a user-supplied URL; requests are
always built against finviz.com / elite.finviz.com (no arbitrary-URL fetch).
"""

import csv
import io
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_ALLOWED_HOSTS = {"finviz.com", "www.finviz.com", "elite.finviz.com"}

# Query params worth carrying over from a pasted screener URL
_KEEP_PARAMS = ("f", "s", "o", "v")

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def filters_from_url(url: str) -> dict:
    """Extract screener parameters from a pasted Finviz URL.

    Raises ValueError if the URL is not a finviz.com screener link.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Not a valid URL")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"Not a finviz.com URL: {parsed.hostname}")
    qs = parse_qs(parsed.query)
    return {k: qs[k][0] for k in _KEEP_PARAMS if k in qs}


def parse_export_csv(text: str) -> list:
    """Parse the Elite export.ashx CSV into [{symbol, name, sector, industry}]."""
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for r in reader:
        sym = (r.get("Ticker") or "").strip().upper()
        if not sym or not _TICKER_RE.match(sym):
            continue
        rows.append({
            "symbol":   sym,
            "name":     (r.get("Company")  or "").strip(),
            "sector":   (r.get("Sector")   or "").strip(),
            "industry": (r.get("Industry") or "").strip(),
        })
    return rows


def parse_screener_html(html: str) -> list:
    """Pull tickers out of the public screener HTML.

    Markup shifts between Finviz revisions, so match the one stable thing:
    anchors linking to quote.ashx?t=<TICKER>.  Order-preserving dedupe.
    """
    seen = set()
    rows = []
    for m in re.finditer(r'href="[^"]*quote\.ashx\?t=([A-Za-z0-9.\-]{1,10})[^"]*"', html):
        sym = m.group(1).upper()
        if sym in seen or not _TICKER_RE.match(sym):
            continue
        seen.add(sym)
        rows.append({"symbol": sym, "name": "", "sector": "", "industry": ""})
    return rows


def fetch_finviz(url: str = None, filters: dict = None, auth: str = None,
                 pages: int = 1, timeout: int = 15, _session=None) -> list:
    """Fetch screener results.  Returns [{symbol, name, sector, industry}].

    url     — pasted finviz screener URL (filters are extracted from it)
    filters — alternative to url: {"f": "...", "s": "...", "v": "111"}
    auth    — Finviz Elite API token; uses the official CSV export when set
    pages   — public scrape only: pages of 20 rows to fetch (max 5)
    """
    import requests
    session = _session or requests.Session()

    params = dict(filters or {})
    if url:
        params.update(filters_from_url(url))
    params.setdefault("v", "111")

    if auth:
        params["auth"] = auth
        resp = session.get("https://elite.finviz.com/export.ashx",
                           params=params, headers={"User-Agent": _UA},
                           timeout=timeout)
        resp.raise_for_status()
        return parse_export_csv(resp.text)

    rows = []
    seen = set()
    pages = max(1, min(int(pages), 5))
    for page in range(pages):
        page_params = dict(params)
        if page:
            page_params["r"] = str(page * 20 + 1)
            time.sleep(1.0)  # be polite to the public site
        resp = session.get("https://finviz.com/screener.ashx",
                           params=page_params, headers={"User-Agent": _UA},
                           timeout=timeout)
        resp.raise_for_status()
        batch = parse_screener_html(resp.text)
        new   = [r for r in batch if r["symbol"] not in seen]
        if not new:
            break
        for r in new:
            seen.add(r["symbol"])
        rows.extend(new)
        if len(batch) < 20:
            break
    return rows
