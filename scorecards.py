"""
scorecards.py — Momentum setup detection + grading.

Implements the four setups from the Qullamaggie/Stockbee process on top of
locally-stored OHLCV (FinViz-style filters, computed offline — no scraping):

  1. Continuation breakout   — leader breaks out of a tight base on volume.
  2. Momentum burst          — Stockbee 4%+ range-expansion day.
  3. Episodic pivot          — news gap on a volume surge.
  4. Parabolic (exhaustion)  — climactic extension; watch / trim / short.

Each detector returns a score 0-100 and a grade (A+/A/B/skip). Reuses the
indicator helpers in scanner.py — no duplicated math.
"""

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import database as db
from scanner import _rsi, _safe

# ── tunable thresholds (centralised so logic stays readable) ────────────────────
MIN_BARS        = 120
MIN_PRICE       = 3.0
MIN_DOLLAR_VOL  = 5_000_000

GRADE_APLUS = 85
GRADE_A     = 70
GRADE_B     = 55


def _grade(score):
    if score >= GRADE_APLUS:
        return "A+"
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B:
        return "B"
    return "skip"


# ── metrics ──────────────────────────────────────────────────────────────────

def _local_metrics(df):
    """All per-symbol metrics the detectors need."""
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    openp  = df["open"]
    vol    = df["volume"]
    n      = len(df)

    price = float(close.iloc[-1])

    rng     = (high / low - 1.0) * 100.0
    adr_pct = float(rng.tail(20).mean())

    def _perf(p):
        return float(close.pct_change(p).iloc[-1] * 100.0) if n > p else None

    sma10 = float(close.rolling(10).mean().iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])

    vol20      = float(vol.rolling(20).mean().iloc[-1])
    vol_ratio  = (float(vol.iloc[-1]) / vol20) if vol20 else None
    dollar_vol = price * vol20 if vol20 else 0.0

    gap_pct = float((openp.iloc[-1] / close.iloc[-2] - 1.0) * 100.0) if n > 1 else 0.0

    day_range = float(high.iloc[-1] - low.iloc[-1])
    close_near_high = ((float(close.iloc[-1]) - float(low.iloc[-1])) / day_range) if day_range > 1e-9 else 0.0

    range_today_pct = float(high.iloc[-1] / low.iloc[-1] - 1.0) * 100.0
    range_expansion = (range_today_pct / adr_pct) if adr_pct else None

    avg_rng_5  = float(rng.tail(5).mean())
    avg_rng_20 = float(rng.tail(20).mean())
    range_contraction = (avg_rng_5 / avg_rng_20) if avg_rng_20 else None

    rsi_s  = _rsi(close, 14).dropna()
    rsi14  = float(rsi_s.iloc[-1]) if len(rsi_s) else None

    hi_252 = float(close.rolling(min(252, n)).max().iloc[-1])
    dist_from_high = (price / hi_252 - 1.0) * 100.0 if hi_252 else None

    return {
        "price":             round(price, 2),
        "adr_pct":           round(adr_pct, 2),
        "perf_1m":           round(_perf(21), 2) if _perf(21) is not None else None,
        "perf_3m":           round(_perf(63), 2) if _perf(63) is not None else None,
        "perf_6m":           round(_perf(126), 2) if _perf(126) is not None else None,
        "ret_1d":            round(_perf(1), 2) if _perf(1) is not None else None,
        "ret_3d":            round(_perf(3), 2) if _perf(3) is not None else None,
        "dist_10":           round((price / sma10 - 1.0) * 100.0, 2) if sma10 else None,
        "dist_20":           round((price / sma20 - 1.0) * 100.0, 2) if sma20 else None,
        "dist_50":           round((price / sma50 - 1.0) * 100.0, 2) if sma50 else None,
        "sma10": sma10, "sma20": sma20, "sma50": sma50,
        "vol_ratio":         round(vol_ratio, 2) if vol_ratio else None,
        "dollar_vol":        round(dollar_vol, 0),
        "gap_pct":           round(gap_pct, 2),
        "close_near_high":   round(close_near_high, 2),
        "range_expansion":   round(range_expansion, 2) if range_expansion else None,
        "range_contraction": round(range_contraction, 2) if range_contraction else None,
        "rsi14":             round(rsi14, 1) if rsi14 is not None else None,
        "dist_from_high":    round(dist_from_high, 2) if dist_from_high is not None else None,
    }


def _g(m, key, default=0.0):
    v = m.get(key)
    return v if v is not None else default


# ── detectors ────────────────────────────────────────────────────────────────

