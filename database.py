"""
database.py - SQLite manager for the Financial Dashboard
Tables:
  - symbols  : tracked tickers with metadata
  - ohlcv    : OHLCV bars (daily + weekly)
"""

import json
import logging
import sqlite3
import os
import pandas as pd
from datetime import datetime, timezone
import indicator_cache as cache

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "finance.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol         TEXT    NOT NULL UNIQUE,
            name           TEXT,
            sector         TEXT,
            added_at       TEXT    NOT NULL,
            last_fetch     TEXT,
            quality_report TEXT
        )
    """)
    # Migrate existing databases that lack the quality_report column
    existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(symbols)").fetchall()]
    if "quality_report" not in existing_cols:
        cur.execute("ALTER TABLE symbols ADD COLUMN quality_report TEXT")

    # Migrations — add new columns to existing DBs without data loss
    for col, defn in [
        ('group_tag',     "TEXT    DEFAULT ''"),
        ('sort_order',    'INTEGER DEFAULT 0'),
        ('notes',         "TEXT    DEFAULT ''"),
        ('next_earnings', 'TEXT'),
        ('watchlist_tier','TEXT    DEFAULT "watchlist"'),
        ('setup_grade',   "TEXT    DEFAULT ''"),
    ]:
        try:
            cur.execute(f"ALTER TABLE symbols ADD COLUMN {col} {defn}")
        except Exception:
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

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ohlcv ON ohlcv(symbol, freq, date)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals (
            symbol     TEXT PRIMARY KEY,
            data       TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol       TEXT    NOT NULL,
            field        TEXT    NOT NULL,
            condition    TEXT    NOT NULL,
            threshold    REAL    NOT NULL,
            triggered_at TEXT,
            created_at   TEXT    NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            qty         REAL NOT NULL,
            entry_price REAL NOT NULL,
            opened_at   TEXT NOT NULL,
            closed_at   TEXT,
            exit_price  REAL,
            notes       TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL,
            direction   TEXT NOT NULL DEFAULT 'long',
            entry_date  TEXT NOT NULL,
            exit_date   TEXT,
            entry_price REAL NOT NULL,
            exit_price  REAL,
            qty         REAL NOT NULL DEFAULT 1,
            setup       TEXT DEFAULT '',
            tags        TEXT DEFAULT '',
            thesis      TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        )
    """)

    # Enhanced journal columns for trade process tracking.
    # Must run AFTER the CREATE TABLE above so fresh databases get them too.
    for col, defn in [
        ('setup_grade',    "TEXT    DEFAULT ''"),
        ('market_regime',  "TEXT    DEFAULT ''"),
        ('entry_rvol',     'REAL'),
        ('lod_dist_atr',   'REAL'),
        ('mistake_tags',   "TEXT    DEFAULT ''"),
        ('stop_loss',      'REAL'),
        ('review_grade',    "TEXT DEFAULT ''"),
        ('review_mistakes', "TEXT DEFAULT ''"),
        ('review_lesson',   "TEXT DEFAULT ''"),
        ('mae_r',           'REAL'),
        ('mfe_r',           'REAL'),
        # Setup context snapshot for edge attribution analytics
        ('pattern',        "TEXT DEFAULT ''"),
        ('trigger_status', "TEXT DEFAULT ''"),
        ('readiness',      'INTEGER'),
        ('rs_rank',        'INTEGER'),
    ]:
        try:
            cur.execute(f"ALTER TABLE journal ADD COLUMN {col} {defn}")
        except Exception:
            pass  # column already exists

    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategies (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            conditions TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_diary (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT NOT NULL UNIQUE,
            regime_state  TEXT DEFAULT '',
            risk_pedal    TEXT DEFAULT '',
            breadth_pct20 REAL,
            breadth_pct50 REAL,
            new_highs     INTEGER,
            new_lows      INTEGER,
            notes         TEXT DEFAULT '',
            created_at    TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_plans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT NOT NULL UNIQUE,
            trigger_price REAL,
            stop_price    REAL,
            trigger_type  TEXT DEFAULT '',
            notes         TEXT DEFAULT '',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sector_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            sector     TEXT NOT NULL,
            avg_5d     REAL,
            avg_20d    REAL,
            rs_rank    INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(date, sector)
        )
    """)

    conn.commit()
    conn.close()


def get_setting(key: str, default: str = None):
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))
    conn.commit()
    conn.close()


# ── Sector History ────────────────────────────────────────────────────────────

def save_sector_snapshot(snapshot_date: str, sectors: list) -> None:
    """Persist sector performance snapshot for rotation analysis.

    sectors = [{"sector": str, "avg_5d": float, "avg_20d": float, "rs_rank": int}]
    """
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    for s in sectors:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sector_history "
                "(date, sector, avg_5d, avg_20d, rs_rank, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (snapshot_date, s["sector"],
                 s.get("avg_5d"), s.get("avg_20d"), s.get("rs_rank"), now)
            )
        except Exception:
            pass
    conn.commit()
    conn.close()


def get_sector_history(days: int = 30) -> list:
    """Return sector_history rows from the last N days, newest first."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, sector, avg_5d, avg_20d, rs_rank "
        "FROM sector_history WHERE date >= ? ORDER BY date DESC, sector",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Symbol CRUD ────────────────────────────────────────────────────────────────

def list_symbols():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM symbols ORDER BY COALESCE(NULLIF(group_tag,''), 'zzz'), symbol"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_symbol_group(symbol: str, group_tag: str):
    """Set the group tag for a symbol (empty string = no group)."""
    conn = get_connection()
    conn.execute(
        "UPDATE symbols SET group_tag=? WHERE symbol=?",
        (group_tag.strip(), symbol.upper())
    )
    conn.commit()
    conn.close()


def add_symbol(symbol: str, name: str = "", sector: str = ""):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO symbols (symbol, name, sector, added_at) VALUES (?,?,?,?)",
            (symbol.upper(), name, sector, now)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False       # already exists
    finally:
        conn.close()


def remove_symbol(symbol: str):
    sym = symbol.upper()
    conn = get_connection()
    conn.execute("DELETE FROM symbols WHERE symbol = ?", (sym,))
    conn.execute("DELETE FROM ohlcv WHERE symbol = ?", (sym,))
    conn.commit()
    conn.close()
    cache.bump_version(sym)


def update_last_fetch(symbol: str):
    conn = get_connection()
    conn.execute(
        "UPDATE symbols SET last_fetch = ? WHERE symbol = ?",
        (datetime.now(timezone.utc).isoformat(), symbol.upper())
    )
    conn.commit()
    conn.close()


def update_quality_report(symbol: str, report: dict):
    conn = get_connection()
    conn.execute(
        "UPDATE symbols SET quality_report = ? WHERE symbol = ?",
        (json.dumps(report), symbol.upper())
    )
    conn.commit()
    conn.close()


def get_quality_report(symbol: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT quality_report FROM symbols WHERE symbol = ?",
        (symbol.upper(),)
    ).fetchone()
    conn.close()
    if row is None or row["quality_report"] is None:
        return None
    try:
        return json.loads(row["quality_report"])
    except Exception:
        return None


def update_symbol_info(symbol: str, name: str, sector: str):
    """Update the name and sector metadata for an existing symbol."""
    conn = get_connection()
    conn.execute(
        "UPDATE symbols SET name = ?, sector = ? WHERE symbol = ?",
        (name, sector, symbol.upper())
    )
    conn.commit()
    conn.close()


# ── OHLCV CRUD ─────────────────────────────────────────────────────────────────

def upsert_ohlcv(symbol: str, freq: str, df: pd.DataFrame):
    """
    Upsert OHLCV rows from a DataFrame.
    df must have columns: open, high, low, close, volume
    df index must be datetime.
    """
    conn = get_connection()
    sym = symbol.upper()
    params = []
    for date_idx, row in df.iterrows():
        date_str = date_idx.strftime("%Y-%m-%d")
        try:
            params.append((
                sym, freq, date_str,
                float(row["open"]), float(row["high"]),
                float(row["low"]),  float(row["close"]),
                float(row["volume"])
            ))
        except Exception as exc:
            logger.warning("upsert_ohlcv skipped row %s %s %s: %s", sym, freq, date_str, exc)

    if params:
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
            params
        )
    conn.commit()
    conn.close()
    return len(params)


