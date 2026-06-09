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
        raise errors.validation(f"Invalid tier: {tier}. Use watchlist/stalk/focus/active")
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
