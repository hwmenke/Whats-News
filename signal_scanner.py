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
import pandas as pd

import database as db
import fair_value_lab as fvl
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


@_routine("td9", "TD-9 SETUP",
          "TD-sequential-style count reached ±9 — setup completion zone (9–12)")
def _r_td9(ctx):
    td = _last(ctx["st"], "td") * 6.5
    if not np.isfinite(td) or abs(td) < 9 or abs(td) >= 13:
        return None
    return {"side": "bull" if td < 0 else "bear",
            "strength": min(abs(td) / 13 * 100, 100),
            "detail": f"{'sell' if td > 0 else 'buy'} setup count {td:+.0f}"}


@_routine("td13", "TD-13 EXHAUSTION",
          "TD-sequential-style count hit the ±13 cap — full countdown exhaustion")
def _r_td13(ctx):
    td = _last(ctx["st"], "td") * 6.5
    if not np.isfinite(td) or abs(td) < 13:
        return None
    return {"side": "bull" if td < 0 else "bear",
            "strength": 100,
            "detail": f"count exhausted at {td:+.0f} — {'sell' if td > 0 else 'buy'} countdown complete"}


@_routine("pca_divergence", "PCA DIVERGENCE",
          "Price ≥ 2σ away from its PCA eigenportfolio factor anchor (stat-arb residual)")
def _r_pca_divergence(ctx):
    try:
        pca = fvl.pca_divergence(ctx["symbol"])
    except Exception:
        return None
    if not pca or abs(pca["z"]) < 2.0:
        return None
    z = pca["z"]
    return {"side": "bull" if z < 0 else "bear",
            "strength": min(abs(z) * 30, 100),
            "detail": f"{z:+.1f}σ vs PCA factor anchor ({pca['n_universe']}-asset panel)"}


# ── scanning ──────────────────────────────────────────────────────────────────

def _scan_one_inner(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=SCAN_BARS)
    if df.empty or len(df) < MIN_BARS:
        return {"symbol": symbol, "skipped": f"need ≥ {MIN_BARS} bars", "signals": []}

    st  = ql._state_frame(df)
    ctx = {"symbol": symbol, "st": st,
           "knn": ql._knn(st), "mr": ql._mean_reversion(st)}

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

    all_signals = [sig for r in results for sig in r.get("signals", [])]
    try:  # journal every clean fire so routines build a live track record
        journaled = db.record_signals([s2 for s2 in all_signals if not s2.get("error")])
    except Exception:
        journaled = 0

    wanted  = set(routines) if routines else None
    signals = [sig for sig in all_signals
               if wanted is None or sig["routine"] in wanted]
    signals.sort(key=lambda s2: -s2["strength"])

    counts = {}
    for sig in signals:
        if not sig.get("error"):
            counts[sig["routine"]] = counts.get(sig["routine"], 0) + 1
    catalog = [{**r, "count": counts.get(r["id"], 0)} for r in routine_catalog()]

    return {
        "signals":   signals,
        "routines":  catalog,
        "n_symbols": len(symbols),
        "journaled_new": journaled,
        "skipped":   [{"symbol": r["symbol"], "reason": r["skipped"]}
                      for r in results if r.get("skipped")],
    }


# ── track record: historical event study + live journal ──────────────────────
#
# Two views of "does this routine work?":
#   hist  Each routine's firing rule is re-evaluated over a symbol's full
#         history (vectorised, 10-bar cool-off) and forward 1W/1M returns
#         measured, direction-adjusted (bull +ret, bear −ret).  KNN / PCA
#         routines are live-only (too heavy to replay bar by bar).
#   live  Forward returns of the signals actually journaled by past scans.

TRACK_H = (5, 21)


def _crossed_series(s, lookback: int = 3):
    """+1/-1 where sign flipped to that side within `lookback` bars, else 0."""
    sg = np.sign(s)
    changed = pd.Series(False, index=s.index)
    for k in range(1, lookback + 1):
        changed |= sg.shift(k).ne(sg)
    return (sg * changed).fillna(0.0)


def _hist_events(st, mr) -> dict:
    """{routine_id: (fire_mask, side_series)} on st.index. side: +1/-1."""
    out = {}
    v   = st["val_score"]
    out["val_extreme"] = (v.abs() >= 60, -np.sign(v))

    x8 = _crossed_series(st["ewmac_8"], 3)
    out["cheap_reversal"] = (((v <= -30) & (x8 > 0)) | ((v >= 30) & (x8 < 0)),
                             np.sign(x8))

    xf = _crossed_series(st["cta_fc"], 2)
    out["cta_flip"] = ((xf != 0) & (st["cta_score"].abs() >= 20), np.sign(xf))

    e = st["exh_score"]
    out["exh_event"] = (e.abs() >= 70, -np.sign(e))

    # squeeze is direction-agnostic; trade it with the trend filter's side
    sq = st["squeeze"]
    out["squeeze_alert"] = ((sq >= 85) & (sq.shift(1) < 85),
                            np.sign(st["ewmac_16"]).fillna(0.0))

    close = st["close"]
    hi = close.rolling(252, min_periods=252).max()
    lo = close.rolling(252, min_periods=252).min()
    vz = st["volume_z"]
    brk = ((close >= hi) & (vz > 0.5)) | ((close <= lo) & (vz > 0.5))
    out["hi_lo_break"] = (brk, np.where(close >= hi, 1.0, -1.0))

    vc = st["vol_climax"]
    out["vol_climax"] = (vc.abs() >= 2.5, -np.sign(vc))   # contrarian read

    td = st["td"] * 6.5
    out["td9"]  = ((td.abs() >= 9) & (td.abs() < 13), -np.sign(td))
    out["td13"] = (td.abs() >= 13, -np.sign(td))

    if mr and mr.get("character") == "MEAN-REVERTING":
        rz = st["resid_z"]
        out["mr_stretch"] = (rz.abs() >= 2.0, -np.sign(rz))
    return out


