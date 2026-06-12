"""
sample_data.py - Deterministic sample NFL slate.

Used whenever live sources are unreachable (no API key, offline, offseason).
Lines are generated from the seed power ratings plus per-game "market error"
noise, so the board behaves like a real one: books disagree by half-points,
prices vary, and a handful of games show genuine model-vs-market edges.
"""

import random
from datetime import datetime, timedelta, timezone

import odds_math as om
from model import DEFAULT_RATINGS, HOME_FIELD_ADVANTAGE, win_probability

SAMPLE_BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN BET"]

# A plausible week-1 slate: (away, home, day_offset, hour_utc)
SAMPLE_SLATE = [
    ("KC",  "BUF", 0, 0.5),   # Thursday night marquee
    ("CIN", "CLE", 3, 17),
    ("NE",  "MIA", 3, 17),
    ("PIT", "NYJ", 3, 17),
    ("CAR", "ATL", 3, 17),
    ("JAX", "IND", 3, 17),
    ("MIN", "CHI", 3, 17),
    ("TEN", "HOU", 3, 17),
    ("WAS", "NYG", 3, 17),
    ("SEA", "ARI", 3, 20),
    ("DEN", "LV",  3, 20),
    ("DAL", "PHI", 3, 20),
    ("GB",  "DET", 3, 20),
    ("LAC", "SF",  3, 24.3),  # Sunday night
    ("TB",  "NO",  4, 0.25),  # Monday night
    ("BAL", "LAR", 4, 0.25),
]

_SEED = 20260901


def _next_kickoff_base():
    """Anchor the slate to the upcoming Thursday so dates always look current."""
    now = datetime.now(timezone.utc)
    days_ahead = (3 - now.weekday()) % 7 or 7  # next Thursday
    base = (now + timedelta(days=days_ahead)).replace(hour=0, minute=20, second=0, microsecond=0)
    return base


def build_sample_board():
    rng = random.Random(_SEED)
    base = _next_kickoff_base()
    games = []

    for away, home, day_off, hour in SAMPLE_SLATE:
        true_margin = (
            DEFAULT_RATINGS[home] - DEFAULT_RATINGS[away] + HOME_FIELD_ADVANTAGE
        )
        # Market error: the consensus drifts off the "true" number by up to a
        # couple of points - this is where the sample edges come from.
        market_margin = true_margin + rng.gauss(0, 1.4)
        consensus_line = round(-market_margin * 2) / 2.0
        consensus_total = round((44.5 + rng.gauss(0, 3.0)) * 2) / 2.0
        p_home_market = win_probability(market_margin)

        kickoff = base + timedelta(days=day_off, hours=hour)
        game_id = f"{kickoff:%Y%m%d}-{away}-{home}"

        books = {}
        for book in SAMPLE_BOOKS:
            line = consensus_line + rng.choice([-0.5, 0.0, 0.0, 0.0, 0.5])
            spread_juice = rng.choice([-118, -115, -112, -110, -110, -108, -105])
            other = -220 - spread_juice  # keep the pair summing near standard vig
            p_book = min(max(p_home_market + rng.gauss(0, 0.012), 0.04), 0.96)
            ml_home = om.prob_to_american(min(p_book * 1.024, 0.99))
            ml_away = om.prob_to_american(min((1.0 - p_book) * 1.024, 0.99))
            total = consensus_total + rng.choice([-0.5, 0.0, 0.0, 0.5])
            books[book] = {
                "spread": {"home_line": line, "home_price": spread_juice, "away_price": other},
                "moneyline": {"home": ml_home, "away": ml_away},
                "total": {"line": total, "over": rng.choice([-112, -110, -108]),
                          "under": rng.choice([-112, -110, -108])},
            }

        # Prediction markets quote pure probabilities (their fee shows up in
        # the bid/ask, not the midpoint), so no vig is applied here.
        prediction_markets = {
            "Polymarket": {"home_prob": round(min(max(p_home_market + rng.gauss(0, 0.015), 0.02), 0.98), 3)},
            "Kalshi":     {"home_prob": round(min(max(p_home_market + rng.gauss(0, 0.015), 0.02), 0.98), 3)},
        }

        games.append({
            "id": game_id,
            "kickoff": kickoff.isoformat(),
            "away": away,
            "home": home,
            "books": books,
            "prediction_markets": prediction_markets,
        })

    return games
