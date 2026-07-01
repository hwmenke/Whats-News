"""Alert CRUD + evaluation routes."""
import logging
from flask import Blueprint, jsonify, request

import database as db
import errors
import swing_core

logger = logging.getLogger(__name__)
alerts_bp = Blueprint("alerts", __name__)

ALERT_FIELDS = ("price", "rsi_14", "kama10_pct", "kama20_pct", "kama50_pct")


@alerts_bp.route("/api/alerts", methods=["GET"])
def list_alerts():
    symbol = request.args.get("symbol")
    return jsonify(db.list_alerts(symbol.upper() if symbol else None))


@alerts_bp.route("/api/alerts", methods=["POST"])
def create_alert():
    body = request.get_json(silent=True) or {}
    symbol    = body.get("symbol", "").strip().upper()
    field     = body.get("field", "").strip()
    condition = body.get("condition", "").strip()
    threshold = body.get("threshold")

    if not symbol:
        raise errors.symbol_required()
    if field not in ALERT_FIELDS:
        raise errors.validation(f"field must be one of: {', '.join(ALERT_FIELDS)}")
    if condition not in ("above", "below"):
        raise errors.validation("condition must be 'above' or 'below'")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise errors.validation("threshold must be a number")

    alert_id = db.add_alert(symbol, field, condition, threshold)
    return jsonify({"id": alert_id, "message": "Alert created"}), 201


@alerts_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    db.delete_alert(alert_id)
    return jsonify({"message": "deleted"})


@alerts_bp.route("/api/alerts/<int:alert_id>/reset", methods=["POST"])
def reset_alert(alert_id):
    db.reset_alert(alert_id)
    return jsonify({"message": "reset"})


def _alert_field_value(symbol: str, field: str):
    """Compute the current value of an alert field from stored daily bars."""
    df = db.get_ohlcv_df(symbol, "daily", limit=80)
    if df.empty or len(df) < 15:
        return None
    close = df["close"]
    price = float(close.iloc[-1])
    if field == "price":
        return price
    if field == "rsi_14":
        v = swing_core.rsi(close, 14).iloc[-1]
        return float(v) if v == v else None
    if field.startswith("kama") and field.endswith("_pct"):
        period = int(field[4:field.index("_")])
        k = swing_core.kama(close, period).iloc[-1]
        if k != k or not k:
            return None
        return (price / float(k) - 1) * 100
    return None


@alerts_bp.route("/api/alerts/check", methods=["POST"])
def check_alerts():
    """
    Evaluate all untriggered alerts against latest stored data.
    Marks newly-triggered alerts in the DB and returns them.
    DB-only — safe to poll from the frontend.
    """
    alerts    = db.list_alerts()
    triggered = []
    for a in alerts:
        if a.get("triggered_at"):
            continue
        try:
            value = _alert_field_value(a["symbol"], a["field"])
            if value is None:
                continue
            hit = (value > a["threshold"]) if a["condition"] == "above" \
                  else (value < a["threshold"])
            if hit:
                db.mark_alert_triggered(a["id"])
                a["value"] = round(value, 4)
                triggered.append(a)
        except Exception as exc:
            logger.debug("Alert check skipped %s: %s", a.get("symbol"), exc)
    return jsonify({"checked": len(alerts), "triggered": triggered})
