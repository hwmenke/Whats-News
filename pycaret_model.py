"""
pycaret_model.py  –  AutoML directional-prediction module using PyCaret.

Trains classification models on historical technical-indicator features to
predict whether the stock will close UP or DOWN over the next `horizon`
trading days.  The best model from compare_models() is used to classify the
current (most-recent) bar.

Feature set (mirrors knn_model.py, no `ta` dependency):
    rsi14, vol20_ann, macd_hist, cci_norm, vol_ratio,
    kama_dist_10, kama_dist_20, kama_dist_50
"""

import numpy as np
import pandas as pd
import database as db

try:
    from pycaret.classification import ClassificationExperiment
    PYCARET_AVAILABLE = True
except ImportError:
    PYCARET_AVAILABLE = False


# ── Technical indicator helpers ────────────────────────────────────────────────

def _kama(close: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    prices = close.to_numpy(dtype=float, copy=True)
    kama_vals = np.full(len(prices), np.nan)
    if len(prices) < window:
        return pd.Series(kama_vals, index=close.index)
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    kama_vals[window - 1] = prices[window - 1]
    for i in range(window, len(prices)):
        direction = abs(prices[i] - prices[i - window])
        volatility = np.sum(np.abs(np.diff(prices[i - window : i + 1])))
        er = direction / volatility if volatility != 0 else 0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama_vals[i] = kama_vals[i - 1] + sc * (prices[i] - kama_vals[i - 1])
    return pd.Series(kama_vals, index=close.index)


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=window - 1, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).ewm(com=window - 1, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    return macd - macd.ewm(span=signal, adjust=False).mean()


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    sma = tp.rolling(window).mean()
    mad = tp.rolling(window).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


# ── Feature engineering ────────────────────────────────────────────────────────

FEATURE_COLS = [
    "rsi14", "vol20_ann", "macd_hist", "cci_norm",
    "vol_ratio", "kama_dist_10", "kama_dist_20", "kama_dist_50",
]

FAST_CLASSIFIERS = ["lr", "dt", "rf", "et", "nb", "ridge", "lda"]


def _build_features(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Build feature + binary target dataframe; drop all rows with NaN."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    feat = pd.DataFrame(index=df.index)
    feat["rsi14"]       = _rsi(close, 14)
    feat["vol20_ann"]   = close.pct_change().rolling(20).std() * np.sqrt(252)
    feat["macd_hist"]   = _macd_hist(close)
    feat["cci_norm"]    = _cci(high, low, close, 20) / 200.0
    vol_ma20            = vol.rolling(20).mean()
    feat["vol_ratio"]   = vol / vol_ma20.replace(0, np.nan)
    for period in [10, 20, 50]:
        kama_s = _kama(close, window=period)
        feat[f"kama_dist_{period}"] = (close / kama_s.replace(0, np.nan)) - 1.0

    # Label: direction of `horizon`-day forward return (last `horizon` rows are unknown)
    fwd_ret = close.pct_change(horizon).shift(-horizon)
    feat["target"] = np.where(fwd_ret > 0.0, "UP", "DOWN")
    feat.loc[feat.index[-horizon:], "target"] = np.nan

    return feat.dropna(subset=FEATURE_COLS + ["target"]).copy()


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if np.isnan(f) else round(f, 6)
    except Exception:
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def train_and_predict(symbol: str, horizon: int = 5, n_models: int = 5) -> dict:
    """
    Train PyCaret classification models on technical-indicator features and
    return a directional prediction (UP / DOWN) for the most-recent bar.

    Args:
        symbol:   Ticker (e.g. 'AAPL').
        horizon:  Forward window in trading days (1, 5, 10, or 20).
        n_models: Number of classifiers to compare (1–7).

    Returns a dict with:
        symbol, horizon_days, as_of, prediction, confidence,
        leaderboard, feature_importance, current_features, training_samples.
    """
    if not PYCARET_AVAILABLE:
        return {"error": "PyCaret is not installed – run: pip install pycaret"}

    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty or len(df) < 100:
        return {"error": f"Not enough data for {symbol} (need ≥ 100 bars)"}

    feat_df = _build_features(df, horizon=horizon)
    if len(feat_df) < 60:
        return {"error": f"Only {len(feat_df)} valid rows after cleaning (need ≥ 60)"}

    # Most-recent bar → unseen prediction point (excluded from training)
    current_features = feat_df[FEATURE_COLS].iloc[[-1]].copy()
    train_df = feat_df.iloc[:-1][FEATURE_COLS + ["target"]].copy()

    # ── PyCaret experiment (OOP API for thread safety in Flask) ────────────────
    exp = ClassificationExperiment()
    exp.setup(
        data=train_df,
        target="target",
        session_id=42,
        verbose=False,
        html=False,
        fold_strategy="timeseries",
        fold=5,
        fix_imbalance=True,
        normalize=True,
        remove_multicollinearity=False,
        feature_selection=False,
    )

    include = FAST_CLASSIFIERS[: min(n_models, len(FAST_CLASSIFIERS))]
    best_model = exp.compare_models(include=include, sort="AUC", verbose=False, n_select=1)

    leaderboard_df = exp.pull()
    leaderboard = leaderboard_df.head(n_models).to_dict(orient="records")
    for row in leaderboard:
        for k, v in row.items():
            if isinstance(v, float) and np.isnan(v):
                row[k] = None

    # ── Predict current bar ────────────────────────────────────────────────────
    pred_df = exp.predict_model(best_model, data=current_features, verbose=False)

    label_col = next(
        (c for c in ("prediction_label", "Label") if c in pred_df.columns),
        pred_df.columns[-2],
    )
    score_col = next(
        (c for c in ("prediction_score", "Score") if c in pred_df.columns),
        pred_df.columns[-1],
    )
    pred_label = str(pred_df[label_col].iloc[0])
    pred_score = _safe_float(pred_df[score_col].iloc[0]) or 0.0

    # ── Feature importance (tree-based or linear coefficients) ────────────────
    feat_importance = None
    try:
        if hasattr(best_model, "feature_importances_"):
            feat_importance = {
                col: round(float(imp), 6)
                for col, imp in zip(FEATURE_COLS, best_model.feature_importances_)
            }
        elif hasattr(best_model, "coef_"):
            coefs = best_model.coef_
            if coefs.ndim > 1:
                coefs = coefs[0]
            feat_importance = {
                col: round(float(abs(c)), 6)
                for col, c in zip(FEATURE_COLS, coefs)
            }
    except Exception:
        pass

    current_raw = {
        col: _safe_float(v)
        for col, v in current_features.iloc[0].items()
    }

    return {
        "symbol":             symbol,
        "horizon_days":       horizon,
        "as_of":              feat_df.index[-1].strftime("%Y-%m-%d"),
        "prediction":         pred_label,
        "confidence":         round(float(pred_score), 4),
        "leaderboard":        leaderboard,
        "feature_importance": feat_importance,
        "current_features":   current_raw,
        "training_samples":   len(train_df),
    }
