"""
pipeline.py - Orchestration: identifier in, Snapshot out.

This is the entry point both the CLI and FinDash call. It resolves the
issuer, picks the governing filing under point-in-time rules, runs the XBRL
layer, and builds the net-debt bridge. Document/LLM extraction hangs off the
same Snapshot in later phases.
"""
from __future__ import annotations

from datetime import date

from .analytics import netdebt
from .edgar.client import EdgarClient, EdgarUnreachable
from .edgar.filings import latest, parse_submissions
from .edgar.tickers import TickerResolver
from .models.snapshot import CommonEquity, DebtSummary, Liquidity, Snapshot
from .xbrl.companyfacts import FactResolver, extension_namespaces
from .xbrl.tagmap import EQUITY_CONCEPTS, LIQUIDITY_CONCEPTS, concept


def build_snapshot(
    identifier: str,
    as_of: date | None = None,
    client: EdgarClient | None = None,
    point_in_time: bool = True,
) -> Snapshot:
    """
    Fetch and assemble a capital-structure snapshot.

    Raises EdgarUnreachable when SEC cannot be reached, so callers can tell
    "no network" apart from "issuer has no data".
    """
    own_client = client is None
    client = client or EdgarClient()

    try:
        ident = TickerResolver(client).resolve(identifier)
        cik = ident["cik"]

        subs = client.submissions(cik)
        filings = parse_submissions(subs)
        governing = latest(filings, as_of=as_of, point_in_time=point_in_time)

        facts = client.company_facts(cik)
        resolver = FactResolver(facts, cik, as_of=as_of, point_in_time=point_in_time)

        liq_fields = resolver.resolve_all(LIQUIDITY_CONCEPTS)
        eq_fields = resolver.resolve_all(EQUITY_CONCEPTS)

        snap = Snapshot(
            cik=cik,
            ticker=ident.get("ticker", ""),
            company_name=subs.get("name") or ident.get("title", ""),
            as_of=as_of,
            point_in_time=point_in_time,
            source_filing=(
                {
                    "accession_number": governing.accession_number,
                    "form": governing.form,
                    "filing_date": governing.filing_date.isoformat(),
                    "period_end": governing.period_end.isoformat() if governing.period_end else None,
                }
                if governing else None
            ),
            liquidity=Liquidity(**{
                k: v for k, v in liq_fields.items()
                if k in Liquidity.model_fields
            }),
            common_equity=CommonEquity(**{
                k: v for k, v in eq_fields.items()
                if k in CommonEquity.model_fields
            }),
            debt_summary=DebtSummary(**{
                k: v for k, v in liq_fields.items()
                if k in DebtSummary.model_fields
            }),
            extension_namespaces=extension_namespaces(facts),
        )

        snap.net_debt = netdebt.build(snap)

        if governing is None:
            snap.warnings.append(
                "No 10-K/10-Q found for the requested as-of date; XBRL facts "
                "may come from a later filing."
            )
        if snap.extension_namespaces:
            snap.warnings.append(
                "Filer uses custom extension taxonomies "
                f"({', '.join(snap.extension_namespaces)}) — some concepts may "
                "need document extraction."
            )
        return snap

    finally:
        if own_client:
            client.close()


def snapshot_or_error(identifier: str, as_of: date | None = None,
                      point_in_time: bool = True) -> dict:
    """
    Same as build_snapshot but returns a JSON-able dict, converting
    unreachable-SEC into a structured error instead of an exception. This is
    what the FinDash endpoint calls.
    """
    try:
        snap = build_snapshot(identifier, as_of=as_of, point_in_time=point_in_time)
        return {"ok": True, "snapshot": snap.model_dump(mode="json", warnings=False)}
    except EdgarUnreachable as exc:
        return {
            "ok": False,
            "error": "sec_unreachable",
            "detail": str(exc),
            "hint": "SEC endpoints (data.sec.gov, www.sec.gov) must be reachable "
                    "from this environment.",
        }
    except LookupError as exc:
        return {"ok": False, "error": "unknown_identifier", "detail": str(exc)}
    except ValueError as exc:
        # A missing User-Agent is a one-line config fix, not a bad request —
        # give it its own error type so the UI can say exactly what to set.
        if "User-Agent" in str(exc):
            return {
                "ok": False,
                "error": "config_required",
                "detail": str(exc),
                "hint": "SEC requires a contact email on every request. Set "
                        "CAPSTRUCT_USER_AGENT, e.g. "
                        '`export CAPSTRUCT_USER_AGENT="FinDash you@example.com"`',
            }
        return {"ok": False, "error": "bad_request", "detail": str(exc)}