def get_ohlcv(symbol: str, freq: str = "daily", limit: int = 500) -> list:
    """Fetch the most recent N rows, returned in ascending date order."""
    conn = get_connection()
    # To get the latest rows but keep them in chronological order, 
    # we select DESC then wrap and sort ASC.
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
    conn.close()
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
    conn = get_connection()
    row = conn.execute(
        "SELECT last_fetch FROM symbols WHERE symbol = ?", (symbol.upper(),)
    ).fetchone()
    conn.close()
    if not row or not row["last_fetch"]:
        return False
    from datetime import timedelta
    last = datetime.fromisoformat(row["last_fetch"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last < timedelta(hours=hours)


def get_latest_ohlcv_date(symbol: str, freq: str = "daily"):
    """Return the most recent date string in the ohlcv table, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(date) AS d FROM ohlcv WHERE symbol = ? AND freq = ?",
        (symbol.upper(), freq)
    ).fetchone()
    conn.close()
    return row["d"] if row and row["d"] else None


def set_symbol_notes(symbol: str, notes: str):
    conn = get_connection()
    conn.execute(
        "UPDATE symbols SET notes=? WHERE symbol=?",
        (notes, symbol.upper())
    )
    conn.commit()
    conn.close()


# ── Fundamentals ───────────────────────────────────────────────────────────────

def upsert_fundamentals(symbol: str, data: dict):
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO fundamentals (symbol, data, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at
        """,
        (symbol.upper(), json.dumps(data), now)
    )
    conn.commit()
    conn.close()


def get_fundamentals(symbol: str):
    conn = get_connection()
    row  = conn.execute(
        "SELECT data, fetched_at FROM fundamentals WHERE symbol = ?",
        (symbol.upper(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"data": json.loads(row["data"]), "fetched_at": row["fetched_at"]}


# ── Alerts CRUD ────────────────────────────────────────────────────────────────

def list_alerts(symbol: str = None) -> list:
    conn = get_connection()
    if symbol:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE symbol=? ORDER BY created_at DESC",
            (symbol.upper(),)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY symbol, created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_alert(symbol: str, field: str, condition: str, threshold: float) -> int:
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    cur  = conn.execute(
        "INSERT INTO alerts (symbol, field, condition, threshold, created_at) VALUES (?,?,?,?,?)",
        (symbol.upper(), field, condition, threshold, now)
    )
    alert_id = cur.lastrowid
    conn.commit()
    conn.close()
    return alert_id


def delete_alert(alert_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


def mark_alert_triggered(alert_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE alerts SET triggered_at=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(), alert_id)
    )
    conn.commit()
    conn.close()


def reset_alert(alert_id: int):
    conn = get_connection()
    conn.execute("UPDATE alerts SET triggered_at=NULL WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()


# ── Positions CRUD ─────────────────────────────────────────────────────────────

def list_positions(include_closed: bool = True) -> list:
    conn = get_connection()
    if include_closed:
        rows = conn.execute(
            "SELECT * FROM positions ORDER BY symbol, opened_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM positions WHERE closed_at IS NULL ORDER BY symbol, opened_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_position(symbol: str, qty: float, entry_price: float,
                 opened_at: str = None, notes: str = "") -> int:
    conn = get_connection()
    opened_at = opened_at or datetime.now(timezone.utc).date().isoformat()
    cur = conn.execute(
        "INSERT INTO positions (symbol, qty, entry_price, opened_at, notes) VALUES (?,?,?,?,?)",
        (symbol.upper(), qty, entry_price, opened_at, notes)
    )
    pos_id = cur.lastrowid
    conn.commit()
    conn.close()
    return pos_id


def update_position(pos_id: int, **kwargs):
    allowed = {"qty", "entry_price", "opened_at", "closed_at", "exit_price", "notes"}
    fields  = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn = get_connection()
    conn.execute(
        f"UPDATE positions SET {set_clause} WHERE id=?",
        (*fields.values(), pos_id)
    )
    conn.commit()
    conn.close()


def delete_position(pos_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
    conn.commit()
    conn.close()


# ── Journal CRUD ───────────────────────────────────────────────────────────────

def list_journal(symbol: str = None, tag: str = None) -> list:
    conn = get_connection()
    if symbol:
        rows = conn.execute(
            "SELECT * FROM journal WHERE symbol=? ORDER BY entry_date DESC",
            (symbol.upper(),)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM journal ORDER BY entry_date DESC").fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    if tag:
        result = [r for r in result if tag.lower() in (r.get("tags") or "").lower()]
    return result


def add_journal_entry(symbol: str, direction: str, entry_date: str, entry_price: float,
                      qty: float = 1, exit_date: str = None, exit_price: float = None,
                      stop_loss: float = None,
                      setup: str = "", tags: str = "", thesis: str = "",
                      market_regime: str = "", entry_rvol: float = None,
                      lod_dist_atr: float = None,
                      mae_r: float = None, mfe_r: float = None,
                      pattern: str = "", trigger_status: str = "",
                      readiness: int = None, rs_rank: int = None) -> int:
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    cur  = conn.execute(
        """INSERT INTO journal
           (symbol, direction, entry_date, exit_date, entry_price, exit_price,
            stop_loss, qty, setup, tags, thesis,
            market_regime, entry_rvol, lod_dist_atr, mae_r, mfe_r,
            pattern, trigger_status, readiness, rs_rank, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol.upper(), direction, entry_date, exit_date,
         float(entry_price),
         float(exit_price) if exit_price is not None else None,
         float(stop_loss) if stop_loss is not None else None,
         float(qty), setup, tags, thesis,
         market_regime,
         float(entry_rvol) if entry_rvol is not None else None,
         float(lod_dist_atr) if lod_dist_atr is not None else None,
         float(mae_r) if mae_r is not None else None,
         float(mfe_r) if mfe_r is not None else None,
         pattern or "", trigger_status or "",
         int(readiness) if readiness is not None else None,
         int(rs_rank)   if rs_rank   is not None else None,
         now)
    )
    jid = cur.lastrowid
    conn.commit()
    conn.close()
    return jid


def update_journal_entry(entry_id: int, **kwargs):
    allowed = {"direction", "entry_date", "exit_date", "entry_price",
               "exit_price", "stop_loss", "qty", "setup", "tags", "thesis",
               "review_grade", "review_mistakes", "review_lesson",
               "market_regime", "entry_rvol", "lod_dist_atr", "mae_r", "mfe_r",
               "pattern", "trigger_status", "readiness", "rs_rank"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn = get_connection()
    conn.execute(f"UPDATE journal SET {set_clause} WHERE id=?",
                 (*fields.values(), entry_id))
    conn.commit()
    conn.close()


def delete_journal_entry(entry_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM journal WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()


# ── Strategies CRUD ────────────────────────────────────────────────────────────

def list_strategies() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM strategies ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_strategy(name: str, conditions: list) -> int:
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    cur  = conn.execute(
        "INSERT INTO strategies (name, conditions, created_at, updated_at) VALUES (?,?,?,?)",
        (name, json.dumps(conditions), now, now)
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def update_strategy(strategy_id: int, name: str = None, conditions: list = None):
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    if name is not None and conditions is not None:
        conn.execute(
            "UPDATE strategies SET name=?, conditions=?, updated_at=? WHERE id=?",
            (name, json.dumps(conditions), now, strategy_id)
        )
    elif name is not None:
        conn.execute("UPDATE strategies SET name=?, updated_at=? WHERE id=?",
                     (name, now, strategy_id))
    elif conditions is not None:
        conn.execute("UPDATE strategies SET conditions=?, updated_at=? WHERE id=?",
                     (json.dumps(conditions), now, strategy_id))
    conn.commit()
    conn.close()


def delete_strategy(strategy_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM strategies WHERE id=?", (strategy_id,))
    conn.commit()
    conn.close()


# ── Watchlist Tier (focus pipeline) ───────────────────────────────────────────

VALID_TIERS = {"back_watchlist", "watchlist", "stalk", "focus", "active"}

def get_symbol_tier(symbol: str) -> str:
    conn = get_connection()
    row  = conn.execute("SELECT watchlist_tier FROM symbols WHERE symbol=?", (symbol.upper(),)).fetchone()
    conn.close()
    return (row["watchlist_tier"] or "watchlist") if row else "watchlist"


def set_symbol_tier(symbol: str, tier: str) -> bool:
    if tier not in VALID_TIERS:
        return False
    conn = get_connection()
    conn.execute("UPDATE symbols SET watchlist_tier=? WHERE symbol=?", (tier, symbol.upper()))
    conn.commit()
    conn.close()
    return True


def set_setup_grade(symbol: str, grade: str):
    conn = get_connection()
    conn.execute("UPDATE symbols SET setup_grade=? WHERE symbol=?", (grade, symbol.upper()))
    conn.commit()
    conn.close()


def list_symbols_by_tier() -> dict:
    """Return {tier: [symbol_rows]} for the focus pipeline."""
    conn  = get_connection()
    rows  = conn.execute("SELECT * FROM symbols ORDER BY symbol").fetchall()
    conn.close()
    result = {t: [] for t in ("back_watchlist", "watchlist", "stalk", "focus", "active")}
    for r in rows:
        tier = r["watchlist_tier"] or "watchlist"
        if tier not in result:
            tier = "watchlist"
        result[tier].append(dict(r))
    return result


# ── Market Diary CRUD ─────────────────────────────────────────────────────────

def list_diary(limit: int = 60) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM market_diary ORDER BY date DESC LIMIT ?", (int(limit),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_diary_entry(date: str, regime_state: str = "", risk_pedal: str = "",
                       breadth_pct20: float = None, breadth_pct50: float = None,
                       new_highs: int = None, new_lows: int = None,
                       notes: str = "") -> None:
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO market_diary
           (date, regime_state, risk_pedal, breadth_pct20, breadth_pct50,
            new_highs, new_lows, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
             regime_state=excluded.regime_state,
             risk_pedal=excluded.risk_pedal,
             breadth_pct20=excluded.breadth_pct20,
             breadth_pct50=excluded.breadth_pct50,
             new_highs=excluded.new_highs,
             new_lows=excluded.new_lows,
             notes=excluded.notes""",
        (date, regime_state, risk_pedal,
         float(breadth_pct20) if breadth_pct20 is not None else None,
         float(breadth_pct50) if breadth_pct50 is not None else None,
         int(new_highs) if new_highs is not None else None,
         int(new_lows)  if new_lows  is not None else None,
         notes, now)
    )
    conn.commit()
    conn.close()


def delete_diary_entry(date: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM market_diary WHERE date=?", (date,))
    conn.commit()
    conn.close()


# ── Trade Plans CRUD (focus-list entry planner) ───────────────────────────────

def list_trade_plans() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM trade_plans ORDER BY symbol").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_trade_plan(symbol: str, trigger_price: float = None,
                      stop_price: float = None, trigger_type: str = "",
                      notes: str = "") -> None:
    conn = get_connection()
    now  = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO trade_plans
           (symbol, trigger_price, stop_price, trigger_type, notes,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET
             trigger_price=excluded.trigger_price,
             stop_price=excluded.stop_price,
             trigger_type=excluded.trigger_type,
             notes=excluded.notes,
             updated_at=excluded.updated_at""",
        (symbol.upper(),
         float(trigger_price) if trigger_price is not None else None,
         float(stop_price)    if stop_price    is not None else None,
         trigger_type, notes, now, now)
    )
    conn.commit()
    conn.close()


def delete_trade_plan(symbol: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM trade_plans WHERE symbol=?", (symbol.upper(),))
    conn.commit()
    conn.close()
