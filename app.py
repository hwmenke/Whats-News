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
import news as news_mod
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

# ── Auto-refresh scheduler ────────────────────────────────────────────────────
# Set AUTO_REFRESH_TIME=17:00 (24h, ET) to enable daily auto-refresh.
_auto_refresh_state = {"enabled": False, "next_run": None, "last_run": None}

def _auto_refresh_loop():
    import datetime as _dt
    refresh_time_str = os.environ.get("AUTO_REFRESH_TIME", "")
    if not refresh_time_str:
        return
    try:
        hh, mm = map(int, refresh_time_str.split(":"))
    except ValueError:
        logger.warning("AUTO_REFRESH_TIME must be HH:MM, got %r", refresh_time_str)
        return

    _auto_refresh_state["enabled"] = True
    logger.info("Auto-refresh enabled at %02d:%02d daily", hh, mm)

    while True:
        now    = _dt.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += _dt.timedelta(days=1)
        _auto_refresh_state["next_run"] = target.isoformat()
        wait = (target - now).total_seconds()
        time.sleep(wait)

        logger.info("Auto-refresh: starting daily data refresh")
        symbols = db.list_symbols()
        for s in symbols:
            try:
                fetcher.fetch_and_store(s["symbol"])
            except Exception as e:
                logger.warning("Auto-refresh failed for %s: %s", s["symbol"], e)
        _auto_refresh_state["last_run"] = _dt.datetime.now().isoformat()
        logger.info("Auto-refresh: complete")

_ar_thread = threading.Thread(target=_auto_refresh_loop, daemon=True)
_ar_thread.start()

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


# -- KNN Watchlist Scan --------------------------------------------------------

@app.route("/api/knn/scan", methods=["GET", "POST"])
def knn_scan():
    try:
        k = int(request.args.get("k", 10))
    except (TypeError, ValueError):
        k = 10
    try:
        symbols = [s["symbol"] for s in db.list_symbols()]
        if not symbols:
            return jsonify([])
        results = knn_model.scan_watchlist(symbols, k=k)
        return jsonify(results)
    except Exception as e:
        return _err(str(e), 500)


# -- KNN Walk-Forward Backtest -------------------------------------------------

@app.route("/api/knn/walk-forward/<string:symbol>")
def knn_walk_forward(symbol):
    try:
        min_train = int(request.args.get("min_train", 200))
        step      = int(request.args.get("step",      21))
        k         = int(request.args.get("k",         10))
        horizon   = int(request.args.get("horizon",   5))
    except (TypeError, ValueError):
        return _err("Invalid parameter")
    try:
        result = knn_model.walk_forward_backtest(
            symbol.upper(), min_train=min_train, step=step, k=k, horizon=horizon
        )
        if "error" in result:
            return _err(result["error"], 404)
        return jsonify(result)
    except Exception as e:
        return _err(str(e), 500)


# -- Scanner Custom Indicator --------------------------------------------------

@app.route("/api/scanner/custom-indicator", methods=["POST"])
def scanner_custom_indicator():
    body = request.get_json(silent=True) or {}
    symbols = body.get("symbols") or [s["symbol"] for s in db.list_symbols()]
    indic   = body.get("indicator", {})
    if not indic or not indic.get("type"):
        return _err("indicator.type is required")
    try:
        from scanner import compute_custom_indicator
        results = compute_custom_indicator(symbols, indic)
        return jsonify(results)
    except Exception as e:
        return _err(str(e), 500)


# -- Backtester -----------------------------------------------------------------

@app.route("/api/backtest/<string:symbol>")
def get_backtest(symbol):
    try:
        train_pct = float(request.args.get("train_pct", 0.7))
        train_pct = max(0.5, min(train_pct, 0.95))
    except (TypeError, ValueError):
        train_pct = 0.7
    try:
        result = backtester.run_optimization(symbol.upper(), train_pct=train_pct)
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


# -- Quick stats (lightweight watchlist badges) ---------------------------------

