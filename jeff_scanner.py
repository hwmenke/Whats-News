"""
jeff_scanner.py — Watchlist-wide "Jeff setup" scan.

For every watched symbol, computes the swing grade (A/B/C), a 0–5 readiness
(timing) score, base-structure analysis (trigger/pivot, pattern, base length),
and relative strength vs SPY / intra-list rank.

Results are ranked grade → readiness → RVOL so the most actionable setups float
to the top.  The whole scan is memoised through indicator_cache so repeat tab
visits are instant and only invalidate when underlying OHLCV changes.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import database as db
import indicator_cache as cache
import swing_core

logger = logging.getLogger(__name__)


# ── relative strength helpers ──────────────────────────────────────────────────

def _rets(close):
    """20- and 60-bar percentage returns from a close series."""
    def r(n):
        return round((float(close.iloc[-1]) / float(close.iloc[-1 - n]) - 1) * 100, 2) \
            if len(close) > n else None
    return {"r20": r(20), "r60": r(60)}


def _get_spy_rets():
    """SPY benchmark returns from the local DB, or None if unavailable."""
    try:
        df = db.get_ohlcv_df("SPY", "daily", limit=200)
        if df.empty or len(df) < 30:
            return None
        return _rets(df["close"])
    except Exception:
        return None


# ── base / trigger structure ────────────────────────────────────────────────────

def _base_structure(df, sd):
    """Pivot trigger, distance-to-trigger status, contraction & pattern label."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    n     = len(close)
    last_close = float(close.iloc[-1])

    # Trigger = the resistance pivot the stock must clear (20-bar high)
    look    = min(20, n)
    trigger = float(high.tail(look).max())
    dist    = round((trigger / last_close - 1) * 100, 2) if last_close else None

    if   dist is None: status = "—"
    elif dist <= 1.5:  status = "AT"
    elif dist <= 5:    status = "NEAR"
    elif dist <= 12:   status = "WATCH"
    else:              status = "EARLY"

    # Volatility contraction: recent 10-bar range vs the 30 bars before it
    rng = (high - low)
    if n >= 40:
        recent = float(rng.tail(10).mean())
        prior  = float(rng.iloc[-40:-10].mean())
        range_ratio = round(recent / prior, 2) if prior > 0 else 1.0
    else:
        range_ratio = 1.0

    # Base length: bars in the last 30 sitting within 8% below the trigger
    last30  = close.tail(min(30, n))
    in_base = int((last30 >= trigger * 0.92).sum())
    base_weeks = round(in_base / 5.0, 1)

    # Pattern heuristic
    vcp = sd["vcp_score"]
    if range_ratio < 0.6 and vcp > 0.5:
        pattern = "VCP"
    elif range_ratio < 0.8 and dist is not None and dist < 8:
        pattern = "Flat Base"
    elif dist is not None and dist < 12:
        pattern = "Consolidation"
    else:
        pattern = "Building"

    return {
        "trigger":          round(trigger, 2),
        "trigger_dist_pct": dist,
        "trigger_status":   status,
        "range_ratio":      range_ratio,
        "base_weeks":       base_weeks,
        "pattern":          pattern,
    }


def _checks(sd):
    """The 7 Jeff criteria as booleans; readiness counts the 5 timing ones."""
    rsi14 = sd.get("rsi_14")
    checks = {
        "rvol": sd["rvol"] >= 1.0,
        "ext":  not sd["too_extended"],
        "lod":  sd["lod_dist_atr"] < 0.6,
        "vcp":  sd["vcp_score"] > 0.5,
        "high": sd["range_pos_52w"] >= 0.60,
        "kama": sd["kama_alignment"] >= 2,
        "rsi":  rsi14 is not None and 50 <= rsi14 <= 80,
    }
    readiness = sum(1 for k in ("rvol", "ext", "lod", "vcp", "kama") if checks[k])
    return checks, readiness


# ── single-symbol row ────────────────────────────────────────────────────────────

