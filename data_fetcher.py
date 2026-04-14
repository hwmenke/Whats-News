"""
data_fetcher.py - Download OHLCV from Yahoo Finance and store in DB
Supports incremental fetching: only downloads bars newer than what's in the DB.
"""

import datetime
import yfinance as yf
import pandas as pd
import database as db


def _clean_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance output to lowercase columns and drop NaN rows."""
    print(f"-- Fetcher: Normalizing {len(raw)} rows of raw data")
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]

    # yfinance sometimes returns MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        print("-- Fetcher: Detected MultiIndex columns, flattening...")
        df.columns = [c[0].lower() for c in df.columns]

    # Ensure required columns exist
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"!! Fetcher: Missing columns {missing}. Available: {df.columns.tolist()}")
        # Fallback for common yfinance naming variations
        if "adj close" in df.columns and "close" not in df.columns:
            df["close"] = df["adj close"]
    
    # Final filter
    available = [c for c in required if c in df.columns]
    df = df[available]
    df.dropna(inplace=True)
    df.index = pd.to_datetime(df.index)
    df.index = df.index.tz_localize(None)
    return df


def fetch_and_store(symbol: str, period: str = "2y") -> dict:
    """
    Download daily data from Yahoo Finance, resample to weekly,
    and upsert both into the database.
    If data already exists in the DB, only downloads bars from last_date + 1 day
    forward (incremental mode). Falls back to full 2y download if no data exists.
    """
    sym = symbol.upper()
    print(f"++ Fetcher: Starting fetch for {sym}")
    ticker = yf.Ticker(sym)

    # Check if we have existing data and can do an incremental fetch
    last_date_str = db.get_latest_ohlcv_date(sym, "daily")
    if last_date_str:
        last_date  = datetime.date.fromisoformat(last_date_str)
        start_date = last_date + datetime.timedelta(days=1)
        start_str  = start_date.isoformat()
        print(f"++ Fetcher: Incremental fetch for {sym} from {start_str}")
        raw = ticker.history(start=start_str, interval="1d", auto_adjust=True)
    else:
        print(f"++ Fetcher: Full {period} download for {sym}")
        raw = ticker.history(period=period, interval="1d", auto_adjust=True)

    if raw.empty:
        print(f"!! Fetcher: No data returned for {sym}")
        return {"symbol": sym, "error": f"No data returned for {sym}"}

    daily_df = _clean_df(raw)
    print(f"++ Fetcher: Processed {len(daily_df)} daily bars")

    # Resample to weekly (week ending Friday)
    weekly_df = daily_df.resample("W-FRI").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum"
    }).dropna()
    print(f"++ Fetcher: Resampled to {len(weekly_df)} weekly bars")

    daily_count  = db.upsert_ohlcv(sym, "daily",  daily_df)
    weekly_count = db.upsert_ohlcv(sym, "weekly", weekly_df)
    print(f"++ Fetcher: Database updated ({daily_count}d, {weekly_count}w)")

    # Pull meta info (name, sector) - try/except as this can be slow/fail
    name, sector = "", ""
    try:
        print(f"++ Fetcher: Requesting ticker.info for {sym}...")
        info   = ticker.info
        name   = info.get("longName", "")
        sector = info.get("sector", f"{info.get('industry', '')}").strip()
        print(f"++ Fetcher: Info retrieved: {name} ({sector})")
    except Exception as e:
        print(f"!! Fetcher: Metadata download failed (skipped): {str(e)}")

    db.update_symbol_info(sym, name, sector)
    db.update_last_fetch(sym)

    return {
        "symbol":       sym,
        "name":         name,
        "sector":       sector,
        "daily_rows":   daily_count,
        "weekly_rows":  weekly_count,
    }
