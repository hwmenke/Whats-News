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
import social_trends

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


@swing_bp.route("/api/focus-pipeline", methods=["GET"])
def focus_pipeline():
    """Watchlist grouped by tier (focus/watch/radar) with swing data + grade."""
    tiers = db.list_symbols_by_tier()
    result = {}
    for tier, syms in tiers.items():
        enriched = []
        for s in syms:
            entry = {"symbol": s["symbol"], "name": s.get("name") or "",
                     "sector": s.get("sector") or "",
                     "setup_grade": s.get("setup_grade") or "", "tier": tier}
            try:
                sd = swing_core.swing_data_for(s["symbol"])
                entry.update({"adr_pct": sd.get("adr_pct"), "rvol": sd.get("rvol"),
                              "atr_mult_50ma": sd.get("atr_mult_50ma")})
            except Exception:
                pass
            enriched.append(entry)
        result[tier] = enriched
    return jsonify(result)


@swing_bp.route("/api/symbols/<string:symbol>/tier", methods=["PUT"])
def set_tier(symbol):
    body = request.get_json(silent=True) or {}
    db.set_tier(symbol.upper(), body.get("tier", "watch"))
    return jsonify({"message": "ok"})


# ── Market rotation: RRG (relative-rotation graph) ──────────────────────────────
rrg_bp = Blueprint("mod_rrg", __name__)


@rrg_bp.route("/api/rrg", methods=["GET"])
def rrg():
    import numpy as np
    benchmark = request.args.get("benchmark", "SPY").upper()
    period = max(2, min(int(request.args.get("period", 10)), 52))
    trail_n = max(2, min(int(request.args.get("trail", 5)), 12))
    bdf = db.get_ohlcv_df(benchmark, "weekly", limit=120)
    if bdf.empty:
        return _bad(f"No data for benchmark {benchmark}. Fetch it first.", 404)
    symbols = [s["symbol"] for s in db.list_symbols() if s["symbol"] != benchmark]
    if not symbols:
        return jsonify({"benchmark": benchmark, "symbols": []})

    def _quad(r, m):
        if r >= 100 and m >= 100: return "leading"
        if r >= 100 and m < 100:  return "weakening"
        if r < 100 and m < 100:   return "lagging"
        return "improving"

    out = []
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "weekly", limit=120)
            if df.empty:
                continue
            common = df.index.intersection(bdf.index)
            if len(common) < period + 10:
                continue
            sc, bc = df.loc[common, "close"], bdf.loc[common, "close"]
            rs_raw = sc / bc.replace(0, float("nan"))
            rs_ema = rs_raw.ewm(span=period, adjust=False).mean()
            rs_roll = rs_ema.rolling(min(52, len(rs_ema))).mean().replace(0, float("nan"))
            rs_ratio = (rs_ema / rs_roll * 100).fillna(100)
            rs_mom = rs_ratio.pct_change(period) * 100 + 100
            valid = [(r, m) for r, m in zip(rs_ratio.values, rs_mom.values)
                     if np.isfinite(r) and np.isfinite(m)]
            trail = [{"rs_ratio": round(r, 3), "rs_mom": round(m, 3)} for r, m in valid[-trail_n:]]
            if not trail:
                continue
            last = trail[-1]
            out.append({"symbol": sym, "rs_ratio": last["rs_ratio"], "rs_mom": last["rs_mom"],
                        "trail": trail, "quadrant": _quad(last["rs_ratio"], last["rs_mom"])})
        except Exception:
            continue
    return jsonify({"benchmark": benchmark, "symbols": out})


# ── Sector heat-map ─────────────────────────────────────────────────────────────
sector_bp = Blueprint("mod_sector", __name__)


