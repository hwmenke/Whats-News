"""
app.py - Whats-News analysis dashboard (compute layer)

Reads watchlist / OHLCV on the fly from the Data Management service
(data_service/app.py, default :8051). This process owns charts, indicators,
scanner analytics, and news — not SQLite writes or Yahoo downloads.

Run both:
  python -m data_service.app   # data plane  :8051
  python app.py                # analysis UI :8050

Tests / single-process: DATA_SERVICE_MODE=embedded
"""

import json
import os
import urllib.error
import urllib.request

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS

import data_client
import market_data as md
import indicators as ind
import stats as stats
import knn_model
import backtester
import scanner
import adaptive_trend as adaptive
import conditional_dist
import yfinance as yf
import portfolio
import setup_scanner
import index_universe
import precache  # precache: TTL + prewarm knobs for expensive reads

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)


def _data_error(exc):
    if isinstance(exc, data_client.DataServiceError):
        status = exc.status or 502
        payload = exc.payload if isinstance(exc.payload, dict) else {"error": str(exc)}
        if "error" not in payload:
            payload = {**payload, "error": str(exc)}
        return jsonify(payload), status
    return jsonify({"error": str(exc)}), 502


# -- Static files ---------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/news")
def news_page():
    return send_from_directory(".", "news.html")


@app.route("/api/health")
def health():
    try:
        data_health = md.health()
    except Exception as exc:
        data_health = {"ok": False, "error": str(exc)}
    try:
        symbol_count = len(md.list_symbols())
    except Exception:
        symbol_count = None
    return jsonify({
        "ok": True,
        "service": "whats-news",
        "layer": "analysis",
        "symbol_count": symbol_count,
        "data_service": data_health,
        "data_mode": data_client.DATA_SERVICE_MODE,
        "data_url": data_client.DATA_SERVICE_URL,
    })


@app.route("/api/portfolio/snapshot", methods=["GET"])
def portfolio_snapshot():
    """Watchlist tape: day change, RSI, regime vs KAMA — for PM desk."""
    # precache: short TTL so the tape feels instant; ?refresh=1 bypasses.
    try:
        refresh = precache.wants_refresh(request.args)
        symbols = sorted(s["symbol"] for s in md.list_symbols())
        key = ("portfolio", tuple(symbols))

        def _compute():
            return portfolio.portfolio_snapshot()

        payload, hit = precache.cached_call(
            "portfolio", key, _compute, precache.PORTFOLIO_TTL_S,
            refresh=refresh,
        )
        _payload, remaining = precache.cache_get("portfolio", key)
        precache.maybe_refresh_in_background(
            "portfolio", key, _compute, precache.PORTFOLIO_TTL_S, remaining)
        resp = jsonify({**payload, "cached": hit})
        resp.headers["X-Cache"] = "HIT" if hit else "MISS"
        return resp
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pm-desk/<string:symbol>", methods=["GET"])
def pm_desk(symbol):
    """Single-name TA decision strip for portfolio managers."""
    try:
        snap = portfolio.snapshot_symbol(symbol.upper())
        if not snap.get("ready"):
            return jsonify(snap), 404
        meta = next((s for s in md.list_symbols() if s["symbol"] == symbol.upper()), {}) or {}
        snap["sector"] = meta.get("sector") or ""
        snap["peer_etf"] = portfolio.peer_etf_for(snap["sector"])
        try:
            risk = float(request.args.get("risk", 100))
        except (TypeError, ValueError):
            risk = 100.0
        stop_mode = (request.args.get("stop") or "atr").strip().lower()
        stop_price = None
        if stop_mode == "box":
            box = snap.get("darvas") or {}
            stop_price = box.get("bottom")
        elif stop_mode == "user":
            try:
                stop_price = float(request.args.get("stop_price"))
            except (TypeError, ValueError):
                stop_price = None
        snap["size"] = portfolio.position_size(
            snap.get("price"),
            snap.get("atr14"),
            risk,
            1.5,
            stop_price=stop_price,
        )
        # Structural risk box: entry / stop / target for chart overlays
        entry = snap.get("price")
        if stop_mode == "user" and stop_price:
            stop = stop_price
        elif stop_mode == "box" and stop_price:
            stop = stop_price
        else:
            stop = snap.get("stop_long_1_5atr")
        target = None
        try:
            t = request.args.get("target")
            if t is not None and str(t).strip() != "":
                target = float(t)
        except (TypeError, ValueError):
            target = None
        if target is None and snap.get("darvas"):
            target = snap["darvas"].get("target")
        r_mult = None
        if entry and stop and target and abs(entry - stop) > 1e-9:
            r_mult = round((target - entry) / abs(entry - stop), 2)
        snap["risk_box"] = {
            "entry": entry,
            "stop": stop,
            "target": target,
            "r_multiple": r_mult,
            "stop_mode": stop_mode,
        }
        snap.pop("closes_30", None)
        return jsonify(snap)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spy-rs/<string:symbol>", methods=["GET"])
