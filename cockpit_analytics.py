"""
cockpit_analytics.py — Performance analytics on the trade journal.

Pure (reads the `trades` table via journal.list_trades). Powers the
Performance tab: equity curve (R and $), drawdown, R-distribution,
and expectancy broken down by setup.
"""

from collections import defaultdict

import journal


def _expectancy(rs):
    n = len(rs)
    if not n:
        return {"count": 0, "wins": 0, "win_rate": 0.0, "avg_r": 0.0,
                "expectancy_r": 0.0, "total_r": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return {
        "count": n,
        "wins": len(wins),
        "win_rate": round(win_rate * 100, 1),
        "avg_r": round(sum(rs) / n, 2),
        "expectancy_r": round(win_rate * avg_win + (1 - win_rate) * avg_loss, 2),
        "total_r": round(sum(rs), 2),
    }


def compute_performance():
    closed = [t for t in journal.list_trades("closed")
              if t.get("r_multiple") is not None]
    # Order chronologically by exit date (fall back to entry/id)
    closed.sort(key=lambda t: (t.get("exit_date") or t.get("entry_date") or "",
                               t.get("id") or 0))

    # ── Equity curve (R and $) + drawdown in R ──────────────────────────────
    curve = []
    cum_r = cum_pnl = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for t in closed:
        cum_r += t["r_multiple"]
        cum_pnl += (t.get("pnl") or 0.0)
        peak_r = max(peak_r, cum_r)
        max_dd_r = max(max_dd_r, peak_r - cum_r)
        curve.append({
            "date": t.get("exit_date") or t.get("entry_date"),
            "symbol": t.get("symbol"),
            "r": round(t["r_multiple"], 2),
            "cum_r": round(cum_r, 2),
            "cum_pnl": round(cum_pnl, 2),
        })

    # ── R-distribution histogram ────────────────────────────────────────────
    bins = [(-99, -2), (-2, -1), (-1, 0), (0, 1), (1, 2), (2, 3), (3, 5), (5, 99)]
    labels = ["<-2R", "-2..-1R", "-1..0R", "0..1R", "1..2R", "2..3R", "3..5R", ">5R"]
    hist = [0] * len(bins)
    for t in closed:
        r = t["r_multiple"]
        for i, (lo, hi) in enumerate(bins):
            if lo <= r < hi:
                hist[i] += 1
                break
    distribution = [{"bucket": labels[i], "count": hist[i]} for i in range(len(bins))]

    # ── Expectancy by setup + by direction ──────────────────────────────────
    by_setup_r = defaultdict(list)
    by_dir_r = defaultdict(list)
    for t in closed:
        by_setup_r[(t.get("setup_type") or "—")].append(t["r_multiple"])
        by_dir_r[t.get("direction") or "long"].append(t["r_multiple"])

    by_setup = [{"setup": k, **_expectancy(v)}
                for k, v in sorted(by_setup_r.items(), key=lambda kv: -sum(kv[1]))]
    by_direction = [{"direction": k, **_expectancy(v)} for k, v in by_dir_r.items()]

    # ── Monthly R ───────────────────────────────────────────────────────────
    by_month_r = defaultdict(list)
    for t in closed:
        d = (t.get("exit_date") or t.get("entry_date") or "")[:7]
        if d:
            by_month_r[d].append(t["r_multiple"])
    monthly = [{"month": m, "r": round(sum(rs), 2), "trades": len(rs)}
               for m, rs in sorted(by_month_r.items())]

    overall = _expectancy([t["r_multiple"] for t in closed])
    overall["max_drawdown_r"] = round(max_dd_r, 2)
    overall["total_pnl"] = round(cum_pnl, 2)

    return {
        "overall": overall,
        "equity_curve": curve,
        "distribution": distribution,
        "by_setup": by_setup,
        "by_direction": by_direction,
        "monthly": monthly,
    }


def export_trades_csv():
    """Flatten all trades to CSV text."""
    import csv
    import io
    rows = journal.list_trades()
    cols = ["id", "symbol", "direction", "status", "setup_type", "entry_date",
            "exit_date", "entry_time", "entry_price", "stop_price", "exit_price",
            "shares", "r_multiple", "pct_move", "pnl", "result", "notes"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()
