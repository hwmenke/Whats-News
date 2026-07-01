"""
seasonality.py — Historical Return Seasonality Analysis

Decomposes a symbol's price history into recurring calendar patterns:
  • Monthly  — average return for each calendar month (Jan … Dec)
  • Day-of-week — average return for Mon … Fri
  • Quarterly  — average return for Q1 … Q4
  • Year × Month heatmap — full matrix of every year/month combination

All returns are simple close-to-close returns for the relevant period
(e.g. monthly = first trading day open to last trading day close).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import database as db
import indicator_cache as cache

MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
DOW_NAMES   = ["Mon","Tue","Wed","Thu","Fri"]


def _safe(v):
    if v is None: return None
    try:
        if np.isnan(v): return None
    except: pass
    return round(float(v), 4)


def compute_seasonality(symbol: str) -> dict:
    return cache.get_or_compute(
        "seasonality", symbol, "daily",
        lambda: _compute_inner(symbol),
    )


def _compute_inner(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty:
        return {"error": f"No data for {symbol}"}
    if len(df) < 252:
        return {"error": "Need at least 1 year of daily data"}

    close = df["close"]

    # ── Daily returns ──────────────────────────────────────────
    daily_ret   = close.pct_change()
    daily_ret.index = pd.to_datetime(daily_ret.index)

    # ── Monthly returns (resample to month-end) ────────────────
    monthly_close  = close.resample("ME").last()
    monthly_ret    = monthly_close.pct_change().dropna()
    monthly_ret.index = pd.to_datetime(monthly_ret.index)

    # ── Day-of-week ────────────────────────────────────────────
    dow_stats = []
    for dow in range(5):
        mask = daily_ret.index.dayofweek == dow
        vals = daily_ret[mask].dropna()
        dow_stats.append({
            "name":     DOW_NAMES[dow],
            "mean":     _safe(vals.mean()),
            "median":   _safe(vals.median()),
            "hit_rate": _safe((vals > 0).mean()),
            "n":        int(len(vals)),
            "std":      _safe(vals.std()),
        })

    # ── Monthly calendar stats ─────────────────────────────────
    monthly_stats = []
    for m in range(1, 13):
        mask = monthly_ret.index.month == m
        vals = monthly_ret[mask].dropna()
        monthly_stats.append({
            "month":    m,
            "name":     MONTH_NAMES[m - 1],
            "mean":     _safe(vals.mean()),
            "median":   _safe(vals.median()),
            "hit_rate": _safe((vals > 0).mean()),
            "best":     _safe(vals.max()),
            "worst":    _safe(vals.min()),
            "n":        int(len(vals)),
            "std":      _safe(vals.std()),
        })

    # ── Quarterly stats ────────────────────────────────────────
    quarterly_close = close.resample("QE").last()
    quarterly_ret   = quarterly_close.pct_change().dropna()
    quarterly_ret.index = pd.to_datetime(quarterly_ret.index)

    quarterly_stats = []
    for q in range(1, 5):
        mask = quarterly_ret.index.quarter == q
        vals = quarterly_ret[mask].dropna()
        quarterly_stats.append({
            "quarter":  q,
            "name":     f"Q{q}",
            "mean":     _safe(vals.mean()),
            "hit_rate": _safe((vals > 0).mean()),
            "best":     _safe(vals.max()),
            "worst":    _safe(vals.min()),
            "n":        int(len(vals)),
        })

    # ── Year × Month heatmap ───────────────────────────────────
    years = sorted(monthly_ret.index.year.unique())
    # One groupby pass instead of years×12 individual boolean masks
    monthly_grouped = monthly_ret.groupby(
        [monthly_ret.index.year, monthly_ret.index.month]
    ).first()

    heatmap = []
    for yr in years:
        row = {"year": int(yr), "months": {
            str(m): _safe(monthly_grouped.get((yr, m))) for m in range(1, 13)
        }}
        yr_vals = monthly_ret[monthly_ret.index.year == yr].dropna()
        row["annual"] = _safe((1 + yr_vals).prod() - 1) if len(yr_vals) else None
        heatmap.append(row)

    # ── Best / worst calendar facts ────────────────────────────
    best_month  = max(monthly_stats, key=lambda x: x["mean"] or -999)
    worst_month = min(monthly_stats, key=lambda x: x["mean"] or 999)
    best_dow    = max(dow_stats,     key=lambda x: x["mean"] or -999)
    worst_dow   = min(dow_stats,     key=lambda x: x["mean"] or 999)

    return {
        "symbol":          symbol,
        "n_years":         len(years),
        "n_monthly_obs":   int(len(monthly_ret)),
        "monthly_stats":   monthly_stats,
        "dow_stats":       dow_stats,
        "quarterly_stats": quarterly_stats,
        "heatmap":         heatmap,
        "highlights": {
            "best_month":  best_month["name"],
            "worst_month": worst_month["name"],
            "best_dow":    best_dow["name"],
            "worst_dow":   worst_dow["name"],
            "best_month_mean":  best_month["mean"],
            "worst_month_mean": worst_month["mean"],
        },
    }
