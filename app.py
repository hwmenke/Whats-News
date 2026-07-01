"""
app.py - Flask REST API server for the Financial Dashboard
Run: python app.py
"""

import concurrent.futures
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS

import database as db
import data_fetcher as fetcher
import indicators as ind
import stats as stats
import adaptive_trend as adaptive
import scanner as scan
from utils import kama as kama_fn, rsi as rsi_fn
import ticker_lists as tl
import knn_model
import backtester
import spy_vix_phase_plane as phase_plane
import newsletter_engine
import social_trends
import insights
import llm_insights
import swirligram as swirl
import market_regime as mr
import momentum_ranker as mom_rank
import vol_momentum as vol_mom
import seasonality as seas
import data_quality as dq
import portfolio_backtest as pb
import errors
from errors import ApiError
from api import ALL_BLUEPRINTS
import journal
import scorecards
import regime as regime_mod
import risk as risk_mod
import settings_store

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)
errors.register(app)
for _bp in ALL_BLUEPRINTS:
    app.register_blueprint(_bp)

# Initialise the database on startup
db.init_db()

# In-memory cache for the phase-plane image (rebuilt at most once per hour)
_pp_cache: dict = {"png": None, "meta": None, "ts": 0.0}

# Warm the numba JIT cache so the first real request isn't slow
try:
    from ta_core import _kama_nb as _kama_nb_fn
    import numpy as _np_warm
    if _kama_nb_fn is not None:
        _kama_nb_fn(_np_warm.ones(50, dtype=float), 10, 0.6667, 0.0645)
    del _kama_nb_fn, _np_warm
except Exception:
    pass


# -- Helpers --------------------------------------------------------------------

_AT_INT_PARAMS   = ["sb_er","sb_fast","sb_slow","mb_er","mb_fast","mb_slow",
                    "lb_er","lb_fast","lb_slow","atr_n"]
_AT_FLOAT_PARAMS = ["confirm_mult"]


def _parse_at_config() -> dict:
    """Parse optional adaptive-trend tuning params from the current request."""
    config = {}
    for p in _AT_INT_PARAMS:
        v = request.args.get(p)
        if v is not None:
            try:
                config[p] = int(v)
            except ValueError:
                pass
    for p in _AT_FLOAT_PARAMS:
        v = request.args.get(p)
        if v is not None:
            try:
                config[p] = float(v)
            except ValueError:
                pass
    return config


# -- Optional HTTP basic auth (set DASHBOARD_PASSWORD to enable) ---------------
# Off by default for local use; turn it on before exposing the dashboard
# beyond localhost (e.g. behind a Cloudflare Tunnel).
_DASH_USER = os.environ.get("DASHBOARD_USER", "admin")
_DASH_PASS = os.environ.get("DASHBOARD_PASSWORD", "")

if _DASH_PASS:
    import base64
    from functools import wraps

    def _check_auth(header):
        if not header or not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.split(None, 1)[1]).decode("utf-8")
            u, _, p = decoded.partition(":")
        except Exception:
            return False
        return u == _DASH_USER and p == _DASH_PASS

    @app.before_request
    def _require_auth():
        if request.method == "OPTIONS":          # let CORS preflights through
            return None
        if not _check_auth(request.headers.get("Authorization", "")):
            return Response("Auth required", 401,
                            {"WWW-Authenticate": 'Basic realm="FinDash"'})

    print("++ app: HTTP basic auth enabled")


# -- Static files ---------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# -- Symbols --------------------------------------------------------------------

@app.route("/api/symbols", methods=["GET"])
def get_symbols():
    return jsonify(db.list_symbols())


@app.route("/api/symbols", methods=["POST"])
def add_symbol():
    data   = request.get_json(force=True)
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        raise errors.symbol_required()
    added = db.add_symbol(symbol)
    if not added:
        return jsonify({"message": f"{symbol} already in watchlist"}), 200
    return jsonify({"message": f"{symbol} added"}), 201


@app.route("/api/symbols/<string:symbol>", methods=["DELETE"])
def delete_symbol(symbol):
    db.remove_symbol(symbol.upper())
    return jsonify({"message": f"{symbol.upper()} removed"})


# -- Data fetch -----------------------------------------------------------------

@app.route("/api/fetch/<string:symbol>", methods=["POST"])
def fetch_symbol(symbol):
    print(f">> API: Fetch request for {symbol}")
    result = fetcher.fetch_and_store(symbol.upper())
    if "error" in result:
        print(f"!! API: Error fetching {symbol}: {result['error']}")
        raise errors.fetch_failed(symbol.upper(), result["error"])
    print(f"<< API: Successfully fetched {symbol}")
    return jsonify(result)


@app.route("/api/refresh", methods=["POST"])
def refresh_all():
    symbols = db.list_symbols()
    results = []

    def _fetch(sym):
        try:
            return fetcher.fetch_and_store(sym)
        except Exception as e:
            return {"symbol": sym, "error": str(e)}

    with ThreadPoolExecutor(max_workers=min(8, len(symbols) or 1)) as pool:
        futures = {pool.submit(_fetch, s["symbol"]): s["symbol"] for s in symbols}
        for future in as_completed(futures):
            results.append(future.result())

    return jsonify(results)


