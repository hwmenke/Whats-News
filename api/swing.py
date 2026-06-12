"""Jeff Sun swing-workflow routes: swing data, setup grade, scan,
focus-pipeline tiers, and guru strategy scans."""
import logging
from flask import Blueprint, jsonify, request

import database as db
import errors
import guru_scanner
import jeff_scanner
import swing_core

logger = logging.getLogger(__name__)
swing_bp = Blueprint("swing", __name__)

_swing_data_for   = swing_core.swing_data_for
_grade_from_swing = swing_core.grade_from_swing


@swing_bp.route("/api/swing-data/<string:symbol>", methods=["GET"])
def get_swing_data(symbol):
    try:
        return jsonify(_swing_data_for(symbol))
    except ValueError as e:
        raise errors.ApiError("NO_DATA", str(e), http=404)
    except errors.ApiError:
        raise
    except Exception as e:
        logger.exception("swing-data error")
        raise errors.computation_failed(str(e))


@swing_bp.route("/api/setup-grade/<string:symbol>", methods=["GET"])
def get_setup_grade(symbol):
    try:
        sd     = _swing_data_for(symbol)
        result = _grade_from_swing(sd)
        result.update(sd)
        # Persist grade to DB
        try:
            db.set_setup_grade(symbol, result["grade"])
        except Exception:
            pass
        return jsonify(result)
    except ValueError as e:
        raise errors.ApiError("NO_DATA", str(e), http=404)
    except errors.ApiError:
        raise
    except Exception as e:
        logger.exception("setup-grade error")
        raise errors.computation_failed(str(e))


@swing_bp.route("/api/jeff-scan", methods=["GET"])
def get_jeff_scan():
    """Watchlist-wide Jeff setup scan: grade, readiness, trigger, RS — ranked."""
    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify({"rows": [], "spy_available": False})
    try:
        rows = jeff_scanner.compute_jeff_scan(symbols)
        spy_available = any(r.get("rs_vs_spy") is not None for r in rows)

        # Sector performance percentiles (free — uses ret_20d already in rows)
        sector_ret20: dict = {}
        for r in rows:
            sec = r.get("sector") or ""
            ret = r.get("ret_20d")
            if sec and ret is not None:
                sector_ret20.setdefault(sec, []).append(ret)
        sector_avg = {s: sum(v) / len(v) for s, v in sector_ret20.items() if v}
        if sector_avg:
            avgs = sorted(sector_avg.values())
            n = len(avgs)
            for r in rows:
                sec = r.get("sector") or ""
                if sec and sec in sector_avg:
                    avg = sector_avg[sec]
                    pct = round(sum(1 for v in avgs if v <= avg) / n * 100)
                    r["sector_rank_pct"] = pct

        return jsonify({"rows": rows, "spy_available": spy_available})
    except Exception as e:
        logger.exception("jeff-scan error")
        raise errors.computation_failed(str(e))


# ── Focus Pipeline Tier ───────────────────────────────────────────────────────

@swing_bp.route("/api/symbols/<string:symbol>/tier", methods=["PUT"])
def set_symbol_tier_route(symbol):
    body = request.get_json(silent=True) or {}
    tier = body.get("tier", "watchlist")
    if not db.set_symbol_tier(symbol, tier):
        raise errors.validation(
            f"Invalid tier: {tier}. Use back_watchlist/watchlist/stalk/focus/active")
    return jsonify({"symbol": symbol.upper(), "tier": tier})


@swing_bp.route("/api/focus-pipeline", methods=["GET"])
def get_focus_pipeline():
    """Return all symbols grouped by watchlist tier, with swing data and grade."""
    tiers   = db.list_symbols_by_tier()
    result  = {}
    for tier, syms in tiers.items():
        enriched = []
        for s in syms:
            entry = {
                "symbol":      s["symbol"],
                "name":        s.get("name") or "",
                "sector":      s.get("sector") or "",
                "setup_grade": s.get("setup_grade") or "",
                "tier":        tier,
            }
            try:
                sd = _swing_data_for(s["symbol"])
                entry.update({
                    "adr_pct":       sd["adr_pct"],
                    "rvol":          sd["rvol"],
                    "atr_mult_50ma": sd["atr_mult_50ma"],
                })
            except Exception:
                pass
            enriched.append(entry)
        result[tier] = enriched
    return jsonify(result)


