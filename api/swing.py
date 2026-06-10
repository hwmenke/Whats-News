"""Jeff Sun swing-workflow routes: swing data, setup grade, scan,
focus-pipeline tiers."""
import logging
from flask import Blueprint, jsonify, request

import database as db
import errors
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
            })
            trig = row["trigger_price"]
            stop = row["stop_price"]
            if trig and stop and trig > stop:
                row["risk_per_sh"] = round(trig - stop, 4)
            if trig and sd["last_close"]:
                row["dist_to_trigger_pct"] = round(
                    (trig / sd["last_close"] - 1) * 100, 2)
            row["flags"] = {
                "lod_too_far":  sd["lod_dist_atr"] > 0.6,
                "too_extended": sd["atr_mult_50ma"] > 4.0,
                "low_rvol":     sd["rvol"] < 1.0,
            }
        except Exception:
            row["error"] = "no data"
        rows.append(row)

    return jsonify({"rows": rows})


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
