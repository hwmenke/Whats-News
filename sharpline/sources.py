"""
sources.py - Seamless odds ingestion: live where possible, graceful everywhere.

Sportsbook lines, in priority order:
  1. The Odds API (https://the-odds-api.com) - lines across all major US books.
     Free tier: 500 requests/month. Paste your key in Settings (or set
     ODDS_API_KEY in the environment).
  2. ESPN's public scoreboard API - no key at all; carries ESPN BET's spread,
     total and moneylines for every game of the current week.
  3. Model-generated lines on the REAL upcoming schedule (from nflverse).
  4. A built-in fictional slate (only if the schedule has never been fetched).

Prediction markets (Polymarket, Kalshi) are layered on top whenever reachable -
both are public, keyless APIs.

Every response carries a "sources" dict so the UI can show exactly where each
piece of data came from.
"""

import os
import re
import time

import requests

import ratings as ratings_mod
from model import NFL_TEAMS
from sample_data import build_board_from_slate, build_sample_board

ODDS_API_URL = (
    "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
    "?regions=us&markets=h2h,spreads,totals&oddsFormat=american&apiKey={key}"
)
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
POLYMARKET_URL = "https://gamma-api.polymarket.com/events?tag_slug=nfl&closed=false&limit=100"
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXNFLGAME&status=open&limit=200"

TIMEOUT = 12

# Map full team names (as the APIs return them) to our abbreviations.
NAME_TO_ABBR = {info["name"].lower(): abbr for abbr, info in NFL_TEAMS.items()}
for abbr, info in list(NFL_TEAMS.items()):
    parts = info["name"].rsplit(" ", 1)
    NAME_TO_ABBR[parts[-1].lower()] = abbr   # nickname ("Chiefs")
    NAME_TO_ABBR[parts[0].lower()] = abbr    # city ("Kansas City")


def team_abbr(name):
    if not name:
        return None
    key = name.strip().lower()
    if key.upper() in NFL_TEAMS:
        return key.upper()
    if key in NAME_TO_ABBR:
        return NAME_TO_ABBR[key]
    last = key.rsplit(" ", 1)[-1]
    return NAME_TO_ABBR.get(last)


# -- The Odds API -------------------------------------------------------------------

def fetch_odds_api(api_key):
    """Returns a list of normalised games, or None on any failure."""
    if not api_key:
        return None
    try:
        resp = requests.get(ODDS_API_URL.format(key=api_key), timeout=TIMEOUT)
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


# -- ESPN (keyless) ------------------------------------------------------------------

def fetch_espn():
    """ESPN BET lines from the public scoreboard - zero configuration."""
    try:
        resp = requests.get(ESPN_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception:
        return None

    games = []
    for ev in events:
        try:
            comp = ev["competitions"][0]
            if comp.get("status", {}).get("type", {}).get("completed"):
                continue
            home = away = None
            for c in comp.get("competitors", []):
                abbr = team_abbr(c.get("team", {}).get("abbreviation")
                                 or c.get("team", {}).get("displayName"))
                if c.get("homeAway") == "home":
                    home = abbr
                else:
                    away = abbr
            if not home or not away:
                continue
            odds_list = comp.get("odds") or []
            if not odds_list:
                continue
            o = odds_list[0]
            book = (o.get("provider") or {}).get("name") or "ESPN BET"
            entry = {}

            # Spread: parse "BUF -2.5" so we know which side is favoured.
            details = o.get("details") or ""
            m = re.match(r"([A-Z]{2,4})\s*([+-]?\d+(?:\.\d+)?)", details)
            if m:
                fav, line = team_abbr(m.group(1)), float(m.group(2))
                if fav in (home, away):
                    home_line = line if fav == home else -line
                    hto, ato = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
                    entry["spread"] = {
                        "home_line": home_line,
                        "home_price": int(hto.get("spreadOdds") or -110),
                        "away_price": int(ato.get("spreadOdds") or -110),
                    }

            hto, ato = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
            if hto.get("moneyLine") and ato.get("moneyLine"):
                entry["moneyline"] = {"home": int(hto["moneyLine"]),
                                      "away": int(ato["moneyLine"])}
            if o.get("overUnder"):
                entry["total"] = {
                    "line": float(o["overUnder"]),
                    "over": int(o.get("overOdds") or -110),
                    "under": int(o.get("underOdds") or -110),
                }
            if not entry:
                continue

            kick = ev.get("date", "")
            games.append({
                "id": f"{kick[:10].replace('-', '')}-{away}-{home}",
                "kickoff": kick,
                "away": away,
                "home": home,
                "books": {book: entry},
                "prediction_markets": {},
            })
        except Exception:
            continue
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
CACHE_TTL = 120  # seconds; respects The Odds API's monthly quota


def get_board(force_refresh=False, api_key=None, ratings=None, hfa=2.0):
    """
    The unified odds board. Tries every live source, falls back to pricing
    the real schedule with the model, and tags where each layer came from.
    """
    now = time.time()
    if not force_refresh and _cache["board"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["board"]

    api_key = api_key or os.environ.get("ODDS_API_KEY", "")
    src = {"sportsbooks": None, "polymarket": False, "kalshi": False,
           "schedule": "live"}

    games = fetch_odds_api(api_key)
    if games:
        src["sportsbooks"] = "the-odds-api"
    else:
        games = fetch_espn()
        if games:
            src["sportsbooks"] = "espn"

    nfl_games = ratings_mod.fetch_games()

    if games:
        live = True
        poly, kalshi = fetch_polymarket(), fetch_kalshi()
        src["polymarket"], src["kalshi"] = bool(poly), bool(kalshi)
        for g in games:
            key = (g["away"], g["home"])
            pm = {}
            if key in poly:
                pm["Polymarket"] = {"home_prob": round(poly[key], 3)}
            if key in kalshi:
                pm["Kalshi"] = {"home_prob": round(kalshi[key], 3)}
            g["prediction_markets"] = pm
    else:
        live = False
        from model import DEFAULT_RATINGS
        ratings = ratings or DEFAULT_RATINGS
        slate = ratings_mod.upcoming_slate(nfl_games) if nfl_games else None
        if slate:
            games = build_board_from_slate(slate, ratings, hfa=hfa)
            src["sportsbooks"] = "model"
            src["schedule"] = "nflverse"
        else:
            games = build_sample_board()
            src["sportsbooks"] = "sample"
            src["schedule"] = "builtin"

    # Rest-day situational flags from the real schedule, whatever the source.
    if nfl_games:
        situ = ratings_mod.situational_lookup(nfl_games)
        for g in games:
            g.setdefault("situational", situ.get((g["away"], g["home"]), {}))

    board = {
        "as_of": now,
        "source": "live" if live else "sample",
        "sources": src,
        "games": games,
    }
    _cache.update(board=board, ts=now)
    return board
