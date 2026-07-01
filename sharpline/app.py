"""
app.py - SharpLine Flask server.

Run:  python3 app.py        (serves on http://localhost:8051)

Zero configuration needed:
  * power ratings sync themselves from nflverse game data on first start
  * sportsbook lines come from ESPN's keyless public API when in season
  * Polymarket and Kalshi probabilities are public, no key
  * paste a free The Odds API key in Settings for multi-book line shopping
  * offline, the real schedule is priced by the model so the UI always works
"""

import threading
import time

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import database as db
import ratings as ratings_mod
import sources
from edges import analyse_board
from model import DEFAULT_RATINGS, NFL_TEAMS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

db.init_db()

AUTO_REFRESH_SECS = 600  # snapshot the board every 10 min for line movement


def _current_ratings():
    return db.get_ratings(defaults=DEFAULT_RATINGS)


def _board(force=False):
    s = db.get_settings()
    return sources.get_board(
        force_refresh=force,
        api_key=s.get("odds_api_key") or None,
        ratings=_current_ratings(),
        hfa=s["hfa"],
    )


def _sync_ratings(force=False):
    """Pull nflverse data and recompute Elo ratings. Returns meta or None."""
    games = ratings_mod.fetch_games(force=force)
    if not games:
        return None
    ratings, meta = ratings_mod.compute_elo_ratings(games)
    if not ratings:
        return None
    db.set_ratings(ratings)
    db.set_settings({"ratings_source": "nflverse",
                     "ratings_synced_at": str(meta["synced_at"])})
    return meta


def _startup_worker():
    """First boot: auto-sync ratings if the user has never touched them,
    then keep snapshotting the board for line-movement history."""
    s = db.get_settings()
    if s.get("ratings_source") == "seed":
        _sync_ratings()
    while True:
        try:
            db.snapshot_board(_board(force=True))
        except Exception:
            pass
        time.sleep(AUTO_REFRESH_SECS)


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# -- Board & edges -----------------------------------------------------------------

@app.route("/api/board")
def api_board():
    force = request.args.get("refresh") == "1"
    board = _board(force=force)
    if force:
        db.snapshot_board(board)
    return jsonify(board)


@app.route("/api/edges")
def api_edges():
    board = _board(force=request.args.get("refresh") == "1")
    return jsonify(analyse_board(board, _current_ratings(), db.get_settings()))


@app.route("/api/movement/<game_id>")
def api_movement(game_id):
    market = request.args.get("market", "spread")
    return jsonify(db.get_movement(game_id, market))


# -- Ratings -----------------------------------------------------------------------

@app.route("/api/ratings", methods=["GET"])
def api_ratings():
    ratings = _current_ratings()
    s = db.get_settings()
    return jsonify({
        "source": s.get("ratings_source", "seed"),
        "synced_at": float(s["ratings_synced_at"]) if s.get("ratings_synced_at") else None,
        "teams": [
            {"team": abbr, "rating": ratings.get(abbr, 0.0), **NFL_TEAMS[abbr]}
            for abbr in sorted(NFL_TEAMS, key=lambda a: -ratings.get(a, 0.0))
        ],
    })


@app.route("/api/ratings", methods=["PUT"])
def api_ratings_update():
    data = request.get_json(force=True)
    updates = {t: float(r) for t, r in data.items() if t in NFL_TEAMS}
    if not updates:
        return jsonify({"error": "no valid teams in payload"}), 400
    db.set_ratings(updates)
    db.set_settings({"ratings_source": "manual"})
    return jsonify({"message": f"updated {len(updates)} rating(s)"})


@app.route("/api/ratings/sync", methods=["POST"])
def api_ratings_sync():
    meta = _sync_ratings(force=True)
    if meta is None:
        return jsonify({"error": "could not fetch nflverse data (offline?)"}), 502
    return jsonify({"message": "ratings recomputed from nflverse", **meta})


@app.route("/api/ratings/reset", methods=["POST"])
def api_ratings_reset():
    db.set_ratings(DEFAULT_RATINGS)
    db.set_settings({"ratings_source": "seed", "ratings_synced_at": ""})
    return jsonify({"message": "ratings reset to seed defaults"})


# -- Settings ----------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def api_settings():
    return jsonify(db.get_settings())


@app.route("/api/settings", methods=["PUT"])
def api_settings_update():
    data = request.get_json(force=True)
    numeric = {"bankroll", "kelly_fraction", "max_bet_pct", "edge_threshold", "hfa"}
    updates = {k: float(v) for k, v in data.items() if k in numeric}
    if "odds_api_key" in data:
        updates["odds_api_key"] = str(data["odds_api_key"]).strip()
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
    threading.Thread(target=_startup_worker, daemon=True).start()
    print("SharpLine running on http://localhost:8051")
    app.run(host="0.0.0.0", port=8051, debug=False)
