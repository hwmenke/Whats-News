"""
knn_forecast.py — Weighted KNN Pattern-Recognition & Multi-Horizon Forecast

Algorithm:
  1. Build a 17-feature matrix covering 5 groups (trend, momentum,
     volatility, price_action, volume) from OHLCV history.
  2. Normalize each feature with z-score across the training window,
     clip to [-3, 3] for outlier robustness.
  3. Apply group-level weights to the per-feature squared errors before
     summing into a weighted Euclidean distance.
  4. Find the K training bars most similar to the current (last) bar.
  5. For each bar in the K-set, look forward h bars and compute returns.
  6. Return per-horizon statistics + the top-K neighbor table.

Lookahead safety: training candidates are restricted to bars that have at
least MAX_HORIZON bars of future price data available (i.e. indices
0 … N-1-MAX_HORIZON).  The query is always the most recent bar (index N-1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import database as db
import indicator_cache as cache
from ta_core import _kama, _rsi, _bollinger, _macd

# ── Constants ─────────────────────────────────────────────────
HORIZONS      = [5, 20, 63, 126]          # bars forward
MAX_HORIZON   = max(HORIZONS)             # 126
MIN_TRAIN     = 150                       # minimum training bars needed

DEFAULT_WEIGHTS = {
    "trend":        0.25,
    "momentum":     0.25,
    "volatility":   0.20,
    "price_action": 0.20,
    "volume":       0.10,
}

# ── Feature catalogue ─────────────────────────────────────────
# Each entry: (internal_key, group, label, description)
FEATURE_CATALOGUE = [
    # Trend
    ("kama10_dist",  "trend",        "KAMA-10 Distance",   "How far close is from fast KAMA (in ATR units). Positive = above KAMA (bullish location)."),
    ("kama20_dist",  "trend",        "KAMA-20 Distance",   "Position relative to medium KAMA. Core trend-alignment signal."),
    ("kama50_dist",  "trend",        "KAMA-50 Distance",   "Position relative to slow KAMA. Macro structural position."),
    ("kama_slope",   "trend",        "KAMA-10 Slope",      "5-bar rate-of-change of fast KAMA (ATR-normalised). Positive = accelerating uptrend."),
    # Momentum
    ("rsi14",        "momentum",     "RSI-14",             "Classic Wilder RSI. > 70 overbought, < 30 oversold. Persistence matters as much as extremes."),
    ("rsi7",         "momentum",     "RSI-7",              "Fast RSI. Captures intra-trend micro-momentum reversals and short pullbacks."),
    ("roc5",         "momentum",     "ROC-5",              "5-bar log return. Raw price momentum over the past week of trading."),
    ("roc20",        "momentum",     "ROC-20",             "20-bar log return. Medium-term momentum — whether the market is in a runup or pullback phase."),
    ("macd_hist",    "momentum",     "MACD Histogram",     "MACD(12,26,9) histogram normalised by ATR. Positive and rising = strengthening momentum."),
    # Volatility
    ("atr_rank",     "volatility",   "ATR Percentile",     "ATR-14 as % of price, then ranked over 252 bars. High rank = unusually volatile; low = compressed."),
    ("bb_pct",       "volatility",   "BB %B",              "Bollinger Band %B (20-bar, 2σ). 0 = at lower band, 1 = at upper band, outside = mean-reversion signal."),
    ("hv20_rank",    "volatility",   "HV-20 Rank",         "20-day realized vol (annualised) percentile over 252 bars. High = expansion phase, low = contraction."),
    # Price Action
    ("body_ratio",   "price_action", "Candle Body %",      "Body as % of total range. High = conviction bar; low = indecision / doji. Range [0, 1]."),
    ("upper_shadow", "price_action", "Upper Shadow %",     "Upper wick fraction of range. High = selling pressure / rejection at highs (bearish weight)."),
    ("streak",       "price_action", "Close Streak",       "Consecutive bars closing above/below prior close, normalised to [-1, +1]. Momentum persistence signal."),
    # Volume
    ("vol_ratio",    "volume",       "Relative Volume",    "Log(volume / 20-bar EMA of volume). Positive = above-average participation; negative = light trade."),
    ("obv_slope",    "volume",       "OBV Slope",          "5-bar On-Balance-Volume change, normalised. Rising OBV with rising price = healthy accumulation."),
]

FEATURE_KEYS   = [f[0] for f in FEATURE_CATALOGUE]
FEATURE_GROUPS = {f[0]: f[1] for f in FEATURE_CATALOGUE}
FEATURE_LABELS = {f[0]: f[2] for f in FEATURE_CATALOGUE}
FEATURE_DESCS  = {f[0]: f[3] for f in FEATURE_CATALOGUE}

# Features per group (for per-feature weight = group_weight / group_size)
from collections import defaultdict as _dd
_GROUP_FEATURES: dict[str, list[str]] = _dd(list)
for _k, _g, *_ in FEATURE_CATALOGUE:
    _GROUP_FEATURES[_g].append(_k)
_GROUP_FEATURES = dict(_GROUP_FEATURES)


# ── ATR-14 helper (simple Wilder, no ta_core dependency) ──────
def _atr14(df: pd.DataFrame) -> pd.Series:
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    n     = len(close)
    prev  = np.empty(n);  prev[0] = close[0];  prev[1:] = close[:-1]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = np.full(n, np.nan)
    if n < 14:
        return pd.Series(atr, index=df.index)
    atr[13] = tr[:14].mean()
    alpha   = 1.0 / 14.0
    for i in range(14, n):
        atr[i] = atr[i - 1] + alpha * (tr[i] - atr[i - 1])
    return pd.Series(atr, index=df.index)


def _pct_rank(series: pd.Series, window: int = 252) -> pd.Series:
    """Rolling percentile rank [0, 1]."""
    def _rank(x):
        return (x[:-1] < x[-1]).sum() / max(len(x) - 1, 1)
    return series.rolling(window, min_periods=20).apply(_rank, raw=True)


# ── Feature engineering ───────────────────────────────────────
def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construct the full 17-column feature DataFrame aligned to df's index.
    All features are dimensionless (ratios, normalised by ATR or rank).
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    eps    = 1e-10
    atr    = _atr14(df)
    atr_s  = atr.clip(lower=eps)     # safe ATR for division

    # ── Trend ──────────────────────────────────────────────────
    k10 = _kama(close, window=10)
    k20 = _kama(close, window=20)
    k50 = _kama(close, window=50)

    kama10_dist = (close - k10) / atr_s
    kama20_dist = (close - k20) / atr_s
    kama50_dist = (close - k50) / atr_s
    kama_slope  = k10.diff(5) / atr_s

    # ── Momentum ───────────────────────────────────────────────
    rsi14    = _rsi(close, window=14)
    rsi7     = _rsi(close, window=7)
    roc5     = np.log(close / close.shift(5).replace(0, np.nan))
    roc20    = np.log(close / close.shift(20).replace(0, np.nan))
    _, _, macd_h = _macd(close)
    macd_hist = macd_h / atr_s

    # ── Volatility ─────────────────────────────────────────────
    atr_pct   = atr / close.clip(lower=eps)
    atr_rank  = _pct_rank(atr_pct, 252)

    upper, mid, lower = _bollinger(close, window=20, num_std=2.0)
    band_range = (upper - lower).clip(lower=eps)
    bb_pct     = (close - lower) / band_range

    log_ret    = np.log(close / close.shift(1).replace(0, np.nan))
    hv20       = log_ret.rolling(20).std() * np.sqrt(252)
    hv20_rank  = _pct_rank(hv20, 252)

    # ── Price Action ───────────────────────────────────────────
    candle_range = (high - low).clip(lower=eps)
    body         = (close - open_).abs()
    body_ratio   = body / candle_range

    hi_shadow    = high - pd.concat([open_, close], axis=1).max(axis=1)
    upper_shadow = hi_shadow.clip(lower=0) / candle_range

    # Consecutive up/down streak (capped at ±5, normalised to [-1,+1])
    direction = np.sign(close.diff()).fillna(0).astype(int).values
    streak_vals = np.zeros(len(direction))
    cur = 0
    for i in range(1, len(direction)):
        d = direction[i]
        if d == 0:
            cur = 0
        elif d == cur / max(abs(cur), 1) or cur == 0:
            cur = cur + d
        else:
            cur = d
        streak_vals[i] = np.clip(cur, -5, 5)
    streak = pd.Series(streak_vals / 5.0, index=close.index)

    # ── Volume ─────────────────────────────────────────────────
    vol_ema20  = volume.ewm(span=20, adjust=False).mean().clip(lower=1)
    vol_ratio  = np.log((volume / vol_ema20).clip(lower=eps))

    obv       = (np.sign(close.diff()) * volume).cumsum()
    obv_std   = obv.rolling(20).std().clip(lower=eps)
    obv_slope = obv.diff(5) / obv_std

    # ── Assemble ───────────────────────────────────────────────
    feats = pd.DataFrame({
        "kama10_dist":  kama10_dist,
        "kama20_dist":  kama20_dist,
        "kama50_dist":  kama50_dist,
        "kama_slope":   kama_slope,
        "rsi14":        rsi14,
        "rsi7":         rsi7,
        "roc5":         roc5,
        "roc20":        roc20,
        "macd_hist":    macd_hist,
        "atr_rank":     atr_rank,
        "bb_pct":       bb_pct,
        "hv20_rank":    hv20_rank,
        "body_ratio":   body_ratio,
        "upper_shadow": upper_shadow,
        "streak":       streak,
        "vol_ratio":    vol_ratio,
        "obv_slope":    obv_slope,
    }, index=df.index)

    return feats


# ── Normalisation ─────────────────────────────────────────────
def _zscore(mat: np.ndarray, query: np.ndarray):
    """Z-score mat and query using mat's stats, clip to [-3, 3]."""
    mu  = np.nanmean(mat, axis=0)
    std = np.nanstd(mat,  axis=0)
    std = np.where(std < 1e-10, 1.0, std)
    mat_n   = np.clip((mat   - mu) / std, -3, 3)
    query_n = np.clip((query - mu) / std, -3, 3)
    return mat_n, query_n


