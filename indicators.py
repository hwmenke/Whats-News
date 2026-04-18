"""
indicators.py - Compute technical analysis indicators for a symbol + freq.
Pure numpy/pandas — no external TA library required.
Returns a dict ready to be JSON-serialised.
"""

import numpy as np
import pandas as pd
import database as db
from ta_core import _kama, _rsi, _bollinger, _macd, _cci


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


def compute_indicators(symbol: str, freq: str = "daily", kama_periods: list = None) -> dict:
    if kama_periods is None:
        kama_periods = [10, 20, 50]

    df = db.get_ohlcv_df(symbol, freq, limit=1000)
    if df.empty:
        return {"error": "No OHLCV data found"}

    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    result = {}

    # ── KAMA ──────────────────────────────────────────────────────
    for period in kama_periods:
        try:
            result[f"kama_{period}"] = _series_to_list(_kama(close, window=period))
        except Exception:
            result[f"kama_{period}"] = []

    # ── Bollinger Bands ───────────────────────────────────────────
    try:
        bb_upper, bb_mid, bb_lower = _bollinger(close, window=20, num_std=2.0)
        result["bb_upper"]  = _series_to_list(bb_upper)
        result["bb_middle"] = _series_to_list(bb_mid)
        result["bb_lower"]  = _series_to_list(bb_lower)
    except Exception:
        result["bb_upper"] = result["bb_middle"] = result["bb_lower"] = []

    # ── RSI (7, 14, 21) ───────────────────────────────────────────
    rsi_series = {}
    for period in [7, 14, 21]:
        try:
            s = _rsi(close, window=period)
            rsi_series[period] = s
            result[f"rsi_{period}"] = _series_to_list(s)
        except Exception:
            rsi_series[period] = pd.Series(np.nan, index=close.index)
            result[f"rsi_{period}"] = []

    # ── MACD (12/26/9) ────────────────────────────────────────────
    try:
        macd_line, macd_signal, macd_hist = _macd(close, fast=12, slow=26, signal=9)
        result["macd_line"]   = _series_to_list(macd_line)
        result["macd_signal"] = _series_to_list(macd_signal)
        result["macd_hist"]   = _series_to_list(macd_hist)
    except Exception:
        macd_hist = pd.Series(np.nan, index=close.index)
        result["macd_line"] = result["macd_signal"] = result["macd_hist"] = []

    # ── CCI (20) ──────────────────────────────────────────────────
    try:
        cci_vals = _cci(high, low, close, window=20)
        result["cci"] = _series_to_list(cci_vals)
    except Exception:
        cci_vals = pd.Series(np.nan, index=close.index)
        result["cci"] = []

    # ── Composite Trend Score ─────────────────────────────────────
    try:
        rsi_ref  = rsi_series.get(14, pd.Series(np.nan, index=close.index))
        macd_ref = macd_hist if isinstance(macd_hist, pd.Series) else pd.Series(np.nan, index=close.index)
        cci_ref  = cci_vals  if isinstance(cci_vals,  pd.Series) else pd.Series(np.nan, index=close.index)

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
