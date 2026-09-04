"""
database.py - SQLite manager for Whats-News / FinDash
Tables:
  - symbols  : tracked tickers with metadata
  - ohlcv    : OHLCV bars (daily + weekly)

Tuned for large watchlists: WAL mode, busy timeout, bulk upserts,
and indexes that keep per-symbol reads fast as the row count grows.
"""

import logging
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "finance.db")

# SQLite pragmas that keep many-ticker workloads responsive
_PRAGMAS = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("temp_store", "MEMORY"),
    ("busy_timeout", "5000"),
    ("cache_size", "-64000"),  # ~64 MiB page cache
    ("foreign_keys", "ON"),
)


def get_connection():
    """Open a connection with scale-friendly pragmas applied.

    An empty ``finance.db`` file (created by a previous connect with no
    ``init_db``) gets tables here so watchlist / news / chart never hit
    ``no such table: symbols``.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    for name, value in _PRAGMAS:
        conn.execute(f"PRAGMA {name}={value}")
    _ensure_schema(conn)
    return conn


@contextmanager
def connection():
    """Context manager that always closes the connection."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _schema_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [r["name"] if isinstance(r, sqlite3.Row) else r[0] for r in rows]


def _create_schema(conn):
    """Idempotent CREATE TABLE / INDEX. Safe on an already-initialized DB."""
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL UNIQUE,
            name        TEXT,
            sector      TEXT,
            added_at    TEXT    NOT NULL,
            last_fetch  TEXT
        )
    """)

    # Migrations — add new columns to existing DBs without data loss
    for col, defn in [
        ("group_tag", "TEXT    DEFAULT ''"),
        ("sort_order", "INTEGER DEFAULT 0"),
    ]:
        try:
            cur.execute(f"ALTER TABLE symbols ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass  # column already exists

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol     TEXT    NOT NULL,
            freq       TEXT    NOT NULL,   -- 'daily' | 'weekly'
            date       TEXT    NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     REAL,
            UNIQUE(symbol, freq, date)
        )
    """)

    # Primary lookup path: symbol + freq + date range / LIMIT
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_freq_date
        ON ohlcv(symbol, freq, date)
    """)
    # Keep the legacy name for older DBs that already have it
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ohlcv
        ON ohlcv(symbol, freq, date)
    """)
    # Watchlist grouping / listing
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_symbols_group_symbol
        ON symbols(group_tag, symbol)
    """)
    # Incremental refresh scans
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_symbols_last_fetch
        ON symbols(last_fetch)
    """)


def _ensure_schema(conn):
    """If this file has no ``symbols`` table, create the full schema now."""
    if "symbols" in _schema_tables(conn):
        return
    _create_schema(conn)
    conn.commit()


def init_db():
    """Create tables and indexes if they don't exist. Idempotent."""
    with connection() as conn:
        _create_schema(conn)


def schema_tables():
    """User table names in the current DB file (health / tests)."""
    with connection() as conn:
        return _schema_tables(conn)


# ── Symbol CRUD ────────────────────────────────────────────────────────────────

def list_symbols():
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM symbols "
            "ORDER BY COALESCE(NULLIF(group_tag,''), 'zzz'), symbol"
        ).fetchall()
    return [dict(r) for r in rows]