def _detect_continuation(m):
    trend_ok = (_g(m, "price") > _g(m, "sma50") > 0 and
                _g(m, "sma10") > _g(m, "sma20") > _g(m, "sma50"))
    contraction = _g(m, "range_contraction", 1.0) < 0.6
    expansion   = _g(m, "range_expansion", 0.0) >= 1.5
    near_hi     = _g(m, "close_near_high") >= 0.7
    volume      = _g(m, "vol_ratio") >= 1.5
    near_high   = _g(m, "dist_from_high", -99) >= -15
    if not (trend_ok and expansion and near_hi):
        return None

    score = 0.0
    score += 25 if trend_ok else 0
    score += 25 if (contraction and expansion) else (12 if expansion else 0)
    score += min(20, _g(m, "vol_ratio") / 2.0 * 20) if volume else 0
    score += 15 * _g(m, "close_near_high")
    score += 15 if near_high else 0
    return ("continuation", round(score), _grade(round(score)))


def _detect_momentum_burst(m):
    move   = _g(m, "ret_1d")
    if move < 4.0:
        return None
    volume = _g(m, "vol_ratio") >= 1.5
    near_hi = _g(m, "close_near_high") >= 0.6
    if not (volume and near_hi):
        return None

    score = 0.0
    score += min(35, move / 8.0 * 35)               # move magnitude
    score += min(30, _g(m, "vol_ratio") / 2.0 * 30)  # volume
    score += 20 * _g(m, "close_near_high")           # close strength
    score += min(15, max(0, _g(m, "ret_3d")) / 10.0 * 15)  # 3-day momentum
    return ("momentum_burst", round(score), _grade(round(score)))


def _detect_episodic_pivot(m):
    gap = _g(m, "gap_pct")
    if gap < 4.0:
        return None
    surge   = _g(m, "vol_ratio") >= 2.0
    near_hi = _g(m, "close_near_high") >= 0.5
    not_ext = _g(m, "perf_1m", 0) < 40
    if not (surge and near_hi):
        return None

    score = 0.0
    score += min(35, gap / 10.0 * 35)                # gap size
    score += min(35, _g(m, "vol_ratio") / 3.0 * 35)  # volume surge
    score += 15 * _g(m, "close_near_high")           # close strength
    score += 15 if not_ext else 0                    # not already extended
    return ("episodic_pivot", round(score), _grade(round(score)))


def _detect_parabolic(m):
    far   = _g(m, "perf_1m", 0) >= 50 or _g(m, "dist_10", 0) >= 25
    hot   = _g(m, "rsi14", 0) >= 80
    blow  = _g(m, "range_expansion", 0) >= 2
    if not (far and hot):
        return None

    score = 0.0
    score += min(35, _g(m, "dist_10", 0) / 25.0 * 35)   # extension above 10MA
    score += min(25, (_g(m, "rsi14", 0) - 70) / 30.0 * 25)
    score += min(25, _g(m, "perf_1m", 0) / 50.0 * 25)
    score += 15 if blow else 0
    return ("parabolic", round(score), _grade(round(score)))


_DETECTORS = [_detect_continuation, _detect_momentum_burst,
              _detect_episodic_pivot, _detect_parabolic]


# ── orchestration ────────────────────────────────────────────────────────────

def scan_symbol(sym):
    try:
        df = db.get_ohlcv_df(sym, "daily", limit=300)
        if df is None or df.empty or len(df) < MIN_BARS:
            return None
        m = _local_metrics(df)
        if m["price"] < MIN_PRICE or _g(m, "dollar_vol") < MIN_DOLLAR_VOL:
            return None

        setups = []
        for det in _DETECTORS:
            res = det(m)
            if res and res[2] != "skip":
                setups.append({"type": res[0], "score": res[1], "grade": res[2]})
        if not setups:
            return None

        setups.sort(key=lambda s: s["score"], reverse=True)
        return {"symbol": sym, "metrics": m, "setups": setups,
                "best_grade": setups[0]["grade"], "best_score": setups[0]["score"]}
    except Exception as e:
        return {"symbol": sym, "error": str(e)}


_GRADE_RANK = {"A+": 3, "A": 2, "B": 1, "skip": 0}


def run_momentum_scan(symbols=None):
    if symbols is None:
        symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        raw = list(pool.map(scan_symbol, symbols))

    results = [r for r in raw if r and "setups" in r]
    results.sort(key=lambda r: (_GRADE_RANK.get(r["best_grade"], 0), r["best_score"]),
                 reverse=True)
    return results
