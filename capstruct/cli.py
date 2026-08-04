"""
cli.py - capstruct command line.

    capstruct fetch AAPL --as-of 2025-06-30
    capstruct fetch 0000320193 --output capital_structure.json
    capstruct audit AAPL          # provenance trail for every field
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from .edgar.client import EdgarUnreachable
from .models.provenance import Missing, Sourced
from .pipeline import build_snapshot

app = typer.Typer(add_completion=False, help="SEC capital structure extractor")


def _fmt(value: float | None, unit: str = "USD") -> str:
    if value is None:
        return "—"
    if unit == "shares":
        return f"{value:,.0f}"
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= div:
            return f"${value / div:,.2f}{suffix}"
    return f"${value:,.0f}"


def _render(snap) -> None:
    typer.secho(f"\n{snap.company_name} ({snap.ticker or snap.cik})",
                fg=typer.colors.CYAN, bold=True)
    if snap.source_filing:
        f = snap.source_filing
        typer.echo(f"  governing filing: {f['form']} {f['accession_number']} "
                   f"filed {f['filing_date']} (period {f['period_end']})")
    typer.echo(f"  as-of: {snap.as_of or 'latest'}  "
               f"({'point-in-time' if snap.point_in_time else 'period-based'})")

    def row(label: str, field, unit: str = "USD") -> None:
        if isinstance(field, Sourced):
            flag = "" if field.confidence == "high" else f"  ({field.confidence})"
            typer.echo(f"    {label:<34}{_fmt(field.value, unit):>16}{flag}")
        elif isinstance(field, Missing):
            typer.secho(f"    {label:<34}{'MISSING':>16}", fg=typer.colors.YELLOW)

    typer.secho("\n  Liquidity", bold=True)
    liq = snap.liquidity
    row("Cash and equivalents", liq.cash_and_equivalents)
    row("Short-term investments", liq.short_term_investments)
    row("Restricted cash (current)", liq.restricted_cash_current)
    row("Restricted cash (non-current)", liq.restricted_cash_noncurrent)
    row("Revolver commitment", liq.revolver_commitment)
    row("Revolver drawn", liq.revolver_drawn)
    row("Revolver available", liq.revolver_available)

    typer.secho("\n  Net debt bridge", bold=True)
    nd = snap.net_debt
    for c in nd.components:
        sign = "+" if c["sign"] > 0 else "−"
        val = _fmt(c["value"]) if c["available"] else "MISSING"
        typer.echo(f"    {sign} {c['label']:<32}{val:>16}")
    typer.secho(f"    {'= Net debt':<34}{_fmt(nd.net_debt):>16}",
                bold=True, fg=typer.colors.RED if nd.incomplete else None)
    if nd.incomplete:
        typer.secho("    ⚠ bridge is incomplete — see notes", fg=typer.colors.YELLOW)
    for n in nd.notes:
        typer.echo(f"      · {n}")

    typer.secho("\n  Common equity", bold=True)
    eq = snap.common_equity
    row("Shares outstanding (cover page)", eq.cover_page_shares_outstanding, "shares")
    row("Shares outstanding (balance sheet)", eq.balance_sheet_shares_outstanding, "shares")
    row("Diluted shares (as reported)", eq.diluted_shares_reported, "shares")

    for w in snap.warnings:
        typer.secho(f"\n  ⚠ {w}", fg=typer.colors.YELLOW)
    typer.echo("")


@app.command()
def fetch(
    identifier: str = typer.Argument(..., help="Ticker or CIK"),
    as_of: str = typer.Option(None, "--as-of", help="YYYY-MM-DD"),
    output: Path = typer.Option(None, "--output", "-o", help="Write JSON here"),
    period_based: bool = typer.Option(
        False, "--period-based",
        help="Select by period end rather than what was knowable at --as-of",
    ),
):
    """Fetch a capital structure snapshot."""
    as_of_date = date.fromisoformat(as_of) if as_of else None
    try:
        snap = build_snapshot(identifier, as_of=as_of_date,
                              point_in_time=not period_based)
    except EdgarUnreachable as exc:
        typer.secho(f"SEC unreachable: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    except LookupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except ValueError as exc:
        # Missing User-Agent is a config fix, not a stack trace.
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(3)

    if output:
        output.write_text(json.dumps(
            snap.model_dump(mode="json", warnings=False), indent=2))
        typer.secho(f"wrote {output}", fg=typer.colors.GREEN)
    else:
        _render(snap)


@app.command()
def audit(
    identifier: str = typer.Argument(..., help="Ticker or CIK"),
    as_of: str = typer.Option(None, "--as-of", help="YYYY-MM-DD"),
):
    """Print the provenance trail for every extracted field."""
    as_of_date = date.fromisoformat(as_of) if as_of else None
    try:
        snap = build_snapshot(identifier, as_of=as_of_date)
    except EdgarUnreachable as exc:
        typer.secho(f"SEC unreachable: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(3)

    typer.secho(f"\nProvenance — {snap.company_name}\n", bold=True)
    for line in snap.audit_lines():
        typer.echo(f"  {line}")
    typer.echo("")


if __name__ == "__main__":
    app()
