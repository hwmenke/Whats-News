"""Equity ENGINE / TAKEAWAY / VCP / RSI-C / TMS / Pattern / Stretch.

Public Yahoo/SQLite OHLCV only. No vendor terminal feed. No invented fractal beyond
SPEC 25/27 (fractal_scan). Blank when bars are missing.

Formulas (also on API ``formulas``):

RSI-C
    Wilder RSI(n) for n = 2..21 (20 lookbacks). Bucket = share of those
    RSIs in a zone. Extreme ≥90%, Lean ≥70%, Tilt ≥55%.
    OS zones: <20 / <10. OB: >80 / >90. Trend↑: 50–75. Trend↓: 25–50.
    Align = 1 − min(1, stdev(RSI_n) / 25). RSI-C composite = mean of the 20.
    Daily OS + Weekly TREND↑ → pullback-in-uptrend note (not a trade).
    Δ = RSI(n)_t − RSI(n)_{t−lag}, default n=14, lag=5.

VCP (honest proxy, not certified Minervini VCP)
    TIGHTENING: range_10/range_50 ≤ 0.55 or ATR14 declining.
    COILED: tightening and within 5% of the 20-bar high or low.
    BREAK ↑ / BREAK ↓: last close beyond the prior 20-bar high/low
    after tightening (or a raw 20d range break if no contraction).
    Weekly Pattern W uses the same idea on weekly bars (52w high/low ±0.1%).

TMS / Impulse
    TMS 0–100 = 0.5·RSI14 + 0.5·clip(50 + 10·(close/SMA50−1)·100, 0, 100).
    Zones: EXTREME − <15, MILD − <35, NEUTRAL 35–55, MILD + <70,
    SOLID + <85, STRONG + ≥85. Impulse from ΔTMS over 5 bars:
    ACCEL ± (|Δ|≥8), RISING/EASING (|Δ|≥3), STEADY else;
    FADE + if TMS>70 and Δ<−3; TURN ↑ if Δ flips from − to +.

Str (−5…+5)
    +2 / −2 if close breaks the prior 20-bar high/low;
    +2 / −2 for the prior 55-bar high/low;
    +1 / −1 if Bollinger %B (20,2) ≥ 1 or ≤ 0.
    Clamp to [−5, +5]. Omit if <56 bars.

ADMA stretch
    ADMA = adaptive_trend._adaptive_ma(close, er=20, fast=2, slow=60, method=adma).
    stretch_pct = (close/ADMA − 1)·100. Cross-sectional percentile among
    names that have ADMA. Omit %ile when fewer than 3 scored names.

ENGINE state machine
    Primary:
      NO TRADE  — <55 daily bars, or no setup and no weekly confirm.
      WATCH     — forming / coiled / RSI-C lean, not an accepted break.
      OPPORTUNITY — VCP BREAK or 3M range break, and D+W or RSI-C agrees.
    Phase (priority EXTENDED > ACCEPTED > TRIGGERED > FORMING > DORMANT):
      FORMING   — VCP TIGHTENING or COILED, no range break.
      TRIGGERED — 20d or 55d range break on the last close.
      ACCEPTED  — break still holds and (prior close also beyond or vol≥1.2×).
      EXTENDED  — |stretch_pct| in the top decile of the desk, or |vs ADMA|≥3%.
      DORMANT   — mid-range, RSI-C MIXED, no VCP.
    D1.x = SPEC 25/27 Fractal D (65d) when the estimator returns a number.
    D+W  = daily and weekly RSI-C trend signs agree.
    TF!  = fractal read FRAGILE (SPEC 25/27 only — never invented).

Pattern scanner
    Daily 3M=63, 1M=21. Breakout / Breakdown = new 3M high / low.
    From Bottom / From Top = 1M break from the opposite third of the 3M range.
    Weekly 1Y=52, 6M=26, ±0.1% on the 1Y extreme. From Bottom/Top = 6M extreme
    while still in the bottom/top third of the 1Y range. Display cap 15.

TAKEAWAY
    SENTIMENT — VCP — RSI-C — TMS (Impulse) — optional Pattern W.
    SENTIMENT from Bias: LONG ≥1.5, LEAN LONG ≥0.5, SHORT ≤−1.5,
    LEAN SHORT ≤−0.5, else NEUTRAL. Bias sums documented VCP / RSI-C /
    TMS / 3M-break points. Not a win rate.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd

import adaptive_trend
import fractal_scan
import market_data as md
import portfolio

NOTE = (
    "Yahoo/SQLite OHLCV only. ENGINE / TAKEAWAY are research labels from stored "
    "bars — not a live vendor sheet and not a win rate. Blank when bars are missing."
)
VCP_NOTE = "honest proxy, not certified VCP"
FRACTAL_NOTE = "SPEC 25/27 only — null D is a failed window, not invented."

RSI_LOOKBACKS = tuple(range(2, 22))
RSI_N_DEFAULT = 14
DELTA_LAG_DEFAULT = 5
EXTREME = 0.90
LEAN = 0.70
TILT = 0.55
NEAR_PCT = 5.0
VCP_RANGE = 0.55
STR_BARS_20 = 20
STR_BARS_55 = 55
DAILY_3M = 63
DAILY_1M = 21
WEEKLY_1Y = 52
WEEKLY_6M = 26
WEEKLY_EPS = 0.001
DISPLAY_CAP = 15
MIN_ENGINE_BARS = 55
SECTOR_ETFS = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)

FORMULAS = {
    "rsi_c": (
        "Wilder RSI(2)..RSI(21); Extreme≥90% Lean≥70% Tilt≥55% of lookbacks "
        "in OS<20 / OB>80 / trend 50-75 or 25-50. Align=1-min(1,σ/25)."
    ),
    "vcp": (
        f"TIGHTENING if range10/range50≤{VCP_RANGE} or ATR14↓; COILED if also "
        "within 5% of 20d high/low; BREAK if close beyond prior 20d extreme."
    ),
    "tms": "0.5*RSI14 + 0.5*clip(50+10*(close/SMA50-1)*100,0,100). Impulse from 5-bar ΔTMS.",
    "str": "+2/−2 prior 20d high/low break; +2/−2 prior 55d; +1/−1 BB %B≥1 / ≤0; clamp [-5,+5].",
    "engine": (
        "NO TRADE if <55 bars or no setup; WATCH if forming/lean; OPPORTUNITY if "
        "VCP/3M break and D+W or RSI-C agrees. Phase EXTENDED>ACCEPTED>TRIGGERED>FORMING>DORMANT. "
        "D1.x=SPEC 25/27 65d D. D+W=daily/weekly RSI-C sign. TF!=FRAGILE."
    ),
    "pattern": (
        "Daily 3M=63 / 1M=21 new highs-lows; From Bottom/Top = 1M break from opposite 3M third. "
        "Weekly 1Y=52 / 6M=26 ±0.1%; From Bottom/Top = 6M extreme in 1Y opposite third."
    ),
    "takeaway": "SENTIMENT — VCP — RSI-C — TMS (Impulse) — Pattern W. Bias is a point sum, not a win rate.",
    "adma_stretch": "ADMA(er=20,fast=2,slow=60); stretch%=(close/ADMA-1)*100; desk percentile if n≥3.",
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


def _series(df: Optional[pd.DataFrame], col: str) -> pd.Series:
    if df is None or df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _load(symbol: str, freq: str, limit: int = 400) -> Optional[pd.DataFrame]:
    try:
        df = md.get_ohlcv_df(symbol, freq, limit=limit)
    except Exception:
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    return df[~df.index.duplicated(keep="last")].sort_index()


def _weekly_from_daily(daily: pd.DataFrame) -> Optional[pd.DataFrame]:
    if daily is None or daily.empty:
        return None
    need = [c for c in ("open", "high", "low", "close", "volume") if c in daily.columns]
    if "close" not in need:
        return None
    g = daily[need].resample("W-FRI").agg(
        {c: ("last" if c in ("close", "open") else ("sum" if c == "volume" else ("max" if c == "high" else "min")))
         for c in need}
    ).dropna(subset=["close"])
    if "open" in daily.columns:
        g["open"] = daily["open"].resample("W-FRI").first()
    return g if len(g) else None


def resolve_weekly(symbol: str, daily: Optional[pd.DataFrame], weekly: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    if weekly is not None and not weekly.empty:
        return weekly
    stored = _load(symbol, "weekly", 120) if symbol else None
    if stored is not None:
        return stored
    return _weekly_from_daily(daily) if daily is not None else None


def last_rsi(close: pd.Series, n: int) -> Optional[float]:
    if close is None or len(close.dropna()) < n + 2:
        return None
    s = portfolio._rsi(close.astype(float), n).dropna()
    if s.empty:
        delta = close.astype(float).diff().dropna()
        if len(delta) >= n and (delta >= 0).all():
            return 100.0
        if len(delta) >= n and (delta <= 0).all():
            return 0.0
        return None
    return _round(float(s.iloc[-1]), 2)


def rsi_at(close: pd.Series, n: int, offset: int = 0) -> Optional[float]:
    if close is None or len(close.dropna()) < n + 2 + offset:
        return None
    series = close.astype(float)
    if offset:
        series = series.iloc[: len(series) - offset]
    return last_rsi(series, n)


def rsi_counter(close: pd.Series) -> dict:
    """20-lookback RSI-C pack. Blank buckets when too few closes."""
    empty = {
        "ready": False,
        "avg_rsi": None,
        "align": None,
        "pct_os20": None,
        "pct_os10": None,
        "pct_ob80": None,
        "pct_ob90": None,
        "pct_trend_up": None,
        "pct_trend_dn": None,
        "state": None,
        "values": {},
    }
    if close is None or len(close.dropna()) < 24:
        return empty
    vals = {}
    for n in RSI_LOOKBACKS:
        vals[n] = last_rsi(close, n)
    have = [v for v in vals.values() if v is not None]
    if len(have) < 10:
        return empty
    arr = np.asarray(have, dtype=float)
    def share(pred):
        return _round(sum(1 for v in have if pred(v)) / len(have), 3)

    pct_os20 = share(lambda v: v < 20)
    pct_os10 = share(lambda v: v < 10)
    pct_ob80 = share(lambda v: v > 80)
    pct_ob90 = share(lambda v: v > 90)
    pct_up = share(lambda v: 50 <= v <= 75)
    pct_dn = share(lambda v: 25 <= v <= 50)
    align = _round(max(0.0, 1.0 - min(1.0, float(np.std(arr, ddof=1)) / 25.0 if len(arr) > 1 else 0.0)), 3)
    state = _rsi_c_state(pct_os20, pct_ob80, pct_up, pct_dn)
    return {
        "ready": True,
        "avg_rsi": _round(float(arr.mean()), 2),
        "align": align,
        "pct_os20": pct_os20,
        "pct_os10": pct_os10,
        "pct_ob80": pct_ob80,
        "pct_ob90": pct_ob90,
        "pct_trend_up": pct_up,
        "pct_trend_dn": pct_dn,
        "state": state,
        "values": {str(k): vals[k] for k in RSI_LOOKBACKS},
    }


def _rsi_c_state(os20, ob80, up, dn) -> str:
    os20, ob80, up, dn = os20 or 0, ob80 or 0, up or 0, dn or 0
    if os20 >= EXTREME:
        return "OS EXTREME"
    if os20 >= LEAN:
        return "OVERSOLD"
    if os20 >= TILT:
        return "OS LEAN"
    if ob80 >= EXTREME:
        return "OB EXTREME"
    if ob80 >= LEAN:
        return "OVERBOUGHT"
    if ob80 >= TILT:
        return "OB LEAN"
    if up >= EXTREME:
        return "TREND ↑ STRONG"
    if up >= LEAN:
        return "TREND ↑"
    if up >= TILT:
        return "TILT ↑"
    if dn >= EXTREME:
        return "TREND ↓ STRONG"
    if dn >= LEAN:
        return "TREND ↓"
    if dn >= TILT:
        return "TILT ↓"
    return "MIXED"


def _os_state(state: Optional[str]) -> bool:
    return (state or "") in ("OS EXTREME", "OVERSOLD", "OS LEAN")


def _trend_up_state(state: Optional[str]) -> bool:
    return (state or "").startswith("TREND ↑") or (state or "") == "TILT ↑"


def _trend_dn_state(state: Optional[str]) -> bool:
    return (state or "").startswith("TREND ↓") or (state or "") == "TILT ↓"


def vcp_phase(high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
    """Honest VCP proxy. Blank phase when windows are short."""
    out = {"phase": None, "range_10_50": None, "atr_declining": None, "note": VCP_NOTE}
    if close is None or len(close.dropna()) < 21:
        return out
    last = _finite(close.iloc[-1])
    if last is None:
        return out
    r10 = None
    if len(high.dropna()) >= 50 and len(low.dropna()) >= 50:
        span10 = _finite(high.tail(10).max()) - _finite(low.tail(10).min())
        span50 = _finite(high.tail(50).max()) - _finite(low.tail(50).min())
        if span10 is not None and span50 and span50 > 0:
            r10 = _round(span10 / span50, 3)
    atr_down = None
    if len(close) >= 20:
        atr = portfolio._atr(high.astype(float), low.astype(float), close.astype(float), 14).dropna()
        if len(atr) >= 6:
            a0, a1 = _finite(atr.iloc[-1]), _finite(atr.iloc[-6])
            if a0 is not None and a1 is not None:
                atr_down = a0 < a1
    tightening = (r10 is not None and r10 <= VCP_RANGE) or atr_down is True
    prior_h = _finite(high.iloc[-21:-1].max()) if len(high) >= 21 else None
    prior_l = _finite(low.iloc[-21:-1].min()) if len(low) >= 21 else None
    near_hi = prior_h and last >= prior_h * (1 - NEAR_PCT / 100.0)
    near_lo = prior_l and last <= prior_l * (1 + NEAR_PCT / 100.0)
    broke_up = prior_h is not None and last >= prior_h
    broke_dn = prior_l is not None and last <= prior_l
    phase = None
    if broke_up:
        phase = "BREAK ↑"
    elif broke_dn:
        phase = "BREAK ↓"
    elif tightening and (near_hi or near_lo):
        phase = "COILED"
    elif tightening:
        phase = "TIGHTENING"
    out.update({"phase": phase, "range_10_50": r10, "atr_declining": atr_down})
    return out


def tms_pack(close: pd.Series) -> dict:
    empty = {"tms": None, "zone": None, "impulse": None, "delta": None}
    if close is None or len(close.dropna()) < 50:
        return empty
    rsi = last_rsi(close, 14)
    sma50 = portfolio.last_sma(close, 50)
    last = _finite(close.iloc[-1])
    if rsi is None or sma50 is None or not last or sma50 <= 0:
        return empty
    vs = (last / sma50 - 1.0) * 100.0
    tms = 0.5 * rsi + 0.5 * float(np.clip(50.0 + 10.0 * vs, 0.0, 100.0))
    tms = _round(tms, 1)
    if tms < 15:
        zone = "EXTREME −"
    elif tms < 35:
        zone = "MILD −"
    elif tms < 55:
        zone = "NEUTRAL"
    elif tms < 70:
        zone = "MILD +"
    elif tms < 85:
        zone = "SOLID +"
    else:
        zone = "STRONG +"
    def _tms_only(series):
        if series is None or len(series.dropna()) < 50:
            return None
        r = last_rsi(series, 14)
        s = portfolio.last_sma(series, 50)
        c = _finite(series.iloc[-1])
        if r is None or s is None or not c or s <= 0:
            return None
        return _round(0.5 * r + 0.5 * float(np.clip(50.0 + 10.0 * ((c / s - 1.0) * 100.0), 0.0, 100.0)), 1)

    prev_tms = _tms_only(close.iloc[:-5]) if len(close) > 55 else None
    older_tms = _tms_only(close.iloc[:-10]) if len(close) > 60 else None
    delta = _round(tms - prev_tms, 1) if prev_tms is not None else None
    impulse = "STEADY"
    if delta is not None:
        if tms > 70 and delta <= -3:
            impulse = "FADE +"
        elif older_tms is not None and prev_tms is not None and (prev_tms - older_tms) < 0 and delta > 0:
            impulse = "TURN ↑"
        elif delta >= 8:
            impulse = "ACCEL +"
        elif delta <= -8:
            impulse = "ACCEL −"
        elif delta >= 3:
            impulse = "RISING"
        elif delta <= -3:
            impulse = "EASING"
    return {"tms": tms, "zone": zone, "impulse": impulse, "delta": delta}


def bollinger_pct_b(close: pd.Series, n: int = 20, k: float = 2.0) -> Optional[float]:
    if close is None or len(close.dropna()) < n:
        return None
    win = close.astype(float).tail(n)
    mid = float(win.mean())
    sd = float(win.std(ddof=1)) if len(win) > 1 else 0.0
    if sd <= 1e-12:
        return None
    last = _finite(win.iloc[-1])
    if last is None:
        return None
    return _round((last - (mid - k * sd)) / (2 * k * sd), 3)


def breakout_str(high: pd.Series, low: pd.Series, close: pd.Series) -> Optional[int]:
    if close is None or len(close.dropna()) < STR_BARS_55 + 1:
        return None
    last = _finite(close.iloc[-1])
    if last is None:
        return None
    score = 0
    h20 = _finite(high.iloc[-STR_BARS_20 - 1 : -1].max())
    l20 = _finite(low.iloc[-STR_BARS_20 - 1 : -1].min())
    h55 = _finite(high.iloc[-STR_BARS_55 - 1 : -1].max())
    l55 = _finite(low.iloc[-STR_BARS_55 - 1 : -1].min())
    if h20 is not None and last >= h20:
        score += 2
    elif l20 is not None and last <= l20:
        score -= 2
    if h55 is not None and last >= h55:
        score += 2
    elif l55 is not None and last <= l55:
        score -= 2
    pb = bollinger_pct_b(close)
    if pb is not None:
        if pb >= 1.0:
            score += 1
        elif pb <= 0.0:
            score -= 1
    return int(max(-5, min(5, score)))


def adma_stretch(close: pd.Series) -> Optional[float]:
    if close is None or len(close.dropna()) < 40:
        return None
    ma = adaptive_trend._adaptive_ma(close.astype(float), 20, 2, 60, method="adma")
    last_ma = _finite(ma.dropna().iloc[-1]) if ma is not None and len(ma.dropna()) else None
    last = _finite(close.iloc[-1])
    if last is None or last_ma is None or last_ma <= 0:
        return None
    return _round((last / last_ma - 1.0) * 100.0, 2)


def daily_pattern(high: pd.Series, low: pd.Series, close: pd.Series) -> Optional[str]:
    if close is None or len(close.dropna()) < DAILY_3M + 1:
        return None
    last = _finite(close.iloc[-1])
    if last is None:
        return None
    hi3 = _finite(high.iloc[-DAILY_3M - 1 : -1].max())
    lo3 = _finite(low.iloc[-DAILY_3M - 1 : -1].min())
    hi1 = _finite(high.iloc[-DAILY_1M - 1 : -1].max()) if len(high) > DAILY_1M else None
    lo1 = _finite(low.iloc[-DAILY_1M - 1 : -1].min()) if len(low) > DAILY_1M else None
    if hi3 is not None and last >= hi3:
        return "Breakout"
    if lo3 is not None and last <= lo3:
        return "Breakdown"
    span = None
    if hi3 is not None and lo3 is not None and hi3 > lo3:
        span = (last - lo3) / (hi3 - lo3)
    if hi1 is not None and last >= hi1 and span is not None and span <= 1.0 / 3.0:
        return "From Bottom"
    if lo1 is not None and last <= lo1 and span is not None and span >= 2.0 / 3.0:
        return "From Top"
    return None


def weekly_pattern(high: pd.Series, low: pd.Series, close: pd.Series) -> Optional[str]:
    if close is None or len(close.dropna()) < WEEKLY_6M + 2:
        return None
    last = _finite(close.iloc[-1])
    if last is None:
        return None
    use_1y = len(close.dropna()) >= WEEKLY_1Y
    n = WEEKLY_1Y if use_1y else max(WEEKLY_6M + 2, len(close.dropna()))
    hi = _finite(high.tail(n).max())
    lo = _finite(low.tail(n).min())
    hi6 = _finite(high.tail(WEEKLY_6M).max())
    lo6 = _finite(low.tail(WEEKLY_6M).min())
    if hi is not None and last >= hi * (1 - WEEKLY_EPS):
        return "Breakout"
    if lo is not None and last <= lo * (1 + WEEKLY_EPS):
        return "Breakdown"
    span = None
    if hi is not None and lo is not None and hi > lo:
        span = (last - lo) / (hi - lo)
    if hi6 is not None and last >= hi6 * (1 - WEEKLY_EPS) and span is not None and span <= 1.0 / 3.0:
        return "From Bottom"
    if lo6 is not None and last <= lo6 * (1 + WEEKLY_EPS) and span is not None and span >= 2.0 / 3.0:
        return "From Top"
    return None


def _sigma(close: pd.Series, horizon: int) -> Optional[float]:
    if close is None or len(close.dropna()) < horizon + 21:
        return None
    rets = close.astype(float).pct_change().dropna()
    if len(rets) < horizon + 20:
        return None
    move = float((close.iloc[-1] / close.iloc[-horizon - 1] - 1.0))
    daily = rets.iloc[-horizon - 20 : -horizon] if horizon else rets.tail(20)
    # 1d sigma uses last 20 daily returns excluding today
    if horizon == 1:
        daily = rets.iloc[:-1].tail(20)
        move = float(rets.iloc[-1])
    sd = float(daily.std(ddof=1)) if len(daily) >= 10 else None
    if not sd or sd <= 1e-12:
        return None
    return _round(move / (sd * (horizon ** 0.5 if horizon > 1 else 1.0)), 2)


def _ret(close: pd.Series, bars: int) -> Optional[float]:
    if close is None or len(close.dropna()) <= bars:
        return None
    a, b = _finite(close.iloc[-bars - 1]), _finite(close.iloc[-1])
    if a is None or b is None or a <= 0:
        return None
    return _round((b / a - 1.0) * 100.0, 2)


def _fractal_d(symbol: str, close: pd.Series) -> tuple[Optional[str], Optional[str]]:
    """SPEC 25/27 only. Returns (D1.x label, read) or (None, None)."""
    try:
        px = close.astype(float).dropna().to_numpy()
        row = fractal_scan.measure_symbol(symbol, closes=px)
    except Exception:
        return None, None
    if not row:
        return None, None
    d = _finite(row.get("d_65d"))
    label = f"D{d:.1f}" if d is not None else None
    return label, row.get("read")


def _bias(vcp, rsi_state, tms_zone, daily_pat) -> float:
    score = 0.0
    if vcp == "BREAK ↑":
        score += 1.0
    elif vcp == "BREAK ↓":
        score -= 1.0
    elif vcp == "COILED":
        score += 0.4
    if _trend_up_state(rsi_state):
        score += 1.0
    elif _trend_dn_state(rsi_state):
        score -= 1.0
    elif _os_state(rsi_state):
        score += 0.3
    if tms_zone == "STRONG +":
        score += 0.5
    elif tms_zone == "SOLID +":
        score += 0.3
    elif tms_zone == "EXTREME −":
        score -= 0.5
    if daily_pat == "Breakout":
        score += 1.0
    elif daily_pat == "Breakdown":
        score -= 1.0
    return round(score, 1)


def _sentiment(bias: float) -> str:
    if bias >= 1.5:
        return "LONG"
    if bias >= 0.5:
        return "LEAN LONG"
    if bias <= -1.5:
        return "SHORT"
    if bias <= -0.5:
        return "LEAN SHORT"
    return "NEUTRAL"


def _engine_states(vcp, rsi_d, daily_pat, str_n, stretch, dw, bars, fragile: bool) -> tuple[str, str]:
    triggered = str_n is not None and abs(str_n) >= 2
    accepted = str_n is not None and abs(str_n) >= 4
    extended = stretch is not None and abs(stretch) >= 3.0
    forming = vcp in ("TIGHTENING", "COILED")
    lean = _os_state(rsi_d) or (rsi_d or "").startswith("OB")
    agree = False
    if daily_pat == "Breakout" or vcp == "BREAK ↑":
        agree = dw == "D+W ↑" or _trend_up_state(rsi_d)
    elif daily_pat == "Breakdown" or vcp == "BREAK ↓":
        agree = dw == "D+W ↓" or _trend_dn_state(rsi_d)
    broke = vcp in ("BREAK ↑", "BREAK ↓") or daily_pat in ("Breakout", "Breakdown")

    if bars < MIN_ENGINE_BARS:
        return "NO TRADE", "DORMANT"
    if extended:
        phase = "EXTENDED"
    elif accepted and broke:
        phase = "ACCEPTED"
    elif triggered:
        phase = "TRIGGERED"
    elif forming:
        phase = "FORMING"
    else:
        phase = "DORMANT"

    if broke and agree:
        primary = "OPPORTUNITY"
    elif forming or lean or triggered:
        primary = "WATCH"
    elif broke and not agree:
        primary = "WATCH"
    else:
        primary = "NO TRADE"
    if fragile and primary == "NO TRADE" and forming:
        primary = "WATCH"
    return primary, phase


def measure(
    symbol: str,
    daily: Optional[pd.DataFrame] = None,
    weekly: Optional[pd.DataFrame] = None,
    *,
    rsi_n: int = RSI_N_DEFAULT,
    lag: int = DELTA_LAG_DEFAULT,
) -> dict:
    """One ENGINE row from stored (or injected) frames."""
    sym = str(symbol or "").strip().upper()
    ddf = daily if daily is not None else _load(sym, "daily", 400)
    wdf = resolve_weekly(sym, ddf, weekly)
    empty = {
        "symbol": sym,
        "ready": False,
        "engine": None,
        "takeaway": None,
        "note": NOTE,
    }
    if not sym or ddf is None or ddf.empty:
        return {**empty, "error": "No stored daily bars"}

    close = _series(ddf, "close")
    high = _series(ddf, "high") if "high" in ddf.columns else close
    low = _series(ddf, "low") if "low" in ddf.columns else close
    last = _finite(close.iloc[-1]) if len(close) else None
    prev = _finite(close.iloc[-2]) if len(close) > 1 else None
    rsi_d = rsi_counter(close)
    rsi_w = rsi_counter(_series(wdf, "close")) if wdf is not None else rsi_counter(pd.Series(dtype=float))
    vcp = vcp_phase(high, low, close)
    w_vcp = vcp_phase(_series(wdf, "high"), _series(wdf, "low"), _series(wdf, "close")) if wdf is not None else {"phase": None}
    tms = tms_pack(close)
    str_n = breakout_str(high, low, close)
    stretch = adma_stretch(close)
    pat_d = daily_pattern(high, low, close)
    pat_w = weekly_pattern(_series(wdf, "high"), _series(wdf, "low"), _series(wdf, "close")) if wdf is not None else None
    sma20 = portfolio.last_sma(close, 20)
    vs20 = _round((last / sma20 - 1.0) * 100.0, 2) if last and sma20 else None
    hi52 = _finite(high.tail(252).max()) if len(high.dropna()) >= 60 else None
    dist_52w = _round((last / hi52 - 1.0) * 100.0, 2) if last and hi52 else None
    d_label, d_read = _fractal_d(sym, close)
    dw = None
    if _trend_up_state(rsi_d.get("state")) and _trend_up_state(rsi_w.get("state")):
        dw = "D+W ↑"
    elif _trend_dn_state(rsi_d.get("state")) and _trend_dn_state(rsi_w.get("state")):
        dw = "D+W ↓"
    bias = _bias(vcp.get("phase"), rsi_d.get("state"), tms.get("zone"), pat_d)
    sent = _sentiment(bias)
    primary, phase = _engine_states(
        vcp.get("phase"), rsi_d.get("state"), pat_d, str_n, stretch, dw, int(len(close.dropna())),
        d_read == "FRAGILE",
    )
    tags = []
    if dw:
        tags.append("D+W")
    if d_read == "FRAGILE":
        tags.append("TF!")
    engine_parts = [primary, phase]
    if d_label:
        engine_parts.append(d_label)
    engine_parts.extend(tags)
    engine = " | ".join(engine_parts)
    take_bits = [
        sent,
        f"VCP {vcp.get('phase')}" if vcp.get("phase") else None,
        f"RSI-C {rsi_d.get('state')}" if rsi_d.get("state") else None,
        f"TMS {tms.get('zone')} ({tms.get('impulse')})" if tms.get("zone") else None,
        f"W: {pat_w}" if pat_w else None,
    ]
    takeaway = " — ".join(b for b in take_bits if b)
    pb_note = None
    if _os_state(rsi_d.get("state")) and _trend_up_state(rsi_w.get("state")):
        pb_note = "pullback-in-uptrend (Daily OS + Weekly TREND↑) — research note, not a trade"

    use_n = int(rsi_n) if rsi_n else RSI_N_DEFAULT
    use_lag = int(lag) if lag else DELTA_LAG_DEFAULT
    rsi14 = last_rsi(close, use_n)
    rsi14_prev = rsi_at(close, use_n, use_lag)
    rsi_delta = _round(rsi14 - rsi14_prev, 1) if rsi14 is not None and rsi14_prev is not None else None

    return {
        "symbol": sym,
        "ready": last is not None,
        "price": _round(last, 4),
        "day_pct": _round((last / prev - 1.0) * 100.0, 2) if last and prev else None,
        "bars": int(len(close.dropna())),
        "weekly_bars": int(len(_series(wdf, "close").dropna())) if wdf is not None else 0,
        "vs20": vs20,
        "dist_52w_pct": dist_52w,
        "vol30": _round(float(close.pct_change().tail(30).std(ddof=1) * (252 ** 0.5) * 100.0), 1) if len(close.dropna()) >= 31 else None,
        "sigma_1d": _sigma(close, 1),
        "sigma_1w": _sigma(close, 5),
        "sigma_1m": _sigma(close, 21),
        "ret_1d": _ret(close, 1),
        "ret_1w": _ret(close, 5),
        "ret_1m": _ret(close, 21),
        "ret_3m": _ret(close, 63),
        "ret_6m": _ret(close, 126),
        "ret_12m": _ret(close, 252),
        "vcp": vcp.get("phase"),
        "vcp_note": VCP_NOTE,
        "tms": tms.get("tms"),
        "tms_zone": tms.get("zone"),
        "impulse": tms.get("impulse"),
        "pattern_w": pat_w,
        "pattern_d": pat_d,
        "bias": bias,
        "sentiment": sent,
        "takeaway": takeaway,
        "dw": dw,
        "engine": engine,
        "engine_primary": primary,
        "engine_phase": phase,
        "d_label": d_label,
        "fractal_read": d_read,
        "fractal_note": FRACTAL_NOTE,
        "str": str_n,
        "stretch_pct": stretch,
        "stretch_pctile": None,
        "rsi_c": rsi_d,
        "rsi_c_w": rsi_w,
        "rsi14": rsi14,
        "rsi_delta": rsi_delta,
        "pullback_in_uptrend": pb_note,
        "gray_tag": " · ".join(x for x in (rsi_d.get("state"), vcp.get("phase")) if x),
        "note": NOTE,
    }


def _symbols(symbols: Optional[list[str]]) -> list[str]:
    if symbols is None:
        try:
            return [s.upper() for s in md.list_symbols_with_ohlcv("daily", min_bars=30)]
        except Exception:
            return []
    return [str(s).strip().upper() for s in symbols if str(s).strip()]


def _score_desk(
    symbols: Optional[list[str]],
    frames: Optional[dict] = None,
    *,
    rsi_n: int = RSI_N_DEFAULT,
    lag: int = DELTA_LAG_DEFAULT,
) -> list[dict]:
    names = _symbols(symbols)
    if frames is not None:
        names = names or [s.upper() for s in frames if not str(s).upper().endswith("_W")]
    rows = []
    if frames is not None:
        for sym in names:
            rows.append(measure(
                sym,
                daily=frames.get(sym),
                weekly=frames.get(f"{sym}_W"),
                rsi_n=rsi_n,
                lag=lag,
            ))
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(measure, sym, rsi_n=rsi_n, lag=lag): sym for sym in names}
            for fut in as_completed(futs):
                row = fut.result()
                if row:
                    rows.append(row)
    scored = [r for r in rows if r.get("stretch_pct") is not None]
    if len(scored) >= 3:
        ordered = sorted(scored, key=lambda r: r["stretch_pct"])
        n = len(ordered)
        for i, r in enumerate(ordered):
            r["stretch_pctile"] = _round((i / (n - 1)) * 100.0, 1) if n > 1 else 50.0
    rows.sort(key=lambda r: (not r.get("ready"), -(r.get("bias") or 0), r.get("symbol") or ""))
    return rows


def board(symbols: Optional[list[str]] = None, frames: Optional[dict] = None) -> dict:
    rows = _score_desk(symbols, frames)
    ready = [r for r in rows if r.get("ready")]
    counts = {"WATCH": 0, "OPPORTUNITY": 0, "NO TRADE": 0}
    for r in ready:
        counts[r.get("engine_primary") or "NO TRADE"] = counts.get(r.get("engine_primary") or "NO TRADE", 0) + 1
    return {
        "ready": bool(ready),
        "count": len(ready),
        "scanned": len(rows),
        "counts": counts,
        "rows": ready,
        "message": None if ready else "Empty ENGINE — no stored daily bars.",
        "note": NOTE,
        "formulas": FORMULAS,
        "state_machine": FORMULAS["engine"],
    }


def rsi_counter_board(
    symbols: Optional[list[str]] = None,
    frames: Optional[dict] = None,
    *,
    rsi_n: int = RSI_N_DEFAULT,
    lag: int = DELTA_LAG_DEFAULT,
) -> dict:
    rows = _score_desk(symbols, frames, rsi_n=rsi_n, lag=lag)
    daily = {"oversold": [], "overbought": [], "trend_up": [], "trend_dn": []}
    weekly = {"oversold": [], "overbought": [], "trend_up": [], "trend_dn": []}
    accel, fade = [], []
    pullbacks = []
    for r in rows:
        if not r.get("ready"):
            continue
        d = r.get("rsi_c") or {}
        w = r.get("rsi_c_w") or {}
        item = {
            "symbol": r["symbol"],
            "state": d.get("state"),
            "avg_rsi": d.get("avg_rsi"),
            "align": d.get("align"),
            "pct_os20": d.get("pct_os20"),
            "pct_ob80": d.get("pct_ob80"),
            "pct_trend_up": d.get("pct_trend_up"),
            "pct_trend_dn": d.get("pct_trend_dn"),
            "rsi_c": d.get("avg_rsi"),
            "w_state": w.get("state"),
            "w_avg": w.get("avg_rsi"),
            "w_align": w.get("align"),
            "delta": r.get("rsi_delta"),
        }
        st = d.get("state") or ""
        if _os_state(st):
            daily["oversold"].append(item)
        elif st.startswith("OB") or st == "OVERBOUGHT":
            daily["overbought"].append(item)
        if _trend_up_state(st):
            daily["trend_up"].append(item)
        if _trend_dn_state(st):
            daily["trend_dn"].append(item)
        wst = w.get("state") or ""
        witem = {**item, "state": wst, "avg_rsi": w.get("avg_rsi"), "align": w.get("align")}
        if _os_state(wst):
            weekly["oversold"].append(witem)
        elif wst.startswith("OB") or wst == "OVERBOUGHT":
            weekly["overbought"].append(witem)
        if _trend_up_state(wst):
            weekly["trend_up"].append(witem)
        if _trend_dn_state(wst):
            weekly["trend_dn"].append(witem)
        if r.get("rsi_delta") is not None:
            if r["rsi_delta"] >= 0:
                accel.append(item)
            else:
                fade.append(item)
        if r.get("pullback_in_uptrend"):
            pullbacks.append({"symbol": r["symbol"], "note": r["pullback_in_uptrend"]})

    def top(lst, key, reverse=True):
        return sorted(lst, key=lambda x: (x.get(key) is None, -(x.get(key) or 0) if reverse else (x.get(key) or 0)))[:DISPLAY_CAP]

    sectors = []
    have = {r["symbol"] for r in rows if r.get("ready")}
    for etf in SECTOR_ETFS:
        if etf in have:
            hit = next(r for r in rows if r["symbol"] == etf)
            sectors.append({
                "symbol": etf,
                "rsi14": hit.get("rsi14"),
                "delta": hit.get("rsi_delta"),
                "state": (hit.get("rsi_c") or {}).get("state"),
            })

    empty = not any(daily.values()) and not any(weekly.values())
    return {
        "ready": not empty,
        "rsi_n": int(rsi_n),
        "lag": int(lag),
        "daily": {k: top(v, "avg_rsi") for k, v in daily.items()},
        "weekly": {k: top(v, "avg_rsi") for k, v in weekly.items()},
        "accelerating": top(accel, "delta"),
        "fading": top(fade, "delta", reverse=False),
        "sectors": sectors,
        "pullbacks": pullbacks,
        "controls": {"rsi_n": int(rsi_n), "lag": int(lag), "note": "Daily LEFT / Weekly RIGHT. Extreme≥90 Lean≥70 Tilt≥55."},
        "howto": (
            "RSI-C uses RSI(2)…RSI(21). Extreme ≥90% of lookbacks in-zone, Lean ≥70%, Tilt ≥55%. "
            "Daily LEFT / Weekly RIGHT. Daily OS + Weekly TREND↑ is a pullback-in-uptrend note — not a trade. "
            "Align = tightness of the 20 lookbacks. Δ = RSI14 change over lag bars."
        ),
        "message": None if not empty else "Empty RSI-C — need ≥24 stored closes per name.",
        "note": NOTE,
        "formulas": FORMULAS,
    }


def pattern_board(symbols: Optional[list[str]] = None, frames: Optional[dict] = None) -> dict:
    rows = _score_desk(symbols, frames)
    daily = {"Breakout": [], "Breakdown": [], "From Bottom": [], "From Top": []}
    weekly = {"Breakout": [], "Breakdown": [], "From Bottom": [], "From Top": []}
    for r in rows:
        if not r.get("ready"):
            continue
        item = {"symbol": r["symbol"], "takeaway": r.get("takeaway"), "gray_tag": r.get("gray_tag")}
        if r.get("pattern_d") in daily:
            daily[r["pattern_d"]].append(item)
        if r.get("pattern_w") in weekly:
            weekly[r["pattern_w"]].append(item)
    def pack(bucket):
        counts = {k: len(v) for k, v in bucket.items()}
        shown = {k: v[:DISPLAY_CAP] for k, v in bucket.items()}
        return {"counts": counts, "rows": shown}
    dpack, wpack = pack(daily), pack(weekly)
    empty = sum(dpack["counts"].values()) + sum(wpack["counts"].values()) == 0
    return {
        "ready": not empty,
        "daily": dpack,
        "weekly": wpack,
        "howto": (
            "Daily: Breakout/Breakdown = new 3-month (63d) high/low. "
            "From Bottom/Top = 1-month (21d) break from the opposite third of the 3M range. "
            "Weekly: 1Y high/low ±0.1%; From Bottom/Top = 6M extreme still in the opposite 1Y third. "
            "Lists cap at 15; counts are the true totals. Empty is no stored bars — not a fake print."
        ),
        "message": None if not empty else "Empty pattern scanner — no 3M/1Y extremes on stored bars.",
        "note": NOTE,
        "formulas": FORMULAS,
    }


def stretch_board(symbols: Optional[list[str]] = None, frames: Optional[dict] = None) -> dict:
    rows = [r for r in _score_desk(symbols, frames) if r.get("ready")]
    with_str = [r for r in rows if r.get("str") is not None]
    with_px = [r for r in rows if r.get("stretch_pctile") is not None]
    strongest = sorted(with_str, key=lambda r: -(r.get("str") or 0))[:DISPLAY_CAP]
    weakest = sorted(with_str, key=lambda r: (r.get("str") or 0))[:DISPLAY_CAP]
    stretched = sorted(with_px, key=lambda r: -(r.get("stretch_pctile") or 0))[:DISPLAY_CAP]
    compressed = sorted(with_px, key=lambda r: (r.get("stretch_pctile") or 0))[:DISPLAY_CAP]

    def slim(r):
        return {
            "symbol": r["symbol"],
            "str": r.get("str"),
            "stretch_pct": r.get("stretch_pct"),
            "stretch_pctile": r.get("stretch_pctile"),
            "gray_tag": r.get("gray_tag"),
            "takeaway": r.get("takeaway"),
        }

    empty = not with_str and not with_px
    return {
        "ready": not empty,
        "strongest": [slim(r) for r in strongest if (r.get("str") or 0) > 0],
        "breakdowns": [slim(r) for r in weakest if (r.get("str") or 0) < 0],
        "stretched": [slim(r) for r in stretched],
        "compressed": [slim(r) for r in compressed],
        "howto": (
            "Str = −5…+5 from 20d & 55d range breaks plus Bollinger %B. "
            "Stretched = highest ADMA percentile (extended vs MA complex). "
            "Compressed = tightest (energy building). Gray tag = RSI-C state · VCP phase. "
            "Percentile omitted when fewer than 3 names have ADMA."
        ),
        "message": None if not empty else "Empty stretch board — need ≥56 daily bars for Str.",
        "note": NOTE,
        "formulas": FORMULAS,
    }


def sigma_board(symbols: Optional[list[str]] = None, frames: Optional[dict] = None) -> dict:
    rows = [r for r in _score_desk(symbols, frames) if r.get("ready")]
    slim = [{
        "symbol": r["symbol"],
        "price": r.get("price"),
        "ret_1d": r.get("ret_1d"),
        "ret_1w": r.get("ret_1w"),
        "ret_1m": r.get("ret_1m"),
        "ret_3m": r.get("ret_3m"),
        "ret_6m": r.get("ret_6m"),
        "ret_12m": r.get("ret_12m"),
        "sigma_1d": r.get("sigma_1d"),
        "sigma_1w": r.get("sigma_1w"),
        "sigma_1m": r.get("sigma_1m"),
        "rsi14": r.get("rsi14"),
        "takeaway": r.get("takeaway"),
    } for r in rows]
    return {
        "ready": bool(slim),
        "rows": slim,
        "message": None if slim else "Empty sigma grid — no stored closes.",
        "note": "σ = move / (trailing daily σ × √horizon). Yahoo/SQLite only — not a vendor terminal feed.",
        "formulas": FORMULAS,
    }


def command_board(symbols: Optional[list[str]] = None, frames: Optional[dict] = None) -> dict:
    rows = _score_desk(symbols, frames)
    ready = [r for r in rows if r.get("ready")]
    counts = {"WATCH": 0, "OPPORTUNITY": 0, "NO TRADE": 0}
    for r in ready:
        counts[r.get("engine_primary") or "NO TRADE"] = counts.get(r.get("engine_primary") or "NO TRADE", 0) + 1
    pats = pattern_board(symbols, frames)
    return {
        "ready": bool(ready),
        "n": len(ready),
        "engine_counts": counts,
        "opportunity": [r["symbol"] for r in ready if r.get("engine_primary") == "OPPORTUNITY"][:12],
        "pullbacks": [r["symbol"] for r in ready if r.get("pullback_in_uptrend")][:12],
        "pattern_counts": {
            "daily": (pats.get("daily") or {}).get("counts") or {},
            "weekly": (pats.get("weekly") or {}).get("counts") or {},
        },
        "message": None if ready else "Empty command — seed a sleeve and Fetch Yahoo.",
        "note": NOTE,
        "formulas": FORMULAS,
        "nav": ["command", "setup", "pattern", "rsi_c", "macro", "sigma", "book", "chart"],
    }


def catalog() -> dict:
    return {
        "formulas": FORMULAS,
        "state_machine": FORMULAS["engine"],
        "controls": {"rsi_n": RSI_N_DEFAULT, "lag": DELTA_LAG_DEFAULT, "lookbacks": list(RSI_LOOKBACKS)},
        "note": NOTE,
        "vcp_note": VCP_NOTE,
        "fractal_note": FRACTAL_NOTE,
    }
