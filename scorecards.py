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
# Liquidity / universe gates
MIN_BARS        = 120
MIN_PRICE       = 5.0          # Qullamaggie prefers > $10; $5 hard floor
MIN_DOLLAR_VOL  = 10_000_000   # $10M/day liquid-leader floor

# Grade boundaries (per setup score 0-100)
GRADE_APLUS = 85
GRADE_A     = 70
GRADE_B     = 55

# Continuation breakout
CONT_LEADERSHIP_3M   = 20.0    # min prior 3-month move (%) to count as a leader
CONT_CONTRACTION     = 0.70    # pre-breakout range contraction ratio (< = tight)
CONT_EXPANSION       = 1.50    # breakout-day range / ADR
CONT_VOL_RATIO       = 1.40
CONT_CLOSE_NEAR_HIGH = 0.60
CONT_MAX_UP_DAYS     = 3        # reject if already 4+ up days into the move
CONT_MIN_FROM_HIGH   = -25.0   # within 25% of the 52w high

# Stockbee momentum burst
BURST_MOVE_MIN       = 4.0     # 4%+ range-expansion day
BURST_MOVE_STRONG    = 8.0     # full marks at 8%+
BURST_VOL_RATIO      = 1.50
BURST_CLOSE_NEAR_HIGH= 0.60
BURST_MAX_UP_DAYS    = 4       # don't chase after several up days in a row
BURST_PRIOR_TIGHT    = 0.70    # prior-day contraction earns bonus

# Episodic pivot (news gap)
EP_GAP_MIN           = 8.0     # toward Qullamaggie's 10%+ gap; full marks at 12%
EP_GAP_FULL          = 12.0
EP_VOL_RATIO         = 2.50    # "massive" relative volume
EP_VOL_FULL          = 4.0
EP_CLOSE_NEAR_HIGH   = 0.50
EP_MAX_PRIOR_MOVE_3M = 50.0    # prefer names not already extended over 3-6 months

# Parabolic (exhaustion / watch-or-short)
PARA_PERF_1M         = 50.0    # +50%+ in a month
PARA_DIST_20         = 25.0    # far above the 20-day MA
PARA_RSI             = 75.0
PARA_UP_DAYS         = 3        # consecutive up days
PARA_EXPANSION       = 1.50


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

    # Contraction of the run-up *into* today (exclude the breakout day itself),
    # so a tight base ahead of a range-expansion day scores well.
    prior_rng   = rng.iloc[:-1]
    pr5  = float(prior_rng.tail(5).mean())  if len(prior_rng) >= 5  else None
    pr20 = float(prior_rng.tail(20).mean()) if len(prior_rng) >= 20 else None
    prior_contraction = (pr5 / pr20) if (pr5 and pr20) else None

    # Consecutive up-days ending today (used to avoid chasing extended moves).
    up_days = 0
    chg = close.diff()
    for v in reversed(chg.tolist()):
        if v is not None and v > 0:
            up_days += 1
        else:
            break

    # Higher-lows: most-recent swing low above the prior swing low.
    if n >= 20:
        higher_lows = float(low.tail(5).min()) > float(low.iloc[-15:-5].min())
    else:
        higher_lows = None

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
        "prior_contraction": round(prior_contraction, 2) if prior_contraction else None,
        "up_days":           up_days,
        "higher_lows":       higher_lows,
        "rsi14":             round(rsi14, 1) if rsi14 is not None else None,
        "dist_from_high":    round(dist_from_high, 2) if dist_from_high is not None else None,
    }


def _g(m, key, default=0.0):
    v = m.get(key)
    return v if v is not None else default


# ── detectors ────────────────────────────────────────────────────────────────

