"""
portfolio.py — Fast watchlist / PM-desk snapshots for technical analysis.
"""

from __future__ import annotations

from datetime import date, timedelta

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


def _bar_date(row) -> str:
    raw = row.get("date") if isinstance(row, dict) else row
    return str(raw)[:10]


SPY_RS_NOTE = "close/SPY close comparison line, not a published rating"


def spy_rs_overlay(symbol_rows: list | None, spy_rows: list | None) -> dict:
    """Daily close/SPY close comparison, rebased onto the last symbol close.

    Overlay value at t = close_t * (SPY_last / SPY_t). The line ends at the
    last print so it sits on the price pane as a comparison, not a rating.
    """
    spy_close: dict[str, float] = {}
    for row in spy_rows or []:
        if not isinstance(row, dict):
            continue
        day = _bar_date(row)
        try:
            px = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if day and px > 0:
            spy_close[day] = px

    aligned: list[tuple[str, float, float]] = []
    for row in symbol_rows or []:
        if not isinstance(row, dict):
            continue
        day = _bar_date(row)
        spy_px = spy_close.get(day)
        if not day or not spy_px:
            continue
        try:
            px = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        aligned.append((day, px, px / spy_px))

    if not aligned:
        return {
            "ready": False,
            "benchmark": "SPY",
            "basis": "close_ratio",
            "rebase": "last_close",
            "note": SPY_RS_NOTE,
            "points": [],
            "last_ratio": None,
            "n": 0,
        }

    last_close = aligned[-1][1]
    last_ratio = aligned[-1][2]
    scale = last_close / last_ratio if last_ratio else 0.0
    points = [
        {
            "date": day,
            "ratio": round(ratio, 6),
            "value": round(ratio * scale, 4),
        }
        for day, _px, ratio in aligned
    ]
    return {
        "ready": True,
        "benchmark": "SPY",
        "basis": "close_ratio",
        "rebase": "last_close",
        "note": SPY_RS_NOTE,
        "points": points,
        "last_ratio": round(last_ratio, 6),
        "n": len(points),
    }


def spy_rs_weekly_from_daily_points(
    daily_points: list | None, weekly_rows: list | None
) -> dict:
    """Weekly close/SPY comparison from the same daily overlay series.

    For each W-FRI weekly bar, take the last daily overlay ratio whose date
    falls in that week (week-ending date back 6 calendar days). Rebase onto
    the last weekly print so the line sits on weekly candles. Missing weeks
    are skipped; if nothing aligns, ready=False so the weekly line can stay
    off while the daily overlay still works.
    """
    empty = {
        "ready": False,
        "benchmark": "SPY",
        "basis": "close_ratio",
        "rebase": "last_close",
        "freq": "weekly",
        "note": SPY_RS_NOTE,
        "points": [],
        "last_ratio": None,
        "n": 0,
    }

    daily: list[tuple[str, float]] = []
    for point in daily_points or []:
        if not isinstance(point, dict):
            continue
        day = str(point.get("date") or "")[:10]
        try:
            ratio = float(point.get("ratio"))
        except (TypeError, ValueError):
            continue
        if day and ratio > 0:
            daily.append((day, ratio))
    daily.sort(key=lambda item: item[0])

    weeks: list[tuple[str, float]] = []
    for row in weekly_rows or []:
        if not isinstance(row, dict):
            continue
        day = _bar_date(row)
        try:
            px = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if day and px > 0:
            weeks.append((day, px))

    if not daily or not weeks:
        return empty

    aligned: list[tuple[str, float, float]] = []
    for week_date, week_close in weeks:
        try:
            week_end = date.fromisoformat(week_date)
        except ValueError:
            continue
        week_start = (week_end - timedelta(days=6)).isoformat()
        hit_ratio = None
        for day, ratio in daily:
            if day < week_start:
                continue
            if day > week_date:
                break
            hit_ratio = ratio
        if hit_ratio is None:
            continue
        aligned.append((week_date, week_close, hit_ratio))

    if not aligned:
        return empty

    last_close = aligned[-1][1]
    last_ratio = aligned[-1][2]
    scale = last_close / last_ratio if last_ratio else 0.0
    points = [
        {
            "date": day,
            "ratio": round(ratio, 6),
            "value": round(ratio * scale, 4),
        }
        for day, _px, ratio in aligned
    ]
    return {
        "ready": True,
        "benchmark": "SPY",
        "basis": "close_ratio",
        "rebase": "last_close",
        "freq": "weekly",
        "note": SPY_RS_NOTE,
        "points": points,
        "last_ratio": round(last_ratio, 6),
        "n": len(points),
    }


