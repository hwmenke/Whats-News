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
from shared_indicators import _kama
from config import KAMA_PERIODS


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

    for period in KAMA_PERIODS:
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


def scan_watchlist(symbols: list, k: int = 10) -> list:
    """
    Run KNN lookalike on every symbol in `symbols`.
    Returns a compact summary row per symbol (sorted by 5D win rate desc).
    """
    results = []
    for sym in symbols:
        try:
            r = compute_knn_lookalike(sym, k=k)
            if "error" in r:
                results.append({"symbol": sym, "error": r["error"]})
                continue
            s = r["summary"]
            results.append({
                "symbol":      sym,
                "as_of":       r["as_of"],
                "fwd_1d_win":  s["fwd_1d"]["positive_pct"],
                "fwd_1d_mean": s["fwd_1d"]["mean"],
                "fwd_5d_win":  s["fwd_5d"]["positive_pct"],
                "fwd_5d_mean": s["fwd_5d"]["mean"],
                "fwd_20d_win": s["fwd_20d"]["positive_pct"],
                "fwd_20d_mean":s["fwd_20d"]["mean"],
                "k":           r["k"],
            })
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})

    results.sort(key=lambda x: (x.get("fwd_5d_win") or 0), reverse=True)
    return results


def walk_forward_backtest(symbol: str, min_train: int = 200,
                          step: int = 21, k: int = 10, horizon: int = 5) -> dict:
    """
    Walk-forward backtest of KNN directional predictions.

    At each evaluation bar (spaced `step` bars apart, starting after `min_train`
    bars of history) the model:
      1. Fits KNN on all bars up to (but not including) the evaluation bar.
      2. Finds the K nearest historical moments.
      3. Predicts direction from the mean neighbour forward-return.
      4. Compares to actual `horizon`-bar forward return.

    Returns accuracy stats and an equity curve (long if bullish, short if bearish).
    """
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty or len(df) < min_train + horizon + 60:
        return {"error": f"Not enough data for {symbol}"}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ── Build feature matrix ─────────────────────────────────────────────
    feat = pd.DataFrame(index=df.index)
    feat["rsi14"]     = ta.momentum.RSIIndicator(close, window=14).rsi()
    feat["vol20_ann"] = close.pct_change().rolling(20).std() * np.sqrt(252)
    macd_ind          = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    feat["macd_hist"] = macd_ind.macd_diff()
    cci_ind           = ta.trend.CCIIndicator(high, low, close, window=20)
    feat["cci_norm"]  = cci_ind.cci() / 200.0
    vol_ma20          = volume.rolling(20).mean()
    feat["vol_ratio"] = volume / vol_ma20.replace(0, np.nan)
    for period in KAMA_PERIODS:
        kama_s = _kama(close, window=period)
        feat[f"kama_dist_{period}"] = (close / kama_s.replace(0, np.nan)) - 1.0

    feat["close"] = close.values

    FEATURE_COLS = [
        "rsi14", "vol20_ann", "macd_hist", "cci_norm",
        "vol_ratio", "kama_dist_10", "kama_dist_20", "kama_dist_50",
    ]

    # Keep only rows where all features are valid, then reset to integer index
    valid  = feat[FEATURE_COLS + ["close"]].dropna(subset=FEATURE_COLS)
    valid  = valid.reset_index()          # original DatetimeIndex → "date" column
    n      = len(valid)

    if n < min_train + horizon + 20:
        return {"error": f"Only {n} valid feature rows — need {min_train + horizon + 20}"}

    X_all     = valid[FEATURE_COLS].values.astype(float)
    close_arr = valid["close"].values.astype(float)
    date_arr  = valid["date"].values   # numpy datetime64

    records = []
    for eval_i in range(min_train, n - horizon, step):
        X_train    = X_all[:eval_i]
        scaler     = StandardScaler()
        X_train_sc = scaler.fit_transform(X_train)

        x_q = scaler.transform(X_all[eval_i:eval_i + 1])

        nn_k = min(k, len(X_train_sc) - 1)
        if nn_k < 3:
            continue
        nn_model = NearestNeighbors(n_neighbors=nn_k, metric="euclidean")
        nn_model.fit(X_train_sc)
        _, idxs = nn_model.kneighbors(x_q)

        # Neighbour forward returns (only include those far enough from eval_i)
        nbr_fwd = []
        for nbr_i in idxs[0]:
            fwd_i = nbr_i + horizon
            if fwd_i < eval_i and close_arr[nbr_i] != 0:
                nbr_fwd.append(
                    (close_arr[fwd_i] - close_arr[nbr_i]) / close_arr[nbr_i]
                )

        if len(nbr_fwd) < 3:
            continue

        pred_mean = float(np.mean(nbr_fwd))
        pred_dir  = 1 if pred_mean > 0 else -1

        c0 = close_arr[eval_i]
        c1 = close_arr[eval_i + horizon]
        actual_ret = (c1 - c0) / c0 if c0 != 0 else 0.0
        actual_dir = 1 if actual_ret > 0 else -1

        date_str = str(date_arr[eval_i])[:10]
        records.append({
            "date":       date_str,
            "predicted":  pred_dir,
            "pred_mean":  round(pred_mean * 100, 3),
            "actual_ret": round(actual_ret * 100, 3),
            "correct":    pred_dir == actual_dir,
        })

    if not records:
        return {"error": "No evaluation points generated (try reducing min_train)"}

    n_total   = len(records)
    n_correct = sum(1 for r in records if r["correct"])
    accuracy  = n_correct / n_total

    # Equity curve — 1 unit long or short at each evaluation bar
    cum = 0.0
    equity = [{"date": records[0]["date"], "equity": 0.0}]
    for r in records:
        pnl = r["predicted"] * (r["actual_ret"] / 100)
        cum += pnl
        equity.append({"date": r["date"], "equity": round(cum * 100, 4)})

    return {
        "symbol":       symbol,
        "horizon_days": horizon,
        "n_total":      n_total,
        "n_correct":    n_correct,
        "accuracy":     round(accuracy, 4),
        "equity_curve": equity,
        "records":      records[-60:],   # last 60 rows for the detail table
    }
