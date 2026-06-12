"""
edges.py - Compare the model's numbers to the market and surface plays.

For every game:
  * compute the market consensus (median line, de-vigged win prob across
    books AND prediction markets)
  * price the game with the power-rating model
  * for each side of the spread and moneyline at every book, compute the
    model's edge in probability terms and EV; keep the best price per side
  * flag plays whose edge clears the configured threshold, with a capped
    fractional-Kelly stake suggestion
"""

import statistics

import odds_math as om
from model import predict_game, cover_probability


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def market_consensus(game):
    """De-vigged consensus across sportsbooks and prediction markets."""
    lines, totals, home_probs = [], [], []
    for quote in game.get("books", {}).values():
        if "spread" in quote:
            lines.append(quote["spread"]["home_line"])
        if "total" in quote:
            totals.append(quote["total"]["line"])
        if "moneyline" in quote:
            p_h = om.american_to_prob(quote["moneyline"]["home"])
            p_a = om.american_to_prob(quote["moneyline"]["away"])
            q_h, _ = om.devig_power(p_h, p_a)
            home_probs.append(q_h)
    for quote in game.get("prediction_markets", {}).values():
        if quote.get("home_prob") is not None:
            home_probs.append(quote["home_prob"])
    return {
        "home_line": _median(lines),
        "total": _median(totals),
        "home_prob": round(_median(home_probs), 4) if home_probs else None,
    }


def best_price(game, market, side):
    """Best available price for one side across all books. Returns (book, quote)."""
    best, best_book = None, None
    for book, quote in game.get("books", {}).items():
        q = quote.get(market)
        if not q:
            continue
        if market == "moneyline":
            price, line = q[side], None
        else:  # spread
            if side == "home":
                price, line = q["home_price"], q["home_line"]
            else:
                price, line = q["away_price"], -q["home_line"]
        # prefer better line first (more points), then better price
        key = (line if line is not None else 0, om.american_to_decimal(price))
        if best is None or key > best:
            best = key
            best_book = (book, {"price": price, "line": line})
    return best_book


def analyse_game(game, ratings, settings):
    pred = predict_game(game["home"], game["away"], ratings, hfa=settings["hfa"])
    consensus = market_consensus(game)
    plays = []

    # -- Spread: evaluate both sides at their best available number ----------------
    for side in ("home", "away"):
        bp = best_price(game, "spread", side)
        if not bp:
            continue
        book, q = bp
        home_line = q["line"] if side == "home" else -q["line"]
        p_cover, p_push = cover_probability(pred["pred_margin"], home_line)
        p_side = p_cover if side == "home" else 1.0 - p_cover - p_push
        p_win_given_no_push = p_side / (1.0 - p_push) if p_push < 1 else 0.0
        ev = om.expected_value(p_win_given_no_push, q["price"]) * (1.0 - p_push)
        plays.append({
            "market": "spread",
            "side": side,
            "team": game[side],
            "book": book,
            "line": q["line"],
            "price": q["price"],
            "model_prob": round(p_win_given_no_push, 4),
            "edge": round(p_win_given_no_push - om.american_to_prob(q["price"]), 4),
            "ev_per_dollar": round(ev, 4),
        })

    # -- Moneyline ------------------------------------------------------------------
    for side in ("home", "away"):
        bp = best_price(game, "moneyline", side)
        if not bp:
            continue
        book, q = bp
        p_model = pred["home_win_prob"] if side == "home" else pred["away_win_prob"]
        plays.append({
            "market": "moneyline",
            "side": side,
            "team": game[side],
            "book": book,
            "line": None,
            "price": q["price"],
            "model_prob": round(p_model, 4),
            "edge": round(p_model - om.american_to_prob(q["price"]), 4),
            "ev_per_dollar": round(om.expected_value(p_model, q["price"]), 4),
        })

    # -- Stake suggestions for qualifying plays ---------------------------------------
    threshold = settings["edge_threshold"]
    bankroll = settings["bankroll"]
    for p in plays:
        p["play"] = p["edge"] >= threshold and p["ev_per_dollar"] > 0
        p["stars"] = min(5, int(p["edge"] / threshold)) if p["play"] else 0
        p["stake"] = (
            om.kelly_stake(bankroll, p["model_prob"], p["price"],
                           fraction=settings["kelly_fraction"],
                           cap=settings["max_bet_pct"])
            if p["play"] else 0.0
        )

    return {
        "game_id": game["id"],
        "kickoff": game["kickoff"],
        "away": game["away"],
        "home": game["home"],
        "model": pred,
        "consensus": consensus,
        "line_value": (
            round(pred["model_spread_home"] - consensus["home_line"], 2)
            if consensus["home_line"] is not None else None
        ),
        "plays": sorted(plays, key=lambda p: -p["edge"]),
    }


def analyse_board(board, ratings, settings):
    games = [analyse_game(g, ratings, settings) for g in board["games"]]
    picks = [
        {**p, "game_id": g["game_id"], "kickoff": g["kickoff"],
         "matchup": f"{g['away']} @ {g['home']}"}
        for g in games for p in g["plays"] if p["play"]
    ]
    picks.sort(key=lambda p: -p["edge"])
    return {"as_of": board["as_of"], "source": board["source"],
            "games": games, "picks": picks}