def list_symbol_codes():
    """Return just ticker strings — cheaper than list_symbols() at scale."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT symbol FROM symbols ORDER BY symbol"
        ).fetchall()
    return [r["symbol"] for r in rows]


def set_symbol_group(symbol: str, group_tag: str):
    """Set the group tag for a symbol (empty string = no group)."""
    with connection() as conn:
        conn.execute(
            "UPDATE symbols SET group_tag=? WHERE symbol=?",
            (group_tag.strip(), symbol.upper()),
        )


def add_symbol(symbol: str, name: str = "", sector: str = ""):
    with connection() as conn:
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(
                "INSERT INTO symbols (symbol, name, sector, added_at) VALUES (?,?,?,?)",
                (symbol.upper(), name, sector, now),
            )
            return True
        except sqlite3.IntegrityError:
            return False  # already exists


def add_symbols(symbols, name: str = "", sector: str = "") -> dict:
    """
    Bulk-add tickers in one transaction.
    Returns {"added": [...], "skipped": [...]} for symbols that already exist.
    """
    added, skipped = [], []
    now = datetime.now(timezone.utc).isoformat()
    cleaned = []
    seen = set()
    for raw in symbols:
        if not raw or not str(raw).strip():
            continue
        sym = str(raw).strip().upper()
        if sym in seen:
            continue
        seen.add(sym)
        cleaned.append(sym)

    if not cleaned:
        return {"added": [], "skipped": []}

    with connection() as conn:
        for sym in cleaned:
            try:
                conn.execute(
                    "INSERT INTO symbols (symbol, name, sector, added_at) VALUES (?,?,?,?)",
                    (sym, name, sector, now),
                )
                added.append(sym)
            except sqlite3.IntegrityError:
                skipped.append(sym)
    return {"added": added, "skipped": skipped}


def add_universe_symbols(symbol_indices: dict[str, list[str]]) -> dict:
    """
    Register universe tickers with univ:<index> group tags.
    symbol_indices: {symbol: [index_id, ...]} — does not overwrite desk symbols
    (empty group_tag or non-univ tag).
    """
    added, skipped, tagged = [], [], []
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        for sym, indices in symbol_indices.items():
            sym = str(sym).strip().upper()
            if not sym:
                continue
            tag = f"univ:{indices[0]}" if indices else "univ:unknown"
            row = conn.execute(
                "SELECT symbol, group_tag FROM symbols WHERE symbol = ?",
                (sym,),
            ).fetchone()
            if row:
                skipped.append(sym)
                existing_tag = (row["group_tag"] or "").strip()
                if existing_tag.startswith("univ:") and existing_tag != tag:
                    conn.execute(
                        "UPDATE symbols SET group_tag = ? WHERE symbol = ?",
                        (tag, sym),
                    )
                    tagged.append(sym)
                continue
            conn.execute(
                "INSERT INTO symbols (symbol, name, sector, added_at, group_tag) "
                "VALUES (?,?,?,?,?)",
                (sym, "", "", now, tag),
            )
            added.append(sym)
    return {"added": added, "skipped": skipped, "retagged": tagged}


def list_desk_symbols():
    """Trading desk sidebar — excludes univ:* archive-only names."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM symbols "
            "WHERE group_tag IS NULL OR group_tag = '' OR group_tag NOT LIKE 'univ:%' "
            "ORDER BY COALESCE(NULLIF(group_tag,''), 'zzz'), symbol"
        ).fetchall()
    return [dict(r) for r in rows]


def list_symbols_with_ohlcv(freq: str = "daily", min_bars: int = 30) -> list[str]:
    """Symbols with enough stored bars for scanning / charts."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT symbol FROM ohlcv
            WHERE freq = ?
            GROUP BY symbol
            HAVING COUNT(*) >= ?
            ORDER BY symbol
            """,
            (freq, min_bars),
        ).fetchall()
    return [r["symbol"] for r in rows]


def promote_to_desk(symbol: str) -> bool:
    """Move a universe symbol onto the trading desk (clear univ tag)."""
    with connection() as conn:
        cur = conn.execute(
            "UPDATE symbols SET group_tag = '' WHERE symbol = ?",
            (symbol.upper(),),
        )
        return cur.rowcount > 0


def remove_symbol(symbol: str):
    with connection() as conn:
        conn.execute("DELETE FROM symbols WHERE symbol = ?", (symbol.upper(),))
        conn.execute("DELETE FROM ohlcv WHERE symbol = ?", (symbol.upper(),))


def update_last_fetch(symbol: str):
    with connection() as conn:
        conn.execute(
            "UPDATE symbols SET last_fetch = ? WHERE symbol = ?",
            (datetime.now(timezone.utc).isoformat(), symbol.upper()),
        )


def update_symbol_info(symbol: str, name: str, sector: str):
    """Update the name and sector metadata for an existing symbol."""
    with connection() as conn:
        conn.execute(
            "UPDATE symbols SET name = ?, sector = ? WHERE symbol = ?",
            (name, sector, symbol.upper()),
        )


# ── OHLCV CRUD ─────────────────────────────────────────────────────────────────

