"""
provenance.py - Every extracted value carries where it came from.

A value that cannot be traced back to a sentence in a specific filing is
worse than a missing one, so `Sourced[T]` is the only way values enter the
model layer. `Missing` records the attempt that failed, which is why a
field is null rather than leaving the caller guessing.
"""
from __future__ import annotations

from datetime import date
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

SourceType = Literal["xbrl", "footnote", "exhibit", "cover_page", "derived"]
Confidence = Literal["high", "medium", "low"]

EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"


class Sourced(BaseModel, Generic[T]):
    """A value plus a full audit trail back to the filing it came from."""

    value: T
    source_type: SourceType
    accession_number: str
    filing_date: date
    period_end: date
    excerpt: str | None = None
    url: str = ""
    confidence: Confidence = "high"
    # Which XBRL tag / footnote heading / exhibit produced this, so a wrong
    # value can be traced to the rule that picked it, not just the filing.
    locator: str | None = None

    def audit(self) -> str:
        """One-line human-readable trace, for terminal output and logs."""
        parts = [
            f"{self.value!r}",
            f"[{self.source_type}",
            f"{self.locator}]" if self.locator else "]",
            f"{self.accession_number} filed {self.filing_date}",
            f"period {self.period_end}",
            f"confidence={self.confidence}",
        ]
        return " ".join(p for p in parts if p)


class Missing(BaseModel):
    """
    Records a failed extraction. Never silently return null — say which
    sources were tried so the gap is actionable.
    """

    field: str
    tried: list[str] = Field(default_factory=list)
    reason: str = "not found"

    def audit(self) -> str:
        return f"{self.field}: MISSING ({self.reason}; tried {', '.join(self.tried) or 'nothing'})"


def filing_url(cik: int | str, accession_number: str, document: str | None = None) -> str:
    """Deep link to a filing or one of its documents."""
    cik_int = int(str(cik).lstrip("0") or 0)
    acc_nodash = accession_number.replace("-", "")
    base = f"{EDGAR_ARCHIVE}/{cik_int}/{acc_nodash}"
    return f"{base}/{document}" if document else f"{base}/{accession_number}-index.htm"
