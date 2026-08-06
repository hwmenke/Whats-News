"""
sources/nasdaq.py - Symbol universe from the Nasdaq Trader symbol directory.

  nasdaqtraded.txt  every symbol traded on any US venue (~12k, incl. ETFs)
  nasdaqlisted.txt  Nasdaq-listed issues, with market category
  otherlisted.txt   NYSE / NYSE American / Arca / Cboe / IEX issues
  mfundslist.txt    mutual funds (~30k)

These are pipe-delimited, one header line, and a trailing
"File Creation Time: …" line that has to be dropped.

The directory also carries preferreds, warrants, units and rights in CQS/ACT
notation (`ALL.PRB`, `SPAC.WS`, `SPAC.U`), which Yahoo spells differently
(`ALL-PB`, `SPAC-WT`, `SPAC-UN`) — `to_yahoo_symbol` does that translation.
"""

import logging
import re

from ..db import STATUS_ACTIVE, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE = "nasdaq"
BASE = "https://www.nasdaqtrader.com/dynamic/SymDir"
TRADED_URL = f"{BASE}/nasdaqtraded.txt"
NASDAQ_URL = f"{BASE}/nasdaqlisted.txt"
OTHER_URL = f"{BASE}/otherlisted.txt"
MFUNDS_URL = f"{BASE}/mfundslist.txt"

# otherlisted.txt "Exchange" column -> Yahoo exchange code.
EXCHANGE_CODES = {
    "A": ("ASE", "NYSE American"),
    "N": ("NYQ", "NYSE"),
    "P": ("PCX", "NYSE Arca"),
    "Z": ("BTS", "Cboe BZX"),
    "V": ("IEX", "IEX"),
}

# ACT/CQS class suffixes that carry an optional trailing class letter.
# `ALL.PRB` -> `ALL-PB`, `ALL.PR` -> `ALL-P`, `SPAC.WS.A` -> `SPAC-WTA`.
CLASS_SUFFIX_RE = re.compile(r"(.+?)\.(PR|WS)\.?([A-Z]?)")
CLASS_SUFFIX_MAP = {"PR": "-P", "WS": "-WT"}

# Suffixes that take no trailing letter at all. These must match the very end
# of the symbol: an earlier version tested `".U" in s`, which turned `RGC.US`
# into `RGC-UNS` and `ABC.RT` into `ABC-RTT` — symbols Yahoo has never heard
# of, which then come back empty and get written off as delisted.
EXACT_SUFFIX_MAP = [
    (".U", "-UN"),    # unit:   SPAC.U -> SPAC-UN
    (".R", "-RT"),    # right:  SPAC.R -> SPAC-RT
]


def fetch(http, include_funds: bool = True) -> list:
    """Return ticker records from the Nasdaq Trader directory. Never raises."""
    records = {}

    for url, parser, label in (
        (TRADED_URL, _parse_traded, "nasdaqtraded"),
        (NASDAQ_URL, _parse_nasdaq_listed, "nasdaqlisted"),
        (OTHER_URL, _parse_other_listed, "otherlisted"),
    ):
        try:
            for rec in parser(http.get_text(url)):
                existing = records.get(rec["symbol"])
                if existing is None:
                    records[rec["symbol"]] = rec
                else:
                    # Later files carry the exchange detail the superset lacks.
                    for key in ("exchange", "exchange_name", "name", "quote_type"):
                        if not existing.get(key) and rec.get(key):
                            existing[key] = rec[key]
            logger.info("nasdaq: %d symbols after %s", len(records), label)
        except Exception as exc:
            logger.warning("nasdaq: %s failed: %s", label, exc)

    if include_funds:
        try:
            for rec in _parse_mutual_funds(http.get_text(MFUNDS_URL)):
                records.setdefault(rec["symbol"], rec)
            logger.info("nasdaq: %d symbols after mfundslist", len(records))
        except Exception as exc:
            logger.warning("nasdaq: mfundslist failed: %s", exc)

    return list(records.values())


# ── parsers ────────────────────────────────────────────────────────────────────

