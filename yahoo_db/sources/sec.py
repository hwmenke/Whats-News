"""
sources/sec.py - Symbol universe from SEC EDGAR.

  company_tickers.json           ~10k  ticker -> CIK/company name
  company_tickers_exchange.json  ~10k  the same plus the listing exchange

These cover every SEC registrant with a ticker, which includes companies whose
shares have stopped trading but that are still filing — a useful slice of the
delisted universe that the exchange directories have already dropped.
"""

import logging

from ..db import STATUS_UNKNOWN, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE = "sec"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# SEC exchange label -> Yahoo exchange code, best effort.
EXCHANGE_MAP = {
    "Nasdaq": "NMS",
    "NYSE": "NYQ",
    "NYSE American": "ASE",
    "NYSE Arca": "PCX",
    "CBOE": "BTS",
    "OTC": "PNK",
}


def fetch(http) -> list:
    """Return ticker records discovered at the SEC. Never raises: a source that
    is down should not abort the whole universe refresh."""
    records = {}

    try:
        payload = http.get_json(EXCHANGE_URL)
        records.update(_parse_exchange_payload(payload))
        logger.info("sec: %d symbols from company_tickers_exchange.json", len(records))
    except Exception as exc:
        logger.warning("sec: exchange file failed: %s", exc)

    try:
        payload = http.get_json(TICKERS_URL)
        for rec in _parse_tickers_payload(payload):
            records.setdefault(rec["symbol"], rec)
        logger.info("sec: %d symbols after company_tickers.json", len(records))
    except Exception as exc:
        logger.warning("sec: ticker file failed: %s", exc)

    return list(records.values())


def _parse_exchange_payload(payload) -> dict:
    """{"fields": ["cik","name","ticker","exchange"], "data": [[...], …]}"""
    fields = [str(f).lower() for f in payload.get("fields", [])]
    out = {}
    for row in payload.get("data", []):
        item = dict(zip(fields, row))
        symbol = normalize_symbol(item.get("ticker"), us_style=True)
        if not symbol:
            continue
        exchange_name = item.get("exchange") or ""
        out[symbol] = {
            "symbol": symbol,
            "name": item.get("name") or "",
            "quote_type": "EQUITY",
            "exchange": EXCHANGE_MAP.get(exchange_name, ""),
            "exchange_name": exchange_name,
            "status": STATUS_UNKNOWN,
            "source": SOURCE,
        }
    return out


def _parse_tickers_payload(payload) -> list:
    """{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, …}"""
    out = []
    values = payload.values() if isinstance(payload, dict) else payload
    for item in values:
        if not isinstance(item, dict):
            continue
        symbol = normalize_symbol(item.get("ticker"), us_style=True)
        if not symbol:
            continue
        out.append({
            "symbol": symbol,
            "name": item.get("title") or "",
            "quote_type": "EQUITY",
            "status": STATUS_UNKNOWN,
            "source": SOURCE,
        })
    return out
