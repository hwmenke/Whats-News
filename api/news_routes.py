"""News, calendar, newsletter, and earnings routes."""
import logging
from flask import Blueprint, jsonify, request

import database as db
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
