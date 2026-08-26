"""
portfolio.py — Fast watchlist / PM-desk snapshots for technical analysis.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

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


def snapshot_symbol(
    symbol: str,
    light: bool = False,
    include_scanner: bool = False,
    df=None,
    weekly_df=None,
) -> dict:
    sym = symbol.upper()
    if df is None:
        df = md.get_ohlcv_df(sym, "daily", limit=260)
    if df is None or df.empty or len(df) < 25:
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
    # Distance from the *prior* N-day high (excludes today) so a breakout
    # can print positive. pct_off_Nd_high keeps "how far under today's ceiling."
    def _dist_from_prior_high(n: int):
        if len(high) < 2:
            return None
        prior = high.iloc[:-1]
        window = prior.tail(min(n, len(prior)))
        if window.empty:
            return None
        hi = float(window.max())
        return round((last / hi - 1.0) * 100, 2) if hi else None

    def _pct_off_high(n: int):
        window = high.tail(min(n, len(high)))
        hi = float(window.max()) if len(window) else None
        return round((last / hi - 1.0) * 100, 2) if hi else None

    dist_20d_high = _dist_from_prior_high(20)
    dist_63d_high = _dist_from_prior_high(63)
    pct_off_20d_high = _pct_off_high(20)

    # Volume surge: today's bar vs 20-bar average volume.
    vol_avg20 = float(volume.tail(21).iloc[:-1].mean()) if len(volume) > 21 else (
        float(volume.iloc[:-1].mean()) if len(volume) > 1 else None
    )
    vol_today = float(volume.iloc[-1])
    vol_ratio = round(vol_today / vol_avg20, 2) if vol_avg20 and vol_avg20 > 0 else None
    dollar_vol_20d = None
    if len(close) >= 5:
        dv = (close * volume).tail(min(20, len(close)))
        dollar_vol_20d = round(float(dv.mean()), 0) if len(dv) else None

    # Gap %: today's open vs prior close — episodic-pivot (EP) path.
    today_open = float(open_.iloc[-1])
    gap_pct = round((today_open / prev - 1.0) * 100, 2) if prev else None

    is_near_high = pct_off_20d_high is not None and pct_off_20d_high >= -5.0
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

    as_of = None
    try:
        as_of = pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")
    except Exception:
        as_of = str(df.index[-1])[:10] if len(df) else None

    regime_w = "n/a"
    vs_kama_w = None
    if not light:
        w_df = weekly_df if weekly_df is not None else md.get_ohlcv_df(sym, "weekly", limit=80)
        if w_df is not None and not w_df.empty and len(w_df) >= 25:
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

    darvas = darvas_box(df) if not light else None

    row = {
        "symbol": sym,
        "ready": True,
        "as_of": as_of,
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
        "dist_20d_high_pct": dist_20d_high,
        "dist_63d_high_pct": dist_63d_high,
        "pct_off_20d_high_pct": pct_off_20d_high,
        "vol_ratio_5_20": vol_ratio,
        "dollar_vol_20d": dollar_vol_20d,
        "gap_pct": gap_pct,
        "is_near_high": is_near_high,
        "is_vol_surge": is_vol_surge,
        "is_ep": is_ep,
        "breakout_score": breakout_score,
        "darvas": darvas,
    }

    if not light:
        row["closes_30"] = [round(float(x), 4) for x in close.tail(30).tolist()]

    if include_scanner and len(df) >= 22:
        try:
            import scanner as scan_mod
            tf = scan_mod._compute_tf(df, 252)
            if tf:
                for key, val in tf.items():
                    row[f"d_{key}"] = val
        except Exception:
            pass

    return row


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


def portfolio_snapshot(
    scope: str = "all",
    light: bool = False,
    symbols: list[str] | None = None,
    max_workers: int = 8,
    use_cache: bool = True,
) -> dict:
    symbols_meta = {s["symbol"]: s for s in md.list_symbols()}

    if symbols:
        sym_list = [s.upper() for s in symbols]
    elif scope == "desk":
        sym_list = [s["symbol"] for s in md.list_desk_symbols()]
    elif scope == "with_data":
        sym_list = md.list_symbols_with_ohlcv("daily", min_bars=30)
    else:
        sym_list = list(symbols_meta.keys())

    from_cache = False
    rows: list[dict] = []

    # Fast path: precomputed metrics (desk tape / light views)
    if use_cache and light:
        try:
            import desk_metrics
            cached = desk_metrics.load_cached_rows(sym_list, ready_only=False)
            if cached and len(cached) >= max(1, int(0.4 * len(sym_list))):
                by_sym = {r["symbol"]: r for r in cached if r.get("symbol")}
                for sym in sym_list:
                    if sym in by_sym:
                        rows.append(dict(by_sym[sym]))
                    else:
                        rows.append({"symbol": sym, "ready": False, "error": "metrics miss"})
                from_cache = True
        except Exception:
            rows = []
            from_cache = False

    if not from_cache:
        include_scanner = not light

        def _snap(sym: str) -> dict:
            return snapshot_symbol(sym, light=light, include_scanner=include_scanner)

        workers = min(max_workers, max(1, len(sym_list)))
        if workers <= 1 or len(sym_list) <= 3:
            rows = [_snap(sym) for sym in sym_list]
        else:
            rows = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_snap, sym): sym for sym in sym_list}
                for fut in as_completed(futures):
                    rows.append(fut.result())
            rows.sort(key=lambda r: r.get("symbol") or "")

    ready = [r for r in rows if r.get("ready")]

    # Attach group tags for rollups
    for row in rows:
        meta = symbols_meta.get(row["symbol"], {})
        row["group_tag"] = (meta.get("group_tag") or row.get("group_tag") or "").strip()
        row["sector"] = meta.get("sector") or row.get("sector") or ""
        row["peer_etf"] = peer_etf_for(row["sector"])
        if row.get("ready") and row.get("size_risk_100") is None:
            row["size_risk_100"] = position_size(row.get("price"), row.get("atr14"), 100.0, 1.5)

    # Relative strength rank by 21D return (1 = strongest) — skip if cache already ranked
    ranked = sorted(
        ready,
        key=lambda r: (r.get("ret_21d_pct") is not None, r.get("ret_21d_pct") or -1e9),
        reverse=True,
    )
    if not from_cache or any(r.get("rs_rank_21d") is None for r in ready):
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
        "count": len(sym_list),
        "ready_count": len(ready),
        "scope": scope,
        "light": light,
        "from_cache": from_cache,
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
    }
