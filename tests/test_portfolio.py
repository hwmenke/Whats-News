import os
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import numpy as np
import pandas as pd

import app as app_module
import database as db
import portfolio


class PortfolioSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "p.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _seed(self, symbol="AAPL", n=80):
        db.add_symbol(symbol)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 100 + np.linspace(0, 10, n) + np.sin(np.linspace(0, 6, n)) * 2
        df = pd.DataFrame(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(n, 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", df)

    def _seed_breakout(self, symbol="EPCO", n=80):
        """Flat-then-gap-up-on-volume series to exercise near-high/EP fields."""
        db.add_symbol(symbol)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = np.full(n, 50.0)
        close[-1] = 55.0  # +10% gap day, new high
        volume = np.full(n, 1_000_000.0)
        volume[-1] = 3_000_000.0  # 3x average volume
        df = pd.DataFrame(
            {
                "open": np.concatenate([close[:-1] - 0.1, [52.5]]),  # ~5% gap open
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": volume,
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", df)

    def test_snapshot_ready(self):
        self._seed()
        snap = portfolio.snapshot_symbol("AAPL")
        self.assertTrue(snap["ready"])
        self.assertIn(snap["regime"], ("uptrend", "downtrend", "range"))
        self.assertIsNotNone(snap["rsi14"])
        self.assertIsNotNone(snap["stop_long_1_5atr"])

    def test_snapshot_breakout_fields(self):
        self._seed_breakout()
        snap = portfolio.snapshot_symbol("EPCO")
        self.assertTrue(snap["ready"])
        self.assertIn("dist_20d_high_pct", snap)
        self.assertIn("vol_ratio_5_20", snap)
        self.assertIn("gap_pct", snap)
        # Sitting at a fresh high, on volume, with a gap → all three flags true.
        self.assertTrue(snap["is_near_high"])
        self.assertTrue(snap["is_vol_surge"])
        self.assertTrue(snap["is_ep"])
        self.assertGreaterEqual(snap["breakout_score"], 3)

    def test_breakout_queue_and_news_focus_prefer_strong_names(self):
        self._seed_breakout("EPCO")  # near-high + vol surge + EP
        self._seed("WEAK", n=80)     # plain uptrend, not near-high/vol-surge
        data = portfolio.portfolio_snapshot()
        self.assertIn("breakout_queue", data)
        queue_syms = [r["symbol"] for r in data["breakout_queue"]]
        self.assertIn("EPCO", queue_syms)
        # News focus must be driven by breakout/strong names, never the
        # weakest-RS name alone (see METHODOLOGY_REVIEW.md must-not-do #3).
        self.assertIn("EPCO", data["news_focus"])
        if data.get("weakest_rs"):
            weakest_sym = data["weakest_rs"]["symbol"]
            strongest_sym = data["strongest_rs"]["symbol"] if data.get("strongest_rs") else None
            if weakest_sym != strongest_sym and weakest_sym not in queue_syms:
                self.assertNotEqual(data["news_focus"][0], weakest_sym)

    def test_portfolio_endpoint(self):
        self._seed("AAPL")
        self._seed("MSFT", n=90)
        res = self.client.get("/api/portfolio/snapshot")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["ready_count"], 2)
        self.assertEqual(len(data["tape"]), 2)
        ranks = {r["symbol"]: r["rs_rank_21d"] for r in data["symbols"] if r.get("ready")}
        self.assertEqual(sorted(ranks.values()), [1, 2])
        self.assertIn(data["symbols"][0].get("alert"), (None, "RSI_OB", "RSI_OS"))
        self.assertIn("alerts", data)
        self.assertIn("news_focus", data)
        self.assertIsInstance(data.get("group_rollup"), list)
        self.assertIn("heatmap", data)
        self.assertTrue(any(r.get("peer_etf") for r in data["symbols"] if r.get("ready")))
        ready_row = next(r for r in data["symbols"] if r.get("ready"))
        self.assertIn("size_risk_100", ready_row)
        self.assertIn("is_near_high", ready_row)
        self.assertIn("vol_ratio_5_20", ready_row)
        self.assertIn("breakout_queue", data)
        self.assertEqual(data.get("rs_basis"), "watchlist_21d")
        self.assertIn("not a published", (data.get("rs_note") or "").lower())

    def test_pm_desk_endpoint(self):
        self._seed("AAPL")
        res = self.client.get("/api/pm-desk/AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ready"])

    def test_pm_desk_missing(self):
        db.add_symbol("ZZZ")
        res = self.client.get("/api/pm-desk/ZZZ")
        self.assertEqual(res.status_code, 404)

    def test_position_size_prefers_user_stop(self):
        # ATR path: stop distance = 1.5 × 2.0 = 3.0 → floor(100/3) = 33 shares
        atr = portfolio.position_size(100, 2.0, 100, 1.5)
        # Tighter user stop (distance 2.0) → more shares than ATR fallback
        user = portfolio.position_size(100, 2.0, 100, 1.5, stop_price=98)
        self.assertEqual(atr["stop_source"], "atr")
        self.assertEqual(user["stop_source"], "user_stop")
        self.assertEqual(user["stop_distance"], 2.0)
        self.assertEqual(atr["stop_distance"], 3.0)
        self.assertGreater(user["shares"], atr["shares"])

    def test_darvas_box_and_endpoint(self):
        self._seed("BOXA", n=80)
        snap = portfolio.snapshot_symbol("BOXA")
        self.assertTrue(snap["ready"])
        self.assertIn("darvas", snap)
        # Synthetic sine wave may or may not form a box; API must still respond.
        res = self.client.get("/api/darvas-box/BOXA")
        self.assertIn(res.status_code, (200, 404))
        if res.status_code == 200:
            body = res.get_json()
            self.assertIn(body["state"], ("in_box", "breakout", "failed"))
            self.assertGreater(body["top"], body["bottom"])

    def test_pm_desk_user_stop_and_risk_box(self):
        self._seed("AAPL")
        res = self.client.get("/api/pm-desk/AAPL?risk=100&stop=user&stop_price=90&target=120")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["size"]["stop_source"], "user_stop")
        self.assertIn("risk_box", data)
        self.assertEqual(data["risk_box"]["stop_mode"], "user")
        self.assertEqual(data["risk_box"]["stop"], 90)
        self.assertEqual(data["risk_box"]["target"], 120)
        self.assertIsNotNone(data["risk_box"]["r_multiple"])


class LabelHonestyTests(unittest.TestCase):
    """Guardrail: never brand book ranks as a published RS Rating or invent EPS."""

    def test_frontend_has_no_ibd_or_fake_eps(self):
        roots = ["scripts/app.js", "scripts/charts.js", "index.html", "portfolio.py"]
        ibd = re.compile(r"ibd", re.IGNORECASE)
        eps = re.compile(r"EPS\s*Rating", re.IGNORECASE)
        for path in roots:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                ibd.search(text),
                msg=f"{path} must not contain the IBD substring",
            )
            self.assertIsNone(
                eps.search(text),
                msg=f"{path} must not contain fake EPS Rating branding",
            )
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        self.assertIn("Book RS", app_js)
        self.assertIn("not a published rating", app_js)
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("not a published rating", html)
        self.assertIn("watchlist 21D", html)


