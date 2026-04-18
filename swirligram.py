"""
swirligram.py — RSI Phase-Space (Swirligram) analysis.

A Swirligram plots RSI on the X axis and Δ-RSI (1-bar change) on the Y axis,
creating a phase-space portrait that reveals acceleration / deceleration patterns.

Key buy signal (per user intent):
  - Weekly RSI 50-60 (healthy medium-term anchor, not overbought)
  - Daily RSI recently bounced from <20 oversold, now 25-45 and accelerating up
  - i.e. dRSI > 0 — "low but going from 10 → 40"
"""

import numpy as np
import pandas as pd
import database as db
from ta_core import _rsi


def _safe(v):
    if v is None:
        return None
    try:
        if np.isnan(v):
            return None
    except Exception:
        pass
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return round(float(v), 3)
    return v


# ── Signal scoring ─────────────────────────────────────────────────────────────

def _score_daily(rsi_s: pd.Series, drsi_s: pd.Series) -> dict:
    """
    Score the current daily RSI phase for a buy-setup.

    Ideal scenario (per user intent):
      - Was deeply oversold (< 20) within last 15 bars
      - Now in recovery zone (25 – 45)
      - dRSI > 0 (accelerating upward — "going from 10 to 40")
    """
    valid = rsi_s.dropna()
    dvalid = drsi_s.dropna()
    if len(valid) < 10:
        return {"label": "No Data", "score": 0, "color": "gray", "details": []}

    cur_rsi  = float(valid.iloc[-1])
    cur_drsi = float(dvalid.iloc[-1]) if len(dvalid) else 0.0
    score    = 0
    details  = []

    # ── Zone score ──────────────────────────────────────────────
    if 25 <= cur_rsi <= 45:
        score += 35
        details.append(f"RSI {cur_rsi:.1f} — ideal recovery zone [25–45] ✓")
    elif 45 < cur_rsi <= 55:
        score += 15
        details.append(f"RSI {cur_rsi:.1f} — mid-range neutral")
    elif cur_rsi < 25:
        score += 12
        details.append(f"RSI {cur_rsi:.1f} — deeply oversold, watch for upturn")
    elif cur_rsi > 70:
        score -= 20
        details.append(f"RSI {cur_rsi:.1f} — overbought ✗")
    else:
        details.append(f"RSI {cur_rsi:.1f}")

    # ── Bounced from oversold? ───────────────────────────────────
    lookback = valid.iloc[-15:]
    was_deep  = (lookback < 20).any()
    was_os    = (lookback < 25).any()

    if was_deep and cur_rsi >= 25:
        days_since = int(((lookback < 20).values[::-1]).argmax()) + 1
        score += 30
        details.append(f"Bounced from <20 oversold {days_since}d ago ✓✓")
    elif was_os and cur_rsi >= 30:
        days_since = int(((lookback < 25).values[::-1]).argmax()) + 1
        score += 18
        details.append(f"Recovering from <25 oversold {days_since}d ago ✓")

    # ── Acceleration (dRSI) ──────────────────────────────────────
    if cur_drsi > 4:
        score += 22
        details.append(f"Strong acceleration +{cur_drsi:.1f}/bar ✓✓")
    elif cur_drsi > 1.5:
        score += 14
        details.append(f"Accelerating +{cur_drsi:.1f}/bar ✓")
    elif cur_drsi > 0:
        score += 6
        details.append(f"Slightly rising +{cur_drsi:.1f}/bar")
    elif cur_drsi < -4:
        score -= 18
        details.append(f"Sharp deceleration {cur_drsi:.1f}/bar ✗")
    elif cur_drsi < -1:
        score -= 8
        details.append(f"Falling {cur_drsi:.1f}/bar")

    # ── 5-bar RSI momentum ───────────────────────────────────────
    if len(valid) >= 5:
        gain_5 = float(valid.iloc[-1] - valid.iloc[-5])
        if gain_5 > 10:
            score += 13
            details.append(f"5-bar RSI gain +{gain_5:.1f} ✓")
        elif gain_5 > 4:
            score += 6
            details.append(f"5-bar RSI +{gain_5:.1f}")
        elif gain_5 < -8:
            score -= 8

    score = max(0, min(100, score))

    if   score >= 70: label, color = "Strong Buy Setup",  "green"
    elif score >= 50: label, color = "Buy Setup",          "yellow"
    elif score >= 30: label, color = "Watch",              "orange"
    else:             label, color = "No Setup",           "gray"

    return {"label": label, "score": score, "color": color, "details": details}


