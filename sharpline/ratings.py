"""
ratings.py - Data-driven power ratings and the real NFL schedule, via nflverse.

nflverse (https://github.com/nflverse/nfldata) publishes every NFL game since
1999 - scores, schedule, rest days - as a plain CSV on GitHub, no key needed.

From it we derive:
  * ELO-BASED POWER RATINGS: margin-of-victory weighted Elo (538-style MOV
    multiplier), regressed one-third to the mean at every season boundary,
    converted to a points scale (25 Elo ~ 1 point).
  * THE UPCOMING SLATE: the next week of real games, with rest-day situational
    flags (bye = 13+ days, short week = 5 or fewer) feeding the model's
    Walters-style adjustments automatically.

The CSV is cached on disk so everything keeps working offline after one
successful fetch.
"""

import csv
import io
import os
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    EASTERN = None

import requests

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "games.csv")
CACHE_TTL = 6 * 3600  # refetch at most every 6 hours

# nflverse team codes that differ from ours
CODE_MAP = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}

# Elo parameters (FiveThirtyEight-style)
ELO_START = 1500.0
ELO_K = 20.0
ELO_HFA = 48.0           # home-field advantage in Elo points
SEASON_REGRESS = 1 / 3   # pull toward the mean at each season boundary
ELO_PER_POINT = 25.0     # 25 Elo points ~ 1 point of NFL margin


def _code(team):
    return CODE_MAP.get(team, team)


# -- Data fetch ---------------------------------------------------------------------

def fetch_games(force=False):
    """Return parsed games.csv rows, using the disk cache when fresh or offline."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    fresh = (
        os.path.exists(CACHE_FILE)
        and time.time() - os.path.getmtime(CACHE_FILE) < CACHE_TTL
    )
    if force or not fresh:
        try:
            resp = requests.get(GAMES_URL, timeout=30)
            resp.raise_for_status()
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(resp.text)
        except Exception:
            pass  # fall through to whatever cache exists
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(io.StringIO(f.read())))


# -- Elo power ratings ----------------------------------------------------------------

def _mov_multiplier(margin, elo_diff_winner):
    """538's margin-of-victory multiplier: blowouts count more, but less so
    when the favourite was expected to roll anyway."""
    import math
    return math.log(abs(margin) + 1.0) * (2.2 / (elo_diff_winner * 0.001 + 2.2))


def compute_elo_ratings(games):
    """
    Run margin-weighted Elo over every completed game, oldest first, regressing
    one-third to the mean at each season boundary (including into an upcoming
    season that has no results yet). Returns (ratings_points, meta).
    """
    import math

    completed = [g for g in games if g.get("result") not in (None, "", "NA")]
    completed.sort(key=lambda g: (g["season"], g["gameday"], g["gametime"] or ""))
    if not completed:
        return None, None

    elo = {}
    season = None
    max_season = max(int(g["season"]) for g in games if g.get("season"))

    for g in completed:
        if g["season"] != season:
            season = g["season"]
            for t in elo:
                elo[t] = ELO_START + (elo[t] - ELO_START) * (1 - SEASON_REGRESS)
        home, away = _code(g["home_team"]), _code(g["away_team"])
        result = float(g["result"])  # home score - away score
        e_h, e_a = elo.setdefault(home, ELO_START), elo.setdefault(away, ELO_START)
        hfa = ELO_HFA if g.get("location", "Home") == "Home" else 0.0

        exp_home = 1.0 / (1.0 + 10.0 ** (-((e_h + hfa) - e_a) / 400.0))
        actual = 1.0 if result > 0 else 0.0 if result < 0 else 0.5
        if result > 0:
            mult = _mov_multiplier(result, (e_h + hfa) - e_a)
        elif result < 0:
            mult = _mov_multiplier(result, e_a - (e_h + hfa))
        else:
            mult = 1.0
        delta = ELO_K * mult * (actual - exp_home)
        elo[home] = e_h + delta
        elo[away] = e_a - delta

    last_season = int(completed[-1]["season"])
    if max_season > last_season:
        # Preseason of a new year: regress once more before any kickoff.
        for t in elo:
            elo[t] = ELO_START + (elo[t] - ELO_START) * (1 - SEASON_REGRESS)

    ratings = {t: round((e - ELO_START) / ELO_PER_POINT, 2) for t, e in elo.items()}
    meta = {
        "method": "nflverse Elo (MOV-weighted, 1/3 season regression)",
        "through_season": last_season,
        "games_used": len(completed),
        "synced_at": time.time(),
    }
    return ratings, meta


# -- Upcoming slate -------------------------------------------------------------------

def _kickoff_iso(gameday, gametime):
    """nflverse times are US/Eastern; emit a timezone-aware ISO string."""
    t = gametime or "13:00"
    dt = datetime.strptime(f"{gameday} {t}", "%Y-%m-%d %H:%M")
    if EASTERN is not None:
        dt = dt.replace(tzinfo=EASTERN)
    return dt.isoformat()


def upcoming_slate(games, now=None):
    """
    The next week of real, unplayed games: list of dicts with id, kickoff,
    away, home, and situational rest flags for the model. None if the
    schedule has nothing left (or data is unavailable).
    """
    if not games:
        return None
    now = now or datetime.now(EASTERN) if EASTERN else datetime.now()
    today = now.strftime("%Y-%m-%d")

    unplayed = [
        g for g in games
        if g.get("result") in (None, "", "NA")
        and g.get("gameday", "") >= today
        and g.get("game_type") in ("REG", "POST", "WC", "DIV", "CON", "SB")
    ]
    if not unplayed:
        return None
    unplayed.sort(key=lambda g: (g["season"], int(g["week"]), g["gameday"]))
    season, week = unplayed[0]["season"], unplayed[0]["week"]
    slate = []
    for g in unplayed:
        if g["season"] != season or g["week"] != week:
            break
        away, home = _code(g["away_team"]), _code(g["home_team"])
        away_rest = int(g["away_rest"] or 7)
        home_rest = int(g["home_rest"] or 7)
        slate.append({
            "id": f"{g['gameday'].replace('-', '')}-{away}-{home}",
            "kickoff": _kickoff_iso(g["gameday"], g["gametime"]),
            "away": away,
            "home": home,
            "week": int(week),
            "season": int(season),
            "situational": {
                "home_bye": home_rest >= 13,
                "away_bye": away_rest >= 13,
                "home_short_week": home_rest <= 5,
                "away_short_week": away_rest <= 5,
            },
        })
    return slate or None


def situational_lookup(games):
    """Map (away, home) -> situational flags for the next few weeks, so rest
    adjustments apply even when the slate comes from a live odds feed."""
    out = {}
    for g in upcoming_slate(games) or []:
        out[(g["away"], g["home"])] = g["situational"]
    return out