# ── Trade Plans (focus-list entry planner) ────────────────────────────────────

@swing_bp.route("/api/trade-plans", methods=["GET"])
def list_trade_plans_route():
    """All saved plans + every focus/active-tier symbol, enriched with live
    swing data, R-per-share, distance-to-trigger and hard-rule flags."""
    plans   = {p["symbol"]: p for p in db.list_trade_plans()}
    tiers   = db.list_symbols_by_tier()
    symbols = {s["symbol"] for s in tiers.get("focus", []) + tiers.get("active", [])}
    symbols |= set(plans.keys())

    tier_of = {}
    for tier, syms in tiers.items():
        for s in syms:
            tier_of[s["symbol"]] = tier

    rows = []
    for sym in sorted(symbols):
        plan = plans.get(sym, {})
        row = {
            "symbol":        sym,
            "tier":          tier_of.get(sym, ""),
            "trigger_price": plan.get("trigger_price"),
            "stop_price":    plan.get("stop_price"),
            "trigger_type":  plan.get("trigger_type") or "",
            "notes":         plan.get("notes") or "",
            "has_plan":      sym in plans,
        }
        try:
            sd = _swing_data_for(sym)
            row.update({
                "last_close":    sd["last_close"],
                "atr_14":        sd["atr_14"],
                "rvol":          sd["rvol"],
                "adr_pct":       sd["adr_pct"],
                "lod_dist_atr":  sd["lod_dist_atr"],
                "atr_mult_50ma": sd["atr_mult_50ma"],
                "pocket_pivot":  sd.get("pocket_pivot", False),
                "vol_dryup":     sd.get("vol_dryup", False),
            })
            trig = row["trigger_price"]
            stop = row["stop_price"]
            if trig and stop and trig > stop:
                row["risk_per_sh"] = round(trig - stop, 4)
            if trig and sd["last_close"]:
                row["dist_to_trigger_pct"] = round(
                    (trig / sd["last_close"] - 1) * 100, 2)
            row["flags"] = {
                "lod_too_far":     sd["lod_dist_atr"] > 0.6,
                "too_extended":    sd["atr_mult_50ma"] > 4.0,
                "low_rvol":        sd["rvol"] < 1.0,
                "ma200_declining": bool(sd.get("ma200_declining")),
            }
        except Exception:
            row["error"] = "no data"
        rows.append(row)

    return jsonify({"rows": rows})


# ── Breakout Board ─────────────────────────────────────────────────────────────

def _auto_pivot(sym: str):
    """Consolidation pivot = highest high of the last 20 completed bars
    (excluding today), plus today's high/close for trigger detection."""
    df = db.get_ohlcv_df(sym, "daily", limit=30)
    if df.empty or len(df) < 5:
        return None, None, None
    today      = df.iloc[-1]
    prior      = df.iloc[:-1].tail(20)
    pivot      = float(prior["high"].max())
    return pivot, float(today["high"]), float(today["close"])


def _breakout_status(pivot, today_high, close, dist_pct):
    if pivot is None or dist_pct is None:
        return "UNKNOWN"
    if today_high is not None and today_high >= pivot:
        return "TRIGGERED" if close >= pivot else "BREAKING"
    if dist_pct <= 1.0:
        return "AT PIVOT"
    if dist_pct <= 5.0:
        return "NEAR"
    return "BASING"


_STATUS_ORDER = {"TRIGGERED": 0, "BREAKING": 1, "AT PIVOT": 2,
                 "NEAR": 3, "BASING": 4, "UNKNOWN": 5}


