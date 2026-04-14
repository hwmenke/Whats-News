"""
scanner.py - S&P 500 market scanner.
Fetches S&P 500 tickers from Wikipedia, bulk-downloads data, and scans for signals.
"""

import numpy as np
import pandas as pd
import ta
from concurrent.futures import ThreadPoolExecutor, as_completed

import database as db
import data_fetcher as fetcher

# ── Module-level bulk-fetch status ───────────────────────────────────────────
_fetch_status = {
    "running":  False,
    "progress": 0,
    "total":    0,
    "done":     0,
    "summary":  None,
}


def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's Adaptive Moving Average."""
    prices = close.to_numpy(dtype=float, copy=True)
    kama_vals = np.full(len(prices), np.nan)

    if len(prices) < window:
        return pd.Series(kama_vals, index=close.index)

    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    kama_vals[window - 1] = prices[window - 1]

    for i in range(window, len(prices)):
        direction = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
        er = direction / volatility if volatility != 0 else 0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama_vals[i] = kama_vals[i - 1] + sc * (prices[i] - kama_vals[i - 1])

    return pd.Series(kama_vals, index=close.index)


def get_sp500_tickers() -> pd.DataFrame:
    """
    Scrape S&P 500 constituents from Wikipedia.
    Returns a DataFrame with at least 'Symbol' and 'Security' columns.
    Replaces '.' with '-' in symbols for yfinance compatibility.
    """
    url    = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df     = tables[0]

    # Standardise column names
    df.columns = [c.strip() for c in df.columns]

    # The ticker column may be named 'Symbol' or 'Ticker symbol'
    for col in df.columns:
        if "symbol" in col.lower() or "ticker" in col.lower():
            df = df.rename(columns={col: "Symbol"})
            break

    df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)
    return df


def bulk_fetch_sp500(max_workers: int = 5, force_refresh: bool = False) -> dict:
    """
    Add all S&P 500 tickers to the DB and fetch their OHLCV data.
    Skips symbols fetched within the last 23 hours unless force_refresh=True.
    Updates the module-level _fetch_status dict throughout.
    """
    global _fetch_status

    try:
        sp500_df = get_sp500_tickers()
        symbols  = sp500_df["Symbol"].tolist()
    except Exception as e:
        _fetch_status["running"] = False
        return {"error": f"Failed to fetch S&P 500 list: {str(e)}"}

    _fetch_status["total"]    = len(symbols)
    _fetch_status["done"]     = 0
    _fetch_status["progress"] = 0

    # Ensure all symbols are in the DB first
    for sym in symbols:
        db.add_symbol(sym)

    results = {"total": len(symbols), "success": 0, "skipped": 0, "failed": 0, "errors": []}

    def _fetch_one(sym):
        if not force_refresh and db.is_recently_fetched(sym):
            return ("skipped", sym, None)
        try:
            res = fetcher.fetch_and_store(sym)
            if "error" in res:
                return ("failed", sym, res["error"])
            return ("success", sym, None)
        except Exception as e:
            return ("failed", sym, str(e))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            status_str, sym, err = future.result()
            results[status_str] += 1
            if err:
                results["errors"].append({"symbol": sym, "error": err})

            _fetch_status["done"] += 1
            total = _fetch_status["total"] or 1
            _fetch_status["progress"] = round(_fetch_status["done"] / total * 100, 1)

    _fetch_status["running"] = False
    _fetch_status["summary"] = results
    return results