@app.route("/api/symbols/quick-stats", methods=["GET"])
def quick_stats():
    """
    Return per-symbol stats for watchlist badges + sort/filter.
    DB-only — no network calls. Runs on every page load.
    Fields: price, chg (1D%), ret_5d (1W%), ret_1m, rsi14, vol_ratio, above_sma20
    """
    import numpy as np
    from shared_indicators import _rsi

    symbols = [s["symbol"] for s in db.list_symbols()]
    results = []
    for sym in symbols:
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=60)
            if df.empty or len(df) < 2:
                results.append({"symbol": sym})
                continue
            close  = df["close"]
            volume = df["volume"] if "volume" in df.columns else None
            price  = float(close.iloc[-1])
            prev   = float(close.iloc[-2])
            chg    = round((price - prev) / prev * 100, 2) if prev else None

            ret_5d = None
            if len(close) >= 6:
                p5 = float(close.iloc[-6])
                ret_5d = round((price - p5) / p5 * 100, 2) if p5 else None

            ret_1m = None
            if len(close) >= 22:
                p1m = float(close.iloc[-22])
                ret_1m = round((price - p1m) / p1m * 100, 2) if p1m else None

            rsi14 = None
            if len(close) >= 15:
                r = _rsi(close, 14)
                v = r.iloc[-1]
                if not np.isnan(v):
                    rsi14 = round(float(v), 1)

            vol_ratio = None
            above_sma20 = None
            if volume is not None and len(volume) >= 20:
                avg20 = float(volume.iloc[-20:].mean())
                if avg20 > 0:
                    vol_ratio = round(float(volume.iloc[-1]) / avg20, 2)
            if len(close) >= 20:
                sma20 = float(close.iloc[-20:].mean())
                above_sma20 = price > sma20

            results.append({
                "symbol":      sym,
                "price":       round(price, 2),
                "chg":         chg,
                "ret_5d":      ret_5d,
                "ret_1m":      ret_1m,
                "rsi14":       rsi14,
                "vol_ratio":   vol_ratio,
                "above_sma20": above_sma20,
            })
        except Exception:
            results.append({"symbol": sym})
    return jsonify(results)


# -- Notes ---------------------------------------------------------------------

@app.route("/api/symbols/<string:symbol>/notes", methods=["PUT"])
def set_notes(symbol):
    body  = request.get_json(silent=True) or {}
    notes = body.get("notes", "")
    db.set_symbol_notes(symbol.upper(), notes)
    return jsonify({"message": "ok"})


# -- Fundamentals ---------------------------------------------------------------

@app.route("/api/fundamentals/<string:symbol>", methods=["GET"])
def get_fundamentals(symbol):
    row = db.get_fundamentals(symbol.upper())
    if row is None:
        return _err("No fundamental data. Fetch the symbol first.", 404)
    return jsonify(row)


# -- Alerts --------------------------------------------------------------------

@app.route("/api/alerts", methods=["GET"])
def list_alerts():
    symbol = request.args.get("symbol")
    return jsonify(db.list_alerts(symbol.upper() if symbol else None))


@app.route("/api/alerts", methods=["POST"])
def create_alert():
    body = request.get_json(silent=True) or {}
    symbol    = body.get("symbol", "").strip().upper()
    field     = body.get("field", "").strip()
    condition = body.get("condition", "").strip()
    threshold = body.get("threshold")

    if not symbol:
        return _err("symbol is required")
    if field not in ("price", "rsi_14", "kama10_pct", "kama20_pct", "kama50_pct"):
        return _err("field must be one of: price, rsi_14, kama10_pct, kama20_pct, kama50_pct")
    if condition not in ("above", "below"):
        return _err("condition must be 'above' or 'below'")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return _err("threshold must be a number")

    alert_id = db.add_alert(symbol, field, condition, threshold)
    return jsonify({"id": alert_id, "message": "Alert created"}), 201


@app.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    db.delete_alert(alert_id)
    return jsonify({"message": "deleted"})


@app.route("/api/alerts/<int:alert_id>/reset", methods=["POST"])
def reset_alert(alert_id):
    db.reset_alert(alert_id)
    return jsonify({"message": "reset"})


@app.route("/api/alerts/check", methods=["GET"])
def check_alerts():
    """
    Evaluate all untriggered alerts against latest stored indicator values.
    Returns list of newly triggered alerts.
    """
    import concurrent.futures

    alerts = [a for a in db.list_alerts() if not a.get("triggered_at")]
    if not alerts:
        return jsonify([])

    # Group by symbol so we fetch indicators once per symbol
    by_symbol: dict[str, list] = {}
    for a in alerts:
        by_symbol.setdefault(a["symbol"], []).append(a)

    triggered = []

    def _check_symbol(sym, sym_alerts):
        result = []
        try:
            ohlcv = db.get_ohlcv_df(sym, "daily", limit=100)
            if ohlcv.empty:
                return result
            close  = ohlcv["close"]
            price  = float(close.iloc[-1])
            from shared_indicators import _kama, _rsi
            rsi14  = float(_rsi(close, 14).dropna().iloc[-1])
            kama10 = float(_kama(close, 10).dropna().iloc[-1])
            kama20 = float(_kama(close, 20).dropna().iloc[-1])
            kama50 = float(_kama(close, 50).dropna().iloc[-1])
            values = {
                "price":      price,
                "rsi_14":     rsi14,
                "kama10_pct": round((price / kama10 - 1) * 100, 2) if kama10 else None,
                "kama20_pct": round((price / kama20 - 1) * 100, 2) if kama20 else None,
                "kama50_pct": round((price / kama50 - 1) * 100, 2) if kama50 else None,
            }
            for alert in sym_alerts:
                val = values.get(alert["field"])
                if val is None:
                    continue
                fired = (alert["condition"] == "above" and val > alert["threshold"]) or \
                        (alert["condition"] == "below" and val < alert["threshold"])
                if fired:
                    db.mark_alert_triggered(alert["id"])
                    result.append({**alert, "current_value": val})
        except Exception as e:
            logger.warning("Alert check failed for %s: %s", sym, e)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_check_symbol, sym, alts): sym
                for sym, alts in by_symbol.items()}
        for f in concurrent.futures.as_completed(futs):
            triggered.extend(f.result())

    return jsonify(triggered)


