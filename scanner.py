"""
scanner.py — Multi-timeframe watchlist scanner.

Metrics computed per symbol × (daily / weekly / monthly):
  RSI        : rsi_7, rsi_14, rsi_21
  KAMA ratios: p_kf_pct  — percentile rank of close/KAMA_fast
               p_km_pct  — percentile rank of close/KAMA_medium
               kf_km     — (KAMA_fast / KAMA_medium − 1) × 100  (cross %)
  Momentum   : roc_1m, roc_3m, roc_6m  (rate of change)
               bb_b      — Bollinger %B
  Volatility : atr_pct   — ATR(14) as % of price
  Structure  : vol_ratio — 5-bar / 20-bar avg volume
               dist_hi   — % below lookback-period high  (0 = at high)
               dist_sma  — % above/below 200-bar SMA

Timeframe lookbacks used for percentile rank windows:
  daily  → 252 bars   (~1 year)
  weekly →  52 bars   (~1 year)
  monthly→  36 bars   (~3 years)
"""

import numpy as np
import pandas as pd
import database as db
from ta_core import _kama, _rsi as _rsi_core


# ── type helpers ─────────────────────────────────────────────────────

def _safe(v):
    """Coerce numpy scalar → Python native; None on NaN."""
    if v is None:
        return None
    try:
        if np.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return round(float(v), 4)
    return v


def _last(s: pd.Series):
    """Return last non-NaN value of a Series, or None."""
    valid = s.dropna()
    return _safe(valid.iloc[-1]) if len(valid) else None


def _rsi(close: pd.Series, n: int) -> pd.Series:
    return _rsi_core(close, window=n)


def _pct_rank(series: pd.Series, lookback: int) -> pd.Series:
    """
    Rolling percentile rank: where does the current bar's value sit
    within the previous `lookback` bars?  Returns 0–100.
    Uses numpy searchsorted for speed.
    """
    arr = series.values.astype(float)
    n   = len(arr)
    out = np.full(n, np.nan)
    for i in range(lookback, n):
        cur = arr[i]
        if np.isnan(cur):
            continue
        window = arr[i - lookback: i]
        valid  = window[~np.isnan(window)]
        if len(valid) == 0:
            continue
        out[i] = float(
            np.searchsorted(np.sort(valid), cur, side='right')
        ) / len(valid) * 100.0
    return pd.Series(out, index=series.index)


# ── per-timeframe computation ─────────────────────────────────────────

