"""Paper book: Fidelity CSV + manual lines, marked from stored Yahoo closes.

No live broker, no invented P&L / VaR. Missing bars → omit that metric.
Empty book → honest zeros, never demo AXE-scale numbers.
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timezone

import numpy as np

import database as db
import market_data as md

NOTE = (
    "Paper / local only. Marks and VaR use stored Yahoo daily closes. "
    "Empty book is zeros — not a demo P&L. Import a Fidelity Positions CSV "
    "(Symbol + Quantity; Average Cost Basis optional), sync Alpaca paper, or add a line. "
    "Alpaca paper — not live P&L."
)
KNOWN_SOURCES = ("manual", "fidelity_csv", "alpaca_paper")
SOURCE_MANUAL = "manual"
SOURCE_FIDELITY = "fidelity_csv"
SOURCE_ALPACA = "alpaca_paper"
SOURCE_UNMARKED = "unmarked"
CASH_SKIP = {
    "CASH", "USD", "SPAXX", "SPAXX**", "FDRXX", "FZFXX", "SPRXX",
    "PENDING ACTIVITY", "CORE",
}
Z95 = 1.6448536269514722
Z99 = 2.3263478740408408
MIN_RET = 20
MIN_DD = 10
# Concentration chips — documented thresholds, no fake alerts.
# top_weight_pct = max(|MV_i| / gross) * 100
# top5_share = sum of the five largest |MV| / gross * 100
# HHI = sum(w_i^2) * 10000  (standard 0–10000; 2500 = moderately concentrated)
CONCENTRATED_TOP_WEIGHT = 25.0
CONCENTRATED_TOP5_SHARE = 80.0
CONCENTRATED_HHI = 2500.0
# Peak-to-trough on marked NAV: (nav - running_peak) / abs(peak) * 100.
# DD_WARNING when max_dd_pct <= -10. Omitted if equity_curve has fewer than MIN_DD points.
DD_WARNING_PCT = -10.0
DESK_DEFAULT = "Whats-News"
CONCENTRATION_NOTE = (
    f"CONCENTRATED if top weight ≥{CONCENTRATED_TOP_WEIGHT:.0f}%, "
    f"top-5 share ≥{CONCENTRATED_TOP5_SHARE:.0f}%, or HHI ≥{CONCENTRATED_HHI:.0f}. "
    "Weights are |MV| / gross from stored marks."
)
DRAWDOWN_NOTE = (
    f"Peak-to-trough on marked NAV. Omitted under {MIN_DD} NAV points. "
    f"DD_WARNING if max DD ≤ {DD_WARNING_PCT:.0f}%."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(val):
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _round(val, digits=2):
    num = _finite(val)
    if num is None:
        return None
    return round(num, digits)


def _norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _signed_qty(qty, side=None):
    q = _finite(qty)
    if q is None:
        return None, None
    s = (side or "").strip().lower()
    if s in ("short", "s", "sell"):
        return -abs(q), "short"
    if s in ("long", "l", "buy"):
        return abs(q), "long"
    if q < 0:
        return q, "short"
    return q, "long"


def parse_fidelity_csv(text: str) -> list[dict]:
    """Parse a Fidelity Positions export (or any CSV with Symbol + Quantity)."""
    raw = (text or "").replace("\ufeff", "").strip()
    if not raw:
        return []
    # Drop trailing disclaimer rows that are not CSV
    lines = []
    for line in raw.splitlines():
        if line.strip().lower().startswith("the data and information"):
            break
        if line.strip().lower().startswith("copyright"):
            break
        lines.append(line)
    if not lines:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if not reader.fieldnames:
        return []
    keymap = { _norm_header(h): h for h in reader.fieldnames if h }

    def col(*aliases):
        for alias in aliases:
            key = keymap.get(_norm_header(alias))
            if key:
                return key
        return None

    sym_k = col("symbol", "ticker", "sym", "symbol ticker")
    qty_k = col("quantity", "qty", "shares", "share quantity", "quantity 1")
    cost_k = col(
        "cost basis average", "average cost basis", "cost basis avg",
        "avg cost", "average cost", "cost/share", "unit cost",
        "average cost basis $",
    )
    side_k = col("side", "position", "long/short", "type")
    note_k = col("description", "name", "security name", "security description")
    if not sym_k or not qty_k:
        raise ValueError(
            "CSV needs a Symbol (or Ticker) column and a Quantity column. "
            "Fidelity: Positions → download CSV."
        )
    out = []
    for row in reader:
        symbol = str(row.get(sym_k) or "").strip().upper()
        if not symbol or symbol in CASH_SKIP or symbol.startswith("**"):
            continue
        qty_raw = str(row.get(qty_k) or "").replace(",", "").replace("$", "").strip()
        if not qty_raw or qty_raw in ("--", "—"):
            continue
        signed, side = _signed_qty(qty_raw, row.get(side_k) if side_k else None)
        if signed is None or signed == 0:
            continue
        cost = None
        if cost_k:
            cost = _finite(str(row.get(cost_k) or "").replace(",", "").replace("$", ""))
        note = str(row.get(note_k) or "").strip() if note_k else ""
        out.append({
            "symbol": symbol,
            "qty": signed,
            "side": side,
            "avg_cost": cost,
            "note": note,
            "source": "fidelity_csv",
        })
    return out


def normalize_source(raw, *, default: str = SOURCE_MANUAL) -> str:
    s = (raw or "").strip().lower()
    if s in KNOWN_SOURCES:
        return s
    if not s:
        return default
    return SOURCE_UNMARKED


def clear_source(source: str) -> int:
    tag = normalize_source(source, default="")
    if tag not in KNOWN_SOURCES:
        return 0
    with db.connection() as conn:
        cur = conn.execute("DELETE FROM paper_positions WHERE source=?", (tag,))
        return cur.rowcount


def get_desk_name() -> str:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT value FROM paper_book_meta WHERE key=?",
            ("desk_name",),
        ).fetchone()
    if not row or not (row["value"] or "").strip():
        return DESK_DEFAULT
    return str(row["value"]).strip()[:80]


def set_desk_name(name: str) -> str:
    val = (name or "").strip()[:80] or DESK_DEFAULT
    now = _now()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO paper_book_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("desk_name", val),
        )
        conn.execute(
            "INSERT INTO paper_book_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("updated_at", now),
        )
    return val


def list_positions() -> list[dict]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM paper_positions ORDER BY symbol"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_position(*, symbol, qty, side=None, avg_cost=None, note="", source="manual") -> dict:
    signed, side_n = _signed_qty(qty, side)
    if not symbol or signed is None or signed == 0:
        raise ValueError("Need symbol and non-zero quantity")
    sym = str(symbol).strip().upper()
    cost = _finite(avg_cost)
    source = normalize_source(source)
    now = _now()
    with db.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM paper_positions WHERE symbol=?", (sym,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE paper_positions SET qty=?, side=?, avg_cost=?, note=?, "
                "source=?, updated_at=? WHERE symbol=?",
                (signed, side_n, cost, note or "", source, now, sym),
            )
            pid = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO paper_positions "
                "(symbol, qty, side, avg_cost, note, source, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (sym, signed, side_n, cost, note or "", source, now, now),
            )
            pid = cur.lastrowid
    return next(p for p in list_positions() if p["id"] == pid)


def update_position(pid: int, **fields) -> dict | None:
    rows = list_positions()
    cur = next((p for p in rows if int(p["id"]) == int(pid)), None)
    if cur is None:
        return None
    qty = fields["qty"] if "qty" in fields else cur["qty"]
    side = fields.get("side", cur["side"])
    return upsert_position(
        symbol=fields.get("symbol", cur["symbol"]),
        qty=qty,
        side=side,
        avg_cost=fields["avg_cost"] if "avg_cost" in fields else cur.get("avg_cost"),
        note=fields["note"] if "note" in fields else cur.get("note") or "",
        source=fields.get("source") or cur.get("source") or "manual",
    )


def delete_position(pid: int) -> bool:
    with db.connection() as conn:
        cur = conn.execute("DELETE FROM paper_positions WHERE id=?", (int(pid),))
        return cur.rowcount > 0


def clear_positions() -> int:
    with db.connection() as conn:
        cur = conn.execute("DELETE FROM paper_positions")
        return cur.rowcount


def import_csv(text: str, *, replace: bool = False) -> dict:
    parsed = parse_fidelity_csv(text)
    if replace:
        clear_source(SOURCE_FIDELITY)
    imported = []
    for row in parsed:
        imported.append(upsert_position(**row))
    return {
        "imported": len(imported),
        "positions": imported,
        "message": NOTE,
        "replace": replace,
    }


def _daily_closes(symbol: str, limit: int = 320) -> list[tuple[str, float]]:
    df = md.get_ohlcv_df(symbol, "daily", limit=limit)
    if df is None or df.empty or "close" not in df.columns:
        return []
    out = []
    for idx, row in df.iterrows():
        px = _finite(row["close"])
        if px is None or px <= 0:
            continue
        date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        out.append((date, px))
    return out


def _mark_position(pos: dict) -> dict:
    closes = _daily_closes(pos["symbol"])
    last = closes[-1] if closes else None
    prev = closes[-2] if len(closes) > 1 else None
    qty = _finite(pos.get("qty")) or 0.0
    px = last[1] if last else None
    px1 = prev[1] if prev else None
    mv = qty * px if px is not None else None
    day = qty * (px - px1) if px is not None and px1 is not None else None
    cost = _finite(pos.get("avg_cost"))
    unrl = qty * (px - cost) if px is not None and cost is not None else None
    return {
        "id": pos.get("id"),
        "symbol": pos["symbol"],
        "qty": _round(qty, 4),
        "side": pos.get("side") or ("short" if qty < 0 else "long"),
        "avg_cost": _round(cost, 4),
        "note": pos.get("note") or "",
        "source": normalize_source(pos.get("source")),
        "ready": px is not None,
        "price": _round(px, 4),
        "prev_price": _round(px1, 4),
        "market_value": _round(mv, 2),
        "day_pnl": _round(day, 2),
        "unrealized": _round(unrl, 2),
        "day_pct": _round(((px / px1) - 1.0) * 100.0, 2) if px and px1 else None,
        "bars": len(closes),
        "_closes": closes,
    }


def _equity_curve(marked: list[dict]) -> list[dict]:
    ready = [m for m in marked if m["ready"] and m["_closes"]]
    if not ready:
        return []
    series = {}
    for m in ready:
        qty = m["qty"] or 0.0
        last = None
        for date, px in m["_closes"]:
            last = px
            series.setdefault(date, {})[m["symbol"]] = qty * px
        # carry last mark so a missing day does not drop the name
        if last is None:
            continue
    dates = sorted(series)
    # require every ready name to have a mark (carried via last close on its last date+)
    symbols = [m["symbol"] for m in ready]
    last_mv = {s: None for s in symbols}
    curve = []
    for date in dates:
        day = series[date]
        for s in symbols:
            if s in day:
                last_mv[s] = day[s]
        if any(v is None for v in last_mv.values()):
            continue
        nav = float(sum(last_mv.values()))
        if not math.isfinite(nav):
            continue
        curve.append({"date": date, "nav": round(nav, 2)})
    return curve


def _returns(curve: list[dict]) -> np.ndarray:
    if len(curve) < 2:
        return np.asarray([], dtype=float)
    nav = np.asarray([p["nav"] for p in curve], dtype=float)
    prev = nav[:-1]
    ok = np.abs(prev) > 1e-9
    if not np.any(ok):
        return np.asarray([], dtype=float)
    r = (nav[1:] - prev) / np.abs(prev)
    return r[ok & np.isfinite(r)]


def _hist_var(returns: np.ndarray, alpha: float):
    if len(returns) < MIN_RET:
        return None, None
    q = float(np.percentile(returns, alpha * 100.0))
    # VaR as a positive loss fraction
    return -q, None


def _param_var(returns: np.ndarray, z: float):
    if len(returns) < MIN_RET:
        return None
    mu = float(returns.mean())
    sig = float(returns.std(ddof=1))
    if not math.isfinite(sig) or sig <= 0:
        return None
    # Loss quantile of Normal(mu, sig)
    return -(mu + (-z) * sig)


def _cvar(returns: np.ndarray, alpha: float):
    if len(returns) < MIN_RET:
        return None
    q = float(np.percentile(returns, alpha * 100.0))
    tail = returns[returns <= q]
    if len(tail) == 0:
        return None
    return -float(tail.mean())


def _skew(returns: np.ndarray):
    n = len(returns)
    if n < 3:
        return None
    mu = float(returns.mean())
    sig = float(returns.std(ddof=1))
    if sig <= 0:
        return None
    m3 = float(np.mean(((returns - mu) / sig) ** 3))
    return m3


def _histogram(returns: np.ndarray) -> list[dict]:
    if len(returns) < 2:
        return []
    bins = min(12, max(6, int(math.sqrt(len(returns)))))
    counts, edges = np.histogram(returns, bins=bins)
    out = []
    for i, c in enumerate(counts):
        out.append({
            "lo": round(float(edges[i]) * 100.0, 3),
            "hi": round(float(edges[i + 1]) * 100.0, 3),
            "n": int(c),
        })
    return out


def _beta_vs_spy(curve: list[dict]) -> float | None:
    if len(curve) < MIN_RET + 1:
        return None
    spy = _daily_closes("SPY", limit=400)
    if len(spy) < MIN_RET + 1:
        return None
    spy_map = {d: p for d, p in spy}
    aligned_p = []
    aligned_s = []
    prev_nav = None
    prev_spy = None
    for pt in curve:
        px = spy_map.get(pt["date"])
        if px is None or prev_nav is None or prev_spy is None or prev_spy <= 0 or abs(prev_nav) <= 1e-9:
            prev_nav = pt["nav"]
            prev_spy = px
            continue
        aligned_p.append((pt["nav"] - prev_nav) / abs(prev_nav))
        aligned_s.append((px - prev_spy) / prev_spy)
        prev_nav = pt["nav"]
        prev_spy = px
    if len(aligned_p) < MIN_RET:
        return None
    rp = np.asarray(aligned_p, dtype=float)
    rs = np.asarray(aligned_s, dtype=float)
    var_s = float(np.var(rs, ddof=1))
    if var_s <= 0:
        return None
    cov = float(np.cov(rp, rs, ddof=1)[0, 1])
    beta = cov / var_s
    if not math.isfinite(beta):
        return None
    return round(beta, 3)


def _concentration(ready: list[dict]) -> dict:
    """HHI / top weight / top-5 share from |MV| / gross. Omit when gross is 0."""
    weights = []
    for m in ready:
        mv = _finite(m.get("market_value"))
        if mv is None:
            continue
        weights.append((m.get("symbol") or "", abs(mv)))
    gross = sum(w for _, w in weights)
    if gross <= 1e-9 or not weights:
        return {
            "ready": False,
            "top_weight_pct": None,
            "top_symbol": None,
            "top5_share": None,
            "hhi": None,
            "n": 0,
            "note": CONCENTRATION_NOTE,
        }
    shares = sorted(((sym, w / gross) for sym, w in weights), key=lambda x: -x[1])
    top_sym, top_w = shares[0]
    top5 = sum(w for _, w in shares[:5])
    hhi = sum(w * w for _, w in shares) * 10000.0
    return {
        "ready": True,
        "top_weight_pct": _round(top_w * 100.0, 2),
        "top_symbol": top_sym,
        "top5_share": _round(top5 * 100.0, 2),
        "hhi": _round(hhi, 1),
        "n": len(shares),
        "note": CONCENTRATION_NOTE,
    }


def _max_drawdown(curve: list[dict]) -> dict:
    """Peak-to-trough on marked NAV. Omit when the series is too short."""
    empty = {
        "ready": False,
        "max_dd_pct": None,
        "peak_date": None,
        "trough_date": None,
        "n": len(curve or []),
        "note": DRAWDOWN_NOTE,
    }
    if not curve or len(curve) < MIN_DD:
        return empty
    peak = None
    peak_date = None
    worst = 0.0
    worst_peak = None
    worst_trough = None
    for pt in curve:
        nav = _finite(pt.get("nav"))
        date = pt.get("date")
        if nav is None:
            continue
        if peak is None or nav > peak:
            peak = nav
            peak_date = date
        if peak is None or abs(peak) <= 1e-9:
            continue
        dd = (nav - peak) / abs(peak) * 100.0
        if dd < worst:
            worst = dd
            worst_peak = peak_date
            worst_trough = date
    if worst >= 0:
        return {
            "ready": True,
            "max_dd_pct": 0.0,
            "peak_date": peak_date,
            "trough_date": peak_date,
            "n": len(curve),
            "note": DRAWDOWN_NOTE,
        }
    return {
        "ready": True,
        "max_dd_pct": _round(worst, 2),
        "peak_date": worst_peak,
        "trough_date": worst_trough,
        "n": len(curve),
        "note": DRAWDOWN_NOTE,
    }


def _risk_alerts(concentration: dict, drawdown: dict) -> list[dict]:
    """Only fire when a documented threshold is actually crossed."""
    alerts = []
    if concentration.get("ready"):
        top = concentration.get("top_weight_pct")
        top5 = concentration.get("top5_share")
        hhi = concentration.get("hhi")
        hit = (
            (top is not None and top >= CONCENTRATED_TOP_WEIGHT)
            or (top5 is not None and top5 >= CONCENTRATED_TOP5_SHARE)
            or (hhi is not None and hhi >= CONCENTRATED_HHI)
        )
        if hit:
            alerts.append({
                "id": "CONCENTRATED",
                "label": "CONCENTRATED",
                "reason": (
                    f"top {concentration.get('top_symbol') or '?'} "
                    f"{top}% · top5 {top5}% · HHI {hhi}"
                ),
            })
    if drawdown.get("ready") and drawdown.get("max_dd_pct") is not None:
        if drawdown["max_dd_pct"] <= DD_WARNING_PCT:
            alerts.append({
                "id": "DD_WARNING",
                "label": "DD_WARNING",
                "reason": (
                    f"max DD {drawdown['max_dd_pct']}% "
                    f"({drawdown.get('peak_date') or '?'} → {drawdown.get('trough_date') or '?'})"
                ),
            })
    return alerts


def _closes_to_series(closes: list):
    if not closes:
        return None
    try:
        import pandas as pd
        vals = [c[1] for c in closes if c and _finite(c[1]) is not None]
        if len(vals) < 2:
            return None
        return pd.Series(vals, dtype=float)
    except Exception:
        return None


def _holding_opinion(marked: dict, *, hmm_label=None, fractal_read=None) -> dict:
    """day% / vs SMA50 / RSI14 / fractal / inherited SPY HMM — real or blank."""
    closes = marked.get("_closes") or []
    series = _closes_to_series(closes)
    vs50 = None
    rsi14 = None
    if series is not None:
        sma50 = None
        try:
            import portfolio as port
            sma50 = port.last_sma(series, 50)
            rsi_s = port._rsi(series, 14).dropna()
            if len(rsi_s):
                rsi14 = _round(float(rsi_s.iloc[-1]), 2)
            else:
                delta = series.diff().dropna()
                if len(delta) >= 14 and (delta >= 0).all():
                    rsi14 = 100.0
                elif len(delta) >= 14 and (delta <= 0).all():
                    rsi14 = 0.0
        except Exception:
            sma50 = None
        last = _finite(series.iloc[-1]) if len(series) else None
        if last and sma50 and sma50 > 0:
            vs50 = _round((last / sma50 - 1.0) * 100.0, 2)
    return {
        "vs_sma50": vs50,
        "rsi14": rsi14,
        "fractal_read": fractal_read,
        "hmm_label": hmm_label,
    }


def _spy_hmm_label():
    try:
        import hmm_regime
        spy = hmm_regime.fit_spy(n_states=2)
        if not spy or not spy.get("available"):
            return None
        label = spy.get("current_read") or spy.get("current_label")
        return str(label) if label else None
    except Exception:
        return None


def _fractal_read(symbol: str, closes: list):
    try:
        import fractal_scan
        px = [c[1] for c in closes if c and _finite(c[1]) is not None]
        row = fractal_scan.measure_symbol(symbol, closes=px)
        if not row:
            return None
        read = row.get("read")
        return str(read) if read else None
    except Exception:
        return None


def empty_pnl() -> dict:
    return {
        "ready": False,
        "desk_name": get_desk_name() if _table_ready() else DESK_DEFAULT,
        "note": NOTE,
        "message": "Empty paper book. Import a Fidelity Positions CSV, sync Alpaca paper, or add a line. No invented P&L.",
        "sources": [],
        "unmarked_count": 0,
        "count": 0,
        "marked_count": 0,
        "today_pnl": None,
        "today_pnl_pct": None,
        "nav": None,
        "exposure": {
            "gross": 0.0,
            "long": 0.0,
            "short": 0.0,
            "net": 0.0,
            "gross_pct": None,
            "long_pct": None,
            "short_pct": None,
            "net_pct": None,
        },
        "beta_spy": None,
        "var": {},
        "distribution": {"mean": None, "stdev": None, "skew": None, "n": 0, "bins": []},
        "equity_curve": [],
        "curve_label": "daily mark series from stored closes — no intraday bars",
        "positions": [],
        "tape": [],
        "concentration": {
            "ready": False,
            "top_weight_pct": None,
            "top_symbol": None,
            "top5_share": None,
            "hhi": None,
            "n": 0,
            "note": CONCENTRATION_NOTE,
        },
        "drawdown": {
            "ready": False,
            "max_dd_pct": None,
            "peak_date": None,
            "trough_date": None,
            "n": 0,
            "note": DRAWDOWN_NOTE,
        },
        "alerts": [],
    }


def _table_ready() -> bool:
    try:
        return "paper_positions" in db.schema_tables()
    except Exception:
        return False


def book_pnl() -> dict:
    if not _table_ready():
        return empty_pnl()
    raw = list_positions()
    if not raw:
        return empty_pnl()
    tagged = []
    unmarked = []
    for p in raw:
        src = normalize_source(p.get("source"))
        p = {**p, "source": src}
        if src == SOURCE_UNMARKED:
            unmarked.append(p)
        else:
            tagged.append(p)
    if not tagged:
        empty = empty_pnl()
        empty["count"] = len(unmarked)
        empty["unmarked_count"] = len(unmarked)
        empty["positions"] = [_mark_position(p) | {"omitted_from_pnl": True} for p in unmarked]
        for m in empty["positions"]:
            m.pop("_closes", None)
        empty["message"] = (
            "Unmarked lines omitted from P&L. Tag source as manual, fidelity_csv, or alpaca_paper. "
            "No invented P&L."
        )
        return empty
    marked = [_mark_position(p) for p in tagged]
    ready = [m for m in marked if m["ready"] and m["market_value"] is not None]
    long_mv = sum(m["market_value"] for m in ready if (m["qty"] or 0) > 0)
    short_mv = sum(abs(m["market_value"]) for m in ready if (m["qty"] or 0) < 0)
    net = long_mv - short_mv
    gross = long_mv + short_mv
    today = sum((m["day_pnl"] or 0.0) for m in ready if m["day_pnl"] is not None)
    prev_nav = 0.0
    have_prev = False
    for m in ready:
        if m["prev_price"] is not None and m["qty"] is not None:
            prev_nav += m["qty"] * m["prev_price"]
            have_prev = True
    today_pct = None
    if have_prev and abs(prev_nav) > 1e-9:
        today_pct = (today / abs(prev_nav)) * 100.0
    nav = net if ready else None
    curve = _equity_curve(marked)
    rets = _returns(curve)
    var_pack = {}
    if len(rets) >= MIN_RET:
        h95, _ = _hist_var(rets, 0.05)
        h99, _ = _hist_var(rets, 0.01)
        p95 = _param_var(rets, Z95)
        p99 = _param_var(rets, Z99)
        es = _cvar(rets, 0.05)
        scale = abs(nav) if nav is not None else None

        def pack(frac):
            if frac is None:
                return {"pct": None, "usd": None}
            return {
                "pct": _round(frac * 100.0, 3),
                "usd": _round(frac * scale, 2) if scale is not None else None,
            }

        var_pack = {
            "n": int(len(rets)),
            "hist_95": pack(h95),
            "hist_99": pack(h99),
            "param_95": pack(p95),
            "param_99": pack(p99),
            "es_95": pack(es),
            "note": "1-day VaR / ES from daily book NAV returns. Omitted under 20 days.",
        }
    dist = {
        "mean": _round(float(rets.mean()) * 100.0, 3) if len(rets) else None,
        "stdev": _round(float(rets.std(ddof=1)) * 100.0, 3) if len(rets) >= 2 else None,
        "skew": _round(_skew(rets), 3) if len(rets) >= 3 else None,
        "n": int(len(rets)),
        "bins": _histogram(rets),
    }
    concentration = _concentration(ready)
    drawdown = _max_drawdown(curve)
    alerts = _risk_alerts(concentration, drawdown)
    hmm_label = _spy_hmm_label() if ready else None
    for m in marked:
        mv = _finite(m.get("market_value"))
        m["weight_pct"] = _round(abs(mv) / gross * 100.0, 2) if mv is not None and gross > 0 else None
        frac = _fractal_read(m.get("symbol") or "", m.get("_closes") or []) if m.get("ready") else None
        m.update(_holding_opinion(m, hmm_label=hmm_label, fractal_read=frac))
        m.pop("_closes", None)
    tape = [
        {
            "symbol": m["symbol"],
            "day_pct": m["day_pct"],
            "day_pnl": m["day_pnl"],
            "ready": m["ready"],
            "vs_sma50": m.get("vs_sma50"),
            "rsi14": m.get("rsi14"),
            "fractal_read": m.get("fractal_read"),
            "hmm_label": m.get("hmm_label"),
            "weight_pct": m.get("weight_pct"),
        }
        for m in marked
    ]
    def pct_of_gross(part):
        if gross <= 0:
            return None
        return _round(part / gross * 100.0, 2)

    return {
        "ready": bool(ready),
        "desk_name": get_desk_name(),
        "note": NOTE,
        "message": None if ready else "Positions saved, but no stored closes to mark. Fetch Yahoo.",
        "count": len(marked),
        "marked_count": len(ready),
        "today_pnl": _round(today, 2) if ready else None,
        "today_pnl_pct": _round(today_pct, 2) if ready else None,
        "nav": _round(nav, 2),
        "exposure": {
            "gross": _round(gross, 2) or 0.0,
            "long": _round(long_mv, 2) or 0.0,
            "short": _round(short_mv, 2) or 0.0,
            "net": _round(net, 2) or 0.0,
            "gross_pct": 100.0 if gross else None,
            "long_pct": pct_of_gross(long_mv),
            "short_pct": pct_of_gross(short_mv),
            "net_pct": pct_of_gross(net) if net is not None else None,
        },
        "beta_spy": _beta_vs_spy(curve),
        "var": var_pack,
        "distribution": dist,
        "equity_curve": curve[-260:],
        "curve_label": "daily mark series from stored closes — no intraday bars",
        "positions": marked + [
            {k: v for k, v in {**_mark_position(p), "omitted_from_pnl": True}.items() if k != "_closes"}
            for p in unmarked
        ],
        "tape": tape,
        "sources": sorted({normalize_source(m.get("source")) for m in marked}),
        "unmarked_count": len(unmarked),
        "concentration": concentration,
        "drawdown": drawdown,
        "alerts": alerts,
    }
