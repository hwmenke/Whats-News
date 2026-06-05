"""
journal.py — Trade journal CRUD + PnL / R-multiple analytics.

A much-improved, automated version of the Qullamaggie/Stockbee spreadsheet:
Open positions get a live R-multiple from the latest close; closed positions
freeze their realized metrics. compute_trade_metrics() is the single source
of truth for both paths.
"""

from datetime import datetime, timezone

import database as db
import risk as risk


# ── helpers ────────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc).isoformat()


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _latest_close(symbol):
    """Most recent daily close for a symbol, or None if no data stored."""
    df = db.get_ohlcv_df(symbol.upper(), "daily", limit=2)
    if df is None or df.empty:
        return None
    try:
        return float(df["close"].iloc[-1])
    except Exception:
        return None


# ── per-trade metrics ──────────────────────────────────────────────────────────

def compute_trade_metrics(row, current_price=None):
    """
    Given a trade row (dict) and a reference price, compute R-multiple,
    %move, pnl and result. Used live for open trades and frozen for closed.
    """
    direction = (row.get("direction") or "long").lower()
    sign      = -1.0 if direction == "short" else 1.0

    entry  = _num(row.get("entry_price"))
    stop   = _num(row.get("stop_price"))
    shares = _num(row.get("shares"), 0.0) or 0.0
    status = row.get("status", "open")

    # Reference price: exit price if closed, else the live current price.
    if status == "closed":
        px = _num(row.get("exit_price"))
    else:
        px = _num(current_price)
        if px is None:
            px = _latest_close(row.get("symbol", ""))

    risk_per_share    = abs(entry - stop) if (entry is not None and stop is not None) else None
    initial_risk_usd  = (risk_per_share * shares) if risk_per_share else None

    metrics = {
        "current_price":     round(px, 4) if px is not None else None,
        "risk_per_share":    round(risk_per_share, 4) if risk_per_share else None,
        "initial_risk_usd":  round(initial_risk_usd, 2) if initial_risk_usd else None,
        "r_multiple":        None,
        "pct_move":          None,
        "pnl":               None,
        "result":            "holding" if status == "open" else None,
    }

    if px is None or entry is None or entry == 0:
        return metrics

    move_per_share = (px - entry) * sign
    metrics["pct_move"] = round((px - entry) / entry * 100.0 * sign, 2)
    metrics["pnl"]      = round(move_per_share * shares, 2)

    if risk_per_share and risk_per_share > 1e-9:
        r = move_per_share / risk_per_share
        metrics["r_multiple"] = round(r, 2)
        if status == "closed":
            if r > 1e-9:
                metrics["result"] = "win"
            elif r < -1e-9:
                metrics["result"] = "loss"
            else:
                metrics["result"] = "breakeven"
    return metrics


def _management_cues(row, metrics):
    """
    Process-rule cues for an OPEN position (pure, from stored OHLCV):
    time-stop, moving-average trail, partial reminder, stop breach.
    """
    cues = []
    if row.get("status") != "open":
        return cues
    r = metrics.get("r_multiple")

    # Days held
    days_held = None
    try:
        ed = row.get("entry_date")
        if ed:
            d0 = datetime.fromisoformat(str(ed)[:10]).date()
            days_held = (datetime.now(timezone.utc).date() - d0).days
    except Exception:
        pass

    # Price vs 10/20-day moving averages
    below_10ma = below_20ma = None
    try:
        dfr = db.get_ohlcv_df(row.get("symbol", "").upper(), "daily", limit=60)
        if dfr is not None and not dfr.empty and len(dfr) >= 20:
            close = dfr["close"]
            px = float(close.iloc[-1])
            below_10ma = px < float(close.rolling(10).mean().iloc[-1])
            below_20ma = px < float(close.rolling(20).mean().iloc[-1])
    except Exception:
        pass

    if r is not None and r <= -1.0:
        cues.append({"level": "danger", "text": "At/through stop — exit"})
    if r is not None and r >= 2.0:
        cues.append({"level": "good", "text": "+2R — consider taking a partial"})
    if days_held is not None and days_held >= 5 and r is not None and r < 0.5:
        cues.append({"level": "warn", "text": f"Time stop: no progress in {days_held}d"})
    if below_10ma:
        cues.append({"level": "warn", "text": "Below 10-day MA — trail/exit (fast)"})
    elif below_20ma:
        cues.append({"level": "warn", "text": "Below 20-day MA — trail/exit"})

    return cues, days_held


def _enrich(row):
    """Row dict + computed metrics (+ management cues for open trades)."""
    d = dict(row)
    m = compute_trade_metrics(d)
    d.update(m)
    if d.get("status") == "open":
        cues, days_held = _management_cues(d, m)
        d["cues"] = cues
        d["days_held"] = days_held
    return d


# ── CRUD ────────────────────────────────────────────────────────────────────────

_FIELDS = [
    "symbol", "direction", "status", "setup_type", "entry_date", "exit_date",
    "entry_time", "entry_price", "stop_price", "exit_price", "shares",
    "risk_pct", "equity_at_entry", "chart_entry_url", "chart_exit_url", "notes",
]


