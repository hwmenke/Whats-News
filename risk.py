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

# Position / exposure caps from the process doc
NORMAL_POSITION_PCT = 20.0    # normal single position is 10-20% of equity
MAX_OVERNIGHT_PCT   = 30.0    # avoid > ~30% of equity overnight in one name
MAX_PORTFOLIO_HEAT  = 5.0     # max total open risk if every stop is hit (%)


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

    # Cap the suggested size so a tight stop can't imply an oversized position.
    max_value      = equity * (MAX_OVERNIGHT_PCT / 100.0)
    capped_shares  = shares
    if position_value > max_value and entry > 0:
        capped_shares = math.floor(max_value / entry) if whole_shares else round(max_value / entry, 4)

    warnings = []
    if warning:
        warnings.append(warning)
    if pct_of_equity > MAX_OVERNIGHT_PCT:
        warnings.append(
            f"position is {pct_of_equity:.0f}% of equity — exceeds the "
            f"{MAX_OVERNIGHT_PCT:.0f}% overnight cap (capped to {capped_shares} sh)")
    elif pct_of_equity > NORMAL_POSITION_PCT:
        warnings.append(
            f"position is {pct_of_equity:.0f}% of equity — above the normal "
            f"{NORMAL_POSITION_PCT:.0f}% size")

    return {
        "direction":      direction,
        "equity":         round(equity, 2),
        "risk_pct":       round(risk_pct, 4),
        "dollar_risk":    round(dollar_risk, 2),
        "risk_per_share": round(risk_per_share, 4),
        "shares":         shares,
        "capped_shares":  capped_shares,
        "position_value": round(position_value, 2),
        "pct_of_equity":  round(pct_of_equity, 2),
        "exceeds_position_cap": pct_of_equity > MAX_OVERNIGHT_PCT,
        # Back-compat: single string for older callers; full list for new UI.
        "warning":        warnings[0] if warnings else None,
        "warnings":       warnings,
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
        "heat_warning":      (heat_pct is not None and heat_pct > MAX_PORTFOLIO_HEAT),
    }
