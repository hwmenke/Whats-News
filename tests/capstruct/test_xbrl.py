"""
XBRL layer tests: tag fallback chains, namespace handling, point-in-time fact
selection, extension-tag detection, and the net-debt bridge.

Fixtures are hand-built companyfacts payloads shaped exactly like SEC's, each
encoding one of the traps in the spec.
"""
import unittest
from datetime import date

from capstruct.analytics import netdebt
from capstruct.models.provenance import Missing, Sourced
from capstruct.models.snapshot import DebtSummary, Liquidity, Snapshot
from capstruct.xbrl.companyfacts import (
    FactResolver, extension_namespaces, iter_facts, pick_fact,
)
from capstruct.xbrl.tagmap import EQUITY_CONCEPTS, LIQUIDITY_CONCEPTS, concept


def usd(val, end, filed, accn="0000-24-001", form="10-Q"):
    return {"val": val, "end": end, "filed": filed, "accn": accn, "form": form}


# A filer that uses the PREFERRED cash tag.
CLEAN_FILER = {
    "cik": 111,
    "facts": {
        "us-gaap": {
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
                usd(1_000, "2024-03-31", "2024-05-01"),
                usd(1_500, "2024-06-30", "2024-08-01"),
            ]}},
            "ShortTermInvestments": {"units": {"USD": [
                usd(500, "2024-06-30", "2024-08-01"),
            ]}},
            "LongTermDebt": {"units": {"USD": [
                usd(4_000, "2024-06-30", "2024-08-01"),
            ]}},
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {"units": {"shares": [
                usd(9_000, "2024-07-25", "2024-08-01"),
            ]}},
        },
    },
}

# A filer that reports only the BROADER cash tag (restricted cash included)
# and uses a custom extension namespace.
FALLBACK_FILER = {
    "cik": 222,
    "facts": {
        "us-gaap": {
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": {
                "units": {"USD": [usd(2_200, "2024-06-30", "2024-08-01")]}
            },
            "RestrictedCashCurrent": {"units": {"USD": [
                usd(200, "2024-06-30", "2024-08-01"),
            ]}},
        },
        "acme": {   # custom extension taxonomy
            "AcmeSpecialBorrowings": {"units": {"USD": [
                usd(750, "2024-06-30", "2024-08-01"),
            ]}},
        },
    },
}


class TagFallbackTests(unittest.TestCase):
    def test_preferred_tag_wins_with_high_confidence(self):
        r = FactResolver(CLEAN_FILER, 111)
        got = r.resolve(concept("cash_and_equivalents"))
        self.assertIsInstance(got, Sourced)
        self.assertEqual(got.value, 1_500)
        self.assertEqual(got.locator, "us-gaap:CashAndCashEquivalentsAtCarryingValue")
        self.assertEqual(got.confidence, "high")

    def test_falls_back_and_degrades_confidence(self):
        # The broader roll-up tag is a superset (it includes restricted cash),
        # so using it must not claim the same confidence as the clean tag.
        r = FactResolver(FALLBACK_FILER, 222)
        got = r.resolve(concept("cash_and_equivalents"))
        self.assertIsInstance(got, Sourced)
        self.assertEqual(got.value, 2_200)
        self.assertEqual(got.confidence, "medium")
        self.assertIn("RestrictedCash", got.locator)

    def test_missing_lists_every_tag_tried(self):
        # Never a bare None — the gap has to be actionable.
        r = FactResolver(FALLBACK_FILER, 222)
        got = r.resolve(concept("short_term_investments"))
        self.assertIsInstance(got, Missing)
        self.assertEqual(got.field, "short_term_investments")
        self.assertIn("us-gaap:ShortTermInvestments", got.tried)
        self.assertGreater(len(got.tried), 1)

    def test_cover_page_uses_dei_namespace(self):
        r = FactResolver(CLEAN_FILER, 111)
        got = r.resolve(concept("cover_page_shares_outstanding"))
        self.assertIsInstance(got, Sourced)
        self.assertEqual(got.value, 9_000)
        self.assertEqual(got.source_type, "cover_page")
        # Cover-page date is more current than the balance sheet date; both
        # must be recoverable from the record.
        self.assertEqual(got.period_end, date(2024, 7, 25))
        self.assertEqual(got.filing_date, date(2024, 8, 1))

    def test_detects_custom_extension_namespaces(self):
        self.assertEqual(extension_namespaces(FALLBACK_FILER), ["acme"])
        self.assertEqual(extension_namespaces(CLEAN_FILER), [])


