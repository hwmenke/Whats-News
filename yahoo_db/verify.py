"""
verify.py - Offline data-quality audit of what is already in the store.

Design notes
  * Nothing here touches the network. Every answer comes from the database, so
    `verify` is safe to run beside a download that is still going.
  * Each check returns a count plus a bounded sample, never the whole offender
    list — a 100k-symbol universe with a systematic problem would otherwise
    print for an hour. `limit` sizes every sample.
  * The checks describe, they do not accuse. Yahoo's history is what it is: an
    exchange holiday, a zero-volume FX bar and a doubled close in a penny stock
    are all normal. Every heuristic below is tuned to stay quiet about the
    normal case, and the line it draws is written down next to it.
  * `apply_fixes` only rewrites columns that are *derived* from rows we already
    hold — has_data, delisted_at, status. It never writes or deletes a price.
"""

import logging
from datetime import date, timedelta

from .db import STATUS_ACTIVE, STATUS_DELISTED, utcnow

logger = logging.getLogger(__name__)

# A gap of this many *weekday* sessions is reported. US exchanges have never
# closed for five consecutive weekdays outside a world war — the long modern
# closures are four days (9/11, 2001) and two (Sandy, 2012), and no holiday
# cluster reaches three — so five keeps every holiday quiet while still
# catching a month of missing bars. It does still flag genuine trading halts
# and symbols too illiquid to print every session; that is the intended
# trade-off, because both are things you want to know about your archive.
DEFAULT_GAP_WEEKDAYS = 5

# Runs of zero-volume bars at least this long, and only for symbols that report
# real volume somewhere in their history — an index or an FX pair carries
# volume 0 on every bar by convention, which is a data model, not a defect.
DEFAULT_ZERO_VOLUME_RUN = 5

# Close ratios that look like an unrecorded split. Inverses (reverse splits)
# are derived, not listed.
SPLIT_FACTORS = (1.5, 2.0, 3.0, 10.0)
DEFAULT_SPLIT_TOLERANCE = 0.04      # ±4% around the factor
# Yahoo dates a split on its ex-date and the price discontinuity can land a
# session either side of it, so a split row this close counts as recorded.
SPLIT_DATE_SLACK_DAYS = 4

# Floating point noise: a close is only "outside" its own range when it misses
# by more than this, relatively.
PRICE_EPSILON = 1e-6


def run(store, interval: str = "1d", limit: int = 10,
        gap_weekdays: int = DEFAULT_GAP_WEEKDAYS,
        stale_days: int = 30,
        zero_volume_run: int = DEFAULT_ZERO_VOLUME_RUN,
        split_tolerance: float = DEFAULT_SPLIT_TOLERANCE) -> dict:
    """Run every check and return the report as a plain dict (JSON-ready)."""
    market_last = _market_last_date(store, interval)
    report = {
        "generated_at": utcnow(),
        "db_path": str(store.db_path),
        "interval": interval,
        "limit": limit,
        "market_last_date": market_last,
        "totals": _totals(store, interval),
        "checks": {},
    }

    report["checks"]["no_prices"] = check_no_prices(store, interval, limit)
    report["checks"]["price_gaps"] = check_price_gaps(
        store, interval, limit, gap_weekdays)
    report["checks"].update(check_suspicious_bars(store, interval, limit))
    report["checks"]["zero_volume_runs"] = check_zero_volume_runs(
        store, interval, limit, zero_volume_run)
    report["checks"].update(check_date_integrity(store, interval, limit))
    report["checks"]["split_suspects"] = check_split_suspects(
        store, interval, limit, split_tolerance)
    report["checks"]["stale_active"] = check_stale_active(
        store, interval, limit, stale_days, market_last)
    report["checks"]["fetch_log"] = check_fetch_log(store, interval, limit)

    report["problem_count"] = sum(c["count"] for c in report["checks"].values())
    return report


# ── checks ─────────────────────────────────────────────────────────────────────