def linked_ohlc_bar(
    source_freq: str,
    date_key: str,
    daily_rows: list | None,
    weekly_rows: list | None,
) -> dict | None:
    """Match a hovered daily date to its W-FRI weekly bar (and vice versa).

    Daily → first weekly bar with date >= daily (the covering Friday bar).
    Weekly → last daily bar with date <= weekly (that week's last print).
    Chart range sync is separate; this is bar readout only.
    """
    key = str(date_key or "")[:10]
    if not key:
        return None
    freq = (source_freq or "").lower()
    if freq == "daily":
        rows = weekly_rows or []
        for row in rows:
            if _bar_date(row) >= key:
                return row
        return rows[-1] if rows else None
    found = None
    for row in daily_rows or []:
        if _bar_date(row) <= key:
            found = row
        else:
            break
    return found


ADR_LOOKBACK = 20
ADR_MIN_BARS = 5
LEGEND_MINUS = "\u2212"


def _adr_bar_range_pct(row) -> float | None:
    if not isinstance(row, dict):
        return None
    try:
        high = float(row.get("high"))
        low = float(row.get("low"))
        close = float(row.get("close"))
    except (TypeError, ValueError):
        return None
    if high > 0 and low > 0 and close > 0:
        return ((high - low) / close) * 100
    return None


def legend_adr_pct(
    rows: list | None,
    lookback: int = ADR_LOOKBACK,
    min_bars: int = ADR_MIN_BARS,
) -> float | None:
    """Mean of ((high-low)/close)*100 over the last `lookback` daily bars
    that have high, low, close > 0. Omit if fewer than `min_bars` such bars.

    Stock statistic from the latest daily series — not the hovered window.
    """
    ranges: list[float] = []
    for row in reversed(rows or []):
        pct = _adr_bar_range_pct(row)
        if pct is None:
            continue
        ranges.append(pct)
        if len(ranges) >= lookback:
            break
    if len(ranges) < min_bars:
        return None
    return sum(ranges) / len(ranges)


def legend_sma200_dist_pct(close, sma200) -> float | None:
    """(close / sma200 - 1) * 100. Omit if either is missing or not > 0."""
    try:
        c = float(close)
        s = float(sma200)
    except (TypeError, ValueError):
        return None
    if c > 0 and s > 0:
        return (c / s - 1) * 100
    return None


def format_legend_adr(adr) -> str:
    if adr is None:
        return ""
    try:
        n = float(adr)
    except (TypeError, ValueError):
        return ""
    if n != n:  # NaN
        return ""
    return f"ADR {n:.2f}%"


def format_legend_sma200_dist(pct) -> str:
    if pct is None:
        return ""
    try:
        n = float(pct)
    except (TypeError, ValueError):
        return ""
    if n != n:
        return ""
    sign = "+" if n >= 0 else LEGEND_MINUS
    return f"200 {sign}{abs(n):.1f}%"


def legend_stat_text_bits(
    freq: str,
    *,
    close=None,
    sma200=None,
    daily_rows: list | None = None,
) -> list[str]:
    """Plain legend bits. ADR is daily-only; SMA200 distance follows the hovered bar."""
    bits: list[str] = []
    if (freq or "").lower() == "daily":
        adr_txt = format_legend_adr(legend_adr_pct(daily_rows))
        if adr_txt:
            bits.append(adr_txt)
    dist_txt = format_legend_sma200_dist(legend_sma200_dist_pct(close, sma200))
    if dist_txt:
        bits.append(dist_txt)
    return bits


