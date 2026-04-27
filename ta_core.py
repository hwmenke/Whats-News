"""
ta_core.py — Canonical TA primitives shared across indicators.py, scanner.py, stats.py.

All functions are pure (no DB access) and return pd.Series or tuples thereof.
"""

import numpy as np
import pandas as pd

try:
    import numba
    _NUMBA = True
except ImportError:
    _NUMBA = False


def _make_kama_nb():
    """Build the numba-JIT KAMA inner loop (cached). Falls back to pure numpy."""
    if not _NUMBA:
        return None
    import numba as nb

    @nb.njit(cache=True)
    def _kama_nb(prices: np.ndarray, window: int,
                 fast_sc: float, slow_sc: float) -> np.ndarray:
        n = len(prices)
        out = np.full(n, np.nan)
        if n < window:
            return out
        out[window - 1] = prices[window - 1]
        # Pre-compute abs-diff array — O(N) pass
        abs_diff = np.empty(n - 1)
        for j in range(n - 1):
            abs_diff[j] = abs(prices[j + 1] - prices[j])
        # Seed the running volatility window sum
        vol_sum = 0.0
        for j in range(window - 1):
            vol_sum += abs_diff[j]
        # Slide the window: O(N) total
        for i in range(window, n):
            vol_sum += abs_diff[i - 1]
            vol_sum -= abs_diff[i - window]
            direction = abs(prices[i] - prices[i - window])
            er  = direction / vol_sum if vol_sum > 1e-12 else 0.0
            sc  = (er * (fast_sc - slow_sc) + slow_sc) ** 2
            out[i] = out[i - 1] + sc * (prices[i] - out[i - 1])
        return out

    return _kama_nb


_kama_nb = _make_kama_nb()


def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's Adaptive Moving Average (numba-accelerated when available)."""
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    prices  = close.to_numpy(dtype=float, copy=True)
    if _kama_nb is not None:
        out = _kama_nb(prices, window, fast_sc, slow_sc)
    else:
        n   = len(prices)
        out = np.full(n, np.nan)
        if n >= window:
            out[window - 1] = prices[window - 1]
            for i in range(window, n):
                direction  = abs(prices[i] - prices[i - window])
                volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
                er  = direction / volatility if volatility > 1e-12 else 0.0
                sc  = (er * (fast_sc - slow_sc) + slow_sc) ** 2
                out[i] = out[i - 1] + sc * (prices[i] - out[i - 1])
    return pd.Series(out, index=close.index)


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI via exponential moving average."""
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
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