# -- Relative Strength ---------------------------------------------------------

@app.route("/api/relative-strength/<string:symbol>", methods=["GET"])
def get_relative_strength(symbol):
    """
    Returns the symbol's close divided by a benchmark close, both normalised
    to 1.0 at the start of the window.  Query params:
      bench : benchmark symbol (default SPY)
      freq  : daily | weekly (default daily)
      limit : number of bars (default 252)
    """
    bench = request.args.get("bench", "SPY").strip().upper()
    freq  = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
        if limit < 2:
            raise ValueError
    except (TypeError, ValueError):
        return _err("limit must be an integer >= 2")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    sym_df   = db.get_ohlcv_df(symbol.upper(), freq, limit=limit)
    bench_df = db.get_ohlcv_df(bench, freq, limit=limit)

    if sym_df.empty:
        return _err(f"No data for {symbol.upper()}. Fetch it first.", 404)
    if bench_df.empty:
        return _err(f"No data for benchmark {bench}. Fetch it first.", 404)

    import numpy as np
    # Align on common dates
    common = sym_df.index.intersection(bench_df.index)
    if len(common) < 2:
        return _err("Not enough overlapping dates between symbol and benchmark", 404)

    sym_close   = sym_df.loc[common, "close"]
    bench_close = bench_df.loc[common, "close"]

    # Normalise both to 1.0 at the first common date
    sym_norm   = sym_close   / sym_close.iloc[0]
    bench_norm = bench_close / bench_close.iloc[0]
    rs         = sym_norm / bench_norm

    from shared_indicators import _safe
    result = [
        {"date": d.strftime("%Y-%m-%d"), "rs": _safe(round(float(v), 6)),
         "sym": _safe(round(float(s), 6)), "bench": _safe(round(float(b), 6))}
        for d, v, s, b in zip(common, rs.values, sym_norm.values, bench_norm.values)
    ]
    return jsonify({"symbol": symbol.upper(), "bench": bench, "series": result})


# -- Correlations --------------------------------------------------------------

@app.route("/api/correlations", methods=["GET"])
def get_correlations():
    """
    Pairwise Pearson correlation of daily returns across all watchlist symbols.
    Query params:
      freq  : daily | weekly (default daily)
      limit : bars to use   (default 252)
    """
    freq = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
        if limit < 5:
            raise ValueError
    except (TypeError, ValueError):
        return _err("limit must be an integer >= 5")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    symbols = [s["symbol"] for s in db.list_symbols()]
    if len(symbols) < 2:
        return _err("Need at least 2 symbols in the watchlist", 400)

    import numpy as np

    frames = {}
    for sym in symbols:
        df = db.get_ohlcv_df(sym, freq, limit=limit)
        if not df.empty and len(df) >= 5:
            frames[sym] = df["close"].pct_change().dropna()

    if len(frames) < 2:
        return _err("Not enough symbols with data", 400)

    import pandas as pd
    prices = pd.DataFrame(frames)
    corr   = prices.corr(method="pearson")

    syms = list(corr.columns)
    matrix = []
    for s1 in syms:
        row = []
        for s2 in syms:
            v = corr.loc[s1, s2]
            row.append(None if (v is None or (isinstance(v, float) and np.isnan(v)))
                       else round(float(v), 4))
        matrix.append(row)

    return jsonify({"symbols": syms, "matrix": matrix})


# -- Positions (Portfolio) -----------------------------------------------------

@app.route("/api/positions", methods=["GET"])
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


@app.route("/api/positions", methods=["POST"])
def create_position():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    try:
        qty         = float(body["qty"])
        entry_price = float(body["entry_price"])
        if qty == 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return _err("qty (non-zero) and entry_price are required numbers")

    opened_at = body.get("opened_at")
    notes     = body.get("notes", "")
    pos_id    = db.add_position(symbol, qty, entry_price, opened_at, notes)
    return jsonify({"id": pos_id, "message": "Position created"}), 201