class FrontendContractTests(unittest.TestCase):
    def test_jump_palette_never_adds_on_enter(self):
        with open("scripts/desk_palette.js", encoding="utf-8") as fh:
            pal = fh.read()
        self.assertIn("Enter never mutates", pal)
        self.assertIn("Shift+Enter", pal)
        self.assertIn("function visibleSymbolCodes", pal)

    def test_news_surfaces_are_labeled(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("Watchlist news", html)
        self.assertIn("News · this ticker", html)
        self.assertIn("function syncNewsSurfaceLabels", js)
        self.assertIn("News for this ticker", html)

    def test_yahoo_throttle_banner_and_bulk_progress(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('id="yahoo-throttle-banner"', html)
        self.assertIn("function showYahooThrottleBanner", js)
        self.assertIn("yahoo_throttle", js)
        self.assertIn('id="bulk-progress-log"', html)
        self.assertIn("Downloading", js)
        self.assertIn("Focus (f)", html)

    def test_ohlc_legend_and_watchlist_filter(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("function paintOhlcLegend", charts)
        self.assertIn('id="chart-legend-daily"', html)
        self.assertIn('id="watchlist-filter"', html)
        self.assertIn("scripts/desk_palette.js", html)

    def test_aria_pressed_on_tape_focus_pane_pills(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        self.assertIn('aria-pressed="true"', html)
        self.assertIn('id="pill-focus"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn("setPressed", app_js)
        self.assertIn("aria-pressed", charts)
        for pill_id in ("pill-pane-rsi", "pill-pane-macd", "pill-pane-trend", "pill-focus"):
            self.assertIn(f'id="{pill_id}"', html)
            idx = html.index(f'id="{pill_id}"')
            snippet = html[idx : idx + 160]
            self.assertIn("aria-pressed", snippet, msg=f"{pill_id} missing aria-pressed")

    def test_bulk_modal_focus_trap(self):
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("function trapFocusIn", app_js)
        self.assertIn("onBulkModalKeydown", app_js)
        self.assertIn("setAppInert", app_js)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('aria-modal="true"', html)
        self.assertIn('aria-haspopup="dialog"', html)

    def test_empty_state_keyboard_hint_row(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        self.assertIn('id="kbd-hint-row"', html)
        self.assertIn("<kbd>?</kbd>", html)
        self.assertIn("<kbd>/</kbd>", html)
        self.assertIn("<kbd>j</kbd>", html)
        self.assertIn("function openKbdHelp", app_js)
        self.assertIn('id="kbd-help"', html)

    def test_chart_sticky_legend_reuse_and_packs(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        self.assertIn("keep the last hovered bar", charts)
        self.assertIn("function chartsAreLive", charts)
        self.assertIn("if (chartsAreLive()) return", charts)
        self.assertIn("function computeSma", charts)
        self.assertIn("minervini", charts)
        self.assertIn("stockbee", charts)
        self.assertIn("function applyPriceMarkers", charts)
        self.assertIn("VOL_CLIMAX_RATIO", charts)
        self.assertIn("NOW ${last.toFixed(1)}", charts)
        self.assertIn('data-chart-pack="minervini"', html)
        self.assertIn('data-chart-pack="stockbee"', html)
        self.assertIn("chart-daily-ep-badge", html)
        self.assertIn("_pendingChartPack", setup)
        self.assertNotRegex(charts, r"\bIBD\b")
        self.assertNotRegex(html, r"\bIBD\b")

    def test_desk_workspaces_and_scanner_enter(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            css = fh.read()
        with open("scripts/desk_palette.js", encoding="utf-8") as fh:
            pal = fh.read()
        self.assertIn('data-workspace="chart"', html)
        self.assertIn('data-workspace="scan"', html)
        self.assertIn('data-workspace="review"', html)
        self.assertIn("function setWorkspace", app_js)
        self.assertIn("function applyReviewDrawerLayout", app_js)
        self.assertIn("showScanSplit", app_js)
        self.assertIn("workspace === 'scan'", app_js)
        self.assertIn("function moveSetupScanSelection", setup)
        self.assertIn("function openSelectedSetupRow", setup)
        self.assertIn("Stay in Scan workspace", setup)
        self.assertNotIn("switchTab('charts')", setup)
        self.assertIn("body.workspace-scan #scanner-area", css)
        self.assertIn("body.workspace-review #book-drawer", css)
        self.assertIn("body.workspace-review #journal-drawer", css)
        self.assertIn("Workspace: Scan", pal)
        self.assertIn("<kbd>Enter</kbd>", html)
        self.assertNotRegex(app_js, r"\bIBD\b")
        self.assertNotRegex(setup, r"\bIBD\b")

    def test_desk_restores_last_symbol_and_workspace(self):
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        self.assertIn("whats-news-workspace", app_js)
        self.assertIn("whats-news-last-symbol", app_js)
        self.assertIn("LAST_SYMBOL_KEY", app_js)
        self.assertIn("WORKSPACE_KEY", app_js)
        self.assertIn("setWorkspace('scan', { skipChart: true })", app_js)
        self.assertNotRegex(app_js, r"\bIBD\b")

    def test_neighbor_chart_prefetch_for_jk(self):
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("scripts/desk_palette.js", encoding="utf-8") as fh:
            pal = fh.read()
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        self.assertIn("function visibleSymbolCodes", pal)
        self.assertIn("function neighborVisibleSymbols", app_js)
        self.assertIn("function scheduleNeighborPrefetch", app_js)
        self.assertIn("function abortChartPrefetch", app_js)
        self.assertIn("function fetchChartBundle", app_js)
        self.assertIn("visibleSymbolCodes()", app_js)
        self.assertIn("scheduleNeighborPrefetch(symbol)", app_js)
        self.assertIn("new AbortController", app_js)
        self.assertIn("ignore stale prefetch", app_js)
        self.assertIn("isYahooThrottle(lastFetchError)", app_js)
        self.assertIn("do not prefetch-spam the universe", app_js)
        self.assertIn("state.workspace === 'scan'", app_js)
        self.assertIn("${API}/ohlcv/${symbol}?freq=daily", app_js)
        self.assertIn("${API}/ohlcv/${symbol}?freq=weekly", app_js)
        self.assertIn("${API}/indicators/${symbol}?freq=daily", app_js)
        self.assertIn("${API}/indicators/${symbol}?freq=weekly", app_js)
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        self.assertIn("function moveSetupScanSelection", setup)
        self.assertIn("window.moveSetupScanSelection", setup)
        self.assertNotRegex(app_js, r"\bIBD\b")
        self.assertNotRegex(charts, r"\bIBD\b")
        self.assertNotRegex(html, r"\bIBD\b")
        self.assertNotRegex(port, r"\bIBD\b")
        self.assertIsNone(re.search(r"ibd", app_js, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", charts, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", html, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", port, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