# ── Per-feature weights ───────────────────────────────────────
def _feature_weights(group_weights: dict) -> np.ndarray:
    """
    Expand group weights to per-feature weights so each group's total
    contribution equals its group weight regardless of feature count.
    Returns array aligned to FEATURE_KEYS order.
    """
    w = np.zeros(len(FEATURE_KEYS))
    for i, key in enumerate(FEATURE_KEYS):
        grp    = FEATURE_GROUPS[key]
        gw     = group_weights.get(grp, DEFAULT_WEIGHTS.get(grp, 0.0))
        n_feat = len(_GROUP_FEATURES.get(grp, [1]))
        w[i]   = gw / n_feat
    # Normalise so weights sum to 1
    total = w.sum()
    return w / total if total > 1e-10 else w


# ── KNN core ──────────────────────────────────────────────────
def _weighted_knn(mat_n: np.ndarray, query_n: np.ndarray,
                  feat_w: np.ndarray, k: int):
    """
    Weighted Euclidean distance from query to every row of mat_n.
    Returns (sorted_indices, sorted_distances).
    """
    diff  = mat_n - query_n[np.newaxis, :]           # (n_train, n_feat)
    dist  = np.sqrt((feat_w * diff ** 2).sum(axis=1)) # (n_train,)
    idx   = np.argsort(dist)[:k]
    return idx, dist[idx]