def spy_rs_api(symbol):
    """Daily close/SPY close comparison line — not a published rating."""
    try:
        try:
            limit = int(request.args.get("limit", 500))
        except (TypeError, ValueError):
            return jsonify({"error": "limit must be an integer"}), 400
        if limit <= 0:
            return jsonify({"error": "limit must be a positive integer"}), 400
        sym = symbol.upper()
        if sym == "SPY":
            payload = portfolio.spy_rs_overlay([], [])
            payload.update({
                "symbol": "SPY",
                "ready": False,
                "error": "SPY vs SPY is not a comparison",
            })
            return jsonify(payload)
        rows = md.get_ohlcv(sym, "daily", limit)
        if not rows:
            return jsonify({"error": "No data. Fetch the symbol first."}), 404
        spy_rows = md.get_ohlcv("SPY", "daily", limit)
        payload = portfolio.spy_rs_overlay(rows, spy_rows)
        payload["symbol"] = sym
        if not payload.get("ready") and not spy_rows:
            payload["error"] = "No SPY daily data — fetch SPY first"
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/darvas-box/<string:symbol>", methods=["GET"])
def darvas_box_api(symbol):
    """Darvas box levels for chart overlay — distinct from KAMA/RSI."""
    try:
        freq = request.args.get("freq", "daily")
        if freq not in ("daily", "weekly"):
            return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400
        df = md.get_ohlcv_df(symbol.upper(), freq, limit=260)
        box = portfolio.darvas_box(df)
        if not box:
            return jsonify({"symbol": symbol.upper(), "ready": False, "error": "No box"}), 404
        return jsonify({"symbol": symbol.upper(), "ready": True, "freq": freq, **box})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# -- Symbols (proxied to data service) -----------------------------------------

@app.route("/api/symbols", methods=["GET"])
def get_symbols():
    try:
        desk = request.args.get("desk", "").lower() in ("1", "true", "yes")
        if desk:
            return jsonify(md.list_desk_symbols())
        return jsonify(md.list_symbols())
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/symbols/with-data", methods=["GET"])
def symbols_with_data():
    try:
        freq = request.args.get("freq", "daily")
        try:
            min_bars = int(request.args.get("min_bars", 30))
        except (TypeError, ValueError):
            return jsonify({"error": "min_bars must be an integer"}), 400
        codes = md.list_symbols_with_ohlcv(freq, min_bars)
        return jsonify({"symbols": codes, "count": len(codes)})
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/symbols/<string:symbol>/promote", methods=["POST"])
def promote_symbol_to_desk(symbol):
    """Move a universe-only symbol onto the trading desk."""
    try:
        return jsonify(md.promote_to_desk(symbol.upper()))
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/symbols", methods=["POST"])
def add_symbol():
    data = request.get_json(force=True) or {}
    try:
        if "symbols" in data:
            raw = data.get("symbols") or []
            if not isinstance(raw, list):
                return jsonify({"error": "symbols must be a list"}), 400
            result = md.add_symbols(raw)
            status = 201 if result.get("added") else 200
            return jsonify({
                "message": f"{len(result.get('added', []))} added, {len(result.get('skipped', []))} skipped",
                **result,
            }), status

        symbol = data.get("symbol", "").strip().upper()
        if not symbol:
            return jsonify({"error": "symbol is required"}), 400
        result = md.add_symbol(symbol)
        added = result.get("added")
        if added is False or (added is None and "already" in result.get("message", "").lower()):
            return jsonify(result), 200
        return jsonify(result), 201
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/symbols/<string:symbol>", methods=["DELETE"])
def delete_symbol(symbol):
    try:
        return jsonify(md.remove_symbol(symbol.upper()))
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/symbols/<string:symbol>/group", methods=["PUT"])
def set_symbol_group(symbol):
    data = request.get_json(force=True) or {}
    group_tag = data.get("group_tag", "").strip()
    try:
        return jsonify(md.set_symbol_group(symbol.upper(), group_tag))
    except Exception as exc:
        return _data_error(exc)


