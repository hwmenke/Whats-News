"""
db.py - SQLite store for the Yahoo data downloader.

Tables
  tickers         : the symbol universe (active + delisted), one row per symbol
  prices          : OHLCV bars, one row per (symbol, interval, date)
  dividends       : cash dividends, one row per (symbol, date)
  splits          : share splits, one row per (symbol, date)
  profiles        : company/fund metadata snapshot, one row per symbol
  fetch_log       : the outcome of every download attempt (drives resume + retries)
  lookup_progress : finished lookup-crawl triples (drives the universe resume)
  meta            : schema version and bookkeeping key/values

The database is opened in WAL mode with a large page cache: this store is
written by one long-running downloader while being read by anything else.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# 2 added lookup_progress. Every table is created with IF NOT EXISTS and the
# CLI runs init_schema on every command, so an older database picks the new
# table up on its next run — no migration step.
SCHEMA_VERSION = 2

# Symbol lifecycle states.
STATUS_ACTIVE = "active"
STATUS_DELISTED = "delisted"
STATUS_UNKNOWN = "unknown"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class Store:
    """Thin wrapper around a SQLite connection. Not thread-safe; give each
    worker thread its own Store (or let the downloader do the writing)."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=60)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-64000")   # ~64 MB page cache
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA foreign_keys=ON")

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def init_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS tickers (
            symbol        TEXT PRIMARY KEY,
            name          TEXT,
            quote_type    TEXT,          -- EQUITY | ETF | INDEX | CRYPTOCURRENCY | …
            exchange      TEXT,          -- Yahoo exchange code (NMS, NYQ, PCX, …)
            exchange_name TEXT,
            status        TEXT NOT NULL DEFAULT 'unknown',  -- active|delisted|unknown
            sources       TEXT NOT NULL DEFAULT '',  -- comma-separated discovery sources
            first_seen    TEXT NOT NULL,
            last_seen     TEXT NOT NULL, -- last time a source still listed it
            delisted_at   TEXT,          -- date of the last bar we ever saw
            has_data      INTEGER NOT NULL DEFAULT 0,
            notes         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tickers_status ON tickers(status);
        CREATE INDEX IF NOT EXISTS idx_tickers_type   ON tickers(quote_type);

        CREATE TABLE IF NOT EXISTS prices (
            symbol    TEXT NOT NULL,
            interval  TEXT NOT NULL,     -- 1d | 1wk | 1mo
            date      TEXT NOT NULL,     -- YYYY-MM-DD
            open      REAL,
            high      REAL,
            low       REAL,
            close     REAL,
            adj_close REAL,
            volume    REAL,
            PRIMARY KEY (symbol, interval, date)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

        CREATE TABLE IF NOT EXISTS dividends (
            symbol TEXT NOT NULL,
            date   TEXT NOT NULL,
            amount REAL,
            PRIMARY KEY (symbol, date)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS splits (
            symbol TEXT NOT NULL,
            date   TEXT NOT NULL,
            ratio  REAL,
            PRIMARY KEY (symbol, date)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS profiles (
            symbol              TEXT PRIMARY KEY,
            long_name           TEXT,
            short_name          TEXT,
            quote_type          TEXT,
            sector              TEXT,
            industry            TEXT,
            country             TEXT,
            currency            TEXT,
            exchange            TEXT,
            market_cap          REAL,
            shares_outstanding  REAL,
            first_trade_date    TEXT,
            raw_json            TEXT,
            fetched_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fetch_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            interval    TEXT NOT NULL,
            status      TEXT NOT NULL,   -- ok | empty | error
            rows        INTEGER NOT NULL DEFAULT 0,
            first_date  TEXT,
            last_date   TEXT,
            error       TEXT,
            fetched_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_fetch_log_symbol
            ON fetch_log(symbol, interval, fetched_at);

        -- One row per (region, quote_type, prefix) the lookup crawl has fully
        -- paginated. Written only after a triple finishes, so an interrupted
        -- crawl retries whatever it was in the middle of.
        CREATE TABLE IF NOT EXISTS lookup_progress (
            region       TEXT NOT NULL,
            quote_type   TEXT NOT NULL,
            prefix       TEXT NOT NULL,
            symbols      INTEGER NOT NULL DEFAULT 0,  -- rows the triple returned
            completed_at TEXT NOT NULL,
            PRIMARY KEY (region, quote_type, prefix)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        # Columns added after v1 shipped. CREATE TABLE IF NOT EXISTS will not
        # add them to a database that already exists, so do it by hand and
        # ignore the "duplicate column" error on a database that has them.
        for column, definition in (
            ("needs_full_refetch", "INTEGER NOT NULL DEFAULT 0"),
        ):
            try:
                cur.execute(f"ALTER TABLE tickers ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass    # already present

        # `status` belongs in this index: symbols_to_fetch filters on it, and
        # without it every matching log row costs an extra table lookup.
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_fetch_log_lookup
                       ON fetch_log(symbol, interval, status, fetched_at)""")

        self.conn.commit()
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    # ── meta ───────────────────────────────────────────────────────────────────

    def set_meta(self, key: str, value: str):
        with self.tx() as c:
            c.execute(
                "INSERT INTO meta (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # ── tickers ────────────────────────────────────────────────────────────────

    def upsert_tickers(self, records) -> dict:
        """Merge discovered symbols into the universe.

        `records` is an iterable of dicts with at least a `symbol` key; the
        optional keys are name/quote_type/exchange/exchange_name/status/source.

        Existing rows keep their first_seen, keep any field the new record
        leaves blank, and accumulate the set of sources that have ever listed
        them. Returns {"inserted": n, "updated": n}.
        """
        now = utcnow()
        inserted = updated = 0
        with self.tx() as c:
            for rec in records:
                symbol = normalize_symbol(rec.get("symbol"))
                if not symbol:
                    continue
                source = (rec.get("source") or "").strip()
                row = c.execute(
                    "SELECT symbol, sources, status FROM tickers WHERE symbol=?",
                    (symbol,),
                ).fetchone()
                if row is None:
                    c.execute(
                        """INSERT INTO tickers
                           (symbol, name, quote_type, exchange, exchange_name,
                            status, sources, first_seen, last_seen)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            symbol,
                            rec.get("name"),
                            rec.get("quote_type"),
                            rec.get("exchange"),
                            rec.get("exchange_name"),
                            rec.get("status") or STATUS_UNKNOWN,
                            source,
                            now,
                            now,
                        ),
                    )
                    inserted += 1
                else:
                    sources = merge_sources(row["sources"], source)
                    # A source listing the symbol today only ever promotes an
                    # unknown symbol to active — it never revives a symbol we
                    # have already proven delisted from its price history.
                    # A source saying "unknown" is not an opinion, it is the
                    # absence of one — several sources hard-code it — so it
                    # must never demote a symbol we have proven active.
                    new_status = rec.get("status")
                    if new_status in (None, "", STATUS_UNKNOWN):
                        status = row["status"]
                    elif row["status"] == STATUS_DELISTED:
                        status = STATUS_DELISTED
                    else:
                        status = new_status
                    c.execute(
                        """UPDATE tickers SET
                               name          = COALESCE(NULLIF(?, ''), name),
                               quote_type    = COALESCE(NULLIF(?, ''), quote_type),
                               exchange      = COALESCE(NULLIF(?, ''), exchange),
                               exchange_name = COALESCE(NULLIF(?, ''), exchange_name),
                               status        = ?,
                               sources       = ?,
                               last_seen     = ?
                           WHERE symbol = ?""",
                        (
                            rec.get("name") or "",
                            rec.get("quote_type") or "",
                            rec.get("exchange") or "",
                            rec.get("exchange_name") or "",
                            status,
                            sources,
                            now,
                            symbol,
                        ),
                    )
                    updated += 1
        return {"inserted": inserted, "updated": updated}

    def count_tickers(self, status: str = None) -> int:
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) n FROM tickers WHERE status=?", (status,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) n FROM tickers").fetchone()
        return row["n"]

    def symbols_to_fetch(self, interval: str, limit: int = None,
                         refresh_after_hours: int = 20,
                         include_delisted: bool = True,
                         quote_types: list = None,
                         max_failure_backoff_days: int = 30,
                         delisted_recheck_days: int = 30,
                         force: bool = False) -> list:
        """Symbols due for a download, longest-waiting first.

        Due means one of:
          * never fetched successfully, and not inside its failure backoff;
          * last successful fetch older than `refresh_after_hours`.

        Two things keep a large universe from wasting every run on hopeless
        symbols: a symbol proven delisted is fetched once (its history is
        final), and a symbol that keeps coming back empty backs off
        exponentially — 1, 2, 4, … days up to `max_failure_backoff_days`.
        `force=True` ignores both and returns everything.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=refresh_after_hours)).isoformat(
            timespec="seconds")

        where = ["1=1"]
        params = []
        if not include_delisted:
            where.append("t.status != ?")
            params.append(STATUS_DELISTED)
        if quote_types:
            placeholders = ",".join("?" for _ in quote_types)
            where.append(f"UPPER(COALESCE(t.quote_type,'')) IN ({placeholders})")
            params.extend([q.upper() for q in quote_types])

        sql = f"""
            SELECT t.symbol,
                   t.status,
                   (SELECT MAX(fetched_at) FROM fetch_log f
                     WHERE f.symbol=t.symbol AND f.interval=? AND f.status='ok') AS last_ok,
                   (SELECT MAX(fetched_at) FROM fetch_log f
                     WHERE f.symbol=t.symbol AND f.interval=?) AS last_try,
                   (SELECT COUNT(*) FROM fetch_log f
                     WHERE f.symbol=t.symbol AND f.interval=?) AS attempts
            FROM tickers t
            WHERE {' AND '.join(where)}
        """
        rows = self.conn.execute(
            sql, [interval, interval, interval] + params).fetchall()

        due = []
        for r in rows:
            last_ok, last_try = r["last_ok"], r["last_try"]
            if force:
                due.append((last_try or "", r["symbol"]))
            elif last_ok is None:
                if last_try is None:
                    due.append(("", r["symbol"]))
                elif last_try <= _backoff_cutoff(now, r["attempts"],
                                                 max_failure_backoff_days):
                    due.append((last_try, r["symbol"]))
            elif r["status"] == STATUS_DELISTED:
                # A dead symbol's history is final, so it does not need the
                # daily pass — but it is not checked *never* either: we may
                # have written it off during a Yahoo outage, so look again on a
                # slow cadence and let a real bar revive it.
                if last_ok <= (now - timedelta(days=max(1, delisted_recheck_days))
                               ).isoformat(timespec="seconds"):
                    due.append((last_ok, r["symbol"]))
            elif last_ok <= cutoff:
                due.append((last_ok, r["symbol"]))

        due.sort()
        symbols = [s for _, s in due]
        return symbols[:limit] if limit else symbols

    def mark_status(self, symbol: str, status: str, delisted_at: str = None,
                    notes: str = None):
        with self.tx() as c:
            c.execute(
                """UPDATE tickers SET
                       status      = ?,
                       delisted_at = COALESCE(?, delisted_at),
                       notes       = COALESCE(?, notes)
                   WHERE symbol = ?""",
                (status, delisted_at, notes, normalize_symbol(symbol)),
            )

    def symbols_needing_full_refetch(self, symbols) -> set:
        """Symbols flagged for a full re-download — currently, those that have
        gained a split since we last stored their history."""
        out = set()
        clean = [normalize_symbol(s) for s in symbols if s]
        for chunk in _chunks(clean, 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"""SELECT symbol FROM tickers
                    WHERE needs_full_refetch=1 AND symbol IN ({placeholders})""",
                list(chunk),
            ).fetchall()
            out.update(r["symbol"] for r in rows)
        return out

    def clear_full_refetch(self, symbol: str):
        with self.tx() as c:
            c.execute("UPDATE tickers SET needs_full_refetch=0 WHERE symbol=?",
                      (normalize_symbol(symbol),))

    def consecutive_empty_fetches(self, symbol: str, interval: str) -> int:
        """How many times in a row the most recent fetches came back empty.

        Anything that is not an empty result — a success, or an error we can
        attribute to Yahoo rather than to the symbol — resets the count, so a
        bad afternoon cannot accumulate into a delisting.
        """
        rows = self.conn.execute(
            """SELECT status FROM fetch_log
               WHERE symbol=? AND interval=?
               ORDER BY fetched_at DESC, id DESC LIMIT 20""",
            (normalize_symbol(symbol), interval),
        ).fetchall()
        streak = 0
        for r in rows:
            if r["status"] != "empty":
                break
            streak += 1
        return streak

    def mark_has_data(self, symbol: str, last_date: str):
        with self.tx() as c:
            c.execute(
                "UPDATE tickers SET has_data=1, delisted_at=? WHERE symbol=?",
                (last_date, normalize_symbol(symbol)),
            )

    # ── prices / actions ───────────────────────────────────────────────────────

    def upsert_prices(self, symbol: str, interval: str, df) -> int:
        """Upsert a DataFrame of bars. Index must be datetime-like; columns are
        matched case-insensitively against open/high/low/close/adj close/volume."""
        rows = _bars_to_rows(symbol, interval, df)
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany(
                """INSERT INTO prices
                       (symbol, interval, date, open, high, low, close, adj_close, volume)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol, interval, date) DO UPDATE SET
                       open=excluded.open, high=excluded.high, low=excluded.low,
                       close=excluded.close, adj_close=excluded.adj_close,
                       volume=excluded.volume""",
                rows,
            )
        return len(rows)

    def upsert_actions(self, symbol: str, dividends=None, splits=None) -> dict:
        sym = normalize_symbol(symbol)
        div_rows, split_rows = [], []
        for series, sink in ((dividends, div_rows), (splits, split_rows)):
            if series is None or len(series) == 0:
                continue
            for idx, value in series.items():
                try:
                    if value is None or float(value) == 0.0:
                        continue
                    sink.append((sym, _date_str(idx), float(value)))
                except (TypeError, ValueError):
                    continue
        new_splits = 0
        with self.tx() as c:
            if div_rows:
                c.executemany(
                    "INSERT INTO dividends (symbol, date, amount) VALUES (?,?,?) "
                    "ON CONFLICT(symbol, date) DO UPDATE SET amount=excluded.amount",
                    div_rows,
                )
            if split_rows:
                known = {r["date"] for r in c.execute(
                    "SELECT date FROM splits WHERE symbol=?", (sym,)).fetchall()}
                new_splits = sum(1 for r in split_rows if r[1] not in known)
                c.executemany(
                    "INSERT INTO splits (symbol, date, ratio) VALUES (?,?,?) "
                    "ON CONFLICT(symbol, date) DO UPDATE SET ratio=excluded.ratio",
                    split_rows,
                )
                if new_splits:
                    # Yahoo restates a symbol's ENTIRE price history when it
                    # splits, so the bars we already hold are now on the wrong
                    # basis. An incremental window can never repair that —
                    # flag the symbol for a full re-download.
                    c.execute(
                        "UPDATE tickers SET needs_full_refetch=1 WHERE symbol=?",
                        (sym,))
        return {"dividends": len(div_rows), "splits": len(split_rows),
                "new_splits": new_splits}

    def upsert_profile(self, symbol: str, info: dict):
        sym = normalize_symbol(symbol)
        first_trade = info.get("firstTradeDateEpochUtc") or info.get("firstTradeDateMilliseconds")
        first_trade_str = None
        if first_trade:
            try:
                seconds = float(first_trade)
                if seconds > 1e11:      # milliseconds
                    seconds /= 1000.0
                first_trade_str = datetime.fromtimestamp(
                    seconds, tz=timezone.utc
                ).date().isoformat()
            except (TypeError, ValueError, OSError, OverflowError):
                first_trade_str = None
        with self.tx() as c:
            c.execute(
                """INSERT INTO profiles
                     (symbol, long_name, short_name, quote_type, sector, industry,
                      country, currency, exchange, market_cap, shares_outstanding,
                      first_trade_date, raw_json, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET
                     long_name=excluded.long_name, short_name=excluded.short_name,
                     quote_type=excluded.quote_type, sector=excluded.sector,
                     industry=excluded.industry, country=excluded.country,
                     currency=excluded.currency, exchange=excluded.exchange,
                     market_cap=excluded.market_cap,
                     shares_outstanding=excluded.shares_outstanding,
                     first_trade_date=excluded.first_trade_date,
                     raw_json=excluded.raw_json, fetched_at=excluded.fetched_at""",
                (
                    sym,
                    info.get("longName"),
                    info.get("shortName"),
                    info.get("quoteType"),
                    info.get("sector"),
                    info.get("industry"),
                    info.get("country"),
                    info.get("currency"),
                    info.get("exchange"),
                    _as_float(info.get("marketCap")),
                    _as_float(info.get("sharesOutstanding")),
                    first_trade_str,
                    json.dumps(info, default=str)[:200000],
                    utcnow(),
                ),
            )

    def last_price_date(self, symbol: str, interval: str):
        row = self.conn.execute(
            "SELECT MAX(date) d FROM prices WHERE symbol=? AND interval=?",
            (normalize_symbol(symbol), interval),
        ).fetchone()
        return row["d"] if row and row["d"] else None

    def last_price_dates(self, symbols, interval: str) -> dict:
        """Bulk version of last_price_date for a batch of symbols."""
        out = {}
        symbols = [normalize_symbol(s) for s in symbols if s]
        for chunk in _chunks(symbols, 500):
            placeholders = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"""SELECT symbol, MAX(date) d FROM prices
                    WHERE interval=? AND symbol IN ({placeholders})
                    GROUP BY symbol""",
                [interval] + list(chunk),
            ).fetchall()
            for r in rows:
                out[r["symbol"]] = r["d"]
        return out

    # ── fetch log ──────────────────────────────────────────────────────────────

    def log_fetch(self, symbol: str, interval: str, status: str, rows: int = 0,
                  first_date: str = None, last_date: str = None, error: str = None):
        with self.tx() as c:
            c.execute(
                """INSERT INTO fetch_log
                     (symbol, interval, status, rows, first_date, last_date, error, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    normalize_symbol(symbol), interval, status, rows,
                    first_date, last_date, (error or "")[:500] or None, utcnow(),
                ),
            )

    def log_fetches(self, entries):
        """Batch form of log_fetch; `entries` are dicts with the same keys."""
        now = utcnow()
        rows = [
            (
                normalize_symbol(e["symbol"]), e["interval"], e["status"],
                e.get("rows", 0), e.get("first_date"), e.get("last_date"),
                (e.get("error") or "")[:500] or None, now,
            )
            for e in entries
        ]
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany(
                """INSERT INTO fetch_log
                     (symbol, interval, status, rows, first_date, last_date, error, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    # ── lookup crawl progress ──────────────────────────────────────────────────

    def lookup_prefixes_done(self, region: str, quote_type: str,
                             max_age_days: int = 14) -> set:
        """Prefixes already crawled for this (region, quote_type) and still
        fresh enough to trust. Loaded one pair at a time on purpose: a deep
        worldwide crawl has millions of triples but only ~50k per pair."""
        region, quote_type = _lookup_key(region, quote_type)
        rows = self.conn.execute(
            "SELECT prefix FROM lookup_progress "
            "WHERE region=? AND quote_type=? AND completed_at >= ?",
            (region, quote_type, _age_cutoff(max_age_days)),
        ).fetchall()
        return {r["prefix"] for r in rows}

    def count_lookup_prefixes_done(self, regions, quote_types,
                                   max_age_days: int = 14) -> int:
        """How many of the requested pairs' triples are still fresh — one COUNT
        for the resume line in the log, without materialising the prefixes."""
        pairs = [_lookup_key(r, q) for r in regions for q in quote_types]
        if not pairs:
            return 0
        clause = " OR ".join("(region=? AND quote_type=?)" for _ in pairs)
        params = [p for pair in pairs for p in pair] + [_age_cutoff(max_age_days)]
        row = self.conn.execute(
            f"SELECT COUNT(*) n FROM lookup_progress "
            f"WHERE ({clause}) AND completed_at >= ?", params
        ).fetchone()
        return row["n"]

    def mark_lookup_prefix(self, region: str, quote_type: str, prefix: str,
                           symbols: int = 0):
        """Record a triple as finished. Called only once its pagination has
        completed and its symbols are already merged, so the checkpoint can
        never claim more progress than the database actually holds."""
        region, quote_type = _lookup_key(region, quote_type)
        with self.tx() as c:
            c.execute(
                """INSERT INTO lookup_progress
                     (region, quote_type, prefix, symbols, completed_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(region, quote_type, prefix) DO UPDATE SET
                     symbols=excluded.symbols, completed_at=excluded.completed_at""",
                (region, quote_type, str(prefix), int(symbols), utcnow()),
            )

    def clear_lookup_progress(self, regions=None, quote_types=None) -> int:
        """Forget checkpoints so the next crawl starts from prefix "A" again.
        Narrowed to the regions/types being crawled when they are given, so a
        `--lookup-restart` of one region does not discard another's night."""
        where, params = ["1=1"], []
        if regions:
            placeholders = ",".join("?" for _ in regions)
            where.append(f"region IN ({placeholders})")
            params.extend(_lookup_key(r, "")[0] for r in regions)
        if quote_types:
            placeholders = ",".join("?" for _ in quote_types)
            where.append(f"quote_type IN ({placeholders})")
            params.extend(_lookup_key("", q)[1] for q in quote_types)
        with self.tx() as c:
            cur = c.execute(
                f"DELETE FROM lookup_progress WHERE {' AND '.join(where)}", params)
            return cur.rowcount

    # ── reporting ──────────────────────────────────────────────────────────────

    def stats(self, interval: str = "1d") -> dict:
        c = self.conn
        one = lambda sql, params=(): c.execute(sql, params).fetchone()[0]  # noqa: E731
        out = {
            "db_path": str(self.db_path),
            "db_size_mb": round(self.db_path.stat().st_size / 1e6, 1)
            if self.db_path.exists() else 0.0,
            "tickers_total": one("SELECT COUNT(*) FROM tickers"),
            "tickers_active": one(
                "SELECT COUNT(*) FROM tickers WHERE status=?", (STATUS_ACTIVE,)),
            "tickers_delisted": one(
                "SELECT COUNT(*) FROM tickers WHERE status=?", (STATUS_DELISTED,)),
            "tickers_unknown": one(
                "SELECT COUNT(*) FROM tickers WHERE status=?", (STATUS_UNKNOWN,)),
            "tickers_with_data": one("SELECT COUNT(*) FROM tickers WHERE has_data=1"),
            "price_rows": one("SELECT COUNT(*) FROM prices WHERE interval=?", (interval,)),
            "symbols_with_prices": one(
                "SELECT COUNT(DISTINCT symbol) FROM prices WHERE interval=?", (interval,)),
            "dividend_rows": one("SELECT COUNT(*) FROM dividends"),
            "split_rows": one("SELECT COUNT(*) FROM splits"),
            "profiles": one("SELECT COUNT(*) FROM profiles"),
            "date_min": one("SELECT MIN(date) FROM prices WHERE interval=?", (interval,)),
            "date_max": one("SELECT MAX(date) FROM prices WHERE interval=?", (interval,)),
        }
        out["by_source"] = [
            dict(r) for r in c.execute(
                "SELECT sources, COUNT(*) n FROM tickers GROUP BY sources ORDER BY n DESC LIMIT 20"
            ).fetchall()
        ]
        out["by_type"] = [
            dict(r) for r in c.execute(
                "SELECT COALESCE(NULLIF(quote_type,''),'unknown') quote_type, "
                "COUNT(*) n FROM tickers GROUP BY 1 ORDER BY n DESC LIMIT 20"
            ).fetchall()
        ]
        return out

    def mark_stale_as_delisted(self, interval: str, stale_days: int) -> int:
        """Flag symbols whose newest stored bar is older than `stale_days` as
        delisted. The market's own newest bar date is the reference point, so a
        weekend or a stale database does not sweep the whole universe."""
        row = self.conn.execute(
            "SELECT MAX(date) d FROM prices WHERE interval=?", (interval,)
        ).fetchone()
        market_last = row["d"] if row and row["d"] else None
        if not market_last:
            return 0
        cutoff = (
            datetime.fromisoformat(market_last).date() - timedelta(days=stale_days)
        ).isoformat()
        with self.tx() as c:
            cur = c.execute(
                """UPDATE tickers SET status=?, delisted_at=(
                        SELECT MAX(date) FROM prices p
                        WHERE p.symbol=tickers.symbol AND p.interval=?)
                   WHERE status != ?
                     AND has_data = 1
                     AND (SELECT MAX(date) FROM prices p
                          WHERE p.symbol=tickers.symbol AND p.interval=?) < ?""",
                (STATUS_DELISTED, interval, STATUS_DELISTED, interval, cutoff),
            )
            return cur.rowcount


# ── helpers ────────────────────────────────────────────────────────────────────

# Yahoo market suffixes that are a single letter, so `VOD.L` (London) is not
# mistaken for a share class the way `BRK.B` is. Multi-letter suffixes (.TO,
# .AX, .SW …) are never ambiguous.
SINGLE_LETTER_EXCHANGE_SUFFIXES = {"L", "T", "F", "V"}


def normalize_symbol(symbol, us_style: bool = False) -> str:
    """Yahoo's canonical form: upper-case, unspaced, `$` index prefix mapped to
    `^`, and share-class separators mapped to `-` (BRK.B -> BRK-B, BF/B -> BF-B).

    A one-letter tail after a dot is ambiguous — `BRK.A` is a share class but
    `VOD.L` is the London listing — so the four single-letter exchange suffixes
    keep their dot. Pass `us_style=True` for symbols that came from a US-only
    directory, where a one-letter tail is always a share class.
    """
    if symbol is None:
        return ""
    s = str(symbol).strip().upper()
    if not s:
        return ""
    if s.startswith("$"):
        s = "^" + s[1:]
    s = s.replace(" ", "")
    if s.startswith("^") or "-USD" in s or "=" in s:
        return s
    if "/" in s:
        head, _, tail = s.rpartition("/")
        if head and len(tail) <= 2:
            s = f"{head}-{tail}"
    if "." in s:
        head, _, tail = s.rpartition(".")
        if head and len(tail) == 1 and (
            us_style or tail not in SINGLE_LETTER_EXCHANGE_SUFFIXES
        ):
            s = f"{head}-{tail}"
    return s


def _lookup_key(region: str, quote_type: str) -> tuple:
    """Canonical spelling of a crawl coordinate, so `--lookup-types EQUITY` and
    `--lookup-types equity` resume each other instead of crawling twice."""
    return (str(region or "").strip().upper(),
            str(quote_type or "").strip().lower())


def _age_cutoff(days: int) -> str:
    """ISO timestamp `days` ago. Comparing ISO strings is a valid ordering here
    because every timestamp we write is UTC with the same offset."""
    return (datetime.now(timezone.utc) - timedelta(days=max(0, days))).isoformat(
        timespec="seconds")


def _backoff_cutoff(now, attempts: int, cap_days: int) -> str:
    """Failed-symbol backoff: retry after 1, 2, 4, … days, capped."""
    days = min(2 ** max(0, (attempts or 1) - 1), max(1, cap_days))
    return (now - timedelta(days=days)).isoformat(timespec="seconds")


def merge_sources(existing: str, new: str) -> str:
    parts = [p for p in (existing or "").split(",") if p]
    if new and new not in parts:
        parts.append(new)
    return ",".join(sorted(set(parts)))


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _as_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_str(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _bars_to_rows(symbol: str, interval: str, df) -> list:
    """Flatten a yfinance bar frame into insert tuples, skipping empty rows."""
    if df is None or len(df) == 0:
        return []

    sym = normalize_symbol(symbol)
    frame = df.copy()

    # A single-ticker slice of a grouped yf.download still carries a column
    # MultiIndex; drop every level but the field name.
    if hasattr(frame.columns, "nlevels") and frame.columns.nlevels > 1:
        frame.columns = [
            next((str(part) for part in reversed(tuple(col)) if part), "")
            for col in frame.columns
        ]
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    # Keep the first of any duplicate column labels.
    frame = frame.loc[:, ~frame.columns.duplicated()]

    def col(name):
        return frame[name] if name in frame.columns else None

    o, h, l_, c = col("open"), col("high"), col("low"), col("close")
    adj = col("adj close")
    if adj is None:
        adj = col("adj_close")
    v = col("volume")

    rows = []
    for i, idx in enumerate(frame.index):
        vals = [
            _cell(o, i), _cell(h, i), _cell(l_, i),
            _cell(c, i), _cell(adj, i), _cell(v, i),
        ]
        if all(x is None for x in vals[:4]):
            continue  # padding row from a multi-symbol download
        rows.append((sym, interval, _date_str(idx), *vals))
    return rows


def _cell(series, position):
    if series is None:
        return None
    try:
        value = series.iloc[position]
    except (IndexError, KeyError):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value  # NaN check without importing numpy
