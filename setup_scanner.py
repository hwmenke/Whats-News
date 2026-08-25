"""
setup_scanner.py — Named methodology setups + tags.

Families (honest, mechanical — not licensed signals):
  - Qullamaggie, Darvas, Brandt, Stage (Weinstein/Jacobs-style)
  - Minervini: Trend Template / VCP / pivot
  - Stockbee: EP / range expansion / 9–20 EMA / anticipation

Never claim IBD RS / CAN SLIM / official Factor, SEPA, or Stockbee MM signals.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import market_data as md
import methodology_badges
import portfolio
import stage_analysis
import ta_templates

log = logging.getLogger(__name__)

# Serve cache when at least this fraction of the requested universe is ready.
CACHE_COVERAGE_MIN = 0.5


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
    "TIGHT_COIL": "Near high + dry volume / VCP / anticipation (triage)",
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
        "tags": ["STOCKBEE_EP", "STOCKBEE_RE", "STOCKBEE_EMA", "STOCKBEE_ANT", "TIGHT_COIL"],
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


def _r_to_box(price, box_low, atr) -> Optional[float]:
    """How many 1.5×ATR units from price down to the Darvas/box low."""
    if price is None or box_low is None or atr is None or atr <= 0:
        return None
    dist = float(price) - float(box_low)
    unit = 1.5 * float(atr)
    if unit <= 0:
        return None
    return round(dist / unit, 2)


def _scan_one_setup(symbol: str) -> Optional[dict]:
    try:
        sym = symbol.upper()
        daily = md.get_ohlcv_df(sym, "daily", limit=280)
        weekly = md.get_ohlcv_df(sym, "weekly", limit=160)
        snap = portfolio.snapshot_symbol(sym, light=False, include_scanner=True, df=daily, weekly_df=weekly)
        if not snap.get("ready"):
            return {
                "symbol": sym,
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
        st = stage_analysis.classify_stage(sym, df=weekly)
        stage_n = st.get("stage") or 0
        if stage_n in (1, 2, 3, 4):
            setups.append(f"STAGE_{stage_n}")
            families.append("stage")
        if st.get("early_stage2"):
            setups.append("STAGE_2_EARLY")
            if "stage" not in families:
                families.append("stage")

        # ── Minervini (Trend Template / VCP) ──────────────────────────
        tt = ta_templates.minervini_trend_template(sym, df=daily)
        for tag in tt.get("tags") or []:
            setups.append(tag)
        if tt.get("tags"):
            families.append("minervini")

        # ── Stockbee (EP / RE / EMA / anticipation) ───────────────────
        sb = ta_templates.stockbee_momentum(sym, df=daily)
        for tag in sb.get("tags") or []:
            setups.append(tag)
        if sb.get("tags"):
            families.append("stockbee")

        vol_dry = bool(tt.get("vol_dry"))
        if "STOCKBEE_ANT" in setups or (
            tt.get("vcp") and snap.get("is_near_high") and vol_dry
        ):
            setups.append("TIGHT_COIL")
            if "stockbee" not in families:
                families.append("stockbee")

        # Momentum extras for SBW / SB9 / 52W badges (reuse daily bars)
        mx = methodology_badges.momentum_extras(sym, df=daily)
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
        if "TIGHT_COIL" in setups:
            score += 1
        if stage_n == 2:
            score += 1
        if state == "in_box" and snap.get("dist_20d_high_pct") is not None:
            if snap["dist_20d_high_pct"] >= -2:
                score += 1

        atr = snap.get("atr14")
        stop = snap.get("stop_long_1_5atr")
        r_box = _r_to_box(snap.get("price"), box.get("bottom"), atr)

        payload = {
            "symbol": snap["symbol"],
            "ready": True,
            "as_of": snap.get("as_of"),
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
            "atr14": atr,
            "atr_pct": snap.get("atr_pct"),
            "stop_long_1_5atr": stop,
            "rsi14": snap.get("rsi14"),
            "rsi_zone": zone,
            "vol_dry": vol_dry,
            "r_to_box": r_box,
            "ep_quality": (
                "strong" if (snap.get("gap_pct") or 0) >= 4 and (snap.get("vol_ratio_5_20") or 0) >= 2
                else ("soft" if snap.get("is_ep") else None)
            ),
            "vs_kama20_pct": snap.get("vs_kama20_pct"),
            "kama20": snap.get("kama20"),
            "dist_63d_high_pct": snap.get("dist_63d_high_pct"),
            "pct_off_20d_high_pct": snap.get("pct_off_20d_high_pct"),
            "breakout_score": snap.get("breakout_score"),
            "dollar_vol_20d": snap.get("dollar_vol_20d"),
        }
        for key, val in snap.items():
            if key.startswith("d_") and key not in payload:
                payload[key] = val
        return payload
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
    min_change: Optional[float] = None,
    max_change: Optional[float] = None,
    min_vol: Optional[float] = None,
    max_rs: Optional[int] = None,
    min_rts: Optional[int] = None,
    regime: Optional[str] = None,
    strike: bool = False,
    dual_up: bool = False,
    rsi_extreme: bool = False,
) -> dict:
    filtered = []
    for row in results:
        if not row:
            continue
        if rsi_extreme:
            setups = row.get("setups") or []
            if "RSI_OB" not in setups and "RSI_OS" not in setups:
                continue
        elif setup_filter and setup_filter not in row.get("setups", []):
            continue
        if family and family not in row.get("families", []):
            continue
        if stage is not None and row.get("stage") != stage:
            continue
        if row.get("setup_score", 0) < min_score:
            continue
        chg = row.get("change_pct")
        if min_change is not None and (chg is None or chg < min_change):
            continue
        if max_change is not None and (chg is None or chg > max_change):
            continue
        vol = row.get("vol_ratio_5_20")
        if min_vol is not None and (vol is None or vol < min_vol):
            continue
        rs = row.get("rs_rank_21d")
        if max_rs is not None and (rs is None or rs > max_rs):
            continue
        if regime and row.get("regime") != regime:
            continue
        if dual_up and not (
            row.get("regime") == "uptrend" and row.get("regime_weekly") == "uptrend"
        ):
            continue
        filtered.append(row)

    filtered.sort(
        key=lambda r: (
            -(r.get("setup_score") or 0),
            -(r.get("rts") if r.get("rts") is not None else -1),
            -(r.get("change_pct") or 0),
            r.get("symbol") or "",
        )
    )

    ready = [r for r in filtered if r.get("ready")]
    # Rank Book RS / RTS against the *unfiltered* incoming set so a live
    # scan cannot mint "97 Club" inside a 30-name subset. Cache rows already
    # carry universe ranks from desk_metrics.finalize_payloads.
    if not from_cache:
        universe = [r for r in results if r and r.get("ready")]
        ranked = sorted(
            universe,
            key=lambda r: (r.get("ret_21d_pct") is not None, r.get("ret_21d_pct") or -1e9),
            reverse=True,
        )
        n = len(ranked)
        rank_of = {id(r): i for i, r in enumerate(ranked, start=1)}
        for row in universe:
            row["rs_rank_21d"] = rank_of.get(id(row))
            row["rs_n"] = n

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

    if min_rts is not None:
        filtered = [
            r for r in filtered
            if r.get("rts") is not None and r.get("rts") >= min_rts
        ]
        ready = [r for r in filtered if r.get("ready")]

    if strike:
        filtered = [r for r in filtered if r.get("strike_zone")]
        ready = [r for r in filtered if r.get("ready")]

    if badge:
        badge_u = badge.upper()
        filtered = [r for r in filtered if badge_u in (r.get("badge_codes") or [])]
        ready = [r for r in filtered if r.get("ready")]

    if limit and len(filtered) > limit:
        total_matched = len(filtered)
        filtered = filtered[:limit]
    else:
        total_matched = len(filtered)

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
        "total_matched": total_matched,
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
    min_change: Optional[float] = None,
    max_change: Optional[float] = None,
    min_vol: Optional[float] = None,
    max_rs: Optional[int] = None,
    min_rts: Optional[int] = None,
    regime: Optional[str] = None,
    strike: bool = False,
    dual_up: bool = False,
    rsi_extreme: bool = False,
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

    filter_kw = dict(
        setup_filter=setup_filter,
        family=family,
        stage=stage,
        badge=badge,
        limit=limit,
        min_score=min_score,
        min_change=min_change,
        max_change=max_change,
        min_vol=min_vol,
        max_rs=max_rs,
        min_rts=min_rts,
        regime=regime,
        strike=strike,
        dual_up=dual_up,
        rsi_extreme=rsi_extreme,
    )

    if use_cache and not live:
        try:
            import desk_metrics
            cached = desk_metrics.load_cached_rows(symbols, ready_only=False)
            ready_n = sum(1 for r in cached if r.get("ready"))
            coverage = (ready_n / len(symbols)) if symbols else 0.0
            if cached and coverage >= CACHE_COVERAGE_MIN:
                by_sym = {r["symbol"]: r for r in cached if r.get("symbol")}
                results = [by_sym[s] for s in symbols if s in by_sym]
                out = _filter_and_rollup(
                    results,
                    symbols_scanned=len(symbols),
                    from_cache=True,
                    **filter_kw,
                )
                out["market_context"] = desk_metrics.market_context(results)
                out["cache"] = {
                    "coverage_pct": round(100.0 * coverage, 1),
                    "ready": ready_n,
                    "requested": len(symbols),
                    "min_coverage": CACHE_COVERAGE_MIN,
                    **desk_metrics.freshness_meta(results),
                }
                return out
        except Exception:
            log.exception("metrics cache serve failed; falling back to live scan")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_scan_one_setup, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)

    out = _filter_and_rollup(
        results,
        symbols_scanned=len(symbols),
        from_cache=False,
        **filter_kw,
    )
    try:
        import desk_metrics
        out["market_context"] = desk_metrics.market_context(results)
    except Exception:
        out["market_context"] = None
    out["cache"] = {"coverage_pct": 0, "ready": 0, "requested": len(symbols), "freshness": "live"}
    return out
