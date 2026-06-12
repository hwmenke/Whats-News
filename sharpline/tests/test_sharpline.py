"""Unit tests for SharpLine's odds math, model, and edge engine."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import odds_math as om
from model import (
    DEFAULT_RATINGS, NFL_TEAMS, cover_probability, predict_game, win_probability,
)
from sample_data import build_sample_board
from edges import analyse_board, market_consensus


# -- odds_math ----------------------------------------------------------------------

def test_american_decimal_roundtrip():
    for odds in (-110, -200, +150, +100, -105, +320):
        dec = om.american_to_decimal(odds)
        assert om.decimal_to_american(dec) == odds


def test_implied_prob():
    assert om.american_to_prob(-110) == pytest.approx(110 / 210)
    assert om.american_to_prob(+100) == pytest.approx(0.5)
    assert om.american_to_prob(+150) == pytest.approx(0.4)


def test_prob_to_american_roundtrip():
    for p in (0.25, 0.4, 0.5, 0.6, 0.75):
        assert om.american_to_prob(om.prob_to_american(p)) == pytest.approx(p, abs=0.01)


def test_devig_sums_to_one():
    p1, p2 = om.american_to_prob(-150), om.american_to_prob(+130)
    for fn in (om.devig_multiplicative, om.devig_power):
        q1, q2 = fn(p1, p2)
        assert q1 + q2 == pytest.approx(1.0)
        assert q1 > q2  # favourite stays the favourite


def test_devig_power_shades_longshot():
    # Power method assigns more of the vig to the longshot (favourite-longshot
    # bias), so the favourite's fair prob comes out HIGHER than multiplicative.
    p1, p2 = om.american_to_prob(-300), om.american_to_prob(+240)
    m1, _ = om.devig_multiplicative(p1, p2)
    w1, _ = om.devig_power(p1, p2)
    assert w1 > m1


def test_kelly():
    # 55% at -110 is a classic positive-EV spot
    f = om.kelly_fraction(0.55, -110)
    assert 0.0 < f < 0.1
    # no edge -> no bet
    assert om.kelly_fraction(0.50, -110) == 0.0
    # stake respects the hard cap
    stake = om.kelly_stake(10000, 0.80, +200, fraction=1.0, cap=0.03)
    assert stake == 300.0


def test_expected_value_sign():
    assert om.expected_value(0.55, -110) > 0
    assert om.expected_value(0.50, -110) < 0


# -- model ------------------------------------------------------------------------

def test_win_probability_monotone():
    probs = [win_probability(m) for m in (-10, -3, 0, 3, 10)]
    assert probs == sorted(probs)
    assert win_probability(0) == pytest.approx(0.5, abs=0.02)
    assert win_probability(14) > 0.80


def test_key_number_three_is_worth_more():
    # Moving the line across 3 should swing cover prob more than across 8.
    pred = 0.0
    across_three = cover_probability(pred, -2.5)[0] - cover_probability(pred, -3.5)[0]
    across_eight = cover_probability(pred, -7.5)[0] - cover_probability(pred, -8.5)[0]
    assert across_three > across_eight


def test_cover_prob_push():
    p_cover, p_push = cover_probability(3.0, -3.0)
    assert p_push > 0.02  # landing exactly on 3 happens often
    assert p_cover + p_push < 1.0


def test_predict_game():
    pred = predict_game("BUF", "TEN", DEFAULT_RATINGS)
    assert pred["pred_margin"] > 7  # big favourite at home
    assert pred["home_win_prob"] > 0.7
    assert pred["home_win_prob"] + pred["away_win_prob"] == pytest.approx(1.0)


def test_all_teams_have_ratings_and_colors():
    assert set(DEFAULT_RATINGS) == set(NFL_TEAMS)
    for info in NFL_TEAMS.values():
        assert info["color"].startswith("#")


# -- ratings engine -----------------------------------------------------------------

def _synthetic_games():
    # Team A beats everyone by 10 at home and away; B and C split evenly.
    rows = []
    for season in ("2024", "2025"):
        for wk, (away, home, result) in enumerate([
            ("B", "A", 10), ("C", "A", 10), ("A", "B", -10), ("A", "C", -10),
            ("B", "C", 0), ("C", "B", 3),
        ], start=1):
            rows.append({
                "season": season, "week": str(wk), "game_type": "REG",
                "gameday": f"{season}-10-{wk:02d}", "gametime": "13:00",
                "away_team": away, "home_team": home, "result": str(result),
                "location": "Home",
            })
    return rows


def test_elo_ratings_order_and_scale():
    from ratings import compute_elo_ratings
    ratings, meta = compute_elo_ratings(_synthetic_games())
    assert ratings["A"] > ratings["B"]
    assert ratings["A"] > ratings["C"]
    assert ratings["A"] > 0 > min(ratings["B"], ratings["C"])
    assert meta["games_used"] == 12
    assert meta["through_season"] == 2025


def test_elo_regresses_into_new_season():
    from ratings import compute_elo_ratings
    games = _synthetic_games()
    # add an unplayed 2026 game: ratings should be regressed toward zero
    games.append({"season": "2026", "week": "1", "game_type": "REG",
                  "gameday": "2026-09-13", "gametime": "13:00",
                  "away_team": "B", "home_team": "A", "result": "",
                  "location": "Home"})
    with_next, _ = compute_elo_ratings(games)
    without_next, _ = compute_elo_ratings(_synthetic_games())
    assert abs(with_next["A"]) < abs(without_next["A"])


def test_upcoming_slate_situational_flags():
    from ratings import upcoming_slate
    games = [{
        "season": "2099", "week": "5", "game_type": "REG",
        "gameday": "2099-10-11", "gametime": "13:00",
        "away_team": "B", "home_team": "A", "result": "",
        "away_rest": "14", "home_rest": "4", "location": "Home",
    }]
    slate = upcoming_slate(games)
    assert slate and slate[0]["situational"]["away_bye"]
    assert slate[0]["situational"]["home_short_week"]
    assert slate[0]["id"] == "20991011-B-A"


# -- sample board & edges --------------------------------------------------------------

def test_sample_board_shape():
    games = build_sample_board()
    assert len(games) >= 12
    g = games[0]
    assert {"id", "kickoff", "away", "home", "books", "prediction_markets"} <= set(g)
    for q in g["books"].values():
        assert {"spread", "moneyline", "total"} <= set(q)
    assert "Polymarket" in g["prediction_markets"]


def test_sample_board_deterministic():
    b1, b2 = build_sample_board(), build_sample_board()
    assert b1[0]["books"] == b2[0]["books"]


def test_market_consensus_devig():
    g = build_sample_board()[0]
    cons = market_consensus(g)
    assert cons["home_line"] is not None
    assert 0.0 < cons["home_prob"] < 1.0


def test_analyse_board_produces_picks():
    board = {"as_of": 0.0, "source": "sample", "games": build_sample_board()}
    settings = {"bankroll": 10000, "kelly_fraction": 0.25, "max_bet_pct": 0.03,
                "edge_threshold": 0.02, "hfa": 2.0}
    out = analyse_board(board, DEFAULT_RATINGS, settings)
    assert len(out["games"]) == len(board["games"])
    # sample data plants market error, so at least one edge should surface
    assert len(out["picks"]) >= 1
    for p in out["picks"]:
        assert p["edge"] >= settings["edge_threshold"]
        assert 0 < p["stake"] <= settings["bankroll"] * settings["max_bet_pct"] + 0.01
