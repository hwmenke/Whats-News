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
    if kama_periods is None:
        kama_periods = [10, 20, 50]

    # Increase history to 1000 bars for better indicator padding
    df = db.get_ohlcv_df(symbol, freq, limit=1000)
    if df.empty:
        return {"error": "No OHLCV data found"}

    close = df["close"]
    high = df["high"]
    low = df["low"]

    result = {}

    # ── Trend: KAMA ───────────────────────────────────────────────
    for period in kama_periods:
        try:
            result[f"kama_{period}"] = _series_to_list(_kama(close, window=period))
        except Exception:
            result[f"kama_{period}"] = []

    # ── Volatility: Bollinger Bands ────────────────────────────────
    try:
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        result["bb_upper"]  = _series_to_list(bb.bollinger_hband())
        result["bb_middle"] = _series_to_list(bb.bollinger_mavg())
        result["bb_lower"]  = _series_to_list(bb.bollinger_lband())
    except Exception:
        result["bb_upper"] = result["bb_middle"] = result["bb_lower"] = []

    # ── Momentum: RSI (7, 14, 21) ─────────────────────────────────
    rsi_series = {}
    for period in [7, 14, 21]:
        try:
            rsi_ind = ta.momentum.RSIIndicator(close, window=period)
            rsi_series[period] = rsi_ind.rsi()
            result[f"rsi_{period}"] = _series_to_list(rsi_series[period])
        except Exception:
            rsi_series[period] = pd.Series(np.nan, index=close.index)
            result[f"rsi_{period}"] = []

    # ── Momentum: MACD ────────────────────────────────────────────
    try:
        macd_ind    = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_line   = macd_ind.macd()
        macd_signal = macd_ind.macd_signal()
        macd_hist   = macd_ind.macd_diff()
        result["macd_line"]   = _series_to_list(macd_line)
        result["macd_signal"] = _series_to_list(macd_signal)
        result["macd_hist"]   = _series_to_list(macd_hist)
    except Exception:
        macd_hist = pd.Series(np.nan, index=close.index) # For trend score calc
        result["macd_line"] = result["macd_signal"] = result["macd_hist"] = []

    # ── Trend: CCI (20) ───────────────────────────────────────────
    try:
        cci_ind  = ta.trend.CCIIndicator(high, low, close, window=20)
        cci_vals = cci_ind.cci()
        result["cci"] = _series_to_list(cci_vals)
    except Exception:
        cci_vals = pd.Series(np.nan, index=close.index)
        result["cci"] = []

    # Composite Trend Score
    try:
        rsi_ref = rsi_series.get(14, pd.Series(np.nan, index=close.index))
        macd_ref = macd_hist if 'macd_hist' in locals() else pd.Series(np.nan, index=close.index)
        cci_ref = cci_vals if 'cci_vals' in locals() else pd.Series(np.nan, index=close.index)

        rsi_score  = np.where(rsi_ref > 80, 0, np.where(rsi_ref > 50, 1, -1))
        cci_score  = np.where(cci_ref > 0, 1, -1)
        macd_score = np.where(macd_ref > 0, 1, -1)

        total_score = rsi_score + cci_score + macd_score
        mask = rsi_ref.isna() | cci_ref.isna() | macd_ref.isna()
        total_score = np.where(mask, np.nan, total_score)
        result["trend_score"] = _series_to_list(pd.Series(total_score, index=close.index))
    except Exception:
        result["trend_score"] = []

    return result

    return result
