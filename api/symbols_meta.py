"""Symbol metadata routes: groups, notes, fundamentals, quick-stats,
watchlist export/import, data coverage, ranged fetch."""
import logging
from flask import Blueprint, jsonify, request

import database as db
import errors

logger = logging.getLogger(__name__)
symbols_bp = Blueprint("symbols_meta", __name__)


@symbols_bp.route("/api/symbols/<string:symbol>/group", methods=["PUT"])
def set_symbol_group(symbol):
    data      = request.get_json(silent=True) or {}
    group_tag = data.get("group_tag", "").strip()
    db.set_symbol_group(symbol.upper(), group_tag)
    return jsonify({"message": "ok"})


@symbols_bp.route("/api/symbols/quick-stats", methods=["GET"])
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


@symbols_bp.route("/api/symbols/<string:symbol>/notes", methods=["PUT"])
def set_notes(symbol):
    body  = request.get_json(silent=True) or {}
    notes = body.get("notes", "")
    db.set_symbol_notes(symbol.upper(), notes)
    return jsonify({"message": "ok"})


@symbols_bp.route("/api/fundamentals/<string:symbol>", methods=["GET"])
def get_fundamentals(symbol):
    row = db.get_fundamentals(symbol.upper())
    if row is None:
        raise errors.ApiError("NO_DATA", "No fundamental data.",
                              hint="Fetch the symbol first.", http=404)
    return jsonify(row)


# ── Watchlist Export / Import ──────────────────────────────────────────────────

@symbols_bp.route("/api/export", methods=["GET"])
def export_watchlist():
    return jsonify({
        "version":   2,
        "symbols":   db.list_symbols(),
        "alerts":    db.list_alerts(),
        "positions": db.list_positions(),
    })


@symbols_bp.route("/api/import", methods=["POST"])
def import_watchlist():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or "symbols" not in data:
        raise errors.validation("Invalid import format — expected {symbols: [...], ...}")

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


# ── Data Coverage ─────────────────────────────────────────────────────────────

@symbols_bp.route("/api/data-coverage", methods=["GET"])
def get_data_coverage():
    """Per-symbol coverage stats: date range, bar counts, staleness."""
    from datetime import date as _date
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT s.symbol, s.name, s.sector, s.last_fetch,
               COUNT(CASE WHEN o.freq='daily'  THEN 1 END) AS daily_count,
               COUNT(CASE WHEN o.freq='weekly' THEN 1 END) AS weekly_count,
               MIN(CASE WHEN o.freq='daily'    THEN o.date END) AS first_daily,
               MAX(CASE WHEN o.freq='daily'    THEN o.date END) AS last_daily
        FROM symbols s
        LEFT JOIN ohlcv o ON o.symbol = s.symbol
        GROUP BY s.symbol
        ORDER BY s.symbol
    """).fetchall()
    conn.close()

    today = _date.today()
    result = []
    for r in rows:
        r = dict(r)
        no_data = not r["first_daily"]
        has_gap = False
        if r["last_daily"]:
            last = _date.fromisoformat(r["last_daily"])
            has_gap = (today - last).days > 7
        result.append({
            "symbol":       r["symbol"],
            "name":         r["name"] or "",
            "sector":       r["sector"] or "",
            "last_fetch":   r["last_fetch"] or "",
            "daily_count":  r["daily_count"] or 0,
            "weekly_count": r["weekly_count"] or 0,
            "first_daily":  r["first_daily"] or "",
            "last_daily":   r["last_daily"] or "",
            "no_data":      no_data,
            "has_gap":      has_gap,
        })
    return jsonify(result)


@symbols_bp.route("/api/fetch-range/<string:symbol>", methods=["POST"])
def fetch_range(symbol):
    """Fetch history for a symbol between start_date and end_date."""
    body       = request.get_json(silent=True) or {}
    start_date = body.get("start_date", "2000-01-01")
    try:
        import data_fetcher as df_mod
        df_mod.fetch_full_history(symbol.upper(), start=start_date)
        return jsonify({"ok": True, "symbol": symbol.upper(), "start": start_date})
    except Exception as e:
        logger.exception("fetch-range error")
        raise errors.computation_failed(str(e))
