"""
knn_model.py - KNN Lookalike Engine
Finds K most similar historical moments based on current market conditions.
"""

import numpy as np
import pandas as pd
import ta
import database as db
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors


def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's Adaptive Moving Average."""
    prices = close.to_numpy(dtype=float, copy=True)
    kama_vals = np.full(len(prices), np.nan)

    if len(prices) < window:
        return pd.Series(kama_vals, index=close.index)

    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    kama_vals[window - 1] = prices[window - 1]

    for i in range(window, len(prices)):
        direction = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window: i + 1])))
        er = direction / volatility if volatility != 0 else 0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama_vals[i] = kama_vals[i - 1] + sc * (prices[i] - kama_vals[i - 1])

    return pd.Series(kama_vals, index=close.index)


def _safe_float(val):
    """Convert to Python float or None."""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        return float(val)
    except Exception:
        return None


def compute_knn_lookalike(symbol: str, k: int = 15) -> dict:
    """
    Find the K most similar historical market moments for the given symbol.

    Features used:
      - RSI(14)
      - 20-day annualised volatility
      - MACD histogram
      - CCI / 200
      - Volume ratio vs 20-day MA
      - Price-vs-KAMA distance for periods 10, 20, 50

    Returns a dict with:
      - current_features
      - neighbors (list of dicts with date, distance, fwd_1d, fwd_5d, fwd_20d)
      - summary (mean/median/positive_pct/best/worst per horizon)
      - as_of (most recent date string)
    """
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty or len(df) < 60:
        return {"error": f"Not enough data for {symbol}"}

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    # ── Build feature matrix ──────────────────────────────────────────────────
    df["rsi14"] = ta.momentum.RSIIndicator(close, window=14).rsi()

    ret_1d = close.pct_change()
    df["vol20_ann"] = ret_1d.rolling(20).std() * np.sqrt(252)

    macd_ind     = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    df["macd_hist"] = macd_ind.macd_diff()

    cci_ind  = ta.trend.CCIIndicator(high, low, close, window=20)
    df["cci_norm"] = cci_ind.cci() / 200.0

    vol_ma20 = vol.rolling(20).mean()
    df["vol_ratio"] = vol / vol_ma20.replace(0, np.nan)

    for period in [10, 20, 50]:
        kama_s = _kama(close, window=period)
        df[f"kama_dist_{period}"] = (close / kama_s.replace(0, np.nan)) - 1.0

    # Forward returns (for labelling neighbours)
    df["fwd_1d"]  = close.pct_change(1).shift(-1)
    df["fwd_5d"]  = close.pct_change(5).shift(-5)
    df["fwd_20d"] = close.pct_change(20).shift(-20)

    FEATURE_COLS = [
        "rsi14", "vol20_ann", "macd_hist", "cci_norm",
        "vol_ratio", "kama_dist_10", "kama_dist_20", "kama_dist_50",
    ]

    # Drop rows where any feature is NaN
    df_feat = df[FEATURE_COLS + ["fwd_1d", "fwd_5d", "fwd_20d"]].dropna(subset=FEATURE_COLS)
    if len(df_feat) < k + 1:
        return {"error": f"Not enough valid feature rows for {symbol}"}

    X = df_feat[FEATURE_COLS].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Last row = current state (most recent bar)
    # We exclude it from the neighbor search so it doesn't find itself.
    current_idx = len(X_scaled) - 1
    current_vec = X_scaled[current_idx].reshape(1, -1)

    # Fit on all historical points except the last one
    X_hist = X_scaled[:current_idx]
    df_hist = df_feat.iloc[:current_idx]

    nn = NearestNeighbors(n_neighbors=min(k, len(X_hist)), metric="euclidean")
    nn.fit(X_hist)
    distances, indices = nn.kneighbors(current_vec)
    distances = distances[0]
    indices   = indices[0]

    # ── Build neighbour list ──────────────────────────────────────────────────
    neighbors = []
    for dist, idx in zip(distances, indices):
        row  = df_hist.iloc[idx]
        date = df_hist.index[idx]
        neighbors.append({
            "date":     date.strftime("%Y-%m-%d"),
            "distance": round(float(dist), 4),
            "fwd_1d":   _safe_float(row["fwd_1d"]),
            "fwd_5d":   _safe_float(row["fwd_5d"]),
            "fwd_20d":  _safe_float(row["fwd_20d"]),
        })

    # ── Summary stats per horizon ─────────────────────────────────────────────
    def horizon_summary(key):
        vals = [n[key] for n in neighbors if n[key] is not None]
        if not vals:
            return {"mean": None, "median": None, "positive_pct": None, "best": None, "worst": None}
        arr = np.array(vals)
        return {
            "mean":         round(float(np.mean(arr)), 6),
            "median":       round(float(np.median(arr)), 6),
            "positive_pct": round(float((arr > 0).mean()), 4),
            "best":         round(float(arr.max()), 6),
            "worst":        round(float(arr.min()), 6),
        }

    summary = {
        "fwd_1d":  horizon_summary("fwd_1d"),
        "fwd_5d":  horizon_summary("fwd_5d"),
        "fwd_20d": horizon_summary("fwd_20d"),
    }

    # ── Current feature values (unscaled) ─────────────────────────────────────
    current_raw = df_feat[FEATURE_COLS].iloc[-1]
    current_features = {col: _safe_float(current_raw[col]) for col in FEATURE_COLS}

    return {
        "symbol":           symbol,
        "as_of":            df_feat.index[-1].strftime("%Y-%m-%d"),
        "k":                k,
        "current_features": current_features,
        "neighbors":        neighbors,
        "summary":          summary,
    }