# -- OHLCV ----------------------------------------------------------------------

@app.route("/api/ohlcv/<string:symbol>", methods=["GET"])
def get_ohlcv(symbol):
    freq = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 500))
    except (TypeError, ValueError):
        raise errors.validation("limit must be an integer")

    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    if limit <= 0:
        raise errors.validation("limit must be a positive integer")

    rows = db.get_ohlcv(symbol.upper(), freq, limit)
    if not rows:
        raise errors.no_data(symbol.upper())
    return jsonify(rows)


# -- Indicators -----------------------------------------------------------------

@app.route("/api/indicators/<string:symbol>", methods=["GET"])
def get_indicators(symbol):
    freq = request.args.get("freq", "daily")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")

    kama_param = request.args.get("kama", "10,20,50")
    try:
        kama_periods = [int(p) for p in kama_param.split(",") if p.strip()]
        if not kama_periods:
            kama_periods = [10, 20, 50]
    except ValueError:
        raise errors.validation("kama must be comma-separated integers")

    result = ind.compute_indicators(symbol.upper(), freq, kama_periods)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- KNN Lookalike --------------------------------------------------------------

@app.route("/api/knn/<string:symbol>")
def get_knn(symbol):
    try:
        k = int(request.args.get("k", 15))
    except (TypeError, ValueError):
        raise errors.validation("k must be an integer")
    result = knn_model.compute_knn_lookalike(symbol.upper(), k=k)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- Backtester -----------------------------------------------------------------

@app.route("/api/backtest/<string:symbol>")
def get_backtest(symbol):
    result = backtester.run_optimization(symbol.upper())
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- Stats ----------------------------------------------------------------------

@app.route("/api/stats/<string:symbol>", methods=["GET"])
def get_stats(symbol):
    result = stats.compute_stats(symbol.upper())
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- Adaptive Trend -------------------------------------------------------------

@app.route("/api/adaptive-trend/<string:symbol>", methods=["GET"])
def get_adaptive_trend(symbol):
    freq   = request.args.get("freq", "daily")
    method = request.args.get("method", "kama")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    if method not in ("kama", "adma"):
        raise errors.validation("method must be 'kama' or 'adma'")

    _int_keys = ("sb_er","sb_slow","mb_er","mb_slow","lb_er","lb_slow",
                 "atr_fast","atr_slow","atr_er")
    custom = {}
    for k in _int_keys:
        v = request.args.get(k)
        if v is not None:
            try:
                custom[k] = int(v)
            except ValueError:
                raise errors.validation(f"{k} must be an integer")

    result = adaptive.compute_adaptive_trend(
        symbol.upper(), freq, method, params=custom or None)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


@app.route("/api/adaptive-trend/<string:symbol>/optimize", methods=["POST"])
def optimize_trend(symbol):
    body   = request.get_json(force=True) or {}
    freq   = body.get("freq", "daily")
    method = body.get("method", "kama")
    if freq == "both":          # UI "Both" mode — optimize on the daily series
        freq = "daily"
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    if method not in ("kama", "adma"):
        raise errors.validation("method must be 'kama' or 'adma'")
    try:
        result = adaptive.optimize_adaptive_trend(symbol.upper(), freq, method)
    except Exception as e:
        logger.exception("optimize_adaptive_trend crashed for %s", symbol)
        raise errors.computation_failed(f"{type(e).__name__}: {e}")
    if "error" in result:
        # Pass the real reason through (e.g. insufficient bars) instead of
        # masking everything as a 404 no-data error.
        raise errors.ApiError("OPTIMIZE_FAILED", result["error"], http=422)
    return jsonify(result)


# -- Trend Scan ----------------------------------------------------------------

