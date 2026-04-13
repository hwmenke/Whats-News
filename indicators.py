"""
indicators.py - Compute technical analysis indicators for a symbol + freq.
Pure numpy/pandas — no external TA library required.
Returns a dict ready to be JSON-serialised.
"""

import numpy as np
import pandas as pd
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
    """Kaufman's Adaptive Moving Average."""
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    prices = close.values
    kama_vals = np.full(len(prices), np.nan)
    kama_vals[window - 1] = prices[window - 1]
    for i in range(window, len(prices)):
        direction  = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
        er  = direction / volatility if volatility != 0 else 0
        sc  = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama_vals[i] = kama_vals[i - 1] + sc * (prices[i] - kama_vals[i - 1])
    return pd.Series(kama_vals, index=close.index)


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI via exponential moving average."""
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0):
    """Returns (upper, middle, lower) Bollinger Band series."""
    mid   = close.rolling(window).mean()
    std   = close.rolling(window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram) series."""
    ema_fast    = close.ewm(span=fast,   adjust=False).mean()
    ema_slow    = close.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist        = macd_line - signal_line
    return macd_line, signal_line, hist


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    tp = (high + low + close) / 3.0
    ma = tp.rolling(window).mean()
    md = tp.rolling(window).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


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
