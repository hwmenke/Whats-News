"""
data_fetcher.py - Download OHLCV from Yahoo Finance and store in DB
Supports incremental fetching: only downloads bars newer than what's in the DB.
"""

import datetime
import time
import yfinance as yf
import pandas as pd
import database as db

# If an overlapping bar's close jumps this much after auto_adjust, treat it
# as a split/dividend seam and re-download full history instead of mixing
# unadjusted stored bars with newly adjusted ones.
ADJUSTMENT_SEAM_PCT = 15.0


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


def adjustment_seam(
    stored_closes: dict,
    daily_df: pd.DataFrame,
    threshold_pct: float = ADJUSTMENT_SEAM_PCT,
) -> bool:
    """True when overlap closes disagree by ≥ threshold (split/div adjust)."""
    if not stored_closes or daily_df is None or daily_df.empty:
        return False
    if "close" not in daily_df.columns:
        return False
    for ts, row in daily_df.iterrows():
        try:
            d = pd.Timestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            continue
        old = stored_closes.get(d)
        if old is None:
            continue
        try:
            old_c = float(old)
            new_c = float(row["close"])
        except (TypeError, ValueError):
            continue
        if old_c <= 0 or new_c <= 0:
            continue
        if abs(new_c / old_c - 1.0) * 100.0 >= threshold_pct:
            return True
    return False


def _stored_closes(symbol: str, limit: int = 40) -> dict:
    rows = db.get_ohlcv(symbol, "daily", limit=limit)
    out = {}
    for r in rows or []:
        d = str(r.get("date") or "")[:10]
        try:
            out[d] = float(r["close"])
        except (TypeError, ValueError, KeyError):
            continue
    return out


def fetch_and_store(symbol: str, period: str = "2y", overlap_days: int = 3) -> dict:
    """
    Download daily data from Yahoo Finance, resample to weekly,
    and upsert both into the database.
    If data already exists in the DB, only downloads from (last_date - overlap_days)
    forward (incremental mode). Falls back to full period download if no data exists.
    """
    sym = symbol.upper()
    print(f"++ Fetcher: Starting fetch for {sym}")
    ticker = yf.Ticker(sym)

    # Check if we have existing data and can do an incremental fetch
    last_date_str = db.get_latest_ohlcv_date(sym, "daily")
    if last_date_str:
        last_date  = datetime.date.fromisoformat(last_date_str)
        start_date = last_date - datetime.timedelta(days=max(0, overlap_days))
        start_str  = start_date.isoformat()
        print(f"++ Fetcher: Incremental fetch for {sym} from {start_str} (overlap {overlap_days}d)")
        raw = ticker.history(start=start_str, interval="1d", auto_adjust=True)
    else:
        print(f"++ Fetcher: Full {period} download for {sym}")
        raw = ticker.history(period=period, interval="1d", auto_adjust=True)

    if raw.empty:
        print(f"!! Fetcher: No data returned for {sym}")
        return {"symbol": sym, "error": f"No data returned for {sym}"}

    daily_df = _clean_df(raw)
    print(f"++ Fetcher: Processed {len(daily_df)} daily bars")

    if last_date_str and adjustment_seam(_stored_closes(sym), daily_df):
        print(f"!! Fetcher: Adjustment seam on {sym} — full re-download")
        return fetch_full_history(sym)

    # Resample to weekly (week ending Friday)
    weekly_df = daily_df.resample("W-FRI").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum"
    }).dropna()
    # Incremental windows start mid-week; the first resampled bar is a
    # partial week and would overwrite a good stored weekly OHLC.
    if last_date_str and len(weekly_df) > 1:
        weekly_df = weekly_df.iloc[1:]
    print(f"++ Fetcher: Resampled to {len(weekly_df)} weekly bars")

    daily_count  = db.upsert_ohlcv(sym, "daily",  daily_df)
    weekly_count = db.upsert_ohlcv(sym, "weekly", weekly_df)
    print(f"++ Fetcher: Database updated ({daily_count}d, {weekly_count}w)")

    # Pull meta info (name, sector) - try/except as this can be slow/fail
    name, sector = "", ""
    try:
        print(f"++ Fetcher: Requesting ticker.info for {sym}...")
        info   = ticker.info
        name   = info.get("longName") or ""
        sector = (info.get("sector") or info.get("industry") or "").strip()
        print(f"++ Fetcher: Info retrieved: {name} ({sector})")
    except Exception as e:
        print(f"!! Fetcher: Metadata download failed (skipped): {str(e)}")

    if name or sector:
        db.update_symbol_info(sym, name, sector)
    db.update_last_fetch(sym)

    return {
        "symbol":       sym,
        "name":         name,
        "sector":       sector,
        "daily_rows":   daily_count,
        "weekly_rows":  weekly_count,
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

            daily_count  = db.upsert_ohlcv(sym, "daily",  daily_df)
            weekly_count = db.upsert_ohlcv(sym, "weekly", weekly_df)
            print(f"++ Fetcher: Stored {daily_count}d / {weekly_count}w for {sym}")

            # Metadata (best-effort)
            name, sector = "", ""
            try:
                info   = ticker.info
                name   = info.get("longName") or ""
                sector = (info.get("sector") or info.get("industry") or "").strip()
            except Exception:
                pass

            if name or sector:
                db.update_symbol_info(sym, name, sector)
            db.update_last_fetch(sym)

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
