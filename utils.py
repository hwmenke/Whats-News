"""
utils.py - Shared indicator implementations and type helpers.

Canonical versions of KAMA, RSI, and numpy→Python coercion used across
multiple modules. Import from here instead of copying.
"""

import numpy as np
import pandas as pd


# ── Type helpers ──────────────────────────────────────────────────────────────

def safe(val):
    """Convert numpy scalars to Python natives; NaN/None → None."""
    if val is None:
        return None
    try:
        if np.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return float(val)
    return val


def series_to_list(s: pd.Series) -> list:
    """Convert a DatetimeIndex Series to [{date, value}, ...] for JSON."""
    return [{"date": d.strftime("%Y-%m-%d"), "value": safe(v)}
            for d, v in zip(s.index, s.values)]


# ── Indicators ────────────────────────────────────────────────────────────────

def kama(close: pd.Series, window: int = 10,
         fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's Adaptive Moving Average.

    Uses `volatility > 1e-12` guard to avoid division by near-zero noise.
    """
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    prices = close.to_numpy(dtype=float, copy=True)
    n = len(prices)
    out = np.full(n, np.nan)
    if n < window:
        return pd.Series(out, index=close.index)
    out[window - 1] = prices[window - 1]
    for i in range(window, n):
        direction = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
        er = direction / volatility if volatility > 1e-12 else 0.0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        out[i] = out[i - 1] + sc * (prices[i] - out[i - 1])
    return pd.Series(out, index=close.index)


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI via exponential moving average.

    min_periods=window suppresses warm-up values during the initial period.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))