def position_size(
    price,
    atr,
    risk_dollars: float = 100.0,
    atr_mult: float = 1.5,
    *,
    stop_price: float | None = None,
) -> dict:
    """Shares such that stop distance ≈ risk_dollars.

    Prefer a user/structural stop (`stop_price`). Fall back to atr_mult×ATR
    when no stop is provided (Brandt / Neumann risk box).
    """
    if not price or risk_dollars <= 0:
        return {
            "shares": None,
            "risk_dollars": risk_dollars,
            "stop_distance": None,
            "notional": None,
            "stop_source": None,
        }
    stop_source = "atr"
    if stop_price is not None and float(stop_price) > 0:
        stop_distance = abs(float(price) - float(stop_price))
        stop_source = "user_stop"
    elif atr and atr > 0:
        stop_distance = float(atr) * atr_mult
        stop_source = "atr"
    else:
        return {
            "shares": None,
            "risk_dollars": risk_dollars,
            "stop_distance": None,
            "notional": None,
            "stop_source": None,
        }
    shares = int(risk_dollars // stop_distance) if stop_distance > 0 else 0
    return {
        "shares": shares,
        "risk_dollars": risk_dollars,
        "stop_distance": round(stop_distance, 2),
        "notional": round(shares * float(price), 2) if shares else 0.0,
        "stop_source": stop_source,
    }


def darvas_box(df: pd.DataFrame, lookback: int = 20, confirm: int = 3) -> dict | None:
    """Detect a simple Darvas-style consolidation box on OHLCV.

    Box top = rolling N-bar high that held for `confirm` bars without a new high.
    Box low = lowest low during that hold window. State is in_box / breakout / failed.
    Never conflated with KAMA/RSI (see METHODOLOGY_REVIEW.md).
    """
    if df is None or df.empty or len(df) < lookback + confirm + 2:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    # Find last bar where a lookback-high held for `confirm` bars
    roll_hi = high.rolling(lookback).max()
    box_top = None
    box_low = None
    since_idx = None
    for i in range(len(df) - confirm - 1, lookback - 1, -1):
        top = float(roll_hi.iloc[i])
        if pd.isna(top):
            continue
        window = high.iloc[i + 1 : i + 1 + confirm]
        if len(window) < confirm:
            continue
        if float(window.max()) <= top + 1e-9:
            # Confirmed: no new high for `confirm` bars after the pivot
            hold = df.iloc[max(0, i - lookback + 1) : i + 1 + confirm]
            box_top = top
            box_low = float(hold["low"].astype(float).min())
            since_idx = i - lookback + 1
            break
    if box_top is None or box_low is None or box_top <= box_low:
        return None
    last = float(close.iloc[-1])
    if last > box_top:
        state = "breakout"
    elif last < box_low:
        state = "failed"
    else:
        state = "in_box"
    since = None
    try:
        since = str(df.index[max(0, since_idx)].date()) if since_idx is not None else None
    except Exception:
        since = None
    height = box_top - box_low
    return {
        "top": round(box_top, 2),
        "bottom": round(box_low, 2),
        "height": round(height, 2),
        "state": state,
        "since": since,
        "target": round(box_top + height, 2),  # 1× measured move
        "pct_to_top": round((last / box_top - 1.0) * 100, 2) if box_top else None,
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
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    chg = last - prev
    chg_pct = (chg / prev * 100) if prev else 0.0

    # ── Momentum / breakout metrics (Qullamaggie loop) ──────────────
    # Distance from N-day high, 0 = sitting at the high (near-high queue).
    def _dist_from_high(n: int):
        window = high.tail(min(n, len(high)))
        hi = float(window.max()) if len(window) else None
        return round((last / hi - 1.0) * 100, 2) if hi else None

    dist_20d_high = _dist_from_high(20)
    dist_63d_high = _dist_from_high(63)

    # Volume surge: today's bar vs 20-bar average volume.
    vol_avg20 = float(volume.tail(21).iloc[:-1].mean()) if len(volume) > 21 else (
        float(volume.iloc[:-1].mean()) if len(volume) > 1 else None
    )
    vol_today = float(volume.iloc[-1])
    vol_ratio = round(vol_today / vol_avg20, 2) if vol_avg20 and vol_avg20 > 0 else None

    # Gap %: today's open vs prior close — episodic-pivot (EP) path.
    today_open = float(open_.iloc[-1])
    gap_pct = round((today_open / prev - 1.0) * 100, 2) if prev else None

    is_near_high = dist_20d_high is not None and dist_20d_high >= -5.0
    is_vol_surge = vol_ratio is not None and vol_ratio >= 1.5
    is_ep = (
        gap_pct is not None and vol_ratio is not None
        and gap_pct >= 4.0 and vol_ratio >= 1.5
    )
    breakout_score = (
        (1 if is_near_high else 0)
        + (1 if is_vol_surge else 0)
        + (1 if is_ep else 0)
    )

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
        # Momentum / breakout (Qullamaggie loop) — near-high, volume surge, EP/gap
        "dist_20d_high_pct": dist_20d_high,
        "dist_63d_high_pct": dist_63d_high,
        "vol_ratio_5_20": vol_ratio,
        "gap_pct": gap_pct,
        "is_near_high": is_near_high,
        "is_vol_surge": is_vol_surge,
        "is_ep": is_ep,
        "breakout_score": breakout_score,
        "darvas": darvas_box(df),
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

    # Watchlist-relative 21D return rank (1 = strongest in this book).
    # Book RS only — not a published rating.
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

    # Breakout queue: near-high + volume-confirmed names (Qullamaggie loop),
    # NOT an RSI OS/weak-RS list. Ranked by breakout_score, then closest to high.
    breakout_queue = sorted(
        (r for r in ready if r.get("is_near_high") or r.get("is_vol_surge")),
        key=lambda r: (
            -(r.get("breakout_score") or 0),
            -(r.get("dist_20d_high_pct") if r.get("dist_20d_high_pct") is not None else -999),
        ),
    )[:12]

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

    # Book news defaults to STRONG names — breakout queue + top RS — not
    # RSI OS/weak-RS. See METHODOLOGY_REVIEW.md must-not-do #3.
    strong_focus = [r["symbol"] for r in breakout_queue[:3]]
    strong_focus += [r["symbol"] for r in ranked[:3]]
    focus_news = list(dict.fromkeys(strong_focus))

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
        "breakout_queue": breakout_queue,
        "rs_basis": "watchlist_21d",
        "rs_note": "Book RS is this watchlist's 21D return rank, not a published rating",
    }
