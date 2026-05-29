"""
knn_model.py - KNN Lookalike Engine
Finds K most similar historical moments based on current market conditions.
"""

from __future__ import annotations

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

    # ── Ensemble composite + confidence ───────────────────────────────────────
    # Composite: weighted blend of the three horizon win-rates, mapped to -100..+100
    weights = {"fwd_1d": 0.2, "fwd_5d": 0.4, "fwd_20d": 0.4}
    comp_num, comp_den = 0.0, 0.0
    for key, w in weights.items():
        pp = summary[key]["positive_pct"]
        if pp is not None:
            comp_num += w * (pp - 0.5) * 2  # center 50% → 0, scale to -1..+1
            comp_den += w
    ensemble_score = round(comp_num / comp_den * 100, 1) if comp_den else None

    # Confidence: how tight are the K neighbour distances? Lower spread = higher
    # confidence. Normalised so 0 spread → 1.0, large spread → →0.
    dist_arr = np.array([n["distance"] for n in neighbors], dtype=float)
    if len(dist_arr) >= 2 and dist_arr.mean() > 0:
        cv = dist_arr.std() / dist_arr.mean()           # coefficient of variation
        confidence = round(float(max(0.0, min(1.0, 1.0 - cv))), 3)
    else:
        confidence = None

    if ensemble_score is None:
        ensemble_label = "—"
    elif ensemble_score >=  40: ensemble_label = "STRONG BULL"
    elif ensemble_score >=  15: ensemble_label = "BULLISH"
    elif ensemble_score <= -40: ensemble_label = "STRONG BEAR"
    elif ensemble_score <= -15: ensemble_label = "BEARISH"
    else:                       ensemble_label = "NEUTRAL"

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
        "ensemble_score":   ensemble_score,
        "ensemble_label":   ensemble_label,
        "confidence":       confidence,
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


def feature_importance(symbol: str, k: int = 15, n_perms: int = 20) -> dict:
    """
    Permutation importance: for each feature, shuffle it n_perms times and
    measure how much the mean distance to the K nearest neighbours increases.
    Larger increase = more important feature.
    """
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty or len(df) < 60:
        return {"error": f"Not enough data for {symbol}"}

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    df["rsi14"]     = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["vol20_ann"] = close.pct_change().rolling(20).std() * np.sqrt(252)
    macd_ind        = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    df["macd_hist"] = macd_ind.macd_diff()
    cci_ind         = ta.trend.CCIIndicator(high, low, close, window=20)
    df["cci_norm"]  = cci_ind.cci() / 200.0
    vol_ma20        = vol.rolling(20).mean()
    df["vol_ratio"] = vol / vol_ma20.replace(0, np.nan)
    for period in KAMA_PERIODS:
        kama_s = _kama(close, window=period)
        df[f"kama_dist_{period}"] = (close / kama_s.replace(0, np.nan)) - 1.0

    FEATURE_COLS = [
        "rsi14", "vol20_ann", "macd_hist", "cci_norm",
        "vol_ratio", "kama_dist_10", "kama_dist_20", "kama_dist_50",
    ]
    FEATURE_LABELS = {
        "rsi14":        "RSI(14)",
        "vol20_ann":    "Volatility 20D",
        "macd_hist":    "MACD Histogram",
        "cci_norm":     "CCI / 200",
        "vol_ratio":    "Volume Ratio",
        "kama_dist_10": "vs KAMA-10",
        "kama_dist_20": "vs KAMA-20",
        "kama_dist_50": "vs KAMA-50",
    }

    df_feat = df[FEATURE_COLS].dropna(subset=FEATURE_COLS)
    if len(df_feat) < k + 10:
        return {"error": "Not enough valid rows"}

    X      = df_feat[FEATURE_COLS].values.astype(float)
    scaler = StandardScaler()
    Xs     = scaler.fit_transform(X)

    current_vec = Xs[-1:].copy()
    X_hist      = Xs[:-1]

    nn = NearestNeighbors(n_neighbors=min(k, len(X_hist) - 1), metric="euclidean")
    nn.fit(X_hist)
    base_dists, _ = nn.kneighbors(current_vec)
    base_mean     = float(base_dists[0].mean())

    importances = []
    rng = np.random.default_rng(42)
    for i, col in enumerate(FEATURE_COLS):
        increases = []
        for _ in range(n_perms):
            X_perm        = Xs.copy()
            perm_idx      = rng.permutation(len(X_perm))
            X_perm[:, i]  = X_perm[perm_idx, i]
            c_perm        = X_perm[-1:]
            h_perm        = X_perm[:-1]
            nn_p = NearestNeighbors(n_neighbors=min(k, len(h_perm) - 1), metric="euclidean")
            nn_p.fit(h_perm)
            d_perm, _     = nn_p.kneighbors(c_perm)
            increases.append(float(d_perm[0].mean()) - base_mean)
        importances.append({
            "feature":   col,
            "label":     FEATURE_LABELS.get(col, col),
            "importance": round(float(np.mean(increases)), 6),
            "value":     round(float(df_feat[col].iloc[-1]), 6),
        })

    importances.sort(key=lambda x: x["importance"], reverse=True)
    max_imp = max(abs(x["importance"]) for x in importances) or 1
    for x in importances:
        x["pct"] = round(x["importance"] / max_imp * 100, 1)

    return {
        "symbol":      symbol,
        "base_dist":   round(base_mean, 4),
        "features":    importances,
    }