def _score_weekly(rsi_s: pd.Series, drsi_s: pd.Series) -> dict:
    """
    Score the weekly RSI phase — ideal anchor is 50-60 (healthy uptrend,
    not overbought, confirming medium-term demand exists).
    """
    valid = rsi_s.dropna()
    dvalid = drsi_s.dropna()
    if len(valid) < 5:
        return {"label": "No Data", "score": 0, "color": "gray", "details": []}

    cur_rsi  = float(valid.iloc[-1])
    cur_drsi = float(dvalid.iloc[-1]) if len(dvalid) else 0.0
    score    = 0
    details  = []

    # ── Zone score ──────────────────────────────────────────────
    if 50 <= cur_rsi <= 62:
        score += 50
        details.append(f"Weekly RSI {cur_rsi:.1f} — ideal anchor [50–62] ✓✓")
    elif 45 <= cur_rsi < 50:
        score += 30
        details.append(f"Weekly RSI {cur_rsi:.1f} — approaching ideal zone ✓")
    elif 62 < cur_rsi <= 70:
        score += 22
        details.append(f"Weekly RSI {cur_rsi:.1f} — slightly above ideal, still ok")
    elif cur_rsi > 70:
        score -= 8
        details.append(f"Weekly RSI {cur_rsi:.1f} — weekly overbought ✗")
    elif cur_rsi < 30:
        score += 8
        details.append(f"Weekly RSI {cur_rsi:.1f} — weekly deeply oversold, structural risk")
    elif cur_rsi < 45:
        score += 12
        details.append(f"Weekly RSI {cur_rsi:.1f} — weekly weak, below ideal")
    else:
        details.append(f"Weekly RSI {cur_rsi:.1f}")

    # ── Weekly dRSI ──────────────────────────────────────────────
    if cur_drsi > 1.5:
        score += 22
        details.append(f"Weekly RSI rising +{cur_drsi:.2f} ✓")
    elif cur_drsi > 0:
        score += 12
        details.append(f"Weekly RSI ticking up +{cur_drsi:.2f}")
    elif cur_drsi > -2:
        score += 6
        details.append(f"Weekly RSI stable {cur_drsi:.2f}")
    else:
        score -= 10
        details.append(f"Weekly RSI falling {cur_drsi:.2f} ✗")

    # ── 3-week slope ─────────────────────────────────────────────
    if len(valid) >= 4:
        slope = float(valid.iloc[-1] - valid.iloc[-4])
        if slope > 4:
            score += 15
            details.append(f"3-week RSI slope +{slope:.1f} ✓")
        elif slope > 0:
            score += 6
        elif slope < -6:
            score -= 10
            details.append(f"3-week RSI declining {slope:.1f} ✗")

    score = max(0, min(100, score))

    if   score >= 70: label, color = "Strong Weekly Anchor", "green"
    elif score >= 50: label, color = "Good Weekly Anchor",   "yellow"
    elif score >= 30: label, color = "Weak Weekly",          "orange"
    else:             label, color = "Poor Weekly",          "gray"

    return {"label": label, "score": score, "color": color, "details": details}


# ── Public ─────────────────────────────────────────────────────────────────────

def compute_swirligram(symbol: str, rsi_period: int = 14,
                       daily_trail: int = 90,
                       weekly_trail: int = 52) -> dict:
    """
    Return daily + weekly RSI phase-space data for the Swirligram tab.

    Response shape:
    {
      symbol, rsi_period,
      daily: {
        rsi, drsi, dates,   <- lists of floats / strings, aligned
        current: {rsi, drsi},
        signal: {label, score, color, details}
      },
      weekly: { ...same... } | null,
      combined: {label, score, color}
    }
    """
    daily_limit  = daily_trail  + rsi_period + 60
    weekly_limit = weekly_trail + rsi_period + 20

    df_d = db.get_ohlcv_df(symbol.upper(), "daily",  limit=daily_limit)
    df_w = db.get_ohlcv_df(symbol.upper(), "weekly", limit=weekly_limit)

    if df_d.empty:
        return {"error": f"No daily data for {symbol}"}

    # ── Daily ────────────────────────────────────────────────────
    rsi_d  = _rsi(df_d["close"], window=rsi_period)
    drsi_d = rsi_d.diff()

    valid_d = rsi_d.dropna()
    n_d     = min(daily_trail, len(valid_d))
    rsi_d_t  = valid_d.iloc[-n_d:]
    drsi_d_t = drsi_d.reindex(rsi_d_t.index)

    daily_signal = _score_daily(rsi_d, drsi_d)

    result_daily = {
        "rsi":     [_safe(v) for v in rsi_d_t.values],
        "drsi":    [_safe(v) for v in drsi_d_t.values],
        "dates":   [d.strftime("%Y-%m-%d") for d in rsi_d_t.index],
        "current": {
            "rsi":  _safe(rsi_d_t.iloc[-1]),
            "drsi": _safe(drsi_d_t.iloc[-1]),
        },
        "signal": daily_signal,
    }

    # ── Weekly ───────────────────────────────────────────────────
    result_weekly = None
    if not df_w.empty:
        rsi_w  = _rsi(df_w["close"], window=rsi_period)
        drsi_w = rsi_w.diff()

        valid_w = rsi_w.dropna()
        n_w     = min(weekly_trail, len(valid_w))
        rsi_w_t  = valid_w.iloc[-n_w:]
        drsi_w_t = drsi_w.reindex(rsi_w_t.index)

        weekly_signal = _score_weekly(rsi_w, drsi_w)

        result_weekly = {
            "rsi":     [_safe(v) for v in rsi_w_t.values],
            "drsi":    [_safe(v) for v in drsi_w_t.values],
            "dates":   [d.strftime("%Y-%m-%d") for d in rsi_w_t.index],
            "current": {
                "rsi":  _safe(rsi_w_t.iloc[-1]),
                "drsi": _safe(drsi_w_t.iloc[-1]),
            },
            "signal": weekly_signal,
        }

    # ── Combined signal ──────────────────────────────────────────
    d_score = daily_signal["score"]
    w_score = result_weekly["signal"]["score"] if result_weekly else 0

    combined_score = int(round(d_score * 0.55 + w_score * 0.45))

    if   combined_score >= 65: combined_label, combined_color = "STRONG BUY SETUP",  "green"
    elif combined_score >= 50: combined_label, combined_color = "BUY SETUP",          "yellow"
    elif combined_score >= 35: combined_label, combined_color = "Watch",              "orange"
    else:                      combined_label, combined_color = "No Setup",           "gray"

    return {
        "symbol":     symbol.upper(),
        "rsi_period": rsi_period,
        "daily":      result_daily,
        "weekly":     result_weekly,
        "combined":   {
            "label": combined_label,
            "score": combined_score,
            "color": combined_color,
        },
    }