def check_no_prices(store, interval: str, limit: int) -> dict:
    """Symbols in the universe with not a single bar, broken out by status.

    Unknown/active symbols here are the download's backlog; delisted ones are
    usually symbols Yahoo never had at all, which is a normal outcome of a
    brute-force universe crawl rather than a fault.
    """
    rows = store.conn.execute(
        """SELECT t.status, COUNT(*) n FROM tickers t
           WHERE NOT EXISTS (SELECT 1 FROM prices p
                             WHERE p.symbol = t.symbol AND p.interval = ?)
           GROUP BY t.status ORDER BY n DESC""",
        (interval,),
    ).fetchall()

    by_status = {}
    for row in rows:
        sample = store.conn.execute(
            """SELECT t.symbol FROM tickers t
               WHERE t.status = ?
                 AND NOT EXISTS (SELECT 1 FROM prices p
                                 WHERE p.symbol = t.symbol AND p.interval = ?)
               ORDER BY t.symbol LIMIT ?""",
            (row["status"], interval, limit),
        ).fetchall()
        by_status[row["status"]] = {
            "count": row["n"],
            "sample": [r["symbol"] for r in sample],
        }

    total = sum(v["count"] for v in by_status.values())
    return {
        "label": "symbols with no price rows",
        "count": total,
        "by_status": by_status,
        "sample": [{"symbol": s} for status in by_status
                   for s in by_status[status]["sample"]][:limit],
        "note": "delisted symbols with no bars are usually tickers Yahoo never "
                "carried; active/unknown ones are still owed a download",
    }


def check_price_gaps(store, interval: str, limit: int, gap_weekdays: int) -> dict:
    """Holes in a daily series that are too long to be a holiday.

    SQL narrows to date pairs more than `gap_weekdays` calendar days apart —
    a safe superset, since a span of N calendar days can hold at most N-1
    weekdays — and the exact weekday count is then computed per pair.
    """
    if interval != "1d":
        return _skipped("trading-day gaps",
                        f"only meaningful for 1d bars, not {interval}")

    rows = store.conn.execute(
        """SELECT symbol, prev_date, date FROM (
               SELECT symbol, date,
                      LAG(date) OVER (PARTITION BY symbol ORDER BY date) AS prev_date
               FROM prices WHERE interval = ?
           )
           WHERE prev_date IS NOT NULL
             AND julianday(date) - julianday(prev_date) > ?""",
        (interval, gap_weekdays),
    ).fetchall()

    gaps = []
    symbols = set()
    for row in rows:
        missing = _weekdays_between(row["prev_date"], row["date"])
        if missing < gap_weekdays:
            continue
        symbols.add(row["symbol"])
        gaps.append({"symbol": row["symbol"], "from": row["prev_date"],
                     "to": row["date"], "missing_weekdays": missing})

    gaps.sort(key=lambda g: -g["missing_weekdays"])
    return {
        "label": "trading-day gaps",
        "count": len(gaps),
        "symbols": len(symbols),
        "sample": gaps[:limit],
        "note": f"a hole of >= {gap_weekdays} weekday sessions; shorter ones are "
                f"holidays and are not reported",
    }


def check_suspicious_bars(store, interval: str, limit: int) -> dict:
    """Bars that violate their own arithmetic. Each is a separate check so the
    report says which kind of broken, not just how much."""
    conditions = [
        ("high_below_low", "high above low is violated",
         "high IS NOT NULL AND low IS NOT NULL AND high < low"),
        ("close_outside_range", "close outside [low, high]",
         f"close IS NOT NULL AND ("
         f"(low  IS NOT NULL AND close < low  - {PRICE_EPSILON} * ABS(low)) OR "
         f"(high IS NOT NULL AND close > high + {PRICE_EPSILON} * ABS(high)))"),
        ("non_positive_price", "zero or negative price",
         "(open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR adj_close <= 0)"),
        ("negative_volume", "negative volume", "volume < 0"),
    ]

    out = {}
    for name, label, predicate in conditions:
        count = store.conn.execute(
            f"SELECT COUNT(*) n FROM prices WHERE interval = ? AND ({predicate})",
            (interval,),
        ).fetchone()["n"]
        sample = store.conn.execute(
            f"""SELECT symbol, date, open, high, low, close, volume
                FROM prices WHERE interval = ? AND ({predicate})
                ORDER BY symbol, date LIMIT ?""",
            (interval, limit),
        ).fetchall() if count else []
        out[name] = {
            "label": label,
            "count": count,
            "sample": [dict(r) for r in sample],
        }
    return out


