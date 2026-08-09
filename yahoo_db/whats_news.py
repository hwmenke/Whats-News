"""
whats_news.py - Drop-in adapter that points the What's News dashboard at the
yahoo_db archive.

The dashboard was written against `database.py` (its own small finance.db) and
`data_fetcher.py`. This module exposes the same function names with the same
signatures and return shapes, backed by the archive instead. Plugging it in is
two import lines in app.py:

    import database as db            ->  from yahoo_db import whats_news as db
    import data_fetcher as fetcher   ->  from yahoo_db import whats_news as fetcher

Nothing else in the dashboard has to change: `freq` still means
"daily"/"weekly", `get_ohlcv` still returns the same row dicts in the same
order, and `fetch_and_store` still returns the same summary keys.

Two things genuinely differ, both on purpose:

  * **The sidebar shows a watchlist, not the universe.** The archive holds
    tens of thousands of symbols; the dashboard renders every row `list_symbols`
    returns. So this module keeps a small `watchlist` table and lists that.
    `add_symbol` puts a symbol on the watchlist (registering it in the universe
    if it is new); `search_symbols` is there for finding things to add.

  * **`remove_symbol` does not delete price history.** In the dashboard's own
    database, removing a symbol dropped its bars — fine when they are two years
    of data you can refetch in a second. Here they may be fifteen years of a
    delisted company Yahoo will never serve again, so removal takes the symbol
    off the watchlist and leaves the archive untouched.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import load_config
from .db import STATUS_DELISTED, Store, normalize_symbol, utcnow
from .downloader import Downloader

logger = logging.getLogger(__name__)

# The dashboard's vocabulary -> the archive's.
FREQ_TO_INTERVAL = {"daily": "1d", "weekly": "1wk", "monthly": "1mo"}
# Weekly bars are derived from daily unless the archive really holds 1wk rows,
# so a `download --interval 1wk` pass is optional rather than required.
RESAMPLE_RULE = {"weekly": "W-FRI", "monthly": "ME"}

_cfg = None
_store = None


# ── wiring ─────────────────────────────────────────────────────────────────────

def configure(db_path=None, **overrides):
    """Point the adapter at a specific archive. Optional — without it the
    normal YDB_* config applies, so `YDB_DB_PATH=... python app.py` is enough."""
    global _cfg, _store
    if _store is not None:
        _store.close()
        _store = None
    _cfg = load_config(db_path=db_path, **overrides)
    return _cfg


def config():
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


def store() -> Store:
    """The shared Store. Flask's dev server is threaded, so each call checks
    the connection belongs to this thread and reopens if not."""
    global _store
    if _store is None:
        _store = Store(config().db_path)
        _store.init_schema()
        _init_watchlist(_store)
    return _store


def init_db():
    """Same name the dashboard calls at startup."""
    store()


def _init_watchlist(st: Store):
    with st.tx() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol     TEXT PRIMARY KEY,
                group_tag  TEXT    NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                added_at   TEXT    NOT NULL
            )
        """)


# ── symbols (database.py-compatible) ───────────────────────────────────────────

def list_symbols() -> list:
    """Watchlist rows, shaped exactly like the dashboard's `symbols` table."""
    st = store()
    rows = st.conn.execute("""
        SELECT w.symbol, w.group_tag, w.sort_order, w.added_at,
               t.name, t.quote_type, t.status, t.delisted_at,
               p.sector AS profile_sector,
               (SELECT MAX(fetched_at) FROM fetch_log f
                 WHERE f.symbol = w.symbol AND f.status = 'ok') AS last_fetch
        FROM watchlist w
        LEFT JOIN tickers  t ON t.symbol = w.symbol
        LEFT JOIN profiles p ON p.symbol = w.symbol
        ORDER BY COALESCE(NULLIF(w.group_tag,''), 'zzz'), w.symbol
    """).fetchall()

    out = []
    for i, r in enumerate(rows, start=1):
        out.append({
            # The frontend uses `id` only as a list key.
            "id": i,
            "symbol": r["symbol"],
            "name": r["name"] or "",
            "sector": r["profile_sector"] or r["quote_type"] or "",
            "added_at": r["added_at"],
            "last_fetch": r["last_fetch"],
            "group_tag": r["group_tag"] or "",
            "sort_order": r["sort_order"],
            # Extra, ignored by the current UI but available to it.
            "status": r["status"] or "unknown",
            "delisted_at": r["delisted_at"],
        })
    return out


