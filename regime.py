"""
regime.py — Market regime + breadth dashboard.

Classifies the tape as Offensive / Constructive / Choppy / Defensive from
SPY & QQQ trend structure plus watchlist breadth, and returns suggested
exposure / risk gating to inform position sizing.
"""

from concurrent.futures import ThreadPoolExecutor

import database as db

INDEX_SYMBOLS = ["SPY", "QQQ"]

# Suggested gating per regime — mirrors the process doc's exposure tables
# (gross exposure %, max risk per trade %, max open positions, max portfolio heat %).
SUGGESTED = {
    "Offensive":    {"exposure_pct": 100, "max_risk_pct": 1.0,  "max_positions": 8, "max_heat_pct": 5.0},
    "Constructive": {"exposure_pct": 60,  "max_risk_pct": 0.75, "max_positions": 5, "max_heat_pct": 3.0},
    "Choppy":       {"exposure_pct": 30,  "max_risk_pct": 0.35, "max_positions": 3, "max_heat_pct": 2.0},
    "Defensive":    {"exposure_pct": 15,  "max_risk_pct": 0.25, "max_positions": 1, "max_heat_pct": 1.0},
    "Unknown":      {"exposure_pct": 0,   "max_risk_pct": 0.25, "max_positions": 0, "max_heat_pct": 0.5},
}

# Classification thresholds (breadth = % of watchlist above the moving average)
OFFENSIVE_INDEX_SCORE   = 3
OFFENSIVE_PCT_ABOVE_50  = 60
OFFENSIVE_PCT_ABOVE_200 = 50
CONSTRUCTIVE_INDEX_SCORE = 1
CONSTRUCTIVE_PCT_ABOVE_50 = 45
DEFENSIVE_INDEX_SCORE   = -2
DEFENSIVE_PCT_ABOVE_50  = 30
DEFENSIVE_PCT_ABOVE_200 = 25


def _index_score(symbol):
    df = db.get_ohlcv_df(symbol, "daily", limit=300)
    if df is None or df.empty or len(df) < 200:
        return None
    close = df["close"]
    price = float(close.iloc[-1])
    sma50  = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    s50  = float(sma50.iloc[-1])
    s200 = float(sma200.iloc[-1])
    slope50 = float(sma50.iloc[-1] - sma50.iloc[-5])

    if price > s50 > s200 and slope50 > 0:
        score = 2
    elif price > s200:
        score = 1
    elif price < s200 and s50 < s200:
        score = -2
    elif price < s50:
        score = -1
    else:
        score = 0

    return {
        "symbol": symbol, "price": round(price, 2),
        "sma50": round(s50, 2), "sma200": round(s200, 2),
        "slope50_up": slope50 > 0, "score": score,
        "above_50": price > s50, "above_200": price > s200,
    }


def _breadth_one(sym):
    df = db.get_ohlcv_df(sym, "daily", limit=300)
    if df is None or df.empty or len(df) < 60:
        return None
    close = df["close"]
    vol   = df["volume"]
    price = float(close.iloc[-1])

    def _sma(n):
        return float(close.rolling(n).mean().iloc[-1]) if len(df) >= n else None

    s20, s50, s200 = _sma(20), _sma(50), _sma(200)
    vol20 = float(vol.rolling(20).mean().iloc[-1]) if len(df) >= 20 else None
    vol_ratio = (float(vol.iloc[-1]) / vol20) if vol20 else None
    ret1 = float(close.pct_change(1).iloc[-1] * 100.0) if len(df) > 1 else 0.0
    hi = float(close.rolling(min(252, len(df))).max().iloc[-1])

    return {
        "above_20":  s20 is not None and price > s20,
        "above_50":  s50 is not None and price > s50,
        "above_200": s200 is not None and price > s200,
        "up4_vol":   ret1 >= 4 and (vol_ratio or 0) >= 1.5,
        "down4_vol": ret1 <= -4 and (vol_ratio or 0) >= 1.5,
        "new_high":  hi and price >= hi * 0.999,
    }


def breadth(symbols=None):
    if symbols is None:
        symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return {"total": 0}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(_breadth_one, symbols) if r]

    total = len(rows)
    if not total:
        return {"total": 0}

    def _pct(key):
        return round(sum(1 for r in rows if r[key]) / total * 100.0, 1)

    return {
        "total":         total,
        "pct_above_20":  _pct("above_20"),
        "pct_above_50":  _pct("above_50"),
        "pct_above_200": _pct("above_200"),
        "up4_count":     sum(1 for r in rows if r["up4_vol"]),
        "down4_count":   sum(1 for r in rows if r["down4_vol"]),
        "new_highs":     sum(1 for r in rows if r["new_high"]),
    }


def compute_regime():
    indices = {}
    index_score = 0
    have_index = False
    for sym in INDEX_SYMBOLS:
        s = _index_score(sym)
        indices[sym] = s
        if s:
            index_score += s["score"]
            have_index = True

    if not have_index:
        return {
            "regime": "Unknown",
            "reason": "SPY/QQQ data not found — add and fetch them first.",
            "index": indices, "breadth": {"total": 0},
            "index_score": None, "suggested": SUGGESTED["Unknown"],
        }

    b = breadth()
    pct50  = b.get("pct_above_50", 0)
    pct200 = b.get("pct_above_200", 0)
    up4    = b.get("up4_count", 0)
    down4  = b.get("down4_count", 0)

    if (index_score >= OFFENSIVE_INDEX_SCORE and
            pct50 >= OFFENSIVE_PCT_ABOVE_50 and
            pct200 >= OFFENSIVE_PCT_ABOVE_200 and up4 > down4):
        regime = "Offensive"
    elif index_score >= CONSTRUCTIVE_INDEX_SCORE and pct50 >= CONSTRUCTIVE_PCT_ABOVE_50:
        regime = "Constructive"
    elif (index_score <= DEFENSIVE_INDEX_SCORE or
          pct50 < DEFENSIVE_PCT_ABOVE_50 or
          pct200 < DEFENSIVE_PCT_ABOVE_200 or down4 > 2 * up4):
        regime = "Defensive"
    else:
        regime = "Choppy"

    return {
        "regime":      regime,
        "index_score": index_score,
        "index":       indices,
        "breadth":     b,
        "suggested":   SUGGESTED[regime],
    }
