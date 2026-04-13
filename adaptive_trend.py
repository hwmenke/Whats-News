"""
adaptive_trend.py — Multi-horizon Adaptive Trend System
Computes SB/MB/LB baselines, MRT/LRT stop bands, SDB/MDB/LDB TP bands,
short/medium/long regime states, and entry signals.

All key parameters are exposed through DEFAULT_PARAMS and can be
overridden per-request to support UI-driven optimization.
"""

import numpy as np
import pandas as pd
import database as db


# ── JSON helpers ──────────────────────────────────────────────

def _safe(val):
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


# ── Default parameters ────────────────────────────────────────

DEFAULT_PARAMS = {
    # Baseline MA (fast period fixed at 2 — max responsiveness ceiling)
    "sb_er": 10, "sb_slow": 15,   # short baseline
    "mb_er": 20, "mb_slow": 30,   # medium baseline  (master regime)
    "lb_er": 40, "lb_slow": 60,   # long baseline
    "fast":   2,                   # fast EMA period (shared by all three)
    # Adaptive ATR
    "atr_fast": 5,  "atr_slow": 30, "atr_er": 20,
    # Regime confirmation threshold (as ATR multiple)
    "confirm_mult": 0.10,
    # Ratchet band ATR multiples
    "sdb_mult": 2.00, "mrt_mult": 2.25, "mdb_mult": 4.50,
    "lrt_mult": 2.25, "ldb_mult": 4.50,
}


# ── Core indicators ───────────────────────────────────────────

def _adaptive_ma(src: pd.Series, er_len: int, fast_period: int,
                 slow_period: int, method: str = "kama") -> pd.Series:
    """
    Adaptive moving average.
      KAMA : alpha = (slow_sc + ER*(fast_sc-slow_sc))^2   [Kaufman squaring]
      ADMA : alpha =  slow_sc + ER*(fast_sc-slow_sc)      [linear — no squaring]
    ER = |net_move| / |sum_of_abs_moves| over er_len bars.
    """
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)
    prices  = src.values.astype(float)
    n       = len(prices)
    out     = np.full(n, np.nan)

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

        alpha  = max(min(alpha, 1.0), 0.0)
        out[i] = out[i - 1] + alpha * (prices[i] - out[i - 1])

    return pd.Series(out, index=src.index)


def _adaptive_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                  fast_n: int = 5, slow_n: int = 30, er_len: int = 20) -> pd.Series:
    """
    ER-Adaptive ATR.

    The smoothing constant adapts to the Efficiency Ratio of price:
      Trending (ER → 1): fast_n period → ATR tracks volatility changes quickly
      Choppy   (ER → 0): slow_n period → ATR stays stable, filters noise

    alpha = slow_sc + ER × (fast_sc − slow_sc)   [linear, intentionally no squaring]
    atr[i] = atr[i-1] + alpha × (TR[i] − atr[i-1])
    """
    prices = close.values.astype(float)
    highs  = high.values.astype(float)
    lows   = low.values.astype(float)
    n      = len(prices)

    # Vectorised true range
    prev_c      = np.empty(n)
    prev_c[0]   = prices[0]
    prev_c[1:]  = prices[:-1]
    tr_arr = np.maximum(
        highs - lows,
        np.maximum(np.abs(highs - prev_c), np.abs(lows - prev_c)),
    )

    fast_sc = 2.0 / (fast_n + 1)
    slow_sc = 2.0 / (slow_n + 1)
    atr_vals = np.full(n, np.nan)

    if er_len >= n:
        return pd.Series(atr_vals, index=close.index)

    # Seed with simple mean of first er_len bars
    atr_vals[er_len - 1] = np.mean(tr_arr[:er_len])

    for i in range(er_len, n):
        direction  = abs(prices[i] - prices[i - er_len])
        volatility = np.sum(np.abs(np.diff(prices[i - er_len: i + 1])))
        er         = direction / volatility if volatility > 1e-12 else 0.0

        alpha        = slow_sc + er * (fast_sc - slow_sc)
        alpha        = max(min(alpha, 1.0), slow_sc)
        atr_vals[i]  = atr_vals[i - 1] + alpha * (tr_arr[i] - atr_vals[i - 1])

    return pd.Series(atr_vals, index=close.index)


