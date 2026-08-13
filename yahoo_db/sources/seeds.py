"""
sources/seeds.py - Symbols from local files.

Drop any .csv/.txt/.tsv file into `yahoo_db/seeds/` and every symbol in it
joins the universe. This is the escape hatch for lists no API will give you:
historical index constituents, a broker's delisted-securities export, an old
watchlist, symbols scraped from a 2011 10-K.

Accepted shapes
  one symbol per line                            AAPL
  CSV/TSV with a symbol-ish header column        symbol,name,status
                                                 AAPL,Apple Inc.,active

Recognised header names: symbol, ticker, act symbol, nasdaq symbol, code.
Optional companion columns: name/security name/company, status, exchange,
quote_type/type.
"""

import csv
import logging
from pathlib import Path

from ..db import STATUS_DELISTED, STATUS_UNKNOWN, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE = "seeds"
SYMBOL_KEYS = ("symbol", "ticker", "act symbol", "nasdaq symbol", "code")
NAME_KEYS = ("name", "security name", "company", "company name", "title")
STATUS_KEYS = ("status", "state")
TYPE_KEYS = ("quote_type", "quotetype", "type", "security type")
EXCHANGE_KEYS = ("exchange", "listing exchange", "exch")
SUFFIXES = (".csv", ".txt", ".tsv")


def fetch(seeds_dir) -> list:
    """Return ticker records from every seed file. Never raises."""
    directory = Path(seeds_dir)
    if not directory.is_dir():
        logger.info("seeds: %s does not exist, skipping", directory)
        return []

    records = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SUFFIXES or path.name.startswith("."):
            continue
        try:
            found = parse_seed_file(path)
        except Exception as exc:
            logger.warning("seeds: %s failed: %s", path.name, exc)
            continue
        for rec in found:
            records.setdefault(rec["symbol"], rec)
        logger.info("seeds: %d symbols from %s", len(found), path.name)
    return list(records.values())


def parse_seed_file(path) -> list:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    header_cells = [c.strip().lower() for c in lines[0].split(delimiter)]
    has_header = any(cell in SYMBOL_KEYS for cell in header_cells)

    # Whole-file default: a file named *delisted* marks its symbols dead unless
    # a status column says otherwise.
    default_status = (
        STATUS_DELISTED if "delist" in path.stem.lower() else STATUS_UNKNOWN
    )

    if not has_header:
        out = []
        for line in lines:
            symbol = normalize_symbol(line.split(delimiter)[0])
            if symbol and not symbol.startswith("#"):
                out.append({
                    "symbol": symbol,
                    "status": default_status,
                    "source": SOURCE,
                })
        return out

    out = []
    for row in csv.DictReader(lines, delimiter=delimiter):
        item = {(k or "").strip().lower(): (v or "").strip()
                for k, v in row.items() if k}
        symbol = normalize_symbol(_pick(item, SYMBOL_KEYS))
        if not symbol:
            continue
        status = (_pick(item, STATUS_KEYS) or "").lower() or default_status
        if status not in ("active", "delisted", "unknown"):
            status = default_status
        out.append({
            "symbol": symbol,
            "name": _pick(item, NAME_KEYS),
            "quote_type": (_pick(item, TYPE_KEYS) or "").upper(),
            "exchange": _pick(item, EXCHANGE_KEYS),
            "status": status,
            "source": SOURCE,
        })
    return out


def _pick(item: dict, keys) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return value
    return ""
