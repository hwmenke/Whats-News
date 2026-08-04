"""
tagmap.py - Concept -> ordered tag fallback chains.

Two filers reporting the same economic concept routinely pick different
us-gaap tags, and some invent extension tags. Each concept therefore has a
PRIORITY LIST, tried in order; the first tag with a usable fact wins and the
tag that produced it is recorded as the value's locator.

Order matters: the most specific/narrow tag comes first, broader
roll-up tags after. Cash is the canonical example — the "restricted cash
included" variant is a superset and must not outrank the clean one.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Concept:
    name: str
    tags: tuple[str, ...]
    namespace: str = "us-gaap"
    # Facts are point-in-time (instant, e.g. a balance) or period-based
    # (duration, e.g. revenue). Picking the wrong one silently mixes them.
    kind: str = "instant"
    unit: str = "USD"
    description: str = ""
    extension_hints: tuple[str, ...] = field(default_factory=tuple)


LIQUIDITY_CONCEPTS: tuple[Concept, ...] = (
    Concept(
        name="cash_and_equivalents",
        tags=(
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "CashAndDueFromBanks",
            "CashCashEquivalentsAndShortTermInvestments",
        ),
        description="Unrestricted cash and cash equivalents",
    ),
    Concept(
        name="short_term_investments",
        tags=(
            "ShortTermInvestments",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
            "MarketableSecuritiesCurrent",
            "OtherShortTermInvestments",
        ),
        description="Short-term investments / marketable securities",
    ),
    Concept(
        name="restricted_cash_current",
        tags=(
            "RestrictedCashCurrent",
            "RestrictedCashAndCashEquivalentsAtCarryingValue",
            "RestrictedCashAndInvestmentsCurrent",
        ),
        description="Restricted cash, current",
    ),
    Concept(
        name="restricted_cash_noncurrent",
        tags=(
            "RestrictedCashNoncurrent",
            "RestrictedCashAndInvestmentsNoncurrent",
        ),
        description="Restricted cash, non-current",
    ),
    Concept(
        name="total_debt",
        tags=(
            "DebtLongtermAndShorttermCombinedAmount",
            "LongTermDebt",
            "LongTermDebtNoncurrent",
            "DebtInstrumentCarryingAmount",
        ),
        description="Gross debt (carrying)",
    ),
    Concept(
        name="long_term_debt_current",
        tags=(
            "LongTermDebtCurrent",
            "DebtCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
        ),
        description="Current portion of long-term debt",
    ),
    Concept(
        name="revolver_drawn",
        tags=(
            "LineOfCredit",
            "LineOfCreditFacilityAmountOutstanding",
            "LongTermLineOfCredit",
        ),
        description="Revolver drawn balance",
    ),
    Concept(
        name="revolver_commitment",
        tags=("LineOfCreditFacilityMaximumBorrowingCapacity",),
        description="Revolver total commitment",
    ),
    Concept(
        name="revolver_available",
        tags=("LineOfCreditFacilityRemainingBorrowingCapacity",),
        description="Revolver remaining capacity",
    ),
)

EQUITY_CONCEPTS: tuple[Concept, ...] = (
    Concept(
        name="cover_page_shares_outstanding",
        tags=("EntityCommonStockSharesOutstanding",),
        namespace="dei",              # cover-page facts are NOT us-gaap
        unit="shares",
        description="Shares outstanding from the cover page (more current "
                    "than the balance sheet date)",
    ),
    Concept(
        name="balance_sheet_shares_outstanding",
        tags=(
            "CommonStockSharesOutstanding",
            "CommonStockSharesIssued",
        ),
        unit="shares",
        description="Shares outstanding at the balance sheet date",
    ),
    Concept(
        name="diluted_shares_reported",
        tags=(
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfDilutedSharesOutstandingAdjustment",
        ),
        kind="duration",
        unit="shares",
        description="As-reported weighted average diluted shares",
    ),
)

ALL_CONCEPTS: tuple[Concept, ...] = LIQUIDITY_CONCEPTS + EQUITY_CONCEPTS

BY_NAME: dict[str, Concept] = {c.name: c for c in ALL_CONCEPTS}


def concept(name: str) -> Concept:
    try:
        return BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"unknown concept {name!r}") from exc