class FactSelectionTests(unittest.TestCase):
    def test_point_in_time_excludes_unfiled_facts(self):
        facts = iter_facts(CLEAN_FILER, "CashAndCashEquivalentsAtCarryingValue")
        # On 2024-07-15 the Q2 figure (filed 08-01) was not yet public.
        picked = pick_fact(facts, as_of=date(2024, 7, 15))
        self.assertEqual(picked.value, 1_000)
        self.assertEqual(picked.end, date(2024, 3, 31))

    def test_period_based_mode_allows_later_filing(self):
        facts = iter_facts(CLEAN_FILER, "CashAndCashEquivalentsAtCarryingValue")
        picked = pick_fact(facts, as_of=date(2024, 7, 15), point_in_time=False)
        self.assertEqual(picked.value, 1_500)

    def test_unit_mismatch_falls_back_to_sole_unit(self):
        facts = iter_facts(CLEAN_FILER, "EntityCommonStockSharesOutstanding",
                           namespace="dei", unit="USD")
        self.assertEqual(len(facts), 1)          # found via the only unit present
        self.assertEqual(facts[0].unit, "shares")

    def test_absent_tag_returns_empty(self):
        self.assertEqual(iter_facts(CLEAN_FILER, "NoSuchTag"), [])


class NetDebtTests(unittest.TestCase):
    def _snapshot(self, facts, cik):
        r = FactResolver(facts, cik)
        liq = r.resolve_all(LIQUIDITY_CONCEPTS)
        return Snapshot(
            cik=cik,
            liquidity=Liquidity(**{k: v for k, v in liq.items()
                                   if k in Liquidity.model_fields}),
            debt_summary=DebtSummary(**{k: v for k, v in liq.items()
                                        if k in DebtSummary.model_fields}),
        )

    def test_bridge_arithmetic_and_traceability(self):
        snap = self._snapshot(CLEAN_FILER, 111)
        bridge = netdebt.build(snap)
        self.assertEqual(bridge.gross_debt, 4_000)
        self.assertEqual(bridge.less_cash, 1_500)
        self.assertEqual(bridge.less_short_term_investments, 500)
        self.assertEqual(bridge.net_debt, 2_000)
        self.assertFalse(bridge.incomplete)
        # Every component carries its own provenance
        gross = [c for c in bridge.components if c["label"] == "Gross debt"][0]
        self.assertTrue(gross["available"])
        self.assertEqual(gross["locator"], "us-gaap:LongTermDebt")

    def test_incomplete_bridge_is_flagged_not_silently_smaller(self):
        snap = self._snapshot(FALLBACK_FILER, 222)   # no debt tag at all
        bridge = netdebt.build(snap)
        self.assertTrue(bridge.incomplete)
        self.assertIsNone(bridge.net_debt)
        self.assertTrue(any("understated" in n for n in bridge.notes))

    def test_restricted_cash_is_not_netted(self):
        snap = self._snapshot(FALLBACK_FILER, 222)
        bridge = netdebt.build(snap)
        self.assertTrue(any("Restricted cash" in n for n in bridge.notes))
        # 200 of restricted cash must not appear as a deduction
        labels = [c["label"] for c in bridge.components]
        self.assertNotIn("Less: restricted cash", labels)


class ProvenanceTests(unittest.TestCase):
    def test_every_resolved_field_can_be_audited(self):
        r = FactResolver(CLEAN_FILER, 111)
        liq = r.resolve_all(LIQUIDITY_CONCEPTS)
        eq = r.resolve_all(EQUITY_CONCEPTS)
        snap = Snapshot(
            cik=111,
            liquidity=Liquidity(**{k: v for k, v in liq.items()
                                   if k in Liquidity.model_fields}),
        )
        lines = snap.audit_lines()
        self.assertTrue(lines)
        # Every field is accounted for: either a sourced value carrying a
        # confidence, or an explicit MISSING naming what was tried. Nothing
        # is silently absent from the trail.
        self.assertTrue(all(("confidence=" in ln) or ("MISSING" in ln)
                            for ln in lines))
        self.assertTrue(any("MISSING" in ln for ln in lines))
        self.assertTrue(any("confidence=high" in ln for ln in lines))
        # A resolved value knows its filing and its tag
        cash = liq["cash_and_equivalents"]
        self.assertIn("0000-24-001", cash.audit())
        self.assertTrue(cash.url.startswith("https://www.sec.gov/Archives/"))


if __name__ == "__main__":
    unittest.main()