def _row_for(sym, spy_rets, tier_map):
    try:
        df = db.get_ohlcv_df(sym, "daily", limit=260)
        if df.empty or len(df) < 20:
            return {"symbol": sym, "error": "No data — fetch first",
                    "tier": tier_map.get(sym, "watchlist")}

        sd    = swing_core.swing_data_for(sym, df=df)
        grade = swing_core.grade_from_swing(sd)
        base  = _base_structure(df, sd)
        checks, readiness = _checks(sd)

        sr  = _rets(df["close"])
        rs_vs_spy = None
        if spy_rets and sr["r20"] is not None and spy_rets["r20"] is not None:
            rs_vs_spy = round(sr["r20"] - spy_rets["r20"], 2)

        return {
            "symbol":        sym,
            "tier":          tier_map.get(sym, "watchlist"),
            "grade":         grade["grade"],
            "score":         grade["score"],
            "readiness":     readiness,
            "checks":        checks,
            "last_close":    sd["last_close"],
            "rvol":          sd["rvol"],
            "atr_14":        sd["atr_14"],
            "atr_mult_50ma": sd["atr_mult_50ma"],
            "above_50ma":    sd["above_50ma"],
            "lod_dist_atr":  sd["lod_dist_atr"],
            "vcp_score":     sd["vcp_score"],
            "range_pos_52w": sd["range_pos_52w"],
            "rsi_14":        sd["rsi_14"],
            "kama_alignment":sd["kama_alignment"],
            "ret_20d":       sd["ret_20d"],
            "ret_60d":       sr["r60"],
            "rs_vs_spy":     rs_vs_spy,
            "rs_rank":       None,            # filled in after the full pass
            **base,
        }
    except Exception as e:
        logger.debug("jeff-scan row failed for %s: %s", sym, e)
        return {"symbol": sym, "error": str(e),
                "tier": tier_map.get(sym, "watchlist")}


# ── public entry ─────────────────────────────────────────────────────────────────

def compute_jeff_scan(symbols: list) -> list:
    sym_key = tuple(sorted(symbols))
    return cache.get_or_compute(
        "compute_jeff_scan", "__all__", "daily",
        lambda: _compute_jeff_inner(symbols),
        symbols=sym_key,
    )


def _compute_jeff_inner(symbols: list) -> list:
    spy_rets = _get_spy_rets()

    # symbol → tier map (one query)
    tier_map = {}
    try:
        for row in db.list_symbols():
            tier_map[row["symbol"]] = row.get("watchlist_tier") or "watchlist"
    except Exception:
        pass

    # Parallel compute (SQLite WAL allows concurrent reads)
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(lambda s: _row_for(s, spy_rets, tier_map), symbols))

    # Intra-list RS rank by 60-day return (percentile, 1=weakest … 100=strongest)
    ranked = [r for r in rows if not r.get("error") and r.get("ret_60d") is not None]
    ranked.sort(key=lambda r: r["ret_60d"])
    m = len(ranked)
    for i, r in enumerate(ranked):
        r["rs_rank"] = round((i + 1) / m * 100) if m else None

    # Composite opportunity score (0–100): grade quality + timing + RS + trigger proximity
    _grade_pts   = {"A": 40, "B": 25, "C": 10}
    _trigger_pts = {"AT": 10, "NEAR": 6, "WATCH": 2, "EARLY": 0}
    for r in rows:
        if r.get("error"):
            r["opp_score"] = 0
            continue
        pts  = _grade_pts.get(r.get("grade", "C"), 10)
        pts += (r.get("readiness") or 0) * 6
        pts += round((r.get("rs_rank") or 0) * 0.20)
        pts += _trigger_pts.get(r.get("trigger_status"), 0)
        r["opp_score"] = pts

    # Persist fresh grades so the dashboard strength table stays in sync
    for r in rows:
        if not r.get("error") and r.get("grade"):
            try:
                db.set_setup_grade(r["symbol"], r["grade"])
            except Exception:
                pass

    # Rank: grade A→B→C, then readiness desc, then RVOL desc; errors last
    grade_rank = {"A": 0, "B": 1, "C": 2}
    rows.sort(key=lambda x: (
        4 if x.get("error") else grade_rank.get(x.get("grade"), 3),
        -(x.get("readiness") or 0),
        -(x.get("rvol") or 0),
    ))
    return rows
