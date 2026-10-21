"""Independent Fractal D estimator — SPEC 25/27 rebuild (odds-edge TRIALS).

Not BCA proprietary report text. D = 2 − H where H is the OLS slope of
ln(M_k) on ln(k) from non-overlapping block |log-return sums|.

NaN / missing bars → null D. Never invent a number.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

import market_data as md

SOURCE = "whats-news fractal_scan (SPEC 25/27)"
NOTE = (
    "Independent SPEC 25/27 rebuild (log-return block scaling). "
    "Not a BCA proprietary estimator. "
    "FRAGILE = D≤1.40 and |window move|>5% — fade the move. "
    "SPEC footnote: BCA published ~2-in-3 reversal — not a computed win rate."
)
COLUMNS = ["symbol", "d_65d", "d_130d", "move_65d", "move_130d", "read", "tags"]
HORIZONS = (1, 2, 4, 8, 16, 32)
CORE_INDEX = ("SPY", "QQQ", "IWM")
WIN_65 = 65
WIN_130 = 130
FRAGILE_D = 1.40
FRAGILE_MOVE = 5.0
COLLAPSE_D = 0.10


def _finite_array(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    return arr[np.isfinite(arr)]


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float | None:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2 or len(x) != len(y):
        return None
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    var_x = float(np.sum((x - x_mean) ** 2))
    if var_x <= 0:
        return None
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / var_x)
    if not math.isfinite(slope):
        return None
    return slope


def _log_returns(prices) -> np.ndarray | None:
    p = _finite_array(prices)
    if len(p) < 2 or np.any(p <= 0):
        return None
    r = np.diff(np.log(p))
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return None
    return r


def hurst_H(prices) -> float | None:
    """OLS H from ln(M_k) ~ ln(k). None when fewer than 3 valid horizons."""
    r = _log_returns(prices)
    if r is None:
        return None
    t = len(r)
    xs: list[float] = []
    ys: list[float] = []
    for k in HORIZONS:
        n_blocks = t // k
        if n_blocks < 2:
            continue
        blocks = r[: n_blocks * k].reshape(n_blocks, k)
        moves = np.abs(blocks.sum(axis=1))
        mk = float(moves.mean())
        if mk <= 0 or not math.isfinite(mk):
            continue
        xs.append(math.log(float(k)))
        ys.append(math.log(mk))
    if len(xs) < 3:
        return None
    return _ols_slope(np.asarray(xs), np.asarray(ys))


def hurst_D(prices) -> float | None:
    """D = 2 − H. None when H cannot be estimated."""
    h = hurst_H(prices)
    if h is None:
        return None
    d = 2.0 - h
    if not math.isfinite(d):
        return None
    return float(d)


def simple_move_pct(prices) -> float | None:
    """Raw price move % over the window: last/first − 1. SPEC: simple %, not a win rate."""
    p = _finite_array(prices)
    if len(p) < 2 or p[0] == 0:
        return None
    move = (float(p[-1]) / float(p[0]) - 1.0) * 100.0
    if not math.isfinite(move):
        return None
    return move


def reading(d: float | None, move_pct: float | None) -> str | None:
    """Label bands from SPEC 25/27. Flat + low D is not FRAGILE."""
    if d is None:
        return None
    abs_move = abs(move_pct) if move_pct is not None else 0.0
    if d <= FRAGILE_D and abs_move > FRAGILE_MOVE:
        return "FRAGILE"
    if d <= 1.50:
        return "orderly"
    if d < 1.70:
        return "near-random"
    if d < 1.85:
        return "choppy"
    return "max chop"


def _round(val: float | None, digits: int) -> float | None:
    if val is None or not math.isfinite(val):
        return None
    return round(float(val), digits)


def window_pack(closes, n: int) -> dict:
    """D / move / read for closes[-n:]. Nulls when the window is short, gappy, or D is NaN."""
    arr = np.asarray(closes, dtype=float).reshape(-1)
    if len(arr) < n:
        return {"d": None, "h": None, "move": None, "read": None}
    window = arr[-n:]
    if np.any(~np.isfinite(window)) or np.any(window <= 0):
        return {"d": None, "h": None, "move": None, "read": None}
    d = hurst_D(window)
    h = hurst_H(window)
    move = simple_move_pct(window)
    return {
        "d": _round(d, 4),
        "h": _round(h, 4),
        "move": _round(move, 2),
        "read": reading(d, move),
    }


def _prior_closes(closes, n: int):
    arr = np.asarray(closes, dtype=float).reshape(-1)
    if len(arr) < n + 1:
        return None
    return arr[-(n + 1) : -1]


def _daily_closes(symbol: str, limit: int = 260) -> np.ndarray:
    df = md.get_ohlcv_df(symbol, "daily", limit=limit)
    if df is None or df.empty or "close" not in df.columns:
        return np.asarray([], dtype=float)
    return np.asarray(df["close"].astype(float), dtype=float)


def _scan_symbols(desk: bool = True) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    rows: Iterable = []
    try:
        rows = md.list_desk_symbols() if desk else md.list_symbols()
    except Exception:
        rows = []
    for row in rows or []:
        sym = str((row or {}).get("symbol") or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    for sym in CORE_INDEX:
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def measure_symbol(symbol: str, closes=None) -> dict | None:
    """One scan row from stored (or supplied) daily closes. Null D if estimator fails."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    p = np.asarray(closes, dtype=float).reshape(-1) if closes is not None else _daily_closes(sym)
    if len(p) < 2 or not np.any(np.isfinite(p)):
        return None
    w65 = window_pack(p, WIN_65)
    w130 = window_pack(p, WIN_130)
    read = w65["read"] or w130["read"]
    tags: list[str] = []
    if read == "FRAGILE":
        tags.append("FRAGILE")

    prior65 = _prior_closes(p, WIN_65)
    if prior65 is not None and w65["d"] is not None:
        prev = window_pack(prior65, WIN_65)
        if (
            prev["d"] is not None
            and w65["d"] <= FRAGILE_D
            and abs(w65["move"] or 0) > FRAGILE_MOVE
            and prev["d"] > FRAGILE_D
        ):
            tags.append("new_fragile")
        if prev["d"] is not None and (prev["d"] - w65["d"]) >= COLLAPSE_D:
            tags.append("sharp_collapse_65")

    prior130 = _prior_closes(p, WIN_130)
    if prior130 is not None and w130["d"] is not None:
        prev = window_pack(prior130, WIN_130)
        if prev["d"] is not None and (prev["d"] - w130["d"]) >= COLLAPSE_D:
            tags.append("sharp_collapse_130")

    return {
        "symbol": sym,
        "d_65d": w65["d"],
        "d_130d": w130["d"],
        "move_65d": w65["move"],
        "move_130d": w130["move"],
        "read": read,
        "tags": tags,
        "bars": int(len(p)),
    }


def status() -> dict:
    return {
        "available": True,
        "source": SOURCE,
        "expected": SOURCE,
        "reason": NOTE,
        "note": NOTE,
    }


def scan(*, desk: bool = True) -> dict:
    """GET /api/fractal/scan — desk watchlist + core indices, stored closes only."""
    rows = []
    for sym in _scan_symbols(desk=desk):
        row = measure_symbol(sym)
        if row is None:
            continue
        rows.append(row)
    return {
        **status(),
        "columns": COLUMNS,
        "rows": rows,
        "message": NOTE,
        "count": len(rows),
    }


def empty_scan() -> dict:
    return {
        **status(),
        "columns": COLUMNS,
        "rows": [],
        "message": NOTE,
        "count": 0,
    }
