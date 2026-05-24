"""
newsletter_engine.py — Self-contained Daily Edge engine for the Whats-News app.

Uses the existing yfinance SQLite cache to compute:
  - Feature engineering (percentile ranks, z-scores, momentum, vol, drawdown,
    RSI, Bollinger, streaks, support/resistance)
  - Story scoring (18 rules, section diversity quotas)
  - Chart.js v4 config generation for each selected story

All feature math is self-contained so this module does not depend on the
separate dailynews repository.
"""

from __future__ import annotations
import math
import datetime
from typing import Any

import numpy as np
import pandas as pd

try:
    from scipy import stats as sp_stats
    from scipy.signal import find_peaks
    _SCIPY = True
except ImportError:
    _SCIPY = False

import database as db

# ── Design tokens (538-style) ───────────────────────────────────────────────────
BLUE  = "#185FA5"; CORAL = "#D85A30"; GREEN = "#1D9E75"
RED   = "#E24B4A"; AMBER = "#EF9F27"; GRAY  = "#888780"
GRID  = "rgba(0,0,0,0.06)"; TICK = "rgba(0,0,0,0.4)"
FONT  = "system-ui,-apple-system,sans-serif"
PALETTE = [BLUE, CORAL, GREEN, AMBER, "#534AB7", GRAY]


# ───────────────────────────────────────────────────────────────────────────────
# 1. FEATURE ENGINEERING
# ───────────────────────────────────────────────────────────────────────────────

def _pct_rank(window: pd.Series, value: float) -> float:
    """Percentile rank of value within window (0–100)."""
    if _SCIPY:
        return float(sp_stats.percentileofscore(window.dropna(), value, kind="rank"))
    arr = window.dropna().values
    return float(np.searchsorted(np.sort(arr), value) / len(arr) * 100) if len(arr) else 50.0


