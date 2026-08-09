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

Telling "dead" apart from "Yahoo is having a bad day"
  This is the whole ballgame for a multi-hour run. yfinance hides exceptions by
  default (`YfConfig.debug.hide_exceptions`), so a 500, a rate limit and a
  genuinely dead ticker all arrive as the same empty DataFrame. Believing that
  empty frame means "delisted" lets one bad twenty minutes permanently bury
  every symbol it touched. So:
    * exceptions are un-hidden and classified — only a real prices-missing
      error counts as evidence of death, never a rate limit or a timeout;
    * a symbol must come back empty on `delist_after_empty_fetches` separate
      runs before it is written off;
    * a whole batch coming back empty is treated as a batch-level failure, not
      as N simultaneous delistings — that is what a rate limit looks like;
    * bars arriving for a symbol we had written off revive it.
"""

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from yfinance.config import YfConfig

from .db import STATUS_ACTIVE, STATUS_DELISTED, Store, normalize_symbol

logger = logging.getLogger(__name__)

# Phrases Yahoo/yfinance use when a symbol has no data at all any more.
DELISTED_HINTS = ("delisted", "no data found", "no price data found",
                  "symbol may be delisted")
RATE_LIMIT_HINTS = ("too many requests", "rate limit", "429")


def _exception_kind(exc) -> str:
    """Classify a yfinance failure: 'missing' (real evidence the symbol has no
    data), 'rate_limit', or 'transient' (anything else — never evidence)."""
    name = type(exc).__name__
    if name == "YFRateLimitError":
        return "rate_limit"
    if name in ("YFPricesMissingError", "YFTickerMissingError"):
        return "missing"
    message = str(exc).lower()
    if any(hint in message for hint in RATE_LIMIT_HINTS):
        return "rate_limit"
    if any(hint in message for hint in DELISTED_HINTS):
        return "missing"
    return "transient"


class Downloader:
    def __init__(self, cfg, store: Store):
        self.cfg = cfg
        self.store = store
        self.stats = defaultdict(int)
        # Make Ticker.history() raise instead of returning an empty frame, so
        # _retry_single can tell a dead symbol from a sick server. yf.download's
        # worker overrides this per call and swallows exceptions regardless.
        YfConfig.debug.hide_exceptions = False

    # ── public API ─────────────────────────────────────────────────────────────

    def run(self, symbols=None, interval: str = None, limit: int = None,
            include_delisted: bool = True, quote_types=None, exclude_types=None,
            single_retry: bool = True, force: bool = False,
            progress=None) -> dict:
        """Download every due symbol. Returns a summary dict."""
        # Counters are per call: a Downloader reused for a second run must not
        # report the first run's totals again.
        self.stats = defaultdict(int)
        interval = interval or self.cfg.interval
        # A run over an explicit subset must not draw universe-wide conclusions:
        # `download --symbols AAPL` has no business delisting anything else.
        # A type filter is different — it is a standing partition of the
        # universe, not an ad-hoc slice — so it still sweeps, scoped to itself.
        full_run = symbols is None and not limit
        if symbols is None:
            symbols = self.store.symbols_to_fetch(
                interval=interval,
                limit=limit,
                refresh_after_hours=self.cfg.refresh_after_hours,
                include_delisted=include_delisted,
                quote_types=quote_types,
                exclude_types=exclude_types,
                max_failure_backoff_days=self.cfg.max_failure_backoff_days,
                delisted_recheck_days=self.cfg.delisted_recheck_days,
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

        groups = self._group_by_start(symbols, interval, force=force)
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

        if full_run:
            swept = self.store.mark_stale_as_delisted(
                interval, self.cfg.stale_days,
                quote_types=quote_types, exclude_types=exclude_types)
            self.stats["marked_delisted_stale"] += swept
        return dict(self.stats, symbols=processed)

    def fetch_profiles(self, symbols=None, limit: int = None,
                       refetch_days: int = 30, progress=None) -> dict:
        """Store company/fund metadata (sector, currency, market cap, …).

        One HTTP call per symbol, so this is deliberately separate from the
        price download — run it on the slice you care about.
        """
        self.stats = defaultdict(int)
        if symbols is None:
            symbols = self._profiles_due(limit=limit, refetch_days=refetch_days)
        else:
            symbols = [normalize_symbol(s) for s in symbols if normalize_symbol(s)]
            if limit:
                symbols = symbols[:limit]

        done = 0
        consecutive_rate_limits = 0
        for symbol in symbols:
            try:
                info = yf.Ticker(symbol).info or {}
                if info:
                    self.store.upsert_profile(symbol, info)
                    self.stats["profiles_ok"] += 1
                else:
                    self.stats["profiles_empty"] += 1
                consecutive_rate_limits = 0
            except KeyboardInterrupt:
                logger.warning("profiles: interrupted after %d symbols", done)
                break
            except Exception as exc:
                logger.debug("profiles: %s failed: %s", symbol, exc)
                self.stats["profiles_error"] += 1
                # One request per symbol with no backoff turns a throttled run
                # into an unbounded stream of 429s that accomplishes nothing.
                if _exception_kind(exc) == "rate_limit":
                    consecutive_rate_limits += 1
                    self.stats["profiles_rate_limited"] += 1
                    wait = self.cfg.retry_backoff * min(
                        2 ** consecutive_rate_limits, 16)
                    logger.warning("profiles: rate limited (%d in a row); "
                                   "sleeping %.0fs", consecutive_rate_limits, wait)
                    time.sleep(wait)
                    if consecutive_rate_limits >= self.cfg.max_retries:
                        logger.error("profiles: still throttled after %d tries, "
                                     "stopping — re-run to continue",
                                     consecutive_rate_limits)
                        break
                else:
                    consecutive_rate_limits = 0
            done += 1
            if progress and done % 25 == 0:
                progress(done, len(symbols), dict(self.stats))
            if self.cfg.sleep_between_batches:
                time.sleep(self.cfg.sleep_between_batches)
        return dict(self.stats, symbols=done)

    # ── batching ───────────────────────────────────────────────────────────────

    def _group_by_start(self, symbols, interval: str, force: bool = False) -> dict:
        """Map start-date -> symbols. `None` means "download full history".

        Start dates are snapped back to a Monday so the long tail of symbols
        that each stopped trading on a different day still share a batch —
        keying on the exact date fragmented batches down to one symbol per
        HTTP call, which is what makes a run trip rate limits.
        """
        last_dates = self.store.last_price_dates(symbols, interval)
        needs_full = self.store.symbols_needing_full_refetch(symbols)
        overlap = timedelta(days=self.cfg.incremental_overlap_days)
        today = datetime.now(timezone.utc).date()
        groups = defaultdict(list)

        for symbol in symbols:
            last = last_dates.get(symbol)
            # `force` and a newly discovered split both mean "re-download the
            # whole series": Yahoo retroactively restates every bar on a split,
            # so an incremental window would leave a permanent price cliff.
            if force or not last or symbol in needs_full:
                groups[None].append(symbol)
                continue
            try:
                start = date.fromisoformat(last) - overlap
            except ValueError:
                groups[None].append(symbol)
                continue
            if start > today:
                start = today
            start -= timedelta(days=start.weekday())
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

        # A whole multi-symbol batch coming back empty is not fifty companies
        # dying at once — it is Yahoo throttling or failing us. Retrying each
        # one individually would fire fifty more requests into the same wall
        # and bury fifty healthy symbols under failure backoff.
        if len(batch) > 1 and len(empty) == len(batch):
            logger.warning("downloader: entire batch of %d came back empty — "
                           "treating as a server-side failure, backing off",
                           len(batch))
            self.store.log_fetches([
                {"symbol": s, "interval": interval, "status": "error", "rows": 0,
                 "error": "whole batch empty; assumed throttled"} for s in empty
            ])
            self.stats["error"] += len(empty)
            self.stats["batches_throttled"] += 1
            time.sleep(self.cfg.retry_backoff * 4)
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
            kind = _exception_kind(exc)
            self.store.log_fetch(symbol, interval, "error", error=str(exc))
            self.stats["error"] += 1
            self.stats[f"error_{kind}"] += 1
            if kind == "rate_limit":
                # Evidence about Yahoo's mood, not about this company.
                time.sleep(self.cfg.retry_backoff * 4)
            elif kind == "missing":
                self._consider_delisting(symbol, interval, str(exc)[:200])
            return

        if frame is None or frame.empty:
            self.store.log_fetch(symbol, interval, "empty", error="no data returned")
            self.stats["empty"] += 1
            self._consider_delisting(symbol, interval, "no history returned by Yahoo")
            return

        self._store_symbol(symbol, interval, frame)

    def _consider_delisting(self, symbol: str, interval: str, reason: str):
        """Write a symbol off only once it has come back empty on several
        separate runs. One empty response is as likely to be a bad afternoon at
        Yahoo as a dead company, and delisting has real consequences here — a
        delisted symbol is refetched at most once every `delisted_recheck_days`.
        """
        if self.store.last_price_date(symbol, interval):
            return      # we hold real bars for it; only the stale sweep decides
        strikes = self.store.consecutive_empty_fetches(symbol, interval)
        needed = max(1, self.cfg.delist_after_empty_fetches)
        if strikes < needed:
            self.stats["empty_pending_delist"] += 1
            return
        self.store.mark_status(symbol, STATUS_DELISTED,
                               notes=f"{reason} ({strikes} consecutive empty fetches)")
        self.stats["marked_delisted"] += 1

    def _store_symbol(self, symbol: str, interval: str, frame: pd.DataFrame):
        rows = self.store.upsert_prices(symbol, interval, frame)
        actions = self._store_actions(symbol, interval, frame)
        # From the rows actually stored, not the frame's index — padding rows
        # are dropped on the way in and would otherwise name a date that has
        # no bar behind it.
        first_date, last_date = self.store.written_date_range(
            symbol, interval, frame)
        # The refetch this flag asked for has now happened.
        self.store.clear_full_refetch(symbol)

        if rows:
            self.store.mark_has_data(symbol, last_date)
            current = self.store.conn.execute(
                "SELECT status FROM tickers WHERE symbol=?", (symbol,)
            ).fetchone()
            # Bars arriving for a symbol we had written off mean we were wrong
            # — a transient failure, or a ticker that came back from a halt.
            # Evidence beats the earlier guess, so revive it.
            if current and current["status"] == STATUS_DELISTED:
                self.stats["revived"] += 1
            self.store.mark_status(symbol, STATUS_ACTIVE)

        self.store.log_fetch(symbol, interval, "ok" if rows else "empty",
                             rows=rows, first_date=first_date, last_date=last_date)
        self.stats["ok" if rows else "empty"] += 1
        self.stats["rows"] += rows
        self.stats["dividends"] += actions.get("dividends", 0)
        self.stats["splits"] += actions.get("splits", 0)

    def _store_actions(self, symbol: str, interval: str,
                       frame: pd.DataFrame) -> dict:
        # Actions are dated to the bar that contains them, so a 1wk or 1mo run
        # would file the same dividend under the week's or month's opening date
        # and sit alongside the correct daily row. Only daily bars date them
        # exactly, so only daily bars get to write them.
        if interval != "1d":
            return {}
        columns = {str(c).strip().lower(): c for c in frame.columns}
        dividends = frame[columns["dividends"]] if "dividends" in columns else None
        splits = frame[columns["stock splits"]] if "stock splits" in columns else None
        if dividends is None and splits is None:
            return {}
        return self.store.upsert_actions(symbol, dividends=dividends, splits=splits)

    def _profiles_due(self, limit: int = None, refetch_days: int = 30) -> list:
        # Must match db.utcnow()'s tz-aware format, or the string comparison
        # against profiles.fetched_at diverges within the same second.
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=refetch_days)).isoformat(timespec="seconds")
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
