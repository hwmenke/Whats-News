"""
vol_momentum.py — Vol-Adjusted Cross-Sectional Momentum with Turnover Brake

Implements, for every symbol i in the watchlist universe U:

  Vol-adjusted momentum:   S_i = M_i / (Std(r_{t-L:t}) + eps)
  Cross-sectional rank:    Rank_i = rank of S_i within U (1 = strongest)
  Target weight:           w*_i ∝ S_i   s.t.  Σ w* = 0,  Σ|w*| ≤ L_max
  Required change:         Δw_i = w*_i − w_prev_i
  Estimated trading cost:  Cost_i = |Δw_i| · (Spread + Impact + Fee)
  Expected signal gain:    Gain_i = |Δw_i| · |S_i − S_prev_i|

Decision cascade (first match wins):
  1. No-trade band:   |Δw_i| < δ_w  or  |S_i − S_prev_i| < δ_S  → keep position
  2. Turnover brake:  Gain_i ≤ κ·Cost_i                          → keep position
  3. Trade:           w_new_i = w_prev_i + λ·Δw_i   (0 < λ ≤ 1)
       basket: S_i >  τ → LONG,  S_i < −τ → SHORT,  else NEUTRAL

Previous weights/signals persist in the `vol_mom_state` table so Δw and
S_prev are meaningful across runs. GET computes a dry-run; POST /apply
commits the partial-adjusted weights as the new state.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

import database as db

EPS = 1e-4

DEFAULTS = {
    "mom_lb":     126,   # momentum lookback (bars)
    "skip":       5,     # skip most recent bars (short-term reversal guard)
    "vol_lb":     63,    # realized-vol lookback (bars), annualized ×√252
    "l_max":      1.0,   # gross leverage cap Σ|w| ≤ L_max
    "kappa":      1.0,   # turnover-brake cost multiplier κ
    "tau":        0.5,   # basket threshold τ on S
    "lam":        0.5,   # partial adjustment λ, 0 < λ ≤ 1
    "delta_w":    0.005, # no-trade band on |Δw|
    "delta_s":    0.05,  # no-trade band on |S − S_prev|
    "spread_bps": 5.0,
    "impact_bps": 10.0,
    "fee_bps":    1.0,
}


def _round(v, n=4):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return round(f, n)


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    conn = db.get_connection()
    rows = conn.execute("SELECT symbol, weight, signal FROM vol_mom_state").fetchall()
    conn.close()
    return {r["symbol"]: {"weight": r["weight"], "signal": r["signal"]} for r in rows}


def save_state(weights: dict) -> int:
    """Persist {symbol: (weight, signal)} as the new previous-state. Returns count."""
    now  = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    for sym, (w, s) in weights.items():
        conn.execute(
            """
            INSERT INTO vol_mom_state (symbol, weight, signal, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                weight = excluded.weight,
                signal = excluded.signal,
                updated_at = excluded.updated_at
            """,
            (sym, float(w), float(s), now),
        )
    conn.commit()
    conn.close()
    return len(weights)


def reset_state() -> int:
    conn = db.get_connection()
    cur  = conn.execute("DELETE FROM vol_mom_state")
    conn.commit()
    conn.close()
    return cur.rowcount


# ── Signal computation ────────────────────────────────────────────────────────

def _signal_for(sym: str, mom_lb: int, skip: int, vol_lb: int):
    """Return (S, momentum, ann_vol, price) or None if not enough data."""
    need = mom_lb + skip + 2
    df = db.get_ohlcv_df(sym, "daily", limit=need + 40)
    if df.empty or len(df) < need:
        return None
    close = df["close"].astype(float)
    if skip > 0:
        close = close.iloc[:-skip]
    if len(close) < mom_lb + 1:
        return None

    price = float(close.iloc[-1])
    past  = float(close.iloc[-(mom_lb + 1)])
    if past <= 0 or price <= 0:
        return None
    mom = price / past - 1.0

    rets = close.pct_change().dropna().iloc[-vol_lb:]
    if len(rets) < max(10, vol_lb // 2):
        return None
    ann_vol = float(rets.std()) * np.sqrt(252.0)

    s = mom / (ann_vol + EPS)
    return s, mom, ann_vol, float(df["close"].iloc[-1])


def compute_vol_momentum(params: dict | None = None) -> dict:
    """Dry-run computation for the whole watchlist. Does not mutate state."""
    p = {**DEFAULTS, **(params or {})}
    if not (0 < p["lam"] <= 1):
        return {"error": "lam must be in (0, 1]"}
    if p["l_max"] <= 0:
        return {"error": "l_max must be positive"}

    syms_meta = db.list_symbols()
    if not syms_meta:
        return {"error": "No symbols in watchlist"}

    state = _load_state()
    cost_rate = (p["spread_bps"] + p["impact_bps"] + p["fee_bps"]) / 1e4

    computed, skipped = [], []
    for meta in syms_meta:
        sym = meta["symbol"]
        sig = _signal_for(sym, int(p["mom_lb"]), int(p["skip"]), int(p["vol_lb"]))
        if sig is None:
            skipped.append(sym)
            continue
        s, mom, vol, price = sig
        computed.append({"symbol": sym, "s": s, "mom": mom, "vol": vol, "price": price})

    if len(computed) < 2:
        return {"error": "Need at least 2 symbols with enough history "
                         f"({int(p['mom_lb']) + int(p['skip'])}+ daily bars). "
                         "Fetch more data first.", "skipped": skipped}

    # Cross-sectional rank (1 = strongest S)
    order = sorted(computed, key=lambda r: r["s"], reverse=True)
    for i, r in enumerate(order):
        r["rank"] = i + 1

    # Target weights: demeaned S, scaled to gross = L_max (⇒ Σw* = 0, Σ|w*| = L_max)
    s_arr  = np.array([r["s"] for r in computed])
    s_dm   = s_arr - s_arr.mean()
    gross  = np.abs(s_dm).sum()
    w_star = s_dm * (p["l_max"] / gross) if gross > 1e-12 else np.zeros_like(s_dm)

    rows = []
    turnover = 0.0
    for r, wt in zip(computed, w_star):
        sym    = r["symbol"]
        prev   = state.get(sym, {})
        w_prev = float(prev.get("weight") or 0.0)
        s_prev = float(prev.get("signal") or 0.0)

        dw   = float(wt) - w_prev
        ds   = r["s"] - s_prev
        cost = abs(dw) * cost_rate
        gain = abs(dw) * abs(ds)

        # Decision cascade — order matters
        if abs(dw) < p["delta_w"] or abs(ds) < p["delta_s"]:
            decision, w_new = "NO_TRADE_BAND", w_prev
        elif gain <= p["kappa"] * cost:
            decision, w_new = "BRAKE", w_prev
        else:
            decision = "TRADE"
            w_new    = w_prev + p["lam"] * dw
            turnover += abs(w_new - w_prev)

        if decision == "TRADE" and r["s"] > p["tau"]:
            basket = "LONG"
        elif decision == "TRADE" and r["s"] < -p["tau"]:
            basket = "SHORT"
        elif decision == "TRADE":
            basket = "NEUTRAL"
        else:
            basket = "HOLD"

        rows.append({
            "symbol":   sym,
            "price":    _round(r["price"], 2),
            "mom":      _round(r["mom"]),
            "vol":      _round(r["vol"]),
            "s":        _round(r["s"]),
            "s_prev":   _round(s_prev),
            "ds":       _round(ds),
            "rank":     r["rank"],
            "w_prev":   _round(w_prev),
            "w_target": _round(float(wt)),
            "dw":       _round(dw),
            "cost":     _round(cost, 6),
            "gain":     _round(gain, 6),
            "decision": decision,
            "basket":   basket,
            "w_new":    _round(w_new),
        })

    rows.sort(key=lambda r: r["rank"])
    new_w   = np.array([r["w_new"] or 0.0 for r in rows])
    n_trade = sum(1 for r in rows if r["decision"] == "TRADE")

    return {
        "params":  p,
        "rows":    rows,
        "skipped": skipped,
        "summary": {
            "n":        len(rows),
            "n_traded": n_trade,
            "n_long":   sum(1 for r in rows if r["basket"] == "LONG"),
            "n_short":  sum(1 for r in rows if r["basket"] == "SHORT"),
            "gross":    _round(np.abs(new_w).sum()),
            "net":      _round(new_w.sum()),
            "turnover": _round(turnover),
            "est_cost": _round(sum(r["cost"] or 0 for r in rows if r["decision"] == "TRADE"), 6),
        },
    }


def apply_vol_momentum(params: dict | None = None) -> dict:
    """Compute, then persist w_new/S as the new previous-state for every row."""
    result = compute_vol_momentum(params)
    if "error" in result:
        return result
    saved = save_state({r["symbol"]: (r["w_new"] or 0.0, r["s"] or 0.0)
                        for r in result["rows"]})
    result["applied"] = saved
    return result
