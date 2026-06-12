"""
database.py - SQLite persistence for SharpLine.

Tables:
  settings        key/value store (bankroll, kelly fraction, thresholds...)
  ratings         editable team power ratings
  odds_snapshots  every board refresh is archived here for line-movement views
  bets            the bet ledger, including closing lines for CLV grading
"""

import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sharpline.db")

DEFAULT_SETTINGS = {
    "bankroll": "10000",
    "kelly_fraction": "0.25",   # quarter Kelly
    "max_bet_pct": "0.03",      # hard cap per Walters: never >3% on one game
    "edge_threshold": "0.02",   # min model-vs-market prob edge to flag a play
    "hfa": "2.0",
}


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ratings (
                team    TEXT PRIMARY KEY,
                rating  REAL NOT NULL,
                updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      REAL NOT NULL,
                game_id TEXT NOT NULL,
                book    TEXT NOT NULL,
                market  TEXT NOT NULL,   -- spread | moneyline | total
                payload TEXT NOT NULL    -- JSON blob of the quote
            );
            CREATE INDEX IF NOT EXISTS idx_snap_game ON odds_snapshots (game_id, ts);
            CREATE TABLE IF NOT EXISTS bets (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL NOT NULL,
                game_id      TEXT NOT NULL,
                description  TEXT NOT NULL,
                market       TEXT NOT NULL,
                side         TEXT NOT NULL,
                line         REAL,
                odds         INTEGER NOT NULL,
                stake        REAL NOT NULL,
                book         TEXT,
                status       TEXT NOT NULL DEFAULT 'open',  -- open | won | lost | push
                payout       REAL,
                closing_line REAL,
                closing_odds INTEGER,
                clv_pct      REAL
            );
        """)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))


# -- Settings ----------------------------------------------------------------------

def get_settings():
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    out = {r["key"]: r["value"] for r in rows}
    for k in ("bankroll", "kelly_fraction", "max_bet_pct", "edge_threshold", "hfa"):
        if k in out:
            out[k] = float(out[k])
    return out


def set_settings(updates):
    with _conn() as c:
        for k, v in updates.items():
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, str(v)),
            )


# -- Ratings -----------------------------------------------------------------------

def get_ratings(defaults=None):
    with _conn() as c:
        rows = c.execute("SELECT team, rating FROM ratings").fetchall()
    ratings = dict(defaults or {})
    ratings.update({r["team"]: r["rating"] for r in rows})
    return ratings


def set_ratings(ratings):
    now = time.time()
    with _conn() as c:
        for team, rating in ratings.items():
            c.execute(
                "INSERT INTO ratings (team, rating, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(team) DO UPDATE SET rating = excluded.rating, updated = excluded.updated",
                (team, float(rating), now),
            )


# -- Odds snapshots ------------------------------------------------------------------

def snapshot_board(board):
    """Archive every quote on the board for line-movement history."""
    ts = board.get("as_of", time.time())
    with _conn() as c:
        for game in board.get("games", []):
            for book, markets in game.get("books", {}).items():
                for market, quote in markets.items():
                    c.execute(
                        "INSERT INTO odds_snapshots (ts, game_id, book, market, payload) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (ts, game["id"], book, market, json.dumps(quote)),
                    )


def get_movement(game_id, market="spread"):
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, book, payload FROM odds_snapshots "
            "WHERE game_id = ? AND market = ? ORDER BY ts",
            (game_id, market),
        ).fetchall()
    return [
        {"ts": r["ts"], "book": r["book"], **json.loads(r["payload"])}
        for r in rows
    ]


# -- Bets -------------------------------------------------------------------------

def add_bet(bet):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO bets (ts, game_id, description, market, side, line, odds, stake, book) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(), bet["game_id"], bet["description"], bet["market"],
                bet["side"], bet.get("line"), int(bet["odds"]), float(bet["stake"]),
                bet.get("book"),
            ),
        )
        return cur.lastrowid


def list_bets():
    with _conn() as c:
        rows = c.execute("SELECT * FROM bets ORDER BY ts DESC").fetchall()
    return [dict(r) for r in rows]


def settle_bet(bet_id, status, closing_line=None, closing_odds=None):
    from odds_math import american_to_decimal, american_to_prob

    with _conn() as c:
        row = c.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        if row is None:
            return None
        stake, odds = row["stake"], row["odds"]
        if status == "won":
            payout = round(stake * american_to_decimal(odds), 2)
        elif status == "push":
            payout = stake
        elif status == "lost":
            payout = 0.0
        else:  # back to open
            payout = None

        clv_pct = row["clv_pct"]
        if closing_odds is not None:
            # CLV: how much better was our price than the close, in prob terms
            p_bet, p_close = american_to_prob(odds), american_to_prob(int(closing_odds))
            clv_pct = round((p_close - p_bet) * 100.0, 2)

        c.execute(
            "UPDATE bets SET status = ?, payout = ?, closing_line = COALESCE(?, closing_line), "
            "closing_odds = COALESCE(?, closing_odds), clv_pct = COALESCE(?, clv_pct) WHERE id = ?",
            (status, payout, closing_line, closing_odds, clv_pct, bet_id),
        )
        return dict(c.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone())


def delete_bet(bet_id):
    with _conn() as c:
        c.execute("DELETE FROM bets WHERE id = ?", (bet_id,))


def bet_summary():
    bets = list_bets()
    settled = [b for b in bets if b["status"] in ("won", "lost", "push")]
    staked = sum(b["stake"] for b in settled)
    returned = sum(b["payout"] or 0.0 for b in settled)
    clvs = [b["clv_pct"] for b in bets if b["clv_pct"] is not None]
    wins = sum(1 for b in settled if b["status"] == "won")
    losses = sum(1 for b in settled if b["status"] == "lost")
    return {
        "n_bets": len(bets),
        "n_open": sum(1 for b in bets if b["status"] == "open"),
        "record": f"{wins}-{losses}" + (f"-{len(settled) - wins - losses}" if settled else ""),
        "staked": round(staked, 2),
        "profit": round(returned - staked, 2),
        "roi_pct": round((returned - staked) / staked * 100.0, 2) if staked else 0.0,
        "avg_clv_pct": round(sum(clvs) / len(clvs), 2) if clvs else None,
    }
