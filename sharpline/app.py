"""
app.py - SharpLine Flask server.

Run:  python3 app.py        (serves on http://localhost:8051)

Optional:
  ODDS_API_KEY=...   enables live sportsbook lines via The Odds API.
Without a key (or offline) the app serves a realistic sample slate so every
feature still works.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import database as db
import sources
from edges import analyse_board
from model import DEFAULT_RATINGS, NFL_TEAMS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

db.init_db()


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# -- Board & edges -----------------------------------------------------------------

@app.route("/api/board")
def api_board():
    force = request.args.get("refresh") == "1"
    board = sources.get_board(force_refresh=force)
    if force:
        db.snapshot_board(board)
    return jsonify(board)


@app.route("/api/edges")
def api_edges():
    board = sources.get_board(force_refresh=request.args.get("refresh") == "1")
    ratings = db.get_ratings(defaults=DEFAULT_RATINGS)
    settings = db.get_settings()
    return jsonify(analyse_board(board, ratings, settings))


@app.route("/api/movement/<game_id>")
def api_movement(game_id):
    market = request.args.get("market", "spread")
    return jsonify(db.get_movement(game_id, market))


# -- Ratings -----------------------------------------------------------------------

@app.route("/api/ratings", methods=["GET"])
def api_ratings():
    ratings = db.get_ratings(defaults=DEFAULT_RATINGS)
    return jsonify([
        {"team": abbr, "rating": ratings.get(abbr, 0.0), **NFL_TEAMS[abbr]}
        for abbr in sorted(NFL_TEAMS, key=lambda a: -ratings.get(a, 0.0))
    ])


@app.route("/api/ratings", methods=["PUT"])
def api_ratings_update():
    data = request.get_json(force=True)
    updates = {t: float(r) for t, r in data.items() if t in NFL_TEAMS}
    if not updates:
        return jsonify({"error": "no valid teams in payload"}), 400
    db.set_ratings(updates)
    return jsonify({"message": f"updated {len(updates)} rating(s)"})


@app.route("/api/ratings/reset", methods=["POST"])
def api_ratings_reset():
    db.set_ratings(DEFAULT_RATINGS)
    return jsonify({"message": "ratings reset to defaults"})


# -- Settings ----------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def api_settings():
    return jsonify(db.get_settings())


@app.route("/api/settings", methods=["PUT"])
def api_settings_update():
    data = request.get_json(force=True)
    allowed = {"bankroll", "kelly_fraction", "max_bet_pct", "edge_threshold", "hfa"}
    updates = {k: float(v) for k, v in data.items() if k in allowed}
    db.set_settings(updates)
    return jsonify(db.get_settings())


# -- Bets --------------------------------------------------------------------------

@app.route("/api/bets", methods=["GET"])
def api_bets():
    return jsonify({"bets": db.list_bets(), "summary": db.bet_summary()})


@app.route("/api/bets", methods=["POST"])
def api_bets_add():
    bet = request.get_json(force=True)
    required = ("game_id", "description", "market", "side", "odds", "stake")
    missing = [k for k in required if not bet.get(k) and bet.get(k) != 0]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
    bet_id = db.add_bet(bet)
    return jsonify({"id": bet_id}), 201


@app.route("/api/bets/<int:bet_id>/settle", methods=["POST"])
def api_bets_settle(bet_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in ("won", "lost", "push", "open"):
        return jsonify({"error": "status must be won/lost/push/open"}), 400
    bet = db.settle_bet(
        bet_id, status,
        closing_line=data.get("closing_line"),
        closing_odds=data.get("closing_odds"),
    )
    if bet is None:
        return jsonify({"error": "bet not found"}), 404
    return jsonify(bet)


@app.route("/api/bets/<int:bet_id>", methods=["DELETE"])
def api_bets_delete(bet_id):
    db.delete_bet(bet_id)
    return jsonify({"message": "deleted"})


# -- Teams -------------------------------------------------------------------------

@app.route("/api/teams")
def api_teams():
    return jsonify(NFL_TEAMS)


if __name__ == "__main__":
    print("SharpLine running on http://localhost:8051")
    app.run(host="0.0.0.0", port=8051, debug=False)