def add_trade(payload):
    symbol = (payload.get("symbol") or "").strip().upper()
    entry  = _num(payload.get("entry_price"))
    stop   = _num(payload.get("stop_price"))
    if not symbol:
        return {"error": "symbol is required"}
    if entry is None or stop is None:
        return {"error": "entry_price and stop_price are required"}

    direction = (payload.get("direction") or "long").lower()
    if direction not in ("long", "short"):
        return {"error": "direction must be 'long' or 'short'"}

    now = _now()
    conn = db.get_connection()
    cur = conn.execute(
        """
        INSERT INTO trades
            (symbol, direction, status, setup_type, entry_date, entry_time,
             entry_price, stop_price, shares, risk_pct, equity_at_entry,
             chart_entry_url, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            symbol, direction, "open",
            (payload.get("setup_type") or "").strip(),
            payload.get("entry_date") or now[:10],
            (payload.get("entry_time") or "").strip(),
            entry, stop,
            _num(payload.get("shares"), 0.0),
            _num(payload.get("risk_pct")),
            _num(payload.get("equity_at_entry")),
            (payload.get("chart_entry_url") or "").strip(),
            (payload.get("notes") or "").strip(),
            now, now,
        ),
    )
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return get_trade(trade_id)


def get_trade(trade_id):
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": "trade not found"}
    return _enrich(row)


def update_trade(trade_id, payload):
    sets, params = [], []
    for f in _FIELDS:
        if f in payload:
            val = payload[f]
            if f == "symbol" and val:
                val = str(val).strip().upper()
            sets.append(f"{f} = ?")
            params.append(val)
    if not sets:
        return get_trade(trade_id)
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(trade_id)

    conn = db.get_connection()
    conn.execute(f"UPDATE trades SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return get_trade(trade_id)


def close_trade(trade_id, exit_price, exit_date=None, chart_exit_url=None, notes=None):
    exit_price = _num(exit_price)
    if exit_price is None:
        return {"error": "exit_price is required to close a trade"}

    fields = {
        "status":     "closed",
        "exit_price": exit_price,
        "exit_date":  exit_date or _now()[:10],
    }
    if chart_exit_url is not None:
        fields["chart_exit_url"] = str(chart_exit_url).strip()
    if notes is not None:
        fields["notes"] = str(notes).strip()
    return update_trade(trade_id, fields)


def delete_trade(trade_id):
    conn = db.get_connection()
    conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()
    return {"message": "deleted"}


def list_trades(status=None):
    conn = db.get_connection()
    if status in ("open", "closed"):
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = ? ORDER BY id DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY status, id DESC"
        ).fetchall()
    conn.close()
    return [_enrich(r) for r in rows]


# ── cumulative analytics ────────────────────────────────────────────────────────

def cumulative_stats():
    """Batting average, expectancy, total R and dollar aggregates."""
    open_trades   = list_trades("open")
    closed_trades = list_trades("closed")

    closed_r = [t["r_multiple"] for t in closed_trades if t.get("r_multiple") is not None]
    open_r   = [t["r_multiple"] for t in open_trades   if t.get("r_multiple") is not None]

    wins   = [r for r in closed_r if r > 0]
    losses = [r for r in closed_r if r < 0]
    n_closed = len(closed_r)

    batting = (len(wins) / n_closed) if n_closed else 0.0
    avg_win  = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0  # negative
    expectancy = batting * avg_win + (1 - batting) * avg_loss

    risk_usds   = [t["initial_risk_usd"] for t in closed_trades if t.get("initial_risk_usd")]
    pnl_usds    = [t["pnl"] for t in closed_trades if t.get("pnl") is not None]

    equity = None
    try:
        import settings_store
        equity = settings_store.get_settings()["equity"]
    except Exception:
        equity = None

    heat = risk.portfolio_heat(open_trades, equity) if equity else {"open_risk_dollars": None, "heat_pct": None}

    def _r(x, n=2):
        return round(x, n) if x is not None else None

    return {
        "total_closed":     n_closed,
        "open_positions":   len(open_trades),
        "wins":             len(wins),
        "losses":           len(losses),
        "batting_average":  round(batting * 100, 2),
        "avg_win_r":        _r(avg_win),
        "avg_loss_r":       _r(avg_loss),
        "expectancy_r":     _r(expectancy),
        "avg_r":            _r(sum(closed_r) / n_closed) if n_closed else None,
        "total_r_closed":   _r(sum(closed_r)) if closed_r else 0.0,
        "total_r_open":     _r(sum(open_r)) if open_r else 0.0,
        "total_r_all":      _r(sum(closed_r) + sum(open_r)),
        "avg_risk_usd":     _r(sum(risk_usds) / len(risk_usds)) if risk_usds else None,
        "total_pnl_usd":    _r(sum(pnl_usds)) if pnl_usds else 0.0,
        "open_risk_usd":    heat["open_risk_dollars"],
        "portfolio_heat":   heat["heat_pct"],
    }
