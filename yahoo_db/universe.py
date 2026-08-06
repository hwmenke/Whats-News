"""
universe.py - Build and refresh the symbol universe.

Every source contributes symbols; the store merges them. Nothing is ever
deleted: a symbol that drops out of the exchange directories stays in the
database and gets marked delisted once its price history goes stale. That is
what makes the universe grow monotonically toward "every ticker there ever
was" as the downloader keeps running.
"""

import logging

from .db import Store
from .http_client import HttpClient
from .sources import (nasdaq, otc, sec, seeds, static_symbols,
                      wikipedia_indices, yahoo_lookup)

logger = logging.getLogger(__name__)


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
            try:
                records = _run_source(name, cfg, http, progress)
            except Exception as exc:
                logger.error("universe: source %s failed: %s", name, exc)
                summary[name] = {"found": 0, "error": str(exc)}
                continue

            result = store.upsert_tickers(records)
            result["found"] = len(records)
            summary[name] = result
            logger.info("universe: %s -> %d found, %d new, %d updated",
                        name, result["found"], result["inserted"], result["updated"])
    finally:
        http.close()

    store.set_meta("last_universe_refresh", ",".join(sources))
    return summary


def _run_source(name: str, cfg, http, progress):
    if name == "sec":
        return sec.fetch(http)
    if name == "nasdaq":
        return nasdaq.fetch(http)
    if name == "otc":
        return otc.fetch(http)
    if name in ("wikipedia", "wiki", "indices"):
        return wikipedia_indices.fetch(http)
    if name == "seeds":
        return seeds.fetch(cfg.seeds_dir)
    if name == "static":
        return static_symbols.fetch()
    if name in ("yahoo-lookup", "yahoo_lookup", "lookup"):
        return yahoo_lookup.fetch(cfg, progress=progress)
    raise ValueError(
        f"unknown source '{name}' (known: sec, nasdaq, otc, wikipedia, seeds, "
        "static, yahoo-lookup)"
    )