def engineer_features(series: pd.Series, symbol: str) -> dict:
    """
    Compute all analytical features for a close-price series.
    Returns a rich context dict used by scoring and chart generators.
    """
    s = series.dropna()
    if len(s) < 5:
        return {"symbol": symbol, "insufficient_data": True}

    last  = float(s.iloc[-1])
    prev  = float(s.iloc[-2]) if len(s) > 1 else last
    chg   = last - prev
    chg_pct = (last / prev - 1) * 100 if prev != 0 else 0.0
    rets  = s.pct_change()
    moves = s.diff().dropna()

    ctx: dict[str, Any] = {
        "symbol":        symbol,
        "label":         symbol,
        "asset_class":   "equities",
        "last":          last,
        "prev":          prev,
        "daily_chg":     chg,
        "daily_chg_pct": chg_pct,
        "obs_count":     len(s),
        "date_last":     s.index[-1],
        "date_first":    s.index[0],
    }

    # Level and move percentile ranks + z-scores across 6 windows
    WINDOWS = [("1m",21),("3m",63),("6m",126),("1y",252),("2y",504),("3y",756)]
    for lbl, w in WINDOWS:
        win  = s.iloc[-w:]    if len(s)     >= w else s
        wm   = moves.iloc[-w:] if len(moves) >= w else moves
        ctx[f"pct_rank_{lbl}"]     = _pct_rank(win, last)
        ctx[f"mean_{lbl}"]         = float(win.mean())
        ctx[f"std_{lbl}"]          = float(win.std()) if len(win) > 1 else 1.0
        ctx[f"move_pct_rank_{lbl}"]= _pct_rank(wm, chg)
        ctx[f"move_std_{lbl}"]     = float(wm.std()) if len(wm) > 1 else 1.0
        std_l = ctx[f"std_{lbl}"] or 1.0
        std_m = ctx[f"move_std_{lbl}"] or 1.0
        ctx[f"zscore_{lbl}"]       = (last - ctx[f"mean_{lbl}"]) / std_l
        ctx[f"move_zscore_{lbl}"]  = (chg  - float(wm.mean())) / std_m

    # Historical levels: level N periods ago and pct change since
    for lbl, w in [("1w",5),("1m",21),("3m",63),("6m",126),("1y",252),("2y",504),("3y",756)]:
        if len(s) > w:
            ago = float(s.iloc[-w])
            ctx[f"level_{lbl}_ago"]      = ago
            ctx[f"chg_vs_{lbl}_ago"]     = last - ago
            ctx[f"pct_chg_vs_{lbl}_ago"] = (last / ago - 1) * 100 if ago != 0 else None
        else:
            ctx[f"level_{lbl}_ago"] = ctx[f"chg_vs_{lbl}_ago"] = ctx[f"pct_chg_vs_{lbl}_ago"] = None

    # Moving averages
    for w in [10, 20, 50, 100, 200]:
        if len(s) >= w:
            ma = float(s.rolling(w).mean().iloc[-1])
            ctx[f"ma{w}"]          = ma
            ctx[f"above_ma{w}"]    = last > ma
            ctx[f"pct_from_ma{w}"] = (last - ma) / ma * 100 if ma else None
        else:
            ctx[f"ma{w}"] = ctx[f"above_ma{w}"] = ctx[f"pct_from_ma{w}"] = None

    # MA crossovers
    ctx["golden_cross_today"] = ctx["death_cross_today"] = False
    if len(s) >= 202:
        ma50_t = float(s.rolling(50).mean().iloc[-1])
        ma200_t= float(s.rolling(200).mean().iloc[-1])
        ma50_p = float(s.rolling(50).mean().iloc[-2])
        ma200_p= float(s.rolling(200).mean().iloc[-2])
        ctx["golden_cross_today"] = ma50_t > ma200_t and ma50_p <= ma200_p
        ctx["death_cross_today"]  = ma50_t < ma200_t and ma50_p >= ma200_p

    # Trailing returns
    for lbl, w in [("1m",21),("3m",63),("6m",126),("1y",252)]:
        ctx[f"return_{lbl}"] = (last / float(s.iloc[-w]) - 1) * 100 if len(s) > w and s.iloc[-w] != 0 else None

    # Cross-sectional rank placeholders (filled by selector)
    ctx["momentum_rank_1m"] = ctx["momentum_rank_3m"] = ctx["momentum_rank_12m"] = None

    # Realized volatility (annualised)
    for lbl, w in [("1m",21),("3m",63),("1y",252)]:
        wr = rets.iloc[-w:] if len(rets) >= w else rets
        ctx[f"realized_vol_{lbl}"] = float(wr.std() * math.sqrt(252) * 100) if len(wr) > 1 else None
    v1m = ctx.get("realized_vol_1m")
    v1y = ctx.get("realized_vol_1y")
    ctx["vol_regime_elevated"] = bool(v1m and v1y and v1y > 0 and v1m > v1y)
    ctx["vol_ratio_1m_1y"]     = v1m / v1y if v1m and v1y and v1y > 0 else None

    # Drawdown
    for lbl, w in [("1y",252),("2y",504),("3y",756)]:
        win = s.iloc[-w:] if len(s) >= w else s
        pk  = win.cummax()
        dd  = (win - pk) / pk * 100
        ctx[f"current_drawdown_{lbl}"] = float(dd.iloc[-1])
        ctx[f"max_drawdown_{lbl}"]     = float(dd.min())

    w52 = s.iloc[-252:] if len(s) >= 252 else s
    ctx["high_52w"]         = float(w52.max())
    ctx["low_52w"]          = float(w52.min())
    ctx["pct_from_52w_high"]= (last / ctx["high_52w"] - 1) * 100
    ctx["pct_from_52w_low"] = (last / ctx["low_52w"] - 1) * 100 if ctx["low_52w"] != 0 else None
    ctx["at_52w_high"]      = abs(ctx["pct_from_52w_high"]) < 0.5
    ctx["at_52w_low"]       = abs(ctx["pct_from_52w_low"]) < 0.5 if ctx["pct_from_52w_low"] is not None else False
    ctx["pct_from_ath"]     = (last / float(s.max()) - 1) * 100

    # Streak (consecutive up/down days)
    directions = np.sign(s.diff().dropna())
    streak, last_d = 0, float(directions.iloc[-1])
    for d in reversed(directions.values):
        if d == last_d and d != 0:
            streak += 1
        else:
            break
    ctx["streak"] = int(streak * last_d)

    # RSI (14-period)
    delta = s.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss
    rsi_s = 100 - (100 / (1 + rs))
    rsi_v = rsi_s.iloc[-1]
    ctx["rsi_14"]        = float(rsi_v) if pd.notna(rsi_v) else None
    ctx["rsi_overbought"]= ctx["rsi_14"] > 70 if ctx["rsi_14"] else False
    ctx["rsi_oversold"]  = ctx["rsi_14"] < 30 if ctx["rsi_14"] else False

    # Bollinger bands (20, 2σ)
    bm = s.rolling(20).mean()
    bs = s.rolling(20).std()
    bb_u = float((bm + 2 * bs).iloc[-1])
    bb_l = float((bm - 2 * bs).iloc[-1])
    ctx["bb_upper"]         = bb_u
    ctx["bb_lower"]         = bb_l
    ctx["outside_bb_upper"] = last > bb_u
    ctx["outside_bb_lower"] = last < bb_l

    # Extreme move history
    abs_m = moves.abs()
    larger = abs_m[abs_m >= abs(chg)]
    if len(larger) > 1:
        prior = larger.iloc[:-1].index[-1]
        ctx["last_comparable_move_date"]  = prior
        ctx["days_since_comparable_move"] = (s.index[-1] - prior).days
    else:
        ctx["last_comparable_move_date"]  = None
        ctx["days_since_comparable_move"] = None
    ctx["moves_this_large_per_year"] = float(
        (abs_m >= abs(chg)).sum() / max(len(abs_m) / 252, 0.1)
    )

    return ctx


