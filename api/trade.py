"""Trading routes: positions, journal, analytics, R-analytics, strategies,
position sizing, ATR-based risk."""
import logging
import numpy as np
from flask import Blueprint, jsonify, request

import database as db
import errors
import swing_core

logger = logging.getLogger(__name__)
trade_bp = Blueprint("trade", __name__)

_atr = swing_core.atr


# ── Positions (Portfolio) ──────────────────────────────────────────────────────

@trade_bp.route("/api/positions", methods=["GET"])
def list_positions():
    include_closed = request.args.get("include_closed", "true").lower() != "false"
    positions = db.list_positions(include_closed=include_closed)

    # Enrich with current price and unrealised P&L
    for pos in positions:
        if pos.get("closed_at"):
            if pos.get("exit_price") and pos.get("entry_price"):
                pos["realised_pnl"] = round(
                    (pos["exit_price"] - pos["entry_price"]) * pos["qty"], 2)
            continue
        ohlcv = db.get_ohlcv(pos["symbol"], "daily", limit=1)
        if ohlcv:
            cur_price = ohlcv[-1]["close"]
            pos["current_price"]  = round(cur_price, 2)
            pos["current_value"]  = round(cur_price * pos["qty"], 2)
            pos["unrealised_pnl"] = round(
                (cur_price - pos["entry_price"]) * pos["qty"], 2)
            pos["pnl_pct"] = round(
                (cur_price / pos["entry_price"] - 1) * 100, 2)

    return jsonify(positions)


@trade_bp.route("/api/positions", methods=["POST"])
def create_position():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        raise errors.symbol_required()
    try:
        qty         = float(body["qty"])
        entry_price = float(body["entry_price"])
        if qty == 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise errors.validation("qty (non-zero) and entry_price are required numbers")

    opened_at = body.get("opened_at")
    notes     = body.get("notes", "")
    pos_id    = db.add_position(symbol, qty, entry_price, opened_at, notes)
    return jsonify({"id": pos_id, "message": "Position created"}), 201