def check_zero_volume_runs(store, interval: str, limit: int,
                           run_length: int) -> dict:
    """Stretches of consecutive zero-volume bars, ignoring symbols that never
    report volume at all (indices, FX — their zero is a convention).

    Islands are found the usual way: for the zero-volume rows only, the
    difference between the row's position in the series and its position among
    the zeros is constant inside a run.
    """
    rows = store.conn.execute(
        """WITH numbered AS (
               SELECT symbol, date, volume,
                      ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS rn
               FROM prices
               WHERE interval = ?
                 AND symbol IN (SELECT symbol FROM prices
                                WHERE interval = ? AND volume > 0
                                GROUP BY symbol)
           ),
           zeros AS (
               SELECT symbol, date,
                      rn - ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date)
                          AS island
               FROM numbered WHERE volume = 0
           )
           SELECT symbol, MIN(date) first_date, MAX(date) last_date,
                  COUNT(*) bars
           FROM zeros GROUP BY symbol, island
           HAVING bars >= ?
           ORDER BY bars DESC""",
        (interval, interval, run_length),
    ).fetchall()

    return {
        "label": "zero-volume runs",
        "count": len(rows),
        "symbols": len({r["symbol"] for r in rows}),
        "sample": [dict(r) for r in rows[:limit]],
        "note": f"runs of >= {run_length} consecutive zero-volume bars, only for "
                f"symbols that report volume elsewhere",
    }


def check_date_integrity(store, interval: str, limit: int) -> dict:
    """Duplicate and out-of-order dates.

    The (symbol, interval, date) primary key makes a true duplicate row
    impossible and there is no stored ordering to be wrong — every read is
    `ORDER BY date`. What is still possible, and what these check, is a date
    *string* that the key cannot see through: a value that is not plain
    YYYY-MM-DD sorts wrongly against the ones that are, and lets the same
    trading day in twice under two spellings ('2024-01-02' next to
    '2024-01-02 00:00:00'). A date past today is the third way the ordering
    can lie, and it means a bad parse upstream.
    """
    malformed = store.conn.execute(
        """SELECT symbol, date FROM prices
           WHERE interval = ?
             AND date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
           ORDER BY symbol, date LIMIT ?""",
        (interval, limit),
    ).fetchall()
    malformed_count = store.conn.execute(
        """SELECT COUNT(*) n FROM prices
           WHERE interval = ?
             AND date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'""",
        (interval,),
    ).fetchone()["n"]

    duplicates = store.conn.execute(
        """SELECT symbol, SUBSTR(date, 1, 10) day, COUNT(*) rows
           FROM prices WHERE interval = ?
           GROUP BY symbol, day HAVING rows > 1
           ORDER BY rows DESC, symbol LIMIT ?""",
        (interval, limit),
    ).fetchall()
    duplicate_count = store.conn.execute(
        """SELECT COUNT(*) n FROM (
               SELECT symbol FROM prices WHERE interval = ?
               GROUP BY symbol, SUBSTR(date, 1, 10) HAVING COUNT(*) > 1)""",
        (interval,),
    ).fetchone()["n"]

    today = date.today().isoformat()
    future_count = store.conn.execute(
        "SELECT COUNT(*) n FROM prices WHERE interval = ? AND date > ?",
        (interval, today),
    ).fetchone()["n"]
    future = store.conn.execute(
        """SELECT symbol, date FROM prices WHERE interval = ? AND date > ?
           ORDER BY date DESC LIMIT ?""",
        (interval, today, limit),
    ).fetchall() if future_count else []

    return {
        "malformed_dates": {
            "label": "dates that are not plain YYYY-MM-DD",
            "count": malformed_count,
            "sample": [dict(r) for r in malformed],
            "note": "these sort wrongly against well-formed dates",
        },
        "duplicate_dates": {
            "label": "same trading day stored twice",
            "count": duplicate_count,
            "sample": [dict(r) for r in duplicates],
            "note": "the primary key rules out exact duplicates, so a hit here "
                    "means one day arrived under two different date spellings",
        },
        "future_dates": {
            "label": "bars dated in the future",
            "count": future_count,
            "sample": [dict(r) for r in future],
        },
    }