# ───────────────────────────────────────────────────────────────────────────────
# 2. SCORING & SELECTION
# ───────────────────────────────────────────────────────────────────────────────

_SCORING: list[tuple[str, callable]] = [
    ("extreme_move",  lambda c: 40 if abs(c.get("move_zscore_1y",0) or 0) > 3   else 0),
    ("large_move",    lambda c: 25 if 2 < abs(c.get("move_zscore_1y",0) or 0) <= 3 else 0),
    ("notable_move",  lambda c: 12 if 1.5 < abs(c.get("move_zscore_1y",0) or 0) <= 2 else 0),
    ("3y_extreme",    lambda c: 25 if (c.get("pct_rank_3y",50) or 50) > 97 or (c.get("pct_rank_3y",50) or 50) < 3 else 0),
    ("2y_extreme",    lambda c: 15 if (c.get("pct_rank_2y",50) or 50) > 95 or (c.get("pct_rank_2y",50) or 50) < 5 else 0),
    ("1y_extreme",    lambda c: 10 if (c.get("pct_rank_1y",50) or 50) > 90 or (c.get("pct_rank_1y",50) or 50) < 10 else 0),
    ("golden_cross",  lambda c: 30 if c.get("golden_cross_today") else 0),
    ("death_cross",   lambda c: 30 if c.get("death_cross_today")  else 0),
    ("at_52w_high",   lambda c: 20 if c.get("at_52w_high") else 0),
    ("at_52w_low",    lambda c: 20 if c.get("at_52w_low")  else 0),
    ("bb_break",      lambda c: 15 if c.get("outside_bb_upper") or c.get("outside_bb_lower") else 0),
    ("rsi_extreme",   lambda c: 12 if c.get("rsi_overbought") or c.get("rsi_oversold") else 0),
    ("streak_7",      lambda c: 25 if abs(c.get("streak",0) or 0) >= 7 else 0),
    ("streak_5",      lambda c: 15 if 5 <= abs(c.get("streak",0) or 0) < 7 else 0),
    ("streak_4",      lambda c:  8 if abs(c.get("streak",0) or 0) == 4 else 0),
    ("rare_move",     lambda c: 20 if (c.get("moves_this_large_per_year") or 99) < 1 else 0),
    ("vol_elevated",  lambda c: 10 if c.get("vol_regime_elevated") else 0),
    ("severe_dd",     lambda c: 15 if (c.get("current_drawdown_1y") or 0) < -15 else 0),
    ("large_yoy",     lambda c: 12 if abs(c.get("pct_chg_vs_1y_ago") or 0) > 20 else 0),
    ("near_ath",      lambda c: 12 if -2 < (c.get("pct_from_ath") or -99) < 0 else 0),
]

CHART_ROTATION = [
    "line_with_context_band",
    "bar_chart_returns",
    "line_with_percentile_fill",
    "rolling_zscore_chart",
    "regime_chart",
    "distribution_chart",
]


