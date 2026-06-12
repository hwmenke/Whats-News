"""
data_fetcher.py - Download OHLCV from Yahoo Finance and store in DB
Supports incremental fetching: only downloads bars newer than what's in the DB.
"""

import datetime
import time
import yfinance as yf
import numpy as np
import pandas as pd
import database as db
import indicator_cache as cache
import data_quality as dq


def _clean_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance output to lowercase columns and drop NaN rows."""
    print(f"-- Fetcher: Normalizing {len(raw)} rows of raw data")
    df = raw.copy()

    # yfinance sometimes returns MultiIndex columns — must check before lowercasing
    if isinstance(df.columns, pd.MultiIndex):
        print("-- Fetcher: Detected MultiIndex columns, flattening...")
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

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
    # Indices (e.g. ^VIX) often have volume=0/NaN — fill rather than drop
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0.0)
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

    quality = dq.validate(daily_df, "daily")
    db.upsert_ohlcv(sym, "daily",  daily_df)
    db.upsert_ohlcv(sym, "weekly", weekly_df)
    daily_count  = len(daily_df)
    weekly_count = len(weekly_df)
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
    db.update_quality_report(sym, quality)
    cache.bump_version(sym)

    return {
        "symbol":        sym,
        "name":          name,
        "sector":        sector,
        "daily_rows":    daily_count,
        "weekly_rows":   weekly_count,
        "data_quality":  quality,
    }


def fetch_full_history(symbol: str, start: str = "2000-01-01",
                       max_retries: int = 3) -> dict:
    """
    Download full daily history from `start` date to today.
    Resamples to weekly (W-FRI) and monthly (ME).
    Retries with exponential back-off (5s, 10s, 20s) on failure.
    Returns a result dict with keys: symbol, daily_rows, weekly_rows, error (on failure).
    """
    sym   = symbol.upper()
    delay = 5  # initial retry delay seconds

    for attempt in range(1, max_retries + 1):
        try:
            print(f"++ Fetcher: Full-history fetch for {sym} (attempt {attempt})")
            ticker = yf.Ticker(sym)

            raw = ticker.history(start=start, interval="1d", auto_adjust=True)
            if raw.empty:
                print(f"!! Fetcher: No data for {sym}")
                return {"symbol": sym, "error": f"No data returned for {sym}"}

            daily_df = _clean_df(raw)
            print(f"++ Fetcher: {len(daily_df)} daily bars from {start}")

            # Weekly (week ending Friday)
            weekly_df = daily_df.resample("W-FRI").agg({
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
            }).dropna()

            quality = dq.validate(daily_df, "daily")
            db.upsert_ohlcv(sym, "daily",  daily_df)
            db.upsert_ohlcv(sym, "weekly", weekly_df)
            daily_count  = len(daily_df)
            weekly_count = len(weekly_df)
            print(f"++ Fetcher: Stored {daily_count}d / {weekly_count}w for {sym}")

            # Metadata (best-effort)
            name, sector = "", ""
            try:
                info   = ticker.info
                name   = info.get("longName", "")
                sector = info.get("sector", info.get("industry", "")).strip()
            except Exception:
                pass

            db.update_symbol_info(sym, name, sector)
            db.update_last_fetch(sym)
            db.update_quality_report(sym, quality)
            cache.bump_version(sym)
            return {
                "symbol":      sym,
                "name":        name,
                "sector":      sector,
                "daily_rows":  daily_count,
                "weekly_rows": weekly_count,
            }

        except Exception as exc:
            print(f"!! Fetcher: Attempt {attempt} failed for {sym}: {exc}")
            if attempt < max_retries:
                print(f"   Retrying in {delay}s …")
                time.sleep(delay)
                delay *= 2
            else:
                return {"symbol": sym, "error": str(exc)}


def fetch_ratio_and_store(sym_a: str, sym_b: str) -> dict:
    """
    Compute a synthetic OHLCV ratio series for A/B using existing DB data.

    OHLCV construction:
      open  = open_A  / open_B
      close = close_A / close_B
      high  = high_A  / low_B    (conservative upper bound of intraday ratio)
      low   = low_A   / high_B   (conservative lower bound of intraday ratio)
      volume = 0

    Stores the result as symbol "A~B" in the ohlcv table (daily + weekly).
    The tilde separator avoids URL-routing issues with slash characters.
    """
    sym_a     = sym_a.upper()
    sym_b     = sym_b.upper()
    ratio_sym = f"{sym_a}~{sym_b}"

    print(f"++ Ratio: Computing {ratio_sym}")

    df_a = db.get_ohlcv_df(sym_a, "daily", limit=5000)
    df_b = db.get_ohlcv_df(sym_b, "daily", limit=5000)

    if df_a.empty:
        return {"symbol": ratio_sym, "error": f"No data for {sym_a}. Fetch it first."}
    if df_b.empty:
        return {"symbol": ratio_sym, "error": f"No data for {sym_b}. Fetch it first."}

    # Align on common trading dates
    common = df_a.index.intersection(df_b.index)
    if len(common) < 10:
        return {"symbol": ratio_sym,
                "error": f"Only {len(common)} common dates between {sym_a} and {sym_b}."}

    a = df_a.reindex(common)
    b = df_b.reindex(common)

    # Replace zeros in denominator to avoid inf
    b_open  = b["open"].replace(0, np.nan)
    b_high  = b["high"].replace(0, np.nan)
    b_low   = b["low"].replace(0, np.nan)
    b_close = b["close"].replace(0, np.nan)

    ratio_df = pd.DataFrame({
        "open":   a["open"]  / b_open,
        "high":   a["high"]  / b_low,    # conservative upper bound
        "low":    a["low"]   / b_high,   # conservative lower bound
        "close":  a["close"] / b_close,
        "volume": 0.0,
    }, index=common)
    ratio_df.dropna(inplace=True)

    if ratio_df.empty:
        return {"symbol": ratio_sym, "error": "Ratio series is empty after alignment."}

    # Weekly resample
    weekly_df = ratio_df.resample("W-FRI").agg({
        "open":   "first", "high": "max",
        "low":    "min",   "close": "last",
        "volume": "sum",
    }).dropna()

    daily_count  = db.upsert_ohlcv(ratio_sym, "daily",  ratio_df)
    weekly_count = db.upsert_ohlcv(ratio_sym, "weekly", weekly_df)
    cache.bump_version(ratio_sym)

    print(f"++ Ratio: Stored {daily_count}d / {weekly_count}w for {ratio_sym}")
    return {
        "symbol":      ratio_sym,
        "display":     f"{sym_a}/{sym_b}",
        "daily_rows":  daily_count,
        "weekly_rows": weekly_count,
    }
