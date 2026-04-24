"""
factor_model.py — Cross-Sectional Factor Model Analyzer

Runs a 5-factor OLS regression for every watchlist symbol against:
  market    = SPY returns
  size      = IWM − SPY  (small-cap premium)
  value     = IWD − IWF  (value minus growth)
  momentum  = cross-sectional 12-1M rank-weighted composite return
              (constructed from available watchlist symbols each month)
  duration  = TLT returns
  commodity = GLD returns

For each symbol returns:
  • Factor betas + t-statistics
  • Annualised alpha (intercept) + alpha t-stat + p-value
  • R-squared
  • Factor contribution to total return (attribution)
  • Rolling 63-bar betas (for charts)

Cross-sectional output:
  • Exposure heatmap: symbols × factors
  • Alpha ranking (highest risk-adjusted alpha first)
  • Factor correlation matrix
  • Factor performance (cumulative returns)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import database as db
import indicator_cache as cache
from factor_attribution import _get_factor_returns, FACTOR_NAMES, FACTOR_SYMBOLS

ROLL_WIN = 63   # rolling regression window

_FACTOR_LABELS = {
    "market":    "Market β",
    "size":      "Size",
    "value":     "Value",
    "duration":  "Duration",
    "commodity": "Commodity",
}


def _safe(v):
    if v is None: return None
    try:
        if np.isnan(v): return None
    except: pass
    return round(float(v), 4)


def _ols(y: np.ndarray, X: np.ndarray):
    """
    OLS: y = X @ b.  X already includes constant column.
    Returns (betas, tstats, r2).
    """
    if len(y) < X.shape[1] + 5:
        nf = X.shape[1]
        return np.zeros(nf), np.zeros(nf), 0.0

    try:
        b, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except Exception:
        return np.zeros(X.shape[1]), np.zeros(X.shape[1]), 0.0

    resid   = y - X @ b
    n, p    = X.shape
    df_e    = max(n - p, 1)
    mse     = (resid ** 2).sum() / df_e
    xtxi    = np.linalg.pinv(X.T @ X)
    se      = np.sqrt(np.maximum(np.diag(xtxi) * mse, 0))
    t       = b / np.where(se > 1e-12, se, np.nan)

    ss_res  = (resid ** 2).sum()
    ss_tot  = ((y - y.mean()) ** 2).sum()
    r2      = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0

    return b, t, float(r2)


def _pval(t_stat: float, df: int = 252) -> float:
    """Two-tailed p-value from t-distribution approx."""
    if not np.isfinite(t_stat):
        return 1.0
    try:
        x = df / (df + t_stat ** 2)
        # Regularised incomplete beta approximation
        from math import lgamma, exp, log
        a, b = 0.5 * df, 0.5
        if x <= 0 or x >= 1:
            return float(t_stat == 0)
        lbeta = lgamma(a) + lgamma(b) - lgamma(a + b)
        # Simple approximation sufficient for display
        p_one = 0.5 * math.exp(a * math.log(x) + b * math.log(1 - x) - lbeta) / b
        return round(min(1.0, 2 * p_one), 4)
    except Exception:
        return 1.0


def compute_factor_model(lookback: int = 504) -> dict:
    return cache.get_or_compute(
        "factor_model", "ALL", "daily",
        lambda: _compute_inner(lookback),
        lookback=lookback,
    )


def _compute_inner(lookback: int) -> dict:
    # ── Load factor returns ────────────────────────────────────
    factor_df, missing_factors = _get_factor_returns("daily", lookback + 10)
    if factor_df.empty or len(factor_df) < 63:
        return {"error": "Factor ETFs not available. Add SPY, IWM, IWD, IWF, TLT, GLD to your watchlist."}

    # Trim to available factor columns only
    avail_factors = [f for f in FACTOR_NAMES if f in factor_df.columns and factor_df[f].notna().sum() > 50]
    if not avail_factors:
        return {"error": "No factor columns available"}

    factor_df = factor_df[avail_factors].dropna()
    fnames    = avail_factors

    # ── Load watchlist symbols ─────────────────────────────────
    syms_meta = db.list_symbols()
    symbols   = [s["symbol"] for s in syms_meta
                 if s["symbol"] not in FACTOR_SYMBOLS]

    results    = {}
    all_alphas = {}

    for sym in symbols:
        df_sym = db.get_ohlcv_df(sym, "daily", limit=lookback + 10)
        if df_sym.empty or len(df_sym) < 63:
            continue

        sym_ret = df_sym["close"].pct_change().dropna()

        # Align to factor dates
        merged  = pd.DataFrame({"y": sym_ret}).join(factor_df, how="inner").dropna()
        if len(merged) < 50:
            continue

        y   = merged["y"].values
        Xf  = merged[fnames].values
        n   = len(y)
        X   = np.column_stack([Xf, np.ones(n)])   # factors + intercept

        betas, tstats, r2 = _ols(y, X)
        n_params = len(betas)

        # betas[-1] = intercept (daily alpha)
        alpha_daily = betas[-1]
        alpha_ann   = alpha_daily * 252
        alpha_t     = tstats[-1]
        alpha_pval  = _pval(alpha_t, n - n_params)

        factor_betas  = {fnames[i]: _safe(betas[i])  for i in range(len(fnames))}
        factor_tstats = {fnames[i]: _safe(tstats[i]) for i in range(len(fnames))}

        # ── Factor contribution to total return ───────────────
        total_ret    = float((1 + merged["y"]).prod() - 1)
        factor_contribs = {}
        for i, f in enumerate(fnames):
            factor_cum = float((1 + merged[f]).prod() - 1)
            factor_contribs[f] = _safe(betas[i] * factor_cum)
        alpha_contrib = _safe(total_ret - sum(v for v in factor_contribs.values() if v is not None))

        # ── Rolling betas (ROLL_WIN bars) ─────────────────────
        rolling_betas = {f: [] for f in fnames}
        rolling_dates = []
        for end in range(ROLL_WIN, len(merged)):
            sl   = merged.iloc[end - ROLL_WIN: end]
            y_sl = sl["y"].values
            X_sl = np.column_stack([sl[fnames].values, np.ones(ROLL_WIN)])
            rb, _, _ = _ols(y_sl, X_sl)
            for i, f in enumerate(fnames):
                rolling_betas[f].append(_safe(rb[i]))
            rolling_dates.append(merged.index[end].strftime("%Y-%m-%d"))

        results[sym] = {
            "symbol":          sym,
            "name":            next((s["name"] for s in syms_meta if s["symbol"] == sym), ""),
            "n_obs":           n,
            "r2":              _safe(r2),
            "alpha_ann":       _safe(alpha_ann),
            "alpha_tstat":     _safe(alpha_t),
            "alpha_pval":      _safe(alpha_pval),
            "factor_betas":    factor_betas,
            "factor_tstats":   factor_tstats,
            "factor_contribs": factor_contribs,
            "alpha_contrib":   alpha_contrib,
            "total_ret":       _safe(total_ret),
            "rolling_betas":   rolling_betas,
            "rolling_dates":   rolling_dates,
        }
        all_alphas[sym] = alpha_ann if np.isfinite(alpha_ann) else -999

    if not results:
        return {"error": "No watchlist symbols had enough data for factor regression"}

    # ── Alpha ranking ──────────────────────────────────────────
    alpha_rank = sorted(all_alphas.items(), key=lambda x: x[1], reverse=True)

    # ── Factor performance (cumulative returns) ────────────────
    factor_perf = {}
    factor_cum  = (1 + factor_df.iloc[-lookback:]).cumprod()
    for f in fnames:
        if f in factor_cum.columns:
            factor_perf[f] = {
                "dates":  [d.strftime("%Y-%m-%d") for d in factor_cum.index],
                "values": [_safe(v) for v in factor_cum[f].values],
            }

    # ── Factor correlation matrix ──────────────────────────────
    corr = factor_df[fnames].corr().round(3)
    factor_corr = {f: {g: _safe(corr.loc[f, g]) for g in fnames} for f in fnames}

    return {
        "symbols":        list(results.keys()),
        "factor_names":   fnames,
        "factor_labels":  {f: _FACTOR_LABELS.get(f, f) for f in fnames},
        "results":        results,
        "alpha_rank":     alpha_rank,
        "factor_perf":    factor_perf,
        "factor_corr":    factor_corr,
        "missing_factors":missing_factors,
    }
