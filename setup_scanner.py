"""
setup_scanner.py — Named methodology setups + tags.

Families (honest, mechanical — not licensed signals):
  - Qullamaggie, Darvas, Brandt, Stage (Weinstein/Jacobs-style)
  - Minervini: Trend Template / VCP / pivot
  - Stockbee: EP / range expansion / 9–20 EMA / anticipation

Never claim IBD RS / CAN SLIM / official Factor, SEPA, or Stockbee MM signals.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import market_data as md
import methodology_badges
import portfolio
import stage_analysis
import ta_templates


SETUP_IDS = {
    "EP": "Gap ≥4% on ≥1.5× volume (EP path)",
    "NEAR_HIGH": "Within 5% of 20-day high",
    "VOL_SURGE": "Volume ≥1.5× 20-bar average",
    "BREAKOUT_QUEUE": "Near high and/or volume surge",
    "QULLA_BREAKOUT": "Near high + volume surge (momentum breakout)",
    "DARVAS_BOX": "Inside Darvas-style consolidation box",
    "DARVAS_BREAKOUT": "Close above Darvas box top",
    "DARVAS_FAIL": "Close below Darvas box low",
    "BRANDT_RISK_BOX": "Structural box levels for risk (entry/stop/target path)",
    "BRANDT_RANGE": "Daily range regime — wait for structure",
    "STAGE_1": "Stage 1 · Basing (weekly SMA30)",
    "STAGE_2": "Stage 2 · Advancing",
    "STAGE_2_EARLY": "Early Stage 2 · fresh breakout from base",
    "STAGE_3": "Stage 3 · Topping risk",
    "STAGE_4": "Stage 4 · Declining",
    "MINERVINI_TT": "Minervini Trend Template (≥7/8 book checks)",
    "MINERVINI_VCP": "Volatility contraction (ATR dry-up)",
    "MINERVINI_PIVOT": "VCP + near 20D high (pivot pressure)",
    "STOCKBEE_EP": "Stockbee-style EP (gap + volume)",
    "STOCKBEE_RE": "Range expansion day (TR ≫ ATR)",
    "STOCKBEE_EMA": "Close > EMA9 > EMA20",
    "STOCKBEE_ANT": "Anticipation coil after strength",
    "RSI_OB": "RSI overbought (swing alert)",
    "RSI_OS": "RSI oversold (swing alert)",
}

SETUP_FAMILIES = {
    "qullamaggie": {
        "label": "Qullamaggie",
        "blurb": "EP · near high · volume · breakout queue",
        "tags": ["EP", "NEAR_HIGH", "VOL_SURGE", "BREAKOUT_QUEUE", "QULLA_BREAKOUT"],
    },
    "minervini": {
        "label": "Minervini",
        "blurb": "Trend Template · VCP · pivot",
        "tags": ["MINERVINI_TT", "MINERVINI_VCP", "MINERVINI_PIVOT"],
    },
    "stockbee": {
        "label": "Stockbee",
        "blurb": "EP · range expansion · 9/20 EMA · anticipation",
        "tags": ["STOCKBEE_EP", "STOCKBEE_RE", "STOCKBEE_EMA", "STOCKBEE_ANT"],
    },
    "darvas": {
        "label": "Darvas",
        "blurb": "Box · breakout · fail",
        "tags": ["DARVAS_BOX", "DARVAS_BREAKOUT", "DARVAS_FAIL"],
    },
    "brandt": {
        "label": "Brandt",
        "blurb": "Risk box · range wait (structure first)",
        "tags": ["BRANDT_RISK_BOX", "BRANDT_RANGE"],
    },
    "stage": {
        "label": "Stage (1–4)",
        "blurb": "Weinstein-style weekly SMA30 stages",
        "tags": ["STAGE_1", "STAGE_2", "STAGE_2_EARLY", "STAGE_3", "STAGE_4"],
    },
}


def _scan_one_setup(symbol: str) -> Optional[dict]:
    try:
        snap = portfolio.snapshot_symbol(symbol.upper(), light=False)
        if not snap.get("ready"):
            return {
                "symbol": symbol.upper(),
                "ready": False,
                "error": snap.get("error", "No data"),
                "setups": [],
                "families": [],
            }

        setups: list[str] = []
        families: list[str] = []

        # ── Qullamaggie path ──────────────────────────────────────────
        if snap.get("is_ep"):
            setups.append("EP")
        if snap.get("is_near_high"):
            setups.append("NEAR_HIGH")
        if snap.get("is_vol_surge"):
            setups.append("VOL_SURGE")
        if snap.get("is_near_high") or snap.get("is_vol_surge"):
            setups.append("BREAKOUT_QUEUE")
        if snap.get("is_near_high") and snap.get("is_vol_surge"):
            setups.append("QULLA_BREAKOUT")
        if any(t in setups for t in ("EP", "NEAR_HIGH", "VOL_SURGE", "BREAKOUT_QUEUE", "QULLA_BREAKOUT")):
            families.append("qullamaggie")

        # ── Darvas ────────────────────────────────────────────────────
        box = snap.get("darvas") or {}
        state = box.get("state")
        if state == "in_box":
            setups.append("DARVAS_BOX")
        elif state == "breakout":
            setups.append("DARVAS_BREAKOUT")
        elif state == "failed":
            setups.append("DARVAS_FAIL")
        if state in ("in_box", "breakout", "failed"):
            families.append("darvas")

        # ── Brandt (structural risk / range) ──────────────────────────
        if state in ("in_box", "breakout") and box.get("top") and box.get("bottom"):
            setups.append("BRANDT_RISK_BOX")
            families.append("brandt")
        if snap.get("regime") == "range" and "brandt" not in families:
            setups.append("BRANDT_RANGE")
            families.append("brandt")

        # ── Stage analysis ────────────────────────────────────────────
        st = stage_analysis.classify_stage(symbol)
        stage_n = st.get("stage") or 0
        if stage_n in (1, 2, 3, 4):
            setups.append(f"STAGE_{stage_n}")
            families.append("stage")
        if st.get("early_stage2"):
            setups.append("STAGE_2_EARLY")
            if "stage" not in families:
                families.append("stage")

        # ── Minervini (Trend Template / VCP) ──────────────────────────
        tt = ta_templates.minervini_trend_template(symbol)
        for tag in tt.get("tags") or []:
            setups.append(tag)
        if tt.get("tags"):
            families.append("minervini")

        # ── Stockbee (EP / RE / EMA / anticipation) ───────────────────
        sb = ta_templates.stockbee_momentum(symbol)
        for tag in sb.get("tags") or []:
            setups.append(tag)
        if sb.get("tags"):
            families.append("stockbee")

        # Momentum extras for SBW / SB9 / 52W badges (one OHLCV read)
        mx = methodology_badges.momentum_extras(symbol)
        ret_5d = snap.get("ret_5d_pct")
        if ret_5d is None:
            ret_5d = mx.get("ret_5d_pct")
        vs_52 = tt.get("vs_52w_high_pct") if tt.get("ready") else None
        if vs_52 is None:
            vs_52 = mx.get("vs_52w_high_pct")

        zone = snap.get("rsi_zone")
        if zone == "overbought":
            setups.append("RSI_OB")
        elif zone == "oversold":
            setups.append("RSI_OS")

        score = snap.get("breakout_score") or 0
        if state == "breakout":
            score += 2
        if "QULLA_BREAKOUT" in setups:
            score += 2
        if "MINERVINI_TT" in setups:
            score += 2
        if "MINERVINI_PIVOT" in setups:
            score += 1
        if "STOCKBEE_EP" in setups or "STOCKBEE_RE" in setups:
            score += 1
        if stage_n == 2:
            score += 1
        if state == "in_box" and snap.get("dist_20d_high_pct") is not None:
            if snap["dist_20d_high_pct"] >= -2:
                score += 1

        return {
            "symbol": snap["symbol"],
            "ready": True,
            "price": snap.get("price"),
            "change_pct": snap.get("change_pct"),
            "setups": setups,
            "families": families,
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
            "stage": stage_n,
            "stage_label": st.get("stage_label"),
            "vs_sma30_pct": st.get("vs_sma30_pct"),
            "sma30_slope_pct": st.get("sma30_slope_pct"),
            "minervini_score": tt.get("score") if tt.get("ready") else None,
            "minervini_pass": tt.get("pass") if tt.get("ready") else None,
            "stockbee_tags": sb.get("tags") if sb.get("ready") else [],
            "ret_5d_pct": ret_5d,
            "ret_9m_pct": mx.get("ret_9m_pct"),
            "vs_52w_high_pct": vs_52,
            "is_near_high": bool(snap.get("is_near_high")),
            "is_vol_surge": bool(snap.get("is_vol_surge")),
            "is_ep": bool(snap.get("is_ep")),
            "early_stage2": bool(st.get("early_stage2")),
        }
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "ready": False,
            "error": str(exc),
            "setups": [],
            "families": [],
        }


def _filter_and_rollup(
    results: list[dict],
    *,
    symbols_scanned: int,
    setup_filter: Optional[str] = None,
    family: Optional[str] = None,
    stage: Optional[int] = None,
    badge: Optional[str] = None,
    limit: int = 500,
    min_score: int = 0,
    from_cache: bool = False,
) -> dict:
    filtered = []
    for row in results:
        if not row:
            continue
        if setup_filter and setup_filter not in row.get("setups", []):
            continue
        if family and family not in row.get("families", []):
            continue
        if stage is not None and row.get("stage") != stage:
            continue
        if row.get("setup_score", 0) < min_score:
            continue
        filtered.append(row)

    filtered.sort(
        key=lambda r: (
            -(r.get("setup_score") or 0),
            -(r.get("change_pct") or 0),
            r.get("symbol") or "",
        )
    )

    ready = [r for r in filtered if r.get("ready")]
    # Re-rank RS within the filtered set only when live-computed;
    # cache rows already have book-wide RS from precompute.
    if not from_cache:
        ranked = sorted(
            ready,
            key=lambda r: (r.get("ret_21d_pct") is not None, r.get("ret_21d_pct") or -1e9),
            reverse=True,
        )
        for i, row in enumerate(ranked, start=1):
            row["rs_rank_21d"] = i
            row["rs_n"] = len(ranked)

    badge_counts = {k: 0 for k in methodology_badges.BADGE_CATALOG}
    for r in ready:
        if not r.get("badge_codes"):
            bd = methodology_badges.badges_for_row(r, fetch_extras=False)
            r["badges"] = bd["badges"]
            r["badge_codes"] = bd["codes"]
            r["rts"] = bd["rts"]
            r["strike_zone"] = bd["strike_zone"]
        for c in r.get("badge_codes") or []:
            if c in badge_counts:
                badge_counts[c] += 1

    if badge:
        badge_u = badge.upper()
        filtered = [r for r in filtered if badge_u in (r.get("badge_codes") or [])]
        ready = [r for r in filtered if r.get("ready")]

    if limit and len(filtered) > limit:
        filtered = filtered[:limit]

    family_counts = {k: 0 for k in SETUP_FAMILIES}
    stage_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for r in ready:
        for f in r.get("families") or []:
            if f in family_counts:
                family_counts[f] += 1
        st = r.get("stage")
        if st in stage_counts:
            stage_counts[st] += 1

    return {
        "count": len(filtered),
        "scanned": symbols_scanned,
        "setup_filter": setup_filter,
        "family": family,
        "stage": stage,
        "badge": badge,
        "results": filtered,
        "setup_catalog": SETUP_IDS,
        "families": SETUP_FAMILIES,
        "family_counts": family_counts,
        "stage_counts": stage_counts,
        "stage_labels": stage_analysis.STAGE_LABELS,
        "badge_catalog": methodology_badges.BADGE_CATALOG,
        "badge_counts": badge_counts,
        "from_cache": from_cache,
    }


def scan_setups(
    symbols: Optional[list[str]] = None,
    setup_filter: Optional[str] = None,
    family: Optional[str] = None,
    stage: Optional[int] = None,
    badge: Optional[str] = None,
    limit: int = 500,
    min_score: int = 0,
    use_cache: bool = True,
    live: bool = False,
) -> dict:
    """
    Scan symbols for setup tags / families / stage / badges.

    Default: serve precomputed `symbol_metrics` (fast dashboard).
    Pass live=True or use_cache=False to recompute on the fly.
    """
    if symbols is None:
        symbols = md.list_symbols_with_ohlcv("daily", min_bars=30)
    else:
        symbols = [s.upper() for s in symbols]

    if use_cache and not live:
        try:
            import desk_metrics
            cached = desk_metrics.load_cached_rows(symbols, ready_only=False)
            # If we have decent coverage, serve cache (even partial)
            if cached and len(cached) >= max(1, int(0.5 * len(symbols))):
                by_sym = {r["symbol"]: r for r in cached if r.get("symbol")}
                results = [by_sym[s] for s in symbols if s in by_sym]
                return _filter_and_rollup(
                    results,
                    symbols_scanned=len(symbols),
                    setup_filter=setup_filter,
                    family=family,
                    stage=stage,
                    badge=badge,
                    limit=limit,
                    min_score=min_score,
                    from_cache=True,
                )
        except Exception:
            pass

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_one_setup, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)

    return _filter_and_rollup(
        results,
        symbols_scanned=len(symbols),
        setup_filter=setup_filter,
        family=family,
        stage=stage,
        badge=badge,
        limit=limit,
        min_score=min_score,
        from_cache=False,
    )