@app.route("/api/positions/<int:pos_id>", methods=["PUT"])
def update_position(pos_id):
    body = request.get_json(silent=True) or {}
    allowed = {"qty", "entry_price", "opened_at", "closed_at", "exit_price", "notes"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return _err("No valid fields to update")
    db.update_position(pos_id, **updates)
    return jsonify({"message": "updated"})


@app.route("/api/positions/<int:pos_id>", methods=["DELETE"])
def delete_position(pos_id):
    db.delete_position(pos_id)
    return jsonify({"message": "deleted"})


# -- Volume Profile ------------------------------------------------------------

@app.route("/api/volume-profile/<string:symbol>", methods=["GET"])
def get_volume_profile(symbol):
    """
    Returns a price histogram weighted by volume.
    Query params:
      freq  : daily | weekly (default daily)
      limit : bars to use   (default 252)
      bins  : number of price buckets (default 40)
    """
    freq = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
        bins  = int(request.args.get("bins",  40))
        if limit < 5 or bins < 2:
            raise ValueError
    except (TypeError, ValueError):
        return _err("limit (>=5) and bins (>=2) must be positive integers")
    if freq not in ("daily", "weekly"):
        return _err("freq must be 'daily' or 'weekly'")

    df = db.get_ohlcv_df(symbol.upper(), freq, limit=limit)
    if df.empty:
        return _err("No data. Fetch the symbol first.", 404)

    import numpy as np
    prices = ((df["high"] + df["low"]) / 2).values
    vols   = df["volume"].values
    lo, hi = prices.min(), prices.max()
    if lo >= hi:
        return _err("Insufficient price range", 400)

    edges   = np.linspace(lo, hi, bins + 1)
    buckets = []
    for i in range(bins):
        mask   = (prices >= edges[i]) & (prices < edges[i + 1])
        vol_sum = float(vols[mask].sum())
        buckets.append({
            "price_low":  round(float(edges[i]),     4),
            "price_high": round(float(edges[i + 1]), 4),
            "price_mid":  round(float((edges[i] + edges[i + 1]) / 2), 4),
            "volume":     vol_sum,
        })

    total = sum(b["volume"] for b in buckets) or 1
    for b in buckets:
        b["volume_pct"] = round(b["volume"] / total * 100, 2)

    return jsonify({"symbol": symbol.upper(), "buckets": buckets,
                    "price_range": {"low": round(float(lo), 4),
                                    "high": round(float(hi), 4)}})


# -- Auto-refresh status -------------------------------------------------------

@app.route("/api/auto-refresh/status", methods=["GET"])
def auto_refresh_status():
    return jsonify(_auto_refresh_state)


# ── News ───────────────────────────────────────────────────────────────────────

@app.route("/api/news/<string:symbol>", methods=["GET"])
def get_news(symbol):
    limit = min(int(request.args.get("limit", 20)), 50)
    articles = news_mod.fetch_news(symbol, limit=limit)
    return jsonify(articles)


# ── Sector Heatmap ─────────────────────────────────────────────────────────────

@app.route("/api/sector-heatmap", methods=["GET"])
def sector_heatmap():
    import datetime
    import numpy as np
    symbols = db.list_symbols()
    if not symbols:
        return jsonify([])

    today_str = datetime.date.today().isoformat()
    ytd_start = datetime.date.today().replace(month=1, day=1).isoformat()

    sectors: dict[str, list] = {}
    for sym in symbols:
        sector = (sym.get("sector") or "Unknown").strip() or "Unknown"
        sectors.setdefault(sector, []).append(sym["symbol"])

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

            ytd_df  = df[df.index.astype(str) >= ytd_start]
            ret_ytd = float(close.iloc[-1] / ytd_df["close"].iloc[0] - 1) if len(ytd_df) > 0 else None

            rows.append({
                "symbol": s,
                "close":  round(float(close.iloc[-1]), 2),
                "ret_1d":  round(_ret(2), 4)   if _ret(2)   is not None else None,
                "ret_5d":  round(_ret(6), 4)   if _ret(6)   is not None else None,
                "ret_20d": round(_ret(21), 4)  if _ret(21)  is not None else None,
                "ret_ytd": round(ret_ytd, 4)   if ret_ytd   is not None else None,
            })

        if rows:
            # Sector-level averages
            def _avg(key):
                vals = [r[key] for r in rows if r[key] is not None]
                return round(float(np.mean(vals)), 4) if vals else None

            result.append({
                "sector":   sector,
                "count":    len(rows),
                "avg_1d":   _avg("ret_1d"),
                "avg_5d":   _avg("ret_5d"),
                "avg_20d":  _avg("ret_20d"),
                "avg_ytd":  _avg("ret_ytd"),
                "symbols":  rows,
            })

    return jsonify(result)


# ── Signals Dashboard ──────────────────────────────────────────────────────────

@app.route("/api/signals", methods=["GET"])
def get_signals():
    symbols = db.list_symbols()
    if not symbols:
        return jsonify([])

    results = []
    for sym_row in symbols:
        sym = sym_row["symbol"]
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=100)
            if df.empty or len(df) < 30:
                continue
            close = df["close"]
            import ta, numpy as np
            rsi14   = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
            macd    = ta.trend.MACD(close).macd_diff().iloc[-1]
            bb      = ta.volatility.BollingerBands(close)
            bb_pct  = bb.bollinger_pband().iloc[-1]
            vol     = df["volume"]
            vol_ma  = vol.rolling(20).mean().iloc[-1]
            vol_z   = (vol.iloc[-1] - vol_ma) / (vol.std() + 1e-9)

            signals = []
            if rsi14 < 30:   signals.append({"type": "rsi_os", "label": "RSI Oversold",  "bull": True})
            if rsi14 > 70:   signals.append({"type": "rsi_ob", "label": "RSI Overbought","bull": False})
            if macd > 0:     signals.append({"type": "macd_bull", "label": "MACD Bull",  "bull": True})
            if macd < 0:     signals.append({"type": "macd_bear", "label": "MACD Bear",  "bull": False})
            if bb_pct < 0.1: signals.append({"type": "bb_squeeze_low", "label": "BB Lower",  "bull": True})
            if bb_pct > 0.9: signals.append({"type": "bb_squeeze_hi",  "label": "BB Upper",  "bull": False})
            if vol_z > 2.5:  signals.append({"type": "vol_spike",  "label": "Vol Spike",  "bull": None})

            score = sum(1 if s["bull"] else -1 if s["bull"] is False else 0 for s in signals)
            results.append({
                "symbol":  sym,
                "name":    sym_row.get("name", ""),
                "close":   round(float(close.iloc[-1]), 2),
                "rsi14":   round(float(rsi14), 1),
                "macd":    round(float(macd), 4),
                "bb_pct":  round(float(bb_pct), 3),
                "vol_z":   round(float(vol_z), 2),
                "signals": signals,
                "score":   score,
            })
        except Exception as exc:
            logger.debug("Signals skipped %s: %s", sym, exc)

    results.sort(key=lambda r: -abs(r["score"]))
    return jsonify(results)


