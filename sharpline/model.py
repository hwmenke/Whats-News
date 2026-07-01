"""
model.py - Billy Walters-style NFL pricing model.

The approach mirrors how Walters described his operation in "Gambler":

1.  Maintain a POWER RATING for every team on a points scale. The difference
    between two ratings is the expected margin on a neutral field.
2.  Add HOME-FIELD ADVANTAGE and situational adjustments (rest, travel,
    divisional familiarity) to get a predicted spread for the game.
3.  Convert that predicted margin into probabilities using an empirical NFL
    margin-of-victory distribution that respects KEY NUMBERS (3, 7, 6, 10...)
    - the half-point from -2.5 to -3 is worth far more than -7.5 to -8.
4.  Compare the model's number to the de-vigged market. Only bet when the
    edge clears a threshold, and size with capped fractional Kelly.

Ratings are stored in SQLite and fully editable - the model is a tool the
bettor steers, not an oracle.
"""

import math

# -- Teams -------------------------------------------------------------------------

NFL_TEAMS = {
    "ARI": {"name": "Arizona Cardinals",    "div": "NFC West",  "color": "#97233F"},
    "ATL": {"name": "Atlanta Falcons",      "div": "NFC South", "color": "#A71930"},
    "BAL": {"name": "Baltimore Ravens",     "div": "AFC North", "color": "#241773"},
    "BUF": {"name": "Buffalo Bills",        "div": "AFC East",  "color": "#00338D"},
    "CAR": {"name": "Carolina Panthers",    "div": "NFC South", "color": "#0085CA"},
    "CHI": {"name": "Chicago Bears",        "div": "NFC North", "color": "#C83803"},
    "CIN": {"name": "Cincinnati Bengals",   "div": "AFC North", "color": "#FB4F14"},
    "CLE": {"name": "Cleveland Browns",     "div": "AFC North", "color": "#311D00"},
    "DAL": {"name": "Dallas Cowboys",       "div": "NFC East",  "color": "#003594"},
    "DEN": {"name": "Denver Broncos",       "div": "AFC West",  "color": "#FB4F14"},
    "DET": {"name": "Detroit Lions",        "div": "NFC North", "color": "#0076B6"},
    "GB":  {"name": "Green Bay Packers",    "div": "NFC North", "color": "#203731"},
    "HOU": {"name": "Houston Texans",       "div": "AFC South", "color": "#03202F"},
    "IND": {"name": "Indianapolis Colts",   "div": "AFC South", "color": "#002C5F"},
    "JAX": {"name": "Jacksonville Jaguars", "div": "AFC South", "color": "#006778"},
    "KC":  {"name": "Kansas City Chiefs",   "div": "AFC West",  "color": "#E31837"},
    "LAC": {"name": "Los Angeles Chargers", "div": "AFC West",  "color": "#0080C6"},
    "LAR": {"name": "Los Angeles Rams",     "div": "NFC West",  "color": "#003594"},
    "LV":  {"name": "Las Vegas Raiders",    "div": "AFC West",  "color": "#000000"},
    "MIA": {"name": "Miami Dolphins",       "div": "AFC East",  "color": "#008E97"},
    "MIN": {"name": "Minnesota Vikings",    "div": "NFC North", "color": "#4F2683"},
    "NE":  {"name": "New England Patriots", "div": "AFC East",  "color": "#002244"},
    "NO":  {"name": "New Orleans Saints",   "div": "NFC South", "color": "#D3BC8D"},
    "NYG": {"name": "New York Giants",      "div": "NFC East",  "color": "#0B2265"},
    "NYJ": {"name": "New York Jets",        "div": "AFC East",  "color": "#125740"},
    "PHI": {"name": "Philadelphia Eagles",  "div": "NFC East",  "color": "#004C54"},
    "PIT": {"name": "Pittsburgh Steelers",  "div": "AFC North", "color": "#FFB612"},
    "SEA": {"name": "Seattle Seahawks",     "div": "NFC West",  "color": "#002244"},
    "SF":  {"name": "San Francisco 49ers",  "div": "NFC West",  "color": "#AA0000"},
    "TB":  {"name": "Tampa Bay Buccaneers", "div": "NFC South", "color": "#D50A0A"},
    "TEN": {"name": "Tennessee Titans",     "div": "AFC South", "color": "#0C2340"},
    "WAS": {"name": "Washington Commanders","div": "NFC East",  "color": "#5A1414"},
}

