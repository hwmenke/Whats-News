"""
mod_blueprints.py — Flask Blueprints for the ported analytics modules.

One Blueprint per dashboard module so each can be enabled/disabled
independently via the module registry. Error handling is plain jsonify
(decoupled from jeff's ApiError infra). Compute modules are pure-Python.
"""

import logging

from flask import Blueprint, jsonify, request

import database as db
import regression as reg
import strategy_tester as st
import portfolio_backtest as pb
import factor_attribution as fa
import data_quality as dq
import swirligram as swirl
import market_regime as mr
import momentum_ranker as mom_rank
import seasonality as seas
import factor_model as fmodel
import knn_forecast as knn
import news as news_mod
import swing_core
import jeff_scanner

log = logging.getLogger(__name__)


def _bad(msg, code=400):
    return jsonify({"error": msg}), code


# ── Strategy Tester (backtest / walk-forward / portfolio / monte-carlo) ─────────
strategy_bp = Blueprint("mod_strategy", __name__)


@strategy_bp.route("/api/strategy/backtest", methods=["POST"])
def strategy_backtest():
    body = request.get_json(force=True, silent=True) or {}
    symbol = (body.get("symbol") or "").upper()
    freq = body.get("freq", "daily")
    if not symbol:
        return _bad("symbol is required")
    if freq not in ("daily", "weekly"):
        return _bad("freq must be 'daily' or 'weekly'")
    result = st.run_backtest(symbol, freq, body.get("config", {}))
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


@strategy_bp.route("/api/strategy/walk-forward", methods=["POST"])
def strategy_walk_forward():
    body = request.get_json(force=True, silent=True) or {}
    symbol = (body.get("symbol") or "").upper()
    freq = body.get("freq", "daily")
    if not symbol:
        return _bad("symbol is required")
    result = st.walk_forward_optimize(symbol, freq, body.get("config", {}))
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


@strategy_bp.route("/api/strategy/portfolio-backtest", methods=["POST"])
def strategy_portfolio_backtest():
    body = request.get_json(force=True, silent=True) or {}
    symbols = [s.strip().upper() for s in body.get("symbols", []) if s.strip()]
    freq = body.get("freq", "daily")
    sizing = body.get("sizing", "vol_target")
    if not symbols:
        return _bad("symbols are required")
    if len(symbols) > 20:
        return _bad("Max 20 symbols per portfolio backtest")
    if sizing not in ("vol_target", "risk_parity", "equal"):
        return _bad("sizing must be vol_target, risk_parity, or equal")
    result = pb.run_portfolio_backtest(symbols, freq, body.get("config", {}), sizing)
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


@strategy_bp.route("/api/strategy/monte-carlo", methods=["POST"])
def strategy_monte_carlo():
    body = request.get_json(force=True, silent=True) or {}
    trades = body.get("trades", [])
    if not trades:
        return _bad("trades list required")
    return jsonify(st.monte_carlo(trades, int(body.get("n_sim", 1000))))


@strategy_bp.route("/api/strategy/factor-attribution", methods=["POST"])
def strategy_factor_attribution():
    body = request.get_json(force=True, silent=True) or {}
    net_ret = body.get("net_ret", [])
    dates = body.get("dates", [])
    if not net_ret or not dates or len(net_ret) != len(dates):
        return _bad("net_ret and dates required and must be equal length")
    result = fa.compute_factor_attribution(net_ret, dates, body.get("freq", "daily"),
                                           int(body.get("lookback", 504)))
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


@strategy_bp.route("/api/data-quality/<string:symbol>", methods=["GET"])
def data_quality(symbol):
    dfr = db.get_ohlcv_df(symbol.upper(), "daily", limit=2000)
    if dfr.empty:
        return _bad("No data — fetch the symbol first", 404)
    return jsonify(dq.validate(dfr, "daily"))


