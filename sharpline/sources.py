"""
sources.py - Live odds ingestion with graceful fallback.

Sources, in order of preference:
  1. The Odds API (https://the-odds-api.com) - sportsbook lines across US books.
     Free tier: 500 requests/month. Set ODDS_API_KEY in the environment.
  2. Polymarket Gamma API - public, no key. NFL winner markets.
  3. Kalshi public API - no key needed for market data. NFL game markets.

If nothing is reachable (offline, offseason, no key) the bundled sample slate
is served instead, and the response is tagged "source": "sample" so the UI can
say so honestly.
"""

import os
import re
import time

import requests

from model import NFL_TEAMS
from sample_data import build_sample_board

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_URL = (
    "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
    "?regions=us&markets=h2h,spreads,totals&oddsFormat=american&apiKey={key}"
)
POLYMARKET_URL = "https://gamma-api.polymarket.com/events?tag_slug=nfl&closed=false&limit=100"
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXNFLGAME&status=open&limit=200"

TIMEOUT = 12

# Map full team names (as the APIs return them) to our abbreviations.
NAME_TO_ABBR = {info["name"].lower(): abbr for abbr, info in NFL_TEAMS.items()}
# Also accept city-less nicknames ("Chiefs") and city names ("Kansas City").
for abbr, info in list(NFL_TEAMS.items()):
    parts = info["name"].rsplit(" ", 1)
    NAME_TO_ABBR[parts[-1].lower()] = abbr
    NAME_TO_ABBR[parts[0].lower()] = abbr


def team_abbr(name):
    if not name:
        return None
    key = name.strip().lower()
    if key.upper() in NFL_TEAMS:
        return key.upper()
    if key in NAME_TO_ABBR:
        return NAME_TO_ABBR[key]
    # last word usually carries the nickname
    last = key.rsplit(" ", 1)[-1]
    return NAME_TO_ABBR.get(last)


# -- The Odds API -------------------------------------------------------------------

def fetch_sportsbook_odds():
    """Returns a list of normalised games, or None on any failure."""
    if not ODDS_API_KEY:
        return None
    try:
        resp = requests.get(ODDS_API_URL.format(key=ODDS_API_KEY), timeout=TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None

    games = []
    for ev in raw:
        home = team_abbr(ev.get("home_team"))
        away = team_abbr(ev.get("away_team"))
        if not home or not away:
            continue
        kick = ev.get("commence_time", "")
        game = {
            "id": f"{kick[:10].replace('-', '')}-{away}-{home}",
            "kickoff": kick,
            "away": away,
            "home": home,
            "books": {},
            "prediction_markets": {},
        }
        for bm in ev.get("bookmakers", []):
            book = bm.get("title", bm.get("key", "?"))
            entry = {}
            for mkt in bm.get("markets", []):
                outcomes = {team_abbr(o.get("name")) or o.get("name"): o
                            for o in mkt.get("outcomes", [])}
                if mkt["key"] == "h2h" and home in outcomes and away in outcomes:
                    entry["moneyline"] = {
                        "home": int(outcomes[home]["price"]),
                        "away": int(outcomes[away]["price"]),
                    }
                elif mkt["key"] == "spreads" and home in outcomes and away in outcomes:
                    entry["spread"] = {
                        "home_line": float(outcomes[home].get("point", 0)),
                        "home_price": int(outcomes[home]["price"]),
                        "away_price": int(outcomes[away]["price"]),
                    }
                elif mkt["key"] == "totals":
                    over = next((o for o in mkt.get("outcomes", []) if o.get("name") == "Over"), None)
                    under = next((o for o in mkt.get("outcomes", []) if o.get("name") == "Under"), None)
                    if over and under:
                        entry["total"] = {
                            "line": float(over.get("point", 0)),
                            "over": int(over["price"]),
                            "under": int(under["price"]),
                        }
            if entry:
                game["books"][book] = entry
        if game["books"]:
            games.append(game)
    return games or None


# -- Polymarket --------------------------------------------------------------------

def fetch_polymarket():
    """Returns {(away, home): home_prob} best-effort, or {} on failure."""
    out = {}
    try:
        resp = requests.get(POLYMARKET_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        events = resp.json()
    except Exception:
        return out

    for ev in events if isinstance(events, list) else []:
        title = ev.get("title", "")
        m = re.match(r"(.+?)\s+(?:vs\.?|@|at)\s+(.+)", title, re.IGNORECASE)
        if not m:
            continue
        t1, t2 = team_abbr(m.group(1)), team_abbr(m.group(2))
        if not t1 or not t2:
            continue
        for mkt in ev.get("markets", []):
            outcome = team_abbr(mkt.get("groupItemTitle", ""))
            prices = mkt.get("outcomePrices")
            if isinstance(prices, str):
                try:
                    import json as _json
                    prices = _json.loads(prices)
                except Exception:
                    prices = None
            if outcome and prices:
                try:
                    prob = float(prices[0])
                except (ValueError, IndexError, TypeError):
                    continue
                # "T1 vs T2" / "T1 @ T2": treat the second team as home
                if outcome == t2:
                    out[(t1, t2)] = prob
                elif outcome == t1:
                    out[(t1, t2)] = 1.0 - prob
    return out


# -- Kalshi -----------------------------------------------------------------------

def fetch_kalshi():
    """Returns {(away, home): home_prob} best-effort, or {} on failure."""
    out = {}
    try:
        resp = requests.get(KALSHI_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        markets = resp.json().get("markets", [])
    except Exception:
        return out

    for mkt in markets:
        title = mkt.get("title", "")
        m = re.search(r"(.+?)\s+(?:vs\.?|@|at)\s+(.+?)(?:\?|$|:)", title, re.IGNORECASE)
        if not m:
            continue
        t1, t2 = team_abbr(m.group(1)), team_abbr(m.group(2))
        yes_team = team_abbr(mkt.get("yes_sub_title", "")) or t1
        bid, ask = mkt.get("yes_bid"), mkt.get("yes_ask")
        if not t1 or not t2 or bid is None or ask is None or ask == 0:
            continue
        mid = (bid + ask) / 200.0  # cents -> probability
        if yes_team == t2:
            out[(t1, t2)] = mid
        else:
            out[(t1, t2)] = 1.0 - mid
    return out


# -- Orchestration ------------------------------------------------------------------

_cache = {"board": None, "ts": 0.0}
CACHE_TTL = 120  # seconds; respect The Odds API's monthly quota


def get_board(force_refresh=False):
    """Build the unified odds board: sportsbooks + prediction markets."""
    now = time.time()
    if not force_refresh and _cache["board"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["board"]

    games = fetch_sportsbook_odds()
    source = "live" if games else "sample"
    if games is None:
        games = build_sample_board()
        # sample board already includes synthetic prediction-market quotes
    else:
        poly, kalshi = fetch_polymarket(), fetch_kalshi()
        for g in games:
            key = (g["away"], g["home"])
            pm = {}
            if key in poly:
                pm["Polymarket"] = {"home_prob": round(poly[key], 3)}
            if key in kalshi:
                pm["Kalshi"] = {"home_prob": round(kalshi[key], 3)}
            g["prediction_markets"] = pm

    board = {"as_of": now, "source": source, "games": games}
    _cache.update(board=board, ts=now)
    return board
