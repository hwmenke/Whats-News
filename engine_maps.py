"""Visual maps: Scanner scatter, Rotation, Coil, Fractal×TD, TMS Regime.

Yahoo/SQLite OHLCV only. Reuses equity_engine.measure fields.
Public ETF / index proxies — no vendor terminal feed. Blank when bars are missing.
"""

from __future__ import annotations

from typing import Optional

import ticker_lists as tl
import equity_engine as ee
import market_data as md

NOTE = (
    "Yahoo/SQLite only. Maps are research plots from stored bars — not a live "
    "vendor sheet. Blank when a series is short."
)

CLASS_COLORS = {
    "FX G10": "#06B6D4",
    "FX EM": "#A855F7",
    "Rates": "#22C55E",
    "STIR": "#86EFAC",
    "Equity Idx": "#EF4444",
    "US Sector": "#B91C1C",
    "Thematic": "#EAB308",
    "Stock": "#F97316",
    "Commodity": "#0F766E",
    "Bond/Credit": "#3B82F6",
    "Country": "#F43F5E",
    "Vol/Risk": "#6B7280",
}

# Public Yahoo proxies only — not futures chain names.
_CLASS_SYMBOLS = {
    "FX G10": {"UUP", "FXE", "FXY", "FXB", "FXC", "FXA", "FXF", "UDN", "DX-Y.NYB"},
    "FX EM": {"CEW", "EMLC", "CYB", "BZF"},
    "Rates": {"TLT", "IEF", "SHY", "TIP", "GOVT", "ZROZ", "^TNX", "^TYX", "^IRX"},
    "STIR": {"BIL", "SGOV", "TBIL", "SHV"},
    "Equity Idx": {
        "SPY", "QQQ", "IWM", "DIA", "VOO", "IVV", "VTI", "SCHB",
        "^GSPC", "^NDX", "^DJI", "^RUT", "^FTSE", "^N225", "^GDAXI", "^HSI", "^SSEC",
    },
    "US Sector": {
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
        "SMH", "SOXX", "KRE", "KBE",
    },
    "Thematic": {
        "ARKK", "ARKG", "ARKW", "BOTZ", "ICLN", "HACK", "CIBR", "IGV", "IBB", "XBI",
        "ITA", "TAN", "URA",
    },
    "Commodity": {"GLD", "SLV", "IAU", "USO", "UNG", "DBA", "GDX", "GDXJ", "SIL", "PPLT"},
    "Bond/Credit": {"AGG", "BND", "LQD", "HYG", "EMB", "JNK", "VCIT"},
    "Country": {
        "EFA", "EEM", "IEFA", "IEMG", "FXI", "EWJ", "EWZ", "EWG", "EWC", "EWY",
        "EWA", "EWU", "EWH", "EWT", "INDA", "MCHI", "VGK", "VPL", "ACWI", "ACWX",
    },
    "Vol/Risk": {"^VIX", "VIX", "UVXY", "SVOL", "VXX", "VXZ"},
}