@app.route("/api/trend-scan")
def trend_scan():
    """Compute adaptive-trend metrics for every watchlist symbol."""
    freq       = request.args.get("freq",   "daily")
    method     = request.args.get("method", "kama")
    try:
        rsi_period = int(request.args.get("rsi_period", 14))
    except (TypeError, ValueError):
        return jsonify({"error": "rsi_period must be an integer"}), 400
    symbols    = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify([])

    at_config = _parse_at_config()

    def _one(sym):
        try:
            ohlcv = db.get_ohlcv_df(sym, freq, limit=600)
            if ohlcv.empty or len(ohlcv) < 30:
                return {"symbol": sym, "error": "No data — fetch first"}

            close = ohlcv["close"]
            price = float(close.iloc[-1])
            if price <= 0:
                return {"symbol": sym, "error": "Zero price"}

            rsi_s   = rsi_fn(close, rsi_period)
            rsi_val = round(float(rsi_s.dropna().iloc[-1]), 2) if len(rsi_s.dropna()) else None

            def _kd(k):
                s  = kama_fn(close, window=k)
                v  = s.dropna()
                if not len(v):
                    return None
                kv = float(v.iloc[-1])
                return round((price / kv - 1.0) * 100, 2) if kv > 0 else None

            trend = adaptive.compute_adaptive_trend(sym, freq, method, **at_config)

            def _tlast(key):
                arr = trend.get(key, [])
                for d in reversed(arr):
                    if d.get("value") is not None:
                        return float(d["value"])
                return None

            if "error" in trend:
                mrt = mdb = signal = None
            else:
                mrt    = _tlast("mrt")
                mdb    = _tlast("mdb")
                ms     = _tlast("medium_state")
                ss     = _tlast("short_state")
                ls     = _tlast("long_state")
                signal = int((ss or 0) + (ms or 0) + (ls or 0))

            tp2_price  = round(mdb / price, 4) if mdb and price else None
            price_stop = round(price / mrt, 4) if mrt and price else None
            if mrt and mdb and price:
                risk   = abs(price - mrt)
                reward = abs(mdb - price)
                rr = round(reward / risk, 2) if risk > 1e-10 else None
            else:
                rr = None

            return {
                "symbol":     sym,
                "price":      round(price, 2),
                "rsi":        rsi_val,
                "kama10_pct": _kd(10),
                "kama20_pct": _kd(20),
                "kama50_pct": _kd(50),
                "tp2_price":  tp2_price,
                "price_stop": price_stop,
                "rr":         rr,
                "signal":     signal,
                "mrt":        round(mrt, 2) if mrt else None,
                "mdb":        round(mdb, 2) if mdb else None,
            }
        except Exception as e:
            return {"symbol": sym, "error": str(e)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_one, symbols))

    return jsonify(results)


# -- Scanner --------------------------------------------------------------------

@app.route("/api/scanner", methods=["GET"])
def get_scanner():
    """Compute multi-timeframe scanner metrics for every watched symbol."""
    try:
        symbols = [s['symbol'] for s in db.list_symbols()]
        if not symbols:
            return jsonify([])
        data = scan.compute_scanner(symbols)
        return jsonify(data)
    except Exception:
        logger.exception("Scanner computation failed")
        raise errors.computation_failed("Scanner computation failed — check server logs")


# -- Social Trends --------------------------------------------------------------

@app.route("/api/social-trends", methods=["GET"])
def get_social_trends_route():
    """Trending words across Google/TikTok/Twitter/Instagram + pure-play ideas."""
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        return jsonify({"error": "days must be an integer"}), 400

    geo = (request.args.get("geo", "US") or "US").upper()

    src_param = request.args.get("sources", "")
    valid = {s["id"] for s in social_trends.SOURCES}
    sources = [s.strip().lower() for s in src_param.split(",") if s.strip().lower() in valid] or None

    force = request.args.get("force", "").lower() in ("1", "true", "yes")

    try:
        return jsonify(social_trends.get_social_trends(days, geo, sources, force=force))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/social-trends/top", methods=["GET"])
def get_social_trends_top():
    """Lightweight top-movers feed for the always-visible topbar banner."""
    try:
        limit = int(request.args.get("limit", 6))
    except (TypeError, ValueError):
        limit = 6
    try:
        data = social_trends.get_social_trends(30, "US", None)
        movers = [{
            "term":       t["term"],
            "momentum":   t["momentum"],
            "change_pct": t["change_pct"],
            "direction":  t["direction"],
            "tickers":    t.get("tickers", []),
        } for t in data["trends"][:max(1, min(limit, 12))]]
        return jsonify({"generated_at": data["generated_at"], "movers": movers})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/symbols/bulk", methods=["POST"])
def add_symbols_bulk():
    """Add several symbols at once, optionally tagging them with a group.

    Used by the Social Trends 'add whole theme as a group' action. Stores the
    symbols and applies the group tag; price data is fetched lazily on view.
    """
    data    = request.get_json(force=True) or {}
    symbols = [str(s).strip().upper() for s in data.get("symbols", []) if str(s).strip()]
    group   = str(data.get("group_tag", "")).strip()
    if not symbols:
        return jsonify({"error": "symbols list is empty"}), 400

    added = []
    for sym in symbols:
        db.add_symbol(sym)               # idempotent — skips if already present
        if group:
            db.set_symbol_group(sym, group)
        added.append(sym)
    return jsonify({"message": f"{len(added)} symbols added", "symbols": added,
                    "group_tag": group}), 201


@app.route("/api/social-trends/history", methods=["GET"])
def get_social_trend_history():
    """Past snapshots for one term — feeds the trend drill-down sparkline."""
    term = request.args.get("term", "").strip()
    if not term:
        return jsonify({"error": "term is required"}), 400
    try:
        days = max(1, min(int(request.args.get("days", 90)), 365))
    except (TypeError, ValueError):
        days = 90
    return jsonify({"term": term, "days": days,
                    "history": social_trends.get_term_history(term, days=days)})


