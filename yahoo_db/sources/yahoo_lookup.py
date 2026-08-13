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

A deep crawl is tens of thousands of requests, so it is resumable: the caller
supplies hooks that say which (region, type, prefix) triples are already done
and record each one as it finishes. See `fetch`.
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
          fetcher=None, progress=None, completed=None, checkpoint=None) -> list:
    """Crawl the lookup index and return ticker records.

    `fetcher(params) -> dict` is injectable so the crawl can be tested without
    network access; the default goes through yfinance's authenticated session.

    Two optional hooks make an overnight crawl resumable, and they only work as
    a pair:

      * `completed(region, quote_type) -> set of prefixes` names the triples an
        earlier run already finished; those are skipped.
      * `checkpoint(records, region, quote_type, prefix)` runs once a triple has
        been paginated to the end. It must store the records *before* recording
        the triple as done, so an interrupt can only ever cost a re-crawl and
        never a symbol.

    Without the hooks the crawl behaves as it always has: every record is held
    in memory and returned at the end.
    """
    quote_types = quote_types or cfg.lookup_types
    regions = regions or cfg.lookup_regions
    depth = cfg.lookup_depth if depth is None else depth
    sleep = cfg.lookup_sleep if sleep is None else sleep
    fetcher = fetcher or _default_fetcher(cfg)

    queries = generate_queries(depth)
    total_triples = len(queries) * len(quote_types) * len(regions)
    logger.info(
        "yahoo-lookup: %d prefixes x %d types x %d regions = up to %d requests",
        len(queries), len(quote_types), len(regions), total_triples,
    )

    records = {}        # only fills up when nothing is checkpointing
    seen = set()        # symbols already emitted this run, across every triple
    done = skipped = crawled = failed = 0
    for region in regions:
        for quote_type in quote_types:
            already = completed(region, quote_type) if completed else frozenset()
            pending = [q for q in queries if q not in already]
            if len(pending) < len(queries):
                logger.info("yahoo-lookup: %s/%s resuming — skipping %d of %d "
                            "prefixes already done", region, quote_type,
                            len(queries) - len(pending), len(queries))
            skipped += len(queries) - len(pending)
            done += len(queries) - len(pending)

            for query in pending:
                done += 1
                crawled += 1
                try:
                    found = _crawl_one(fetcher, query, quote_type, region, sleep)
                    fresh = _unseen(found, seen)
                    if checkpoint:
                        checkpoint(list(fresh.values()), region, quote_type, query)
                    else:
                        records.update(fresh)
                    # Only now is the triple accounted for — a failure above
                    # leaves it unrecorded, so the next run crawls it again.
                    seen.update(fresh)
                except KeyboardInterrupt:
                    logger.warning(
                        "yahoo-lookup: interrupted after %d prefixes, %d symbols "
                        "kept — re-run to resume", done - 1, len(seen))
                    return list(records.values())
                except Exception as exc:
                    failed += 1
                    logger.warning("yahoo-lookup: %s/%s failed: %s",
                                   query, quote_type, exc)
                    continue
                # Counted on requests actually made, not on `done` — a resume
                # jumps `done` forward in blocks and would step over the tick.
                if progress and crawled % 50 == 0:
                    progress(done, total_triples, len(seen), skipped)
    if progress:
        progress(done, total_triples, len(seen), skipped)
    logger.info("yahoo-lookup: %d symbols discovered (%d prefixes skipped as "
                "already done, %d failed)", len(seen), skipped, failed)
    # A failed prefix silently costs up to a thousand symbols, and a crawl
    # that lost half its prefixes to throttling otherwise looks identical to a
    # clean one — you would not find out until the symbols were missing months
    # later. Failed triples are not checkpointed, so a re-run picks them up.
    if failed:
        share = failed / max(1, crawled)
        log = logger.error if share > 0.1 else logger.warning
        log("yahoo-lookup: %d of %d attempted prefixes failed (%.0f%%) — "
            "re-run to retry them; they were not checkpointed",
            failed, crawled, share * 100)
    return list(records.values())


def _unseen(found, seen) -> dict:
    """{symbol: record} for the records of one triple that this run has not
    emitted yet — the lookup index repeats a symbol under every prefix of it."""
    fresh = {}
    for rec in found:
        if rec["symbol"] not in seen:
            fresh.setdefault(rec["symbol"], rec)
    return fresh


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