def score_and_select(contexts: list[dict], n: int = 20) -> list[dict]:
    """Score all contexts and return top-n with assigned chart types."""
    valid = [c for c in contexts if not c.get("insufficient_data")]

    # Cross-sectional momentum ranks
    for key in ["return_1m", "return_3m", "return_1y"]:
        rets = [(c, c.get(key)) for c in valid if c.get(key) is not None]
        rets.sort(key=lambda x: x[1])
        for rank, (c, _) in enumerate(rets):
            c[f"momentum_rank"] = rank / len(rets) * 100 if rets else 50

    # Score
    for c in valid:
        c["interest_score"] = sum(fn(c) for _, fn in _SCORING)

    # Select top-n, cycling chart types
    ranked = sorted(valid, key=lambda c: c["interest_score"], reverse=True)
    selected = ranked[:n]
    for i, c in enumerate(selected):
        c["chart_type"] = CHART_ROTATION[i % len(CHART_ROTATION)]
    return selected


# ───────────────────────────────────────────────────────────────────────────────
# 3. SUBTITLE GENERATION
# ───────────────────────────────────────────────────────────────────────────────

def _build_subtitle(ctx: dict) -> str:
    """Generate analytical subtitle: move · level context · one extra fact."""
    parts: list[str] = []
    chg     = ctx.get("daily_chg", 0) or 0
    chg_pct = ctx.get("daily_chg_pct", 0) or 0
    sign    = "+" if chg >= 0 else ""
    mz      = ctx.get("move_zscore_1y", 0) or 0
    mr      = ctx.get("move_pct_rank_1y", 50) or 50
    move_s  = f"{sign}{chg_pct:.2f}%"

    if abs(mz) > 3:
        parts.append(f"Extreme move {move_s} — {mr:.0f}th pct of 1Y moves")
    elif abs(mz) > 2:
        parts.append(f"Large move {move_s} — {mr:.0f}th pct of 1Y moves")
    elif abs(mz) > 1.5:
        parts.append(f"Notable move {move_s} — {mr:.0f}th pct of 1Y moves")
    else:
        parts.append(f"Yesterday {move_s}")

    pct3 = ctx.get("pct_rank_3y", 50) or 50
    if pct3 > 95:   parts.append(f"Near 3Y high ({pct3:.0f}th pct)")
    elif pct3 < 5:  parts.append(f"Near 3Y low ({pct3:.0f}th pct)")
    elif pct3 > 80 or pct3 < 20: parts.append(f"{pct3:.0f}th pct of 3Y range")

    streak = ctx.get("streak", 0) or 0
    if abs(streak) >= 4:
        parts.append(f"{abs(streak)}-day {'up' if streak > 0 else 'down'} streak")
    elif ctx.get("golden_cross_today"): parts.append("Golden cross (50d > 200dMA)")
    elif ctx.get("death_cross_today"):  parts.append("Death cross (50d < 200dMA)")
    elif ctx.get("at_52w_high"):        parts.append("At 52-week high")
    elif ctx.get("at_52w_low"):         parts.append("At 52-week low")
    elif ctx.get("outside_bb_upper"):   parts.append("Above upper Bollinger band")
    elif ctx.get("outside_bb_lower"):   parts.append("Below lower Bollinger band")

    if len(parts) < 3:
        p1y = ctx.get("pct_chg_vs_1y_ago")
        if p1y is not None:
            parts.append(f"{'+' if p1y >= 0 else ''}{p1y:.1f}% vs 1Y ago")

    return " · ".join(parts[:3])


# ───────────────────────────────────────────────────────────────────────────────
# 4. CHART.JS v4 CONFIG GENERATORS
# ───────────────────────────────────────────────────────────────────────────────

def _base_opts() -> dict:
    return {
        "responsive": True, "maintainAspectRatio": False,
        "animation":  {"duration": 0},
        "plugins": {
            "legend":   {"display": False},
            "tooltip":  {"mode": "index", "intersect": False,
                         "backgroundColor": "rgba(0,0,0,0.78)",
                         "titleFont": {"family": FONT, "size": 11},
                         "bodyFont":  {"family": FONT, "size": 11}, "padding": 8},
            "annotation": {"annotations": {}},
        },
        "scales": {
            "x": {"grid":  {"color": GRID, "drawBorder": False},
                  "ticks": {"color": TICK, "font": {"family": FONT, "size": 10},
                             "maxRotation": 0, "maxTicksLimit": 8}},
            "y": {"grid":  {"color": GRID, "drawBorder": False},
                  "ticks": {"color": TICK, "font": {"family": FONT, "size": 10},
                             "maxTicksLimit": 6},
                  "position": "right"},
        },
        "elements": {"point": {"radius": 0, "hoverRadius": 4},
                     "line":  {"tension": 0.1}},
        "interaction": {"mode": "index", "intersect": False},
    }