# -- Database (proxied / embedded) ---------------------------------------------

@app.route("/api/db/stats", methods=["GET"])
def db_stats():
    """Watchlist / OHLCV size snapshot for large-ticker ops."""
    try:
        return jsonify(md.get_db_stats())
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/db/optimize", methods=["POST"])
def db_optimize():
    """Run ANALYZE + WAL checkpoint after big bulk loads."""
    try:
        if data_client.use_embedded():
            import database as db
            return jsonify(db.optimize_db())
        return jsonify(data_client._request("POST", "/api/db/optimize") or {})
    except Exception as exc:
        return _data_error(exc)


# -- Data fetch (proxied) -------------------------------------------------------

@app.route("/api/fetch/<string:symbol>", methods=["POST"])
def fetch_symbol(symbol):
    try:
        result = md.fetch_symbol(symbol.upper())
        if "error" in result:
            from data_fetcher import fetch_error_http_status
            return jsonify(result), fetch_error_http_status(result)
        return jsonify(result)
    except Exception as exc:
        return _data_error(exc)


@app.route("/api/refresh", methods=["POST"])
def refresh_all():
    try:
        body = request.get_json(force=True, silent=True) or {}
        try:
            overlap = int(body.get("overlap_days", 3))
        except (TypeError, ValueError):
            overlap = 3
        return jsonify(md.refresh_all(overlap_days=overlap))
    except Exception as exc:
        return _data_error(exc)


# -- OHLCV (on-the-fly from data service) ---------------------------------------

@app.route("/api/ohlcv/<string:symbol>", methods=["GET"])
def get_ohlcv(symbol):
    freq = request.args.get("freq", "daily")
    try:
        limit = int(request.args.get("limit", 500))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400

    if freq not in ("daily", "weekly"):
        return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400
    if limit <= 0:
        return jsonify({"error": "limit must be a positive integer"}), 400

    try:
        rows = md.get_ohlcv(symbol.upper(), freq, limit)
    except data_client.DataServiceError as exc:
        return _data_error(exc)
    except Exception as exc:
        return _data_error(exc)

    if not rows:
        return jsonify({"error": "No data. Fetch the symbol first."}), 404
    return jsonify(rows)


# -- Indicators -----------------------------------------------------------------

@app.route("/api/indicators/<string:symbol>", methods=["GET"])
def get_indicators(symbol):
    freq = request.args.get("freq", "daily")
    if freq not in ("daily", "weekly"):
        return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400

    kama_param = request.args.get("kama", "10,20,50")
    try:
        kama_periods = [int(p) for p in kama_param.split(",") if p.strip()]
        if not kama_periods:
            kama_periods = [10, 20, 50]
    except ValueError:
        return jsonify({"error": "kama must be comma-separated integers"}), 400

    result = ind.compute_indicators(symbol.upper(), freq, kama_periods)
    return jsonify(result)


# -- Stats ----------------------------------------------------------------------

@app.route("/api/stats/<string:symbol>", methods=["GET"])
def get_stats(symbol):
    try:
        result = stats.compute_stats(symbol.upper())
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -- Conditional forward-return distribution ------------------------------------

@app.route("/api/conditional-distribution/<string:symbol>", methods=["POST"])
def conditional_distribution(symbol):
    body = request.get_json(silent=True) or {}
    conditions = body.get("conditions", [])
    if not isinstance(conditions, list):
        return jsonify({"error": "conditions must be a list"}), 400

    horizons = body.get("horizons", [5, 10])
    try:
        horizons = [int(h) for h in horizons]
    except (TypeError, ValueError):
        return jsonify({"error": "horizons must be integers"}), 400
    if not horizons:
        horizons = [5, 10]
    if any(h < 1 or h > 250 for h in horizons):
        return jsonify({"error": "horizons must be between 1 and 250"}), 400

    try:
        result = conditional_dist.compute_conditional_distribution(
            symbol.upper(), conditions, horizons
        )
    except conditional_dist.ConditionError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - surface as JSON, don't 500 the UI
        return jsonify({"error": str(exc)}), 500

    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


# -- KNN Lookalike --------------------------------------------------------------

