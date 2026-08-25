"""
methodology_badges.py — Compact watchlist badges (KQ / MM / SB4 / …).

Inspired by momentum-desk badge rows: short codes that stack on a ticker so
you can scan overlaps and generate smart lists from one click.

Honest labels only — mechanical book proxies, not licensed products.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import market_data as md


# Catalog shown in UI / filter dropdowns
BADGE_CATALOG: Dict[str, dict] = {
    "KQ": {
        "label": "Qullamaggie",
        "blurb": "Near high + volume (momentum breakout path)",
        "tone": "kq",
        "kind": "method",
    },
    "MM": {
        "label": "Minervini",
        "blurb": "Trend Template pass (≥7/8 book checks)",
        "tone": "mm",
        "kind": "method",
    },
    "ON": {
        "label": "O'Neil",
        "blurb": "Stage 2 + near high + strong Book RS (growth proxy)",
        "tone": "on",
        "kind": "method",
    },
    "DB": {
        "label": "Darvas breakout",
        "blurb": "Close above Darvas box top",
        "tone": "db",
        "kind": "method",
    },
    "SB4": {
        "label": "Stockbee 4% day",
        "blurb": "Day change or gap ≥4%",
        "tone": "sb",
        "kind": "method",
    },
    "SBW": {
        "label": "Stockbee 20% week",
        "blurb": "≈5-session return ≥20%",
        "tone": "sb",
        "kind": "method",
    },
    "SB9": {
        "label": "Stockbee 9M mover",
        "blurb": "≈9-month return ≥100%",
        "tone": "sb",
        "kind": "method",
    },
    "52W": {
        "label": "Near 52-week high",
        "blurb": "Within ~10% of 52-week high",
        "tone": "hi",
        "kind": "method",
    },
    "2A": {
        "label": "Stage 2A",
        "blurb": "Early Stage 2 (fresh breakout from base)",
        "tone": "stage",
        "kind": "stage",
    },
    "2B": {
        "label": "Stage 2B",
        "blurb": "Stage 2 advancing (established)",
        "tone": "stage",
        "kind": "stage",
    },
    "97C": {
        "label": "97 Club",
        "blurb": "Book RTS ≥97 (top ~3% of scanned book)",
        "tone": "rts",
        "kind": "method",
    },
}


def book_rts(rs_rank: Optional[int], rs_n: Optional[int]) -> Optional[int]:
    """Map Book RS rank (1=best) → 0–99 Relative Trend Strength style score."""
    if not rs_rank or not rs_n or rs_n < 2:
        return None
    score = round(100.0 * (1.0 - (rs_rank - 1) / max(rs_n - 1, 1)))
    return int(max(1, min(99, score)))


def _ret_from_df(df, bars: int) -> Optional[float]:
    if df is None or df.empty or len(df) < bars + 1:
        return None
    close = df["close"].astype(float)
    last = float(close.iloc[-1])
    prev = float(close.iloc[-(bars + 1)])
    if prev <= 0:
        return None
    return ((last / prev) - 1.0) * 100.0


def momentum_extras(symbol: str, df=None) -> dict:
    """Extra returns for SBW / SB9 / 52W. Pass `df` to skip a second OHLCV load."""
    sym = symbol.upper()
    if df is None:
        df = md.get_ohlcv_df(sym, "daily", limit=220)
    if df is None or df.empty or len(df) < 30:
        return {"ready": False}
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    last = float(close.iloc[-1])
    hi_52 = float(high.tail(min(252, len(high))).max())
    vs_high = ((last / hi_52) - 1.0) * 100 if hi_52 > 0 else None
    return {
        "ready": True,
        "ret_5d_pct": _ret_from_df(df, 5),
        "ret_9m_pct": _ret_from_df(df, 189),
        "vs_52w_high_pct": round(vs_high, 2) if vs_high is not None else None,
    }


def compute_badges(
    *,
    setups: Optional[List[str]] = None,
    families: Optional[List[str]] = None,
    stage: Optional[int] = None,
    early_stage2: bool = False,
    change_pct: Optional[float] = None,
    gap_pct: Optional[float] = None,
    ret_5d_pct: Optional[float] = None,
    ret_9m_pct: Optional[float] = None,
    vs_52w_high_pct: Optional[float] = None,
    dist_20d_high_pct: Optional[float] = None,
    rs_rank_21d: Optional[int] = None,
    rs_n: Optional[int] = None,
    is_near_high: bool = False,
    is_vol_surge: bool = False,
    is_ep: bool = False,
    darvas_state: Optional[str] = None,
) -> dict:
    """
    Return {badges, codes, rts, strike_zone}.
    Each badge: {id, label, tone, kind, title}.
    """
    setups = setups or []
    families = families or []
    codes: List[str] = []

    def add(code: str) -> None:
        if code in BADGE_CATALOG and code not in codes:
            codes.append(code)

    if (
        "QULLA_BREAKOUT" in setups
        or (is_near_high and is_vol_surge)
        or is_ep
        or "EP" in setups
        or "BREAKOUT_QUEUE" in setups
    ):
        add("KQ")

    if "MINERVINI_TT" in setups:
        add("MM")

    if darvas_state == "breakout" or "DARVAS_BREAKOUT" in setups:
        add("DB")

    day4 = (change_pct is not None and change_pct >= 4.0) or (
        gap_pct is not None and gap_pct >= 4.0
    )
    if day4 or "STOCKBEE_EP" in setups:
        add("SB4")

    if ret_5d_pct is not None and ret_5d_pct >= 20.0:
        add("SBW")

    if ret_9m_pct is not None and ret_9m_pct >= 100.0:
        add("SB9")

    if vs_52w_high_pct is not None and vs_52w_high_pct >= -10.0:
        add("52W")

    rts = book_rts(rs_rank_21d, rs_n)
    near = is_near_high or (
        dist_20d_high_pct is not None and dist_20d_high_pct >= -5.0
    )
    stage2 = stage == 2 or "STAGE_2" in setups or early_stage2
    strong_rs = rts is not None and rts >= 75
    if stage2 and near and strong_rs:
        add("ON")

    if early_stage2 or "STAGE_2_EARLY" in setups:
        add("2A")
    elif stage == 2 or "STAGE_2" in setups:
        add("2B")

    if rts is not None and rts >= 97:
        add("97C")

    strike = bool(
        near
        and (
            "MINERVINI_PIVOT" in setups
            or (dist_20d_high_pct is not None and dist_20d_high_pct >= -3.0)
        )
    )

    badges = []
    for code in codes:
        meta = BADGE_CATALOG[code]
        badges.append({
            "id": code,
            "label": meta["label"],
            "tone": meta["tone"],
            "kind": meta["kind"],
            "title": f"{code}: {meta['label']} — {meta['blurb']}",
        })

    return {
        "badges": badges,
        "codes": codes,
        "rts": rts,
        "strike_zone": strike,
    }


def badges_for_row(row: dict, fetch_extras: bool = True) -> dict:
    """Attach badges using row fields; optionally fill SBW/SB9/52W from OHLCV."""
    extras: dict = {}
    if fetch_extras and row.get("symbol"):
        need = (
            row.get("ret_5d_pct") is None
            or row.get("ret_9m_pct") is None
            or row.get("vs_52w_high_pct") is None
        )
        if need:
            extras = momentum_extras(row["symbol"])
    return compute_badges(
        setups=row.get("setups"),
        families=row.get("families"),
        stage=row.get("stage"),
        early_stage2=bool(row.get("early_stage2")),
        change_pct=row.get("change_pct"),
        gap_pct=row.get("gap_pct"),
        ret_5d_pct=row.get("ret_5d_pct", extras.get("ret_5d_pct")),
        ret_9m_pct=row.get("ret_9m_pct", extras.get("ret_9m_pct")),
        vs_52w_high_pct=row.get("vs_52w_high_pct", extras.get("vs_52w_high_pct")),
        dist_20d_high_pct=row.get("dist_20d_high_pct"),
        rs_rank_21d=row.get("rs_rank_21d"),
        rs_n=row.get("rs_n"),
        is_near_high=bool(row.get("is_near_high")),
        is_vol_surge=bool(row.get("is_vol_surge")),
        is_ep=bool(row.get("is_ep")),
        darvas_state=row.get("darvas_state"),
    )


def catalog_for_api() -> dict:
    presets = []
    for code, meta in BADGE_CATALOG.items():
        if meta["kind"] not in ("method", "stage"):
            continue
        presets.append({
            "id": f"badge_{code.lower()}",
            "name": f"{code} · {meta['label']}",
            "badge": code,
            "rules": [{"field": "badge", "op": "has_badge", "value": code}],
            "match": "all",
            "tone": meta["tone"],
            "blurb": meta["blurb"],
        })
    return {"badges": BADGE_CATALOG, "presets": presets}
