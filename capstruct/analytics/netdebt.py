"""
netdebt.py - Gross debt -> less cash -> less short-term investments -> net debt.

Every component keeps its provenance, and a bridge built from incomplete
inputs is flagged rather than quietly reported as a smaller number. A missing
cash line makes net debt look worse; a missing debt line makes it look
better. Both are wrong, so `incomplete` travels with the result.
"""
from __future__ import annotations

from typing import Any

from ..models.provenance import Missing, Sourced
from ..models.snapshot import NetDebtBridge, Snapshot


def _val(field) -> float | None:
    return field.value if isinstance(field, Sourced) else None


def _component(label: str, field, sign: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"label": label, "sign": sign}
    if isinstance(field, Sourced):
        entry.update({
            "value": field.value,
            "source": field.source_type,
            "locator": field.locator,
            "accession": field.accession_number,
            "period_end": field.period_end.isoformat(),
            "confidence": field.confidence,
            "available": True,
        })
    else:
        entry.update({
            "value": None,
            "available": False,
            "reason": field.reason if isinstance(field, Missing) else "not extracted",
        })
    return entry


def build(snapshot: Snapshot) -> NetDebtBridge:
    debt = snapshot.debt_summary
    liq = snapshot.liquidity

    components = [
        _component("Gross debt", debt.total_debt, +1),
        _component("Less: cash and equivalents", liq.cash_and_equivalents, -1),
        _component("Less: short-term investments", liq.short_term_investments, -1),
    ]

    gross = _val(debt.total_debt)
    cash = _val(liq.cash_and_equivalents)
    sti = _val(liq.short_term_investments)

    notes: list[str] = []
    # Restricted cash is deliberately NOT netted — it isn't available to
    # repay debt — but it's surfaced so the reader knows it was considered.
    if isinstance(liq.restricted_cash_current, Sourced):
        notes.append(
            f"Restricted cash (current) of {liq.restricted_cash_current.value:,.0f} "
            "excluded from net debt — not available to repay debt."
        )
    if isinstance(liq.restricted_cash_noncurrent, Sourced):
        notes.append(
            f"Restricted cash (non-current) of "
            f"{liq.restricted_cash_noncurrent.value:,.0f} excluded from net debt."
        )

    incomplete = gross is None or cash is None
    if gross is None:
        notes.append("Gross debt unavailable — net debt understated.")
    if cash is None:
        notes.append("Cash unavailable — net debt overstated.")

    net = None
    if gross is not None:
        net = gross - (cash or 0.0) - (sti or 0.0)

    return NetDebtBridge(
        gross_debt=gross,
        less_cash=cash,
        less_short_term_investments=sti,
        net_debt=net,
        components=components,
        incomplete=incomplete,
        notes=notes,
    )
