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
    """Open a connection with scale-friendly pragmas applied."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    for name, value in _PRAGMAS:
        conn.execute(f"PRAGMA {name}={value}")
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


def init_db():
    """Create tables and indexes if they don't exist."""
    with connection() as conn:
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

        # Precomputed desk / scanner metrics (dashboard cache)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS symbol_metrics (
                symbol       TEXT PRIMARY KEY,
                ready        INTEGER NOT NULL DEFAULT 0,
                as_of        TEXT,
                updated_at   TEXT    NOT NULL,
                price        REAL,
                change_pct   REAL,
                ret_5d_pct   REAL,
                ret_21d_pct  REAL,
                ret_9m_pct   REAL,
                stage        INTEGER,
                setup_score  INTEGER,
                payload      TEXT    NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_score
            ON symbol_metrics(setup_score DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_ret21
            ON symbol_metrics(ret_21d_pct DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_updated
            ON symbol_metrics(updated_at)
        """)


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
        conn.execute("DELETE FROM symbol_metrics WHERE symbol = ?", (symbol.upper(),))


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


def get_max_ohlcv_date(freq: str = "daily"):
    """Latest bar date across the whole archive (for cache staleness)."""
    with connection() as conn:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM ohlcv WHERE freq = ?",
            (freq,),
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
        metrics_count = 0
        metrics_ready = 0
        metrics_updated = None
        try:
            metrics_count = conn.execute(
                "SELECT COUNT(*) AS n FROM symbol_metrics"
            ).fetchone()["n"]
            metrics_ready = conn.execute(
                "SELECT COUNT(*) AS n FROM symbol_metrics WHERE ready = 1"
            ).fetchone()["n"]
            row = conn.execute(
                "SELECT MAX(updated_at) AS d FROM symbol_metrics"
            ).fetchone()
            metrics_updated = row["d"] if row else None
        except sqlite3.OperationalError:
            pass
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
        "metrics_count": metrics_count,
        "metrics_ready": metrics_ready,
        "metrics_updated_at": metrics_updated,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "page_count": page_count,
        "page_size": page_size,
    }


def upsert_symbol_metrics(rows: list) -> int:
    """
    Bulk upsert precomputed metrics.
    Each row: {symbol, ready, as_of, price, change_pct, ret_5d_pct, ret_21d_pct,
               ret_9m_pct, stage, setup_score, payload(dict|str)}
    """
    import json

    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    with connection() as conn:
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if not sym:
                continue
            payload = r.get("payload")
            if isinstance(payload, dict):
                payload = json.dumps(payload, default=str)
            elif payload is None:
                payload = "{}"
            conn.execute(
                """
                INSERT INTO symbol_metrics (
                    symbol, ready, as_of, updated_at, price, change_pct,
                    ret_5d_pct, ret_21d_pct, ret_9m_pct, stage, setup_score, payload
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                    ready=excluded.ready,
                    as_of=excluded.as_of,
                    updated_at=excluded.updated_at,
                    price=excluded.price,
                    change_pct=excluded.change_pct,
                    ret_5d_pct=excluded.ret_5d_pct,
                    ret_21d_pct=excluded.ret_21d_pct,
                    ret_9m_pct=excluded.ret_9m_pct,
                    stage=excluded.stage,
                    setup_score=excluded.setup_score,
                    payload=excluded.payload
                """,
                (
                    sym,
                    1 if r.get("ready") else 0,
                    r.get("as_of"),
                    r.get("updated_at") or now,
                    r.get("price"),
                    r.get("change_pct"),
                    r.get("ret_5d_pct"),
                    r.get("ret_21d_pct"),
                    r.get("ret_9m_pct"),
                    r.get("stage"),
                    r.get("setup_score"),
                    payload,
                ),
            )
            n += 1
    return n


def get_symbol_metrics(symbol: str) -> dict | None:
    import json
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM symbol_metrics WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d.get("payload") or "{}")
    except Exception:
        d["payload"] = {}
    return d


def get_symbol_metrics_many(symbols: list[str] | None = None, ready_only: bool = True) -> list[dict]:
    """Return metrics rows (payload already decoded)."""
    import json
    with connection() as conn:
        if symbols:
            out = []
            chunk = 400
            syms = [s.upper() for s in symbols]
            for i in range(0, len(syms), chunk):
                part = syms[i:i + chunk]
                placeholders = ",".join("?" * len(part))
                sql = f"SELECT * FROM symbol_metrics WHERE symbol IN ({placeholders})"
                if ready_only:
                    sql += " AND ready = 1"
                rows = conn.execute(sql, part).fetchall()
                out.extend(dict(r) for r in rows)
        else:
            sql = "SELECT * FROM symbol_metrics"
            if ready_only:
                sql += " WHERE ready = 1"
            rows = conn.execute(sql).fetchall()
            out = [dict(r) for r in rows]

    for d in out:
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except Exception:
            d["payload"] = {}
    return out


def metrics_status() -> dict:
    with connection() as conn:
        try:
            total = conn.execute("SELECT COUNT(*) AS n FROM symbol_metrics").fetchone()["n"]
            ready = conn.execute(
                "SELECT COUNT(*) AS n FROM symbol_metrics WHERE ready = 1"
            ).fetchone()["n"]
            updated = conn.execute(
                "SELECT MAX(updated_at) AS d FROM symbol_metrics"
            ).fetchone()["d"]
            as_of = conn.execute(
                "SELECT MAX(as_of) AS d FROM symbol_metrics WHERE ready = 1"
            ).fetchone()["d"]
        except sqlite3.OperationalError:
            return {"total": 0, "ready": 0, "updated_at": None, "as_of": None}
    return {"total": total, "ready": ready, "updated_at": updated, "as_of": as_of}


def clear_symbol_metrics(symbol: str | None = None) -> int:
    with connection() as conn:
        if symbol:
            cur = conn.execute(
                "DELETE FROM symbol_metrics WHERE symbol = ?",
                (symbol.upper(),),
            )
        else:
            cur = conn.execute("DELETE FROM symbol_metrics")
        return cur.rowcount or 0


def optimize_db():
    """Run ANALYZE (and a soft checkpoint) after large bulk loads."""
    with connection() as conn:
        conn.execute("ANALYZE")
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
    return get_db_stats()
