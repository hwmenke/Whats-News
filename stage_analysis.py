"""
stage_analysis.py — Weinstein / Jacobs-style stage classification (1–4).

Mechanical book implementation inspired by Stan Weinstein's stage analysis
(popularized in trading education by accounts such as @SteveDJacobs):

  Stage 1  Basing     — price consolidating around a flattening 30-week MA
  Stage 2  Advancing  — price above a rising 30-week MA (preferred long zone)
  Stage 3  Topping    — MA flattening/rolling after an advance; distribution risk
  Stage 4  Declining  — price below a falling 30-week MA

Uses weekly SMA(30) as the classic 30-week MA proxy + volume confirmation hints.
This is a local approximation — not Steve Jacobs' discretionary calls and not a
licensed Weinstein product.
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
    1: "Base / consolidation around flat 30W MA — wait for Stage 2 breakout",
    2: "Advance — price above rising 30W MA (preferred long structure)",
    3: "Topping risk — MA flattening/rolling after advance",
    4: "Decline — price below falling 30W MA (avoid new longs)",
    0: "Not enough weekly history for a stage call",
}

# Action hints (educational, not advice)
STAGE_ACTIONS = {
    1: "Watch for breakout above base + rising MA → Stage 2",
    2: "Favor longs / trail; buy strength on volume",
    3: "Tighten / reduce; avoid fresh breakout buys",
    4: "Avoid new longs; wait for Stage 1 base",
    0: "Fetch more weekly history",
}


def _sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=max(5, n // 2)).mean()


def _empty(sym: str) -> dict:
    return {
        "symbol": sym,
        "stage": 0,
        "stage_label": STAGE_LABELS[0],
        "stage_blurb": STAGE_BLURBS[0],
        "stage_action": STAGE_ACTIONS[0],
        "sma30": None,
        "vs_sma30_pct": None,
        "sma30_slope_pct": None,
        "vol_confirm": None,
        "early_stage2": False,
        "ready": False,
        "sma30_series": [],
    }


def classify_stage(symbol: str, include_series: bool = False) -> dict:
    """
    Return stage 1–4 (or 0) from weekly closes vs SMA(30).

    Heuristics (Jacobs / Weinstein–adjacent, mechanical):
      - ≥40 weekly bars
      - SMA30 slope over ~8 weeks
      - Price vs SMA30
      - Distance from 26-week high
      - Volume: recent 4W avg vs prior 12W (expansion in Stage 2)
      - early_stage2: just broke above SMA after Stage-1-like base
    """
    sym = symbol.upper()
    df = md.get_ohlcv_df(sym, "weekly", limit=160)
    if df is None or df.empty or len(df) < 40:
        return _empty(sym)

    close = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)
    sma30 = _sma(close, 30)
    last = float(close.iloc[-1])
    ma = float(sma30.iloc[-1]) if not pd.isna(sma30.iloc[-1]) else None
    if ma is None or ma <= 0:
        return _empty(sym)

    ma_prev = float(sma30.iloc[-9]) if len(sma30) >= 9 and not pd.isna(sma30.iloc[-9]) else ma
    ma_prev26 = float(sma30.iloc[-27]) if len(sma30) >= 27 and not pd.isna(sma30.iloc[-27]) else ma_prev
    slope_pct = ((ma / ma_prev) - 1.0) * 100 if ma_prev else 0.0
    slope_long_pct = ((ma / ma_prev26) - 1.0) * 100 if ma_prev26 else slope_pct
    vs_pct = ((last / ma) - 1.0) * 100

    hi_26 = float(close.tail(26).max())
    lo_26 = float(close.tail(26).min())
    dist_hi = ((last / hi_26) - 1.0) * 100 if hi_26 else 0.0
    range_pct = ((hi_26 / lo_26) - 1.0) * 100 if lo_26 > 0 else 0.0

    # Was price mostly below MA 12–20 weeks ago? (base → breakout context)
    past = close.iloc[-20:-8] if len(close) >= 20 else close.iloc[:-4]
    past_ma = sma30.iloc[-20:-8] if len(sma30) >= 20 else sma30.iloc[:-4]
    below_count = 0
    pairs = min(len(past), len(past_ma))
    for i in range(pairs):
        c, m = float(past.iloc[i]), float(past_ma.iloc[i]) if not pd.isna(past_ma.iloc[i]) else None
        if m and c < m:
            below_count += 1
    was_basing = pairs > 0 and (below_count / pairs) >= 0.45 and abs(slope_pct) < 2.5

    vol_confirm = None
    if len(volume) >= 16:
        recent = float(volume.tail(4).mean())
        prior = float(volume.iloc[-16:-4].mean())
        if prior > 0:
            vol_confirm = round(recent / prior, 2)

    rising = slope_pct >= 0.6
    falling = slope_pct <= -0.6
    flat = not rising and not falling
    above = vs_pct >= 1.0
    below = vs_pct <= -1.0
    near = abs(vs_pct) < 3.5

    stage = 0
    early_stage2 = False

    if above and rising:
        stage = 2
        # Fresh breakout from base
        if was_basing and vs_pct < 12:
            early_stage2 = True
    elif below and falling:
        stage = 4
    elif near and flat and range_pct < 35:
        stage = 1
    elif (above or near) and (flat or falling) and dist_hi > -15 and slope_long_pct > -1:
        stage = 3
    elif below and flat:
        stage = 1
    elif above and flat:
        stage = 2 if vs_pct >= 4 else 1
    elif below and rising:
        stage = 1  # reclaim attempt — still base until clear Stage 2
    else:
        stage = 1 if near else (2 if above else 4)

    # Volume expansion supports Stage 2; dry-up on Stage 3/4 is common
    if stage == 2 and vol_confirm is not None and vol_confirm >= 1.15:
        pass  # confirmed
    if stage == 3 and vol_confirm is not None and vol_confirm >= 1.3:
        # heavy volume into flat/down MA → distribution hint (stay Stage 3)
        pass

    series = []
    if include_series:
        for dt, val in sma30.dropna().items():
            try:
                d = str(pd.Timestamp(dt).date())
            except Exception:
                d = str(dt)[:10]
            series.append({"time": d, "value": round(float(val), 4)})

    return {
        "symbol": sym,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, STAGE_LABELS[0]),
        "stage_blurb": STAGE_BLURBS.get(stage, STAGE_BLURBS[0]),
        "stage_action": STAGE_ACTIONS.get(stage, STAGE_ACTIONS[0]),
        "sma30": round(ma, 2),
        "vs_sma30_pct": round(vs_pct, 2),
        "sma30_slope_pct": round(slope_pct, 2),
        "sma30_slope_long_pct": round(slope_long_pct, 2),
        "dist_26w_high_pct": round(dist_hi, 2),
        "vol_confirm": vol_confirm,
        "early_stage2": early_stage2,
        "was_basing": was_basing,
        "ready": True,
        "sma30_series": series,
    }
