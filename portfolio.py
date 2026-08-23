"""
portfolio.py — Fast watchlist / PM-desk snapshots for technical analysis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import market_data as md

# Liquid peer ETFs by sector (Yahoo sector strings)
_PEER_ETF = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Health Care": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Discretionary": "XLY",
    "Consumer Defensive": "XLP",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


def peer_etf_for(sector: str | None) -> str:
    if not sector:
        return "SPY"
    return _PEER_ETF.get(str(sector).strip(), "SPY")


def position_size(price, atr, risk_dollars: float = 100.0, atr_mult: float = 1.5) -> dict:
    """Shares such that atr_mult×ATR move ≈ risk_dollars."""
    if not price or not atr or atr <= 0 or risk_dollars <= 0:
        return {"shares": None, "risk_dollars": risk_dollars, "stop_distance": None, "notional": None}
    stop_distance = float(atr) * atr_mult
    shares = int(risk_dollars // stop_distance) if stop_distance else 0
    return {
        "shares": shares,
        "risk_dollars": risk_dollars,
        "stop_distance": round(stop_distance, 2),
        "notional": round(shares * float(price), 2) if shares else 0.0,
    }


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
    df = md.get_ohlcv_df(sym, "daily", limit=260)
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

    # Weekly regime (same KAMA20 logic on weekly bars)
    w_df = md.get_ohlcv_df(sym, "weekly", limit=80)
    regime_w = "n/a"
    vs_kama_w = None
    if not w_df.empty and len(w_df) >= 25:
        w_close = w_df["close"].astype(float)
        w_last = float(w_close.iloc[-1])
        w_kama = _last_valid(_kama(w_close, 20))
        if w_kama and w_kama > 0:
            vs_kama_w = (w_last / w_kama - 1.0) * 100
            if vs_kama_w >= 1.0:
                regime_w = "uptrend"
            elif vs_kama_w <= -1.0:
                regime_w = "downtrend"
            else:
                regime_w = "range"

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
        "regime_weekly": regime_w,
        "vs_kama20_weekly_pct": round(vs_kama_w, 2) if vs_kama_w is not None else None,
        "atr14": round(atr14, 2) if atr14 is not None else None,
        "atr_pct": round(atr_pct, 2) if atr_pct is not None else None,
        "stop_long_1_5atr": stop_long,
        "stop_short_1_5atr": stop_short,
        # last ~30 daily closes for correlation (compact)
        "closes_30": [round(float(x), 4) for x in close.tail(30).tolist()],
    }


def _corr_hint(ready: list) -> dict | None:
    """Pearson corr of daily returns for the two names with most complete closes_30."""
    usable = [r for r in ready if len(r.get("closes_30") or []) >= 20]
    if len(usable) < 2:
        return None
    a, b = usable[0], usable[1]
    ca = np.array(a["closes_30"], dtype=float)
    cb = np.array(b["closes_30"], dtype=float)
    n = min(len(ca), len(cb))
    ra = np.diff(np.log(ca[-n:]))
    rb = np.diff(np.log(cb[-n:]))
    if len(ra) < 10 or np.std(ra) == 0 or np.std(rb) == 0:
        return None
    corr = float(np.corrcoef(ra, rb)[0, 1])
    return {
        "pair": [a["symbol"], b["symbol"]],
        "corr_30d": round(corr, 2),
        "note": "high" if abs(corr) >= 0.7 else ("mod" if abs(corr) >= 0.4 else "low"),
    }


def portfolio_snapshot() -> dict:
    symbols_meta = {s["symbol"]: s for s in md.list_symbols()}
    symbols = list(symbols_meta.keys())
    rows = [snapshot_symbol(sym) for sym in symbols]
    ready = [r for r in rows if r.get("ready")]

    # Attach group tags for rollups
    for row in rows:
        meta = symbols_meta.get(row["symbol"], {})
        row["group_tag"] = (meta.get("group_tag") or "").strip()
        row["sector"] = meta.get("sector") or ""
        row["peer_etf"] = peer_etf_for(row["sector"])
        if row.get("ready"):
            row["size_risk_100"] = position_size(row.get("price"), row.get("atr14"), 100.0, 1.5)

    # Relative strength rank by 21D return (1 = strongest)
    ranked = sorted(
        ready,
        key=lambda r: (r.get("ret_21d_pct") is not None, r.get("ret_21d_pct") or -1e9),
        reverse=True,
    )
    for i, row in enumerate(ranked, start=1):
        row["rs_rank_21d"] = i
        row["rs_n"] = len(ranked)

    # Alert flags for swing PMs
    alerts = []
    for row in rows:
        zone = row.get("rsi_zone")
        row["alert"] = None
        if zone == "overbought":
            row["alert"] = "RSI_OB"
            alerts.append(row["symbol"])
        elif zone == "oversold":
            row["alert"] = "RSI_OS"
            alerts.append(row["symbol"])

    by_day = sorted(ready, key=lambda r: r.get("change_pct") or 0, reverse=True)

    # Group rollup: avg day % by group_tag
    groups = {}
    for row in ready:
        g = row.get("group_tag") or "Ungrouped"
        groups.setdefault(g, []).append(row.get("change_pct") or 0)
    group_rollup = [
        {"group": g, "n": len(vals), "avg_change_pct": round(sum(vals) / len(vals), 2)}
        for g, vals in groups.items()
    ]
    group_rollup.sort(key=lambda x: x["avg_change_pct"], reverse=True)

    # Strip bulky series from API payload after corr
    corr = _corr_hint(ready)
    for row in rows:
        row.pop("closes_30", None)

    weak = ranked[-1] if ranked else None
    focus_news = list(dict.fromkeys(
        alerts + ([weak["symbol"]] if weak else [])
    ))

    # Regime heatmap rows for PM-A
    heatmap = [
        {
            "symbol": r["symbol"],
            "regime": r.get("regime"),
            "regime_weekly": r.get("regime_weekly"),
            "alert": r.get("alert"),
            "rs_rank_21d": r.get("rs_rank_21d"),
            "change_pct": r.get("change_pct"),
        }
        for r in sorted(ready, key=lambda x: x["symbol"])
    ]

    return {
        "count": len(symbols),
        "ready_count": len(ready),
        "symbols": rows,
        "tape": by_day,
        "alerts": alerts,
        "heatmap": heatmap,
        "top_gainer": by_day[0] if by_day else None,
        "top_loser": by_day[-1] if by_day else None,
        "strongest_rs": ranked[0] if ranked else None,
        "weakest_rs": weak,
        "correlation": corr,
        "group_rollup": group_rollup,
        "news_focus": focus_news,
    }
