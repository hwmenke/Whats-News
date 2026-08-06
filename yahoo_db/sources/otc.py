"""
sources/otc.py - Securities quoted on the OTC Markets venues.

Around 11–12k securities are quoted on OTCQX / OTCQB / OTCID / Pink at any one
moment, and the churn is brutal: shells, bankrupt issuers, foreign ordinaries
and unsponsored ADRs appear and vanish constantly. Nothing else here reaches
them — the Nasdaq Trader directory covers exchange venues only, and SEC EDGAR
only knows registrants that still file, which most Pink issuers do not. That
makes OTC both the largest block of US-quoted symbols the other sources miss
and the one with the heaviest delisting turnover.

The site's own stock screener is backed by a paged JSON endpoint:

  https://www.otcmarkets.com/research/stock-screener/api?page=1&pageSize=1000

It is undocumented and its field names have moved around over the years, so
nothing below reads a fixed key. The row list is looked for under any container
name the endpoint has used, and symbol/name/tier are picked by trying candidate
keys in turn. A response shape we do not recognise yields zero rows and a
warning, never an exception — same posture as every other source here.
"""

import logging
import re

from ..db import STATUS_ACTIVE, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE = "otc"
SCREENER_URL = "https://www.otcmarkets.com/research/stock-screener/api"

PAGE_SIZE = 1000
# The whole venue is ~12k names; this is headroom, not a target.
MAX_PAGES = 40

# Container keys the screener has served its rows under.
ROW_KEYS = ("stocks", "records", "results", "data", "items", "securities")
SYMBOL_KEYS = ("symbol", "ticker", "securitySymbol", "primarySymbol")
NAME_KEYS = ("securityName", "companyName", "name", "issuerName", "shortName")
TIER_KEYS = ("tierName", "tierCode", "tierDisplayName", "market", "marketName")

# Yahoo files every OTC Markets tier under the Pink Sheets exchange code, which
# is what `sec.py` already maps its own "OTC" label to.
EXCHANGE = "PNK"

# OTC tickers are 1–5 letters plus an optional qualifier character.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,6}$")


def fetch(http, page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES) -> list:
    """Return the OTC-quoted securities. Never raises."""
    records = {}

    for page in range(1, max_pages + 1):
        try:
            payload = http.get_json(SCREENER_URL,
                                    params={"page": page, "pageSize": page_size})
        except Exception as exc:
            logger.warning("otc: page %d failed: %s", page, exc)
            break

        rows = extract_rows(payload)
        if not rows:
            if page == 1:
                logger.warning("otc: no rows in the screener response — the "
                               "endpoint shape has probably changed")
            break

        before = len(records)
        for rec in parse_records(rows):
            records.setdefault(rec["symbol"], rec)
        logger.info("otc: %d symbols after page %d", len(records), page)

        # An endpoint that quietly ignores `page` serves the same slab forever,
        # so stop as soon as a page stops teaching us anything.
        if len(rows) < page_size or len(records) == before:
            break

    return list(records.values())


def extract_rows(payload) -> list:
    """Find the list of security dicts inside whatever wrapper came back."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ROW_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        # One nesting level deep, e.g. {"data": {"records": [...]}}.
        if isinstance(value, dict):
            nested = extract_rows(value)
            if nested:
                return nested
    return []


def parse_records(rows) -> list:
    """Screener rows -> ticker records, dropping anything that is not a symbol."""
    out = []
    for row in rows:
        symbol = _clean_symbol(_pick(row, SYMBOL_KEYS))
        if not symbol:
            continue
        tier = _pick(row, TIER_KEYS)
        out.append({
            "symbol": symbol,
            "name": _pick(row, NAME_KEYS),
            "quote_type": "EQUITY",
            "exchange": EXCHANGE,
            "exchange_name": tier or "OTC Markets",
            "status": STATUS_ACTIVE,
            "source": SOURCE,
        })
    return out


def _pick(row: dict, keys) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _clean_symbol(raw: str) -> str:
    # US venue, so a dotted tail is a share class rather than a market suffix.
    symbol = normalize_symbol(raw, us_style=True)
    if not symbol:
        return ""
    # A dash means normalize_symbol already split a share class off; check the
    # stem so ABCD-A survives while a stray sentence does not.
    stem = symbol.split("-")[0]
    return symbol if _SYMBOL_RE.match(stem) else ""
