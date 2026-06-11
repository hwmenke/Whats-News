"""
signal_scanner.py — pluggable signal routines scanned across the watchlist.

Each routine is a small function over a symbol's quant-lab state frame (plus
the KNN and mean-reversion model outputs) that either fires a signal or stays
quiet.  Routines are registered with @_routine, so adding a new scanner is one
decorated function — the API, caching, and UI pick it up automatically.

A fired signal:
    { "routine": id, "label": ..., "side": "bull"|"bear"|"watch",
      "strength": 0-100, "detail": human-readable trigger explanation }

scan_symbols() fans out across symbols with a thread pool; per-symbol results
are cached via indicator_cache and invalidated when new OHLCV data arrives.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np

import database as db
import indicator_cache as cache
import quant_lab as ql

SCAN_BARS = 800
MIN_BARS  = ql.MIN_BARS

ROUTINES: list[dict] = []


def _routine(rid: str, label: str, desc: str):
    def deco(fn):
        ROUTINES.append({"id": rid, "label": label, "desc": desc, "fn": fn})
        return fn
    return deco


def routine_catalog() -> list[dict]:
    return [{"id": r["id"], "label": r["label"], "desc": r["desc"]}
            for r in ROUTINES]


# ── helpers ───────────────────────────────────────────────────────────────────

def _last(st, col, default=np.nan) -> float:
    v = st[col].iloc[-1]
    return float(v) if np.isfinite(v) else default


def _crossed_sign(series, lookback: int = 3):
    """+1 / -1 if the sign flipped to that side within the last `lookback`
    bars (and is non-zero now), else 0."""
    tail = series.iloc[-(lookback + 1):].values
    if len(tail) < 2 or not np.isfinite(tail).all():
        return 0
    now = np.sign(tail[-1])
    if now == 0:
        return 0
    return int(now) if any(np.sign(v) != now for v in tail[:-1]) else 0


# ── routines ──────────────────────────────────────────────────────────────────

@_routine("val_extreme", "VALUATION EXTREME",
          "Composite valuation score beyond ±60 — deeply cheap or rich vs its own history")
def _r_val_extreme(ctx):
    v = _last(ctx["st"], "val_score")
    if not np.isfinite(v) or abs(v) < 60:
        return None
    return {"side": "bull" if v < 0 else "bear",
            "strength": min(abs(v), 100),
            "detail": f"valuation {v:+.0f} ({'CHEAP' if v < 0 else 'RICH'})"}


@_routine("cheap_reversal", "VALUE + TURN",
          "Cheap (≤ −30) with the fast EWMAC just flipping positive — or the rich/bearish mirror")
def _r_cheap_reversal(ctx):
    st = ctx["st"]
    v  = _last(st, "val_score")
    x  = _crossed_sign(st["ewmac_8"], 3)
    if np.isfinite(v) and v <= -30 and x > 0:
        return {"side": "bull", "strength": min(abs(v) + 20, 100),
                "detail": f"valuation {v:+.0f} and fast trend turned up"}
    if np.isfinite(v) and v >= 30 and x < 0:
        return {"side": "bear", "strength": min(abs(v) + 20, 100),
                "detail": f"valuation {v:+.0f} and fast trend turned down"}
    return None


@_routine("cta_flip", "TREND FLIP",
          "Combined 3-speed CTA forecast changed sign within the last 2 bars")
def _r_cta_flip(ctx):
    st = ctx["st"]
    x  = _crossed_sign(st["cta_fc"], 2)
    s  = _last(st, "cta_score")
    if x == 0 or not np.isfinite(s) or abs(s) < 20:
        return None
    return {"side": "bull" if x > 0 else "bear",
            "strength": min(abs(s), 100),
            "detail": f"CTA forecast flipped to {s:+.0f}"}


@_routine("exh_event", "EXHAUSTION",
          "Exhaustion composite beyond ±70 — blow-off (fade) or capitulation (buy)")
def _r_exh_event(ctx):
    e = _last(ctx["st"], "exh_score")
    if not np.isfinite(e) or abs(e) < 70:
        return None
    return {"side": "bull" if e < 0 else "bear",
            "strength": min(abs(e), 100),
            "detail": f"{'capitulation' if e < 0 else 'blow-off'} reading {e:+.0f}"}


@_routine("squeeze_alert", "SQUEEZE",
          "Volatility compression ≥ 85th percentile — expansion likely; direction from trend")
def _r_squeeze(ctx):
    st = ctx["st"]
    sq = _last(st, "squeeze")
    if not np.isfinite(sq) or sq < 85:
        return None
    tr = _last(st, "ewmac_16", 0.0)
    return {"side": "watch",
            "strength": min(sq, 100),
            "detail": f"compression {sq:.0f}/100, trend filter {'LONG' if tr > 0 else 'SHORT' if tr < 0 else 'FLAT'}"}


@_routine("hi_lo_break", "52W BREAK",
          "New 252-bar closing high/low with above-average participation")
def _r_hi_lo_break(ctx):
    st = ctx["st"]
    close = st["close"]
    if len(close) < 253:
        return None
    window = close.iloc[-252:]
    c   = float(close.iloc[-1])
    vz  = _last(st, "volume_z", 0.0)
    if c >= float(window.max()) and vz > 0.5:
        return {"side": "bull", "strength": min(60 + vz * 10, 100),
                "detail": f"new 52w closing high, volume z {vz:+.1f}"}
    if c <= float(window.min()) and vz > 0.5:
        return {"side": "bear", "strength": min(60 + vz * 10, 100),
                "detail": f"new 52w closing low, volume z {vz:+.1f}"}
    return None


@_routine("knn_skew", "ANALOG SKEW",
          "KNN analogs strongly one-sided: P(up, 1w) ≥ 70% or ≤ 30%")
def _r_knn_skew(ctx):
    knn = ctx["knn"]
    if not knn or knn.get("k", 0) < 15:
        return None
    h5 = next((h for h in knn["horizons"] if h["h"] == 5), None)
    if not h5 or h5["p_up"] is None:
        return None
    p = h5["p_up"]
    if p >= 0.70:
        return {"side": "bull", "strength": min(p * 100, 100),
                "detail": f"{knn['k']} analogs: P(up,1w) {p:.0%}, median {h5['median']:+.1%}"}
    if p <= 0.30:
        return {"side": "bear", "strength": min((1 - p) * 100, 100),
                "detail": f"{knn['k']} analogs: P(up,1w) {p:.0%}, median {h5['median']:+.1%}"}
    return None


@_routine("mr_stretch", "MR STRETCH",
          "Mean-reverting character with the trend-channel residual beyond ±2σ")
def _r_mr_stretch(ctx):
    mr = ctx["mr"]
    if not mr or mr["character"] != "MEAN-REVERTING":
        return None
    z = mr.get("resid_z")
    if z is None or abs(z) < 2.0:
        return None
    return {"side": "bull" if z < 0 else "bear",
            "strength": min(abs(z) * 30, 100),
            "detail": (f"residual {z:+.1f}σ, half-life {mr['half_life']:.0f} bars, "
                       f"revert hit {mr['revert_hit']:.0%}" if mr.get("revert_hit") is not None
                       else f"residual {z:+.1f}σ, half-life {mr['half_life']:.0f} bars")}


@_routine("vol_climax", "VOLUME CLIMAX",
          "Volume z-score ≥ 2.5 in the direction of the day — possible terminal bar")
def _r_vol_climax(ctx):
    vc = _last(ctx["st"], "vol_climax")
    if not np.isfinite(vc) or abs(vc) < 2.5:
        return None
    return {"side": "watch",
            "strength": min(abs(vc) * 30, 100),
            "detail": f"signed volume climax {vc:+.1f} ({'buying' if vc > 0 else 'selling'} crescendo)"}


@_routine("td9", "TD-9 COUNT",
          "TD-sequential-style count reached ±9 — classic setup completion")
def _r_td9(ctx):
    td = _last(ctx["st"], "td") * 6.5
    if not np.isfinite(td) or abs(td) < 9:
        return None
    return {"side": "bull" if td < 0 else "bear",
            "strength": min(abs(td) / 13 * 100, 100),
            "detail": f"{'sell' if td > 0 else 'buy'} setup count {td:+.0f}"}


# ── scanning ──────────────────────────────────────────────────────────────────

def _scan_one_inner(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=SCAN_BARS)
    if df.empty or len(df) < MIN_BARS:
        return {"symbol": symbol, "skipped": f"need ≥ {MIN_BARS} bars", "signals": []}

    st  = ql._state_frame(df)
    ctx = {"st": st, "knn": ql._knn(st), "mr": ql._mean_reversion(st)}

    date  = st.index[-1].strftime("%Y-%m-%d")
    price = ql._fl(st["close"].iloc[-1], 4)
    out = []
    for r in ROUTINES:
        try:
            hit = r["fn"](ctx)
        except Exception as exc:           # one broken routine must not kill the scan
            hit = None
            out.append({"routine": r["id"], "label": r["label"], "side": "watch",
                        "strength": 0, "detail": f"routine error: {exc}",
                        "symbol": symbol, "date": date, "price": price,
                        "error": True})
        if hit:
            out.append({**hit,
                        "routine": r["id"], "label": r["label"],
                        "symbol": symbol, "date": date, "price": price,
                        "strength": round(float(hit["strength"]), 1)})
    return {"symbol": symbol, "signals": out}


def _scan_one(symbol: str) -> dict:
    return cache.get_or_compute("signal_scan", symbol, "daily",
                                lambda: _scan_one_inner(symbol))


def scan_symbols(symbols: list[str] | None = None,
                 routines: list[str] | None = None) -> dict:
    if symbols is None:
        symbols = [s["symbol"] for s in db.list_symbols()]
    symbols = [s.upper() for s in symbols]
    if not symbols:
        return {"signals": [], "routines": routine_catalog(),
                "n_symbols": 0, "skipped": []}

    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as pool:
        for res in pool.map(_scan_one, symbols):
            results.append(res)

    wanted  = set(routines) if routines else None
    signals = [sig for r in results for sig in r.get("signals", [])
               if wanted is None or sig["routine"] in wanted]
    signals.sort(key=lambda s2: -s2["strength"])

    counts = {}
    for sig in signals:
        counts[sig["routine"]] = counts.get(sig["routine"], 0) + 1
    catalog = [{**r, "count": counts.get(r["id"], 0)} for r in routine_catalog()]

    return {
        "signals":   signals,
        "routines":  catalog,
        "n_symbols": len(symbols),
        "skipped":   [{"symbol": r["symbol"], "reason": r["skipped"]}
                      for r in results if r.get("skipped")],
    }
