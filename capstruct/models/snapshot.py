"""
snapshot.py - The capital structure snapshot returned to callers.

v1 covers liquidity, common equity and the net-debt bridge. Straight debt,
convertibles, warrants and preferred are declared here as empty collections
so the schema (and every consumer) is stable while those extractors land.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from .provenance import Missing, Sourced

# Every field is "a sourced value or an explained absence".
Field_ = Sourced[float] | Missing | None


class Liquidity(BaseModel):
    cash_and_equivalents: Field_ = None
    short_term_investments: Field_ = None
    restricted_cash_current: Field_ = None
    restricted_cash_noncurrent: Field_ = None
    revolver_commitment: Field_ = None
    revolver_drawn: Field_ = None
    revolver_available: Field_ = None


class CommonEquity(BaseModel):
    cover_page_shares_outstanding: Field_ = None
    balance_sheet_shares_outstanding: Field_ = None
    diluted_shares_reported: Field_ = None


class DebtSummary(BaseModel):
    total_debt: Field_ = None
    long_term_debt_current: Field_ = None


class NetDebtBridge(BaseModel):
    """Gross debt -> less cash -> less short-term investments -> net debt."""

    gross_debt: float | None = None
    less_cash: float | None = None
    less_short_term_investments: float | None = None
    net_debt: float | None = None
    components: list[dict[str, Any]] = Field(default_factory=list)
    incomplete: bool = False
    notes: list[str] = Field(default_factory=list)


class Snapshot(BaseModel):
    cik: int
    ticker: str = ""
    company_name: str = ""
    as_of: date | None = None
    point_in_time: bool = True

    source_filing: dict[str, Any] | None = None

    liquidity: Liquidity = Field(default_factory=Liquidity)
    common_equity: CommonEquity = Field(default_factory=CommonEquity)
    debt_summary: DebtSummary = Field(default_factory=DebtSummary)
    net_debt: NetDebtBridge = Field(default_factory=NetDebtBridge)

    # Landing in later phases; present so the schema never changes shape.
    straight_debt: list[dict[str, Any]] = Field(default_factory=list)
    convertibles: list[dict[str, Any]] = Field(default_factory=list)
    warrants: list[dict[str, Any]] = Field(default_factory=list)
    preferred: list[dict[str, Any]] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
    extension_namespaces: list[str] = Field(default_factory=list)

    def audit_lines(self) -> list[str]:
        """Flat audit trail of every field that carries provenance."""
        lines: list[str] = []
        for section in ("liquidity", "common_equity", "debt_summary"):
            block = getattr(self, section)
            for name, val in block.model_dump(warnings=False).items():
                obj = getattr(block, name)
                if obj is None:
                    continue
                lines.append(f"{section}.{name}: {obj.audit()}")
        return lines
