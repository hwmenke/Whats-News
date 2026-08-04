"""
companyfacts.py - Read companyfacts.json and resolve concepts to values.

Walks each concept's tag priority chain, picks the fact that best matches the
as-of date under point-in-time rules, and returns it wrapped in Sourced with
the tag that produced it recorded as the locator. If no tag in the chain
yields a fact, returns Missing listing everything tried — never a bare None.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..models.provenance import Missing, Sourced, filing_url
from .tagmap import Concept


@dataclass(frozen=True)
class Fact:
    value: float
    end: date
    filed: date
    accession: str
    form: str
    tag: str
    namespace: str
    unit: str
    start: date | None = None
    frame: str | None = None


def _d(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def iter_facts(facts_json: dict, tag: str, namespace: str = "us-gaap",
               unit: str = "USD") -> list[Fact]:
    """All facts for one tag, as Fact records. Empty list if absent."""
    node = ((facts_json.get("facts") or {}).get(namespace) or {}).get(tag)
    if not node:
        return []

    units = node.get("units") or {}
    # Unit keys vary ('USD', 'shares', 'USD/shares'); prefer the requested
    # one but fall back to the only available unit rather than returning
    # nothing on a naming mismatch.
    entries = units.get(unit)
    if entries is None:
        if len(units) == 1:
            unit, entries = next(iter(units.items()))
        else:
            return []

    out: list[Fact] = []
    for e in entries:
        end = _d(e.get("end"))
        filed = _d(e.get("filed"))
        if end is None or filed is None or e.get("val") is None:
            continue
        out.append(Fact(
            value=float(e["val"]),
            end=end,
            filed=filed,
            accession=e.get("accn", ""),
            form=e.get("form", ""),
            tag=tag,
            namespace=namespace,
            unit=unit,
            start=_d(e.get("start")),
            frame=e.get("frame"),
        ))
    return out


def pick_fact(facts: list[Fact], as_of: date | None = None,
              point_in_time: bool = True) -> Fact | None:
    """
    Best fact for an as-of date.

    Point-in-time filters to facts already FILED by as_of, then takes the one
    with the latest period end (and, on ties, the latest filing — an amended
    restatement supersedes the original).
    """
    pool = facts
    if as_of is not None:
        if point_in_time:
            pool = [f for f in facts if f.filed <= as_of]
        else:
            pool = [f for f in facts if f.end <= as_of]
    if not pool:
        return None
    return max(pool, key=lambda f: (f.end, f.filed))


class FactResolver:
    """Resolves Concepts against one issuer's companyfacts payload."""

    def __init__(self, facts_json: dict, cik: int | str,
                 as_of: date | None = None, point_in_time: bool = True):
        self.facts = facts_json
        self.cik = cik
        self.as_of = as_of
        self.point_in_time = point_in_time

    def resolve(self, concept: Concept) -> Sourced[float] | Missing:
        tried: list[str] = []
        for tag in concept.tags:
            tried.append(f"{concept.namespace}:{tag}")
            facts = iter_facts(self.facts, tag, concept.namespace, concept.unit)
            if not facts:
                continue
            fact = pick_fact(facts, self.as_of, self.point_in_time)
            if fact is None:
                continue

            # A tag further down the chain is a broader roll-up, so confidence
            # degrades as we fall back.
            rank = concept.tags.index(tag)
            confidence = "high" if rank == 0 else ("medium" if rank == 1 else "low")

            return Sourced[float](
                value=fact.value,
                source_type="cover_page" if concept.namespace == "dei" else "xbrl",
                accession_number=fact.accession,
                filing_date=fact.filed,
                period_end=fact.end,
                url=filing_url(self.cik, fact.accession),
                confidence=confidence,
                locator=f"{fact.namespace}:{fact.tag}",
                excerpt=None,
            )

        return Missing(
            field=concept.name,
            tried=tried,
            reason="no tag in the fallback chain produced a usable fact",
        )

    def resolve_all(self, concepts) -> dict[str, Sourced[float] | Missing]:
        return {c.name: self.resolve(c) for c in concepts}


def available_tags(facts_json: dict, namespace: str = "us-gaap") -> list[str]:
    """Every tag the filer actually used — for discovering extension tags."""
    return sorted(((facts_json.get("facts") or {}).get(namespace) or {}).keys())


def extension_namespaces(facts_json: dict) -> list[str]:
    """Non-standard namespaces present (custom extension taxonomies)."""
    return sorted(
        ns for ns in (facts_json.get("facts") or {}).keys()
        if ns not in ("us-gaap", "dei", "srt", "invest")
    )
