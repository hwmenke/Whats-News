"""
app.py - Flask REST API server for the Financial Dashboard
Run: python app.py
"""

import atexit
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

import database as db
import data_fetcher as fetcher
import indicators as ind
import stats as stats
import knn_model
import backtester
import scanner
import adaptive_trend as adaptive
import ticker_lists as tl
from config import KAMA_PERIODS

app = Flask(__name__, static_folder=".", static_url_path="")

# Restrict CORS to localhost by default; override with CORS_ORIGINS env var
# e.g. CORS_ORIGINS="https://app.example.com,https://staging.example.com"
_cors_origins_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else [r"http://localhost:\d+", r"http://127\.0\.0\.1:\d+"]
)
CORS(app, origins=_cors_origins, supports_credentials=False)

# Shared ref so atexit can join the S&P 500 fetch thread
_sp500_fetch_thread = [None]


def _shutdown_fetch_thread():
    t = _sp500_fetch_thread[0]
    if t is not None and t.is_alive():
        logger.info("Waiting up to 10 s for S&P 500 fetch thread to finish…")
        t.join(timeout=10)
        if t.is_alive():
            logger.warning("Fetch thread did not finish within timeout — exiting anyway")


atexit.register(_shutdown_fetch_thread)

# Initialise the database on startup
db.init_db()


def _err(message: str, status: int = 400):
    """Return a consistent JSON error response."""
    return jsonify({"error": message}), status


class _RateLimiter:
    """Simple per-key token-bucket rate limiter (no external deps)."""

    def __init__(self, min_interval_seconds: float):
        self._interval = min_interval_seconds
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last < self._interval:
                return False
            self._last[key] = now
            return True


# Minimum seconds between successive calls per symbol / globally
_fetch_limiter   = _RateLimiter(min_interval_seconds=30)   # per symbol
_refresh_limiter = _RateLimiter(min_interval_seconds=120)  # global


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
    data   = request.get_json(silent=True) or {}
    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    added = db.add_symbol(symbol)
    if not added:
        return jsonify({"message": f"{symbol} already in watchlist"}), 200
    return jsonify({"message": f"{symbol} added"}), 201


@app.route("/api/symbols/<string:symbol>", methods=["DELETE"])
def delete_symbol(symbol):
    db.remove_symbol(symbol.upper())
    return jsonify({"message": f"{symbol.upper()} removed"})


@app.route("/api/symbols/<string:symbol>/group", methods=["PUT"])
def set_symbol_group(symbol):
    data      = request.get_json(silent=True) or {}
    group_tag = data.get("group_tag", "").strip()
    db.set_symbol_group(symbol.upper(), group_tag)
    return jsonify({"message": "ok"})


# -- Data fetch -----------------------------------------------------------------