@trade_bp.route("/api/positions/<int:pos_id>", methods=["PUT"])
def update_position(pos_id):
    body = request.get_json(silent=True) or {}
    allowed = {"qty", "entry_price", "opened_at", "closed_at", "exit_price", "notes"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        raise errors.validation("No valid fields to update")
    db.update_position(pos_id, **updates)
    return jsonify({"message": "updated"})


@trade_bp.route("/api/positions/<int:pos_id>", methods=["DELETE"])
def delete_position(pos_id):
    db.delete_position(pos_id)
    return jsonify({"message": "deleted"})


# ── Journal ────────────────────────────────────────────────────────────────────

@trade_bp.route("/api/journal", methods=["GET"])
def list_journal():
    symbol = request.args.get("symbol")
    tag    = request.args.get("tag")
    return jsonify(db.list_journal(symbol.upper() if symbol else None, tag))


@trade_bp.route("/api/journal", methods=["POST"])
def create_journal_entry():
    from datetime import datetime as _dt
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        raise errors.symbol_required()
    try:
        entry_price = float(body["entry_price"])
        qty         = float(body.get("qty", 1))
    except (KeyError, TypeError, ValueError):
        raise errors.validation("entry_price (number) is required")

    exit_p = body.get("exit_price")
    stop_p = body.get("stop_loss")
    mae_r  = body.get("mae_r")
    mfe_r  = body.get("mfe_r")

    # Auto-capture entry context (regime, RVOL, LoD) so the 100-trade review
    # can later slice performance by rule compliance.  Best-effort only.
    regime = body.get("market_regime", "")
    rvol   = body.get("entry_rvol")
    lod    = body.get("lod_dist_atr")
    if not regime:
        try:
            import market_regime as _mr
            res = _mr.compute_market_regime("SPY")
            regime = (res.get("current") or {}).get("state", "") if "error" not in res else ""
        except Exception:
            regime = ""
    if rvol is None or lod is None:
        try:
            sd = swing_core.swing_data_for(symbol)
            if rvol is None: rvol = sd.get("rvol")
            if lod  is None: lod  = sd.get("lod_dist_atr")
        except Exception:
            pass

    jid = db.add_journal_entry(
        symbol=symbol,
        direction=body.get("direction", "long"),
        entry_date=body.get("entry_date", _dt.now().date().isoformat()),
        entry_price=entry_price,
        qty=qty,
        exit_date=body.get("exit_date"),
        exit_price=float(exit_p) if exit_p is not None else None,
        stop_loss=float(stop_p) if stop_p is not None else None,
        setup=body.get("setup", ""),
        tags=body.get("tags", ""),
        thesis=body.get("thesis", ""),
        market_regime=regime,
        entry_rvol=float(rvol) if rvol is not None else None,
        lod_dist_atr=float(lod) if lod is not None else None,
        mae_r=float(mae_r) if mae_r is not None else None,
        mfe_r=float(mfe_r) if mfe_r is not None else None,
    )
    if body.get("review_grade") or body.get("review_mistakes") or body.get("review_lesson"):
        db.update_journal_entry(
            jid,
            review_grade=body.get("review_grade", ""),
            review_mistakes=body.get("review_mistakes", ""),
            review_lesson=body.get("review_lesson", ""),
        )

    # Overtrading guard (hard rule: max 3 new positions per session)
    today       = _dt.now().date().isoformat()
    today_count = sum(1 for e in db.list_journal()
                      if (e.get("entry_date") or "")[:10] == today)
    return jsonify({"id": jid, "message": "Journal entry created",
                    "today_count": today_count}), 201


@trade_bp.route("/api/journal/<int:entry_id>", methods=["PUT"])
def update_journal_entry(entry_id):
    body    = request.get_json(silent=True) or {}
    allowed = {"direction", "entry_date", "exit_date", "entry_price",
               "exit_price", "stop_loss", "qty", "setup", "tags", "thesis",
               "review_grade", "review_mistakes", "review_lesson",
               "market_regime", "entry_rvol", "lod_dist_atr", "mae_r", "mfe_r"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        raise errors.validation("No valid fields to update")
    db.update_journal_entry(entry_id, **updates)
    return jsonify({"message": "updated"})


@trade_bp.route("/api/journal/<int:entry_id>", methods=["DELETE"])
def delete_journal_entry(entry_id):
    db.delete_journal_entry(entry_id)
    return jsonify({"message": "deleted"})


# ── Open-trade management (Part XV rules as action hints) ─────────────────────

def _trading_days_since(date_str: str) -> int:
    import numpy as _np
    from datetime import date as _date
    try:
        return int(_np.busday_count(date_str[:10], _date.today().isoformat()))
    except Exception:
        return 0


@trade_bp.route("/api/journal/manage", methods=["GET"])
def manage_open_trades():
    """Per open journal trade: current R, T+N, 10-MA / extension status and
    rule-based action hints (shave >2R, T+3 breakeven, 10-MA exit prep…)."""
    entries = [e for e in db.list_journal() if e.get("exit_price") is None]
    out = []
    for e in entries:
        row = {
            "id":         e["id"],
            "symbol":     e["symbol"],
            "direction":  e.get("direction", "long"),
            "entry_date": e.get("entry_date"),
            "entry_price":e.get("entry_price"),
            "stop_loss":  e.get("stop_loss"),
            "days_held":  _trading_days_since(e.get("entry_date") or ""),
            "hints":      [],
        }
        try:
            df = db.get_ohlcv_df(e["symbol"], "daily", limit=80)
            if df.empty or len(df) < 12:
                row["error"] = "no data"
                out.append(row)
                continue
            close = df["close"]
            cur   = float(close.iloc[-1])
            ma10  = float(close.tail(10).mean())
            ma50  = float(close.tail(51).mean()) if len(close) >= 51 else None
            atr14 = float(_atr(df["high"], df["low"], close, 14).iloc[-1])
            ext   = round((cur - ma50) / atr14, 1) if (ma50 and atr14 > 0) else None

            row["current_price"]  = round(cur, 2)
            row["ma10"]           = round(ma10, 2)
            row["below_10ma"]     = cur < ma10
            row["atr_mult_50ma"]  = ext

            short = row["direction"] == "short"
            entry = float(e["entry_price"])
            stop  = e.get("stop_loss")
            if stop is not None and abs(entry - float(stop)) > 1e-6:
                risk  = abs(entry - float(stop))
                cur_r = round(((entry - cur) if short else (cur - entry)) / risk, 2)
                row["current_r"] = cur_r
            else:
                cur_r = None

            n     = row["days_held"]
            hints = row["hints"]
            if cur_r is not None and cur_r <= -1.0:
                hints.append({"level": "red",
                              "text": f"≤ −1R ({cur_r}R) — stop is violated, execute it"})
            if n <= 2 and cur_r is not None and cur_r >= 2.0:
                hints.append({"level": "green",
                              "text": f"+{cur_r}R in T+{n} — shave ⅓ into strength"})
            if n == 3:
                hints.append({"level": "yellow",
                              "text": "T+3 — reduce risk, move stop toward breakeven"})
            if n <= 3 and cur_r is not None and cur_r >= 4.0:
                hints.append({"level": "green",
                              "text": f"+{cur_r}R before day 4 — move stop to breakeven now"})
            if ext is not None and ext >= 8.0 and not short:
                hints.append({"level": "yellow",
                              "text": f"{ext}× ATR above 50-MA — climactic, take a partial"})
            if n >= 4 and cur < ma10 and not short:
                hints.append({"level": "red",
                              "text": "Closed below 10-MA — prepare next-day opening-range-low exit"})
            if not hints:
                hints.append({"level": "info",
                              "text": "Early window — 3-stop layers active" if n <= 3
                                      else "Hold — manage with the 10-day MA"})
        except Exception:
            row["error"] = "no data"
        out.append(row)
    return jsonify({"open_trades": out})


@trade_bp.route("/api/journal/backfill-excursions", methods=["POST"])
def backfill_excursions():
    """Auto-compute MFE/MAE (in R) for closed trades from the daily bars
    between entry and exit dates.  Only fills entries where they're missing."""
    entries = db.list_journal()
    updated = 0
    dfs: dict = {}
    for e in entries:
        if (e.get("exit_price") is None or e.get("stop_loss") is None
                or not e.get("entry_date") or not e.get("exit_date")):
            continue
        if e.get("mae_r") is not None and e.get("mfe_r") is not None:
            continue
        sym = e["symbol"]
        try:
            if sym not in dfs:
                dfs[sym] = db.get_ohlcv_df(sym, "daily", limit=800)
            df = dfs[sym]
            if df.empty:
                continue
            seg = df.loc[str(e["entry_date"])[:10]: str(e["exit_date"])[:10]]
            if seg.empty:
                continue
            entry = float(e["entry_price"])
            risk  = abs(entry - float(e["stop_loss"]))
            if risk < 1e-6:
                continue
            hi = float(seg["high"].max())
            lo = float(seg["low"].min())
            if e.get("direction", "long") == "short":
                mfe = (entry - lo) / risk
                mae = (entry - hi) / risk
            else:
                mfe = (hi - entry) / risk
                mae = (lo - entry) / risk
            db.update_journal_entry(
                e["id"],
                mfe_r=round(max(mfe, 0.0), 3),
                mae_r=round(min(mae, 0.0), 3),
            )
            updated += 1
        except Exception:
            continue
    return jsonify({"updated": updated})


# ── Portfolio Analytics ────────────────────────────────────────────────────────

@trade_bp.route("/api/analytics", methods=["GET"])
def get_analytics():
    positions = db.list_positions(include_closed=True)
    closed    = [p for p in positions if p.get("closed_at") and p.get("exit_price")]

    if not closed:
        return jsonify({
            "trade_count": 0, "win_rate": None, "profit_factor": None,
            "avg_win": None, "avg_loss": None, "sharpe": None,
            "max_drawdown": None, "equity_curve": [], "trades": [],
        })

    closed.sort(key=lambda p: p.get("closed_at", ""))
    trades = []
    for p in closed:
        pnl = (p["exit_price"] - p["entry_price"]) * p["qty"]
        trades.append({
            "symbol": p["symbol"],
            "date":   p["closed_at"][:10],
            "pnl":    round(pnl, 2),
            "pct":    round((p["exit_price"] / p["entry_price"] - 1) * 100, 2),
        })

    pnls   = [t["pnl"] for t in trades]
    wins   = [v for v in pnls if v > 0]
    losses = [v for v in pnls if v <= 0]

    win_rate      = len(wins) / len(pnls) if pnls else None
    avg_win       = float(np.mean(wins))  if wins   else None
    avg_loss      = float(np.mean(losses)) if losses else None
    profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else None

    cum = 0
    equity = []
    for t in trades:
        cum += t["pnl"]
        equity.append({"date": t["date"], "equity": round(cum, 2)})

    arr    = np.array(pnls)
    sharpe = float(arr.mean() / arr.std() * np.sqrt(252)) if len(arr) >= 3 and arr.std() > 0 else None

    eq_vals = np.array([e["equity"] for e in equity])
    if len(eq_vals) >= 2:
        peak   = np.maximum.accumulate(eq_vals)
        dd     = (eq_vals - peak) / np.where(np.abs(peak) > 0, np.abs(peak), 1.0)
        max_dd = float(dd.min())
    else:
        max_dd = None

    return jsonify({
        "trade_count":   len(trades),
        "win_rate":      round(win_rate, 4)      if win_rate      is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "avg_win":       round(avg_win, 2)       if avg_win       is not None else None,
        "avg_loss":      round(avg_loss, 2)      if avg_loss      is not None else None,
        "sharpe":        round(sharpe, 4)        if sharpe        is not None else None,
        "max_drawdown":  round(max_dd, 4)        if max_dd        is not None else None,
        "equity_curve":  equity,
        "trades":        trades,
    })


# ── R-Multiple Analytics ───────────────────────────────────────────────────────

@trade_bp.route("/api/r-analytics", methods=["GET"])
def get_r_analytics():
    """R-distribution from journal entries that have stop_loss recorded."""
    entries = db.list_journal()

    BUCKETS = [
        {"label": "< −2R",       "min": -999, "max": -2  },
        {"label": "−2R to −1R",  "min": -2,   "max": -1  },
        {"label": "−1R to −0.5R","min": -1,   "max": -0.5},
        {"label": "−0.5R to 0",  "min": -0.5, "max":  0  },
        {"label": "0 to +1R",    "min":  0,   "max":  1  },
        {"label": "+1R to +3R",  "min":  1,   "max":  3  },
        {"label": "+3R to +10R", "min":  3,   "max": 10  },
        {"label": "> +10R",      "min": 10,   "max": 999 },
    ]

    r_trades = []
    for e in entries:
        if e.get("exit_price") is None or e.get("stop_loss") is None:
            continue
        entry = float(e["entry_price"])
        stop  = float(e["stop_loss"])
        exit_ = float(e["exit_price"])
        risk  = abs(entry - stop)
        if risk < 0.0001:
            continue
        r = (exit_ - entry) / risk if e.get("direction", "long") != "short" else (entry - exit_) / risk
        r_trades.append({
            "symbol":       e["symbol"],
            "date":         (e.get("exit_date") or e.get("entry_date") or "")[:10],
            "r":            round(r, 3),
            "setup":        (e.get("setup") or "").strip(),
            "setup_grade":  e.get("setup_grade")    or "",
            "review_grade": e.get("review_grade")   or "",
            "mistakes":     e.get("review_mistakes") or "",
            "regime":       e.get("market_regime")  or "",
            "entry_rvol":   e.get("entry_rvol"),
            "lod":          e.get("lod_dist_atr"),
            "mae_r":        e.get("mae_r"),
            "mfe_r":        e.get("mfe_r"),
        })

    if not r_trades:
        return jsonify({"count": 0, "histogram": BUCKETS})

    rs     = [t["r"] for t in r_trades]
    wins   = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n      = len(rs)

    win_rate     = len(wins) / n
    avg_win_r    = float(np.mean(wins))   if wins   else 0.0
    avg_loss_r   = float(np.mean(losses)) if losses else 0.0
    payoff_ratio = abs(avg_win_r / avg_loss_r) if avg_loss_r else None
    expectancy   = round(win_rate * avg_win_r + (1 - win_rate) * avg_loss_r, 3)

    # Slippage: how much worse than -1R are average losses?
    avg_loss_slippage = round(avg_loss_r - (-1.0), 3) if losses else None

    for b in BUCKETS:
        b["count"] = sum(1 for r in rs if b["min"] <= r < b["max"])
        b["pct"]   = round(b["count"] / n * 100, 1)

    # Per-grade breakdown
    grade_stats = {}
    for grade in ("A", "B", "C", ""):
        g_rs = [t["r"] for t in r_trades if t["setup_grade"] == grade]
        if not g_rs:
            continue
        g_wins   = [r for r in g_rs if r > 0]
        g_losses = [r for r in g_rs if r <= 0]
        g_wr     = len(g_wins) / len(g_rs)
        g_aw     = float(np.mean(g_wins))   if g_wins   else 0.0
        g_al     = float(np.mean(g_losses)) if g_losses else 0.0
        grade_stats[grade or "Ungraded"] = {
            "count":      len(g_rs),
            "win_rate":   round(g_wr, 3),
            "avg_r":      round(float(np.mean(g_rs)), 3),
            "expectancy": round(g_wr * g_aw + (1 - g_wr) * g_al, 3),
        }

    # Mistake tag frequency (comma-separated tags in review_mistakes)
    mistake_freq: dict = {}
    for t in r_trades:
        for tag in (t.get("mistakes") or "").split(","):
            tag = tag.strip()
            if tag:
                mistake_freq[tag] = mistake_freq.get(tag, 0) + 1
    mistake_list = sorted(mistake_freq.items(), key=lambda x: -x[1])

    # Review grade breakdown (A+/A/B/C/D/F)
    rev_grade_stats: dict = {}
    for rg in ("A+", "A", "B", "C", "D", "F", ""):
        rg_rs = [t["r"] for t in r_trades if t.get("review_grade", "") == rg]
        if not rg_rs:
            continue
        rev_grade_stats[rg or "Ungraded"] = {
            "count":    len(rg_rs),
            "avg_r":    round(float(np.mean(rg_rs)), 3),
            "win_rate": round(sum(1 for r in rg_rs if r > 0) / len(rg_rs), 3),
        }

    def _bucket_stats(rs_list):
        if not rs_list:
            return None
        b_wins = [r for r in rs_list if r > 0]
        b_wr   = len(b_wins) / len(rs_list)
        return {
            "count":    len(rs_list),
            "win_rate": round(b_wr, 3),
            "avg_r":    round(float(np.mean(rs_list)), 3),
        }

    # Setup-type breakdown (free-text 'setup' field, case-insensitive)
    setup_groups: dict = {}
    for t in r_trades:
        key = t["setup"].lower() or "(none)"
        setup_groups.setdefault(key, []).append(t["r"])
    setup_stats = {
        k: _bucket_stats(v)
        for k, v in sorted(setup_groups.items(), key=lambda kv: -len(kv[1]))[:10]
    }

    # Rule-compliance slices — does breaking the hard rules cost money?
    compliance = {
        "lod": {
            "pass":    _bucket_stats([t["r"] for t in r_trades if t["lod"] is not None and t["lod"] <= 0.6]),
            "fail":    _bucket_stats([t["r"] for t in r_trades if t["lod"] is not None and t["lod"] > 0.6]),
            "unknown": _bucket_stats([t["r"] for t in r_trades if t["lod"] is None]),
        },
        "rvol": {
            "pass":    _bucket_stats([t["r"] for t in r_trades if t["entry_rvol"] is not None and t["entry_rvol"] >= 1.0]),
            "fail":    _bucket_stats([t["r"] for t in r_trades if t["entry_rvol"] is not None and t["entry_rvol"] < 1.0]),
            "unknown": _bucket_stats([t["r"] for t in r_trades if t["entry_rvol"] is None]),
        },
        "regime": {
            "pass":    _bucket_stats([t["r"] for t in r_trades if t["regime"].upper().startswith("BULL")]),
            "fail":    _bucket_stats([t["r"] for t in r_trades if t["regime"] and not t["regime"].upper().startswith("BULL")]),
            "unknown": _bucket_stats([t["r"] for t in r_trades if not t["regime"]]),
        },
    }

    # 100-trade review: expectancy over the most recent (up to) 100 closed trades
    recent      = sorted(r_trades, key=lambda t: t["date"])[-100:]
    recent_rs   = [t["r"] for t in recent]
    rec_wins    = [r for r in recent_rs if r > 0]
    rec_losses  = [r for r in recent_rs if r <= 0]
    rec_wr      = len(rec_wins) / len(recent_rs)
    rec_aw      = float(np.mean(rec_wins))   if rec_wins   else 0.0
    rec_al      = float(np.mean(rec_losses)) if rec_losses else 0.0
    last100 = {
        "count":      len(recent_rs),
        "win_rate":   round(rec_wr, 4),
        "avg_win_r":  round(rec_aw, 3),
        "avg_loss_r": round(rec_al, 3),
        "expectancy": round(rec_wr * rec_aw + (1 - rec_wr) * rec_al, 3),
    }

    # MAE / MFE aggregates (only trades where they were recorded)
    maes = [t["mae_r"] for t in r_trades if t["mae_r"] is not None]
    mfes = [t["mfe_r"] for t in r_trades if t["mfe_r"] is not None]
    excursion = {
        "count_mae": len(maes),
        "count_mfe": len(mfes),
        "avg_mae_r": round(float(np.mean(maes)), 3) if maes else None,
        "avg_mfe_r": round(float(np.mean(mfes)), 3) if mfes else None,
    }

    return jsonify({
        "count":              n,
        "win_rate":           round(win_rate, 4),
        "avg_win_r":          round(avg_win_r, 3),
        "avg_loss_r":         round(avg_loss_r, 3),
        "payoff_ratio":       round(payoff_ratio, 3) if payoff_ratio else None,
        "expectancy":         expectancy,
        "avg_loss_slippage":  avg_loss_slippage,
        "histogram":          BUCKETS,
        "grade_stats":        grade_stats,
        "mistake_freq":       mistake_list,
        "rev_grade_stats":    rev_grade_stats,
        "setup_stats":        setup_stats,
        "compliance":         compliance,
        "last100":            last100,
        "excursion":          excursion,
    })


# ── Strategies ─────────────────────────────────────────────────────────────────

@trade_bp.route("/api/strategies", methods=["GET"])
def list_strategies_route():
    return jsonify(db.list_strategies())


@trade_bp.route("/api/strategies", methods=["POST"])
def create_strategy():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        raise errors.validation("name is required")
    conditions = body.get("conditions", [])
    if not isinstance(conditions, list):
        raise errors.validation("conditions must be a list")
    sid = db.add_strategy(name, conditions)
    return jsonify({"id": sid, "message": "Strategy created"}), 201


@trade_bp.route("/api/strategies/<int:strategy_id>", methods=["PUT"])
def update_strategy_route(strategy_id):
    body = request.get_json(silent=True) or {}
    name       = body.get("name")
    conditions = body.get("conditions")
    if name is None and conditions is None:
        raise errors.validation("name or conditions required")
    db.update_strategy(strategy_id, name=name, conditions=conditions)
    return jsonify({"message": "updated"})


@trade_bp.route("/api/strategies/<int:strategy_id>", methods=["DELETE"])
def delete_strategy_route(strategy_id):
    db.delete_strategy(strategy_id)
    return jsonify({"message": "deleted"})


# ── ATR-based Risk ─────────────────────────────────────────────────────────────

@trade_bp.route("/api/risk/<string:symbol>", methods=["GET"])
def get_risk(symbol):
    account = float(request.args.get("account", 10000))
    risk_pct = float(request.args.get("risk_pct", 1.0)) / 100
    atr_mult = float(request.args.get("atr_mult", 2.0))

    df = db.get_ohlcv_df(symbol.upper(), "daily", limit=60)
    if df.empty or len(df) < 15:
        raise errors.ApiError("NO_DATA", "Not enough data", http=404)

    close = df["close"].iloc[-1]
    atr14 = _atr(df["high"], df["low"], df["close"], 14).iloc[-1]

    stop_distance = atr14 * atr_mult
    stop_loss     = close - stop_distance
    stop_pct      = stop_distance / close

    risk_amount   = account * risk_pct
    shares        = int(risk_amount / stop_distance) if stop_distance > 0 else 0
    position_size = shares * close

    # Simple R:R targets
    tp1 = close + stop_distance * 1.5
    tp2 = close + stop_distance * 3.0

    # Annualised vol (20-day)
    ret     = df["close"].pct_change().dropna()
    ann_vol = float(ret.tail(20).std() * np.sqrt(252)) if len(ret) >= 20 else None

    # Kelly fraction (very rough: 55% win, 1.5 R:R)
    kelly = max(0.0, 0.55 - 0.45 / 1.5)

    return jsonify({
        "symbol":        symbol.upper(),
        "price":         round(float(close), 2),
        "atr14":         round(float(atr14), 4),
        "stop_distance": round(float(stop_distance), 4),
        "stop_loss":     round(float(stop_loss), 2),
        "stop_pct":      round(float(stop_pct), 4),
        "tp1":           round(float(tp1), 2),
        "tp2":           round(float(tp2), 2),
        "shares":        shares,
        "position_size": round(float(position_size), 2),
        "risk_amount":   round(float(risk_amount), 2),
        "ann_vol":       round(float(ann_vol), 4) if ann_vol else None,
        "kelly":         round(kelly, 4),
    })


# ── Position Sizer ────────────────────────────────────────────────────────────

@trade_bp.route("/api/position-size", methods=["POST"])
def calc_position_size():
    body        = request.get_json(silent=True) or {}
    account     = float(body.get("account",   100000))
    risk_pct    = float(body.get("risk_pct",  0.5)) / 100.0
    entry       = float(body.get("entry",     0))
    stop        = float(body.get("stop",      0))
    if entry <= 0 or stop <= 0 or stop >= entry:
        raise errors.validation("entry must be > stop > 0")

    dollar_risk  = account * risk_pct
    risk_per_sh  = entry - stop
    shares       = int(dollar_risk / risk_per_sh)
    gross_exp    = shares * entry
    stop_pct     = (entry - stop) / entry * 100

    # Liquidity cap (Jeff rule: position ≤ 1–3% of avg daily dollar volume)
    adv_dollar = liq_pct = None
    liq_warning = False
    symbol = (body.get("symbol") or "").strip().upper()
    if symbol:
        try:
            sd = swing_core.swing_data_for(symbol)
            adv_dollar = sd.get("avg_dollar_vol")
            if adv_dollar:
                liq_pct     = round(gross_exp / adv_dollar * 100, 2)
                liq_warning = liq_pct > 2.0
        except Exception:
            pass

    return jsonify({
        "adv_dollar":   adv_dollar,
        "liq_pct_of_adv": liq_pct,
        "liq_warning":  liq_warning,
        "account":      account,
        "risk_pct":     risk_pct * 100,
        "entry":        entry,
        "stop":         stop,
        "dollar_risk":  round(dollar_risk, 2),
        "risk_per_sh":  round(risk_per_sh, 4),
        "shares":       shares,
        "gross_exp":    round(gross_exp, 2),
        "stop_pct":     round(stop_pct, 2),
        "pct_portfolio":round(gross_exp / account * 100, 2),
        "tp1_1r":       round(entry + risk_per_sh * 1,  2),
        "tp2_3r":       round(entry + risk_per_sh * 3,  2),
        "tp3_5r":       round(entry + risk_per_sh * 5,  2),
        "tp4_10r":      round(entry + risk_per_sh * 10, 2),
        "tranche1_stop":round(entry - risk_per_sh * 0.33, 2),
        "tranche2_stop":round(entry - risk_per_sh * 0.67, 2),
        "tranche3_stop":stop,
    })