def cluster_watchlist(symbols: list, n_clusters: int = 4) -> dict:
    """
    Cluster watchlist symbols by current market state using K-means on
    the same 8 features as compute_knn_lookalike.

    Returns clusters with member symbols and centroid feature values.
    """
    from sklearn.cluster import KMeans

    FEATURE_COLS = [
        "rsi14", "vol20_ann", "macd_hist", "cci_norm",
        "vol_ratio", "kama_dist_10", "kama_dist_20", "kama_dist_50",
    ]

    feature_rows = {}
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=5000)
            if df.empty or len(df) < 60:
                continue

            close = df["close"]
            high  = df["high"]
            low   = df["low"]
            vol   = df["volume"]

            df2 = df.copy()
            df2["rsi14"]     = ta.momentum.RSIIndicator(close, window=14).rsi()
            df2["vol20_ann"] = close.pct_change().rolling(20).std() * np.sqrt(252)
            macd_i           = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
            df2["macd_hist"] = macd_i.macd_diff()
            cci_i            = ta.trend.CCIIndicator(high, low, close, window=20)
            df2["cci_norm"]  = cci_i.cci() / 200.0
            vol_ma20         = vol.rolling(20).mean()
            df2["vol_ratio"] = vol / vol_ma20.replace(0, np.nan)
            for p in KAMA_PERIODS:
                kama_s = _kama(close, window=p)
                df2[f"kama_dist_{p}"] = (close / kama_s.replace(0, np.nan)) - 1.0

            last = df2[FEATURE_COLS].dropna(subset=FEATURE_COLS)
            if last.empty:
                continue
            row = last.iloc[-1]
            feature_rows[sym] = {col: float(row[col]) for col in FEATURE_COLS}
        except Exception:
            continue

    if len(feature_rows) < 2:
        return {"error": "Not enough symbols with data for clustering"}

    syms = list(feature_rows.keys())
    X = np.array([[feature_rows[s][f] for f in FEATURE_COLS] for s in syms])

    # Impute NaN with column mean
    for j in range(X.shape[1]):
        col = X[:, j]
        finite = col[np.isfinite(col)]
        col[~np.isfinite(col)] = float(np.mean(finite)) if len(finite) else 0.0

    k = min(n_clusters, len(syms))
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(Xs)

    # Group symbols by cluster
    cluster_map: dict[int, list] = {}
    for i, sym in enumerate(syms):
        c = int(labels[i])
        cluster_map.setdefault(c, []).append(sym)

    # Build result with centroid features + cluster characterisation
    LABEL_MAP = {
        "rsi14":        "RSI(14)",
        "vol20_ann":    "Vol Ann.",
        "macd_hist":    "MACD Hist",
        "cci_norm":     "CCI/200",
        "vol_ratio":    "Vol Ratio",
        "kama_dist_10": "vs KAMA-10",
        "kama_dist_20": "vs KAMA-20",
        "kama_dist_50": "vs KAMA-50",
    }
    CLUSTER_LABELS = ["A", "B", "C", "D"]

    result = []
    for c_id, members in sorted(cluster_map.items()):
        centroid = {}
        for feat in FEATURE_COLS:
            vals = [feature_rows[s][feat] for s in members if np.isfinite(feature_rows[s][feat])]
            centroid[feat] = {
                "label": LABEL_MAP.get(feat, feat),
                "value": round(float(np.mean(vals)), 3) if vals else None,
            }
        # Describe the cluster by notable features
        rsi  = centroid["rsi14"]["value"]
        kama = centroid["kama_dist_20"]["value"]
        mom  = centroid["macd_hist"]["value"]
        if rsi is not None and kama is not None:
            if rsi < 45 and kama < 0:       desc = "Oversold / Below Trend"
            elif rsi > 60 and kama > 0:     desc = "Overbought / Momentum"
            elif mom is not None and mom > 0: desc = "Improving / Bullish Bias"
            else:                            desc = "Mixed / Neutral"
        else:
            desc = "Unknown"

        result.append({
            "cluster_id":    c_id,
            "label":         CLUSTER_LABELS[c_id % len(CLUSTER_LABELS)],
            "description":   desc,
            "members":       members,
            "member_count":  len(members),
            "centroid":      centroid,
        })

    return {
        "n_clusters": k,
        "total_symbols": len(syms),
        "clusters": result,
    }