def check_split_suspects(store, interval: str, limit: int,
                         tolerance: float) -> dict:
    """Day-over-day close ratios that look like a split nobody recorded.

    Prices are stored unadjusted, so a real split shows up as a clean jump in
    `close` and should have a matching row in `splits`. A jump near a common
    factor with no such row means either the actions call missed it or the two
    series disagree — both worth knowing before you compute a return.

    This is a suspect list, not a verdict: a 2x overnight move is entirely
    possible in a biotech or a sub-dollar stock, so the sample carries both
    closes and you decide.
    """
    smallest = min(SPLIT_FACTORS)
    high_bound = smallest * (1 - tolerance)
    low_bound = (1 / smallest) * (1 + tolerance)

    rows = store.conn.execute(
        """SELECT symbol, prev_date, date, prev_close, close,
                  prev_close / close AS ratio
           FROM (
               SELECT symbol, date, close,
                      LAG(date)  OVER w AS prev_date,
                      LAG(close) OVER w AS prev_close
               FROM prices
               WHERE interval = ? AND close > 0
               WINDOW w AS (PARTITION BY symbol ORDER BY date)
           )
           WHERE prev_close IS NOT NULL AND prev_close > 0
             AND (prev_close / close >= ? OR prev_close / close <= ?)""",
        (interval, high_bound, low_bound),
    ).fetchall()

    candidates = []
    for row in rows:
        factor = _nearest_split_factor(row["ratio"], tolerance)
        if factor is None:
            continue
        candidates.append({"symbol": row["symbol"], "date": row["date"],
                           "prev_date": row["prev_date"],
                           "prev_close": row["prev_close"],
                           "close": row["close"],
                           "ratio": round(row["ratio"], 4),
                           "looks_like": factor})

    known = _splits_by_symbol(store, {c["symbol"] for c in candidates})
    unrecorded = [c for c in candidates
                  if not _split_recorded(known.get(c["symbol"], ()), c)]
    unrecorded.sort(key=lambda c: (c["symbol"], c["date"]))

    return {
        "label": "possible unrecorded splits",
        "count": len(unrecorded),
        "symbols": len({c["symbol"] for c in unrecorded}),
        "checked_candidates": len(candidates),
        "sample": unrecorded[:limit],
        "note": f"close ratio within {tolerance:.0%} of "
                f"{', '.join(str(f) for f in SPLIT_FACTORS)} (or their inverses) "
                f"with no splits row within {SPLIT_DATE_SLACK_DAYS} days",
    }


def check_stale_active(store, interval: str, limit: int, stale_days: int,
                       market_last: str) -> dict:
    """Symbols still flagged active whose newest bar is far behind the market's.

    The reference is the newest bar in the whole database rather than today, so
    a weekend, a holiday or an archive that has not been refreshed in a month
    does not turn the entire universe stale at once.
    """
    if not market_last:
        return _skipped("stale but still active", "no price rows at all")

    cutoff = (date.fromisoformat(market_last[:10])
              - timedelta(days=stale_days)).isoformat()
    rows = store.conn.execute(
        """SELECT t.symbol, MAX(p.date) last_date
           FROM tickers t JOIN prices p
             ON p.symbol = t.symbol AND p.interval = ?
           WHERE t.status = ?
           GROUP BY t.symbol HAVING last_date < ?
           ORDER BY last_date""",
        (interval, STATUS_ACTIVE, cutoff),
    ).fetchall()

    return {
        "label": "stale but still marked active",
        "count": len(rows),
        "sample": [dict(r) for r in rows[:limit]],
        "note": f"newest bar more than {stale_days} days behind {market_last}; "
                f"`verify --fix` or `mark-delisted` flags these",
    }


