"""News, calendar, newsletter, and earnings routes."""
import logging
from flask import Blueprint, jsonify, request

import database as db
import econ_calendar
import errors
import news as news_mod
import newsletter_engine

logger = logging.getLogger(__name__)
news_bp = Blueprint("news_routes", __name__)


@news_bp.route("/api/news/<string:symbol>", methods=["GET"])
def get_news(symbol):
    limit = min(int(request.args.get("limit", 20)), 50)
    articles = news_mod.fetch_news(symbol, limit=limit)
    return jsonify(articles)


@news_bp.route("/api/calendar", methods=["GET"])
def get_calendar():
    """Macro + earnings calendar.

    Query params: days_past (default 30), days_fwd (default 180).
    Macro events come from econ_calendar (built-in schedule, refined by
    FRED when an API key is configured in Settings → Economic Data).
    """
    import datetime as dt

    try:
        days_past = min(max(int(request.args.get("days_past", 30)), 0), 365)
        days_fwd  = min(max(int(request.args.get("days_fwd", 180)), 1), 730)
    except (TypeError, ValueError):
        days_past, days_fwd = 30, 180

    today = dt.date.today()
    start = today - dt.timedelta(days=days_past)
    end   = today + dt.timedelta(days=days_fwd)

    fred_key = db.get_setting("fred_api_key")
    events = econ_calendar.get_events(start, end, fred_api_key=fred_key)

    # Watchlist earnings (importance boosted for focus/active tiers)
    for sym in db.list_symbols():
        ed = sym.get("next_earnings")
        if ed and start.isoformat() <= ed[:10] <= end.isoformat():
            tier = sym.get("watchlist_tier") or "watchlist"
            events.append({
                "date":       ed[:10],
                "type":       "EARNINGS",
                "label":      f"{sym['symbol']} Earnings",
                "symbol":     sym["symbol"],
                "category":   "earnings",
                "importance": 3 if tier in ("focus", "active") else 2,
                "approx":     False,
                "color":      econ_calendar.CATEGORY_COLORS["earnings"],
            })

    events.sort(key=lambda e: (e["date"], -e["importance"]))
    return jsonify(events)


# ── App settings (server-side KV; currently: FRED API key) ───────────────────

@news_bp.route("/api/settings", methods=["GET"])
def get_app_settings():
    """Whitelisted settings; secrets reported as present/absent only."""
    return jsonify({
        "fred_api_key_set": bool(db.get_setting("fred_api_key")),
    })


@news_bp.route("/api/settings", methods=["POST"])
def set_app_settings():
    body = request.get_json(silent=True) or {}
    allowed = {"fred_api_key"}
    updated = []
    for key in allowed:
        if key in body:
            db.set_setting(key, str(body[key] or "").strip())
            updated.append(key)
    if not updated:
        raise errors.validation(f"No valid settings keys. Allowed: {sorted(allowed)}")
    return jsonify({"updated": updated})


@news_bp.route("/api/newsletter/data", methods=["GET"])
def get_newsletter_data():
    try:
        n_charts = min(int(request.args.get("n", 20)), 50)
    except (TypeError, ValueError):
        n_charts = 20
    try:
        return jsonify(newsletter_engine.compute_newsletter_data(n_charts=n_charts))
    except Exception as e:
        logger.exception("newsletter error")
        raise errors.computation_failed(str(e))


@news_bp.route("/api/earnings/<string:symbol>", methods=["GET"])
def get_earnings_dates(symbol):
    """Return known earnings dates for a symbol from the watchlist metadata."""
    sym = symbol.upper()
    rows = db.list_symbols()
    entry = next((r for r in rows if r["symbol"] == sym), None)
    dates = []
    if entry and entry.get("next_earnings"):
        dates.append({"date": entry["next_earnings"], "type": "scheduled"})
    return jsonify({"symbol": sym, "dates": dates})
