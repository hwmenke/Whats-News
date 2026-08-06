"""
downloader.py - Pull price history from Yahoo and write it into the store.

Design notes
  * Symbols are downloaded in batches (one yf.download call per batch, with
    yfinance's own thread pool inside it) — an order of magnitude fewer HTTP
    round trips than one call per symbol.
  * Batches are grouped by start date: symbols with nothing stored get full
    history, symbols already in the database get only the missing tail plus a
    few days of overlap so split/dividend re-adjustments land.
  * Every attempt is written to fetch_log, so an interrupted run resumes
    exactly where it stopped instead of starting over.
  * A symbol that comes back empty is retried once on its own to tell a real
    delisting apart from a batch hiccup.
"""

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from .db import STATUS_ACTIVE, STATUS_DELISTED, Store, normalize_symbol

logger = logging.getLogger(__name__)

# Phrases Yahoo/yfinance use when a symbol has no data at all any more.
DELISTED_HINTS = ("delisted", "no data found", "no price data found",
                  "symbol may be delisted")
RATE_LIMIT_HINTS = ("too many requests", "rate limit", "429")


class Downloader:
    def __init__(self, cfg, store: Store):
        self.cfg = cfg
        self.store = store
        self.stats = defaultdict(int)

    # ── public API ─────────────────────────────────────────────────────────────

    def run(self, symbols=None, interval: str = None, limit: int = None,
            include_delisted: bool = True, quote_types=None,
            single_retry: bool = True, force: bool = False,
            progress=None) -> dict:
        """Download every due symbol. Returns a summary dict."""
        interval = interval or self.cfg.interval
        if symbols is None:
            symbols = self.store.symbols_to_fetch(
                interval=interval,
                limit=limit,
                refresh_after_hours=self.cfg.refresh_after_hours,
                include_delisted=include_delisted,
                quote_types=quote_types,
                max_failure_backoff_days=self.cfg.max_failure_backoff_days,
                force=force,
            )
        else:
            symbols = [normalize_symbol(s) for s in symbols if normalize_symbol(s)]
            if limit:
                symbols = symbols[:limit]

        if not symbols:
            logger.info("downloader: nothing due for interval %s", interval)
            return dict(self.stats, symbols=0)

        logger.info("downloader: %d symbols due (interval=%s, batch=%d)",
                    len(symbols), interval, self.cfg.batch_size)

        groups = self._group_by_start(symbols, interval)
        processed = 0
        for start, group_symbols in groups.items():
            for batch in _chunks(group_symbols, self.cfg.batch_size):
                try:
                    self._process_batch(batch, interval, start, single_retry)
                except KeyboardInterrupt:
                    logger.warning("downloader: interrupted after %d symbols", processed)
                    return dict(self.stats, symbols=processed, interrupted=True)
                processed += len(batch)
                if progress:
                    progress(processed, len(symbols), dict(self.stats))
                if self.cfg.sleep_between_batches:
                    time.sleep(self.cfg.sleep_between_batches)

        swept = self.store.mark_stale_as_delisted(interval, self.cfg.stale_days)
        self.stats["marked_delisted_stale"] += swept
        return dict(self.stats, symbols=processed)

    def fetch_profiles(self, symbols=None, limit: int = None,
                       refetch_days: int = 30, progress=None) -> dict:
        """Store company/fund metadata (sector, currency, market cap, …).

        One HTTP call per symbol, so this is deliberately separate from the
        price download — run it on the slice you care about.
        """
        if symbols is None:
            symbols = self._profiles_due(limit=limit, refetch_days=refetch_days)
        else:
            symbols = [normalize_symbol(s) for s in symbols if normalize_symbol(s)]
            if limit:
                symbols = symbols[:limit]

        done = 0
        for symbol in symbols:
            try:
                info = yf.Ticker(symbol).info or {}
                if info:
                    self.store.upsert_profile(symbol, info)
                    self.stats["profiles_ok"] += 1
                else:
                    self.stats["profiles_empty"] += 1
            except KeyboardInterrupt:
                logger.warning("profiles: interrupted after %d symbols", done)
                break
            except Exception as exc:
                logger.debug("profiles: %s failed: %s", symbol, exc)
                self.stats["profiles_error"] += 1
            done += 1
            if progress and done % 25 == 0:
                progress(done, len(symbols), dict(self.stats))
            if self.cfg.sleep_between_batches:
                time.sleep(self.cfg.sleep_between_batches)
        return dict(self.stats, symbols=done)

    # ── batching ───────────────────────────────────────────────────────────────

    def _group_by_start(self, symbols, interval: str) -> dict:
        """Map start-date -> symbols. `None` means "download full history"."""
        last_dates = self.store.last_price_dates(symbols, interval)
        overlap = timedelta(days=self.cfg.incremental_overlap_days)
        today = date.today()
        groups = defaultdict(list)

        for symbol in symbols:
            last = last_dates.get(symbol)
            if not last:
                groups[None].append(symbol)
                continue
            try:
                start = date.fromisoformat(last) - overlap
            except ValueError:
                groups[None].append(symbol)
                continue
            if start > today:
                start = today
            groups[start.isoformat()].append(symbol)
        return groups

    def _process_batch(self, batch, interval: str, start, single_retry: bool):
        frame = self._download(batch, interval, start)
        if frame is None:
            return      # the batch failed outright and already logged an error
        empty = []

        for symbol in batch:
            sub = _slice_symbol(frame, symbol, len(batch))
            if sub is None or sub.empty:
                empty.append(symbol)
                continue
            self._store_symbol(symbol, interval, sub)

        if not empty:
            return

        if single_retry:
            for symbol in empty:
                self._retry_single(symbol, interval, start)
        else:
            self.store.log_fetches([
                {"symbol": s, "interval": interval, "status": "empty",
                 "rows": 0, "error": "no rows in batch response"} for s in empty
            ])
            self.stats["empty"] += len(empty)

    def _download(self, batch, interval: str, start):
        """One yf.download call, with backoff on rate limits."""
        kwargs = dict(
            tickers=list(batch),
            interval=interval,
            group_by="ticker",
            auto_adjust=False,   # keep Close and Adj Close as separate columns
            actions=True,        # dividends + splits in the same response
            threads=self.cfg.workers,
            progress=False,
            timeout=self.cfg.request_timeout,
            ignore_tz=True,
        )
        if start:
            kwargs["start"] = start
        elif self.cfg.history_start and self.cfg.history_start != "max":
            kwargs["start"] = self.cfg.history_start
        else:
            kwargs["period"] = "max"

        delay = self.cfg.retry_backoff
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                return yf.download(**kwargs)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                message = str(exc).lower()
                rate_limited = any(h in message for h in RATE_LIMIT_HINTS)
                if attempt >= self.cfg.max_retries:
                    logger.error("downloader: batch failed permanently: %s", exc)
                    self.store.log_fetches([
                        {"symbol": s, "interval": interval, "status": "error",
                         "rows": 0, "error": str(exc)} for s in batch
                    ])
                    self.stats["error"] += len(batch)
                    return None
                wait = delay * (4 if rate_limited else 1)
                logger.warning("downloader: batch attempt %d failed (%s); retry in %.0fs",
                               attempt, exc, wait)
                time.sleep(wait)
                delay *= 2
        return None

    def _retry_single(self, symbol: str, interval: str, start):
        """Second chance on its own — distinguishes 'dead' from 'batch glitch'."""
        try:
            ticker = yf.Ticker(symbol)
            kwargs = dict(interval=interval, auto_adjust=False, actions=True,
                          timeout=self.cfg.request_timeout)
            if start:
                kwargs["start"] = start
            else:
                kwargs["period"] = "max"
            frame = ticker.history(**kwargs)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            message = str(exc).lower()
            self.store.log_fetch(symbol, interval, "error", error=str(exc))
            self.stats["error"] += 1
            if any(hint in message for hint in DELISTED_HINTS):
                self.store.mark_status(symbol, STATUS_DELISTED, notes=str(exc)[:200])
                self.stats["marked_delisted"] += 1
            return

        if frame is None or frame.empty:
            self.store.log_fetch(symbol, interval, "empty", error="no data returned")
            self.stats["empty"] += 1
            # No history at all and none stored: nothing to trade, ever.
            if not self.store.last_price_date(symbol, interval):
                self.store.mark_status(symbol, STATUS_DELISTED,
                                       notes="no history returned by Yahoo")
                self.stats["marked_delisted"] += 1
            return

        self._store_symbol(symbol, interval, frame)

    def _store_symbol(self, symbol: str, interval: str, frame: pd.DataFrame):
        rows = self.store.upsert_prices(symbol, interval, frame)
        actions = self._store_actions(symbol, frame)
        first_date, last_date = _date_range(frame)

        if rows:
            self.store.mark_has_data(symbol, last_date)
            current = self.store.conn.execute(
                "SELECT status FROM tickers WHERE symbol=?", (symbol,)
            ).fetchone()
            if current and current["status"] != STATUS_DELISTED:
                self.store.mark_status(symbol, STATUS_ACTIVE)

        self.store.log_fetch(symbol, interval, "ok" if rows else "empty",
                             rows=rows, first_date=first_date, last_date=last_date)
        self.stats["ok" if rows else "empty"] += 1
        self.stats["rows"] += rows
        self.stats["dividends"] += actions.get("dividends", 0)
        self.stats["splits"] += actions.get("splits", 0)

    def _store_actions(self, symbol: str, frame: pd.DataFrame) -> dict:
        columns = {str(c).strip().lower(): c for c in frame.columns}
        dividends = frame[columns["dividends"]] if "dividends" in columns else None
        splits = frame[columns["stock splits"]] if "stock splits" in columns else None
        if dividends is None and splits is None:
            return {}
        return self.store.upsert_actions(symbol, dividends=dividends, splits=splits)

    def _profiles_due(self, limit: int = None, refetch_days: int = 30) -> list:
        cutoff = (datetime.utcnow() - timedelta(days=refetch_days)).isoformat()
        sql = """
            SELECT t.symbol
            FROM tickers t
            LEFT JOIN profiles p ON p.symbol = t.symbol
            WHERE t.has_data = 1
              AND (p.symbol IS NULL OR p.fetched_at < ?)
            ORDER BY t.status = 'active' DESC, t.symbol
        """
        params = [cutoff]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [r["symbol"] for r in self.store.conn.execute(sql, params).fetchall()]


# ── frame helpers ──────────────────────────────────────────────────────────────

def _slice_symbol(frame, symbol: str, batch_size: int):
    """Pull one symbol's columns out of a grouped yf.download result."""
    if frame is None or len(frame) == 0:
        return None
    columns = frame.columns
    if getattr(columns, "nlevels", 1) > 1:
        level0 = set(columns.get_level_values(0))
        if symbol in level0:
            return frame[symbol].dropna(how="all")
        # yfinance keeps the requested spelling; fall back to a case-insensitive
        # match before giving up.
        for candidate in level0:
            if str(candidate).upper() == symbol:
                return frame[candidate].dropna(how="all")
        return None
    # Single-ticker download: the frame is already this symbol's data.
    return frame.dropna(how="all") if batch_size == 1 else None


def _date_range(frame):
    if frame is None or len(frame) == 0:
        return None, None
    try:
        return (frame.index[0].strftime("%Y-%m-%d"),
                frame.index[-1].strftime("%Y-%m-%d"))
    except AttributeError:
        return str(frame.index[0])[:10], str(frame.index[-1])[:10]


def _chunks(seq, size):
    seq = list(seq)
    for i in range(0, len(seq), max(1, size)):
        yield seq[i:i + size]
