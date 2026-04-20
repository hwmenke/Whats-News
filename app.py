"""
app.py - Flask REST API server for the Financial Dashboard
Run: python app.py
"""

import json
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
import ticker_lists as tl
import regression as reg
import strategy_tester as st
import swirligram as swirl
import errors
from errors import ApiError

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)
errors.register(app)

# Initialise the database on startup
db.init_db()


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
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    if method not in ("kama", "adma"):
        raise errors.validation("method must be 'kama' or 'adma'")
    result = adaptive.optimize_adaptive_trend(symbol.upper(), freq, method)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- Scanner --------------------------------------------------------------------

@app.route("/api/scanner", methods=["GET"])
def get_scanner():
    """Compute multi-timeframe scanner metrics for every watched symbol."""
    symbols = [s['symbol'] for s in db.list_symbols()]
    if not symbols:
        return jsonify([])
    data = scan.compute_scanner(symbols)
    return jsonify(data)


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


# -- Regression -----------------------------------------------------------------

@app.route("/api/regression/factor-status", methods=["GET"])
def get_factor_status():
    """Return availability of all macro factors in the DB."""
    return jsonify(reg.factor_status())


@app.route("/api/regression/<string:symbol>", methods=["GET"])
def get_regression(symbol):
    """Run OLS regression of symbol forward returns on macro factor features."""
    freq = request.args.get("freq", "daily")
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    try:
        horizon  = int(request.args.get("horizon",  5))
        lookback = int(request.args.get("lookback", 504))
    except (TypeError, ValueError):
        raise errors.validation("horizon and lookback must be integers")
    if not (1 <= horizon <= 60):
        raise errors.validation("horizon must be 1–60")
    if not (60 <= lookback <= 2000):
        raise errors.validation("lookback must be 60–2000")
    result = reg.compute_regression(symbol.upper(), freq, horizon, lookback)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


# -- Strategy Tester ------------------------------------------------------------

@app.route("/api/strategy/backtest", methods=["POST"])
def strategy_backtest():
    """Run a vectorised backtest for a symbol + strategy config."""
    body   = request.get_json(force=True, silent=True) or {}
    symbol = body.get("symbol", "")
    freq   = body.get("freq", "daily")
    config = body.get("config", {})
    if not symbol:
        raise errors.symbol_required()
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    result = st.run_backtest(symbol.upper(), freq, config)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


@app.route("/api/strategy/walk-forward", methods=["POST"])
def strategy_walk_forward():
    """Walk-forward optimization for a strategy config."""
    body   = request.get_json(force=True, silent=True) or {}
    symbol = body.get("symbol", "")
    freq   = body.get("freq", "daily")
    config = body.get("config", {})
    if not symbol:
        raise errors.symbol_required()
    if freq not in ("daily", "weekly"):
        raise errors.validation("freq must be 'daily' or 'weekly'")
    result = st.walk_forward_optimize(symbol.upper(), freq, config)
    if "error" in result:
        raise errors.no_data(symbol.upper())
    return jsonify(result)


@app.route("/api/strategy/monte-carlo", methods=["POST"])
def strategy_monte_carlo():
    """Bootstrap Monte Carlo simulation over a list of trade returns."""
    body   = request.get_json(force=True, silent=True) or {}
    trades = body.get("trades", [])
    n_sim  = int(body.get("n_sim", 1000))
    if not trades:
        raise ApiError("SYMBOL_REQUIRED", "trades list required", http=400)
    result = st.monte_carlo(trades, n_sim)
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


# -- Cache stats (debug) --------------------------------------------------------

@app.route("/api/_cache/stats", methods=["GET"])
def get_cache_stats():
    """Return indicator cache hit/miss stats."""
    import indicator_cache as cache
    return jsonify(cache.cache_stats())


# -- Entry point ----------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"\n  Financial Dashboard running at http://localhost:{port}\n")
    app.run(debug=True, port=port)
