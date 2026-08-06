"""
sources/wikipedia_indices.py - Index constituents, present and past.

Wikipedia maintains a table of current members for every major index and, for
the US indices, a second table listing every addition and removal going back
two decades. The removals are the valuable half: a ticker that left the S&P 500
because the company was acquired, taken private or wound up is exactly the kind
of dead symbol no exchange directory will ever list again, and Yahoo still
answers for its full price history.

That makes this the cheapest delisted coverage available — ten HTTP requests
for a couple of thousand symbols, a large minority of which no longer trade.

The pages are ordinary HTML behind `HttpClient`. Column positions are never
hardcoded: the header is flattened first (including the two-row
`Date | Added | Removed | Reason` header the changes tables use) and columns are
then picked by name, so a re-ordered or re-labelled table degrades to "found
nothing here" instead of importing whatever happened to be in column 2.
"""

import logging
import re
from html.parser import HTMLParser

from ..db import STATUS_ACTIVE, STATUS_UNKNOWN, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE = "wikipedia"
BASE_URL = "https://en.wikipedia.org/wiki/"

# Header words that identify a ticker column and its companion name column.
SYMBOL_HEADERS = ("symbol", "ticker")
NAME_HEADERS = ("security", "company", "name")
# The changes tables put their two ticker columns under one of these groups.
GROUP_HEADERS = ("added", "removed")

# Yahoo tickers are short and built from these characters. Anything else in a
# cell — a date, a footnote, a sentence of prose — is not a symbol.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]*([.\-][A-Z0-9]+)*$")
MAX_SYMBOL_LEN = 12

# Each page contributes one market, so a bare ticker can be given that market's
# Yahoo suffix. Pages without a suffix are US listings, which carry none.
PAGES = [
    {"page": "List_of_S%26P_500_companies", "index": "S&P 500"},
    {"page": "List_of_S%26P_400_companies", "index": "S&P 400"},
    {"page": "List_of_S%26P_600_companies", "index": "S&P 600"},
    {"page": "Nasdaq-100", "index": "Nasdaq-100"},
    {"page": "Dow_Jones_Industrial_Average", "index": "Dow Jones Industrial Average"},
    {"page": "Russell_1000_Index", "index": "Russell 1000"},
    {"page": "FTSE_100_Index", "index": "FTSE 100",
     "suffix": ".L", "exchange": "LSE", "exchange_name": "London"},
    {"page": "DAX", "index": "DAX",
     "suffix": ".DE", "exchange": "GER", "exchange_name": "XETRA"},
    {"page": "CAC_40", "index": "CAC 40",
     "suffix": ".PA", "exchange": "PAR", "exchange_name": "Paris"},
    {"page": "S%26P/TSX_60", "index": "S&P/TSX 60",
     "suffix": ".TO", "exchange": "TOR", "exchange_name": "Toronto"},
]


def fetch(http, pages=None) -> list:
    """Return index members past and present. Never raises: one page that has
    been restructured must not cost us the other nine."""
    records = {}

    for spec in (pages or PAGES):
        try:
            html = http.get_text(BASE_URL + spec["page"])
        except Exception as exc:
            logger.warning("wikipedia: %s unreachable: %s", spec["page"], exc)
            continue

        try:
            found = parse_page(html, spec)
        except Exception as exc:
            logger.warning("wikipedia: %s did not parse: %s", spec["page"], exc)
            continue

        if not found:
            # Reaching a page and finding nothing means its tables moved. That
            # is worth saying out loud, otherwise coverage quietly rots.
            logger.warning("wikipedia: no ticker column found on %s", spec["page"])

        for rec in found:
            existing = records.get(rec["symbol"])
            # Sitting on a current-constituents table beats a mention in a
            # changes row from 2009, so let `active` win the merge.
            if existing is None or (existing["status"] != STATUS_ACTIVE
                                    and rec["status"] == STATUS_ACTIVE):
                records[rec["symbol"]] = rec
        logger.info("wikipedia: %d symbols after %s", len(records), spec["index"])

    return list(records.values())


def parse_page(html: str, spec: dict) -> list:
    """Every symbol on one page, from every table on it."""
    out = []
    for table in extract_tables(html):
        out.extend(_records_from_table(table, spec))
    return out


def _records_from_table(table, spec: dict) -> list:
    """Pull the (symbol, name) pairs out of one table.

    A constituents table has one ticker column; a changes table has two, under
    an `Added`/`Removed` group header. Modelling both as "a set of column
    groups" lets one code path read either.
    """
    groups = {}
    for idx, label in enumerate(table.headers):
        group = _group_of(label)
        if _matches(label, SYMBOL_HEADERS):
            groups.setdefault(group, {}).setdefault("symbol", idx)
        elif _matches(label, NAME_HEADERS):
            groups.setdefault(group, {}).setdefault("name", idx)

    records = []
    for group, columns in groups.items():
        symbol_idx = columns.get("symbol")
        if symbol_idx is None:
            continue
        name_idx = columns.get("name")
        # Membership today proves the symbol trades today. A changes row proves
        # nothing either way — the price download gets to decide.
        status = STATUS_ACTIVE if group == "" else STATUS_UNKNOWN

        for row in table.rows:
            symbol = _clean_symbol(_cell(row, symbol_idx), spec)
            if not symbol:
                continue
            records.append({
                "symbol": symbol,
                "name": _cell(row, name_idx),
                "quote_type": "EQUITY",
                "exchange": spec.get("exchange", ""),
                "exchange_name": spec.get("exchange_name", ""),
                "status": status,
                "source": SOURCE,
            })
    return records


def _matches(label: str, words) -> bool:
    return any(word in label.lower() for word in words)


