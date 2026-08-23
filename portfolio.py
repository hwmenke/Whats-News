"""
portfolio.py — Fast watchlist / PM-desk snapshots for technical analysis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import database as db


def _last_valid(series: pd.Series):
    s = series.dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def _kama(close: pd.Series, window: int = 20, fast: int = 2, slow: int = 30) -> pd.Series:
    """Lightweight KAMA for snapshot metrics (not chart-quality)."""
    change = (close - close.shift(window)).abs()
    volatility = close.diff().abs().rolling(window).sum()
    er = change / volatility.replace(0, np.nan)
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    out = pd.Series(index=close.index, dtype=float)
    if len(close) < window + 1:
        return out
    out.iloc[window] = close.iloc[window]
    for i in range(window + 1, len(close)):
        prev = out.iloc[i - 1]
        if pd.isna(prev):
            prev = close.iloc[i - 1]
        c = sc.iloc[i]
        if pd.isna(c):
            out.iloc[i] = prev
        else:
            out.iloc[i] = prev + c * (close.iloc[i] - prev)
    return out


def _rsi_zone(rsi: float | None) -> str:
    if rsi is None:
        return "n/a"
    if rsi >= 70:
        return "overbought"
    if rsi <= 30:
        return "oversold"
    if rsi >= 55:
        return "bullish"
    if rsi <= 45:
        return "bearish"
    return "neutral"


def snapshot_symbol(symbol: str) -> dict:
    sym = symbol.upper()
    df = db.get_ohlcv_df(sym, "daily", limit=260)
    if df.empty or len(df) < 25:
        return {
            "symbol": sym,
            "ready": False,
            "error": "No data — fetch first",
        }

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    chg = last - prev
    chg_pct = (chg / prev * 100) if prev else 0.0

    rsi14 = _last_valid(_rsi(close, 14))
    kama20 = _last_valid(_kama(close, 20))
    atr14 = _last_valid(_atr(high, low, close, 14))

    vs_kama = None
    regime = "n/a"
    if kama20 and kama20 > 0:
        vs_kama = (last / kama20 - 1.0) * 100
        if vs_kama >= 1.0:
            regime = "uptrend"
        elif vs_kama <= -1.0:
            regime = "downtrend"
        else:
            regime = "range"

    atr_pct = (atr14 / last * 100) if atr14 and last else None
    stop_long = round(last - 1.5 * atr14, 2) if atr14 else None
    stop_short = round(last + 1.5 * atr14, 2) if atr14 else None

    week_ago = close.iloc[-6] if len(close) >= 6 else close.iloc[0]
    month_ago = close.iloc[-22] if len(close) >= 22 else close.iloc[0]
    ret_5d = (last / float(week_ago) - 1) * 100 if week_ago else None
    ret_21d = (last / float(month_ago) - 1) * 100 if month_ago else None

    return {
        "symbol": sym,
        "ready": True,
        "price": round(last, 2),
        "change": round(chg, 2),
        "change_pct": round(chg_pct, 2),
        "ret_5d_pct": round(ret_5d, 2) if ret_5d is not None else None,
        "ret_21d_pct": round(ret_21d, 2) if ret_21d is not None else None,
        "rsi14": round(rsi14, 1) if rsi14 is not None else None,
        "rsi_zone": _rsi_zone(rsi14),
        "kama20": round(kama20, 2) if kama20 is not None else None,
        "vs_kama20_pct": round(vs_kama, 2) if vs_kama is not None else None,
        "regime": regime,
        "atr14": round(atr14, 2) if atr14 is not None else None,
        "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
        "stop_long_1_5atr": stop_long,
        "stop_short_1_5atr": stop_short,
    }


def portfolio_snapshot() -> dict:
    symbols = [s["symbol"] for s in db.list_symbols()]
    rows = [snapshot_symbol(sym) for sym in symbols]
    ready = [r for r in rows if r.get("ready")]
    gainers = sorted(ready, key=lambda r: r.get("change_pct") or 0, reverse=True)
    return {
        "count": len(symbols),
        "ready_count": len(ready),
        "symbols": rows,
        "top_gainer": gainers[0] if gainers else None,
        "top_loser": gainers[-1] if gainers else None,
    }