def _prep(series: pd.Series, lb: int) -> tuple[list, list]:
    s = series.dropna().iloc[-lb:]
    labels = [d.strftime("%b '%y") if hasattr(d, "strftime") else str(d) for d in s.index]
    return labels, [round(float(v), 6) for v in s.values]


def _chart_line_band(series: pd.Series, ctx: dict) -> dict:
    labels, vals = _prep(series, 126)
    n = len(vals)
    m = ctx.get("mean_1y") or float(np.mean(vals)) if vals else 0
    s = ctx.get("std_1y")  or float(np.std(vals)) or 1
    upper = [round(m + s, 6)] * n;  lower = [round(m - s, 6)] * n
    chg = ctx.get("daily_chg", 0) or 0
    pt_c = ["transparent"] * n;  pt_r = [0] * n
    if n:
        pt_c[-1] = GREEN if chg >= 0 else RED;  pt_r[-1] = 5
    return {"type": "line", "data": {"labels": labels, "datasets": [
        {"data": upper, "borderColor": "transparent", "backgroundColor": "rgba(24,95,165,0.09)",
         "fill": "+1", "pointRadius": 0, "order": 3},
        {"data": lower, "borderColor": "transparent", "fill": False, "pointRadius": 0, "order": 4},
        {"data": [round(m,6)]*n, "borderColor": "rgba(136,135,128,0.4)", "borderWidth": 1,
         "borderDash": [4,4], "fill": False, "pointRadius": 0, "order": 2},
        {"data": vals, "borderColor": BLUE, "borderWidth": 1.75, "fill": False,
         "pointBackgroundColor": pt_c, "pointRadius": pt_r, "pointHoverRadius": 5, "order": 1},
    ]}, "options": _base_opts()}


def _chart_pct_fill(series: pd.Series, ctx: dict) -> dict:
    labels, vals = _prep(series, 126)
    p3y = ctx.get("pct_rank_3y", 50) or 50
    if p3y > 90:   bg, lc = "rgba(226,75,74,0.13)",  RED
    elif p3y < 10: bg, lc = "rgba(24,95,165,0.13)",  BLUE
    else:          bg, lc = "rgba(136,135,128,0.10)", BLUE
    return {"type": "line", "data": {"labels": labels, "datasets": [
        {"data": vals, "borderColor": lc, "borderWidth": 1.75,
         "backgroundColor": bg, "fill": "origin", "pointRadius": 0}
    ]}, "options": _base_opts()}


def _chart_returns(series: pd.Series, ctx: dict) -> dict:
    s = series.dropna()
    rets = s.pct_change().dropna().iloc[-63:]
    if rets.empty:
        return _chart_line_band(series, ctx)
    labels = [d.strftime("%b %d") if hasattr(d, "strftime") else str(d) for d in rets.index]
    vals   = [round(float(v)*100, 4) for v in rets.values]
    mr = float(rets.mean()*100);  sr = float(rets.std()*100) or 0.01
    bg = ["rgba(29,158,117,0.75)" if v > sr*0.1 else "rgba(226,75,74,0.75)" if v < -sr*0.1
          else "rgba(136,135,128,0.5)" for v in vals]
    brd = bg.copy();  bw = [1]*len(vals)
    if vals: brd[-1] = "#111";  bw[-1] = 2
    opts = _base_opts()
    opts["plugins"]["annotation"]["annotations"] = {
        "mean": {"type": "line", "yMin": mr, "yMax": mr,
                 "borderColor": "rgba(0,0,0,0.25)", "borderWidth": 1, "borderDash": [4,3]},
        "up1s": {"type": "line", "yMin": mr+sr, "yMax": mr+sr,
                 "borderColor": "rgba(226,75,74,0.3)", "borderWidth": 1, "borderDash": [2,3]},
        "dn1s": {"type": "line", "yMin": mr-sr, "yMax": mr-sr,
                 "borderColor": "rgba(24,95,165,0.3)", "borderWidth": 1, "borderDash": [2,3]},
    }
    return {"type": "bar", "data": {"labels": labels, "datasets": [
        {"data": vals, "backgroundColor": bg, "borderColor": brd, "borderWidth": bw, "barPercentage": 0.85}
    ]}, "options": opts}