def asset_class(symbol: str) -> str:
    """Map a Yahoo symbol to a display class. Unknown listed names → Stock."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return "Stock"
    for cls, names in _CLASS_SYMBOLS.items():
        if sym in names:
            return cls
    tag = ""
    try:
        tag = tl.library_group_tag(sym)
    except Exception:
        tag = ""
    tag = (tag or "").lower()
    if "sector" in tag:
        return "US Sector"
    if "intl" in tag or "countr" in tag:
        return "Country"
    if "commodit" in tag or "resource" in tag:
        return "Commodity"
    if "bond" in tag or "rates" in tag:
        return "Bond/Credit"
    if "theme" in tag or "listed_crypto" in tag:
        return "Thematic"
    if "broad" in tag or "indices" in tag or tag == "sleeve:core":
        return "Equity Idx"
    if sym.startswith("^"):
        return "Equity Idx"
    return "Stock"


def _arrow(score, impulse, prev_impulse=None) -> Optional[str]:
    s, imp = ee._finite(score), ee._finite(impulse)
    if s is None or imp is None:
        return None
    if s * imp > 0 and abs(imp) >= 3:
        return "strengthen"
    if s * imp < 0 and abs(imp) >= 3:
        return "weaken"
    return None


def _spy_strip(rows: list[dict]) -> dict:
    spy = next((r for r in rows if r.get("symbol") == "SPY" and r.get("ready")), None)
    if not spy:
        return {
            "ready": False,
            "label": None,
            "note": "SPY strip omitted — no stored SPY bars. research label, not edge.",
        }
    zone = spy.get("tms_w_zone") or spy.get("tms_zone")
    if zone in ("STRONG +", "SOLID +"):
        label = "RISK-ON"
    elif zone in ("EXTREME −", "MILD −"):
        label = "RISK-OFF"
    else:
        label = "MIXED"
    return {
        "ready": True,
        "label": label,
        "zone": zone,
        "symbol": "SPY",
        "note": "SPY TMS zone → RISK-ON / MIXED / RISK-OFF. research label, not edge.",
    }


def _extremes(rows: list[dict]) -> dict:
    scored = [r for r in rows if r.get("ready") and r.get("ret_12m") is not None]
    top = sorted(scored, key=lambda r: -(r.get("ret_12m") or 0))[:5]
    bot = sorted(scored, key=lambda r: (r.get("ret_12m") or 0))[:5]
    slim = lambda r: {"symbol": r["symbol"], "ret_12m": r.get("ret_12m"), "asset_class": asset_class(r["symbol"])}
    return {
        "top_12m": [slim(r) for r in top],
        "bottom_12m": [slim(r) for r in bot],
        "note": "Top/bottom 12M % from our stored MacroScan closes — not a live vendor print.",
    }


def _pt(row, x, y, extra=None):
    if row.get(x) is None or row.get(y) is None:
        return None
    cls = asset_class(row["symbol"])
    pt = {
        "symbol": row["symbol"],
        "x": row.get(x),
        "y": row.get(y),
        "asset_class": cls,
        "color": CLASS_COLORS.get(cls, "#F97316"),
        "gray_tag": row.get("gray_tag"),
    }
    if extra:
        pt.update(extra)
    return pt


def maps_board(symbols: Optional[list[str]] = None, frames: Optional[dict] = None) -> dict:
    rows = ee._score_desk(symbols, frames)
    ready = [r for r in rows if r.get("ready")]
    scanner_rows = []
    rotation, coil, frac_td = [], [], []
    tms_w_pts, tms_d_pts = [], []
    no_d = 0
    for r in ready:
        cls = asset_class(r["symbol"])
        scanner_rows.append({
            "symbol": r["symbol"],
            "asset_class": cls,
            "color": CLASS_COLORS.get(cls),
            "str": r.get("str"),
            "stretch_pct": r.get("stretch_pct"),
            "stretch_pctile": r.get("stretch_pctile"),
            "delta_d_1m": r.get("delta_d_1m"),
            "d65": r.get("d65"),
            "tms_d": r.get("tms_d"),
            "pos_52w": r.get("pos_52w"),
            "vol30": r.get("vol30"),
            "tes_state": r.get("tes_state"),
            "gray_tag": r.get("gray_tag"),
            "dir5": r.get("dir5"),
            "tmac_star": r.get("tmac_star"),
            "heat_proxy": r.get("heat_proxy") if r.get("heat_proxy") is not None else r.get("tmac_star"),
            "td_count": r.get("td_count"),
            "td_flag": r.get("td_flag"),
            "takeaway": r.get("takeaway"),
        })
        rot = _pt(r, "rsi14", "sigma_1w")
        if rot:
            rotation.append(rot)
        cpt = _pt(r, "coil_12", "pos_13w", extra={"coil_state": r.get("coil_state"), "coil_13": r.get("coil_13")})
        if cpt:
            coil.append(cpt)
        # Fractal markers only when D is present — never invent D.
        if r.get("d65") is not None:
            frac_td.append({
                "symbol": r["symbol"],
                "x": r.get("d65"),
                "y": r.get("td_count"),
                "asset_class": cls,
                "color": CLASS_COLORS.get(cls, "#F97316"),
                "d_label": r.get("d_label"),
                "fractal_read": r.get("fractal_read"),
                "td_flag": r.get("td_flag"),
                "td_side": r.get("td_side"),
            })
        else:
            no_d += 1
        w_arrow = _arrow(r.get("tms_w_score"), r.get("tms_w_impulse_y"))
        d_arrow = _arrow(r.get("tms_score"), r.get("tms_impulse_y"))
        wpt = _pt(r, "tms_w_score", "tms_w_impulse_y", extra={"marker": "solid", "arrow": w_arrow, "zone": r.get("tms_w_zone")})
        if wpt:
            tms_w_pts.append(wpt)
        dpt = _pt(r, "tms_score", "tms_impulse_y", extra={"marker": "hollow", "arrow": d_arrow, "zone": r.get("tms_zone")})
        if dpt:
            tms_d_pts.append(dpt)

    empty = not ready
    try:
        stored_n = len(md.list_symbols_with_ohlcv("daily", min_bars=20))
    except Exception:
        stored_n = 0
    if empty:
        maps_message = (
            f"Desk maps empty — {stored_n} names have stored bars. Refresh after Fetch."
            if stored_n
            else "Empty maps — seed a sleeve and Fetch Yahoo."
        )
    else:
        maps_message = None
    by_zone: dict[str, list[str]] = {}
    for r in ready:
        zone = r.get("tms_w_zone") or r.get("tms_zone")
        if zone:
            by_zone.setdefault(zone, []).append(r["symbol"])
    return {
        "ready": not empty,
        "count": len(ready),
        "scanner": {
            "rows": scanner_rows,
            "scatter": [p for p in (_pt(r, "dir5", "rsi14") for r in ready) if p],
            "howto": (
                "Scanner: Str −5…+5, Stretch% / %ile bar, ΔD 1m and D65 from SPEC 25/27, "
                "TMS-D signed (TMS−50)/5, 52w position bar, Vol30, TES state (see formulas.tes), "
                "gray RSI-C · VCP tag, Dir ±5 heat, TMAC* heat proxy 0–99 (never branded TMAC). "
                "Scatter X=Dir Y=RSI14, color by class. Not a win rate."
            ),
        },
        "rotation": {
            "points": rotation,
            "x_label": "RSI(14)",
            "y_label": "1-week momentum σ",
            "howto": "CROSS-ASSET ROTATION — RSI(14) vs 1w σ. Color by asset class. Crosshair at RSI 50 / 0σ.",
        },
        "coil": {
            "points": coil,
            "x_label": "weekly coil_12 = r12/r26 (tighter ←)",
            "y_label": "13w range position %",
            "bands": {"compressed": 0.45, "coiling": 0.65, "expanding": 0.90},
            "howto": (
                "COIL MAP — weekly coil_12=r12/r26, coil_13=r13/r26 (rN = weekly-return σ). "
                "tighter← vs 13w range %. COMPRESSED≤0.45 COILING≤0.65 EXPANDING≥0.90."
            ),
        },
        "fractal_td": {
            "points": frac_td,
            "no_d": no_d,
            "x_label": "D65 (← smooth/trending · 1.5 = random walk)",
            "y_label": "TD count — setup ±9 countdown ±13 (honest approx)",
            "guides": {"d_smooth": 1.3, "d_rw": 1.5, "td": [-13, 13]},
            "howto": (
                "FRACTAL × TD — D65 from SPEC 25/27 only (no marker without D). "
                "TD is an honest setup/countdown approx. Blank TD is missing count, not a fake 0. "
                "Lines at ±13. Never invented TD13 stars."
            ),
        },
        "tms_regime": {
            "weekly": tms_w_pts,
            "daily": tms_d_pts,
            "x_label": "TMS score (−100…+100)",
            "y_label": "Impulse (Δ TMS)",
            "spy_strip": _spy_strip(ready),
            "by_zone": by_zone,
            "extremes": _extremes(ready),
            "howto": (
                "TMS REGIME MAP — by TMS zone. Score (x) vs Impulse (y). "
                "Solid = weekly TMS-W, hollow = daily TMS-D. "
                "SPY strip is RISK-ON / MIXED / RISK-OFF only — research label, not edge."
            ),
        },
        "classes": CLASS_COLORS,
        "message": maps_message,
        "stored_n": stored_n,
        "note": NOTE,
        "formulas": ee.FORMULAS,
        "tes_note": ee.TES_NOTE,
        "td_note": ee.TD_NOTE,
        "tmac_note": ee.TMAC_NOTE,
    }
