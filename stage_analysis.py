"""
stage_analysis.py — Weinstein-style stage classification (1–4).

Uses weekly SMA(30) as a proxy for the classic 30-week moving average.
This is a mechanical book label — not Steve Jacobs' discretionary classification,
and not a licensed Weinstein product. Labels are honest and local.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

import market_data as md

STAGE_LABELS = {
    1: "Stage 1 · Basing",
    2: "Stage 2 · Advancing",
    3: "Stage 3 · Topping",
    4: "Stage 4 · Declining",
    0: "Stage ? · Unclear",
}

STAGE_BLURBS = {
    1: "Price near flat 30W MA — consolidation / base",
    2: "Price above rising 30W MA — advance",
    3: "Price near rolling-over 30W MA after advance — top risk",
    4: "Price below falling 30W MA — decline",
    0: "Not enough weekly history for a stage call",
}


def _sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=max(5, n // 2)).mean()


def classify_stage(symbol: str) -> dict:
    """
    Return stage 1–4 (or 0) from weekly closes vs SMA(30).

    Rules (mechanical):
      - Need ≥40 weekly bars
      - Slope of SMA30 over ~8 weeks (pct change)
      - Price vs SMA30 and recent peak/trough context
    """
    sym = symbol.upper()
    df = md.get_ohlcv_df(sym, "weekly", limit=120)
    if df is None or df.empty or len(df) < 40:
        return {
            "symbol": sym,
            "stage": 0,
            "stage_label": STAGE_LABELS[0],
            "stage_blurb": STAGE_BLURBS[0],
            "sma30": None,
            "vs_sma30_pct": None,
            "sma30_slope_pct": None,
            "ready": False,
        }

    close = df["close"].astype(float)
    sma30 = _sma(close, 30)
    last = float(close.iloc[-1])
    ma = float(sma30.iloc[-1]) if not pd.isna(sma30.iloc[-1]) else None
    if ma is None or ma <= 0:
        return {
            "symbol": sym,
            "stage": 0,
            "stage_label": STAGE_LABELS[0],
            "stage_blurb": STAGE_BLURBS[0],
            "sma30": None,
            "vs_sma30_pct": None,
            "sma30_slope_pct": None,
            "ready": False,
        }

    ma_prev = float(sma30.iloc[-9]) if len(sma30) >= 9 and not pd.isna(sma30.iloc[-9]) else ma
    slope_pct = ((ma / ma_prev) - 1.0) * 100 if ma_prev else 0.0
    vs_pct = ((last / ma) - 1.0) * 100

    # High of last ~26 weeks vs last
    hi_26 = float(close.tail(26).max())
    lo_26 = float(close.tail(26).min())
    dist_hi = ((last / hi_26) - 1.0) * 100 if hi_26 else 0.0

    rising = slope_pct >= 0.8
    falling = slope_pct <= -0.8
    flat = not rising and not falling
    above = vs_pct >= 1.0
    below = vs_pct <= -1.0
    near = abs(vs_pct) < 3.0

    stage = 0
    if above and rising:
        stage = 2
    elif below and falling:
        stage = 4
    elif near and flat:
        stage = 1
    elif (above or near) and (flat or falling) and dist_hi > -12:
        # Was likely advancing; MA flattening/rolling — Stage 3 risk
        stage = 3
    elif below and flat:
        stage = 1  # low-level base under MA
    elif above and flat:
        stage = 2 if vs_pct >= 3 else 1
    elif below and rising:
        # Early reclaim attempt — still treat as base/early until clearly above
        stage = 1
    else:
        stage = 1 if near else (2 if above else 4)

    return {
        "symbol": sym,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS[0]),
        "stage_blurb": STAGE_BLURBS.get(stage, STAGE_BLURBS[0]),
        "sma30": round(ma, 2),
        "vs_sma30_pct": round(vs_pct, 2),
        "sma30_slope_pct": round(slope_pct, 2),
        "dist_26w_high_pct": round(dist_hi, 2),
        "ready": True,
    }
