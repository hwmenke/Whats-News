"""Macro / Edges boards from stored Yahoo OHLCV.

No invented prices, z-scores, VIX, or win rates. Missing bars stay dark.
Fractal D is not computed here — this repo has no Hurst / D65 estimator.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

import market_data as md
import portfolio
import setup_scanner
import ticker_lists as tl


VIX_CANDIDATES = ("^VIX", "VIX")
FRACTAL_NOTE = (
    "No fractal / Hurst / D65 estimator in this repo. "
    "Will not invent D estimates."
)


def _safe_float(val):
    if val is None:
        return None
    try:
        if isinstance(val, (float, np.floating)) and (math.isnan(val) or math.isinf(val)):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _round(val, digits):
    num = _safe_float(val)
    if num is None:
        return None
    return round(num, digits)


def move_stats(close: pd.Series) -> dict:
    """Day % plus z from stored daily closes. Omit z when the window is too short."""
    if close is None or len(close) < 2:
        return {"ready": False}
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    day_pct = ((last / prev) - 1.0) * 100.0 if prev else None
    rets = close.pct_change().dropna()

    z30 = None
    if len(rets) >= 10:
        window = rets.tail(30)
        sigma = float(window.std(ddof=0))
        last_ret = float(rets.iloc[-1])
        if sigma > 0:
            z30 = last_ret / sigma

    z14 = None
    if len(close) >= 15 and len(rets) >= 10:
        ret14 = (last / float(close.iloc[-15])) - 1.0
        sigma14 = float(rets.tail(14).std(ddof=0))
        if sigma14 > 0:
            z14 = ret14 / (sigma14 * math.sqrt(14.0))

    return {
        "ready": True,
        "px": _round(last, 2),
        "day_pct": _round(day_pct, 2),
        "z30": _round(z30, 2),
        "z14": _round(z14, 2),
        "extreme": z30 is not None and abs(z30) >= 2.0,
        "bars": int(len(close)),
    }


def _daily_close(symbol: str, limit: int = 260) -> pd.Series:
    df = md.get_ohlcv_df(symbol, "daily", limit=limit)
    if df is None or df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)
    return df["close"].astype(float)


def _weekly_close(symbol: str, daily: pd.DataFrame | None = None) -> pd.Series:
    weekly = md.get_ohlcv_df(symbol, "weekly", limit=80)
    if weekly is not None and not weekly.empty and len(weekly) >= 16:
        return weekly["close"].astype(float)
    if daily is None or daily.empty:
        daily = md.get_ohlcv_df(symbol, "daily", limit=400)
    if daily is None or daily.empty:
        return pd.Series(dtype=float)
    work = daily.copy()
    if "close" not in work.columns:
        return pd.Series(dtype=float)
    if not isinstance(work.index, pd.DatetimeIndex):
        if "date" in work.columns:
            work["date"] = pd.to_datetime(work["date"])
            work = work.set_index("date")
        else:
            return pd.Series(dtype=float)
    resampled = work.resample("W-FRI").agg({"close": "last"}).dropna()
    if resampled.empty:
        return pd.Series(dtype=float)
    return resampled["close"].astype(float)


def sleeve_row(symbol: str) -> dict:
    close = _daily_close(symbol)
    stats = move_stats(close)
    return {"symbol": symbol.upper(), **stats}


def vix_regime() -> dict:
    """Quiet / storm from stored ^VIX or VIX. Omit entirely when no bars."""
    for sym in VIX_CANDIDATES:
        df = md.get_ohlcv_df(sym, "daily", limit=260)
        if df is None or df.empty or len(df) < 20:
            continue
        close = df["close"].astype(float)
        last = float(close.iloc[-1])
        window = close.tail(min(252, len(close)))
        pct = float((window < last).sum() / max(len(window), 1) * 100.0)
        if last < 16:
            label = "QUIET"
        elif last >= 25:
            label = "STORM"
        else:
            label = "NORMAL"
        return {
            "ready": True,
            "symbol": sym,
            "vix": _round(last, 1),
            "percentile_1y": round(pct),
            "label": label,
            "note": "From stored Yahoo bars — omitted if no VIX history.",
        }
    return {
        "ready": False,
        "note": "No stored ^VIX/VIX bars — regime line omitted (not invented).",
    }


def empty_macro_board() -> dict:
    return {
        "regime": {"ready": False, "note": "No stored bars yet."},
        "sleeves": [],
        "note": "Yahoo / SQLite only. Cards light up after Fetch.",
    }


def build_macro_board() -> dict:
    sleeves = []
    for spec in tl.sleeves():
        rows = [sleeve_row(t) for t in spec.get("tickers") or []]
        lit = sum(1 for r in rows if r.get("ready"))
        sleeves.append({
            "id": spec["id"],
            "label": spec["label"],
            "group_tag": spec.get("group_tag") or "",
            "filter_kind": spec.get("filter_kind") or "",
            "blurb": spec.get("blurb") or "",
            "skipped": spec.get("skipped") or "",
            "tickers": list(spec.get("tickers") or []),
            "ready_count": lit,
            "rows": rows,
        })
    return {
        "regime": vix_regime(),
        "sleeves": sleeves,
        "note": (
            "Day % and z from stored daily closes (30d / 14d sigma). "
            "|z|≥2 is marked. Empty cells have no bars — not a fake print."
        ),
    }


def _rsi_last(close: pd.Series, window: int = 14):
    """Wilder RSI; a strict grind (no losses) is 100, not a missing print."""
    val = portfolio._last_valid(portfolio._rsi(close, window))
    if val is not None:
        return val
    if close is None or len(close) < window + 1:
        return None
    delta = close.diff().dropna()
    if delta.empty:
        return None
    if float((delta < 0).sum()) == 0:
        return 100.0
    if float((delta > 0).sum()) == 0:
        return 0.0
    return None


def _sma(close: pd.Series, window: int):
    if close is None or len(close) < window:
        return None
    return float(close.tail(window).mean())


def _slope200(close: pd.Series):
    if close is None or len(close) < 205:
        return None
    now = float(close.tail(200).mean())
    prev = float(close.iloc[-205:-5].mean())
    if prev <= 0:
        return None
    if now > prev * 1.0005:
        return "up"
    if now < prev * 0.9995:
        return "down"
    return "flat"


def _edge_tags(snap: dict, rsi14, vs200) -> list:
    tags = []
    if snap.get("is_ep"):
        tags.append("EP")
    if snap.get("is_vol_surge"):
        tags.append("VOL_SURGE")
    if snap.get("is_near_high"):
        tags.append("NEAR_HIGH")
    if snap.get("is_near_high") and (snap.get("is_vol_surge") or (snap.get("breakout_score") or 0) >= 2):
        tags.append("BREAKOUT_QUEUE")
    regime = snap.get("regime")
    if regime == "uptrend":
        tags.append("REGIME_UP")
    elif regime == "downtrend":
        tags.append("REGIME_DOWN")
    if rsi14 is not None:
        if rsi14 >= 70:
            tags.append("RSI_OB")
        elif rsi14 <= 30:
            tags.append("RSI_OS")
    if vs200 is not None and vs200 <= -8:
        tags.append("DEEP_VS_200D")
    return tags


def edge_instrument(symbol: str) -> dict:
    sym = symbol.upper()
    daily = md.get_ohlcv_df(sym, "daily", limit=400)
    if daily is None or daily.empty or len(daily) < 15:
        return {
            "symbol": sym,
            "ready": False,
            "tags": [],
        }
    close = daily["close"].astype(float)
    last = float(close.iloc[-1])
    rsi14 = _rsi_last(close, 14)
    weekly = _weekly_close(sym, daily)
    wrsi = _rsi_last(weekly, 14) if len(weekly) >= 16 else None
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)
    vs50 = ((last / sma50) - 1.0) * 100.0 if sma50 else None
    vs200 = ((last / sma200) - 1.0) * 100.0 if sma200 else None
    snap = portfolio.snapshot_symbol(sym)
    tags = _edge_tags(snap if snap.get("ready") else {}, rsi14, vs200)
    high = daily["high"].astype(float) if "high" in daily.columns else close
    if len(high) >= 200:
        hi52 = float(high.tail(min(252, len(high))).max())
        if hi52 > 0 and last >= hi52 * 0.995:
            tags.append("52w HIGH")
    prev = float(close.iloc[-2])
    day_pct = ((last / prev) - 1.0) * 100.0 if prev else None
    return {
        "symbol": sym,
        "ready": True,
        "px": _round(last, 2),
        "day_pct": _round(day_pct, 2),
        "d_rsi14": _round(rsi14, 1),
        "w_rsi14": _round(wrsi, 1),
        "vs50d": _round(vs50, 1),
        "vs200d": _round(vs200, 1),
        "slope200": _slope200(close),
        "regime": snap.get("regime") if snap.get("ready") else None,
        "tags": tags,
    }


def _desk_symbols() -> list[str]:
    out = []
    for row in md.list_symbols():
        tag = (row.get("group_tag") or "")
        if tag.startswith("univ:"):
            continue
        sym = row.get("symbol")
        if sym:
            out.append(str(sym).upper())
    return out


def _setup_buckets() -> dict:
    desk = _desk_symbols()
    if not desk:
        return {
            "EP": [],
            "NEAR_HIGH": [],
            "VOL_SURGE": [],
            "BREAKOUT_QUEUE": [],
            "RSI_OS": [],
        }
    pack = setup_scanner.scan_setups(symbols=desk, limit=400)
    buckets = {
        "EP": [],
        "NEAR_HIGH": [],
        "VOL_SURGE": [],
        "BREAKOUT_QUEUE": [],
        "RSI_OS": [],
    }
    for row in pack.get("results") or []:
        if not row.get("ready"):
            continue
        sym = row.get("symbol")
        for sid in buckets:
            if sid in (row.get("setups") or []):
                buckets[sid].append(sym)
    return buckets


def empty_edges_board() -> dict:
    return {
        "regime": {"ready": False, "note": "No stored bars yet."},
        "online": [],
        "sections": [],
        "setup_buckets": {
            "EP": [],
            "NEAR_HIGH": [],
            "VOL_SURGE": [],
            "BREAKOUT_QUEUE": [],
            "RSI_OS": [],
        },
        "note": "Tags from stored OHLCV + Whats-News scanner. No screenshot win rates.",
    }


def build_edges_board() -> dict:
    sections = []
    online = []
    for sleeve_id, label in (
        ("core", "Core indices"),
        ("sector_etfs", "Sector ETFs"),
        ("intl_etfs", "International ETFs"),
    ):
        spec = tl.get_sleeve(sleeve_id) or {}
        rows = [edge_instrument(t) for t in spec.get("tickers") or []]
        for row in rows:
            for tag in row.get("tags") or []:
                if tag not in online:
                    online.append(tag)
        sections.append({
            "id": sleeve_id,
            "label": label,
            "rows": rows,
        })
    return {
        "regime": vix_regime(),
        "online": online,
        "sections": sections,
        "setup_buckets": _setup_buckets(),
        "note": (
            "dRSI14 / wRSI14 / vs 50d / vs 200d from stored closes. "
            "Live tags are Whats-News scanner / snapshot flags only — "
            "no hardcoded win-rate percentages."
        ),
    }


def fractal_status() -> dict:
    return {
        "available": False,
        "reason": FRACTAL_NOTE,
    }
