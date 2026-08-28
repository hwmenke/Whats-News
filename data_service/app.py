"""
data_service/app.py — Data Management service for Whats-News

Owns watchlist + OHLCV storage and Yahoo Finance downloads.
The analysis dashboard (app.py on :8050) reads from this service on the fly.

Run:
  python -m data_service.app
  # → http://localhost:8051
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS

# Allow importing shared modules from repo root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import database as db
import data_fetcher as fetcher
import ticker_lists as tl

app = Flask(__name__, static_folder=str(_ROOT), static_url_path="")
CORS(app)

db.init_db()


@app.route("/")
def index():
    return send_from_directory(Path(__file__).resolve().parent, "index.html")


@app.route("/api/health")
def health():
    stats = {}
    try:
        if hasattr(db, "get_db_stats"):
            stats = db.get_db_stats()
        else:
            stats = {"symbol_count": len(db.list_symbols())}
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "service": "data", **stats})


# -- Symbols --------------------------------------------------------------------

@app.route("/api/symbols", methods=["GET"])
def get_symbols():
    return jsonify(db.list_symbols())


@app.route("/api/symbols/codes", methods=["GET"])
def get_symbol_codes():
    if hasattr(db, "list_symbol_codes"):
        codes = db.list_symbol_codes()
    else:
        codes = [s["symbol"] for s in db.list_symbols()]
    return jsonify({"symbols": codes, "count": len(codes)})


@app.route("/api/symbols", methods=["POST"])
def add_symbol():
    data = request.get_json(force=True) or {}

    if "symbols" in data:
        raw = data.get("symbols") or []
        if not isinstance(raw, list):
            return jsonify({"error": "symbols must be a list"}), 400
        if hasattr(db, "add_symbols"):
            result = db.add_symbols(raw)
        else:
            added, skipped = [], []
            for item in raw:
                sym = str(item).strip().upper()
                if not sym:
                    continue
                if db.add_symbol(sym):
                    added.append(sym)
                else:
                    skipped.append(sym)
            result = {"added": added, "skipped": skipped}
        status = 201 if result.get("added") else 200
        return jsonify({
            "message": f"{len(result.get('added', []))} added, {len(result.get('skipped', []))} skipped",
            **result,
        }), status

    symbol = data.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    added = db.add_symbol(symbol)
    if not added:
        return jsonify({"message": f"{symbol} already in watchlist", "added": False}), 200
    return jsonify({"message": f"{symbol} added", "added": True}), 201


@app.route("/api/symbols/<string:symbol>", methods=["DELETE"])
def delete_symbol(symbol):
    db.remove_symbol(symbol.upper())
    return jsonify({"message": f"{symbol.upper()} removed"})


@app.route("/api/symbols/<string:symbol>/fresh", methods=["GET"])
def symbol_fresh(symbol):
    try:
        hours = int(request.args.get("hours", 23))
    except (TypeError, ValueError):
        return jsonify({"error": "hours must be an integer"}), 400
    fresh = db.is_recently_fetched(symbol.upper(), hours=hours)
    return jsonify({"symbol": symbol.upper(), "fresh": fresh, "hours": hours})


@app.route("/api/symbols/<string:symbol>/group", methods=["PUT"])
def set_symbol_group(symbol):
    data = request.get_json(force=True) or {}
    group_tag = data.get("group_tag", "").strip()
    db.set_symbol_group(symbol.upper(), group_tag)
    return jsonify({"message": "ok"})


# -- Fetch ----------------------------------------------------------------------

@app.route("/api/fetch/<string:symbol>", methods=["POST"])
def fetch_symbol(symbol):
    try:
        result = fetcher.fetch_and_store(symbol.upper())
        if "error" in result:
            return jsonify(result), fetcher.fetch_error_http_status(result)
        return jsonify(result)
    except Exception as exc:
        classified = fetcher.classify_yahoo_error(exc)
        status = fetcher.fetch_error_http_status(classified)
        return jsonify({"symbol": symbol.upper(), **classified}), status


@app.route("/api/refresh", methods=["POST"])
def refresh_all():
    if hasattr(db, "list_symbol_codes"):
        symbols = db.list_symbol_codes()
    else:
        symbols = [s["symbol"] for s in db.list_symbols()]
    results = []

    def _fetch(sym):
        try:
            return fetcher.fetch_and_store(sym)
        except Exception as exc:
            return {"symbol": sym, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=min(8, len(symbols) or 1)) as pool:
        futures = {pool.submit(_fetch, s): s for s in symbols}
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
        return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400
    if limit <= 0:
        return jsonify({"error": "limit must be a positive integer"}), 400

    rows = db.get_ohlcv(symbol.upper(), freq, limit)
    if not rows:
        return jsonify({"error": "No data. Fetch the symbol first."}), 404
    return jsonify(rows)


# -- DB ops ---------------------------------------------------------------------

@app.route("/api/db/stats", methods=["GET"])
def db_stats():
    if hasattr(db, "get_db_stats"):
        return jsonify(db.get_db_stats())
    return jsonify({
        "symbol_count": len(db.list_symbols()),
        "service": "data",
    })


@app.route("/api/db/optimize", methods=["POST"])
def db_optimize():
    if hasattr(db, "optimize_db"):
        return jsonify(db.optimize_db())
    return jsonify({"message": "optimize not available in this database build"})


# -- Curated lists + batch fetch ------------------------------------------------

@app.route("/api/data-manager/ticker-lists", methods=["GET"])
def get_ticker_lists():
    return jsonify(tl.TICKER_LIBRARY)


@app.route("/api/data-manager/fetch-batch", methods=["POST"])
def fetch_batch():
    body = request.get_json(force=True) or {}
    tickers = [t.strip().upper() for t in body.get("tickers", []) if str(t).strip()]
    start_date = body.get("start_date", "2000-01-01")
    delay = float(body.get("delay", 1.5))
    add_wl = bool(body.get("add_watchlist", True))

    if not tickers:
        return jsonify({"error": "tickers list is empty"}), 400

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
                        ok = False
                    else:
                        ok_count += 1
                        msg = (
                            f"{result.get('daily_rows', 0)}d / "
                            f"{result.get('weekly_rows', 0)}w rows stored"
                        )
                        ok = True

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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("DATA_PORT", os.environ.get("PORT", 8051)))
    print(f"\n  Data Management service at http://localhost:{port}\n")
    app.run(debug=True, port=port, threaded=True)
