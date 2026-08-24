"""
watchlist_filters.py — Smart watchlist rules (fundamental, price, setups, technicals).

Evaluates rules server-side against stored OHLCV. Use scope=with_data for universe scans.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import market_data as md
import portfolio

# ── Field catalog (for UI + validation) ───────────────────────────────────────

FILTER_CATALOG: List[dict] = [
    # Fundamental / meta
    {"id": "sector", "label": "Sector", "group": "Fundamental", "type": "string", "ops": ["eq", "ne", "contains", "in", "not_empty"]},
    {"id": "group_tag", "label": "Group tag", "group": "Fundamental", "type": "string", "ops": ["eq", "contains", "not_empty"]},
    {"id": "index_tag", "label": "Index tag (univ:*)", "group": "Fundamental", "type": "string", "ops": ["eq", "contains", "startswith"]},
    {"id": "peer_etf", "label": "Peer ETF", "group": "Fundamental", "type": "string", "ops": ["eq", "in"]},
    # Price
    {"id": "price", "label": "Price ($)", "group": "Price", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "change_pct", "label": "Day change %", "group": "Price", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "gap_pct", "label": "Gap % (open)", "group": "Price", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    # History / RS
    {"id": "ret_5d_pct", "label": "Return 5D %", "group": "History", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "ret_21d_pct", "label": "Return 21D %", "group": "History", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "rs_rank_21d", "label": "Book RS rank (1=best)", "group": "History", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_roc_1m", "label": "ROC 1M % (daily TF)", "group": "History", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_roc_3m", "label": "ROC 3M %", "group": "History", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_roc_6m", "label": "ROC 6M %", "group": "History", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    # Volume
    {"id": "vol_ratio_5_20", "label": "Vol today / 20D avg", "group": "Volume", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_vol_ratio", "label": "Vol ratio 5/20 (scanner)", "group": "Volume", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    # MA / structure
    {"id": "vs_kama20_pct", "label": "Price vs KAMA20 %", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "dist_20d_high_pct", "label": "Dist from 20D high %", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "dist_63d_high_pct", "label": "Dist from 63D high %", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_dist_hi", "label": "Dist from period high %", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_dist_sma", "label": "Dist from 200 SMA %", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_p_kf_pct", "label": "P/KAMA fast %ile", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_p_km_pct", "label": "P/KAMA med %ile", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_kf_km", "label": "KAMA fast/med cross %", "group": "MA / Structure", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    # RSI
    {"id": "rsi14", "label": "RSI(14)", "group": "RSI", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_rsi_7", "label": "RSI(7) daily", "group": "RSI", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_rsi_14", "label": "RSI(14) daily", "group": "RSI", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_rsi_21", "label": "RSI(21) daily", "group": "RSI", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "rsi_zone", "label": "RSI zone", "group": "RSI", "type": "enum", "ops": ["eq", "ne"], "values": ["overbought", "oversold", "bullish", "bearish", "neutral"]},
    # Regime
    {"id": "regime", "label": "Daily regime (KAMA)", "group": "Regime", "type": "enum", "ops": ["eq", "ne"], "values": ["uptrend", "downtrend", "range", "n/a"]},
    {"id": "regime_weekly", "label": "Weekly regime", "group": "Regime", "type": "enum", "ops": ["eq", "ne"], "values": ["uptrend", "downtrend", "range", "n/a"]},
    # Setups (bools + tags)
    {"id": "is_ep", "label": "EP (gap+vol)", "group": "Setups", "type": "bool", "ops": ["is_true", "is_false"]},
    {"id": "is_near_high", "label": "Near 20D high", "group": "Setups", "type": "bool", "ops": ["is_true", "is_false"]},
    {"id": "is_vol_surge", "label": "Volume surge", "group": "Setups", "type": "bool", "ops": ["is_true", "is_false"]},
    {"id": "breakout_score", "label": "Breakout score", "group": "Setups", "type": "number", "ops": ["gt", "gte", "eq"]},
    {"id": "darvas_state", "label": "Darvas state", "group": "Setups", "type": "enum", "ops": ["eq", "ne"], "values": ["in_box", "breakout", "failed"]},
    {"id": "setup", "label": "Setup tag", "group": "Setups", "type": "setup", "ops": ["has_setup"],
     "values": ["EP", "NEAR_HIGH", "VOL_SURGE", "BREAKOUT_QUEUE", "QULLA_BREAKOUT",
                "DARVAS_BOX", "DARVAS_BREAKOUT", "DARVAS_FAIL",
                "BRANDT_RISK_BOX", "BRANDT_RANGE",
                "STAGE_1", "STAGE_2", "STAGE_2_EARLY", "STAGE_3", "STAGE_4",
                "MINERVINI_TT", "MINERVINI_VCP", "MINERVINI_PIVOT",
                "STOCKBEE_EP", "STOCKBEE_RE", "STOCKBEE_EMA", "STOCKBEE_ANT",
                "RSI_OB", "RSI_OS"]},
    {"id": "stage", "label": "Weinstein stage (1–4)", "group": "Setups", "type": "number", "ops": ["eq", "in"]},
    {"id": "minervini_pass", "label": "Minervini Trend Template pass", "group": "Setups", "type": "bool", "ops": ["is_true", "is_false"]},
    {"id": "minervini_score", "label": "Minervini TT score (0–8)", "group": "Setups", "type": "number", "ops": ["gt", "gte", "lt", "lte", "eq"]},
    {"id": "badge", "label": "Methodology badge", "group": "Badges", "type": "badge", "ops": ["has_badge"],
     "values": ["KQ", "MM", "ON", "DB", "SB4", "SBW", "SB9", "52W", "2A", "2B", "97C"]},
    {"id": "rts", "label": "Book RTS (0–99)", "group": "Badges", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "strike_zone", "label": "Strike zone (near pivot)", "group": "Badges", "type": "bool", "ops": ["is_true", "is_false"]},
    # Technical
    {"id": "atr_pct", "label": "ATR %", "group": "Technical", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_atr_pct", "label": "ATR % (scanner)", "group": "Technical", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_bb_b", "label": "Bollinger %B", "group": "Technical", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
    {"id": "d_trend_score", "label": "Trend score", "group": "Technical", "type": "number", "ops": ["gt", "gte", "lt", "lte", "between"]},
]

PRESET_LISTS: List[dict] = [
    {
        "id": "preset_ep",
        "name": "EP today",
        "rules": [{"field": "is_ep", "op": "is_true"}],
        "match": "all",
    },
    {
        "id": "preset_near_high",
        "name": "Near 20D high",
        "rules": [{"field": "is_near_high", "op": "is_true"}],
        "match": "all",
    },
    {
        "id": "preset_breakout_queue",
        "name": "Breakout queue",
        "rules": [{"field": "setup", "op": "has_setup", "value": "BREAKOUT_QUEUE"}],
        "match": "all",
    },
    {
        "id": "preset_darvas_break",
        "name": "Darvas breakout",
        "rules": [{"field": "darvas_state", "op": "eq", "value": "breakout"}],
        "match": "all",
    },
    {
        "id": "preset_rsi_os",
        "name": "RSI oversold",
        "rules": [{"field": "rsi_zone", "op": "eq", "value": "oversold"}],
        "match": "all",
    },
    {
        "id": "preset_uptrend_near_high",
        "name": "Uptrend + near high",
        "rules": [
            {"field": "regime", "op": "eq", "value": "uptrend"},
            {"field": "is_near_high", "op": "is_true"},
        ],
        "match": "all",
    },
    {
        "id": "preset_vol_surge",
        "name": "Volume surge",
        "rules": [{"field": "is_vol_surge", "op": "is_true"}],
        "match": "all",
    },
    {
        "id": "preset_strong_rs",
        "name": "Top Book RS (≤20)",
        "rules": [{"field": "rs_rank_21d", "op": "lte", "value": 20}],
        "match": "all",
    },
    {
        "id": "preset_stage2",
        "name": "Stage 2 advancing",
        "rules": [{"field": "setup", "op": "has_setup", "value": "STAGE_2"}],
        "match": "all",
    },
    {
        "id": "preset_stage2_early",
        "name": "Early Stage 2 breakout",
        "rules": [{"field": "setup", "op": "has_setup", "value": "STAGE_2_EARLY"}],
        "match": "all",
    },
    {
        "id": "preset_stage1",
        "name": "Stage 1 basing",
        "rules": [{"field": "setup", "op": "has_setup", "value": "STAGE_1"}],
        "match": "all",
    },
    {
        "id": "preset_minervini_tt",
        "name": "Minervini Trend Template",
        "rules": [{"field": "setup", "op": "has_setup", "value": "MINERVINI_TT"}],
        "match": "all",
    },
    {
        "id": "preset_minervini_pivot",
        "name": "Minervini VCP pivot",
        "rules": [{"field": "setup", "op": "has_setup", "value": "MINERVINI_PIVOT"}],
        "match": "all",
    },
    {
        "id": "preset_stockbee_ep",
        "name": "Stockbee EP",
        "rules": [{"field": "setup", "op": "has_setup", "value": "STOCKBEE_EP"}],
        "match": "all",
    },
    {
        "id": "preset_stockbee_re",
        "name": "Stockbee range expansion",
        "rules": [{"field": "setup", "op": "has_setup", "value": "STOCKBEE_RE"}],
        "match": "all",
    },
    {
        "id": "badge_kq",
        "name": "KQ · Qullamaggie",
        "rules": [{"field": "badge", "op": "has_badge", "value": "KQ"}],
        "match": "all",
    },
    {
        "id": "badge_mm",
        "name": "MM · Minervini",
        "rules": [{"field": "badge", "op": "has_badge", "value": "MM"}],
        "match": "all",
    },
    {
        "id": "badge_sb4",
        "name": "SB4 · 4% day",
        "rules": [{"field": "badge", "op": "has_badge", "value": "SB4"}],
        "match": "all",
    },
    {
        "id": "badge_sbw",
        "name": "SBW · 20% week",
        "rules": [{"field": "badge", "op": "has_badge", "value": "SBW"}],
        "match": "all",
    },
    {
        "id": "badge_sb9",
        "name": "SB9 · 9M mover",
        "rules": [{"field": "badge", "op": "has_badge", "value": "SB9"}],
        "match": "all",
    },
    {
        "id": "badge_db",
        "name": "DB · Darvas breakout",
        "rules": [{"field": "badge", "op": "has_badge", "value": "DB"}],
        "match": "all",
    },
    {
        "id": "badge_on",
        "name": "ON · O'Neil proxy",
        "rules": [{"field": "badge", "op": "has_badge", "value": "ON"}],
        "match": "all",
    },
    {
        "id": "badge_2a",
        "name": "2A · Early Stage 2",
        "rules": [{"field": "badge", "op": "has_badge", "value": "2A"}],
        "match": "all",
    },
]


def _setups_from_row(row: dict) -> List[str]:
    setups: List[str] = []
    if row.get("is_ep"):
        setups.append("EP")
    if row.get("is_near_high"):
        setups.append("NEAR_HIGH")
    if row.get("is_vol_surge"):
        setups.append("VOL_SURGE")
    if row.get("is_near_high") or row.get("is_vol_surge"):
        setups.append("BREAKOUT_QUEUE")
    if row.get("is_near_high") and row.get("is_vol_surge"):
        setups.append("QULLA_BREAKOUT")
    box = row.get("darvas") or {}
    st = box.get("state")
    if st == "in_box":
        setups.append("DARVAS_BOX")
        setups.append("BRANDT_RISK_BOX")
    elif st == "breakout":
        setups.append("DARVAS_BREAKOUT")
        setups.append("BRANDT_RISK_BOX")
    elif st == "failed":
        setups.append("DARVAS_FAIL")
    if row.get("regime") == "range" and "BRANDT_RISK_BOX" not in setups:
        setups.append("BRANDT_RANGE")
    zone = row.get("rsi_zone")
    if zone == "overbought":
        setups.append("RSI_OB")
    elif zone == "oversold":
        setups.append("RSI_OS")
    stage_n = row.get("stage")
    if stage_n in (1, 2, 3, 4):
        setups.append(f"STAGE_{stage_n}")
    if row.get("early_stage2"):
        setups.append("STAGE_2_EARLY")
    for t in row.get("minervini_tags") or []:
        if t not in setups:
            setups.append(t)
    for t in row.get("stockbee_tags") or []:
        if t not in setups:
            setups.append(t)
    return setups


def enrich_row(sym: str, meta: dict) -> dict:
    snap = portfolio.snapshot_symbol(sym, light=False, include_scanner=True)
    row = dict(snap)
    row["group_tag"] = (meta.get("group_tag") or "").strip()
    row["sector"] = (meta.get("sector") or "").strip()
    row["name"] = (meta.get("name") or "").strip()
    tag = row["group_tag"]
    row["index_tag"] = tag if tag.startswith("univ:") else ""
    row["peer_etf"] = portfolio.peer_etf_for(row["sector"])
    box = row.get("darvas") or {}
    row["darvas_state"] = box.get("state")
    try:
        import stage_analysis
        st = stage_analysis.classify_stage(sym)
        row["stage"] = st.get("stage")
        row["stage_label"] = st.get("stage_label")
        row["early_stage2"] = st.get("early_stage2")
        row["vs_sma30_pct"] = st.get("vs_sma30_pct")
    except Exception:
        row["stage"] = 0
    try:
        import ta_templates
        tt = ta_templates.minervini_trend_template(sym)
        row["minervini_pass"] = bool(tt.get("pass")) if tt.get("ready") else False
        row["minervini_score"] = tt.get("score") if tt.get("ready") else None
        row["minervini_tags"] = tt.get("tags") or []
        row["vs_52w_high_pct"] = tt.get("vs_52w_high_pct")
        sb = ta_templates.stockbee_momentum(sym)
        row["stockbee_tags"] = sb.get("tags") or []
    except Exception:
        row["minervini_pass"] = False
        row["minervini_score"] = None
        row["minervini_tags"] = []
        row["stockbee_tags"] = []
    row["setups"] = _setups_from_row(row)
    try:
        import methodology_badges
        mx = methodology_badges.momentum_extras(sym)
        if row.get("ret_5d_pct") is None:
            row["ret_5d_pct"] = mx.get("ret_5d_pct")
        row["ret_9m_pct"] = mx.get("ret_9m_pct")
        if row.get("vs_52w_high_pct") is None:
            row["vs_52w_high_pct"] = mx.get("vs_52w_high_pct")
    except Exception:
        pass
    # Badges need Book RS — filled after ranking in apply_filter
    row["badge_codes"] = []
    row["badges"] = []
    return row


def _resolve_scope(scope: str) -> List[str]:
    if scope == "desk":
        return [s["symbol"] for s in md.list_desk_symbols()]
    if scope == "with_data":
        return md.list_symbols_with_ohlcv("daily", min_bars=30)
    if scope == "universe":
        return md.list_symbol_codes()
    return [s["symbol"] for s in md.list_symbols()]


def _compare(op: str, field_val: Any, rule_val: Any) -> bool:
    if op == "is_true":
        return bool(field_val)
    if op == "is_false":
        return not bool(field_val)
    if op == "not_empty":
        return field_val is not None and str(field_val).strip() != ""
    if op == "has_setup":
        setups = field_val if isinstance(field_val, list) else []
        return str(rule_val) in setups
    if op == "has_badge":
        codes = field_val if isinstance(field_val, list) else []
        return str(rule_val).upper() in [str(c).upper() for c in codes]
    if op == "startswith":
        return str(field_val or "").startswith(str(rule_val or ""))
    if op == "contains":
        return str(rule_val or "").lower() in str(field_val or "").lower()
    if op == "between":
        if not isinstance(rule_val, (list, tuple)) or len(rule_val) != 2:
            return False
        lo, hi = rule_val
        if field_val is None:
            return False
        try:
            v = float(field_val)
            return float(lo) <= v <= float(hi)
        except (TypeError, ValueError):
            return False
    if op == "in":
        if not isinstance(rule_val, list):
            rule_val = [rule_val]
        return field_val in rule_val or str(field_val) in [str(x) for x in rule_val]
    if field_val is None:
        return False
    if op == "eq":
        if isinstance(field_val, bool):
            return field_val == bool(rule_val)
        return str(field_val) == str(rule_val)
    if op == "ne":
        return not _compare("eq", field_val, rule_val)
    try:
        v = float(field_val)
        t = float(rule_val)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return v > t
    if op == "gte":
        return v >= t
    if op == "lt":
        return v < t
    if op == "lte":
        return v <= t
    return False


def _row_matches(row: dict, rules: List[dict], match: str) -> bool:
    if not rules:
        return True
    if not row.get("ready"):
        return False
    results = []
    for rule in rules:
        field = rule.get("field")
        op = rule.get("op")
        val = rule.get("value")
        if field == "setup":
            fv = row.get("setups")
        elif field == "badge":
            fv = row.get("badge_codes")
        elif field == "darvas_state":
            fv = row.get("darvas_state")
        else:
            fv = row.get(field)
        results.append(_compare(op, fv, val))
    return all(results) if match == "all" else any(results)


def apply_filter(
    rules: Optional[List[dict]] = None,
    match: str = "all",
    scope: str = "with_data",
    limit: int = 500,
    max_workers: int = 12,
) -> dict:
    symbols_meta = {s["symbol"]: s for s in md.list_symbols()}
    sym_list = _resolve_scope(scope)

    workers = min(max_workers, max(1, len(sym_list)))

    def _one(sym: str) -> dict:
        return enrich_row(sym, symbols_meta.get(sym, {}))

    rows: List[dict] = []
    if workers <= 1 or len(sym_list) <= 4:
        rows = [_one(s) for s in sym_list]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, s): s for s in sym_list}
            for fut in as_completed(futures):
                rows.append(fut.result())

    ready = [r for r in rows if r.get("ready")]
    ranked = sorted(
        ready,
        key=lambda r: (r.get("ret_21d_pct") is not None, r.get("ret_21d_pct") or -1e9),
        reverse=True,
    )
    for i, row in enumerate(ranked, start=1):
        row["rs_rank_21d"] = i
        row["rs_n"] = len(ranked)

    import methodology_badges
    for row in ready:
        bd = methodology_badges.badges_for_row(row, fetch_extras=False)
        row["badges"] = bd["badges"]
        row["badge_codes"] = bd["codes"]
        row["rts"] = bd["rts"]
        row["strike_zone"] = bd["strike_zone"]

    rules = rules or []
    matched = [r for r in rows if _row_matches(r, rules, match)]
    matched.sort(
        key=lambda r: (
            -(r.get("breakout_score") or 0),
            -(len(r.get("badge_codes") or [])),
            -(r.get("change_pct") or 0),
            r.get("symbol") or "",
        )
    )
    if limit and len(matched) > limit:
        matched = matched[:limit]

    # Slim payload for UI
    slim = []
    for r in matched:
        slim.append({
            "symbol": r["symbol"],
            "price": r.get("price"),
            "change_pct": r.get("change_pct"),
            "setups": r.get("setups"),
            "badges": r.get("badges"),
            "badge_codes": r.get("badge_codes"),
            "rts": r.get("rts"),
            "strike_zone": r.get("strike_zone"),
            "regime": r.get("regime"),
            "rsi14": r.get("rsi14"),
            "rs_rank_21d": r.get("rs_rank_21d"),
            "rs_n": r.get("rs_n"),
            "dist_20d_high_pct": r.get("dist_20d_high_pct"),
            "vol_ratio_5_20": r.get("vol_ratio_5_20"),
            "sector": r.get("sector"),
            "group_tag": r.get("group_tag"),
            "stage": r.get("stage"),
        })

    return {
        "count": len(matched),
        "scanned": len(sym_list),
        "scope": scope,
        "symbols": [r["symbol"] for r in matched],
        "results": slim,
    }


def catalog_for_api() -> dict:
    groups: Dict[str, List[dict]] = {}
    for f in FILTER_CATALOG:
        groups.setdefault(f["group"], []).append(f)
    sectors = sorted({
        (s.get("sector") or "").strip()
        for s in md.list_symbols()
        if (s.get("sector") or "").strip()
    })
    return {
        "fields": FILTER_CATALOG,
        "groups": groups,
        "sectors": sectors,
        "presets": PRESET_LISTS,
        "badge_catalog": __import__("methodology_badges").BADGE_CATALOG,
    }