def _sticky_state(long_cond: pd.Series, short_cond: pd.Series) -> pd.Series:
    """
    Sticky regime: +1 once long fires (holds until short fires), -1 vice-versa.
    """
    state   = np.zeros(len(long_cond), dtype=int)
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
    One-sided ratcheting band (never retreats in the direction of the trade).
      kind='tp'   : TP   — Long: center + mult*ATR (ratchets UP)
      kind='stop' : Stop — Long: center - mult*ATR (ratchets UP)
    Resets on regime flip.
    """
    n           = len(center)
    band        = np.full(n, np.nan)
    prev_regime = 0

    for i in range(n):
        r = int(regime.iloc[i])
        c = center.iloc[i]
        a = atr.iloc[i]

        if r == 0 or not np.isfinite(c) or not np.isfinite(a):
            prev_regime = r
            continue

        raw     = (c + multiple * a) if (r == 1) == (kind == "tp") else (c - multiple * a)
        flipped = (r != prev_regime)

        if i == 0 or flipped or not np.isfinite(band[i - 1]):
            band[i] = raw
        elif r == 1:
            band[i] = max(band[i - 1], raw)
        else:
            band[i] = min(band[i - 1], raw)

        prev_regime = r

    return pd.Series(band, index=center.index)


# ── Full computation ──────────────────────────────────────────

def _build_trend(df: pd.DataFrame, method: str, p: dict) -> dict:
    """
    Core computation shared by compute_adaptive_trend and the optimizer.
    Returns the full trend dict (series, regimes, signals).
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    hlc3  = (high + low + close) / 3.0

    f = p["fast"]
    sb = _adaptive_ma(hlc3, p["sb_er"], f, p["sb_slow"], method)
    mb = _adaptive_ma(hlc3, p["mb_er"], f, p["mb_slow"], method)
    lb = _adaptive_ma(hlc3, p["lb_er"], f, p["lb_slow"], method)

    atr = _adaptive_atr(high, low, close, p["atr_fast"], p["atr_slow"], p["atr_er"])

    sb_slope = sb.diff()
    mb_slope = mb.diff()
    lb_slope = lb.diff()
    confirm  = p["confirm_mult"] * atr

    # Regimes
    sh_long  = (close > sb + 0.5 * confirm) & (sb_slope > 0)
    sh_short = (close < sb - 0.5 * confirm) & (sb_slope < 0)
    short_state = _sticky_state(sh_long.fillna(False), sh_short.fillna(False))

    med_long  = (sb > mb + confirm) & (mb_slope > 0) & (close > mb)
    med_short = (sb < mb - confirm) & (mb_slope < 0) & (close < mb)
    medium_state = _sticky_state(med_long.fillna(False), med_short.fillna(False))

    lng_long  = (mb > lb + confirm) & (lb_slope > 0)
    lng_short = (mb < lb - confirm) & (lb_slope < 0)
    long_state = _sticky_state(lng_long.fillna(False), lng_short.fillna(False))

    med_s = pd.Series(medium_state.values, index=df.index)
    lng_s = pd.Series(long_state.values,   index=df.index)

    sdb = _ratchet_band(sb, med_s, atr, p["sdb_mult"], "tp")
    mrt = _ratchet_band(mb, med_s, atr, p["mrt_mult"], "stop")
    mdb = _ratchet_band(mb, med_s, atr, p["mdb_mult"], "tp")
    lrt = _ratchet_band(lb, lng_s, atr, p["lrt_mult"], "stop")
    ldb = _ratchet_band(lb, lng_s, atr, p["ldb_mult"], "tp")

    med_prev    = medium_state.shift(1)
    is_first    = med_prev.isna()
    entry_long  = (medium_state == 1)  & (med_prev != 1)  & (~is_first)
    entry_short = (medium_state == -1) & (med_prev != -1) & (~is_first)

    def reg_list(s):
        return [{"date": d.strftime("%Y-%m-%d"), "value": int(v)}
                for d, v in zip(s.index, s.values)]

    def bool_list(s):
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
        "short_state":  reg_list(short_state),
        "medium_state": reg_list(medium_state),
        "long_state":   reg_list(long_state),
        "entry_long":   bool_list(entry_long),
        "entry_short":  bool_list(entry_short),
        "atr":          _series_to_list(atr),
        # Echo back active params so UI can display them
        "params": {k: p[k] for k in
                   ("sb_er","sb_slow","mb_er","mb_slow","lb_er","lb_slow",
                    "atr_fast","atr_slow","atr_er")},
    }


def compute_adaptive_trend(symbol: str, freq: str = "daily",
                           method: str = "kama",
                           params: dict = None) -> dict:
    """
    Public entry point.  `params` is an optional dict of overrides on top of
    DEFAULT_PARAMS — only the keys provided are overridden.
    """
    df = db.get_ohlcv_df(symbol, freq, limit=1500)
    if df.empty:
        return {"error": "No OHLCV data found"}

    p = {**DEFAULT_PARAMS, **(params or {})}
    return _build_trend(df, method, p)