def _scan_one(sym: str):
    """
    Compute scanner signals for a single symbol using DB data only.
    Returns None if there is not enough data.
    """
    df = db.get_ohlcv_df(sym, "daily", limit=300)
    if df.empty or len(df) < 60:
        return None

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    try:
        # Price
        price = float(close.iloc[-1])

        # Week return (5 trading days)
        week_ret = float(close.pct_change(5).iloc[-1]) if len(close) >= 6 else None

        # RSI
        rsi_s = ta.momentum.RSIIndicator(close, window=14).rsi()
        rsi   = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else None

        # Trend score (RSI + CCI + MACD like in indicators.py)
        cci_s    = ta.trend.CCIIndicator(high, low, close, window=20).cci()
        macd_ind = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_h   = macd_ind.macd_diff()

        rsi_score  = float(np.where(rsi_s > 80, 0, np.where(rsi_s > 50, 1, -1)).tolist()[-1])
        cci_score  = float(np.where(cci_s > 0, 1, -1).tolist()[-1])
        macd_score = float(np.where(macd_h > 0, 1, -1).tolist()[-1])

        all_nan = rsi_s.isna().iloc[-1] or cci_s.isna().iloc[-1] or macd_h.isna().iloc[-1]
        trend_score = None if all_nan else int(rsi_score + cci_score + macd_score)

        # KAMA distances
        kama_vals = {}
        for period in [10, 20, 50]:
            k_s = _kama(close, window=period)
            k_last = k_s.iloc[-1]
            if not np.isnan(k_last) and k_last != 0:
                kama_vals[period] = (price / k_last - 1.0) * 100.0  # as %
            else:
                kama_vals[period] = None

        # Volume ratio
        vol_ma20 = vol.rolling(20).mean().iloc[-1]
        vol_ratio = float(vol.iloc[-1] / vol_ma20) if vol_ma20 and not np.isnan(vol_ma20) and vol_ma20 != 0 else None

        # Bollinger Band %B
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        bb_range = bb_upper - bb_lower
        bb_pct   = float((price - bb_lower) / bb_range) if bb_range and bb_range != 0 else None

        # MACD histogram latest
        macd_hist_val = float(macd_h.iloc[-1]) if not np.isnan(macd_h.iloc[-1]) else None

        # ── Signals ──────────────────────────────────────────────────────────
        signals = []

        if rsi is not None:
            if rsi < 30:
                signals.append("RSI_OVERSOLD")
            if rsi > 70:
                signals.append("RSI_OVERBOUGHT")

        # KAMA crossover signals (k10 vs k20)
        k10_s = _kama(close, window=10)
        k20_s = _kama(close, window=20)
        if len(k10_s) >= 2 and len(k20_s) >= 2:
            k10_prev, k10_curr = float(k10_s.iloc[-2]), float(k10_s.iloc[-1])
            k20_prev, k20_curr = float(k20_s.iloc[-2]), float(k20_s.iloc[-1])
            if not any(np.isnan(v) for v in [k10_prev, k10_curr, k20_prev, k20_curr]):
                if k10_prev <= k20_prev and k10_curr > k20_curr:
                    signals.append("KAMA_BULL_CROSS")
                if k10_prev >= k20_prev and k10_curr < k20_curr:
                    signals.append("KAMA_BEAR_CROSS")

        if trend_score is not None:
            if trend_score >= 2:
                signals.append("STRONG_BULL")
            if trend_score <= -2:
                signals.append("STRONG_BEAR")

        # MACD crossover signals
        if len(macd_h) >= 2:
            mh_prev = float(macd_h.iloc[-2])
            mh_curr = float(macd_h.iloc[-1])
            if not (np.isnan(mh_prev) or np.isnan(mh_curr)):
                if mh_prev <= 0 and mh_curr > 0:
                    signals.append("MACD_BULL_CROSS")
                if mh_prev >= 0 and mh_curr < 0:
                    signals.append("MACD_BEAR_CROSS")

        if vol_ratio is not None and vol_ratio > 2:
            signals.append("HIGH_VOLUME")

        if bb_pct is not None:
            if bb_pct < 0.05:
                signals.append("BB_LOWER_BAND")
            if bb_pct > 0.95:
                signals.append("BB_UPPER_BAND")

        def _r(v, decimals=2):
            try:
                return round(float(v), decimals) if v is not None and not np.isnan(v) else None
            except Exception:
                return None

        return {
            "symbol":       sym,
            "price":        _r(price, 2),
            "week_ret":     _r(week_ret, 4),
            "rsi":          _r(rsi, 2),
            "trend_score":  trend_score,
            "kama10_dist":  _r(kama_vals[10], 2),
            "kama20_dist":  _r(kama_vals[20], 2),
            "kama50_dist":  _r(kama_vals[50], 2),
            "vol_ratio":    _r(vol_ratio, 2),
            "bb_pct":       _r(bb_pct, 4),
            "macd_hist":    _r(macd_hist_val, 6),
            "signals":      signals,
            "signal_count": len(signals),
        }
    except Exception:
        return None


def run_scanner(symbols: list = None, signal_filter: str = None) -> list:
    """
    Run _scan_one for all symbols in DB (or a provided list).
    Optionally filters by a specific signal name.
    Sorted by (signal_count desc, trend_score desc).
    """
    if symbols is None:
        symbols = [s["symbol"] for s in db.list_symbols()]

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    if signal_filter:
        results = [r for r in results if signal_filter in r["signals"]]

    results.sort(
        key=lambda r: (
            -(r.get("signal_count") or 0),
            -(r.get("trend_score") or 0),
        )
    )
    return results