def add_symbol(symbol: str, name: str = "", sector: str = "") -> bool:
    """Put a symbol on the watchlist. Returns False if it was already there,
    matching the dashboard's expectation."""
    sym = normalize_symbol(symbol)
    if not sym:
        return False
    st = store()
    exists = st.conn.execute(
        "SELECT 1 FROM watchlist WHERE symbol=?", (sym,)).fetchone()
    if exists:
        return False

    # Register it in the universe too, so a symbol typed into the dashboard is
    # picked up by the next archive run even if no source has listed it.
    st.upsert_tickers([{"symbol": sym, "name": name, "source": "watchlist"}])
    with st.tx() as c:
        c.execute("INSERT INTO watchlist (symbol, added_at) VALUES (?,?)",
                  (sym, utcnow()))
    return True


def remove_symbol(symbol: str):
    """Take a symbol off the watchlist.

    Deliberately does NOT delete its bars: the archive may hold history for a
    company that no longer exists, which Yahoo will not serve again. Use the
    yahoo_db CLI if you really want to drop data.
    """
    with store().tx() as c:
        c.execute("DELETE FROM watchlist WHERE symbol=?",
                  (normalize_symbol(symbol),))


def set_symbol_group(symbol: str, group_tag: str):
    with store().tx() as c:
        c.execute("UPDATE watchlist SET group_tag=? WHERE symbol=?",
                  ((group_tag or "").strip(), normalize_symbol(symbol)))


def update_symbol_info(symbol: str, name: str, sector: str):
    """The archive owns metadata, so this only fills a name the universe is
    missing rather than overwriting what a source or profile established."""
    if not name:
        return
    with store().tx() as c:
        c.execute(
            "UPDATE tickers SET name=? WHERE symbol=? AND COALESCE(name,'')=''",
            (name, normalize_symbol(symbol)))


def update_last_fetch(symbol: str):
    """No-op: fetch_log already records this, and it is what list_symbols
    reads. Kept so the dashboard's calls still resolve."""


def search_symbols(query: str, limit: int = 25, include_delisted: bool = True) -> list:
    """Find symbols in the archive to add to the watchlist.

    The sidebar cannot render a hundred thousand rows, so this is how you get
    at everything the archive holds. Prefix matches rank above substring ones.
    """
    q = (query or "").strip().upper()
    if not q:
        return []
    where = ["(symbol LIKE ? OR UPPER(COALESCE(name,'')) LIKE ?)"]
    params = [f"%{q}%", f"%{q}%"]
    if not include_delisted:
        where.append("status != ?")
        params.append(STATUS_DELISTED)
    rows = store().conn.execute(
        f"""SELECT symbol, name, quote_type, status, delisted_at, has_data
            FROM tickers
            WHERE {' AND '.join(where)}
            ORDER BY (symbol = ?) DESC, (symbol LIKE ?) DESC,
                     has_data DESC, symbol
            LIMIT ?""",
        params + [q, f"{q}%", limit],
    ).fetchall()
    return [dict(r) for r in rows]


# ── bars (database.py-compatible) ──────────────────────────────────────────────

def get_ohlcv(symbol: str, freq: str = "daily", limit: int = 500) -> list:
    """Most recent `limit` bars, oldest first — the dashboard's contract."""
    df = get_ohlcv_df(symbol, freq, limit=limit)
    if df.empty:
        return []
    out = []
    for idx, row in df.iterrows():
        out.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": _num(row.get("open")),
            "high": _num(row.get("high")),
            "low": _num(row.get("low")),
            "close": _num(row.get("close")),
            "volume": _num(row.get("volume")),
            "adj_close": _num(row.get("adj_close")),
        })
    return out