@app.route("/api/fetch/<string:symbol>", methods=["POST"])
def fetch_symbol(symbol):
    if not _fetch_limiter.is_allowed(symbol.upper()):
        return _err(f"Rate limit: wait 30 s before re-fetching {symbol.upper()}", 429)
    logger.info("Fetch request for %s", symbol)
    try:
        result = fetcher.fetch_and_store(symbol.upper())
        if "error" in result:
            logger.warning("Error fetching %s: %s", symbol, result["error"])
            return jsonify(result), 400
        logger.info("Successfully fetched %s", symbol)
        return jsonify(result)
    except Exception as e:
        logger.error("Exception fetching %s: %s", symbol, e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def refresh_all():
    if not _refresh_limiter.is_allowed("global"):
        return _err("Rate limit: wait 2 min before refreshing all symbols", 429)
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
        return jsonify({"error": "limit must be an integer"}), 400

    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")
    if limit <= 0:
        return _err("limit must be a positive integer")

    rows = db.get_ohlcv(symbol.upper(), freq, limit)
    if not rows:
        return _err("No data. Fetch the symbol first.", 404)
    return jsonify(rows)


# -- Indicators -----------------------------------------------------------------

@app.route("/api/indicators/<string:symbol>", methods=["GET"])
def get_indicators(symbol):
    freq = request.args.get("freq", "daily")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    kama_param = request.args.get("kama", "10,20,50")
    try:
        kama_periods = [int(p) for p in kama_param.split(",") if p.strip()]
        if not kama_periods:
            kama_periods = KAMA_PERIODS
    except ValueError:
        return _err("kama must be comma-separated integers")

    result = ind.compute_indicators(symbol.upper(), freq, kama_periods)
    return jsonify(result)


# -- Stats ----------------------------------------------------------------------

@app.route("/api/stats/<string:symbol>", methods=["GET"])
def get_stats(symbol):
    try:
        result = stats.compute_stats(symbol.upper())
        if "error" in result:
            return _err(result["error"], 404)
        return jsonify(result)
    except Exception as e:
        return _err(str(e), 500)


# -- KNN Lookalike --------------------------------------------------------------

@app.route("/api/knn/<string:symbol>")
def get_knn(symbol):
    try:
        k = int(request.args.get("k", 15))
        if k < 1:
            raise ValueError
    except (TypeError, ValueError):
        return _err("k must be a positive integer")
    try:
        result = knn_model.compute_knn_lookalike(symbol.upper(), k=k)
        if "error" in result:
            return _err(result["error"], 404)
        return jsonify(result)
    except Exception as e:
        return _err(str(e), 500)


# -- Backtester -----------------------------------------------------------------

@app.route("/api/backtest/<string:symbol>")
def get_backtest(symbol):
    try:
        result = backtester.run_optimization(symbol.upper())
        if "error" in result:
            return _err(result["error"], 404)
        return jsonify(result)
    except Exception as e:
        return _err(str(e), 500)


# -- Adaptive Trend -------------------------------------------------------------

@app.route("/api/adaptive-trend/<string:symbol>", methods=["GET"])
def get_adaptive_trend(symbol):
    freq   = request.args.get("freq", "daily")
    method = request.args.get("method", "kama")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")
    if method not in ("kama", "adma"):
        return _err("method must be 'kama' or 'adma'")

    # Optional tuning params
    int_params   = ["sb_er","sb_fast","sb_slow","mb_er","mb_fast","mb_slow",
                    "lb_er","lb_fast","lb_slow","atr_n"]
    float_params = ["confirm_mult"]
    config = {}
    for p in int_params:
        v = request.args.get(p)
        if v is not None:
            try: config[p] = int(v)
            except ValueError: pass
    for p in float_params:
        v = request.args.get(p)
        if v is not None:
            try: config[p] = float(v)
            except ValueError: pass

    try:
        result = adaptive.compute_adaptive_trend(symbol.upper(), freq, method, **config)
        if "error" in result:
            return _err(result["error"], 404)
        return jsonify(result)
    except Exception as e:
        return _err(str(e), 500)


# -- Trend Scan ----------------------------------------------------------------

@app.route("/api/trend-scan")
def trend_scan():
    """Compute adaptive-trend metrics for every watchlist symbol."""
    import concurrent.futures
    from scanner import _kama as kama_fn, _rsi as rsi_fn

    freq   = request.args.get("freq",   "daily")
    method = request.args.get("method", "kama")
    try:
        rsi_period = int(request.args.get("rsi_period", 14))
        if rsi_period < 2:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "rsi_period must be an integer >= 2"}), 400
    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify([])

    # Parse the same KAMA/ADMA config params as /api/adaptive-trend
    int_params   = ["sb_er","sb_fast","sb_slow","mb_er","mb_fast","mb_slow",
                    "lb_er","lb_fast","lb_slow","atr_n"]
    float_params = ["confirm_mult"]
    at_config = {}
    for p in int_params:
        v = request.args.get(p)
        if v is not None:
            try: at_config[p] = int(v)
            except ValueError: pass
    for p in float_params:
        v = request.args.get(p)
        if v is not None:
            try: at_config[p] = float(v)
            except ValueError: pass

    def _one(sym):
        try:
            ohlcv = db.get_ohlcv_df(sym, freq, limit=600)
            if ohlcv.empty or len(ohlcv) < 30:
                return {"symbol": sym, "error": "No data — fetch first"}

            close = ohlcv["close"]
            price = float(close.iloc[-1])
            if price <= 0:
                return {"symbol": sym, "error": "Zero price"}

            # RSI with configurable period
            rsi_s   = rsi_fn(close, rsi_period)
            rsi_val = round(float(rsi_s.dropna().iloc[-1]), 2) if len(rsi_s.dropna()) else None

            # KAMA distances (price vs KAMA, expressed as %)
            def _kd(k):
                s  = kama_fn(close, window=k)
                v  = s.dropna()
                if not len(v):
                    return None
                kv = float(v.iloc[-1])
                return round((price / kv - 1.0) * 100, 2) if kv > 0 else None

            # Adaptive trend levels (with same config params as chart)
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

            # Derived ratios
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

