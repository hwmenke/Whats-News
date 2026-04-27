"""
pycaret_model.py  –  AutoML directional-prediction module using PyCaret.

Trains classification models on the same 17-feature set used by knn_forecast.py
to predict whether the stock will close UP or DOWN over the next `horizon`
trading days.  The best model from compare_models() classifies the current
(most-recent) bar.

Feature groups:
    trend        – KAMA-10/20/50 distance (ATR-normalised), KAMA-10 slope
    momentum     – RSI-14, RSI-7, ROC-5, ROC-20, MACD histogram
    volatility   – ATR percentile rank, Bollinger %B, HV-20 rank
    price_action – candle body ratio, upper-shadow ratio, close streak
    volume       – log relative volume, OBV slope
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import database as db
from ta_core import _kama, _rsi, _bollinger, _macd

try:
    from pycaret.classification import ClassificationExperiment
    PYCARET_AVAILABLE = True
except ImportError:
    PYCARET_AVAILABLE = False


# ── Feature constants (mirrors knn_forecast.py catalogue) ─────────────────────

FEATURE_COLS = [
    # trend
    "kama10_dist", "kama20_dist", "kama50_dist", "kama_slope",
    # momentum
    "rsi14", "rsi7", "roc5", "roc20", "macd_hist",
    # volatility
    "atr_rank", "bb_pct", "hv20_rank",
    # price action
    "body_ratio", "upper_shadow", "streak",
    # volume
    "vol_ratio", "obv_slope",
]

FAST_CLASSIFIERS = ["lr", "dt", "rf", "et", "nb", "ridge", "lda"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _atr14(df: pd.DataFrame) -> pd.Series:
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    n     = len(close)
    prev  = np.empty(n)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = np.full(n, np.nan)
    if n < 14:
        return pd.Series(atr, index=df.index)
    atr[13] = tr[:14].mean()
    alpha = 1.0 / 14.0
    for i in range(14, n):
        atr[i] = atr[i - 1] + alpha * (tr[i] - atr[i - 1])
    return pd.Series(atr, index=df.index)


def _pct_rank(series: pd.Series, window: int = 252) -> pd.Series:
    def _rank(x):
        return (x[:-1] < x[-1]).sum() / max(len(x) - 1, 1)
    return series.rolling(window, min_periods=20).apply(_rank, raw=True)


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if np.isnan(f) else round(f, 6)
    except Exception:
        return None


# ── Feature engineering ────────────────────────────────────────────────────────

def _build_features(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    Build the full 17-feature matrix + binary UP/DOWN label.
    Last `horizon` rows have no label (no future data yet) and are dropped.
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    eps   = 1e-10
    atr   = _atr14(df)
    atr_s = atr.clip(lower=eps)

    # ── Trend ──────────────────────────────────────────────────────────────────
    k10 = _kama(close, window=10)
    k20 = _kama(close, window=20)
    k50 = _kama(close, window=50)
    kama10_dist = (close - k10) / atr_s
    kama20_dist = (close - k20) / atr_s
    kama50_dist = (close - k50) / atr_s
    kama_slope  = k10.diff(5) / atr_s

    # ── Momentum ───────────────────────────────────────────────────────────────
    rsi14 = _rsi(close, window=14)
    rsi7  = _rsi(close, window=7)
    roc5  = np.log(close / close.shift(5).replace(0, np.nan))
    roc20 = np.log(close / close.shift(20).replace(0, np.nan))
    _, _, macd_h = _macd(close)
    macd_hist = macd_h / atr_s

    # ── Volatility ─────────────────────────────────────────────────────────────
    atr_pct  = atr / close.clip(lower=eps)
    atr_rank = _pct_rank(atr_pct, 252)

    upper, _, lower_bb = _bollinger(close, window=20, num_std=2.0)
    band_range = (upper - lower_bb).clip(lower=eps)
    bb_pct     = (close - lower_bb) / band_range

    log_ret  = np.log(close / close.shift(1).replace(0, np.nan))
    hv20     = log_ret.rolling(20).std() * np.sqrt(252)
    hv20_rank = _pct_rank(hv20, 252)

    # ── Price action ───────────────────────────────────────────────────────────
    candle_range = (high - low).clip(lower=eps)
    body         = (close - open_).abs()
    body_ratio   = body / candle_range

    hi_shadow    = high - pd.concat([open_, close], axis=1).max(axis=1)
    upper_shadow = hi_shadow.clip(lower=0) / candle_range

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

    # ── Volume ─────────────────────────────────────────────────────────────────
    vol_ema20 = volume.ewm(span=20, adjust=False).mean().clip(lower=1)
    vol_ratio = np.log((volume / vol_ema20).clip(lower=eps))
    obv       = (np.sign(close.diff()) * volume).cumsum()
    obv_std   = obv.rolling(20).std().clip(lower=eps)
    obv_slope = obv.diff(5) / obv_std

    # ── Assemble ───────────────────────────────────────────────────────────────
    feat = pd.DataFrame({
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

    # Label: direction of `horizon`-day forward return
    fwd_ret = close.pct_change(horizon).shift(-horizon)
    feat["target"] = np.where(fwd_ret > 0.0, "UP", "DOWN")
    feat.loc[feat.index[-horizon:], "target"] = np.nan

    return feat.dropna(subset=FEATURE_COLS + ["target"]).copy()


# ── Public API ─────────────────────────────────────────────────────────────────

def train_and_predict(symbol: str, horizon: int = 5, n_models: int = 5) -> dict:
    """
    Train PyCaret classification models on 17 technical features and return a
    directional prediction (UP / DOWN) for the most-recent bar.

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

    # ── Feature importance (tree models) or coefficients (linear) ─────────────
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

    current_raw = {col: _safe_float(v) for col, v in current_features.iloc[0].items()}

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