def parse_pipe_file(text: str) -> list:
    """Parse a Nasdaq Trader pipe-delimited file into a list of dicts."""
    rows = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return rows
    header = [h.strip() for h in lines[0].split("|")]
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != len(header):
            continue
        rows.append(dict(zip(header, parts)))
    return rows


def _is_test_issue(row: dict) -> bool:
    return (row.get("Test Issue") or "").upper() == "Y"


def _quote_type(row: dict) -> str:
    return "ETF" if (row.get("ETF") or "").upper() == "Y" else "EQUITY"


def _parse_traded(text: str) -> list:
    out = []
    for row in parse_pipe_file(text):
        if _is_test_issue(row) or (row.get("Nasdaq Traded") or "").upper() == "N":
            continue
        symbol = to_yahoo_symbol(row.get("NASDAQ Symbol") or row.get("Symbol"))
        if not symbol:
            continue
        code, name = EXCHANGE_CODES.get(
            (row.get("Listing Exchange") or "").upper(), ("", "")
        )
        if (row.get("Listing Exchange") or "").upper() == "Q":
            code, name = "NMS", "Nasdaq"
        out.append({
            "symbol": symbol,
            "name": row.get("Security Name") or "",
            "quote_type": _quote_type(row),
            "exchange": code,
            "exchange_name": name,
            "status": STATUS_ACTIVE,
            "source": SOURCE,
        })
    return out


def _parse_nasdaq_listed(text: str) -> list:
    out = []
    for row in parse_pipe_file(text):
        if _is_test_issue(row):
            continue
        symbol = to_yahoo_symbol(row.get("Symbol"))
        if not symbol:
            continue
        out.append({
            "symbol": symbol,
            "name": row.get("Security Name") or "",
            "quote_type": _quote_type(row),
            "exchange": "NMS",
            "exchange_name": "Nasdaq",
            "status": STATUS_ACTIVE,
            "source": SOURCE,
        })
    return out


def _parse_other_listed(text: str) -> list:
    out = []
    for row in parse_pipe_file(text):
        if _is_test_issue(row):
            continue
        symbol = to_yahoo_symbol(row.get("NASDAQ Symbol") or row.get("ACT Symbol"))
        if not symbol:
            continue
        code, name = EXCHANGE_CODES.get((row.get("Exchange") or "").upper(), ("", ""))
        out.append({
            "symbol": symbol,
            "name": row.get("Security Name") or "",
            "quote_type": _quote_type(row),
            "exchange": code,
            "exchange_name": name,
            "status": STATUS_ACTIVE,
            "source": SOURCE,
        })
    return out


def _parse_mutual_funds(text: str) -> list:
    out = []
    for row in parse_pipe_file(text):
        symbol = normalize_symbol(row.get("Fund Symbol"))
        if not symbol:
            continue
        out.append({
            "symbol": symbol,
            "name": row.get("Fund Name") or "",
            "quote_type": "MUTUALFUND",
            "status": STATUS_ACTIVE,
            "source": SOURCE,
        })
    return out


# ── symbol translation ─────────────────────────────────────────────────────────

_VALID = re.compile(r"^[A-Z0-9.\-^=]+$")


def to_yahoo_symbol(raw) -> str:
    """Translate a CQS/ACT symbol into Yahoo's spelling.

    ALL.PRB -> ALL-PB   BRK.A -> BRK-A   SPAC.WS -> SPAC-WT   SPAC.U -> SPAC-UN
    """
    if raw is None:
        return ""
    s = str(raw).strip().upper()
    if not s or not _VALID.match(s):
        return ""
    match = CLASS_SUFFIX_RE.fullmatch(s)
    if match:
        head, kind, tail = match.groups()
        s = f"{head}{CLASS_SUFFIX_MAP[kind]}{tail}"
    else:
        for act, yahoo in EXACT_SUFFIX_MAP:
            if s.endswith(act):
                s = f"{s[:-len(act)]}{yahoo}"
                break
    # These files are US-only, so a one-letter tail is always a share class —
    # `PSA.L` here is Public Storage class L, not a London listing.
    return normalize_symbol(s, us_style=True)