def _chart_zscore(series: pd.Series, ctx: dict) -> dict:
    s = series.dropna()
    rm = s.rolling(252).mean();  rs = s.rolling(252).std()
    z  = ((s - rm) / rs).dropna()
    if z.empty:
        return _chart_line_band(series, ctx)
    labels = [d.strftime("%b '%y") if hasattr(d, "strftime") else str(d) for d in z.index]
    vals   = [round(float(v), 4) for v in z.values]
    bg = ["rgba(226,75,74,0.65)" if v > 2 else "rgba(24,95,165,0.65)" if v < -2
          else "rgba(136,135,128,0.4)" for v in vals]
    opts = _base_opts()
    opts["plugins"]["annotation"]["annotations"] = {
        "z0":  {"type":"line","yMin":0,  "yMax":0,  "borderColor":"rgba(0,0,0,0.25)","borderWidth":1.5},
        "zp2": {"type":"line","yMin":2,  "yMax":2,  "borderColor":"rgba(226,75,74,0.5)","borderWidth":1.5,"borderDash":[3,3]},
        "zn2": {"type":"line","yMin":-2, "yMax":-2, "borderColor":"rgba(24,95,165,0.5)","borderWidth":1.5,"borderDash":[3,3]},
    }
    return {"type": "bar", "data": {"labels": labels, "datasets": [
        {"data": vals, "backgroundColor": bg, "borderWidth": 0,
         "barPercentage": 1.0, "categoryPercentage": 0.96}
    ]}, "options": opts}


def _chart_regime(series: pd.Series, ctx: dict) -> dict:
    s = series.dropna().iloc[-504:]
    ma200 = s.rolling(200).mean()
    labels = [d.strftime("%b '%y") if hasattr(d, "strftime") else str(d) for d in s.index]
    vals   = [round(float(v), 6) for v in s.values]
    ma_v   = [round(float(v), 6) if pd.notna(v) else None for v in ma200.values]
    anns: dict = {}
    i = 0
    while i < len(labels):
        if ma_v[i] is None: i += 1; continue
        above = vals[i] > ma_v[i];  j = i
        while j < len(labels) and ma_v[j] is not None and (vals[j] > ma_v[j]) == above:
            j += 1
        if j > i+1:
            anns[f"r{i}"] = {"type":"box","xMin":labels[i],"xMax":labels[j-1],
                              "backgroundColor": "rgba(29,158,117,0.07)" if above else "rgba(226,75,74,0.07)",
                              "borderWidth":0,"drawTime":"beforeDatasetsDraw"}
        i = j
    opts = _base_opts();  opts["plugins"]["annotation"]["annotations"] = anns
    return {"type": "line", "data": {"labels": labels, "datasets": [
        {"data": ma_v, "borderColor": "rgba(136,135,128,0.5)", "borderWidth": 1,
         "borderDash": [5,4], "fill": False, "pointRadius": 0, "order": 2},
        {"data": vals, "borderColor": BLUE, "borderWidth": 1.75,
         "fill": False, "pointRadius": 0, "pointHoverRadius": 4, "order": 1},
    ]}, "options": opts}


def _chart_dist(series: pd.Series, ctx: dict) -> dict:
    moves = series.dropna().diff().dropna().iloc[-504:]
    chg   = ctx.get("daily_chg", 0) or 0
    if len(moves) < 5:
        return _chart_line_band(series, ctx)
    arr   = moves.values
    edges = np.linspace(arr.min(), arr.max(), 37)
    cnts, _ = np.histogram(arr, bins=edges)
    ctrs  = [(edges[i]+edges[i+1])/2 for i in range(36)]
    today_bin = max(0, min(int(np.searchsorted(edges[:-1], chg, side="right"))-1, 35))
    labels= [f"{c:.4f}" for c in ctrs]
    bg    = [CORAL if i==today_bin else "rgba(24,95,165,0.5)" if ctrs[i]<chg
             else "rgba(136,135,128,0.35)" for i in range(36)]
    opts  = _base_opts();  opts["plugins"]["tooltip"] = {"enabled": False}
    opts["scales"]["x"]["ticks"]["maxTicksLimit"] = 6
    return {"type": "bar", "data": {"labels": labels, "datasets": [
        {"data": list(cnts), "backgroundColor": bg, "borderWidth": 0,
         "barPercentage": 1.0, "categoryPercentage": 1.0}
    ]}, "options": opts}


