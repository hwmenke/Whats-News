"""
regression.py — Macro-factor regression for the Financial Dashboard

Regresses a target symbol's forward returns on a feature matrix built from
macro ETFs (returns, RSI, volatility, cross-asset spreads) using OLS.
All computation is pure numpy — no statsmodels / sklearn dependency.

Feature set per available factor:
  ret_5d   — 5-bar log return
  ret_20d  — 20-bar log return

Additional enrichment:
  SPY_vol20  — 20-day rolling annualised volatility (market regime proxy)
  SPY_rsi14  — RSI-14 of SPY (overbought/oversold context)
  TLT_rsi14  — RSI-14 of TLT (rate sentiment)

Spread features (logret A - logret B over N bars):
  SPY-TLT  5d / 20d  — risk-on spread
  XLK-XLP  5d / 20d  — growth vs defensives
  XLE-XLU  5d        — energy vs utilities
  GLD-SPY  20d       — gold vs equities (safe-haven)
  XLY-XLP  5d        — cyclical vs defensive consumer
"""

import numpy as np
import pandas as pd
import database as db


# ── Macro factor catalogue ─────────────────────────────────────────────────

MACRO_FACTORS = [
    {"symbol": "SPY",  "label": "SPY",  "group": "equity",    "desc": "S&P 500"},
    {"symbol": "QQQ",  "label": "QQQ",  "group": "equity",    "desc": "Nasdaq-100"},
    {"symbol": "IWM",  "label": "IWM",  "group": "equity",    "desc": "Russell 2000"},
    {"symbol": "TLT",  "label": "TLT",  "group": "rates",     "desc": "20+ Yr Treasury"},
    {"symbol": "IEF",  "label": "IEF",  "group": "rates",     "desc": "7-10 Yr Treasury"},
    {"symbol": "HYG",  "label": "HYG",  "group": "rates",     "desc": "High Yield Credit"},
    {"symbol": "GLD",  "label": "GLD",  "group": "commodity", "desc": "Gold"},
    {"symbol": "USO",  "label": "USO",  "group": "commodity", "desc": "Oil"},
    {"symbol": "DBC",  "label": "DBC",  "group": "commodity", "desc": "Commodities Basket"},
    {"symbol": "^VIX", "label": "VIX",  "group": "vol",       "desc": "CBOE Volatility Index"},
    {"symbol": "XLK",  "label": "XLK",  "group": "sector",    "desc": "Technology"},
    {"symbol": "XLF",  "label": "XLF",  "group": "sector",    "desc": "Financials"},
    {"symbol": "XLV",  "label": "XLV",  "group": "sector",    "desc": "Healthcare"},
    {"symbol": "XLE",  "label": "XLE",  "group": "sector",    "desc": "Energy"},
    {"symbol": "XLI",  "label": "XLI",  "group": "sector",    "desc": "Industrials"},
    {"symbol": "XLP",  "label": "XLP",  "group": "sector",    "desc": "Consumer Staples"},
    {"symbol": "XLY",  "label": "XLY",  "group": "sector",    "desc": "Consumer Discr."},
    {"symbol": "XLRE", "label": "XLRE", "group": "sector",    "desc": "Real Estate"},
    {"symbol": "XLB",  "label": "XLB",  "group": "sector",    "desc": "Materials"},
    {"symbol": "XLU",  "label": "XLU",  "group": "sector",    "desc": "Utilities"},
    {"symbol": "XLC",  "label": "XLC",  "group": "sector",    "desc": "Comm. Services"},
    {"symbol": "EEM",  "label": "EEM",  "group": "intl",      "desc": "Emerging Markets"},
    {"symbol": "EFA",  "label": "EFA",  "group": "intl",      "desc": "Developed Markets"},
    {"symbol": "FXI",  "label": "FXI",  "group": "intl",      "desc": "China Large-Cap"},
]

# Spread = log_ret(A, n) - log_ret(B, n).  Both must be in factor_closes.
SPREAD_FEATURES = [
    ("SPY", "TLT",  5,  "SPY-TLT_5d",   "Risk-on spread 5d"),
    ("SPY", "TLT",  20, "SPY-TLT_20d",  "Risk-on spread 20d"),
    ("XLK", "XLP",  5,  "XLK-XLP_5d",   "Growth vs Defensives 5d"),
    ("XLK", "XLP",  20, "XLK-XLP_20d",  "Growth vs Defensives 20d"),
    ("XLE", "XLU",  5,  "XLE-XLU_5d",   "Energy vs Utilities 5d"),
    ("GLD", "SPY",  20, "GLD-SPY_20d",  "Gold vs Equities 20d"),
    ("XLY", "XLP",  5,  "XLY-XLP_5d",   "Cyclical vs Defensive 5d"),
    ("HYG", "TLT",  5,  "HYG-TLT_5d",   "Credit vs Duration 5d"),
    ("QQQ", "IWM",  5,  "QQQ-IWM_5d",   "Large-Growth vs Small-Cap 5d"),
]


