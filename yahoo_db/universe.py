"""
universe.py - Build and refresh the symbol universe.

Every source contributes symbols; the store merges them. Nothing is ever
deleted: a symbol that drops out of the exchange directories stays in the
database and gets marked delisted once its price history goes stale. That is
what makes the universe grow monotonically toward "every ticker there ever
was" as the downloader keeps running.

Most sources are one download and one merge. The Yahoo lookup crawl is an
overnight job instead, so it merges incrementally through a checkpoint and
records every finished (region, type, prefix) triple in `lookup_progress` —
interrupt it and the next run picks up where it stopped. `_Merge` is what lets
both shapes report the same three numbers.
"""

import logging

from .db import Store
from .http_client import HttpClient
from .sources import (nasdaq, otc, sec, seeds, static_symbols,
                      wikipedia_indices, yahoo_lookup)

logger = logging.getLogger(__name__)

LOOKUP_ALIASES = ("yahoo-lookup", "yahoo_lookup", "lookup")


def refresh(cfg, store: Store, sources=None, progress=None) -> dict:
    """Run the requested sources and merge their symbols into `store`.

    Returns {"source": {"found": n, "inserted": n, "updated": n}, …}.
    """
    sources = [s.strip().lower() for s in (sources or cfg.sources)]
    http = HttpClient(
        user_agent=cfg.user_agent,
        timeout=cfg.request_timeout,
        max_retries=cfg.max_retries,
        backoff=cfg.retry_backoff,
    )
    summary = {}

    try:
        for name in sources:
            logger.info("universe: running source %s", name)
            merge = _Merge(store)
            try:
                records = _run_source(name, cfg, http, store, merge, progress)
            except Exception as exc:
                logger.error("universe: source %s failed: %s", name, exc)
                # Whatever a streaming source merged before it failed is
                # already stored, so report that rather than a bare zero.
                summary[name] = dict(merge.totals(), error=str(exc))
                continue

            merge.add(records)      # no-op for a source that already streamed
            summary[name] = merge.totals()
            logger.info("universe: %s -> %d found, %d new, %d updated",
                        name, merge.found, merge.inserted, merge.updated)
    finally:
        http.close()

    store.set_meta("last_universe_refresh", ",".join(sources))
    return summary


class _Merge:
    """Running merge totals for one source.

    A batch source calls `add` once with everything it found; the lookup crawl
    calls it once per finished prefix. Either way the summary line is the same,
    and a crawl that gets interrupted still reports what it actually stored.
    """

    def __init__(self, store: Store):
        self.store = store
        self.found = self.inserted = self.updated = 0

    def add(self, records) -> dict:
        records = list(records or [])
        if not records:
            return {"inserted": 0, "updated": 0}
        result = self.store.upsert_tickers(records)
        self.found += len(records)
        self.inserted += result["inserted"]
        self.updated += result["updated"]
        return result

    def totals(self) -> dict:
        return {"found": self.found, "inserted": self.inserted,
                "updated": self.updated}


def _run_source(name: str, cfg, http, store, merge, progress):
    if name == "sec":
        return sec.fetch(http)
    if name == "nasdaq":
        return nasdaq.fetch(http)
    if name == "otc":
        return otc.fetch(http)
    if name in ("wikipedia", "wiki", "indices"):
        return _run_wikipedia(http, store)
    if name == "seeds":
        return seeds.fetch(cfg.seeds_dir)
    if name == "static":
        return static_symbols.fetch()
    if name in LOOKUP_ALIASES:
        return _run_lookup(cfg, store, merge, progress)
    raise ValueError(
        f"unknown source '{name}' (known: sec, nasdaq, otc, wikipedia, seeds, "
        "static, yahoo-lookup)"
    )


def _run_wikipedia(http, store: Store):
    """Symbols for the universe, and index membership for point-in-time work.

    The changes tables carry the date of every join and departure. Keeping
    those is what lets a backtest ask who was in the index in 2014 rather than
    running today's members over yesterday's prices — the cheapest real defence
    against survivorship bias available here.
    """
    records, membership = wikipedia_indices.fetch_all(http)
    for block in membership:
        index_name = block["index"]
        if block["constituents"]:
            store.replace_index_constituents(index_name, block["constituents"])
        if block["changes"]:
            store.add_index_changes(
                [(index_name, symbol, action, when)
                 for symbol, action, when in block["changes"]])
        logger.info("wikipedia: %s -> %d members, %d dated changes",
                    index_name, len(block["constituents"]), len(block["changes"]))
    return records


def _run_lookup(cfg, store: Store, merge, progress):
    """The resumable crawl: skip finished triples, checkpoint the rest."""
    if cfg.lookup_restart:
        dropped = store.clear_lookup_progress(regions=cfg.lookup_regions,
                                              quote_types=cfg.lookup_types)
        logger.info("yahoo-lookup: --lookup-restart dropped %d checkpoints",
                    dropped)

    resumable = store.count_lookup_prefixes_done(
        cfg.lookup_regions, cfg.lookup_types, cfg.lookup_resume_days)
    if resumable:
        logger.info("yahoo-lookup: resuming — skipping %d prefixes already done "
                    "in the last %d days", resumable, cfg.lookup_resume_days)

    def completed(region, quote_type):
        return store.lookup_prefixes_done(region, quote_type,
                                          cfg.lookup_resume_days)

    def checkpoint(records, region, quote_type, prefix):
        # Order matters: the symbols have to be in the database before the
        # triple is called done, or a crash between the two would lose them
        # for `lookup_resume_days`.
        merge.add(records)
        store.mark_lookup_prefix(region, quote_type, prefix, len(records))

    return yahoo_lookup.fetch(cfg, progress=progress, completed=completed,
                              checkpoint=checkpoint)
