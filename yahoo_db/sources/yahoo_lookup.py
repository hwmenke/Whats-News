"""
sources/yahoo_lookup.py - Brute-force crawl of Yahoo's own symbol lookup.

The exchange directories only know what trades *today*. Yahoo's lookup index
still answers for symbols that stopped trading years ago, so walking it with
every prefix ("A", "AA", "AB", … "ZZ", "0" … "9") over every quote type is the
one source that reaches deep into the delisted universe.

Endpoint (undocumented, used by finance.yahoo.com itself):

  https://query2.finance.yahoo.com/v1/finance/lookup
      ?query=AA&type=equity&start=0&count=100&formatted=false&region=US

The request needs Yahoo's cookie + crumb handshake, which yfinance already
implements — we borrow its session rather than reimplementing it.
"""

import itertools
import logging
import string
import time

from ..db import STATUS_UNKNOWN, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE = "yahoo-lookup"
LOOKUP_URL = "https://query2.finance.yahoo.com/v1/finance/lookup"
PAGE_SIZE = 100
# Yahoo stops returning useful rows well before a deep offset; past this we
# rely on longer prefixes to reach the rest of the matches instead.
MAX_OFFSET = 1000

ALPHABET = string.ascii_uppercase + string.digits


def generate_queries(depth: int = 2, alphabet: str = ALPHABET) -> list:
    """All prefixes from length 1 up to `depth`: A…Z,0…9, AA…99, …"""
    queries = []
    for length in range(1, max(1, depth) + 1):
        queries.extend("".join(combo) for combo in
                       itertools.product(alphabet, repeat=length))
    return queries


def fetch(cfg, quote_types=None, regions=None, depth=None, sleep=None,
          fetcher=None, progress=None) -> list:
    """Crawl the lookup index and return ticker records.

    `fetcher(params) -> dict` is injectable so the crawl can be tested without
    network access; the default goes through yfinance's authenticated session.
    """
    quote_types = quote_types or cfg.lookup_types
    regions = regions or cfg.lookup_regions
    depth = cfg.lookup_depth if depth is None else depth
    sleep = cfg.lookup_sleep if sleep is None else sleep
    fetcher = fetcher or _default_fetcher(cfg)

    queries = generate_queries(depth)
    total_requests = len(queries) * len(quote_types) * len(regions)
    logger.info(
        "yahoo-lookup: %d prefixes x %d types x %d regions = up to %d requests",
        len(queries), len(quote_types), len(regions), total_requests,
    )

    records = {}
    done = 0
    for region in regions:
        for quote_type in quote_types:
            for query in queries:
                done += 1
                try:
                    found = _crawl_one(fetcher, query, quote_type, region, sleep)
                except KeyboardInterrupt:
                    logger.warning("yahoo-lookup: interrupted, keeping %d symbols",
                                   len(records))
                    return list(records.values())
                except Exception as exc:
                    logger.warning("yahoo-lookup: %s/%s failed: %s",
                                   query, quote_type, exc)
                    continue
                for rec in found:
                    records.setdefault(rec["symbol"], rec)
                if progress and done % 50 == 0:
                    progress(done, total_requests, len(records))
    logger.info("yahoo-lookup: %d symbols discovered", len(records))
    return list(records.values())


def _crawl_one(fetcher, query: str, quote_type: str, region: str, sleep: float) -> list:
    """Page through every match for one (prefix, type, region) triple."""
    out = []
    start = 0
    while start < MAX_OFFSET:
        payload = fetcher({
            "query": query,
            "type": quote_type,
            "start": start,
            "count": PAGE_SIZE,
            "formatted": "false",
            "fetchPricingData": "false",
            "lang": "en-US",
            "region": region,
        })
        documents, total = parse_lookup_payload(payload)
        out.extend(documents)
        start += PAGE_SIZE
        if sleep:
            time.sleep(sleep)
        if len(documents) < PAGE_SIZE or start >= total:
            break
    return out


def parse_lookup_payload(payload):
    """-> (records, total_matches). Tolerates the several response shapes the
    endpoint returns for empty results."""
    if not isinstance(payload, dict):
        return [], 0
    results = (payload.get("finance") or {}).get("result") or []
    if not results:
        return [], 0
    block = results[0] or {}
    total = int(block.get("total") or 0)
    records = []
    for doc in block.get("documents") or []:
        symbol = normalize_symbol(doc.get("symbol"))
        if not symbol:
            continue
        records.append({
            "symbol": symbol,
            "name": doc.get("shortName") or doc.get("longName") or "",
            "quote_type": (doc.get("quoteType") or "").upper(),
            "exchange": doc.get("exchange") or "",
            "exchange_name": doc.get("exchDisp") or "",
            # The lookup index carries live and dead symbols alike and does not
            # distinguish them; the price download decides which is which.
            "status": STATUS_UNKNOWN,
            "source": SOURCE,
        })
    return records, total


def _default_fetcher(cfg):
    """A fetcher backed by yfinance's cookie/crumb-aware session."""
    from yfinance.data import YfData

    data = YfData()

    def fetch_params(params):
        return data.get_raw_json(LOOKUP_URL, params=params, timeout=cfg.request_timeout)

    return fetch_params