# ── Factor status (batch DB query) ────────────────────────────────────────

def factor_status() -> list:
    """Return availability status for all macro factors (single DB query)."""
    symbols_needed = [f["symbol"] for f in MACRO_FACTORS]
    conn = db.get_connection()
    placeholders = ",".join("?" * len(symbols_needed))
    rows = conn.execute(
        f"SELECT DISTINCT symbol FROM ohlcv "
        f"WHERE symbol IN ({placeholders}) AND freq='daily'",
        symbols_needed,
    ).fetchall()
    conn.close()
    available = {r["symbol"] for r in rows}
    return [{**f, "available": f["symbol"] in available} for f in MACRO_FACTORS]


# ── Indicator helpers ─────────────────────────────────────────────────────

def _log_ret(series: pd.Series, n: int = 1) -> pd.Series:
    return np.log(series / series.shift(n))


def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta  = series.diff()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_l  = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)) / 100.0   # normalised to 0-1


def _rolling_vol(series: pd.Series, n: int = 20) -> pd.Series:
    """Annualised rolling std of daily log returns."""
    return _log_ret(series, 1).rolling(n).std() * np.sqrt(252)


# ── OLS ───────────────────────────────────────────────────────────────────

def _norm_cdf(x: np.ndarray) -> np.ndarray:
    """
    Standard-normal CDF for x >= 0 using Abramowitz & Stegun approximation.
    Accurate to ~7 decimal places.
    """
    t    = 1.0 / (1.0 + 0.2316419 * np.abs(x))
    poly = ((((1.330274429 * t - 1.821255978) * t + 1.781477937) * t
               - 0.356563782) * t + 0.319381530) * t
    cdf  = 1.0 - (1.0 / np.sqrt(2.0 * np.pi)) * np.exp(-0.5 * x ** 2) * poly
    # Mirror for negative x
    return np.where(x >= 0, cdf, 1.0 - cdf)


def _ols(X: np.ndarray, y: np.ndarray):
    """
    Ordinary Least Squares: X is (n, k) with intercept prepended, y is (n,).
    Returns dict with beta, se, t_stat, p_value, r2, adj_r2, n, k.
    p-values use a two-tailed normal approximation (accurate for n > ~60).
    Returns None on singular/degenerate input.
    """
    n, k = X.shape
    try:
        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return None

    y_hat  = X @ beta
    resid  = y - y_hat
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())

    r2     = 1.0 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - k) if n > k else 0.0

    sigma2 = ss_res / max(n - k, 1)
    try:
        cov = sigma2 * np.linalg.inv(X.T @ X)
        se  = np.sqrt(np.maximum(np.diag(cov), 0.0))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)

    t_stat  = np.where(se > 1e-15, beta / se, 0.0)
    p_value = 2.0 * (1.0 - _norm_cdf(np.abs(t_stat)))

    return {"beta": beta, "se": se, "t_stat": t_stat,
            "p_value": p_value, "r2": r2, "adj_r2": adj_r2, "n": n, "k": k}


# ── Main entry point ──────────────────────────────────────────────────────