# Seed power ratings on a points scale (0 = league average). Edit freely in the
# UI - these are a starting point, not gospel.
DEFAULT_RATINGS = {
    "BUF":  5.5, "KC":   5.0, "BAL":  4.5, "PHI":  4.5, "DET":  4.0,
    "SF":   3.0, "CIN":  2.5, "GB":   2.5, "LAR":  2.0, "HOU":  1.5,
    "LAC":  1.5, "MIN":  1.0, "TB":   1.0, "PIT":  0.5, "MIA":  0.0,
    "SEA":  0.0, "ATL": -0.5, "DAL": -0.5, "WAS": -0.5, "DEN": -1.0,
    "IND": -1.0, "ARI": -1.5, "CHI": -1.5, "NYJ": -2.0, "JAX": -2.5,
    "NO":  -2.5, "LV":  -3.0, "NE":  -3.0, "CLE": -3.5, "NYG": -3.5,
    "CAR": -4.0, "TEN": -4.5,
}

HOME_FIELD_ADVANTAGE = 2.0   # points; league-wide baseline

# Situational adjustments, in points, applied to the side they favour.
ADJ_BYE_WEEK   = 1.0   # team coming off a bye
ADJ_SHORT_WEEK = -1.0  # team on a short week (e.g. Thursday after Sunday)
ADJ_LONG_TRIP  = -0.5  # road team crossing 2+ time zones

# -- Margin distribution -------------------------------------------------------------

# NFL final-margin standard deviation around the spread (empirical ~13.2).
MARGIN_SD = 13.2

# Relative extra mass on key absolute margins, reflecting how often NFL games
# land on these exact numbers (field goals and touchdowns).
KEY_NUMBER_WEIGHTS = {
    3: 1.95, 7: 1.65, 6: 1.30, 10: 1.30, 4: 1.20, 14: 1.20, 1: 1.10, 17: 1.15,
}
MAX_MARGIN = 60


def _margin_pmf(mean):
    """
    Discrete distribution of the home margin of victory: a normal centred on
    `mean`, re-weighted at key numbers and renormalised. Margin 0 (tie) keeps
    only a sliver of mass since overtime makes ties rare.
    """
    pmf = {}
    for m in range(-MAX_MARGIN, MAX_MARGIN + 1):
        z = (m - mean) / MARGIN_SD
        w = math.exp(-0.5 * z * z)
        if m == 0:
            w *= 0.05
        else:
            w *= KEY_NUMBER_WEIGHTS.get(abs(m), 1.0)
        pmf[m] = w
    total = sum(pmf.values())
    return {m: w / total for m, w in pmf.items()}


def win_probability(pred_margin):
    """P(home team wins) given the model's predicted home margin."""
    pmf = _margin_pmf(pred_margin)
    p_win = sum(p for m, p in pmf.items() if m > 0)
    p_tie = pmf.get(0, 0.0)
    return p_win + 0.5 * p_tie


def cover_probability(pred_margin, home_line):
    """
    P(home covers) for a quoted home line (e.g. -2.5 means home laying 2.5).
    Returns (p_cover, p_push). Home covers when margin + line > 0.
    """
    pmf = _margin_pmf(pred_margin)
    p_cover = p_push = 0.0
    for m, p in pmf.items():
        edge = m + home_line
        if edge > 1e-9:
            p_cover += p
        elif abs(edge) <= 1e-9:
            p_push += p
    return p_cover, p_push


# -- Game pricing -----------------------------------------------------------------

def predict_game(home, away, ratings, hfa=HOME_FIELD_ADVANTAGE, situational=None):
    """
    Price a game. `situational` is an optional dict of point adjustments,
    positive = favours home: {"home_bye": True, "away_short_week": True, ...}
    Returns the model's number for the game.
    """
    s = situational or {}
    adj = 0.0
    if s.get("home_bye"):        adj += ADJ_BYE_WEEK
    if s.get("away_bye"):        adj -= ADJ_BYE_WEEK
    if s.get("home_short_week"): adj += ADJ_SHORT_WEEK
    if s.get("away_short_week"): adj -= ADJ_SHORT_WEEK
    if s.get("away_long_trip"):  adj -= ADJ_LONG_TRIP  # hurts away => helps home
    adj += float(s.get("extra", 0.0))  # manual override (injuries, weather, QB)

    margin = ratings.get(home, 0.0) - ratings.get(away, 0.0) + hfa + adj
    p_home = win_probability(margin)
    return {
        "home": home,
        "away": away,
        "pred_margin": round(margin, 2),
        "model_spread_home": round(-margin * 2) / 2.0,  # quoted to half-points
        "home_win_prob": round(p_home, 4),
        "away_win_prob": round(1.0 - p_home, 4),
        "adjustments": round(adj, 2),
    }