def _track_one_inner(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=SCAN_BARS)
    if df.empty or len(df) < MIN_BARS:
        return {}
    st = ql._state_frame(df)
    mr = ql._mean_reversion(st)
    close = st["close"].values
    n = len(close)
    fwd = {h: np.r_[close[h:] / close[:-h] - 1.0, [np.nan] * h] for h in TRACK_H}

    stats: dict = {}
    for rid, (fire, side) in _hist_events(st, mr).items():
        f = np.asarray(fire.values if hasattr(fire, "values") else fire, dtype=bool)
        s = np.asarray(side.values if hasattr(side, "values") else side, dtype=float)
        rets = {h: [] for h in TRACK_H}
        last = -10_000
        for i in range(n):
            if not f[i] or not np.isfinite(s[i]) or s[i] == 0 or i - last < 10:
                continue
            last = i
            for h in TRACK_H:
                r = fwd[h][i]
                if np.isfinite(r):
                    rets[h].append(s[i] * r)              # direction-adjusted
        stats[rid] = {h: rets[h] for h in TRACK_H}
    return stats


def _track_one(symbol: str) -> dict:
    return cache.get_or_compute("track_record", symbol, "daily",
                                lambda: _track_one_inner(symbol))


def _journal_stats() -> dict:
    """Realised forward returns of journaled signals, by routine."""
    rows = db.get_signal_journal()
    by_routine: dict = {}
    closes: dict = {}
    for row in rows:
        sym = row["symbol"]
        if sym not in closes:
            df = db.get_ohlcv_df(sym, "daily", limit=2500)
            closes[sym] = df["close"] if not df.empty else None
        ser = closes[sym]
        rec = by_routine.setdefault(row["routine"], {"n": 0, "adj5": [], "adj21": []})
        rec["n"] += 1
        if ser is None or row["side"] not in ("bull", "bear"):
            continue
        try:
            pos = ser.index.get_loc(pd.Timestamp(row["date"]))
        except KeyError:
            continue
        sgn = 1.0 if row["side"] == "bull" else -1.0
        for h, key in ((5, "adj5"), (21, "adj21")):
            if pos + h < len(ser) and ser.iloc[pos] > 0:
                rec[key].append(sgn * (float(ser.iloc[pos + h] / ser.iloc[pos]) - 1.0))
    return by_routine


def track_record(symbols: list[str] | None = None) -> dict:
    """Per-routine report card: historical event study + live journal."""
    if symbols is None:
        symbols = [s["symbol"] for s in db.list_symbols()]
    symbols = [s.upper() for s in symbols]

    agg: dict = {}
    if symbols:
        with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as pool:
            for res in pool.map(_track_one, symbols):
                for rid, per_h in res.items():
                    rec = agg.setdefault(rid, {h: [] for h in TRACK_H})
                    for h in TRACK_H:
                        rec[h].extend(per_h[h])

    live = _journal_stats()

    def _agg_stats(vals):
        a = np.asarray(vals, dtype=float)
        if len(a) == 0:
            return {"n": 0, "hit": None, "avg": None}
        return {"n": int(len(a)), "hit": round(float((a > 0).mean()), 3),
                "avg": round(float(a.mean()), 4)}

    rows = []
    for r in ROUTINES:
        rid = r["id"]
        h5  = _agg_stats(agg.get(rid, {}).get(5, []))
        h21 = _agg_stats(agg.get(rid, {}).get(21, []))
        lv  = live.get(rid, {"n": 0, "adj5": [], "adj21": []})
        rows.append({
            "routine": rid, "label": r["label"],
            "hist": {"h5": h5, "h21": h21,
                     "available": rid not in ("knn_skew", "pca_divergence")},
            "live": {"n": lv["n"],
                     "h5":  _agg_stats(lv["adj5"]),
                     "h21": _agg_stats(lv["adj21"])},
        })
    rows.sort(key=lambda r2: -(r2["hist"]["h21"]["hit"] or 0))
    return {"rows": rows, "n_symbols": len(symbols),
            "n_journal": int(sum(v["n"] for v in live.values()))}
