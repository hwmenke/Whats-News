"""
data_fetcher.py - Download OHLCV from Yahoo Finance and store in DB
Supports incremental fetching: only downloads bars newer than what's in the DB.
"""

import datetime
import logging
import time
import yfinance as yf
import pandas as pd
import database as db

logger = logging.getLogger(__name__)


def _clean_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance output to lowercase columns and drop NaN rows."""
    logger.debug("Normalizing %d rows of raw data", len(raw))
    df = raw.copy()
    df.columns = [c.lower() for c in df.columns]

    # yfinance sometimes returns MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        logger.debug("Detected MultiIndex columns, flattening")
        df.columns = [c[0].lower() for c in df.columns]

    # Ensure required columns exist
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("Missing columns %s. Available: %s", missing, df.columns.tolist())
        # Fallback for common yfinance naming variations
        if "adj close" in df.columns and "close" not in df.columns:
            df["close"] = df["adj close"]
    
    # Final filter
    available = [c for c in required if c in df.columns]
    df = df[available]
    df.dropna(inplace=True)
    df.index = pd.to_datetime(df.index)
    df.index = df.index.tz_localize(None)

    # Drop rows with non-positive close prices (bad yfinance data)
    bad_rows = (df["close"] <= 0).sum() if "close" in df.columns else 0
    if bad_rows:
        logger.warning("Dropping %d row(s) with close <= 0", bad_rows)
        df = df[df["close"] > 0]

    return df


def fetch_and_store(symbol: str, period: str = "2y") -> dict:
    """
    Download daily data from Yahoo Finance, resample to weekly,
    and upsert both into the database.
    If data already exists in the DB, only downloads bars from last_date + 1 day
    forward (incremental mode). Falls back to full 2y download if no data exists.
    """
    sym = symbol.upper()
    logger.info("Starting fetch for %s", sym)
    ticker = yf.Ticker(sym)

    # Check if we have existing data and can do an incremental fetch
    last_date_str = db.get_latest_ohlcv_date(sym, "daily")
    if last_date_str:
        last_date  = datetime.date.fromisoformat(last_date_str)
        start_date = last_date + datetime.timedelta(days=1)
        start_str  = start_date.isoformat()
        logger.info("Incremental fetch for %s from %s", sym, start_str)
        raw = ticker.history(start=start_str, interval="1d", auto_adjust=True)
    else:
        logger.info("Full %s download for %s", period, sym)
        raw = ticker.history(period=period, interval="1d", auto_adjust=True)

    if raw.empty:
        logger.warning("No data returned for %s", sym)
        return {"symbol": sym, "error": f"No data returned for {sym}"}

    daily_df = _clean_df(raw)
    logger.debug("Processed %d daily bars for %s", len(daily_df), sym)

    # Resample to weekly (week ending Friday)
    weekly_df = daily_df.resample("W-FRI").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum"
    }).dropna()
    logger.debug("Resampled to %d weekly bars for %s", len(weekly_df), sym)

    daily_count  = db.upsert_ohlcv(sym, "daily",  daily_df)
    weekly_count = db.upsert_ohlcv(sym, "weekly", weekly_df)
    logger.info("Database updated for %s (%dd, %dw)", sym, daily_count, weekly_count)

    # Pull meta info (name, sector) - try/except as this can be slow/fail
    name, sector = "", ""
    try:
        info   = ticker.info
        name   = info.get("longName", "")
        sector = info.get("sector", f"{info.get('industry', '')}").strip()
        logger.debug("Metadata for %s: %s (%s)", sym, name, sector)
    except Exception as e:
        logger.warning("Metadata download failed for %s (skipped): %s", sym, e)

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
            logger.info("Full-history fetch for %s (attempt %d/%d)", sym, attempt, max_retries)
            ticker = yf.Ticker(sym)

            raw = ticker.history(start=start, interval="1d", auto_adjust=True)
            if raw.empty:
                logger.warning("No data returned for %s", sym)
                return {"symbol": sym, "error": f"No data returned for {sym}"}

            daily_df = _clean_df(raw)
            logger.debug("%d daily bars from %s for %s", len(daily_df), start, sym)

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
            logger.info("Stored %dd / %dw for %s", daily_count, weekly_count, sym)

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

            return {
                "symbol":      sym,
                "name":        name,
                "sector":      sector,
                "daily_rows":  daily_count,
                "weekly_rows": weekly_count,
            }

        except Exception as exc:
            logger.warning("Attempt %d failed for %s: %s", attempt, sym, exc)
            if attempt < max_retries:
                logger.info("Retrying %s in %ds", sym, delay)
                time.sleep(delay)
                delay *= 2
            else:
                return {"symbol": sym, "error": str(exc)}