@app.route("/api/knn/<string:symbol>")
def get_knn(symbol):
    # precache: K refits are expensive; validate + cache per (symbol, k).
    k_raw = request.args.get("k", 15)
    k, err = precache.parse_capped_int(k_raw, default=15, lo=1,
                                       hi=precache.KNN_K_CAP)
    if err:
        return jsonify({"error": f"k {err}"}), 400
    try:
        refresh = precache.wants_refresh(request.args)
        key = (symbol.upper(), k)

        def _compute():
            return knn_model.compute_knn_lookalike(symbol.upper(), k=k)

        result, hit = precache.cached_call(
            "knn", key, _compute, precache.KNN_TTL_S, refresh=refresh,
            should_cache=lambda p: "error" not in p)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if "error" in result:
        return jsonify(result), 404
    resp = jsonify({**result, "cached": hit})
    resp.headers["X-Cache"] = "HIT" if hit else "MISS"
    return resp


# -- Backtester -----------------------------------------------------------------

@app.route("/api/backtest/<string:symbol>")
def get_backtest(symbol):
    # precache: full FAST×SLOW grid is expensive; cache per symbol.
    try:
        refresh = precache.wants_refresh(request.args)
        key = (symbol.upper(),)

        def _compute():
            return backtester.run_optimization(symbol.upper())

        result, hit = precache.cached_call(
            "backtest", key, _compute, precache.BACKTEST_TTL_S,
            refresh=refresh, should_cache=lambda p: "error" not in p)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if "error" in result:
        return jsonify(result), 404
    resp = jsonify({**result, "cached": hit})
    resp.headers["X-Cache"] = "HIT" if hit else "MISS"
    return resp


# -- Adaptive Trend -------------------------------------------------------------

@app.route("/api/adaptive-trend/<string:symbol>", methods=["GET"])
def get_adaptive_trend(symbol):
    freq   = request.args.get("freq", "daily")
    method = request.args.get("method", "kama")
    if freq not in ("daily", "weekly"):
        return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400
    if method not in ("kama", "adma"):
        return jsonify({"error": "method must be 'kama' or 'adma'"}), 400

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
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -- Trend Scan ----------------------------------------------------------------

@app.route("/api/trend-scan")
def trend_scan():
    """Compute adaptive-trend metrics for every watchlist symbol."""
    import concurrent.futures
    from scanner import _kama as kama_fn, _rsi as rsi_fn

    freq       = request.args.get("freq",   "daily")
    method     = request.args.get("method", "kama")
    # precache: bad params are JSON 400s (never HTML 500s for the UI).
    if freq not in ("daily", "weekly"):
        return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400
    if method not in ("kama", "adma"):
        return jsonify({"error": "method must be 'kama' or 'adma'"}), 400
    rsi_period, err = precache.parse_capped_int(
        request.args.get("rsi_period", 14), default=14, lo=2, hi=100)
    if err:
        return jsonify({"error": f"rsi_period {err}"}), 400
    try:
        symbols = md.list_symbol_codes()
    except Exception as exc:
        return _data_error(exc)
    if not symbols:
        return jsonify([])
    # precache: per-request symbol cap keeps big books smooth.
    limit, err = precache.parse_capped_int(
        request.args.get("limit"), default=len(symbols),
        lo=1, hi=precache.TRENDSCAN_SYMBOL_CAP)
    if err:
        return jsonify({"error": f"limit {err}"}), 400
    symbols = symbols[:limit]
    refresh = precache.wants_refresh(request.args)

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
            ohlcv = md.get_ohlcv_df(sym, freq, limit=600)
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

    # precache: array body shape is the JS contract — flag rides a header.
    key = ("trendscan", freq, method, rsi_period, tuple(sorted(symbols)),
           tuple(sorted(at_config.items())))

    def _compute():
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(_one, symbols))

    try:
        results, hit = precache.cached_call(
            "trendscan", key, _compute, precache.TRENDSCAN_TTL_S,
            refresh=refresh)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    _payload, remaining = precache.cache_get("trendscan", key)
    precache.maybe_refresh_in_background(
        "trendscan", key, _compute, precache.TRENDSCAN_TTL_S, remaining)
    resp = jsonify(results)
    resp.headers["X-Cache"] = "HIT" if hit else "MISS"
    return resp


# -- Scanner --------------------------------------------------------------------

@app.route("/api/scanner/sp500")
def get_sp500():
    tickers = scanner.get_sp500_tickers()
    return jsonify(tickers.to_dict(orient="records"))


