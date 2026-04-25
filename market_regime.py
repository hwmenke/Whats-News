"""
market_regime.py — Multi-factor Market Regime Classifier

Classifies the market into one of five states using three orthogonal
features computed from any symbol (defaults to SPY):

  Trend      : price / SMA-200  (above = +1, below = -1)
  Momentum   : 63-bar total return  (+5% → +1,  -5% → -1,  else 0)
  Volatility : 20-day realised vol percentile rank vs 252-bar history
               low-vol (+1) vs high-vol (-1)

Composite score  = Trend + Momentum + Vol  ∈  {-3 … +3}

State mapping:
  +3           →  BULL STRONG
  +2 / +1      →  BULL
   0           →  CHOP
  -1 / -2      →  BEAR
  -3           →  CRASH
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import database as db
import indicator_cache as cache

# ── Regime metadata ───────────────────────────────────────────
REGIME_META = {
    "BULL STRONG": {"color": "#22c55e", "bg": "rgba(34,197,94,0.15)",  "icon": "🚀", "score_range": [3,  3]},
    "BULL":        {"color": "#4ade80", "bg": "rgba(74,222,128,0.10)", "icon": "📈", "score_range": [1,  2]},
    "CHOP":        {"color": "#94a3b8", "bg": "rgba(148,163,184,0.10)","icon": "↔", "score_range": [0,  0]},
    "BEAR":        {"color": "#f87171", "bg": "rgba(248,113,113,0.10)","icon": "📉", "score_range": [-2,-1]},
    "CRASH":       {"color": "#ef4444", "bg": "rgba(239,68,68,0.15)",  "icon": "💥", "score_range": [-3,-3]},
}

_SCORE_TO_STATE = {3:"BULL STRONG", 2:"BULL", 1:"BULL",
                   0:"CHOP", -1:"BEAR", -2:"BEAR", -3:"CRASH"}


def _safe(v):
    if v is None: return None
    try:
        if np.isnan(v): return None
    except: pass
    return round(float(v), 4)


def _classify_series(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Returns (score_series, state_series) aligned to df's index.
    All non-NaN rows get a score; first 252 bars may be NaN.
    """
    close = df["close"]
    n     = len(close)

    # ── Feature 1: Trend (price vs SMA-200) ───────────────────
    sma200    = close.rolling(200, min_periods=100).mean()
    trend     = np.where(close > sma200, 1, np.where(close < sma200, -1, 0))

    # ── Feature 2: Momentum (63-bar return) ───────────────────
    ret63     = close.pct_change(63)
    momentum  = np.where(ret63 >  0.05,  1,
                np.where(ret63 < -0.05, -1, 0))

    # ── Feature 3: Volatility (20d realised vol rank) ─────────
    log_ret   = np.log(close / close.shift(1))
    hv20      = log_ret.rolling(20).std() * np.sqrt(252)
    hv20_rank = hv20.rolling(252, min_periods=50).rank(pct=True)
    # Low volatility is bullish (regime-wise) → +1 when below median
    vol_sign  = np.where(hv20_rank <  0.40,  1,
                np.where(hv20_rank >  0.70, -1, 0))

    # ── Composite score ────────────────────────────────────────
    score_arr = pd.array(trend + momentum + vol_sign, dtype="Int64")
    score_s   = pd.Series(score_arr, index=df.index, dtype="Int64")
    # Mask early bars that have NaN inputs
    mask      = sma200.isna() | ret63.isna() | hv20_rank.isna()
    score_s[mask] = pd.NA

    state_s = score_s.map(lambda s: _SCORE_TO_STATE.get(int(s), "CHOP") if pd.notna(s) else None)
    return score_s, state_s


def compute_market_regime(symbol: str = "SPY") -> dict:
    return cache.get_or_compute(
        "market_regime", symbol, "daily",
        lambda: _compute_inner(symbol),
    )


def _compute_inner(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=2000)
    if df.empty:
        return {"error": f"No data for {symbol}. Add it to your watchlist first."}

    score_s, state_s = _classify_series(df)

    # ── Current regime ─────────────────────────────────────────
    valid_idx = score_s.dropna().index
    if len(valid_idx) == 0:
        return {"error": "Insufficient data to classify regime"}

    last_date   = valid_idx[-1]
    cur_score   = int(score_s[last_date])
    cur_state   = state_s[last_date]
    cur_meta    = REGIME_META.get(cur_state, {})

    days_in = 1
    for i in range(len(valid_idx) - 2, -1, -1):
        if state_s[valid_idx[i]] == cur_state:
            days_in += 1
        else:
            break

    # ── History (last 504 bars) ────────────────────────────────
    hist_slice = df.iloc[-504:]
    sc_hist    = score_s.reindex(hist_slice.index)
    st_hist    = state_s.reindex(hist_slice.index)

    history = [
        {"date":  d.strftime("%Y-%m-%d"),
         "score": int(sc_hist[d]) if pd.notna(sc_hist[d]) else None,
         "state": st_hist[d],
         "close": round(float(hist_slice.loc[d, "close"]), 2)}
        for d in hist_slice.index
    ]

    # ── Per-regime forward-return stats ───────────────────────
    fwd5  = df["close"].pct_change(5).shift(-5)
    fwd20 = df["close"].pct_change(20).shift(-20)

    regime_stats = {}
    for state in ["BULL STRONG", "BULL", "CHOP", "BEAR", "CRASH"]:
        mask    = state_s == state
        f5      = fwd5[mask].dropna()
        f20     = fwd20[mask].dropna()
        n_days  = int(mask.sum())
        if n_days == 0:
            regime_stats[state] = {"n_days": 0}
            continue
        regime_stats[state] = {
            "n_days":        n_days,
            "fwd5_mean":     _safe(f5.mean()),
            "fwd5_hit_rate": _safe((f5 > 0).mean()),
            "fwd20_mean":    _safe(f20.mean()),
            "fwd20_hit_rate":_safe((f20 > 0).mean()),
            "pct_of_time":   round(n_days / max(len(state_s.dropna()), 1), 3),
        }

    # ── Regime transitions (last 12) ──────────────────────────
    transitions = []
    prev = None
    for d in valid_idx:
        s = state_s[d]
        if s != prev:
            transitions.append({"date": d.strftime("%Y-%m-%d"), "state": s})
            prev = s
    transitions = transitions[-12:]

    return {
        "symbol":       symbol,
        "current": {
            "state":        cur_state,
            "score":        cur_score,
            "days_in":      days_in,
            "date":         last_date.strftime("%Y-%m-%d"),
            "color":        cur_meta.get("color"),
            "bg":           cur_meta.get("bg"),
            "icon":         cur_meta.get("icon"),
        },
        "history":      history,
        "regime_stats": regime_stats,
        "transitions":  transitions,
        "regime_meta":  REGIME_META,
        "n_bars":       len(df),
    }
