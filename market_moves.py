"""Market Moves board — QUANT-locked z from stored Yahoo/SQLite OHLCV.

Never invent PX / z / gamma. Missing bars stay blank ("—").
Not CNBC / Finviz as source of truth.

QUANT LOCK (2026-09-04)
    DAY% = C_t / C_{t-1} − 1
        Yields: display 100 * (y_t − y_{t-1}) in basis points.

    Daily Z (N=30, sample ddof=1), today included in the window:
        z = (r_t − mean(r_{t−29…t})) / sample_stdev(r_{t−29…t}, ddof=1)
        Blank if σ ≈ 0. Bullet when |z| ≥ 2.
        NOT bare r/σ without demeaning.

    14D Z:
        R_14 = C_t / C_{t−14} − 1
        z_14 = R_14 / sample_stdev({rolling 14d simple returns over ~126 ends}, ddof=1)
        NOT R_14 / (σ_daily · √14)
        NOT sd of only the last 14 daily returns.
        Yields use first differences of the stored yield level in place of simple returns.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import market_data as md

NOTE = (
    "Yahoo/stored OHLCV (not CNBC/Finviz as SoT). "
    "shade=|z| intensity · • = |z|≥2 · daily z vs ~30d stdev · "
    "14D: 14-day move in 14-day sigmas."
)
SOURCE_NOTE = "Yahoo/stored OHLCV — not CNBC/Finviz as source of truth."
LEGEND = "shade=|z| intensity · • = |z|≥2 · daily z vs ~30d stdev · 14D: 14-day move in 14-day sigmas"

Z_WINDOW = 30
Z14_HORIZON = 14
Z14_ENDS = 126
Z14_MIN_ENDS = 10
SIGMA_EPS = 1e-12
EXTREME_ABS = 2.0

# Screenshot names → Yahoo-available symbols. Futures without Yahoo stay omitted
# from fetch lists but can still render as "—" if listed.
GROUPS = (
    {
        "id": "indexes",
        "label": "INDEXES",
        "kind": "price",
        "col": 0,
        "rows": [
            ("TSX", "^GSPTSE"),
            ("FTSE", "^FTSE"),
            ("DJI", "^DJI"),
            ("SPX", "^GSPC"),
            ("RSP", "RSP"),
            ("MDY", "MDY"),
            ("DAX", "^GDAXI"),
            ("MEXBOL", "^MXX"),
            ("RUT", "^RUT"),
            ("IJR", "IJR"),
            ("STOXX50", "^STOXX50E"),
            ("KOSPI", "^KS11"),
            ("N225", "^N225"),
            ("IBOV", "^BVSP"),
            ("HSI", "^HSI"),
            ("VIX", "^VIX"),
        ],
    },
    {
        "id": "big_tech",
        "label": "BIG TECH",
        "kind": "price",
        "col": 1,
        "rows": [
            ("TSLA", "TSLA"),
            ("META", "META"),
            ("MSFT", "MSFT"),
            ("NVDA", "NVDA"),
            ("GOOGL", "GOOGL"),
            ("AMZN", "AMZN"),
            ("AAPL", "AAPL"),
            ("NFLX", "NFLX"),
            ("AMD", "AMD"),
            ("AVGO", "AVGO"),
        ],
    },
    {
        "id": "country_etfs",
        "label": "COUNTRY ETFS",
        "kind": "price",
        "col": 2,
        "rows": [
            ("EWC", "EWC"),
            ("EWJ", "EWJ"),
            ("EWU", "EWU"),
            ("EWA", "EWA"),
            ("EWG", "EWG"),
            ("EWW", "EWW"),
            ("EEM", "EEM"),
            ("EWT", "EWT"),
            ("EWY", "EWY"),
            ("EWZ", "EWZ"),
            ("INDA", "INDA"),
            ("MCHI", "MCHI"),
        ],
    },
    {
        "id": "sectors",
        "label": "SECTORS",
        "kind": "price",
        "col": 0,
        "rows": [
            ("XLF", "XLF"),
            ("XLRE", "XLRE"),
            ("XLY", "XLY"),
            ("XLU", "XLU"),
            ("XLI", "XLI"),
            ("XLC", "XLC"),
            ("XLK", "XLK"),
            ("XLV", "XLV"),
            ("XLP", "XLP"),
            ("XLE", "XLE"),
            ("XLB", "XLB"),
        ],
    },
    {
        "id": "tech_themes",
        "label": "TECH THEMES",
        "kind": "price",
        "col": 1,
        "rows": [
            ("IGV", "IGV"),
            ("BOTZ", "BOTZ"),
            ("ICLN", "ICLN"),
            ("GRID", "GRID"),
            ("CIBR", "CIBR"),
            ("SHLD", "SHLD"),
            ("ARTY", "ARTY"),
            ("ITA", "ITA"),
            ("QTUM", "QTUM"),
            ("SMH", "SMH"),
        ],
    },
    {
        "id": "resource_themes",
        "label": "RESOURCE THEMES",
        "kind": "price",
        "col": 2,
        "rows": [
            ("CCJ", "CCJ"),
            ("URNM", "URNM"),
            ("GDX", "GDX"),
            ("URA", "URA"),
            ("GDXJ", "GDXJ"),
            ("SIL", "SIL"),
            ("SILJ", "SILJ"),
            ("AMLP", "AMLP"),
            ("REMX", "REMX"),
            ("XOP", "XOP"),
            ("OIH", "OIH"),
            ("DBA", "DBA"),
            ("MOO", "MOO"),
        ],
    },
    {
        "id": "ags_softs",
        "label": "AGS & SOFTS",
        "kind": "price",
        "col": 0,
        "rows": [
            ("LE", "LE=F"),
            ("LB", "LBS=F"),
            ("GF", "GF=F"),
            ("OJ", "OJ=F"),
            ("ZM", "ZM=F"),
            ("ZS", "ZS=F"),
            ("ZR", "ZR=F"),
            ("HE", "HE=F"),
            ("KC", "KC=F"),
            ("ZC", "ZC=F"),
            ("CC", "CC=F"),
            ("ZL", "ZL=F"),
            ("ZO", "ZO=F"),
            ("ZW", "ZW=F"),
            ("SB", "SB=F"),
            ("CT", "CT=F"),
        ],
    },
    {
        "id": "metals_energy",
        "label": "METALS & ENERGY",
        "kind": "price",
        "col": 1,
        "rows": [
            ("PA", "PA=F"),
            ("PL", "PL=F"),
            ("GLD", "GLD"),
            ("SLV", "SLV"),
            ("HG", "HG=F"),
            ("CL", "CL=F"),
            ("BNO", "BNO"),
            ("NG", "NG=F"),
        ],
    },
    {
        "id": "fx",
        "label": "FX",
        "kind": "price",
        "col": 2,
        "rows": [
            ("GBPUSD", "GBPUSD=X"),
            ("EURUSD", "EURUSD=X"),
            ("USDBRL", "BRL=X"),
            ("USDCNY", "CNY=X"),
            ("USDMXN", "MXN=X"),
            ("USDCHF", "CHF=X"),
            ("DXY", "DX-Y.NYB"),
            ("USDJPY", "JPY=X"),
        ],
    },
    {
        "id": "yields",
        "label": "YIELDS (bp)",
        "kind": "yield",
        "col": 0,
        "rows": [
            ("UK10Y", "GB10Y=RR"),
            ("DE10Y", "DE10Y=RR"),
            ("JP10Y", "JP10Y=RR"),
            ("30Y", "^TYX"),
            ("10Y", "^TNX"),
            ("5Y", "^FVX"),
            ("2Y", "2YY=F"),
        ],
    },
    {
        "id": "bond_etfs",
        "label": "BOND ETFS",
        "kind": "price",
        "col": 1,
        "rows": [
            ("LEMB", "LEMB"),
            ("EMB", "EMB"),
            ("TIP", "TIP"),
            ("AGG", "AGG"),
            ("TLT", "TLT"),
        ],
    },
    {
        "id": "crypto",
        "label": "CRYPTO",
        "kind": "price",
        "col": 2,
        "rows": [
            ("MSTR", "MSTR"),
            ("COIN", "COIN"),
            ("IBIT", "IBIT"),
            ("WGMI", "WGMI"),
        ],
    },
)

CORE_FETCH_GROUPS = ("indexes", "big_tech", "sectors")


def _finite(val):
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return num


def _round(val, digits):
    num = _finite(val)
    if num is None:
        return None
    return round(num, digits)


def _series_returns(level: pd.Series, kind: str) -> pd.Series:
    s = level.astype(float)
    if kind == "yield":
        return s.diff()
    return s.pct_change()


def _rolling_horizon_returns(level: pd.Series, horizon: int, kind: str) -> pd.Series:
    s = level.astype(float)
    if kind == "yield":
        return s - s.shift(horizon)
    return s / s.shift(horizon) - 1.0


def daily_z(level: pd.Series, kind: str = "price", window: int = Z_WINDOW) -> float | None:
    """Demeaned daily z. Today is inside the N-window. Sample σ, ddof=1."""
    if level is None or len(level.dropna()) < window + 1:
        return None
    rets = _series_returns(level, kind).dropna()
    if len(rets) < window:
        return None
    w = rets.iloc[-window:].astype(float)
    if len(w) < window or w.isna().any():
        return None
    sig = float(w.std(ddof=1))
    if sig < SIGMA_EPS:
        return None
    mu = float(w.mean())
    return (float(w.iloc[-1]) - mu) / sig


def z_14d(
    level: pd.Series,
    kind: str = "price",
    horizon: int = Z14_HORIZON,
    ends: int = Z14_ENDS,
    min_ends: int = Z14_MIN_ENDS,
) -> float | None:
    """R_14 / sample σ of rolling 14-day simple returns (~126 ends)."""
    if level is None or len(level.dropna()) < horizon + min_ends:
        return None
    r14 = _rolling_horizon_returns(level, horizon, kind)
    sample = r14.dropna().iloc[-ends:]
    if len(sample) < min_ends:
        return None
    last = _finite(r14.iloc[-1])
    if last is None:
        return None
    sig = float(sample.std(ddof=1))
    if sig < SIGMA_EPS:
        return None
    return last / sig


def move_row(level: pd.Series, kind: str = "price") -> dict:
    """One name from stored closes. Blank fields when the window is short."""
    empty = {
        "ready": False,
        "px": None,
        "day_pct": None,
        "z": None,
        "z14": None,
        "extreme": False,
        "asof": None,
        "bars": int(len(level.dropna())) if level is not None else 0,
    }
    if level is None or len(level.dropna()) < 2:
        return empty
    close = level.astype(float).dropna()
    last = _finite(close.iloc[-1])
    prev = _finite(close.iloc[-2])
    if last is None or prev is None:
        return empty
    if kind == "yield":
        day_pct = 100.0 * (last - prev)
    else:
        day_pct = ((last / prev) - 1.0) * 100.0 if prev else None
    z = daily_z(close, kind=kind)
    z14 = z_14d(close, kind=kind)
    asof = None
    if isinstance(close.index, pd.DatetimeIndex) and len(close.index):
        asof = pd.Timestamp(close.index[-1]).strftime("%Y-%m-%d")
    return {
        "ready": True,
        "px": _round(last, 4 if abs(last) < 10 else 2),
        "day_pct": _round(day_pct, 2),
        "z": _round(z, 2),
        "z14": _round(z14, 2),
        "extreme": z is not None and abs(z) >= EXTREME_ABS,
        "asof": asof,
        "bars": int(len(close)),
    }


def _daily_close(symbol: str, limit: int = 400) -> pd.Series:
    df = md.get_ohlcv_df(symbol, "daily", limit=limit)
    if df is None or df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)
    return df["close"].astype(float)


def group_symbols(group_id: str | None = None) -> list[str]:
    out = []
    seen = set()
    for spec in GROUPS:
        if group_id and spec["id"] != group_id:
            continue
        for _name, yahoo in spec["rows"]:
            sym = str(yahoo).strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(sym)
    return out


def core_symbols() -> list[str]:
    out = []
    seen = set()
    for gid in CORE_FETCH_GROUPS:
        for sym in group_symbols(gid):
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def _clock_et() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.strftime("%a %b %d, %Y %I:%M%p ET").replace(" 0", " ")


def empty_board() -> dict:
    groups = []
    for spec in GROUPS:
        groups.append({
            "id": spec["id"],
            "label": spec["label"],
            "kind": spec["kind"],
            "col": spec["col"],
            "rows": [
                {
                    "symbol": yahoo,
                    "name": name,
                    "px": None,
                    "day_pct": None,
                    "z": None,
                    "z14": None,
                    "extreme": False,
                    "ready": False,
                }
                for name, yahoo in spec["rows"]
            ],
        })
    return {
        "asof": None,
        "asof_et": _clock_et(),
        "groups": groups,
        "legend": LEGEND,
        "source": SOURCE_NOTE,
        "note": NOTE,
        "gamma": None,
    }


def build_board() -> dict:
    board = empty_board()
    asofs = []
    for spec, out in zip(GROUPS, board["groups"]):
        kind = spec["kind"]
        rows = []
        for name, yahoo in spec["rows"]:
            stats = move_row(_daily_close(yahoo), kind=kind)
            if stats.get("asof"):
                asofs.append(stats["asof"])
            rows.append({
                "symbol": yahoo,
                "name": name,
                "px": stats.get("px"),
                "day_pct": stats.get("day_pct"),
                "z": stats.get("z"),
                "z14": stats.get("z14"),
                "extreme": bool(stats.get("extreme")),
                "ready": bool(stats.get("ready")),
            })
        out["rows"] = rows
    board["asof"] = max(asofs) if asofs else None
    board["asof_et"] = _clock_et()
    return board


def seed_symbols(group_ids: list[str] | None = None) -> dict:
    """Add Market Moves Yahoo names to finance.db. Does not invent bars."""
    ids = [g for g in (group_ids or [s["id"] for s in GROUPS]) if g]
    tickers = []
    seen = set()
    for gid in ids:
        for sym in group_symbols(gid):
            if sym not in seen:
                seen.add(sym)
                tickers.append(sym)
    result = md.add_symbols(tickers) if tickers else {"added": [], "existed": []}
    return {
        "groups": ids,
        "tickers": tickers,
        **result,
    }


def fetch_core(delay: float = 1.2, period: str = "1y") -> dict:
    """Fetch Indexes + Big Tech + Sectors into finance.db from Yahoo."""
    import time

    import data_fetcher as fetcher

    seeded = seed_symbols(list(CORE_FETCH_GROUPS))
    fetched = []
    failed = []
    for i, sym in enumerate(seeded["tickers"]):
        if i:
            time.sleep(max(0.0, delay))
        out = fetcher.fetch_and_store(sym, period=period)
        if out.get("error"):
            failed.append({"symbol": sym, "error": out.get("error")})
        else:
            fetched.append({
                "symbol": sym,
                "daily_rows": out.get("daily_rows"),
            })
    return {
        "seeded": seeded,
        "fetched": fetched,
        "failed": failed,
        "note": "Failed Yahoo names stay blank on the board — not invented.",
    }
