"""
risk.py — Risk-first position sizing for the momentum journal.

Pure functions (no DB access). The journal entry form and the
/api/risk/size endpoint both call position_size() so the sizing
the user sees is exactly what gets stored.

Sign convention: long stop is below entry, short stop is above entry,
but we only ever use abs(entry - stop) for the 1R distance, so either
direction works.
"""

import math


def position_size(equity, risk_pct, entry, stop, direction="long",
                  whole_shares=True):
    """
    Compute how many shares to buy so that being stopped out costs
    `risk_pct` percent of `equity`.

    Returns a dict with the sizing breakdown, or {"error": ...} when the
    inputs are invalid (e.g. entry == stop -> infinite size).
    """
    try:
        equity   = float(equity)
        risk_pct = float(risk_pct)
        entry    = float(entry)
        stop     = float(stop)
    except (TypeError, ValueError):
        return {"error": "equity, risk_pct, entry and stop must be numbers"}

    if equity <= 0:
        return {"error": "equity must be positive"}
    if risk_pct <= 0:
        return {"error": "risk_pct must be positive"}
    if entry <= 0:
        return {"error": "entry must be positive"}

    risk_per_share = abs(entry - stop)
    if risk_per_share < 1e-9:
        return {"error": "entry and stop are too close (risk per share is zero)"}

    direction = (direction or "long").lower()
    # Soft validation — warn but don't block (some setups invert the stop).
    warning = None
    if direction == "long" and stop > entry:
        warning = "stop is above entry for a long trade"
    elif direction == "short" and stop < entry:
        warning = "stop is below entry for a short trade"

    dollar_risk = equity * (risk_pct / 100.0)
    raw_shares  = dollar_risk / risk_per_share
    shares      = math.floor(raw_shares) if whole_shares else round(raw_shares, 4)

    position_value = shares * entry
    pct_of_equity  = (position_value / equity * 100.0) if equity else 0.0

    return {
        "direction":      direction,
        "equity":         round(equity, 2),
        "risk_pct":       round(risk_pct, 4),
        "dollar_risk":    round(dollar_risk, 2),
        "risk_per_share": round(risk_per_share, 4),
        "shares":         shares,
        "position_value": round(position_value, 2),
        "pct_of_equity":  round(pct_of_equity, 2),
        "warning":        warning,
    }


def portfolio_heat(open_trades, equity):
    """
    Total open risk if every open stop were hit, as a % of equity.

    `open_trades` is an iterable of dicts with at least
    entry_price, stop_price and shares.
    """
    try:
        equity = float(equity)
    except (TypeError, ValueError):
        equity = 0.0

    total_risk = 0.0
    for t in open_trades:
        try:
            entry  = float(t.get("entry_price"))
            stop   = float(t.get("stop_price"))
            shares = float(t.get("shares") or 0)
        except (TypeError, ValueError):
            continue
        total_risk += abs(entry - stop) * shares

    heat_pct = (total_risk / equity * 100.0) if equity > 0 else None
    return {
        "open_risk_dollars": round(total_risk, 2),
        "heat_pct":          round(heat_pct, 2) if heat_pct is not None else None,
    }
