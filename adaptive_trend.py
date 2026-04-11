"""
adaptive_trend.py - Multi-horizon Adaptive Trend System
Computes SB/MB/LB baselines, MRT/LRT stop bands, SDB/MDB/LDB TP bands,
short/medium/long regime states, and entry signals.
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
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return float(val)
    return val


def _series_to_list(s: pd.Series) -> list:
    return [{"date": d.strftime("%Y-%m-%d"), "value": _safe(v)}
            for d, v in zip(s.index, s.values)]


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    """Wilder's Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder smoothing: seed with simple mean, then EMA with alpha=1/n
    atr_vals = np.full(len(tr), np.nan)
    valid_start = tr.first_valid_index()
    if valid_start is None:
        return pd.Series(atr_vals, index=close.index)
    idx0 = close.index.get_loc(valid_start)
    seed_end = idx0 + n
    if seed_end >= len(tr):
        return pd.Series(atr_vals, index=close.index)
    atr_vals[seed_end - 1] = tr.iloc[idx0:seed_end].mean()
    for i in range(seed_end, len(tr)):
        atr_vals[i] = atr_vals[i - 1] + (tr.iloc[i] - atr_vals[i - 1]) / n
    return pd.Series(atr_vals, index=close.index)


def _adaptive_ma(src: pd.Series, er_len: int, fast_period: int, slow_period: int,
                 method: str = "kama") -> pd.Series:
    """
    Adaptive moving average: KAMA (Kaufman) or ADMA (generic efficiency-ratio EMA).

    KAMA:  alpha = (slow_sc + ER * (fast_sc - slow_sc)) ** 2
    ADMA:  alpha = slow_sc + ER * (fast_sc - slow_sc)   [no squaring]

    where fast_sc = 2/(fast_period+1), slow_sc = 2/(slow_period+1)
    """
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    prices = src.values.astype(float)
    n = len(prices)
    out = np.full(n, np.nan)

    # Find first finite value
    first_valid = next((i for i, v in enumerate(prices) if np.isfinite(v)), None)
    if first_valid is None:
        return pd.Series(out, index=src.index)

    seed = first_valid + er_len
    if seed >= n:
        return pd.Series(out, index=src.index)

    out[seed - 1] = prices[seed - 1]

    for i in range(seed, n):
        if not np.isfinite(prices[i]):
            out[i] = out[i - 1]
            continue
        direction = abs(prices[i] - prices[i - er_len])
        window = prices[i - er_len: i + 1]
        volatility = np.sum(np.abs(np.diff(window)))
        er = direction / volatility if volatility > 1e-12 else 0.0

        if method == "kama":
            alpha = (slow_sc + er * (fast_sc - slow_sc)) ** 2
        else:  # adma — no squaring
            alpha = slow_sc + er * (fast_sc - slow_sc)

        alpha = max(min(alpha, 1.0), 0.0)
        out[i] = out[i - 1] + alpha * (prices[i] - out[i - 1])

    return pd.Series(out, index=src.index)


def _sticky_state(long_cond: pd.Series, short_cond: pd.Series) -> pd.Series:
    """
    Sticky regime:  +1 once long_cond fires, holds until short_cond fires.
                    -1 once short_cond fires, holds until long_cond fires.
                     0 while neither has fired yet.
    """
    state = np.zeros(len(long_cond), dtype=int)
    current = 0
    for i in range(len(long_cond)):
        if current >= 0 and short_cond.iloc[i]:
            current = -1
        elif current <= 0 and long_cond.iloc[i]:
            current = 1
        state[i] = current
    return pd.Series(state, index=long_cond.index)


