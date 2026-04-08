"""
indicators.py - Compute technical analysis indicators for a symbol + freq.
Uses the `ta` library for indicator math.
Returns a dict ready to be JSON-serialised.
"""

import numpy as np
import pandas as pd
import ta
import database as db


def _safe(val):
    """Convert NaN / numpy types to Python-native for JSON."""
    if val is None:
        return None
    try:
        if np.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return val


def _series_to_list(s: pd.Series) -> list:
    return [{"date": d.strftime("%Y-%m-%d"), "value": _safe(v)}
            for d, v in zip(s.index, s.values)]


def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """
    Kaufman's Adaptive Moving Average (KAMA).
    Adapts its speed based on the Efficiency Ratio of price movement.
    """
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)

    prices = close.values
    kama_vals = np.full(len(prices), np.nan)

    # Seed with first valid close
    kama_vals[window - 1] = prices[window - 1]

    for i in range(window, len(prices)):
        direction  = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
        er  = direction / volatility if volatility != 0 else 0
        sc  = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama_vals[i] = kama_vals[i - 1] + sc * (prices[i] - kama_vals[i - 1])

    return pd.Series(kama_vals, index=close.index)


def compute_indicators(symbol: str, freq: str = "daily", kama_periods: list = None) -> dict:
    """
    Compute a full suite of technical indicators.
    kama_periods: list of integer window sizes for KAMA (default [10, 20, 50]).
    Returns a dict with structured data lists for each indicator.
    """
    if kama_periods is None:
        kama_periods = [10, 20, 50]

    df = db.get_ohlcv_df(symbol, freq)
    if df.empty:
        return {"error": "No OHLCV data found"}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]

    result = {}

    # ── Trend: KAMA (Kaufman's Adaptive Moving Average) ───────────
    for period in kama_periods:
        result[f"kama_{period}"] = _series_to_list(_kama(close, window=period))

    # ── Volatility: Bollinger Bands ────────────────────────────────
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    result["bb_upper"]  = _series_to_list(bb.bollinger_hband())
    result["bb_middle"] = _series_to_list(bb.bollinger_mavg())
    result["bb_lower"]  = _series_to_list(bb.bollinger_lband())

    # ── Momentum: RSI (7, 14, 21) ─────────────────────────────────
    rsi_series = {}
    for period in [7, 14, 21]:
        rsi_ind = ta.momentum.RSIIndicator(close, window=period)
        rsi_series[period] = rsi_ind.rsi()
        result[f"rsi_{period}"] = _series_to_list(rsi_series[period])

    # ── Momentum: MACD ────────────────────────────────────────────
    macd_ind    = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd_line   = macd_ind.macd()
    macd_signal = macd_ind.macd_signal()
    macd_hist   = macd_ind.macd_diff()
    result["macd_line"]   = _series_to_list(macd_line)
    result["macd_signal"] = _series_to_list(macd_signal)
    result["macd_hist"]   = _series_to_list(macd_hist)

    # ── Trend: CCI (20) ───────────────────────────────────────────
    cci_ind  = ta.trend.CCIIndicator(high, low, close, window=20)
    cci_vals = cci_ind.cci()
    result["cci"] = _series_to_list(cci_vals)

    # Composite Trend Score (-3 to +3)
    # RSI(14): >80 → 0 (overbought/risky); >50 → +1 (bullish); ≤50 → -1 (bearish)
    # CCI:     >0  → +1 (uptrend);          ≤0  → -1 (downtrend)
    # MACD:    hist>0 → +1 (bullish momentum); ≤0 → -1 (bearish)
    
    # We use the full index to ensure synchronization with other charts
    rsi_score  = np.where(rsi_series[14] > 80, 0,
                 np.where(rsi_series[14] > 50, 1, -1))
    cci_score  = np.where(cci_vals > 0, 1, -1)
    macd_score = np.where(macd_hist > 0, 1, -1)

    # Combine scores, keeping NaNs where any component is NaN
    total_score = rsi_score + cci_score + macd_score
    
    # Mask out values where indicators are NaN (lookback period)
    mask = rsi_series[14].isna() | cci_vals.isna() | macd_hist.isna()
    total_score = np.where(mask, np.nan, total_score)

    result["trend_score"] = _series_to_list(pd.Series(total_score, index=close.index))

    return result
