"""
data_fetcher.py - Download OHLCV from Yahoo Finance and store in DB
"""

import yfinance as yf
import pandas as pd
import database as db


def _clean_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance output to lowercase columns and drop NaN rows."""
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]
    # yfinance sometimes returns MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]]
    df.dropna(inplace=True)
    df.index = pd.to_datetime(df.index)
    df.index = df.index.tz_localize(None)
    return df


def fetch_and_store(symbol: str, period: str = "2y") -> dict:
    """
    Download daily data from Yahoo Finance, resample to weekly,
    and upsert both into the database.
    Returns a dict with row counts.
    """
    sym = symbol.upper()
    ticker = yf.Ticker(sym)

    # Fetch daily OHLCV
    raw = ticker.history(period=period, interval="1d", auto_adjust=True)
    if raw.empty:
        return {"symbol": sym, "error": f"No data returned for {sym}"}

    daily_df = _clean_df(raw)

    # Resample to weekly (week ending Friday, use last close, sum volume)
    weekly_df = daily_df.resample("W-FRI").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum"
    }).dropna()

    daily_count  = db.upsert_ohlcv(sym, "daily",  daily_df)
    weekly_count = db.upsert_ohlcv(sym, "weekly", weekly_df)

    # Pull meta info (name, sector)
    try:
        info   = ticker.info
        name   = info.get("longName", "")
        sector = info.get("sector", "")
    except Exception:
        name, sector = "", ""

    db.update_symbol_info(sym, name, sector)

    db.update_last_fetch(sym)

    return {
        "symbol":       sym,
        "name":         name,
        "sector":       sector,
        "daily_rows":   daily_count,
        "weekly_rows":  weekly_count,
    }