@sector_bp.route("/api/sector-heatmap", methods=["GET"])
def sector_heatmap():
    import datetime
    import numpy as np
    symbols = db.list_symbols()
    if not symbols:
        return jsonify([])
    ytd_start = datetime.date.today().replace(month=1, day=1).isoformat()
    sectors = {}
    for sym in symbols:
        sec = (sym.get("sector") or "Unknown").strip() or "Unknown"
        sectors.setdefault(sec, []).append(sym["symbol"])
    result = []
    for sector, syms in sorted(sectors.items()):
        rows = []
        for s in syms:
            df = db.get_ohlcv_df(s, "daily", limit=260)
            if df.empty or len(df) < 2:
                continue
            close = df["close"]

            def _ret(n):
                return float(close.iloc[-1] / close.iloc[-n] - 1) if len(close) >= n else None

            ytd_df = df[df.index.astype(str) >= ytd_start]
            ret_ytd = float(close.iloc[-1] / ytd_df["close"].iloc[0] - 1) if len(ytd_df) > 0 else None
            rows.append({"symbol": s, "close": round(float(close.iloc[-1]), 2),
                         "ret_1d": round(_ret(2), 4) if _ret(2) is not None else None,
                         "ret_5d": round(_ret(6), 4) if _ret(6) is not None else None,
                         "ret_20d": round(_ret(21), 4) if _ret(21) is not None else None,
                         "ret_ytd": round(ret_ytd, 4) if ret_ytd is not None else None})
        if rows:
            def _avg(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return round(float(np.mean(vals)), 4) if vals else None
            result.append({"sector": sector, "count": len(rows),
                           "avg_1d": _avg("ret_1d"), "avg_5d": _avg("ret_5d"),
                           "avg_20d": _avg("ret_20d"), "avg_ytd": _avg("ret_ytd"),
                           "symbols": rows})
    return jsonify(result)


# ── Social Trends (theme radar + pure-play mapper) ──────────────────────────────
social_bp = Blueprint("mod_social", __name__)


@social_bp.route("/api/social-trends", methods=["GET"])
def social_trends_route():
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        return _bad("days must be an integer")
    geo = (request.args.get("geo", "US") or "US").upper()
    valid = {s["id"] for s in social_trends.SOURCES}
    src = request.args.get("sources", "")
    sources = [s.strip().lower() for s in src.split(",") if s.strip().lower() in valid] or None
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    try:
        return jsonify(social_trends.get_social_trends(days, geo, sources, force=force))
    except Exception as e:
        return _bad(str(e), 500)


# ── Setup-trigger alerts (pure: reuses the momentum scanner) ────────────────────
import scorecards

alerts_bp = Blueprint("mod_alerts", __name__)


@alerts_bp.route("/api/alerts/scan", methods=["GET"])
def alerts_scan():
    """Current watchlist names triggering an A/A+ setup right now."""
    min_grade = request.args.get("grade", "A")
    rank = {"A+": 3, "A": 2, "B": 1}
    floor = rank.get(min_grade, 2)
    out = []
    for r in scorecards.run_momentum_scan():
        if r.get("error") or not r.get("setups"):
            continue
        if rank.get(r["best_grade"], 0) >= floor:
            best = r["setups"][0]
            out.append({"symbol": r["symbol"], "setup": best["type"],
                        "grade": best["grade"], "score": best["score"],
                        "price": r["metrics"].get("price")})
    return jsonify({"alerts": out, "count": len(out)})


# ── Earnings date lookup (network, guarded) ─────────────────────────────────────
earnings_bp = Blueprint("mod_earnings", __name__)


@earnings_bp.route("/api/earnings/<string:symbol>", methods=["GET"])
def earnings_route(symbol):
    """Next earnings date via yfinance; degrades to null offline."""
    sym = symbol.upper()
    try:
        import datetime as _dt
        import yfinance as yf
        tk = yf.Ticker(sym)
        nxt = None
        try:
            cal = tk.get_earnings_dates(limit=8)
            if cal is not None and len(cal):
                future = [d for d in cal.index.to_pydatetime()
                          if d.date() >= _dt.date.today()]
                nxt = (min(future) if future else max(cal.index.to_pydatetime())).date().isoformat()
        except Exception:
            cal = getattr(tk, "calendar", None)
            if cal is not None:
                try:
                    nxt = str(cal.loc["Earnings Date"][0])[:10]
                except Exception:
                    pass
        days = None
        if nxt:
            days = (_dt.date.fromisoformat(nxt[:10]) - _dt.date.today()).days
        return jsonify({"symbol": sym, "earnings_date": nxt, "days_until": days})
    except Exception as e:
        return jsonify({"symbol": sym, "earnings_date": None, "days_until": None,
                        "note": f"unavailable ({str(e)[:60]})"})