def _detect_continuation(m):
    """Leader makes a big prior move, bases tight, then breaks out on volume."""
    leader      = _g(m, "perf_3m", 0) >= CONT_LEADERSHIP_3M
    trend_ok    = (_g(m, "price") > _g(m, "sma50") > 0 and
                   _g(m, "sma10") > _g(m, "sma20") > _g(m, "sma50"))
    contraction = _g(m, "prior_contraction", 1.0) < CONT_CONTRACTION
    expansion   = _g(m, "range_expansion", 0.0) >= CONT_EXPANSION
    near_hi     = _g(m, "close_near_high") >= CONT_CLOSE_NEAR_HIGH
    volume      = _g(m, "vol_ratio") >= CONT_VOL_RATIO
    near_high   = _g(m, "dist_from_high", -99) >= CONT_MIN_FROM_HIGH
    not_ext     = _g(m, "up_days", 0) <= CONT_MAX_UP_DAYS
    higher_lows = bool(m.get("higher_lows"))

    # Hard requirements: a real leader, an actual breakout, near its highs,
    # and not already several days extended.
    if not (trend_ok and leader and expansion and near_hi and near_high and not_ext):
        return None

    score = 0.0
    score += min(20, _g(m, "perf_3m", 0) / 60.0 * 20)        # leadership / prior move
    score += 20 if trend_ok else 0                            # 10>20>50 alignment
    score += 20 if (contraction and expansion) else 10        # tight base -> expansion
    score += min(15, _g(m, "vol_ratio") / 2.0 * 15) if volume else 0
    score += 10 * _g(m, "close_near_high")                    # close strength
    score += 10 if higher_lows else 0                         # constructive base
    score += 5 if _g(m, "up_days", 99) <= 1 else 0            # early in the move
    return ("continuation", round(score), _grade(round(score)))


def _detect_momentum_burst(m):
    """Stockbee burst: range-expansion day out of a quiet base, bought early."""
    move = _g(m, "ret_1d")
    if move < BURST_MOVE_MIN:
        return None
    volume   = _g(m, "vol_ratio") >= BURST_VOL_RATIO
    near_hi  = _g(m, "close_near_high") >= BURST_CLOSE_NEAR_HIGH
    not_ext  = _g(m, "up_days", 0) <= BURST_MAX_UP_DAYS   # don't chase
    if not (volume and near_hi and not_ext):
        return None

    prior_tight = _g(m, "prior_contraction", 1.0) < BURST_PRIOR_TIGHT
    score = 0.0
    score += min(30, move / BURST_MOVE_STRONG * 30)          # move magnitude
    score += min(25, _g(m, "vol_ratio") / 2.0 * 25)          # volume
    score += 15 * _g(m, "close_near_high")                   # close strength
    score += 15 if prior_tight else 0                        # quiet before the burst
    score += max(0, 15 - _g(m, "up_days", 0) * 4)            # earlier = better
    return ("momentum_burst", round(score), _grade(round(score)))


def _detect_episodic_pivot(m):
    """News gap: large gap on massive volume, ideally on a neglected name."""
    gap = _g(m, "gap_pct")
    if gap < EP_GAP_MIN:
        return None
    surge   = _g(m, "vol_ratio") >= EP_VOL_RATIO
    near_hi = _g(m, "close_near_high") >= EP_CLOSE_NEAR_HIGH
    if not (surge and near_hi):
        return None

    not_ext = _g(m, "perf_3m", 0) < EP_MAX_PRIOR_MOVE_3M
    score = 0.0
    score += min(35, gap / EP_GAP_FULL * 35)                 # gap size
    score += min(30, _g(m, "vol_ratio") / EP_VOL_FULL * 30)  # volume surge
    score += 15 * _g(m, "close_near_high")                   # close strength
    score += 20 if not_ext else 0                            # neglected / not extended
    return ("episodic_pivot", round(score), _grade(round(score)))


def _detect_parabolic(m):
    """Climactic exhaustion — a watch/trim/short flag, not a long buy."""
    far  = _g(m, "perf_1m", 0) >= PARA_PERF_1M or _g(m, "dist_20", 0) >= PARA_DIST_20
    days = _g(m, "up_days", 0) >= PARA_UP_DAYS
    hot  = _g(m, "rsi14", 0) >= PARA_RSI
    blow = _g(m, "range_expansion", 0) >= PARA_EXPANSION
    if not (far and hot and days):
        return None

    score = 0.0
    score += min(30, _g(m, "dist_20", 0) / PARA_DIST_20 * 30)       # extension vs 20MA
    score += min(20, _g(m, "up_days", 0) / 5.0 * 20)                # consecutive up days
    score += min(20, (_g(m, "rsi14", 0) - 70) / 30.0 * 20)         # overbought
    score += min(20, _g(m, "perf_1m", 0) / PARA_PERF_1M * 20)      # 1-month blow-off
    score += 10 if blow else 0                                      # climactic range
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