@swing_bp.route("/api/breakout-board", methods=["GET"])
def get_breakout_board():
    """Process candidates (stalk/focus/active tiers + planned symbols) with
    live breakout status: pivot, distance to trigger, hard-rule gates and
    volume character — the 'how are my candidates doing on breakouts' view."""
    want = request.args.get("tiers", "stalk,focus,active")
    want_tiers = {t.strip() for t in want.split(",") if t.strip()}

    tiers = db.list_symbols_by_tier()
    plans = {p["symbol"]: p for p in db.list_trade_plans()}

    tier_of, symbols = {}, set()
    for tier, syms in tiers.items():
        for s in syms:
            tier_of[s["symbol"]] = tier
            if tier in want_tiers:
                symbols.add(s["symbol"])
    symbols |= set(plans.keys())

    rows = []
    for sym in sorted(symbols):
        plan = plans.get(sym, {})
        row = {
            "symbol":   sym,
            "tier":     tier_of.get(sym, ""),
            "has_plan": sym in plans,
        }
        try:
            sd = _swing_data_for(sym)
            g  = _grade_from_swing(sd)
            pivot, today_high, close = _auto_pivot(sym)
            # A saved plan trigger overrides the auto pivot
            if plan.get("trigger_price"):
                pivot = float(plan["trigger_price"])

            dist_pct = None
            if pivot and close:
                dist_pct = round((pivot / close - 1) * 100, 2)

            row.update({
                "grade":         g["grade"],
                "score":         g["score"],
                "last_close":    sd["last_close"],
                "pivot":         round(pivot, 2) if pivot else None,
                "pivot_source":  "plan" if plan.get("trigger_price") else "auto20",
                "dist_pct":      dist_pct,
                "status":        _breakout_status(pivot, today_high, close, dist_pct),
                "rvol":          sd["rvol"],
                "adr_pct":       sd["adr_pct"],
                "atr_mult_50ma": sd["atr_mult_50ma"],
                "lod_dist_atr":  sd["lod_dist_atr"],
                "pocket_pivot":  bool(sd.get("pocket_pivot")),
                "vol_dryup":     bool(sd.get("vol_dryup")),
                "too_extended":  sd["atr_mult_50ma"] > 4.0,
                "lod_too_far":   sd["lod_dist_atr"] > 0.6,
                "low_rvol":      sd["rvol"] < 1.0,
                "ma200_declining": bool(sd.get("ma200_declining")),
                "stop_price":    plan.get("stop_price"),
            })
        except Exception:
            row["error"] = "no data"
            row["status"] = "UNKNOWN"
        rows.append(row)

    rows.sort(key=lambda r: (_STATUS_ORDER.get(r.get("status"), 9),
                             r.get("dist_pct") if r.get("dist_pct") is not None else 999))
    return jsonify({"rows": rows, "tiers": sorted(want_tiers)})


@swing_bp.route("/api/trade-plans", methods=["POST"])
def upsert_trade_plan_route():
    body   = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    if not symbol:
        raise errors.symbol_required()
    trig = body.get("trigger_price")
    stop = body.get("stop_price")
    try:
        trig = float(trig) if trig is not None else None
        stop = float(stop) if stop is not None else None
    except (TypeError, ValueError):
        raise errors.validation("trigger_price and stop_price must be numbers")
    if trig is not None and stop is not None and stop >= trig:
        raise errors.validation("stop_price must be below trigger_price")

    db.upsert_trade_plan(
        symbol,
        trigger_price=trig,
        stop_price=stop,
        trigger_type=body.get("trigger_type", ""),
        notes=body.get("notes", ""),
    )
    return jsonify({"symbol": symbol, "message": "Plan saved"}), 201


@swing_bp.route("/api/trade-plans/<string:symbol>", methods=["DELETE"])
def delete_trade_plan_route(symbol):
    db.delete_trade_plan(symbol)
    return jsonify({"message": "deleted"})


# ── EOD Screens (post-market watchlist-building scans) ────────────────────────

_SCREEN_NAMES = ("parabolic_short", "pullback", "high_adr", "recent_ipo")


