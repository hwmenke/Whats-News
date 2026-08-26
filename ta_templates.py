"""
ta_templates.py — Mechanical Minervini Trend Template + Stockbee momentum helpers.

Honest book implementations from stored OHLCV only.
Not licensed SEPA / Stockbee Market Monitor / IBD products.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

import market_data as md


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(5, n // 3)).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=max(3, n // 2)).mean()


def _last(s: pd.Series):
    v = s.dropna()
    if v.empty:
        return None
    return float(v.iloc[-1])


def minervini_trend_template(symbol: str, df=None) -> dict:
    """
    Classic 8-point Trend Template (price/MA structure) on daily bars.

    Criterion 8 uses 21D return strength as a *book* RS proxy — never IBD RS.
    Pass `df` to avoid a second OHLCV load during batch precompute.
    """
    sym = symbol.upper()
    if df is None:
        df = md.get_ohlcv_df(sym, "daily", limit=280)
    if df is None or df.empty or len(df) < 200:
        return {
            "symbol": sym,
            "ready": False,
            "pass": False,
            "score": 0,
            "max_score": 8,
            "checks": {},
            "tags": [],
        }

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    last = float(close.iloc[-1])

    sma50 = _sma(close, 50)
    sma150 = _sma(close, 150)
    sma200 = _sma(close, 200)
    s50, s150, s200 = _last(sma50), _last(sma150), _last(sma200)

    # 200 SMA rising vs ~22 trading days ago
    s200_prev = None
    if len(sma200.dropna()) >= 22:
        s200_prev = float(sma200.dropna().iloc[-22])

    hi_52 = float(high.tail(min(252, len(high))).max())
    lo_52 = float(low.tail(min(252, len(low))).min())
    vs_low = ((last / lo_52) - 1.0) * 100 if lo_52 > 0 else None
    vs_high = ((last / hi_52) - 1.0) * 100 if hi_52 > 0 else None

    ret_21 = None
    if len(close) >= 22:
        ret_21 = ((last / float(close.iloc[-22])) - 1.0) * 100

    checks = {
        "above_150_200": bool(s150 and s200 and last > s150 and last > s200),
        "sma150_above_200": bool(s150 and s200 and s150 > s200),
        "sma200_rising": bool(s200 and s200_prev and s200 > s200_prev),
        "sma50_above_long": bool(s50 and s150 and s200 and s50 > s150 and s50 > s200),
        "above_sma50": bool(s50 and last > s50),
        "above_52w_low_25pct": bool(vs_low is not None and vs_low >= 25),
        "within_25pct_52w_high": bool(vs_high is not None and vs_high >= -25),
        # Absolute 21D return ≥5% — not a rank-in-book RS check.
        "book_momentum_ok": bool(ret_21 is not None and ret_21 >= 5),
    }
    score = sum(1 for v in checks.values() if v)
    passed = score >= 7  # allow one miss

    # VCP-ish: ATR contracting over last 20 vs prior 20
    prev_c = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_c).abs(), (low - prev_c).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_recent = float(atr.tail(20).mean()) if len(atr) >= 20 else None
    atr_prior = float(atr.iloc[-40:-20].mean()) if len(atr) >= 40 else None
    vcp = bool(atr_recent and atr_prior and atr_recent < atr_prior * 0.85)

    # Pivot pressure: near 20D high after contraction
    hi_20 = float(high.tail(20).max())
    near_pivot = last >= hi_20 * 0.97
    vol_avg = float(volume.tail(21).iloc[:-1].mean()) if len(volume) > 21 else None
    vol_today = float(volume.iloc[-1])
    vol_dry = bool(vol_avg and vol_today < vol_avg * 0.8)
    pivot = bool(vcp and near_pivot)

    tags = []
    if passed:
        tags.append("MINERVINI_TT")
    if vcp:
        tags.append("MINERVINI_VCP")
    if pivot:
        tags.append("MINERVINI_PIVOT")

    return {
        "symbol": sym,
        "ready": True,
        "pass": passed,
        "score": score,
        "max_score": 8,
        "checks": checks,
        "vs_52w_low_pct": round(vs_low, 2) if vs_low is not None else None,
        "vs_52w_high_pct": round(vs_high, 2) if vs_high is not None else None,
        "ret_21d_pct": round(ret_21, 2) if ret_21 is not None else None,
        "vcp": vcp,
        "near_pivot": near_pivot,
        "vol_dry": vol_dry,
        "tags": tags,
        "sma50": round(s50, 2) if s50 else None,
        "sma150": round(s150, 2) if s150 else None,
        "sma200": round(s200, 2) if s200 else None,
    }


def stockbee_momentum(symbol: str, df=None) -> dict:
    """
    Stockbee-style mechanical flags: EP-class gap/vol, 9/20 EMA, range expansion, anticipation coil.
    Pass `df` to reuse bars already loaded by the caller.
    """
    sym = symbol.upper()
    if df is None:
        df = md.get_ohlcv_df(sym, "daily", limit=120)
    if df is None or df.empty or len(df) < 30:
        return {"symbol": sym, "ready": False, "tags": []}

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])

    ema9 = _ema(close, 9)
    ema20 = _ema(close, 20)
    e9, e20 = _last(ema9), _last(ema20)

    gap_pct = ((float(open_.iloc[-1]) / prev) - 1.0) * 100 if prev else None
    vol_avg = float(volume.tail(21).iloc[:-1].mean()) if len(volume) > 21 else None
    vol_ratio = (float(volume.iloc[-1]) / vol_avg) if vol_avg else None

    # True range expansion
    prev_c = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_c).abs(), (low - prev_c).abs()],
        axis=1,
    ).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    tr_today = float(tr.iloc[-1])
    atr_v = _last(atr14)
    range_exp = bool(atr_v and tr_today >= atr_v * 1.8)

    # Anticipation: last 5–8 bars tight vs prior 20, after prior 21D strength
    recent_range = float(high.tail(8).max() - low.tail(8).min()) if len(high) >= 8 else None
    prior_range = float(high.iloc[-28:-8].max() - low.iloc[-28:-8].min()) if len(high) >= 28 else None
    ret_21 = ((last / float(close.iloc[-22])) - 1.0) * 100 if len(close) >= 22 else None
    anticipation = bool(
        recent_range is not None
        and prior_range
        and prior_range > 0
        and recent_range < prior_range * 0.45
        and ret_21 is not None
        and ret_21 >= 8
    )

    ema_stack = bool(e9 and e20 and last > e9 > e20)
    ep_strong = bool(gap_pct is not None and vol_ratio is not None and gap_pct >= 4 and vol_ratio >= 2.0)
    ep_soft = bool(gap_pct is not None and vol_ratio is not None and gap_pct >= 4 and vol_ratio >= 1.5)

    tags = []
    if ep_strong or ep_soft:
        tags.append("STOCKBEE_EP")
    if range_exp:
        tags.append("STOCKBEE_RE")
    if ema_stack:
        tags.append("STOCKBEE_EMA")
    if anticipation:
        tags.append("STOCKBEE_ANT")

    return {
        "symbol": sym,
        "ready": True,
        "tags": tags,
        "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "range_expansion": range_exp,
        "ema_stack_9_20": ema_stack,
        "anticipation": anticipation,
        "ema9": round(e9, 2) if e9 else None,
        "ema20": round(e20, 2) if e20 else None,
    }