def _compute_tf(df: pd.DataFrame, lookback: int):
    """Compute all scanner metrics for one symbol × timeframe."""
    min_bars = max(22, lookback // 8)
    if df is None or len(df) < min_bars:
        return None

    close = df['close']
    high  = df['high']
    low   = df['low']
    vol   = df['volume']

    # ── RSI ──────────────────────────────────────────────────────────
    rsi7  = _rsi(close, 7)
    rsi14 = _rsi(close, 14)
    rsi21 = _rsi(close, 21)

    # ── KAMA baselines ────────────────────────────────────────────────
    kf = _kama(close, window=10, fast=2, slow=30)   # fast
    km = _kama(close, window=20, fast=2, slow=60)   # medium

    kf_safe = kf.replace(0, np.nan)
    km_safe = km.replace(0, np.nan)

    p_kf  = close / kf_safe                         # price / KAMA_fast
    p_km  = close / km_safe                         # price / KAMA_medium
    kf_km = (kf_safe / km_safe - 1.0) * 100        # cross (%)

    p_kf_pct = _pct_rank(p_kf,  lookback)
    p_km_pct = _pct_rank(p_km,  lookback)

    # ── Bollinger %B ──────────────────────────────────────────────────
    bb_n   = min(20, len(close) - 1)
    bb_mid = close.rolling(bb_n).mean()
    bb_std = close.rolling(bb_n).std(ddof=0)
    bb_b   = (close - (bb_mid - 2 * bb_std)) / (4 * bb_std.replace(0, np.nan))

    # ── ATR% ──────────────────────────────────────────────────────────
    prev_c = close.shift(1)
    tr     = pd.concat([
                 high - low,
                 (high - prev_c).abs(),
                 (low  - prev_c).abs(),
             ], axis=1).max(axis=1)
    atr_n  = min(14, len(tr) - 1)
    atr    = tr.ewm(alpha=1.0 / atr_n, adjust=False).mean()
    atr_pct = atr / close.replace(0, np.nan) * 100

    # ── Rate of change ────────────────────────────────────────────────
    nb     = len(close)
    roc_1m = close.pct_change(min(max(1, lookback // 12), nb - 1)) * 100
    roc_3m = close.pct_change(min(max(1, lookback //  4), nb - 1)) * 100
    roc_6m = close.pct_change(min(max(1, lookback //  2), nb - 1)) * 100

    # ── Volume ratio (5-bar / 20-bar avg) ─────────────────────────────
    v5        = vol.rolling(5).mean()
    v20       = vol.rolling(20).mean()
    vol_ratio = v5 / v20.replace(0, np.nan)

    # ── Distance from period high ─────────────────────────────────────
    hi       = close.rolling(min(lookback, nb)).max()
    dist_hi  = (close / hi.replace(0, np.nan) - 1.0) * 100   # 0 = at high

    # ── Distance from 200-bar SMA ─────────────────────────────────────
    sma_n    = min(200, nb - 1)
    sma200   = close.rolling(max(2, sma_n)).mean()
    dist_sma = (close / sma200.replace(0, np.nan) - 1.0) * 100

    return {
        'rsi_7':      _last(rsi7),
        'rsi_14':     _last(rsi14),
        'rsi_21':     _last(rsi21),
        'p_kf_pct':   _last(p_kf_pct),
        'p_km_pct':   _last(p_km_pct),
        'kf_km':      _last(kf_km),
        'bb_b':       _last(bb_b),
        'atr_pct':    _last(atr_pct),
        'roc_1m':     _last(roc_1m),
        'roc_3m':     _last(roc_3m),
        'roc_6m':     _last(roc_6m),
        'vol_ratio':  _last(vol_ratio),
        'dist_hi':    _last(dist_hi),
        'dist_sma':   _last(dist_sma),
    }


# ── monthly resampler ─────────────────────────────────────────────────

def _to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample a daily DatetimeIndex DataFrame to month-end bars.
    Tries pandas 2.2+ 'ME' alias first, falls back to legacy 'M'.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    agg = dict(open='first', high='max', low='min', close='last', volume='sum')
    for alias in ('ME', 'M'):
        try:
            return df.resample(alias).agg(**agg).dropna(subset=['close'])
        except Exception:
            continue
    return pd.DataFrame()


# ── public API ────────────────────────────────────────────────────────

def compute_scanner(symbols: list) -> list:
    """
    Compute D/W/M scanner metrics for every symbol in the list.
    Returns a JSON-serialisable list of row dicts.
    """
    results = []
    for sym in symbols:
        try:
            d_df = db.get_ohlcv_df(sym, 'daily',  limit=600)
            w_df = db.get_ohlcv_df(sym, 'weekly', limit=200)

            if d_df.empty:
                results.append({
                    'symbol': sym, 'error': 'No data — fetch first',
                    'price': None, 'chg': None,
                    'd': None, 'w': None, 'm': None,
                })
                continue

            # Price / change computed before any further processing
            price = _safe(d_df['close'].iloc[-1])
            prev  = _safe(d_df['close'].iloc[-2]) if len(d_df) > 1 else None
            chg   = round((price - prev) / prev * 100, 2) if price and prev else None

            # Monthly resample — isolated so a failure doesn't kill price/D/W
            try:
                m_df = _to_monthly(d_df)
            except Exception:
                m_df = pd.DataFrame()

            # Each timeframe is isolated — one failure won't blank the others
            def _safe_tf(df, lb):
                try:
                    return _compute_tf(df, lb)
                except Exception:
                    return None

            results.append({
                'symbol': sym,
                'price':  price,
                'chg':    chg,
                'd':      _safe_tf(d_df, 252),
                'w':      _safe_tf(w_df, 52),
                'm':      _safe_tf(m_df, 36),
            })
        except Exception as e:
            results.append({
                'symbol': sym, 'error': str(e),
                'price': None, 'chg': None,
                'd': None, 'w': None, 'm': None,
            })

    return results