# ── Forward-return helper ─────────────────────────────────────
def _fwd_returns(close: np.ndarray, neighbor_idxs: np.ndarray,
                 horizon: int) -> np.ndarray:
    """
    Log forward returns: log(close[i+h] / close[i]) for each neighbor.
    Neighbor indices reference positions in the TRAINING slice, which is
    offset from the start of close.  We store the absolute position in
    train_abs_idx separately.
    """
    rets = []
    for abs_i in neighbor_idxs:
        future = abs_i + horizon
        if future < len(close):
            r = np.log(close[future] / close[abs_i]) if close[abs_i] > 0 else np.nan
        else:
            r = np.nan
        rets.append(r)
    return np.array(rets)


# ── Horizon summary ───────────────────────────────────────────
def _horizon_stats(rets: np.ndarray, horizon: int) -> dict:
    valid = rets[np.isfinite(rets)]
    if len(valid) == 0:
        return {"horizon": horizon, "n": 0,
                "bull_pct": None, "mean_ret": None,
                "q25": None, "median": None, "q75": None, "confidence": None}

    bull_pct  = float((valid > 0).mean())
    mean_ret  = float(valid.mean())
    q25, med, q75 = float(np.percentile(valid, 25)), \
                    float(np.percentile(valid, 50)), \
                    float(np.percentile(valid, 75))
    # Confidence: tighter IQR → higher confidence
    iqr        = q75 - q25
    confidence = float(max(0.0, 1.0 - iqr / (abs(mean_ret) + 0.05)))

    return {
        "horizon":    horizon,
        "n":          int(len(valid)),
        "bull_pct":   round(bull_pct, 4),
        "mean_ret":   round(mean_ret, 4),
        "q25":        round(q25, 4),
        "median":     round(med, 4),
        "q75":        round(q75, 4),
        "confidence": round(min(confidence, 1.0), 3),
    }


