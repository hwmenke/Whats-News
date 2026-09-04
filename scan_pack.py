"""Desk scanner pack — MA / RSI / Breakout + style tags + breadth.

All numbers come from stored Yahoo/SQLite daily OHLCV. No invented prices,
win rates, or scraped Stockbee tables.

Formulas (also exposed on each API payload under ``formulas``):

SMA(n)
    Mean of the last n closes. Omitted if fewer than n bars.
    Rising if SMA_t > SMA_{t-1} (needs n+1 closes).

vs SMA(n)
    (close / SMA(n) − 1) × 100.

STACKED_MA
    close > SMA20 > SMA50 > SMA200 (all three SMAs present).

PULLBACK_RISING_MA
    SMA20 rising and −3.0 ≤ vs20 ≤ +0.5, or the same band vs a rising SMA50.

RSI14
    Wilder EWM, alpha = 1/14 (portfolio._rsi). RSI_OS ≤ 30, RSI_OB ≥ 70.
    RSI_RISING_FROM_OS: previous RSI < 30 and current RSI > previous RSI.

NEAR_52W
    (close / max(high, 252 bars) − 1) × 100 ≥ −5. Omitted if < 60 highs.

NEAR_ND
    Same vs 20-bar high (existing setup_scanner NEAR_HIGH idea).

VOL_SURGE
    today's volume / mean(prior 20 volumes) ≥ 1.5. Today excluded from the mean.

EP
    Gap ≥ 4% (open/prev_close − 1) and VOL_SURGE. Same thresholds as setup_scanner.

QULLA style
    Tag if EP or VOL_SURGE or NEAR_ND. Reuses existing setup flags — not a claimed edge.

O'Neil / CANSLIM-ish
    63-day relative strength vs SPY:
        rs_spy_63d = ((sym_t/sym_{t-63}) / (spy_t/spy_{t-63}) − 1) × 100
    ONEIL_RS if rs_spy_63d > 0. EPS is skipped — no fundamentals feed.
    Label: "price/RS only — no fundamentals feed".

Minervini VCP-ish (honest proxy, not certified VCP)
    range_shrink: (max(high,10)−min(low,10)) / (max(high,50)−min(low,50)) ≤ 0.55
    atr_declining: ATR14_t < ATR14_{t-5} (Wilder ATR, portfolio._atr)
    swing_contract: mean of last 3 swing ranges < mean of prior 3 (2-bar extrema)
    VCP_PROXY if (range_shrink or atr_declining or swing_contract) and (NEAR_ND or NEAR_52W).

Breadth (Stockbee-style *idea* from OUR universe only — never scrape third-party tables)
    % of names with bars above SMA50 / SMA200;
    advance/decline over 1d and 5d (close vs close[t-1] / close[t-5]).
    Empty universe → empty strip (all nulls). No invented participation.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd

import market_data as md
import portfolio

NOTE = (
    "Stored Yahoo/SQLite daily bars only. Style chips are filters/tags on real "
    "metrics — not claimed edges. Breadth is our universe, not a scraped Market Monitor."
)
ONEIL_NOTE = "price/RS only — no fundamentals feed"
VCP_NOTE = "honest proxy, not certified VCP"
BREADTH_NOTE = (
    "Stockbee-style breadth idea from our Yahoo/SQLite universe — never scraped."
)

LENSES = ("all", "ma", "rsi", "breakout", "qulla", "oneil", "vcp")

# Pullback band vs a rising MA (percent).
PULLBACK_LO = -3.0
PULLBACK_HI = 0.5
NEAR_HIGH_PCT = -5.0
VOL_SURGE_X = 1.5
EP_GAP_PCT = 4.0
VCP_RANGE_RATIO = 0.55
RS_BARS = 63
HIGH_52W = 252
HIGH_ND = 20
SMA_WINDOWS = (20, 50, 200)

FORMULAS = {
    "sma": "mean(last n closes); rising if SMA_t > SMA_{t-1}",
    "stacked_ma": "close > SMA20 > SMA50 > SMA200",
    "pullback_rising_ma": f"rising SMA20/50 and vs-MA in [{PULLBACK_LO}, {PULLBACK_HI}]%",
    "rsi14": "Wilder EWM alpha=1/14; OS<=30; OB>=70; rising-from-OS if prev<30 and rsi>prev",
    "near_52w": f"(close/max(high,252)-1)*100 >= {NEAR_HIGH_PCT}; omit if <60 highs",
    "near_nd": f"(close/max(high,20)-1)*100 >= {NEAR_HIGH_PCT}",
    "vol_surge": f"today_vol / mean(prior 20 vol) >= {VOL_SURGE_X}",
    "ep": f"gap>= {EP_GAP_PCT}% and vol surge (same as setup_scanner)",
    "qulla": "EP or VOL_SURGE or NEAR_ND — existing setup tags",
    "oneil": f"63d RS vs SPY > 0; {ONEIL_NOTE}",
    "vcp": f"range_10/range_50<={VCP_RANGE_RATIO} or ATR14 declining or 3-swing contract, and near high; {VCP_NOTE}",
    "breadth": BREADTH_NOTE,
}


def _finite(val):
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(num):
        return None
    return num


def _round(val, digits=2):
    num = _finite(val)
    if num is None:
        return None
    return round(num, digits)


def _series(df: pd.DataFrame, col: str) -> pd.Series:
    if df is None or df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _sma(close: pd.Series, n: int) -> Optional[float]:
    return portfolio.last_sma(close, n)


def _sma_prev(close: pd.Series, n: int) -> Optional[float]:
    if close is None or len(close) < n + 1:
        return None
    return portfolio.last_sma(close.iloc[:-1], n)


def _rising(now, prev) -> Optional[bool]:
    a, b = _finite(now), _finite(prev)
    if a is None or b is None:
        return None
    return a > b


def _vs(close, sma) -> Optional[float]:
    c, s = _finite(close), _finite(sma)
    if c is None or s is None or s <= 0:
        return None
    return _round((c / s - 1.0) * 100.0, 2)


def _in_band(vs) -> bool:
    v = _finite(vs)
    return v is not None and PULLBACK_LO <= v <= PULLBACK_HI


def _dist_from_high(close, high: pd.Series, n: int, min_bars: int) -> Optional[float]:
    c = _finite(close)
    if c is None or high is None or len(high.dropna()) < min_bars:
        return None
    window = high.tail(min(n, len(high))).dropna()
    if len(window) < min_bars:
        return None
    hi = _finite(window.max())
    if hi is None or hi <= 0:
        return None
    return _round((c / hi - 1.0) * 100.0, 2)


def _vol_ratio(volume: pd.Series) -> Optional[float]:
    if volume is None or len(volume) < 3:
        return None
    today = _finite(volume.iloc[-1])
    prior = volume.iloc[:-1].tail(20).dropna()
    avg = _finite(prior.mean()) if len(prior) else None
    if today is None or avg is None or avg <= 0:
        return None
    return _round(today / avg, 2)


def _rsi_limit(close: pd.Series) -> Optional[float]:
    """Wilder RSI is undefined when avg loss or gain is 0; use the 0/100 limit."""
    delta = close.astype(float).diff().dropna()
    if len(delta) < 14:
        return None
    if (delta >= 0).all():
        return 100.0
    if (delta <= 0).all():
        return 0.0
    return None


def _rsi_pair(close: pd.Series) -> tuple[Optional[float], Optional[float]]:
    if close is None or len(close.dropna()) < 16:
        return None, None
    series = portfolio._rsi(close.astype(float), 14).dropna()
    if series.empty:
        lim = _rsi_limit(close)
        return (_round(lim, 2), _round(lim, 2)) if lim is not None else (None, None)
    cur = _round(series.iloc[-1], 2)
    prev = _round(series.iloc[-2], 2) if len(series) >= 2 else None
    return cur, prev


def _atr_declining(high: pd.Series, low: pd.Series, close: pd.Series) -> Optional[bool]:
    if min(len(high), len(low), len(close)) < 20:
        return None
    atr = portfolio._atr(high.astype(float), low.astype(float), close.astype(float), 14).dropna()
    if len(atr) < 6:
        return None
    now, prev = _finite(atr.iloc[-1]), _finite(atr.iloc[-6])
    if now is None or prev is None:
        return None
    return now < prev


def _range_ratio(high: pd.Series, low: pd.Series, short: int = 10, long: int = 50) -> Optional[float]:
    if high is None or low is None or len(high) < long or len(low) < long:
        return None
    h10, l10 = high.tail(short), low.tail(short)
    h50, l50 = high.tail(long), low.tail(long)
    r10 = _finite(h10.max()) - _finite(l10.min()) if len(h10) and len(l10) else None
    r50 = _finite(h50.max()) - _finite(l50.min()) if len(h50) and len(l50) else None
    if r10 is None or r50 is None or r50 <= 0:
        return None
    return _round(r10 / r50, 3)


def _swing_ranges(high: pd.Series, low: pd.Series, lookback: int = 2) -> list[float]:
    """Absolute ranges between consecutive 2-bar swing highs/lows.

    A bar is a swing high if high[i] equals max(high[i-lookback:i+lookback+1]).
    Same for swing lows. Need real extrema — omit if we cannot find them.
    """
    if high is None or low is None or len(high) < lookback * 2 + 3:
        return []
    h = high.astype(float).to_numpy()
    l = low.astype(float).to_numpy()
    swings: list[tuple[int, float]] = []
    n = len(h)
    for i in range(lookback, n - lookback):
        w_h = h[i - lookback : i + lookback + 1]
        w_l = l[i - lookback : i + lookback + 1]
        if np.isfinite(h[i]) and h[i] == np.nanmax(w_h):
            swings.append((i, float(h[i])))
        elif np.isfinite(l[i]) and l[i] == np.nanmin(w_l):
            swings.append((i, float(l[i])))
    swings.sort(key=lambda x: x[0])
    ranges = []
    for a, b in zip(swings, swings[1:]):
        rng = abs(b[1] - a[1])
        if np.isfinite(rng) and rng > 0:
            ranges.append(rng)
    return ranges


def _swing_contract(high: pd.Series, low: pd.Series) -> Optional[bool]:
    ranges = _swing_ranges(high, low)
    if len(ranges) < 6:
        return None
    last3 = float(np.mean(ranges[-3:]))
    prior3 = float(np.mean(ranges[-6:-3]))
    if prior3 <= 0:
        return None
    return last3 < prior3


def _load_frame(symbol: str) -> Optional[pd.DataFrame]:
    try:
        df = md.get_ohlcv_df(symbol, "daily", limit=320)
    except Exception:
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    return df


def measure(symbol: str, df: Optional[pd.DataFrame] = None, spy_df: Optional[pd.DataFrame] = None) -> dict:
    """One pack row from a stored (or injected) daily frame."""
    sym = str(symbol or "").strip().upper()
    frame = df if df is not None else _load_frame(sym)
    empty = {
        "symbol": sym,
        "ready": False,
        "tags": [],
        "styles": [],
        "match": {},
    }
    if not sym:
        return empty
    if frame is None or frame.empty:
        return {**empty, "error": "No stored daily bars"}

    close = _series(frame, "close")
    high = _series(frame, "high") if "high" in frame.columns else close
    low = _series(frame, "low") if "low" in frame.columns else close
    opn = _series(frame, "open") if "open" in frame.columns else close
    volume = _series(frame, "volume") if "volume" in frame.columns else pd.Series(dtype=float)
    last = _finite(close.iloc[-1]) if len(close) else None
    prev = _finite(close.iloc[-2]) if len(close) > 1 else None
    day_pct = _round((last / prev - 1.0) * 100.0, 2) if last and prev else None

    sma = {n: _sma(close, n) for n in SMA_WINDOWS}
    sma_prev = {n: _sma_prev(close, n) for n in SMA_WINDOWS}
    rising = {n: _rising(sma[n], sma_prev[n]) for n in SMA_WINDOWS}
    vs = {n: _vs(last, sma[n]) for n in SMA_WINDOWS}

    stacked = (
        last is not None
        and sma[20] is not None
        and sma[50] is not None
        and sma[200] is not None
        and last > sma[20] > sma[50] > sma[200]
    )
    pullback = False
    if rising.get(20) and _in_band(vs[20]):
        pullback = True
    if rising.get(50) and _in_band(vs[50]):
        pullback = True

    rsi, rsi_prev = _rsi_pair(close)
    rsi_os = rsi is not None and rsi <= 30
    rsi_ob = rsi is not None and rsi >= 70
    rsi_rising_os = (
        rsi is not None
        and rsi_prev is not None
        and rsi_prev < 30
        and rsi > rsi_prev
    )

    dist_52w = _dist_from_high(last, high, HIGH_52W, min_bars=60)
    dist_nd = _dist_from_high(last, high, HIGH_ND, min_bars=10)
    near_52w = dist_52w is not None and dist_52w >= NEAR_HIGH_PCT
    near_nd = dist_nd is not None and dist_nd >= NEAR_HIGH_PCT
    vol_x = _vol_ratio(volume)
    vol_surge = vol_x is not None and vol_x >= VOL_SURGE_X
    today_open = _finite(opn.iloc[-1]) if len(opn) else None
    gap = _round((today_open / prev - 1.0) * 100.0, 2) if today_open and prev else None
    is_ep = gap is not None and gap >= EP_GAP_PCT and vol_surge

    rs_spy = None
    if spy_df is not None and not spy_df.empty and "close" in spy_df.columns and len(close) > RS_BARS:
        spy_c = _series(spy_df, "close").dropna()
        if len(spy_c) > RS_BARS and len(close.dropna()) > RS_BARS:
            s0, s1 = _finite(close.iloc[-RS_BARS - 1]), last
            p0, p1 = _finite(spy_c.iloc[-RS_BARS - 1]), _finite(spy_c.iloc[-1])
            if s0 and s1 and p0 and p1 and p0 > 0 and s0 > 0:
                rs_spy = _round(((s1 / s0) / (p1 / p0) - 1.0) * 100.0, 2)
    oneil_rs = rs_spy is not None and rs_spy > 0

    range_shrink = _range_ratio(high, low)
    atr_down = _atr_declining(high, low, close)
    swing_down = _swing_contract(high, low)
    contracted = bool(range_shrink is not None and range_shrink <= VCP_RANGE_RATIO) or atr_down is True or swing_down is True
    near_high = near_52w or near_nd
    vcp_proxy = contracted and near_high

    tags: list[str] = []
    if stacked:
        tags.append("STACKED_MA")
    if pullback:
        tags.append("PULLBACK_RISING_MA")
    if rsi_os:
        tags.append("RSI_OS")
    if rsi_ob:
        tags.append("RSI_OB")
    if rsi_rising_os:
        tags.append("RSI_RISING_FROM_OS")
    if near_52w:
        tags.append("NEAR_52W")
    if near_nd:
        tags.append("NEAR_ND")
    if vol_surge:
        tags.append("VOL_SURGE")
    if is_ep:
        tags.append("EP")
    if near_52w or near_nd:
        tags.append("BREAKOUT")
        if vol_surge:
            tags.append("BREAKOUT_VOL")
    if is_ep or vol_surge or near_nd:
        tags.append("QULLA")
    if oneil_rs:
        tags.append("ONEIL_RS")
    if vcp_proxy:
        tags.append("VCP_PROXY")

    styles = []
    if "QULLA" in tags:
        styles.append("qulla")
    if oneil_rs:
        styles.append("oneil")
    if vcp_proxy:
        styles.append("vcp")

    match = {
        "ma": stacked or pullback,
        "rsi": rsi_os or rsi_ob or rsi_rising_os,
        "breakout": near_52w or near_nd or vol_surge,
        "qulla": "QULLA" in tags,
        "oneil": oneil_rs,
        "vcp": vcp_proxy,
        "all": last is not None,
    }

    return {
        "symbol": sym,
        "ready": last is not None,
        "price": _round(last, 4),
        "day_pct": day_pct,
        "bars": int(len(close.dropna())),
        "sma20": _round(sma[20], 4),
        "sma50": _round(sma[50], 4),
        "sma200": _round(sma[200], 4),
        "sma20_rising": rising[20],
        "sma50_rising": rising[50],
        "sma200_rising": rising[200],
        "vs20": vs[20],
        "vs50": vs[50],
        "vs200": vs[200],
        "stacked_ma": stacked,
        "pullback_rising_ma": pullback,
        "rsi14": rsi,
        "rsi14_prev": rsi_prev,
        "rsi_os": rsi_os,
        "rsi_ob": rsi_ob,
        "rsi_rising_from_os": rsi_rising_os,
        "dist_52w_pct": dist_52w,
        "dist_nd_pct": dist_nd,
        "near_52w": near_52w,
        "near_nd": near_nd,
        "vol_ratio": vol_x,
        "vol_surge": vol_surge,
        "gap_pct": gap,
        "is_ep": is_ep,
        "rs_spy_63d": rs_spy,
        "oneil_note": ONEIL_NOTE,
        "range_10_50": range_shrink,
        "atr_declining": atr_down,
        "swing_contract": swing_down,
        "vcp_proxy": vcp_proxy,
        "vcp_note": VCP_NOTE,
        "tags": tags,
        "styles": styles,
        "match": match,
    }


def empty_breadth(reason: str = "Empty universe — no stored bars to score.") -> dict:
    return {
        "ready": False,
        "n": 0,
        "n_sma50": 0,
        "n_sma200": 0,
        "n_ad_1d": 0,
        "n_ad_5d": 0,
        "pct_above_sma50": None,
        "pct_above_sma200": None,
        "adv_1d": None,
        "dec_1d": None,
        "unch_1d": None,
        "adv_5d": None,
        "dec_5d": None,
        "unch_5d": None,
        "ad_1d": None,
        "ad_5d": None,
        "message": reason,
        "note": BREADTH_NOTE,
        "formulas": FORMULAS,
    }


def _breadth_from_rows(rows: list[dict], frames: dict[str, pd.DataFrame] | None = None) -> dict:
    if not rows:
        return empty_breadth()
    above50 = above200 = n50 = n200 = 0
    adv1 = dec1 = unch1 = 0
    adv5 = dec5 = unch5 = 0
    scored_1d = scored_5d = 0
    for row in rows:
        if not row.get("ready"):
            continue
        if row.get("vs50") is not None:
            n50 += 1
            if row["vs50"] > 0:
                above50 += 1
        if row.get("vs200") is not None:
            n200 += 1
            if row["vs200"] > 0:
                above200 += 1
        day = _finite(row.get("day_pct"))
        if day is not None:
            scored_1d += 1
            if day > 0:
                adv1 += 1
            elif day < 0:
                dec1 += 1
            else:
                unch1 += 1
        frame = None
        if frames is not None:
            frame = frames.get(row["symbol"])
        if frame is None:
            frame = _load_frame(row["symbol"])
        close = _series(frame, "close") if frame is not None else pd.Series(dtype=float)
        if len(close.dropna()) >= 6:
            c0, c5 = _finite(close.iloc[-1]), _finite(close.iloc[-6])
            if c0 is not None and c5 is not None and c5 > 0:
                scored_5d += 1
                chg = c0 - c5
                if chg > 0:
                    adv5 += 1
                elif chg < 0:
                    dec5 += 1
                else:
                    unch5 += 1

    def pct(part, denom):
        if not denom:
            return None
        return _round(part / denom * 100.0, 1)

    def ad(adv, dec):
        tot = (adv or 0) + (dec or 0)
        if tot <= 0:
            return None
        return _round(adv / tot, 3)

    n_ready = sum(1 for r in rows if r.get("ready"))
    if n_ready == 0:
        return empty_breadth("Names listed, but none have stored closes.")
    return {
        "ready": True,
        "n": n_ready,
        "n_sma50": n50,
        "n_sma200": n200,
        "n_ad_1d": scored_1d,
        "n_ad_5d": scored_5d,
        "pct_above_sma50": pct(above50, n50),
        "pct_above_sma200": pct(above200, n200),
        "adv_1d": adv1 if scored_1d else None,
        "dec_1d": dec1 if scored_1d else None,
        "unch_1d": unch1 if scored_1d else None,
        "adv_5d": adv5 if scored_5d else None,
        "dec_5d": dec5 if scored_5d else None,
        "unch_5d": unch5 if scored_5d else None,
        "ad_1d": ad(adv1, dec1),
        "ad_5d": ad(adv5, dec5),
        "message": None,
        "note": BREADTH_NOTE,
        "formulas": FORMULAS,
    }


def _symbols(symbols: Optional[list[str]]) -> list[str]:
    if symbols is None:
        try:
            return [s.upper() for s in md.list_symbols_with_ohlcv("daily", min_bars=20)]
        except Exception:
            return []
    return [str(s).strip().upper() for s in symbols if str(s).strip()]


def scan(
    symbols: Optional[list[str]] = None,
    *,
    lens: str = "all",
    frames: Optional[dict[str, pd.DataFrame]] = None,
    spy_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Scan stored (or injected) frames. lens filters to real matches; empty is honest."""
    kind = (lens or "all").strip().lower()
    if kind not in LENSES:
        kind = "all"
    names = _symbols(symbols)
    if frames is not None:
        names = names or [s.upper() for s in frames]
    spy = spy_df
    if spy is None and frames is not None:
        spy = frames.get("SPY")
    if spy is None:
        spy = _load_frame("SPY")

    rows: list[dict] = []
    if frames is not None:
        for sym in names:
            rows.append(measure(sym, df=frames.get(sym), spy_df=spy))
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(measure, sym, None, spy): sym for sym in names}
            for fut in as_completed(futs):
                row = fut.result()
                if row:
                    rows.append(row)
    rows.sort(key=lambda r: (not r.get("ready"), -(r.get("day_pct") or -1e9), r.get("symbol") or ""))

    if kind != "all":
        hits = [r for r in rows if (r.get("match") or {}).get(kind)]
    else:
        hits = [r for r in rows if r.get("ready")]

    breadth = _breadth_from_rows(rows, frames=frames)
    empty_reason = None
    if not names:
        empty_reason = "Empty universe — no stored bars to score."
        breadth = empty_breadth(empty_reason)
    elif not hits:
        empty_reason = f"No {kind} hits from stored bars. Empty is honest — not a fake print."

    return {
        "lens": kind,
        "lenses": list(LENSES),
        "count": len(hits),
        "scanned": len(names),
        "rows": hits,
        "breadth": breadth,
        "note": NOTE,
        "oneil_note": ONEIL_NOTE,
        "vcp_note": VCP_NOTE,
        "message": empty_reason,
        "formulas": FORMULAS,
    }


def breadth(symbols: Optional[list[str]] = None, frames: Optional[dict[str, pd.DataFrame]] = None) -> dict:
    """Market-monitor *idea* from our symbols only. Empty universe → empty strip."""
    pack = scan(symbols, lens="all", frames=frames)
    strip = pack["breadth"]
    if not pack["scanned"]:
        return empty_breadth()
    return strip
