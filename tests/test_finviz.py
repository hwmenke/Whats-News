"""Finviz public HTML parse + honest empty APIs. No invented tickers."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import finviz_client as fv
import finviz_presets as presets
import app as app_module

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "finviz"


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class FinvizParseTests(unittest.TestCase):
    def test_quote_fixture_has_real_fields(self):
        parsed = fv.parse_quote_html(_read("quote_aapl.html"), "AAPL")
        self.assertTrue(parsed["ready"])
        self.assertEqual(parsed["symbol"], "AAPL")
        self.assertTrue(parsed["sector"])
        self.assertTrue(parsed["industry"])
        snap = parsed["snapshot"]
        self.assertTrue(snap.get("market_cap"))
        self.assertTrue(snap.get("pe"))
        self.assertTrue(snap.get("eps_ttm"))
        self.assertTrue(snap.get("rsi_14"))
        self.assertTrue(snap.get("perf_week"))
        self.assertTrue(snap.get("short_float"))
        self.assertTrue(parsed["news"])
        self.assertTrue(parsed["news"][0]["title"])
        self.assertNotIn("NVDA", parsed["symbol"])

    def test_screener_fixture_rows(self):
        rows = fv.parse_screener_html(_read("screener_v111.html"))
        symbols = [r["symbol"] for r in rows]
        self.assertEqual(symbols, ["NVDA", "AAPL", "MSFT"])
        aapl = next(r for r in rows if r["symbol"] == "AAPL")
        self.assertEqual(aapl["company"], "Apple Inc")
        self.assertEqual(aapl["sector"], "Technology")

    def test_bad_html_is_empty(self):
        quote = fv.parse_quote_html(_read("bad.html"), "AAPL")
        self.assertFalse(quote["ready"])
        self.assertEqual(quote["fields"], {})
        self.assertEqual(quote["news"], [])
        self.assertTrue(quote["reason"])
        self.assertEqual(fv.parse_screener_html(_read("bad.html")), [])
        self.assertEqual(fv.parse_screener_html("<html>no table</html>"), [])
        self.assertEqual(fv.parse_snapshot_pairs(""), {})

    def test_presets_document_finviz_codes(self):
        qulla = presets.get_preset("qulla_momentum")
        self.assertIn("sh_price_o10", qulla["filters"])
        self.assertIn("sh_relvol_o1.5", qulla["filters"])
        self.assertIn("ta_highlow52w_b0to5h", qulla["filters"])
        self.assertIn("fa_epsyoy_o25", qulla["filters"])
        self.assertTrue(presets.screener_url(qulla["filters"]).startswith("https://finviz.com/screener.ashx"))
        self.assertIsNone(presets.get_preset("not_a_real_preset"))


class FinvizApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "finviz.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_disabled_and_unknown_preset_are_empty_200(self):
        put = self.client.put("/api/finviz/settings", json={"enabled": False, "ttl_sec": 120})
        self.assertEqual(put.status_code, 200)
        self.assertFalse(put.get_json()["enabled"])
        res = self.client.get("/api/finviz/screener?preset=qulla_momentum")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["rows"], [])
        self.assertIn("disabled", body["reason"].lower())
        unknown = self.client.get("/api/finviz/screener?preset=nope")
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.get_json()["rows"], [])

    def test_screener_uses_injected_html_not_invented(self):
        self.client.put("/api/finviz/settings", json={"enabled": True})
        html = _read("screener_v111.html")

        def fake_fetch(url):
            self.assertIn("screener.ashx", url)
            self.assertIn("sh_price_o10", url)
            return 200, html

        with patch.object(fv, "_http_get", side_effect=fake_fetch):
            body = self.client.get("/api/finviz/screener?preset=qulla_momentum&force=1").get_json()
        self.assertEqual(body["count"], 3)
        self.assertEqual([r["symbol"] for r in body["rows"]], ["NVDA", "AAPL", "MSFT"])

    def test_blocked_screener_is_empty_200(self):
        self.client.put("/api/finviz/settings", json={"enabled": True})

        def blocked(url):
            return 403, "Forbidden"

        with patch.object(fv, "_http_get", side_effect=blocked):
            body = self.client.get("/api/finviz/screener?preset=near_high&force=1").get_json()
        self.assertEqual(body["rows"], [])
        self.assertIn("403", body["reason"])
        self.assertFalse(body["ready"])

    def test_quote_api_from_fixture(self):
        html = _read("quote_aapl.html")
        with patch.object(fv, "_http_get", return_value=(200, html)):
            body = self.client.get("/api/finviz/quote/AAPL?force=1").get_json()
        self.assertTrue(body["ready"])
        self.assertEqual(body["symbol"], "AAPL")
        self.assertTrue(body["snapshot"].get("pe"))

    def test_presets_endpoint(self):
        body = self.client.get("/api/finviz/presets").get_json()
        ids = {p["id"] for p in body["presets"]}
        self.assertIn("qulla_momentum", ids)
        self.assertIn("sh_price_o10", body["filter_docs"])


if __name__ == "__main__":
    unittest.main()