def _group_of(label: str) -> str:
    lowered = label.lower()
    for group in GROUP_HEADERS:
        if group in lowered:
            return group
    return ""


def _cell(row, index) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _clean_symbol(raw: str, spec: dict) -> str:
    """One table cell -> a Yahoo symbol, or "" if the cell is not a ticker."""
    text = (raw or "").strip().upper()
    # Cells read "AAPL", but also "AAPL (Apple Inc.)" and "AAPL[1]".
    text = text.split("(")[0].split("[")[0].strip()
    text = text.split(" ")[0] if text else ""
    if not text or len(text) > MAX_SYMBOL_LEN or not _SYMBOL_RE.match(text):
        return ""

    suffix = spec.get("suffix") or ""
    # Strip a market suffix the page already spelled out, so it survives
    # normalization intact and does not end up doubled.
    if suffix and text.endswith(suffix):
        text = text[: -len(suffix)]
    # Within a single market a dotted tail is always a share class (BRK.B,
    # BT.A) — the market itself is what `suffix` carries.
    base = normalize_symbol(text, us_style=True)
    if not base:
        return ""
    return base + suffix


# ── HTML tables ────────────────────────────────────────────────────────────────

class Table:
    """One parsed table: flattened column labels plus its body rows."""

    def __init__(self, headers, rows):
        self.headers = headers
        self.rows = rows


def extract_tables(html: str) -> list:
    """Every `wikitable` in `html`, as `Table` objects."""
    parser = _TableParser()
    parser.feed(html or "")
    parser.close()
    return parser.tables


# Tags whose text is decoration, not data: reference markers, sort keys and the
# inline CSS Wikipedia templates emit inside cells.
_SKIP_TAGS = {"sup", "style", "script"}


class _TableParser(HTMLParser):
    """A minimal `<table>` reader that expands colspan/rowspan and flattens a
    multi-row header into one label per column ("Added Ticker", …).

    Only `wikitable`s are kept, and only at the outermost nesting level, so an
    infobox or navbox sitting inside a cell cannot inject phantom rows.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._depth = 0
        self._keep = False
        self._skip = 0
        self._header_rows = []
        self._body_rows = []
        self._cells = []
        self._buffer = []
        self._in_cell = False
        self._row_is_header = True
        self._colspan = 1
        self._rowspan = 1
        self._carry = {}

    # ── tag handling ───────────────────────────────────────────────────────────

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._start_table(attrs)
            return
        if self._depth != 1 or not self._keep:
            return
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "tr":
            self._start_row()
        elif tag in ("th", "td"):
            self._start_cell(tag, attrs)
        elif tag == "br" and self._in_cell:
            self._buffer.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            if self._depth == 1 and self._keep:
                self._end_row()
                self._end_table()
            self._depth = max(0, self._depth - 1)
            return
        if self._depth != 1 or not self._keep:
            return
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in ("th", "td"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()

    def handle_data(self, data):
        if self._in_cell and not self._skip:
            self._buffer.append(data)

    # ── table assembly ─────────────────────────────────────────────────────────

    def _start_table(self, attrs):
        self._keep = "wikitable" in (attrs.get("class") or "")
        self._header_rows = []
        self._body_rows = []
        self._carry = {}
        self._cells = []
        self._in_cell = False

    def _end_table(self):
        if self._header_rows or self._body_rows:
            self.tables.append(Table(_flatten_headers(self._header_rows),
                                     self._body_rows))
        self._keep = False

    def _start_row(self):
        self._end_row()
        self._cells = []
        self._row_is_header = True

    def _end_row(self):
        # A cell left open by unclosed markup still counts as a row.
        if not self._cells and not self._in_cell:
            return
        self._end_cell()
        row = _place(self._cells, self._carry)
        # Header rows are the `th`-only rows before the first body row; a `th`
        # row further down is a section divider, not a second header.
        if self._row_is_header and not self._body_rows:
            self._header_rows.append(row)
        else:
            self._body_rows.append(row)
        self._cells = []

    def _start_cell(self, tag, attrs):
        self._end_cell()
        self._in_cell = True
        self._buffer = []
        self._colspan = _span(attrs.get("colspan"))
        self._rowspan = _span(attrs.get("rowspan"))
        if tag == "td":
            self._row_is_header = False

    def _end_cell(self):
        if not self._in_cell:
            return
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._cells.append((text, self._colspan, self._rowspan))
        self._in_cell = False
        self._buffer = []


def _span(value) -> int:
    try:
        return max(1, min(50, int(str(value).strip())))
    except (TypeError, ValueError):
        return 1


def _place(cells, carry: dict) -> list:
    """Lay one row of cells onto the grid, honouring rowspans still in flight."""
    row = []
    queue = list(cells)
    column = 0
    while queue or column in carry:
        if column in carry:
            text, remaining = carry[column]
            row.append(text)
            if remaining <= 1:
                del carry[column]
            else:
                carry[column] = (text, remaining - 1)
            column += 1
            continue
        text, colspan, rowspan = queue.pop(0)
        for _ in range(colspan):
            row.append(text)
            if rowspan > 1:
                carry[column] = (text, rowspan - 1)
            column += 1
    return row


def _flatten_headers(header_rows) -> list:
    """["Date","Added","Added",…] + ["","Ticker","Security",…]
    -> ["Date", "Added Ticker", "Added Security", …]"""
    width = max((len(row) for row in header_rows), default=0)
    labels = []
    for column in range(width):
        parts = []
        for row in header_rows:
            value = row[column] if column < len(row) else ""
            if value and value not in parts:
                parts.append(value)
        labels.append(" ".join(parts))
    return labels