def get_ohlcv_df(symbol: str, freq: str = "daily", limit: int = 1000) -> pd.DataFrame:
    """Bars as a DataFrame indexed by date, columns open/high/low/close/volume.

    Weekly and monthly are resampled from daily unless the archive actually
    holds them, so the dashboard's timeframe toggle works off a daily-only
    archive with no extra download pass.
    """
    sym = normalize_symbol(symbol)
    interval = FREQ_TO_INTERVAL.get(freq, freq)
    st = store()

    df = _read(st, sym, interval, limit)
    if not df.empty or interval == "1d":
        return df

    # Nothing stored at this interval — derive it from the daily series.
    rule = RESAMPLE_RULE.get(freq)
    if rule is None:
        return df
    bars_per = 7 if freq == "weekly" else 31
    daily = _read(st, sym, "1d", limit * bars_per)
    if daily.empty:
        return daily
    resampled = daily.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "adj_close": "last", "volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"])
    return resampled.tail(limit)


def _read(st: Store, symbol: str, interval: str, limit: int) -> pd.DataFrame:
    rows = st.conn.execute(
        """SELECT * FROM (
               SELECT date, open, high, low, close, adj_close, volume
               FROM prices WHERE symbol=? AND interval=?
               ORDER BY date DESC LIMIT ?
           ) ORDER BY date ASC""",
        (symbol, interval, max(1, limit)),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def get_latest_ohlcv_date(symbol: str, freq: str = "daily"):
    return store().last_price_date(symbol, FREQ_TO_INTERVAL.get(freq, freq))


def is_recently_fetched(symbol: str, hours: int = 23) -> bool:
    row = store().conn.execute(
        """SELECT MAX(fetched_at) d FROM fetch_log
           WHERE symbol=? AND status='ok'""",
        (normalize_symbol(symbol),)).fetchone()
    if not row or not row["d"]:
        return False
    try:
        last = datetime.fromisoformat(row["d"])
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last < timedelta(hours=hours)


def upsert_ohlcv(symbol: str, freq: str, df: pd.DataFrame) -> int:
    """Present so any dashboard code that writes bars keeps working."""
    return store().upsert_prices(symbol, FREQ_TO_INTERVAL.get(freq, freq), df)


# ── fetching (data_fetcher.py-compatible) ──────────────────────────────────────

def fetch_and_store(symbol: str, period: str = "2y") -> dict:
    """Refresh one symbol through the archive's downloader.

    Same return shape as data_fetcher.fetch_and_store: symbol/name/sector/
    daily_rows/weekly_rows, or {"symbol", "error"} on failure. `period` is
    accepted for signature compatibility; the archive always fills the gap
    between what it holds and today, which is what the caller wanted anyway.
    """
    return _fetch(symbol)


def fetch_full_history(symbol: str, start: str = "2000-01-01",
                       max_retries: int = 3) -> dict:
    """Same, but forcing a full re-download from `start`."""
    return _fetch(symbol, start=start, force=True, max_retries=max_retries)


def _fetch(symbol: str, start: str = None, force: bool = False,
           max_retries: int = None) -> dict:
    sym = normalize_symbol(symbol)
    if not sym:
        return {"symbol": symbol, "error": "empty symbol"}

    overrides = {}
    if start:
        overrides["history_start"] = start
    if max_retries:
        overrides["max_retries"] = max_retries
    cfg = config().with_overrides(**overrides) if overrides else config()

    st = store()
    st.upsert_tickers([{"symbol": sym, "source": "watchlist"}])
    result = Downloader(cfg, st).run(symbols=[sym], interval="1d",
                                     force=force, single_retry=True)

    if not result.get("ok"):
        error = st.conn.execute(
            """SELECT error FROM fetch_log WHERE symbol=?
               ORDER BY fetched_at DESC, id DESC LIMIT 1""",
            (sym,)).fetchone()
        return {"symbol": sym,
                "error": (error["error"] if error and error["error"]
                          else f"No data returned for {sym}")}

    row = st.conn.execute(
        """SELECT t.name, t.quote_type, p.sector
           FROM tickers t LEFT JOIN profiles p ON p.symbol = t.symbol
           WHERE t.symbol=?""", (sym,)).fetchone()
    weekly = get_ohlcv_df(sym, "weekly", limit=10_000)

    return {
        "symbol": sym,
        "name": (row["name"] if row else "") or "",
        "sector": ((row["sector"] if row else "")
                   or (row["quote_type"] if row else "") or ""),
        "daily_rows": result.get("rows", 0),
        # Derived, not stored — see get_ohlcv_df.
        "weekly_rows": len(weekly),
    }


def _num(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value