@app.route("/api/scanner/sp500")
def get_sp500():
    tickers = scanner.get_sp500_tickers()
    return jsonify(tickers.to_dict(orient="records"))


@app.route("/api/scanner/fetch", methods=["POST"])
def fetch_sp500():
    force = request.get_json(silent=True) or {}
    force_refresh = force.get("force", False)
    status = scanner.get_fetch_status()
    if status["running"]:
        return jsonify({"message": "Fetch already running", "status": status})
    import threading
    def _run():
        scanner._update_fetch_status(running=True)
        scanner.bulk_fetch_sp500(max_workers=5, force_refresh=force_refresh)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _sp500_fetch_thread[0] = t
    return jsonify({"message": "S&P 500 fetch started"})


@app.route("/api/scanner/status")
def scanner_status():
    return jsonify(scanner.get_fetch_status())


@app.route("/api/scanner/run")
def run_scanner():
    signal_filter = request.args.get("signal")
    results = scanner.run_scanner(signal_filter=signal_filter or None)
    return jsonify(results)


@app.route("/api/scanner", methods=["GET"])
def get_scanner():
    """Compute multi-timeframe scanner metrics for every watched symbol."""
    try:
        symbols = [s['symbol'] for s in db.list_symbols()]
        if not symbols:
            return jsonify([])
        data = scanner.compute_scanner(symbols)
        return jsonify(data)
    except Exception as e:
        return _err(str(e), 500)


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
        "start_date":   "2000-01-01",   // optional, default 2000-01-01
        "delay":        1.5,            // seconds between requests
        "add_watchlist": true           // whether to add each ticker to watchlist
    }
    Streams SSE events:
        data: {"type":"start",  "total": N}
        data: {"type":"result", "index": i, "symbol": "...", "ok": bool, "msg": "..."}
        data: {"type":"done",   "ok": N, "failed": N}
    """
    body        = request.get_json(silent=True) or {}
    tickers     = [t.strip().upper() for t in body.get("tickers", []) if t.strip()]
    start_date  = body.get("start_date", "2000-01-01")
    delay       = float(body.get("delay", 1.5))
    add_wl      = bool(body.get("add_watchlist", True))

    if not tickers:
        return jsonify({"error": "tickers list is empty"}), 400

    # Clamp delay to reasonable range
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

                # Rate-limiting pause (skip after last ticker)
                if i < total - 1:
                    time.sleep(delay)

            yield f"data: {json.dumps({'type': 'done', 'ok': ok_count, 'failed': fail_count})}\n\n"

        except GeneratorExit:
            return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -- Entry point ----------------------------------------------------------------

if __name__ == "__main__":
    try:
        port = int(os.environ.get("PORT", 8050))
        if not (1 <= port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        raise SystemExit("PORT must be an integer between 1 and 65535")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    logger.info("Financial Dashboard running at http://localhost:%d (debug=%s)", port, debug)
    app.run(debug=debug, port=port)