@swing_bp.route("/api/screens/<string:name>", methods=["GET"])
def run_screen(name):
    """Watchlist screens computable from daily OHLCV alone:

      parabolic_short — extreme upside extension (short / inverse candidates)
      pullback        — strong uptrend resting on the 10/20-MA in low volume
      high_adr        — highest average daily ranges (explosive movers)
      recent_ipo      — short price history (proxy for recent listings)
    """
    if name not in _SCREEN_NAMES:
        raise errors.validation(f"Unknown screen: {name}. Use one of {', '.join(_SCREEN_NAMES)}")

    symbols = db.list_symbols()
    rows = []
    for s in symbols:
        sym = s["symbol"]
        try:
            df = db.get_ohlcv_df(sym, freq="daily", limit=260)
            if df.empty or len(df) < 20:
                continue
            sd    = _swing_data_for(sym, df=df)
            close = df["close"]
            row   = {
                "symbol":        sym,
                "sector":        s.get("sector") or "",
                "last_close":    sd["last_close"],
                "adr_pct":       sd["adr_pct"],
                "rvol":          sd["rvol"],
                "atr_mult_50ma": sd["atr_mult_50ma"],
            }

            if name == "parabolic_short":
                ret_5d = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0.0
                if sd["atr_mult_50ma"] >= 6.0 or ret_5d >= 25.0:
                    row["ret_5d"] = round(ret_5d, 1)
                    rows.append(row)

            elif name == "pullback":
                if len(close) < 55:
                    continue
                ma50_now  = float(close.tail(50).mean())
                ma50_back = float(close.iloc[-55:-5].mean())
                ret_30d   = (float(close.iloc[-1]) / float(close.iloc[-31]) - 1) * 100 if len(close) >= 31 else 0.0
                k20       = sd.get("kama20") or {}
                dist_k20  = k20.get("dist_atr")
                pulled_in = dist_k20 is not None and -1.0 <= dist_k20 <= 1.0
                if (ma50_now > ma50_back and float(close.iloc[-1]) > ma50_now
                        and ret_30d >= 15.0 and pulled_in and sd["rvol"] < 1.2):
                    row["ret_30d"]   = round(ret_30d, 1)
                    row["dist_k20"]  = dist_k20
                    row["vol_dryup"] = sd["vol_dryup"]
                    rows.append(row)

            elif name == "high_adr":
                row["ret_20d"] = sd["ret_20d"]
                rows.append(row)

            elif name == "recent_ipo":
                if len(df) < 252:
                    row["bars"] = len(df)
                    row["ret_20d"] = sd["ret_20d"]
                    rows.append(row)
        except Exception:
            continue

    if name == "high_adr":
        rows.sort(key=lambda r: -(r.get("adr_pct") or 0))
        rows = rows[:25]
    elif name == "parabolic_short":
        rows.sort(key=lambda r: -(r.get("atr_mult_50ma") or 0))
    elif name == "recent_ipo":
        rows.sort(key=lambda r: r.get("bars") or 0)
    else:
        rows.sort(key=lambda r: -(r.get("ret_30d") or 0))

    return jsonify({"screen": name, "rows": rows})


# ── Guru scanner ───────────────────────────────────────────────────────────────

_GURU_STRATEGIES = list(guru_scanner.STRATEGIES)

_GURU_META = {
    "qullamaggie": {"label": "Qullamaggie Breakouts",   "icon": "🔥"},
    "minervini":   {"label": "Minervini TTM",            "icon": "📐"},
    "stockbee_4":  {"label": "Stockbee 4% Daily",       "icon": "⚡"},
    "stockbee_20": {"label": "Stockbee 20% Weekly",     "icon": "🚀"},
    "stockbee_9m": {"label": "Stockbee 9M Movers",      "icon": "💰"},
    "canslim":     {"label": "O'Neil CANSLIM",          "icon": "🏆"},
}


@swing_bp.route("/api/guru-scan/<string:strategy>", methods=["GET"])
def get_guru_scan(strategy):
    """Run one of the 6 guru strategies against the watchlist.

    Strategies: qullamaggie | minervini | stockbee_4 | stockbee_20 | stockbee_9m | canslim
    """
    if strategy not in _GURU_STRATEGIES:
        raise errors.validation(
            f"Unknown strategy '{strategy}'. Valid: {', '.join(sorted(_GURU_STRATEGIES))}"
        )
    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify({"strategy": strategy, "rows": [], "count": 0,
                        "meta": _GURU_META.get(strategy, {})})
    try:
        rows = guru_scanner.compute_guru_scan(strategy, symbols)
        return jsonify({
            "strategy": strategy,
            "rows":     rows,
            "count":    len(rows),
            "meta":     _GURU_META.get(strategy, {}),
        })
    except Exception as e:
        logger.exception("guru-scan error")
        raise errors.computation_failed(str(e))


@swing_bp.route("/api/stage-distribution", methods=["GET"])
def get_stage_distribution():
    """Stage distribution across the full watchlist."""
    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify({"counts": {}, "stage_totals": {}, "total": 0, "pct": {}})
    try:
        return jsonify(guru_scanner.compute_stage_distribution(symbols))
    except Exception as e:
        logger.exception("stage-distribution error")
        raise errors.computation_failed(str(e))
