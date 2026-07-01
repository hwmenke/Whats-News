# 🏈 SharpLine — NFL odds, prediction markets & a Walters-style model

A FiveThirtyEight-style dashboard that puts **every NFL price in one place** —
sportsbook spreads/moneylines/totals, **Polymarket** and **Kalshi** win
probabilities — and compares them against a **Billy Walters-inspired power-rating
model** so you can see exactly where you have a number the market doesn't.

## Quick start

```bash
cd sharpline
python3 -m pip install -r requirements.txt
python3 app.py
```

Open **http://localhost:8051**.

**Zero configuration needed.** On first start the app:

1. **Syncs power ratings automatically** from [nflverse](https://github.com/nflverse/nfldata)
   game data (every NFL result since 1999) — margin-weighted Elo, regressed ⅓
   to the mean each season, converted to a points scale.
2. **Pulls live lines keylessly** from ESPN's public scoreboard API (ESPN BET
   spread/ML/total) during the season, plus **Polymarket** and **Kalshi** win
   probabilities — no keys for any of these.
3. Falls back to pricing the **real upcoming schedule** with the model when no
   odds feed is reachable (offseason/offline), so the UI always works. Source
   chips in the masthead show exactly where every layer of data came from.
4. Re-snapshots the board every 10 minutes in the background, building
   line-movement history automatically.

For multi-book line shopping (DraftKings, FanDuel, BetMGM, Caesars…), paste a
free [The Odds API](https://the-odds-api.com) key (500 req/mo) into
**Bet Tracker → Settings** — no restart needed. `ODDS_API_KEY` env var works too.

## What's inside

| Tab | What it does |
|---|---|
| **Odds Board** | Every game × every book, best price per column highlighted, prediction-market probabilities, de-vigged consensus, model line, win-probability bars, line-movement history |
| **Edges & Picks** | Ranked plays where the model beats the break-even price, with star ratings, EV per $1, and capped fractional-Kelly stakes |
| **Power Ratings** | Fully editable team ratings (points vs. average) — save and the whole board reprices |
| **Bet Tracker** | Log bets, settle W/L/push, record closing prices, and track **CLV** — the metric Walters actually graded himself on |
| **Methodology** | The model, explained |

## The model (the Walters playbook)

1. **Power ratings** — each team rated in points vs. league average; the
   difference is the neutral-field margin. Auto-computed from nflverse data
   (Elo), re-syncable with one click, and still fully editable by hand.
   Rest-day situations (byes, short weeks) flow in from the real schedule
   automatically.
2. **Home field + situations** — configurable HFA, bye-week rest edges,
   short-week penalties, long road trips.
3. **Key numbers** — margins are priced with a distribution re-weighted at
   3, 7, 6, 10…, so the half-point from −2.5 to −3 is worth what it should be.
4. **De-vigged consensus** — book moneylines stripped of juice (power method)
   and blended with Polymarket/Kalshi, which trade near fair value.
5. **Edge threshold + fractional Kelly** — bet only when the model clears the
   market by your threshold; stake quarter-Kelly, hard-capped at 3% of roll.
6. **CLV** — beat the closing line or you don't have an edge. The ledger keeps
   score.

## Architecture

```
sharpline/
├── app.py          Flask REST API (port 8051), auto-sync + background refresh
├── sources.py      The Odds API + ESPN + Polymarket + Kalshi, layered fallback
├── ratings.py      nflverse data fetch, Elo power ratings, real schedule
├── sample_data.py  Model-priced lines for offline/offseason
├── model.py        Power ratings, HFA, key-number margin distribution
├── edges.py        Market consensus, best-price scan, edge & stake engine
├── odds_math.py    Conversions, de-vig (multiplicative & power), EV, Kelly
├── database.py     SQLite: settings, ratings, odds snapshots, bet ledger
├── index.html      538-style single-page UI
├── styles/main.css
├── scripts/app.js
└── tests/          pytest suite
```

Run tests with `python3 -m pytest tests/ -v` from the `sharpline/` directory.

> SharpLine is an analytics tool, not betting advice. Bet legally and within
> your means.