def upsert_ohlcv(symbol: str, freq: str, df: pd.DataFrame):
    """
    Upsert OHLCV rows from a DataFrame.
    df must have columns: open, high, low, close, volume
    df index must be datetime.

    Uses vectorized prep + a single executemany (not iterrows) so bulk
    loads of hundreds of tickers stay practical.
    """
    if df is None or df.empty:
        return 0

    sym = symbol.upper()
    required = ("open", "high", "low", "close", "volume")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"upsert_ohlcv missing columns: {missing}")

    work = df.loc[:, list(required)].copy()
    work = work.dropna(how="any")
    if work.empty:
        return 0

    # ISO date strings sort correctly and match existing schema
    idx = pd.to_datetime(work.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    dates = idx.strftime("%Y-%m-%d")
    opens = work["open"].astype(float).to_numpy()
    highs = work["high"].astype(float).to_numpy()
    lows = work["low"].astype(float).to_numpy()
    closes = work["close"].astype(float).to_numpy()
    volumes = work["volume"].astype(float).to_numpy()

    params = list(
        zip(
            [sym] * len(dates),
            [freq] * len(dates),
            dates.tolist(),
            opens.tolist(),
            highs.tolist(),
            lows.tolist(),
            closes.tolist(),
            volumes.tolist(),
        )
    )

    with connection() as conn:
        conn.executemany(
            """
            INSERT INTO ohlcv (symbol, freq, date, open, high, low, close, volume)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol, freq, date) DO UPDATE SET
                open   = excluded.open,
                high   = excluded.high,
                low    = excluded.low,
                close  = excluded.close,
                volume = excluded.volume
            """,
            params,
        )
    return len(params)


def get_ohlcv(symbol: str, freq: str = "daily", limit: int = 500) -> list:
    """Fetch the most recent N rows, returned in ascending date order."""
    with connection() as conn:
        # Latest N rows, then chronological order for charts
        query = """
            SELECT * FROM (
                SELECT date, open, high, low, close, volume
                FROM ohlcv
                WHERE symbol = ? AND freq = ?
                ORDER BY date DESC
                LIMIT ?
            ) ORDER BY date ASC
        """
        rows = conn.execute(query, (symbol.upper(), freq, limit)).fetchall()
    return [dict(r) for r in rows]


def get_ohlcv_df(symbol: str, freq: str = "daily", limit: int = 1000) -> pd.DataFrame:
    rows = get_ohlcv(symbol, freq, limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    return df


def is_recently_fetched(symbol: str, hours: int = 23) -> bool:
    """Return True if symbol was fetched within the last N hours."""
    with connection() as conn:
        row = conn.execute(
            "SELECT last_fetch FROM symbols WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
    if not row or not row["last_fetch"]:
        return False
    last = datetime.fromisoformat(row["last_fetch"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last < timedelta(hours=hours)


def get_latest_ohlcv_date(symbol: str, freq: str = "daily"):
    """Return the most recent date string in the ohlcv table, or None."""
    with connection() as conn:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM ohlcv WHERE symbol = ? AND freq = ?",
            (symbol.upper(), freq),
        ).fetchone()
    return row["d"] if row and row["d"] else None


def get_db_stats() -> dict:
    """
    Lightweight health snapshot for large watchlists.
    Useful for the Data Manager UI / ops checks.
    """
    with connection() as conn:
        symbol_count = conn.execute("SELECT COUNT(*) AS n FROM symbols").fetchone()["n"]
        ohlcv_count = conn.execute("SELECT COUNT(*) AS n FROM ohlcv").fetchone()["n"]
        daily_count = conn.execute(
            "SELECT COUNT(*) AS n FROM ohlcv WHERE freq = 'daily'"
        ).fetchone()["n"]
        weekly_count = conn.execute(
            "SELECT COUNT(*) AS n FROM ohlcv WHERE freq = 'weekly'"
        ).fetchone()["n"]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]

    size_bytes = 0
    if os.path.exists(DB_PATH):
        size_bytes = os.path.getsize(DB_PATH)
        for suffix in ("-wal", "-shm"):
            side = DB_PATH + suffix
            if os.path.exists(side):
                size_bytes += os.path.getsize(side)

    return {
        "path": DB_PATH,
        "journal_mode": journal,
        "symbol_count": symbol_count,
        "ohlcv_rows": ohlcv_count,
        "daily_rows": daily_count,
        "weekly_rows": weekly_count,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "page_count": page_count,
        "page_size": page_size,
    }


def optimize_db():
    """Run ANALYZE (and a soft checkpoint) after large bulk loads."""
    with connection() as conn:
        conn.execute("ANALYZE")
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
    return get_db_stats()