# ── Watchlist Export / Import ──────────────────────────────────────────────────

@app.route("/api/export", methods=["GET"])
def export_watchlist():
    return jsonify({
        "version":   2,
        "symbols":   db.list_symbols(),
        "alerts":    db.list_alerts(),
        "positions": db.list_positions(),
    })


@app.route("/api/import", methods=["POST"])
def import_watchlist():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or "symbols" not in data:
        return _err("Invalid import format — expected {symbols: [...], ...}")

    added = 0
    for sym_row in (data.get("symbols") or []):
        sym = (sym_row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ok = db.add_symbol(sym, sym_row.get("name", ""), sym_row.get("sector", ""))
        if ok:
            added += 1
            if sym_row.get("group_tag"):
                db.set_symbol_group(sym, sym_row["group_tag"])
            if sym_row.get("notes"):
                db.set_symbol_notes(sym, sym_row["notes"])

    for a in (data.get("alerts") or []):
        try:
            db.add_alert(a["symbol"], a["field"], a["condition"], float(a["threshold"]))
        except Exception:
            pass

    return jsonify({"imported": added})


# ── Risk Calculator ────────────────────────────────────────────────────────────

@app.route("/api/risk/<string:symbol>", methods=["GET"])
def get_risk(symbol):
    import numpy as np
    account = float(request.args.get("account", 10000))
    risk_pct = float(request.args.get("risk_pct", 1.0)) / 100
    atr_mult = float(request.args.get("atr_mult", 2.0))

    df = db.get_ohlcv_df(symbol.upper(), "daily", limit=60)
    if df.empty or len(df) < 15:
        return _err("Not enough data", 404)

    close = df["close"].iloc[-1]
    import ta
    atr14 = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range().iloc[-1]

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


# ── Options Chain ──────────────────────────────────────────────────────────────

@app.route("/api/options/<string:symbol>", methods=["GET"])
def get_options(symbol):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        expirations = ticker.options
        if not expirations:
            return jsonify({"symbol": symbol.upper(), "expirations": [], "chain": None})

        expiry = request.args.get("expiry", expirations[0])
        if expiry not in expirations:
            expiry = expirations[0]

        chain    = ticker.option_chain(expiry)
        calls_df = chain.calls
        puts_df  = chain.puts

        def df_to_list(df):
            cols = ["strike", "lastPrice", "bid", "ask", "volume",
                    "openInterest", "impliedVolatility", "inTheMoney"]
            rows = []
            for _, row in df[cols].iterrows():
                rows.append({
                    "strike":  round(float(row.strike), 2),
                    "last":    round(float(row.lastPrice), 2),
                    "bid":     round(float(row.bid), 2),
                    "ask":     round(float(row.ask), 2),
                    "volume":  int(row.volume) if not __import__("math").isnan(row.volume) else 0,
                    "oi":      int(row.openInterest) if not __import__("math").isnan(row.openInterest) else 0,
                    "iv":      round(float(row.impliedVolatility), 4),
                    "itm":     bool(row.inTheMoney),
                })
            return rows

        calls = df_to_list(calls_df)
        puts  = df_to_list(puts_df)

        # Put/call ratio by OI
        total_call_oi = sum(r["oi"] for r in calls)
        total_put_oi  = sum(r["oi"] for r in puts)
        pc_ratio = round(total_put_oi / total_call_oi, 3) if total_call_oi else None

        # Max pain (strike where total option writer profit is maximised)
        all_strikes = sorted(set(r["strike"] for r in calls + puts))
        max_pain_strike = None
        if all_strikes:
            min_pain = float("inf")
            for k in all_strikes:
                pain = (sum(max(0, k - r["strike"]) * r["oi"] for r in calls) +
                        sum(max(0, r["strike"] - k) * r["oi"] for r in puts))
                if pain < min_pain:
                    min_pain = pain
                    max_pain_strike = k

        return jsonify({
            "symbol":      symbol.upper(),
            "expiry":      expiry,
            "expirations": list(expirations),
            "calls":       calls[:30],
            "puts":        puts[:30],
            "pc_ratio":    pc_ratio,
            "max_pain":    max_pain_strike,
        })
    except Exception as exc:
        return _err(f"Options fetch failed: {exc}")


# ── Anomaly Detection ──────────────────────────────────────────────────────────

@app.route("/api/anomalies", methods=["GET"])
def get_anomalies():
    import numpy as np
    symbols  = db.list_symbols()
    anomalies = []

    for sym_row in symbols:
        sym = sym_row["symbol"]
        df  = db.get_ohlcv_df(sym, "daily", limit=60)
        if df.empty or len(df) < 21:
            continue

        flags = []
        close  = df["close"]
        volume = df["volume"]

        # Volume spike: today vs 20-day avg
        vol_avg = volume.iloc[:-1].tail(20).mean()
        vol_std = volume.iloc[:-1].tail(20).std()
        if vol_std > 0:
            vol_z = (volume.iloc[-1] - vol_avg) / vol_std
            if abs(vol_z) > 2.5:
                flags.append({"type": "vol_spike", "label": f"Vol spike ({vol_z:+.1f}σ)", "z": round(float(vol_z), 2)})

        # Price gap: open vs prev close
        if "open" in df.columns and len(df) >= 2:
            gap_pct = (df["open"].iloc[-1] - close.iloc[-2]) / close.iloc[-2]
            if abs(gap_pct) > 0.02:
                flags.append({"type": "price_gap", "label": f"Gap {gap_pct*100:+.1f}%", "z": round(float(gap_pct), 4)})

        # Volatility spike: today range vs avg
        df["range"] = (df["high"] - df["low"]) / close
        rng_today = df["range"].iloc[-1]
        rng_avg   = df["range"].iloc[-21:-1].mean()
        rng_std   = df["range"].iloc[-21:-1].std()
        if rng_std > 0 and rng_today > rng_avg + 2.5 * rng_std:
            flags.append({"type": "vol_range", "label": "High-range candle", "z": round(float((rng_today - rng_avg) / rng_std), 2)})

        # 52-week high/low touch
        high52 = close.tail(252).max()
        low52  = close.tail(252).min()
        if abs(close.iloc[-1] - high52) / high52 < 0.005:
            flags.append({"type": "high52", "label": "52w High", "z": 0})
        elif abs(close.iloc[-1] - low52) / low52 < 0.005:
            flags.append({"type": "low52",  "label": "52w Low",  "z": 0})

        if flags:
            anomalies.append({
                "symbol": sym,
                "name":   sym_row.get("name", ""),
                "close":  round(float(close.iloc[-1]), 2),
                "flags":  flags,
            })

    return jsonify(anomalies)


# ── Journal ────────────────────────────────────────────────────────────────────

@app.route("/api/journal", methods=["GET"])
def list_journal():
    symbol = request.args.get("symbol")
    tag    = request.args.get("tag")
    return jsonify(db.list_journal(symbol.upper() if symbol else None, tag))


@app.route("/api/journal", methods=["POST"])
def create_journal_entry():
    from datetime import datetime as _dt
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    try:
        entry_price = float(body["entry_price"])
        qty         = float(body.get("qty", 1))
    except (KeyError, TypeError, ValueError):
        return _err("entry_price (number) is required")

    exit_p = body.get("exit_price")
    jid = db.add_journal_entry(
        symbol=symbol,
        direction=body.get("direction", "long"),
        entry_date=body.get("entry_date", _dt.now().date().isoformat()),
        entry_price=entry_price,
        qty=qty,
        exit_date=body.get("exit_date"),
        exit_price=float(exit_p) if exit_p is not None else None,
        setup=body.get("setup", ""),
        tags=body.get("tags", ""),
        thesis=body.get("thesis", ""),
    )
    return jsonify({"id": jid, "message": "Journal entry created"}), 201


@app.route("/api/journal/<int:entry_id>", methods=["PUT"])
def update_journal_entry(entry_id):
    body    = request.get_json(silent=True) or {}
    allowed = {"direction", "entry_date", "exit_date", "entry_price",
               "exit_price", "qty", "setup", "tags", "thesis"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return _err("No valid fields to update")
    db.update_journal_entry(entry_id, **updates)
    return jsonify({"message": "updated"})


@app.route("/api/journal/<int:entry_id>", methods=["DELETE"])
def delete_journal_entry(entry_id):
    db.delete_journal_entry(entry_id)
    return jsonify({"message": "deleted"})


# ── Portfolio Analytics ────────────────────────────────────────────────────────

@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    import numpy as np

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


# ── Pair Trading / Spread ──────────────────────────────────────────────────────

@app.route("/api/spread", methods=["GET"])
def get_spread():
    import numpy as np

    sym1 = request.args.get("sym1", "").strip().upper()
    sym2 = request.args.get("sym2", "").strip().upper()
    freq = request.args.get("freq", "daily")
    try:
        limit  = int(request.args.get("limit",  252))
        window = int(request.args.get("window",  20))
    except (TypeError, ValueError):
        return _err("limit and window must be integers")

    if not sym1 or not sym2:  return _err("sym1 and sym2 are required")
    if sym1 == sym2:           return _err("sym1 and sym2 must be different")
    if freq not in ("daily", "weekly"): return _err("freq must be daily or weekly")

    df1 = db.get_ohlcv_df(sym1, freq, limit=limit)
    df2 = db.get_ohlcv_df(sym2, freq, limit=limit)

    if df1.empty: return _err(f"No data for {sym1}. Fetch it first.", 404)
    if df2.empty: return _err(f"No data for {sym2}. Fetch it first.", 404)

    common = df1.index.intersection(df2.index)
    if len(common) < window + 5:
        return _err("Not enough overlapping data", 404)

    c1    = df1.loc[common, "close"]
    c2    = df2.loc[common, "close"]
    ratio = c1 / c2

    rm    = ratio.rolling(window).mean()
    rs    = ratio.rolling(window).std().replace(0, float("nan"))
    zs    = (ratio - rm) / rs

    result = [
        {"date":   d.strftime("%Y-%m-%d"),
         "ratio":  round(float(r), 6) if np.isfinite(r) else None,
         "zscore": round(float(z), 4) if np.isfinite(z) else None}
        for d, r, z in zip(common, ratio.values, zs.values)
    ]

    last_z = float(zs.dropna().iloc[-1]) if len(zs.dropna()) else None
    signal = None
    if last_z is not None:
        if last_z > 2:    signal = "mean_revert_short"
        elif last_z < -2: signal = "mean_revert_long"
        else:             signal = "neutral"

    return jsonify({
        "sym1": sym1, "sym2": sym2, "window": window,
        "last_zscore": round(last_z, 4) if last_z and np.isfinite(last_z) else None,
        "signal":  signal,
        "series":  result,
    })


# ── Macro Overlay ──────────────────────────────────────────────────────────────

@app.route("/api/macro", methods=["GET"])
def get_macro():
    import numpy as np
    import pandas as pd

    freq  = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 252))
    except (TypeError, ValueError):
        limit = 252

    macro_map = {"VIX": "^VIX", "DXY": "DX-Y.NYB", "US10Y": "^TNX", "OIL": "CL=F"}
    result = {}

    for label, sym in macro_map.items():
        df = db.get_ohlcv_df(sym, freq, limit=limit)
        if df.empty:
            try:
                import yfinance as yf
                hist = yf.Ticker(sym).history(period="2y",
                                              interval="1d" if freq == "daily" else "1wk")
                if hist.empty:
                    continue
                hist.index = pd.to_datetime(hist.index).tz_localize(None)
                hist.columns = [c.lower() for c in hist.columns]
                df = hist[["open", "high", "low", "close", "volume"]]
                try:
                    db.upsert_ohlcv(sym, freq, df)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("Macro fetch failed for %s: %s", sym, exc)
                continue
        if df.empty:
            continue
        close = df["close"].tail(limit)
        result[label] = [
            {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
            for d, v in zip(close.index, close.values)
            if np.isfinite(v)
        ]

    return jsonify(result)


# ── Macro Economic Calendar ────────────────────────────────────────────────────

@app.route("/api/calendar", methods=["GET"])
def get_calendar():
    import datetime as dt

    today = dt.date.today()
    year  = today.year

    fomc_dates = [
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
    ]

    events = [{"date": d, "type": "FOMC", "label": "FOMC Meeting", "color": "#3b82f6"}
              for d in fomc_dates]

    months = [f"{year:04d}-{m:02d}" for m in range(1, 13)] + \
             [f"{year+1:04d}-{m:02d}" for m in range(1, 7)]
    for ym in months:
        events.append({"date": ym + "-13", "type": "CPI",
                        "label": "CPI Release", "color": "#f97316"})
        events.append({"date": ym + "-05", "type": "NFP",
                        "label": "Jobs Report (NFP)", "color": "#22c55e"})

    for sym in db.list_symbols():
        ed = sym.get("next_earnings")
        if ed:
            events.append({"date": ed, "type": "EARNINGS",
                            "label": f"{sym['symbol']} Earnings",
                            "symbol": sym["symbol"], "color": "#a855f7"})

    past_limit   = (today - dt.timedelta(days=30)).isoformat()
    future_limit = (today + dt.timedelta(days=180)).isoformat()
    events = sorted(
        [e for e in events if past_limit <= e["date"] <= future_limit],
        key=lambda e: e["date"]
    )
    return jsonify(events)


# ── Strategies ─────────────────────────────────────────────────────────────────

@app.route("/api/strategies", methods=["GET"])
def list_strategies_route():
    return jsonify(db.list_strategies())


@app.route("/api/strategies", methods=["POST"])
def create_strategy():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return _err("name is required")
    conditions = body.get("conditions", [])
    if not isinstance(conditions, list):
        return _err("conditions must be a list")
    sid = db.add_strategy(name, conditions)
    return jsonify({"id": sid, "message": "Strategy created"}), 201


@app.route("/api/strategies/<int:strategy_id>", methods=["PUT"])
def update_strategy_route(strategy_id):
    body = request.get_json(silent=True) or {}
    name       = body.get("name")
    conditions = body.get("conditions")
    if name is None and conditions is None:
        return _err("name or conditions required")
    db.update_strategy(strategy_id, name=name, conditions=conditions)
    return jsonify({"message": "updated"})


@app.route("/api/strategies/<int:strategy_id>", methods=["DELETE"])
def delete_strategy_route(strategy_id):
    db.delete_strategy(strategy_id)
    return jsonify({"message": "deleted"})


@app.route("/api/strategies/<int:strategy_id>/run", methods=["POST"])
def run_strategy_route(strategy_id):
    import concurrent.futures

    strats = db.list_strategies()
    strat  = next((s for s in strats if s["id"] == strategy_id), None)
    if not strat:
        return _err("Strategy not found", 404)

    try:
        conditions = (
            json.loads(strat["conditions"])
            if isinstance(strat["conditions"], str)
            else strat["conditions"]
        )
    except Exception:
        return _err("Invalid strategy conditions")

    symbols = [s["symbol"] for s in db.list_symbols()]
    if not symbols:
        return jsonify([])

    def _evaluate(sym):
        try:
            df = db.get_ohlcv_df(sym, "daily", limit=100)
            if df.empty or len(df) < 20:
                return None
            from shared_indicators import _kama, _rsi
            close = df["close"]
            price = float(close.iloc[-1])
            rsi14 = float(_rsi(close, 14).dropna().iloc[-1])
            k10   = float(_kama(close, 10).dropna().iloc[-1])
            k20   = float(_kama(close, 20).dropna().iloc[-1])
            k50   = float(_kama(close, 50).dropna().iloc[-1])

            values = {
                "price":      price,
                "rsi":        rsi14,
                "kama10_pct": round((price / k10 - 1) * 100, 2) if k10 else None,
                "kama20_pct": round((price / k20 - 1) * 100, 2) if k20 else None,
                "kama50_pct": round((price / k50 - 1) * 100, 2) if k50 else None,
            }

            for cond in conditions:
                field   = cond.get("field")
                op      = cond.get("op")
                val     = cond.get("value")
                val2    = cond.get("value2")
                current = values.get(field)
                if current is None:
                    return None
                if op == "above"   and not (current > val):           return None
                if op == "below"   and not (current < val):           return None
                if op == "between" and not (val <= current <= val2):  return None

            return {"symbol": sym, "price": round(price, 2),
                    "rsi": round(rsi14, 1), "kama10_pct": values["kama10_pct"]}
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_evaluate, symbols))

    return jsonify([r for r in results if r is not None])


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