def _ratchet_band(center: pd.Series, regime: pd.Series, atr: pd.Series,
                  multiple: float, kind: str = "tp") -> pd.Series:
    """
    One-sided ratcheting band.

    kind='tp':   TP band — sits on the profit side of the baseline.
                 Long  regime: center + multiple*ATR, only moves UP.
                 Short regime: center - multiple*ATR, only moves DOWN.

    kind='stop': Stop band — sits on the loss side of the baseline.
                 Long  regime: center - multiple*ATR, only moves UP.
                 Short regime: center + multiple*ATR, only moves DOWN.

    Resets to raw target whenever the regime flips.
    """
    n = len(center)
    band = np.full(n, np.nan)
    prev_regime = 0

    for i in range(n):
        r = int(regime.iloc[i])
        c = center.iloc[i]
        a = atr.iloc[i]

        if r == 0 or not np.isfinite(c) or not np.isfinite(a):
            prev_regime = r
            continue

        if kind == "tp":
            raw = c + multiple * a if r == 1 else c - multiple * a
        else:  # stop
            raw = c - multiple * a if r == 1 else c + multiple * a

        regime_flipped = (r != prev_regime)

        if i == 0 or regime_flipped or np.isnan(band[i - 1]):
            band[i] = raw
        else:
            if r == 1:
                band[i] = max(band[i - 1], raw)
            else:
                band[i] = min(band[i - 1], raw)

        prev_regime = r

    return pd.Series(band, index=center.index)


def compute_adaptive_trend(symbol: str, freq: str = "daily",
                           method: str = "kama") -> dict:
    """
    Full adaptive trend computation for one symbol + frequency.

    Returns a dict ready for JSON serialisation, containing:
      SB, MB, LB, SDB, MRT, MDB, LRT, LDB,
      short_state, medium_state, long_state,
      entry_long, entry_short
    """
    df = db.get_ohlcv_df(symbol, freq, limit=1000)
    if df.empty:
        return {"error": "No OHLCV data found"}

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    hlc3  = (high + low + close) / 3.0

    # ── Adaptive baselines ────────────────────────────────────
    sb = _adaptive_ma(hlc3, er_len=10, fast_period=2, slow_period=15, method=method)
    mb = _adaptive_ma(hlc3, er_len=20, fast_period=2, slow_period=30, method=method)
    lb = _adaptive_ma(hlc3, er_len=40, fast_period=2, slow_period=60, method=method)

    # ── ATR ───────────────────────────────────────────────────
    atr = _atr(high, low, close, n=20)

    # ── Slopes (1-bar diff of baselines) ─────────────────────
    sb_slope = sb.diff()
    mb_slope = mb.diff()
    lb_slope = lb.diff()

    # ── Confirmation threshold ────────────────────────────────
    # 0.10 * ATR: keeps regime from flipping on tiny wiggles
    confirm = 0.10 * atr

    # ── Regime conditions ─────────────────────────────────────
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

    # ── Entry signals (medium regime flip) ────────────────────
    med_prev = medium_state.shift(1).fillna(0).astype(int)
    entry_long  = (medium_state == 1) & (med_prev != 1)
    entry_short = (medium_state == -1) & (med_prev != -1)

    # ── Serialise ─────────────────────────────────────────────
    def regime_list(s: pd.Series) -> list:
        """Emit {date, value} for integer regime series; use 0 for NaN."""
        return [{"date": d.strftime("%Y-%m-%d"), "value": int(v)}
                for d, v in zip(s.index, s.values)]

    def bool_list(s: pd.Series) -> list:
        return [{"date": d.strftime("%Y-%m-%d"), "value": bool(v)}
                for d, v in zip(s.index, s.values)]

    return {
        # Baselines
        "sb":  _series_to_list(sb),
        "mb":  _series_to_list(mb),
        "lb":  _series_to_list(lb),
        # Bands
        "sdb": _series_to_list(sdb),
        "mrt": _series_to_list(mrt),
        "mdb": _series_to_list(mdb),
        "lrt": _series_to_list(lrt),
        "ldb": _series_to_list(ldb),
        # Regimes
        "short_state":  regime_list(short_state),
        "medium_state": regime_list(medium_state),
        "long_state":   regime_list(long_state),
        # Signals
        "entry_long":  bool_list(entry_long),
        "entry_short": bool_list(entry_short),
        # ATR (for reference)
        "atr": _series_to_list(atr),
    }
