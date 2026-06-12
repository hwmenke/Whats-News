"""
factor_attribution.py — Rolling factor-model attribution for strategy returns.

FACTORS (Fama-French inspired, using ETF proxies):
  market    = SPY daily return
  size      = IWM - SPY  (small-minus-large)
  value     = IWD - IWF  (value-minus-growth)
  duration  = TLT daily return
  commodity = GLD daily return

Usage:
  compute_factor_attribution(net_ret, dates, freq) -> dict
"""

import math
import numpy as np
import pandas as pd
import database as db

FACTOR_SYMBOLS = ["SPY", "IWM", "IWD", "IWF", "TLT", "GLD"]
FACTOR_NAMES   = ["market", "size", "value", "duration", "commodity"]
ROLLING_WINDOW = 63   # ~1 quarter of daily bars


def _get_factor_returns(freq: str, lookback: int) -> tuple[pd.DataFrame, list]:
    """
    Fetch close prices for all factor ETFs, compute returns and factor columns.
    Returns (factor_df, missing_symbols).
    """
    frames  = {}
    missing = []
    for sym in FACTOR_SYMBOLS:
        df = db.get_ohlcv_df(sym, freq, limit=lookback + 5)
        if df.empty:
            missing.append(sym)
        else:
            frames[sym] = df["close"]

    if not frames:
        return pd.DataFrame(), missing

    prices = pd.DataFrame(frames)
    rets   = prices.pct_change()

    factors = pd.DataFrame(index=rets.index)
    if "SPY" in rets.columns:
        factors["market"] = rets["SPY"]
    else:
        factors["market"] = np.nan

    if "IWM" in rets.columns and "SPY" in rets.columns:
        factors["size"] = rets["IWM"] - rets["SPY"]
    else:
        factors["size"] = np.nan

    if "IWD" in rets.columns and "IWF" in rets.columns:
        factors["value"] = rets["IWD"] - rets["IWF"]
    else:
        factors["value"] = np.nan

    if "TLT" in rets.columns:
        factors["duration"] = rets["TLT"]
    else:
        factors["duration"] = np.nan

    if "GLD" in rets.columns:
        factors["commodity"] = rets["GLD"]
    else:
        factors["commodity"] = np.nan

    return factors, missing


def _ols(y: np.ndarray, X: np.ndarray) -> tuple:
    """
    Simple OLS: returns (betas, alpha, r2, se_betas, se_alpha).
    X should NOT include a constant column — intercept added internally.
    """
    n, k = X.shape
    Xc = np.column_stack([np.ones(n), X])   # add intercept
    try:
        betas, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
    except np.linalg.LinAlgError:
        betas = np.zeros(k + 1)

    alpha   = betas[0]
    betas_f = betas[1:]
    y_hat   = Xc @ betas
    resid   = y - y_hat
    ss_res  = float(resid @ resid)
    ss_tot  = float(((y - y.mean()) ** 2).sum())
    r2      = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

    # Standard errors via (X'X)^{-1} * s^2
    s2  = ss_res / max(n - k - 1, 1)
    try:
        cov = s2 * np.linalg.inv(Xc.T @ Xc)
        ses = np.sqrt(np.diag(cov).clip(0))
    except np.linalg.LinAlgError:
        ses = np.full(k + 1, np.nan)

    return betas_f, alpha, r2, ses[1:], ses[0]


def compute_factor_attribution(
    net_ret: list,
    dates:   list,
    freq:    str = "daily",
    lookback: int = 504,
) -> dict:
    """
    Given a strategy's bar-by-bar net returns and matching dates, run OLS attribution.

    Returns {
        dates, factor_names, betas (full-period), tstats, r2,
        intercept_tstat, intercept_pval,
        rolling_betas {factor: [float,...]},
        rolling_r2 [float,...],
        cumulative_alpha [float,...],
        missing_factors [str,...],
    }
    """
    if len(net_ret) < 30:
        return {"error": "Insufficient data for factor attribution (need ≥ 30 bars)"}

    strat = pd.Series(net_ret, index=pd.to_datetime(dates))
    factors, missing = _get_factor_returns(freq, lookback)

    if factors.empty:
        return {
            "error": "No factor data available — fetch SPY, IWM, IWD, IWF, TLT, GLD first",
            "missing_factors": missing,
        }

    # Align on common index
    common = strat.index.intersection(factors.index)
    if len(common) < 30:
        return {"error": "Insufficient overlapping dates between strategy and factor data"}

    y_all = strat.reindex(common).values.astype(float)
    F_all = factors.reindex(common).values.astype(float)

    # Drop rows where any factor or strategy is NaN
    valid = np.isfinite(y_all) & np.all(np.isfinite(F_all), axis=1)
    y_v   = y_all[valid]
    F_v   = F_all[valid]
    dates_v = [d.strftime("%Y-%m-%d") for d in common[valid]]

    if len(y_v) < 20:
        return {"error": "Too few valid aligned bars after NaN removal"}

    n  = len(y_v)
    nf = F_v.shape[1]
    ann = 252.0 if freq == "daily" else 52.0

    # Full-period OLS
    betas_full, alpha_full, r2_full, ses_full, se_alpha = _ols(y_v, F_v)
    tstats_full = betas_full / np.where(ses_full > 1e-12, ses_full, np.nan)
    t_alpha     = float(alpha_full / se_alpha) if se_alpha > 1e-12 else 0.0

    # Two-sided p-value for intercept (normal approx)
    from math import erfc, sqrt as msqrt
    p_alpha = float(erfc(abs(t_alpha) / msqrt(2)))

    # Rolling OLS (ROLLING_WINDOW bars)
    roll = min(ROLLING_WINDOW, n // 2)
    rolling_betas = np.full((n, nf), np.nan)
    rolling_r2    = np.full(n, np.nan)
    rolling_alpha = np.full(n, np.nan)

    for i in range(roll - 1, n):
        start = i - roll + 1
        y_w   = y_v[start:i + 1]
        F_w   = F_v[start:i + 1]
        mask  = np.isfinite(y_w) & np.all(np.isfinite(F_w), axis=1)
        if mask.sum() < nf + 2:
            continue
        b, a, r2, _, _ = _ols(y_w[mask], F_w[mask])
        rolling_betas[i] = b
        rolling_r2[i]    = r2
        rolling_alpha[i] = a

    # Cumulative alpha = running sum of daily alpha estimates
    cum_alpha = np.where(np.isfinite(rolling_alpha),
                         np.nancumsum(rolling_alpha), np.nan)

    def _safe_list(arr):
        return [None if not np.isfinite(v) else round(float(v), 6) for v in arr]

    return {
        "dates":             dates_v,
        "factor_names":      FACTOR_NAMES,
        "factor_betas":      {FACTOR_NAMES[i]: round(float(betas_full[i]), 6) for i in range(nf)},
        "factor_tstats":     {FACTOR_NAMES[i]: round(float(tstats_full[i]), 4) for i in range(nf)},
        "r2":                round(float(r2_full), 4),
        "intercept_alpha":   round(float(alpha_full * ann), 6),  # annualised
        "intercept_tstat":   round(t_alpha, 4),
        "intercept_pval":    round(p_alpha, 4),
        "rolling_betas":     {FACTOR_NAMES[i]: _safe_list(rolling_betas[:, i]) for i in range(nf)},
        "rolling_r2":        _safe_list(rolling_r2),
        "cumulative_alpha":  _safe_list(cum_alpha),
        "missing_factors":   missing,
    }