# ── Public entry point ────────────────────────────────────────
def compute_knn_forecast(symbol: str, freq: str = "daily",
                         k: int = 20,
                         group_weights: dict | None = None) -> dict:
    return cache.get_or_compute(
        "knn_forecast", symbol, freq,
        lambda: _compute_inner(symbol, freq, k, group_weights),
        k=k,
        weights=tuple(sorted((group_weights or DEFAULT_WEIGHTS).items())),
    )


def _compute_inner(symbol: str, freq: str, k: int,
                   group_weights: dict | None) -> dict:
    df = db.get_ohlcv_df(symbol, freq, limit=2000)
    if df.empty:
        return {"error": "No OHLCV data"}
    if len(df) < MIN_TRAIN + MAX_HORIZON:
        return {"error": f"Need at least {MIN_TRAIN + MAX_HORIZON} bars; got {len(df)}"}

    gw      = {**DEFAULT_WEIGHTS, **(group_weights or {})}
    feat_w  = _feature_weights(gw)

    # Build full feature matrix (dates × features)
    feats   = _build_features(df)

    # Drop rows with any NaN — keeps the index aligned to df
    valid_mask = feats.notna().all(axis=1)
    feats_clean = feats[valid_mask]
    df_clean    = df[valid_mask]

    n           = len(feats_clean)
    close_arr   = df_clean["close"].values.astype(float)
    dates_arr   = [d.strftime("%Y-%m-%d") for d in df_clean.index]
    feat_arr    = feats_clean[FEATURE_KEYS].values.astype(float)

    # The query is the last bar (index n-1 in the clean array)
    # Training candidates are 0 … n-1-MAX_HORIZON (safe lookahead window)
    train_end   = n - 1 - MAX_HORIZON      # inclusive upper bound for training
    if train_end < MIN_TRAIN:
        return {"error": "Not enough training history after feature warm-up"}

    train_mat   = feat_arr[:train_end + 1]   # (n_train, n_feat)
    query_vec   = feat_arr[n - 1]            # (n_feat,)

    mat_n, query_n = _zscore(train_mat, query_vec)
    k_actual       = min(k, train_end + 1)
    train_idxs, distances = _weighted_knn(mat_n, query_n, feat_w, k_actual)

    # Map relative train indices → absolute positions in clean array
    abs_idxs = train_idxs   # already absolute (train_mat is prefix of feat_arr)

    # ── Horizon forecasts ─────────────────────────────────────
    horizon_results = []
    neighbor_rets   = {}
    for h in HORIZONS:
        rets  = _fwd_returns(close_arr, abs_idxs, h)
        neighbor_rets[h] = rets
        horizon_results.append(_horizon_stats(rets, h))

    # ── Neighbor table ────────────────────────────────────────
    max_dist    = distances.max() if distances.max() > 1e-10 else 1.0
    similarity  = 1.0 - distances / max_dist     # [0, 1] — higher = more similar

    neighbors = []
    for rank, (abs_i, dist, sim) in enumerate(zip(abs_idxs, distances, similarity)):
        row = {
            "rank":       rank + 1,
            "date":       dates_arr[abs_i],
            "similarity": round(float(sim), 4),
            "distance":   round(float(dist), 4),
        }
        for h in HORIZONS:
            r = neighbor_rets[h][rank]
            row[f"ret_h{h}"] = round(float(r), 4) if np.isfinite(r) else None
        neighbors.append(row)

    # ── Current feature snapshot (query bar) ─────────────────
    feat_snap = {}
    for key in FEATURE_KEYS:
        val = float(feats_clean[key].iloc[-1])
        feat_snap[key] = {
            "value":  round(val, 4) if np.isfinite(val) else None,
            "norm":   round(float(query_n[FEATURE_KEYS.index(key)]), 3),
            "group":  FEATURE_GROUPS[key],
            "label":  FEATURE_LABELS[key],
            "desc":   FEATURE_DESCS[key],
        }

    # ── Group importance (mean absolute weight × feature count) ──
    group_contrib = {}
    for grp in DEFAULT_WEIGHTS:
        keys_in_grp = _GROUP_FEATURES.get(grp, [])
        idxs        = [FEATURE_KEYS.index(k) for k in keys_in_grp if k in FEATURE_KEYS]
        contrib     = float(feat_w[idxs].sum()) if idxs else 0.0
        group_contrib[grp] = round(contrib, 4)

    return {
        "symbol":        symbol,
        "freq":          freq,
        "k":             k_actual,
        "n_train":       train_end + 1,
        "query_date":    dates_arr[-1],
        "horizons":      horizon_results,
        "neighbors":     neighbors,
        "features":      feat_snap,
        "group_weights": {g: round(gw[g], 3) for g in DEFAULT_WEIGHTS},
        "group_contrib": group_contrib,
    }
