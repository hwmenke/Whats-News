"""
desk_metrics.py — Precompute symbol metrics for a fast dashboard.

Heavy work (snapshot + stage + Minervini + Stockbee + badges) runs once into
`symbol_metrics`. Setups board, smart lists, and desk tape then read the cache.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import data_client as dc
import methodology_badges
import setup_scanner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_one(symbol: str) -> dict:
    """Compute one metrics row (payload = full scan row without RS/badges)."""
    row = setup_scanner._scan_one_setup(symbol)
    if not row:
        row = {"symbol": symbol.upper(), "ready": False, "error": "empty", "setups": [], "families": []}
    as_of = None
    try:
        as_of = dc.get_ohlcv(symbol, "daily", limit=1)
        if as_of:
            as_of = as_of[-1].get("date")
    except Exception:
        as_of = None

    payload = dict(row)
    # RS / badges filled in finalize_batch
    payload.pop("rs_rank_21d", None)
    payload.pop("rs_n", None)
    payload.pop("badges", None)
    payload.pop("badge_codes", None)
    payload.pop("rts", None)
    payload.pop("strike_zone", None)

    return {
        "symbol": payload.get("symbol") or symbol.upper(),
        "ready": bool(payload.get("ready")),
        "as_of": as_of,
        "updated_at": _now(),
        "price": payload.get("price"),
        "change_pct": payload.get("change_pct"),
        "ret_5d_pct": payload.get("ret_5d_pct"),
        "ret_21d_pct": payload.get("ret_21d_pct"),
        "ret_9m_pct": payload.get("ret_9m_pct"),
        "stage": payload.get("stage"),
        "setup_score": payload.get("setup_score") or 0,
        "payload": payload,
    }


def finalize_payloads(rows: list[dict]) -> list[dict]:
    """Assign Book RS ranks + methodology badges across a batch."""
    ready = [r for r in rows if r.get("ready") and isinstance(r.get("payload"), dict)]
    ranked = sorted(
        ready,
        key=lambda r: (
            r["payload"].get("ret_21d_pct") is not None,
            r["payload"].get("ret_21d_pct") or -1e9,
        ),
        reverse=True,
    )
    n = len(ranked)
    for i, r in enumerate(ranked, start=1):
        p = r["payload"]
        p["rs_rank_21d"] = i
        p["rs_n"] = n
        bd = methodology_badges.badges_for_row(p, fetch_extras=False)
        p["badges"] = bd["badges"]
        p["badge_codes"] = bd["codes"]
        p["rts"] = bd["rts"]
        p["strike_zone"] = bd["strike_zone"]
        r["payload"] = p
    return rows


def refresh_symbols(
    symbols: Optional[list[str]] = None,
    max_workers: int = 8,
    limit: int = 0,
    progress_cb=None,
) -> dict:
    """
    Precompute metrics for symbols (default: all with daily OHLCV).
    Returns {ok, failed, total, updated_at, status}.
    """
    if symbols is None:
        symbols = dc.list_symbols_with_ohlcv("daily", min_bars=30)
    else:
        symbols = [s.upper() for s in symbols]
    if limit and limit > 0:
        symbols = symbols[:limit]

    total = len(symbols)
    ok = fail = 0
    computed: list[dict] = []
    workers = min(max_workers, max(1, total))

    def _one(sym: str) -> dict:
        try:
            return compute_one(sym)
        except Exception as exc:
            return {
                "symbol": sym,
                "ready": False,
                "updated_at": _now(),
                "setup_score": 0,
                "payload": {"symbol": sym, "ready": False, "error": str(exc), "setups": [], "families": []},
            }

    if workers <= 1 or total <= 3:
        for i, sym in enumerate(symbols):
            row = _one(sym)
            computed.append(row)
            if row.get("ready"):
                ok += 1
            else:
                fail += 1
            if progress_cb:
                progress_cb(i + 1, total, sym, bool(row.get("ready")))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, sym): sym for sym in symbols}
            done = 0
            for fut in as_completed(futures):
                sym = futures[fut]
                row = fut.result()
                computed.append(row)
                done += 1
                if row.get("ready"):
                    ok += 1
                else:
                    fail += 1
                if progress_cb:
                    progress_cb(done, total, sym, bool(row.get("ready")))

    finalize_payloads(computed)
    # Upsert in chunks
    chunk = 200
    written = 0
    for i in range(0, len(computed), chunk):
        written += dc.upsert_symbol_metrics(computed[i:i + chunk])

    status = dc.metrics_status()
    return {
        "ok": ok,
        "failed": fail,
        "total": total,
        "written": written,
        "updated_at": status.get("updated_at"),
        "status": status,
    }


def load_cached_rows(
    symbols: Optional[list[str]] = None,
    ready_only: bool = True,
) -> list[dict]:
    """Return decoded payload dicts from the metrics cache."""
    rows = dc.get_symbol_metrics_many(symbols, ready_only=ready_only)
    out = []
    for r in rows:
        p = r.get("payload") or {}
        if not isinstance(p, dict):
            continue
        # Prefer indexed columns when payload is thin
        p.setdefault("symbol", r.get("symbol"))
        p.setdefault("price", r.get("price"))
        p.setdefault("change_pct", r.get("change_pct"))
        p.setdefault("ret_5d_pct", r.get("ret_5d_pct"))
        p.setdefault("ret_21d_pct", r.get("ret_21d_pct"))
        p.setdefault("ret_9m_pct", r.get("ret_9m_pct"))
        p.setdefault("stage", r.get("stage"))
        p.setdefault("setup_score", r.get("setup_score"))
        p["metrics_updated_at"] = r.get("updated_at")
        p["metrics_as_of"] = r.get("as_of")
        p["from_cache"] = True
        out.append(p)
    return out


def cache_coverage(symbols: Optional[list[str]] = None) -> dict:
    status = dc.metrics_status()
    if symbols is None:
        universe = dc.list_symbols_with_ohlcv("daily", min_bars=30)
    else:
        universe = [s.upper() for s in symbols]
    cached = {r["symbol"] for r in dc.get_symbol_metrics_many(universe, ready_only=True)}
    missing = [s for s in universe if s not in cached]
    return {
        **status,
        "universe": len(universe),
        "cached": len(cached),
        "missing": len(missing),
        "coverage_pct": round(100.0 * len(cached) / len(universe), 1) if universe else 0.0,
        "missing_sample": missing[:20],
    }