# ── Swirligram (RSI phase-space) ────────────────────────────────────────────────
swirligram_bp = Blueprint("mod_swirligram", __name__)


@swirligram_bp.route("/api/swirligram/<string:symbol>", methods=["GET"])
def swirligram_route(symbol):
    try:
        period = int(request.args.get("period", 14))
        trail = int(request.args.get("trail", 90))
        wtrail = int(request.args.get("wtrail", 52))
    except (TypeError, ValueError):
        return _bad("period/trail must be integers")
    result = swirl.compute_swirligram(symbol.upper(), period, trail, wtrail)
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── Market Regime (Market Dashboard) ────────────────────────────────────────────
market_bp = Blueprint("mod_market", __name__)


@market_bp.route("/api/market-regime", methods=["GET"])
def market_regime_route():
    result = mr.compute_market_regime(request.args.get("symbol", "SPY").upper())
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── Momentum Ranker ──────────────────────────────────────────────────────────────
momranker_bp = Blueprint("mod_momranker", __name__)


@momranker_bp.route("/api/momentum-rank", methods=["GET"])
def momentum_rank_route():
    result = mom_rank.compute_momentum_ranks()
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── Seasonality ──────────────────────────────────────────────────────────────────
seasonality_bp = Blueprint("mod_seasonality", __name__)


@seasonality_bp.route("/api/seasonality/<string:symbol>", methods=["GET"])
def seasonality_route(symbol):
    result = seas.compute_seasonality(symbol.upper())
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── Factor Model ─────────────────────────────────────────────────────────────────
factor_bp = Blueprint("mod_factor", __name__)


@factor_bp.route("/api/factor-model", methods=["GET"])
def factor_model_route():
    lookback = min(int(request.args.get("lookback", 504)), 1260)
    result = fmodel.compute_factor_model(lookback)
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── Regression (macro factor OLS) ────────────────────────────────────────────────
regression_bp = Blueprint("mod_regression", __name__)


@regression_bp.route("/api/regression/factor-status", methods=["GET"])
def factor_status():
    return jsonify(reg.factor_status())


@regression_bp.route("/api/regression/<string:symbol>", methods=["GET"])
def regression_route(symbol):
    freq = request.args.get("freq", "daily")
    try:
        horizon = int(request.args.get("horizon", 5))
        lookback = int(request.args.get("lookback", 504))
    except (TypeError, ValueError):
        return _bad("horizon and lookback must be integers")
    result = reg.compute_regression(symbol.upper(), freq, horizon, lookback)
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── KNN Forecast (17-feature weighted) ───────────────────────────────────────────
knnf_bp = Blueprint("mod_knnforecast", __name__)


@knnf_bp.route("/api/knn-forecast/<string:symbol>", methods=["POST"])
def knn_forecast_route(symbol):
    body = request.get_json(silent=True) or {}
    freq = body.get("freq", "daily")
    k = max(5, min(int(body.get("k", 20)), 50))
    raw_w = body.get("weights", {})
    group_weights = None
    if raw_w:
        total = sum(float(v) for v in raw_w.values() if v is not None)
        if total > 1e-10:
            group_weights = {g: float(raw_w.get(g, 0)) / total
                             for g in ["trend", "momentum", "volatility",
                                       "price_action", "volume"]}
    result = knn.compute_knn_forecast(symbol.upper(), freq, k, group_weights)
    return jsonify(result) if "error" not in result else (jsonify(result), 422)


# ── News (RSS headlines + naive sentiment) ───────────────────────────────────────
news_bp = Blueprint("mod_news", __name__)


@news_bp.route("/api/news/<string:symbol>", methods=["GET"])
def news_route(symbol):
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    return jsonify(news_mod.fetch_news(symbol.upper(), limit))


# ── Jeff Sun Swing suite (swing data / grade / scan / breadth / sizing) ─────────
swing_bp = Blueprint("mod_swing", __name__)


