"""
Tests for the EDGAR foundation: rate limiter, cache policy, filing selection.

No network: the limiter uses injected clocks and the client is driven through
an httpx MockTransport.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import httpx

from capstruct.edgar.cache import IMMUTABLE, MUTABLE_TTL, ResponseCache, policy_for
from capstruct.edgar.client import EdgarClient, EdgarUnreachable
from capstruct.edgar.filings import Filing, latest, parse_submissions, select
from capstruct.edgar.ratelimit import TokenBucket

UA = "CapStruct Test test@example.com"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class RateLimitTests(unittest.TestCase):
    def test_burst_then_throttle(self):
        clock = FakeClock()
        b = TokenBucket(rate=10, capacity=10,
                        time_fn=clock.time, sleep_fn=clock.sleep)
        # Capacity allows an immediate burst with no waiting.
        for _ in range(10):
            self.assertEqual(b.acquire(), 0.0)
        # The 11th must wait for a refill.
        waited = b.acquire()
        self.assertAlmostEqual(waited, 0.1, places=6)

    def test_sustained_rate_never_exceeds_limit(self):
        clock = FakeClock()
        b = TokenBucket(rate=10, capacity=1,
                        time_fn=clock.time, sleep_fn=clock.sleep)
        b.acquire()
        for _ in range(20):
            b.acquire()
        # 20 requests after the first at 10/sec == 2.0s of virtual time.
        self.assertAlmostEqual(clock.now, 2.0, places=6)

    def test_default_rate_is_under_sec_limit(self):
        self.assertLessEqual(TokenBucket().rate, 10.0)

    def test_rejects_impossible_request(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate=5, capacity=5).acquire(6)


class CachePolicyTests(unittest.TestCase):
    def test_archives_are_immutable(self):
        url = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl.htm"
        self.assertIs(policy_for(url), IMMUTABLE)

    def test_xbrl_apis_are_mutable(self):
        # companyfacts is rebuilt as new filings land — caching it forever
        # would serve a stale capital structure.
        self.assertEqual(
            policy_for("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"),
            MUTABLE_TTL,
        )

    def test_roundtrip_and_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            c = ResponseCache(d)
            url = "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json"
            c.put(url, b"hello", etag='"abc"', ttl=MUTABLE_TTL)
            e = c.get(url)
            self.assertEqual(e.body, b"hello")
            self.assertEqual(e.etag, '"abc"')
            self.assertFalse(e.expired)

            c.put(url, b"stale", ttl=-1)          # already past its TTL
            self.assertTrue(c.get(url).expired)


class ClientTests(unittest.TestCase):
    def _client(self, handler, cache_dir):
        return EdgarClient(
            user_agent=UA,
            cache=ResponseCache(cache_dir),
            bucket=TokenBucket(rate=1000, capacity=1000),
            transport=httpx.MockTransport(handler),
        )

    def test_requires_contact_email_in_user_agent(self):
        with self.assertRaises(ValueError):
            EdgarClient(user_agent="capstruct")

    def test_sends_user_agent_and_caches(self):
        seen = []

        def handler(request):
            seen.append(request.headers.get("user-agent"))
            return httpx.Response(200, json={"ok": True}, headers={"ETag": '"v1"'})

        with tempfile.TemporaryDirectory() as d:
            c = self._client(handler, d)
            url = "https://www.sec.gov/Archives/edgar/data/1/x/doc.htm"
            self.assertEqual(c.get_json(url), {"ok": True})
            c.get_json(url)                      # second call served from cache
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0], UA)

    def test_403_becomes_unreachable_not_empty_data(self):
        def handler(request):
            return httpx.Response(403, text="blocked")

        with tempfile.TemporaryDirectory() as d:
            c = self._client(handler, d)
            with self.assertRaises(EdgarUnreachable):
                c.get("https://data.sec.gov/api/xbrl/companyfacts/CIK1.json")

    def test_304_revalidation_serves_cached_body(self):
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(200, content=b"body-v1",
                                      headers={"ETag": '"v1"'})
            return httpx.Response(304)

        with tempfile.TemporaryDirectory() as d:
            c = self._client(handler, d)
            url = "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json"
            self.assertEqual(c.get(url), b"body-v1")
            c.cache.put(url, b"body-v1", etag='"v1"', ttl=-1)   # force expiry
            self.assertEqual(c.get(url), b"body-v1")            # 304 path
            self.assertEqual(state["n"], 2)

    def test_concept_url_supports_dei_namespace(self):
        # Cover-page shares live under dei, not us-gaap — a client hardcoded
        # to us-gaap silently fails to find them.
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={})

        with tempfile.TemporaryDirectory() as d:
            c = self._client(handler, d)
            c.company_concept(320193, "EntityCommonStockSharesOutstanding",
                              namespace="dei")
            self.assertIn("/dei/EntityCommonStockSharesOutstanding.json",
                          captured["url"])


class FilingSelectionTests(unittest.TestCase):
    SUBMISSIONS = {
        "cik": 320193,
        "name": "Test Co",
        "filings": {"recent": {
            "accessionNumber": ["0000-24-Q2", "0000-24-Q2A", "0000-24-Q3", "0000-25-Q1"],
            "form":            ["10-Q", "10-Q/A", "10-Q", "10-Q"],
            "filingDate":      ["2024-08-01", "2024-09-15", "2024-11-01", "2025-05-01"],
            "reportDate":      ["2024-06-30", "2024-06-30", "2024-09-30", "2025-03-31"],
            "primaryDocument": ["q2.htm", "q2a.htm", "q3.htm", "q1.htm"],
        }},
    }

    def setUp(self):
        self.filings = parse_submissions(self.SUBMISSIONS)

    def test_parses_all_filings(self):
        self.assertEqual(len(self.filings), 4)
        self.assertEqual(self.filings[0].cik, 320193)

    def test_amendment_supersedes_original(self):
        chosen = select(self.filings)
        q2 = [f for f in chosen if f.period_end == date(2024, 6, 30)]
        self.assertEqual(len(q2), 1)                     # not both
        self.assertEqual(q2[0].accession_number, "0000-24-Q2A")

    def test_point_in_time_excludes_not_yet_filed(self):
        # On 2024-08-15 the Q2 amendment (filed 09-15) did not yet exist.
        chosen = latest(self.filings, as_of=date(2024, 8, 15))
        self.assertEqual(chosen.accession_number, "0000-24-Q2")

    def test_point_in_time_blocks_lookahead(self):
        # Q2 ended 06-30 but was not filed until 08-01: as of 07-15 nothing
        # about Q2 was knowable.
        chosen = latest(self.filings, as_of=date(2024, 7, 15))
        self.assertIsNone(chosen)

    def test_period_based_mode_allows_it(self):
        chosen = latest(self.filings, as_of=date(2024, 7, 15), point_in_time=False)
        self.assertEqual(chosen.period_end, date(2024, 6, 30))

    def test_latest_is_newest_period(self):
        self.assertEqual(latest(self.filings).period_end, date(2025, 3, 31))


if __name__ == "__main__":
    unittest.main()
