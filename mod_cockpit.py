"""
mod_cockpit.py — Blueprints for the cockpit review tools (performance, export).

Pure: built on the journal `trades` table via cockpit_analytics.
"""

from flask import Blueprint, jsonify, Response

import cockpit_analytics as ca

# ── Performance analytics ────────────────────────────────────────────────────────
performance_bp = Blueprint("mod_performance", __name__)


@performance_bp.route("/api/performance", methods=["GET"])
def performance():
    return jsonify(ca.compute_performance())


@performance_bp.route("/api/journal/export.csv", methods=["GET"])
def export_csv():
    csv_text = ca.export_trades_csv()
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"},
    )
