"""
app.py - Flask REST API server for the Financial Dashboard
Run: python app.py
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import database as db
import data_fetcher as fetcher
import indicators as ind
import stats as stats

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

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
        return jsonify({"error": "symbol is required"}), 400
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
    try:
        result = fetcher.fetch_and_store(symbol.upper())
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    freq  = request.args.get("freq",  "daily")
    limit = int(request.args.get("limit", 500))

    if freq not in ("daily", "weekly"):
        return jsonify({"error": "freq must be 'daily' or 'weekly'"}), 400

    rows = db.get_ohlcv(symbol.upper(), freq, limit)
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


# -- Entry point ----------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"\n  Financial Dashboard running at http://localhost:{port}\n")
    app.run(debug=True, port=port)