@app.route("/api/scanner/fetch", methods=["POST"])
def fetch_sp500():
    force = request.get_json(force=True, silent=True) or {}
    force_refresh = force.get("force", False)
    if scanner._fetch_status["running"]:
        return jsonify({"message": "Fetch already running", "status": scanner._fetch_status})
    import threading
    def _run():
        scanner._fetch_status["running"] = True
        result = scanner.bulk_fetch_sp500(max_workers=5, force_refresh=force_refresh)
        scanner._fetch_status["running"] = False
        scanner._fetch_status["summary"] = result
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"message": "S&P 500 fetch started"})


@app.route("/api/scanner/status")
def scanner_status():
    return jsonify(scanner._fetch_status)


@app.route("/api/scanner/run")
def run_scanner():
    signal_filter = request.args.get("signal")
    results = scanner.run_scanner(signal_filter=signal_filter or None)
    return jsonify(results)


@app.route("/api/scanner", methods=["GET"])
def get_scanner():
    """Compute multi-timeframe scanner metrics for symbols with stored data."""
    # precache: TTL + ?refresh=1 + symbol cap; array body is the JS contract.
    try:
        universe = request.args.get("universe", "1").lower() in ("1", "true", "yes")
        if universe:
            symbols = md.list_symbols_with_ohlcv("daily", min_bars=30)
        else:
            symbols = [s["symbol"] for s in md.list_desk_symbols()]
        if not symbols:
            return jsonify([])
        limit, err = precache.parse_capped_int(
            request.args.get("limit"), default=len(symbols),
            lo=1, hi=precache.SCANNER_SYMBOL_CAP)
        if err:
            return jsonify({"error": f"limit {err}"}), 400
        symbols = symbols[:limit]
        refresh = precache.wants_refresh(request.args)
        key = ("scanner", universe, tuple(sorted(symbols)), len(symbols))

        def _compute():
            return scanner.compute_scanner(list(symbols))

        data, hit = precache.cached_call(
            "scanner", key, _compute, precache.SCANNER_TTL_S,
            refresh=refresh)
        _payload, remaining = precache.cache_get("scanner", key)
        precache.maybe_refresh_in_background(
            "scanner", key, _compute, precache.SCANNER_TTL_S, remaining)
        resp = jsonify(data)
        resp.headers["X-Cache"] = "HIT" if hit else "MISS"
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/setups/catalog", methods=["GET"])
def setups_catalog():
    return jsonify({"setups": setup_scanner.SETUP_IDS})


@app.route("/api/setups/scan", methods=["GET"])
def setups_scan():
    """Scan stored universe for named trading setups."""
    # precache: TTL + ?refresh=1; bad params are JSON 400s.
    setup_filter = request.args.get("setup") or None
    limit, err = precache.parse_capped_int(
        request.args.get("limit", 250), default=250,
        lo=1, hi=precache.SETUPS_LIMIT_CAP)
    if err:
        return jsonify({"error": f"limit {err}"}), 400
    min_score, err = precache.parse_capped_int(
        request.args.get("min_score", 0), default=0, lo=0, hi=100)
    if err:
        return jsonify({"error": f"min_score {err}"}), 400
    try:
        universe_only = request.args.get("universe", "1").lower() in ("1", "true", "yes")
        if universe_only:
            symbols = md.list_symbols_with_ohlcv("daily", min_bars=30)
        else:
            symbols = [s["symbol"] for s in md.list_desk_symbols()]
        refresh = precache.wants_refresh(request.args)
        key = (setup_filter, limit, min_score, universe_only,
               tuple(sorted(symbols)))

        def _compute():
            return setup_scanner.scan_setups(
                symbols=list(symbols),
                setup_filter=setup_filter,
                limit=limit,
                min_score=min_score,
            )

        payload, hit = precache.cached_call(
            "setups", key, _compute, precache.SETUPS_TTL_S,
            refresh=refresh)
        _cached_payload, remaining = precache.cache_get("setups", key)
        precache.maybe_refresh_in_background(
            "setups", key, _compute, precache.SETUPS_TTL_S, remaining)
        resp = jsonify({**payload, "cached": hit})
        resp.headers["X-Cache"] = "HIT" if hit else "MISS"
        return resp
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/universe/registry", methods=["GET"])
def universe_registry():
    return jsonify({"indices": index_universe.registry_for_api()})