def check_fetch_log(store, interval: str, limit: int) -> dict:
    """Health of the download ledger: how attempts ended and why."""
    by_status = {
        r["status"]: {"attempts": r["n"], "symbols": r["symbols"]}
        for r in store.conn.execute(
            """SELECT status, COUNT(*) n, COUNT(DISTINCT symbol) symbols
               FROM fetch_log WHERE interval = ? GROUP BY status ORDER BY n DESC""",
            (interval,),
        ).fetchall()
    }

    top_errors = [
        dict(r) for r in store.conn.execute(
            """SELECT error, COUNT(*) n FROM fetch_log
               WHERE interval = ? AND error IS NOT NULL AND error != ''
               GROUP BY error ORDER BY n DESC LIMIT ?""",
            (interval, limit),
        ).fetchall()
    ]

    # A symbol whose *latest* attempt failed is the actionable set — one old
    # error followed by a success is not a problem.
    failing = store.conn.execute(
        """SELECT symbol, status, error, fetched_at FROM fetch_log f
           WHERE interval = ? AND status != 'ok'
             AND fetched_at = (SELECT MAX(fetched_at) FROM fetch_log g
                               WHERE g.symbol = f.symbol AND g.interval = f.interval)
           ORDER BY fetched_at DESC""",
        (interval,),
    ).fetchall()

    errors = by_status.get("error", {}).get("attempts", 0)
    empties = by_status.get("empty", {}).get("attempts", 0)
    return {
        "label": "fetch_log health",
        # Distinct symbols, not rows: two attempts can share a timestamp to the
        # second, and one symbol is one problem either way.
        "count": len({r["symbol"] for r in failing}),
        "by_status": by_status,
        "error_attempts": errors,
        "empty_attempts": empties,
        "top_errors": top_errors,
        "sample": [dict(r) for r in failing[:limit]],
        "note": "count is symbols whose most recent attempt did not succeed",
    }


# ── fixes ──────────────────────────────────────────────────────────────────────

def apply_fixes(store, interval: str = "1d", stale_days: int = 30) -> dict:
    """Repair the things that are derivable from data already in the database.

    Deliberately short. Only two kinds of change qualify as unambiguously safe:

      * `has_data` / `delisted_at` on tickers are caches of "does this symbol
        have bars, and what is the newest one" — the prices table is the
        authority, so re-deriving them cannot lose information.
      * the stale sweep, which is exactly what `mark-delisted` already does and
        what every download run finishes with.

    What is *not* here, on purpose: re-queueing symbols for download. fetch_log
    is append-only evidence and `symbols_to_fetch` reads it as "how many times
    have we tried and when" — writing a row makes a symbol *less* due, not
    more, and deleting rows would throw away the record of why it failed. The
    lever for that is `download --force --symbols …`, and verify prints the
    symbols to hand it.
    """
    fixed = {}

    with store.tx() as c:
        cur = c.execute(
            f"""UPDATE tickers SET
                    has_data = 1,
                    delisted_at = (SELECT MAX(date) FROM prices p
                                   WHERE p.symbol = tickers.symbol
                                     AND p.interval = ?)
                WHERE EXISTS (SELECT 1 FROM prices p
                              WHERE p.symbol = tickers.symbol AND p.interval = ?)
                  AND (has_data = 0
                       OR delisted_at IS NULL
                       OR delisted_at != (SELECT MAX(date) FROM prices p
                                          WHERE p.symbol = tickers.symbol
                                            AND p.interval = ?))""",
            (interval, interval, interval),
        )
        fixed["has_data_set"] = cur.rowcount

        # The mirror image: a flag claiming bars that are not there. Only the
        # flag is cleared — delisted_at may have come from a source rather than
        # from prices, and nothing here knows better than whoever wrote it.
        cur = c.execute(
            """UPDATE tickers SET has_data = 0
               WHERE has_data = 1
                 AND NOT EXISTS (SELECT 1 FROM prices p
                                 WHERE p.symbol = tickers.symbol
                                   AND p.interval = ?)""",
            (interval,),
        )
        fixed["has_data_cleared"] = cur.rowcount

    fixed["marked_delisted_stale"] = store.mark_stale_as_delisted(
        interval, stale_days)
    logger.info("verify --fix: %s", fixed)
    return fixed


