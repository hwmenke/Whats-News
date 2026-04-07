"""
database.py - SQLite manager for the Financial Dashboard
Tables:
  - symbols  : tracked tickers with metadata
  - ohlcv    : OHLCV bars (daily + weekly)
"""

import sqlite3
import os
import pandas as pd
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "finance.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
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

    conn.commit()
    conn.close()


# ── Symbol CRUD ────────────────────────────────────────────────────────────────

def list_symbols():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM symbols ORDER BY symbol").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_symbol(symbol: str, name: str = "", sector: str = ""):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
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
    conn = get_connection()
    conn.execute("DELETE FROM symbols WHERE symbol = ?", (symbol.upper(),))
    conn.execute("DELETE FROM ohlcv WHERE symbol = ?", (symbol.upper(),))
    conn.commit()
    conn.close()


def update_last_fetch(symbol: str):
    conn = get_connection()
    conn.execute(
        "UPDATE symbols SET last_fetch = ? WHERE symbol = ?",
        (datetime.utcnow().isoformat(), symbol.upper())
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
    rows_inserted = 0
    for date_idx, row in df.iterrows():
        date_str = date_idx.strftime("%Y-%m-%d")
        try:
            conn.execute(
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
                (sym, freq, date_str,
                 float(row["open"]), float(row["high"]),
                 float(row["low"]),  float(row["close"]),
                 float(row["volume"]))
            )
            rows_inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return rows_inserted


def get_ohlcv(symbol: str, freq: str = "daily", limit: int = 500) -> list:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM ohlcv
        WHERE symbol = ? AND freq = ?
        ORDER BY date ASC
        LIMIT ?
        """,
        (symbol.upper(), freq, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ohlcv_df(symbol: str, freq: str = "daily") -> pd.DataFrame:
    rows = get_ohlcv(symbol, freq, limit=1000)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    return df
