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


def compute_indicators(symbol: str, freq: str = "daily") -> dict:
    """
    Compute a full suite of technical indicators.
    Returns a dict with structured data lists for each indicator.
    """
    df = db.get_ohlcv_df(symbol, freq)
    if df.empty:
        return {"error": "No OHLCV data found"}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    result = {}

    # ── Trend: Moving Averages ─────────────────────────────────────
    for period in [20, 50, 200]:
        sma = ta.trend.sma_indicator(close, window=period)
        result[f"sma_{period}"] = _series_to_list(sma)

    for period in [12, 26]:
        ema = ta.trend.ema_indicator(close, window=period)
        result[f"ema_{period}"] = _series_to_list(ema)

    # ── Volatility: Bollinger Bands ────────────────────────────────
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    result["bb_upper"]  = _series_to_list(bb.bollinger_hband())
    result["bb_middle"] = _series_to_list(bb.bollinger_mavg())
    result["bb_lower"]  = _series_to_list(bb.bollinger_lband())

    # ── Volatility: ATR ───────────────────────────────────────────
    atr = ta.volatility.AverageTrueRange(high, low, close, window=14)
    result["atr"] = _series_to_list(atr.average_true_range())

    # ── Momentum: RSI ─────────────────────────────────────────────
    rsi = ta.momentum.RSIIndicator(close, window=14)
    result["rsi"] = _series_to_list(rsi.rsi())

    # ── Momentum: Stochastic ──────────────────────────────────────
    stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
    result["stoch_k"] = _series_to_list(stoch.stoch())
    result["stoch_d"] = _series_to_list(stoch.stoch_signal())

    # ── Momentum: MACD ────────────────────────────────────────────
    macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    result["macd_line"]   = _series_to_list(macd.macd())
    result["macd_signal"] = _series_to_list(macd.macd_signal())
    result["macd_hist"]   = _series_to_list(macd.macd_diff())

    # ── Volume: OBV ───────────────────────────────────────────────
    obv = ta.volume.OnBalanceVolumeIndicator(close, volume)
    result["obv"] = _series_to_list(obv.on_balance_volume())

    # ── Volume: SMA 20 ────────────────────────────────────────────
    vol_sma = ta.trend.sma_indicator(volume, window=20)
    result["vol_sma_20"] = _series_to_list(vol_sma)

    return result