@swing_bp.route("/api/swing-data/<string:symbol>", methods=["GET"])
def swing_data(symbol):
    try:
        return jsonify(swing_core.swing_data_for(symbol.upper()))
    except ValueError as e:
        return _bad(str(e), 404)
    except Exception as e:
        log.exception("swing-data")
        return _bad(str(e), 500)


@swing_bp.route("/api/setup-grade/<string:symbol>", methods=["GET"])
def setup_grade(symbol):
    try:
        sd = swing_core.swing_data_for(symbol.upper())
        result = swing_core.grade_from_swing(sd)
        result.update(sd)
        return jsonify(result)
    except ValueError as e:
        return _bad(str(e), 404)
    except Exception as e:
        log.exception("setup-grade")
        return _bad(str(e), 500)


@swing_bp.route("/api/jeff-scan", methods=["GET"])
def jeff_scan():
    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify({"rows": [], "spy_available": False})
    try:
        rows = jeff_scanner.compute_jeff_scan(symbols)
        spy = any(r.get("rs_vs_spy") is not None for r in rows)
        return jsonify({"rows": rows, "spy_available": spy})
    except Exception as e:
        log.exception("jeff-scan")
        return _bad(str(e), 500)


@swing_bp.route("/api/breadth", methods=["GET"])
def breadth():
    symbols = db.list_symbols()
    if not symbols:
        return _bad("No symbols in watchlist", 404)
    above_20 = above_50 = above_200 = adv = dec = new_hi = new_lo = total = 0
    for row in symbols:
        try:
            dfr = db.get_ohlcv_df(row["symbol"], freq="daily", limit=260)
            if dfr.empty or len(dfr) < 20:
                continue
            close = dfr["close"]
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else last
            total += 1
            if last > float(close.tail(21).mean()):  above_20 += 1
            if last > float(close.tail(51).mean()):  above_50 += 1
            if len(close) >= 200 and last > float(close.tail(201).mean()): above_200 += 1
            if last >= prev: adv += 1
            else:            dec += 1
            hi = float(dfr["high"].tail(252).max())
            lo = float(dfr["low"].tail(252).min())
            if hi > 0 and abs(last - hi) / hi < 0.01: new_hi += 1
            if lo > 0 and abs(last - lo) / lo < 0.01: new_lo += 1
        except Exception:
            pass
    pct = lambda n: round(n / total * 100, 1) if total else 0
    return jsonify({
        "total": total, "pct_above_20ma": pct(above_20),
        "pct_above_50ma": pct(above_50), "pct_above_200ma": pct(above_200),
        "advances": adv, "declines": dec,
        "ad_ratio": round(adv / dec, 2) if dec else adv,
        "new_highs": new_hi, "new_lows": new_lo,
    })


@swing_bp.route("/api/position-size", methods=["POST"])
def position_size():
    body = request.get_json(silent=True) or {}
    account = float(body.get("account", 100000))
    risk_pct = float(body.get("risk_pct", 0.5)) / 100.0
    entry = float(body.get("entry", 0))
    stop = float(body.get("stop", 0))
    if entry <= 0 or stop <= 0 or stop >= entry:
        return _bad("entry must be > stop > 0")
    dollar_risk = account * risk_pct
    rps = entry - stop
    shares = int(dollar_risk / rps)
    gross = shares * entry
    return jsonify({
        "account": account, "risk_pct": risk_pct * 100, "entry": entry, "stop": stop,
        "dollar_risk": round(dollar_risk, 2), "risk_per_sh": round(rps, 4),
        "shares": shares, "gross_exp": round(gross, 2),
        "stop_pct": round(rps / entry * 100, 2),
        "pct_portfolio": round(gross / account * 100, 2),
        "tp1_1r": round(entry + rps, 2), "tp2_3r": round(entry + rps * 3, 2),
        "tp3_5r": round(entry + rps * 5, 2), "tp4_10r": round(entry + rps * 10, 2),
    })
