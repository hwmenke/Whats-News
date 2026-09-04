"""Alpaca paper read-only sync — no orders, no live URL, no invented P&L."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATA_SERVICE_MODE"] = "embedded"

import alpaca_paper as ap
import data_client
import database as db
import paper_book as pb
import app as app_module

FIXTURE = Path(__file__).parent / "fixtures" / "alpaca"


def _load(name: str):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


class AlpacaGateTests(unittest.TestCase):
    def test_orders_and_writes_denied(self):
        with self.assertRaises(ap.AlpacaDenied):
            ap.assert_read_only("POST", "/v2/orders")
        with self.assertRaises(ap.AlpacaDenied):
            ap.assert_read_only("DELETE", "/v2/orders/abc")
        with self.assertRaises(ap.AlpacaDenied):
            ap.assert_read_only("DELETE", "/v2/positions/AAPL")
        with self.assertRaises(ap.AlpacaDenied):
            ap.assert_read_only("POST", "/v2/positions/AAPL")
        with self.assertRaises(ap.AlpacaDenied):
            ap.assert_read_only("GET", "/v2/orders")
        with self.assertRaises(ap.AlpacaDenied):
            ap.assert_read_only("GET", "/v2/positions/AAPL/close")
        ap.assert_read_only("GET", "/v2/account")
        ap.assert_read_only("GET", "/v2/positions")
        ap.assert_read_only("GET", "/v2/account/portfolio/history")
        ap.assert_read_only("GET", "/v2/account/activities")
        self.assertFalse(hasattr(ap, "submit_order"))
        self.assertFalse(hasattr(ap, "close_position"))
        self.assertFalse(hasattr(ap, "cancel_order"))

    def test_live_url_refused(self):
        with patch.dict(os.environ, {"APCA_API_BASE_URL": "https://api.alpaca.markets"}, clear=False):
            with self.assertRaises(ap.AlpacaDenied) as ctx:
                ap.resolve_base_url()
            self.assertIn("refused", str(ctx.exception).lower())
        self.assertEqual(ap.resolve_base_url("https://paper-api.alpaca.markets"), "https://paper-api.alpaca.markets")


class AlpacaApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "alpaca.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()
        self._env = patch.dict(os.environ, {
            "APCA_API_KEY_ID": "",
            "APCA_API_SECRET_KEY": "",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
        }, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_status_and_sync_empty_without_keys(self):
        st = self.client.get("/api/alpaca/status").get_json()
        self.assertTrue(st["paper"])
        self.assertFalse(st["configured"])
        self.assertNotIn("AK", json.dumps(st))
        self.assertIsInstance(st.get("has_secret"), bool)
        self.assertFalse(st.get("has_secret"))
        self.assertIn("not live", st["note"].lower())
        sync = self.client.post("/api/alpaca/sync").get_json()
        self.assertFalse(sync["ok"])
        self.assertEqual(sync["positions"], [])
        self.assertEqual(sync["imported"], 0)
        self.assertIn("missing", sync["reason"].lower())

    def test_sync_maps_fixture_and_never_hits_orders(self):
        calls = []
        acct = json.dumps(_load("account.json"))
        poss = json.dumps(_load("positions.json"))

        def fake_get(url, headers):
            calls.append(url)
            self.assertNotIn("orders", url.lower())
            self.assertNotIn("close", url.lower())
            self.assertTrue(url.startswith("https://paper-api.alpaca.markets"))
            if url.endswith("/v2/account"):
                return 200, acct
            if url.endswith("/v2/positions"):
                return 200, poss
            self.fail(f"unexpected URL {url}")

        with patch.dict(os.environ, {
            "APCA_API_KEY_ID": "PKTEST",
            "APCA_API_SECRET_KEY": "secret-test-not-real",
        }, clear=False):
            with patch.object(ap, "_http_get", side_effect=fake_get):
                body = ap.sync(fetch=ap._http_get)
        self.assertTrue(body["ok"])
        self.assertTrue(body["paper"])
        self.assertEqual(body["source"], "alpaca_paper")
        self.assertEqual(body["imported"], 2)
        self.assertEqual({p["symbol"] for p in body["positions"]}, {"AAPL", "MSFT"})
        self.assertTrue(all(p["source"] == "alpaca_paper" for p in body["positions"]))
        self.assertEqual(body["account"]["account_tail"], "5678")
        self.assertNotIn("PKTEST", json.dumps(body))
        self.assertNotIn("secret-test-not-real", json.dumps(body))
        self.assertTrue(all("/v2/orders" not in u for u in calls))
        listed = {p["symbol"]: p for p in pb.list_positions()}
        self.assertEqual(listed["AAPL"]["source"], "alpaca_paper")
        self.assertEqual(listed["MSFT"]["side"], "short")

    def test_live_env_sync_is_empty(self):
        with patch.dict(os.environ, {
            "APCA_API_KEY_ID": "PKTEST",
            "APCA_API_SECRET_KEY": "secret-test-not-real",
            "APCA_API_BASE_URL": "https://api.alpaca.markets",
        }, clear=False):
            body = self.client.post("/api/alpaca/sync").get_json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["positions"], [])
        self.assertIn("refused", body["reason"].lower())

    def test_fidelity_and_alpaca_stay_tagged(self):
        pb.import_csv(
            "Symbol,Quantity,Cost Basis Average\nAAPL,2,100\n",
            replace=False,
        )
        pb.upsert_position(symbol="QQQ", qty=1, source="alpaca_paper")
        pb.import_csv(
            "Symbol,Quantity,Cost Basis Average\nMSFT,3,200\n",
            replace=True,
        )
        rows = {p["symbol"]: p["source"] for p in pb.list_positions()}
        self.assertEqual(rows.get("QQQ"), "alpaca_paper")
        self.assertEqual(rows.get("MSFT"), "fidelity_csv")
        self.assertNotIn("AAPL", rows)

    def test_unmarked_source_omitted_from_pnl(self):
        pb.upsert_position(symbol="IBM", qty=4, source="mystery_broker")
        pnl = pb.book_pnl()
        self.assertFalse(pnl["ready"])
        self.assertIsNone(pnl["today_pnl"])
        self.assertEqual(pnl["unmarked_count"], 1)
        self.assertIn("Unmarked", pnl["message"])

    def test_surfaces_say_not_live(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/paper_book.js", encoding="utf-8") as fh:
            js = fh.read()
        with open("mobile/lib/ui/book_page.dart", encoding="utf-8") as fh:
            dart = fh.read()
        blob = html + js + dart
        self.assertIn("Alpaca paper — not live P&L", dart)
        self.assertIn("Alpaca paper — not live P&amp;L", html)
        self.assertIn("/api/alpaca/sync", js)
        self.assertNotIn("api.alpaca.markets", js)
        self.assertNotIn("submit_order", blob)


if __name__ == "__main__":
    unittest.main()