@app.route("/api/social-trends/for-ticker/<string:ticker>", methods=["GET"])
def get_themes_for_ticker_route(ticker):
    """Reverse view — which trend themes contain this ticker."""
    return jsonify({"ticker": ticker.upper(),
                    "themes": social_trends.get_themes_for_ticker(ticker)})


@app.route("/api/social-trends/theme/<path:theme>", methods=["GET"])
def get_theme_cohort_route(theme):
    """All stocks in a theme + 5d/20d cohort stats — feeds drill-down modal."""
    stats = social_trends.get_theme_cohort_stats(theme)
    if not stats:
        return jsonify({"error": "theme not found"}), 404
    return jsonify(stats)


@app.route("/api/social-trends/prime", methods=["POST"])
def prime_idea_prices():
    """Background OHLCV sweep for the current top pure-play tickers.

    Bounded by the caller's ``limit`` (max 30). Idempotent: a sweep already
    running is reported via ``/api/social-trends/prime/status``.
    """
    body  = request.get_json(force=True, silent=True) or {}
    try:
        limit = max(1, min(int(body.get("limit", 20)), 30))
    except (TypeError, ValueError):
        limit = 20

    data    = social_trends.get_social_trends(30)
    tickers = [i["ticker"] for i in (data.get("ideas") or [])
               if not i.get("in_watchlist") and i.get("ret_20d") is None][:limit]
    if not tickers:
        return jsonify({"started": False, "queued": 0, "reason": "all top ideas already have price data"})

    res = social_trends.start_prime_sweep(tickers, fetcher.fetch_and_store, delay=1.2)
    return jsonify({**res, "tickers": tickers})


@app.route("/api/social-trends/prime/status", methods=["GET"])
def prime_status_route():
    return jsonify(social_trends.prime_status())