# ── helpers ────────────────────────────────────────────────────────────────────

def _totals(store, interval: str) -> dict:
    one = lambda sql, params=(): store.conn.execute(sql, params).fetchone()[0]  # noqa: E731
    return {
        "tickers": one("SELECT COUNT(*) FROM tickers"),
        "tickers_active": one("SELECT COUNT(*) FROM tickers WHERE status=?",
                              (STATUS_ACTIVE,)),
        "tickers_delisted": one("SELECT COUNT(*) FROM tickers WHERE status=?",
                                (STATUS_DELISTED,)),
        "price_rows": one("SELECT COUNT(*) FROM prices WHERE interval=?",
                          (interval,)),
        "symbols_with_prices": one(
            "SELECT COUNT(DISTINCT symbol) FROM prices WHERE interval=?",
            (interval,)),
        "split_rows": one("SELECT COUNT(*) FROM splits"),
    }


def _market_last_date(store, interval: str):
    row = store.conn.execute(
        "SELECT MAX(date) d FROM prices WHERE interval=?", (interval,)
    ).fetchone()
    return row["d"] if row and row["d"] else None


def _skipped(label: str, why: str) -> dict:
    return {"label": label, "count": 0, "sample": [], "skipped": why,
            "note": f"skipped: {why}"}


def _weekdays_between(start: str, end: str) -> int:
    """Mon–Fri days strictly between two ISO dates. Weekends are free; public
    holidays are not modelled, which is why the gap threshold is set above the
    longest holiday closure instead of trying to enumerate calendars."""
    try:
        first = date.fromisoformat(str(start)[:10]) + timedelta(days=1)
        last = date.fromisoformat(str(end)[:10]) - timedelta(days=1)
    except ValueError:
        return 0
    if last < first:
        return 0
    # Whole weeks contribute five each; the remainder is counted directly.
    span = (last - first).days + 1
    weeks, remainder = divmod(span, 7)
    count = weeks * 5
    for offset in range(remainder):
        if (first + timedelta(days=weeks * 7 + offset)).weekday() < 5:
            count += 1
    return count


def _nearest_split_factor(ratio: float, tolerance: float):
    """Which split the ratio looks like — 2.0 for a 2:1, 0.1 for a 1:10 — or
    None when it is just a big move."""
    for factor in SPLIT_FACTORS:
        if abs(ratio / factor - 1) <= tolerance:
            return factor
        if abs(ratio * factor - 1) <= tolerance:
            return round(1 / factor, 4)
    return None


def _splits_by_symbol(store, symbols) -> dict:
    out = {}
    symbols = sorted(symbols)
    for i in range(0, len(symbols), 500):
        chunk = symbols[i:i + 500]
        placeholders = ",".join("?" for _ in chunk)
        for row in store.conn.execute(
            f"SELECT symbol, date FROM splits WHERE symbol IN ({placeholders})",
            chunk,
        ).fetchall():
            out.setdefault(row["symbol"], []).append(row["date"])
    return out


def _split_recorded(split_dates, candidate) -> bool:
    """True when a splits row sits close enough to the discontinuity to explain
    it. Yahoo's ex-date and the bar the jump lands on can differ by a session,
    and by more around a holiday, hence the slack."""
    try:
        low = (date.fromisoformat(candidate["prev_date"][:10])
               - timedelta(days=SPLIT_DATE_SLACK_DAYS)).isoformat()
        high = (date.fromisoformat(candidate["date"][:10])
                + timedelta(days=SPLIT_DATE_SLACK_DAYS)).isoformat()
    except ValueError:
        return False
    return any(low <= str(d)[:10] <= high for d in split_dates)