@app.route("/api/universe/sync", methods=["POST"])
def universe_sync():
    """Register index constituents in DB (no Yahoo download)."""
    try:
        body = request.get_json(force=True) or {}
        indices = body.get("indices") or ["all"]
        merged = index_universe.merged_universe(indices)
        if data_client.use_embedded():
            import database as db
            sync = db.add_universe_symbols(merged.get("symbol_indices") or {})
        else:
            sync = {"error": "universe sync requires embedded mode"}
        return jsonify({
            "total_unique": merged.get("total_unique"),
            "per_index": merged.get("per_index"),
            "errors": merged.get("errors"),
            "sync": sync,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/universe/archive", methods=["POST"])
def universe_archive():
    """
    SSE batch: full history download for symbols in DB (optionally only missing).
    Body: {start_date, delay, only_missing, limit}
    """
    body = request.get_json(force=True) or {}
    start_date = body.get("start_date", "2000-01-01")
    try:
        delay = max(0.3, min(float(body.get("delay", 1.5)), 10.0))
    except (TypeError, ValueError):
        return jsonify({"error": "delay must be a number"}), 400
    only_missing = bool(body.get("only_missing", False))
    try:
        limit = int(body.get("limit", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400

    if not data_client.use_embedded():
        return jsonify({"error": "universe archive requires embedded mode"}), 400

    import time
    import database as db
    import data_fetcher as fetcher

    if only_missing:
        have = set(db.list_symbols_with_ohlcv("daily", min_bars=1))
        tickers = [s for s in db.list_symbol_codes() if s not in have]
    else:
        tickers = db.list_symbol_codes()
    if limit > 0:
        tickers = tickers[:limit]

    def generate():
        ok_count = fail_count = 0
        yield f"data: {json.dumps({'type': 'start', 'total': len(tickers)})}\n\n"
        for i, sym in enumerate(tickers):
            try:
                result = fetcher.fetch_full_history(sym, start=start_date)
                if "error" in result:
                    fail_count += 1
                    ok, msg = False, result["error"]
                else:
                    ok_count += 1
                    ok, msg = True, (
                        f"{result.get('daily_rows', 0)}d / "
                        f"{result.get('weekly_rows', 0)}w rows stored"
                    )
                yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': ok, 'msg': msg})}\n\n"
            except Exception as exc:
                fail_count += 1
                yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': False, 'msg': str(exc)})}\n\n"
            if i < len(tickers) - 1:
                time.sleep(delay)
        if ok_count:
            db.optimize_db()
        yield f"data: {json.dumps({'type': 'done', 'ok': ok_count, 'failed': fail_count})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/universe/refresh", methods=["POST"])
def universe_refresh():
    """SSE incremental refresh for all symbols in DB."""
    body = request.get_json(force=True) or {}
    try:
        delay = max(0.2, min(float(body.get("delay", 0.8)), 10.0))
    except (TypeError, ValueError):
        return jsonify({"error": "delay must be a number"}), 400
    try:
        overlap = int(body.get("overlap_days", 5))
    except (TypeError, ValueError):
        overlap = 5
    try:
        limit = int(body.get("limit", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400

    if not data_client.use_embedded():
        return jsonify({"error": "universe refresh requires embedded mode"}), 400

    import time
    import database as db
    import data_fetcher as fetcher

    tickers = db.list_symbol_codes()
    if limit > 0:
        tickers = tickers[:limit]

    def generate():
        ok_count = fail_count = skip_count = 0
        yield f"data: {json.dumps({'type': 'start', 'total': len(tickers)})}\n\n"
        for i, sym in enumerate(tickers):
            try:
                if db.is_recently_fetched(sym, hours=4):
                    skip_count += 1
                    yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': True, 'msg': 'skipped (recent)'})}\n\n"
                else:
                    result = fetcher.fetch_and_store(sym, overlap_days=overlap)
                    if "error" in result:
                        fail_count += 1
                        ok, msg = False, result["error"]
                    else:
                        ok_count += 1
                        ok, msg = True, f"{result.get('daily_rows', 0)}d updated"
                    yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': ok, 'msg': msg})}\n\n"
            except Exception as exc:
                fail_count += 1
                yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': False, 'msg': str(exc)})}\n\n"
            if i < len(tickers) - 1:
                time.sleep(delay)
        yield f"data: {json.dumps({'type': 'done', 'ok': ok_count, 'failed': fail_count, 'skipped': skip_count})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- News -----------------------------------------------------------------------

@app.route("/api/news", methods=["GET"])
def get_all_news():
    """Fetch news for all watchlist symbols using yfinance."""
    # precache: one page load otherwise fires a sequential Yahoo request
    # per symbol (throttle-prone). TTL + ?refresh=1 + per-request limit.
    # Single-symbol /api/news/<symbol> below stays live (uncached).
    try:
        symbols = md.list_symbol_codes()
    except Exception as exc:
        return _data_error(exc)
    if not symbols:
        return jsonify({"articles": [], "message": "No symbols in watchlist"})

    limit, err = precache.parse_capped_int(
        request.args.get("limit"), default=precache.NEWS_LIMIT_CAP,
        lo=1, hi=precache.NEWS_LIMIT_CAP)
    if err:
        return jsonify({"error": f"limit {err}"}), 400
    refresh = precache.wants_refresh(request.args)
    key = (tuple(sorted(symbols)), limit)

    def _compute():
        import time as _time

        all_articles = []
        seen_urls = set()
        errors = []

        for i, symbol in enumerate(symbols):
            try:
                ticker = yf.Ticker(symbol)
                news_items = ticker.news

                if not news_items:
                    continue

                for item in news_items:
                    content = item.get("content", {})
                    url = (content.get("canonicalUrl", {}).get("url") or
                           content.get("clickThroughUrl", {}).get("url") or "")

                    if url and url in seen_urls:
                        continue

                    if url:
                        seen_urls.add(url)

                    provider = content.get("provider", {})
                    article = {
                        "symbol": symbol,
                        "title": content.get("title", "No title"),
                        "summary": content.get("summary") or content.get("description", ""),
                        "url": url,
                        "publish_time": content.get("pubDate", ""),
                        "provider": provider.get("displayName", "Yahoo Finance"),
                        "provider_url": provider.get("url", "https://finance.yahoo.com/")
                    }
                    all_articles.append(article)

            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
            # precache: small gap between Yahoo calls avoids 429 storms.
            if precache.NEWS_GAP_S > 0 and i < len(symbols) - 1:
                _time.sleep(precache.NEWS_GAP_S)

        all_articles.sort(key=lambda x: x.get("publish_time", ""), reverse=True)

        result = {
            "articles": all_articles[:limit],
            "source": "Yahoo Finance",
            "symbol_count": len(symbols),
            "article_count": min(len(all_articles), limit),
        }

        if errors:
            result["errors"] = errors

        return result

    try:
        result, hit = precache.cached_call(
            "news", key, _compute, precache.NEWS_TTL_S, refresh=refresh)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    _payload, remaining = precache.cache_get("news", key)
    precache.maybe_refresh_in_background(
        "news", key, _compute, precache.NEWS_TTL_S, remaining)
    resp = jsonify({**result, "cached": hit})
    resp.headers["X-Cache"] = "HIT" if hit else "MISS"
    return resp


@app.route("/api/news/<string:symbol>", methods=["GET"])
def get_symbol_news(symbol):
    """Fetch news for a specific symbol using yfinance."""
    try:
        ticker = yf.Ticker(symbol.upper())
        news_items = ticker.news
        
        if not news_items:
            return jsonify({
                "symbol": symbol.upper(),
                "articles": [],
                "message": f"No news available for {symbol.upper()}",
                "source": "Yahoo Finance"
            })
        
        articles = []
        for item in news_items:
            content = item.get("content", {})
            provider = content.get("provider", {})
            
            article = {
                "title": content.get("title", "No title"),
                "summary": content.get("summary") or content.get("description", ""),
                "url": (content.get("canonicalUrl", {}).get("url") or 
                       content.get("clickThroughUrl", {}).get("url") or ""),
                "publish_time": content.get("pubDate", ""),
                "provider": provider.get("displayName", "Yahoo Finance"),
                "provider_url": provider.get("url", "https://finance.yahoo.com/")
            }
            articles.append(article)
        
        return jsonify({
            "symbol": symbol.upper(),
            "articles": articles,
            "article_count": len(articles),
            "source": "Yahoo Finance"
        })
        
    except Exception as e:
        return jsonify({
            "symbol": symbol.upper(),
            "error": str(e),
            "source": "Yahoo Finance"
        }), 500


# -- Cache knobs (precache) --------------------------------------------------------

@app.route("/api/cache/stats", methods=["GET"])
def cache_stats():
    """TTL sizes + tunables for the read caches. Read-only, never fetches."""
    try:
        stats = precache.cache_stats()
        try:
            stats["watchlist_symbols"] = len(md.list_symbol_codes())
        except Exception:
            stats["watchlist_symbols"] = None
        return jsonify(stats)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/cache/prewarm", methods=["POST"])
def cache_prewarm():
    """Trigger a background prewarm (DB-backed only, never Yahoo)."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        try:
            cap = int(body.get("symbols", precache.PREFETCH_SYMBOLS))
        except (TypeError, ValueError):
            return jsonify({"error": "symbols must be an integer"}), 400
        cap = max(0, min(cap, 500))
        precache.schedule_background(lambda: precache.prewarm_sync(cap))
        return jsonify({"message": "prewarm started", "symbols_cap": cap})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# -- Data Manager (proxied to data service) -------------------------------------

@app.route("/api/data-manager/ticker-lists", methods=["GET"])
def get_ticker_lists():
    """Curated ticker library — served by the data service."""
    if data_client.use_embedded():
        import ticker_lists as tl
        return jsonify(tl.TICKER_LIBRARY)
    try:
        url = f"{data_client.DATA_SERVICE_URL}/api/data-manager/ticker-lists"
        with urllib.request.urlopen(url, timeout=30) as resp:
            return Response(resp.read(), mimetype="application/json")
    except Exception as exc:
        return _data_error(data_client.DataServiceError(str(exc)))


@app.route("/api/data-manager/fetch-batch", methods=["POST"])
def fetch_batch():
    """
    Proxy SSE batch fetch to the data service (or run embedded for tests).
    """
    body = request.get_json(force=True) or {}

    if data_client.use_embedded():
        import time
        import database as db
        import data_fetcher as fetcher

        tickers = [t.strip().upper() for t in body.get("tickers", []) if str(t).strip()]
        start_date = body.get("start_date", "2000-01-01")
        try:
            delay = max(0.3, min(float(body.get("delay", 1.5)), 10.0))
        except (TypeError, ValueError):
            return jsonify({"error": "delay must be a number"}), 400
        add_wl = bool(body.get("add_watchlist", True))
        if not tickers:
            return jsonify({"error": "tickers list is empty"}), 400

        def generate_embedded():
            ok_count = fail_count = 0
            yield f"data: {json.dumps({'type': 'start', 'total': len(tickers)})}\n\n"
            for i, sym in enumerate(tickers):
                try:
                    if add_wl:
                        db.add_symbol(sym)
                    result = fetcher.fetch_full_history(sym, start=start_date)
                    if "error" in result:
                        fail_count += 1
                        ok, msg = False, result["error"]
                    else:
                        ok_count += 1
                        ok, msg = True, (
                            f"{result.get('daily_rows', 0)}d / "
                            f"{result.get('weekly_rows', 0)}w rows stored"
                        )
                    yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': ok, 'msg': msg})}\n\n"
                except Exception as exc:
                    fail_count += 1
                    yield f"data: {json.dumps({'type': 'result', 'index': i, 'symbol': sym, 'ok': False, 'msg': str(exc)})}\n\n"
                if i < len(tickers) - 1:
                    time.sleep(delay)
            yield f"data: {json.dumps({'type': 'done', 'ok': ok_count, 'failed': fail_count})}\n\n"

        return Response(
            stream_with_context(generate_embedded()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Stream-proxy SSE from the data service
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{data_client.DATA_SERVICE_URL}/api/data-manager/fetch-batch",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    def generate_proxy():
        try:
            with urllib.request.urlopen(req, timeout=3600) as resp:
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    yield chunk
        except urllib.error.URLError as exc:
            yield f"data: {json.dumps({'type': 'result', 'index': 0, 'symbol': '?', 'ok': False, 'msg': str(exc.reason)})}\n\n".encode()
            yield f"data: {json.dumps({'type': 'done', 'ok': 0, 'failed': 1})}\n\n".encode()

    return Response(
        stream_with_context(generate_proxy()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- Entry point ----------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    mode = data_client.DATA_SERVICE_MODE
    url = data_client.DATA_SERVICE_URL
    print(f"\n  Whats-News analysis at http://localhost:{port}")
    print(f"  News feed:              http://localhost:{port}/news")
    print(f"  Data service mode={mode} url={url}\n")
    # precache: warm DB-backed read caches off the request path.
    try:
        precache.prewarm_async()
    except Exception as exc:
        print(f"  Prewarm skipped: {exc}")
    app.run(debug=True, port=port)