@app.route("/api/social-trends/reload-themes", methods=["POST"])
def reload_themes_route():
    """Force-reload themes.json (for editing the file while the app is running)."""
    try:
        themes = social_trends.load_themes(force=True)
        return jsonify({"loaded": len(themes)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# -- v5: LLM-augmented insight (ι) ---------------------------------------------

def _payload_for_llm():
    return social_trends.get_social_trends(30)


@app.route("/api/llm/narrative", methods=["GET"])
def llm_narrative_route():
    """Daily 'three things to watch' generated from today's payload."""
    return jsonify(llm_insights.daily_narrative(_payload_for_llm()))


@app.route("/api/llm/explain", methods=["GET"])
def llm_explain_route():
    term = request.args.get("term", "").strip()
    if not term:
        return jsonify({"error": "term required"}), 400
    return jsonify(llm_insights.explain_trend(term, _payload_for_llm()))


@app.route("/api/llm/critique", methods=["GET"])
def llm_critique_route():
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    payload = _payload_for_llm()
    idea = next((i for i in payload.get("ideas") or [] if i["ticker"] == ticker), None)
    if not idea:
        return jsonify({"error": f"no idea found for {ticker}"}), 404
    return jsonify(llm_insights.critique_idea(idea, payload))


# -- v5: derived analytics (π · ν · μ · κ.4 · λ · ο · ρ) -----------------------

@app.route("/api/insights/portfolio", methods=["GET"])
def insights_portfolio_route():
    """Phase μ — theme exposure of the watchlist (or an explicit ?tickers= list)."""
    raw = request.args.get("tickers")
    if raw:
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    else:
        tickers = [s["symbol"] for s in db.list_symbols()]
    return jsonify(insights.portfolio_exposure(tickers))


@app.route("/api/insights/streaks", methods=["GET"])
def insights_streaks_route():
    """Phase π — top terms by consecutive-day momentum streak."""
    try:
        days = max(2, min(int(request.args.get("days", 14)), 90))
    except (TypeError, ValueError):
        days = 14
    return jsonify({"days": days, "streaks": insights.streak_summary(days=days)})


@app.route("/api/insights/anomalies", methods=["GET"])
def insights_anomalies_route():
    """Phase π — momentum exceptional *for its theme*, not absolute."""
    return jsonify({"anomalies": insights.anomaly_baselines(_payload_for_llm())})


@app.route("/api/insights/arbitrage", methods=["GET"])
def insights_arbitrage_route():
    """Phase κ.4 — Google leading social (or vice versa) per term."""
    return jsonify({"arbitrage": insights.search_arbitrage(_payload_for_llm())})


@app.route("/api/insights/lifecycle/<path:term>", methods=["GET"])
def insights_lifecycle_route(term):
    payload = _payload_for_llm()
    t = next((x for x in payload.get("trends") or [] if x["term"].lower() == term.lower()), None)
    if not t:
        return jsonify({"error": "term not found"}), 404
    return jsonify({"term": t["term"], **insights.lifecycle_classify(t.get("spark") or [])})


@app.route("/api/insights/seasonality/<path:theme>", methods=["GET"])
def insights_seasonality_route(theme):
    hint = insights.seasonality_hint(theme)
    if not hint:
        return jsonify({"theme": theme, "season": None, "note": None})
    return jsonify(hint)


@app.route("/api/insights/position-size", methods=["GET"])
def insights_position_size_route():
    ticker = request.args.get("ticker", "").strip().upper()
    try:
        capital = float(request.args.get("capital", 10000))
    except (TypeError, ValueError):
        capital = 10000.0
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    payload = _payload_for_llm()
    idea = next((i for i in payload.get("ideas") or [] if i["ticker"] == ticker), None)
    if not idea:
        return jsonify({"error": f"no idea for {ticker}"}), 404
    return jsonify({"ticker": ticker, **insights.position_size(idea, capital)})


@app.route("/api/insights/risk/<string:ticker>", methods=["GET"])
def insights_risk_route(ticker):
    """Phase π — earnings within N days, FOMC, etc. (yfinance best-effort)."""
    return jsonify({"ticker": ticker.upper(), **insights.risk_overlay(ticker)})


@app.route("/api/insights/sec/<string:ticker>", methods=["GET"])
def insights_sec_route(ticker):
    """Phase λ — Form 4 / 13F counts as 'smart money confirms' read."""
    return jsonify({"ticker": ticker.upper(), **insights.institutional_signal(ticker)})


@app.route("/api/insights/trade-links/<string:ticker>", methods=["GET"])
def insights_trade_links_route(ticker):
    return jsonify({"ticker": ticker.upper(), "links": insights.trade_deeplinks(ticker)})


@app.route("/api/insights/rotation", methods=["GET"])
def insights_rotation_route():
    """Phase ξ.3 — which themes gained or lost attention vs N days ago."""
    try:
        days = max(1, min(int(request.args.get("days", 7)), 60))
    except (TypeError, ValueError):
        days = 7
    return jsonify(insights.theme_rotation(days_back=days))


@app.route("/api/insights/scenario/<string:ticker>", methods=["GET"])
def insights_scenario_route(ticker):
    """Phase ο.2 — projected price if momentum hits a target."""
    try:
        target = int(request.args.get("target_mom", 95))
        beta   = float(request.args.get("beta", 0.30))
    except (TypeError, ValueError):
        return jsonify({"error": "target_mom must be int, beta must be float"}), 400
    payload = _payload_for_llm()
    idea = next((i for i in payload.get("ideas") or [] if i["ticker"] == ticker.upper()), None)
    if not idea:
        return jsonify({"error": f"no idea for {ticker}"}), 404
    return jsonify(insights.scenario(idea, target_momentum=target, theme_beta=beta))


@app.route("/api/insights/signal", methods=["GET"])
def insights_signal_route():
    """Phase ρ — evaluate a tiny DSL expression against the current ideas list."""
    expr = request.args.get("expr", "").strip()
    if not expr:
        return jsonify({"error": "expr required"}), 400
    return jsonify(insights.evaluate_signal(expr, _payload_for_llm()))


@app.route("/api/insights/sentiment", methods=["POST"])
def insights_sentiment_route():
    """Phase κ.2 — lightweight lexicon sentiment scorer."""
    body = request.get_json(force=True, silent=True) or {}
    text = body.get("text", "")
    return jsonify(social_trends.sentiment_score(text))


@app.route("/api/insights/co-movement", methods=["GET"])
def insights_comovement_route():
    """Phase ζ.1 — top-correlated + top-anti-correlated trend pairs."""
    return jsonify(insights.co_movement(_payload_for_llm()))


@app.route("/api/insights/rolled-over", methods=["GET"])
def insights_rolled_over_route():
    """Phase ζ.4 — terms whose phase flipped to fading (contrarian short)."""
    return jsonify({"rolled_over": insights.rolled_over(_payload_for_llm())})


@app.route("/api/insights/relative-strength/<string:ticker>", methods=["GET"])
def insights_rs_route(ticker):
    bm = request.args.get("vs", "SPY").upper()
    return jsonify({"ticker": ticker.upper(), **insights.relative_strength(ticker, bm)})


@app.route("/api/insights/liquidity/<string:ticker>", methods=["GET"])
def insights_liquidity_route(ticker):
    try:
        thr = float(request.args.get("threshold", 10_000_000))
    except (TypeError, ValueError):
        thr = 10_000_000
    return jsonify({"ticker": ticker.upper(), **insights.liquidity_guard(ticker, thr)})


@app.route("/api/insights/edge-grade/<string:ticker>", methods=["GET"])
def insights_edge_grade_route(ticker):
    payload = _payload_for_llm()
    idea = next((i for i in payload.get("ideas") or [] if i["ticker"] == ticker.upper()), None)
    if not idea:
        return jsonify({"error": f"no idea for {ticker}"}), 404
    rs  = insights.relative_strength(ticker, request.args.get("vs", "SPY").upper())
    liq = insights.liquidity_guard(ticker)
    return jsonify({"ticker": ticker.upper(),
                    **insights.edge_grade(idea, rs=rs, liq=liq),
                    "rs": rs, "liquidity": liq})


@app.route("/api/insights/digest", methods=["GET"])
def insights_digest_route():
    """Phase ε.1 — JSON + HTML morning digest."""
    fmt = request.args.get("format", "json").lower()
    d = insights.daily_digest()
    if fmt == "html":
        return Response(d["html"], mimetype="text/html")
    return jsonify(d["json"])


@app.route("/api/insights/theme-compare", methods=["GET"])
def insights_theme_compare_route():
    a = request.args.get("a", "").strip()
    b = request.args.get("b", "").strip()
    if not a or not b:
        return jsonify({"error": "both a and b required"}), 400
    return jsonify(insights.theme_compare(a, b))


@app.route("/api/insights/notebook/<string:ticker>", methods=["GET"])
def insights_notebook_route(ticker):
    payload = _payload_for_llm()
    idea = next((i for i in payload.get("ideas") or [] if i["ticker"] == ticker.upper()), None)
    if not idea:
        return jsonify({"error": f"no idea for {ticker}"}), 404
    snippet = insights.export_idea_notebook(idea)
    return Response(snippet, mimetype="text/x-python")


# -- Data Manager ---------------------------------------------------------------

@app.route("/api/data-manager/ticker-lists", methods=["GET"])
def get_ticker_lists():
    """Return the curated ticker library (categories + tickers)."""
    return jsonify(tl.TICKER_LIBRARY)


@app.route("/api/data-manager/fetch-batch", methods=["POST"])
def fetch_batch():
    """
    SSE streaming endpoint.
    POST body: {
        "tickers":      ["AAPL", ...],
        "start_date":   "2000-01-01",
        "delay":        1.5,
        "add_watchlist": true
    }
    """
    body        = request.get_json(force=True) or {}
    tickers     = [t.strip().upper() for t in body.get("tickers", []) if t.strip()]
    start_date  = body.get("start_date", "2000-01-01")
    delay       = float(body.get("delay", 1.5))
    add_wl      = bool(body.get("add_watchlist", True))

    if not tickers:
        raise ApiError("SYMBOL_REQUIRED", "tickers list is empty", http=400)

    delay = max(0.3, min(delay, 10.0))

    def generate():
        ok_count = 0
        fail_count = 0
        total = len(tickers)

        try:
            yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

            for i, sym in enumerate(tickers):
                try:
                    if add_wl:
                        db.add_symbol(sym)

                    result = fetcher.fetch_full_history(sym, start=start_date)

                    if "error" in result:
                        fail_count += 1
                        msg = result["error"]
                        ok  = False
                    else:
                        ok_count += 1
                        msg = (f"{result.get('daily_rows', 0)}d / "
                               f"{result.get('weekly_rows', 0)}w rows stored")
                        ok  = True

                    yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': ok, 'msg': msg})}\n\n"

                except GeneratorExit:
                    return
                except Exception as exc:
                    fail_count += 1
                    yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': False, 'msg': str(exc)})}\n\n"

                if i < total - 1:
                    time.sleep(delay)

            yield f"data: {json.dumps({'type': 'done', 'ok': ok_count, 'failed': fail_count})}\n\n"

        except GeneratorExit:
            return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- Price Ratios ---------------------------------------------------------------

@app.route("/api/fetch-ratio", methods=["POST"])
def fetch_ratio():
    """
    Compute and store a synthetic A/B ratio OHLCV series.
    POST body: {"sym_a": "AAPL", "sym_b": "MSFT"}
    """
    body  = request.get_json(force=True) or {}
    sym_a = body.get("sym_a", "").strip().upper()
    sym_b = body.get("sym_b", "").strip().upper()
    if not sym_a or not sym_b:
        raise ApiError("SYMBOL_REQUIRED", "sym_a and sym_b are required", http=400)
    if sym_a == sym_b:
        raise errors.validation("sym_a and sym_b must be different")
    valid = re.compile(r'^[\^]?[A-Z][A-Z0-9.\-\^]{0,9}$')
    if not valid.match(sym_a) or not valid.match(sym_b):
        raise errors.invalid_symbol(f"{sym_a}/{sym_b}")
    result = fetcher.fetch_ratio_and_store(sym_a, sym_b)
    if "error" in result:
        raise ApiError("FETCH_FAILED", result["error"], http=400)
    db.add_symbol(result["symbol"])
    return jsonify(result), 201


# -- Data Quality ----------------------------------------------------------------

@app.route("/api/data-quality/<string:symbol>", methods=["GET"])
def get_data_quality(symbol):
    """Return stored data-quality report for a symbol."""
    report = db.get_quality_report(symbol.upper())
    if report is None:
        # Run on-demand if not stored yet
        df = db.get_ohlcv_df(symbol.upper(), "daily", limit=2000)
        if df.empty:
            raise errors.no_data(symbol.upper())
        report = dq.validate(df, "daily")
    return jsonify(report)


@app.route("/api/strategy/portfolio-backtest", methods=["POST"])
def portfolio_backtest_endpoint():
    """Multi-asset portfolio backtest with vol-targeted / risk-parity / equal sizing."""
    body    = request.get_json(force=True, silent=True) or {}
    symbols = [s.strip().upper() for s in body.get("symbols", []) if s.strip()]
    freq    = body.get("freq", "daily")
    config  = body.get("config", {})
    sizing  = body.get("sizing", "vol_target")

    if not symbols:
        raise errors.symbol_required()
    if len(symbols) > 20:
        raise errors.validation("Max 20 symbols per portfolio backtest")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    if sizing not in ("vol_target", "risk_parity", "equal"):
        raise errors.validation("sizing must be vol_target, risk_parity, or equal")

    # Data quality gate
    for sym in symbols:
        df = db.get_ohlcv_df(sym, freq, limit=200)
        if df.empty:
            continue
        report = dq.validate(df, freq)
        if not report["ok"]:
            crits = [i for i in report["issues"] if i["severity"] == "critical"]
            if crits:
                raise ApiError("DATA_QUALITY",
                               f"Data quality check failed for {sym}",
                               hint=crits[0]["detail"], http=422)

    result = pb.run_portfolio_backtest(symbols, freq, config, sizing)
    if "error" in result:
        raise ApiError("COMPUTATION_FAILED", result["error"], http=422)
    return jsonify(result)


# -- Swirligram -----------------------------------------------------------------

@app.route("/api/swirligram/<string:symbol>", methods=["GET"])
def get_swirligram(symbol):
    """RSI phase-space (Swirligram) for daily + weekly timeframes."""
    try:
        rsi_period   = int(request.args.get("period", 14))
        daily_trail  = int(request.args.get("trail",  90))
        weekly_trail = int(request.args.get("wtrail", 52))
    except (TypeError, ValueError):
        raise errors.validation("period/trail must be integers")
    if not (5 <= rsi_period <= 50):
        raise errors.validation("period must be 5–50")
    if not (20 <= daily_trail <= 504):
        raise errors.validation("trail must be 20–504")
    result = swirl.compute_swirligram(
        symbol.upper(), rsi_period, daily_trail, weekly_trail)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- Market Regime --------------------------------------------------------------

@app.route("/api/market-regime", methods=["GET"])
def market_regime_route():
    symbol = request.args.get("symbol", "SPY").upper()
    result = mr.compute_market_regime(symbol)
    if "error" in result:
        return jsonify(result), 422
    return jsonify(result)


# -- Momentum Ranker ------------------------------------------------------------

@app.route("/api/momentum-rank", methods=["GET"])
def momentum_rank_route():
    result = mom_rank.compute_momentum_ranks()
    if "error" in result:
        return jsonify(result), 422
    return jsonify(result)


# -- Vol-Adjusted Momentum (turnover-brake portfolio) -----------------------------

_VM_FLOAT_PARAMS = ("l_max", "kappa", "tau", "lam", "delta_w", "delta_s",
                    "spread_bps", "impact_bps", "fee_bps")
_VM_INT_PARAMS   = ("mom_lb", "skip", "vol_lb")


def _parse_vm_params(source) -> dict:
    """Pull known vol-momentum params from a request-args dict or JSON body."""
    params = {}
    for k in _VM_FLOAT_PARAMS:
        v = source.get(k)
        if v is not None and v != "":
            try:
                params[k] = float(v)
            except (TypeError, ValueError):
                raise errors.validation(f"{k} must be a number")
    for k in _VM_INT_PARAMS:
        v = source.get(k)
        if v is not None and v != "":
            try:
                params[k] = int(v)
            except (TypeError, ValueError):
                raise errors.validation(f"{k} must be an integer")
    return params


@app.route("/api/vol-momentum", methods=["GET"])
def vol_momentum_route():
    """Dry-run: signals, ranks, target weights and trade decisions. No state change."""
    result = vol_mom.compute_vol_momentum(_parse_vm_params(request.args))
    if "error" in result:
        return jsonify(result), 422
    return jsonify(result)


@app.route("/api/vol-momentum/apply", methods=["POST"])
def vol_momentum_apply_route():
    """Compute and persist the partial-adjusted weights as the new state."""
    body = request.get_json(force=True, silent=True) or {}
    result = vol_mom.apply_vol_momentum(_parse_vm_params(body))
    if "error" in result:
        return jsonify(result), 422
    return jsonify(result)


@app.route("/api/vol-momentum/state", methods=["DELETE"])
def vol_momentum_reset_route():
    """Clear persisted weights/signals (fresh start: w_prev = 0, S_prev = 0)."""
    return jsonify({"cleared": vol_mom.reset_state()})


# -- Seasonality ----------------------------------------------------------------

@app.route("/api/seasonality/<string:symbol>", methods=["GET"])
def seasonality_route(symbol: str):
    result = seas.compute_seasonality(symbol.upper())
    if "error" in result:
        return jsonify(result), 422
    return jsonify(result)


# -- Cache stats (debug) --------------------------------------------------------

@app.route("/api/_cache/stats", methods=["GET"])
def get_cache_stats():
    """Return indicator cache hit/miss stats."""
    import indicator_cache as cache
    return jsonify(cache.cache_stats())


# -- Backup / restore -----------------------------------------------------------

@app.route("/api/backup", methods=["GET"])
def download_backup():
    """Download a copy of the SQLite database for backup purposes."""
    import shutil, datetime
    src = db.DB_PATH
    if not os.path.exists(src):
        raise errors.ApiError("NO_DATA", "Database file not found", http=404)
    date_tag = datetime.date.today().strftime("%Y%m%d")
    return send_from_directory(
        os.path.dirname(src),
        os.path.basename(src),
        as_attachment=True,
        download_name=f"finance_{date_tag}.db",
    )


# -- Phase Plane ----------------------------------------------------------------

@app.route("/api/phase-plane/meta", methods=["GET"])
def phase_plane_meta():
    """Return current state scalars (VIX, nu, rho, date) as JSON."""
    refresh = request.args.get("refresh", "0") == "1"
    if refresh or _pp_cache["meta"] is None or time.time() - _pp_cache["ts"] > 3600:
        try:
            _pp_cache["meta"] = phase_plane.generate_meta()
            _pp_cache["ts"]   = time.time()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify(_pp_cache["meta"])


@app.route("/api/phase-plane/image", methods=["GET"])
def phase_plane_image():
    """Render the phase-plane diagram and return it as a PNG image."""
    refresh = request.args.get("refresh", "0") == "1"
    if refresh or _pp_cache["png"] is None or time.time() - _pp_cache["ts"] > 3600:
        try:
            png, synthetic        = phase_plane.generate_figure_bytes()
            _pp_cache["png"]      = png
            _pp_cache["ts"]       = time.time()
            if _pp_cache["meta"] is None:
                _pp_cache["meta"] = phase_plane.generate_meta()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    from flask import make_response
    resp = make_response(_pp_cache["png"])
    resp.headers["Content-Type"]  = "image/png"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# Note: /api/newsletter/data is served by the news_routes blueprint
# (api/news_routes.py) — kept there to avoid a duplicate route registration.


# -- Trade Journal --------------------------------------------------------------

@app.route("/api/journal/trades", methods=["GET"])
def journal_list():
    status = request.args.get("status")
    if status and status not in ("open", "closed"):
        return jsonify({"error": "status must be 'open' or 'closed'"}), 400
    return jsonify(journal.list_trades(status))


@app.route("/api/journal/trades", methods=["POST"])
def journal_add():
    payload = request.get_json(force=True) or {}
    result = journal.add_trade(payload)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@app.route("/api/journal/trades/<int:trade_id>", methods=["PUT"])
def journal_update(trade_id):
    payload = request.get_json(force=True) or {}
    result = journal.update_trade(trade_id, payload)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/journal/trades/<int:trade_id>/close", methods=["POST"])
def journal_close(trade_id):
    payload = request.get_json(force=True) or {}
    result = journal.close_trade(
        trade_id,
        payload.get("exit_price"),
        exit_date=payload.get("exit_date"),
        chart_exit_url=payload.get("chart_exit_url"),
        notes=payload.get("notes"),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/journal/trades/<int:trade_id>", methods=["DELETE"])
def journal_delete(trade_id):
    return jsonify(journal.delete_trade(trade_id))


@app.route("/api/journal/stats", methods=["GET"])
def journal_stats():
    return jsonify(journal.cumulative_stats())


# -- Position sizing / risk -----------------------------------------------------

@app.route("/api/risk/size", methods=["POST"])
def risk_size():
    p = request.get_json(force=True) or {}
    if p.get("entry") is None or p.get("stop") is None:
        return jsonify({"error": "entry and stop are required"}), 400
    result = risk_mod.position_size(
        p.get("equity"), p.get("risk_pct"), p.get("entry"), p.get("stop"),
        direction=p.get("direction", "long"),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


# -- Journal Settings (equity / risk %) ------------------------------------------
# Namespaced under /api/journal/ — /api/settings is already used by
# api/news_routes.py for the FRED API key setting.

@app.route("/api/journal/settings", methods=["GET"])
def get_settings():
    return jsonify(settings_store.get_settings())


@app.route("/api/journal/settings", methods=["PUT"])
def put_settings():
    p = request.get_json(force=True) or {}
    try:
        result = settings_store.set_settings(p.get("equity"), p.get("risk_pct"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


# -- Momentum scan --------------------------------------------------------------

@app.route("/api/momentum-scan", methods=["GET"])
def momentum_scan():
    try:
        return jsonify(scorecards.run_momentum_scan())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -- Market regime --------------------------------------------------------------

@app.route("/api/regime", methods=["GET"])
def get_regime():
    try:
        return jsonify(regime_mod.compute_regime())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -- Entry point ----------------------------------------------------------------

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 8050))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  Financial Dashboard running at http://localhost:{port}\n")
    app.run(debug=debug, port=port)