_CHART_FNS = {
    "line_with_context_band":    _chart_line_band,
    "bar_chart_returns":         _chart_returns,
    "line_with_percentile_fill": _chart_pct_fill,
    "rolling_zscore_chart":      _chart_zscore,
    "regime_chart":              _chart_regime,
    "distribution_chart":        _chart_dist,
}


# ───────────────────────────────────────────────────────────────────────────────
# 5. MAIN API FUNCTION
# ───────────────────────────────────────────────────────────────────────────────

def compute_newsletter_data(n_charts: int = 20) -> dict:
    """
    Compute the full Daily Edge newsletter dataset from the current watchlist.

    Returns
    -------
    dict with keys:
      edition_date   str          today’s date
      total_symbols  int          symbols processed
      charts         list[dict]   selected chart cards with configs
      errors         list[str]    any symbols that failed
    """
    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return {"error": "No symbols in watchlist. Add tickers and fetch data first.",
                "charts": [], "edition_date": str(datetime.date.today())}

    all_contexts: list[dict] = []
    series_cache: dict[str, pd.Series] = {}
    errors: list[str] = []

    for sym in symbols:
        try:
            ohlcv = db.get_ohlcv_df(sym, "daily", limit=800)
            if ohlcv is None or ohlcv.empty or len(ohlcv) < 20:
                errors.append(f"{sym}: no data")
                continue
            series = ohlcv["close"].dropna()
            series.index = pd.DatetimeIndex(series.index)
            ctx = engineer_features(series, sym)
            if ctx.get("insufficient_data"):
                continue
            all_contexts.append(ctx)
            series_cache[sym] = series
        except Exception as exc:
            errors.append(f"{sym}: {exc}")

    if not all_contexts:
        return {"error": "No data available. Fetch symbols first.",
                "charts": [], "edition_date": str(datetime.date.today()), "errors": errors}

    selected = score_and_select(all_contexts, n=min(n_charts, len(all_contexts)))

    charts_out: list[dict] = []
    for idx, ctx in enumerate(selected):
        sym    = ctx["symbol"]
        series = series_cache.get(sym, pd.Series())
        ctype  = ctx.get("chart_type", "line_with_context_band")
        fn     = _CHART_FNS.get(ctype, _chart_line_band)
        try:
            config = fn(series, ctx)
        except Exception:
            config = _chart_line_band(series, ctx)

        # Last date string
        dl = ctx.get("date_last")
        date_str = dl.strftime("%b %d, %Y") if hasattr(dl, "strftime") else str(dl or "")

        charts_out.append({
            "id":             f"c{idx:04d}-{sym.lower().replace('^','').replace('=','')}",
            "symbol":         sym,
            "label":          sym,
            "asset_class":    ctx.get("asset_class", "equities"),
            "interest_score": int(ctx.get("interest_score", 0)),
            "chart_type":     ctype,
            "last":           round(ctx.get("last", 0), 4),
            "last_formatted": f"{ctx.get('last', 0):.2f}",
            "daily_chg":      round(ctx.get("daily_chg", 0), 4),
            "daily_chg_pct":  round(ctx.get("daily_chg_pct") or 0, 3),
            "chg_formatted":  f"{'+'if ctx.get('daily_chg',0)>=0 else ''}{ctx.get('daily_chg_pct',0):.2f}%",
            "subtitle":       _build_subtitle(ctx),
            "date_last":      date_str,
            "rsi_14":         round(ctx.get("rsi_14") or 0, 1),
            "pct_rank_1y":    round(ctx.get("pct_rank_1y", 50), 1),
            "pct_rank_3y":    round(ctx.get("pct_rank_3y", 50), 1),
            "streak":         ctx.get("streak", 0),
            "realized_vol_1m":round(ctx.get("realized_vol_1m") or 0, 2),
            "current_dd_1y":  round(ctx.get("current_drawdown_1y") or 0, 2),
            "score_breakdown":ctx.get("score_breakdown", {}),
            "chartjs_config": config,
        })

    return {
        "edition_date":  str(datetime.date.today()),
        "total_symbols": len(all_contexts),
        "charts":        charts_out,
        "errors":        errors,
    }