def compute_regression(symbol: str, freq: str = "daily",
                       horizon: int = 5,
                       lookback: int = 504) -> dict:
    """
    Regress forward returns of `symbol` on macro factor features.

    Parameters
    ----------
    symbol   : target symbol (must be in DB)
    freq     : 'daily' | 'weekly'
    horizon  : forward return window in bars (1 / 5 / 20)
    lookback : number of bars to use for the regression window (≤ 2000)
    """
    # ── Load target ───────────────────────────────────────────────
    target_df = db.get_ohlcv_df(symbol, freq, limit=lookback + horizon + 50)
    if target_df.empty:
        return {"error": f"No data for {symbol}. Fetch it first."}

    target_fwd = _log_ret(target_df["close"], horizon).shift(-horizon)
    target_fwd.name = symbol

    # ── Load available factor closes ──────────────────────────────
    label_map    = {f["symbol"]: f["label"] for f in MACRO_FACTORS}
    factor_closes = {}
    for f in MACRO_FACTORS:
        df = db.get_ohlcv_df(f["symbol"], freq, limit=lookback + 80)
        if not df.empty:
            factor_closes[f["symbol"]] = df["close"]

    if len(factor_closes) < 2:
        return {
            "error": (
                "Need at least 2 macro factors in the database. "
                "Go to the Regression tab and click 'Fetch Missing Factors'."
            )
        }

    # ── Feature engineering ───────────────────────────────────────
    features = {}

    for sym, close in factor_closes.items():
        lbl = label_map.get(sym, sym)
        features[f"{lbl}_ret5d"]  = _log_ret(close, 5)
        features[f"{lbl}_ret20d"] = _log_ret(close, 20)

    # Extra enrichment for key macro factors
    if "SPY" in factor_closes:
        features["SPY_vol20"] = _rolling_vol(factor_closes["SPY"], 20)
        features["SPY_rsi14"] = _rsi(factor_closes["SPY"], 14)
    if "TLT" in factor_closes:
        features["TLT_rsi14"] = _rsi(factor_closes["TLT"], 14)
    if "^VIX" in factor_closes:
        # Level change of VIX (not log-return — VIX levels are already a vol measure)
        features["VIX_chg5d"] = factor_closes["^VIX"].diff(5)

    # Spread features
    for sym_a, sym_b, n, name, _ in SPREAD_FEATURES:
        if sym_a in factor_closes and sym_b in factor_closes:
            features[name] = (_log_ret(factor_closes[sym_a], n)
                              - _log_ret(factor_closes[sym_b], n))

    # ── Align features with target index ─────────────────────────
    feat_df = pd.DataFrame(features).reindex(target_fwd.index)

    # Restrict to lookback window
    feat_df    = feat_df.iloc[-lookback:]
    target_fwd = target_fwd.iloc[-lookback:]

    # Drop rows where target is NaN (future bars, leading NaN)
    valid_mask = target_fwd.notna()
    feat_df    = feat_df[valid_mask]
    target_fwd = target_fwd[valid_mask]

    # Drop features with > 20% missing values
    ok_cols = [c for c in feat_df.columns
               if feat_df[c].isna().mean() < 0.20]
    feat_df = feat_df[ok_cols].copy()

    # Forward-fill then drop remaining NaN rows
    feat_df.ffill(inplace=True)
    feat_df.dropna(inplace=True)
    target_fwd = target_fwd.reindex(feat_df.index).dropna()
    feat_df    = feat_df.reindex(target_fwd.index)

    if len(feat_df) < 60:
        return {"error": f"Insufficient aligned data ({len(feat_df)} rows; need ≥ 60)."}
    if len(feat_df.columns) == 0:
        return {"error": "No usable features after filtering."}

    # ── Standardise features (mean-centre, unit-variance) ─────────
    X_raw = feat_df.values.astype(float)
    y_raw = target_fwd.values.astype(float)

    means = X_raw.mean(axis=0)
    stds  = X_raw.std(axis=0)
    stds  = np.where(stds < 1e-12, 1.0, stds)
    X_std = (X_raw - means) / stds

    # Prepend intercept column
    X = np.column_stack([np.ones(len(X_std)), X_std])
    y = y_raw

    result = _ols(X, y)
    if result is None:
        return {"error": "OLS failed (singular feature matrix)."}

    # ── Serialise output ──────────────────────────────────────────
    def _sf(v):
        try:
            f = float(v)
            return None if not np.isfinite(f) else round(f, 6)
        except (TypeError, ValueError):
            return None

    feature_names = ["intercept"] + list(feat_df.columns)
    coefs = [
        {
            "name":    name,
            "coef":    _sf(result["beta"][i]),
            "se":      _sf(result["se"][i]),
            "t_stat":  _sf(result["t_stat"][i]),
            "p_value": _sf(result["p_value"][i]),
        }
        for i, name in enumerate(feature_names)
    ]

    return {
        "symbol":             symbol,
        "freq":               freq,
        "horizon":            horizon,
        "lookback":           lookback,
        "n_obs":              int(result["n"]),
        "n_features":         int(result["k"] - 1),
        "r2":                 _sf(result["r2"]),
        "adj_r2":             _sf(result["adj_r2"]),
        "coefs":              coefs,
        "available_factors":  list(factor_closes.keys()),
        "n_factors_used":     len(factor_closes),
    }