# ── Parameter optimisation ────────────────────────────────────

def _score_params(df: pd.DataFrame, method: str, p: dict,
                  oos_frac: float = 0.30) -> float:
    """
    Score a parameter set on the out-of-sample portion of the data.

    Metric: mean 5-day forward return in long-regime bars
            minus mean 5-day forward return in short-regime bars.
    Higher = system does a better job separating bullish/bearish periods.
    A mild flip-rate penalty discourages overfitted whipsaw solutions.
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    hlc3  = (high + low + close) / 3.0

    f  = p["fast"]
    sb = _adaptive_ma(hlc3, p["sb_er"], f, p["sb_slow"], method)
    mb = _adaptive_ma(hlc3, p["mb_er"], f, p["mb_slow"], method)

    atr = _adaptive_atr(high, low, close, p["atr_fast"], p["atr_slow"], p["atr_er"])

    confirm   = p["confirm_mult"] * atr
    med_long  = (sb > mb + confirm) & (mb.diff() > 0) & (close > mb)
    med_short = (sb < mb - confirm) & (mb.diff() < 0) & (close < mb)
    med_state = _sticky_state(med_long.fillna(False), med_short.fillna(False))

    oos_n = int(len(close) * (1 - oos_frac))
    fwd5  = close.pct_change(5).shift(-5)
    state = med_state.iloc[oos_n:]
    fwd   = fwd5.iloc[oos_n:]

    l_ret = fwd[state ==  1].mean()
    s_ret = fwd[state == -1].mean()

    if not np.isfinite(l_ret) or not np.isfinite(s_ret):
        return -999.0

    separation = float(l_ret - s_ret)

    # Flip-rate penalty — discourage solutions that trade constantly
    flips     = float((med_state.iloc[oos_n:].diff().fillna(0) != 0).sum())
    flip_rate = flips / max(len(state), 1)

    return separation - flip_rate * 0.003


# Search grid ─────────────────────────────────────────────────
# (sb_er, mb_er) pairs — LB is always derived as 2× MB
_ER_PAIRS = [
    (6, 15), (8, 18), (8, 20), (10, 20),
    (10, 25), (12, 25), (12, 30), (15, 30),
]
# (sb_slow, mb_slow) pairs — LB slow = 2× MB slow
_SLOW_PAIRS = [
    (12, 25), (15, 30), (15, 40), (20, 40), (20, 50),
]
# (atr_fast, atr_slow, atr_er)
_ATR_CFGS = [
    (5, 30, 20), (5, 40, 15), (8, 30, 15),
]


def optimize_adaptive_trend(symbol: str, freq: str = "daily",
                            method: str = "kama") -> dict:
    """
    Grid search over ~120 parameter combinations.
    Returns baseline score, best score, improvement %, and the optimal params.
    Uses the last 30% of available data as the out-of-sample test set.
    """
    df = db.get_ohlcv_df(symbol, freq, limit=1500)
    if df.empty:
        return {"error": "No OHLCV data found"}
    if len(df) < 150:
        return {"error": "Insufficient data — need at least 150 bars"}

    default_p = {**DEFAULT_PARAMS}
    baseline  = _score_params(df, method, default_p)

    best_score  = baseline
    best_params = default_p.copy()

    for sb_er, mb_er in _ER_PAIRS:
        for sb_sl, mb_sl in _SLOW_PAIRS:
            for atr_f, atr_s, atr_e in _ATR_CFGS:
                p = {
                    **default_p,
                    "sb_er": sb_er, "sb_slow": sb_sl,
                    "mb_er": mb_er, "mb_slow": mb_sl,
                    "lb_er": mb_er * 2, "lb_slow": mb_sl * 2,
                    "atr_fast": atr_f, "atr_slow": atr_s, "atr_er": atr_e,
                }
                score = _score_params(df, method, p)
                if score > best_score:
                    best_score  = score
                    best_params = p.copy()

    # Keys returned to frontend (excludes internal mult constants)
    _export = ("sb_er", "sb_slow", "mb_er", "mb_slow",
               "lb_er", "lb_slow", "atr_fast", "atr_slow", "atr_er")

    improvement = 0.0
    if abs(baseline) > 1e-10:
        improvement = (best_score - baseline) / abs(baseline) * 100.0

    return {
        "baseline_score":   round(float(baseline),    6),
        "best_score":       round(float(best_score),  6),
        "improvement_pct":  round(float(improvement), 1),
        "optimal_params":   {k: best_params[k] for k in _export},
        "default_params":   {k: default_p[k]   for k in _export},
        "changed":          any(best_params[k] != default_p[k] for k in _export),
    }
