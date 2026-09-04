"""Warnings board — reuses ENGINE Pattern / VCP / RSI-C. No second estimator."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATA_SERVICE_MODE"] = "embedded"

import app as app_module
import data_client
import database as db
import equity_engine as ee

import numpy as np
import pandas as pd


def _frame(close, high=None, low=None, start="2023-01-02"):
    close = np.asarray(close, dtype=float)
    n = len(close)
    idx = pd.bdate_range(start, periods=n)
    hi = close + 0.40 if high is None else np.asarray(high, dtype=float)
    lo = close - 0.40 if low is None else np.asarray(low, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": hi,
            "low": lo,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _uptrend(n=90, start=80.0, end=150.0):
    return np.linspace(start, end, n)


def _crash(n=80, start=150.0, end=40.0):
    return np.linspace(start, end, n)


class WarningsBoardTests(unittest.TestCase):
    def test_empty_is_honest(self):
        out = ee.warnings_board(symbols=[])
        self.assertFalse(out["ready"])
        self.assertIn("Empty", out.get("message") or "")
        self.assertEqual(out["takeaways"], [])
        self.assertEqual(out["vcp"]["tightening"], [])
        self.assertEqual(out["source"], "equity_engine.measure")
        self.assertIn("Not a second estimator", out["note"])

    def test_reuses_pattern_vcp_fields(self):
        frames = {
            "UP": _frame(_uptrend(90)),
            "DN": _frame(_crash(90)),
        }
        out = ee.warnings_board(symbols=["UP", "DN"], frames=frames)
        self.assertTrue(out["ready"])
        daily = out["breakouts"]["daily"]
        self.assertTrue(daily["Breakout"] or daily["Breakdown"] or daily["From Bottom"] or daily["From Top"])
        takeaway_kinds = {r.get("kind") for r in out["takeaways"]}
        self.assertTrue(takeaway_kinds <= {"breaking_up", "breaking_down", "coiled_about_to_move"})
        blob = str(out)
        self.assertNotIn("bloomberg", blob.lower())
        self.assertNotIn("10.95b", blob.lower())
        self.assertNotIn("gamma", blob.lower())

    def test_takeaway_labels_from_existing_fields(self):
        frames = {"UP": _frame(_uptrend(90))}
        out = ee.warnings_board(symbols=["UP"], frames=frames)
        for row in out["takeaways"]:
            self.assertIn(row.get("label"), ("breaking up", "breaking down", "coiled about to move"))
            self.assertIn(row.get("kind"), ("breaking_up", "breaking_down", "coiled_about_to_move"))


class WarningsApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "warn.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_empty_api(self):
        body = self.client.get("/api/engine/warnings?desk=1").get_json()
        self.assertFalse(body["ready"])
        self.assertIn("Empty", body.get("message") or "")
        self.assertEqual(body.get("takeaways"), [])

    def test_api_with_stored_bars(self):
        db.add_symbol("UP")
        db.upsert_ohlcv("UP", "daily", _frame(_uptrend(90)))
        body = self.client.get("/api/engine/warnings?desk=0").get_json()
        self.assertIn("breakouts", body)
        self.assertIn("vcp", body)
        self.assertIn("rsi_c", body)
        self.assertIn("stretch", body)
        self.assertIn("takeaways", body)


class WarningsSurfaceTests(unittest.TestCase):
    def test_web_and_iphone_wired(self):
        blob = ""
        for path in (
            "index.html",
            "scripts/warnings_desk.js",
            "scripts/app.js",
            "scripts/engine_desk.js",
            "mobile/lib/ui/scans_page.dart",
            "mobile/lib/data/api_client.dart",
            "mobile/lib/data/app_state.dart",
            "mobile/lib/ui/book_page.dart",
        ):
            blob += Path(path).read_text(encoding="utf-8")
        self.assertIn('id="warnings-area"', blob)
        self.assertIn('id="tab-warnings"', blob)
        self.assertIn("/api/engine/warnings", blob)
        self.assertIn("getEngineWarnings", blob)
        self.assertIn("_warningsSlivers", blob)
        self.assertIn("Yahoo/SQLite scans · ENGINE + Market Moves", blob)
        self.assertIn("overflow-x: auto", Path("styles/theme.css").read_text(encoding="utf-8"))
        self.assertNotIn(
            "Column order/visibility: GET /api/boards/registry",
            blob,
        )
        self.assertIn("whats-news-risk-SPEC-2026-09-04.md", blob)
        self.assertIn("risk-clusters", blob)
        self.assertIn("Empty buckets omitted", blob)
        self.assertIn("Takeaways", blob)
        self.assertIn("if (rows.isEmpty) return const SizedBox.shrink();", blob)
        scans = Path("mobile/lib/ui/scans_page.dart").read_text(encoding="utf-8")
        self.assertIn("ClipRect(", scans)
        self.assertIn("FittedBox(", scans)
        self.assertIn("BoxFit.scaleDown", scans)
        self.assertIn("LayoutBuilder(", scans)
        self.assertIn("TextOverflow.clip", scans)
        self.assertIn("class ScanNameRow", scans)
        self.assertNotIn("TextOverflow.ellipsis", scans)
        self.assertNotIn("Flexible(", scans)
        self.assertIn("r.label.isNotEmpty ? r.label : r.patternD", scans)
        self.assertIn("_macroSlivers", scans)
        self.assertIn("('macro', 'Macro')", scans)
        self.assertIn("_engTakeawayStrip", Path("scripts/engine_desk.js").read_text(encoding="utf-8"))
        cmd = scans[scans.find("_commandSlivers"):scans.find("_setupEngineSlivers")]
        self.assertTrue(cmd)
        self.assertNotIn("'none'", cmd)
        self.assertNotIn('"none"', cmd)
        self.assertIn("storedN", Path("mobile/lib/data/models.dart").read_text(encoding="utf-8"))
        self.assertIn("seedFetchDesk", Path("mobile/lib/data/app_state.dart").read_text(encoding="utf-8"))
        self.assertIn("reloadMapsAfterSeed", Path("mobile/lib/data/app_state.dart").read_text(encoding="utf-8"))
        self.assertIn("'period': '2y'", Path("mobile/lib/data/api_client.dart").read_text(encoding="utf-8"))
        self.assertIn("Maps not loaded — refresh", Path("mobile/lib/ui/scans_page.dart").read_text(encoding="utf-8"))
        self.assertIn("bookPane == 'upload'", Path("mobile/lib/data/app_state.dart").read_text(encoding="utf-8"))
        self.assertNotIn("bloomberg", blob.lower())
        self.assertNotIn("gamma strip", blob.lower())

    def test_screenshots_on_disk(self):
        root = Path("docs/screenshots")
        for name in (
            "warnings/warnings_board.png",
            "warnings/risk_scaffold.png",
            "warnings/risk_live.png",
            "warnings/risk_hero.png",
            "warnings/risk_ranked_clusters.png",
            "density/scans_dense.png",
        ):
            path = root / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 10_000, name)


if __name__ == "__main__":
    unittest.main()
