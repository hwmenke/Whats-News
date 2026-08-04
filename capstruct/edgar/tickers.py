"""
tickers.py - Ticker <-> CIK resolution against SEC's company_tickers.json.
"""
from __future__ import annotations

import re

CIK_RE = re.compile(r"^\d{1,10}$")


class TickerResolver:
    def __init__(self, client):
        self._client = client
        self._by_ticker: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._by_ticker is None:
            payload = self._client.company_tickers()
            # company_tickers.json is {"0": {cik_str, ticker, title}, ...}
            self._by_ticker = {
                str(row["ticker"]).upper(): {
                    "cik": int(row["cik_str"]),
                    "ticker": str(row["ticker"]).upper(),
                    "title": row.get("title", ""),
                }
                for row in payload.values()
                if row.get("ticker")
            }
        return self._by_ticker

    def resolve(self, identifier: str) -> dict:
        """
        Accept a ticker ('AAPL') or a CIK ('320193' / '0000320193') and
        return {cik, ticker, title}. Raises LookupError if unknown.
        """
        ident = identifier.strip()
        if CIK_RE.match(ident):
            cik = int(ident)
            for row in self._load().values():
                if row["cik"] == cik:
                    return row
            return {"cik": cik, "ticker": "", "title": ""}

        row = self._load().get(ident.upper())
        if row is None:
            raise LookupError(f"unknown ticker or CIK: {identifier!r}")
        return row
