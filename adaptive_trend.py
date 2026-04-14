"""
adaptive_trend.py - Multi-horizon Adaptive Trend System
Computes SB/MB/LB baselines, MRT/LRT stop bands, SDB/MDB/LDB TP bands,
short/medium/long regime states, and entry signals.
"""

import numpy as np
import pandas as pd
import database as db


# ── JSON helpers ──────────────────────────────────────────────

def _safe(val):
    """Convert NaN / numpy types to Python-native for JSON."""
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


def _series_to_list(s: pd.Series) -> list:
    return [{"date": d.strftime("%Y-%m-%d"), "value": _safe(v)}
            for d, v in zip(s.index, s.values)]


# ── Indicators ────────────────────────────────────────────────

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    """Wilder's Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_vals = np.full(len(tr), np.nan)
    first_valid = tr.first_valid_index()
    if first_valid is None:
        return pd.Series(atr_vals, index=close.index)

    idx0     = close.index.get_loc(first_valid)
    seed_end = idx0 + n
    if seed_end > len(tr):
        return pd.Series(atr_vals, index=close.index)

    atr_vals[seed_end - 1] = tr.iloc[idx0:seed_end].mean()
    for i in range(seed_end, len(tr)):
        atr_vals[i] = atr_vals[i - 1] + (tr.iloc[i] - atr_vals[i - 1]) / n

    return pd.Series(atr_vals, index=close.index)


def _adaptive_ma(src: pd.Series, er_len: int, fast_period: int,
                 slow_period: int, method: str = "kama") -> pd.Series:
    """
    Adaptive moving average.
      KAMA  : alpha = (slow_sc + ER*(fast_sc-slow_sc))^2   (Kaufman squaring)
      ADMA  : alpha =  slow_sc + ER*(fast_sc-slow_sc)      (no squaring)
    where fast_sc = 2/(fast+1), slow_sc = 2/(slow+1).
    """
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    prices = src.values.astype(float)
    n      = len(prices)
    out    = np.full(n, np.nan)

    first = next((i for i, v in enumerate(prices) if np.isfinite(v)), None)
    if first is None:
        return pd.Series(out, index=src.index)

    seed = first + er_len
    if seed >= n:
        return pd.Series(out, index=src.index)

    out[seed - 1] = prices[seed - 1]

    for i in range(seed, n):
        if not np.isfinite(prices[i]):
            out[i] = out[i - 1] if np.isfinite(out[i - 1]) else np.nan
            continue
        direction  = abs(prices[i] - prices[i - er_len])
        window     = prices[i - er_len: i + 1]
        volatility = np.sum(np.abs(np.diff(window)))
        er         = direction / volatility if volatility > 1e-12 else 0.0

        if method == "kama":
            alpha = (slow_sc + er * (fast_sc - slow_sc)) ** 2
        else:
            alpha = slow_sc + er * (fast_sc - slow_sc)

        alpha   = max(min(alpha, 1.0), 0.0)
        out[i]  = out[i - 1] + alpha * (prices[i] - out[i - 1])

    return pd.Series(out, index=src.index)


def _sticky_state(long_cond: pd.Series, short_cond: pd.Series, min_hold: int = 5) -> pd.Series:
    """
    Sticky regime:
      +1 once long_cond fires, holds until short_cond fires.
      -1 once short_cond fires, holds until long_cond fires.
       0 while neither has fired yet.
    min_hold: minimum bars before the regime can flip again.
    """
    state = np.zeros(len(long_cond), dtype=int)
    current = 0
    bars_since_flip = min_hold  # allow flip on first signal
    for i in range(len(long_cond)):
        bars_since_flip += 1
        if current >= 0 and short_cond.iloc[i] and bars_since_flip >= min_hold:
            current = -1
            bars_since_flip = 0
        elif current <= 0 and long_cond.iloc[i] and bars_since_flip >= min_hold:
            current = 1
            bars_since_flip = 0
        state[i] = current
    return pd.Series(state, index=long_cond.index)


def _ratchet_band(center: pd.Series, regime: pd.Series, atr: pd.Series,
                  multiple: float, kind: str = "tp") -> pd.Series:
    """
    One-sided ratcheting band.
      kind='tp'   : TP   band — sits on the profit side of center.
                    Long : center + multiple*ATR, only moves UP.
                    Short: center - multiple*ATR, only moves DOWN.
      kind='stop' : Stop band — sits on the loss side of center.
                    Long : center - multiple*ATR, only moves UP.
                    Short: center + multiple*ATR, only moves DOWN.
    Resets whenever the regime flips.
    """
    n           = len(center)
    band        = np.full(n, np.nan)
    prev_regime = 0

    for i in range(n):
        r = int(regime.iloc[i])
        c = center.iloc[i]
        a = atr.iloc[i]

        if r == 0 or not np.isfinite(c) or not np.isfinite(a):
            # still propagate last valid band value forward so series doesn't gap
            if i > 0 and np.isfinite(band[i-1]):
                band[i] = band[i-1]
            prev_regime = r
            continue

        raw = (c + multiple * a) if (r == 1) == (kind == "tp") \
              else (c - multiple * a)

        flipped = (r != prev_regime)
        if i == 0 or flipped or not np.isfinite(band[i - 1]):
            band[i] = raw
        elif r == 1:
            band[i] = max(band[i - 1], raw)
        else:
            band[i] = min(band[i - 1], raw)

        prev_regime = r

    return pd.Series(band, index=center.index)


# ── Main computation ──────────────────────────────────────────

def compute_adaptive_trend(symbol: str, freq: str = "daily",
                           method: str = "kama",
                           sb_er: int = 10, sb_fast: int = 2, sb_slow: int = 30,
                           mb_er: int = 20, mb_fast: int = 2, mb_slow: int = 60,
                           lb_er: int = 40, lb_fast: int = 2, lb_slow: int = 120,
                           atr_n: int = 20, confirm_mult: float = 0.25) -> dict:
    """
    Full adaptive trend computation.

    Returns JSON-ready dict containing:
      Baselines : sb, mb, lb
      Bands     : sdb, mrt, mdb, lrt, ldb
      Regimes   : short_state, medium_state, long_state
      Signals   : entry_long, entry_short
      Extras    : atr
    """
    df = db.get_ohlcv_df(symbol, freq, limit=1500)
    if df.empty:
        return {"error": "No OHLCV data found"}

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    hlc3  = (high + low + close) / 3.0

    # ── Adaptive baselines ────────────────────────────────────
    sb = _adaptive_ma(hlc3, er_len=sb_er, fast_period=sb_fast, slow_period=sb_slow, method=method)
    mb = _adaptive_ma(hlc3, er_len=mb_er, fast_period=mb_fast, slow_period=mb_slow, method=method)
    lb = _adaptive_ma(hlc3, er_len=lb_er, fast_period=lb_fast, slow_period=lb_slow, method=method)

    # ── ATR ───────────────────────────────────────────────────
    atr = _atr(high, low, close, n=atr_n)

    # ── Slopes ───────────────────────────────────────────────
    sb_slope = sb.diff()
    mb_slope = mb.diff()
    lb_slope = lb.diff()

    # Confirmation: confirm_mult × ATR avoids flipping on small wiggles
    confirm = confirm_mult * atr

    # ── Regimes ───────────────────────────────────────────────
    # Short-horizon
    sh_long  = (close > sb + 0.5 * confirm) & (sb_slope > 0)
    sh_short = (close < sb - 0.5 * confirm) & (sb_slope < 0)
    short_state = _sticky_state(sh_long.fillna(False), sh_short.fillna(False))

    # Medium-horizon (master for trade management)
    med_long  = (sb > mb + confirm) & (mb_slope > 0) & (close > mb)
    med_short = (sb < mb - confirm) & (mb_slope < 0) & (close < mb)
    medium_state = _sticky_state(med_long.fillna(False), med_short.fillna(False))

    # Long-horizon
    lng_long  = (mb > lb + confirm) & (lb_slope > 0)
    lng_short = (mb < lb - confirm) & (lb_slope < 0)
    long_state = _sticky_state(lng_long.fillna(False), lng_short.fillna(False))

    med_series = pd.Series(medium_state.values, index=df.index)
    lng_series = pd.Series(long_state.values,   index=df.index)

    # ── Ratcheting bands ──────────────────────────────────────
    sdb = _ratchet_band(sb,  med_series, atr, multiple=2.0,  kind="tp")
    mrt = _ratchet_band(mb,  med_series, atr, multiple=2.25, kind="stop")
    mdb = _ratchet_band(mb,  med_series, atr, multiple=4.5,  kind="tp")
    lrt = _ratchet_band(lb,  lng_series, atr, multiple=2.25, kind="stop")
    ldb = _ratchet_band(lb,  lng_series, atr, multiple=4.5,  kind="tp")

    # ── Entry signals ─────────────────────────────────────────
    # Only emit an entry on the FIRST bar after a regime flip,
    # excluding the very first bar of the series (no prior context).
    med_prev   = medium_state.shift(1)
    is_first   = med_prev.isna()                          # no prior data
    entry_long  = (medium_state == 1) & (med_prev != 1) & (~is_first)
    entry_short = (medium_state == -1) & (med_prev != -1) & (~is_first)

    # ── Serialise ─────────────────────────────────────────────
    def regime_list(s: pd.Series) -> list:
        return [{"date": d.strftime("%Y-%m-%d"), "value": int(v)}
                for d, v in zip(s.index, s.values)]

    def bool_list(s: pd.Series) -> list:
        return [{"date": d.strftime("%Y-%m-%d"), "value": bool(v)}
                for d, v in zip(s.index, s.values)]

    return {
        "sb":  _series_to_list(sb),
        "mb":  _series_to_list(mb),
        "lb":  _series_to_list(lb),
        "sdb": _series_to_list(sdb),
        "mrt": _series_to_list(mrt),
        "mdb": _series_to_list(mdb),
        "lrt": _series_to_list(lrt),
        "ldb": _series_to_list(ldb),
        "short_state":  regime_list(short_state),
        "medium_state": regime_list(medium_state),
        "long_state":   regime_list(long_state),
        "entry_long":   bool_list(entry_long),
        "entry_short":  bool_list(entry_short),
        "atr":          _series_to_list(atr),
    }
