"""
filings.py - Choosing WHICH filing answers an as-of question.

Two rules everything downstream depends on:

1. Point-in-time. `--as-of 2025-06-30` means "as knowable on that date", so
   only filings with filing_date <= as_of are eligible. A Q2 balance sheet
   filed in August must not appear in a June 30 snapshot — the same lookahead
   trap that makes a backtest lie.

2. Supersession. A 10-K/A replaces the 10-K for the same period. Amendments
   are folded onto the original by (form, period), newest filing_date wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

PERIODIC_FORMS = ("10-K", "10-Q")


@dataclass(frozen=True)
class Filing:
    accession_number: str
    form: str
    filing_date: date
    period_end: date | None
    primary_document: str
    cik: int

    @property
    def base_form(self) -> str:
        """'10-K/A' -> '10-K' so amendments group with what they amend."""
        return self.form.split("/")[0]

    @property
    def is_amendment(self) -> bool:
        return self.form.endswith("/A")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_submissions(payload: dict) -> list[Filing]:
    """Flatten a submissions.json `filings.recent` block into Filing records."""
    cik = int(payload.get("cik", 0))
    recent = (payload.get("filings") or {}).get("recent") or {}

    accessions = recent.get("accessionNumber", []) or []
    forms = recent.get("form", []) or []
    filed = recent.get("filingDate", []) or []
    periods = recent.get("reportDate", []) or []
    docs = recent.get("primaryDocument", []) or []

    out: list[Filing] = []
    for i, acc in enumerate(accessions):
        fdate = _parse_date(filed[i] if i < len(filed) else None)
        if fdate is None:
            continue                     # a filing with no date can't be ordered
        out.append(Filing(
            accession_number=acc,
            form=(forms[i] if i < len(forms) else "").strip(),
            filing_date=fdate,
            period_end=_parse_date(periods[i] if i < len(periods) else None),
            primary_document=(docs[i] if i < len(docs) else ""),
            cik=cik,
        ))
    return out


def select(
    filings: Iterable[Filing],
    as_of: date | None = None,
    forms: tuple[str, ...] = PERIODIC_FORMS,
    point_in_time: bool = True,
) -> list[Filing]:
    """
    Eligible filings, newest first, amendments folded in.

    point_in_time=True  -> filed on or before as_of (what was knowable then)
    point_in_time=False -> period ending on or before as_of, regardless of
                           when it was filed (useful for "latest data for Q2"
                           when you don't care about lookahead)
    """
    pool = [f for f in filings if f.base_form in forms]

    if as_of is not None:
        if point_in_time:
            pool = [f for f in pool if f.filing_date <= as_of]
        else:
            pool = [f for f in pool if f.period_end and f.period_end <= as_of]

    # Supersession: newest filing_date wins per (base form, period).
    best: dict[tuple[str, date | None], Filing] = {}
    for f in pool:
        key = (f.base_form, f.period_end)
        cur = best.get(key)
        if cur is None or f.filing_date > cur.filing_date:
            best[key] = f

    return sorted(
        best.values(),
        key=lambda f: (f.period_end or date.min, f.filing_date),
        reverse=True,
    )


def latest(
    filings: Iterable[Filing],
    as_of: date | None = None,
    forms: tuple[str, ...] = PERIODIC_FORMS,
    point_in_time: bool = True,
) -> Filing | None:
    """The single most relevant filing for an as-of date, or None."""
    chosen = select(filings, as_of=as_of, forms=forms, point_in_time=point_in_time)
    return chosen[0] if chosen else None
