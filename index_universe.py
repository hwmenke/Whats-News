"""
index_universe.py — US index constituent lists for bulk archive.

Sources: Wikipedia tables (S&P 500/400/600, Nasdaq-100, Russell 2000).
Tickers are normalized for Yahoo (BRK.B → BRK-B). Universe symbols are tagged
univ:<index_id> in SQLite so they stay out of the trading desk sidebar by default.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import pandas as pd

UNIVERSE_TAG_PREFIX = "univ:"

# Registry of downloadable indices
INDEX_REGISTRY: Dict[str, dict] = {
    "sp500": {
        "label": "S&P 500",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "table": 0,
        "symbol_col": "Symbol",
    },
    "sp400": {
        "label": "S&P MidCap 400",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "table": 0,
        "symbol_col": "Symbol",
    },
    "sp600": {
        "label": "S&P SmallCap 600",
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        "table": 0,
        "symbol_col": "Symbol",
    },
    "ndx100": {
        "label": "Nasdaq-100",
        "url": "https://en.wikipedia.org/wiki/NASDAQ-100",
        "table": 4,
        "symbol_col": "Ticker",
    },
    "russell2000": {
        "label": "Russell 2000",
        "url": "https://en.wikipedia.org/wiki/Russell_2000_Index",
        "table": 2,
        "symbol_col": "Symbol",
    },
}


def normalize_ticker(raw: str) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    sym = str(raw).strip().upper()
    sym = sym.replace(".", "-")
    sym = re.sub(r"\s+", "", sym)
    if not re.match(r"^[A-Z0-9^][A-Z0-9.\-^]*$", sym):
        return None
    return sym


def _symbols_from_wikipedia(url: str, table_idx: int, symbol_col: str) -> List[str]:
    tables = pd.read_html(url)
    if table_idx >= len(tables):
        raise ValueError(f"Table index {table_idx} not found at {url} (have {len(tables)} tables)")
    df = tables[table_idx]
    df.columns = [str(c).strip() for c in df.columns]
    col = symbol_col
    if col not in df.columns:
        for c in df.columns:
            if "symbol" in c.lower() or "ticker" in c.lower():
                col = c
                break
        else:
            raise ValueError(f"No symbol column in {url} columns: {df.columns.tolist()}")
    out: List[str] = []
    seen = set()
    for raw in df[col].astype(str):
        sym = normalize_ticker(raw)
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def fetch_index_symbols(index_id: str) -> List[str]:
    """Return ticker list for one index id (see INDEX_REGISTRY)."""
    meta = INDEX_REGISTRY.get(index_id)
    if not meta:
        raise ValueError(f"Unknown index id: {index_id}")
    return _symbols_from_wikipedia(meta["url"], meta["table"], meta["symbol_col"])


def fetch_all_indices(index_ids: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """Fetch multiple indices; returns {index_id: [symbols]}."""
    ids = index_ids or list(INDEX_REGISTRY.keys())
    result: Dict[str, List[str]] = {}
    for idx in ids:
        if idx == "all":
            continue
        try:
            result[idx] = fetch_index_symbols(idx)
        except Exception as exc:
            result[idx] = []
            result[f"{idx}_error"] = str(exc)  # type: ignore
    return result


def merged_universe(index_ids: Optional[List[str]] = None) -> Dict[str, object]:
    """
    Deduped union of requested indices with per-index counts.
    index_ids: list of keys or ['all'].
    """
    if not index_ids or "all" in index_ids:
        ids = list(INDEX_REGISTRY.keys())
    else:
        ids = [i for i in index_ids if i in INDEX_REGISTRY]

    per_index: Dict[str, int] = {}
    symbol_to_indices: Dict[str, List[str]] = {}
    errors: Dict[str, str] = {}

    for idx in ids:
        try:
            syms = fetch_index_symbols(idx)
            per_index[idx] = len(syms)
            for sym in syms:
                symbol_to_indices.setdefault(sym, []).append(idx)
        except Exception as exc:
            per_index[idx] = 0
            errors[idx] = str(exc)

    symbols = sorted(symbol_to_indices.keys())
    return {
        "indices": ids,
        "per_index": per_index,
        "total_unique": len(symbols),
        "symbols": symbols,
        "symbol_indices": symbol_to_indices,
        "errors": errors,
    }


def universe_group_tag(index_id: str) -> str:
    return f"{UNIVERSE_TAG_PREFIX}{index_id}"


def is_universe_tag(group_tag: str | None) -> bool:
    return bool(group_tag) and str(group_tag).startswith(UNIVERSE_TAG_PREFIX)


def registry_for_api() -> List[dict]:
    return [
        {"id": k, "label": v["label"], "tag": universe_group_tag(k)}
        for k, v in INDEX_REGISTRY.items()
    ]
