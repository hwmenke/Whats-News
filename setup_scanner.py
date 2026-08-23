"""
setup_scanner.py — Scan stored universe for trading setups (not generic metrics only).

Setups are honest labels from portfolio/darvas metrics — not IBD/CAN SLIM claims.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import market_data as md
import portfolio


SETUP_IDS = {
    "EP": "Gap ≥4% on ≥1.5× volume (episodic pivot path)",
    "NEAR_HIGH": "Within 5% of 20-day high",
    "VOL_SURGE": "Volume ≥1.5× 20-bar average",
    "BREAKOUT_QUEUE": "Near high and/or volume surge (momentum tape rule)",
    "DARVAS_BOX": "Inside Darvas-style consolidation box",
    "DARVAS_BREAKOUT": "Close above box top",
    "DARVAS_FAIL": "Close below box low",
    "RSI_OB": "RSI overbought (swing alert)",
    "RSI_OS": "RSI oversold (swing alert)",
}


def _scan_one_setup(symbol: str) -> Optional[dict]:
    try:
        snap = portfolio.snapshot_symbol(symbol.upper())
        if not snap.get("ready"):
            return {
                "symbol": symbol.upper(),
                "ready": False,
                "error": snap.get("error", "No data"),
                "setups": [],
            }

        setups: list[str] = []
        if snap.get("is_ep"):
            setups.append("EP")
        if snap.get("is_near_high"):
            setups.append("NEAR_HIGH")
        if snap.get("is_vol_surge"):
            setups.append("VOL_SURGE")
        if snap.get("is_near_high") or snap.get("is_vol_surge"):
            setups.append("BREAKOUT_QUEUE")

        box = snap.get("darvas") or {}
        state = box.get("state")
        if state == "in_box":
            setups.append("DARVAS_BOX")
        elif state == "breakout":
            setups.append("DARVAS_BREAKOUT")
        elif state == "failed":
            setups.append("DARVAS_FAIL")

        zone = snap.get("rsi_zone")
        if zone == "overbought":
            setups.append("RSI_OB")
        elif zone == "oversold":
            setups.append("RSI_OS")

        score = snap.get("breakout_score") or 0
        if state == "breakout":
            score += 2
        if state == "in_box" and snap.get("dist_20d_high_pct") is not None:
            if snap["dist_20d_high_pct"] >= -2:
                score += 1

        return {
            "symbol": snap["symbol"],
            "ready": True,
            "price": snap.get("price"),
            "change_pct": snap.get("change_pct"),
            "setups": setups,
            "setup_count": len(setups),
            "setup_score": score,
            "rs_rank_21d": snap.get("rs_rank_21d"),
            "rs_n": snap.get("rs_n"),
            "dist_20d_high_pct": snap.get("dist_20d_high_pct"),
            "vol_ratio_5_20": snap.get("vol_ratio_5_20"),
            "gap_pct": snap.get("gap_pct"),
            "regime": snap.get("regime"),
            "regime_weekly": snap.get("regime_weekly"),
            "ret_21d_pct": snap.get("ret_21d_pct"),
            "darvas_state": state,
            "darvas_top": box.get("top"),
            "darvas_bottom": box.get("bottom"),
        }
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "ready": False,
            "error": str(exc),
            "setups": [],
        }


def scan_setups(
    symbols: Optional[list[str]] = None,
    setup_filter: Optional[str] = None,
    limit: int = 500,
    min_score: int = 0,
) -> dict:
    """
    Scan symbols with stored OHLCV for setup tags.
    Default symbol list: all names with ≥30 daily bars in DB.
    """
    if symbols is None:
        symbols = md.list_symbols_with_ohlcv("daily", min_bars=30)
    else:
        symbols = [s.upper() for s in symbols]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_one_setup, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            row = fut.result()
            if not row:
                continue
            if setup_filter and setup_filter not in row.get("setups", []):
                continue
            if row.get("setup_score", 0) < min_score:
                continue
            results.append(row)

    results.sort(
        key=lambda r: (
            -(r.get("setup_score") or 0),
            -(r.get("change_pct") or 0),
            r.get("symbol") or "",
        )
    )

    ready = [r for r in results if r.get("ready")]
    ranked = sorted(
        ready,
        key=lambda r: (r.get("ret_21d_pct") is not None, r.get("ret_21d_pct") or -1e9),
        reverse=True,
    )
    for i, row in enumerate(ranked, start=1):
        row["rs_rank_21d"] = i
        row["rs_n"] = len(ranked)

    if limit and len(results) > limit:
        results = results[:limit]

    return {
        "count": len(results),
        "scanned": len(symbols),
        "setup_filter": setup_filter,
        "results": results,
        "setup_catalog": SETUP_IDS,
    }
