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
        roots = [
            "scripts/app.js",
            "scripts/charts.js",
            "index.html",
            "portfolio.py",
            "scripts/price_alerts.js",
        ]
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

    def test_weekly_trend_ma_pack(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-chart-pack="weinstein"', html)
        self.assertIn("weekly trend MAs", html)
        self.assertIn("not a rating", html)
        self.assertIn("weinstein", charts)
        self.assertIn("SMA_WEEKLY_ONLY", charts)
        self.assertIn("sma: [10, 40]", charts)
        self.assertIn("function smaShown", charts)
        self.assertIn("freq !== 'weekly'", charts)
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

    def test_daily_six_month_fit_and_session_levels(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        self.assertIn("const DAILY_DEFAULT_BARS = 126", charts)
        self.assertIn("WEEKLY_DEFAULT_BARS", charts)
        self.assertIn("function fitAllContent", charts)
        self.assertIn("function applySessionLevels", charts)
        self.assertIn("function setupFitAllOnDoubleClick", charts)
        self.assertIn("dblclick", charts)
        self.assertIn("Double-click to fit all data", charts)
        self.assertIn("'PDH'", charts)
        self.assertIn("'PDL'", charts)
        self.assertIn("'PDC'", charts)
        self.assertIn("'52H'", charts)
        self.assertIn("'52L'", charts)
        self.assertIn("prior day high/low/close", charts)
        self.assertIn("applySessionLevels()", charts)
        self.assertIn("_fitPaneToBars(charts.daily.main, dailyN, DAILY_DEFAULT_BARS)", charts)
        self.assertIn("LineStyle.Dashed", charts)
        self.assertIn("FIFTY_TWO_WEEK_BARS", charts)
        self.assertNotRegex(charts, r"\bIBD\b")
        self.assertIsNone(re.search(r"ibd", charts, re.IGNORECASE))

    def test_linked_ohlc_twin_readout_contract(self):
        with open("scripts/linked_ohlc.js", encoding="utf-8") as fh:
            linked = fh.read()
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        self.assertIn("function linkedBarFor", linked)
        self.assertIn("function paintLinkedTwin", linked)
        self.assertIn("function paintLinkedTwinIfLive", linked)
        self.assertIn("W-FRI", linked)
        self.assertIn("first weekly bar with date >= daily", linked)
        self.assertIn("last daily bar with date <= weekly", linked)
        self.assertIn("paintLinkedTwinIfLive", charts)
        self.assertIn("keep the last hovered bar", charts)
        self.assertIn('id="chart-legend-daily-twin"', html)
        self.assertIn('id="chart-legend-weekly-twin"', html)
        self.assertIn("scripts/linked_ohlc.js", html)
        self.assertIn("def linked_ohlc_bar", port)
        for blob in (linked, charts, html, port):
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))

    def test_linked_ohlc_bar_wfri_mapping(self):
        daily = [
            {"date": "2024-01-08", "open": 10, "high": 11, "low": 9, "close": 10.5},
            {"date": "2024-01-09", "open": 10.5, "high": 12, "low": 10, "close": 11},
            {"date": "2024-01-12", "open": 11, "high": 13, "low": 10.5, "close": 12},
            {"date": "2024-01-16", "open": 12, "high": 12.5, "low": 11, "close": 11.5},
        ]
        weekly = [
            {"date": "2024-01-12", "open": 10, "high": 13, "low": 9, "close": 12},
            {"date": "2024-01-19", "open": 12, "high": 12.5, "low": 11, "close": 11.5},
        ]
        mon = portfolio.linked_ohlc_bar("daily", "2024-01-08", daily, weekly)
        self.assertEqual(mon["date"], "2024-01-12")
        self.assertEqual(mon["high"], 13)
        fri = portfolio.linked_ohlc_bar("weekly", "2024-01-12", daily, weekly)
        self.assertEqual(fri["date"], "2024-01-12")
        self.assertEqual(fri["close"], 12)
        next_w = portfolio.linked_ohlc_bar("weekly", "2024-01-19", daily, weekly)
        self.assertEqual(next_w["date"], "2024-01-16")
        self.assertIsNone(portfolio.linked_ohlc_bar("daily", "", daily, weekly))
        self.assertIsNone(portfolio.linked_ohlc_bar("daily", "2024-01-08", daily, []))

    def test_setup_scan_cache_reuse_within_ttl(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        self.assertIn("SETUP_SCAN_CACHE_TTL_MS = 60 * 1000", setup)
        self.assertIn("SETUP_SCAN_CACHE_KEY", setup)
        self.assertIn("whats-news-setup-scan", setup)
        self.assertIn("function setupScanCacheKey", setup)
        self.assertIn("function readSetupScanCache", setup)
        self.assertIn("function writeSetupScanCache", setup)
        self.assertIn("sessionStorage.getItem(SETUP_SCAN_CACHE_KEY)", setup)
        self.assertIn("sessionStorage.setItem(SETUP_SCAN_CACHE_KEY", setup)
        self.assertIn("async function loadSetupScan(opts)", setup)
        self.assertIn("opts.force === true", setup)
        self.assertIn("opts.allowStaleRows", setup)
        self.assertIn("readSetupScanCache(key)", setup)
        self.assertIn("writeSetupScanCache(key, data)", setup)
        self.assertIn("${API}/setups/scan?limit=300", setup)
        self.assertIn("loadSetupScan({ allowStaleRows: true })", app_js)
        self.assertIn('onclick="loadSetupScan({force:true})"', html)
        self.assertIn("function moveSetupScanSelection", setup)
        self.assertIn("function openSelectedSetupRow", setup)
        self.assertIn("Stay in Scan workspace", setup)
        self.assertNotIn("switchTab('charts')", setup)
        self.assertNotRegex(setup, r"\bIBD\b")
        self.assertNotRegex(app_js, r"\bIBD\b")
        self.assertNotRegex(html, r"\bIBD\b")
        self.assertNotRegex(port, r"\bIBD\b")
        self.assertIsNone(re.search(r"ibd", setup, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", app_js, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", html, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", port, re.IGNORECASE))

    def test_click_bar_opens_journal_for_date(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        self.assertIn("function setupBarClickJournal", charts)
        self.assertIn("subscribeClick", charts)
        self.assertIn("setupBarClickJournal()", charts)
        self.assertIn("onChartBarClick", charts)
        self.assertIn("week-ending date", charts)
        self.assertIn("function onChartBarClick", app_js)
        self.assertIn("function openJournalForDate", app_js)
        self.assertIn("function saveJournalNote", app_js)
        self.assertIn("journal-date", app_js)
        self.assertIn("journal-note", app_js)
        self.assertIn("week-ending", app_js)
        self.assertIn('id="journal-date"', html)
        self.assertIn('id="journal-note"', html)
        self.assertIn('id="journal-compose"', html)
        self.assertIn("keep the last hovered bar", charts)
        self.assertIn("function chartsAreLive", charts)
        self.assertIn("function neighborVisibleSymbols", app_js)
        self.assertIn("function setWorkspace", app_js)
        for blob in (charts, app_js, html, port):
            self.assertNotRegex(blob, r"\bIBD\b")
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))

    def test_price_first_bb_off_hollow_up_volume_last(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        self.assertIn("bb: false", charts)
        self.assertIn("upColor: '#0d1117'", charts)
        self.assertIn("lastValueVisible: true", charts)
        idx = html.index('id="pill-bb"')
        snippet = html[idx : idx + 180]
        self.assertIn("aria-pressed", snippet)
        self.assertNotIn("active-bb", snippet)
        self.assertIn("classList.toggle('active-bb', on)", app_js)
        self.assertNotRegex(charts, r"\bIBD\b")
        self.assertNotRegex(html, r"\bIBD\b")

    def test_spy_rs_overlay_contract(self):
        with open("scripts/spy_rs.js", encoding="utf-8") as fh:
            spy_js = fh.read()
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        self.assertIn("function applySpyRsIfOn", spy_js)
        self.assertIn("function toggleSpyRs", spy_js)
        self.assertIn("let spyRsOn = false", spy_js)
        self.assertIn("not a published rating", spy_js)
        self.assertIn("${_spyRsApi()}/spy-rs/", spy_js)
        self.assertIn("applySpyRsIfOn()", charts)
        self.assertIn("scripts/spy_rs.js", html)
        self.assertIn('id="pill-spy-rs"', html)
        idx = html.index('id="pill-spy-rs"')
        snippet = html[idx : idx + 280]
        self.assertIn("aria-pressed", snippet)
        self.assertIn("not a published rating", snippet)
        self.assertNotIn("active-spy-rs", snippet)
        self.assertIn("def spy_rs_overlay", port)
        self.assertIn("SPY_RS_NOTE", port)
        self.assertIn("close_ratio", port)
        self.assertIn("not a published rating", port)
        for blob in (spy_js, charts, html, app_js, port):
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))

    def test_ohlc_legend_adr_sma200_contract(self):
        with open("scripts/legend_stats.js", encoding="utf-8") as fh:
            stats = fh.read()
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("scripts/linked_ohlc.js", encoding="utf-8") as fh:
            linked = fh.read()
        with open("scripts/spy_rs.js", encoding="utf-8") as fh:
            spy_js = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            css = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        self.assertIn("function legendStatHtmlBits", stats)
        self.assertIn("function computeAdrPct", stats)
        self.assertIn("function distToSma200Pct", stats)
        self.assertIn("function formatAdrLegend", stats)
        self.assertIn("function formatSma200DistLegend", stats)
        self.assertIn("const ADR_LOOKBACK = 20", stats)
        self.assertIn("const ADR_MIN_BARS = 5", stats)
        self.assertIn("lg-stat", stats)
        self.assertIn("not the hovered window", stats)
        self.assertIn("ADR stays daily", stats)
        self.assertIn("legendStatHtmlBits(freq, idx)", charts)
        self.assertIn("keep the last hovered bar", charts)
        self.assertIn("legend-held", charts)
        self.assertIn("paintLinkedTwinIfLive", charts)
        self.assertIn("function setupBarClickJournal", charts)
        self.assertIn("function paintLinkedTwin", linked)
        self.assertIn("scripts/legend_stats.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/legend_stats.js"))
        self.assertIn("scripts/spy_rs.js", html)
        self.assertIn(".chart-ohlc-legend .lg-stat", css)
        self.assertIn("def legend_adr_pct", port)
        self.assertIn("def legend_sma200_dist_pct", port)
        self.assertIn("def format_legend_adr", port)
        self.assertIn("def format_legend_sma200_dist", port)
        self.assertIn("def legend_stat_text_bits", port)
        self.assertNotIn("activeSma", stats)
        self.assertNotIn("smaShown", stats)
        self.assertNotIn("share float", stats.lower())
        self.assertNotIn("share_float", stats)
        for blob in (stats, charts, html, app_js, port, spy_js, setup):
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))


class LegendStatsMathTests(unittest.TestCase):
    """ADR% and dist-to-SMA200 — same formula as scripts/legend_stats.js."""

    def test_adr_mean_last_20_valid_daily_bars(self):
        bar = {"high": 102.41, "low": 100.0, "close": 100.0}
        rows = [bar] * 20
        adr = portfolio.legend_adr_pct(rows)
        self.assertAlmostEqual(adr, 2.41)
        self.assertEqual(portfolio.format_legend_adr(adr), "ADR 2.41%")

    def test_adr_skips_invalid_and_ignores_bars_beyond_20(self):
        old = {"high": 200.0, "low": 100.0, "close": 100.0}  # 100% range
        recent = {"high": 102.41, "low": 100.0, "close": 100.0}
        bad = {"high": 0, "low": 0, "close": 100.0}
        rows = [old] + [recent] * 19 + [bad] + [recent]
        adr = portfolio.legend_adr_pct(rows)
        self.assertAlmostEqual(adr, 2.41)

    def test_adr_omits_when_fewer_than_five_valid_bars(self):
        bar = {"high": 102.0, "low": 100.0, "close": 100.0}
        self.assertIsNone(portfolio.legend_adr_pct([bar] * 4))
        self.assertEqual(portfolio.format_legend_adr(None), "")
        five = portfolio.legend_adr_pct([bar] * 5)
        self.assertAlmostEqual(five, 2.0)

    def test_sma200_distance_format(self):
        up = portfolio.legend_sma200_dist_pct(108.1, 100.0)
        down = portfolio.legend_sma200_dist_pct(96.8, 100.0)
        self.assertAlmostEqual(up, 8.1)
        self.assertAlmostEqual(down, -3.2)
        self.assertEqual(portfolio.format_legend_sma200_dist(up), "200 +8.1%")
        self.assertEqual(portfolio.format_legend_sma200_dist(down), "200 \u22123.2%")
        self.assertIsNone(portfolio.legend_sma200_dist_pct(108.1, None))
        self.assertIsNone(portfolio.legend_sma200_dist_pct(10, 0))
        self.assertEqual(portfolio.format_legend_sma200_dist(None), "")

    def test_legend_bits_adr_daily_only(self):
        daily = [{"high": 102.41, "low": 100.0, "close": 100.0}] * 20
        daily_bits = portfolio.legend_stat_text_bits(
            "daily", close=108.1, sma200=100.0, daily_rows=daily
        )
        weekly_bits = portfolio.legend_stat_text_bits(
            "weekly", close=96.8, sma200=100.0, daily_rows=daily
        )
        self.assertEqual(daily_bits, ["ADR 2.41%", "200 +8.1%"])
        self.assertEqual(weekly_bits, ["200 \u22123.2%"])
        self.assertEqual(
            " ".join(daily_bits),
            "ADR 2.41% 200 +8.1%",
        )
        omitted = portfolio.legend_stat_text_bits(
            "weekly", close=100.0, sma200=None, daily_rows=daily
        )
        self.assertEqual(omitted, [])


class SpyRsOverlayTests(unittest.TestCase):
    """close/SPY close comparison — not a published rating."""

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

    def test_overlay_is_close_ratio_rebased_to_last_print(self):
        symbol = [
            {"date": "2024-01-02", "close": 100},
            {"date": "2024-01-03", "close": 110},
        ]
        spy = [
            {"date": "2024-01-02", "close": 50},
            {"date": "2024-01-03", "close": 50},
        ]
        out = portfolio.spy_rs_overlay(symbol, spy)
        self.assertTrue(out["ready"])
        self.assertEqual(out["benchmark"], "SPY")
        self.assertEqual(out["basis"], "close_ratio")
        self.assertIn("not a published", out["note"].lower())
        self.assertEqual(out["last_ratio"], 2.2)
        self.assertAlmostEqual(out["points"][0]["value"], 100.0)
        self.assertAlmostEqual(out["points"][-1]["value"], 110.0)
        self.assertAlmostEqual(out["points"][0]["ratio"], 2.0)

    def test_overlay_skips_unaligned_and_missing_spy(self):
        empty = portfolio.spy_rs_overlay([], [])
        self.assertFalse(empty["ready"])
        self.assertEqual(empty["points"], [])
        missing = portfolio.spy_rs_overlay(
            [{"date": "2024-01-02", "close": 10}],
            [],
        )
        self.assertFalse(missing["ready"])
        skipped = portfolio.spy_rs_overlay(
            [{"date": "2024-01-02", "close": 10}, {"date": "2024-01-03", "close": 12}],
            [{"date": "2024-01-03", "close": 4}],
        )
        self.assertTrue(skipped["ready"])
        self.assertEqual(skipped["n"], 1)
        self.assertEqual(skipped["points"][0]["date"], "2024-01-03")

    def test_underperform_overlay_starts_above_last_close(self):
        # Stock +10%, SPY +20% → relative line declines into the last print.
        symbol = [
            {"date": "2024-01-02", "close": 100},
            {"date": "2024-01-03", "close": 110},
        ]
        spy = [
            {"date": "2024-01-02", "close": 100},
            {"date": "2024-01-03", "close": 120},
        ]
        out = portfolio.spy_rs_overlay(symbol, spy)
        self.assertAlmostEqual(out["points"][-1]["value"], 110.0)
        self.assertGreater(out["points"][0]["value"], out["points"][-1]["value"])

    def test_spy_rs_endpoint_ready_when_spy_seeded(self):
        idx = pd.date_range("2024-01-01", periods=40, freq="D")
        aapl = 100 + np.linspace(0, 8, 40)
        spy = 50 + np.linspace(0, 2, 40)
        for sym, close in (("AAPL", aapl), ("SPY", spy)):
            db.add_symbol(sym)
            df = pd.DataFrame(
                {
                    "open": close - 0.4,
                    "high": close + 0.8,
                    "low": close - 0.8,
                    "close": close,
                    "volume": np.full(40, 1_000_000.0),
                },
                index=idx,
            )
            db.upsert_ohlcv(sym, "daily", df)
        res = self.client.get("/api/spy-rs/AAPL")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ready"])
        self.assertEqual(data["symbol"], "AAPL")
        self.assertEqual(data["benchmark"], "SPY")
        self.assertGreater(data["n"], 10)
        self.assertIn("not a published", (data.get("note") or "").lower())
        self.assertAlmostEqual(data["points"][-1]["value"], float(aapl[-1]), places=2)

    def test_spy_rs_endpoint_ready_false_without_spy(self):
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        close = 100 + np.linspace(0, 3, 30)
        db.add_symbol("AAPL")
        df = pd.DataFrame(
            {
                "open": close - 0.4,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": np.full(30, 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv("AAPL", "daily", df)
        res = self.client.get("/api/spy-rs/AAPL")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["ready"])
        self.assertIn("SPY", data.get("error") or "")

    def test_spy_rs_endpoint_rejects_spy_vs_spy(self):
        res = self.client.get("/api/spy-rs/SPY")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["ready"])
        self.assertIn("not a comparison", (data.get("error") or "").lower())


class PriceAlertLineTests(unittest.TestCase):
    """User price-alert lines on the daily pane — not RSI tape alerts."""

    def test_shift_click_price_alert_contract(self):
        with open("scripts/price_alerts.js", encoding="utf-8") as fh:
            alerts = fh.read()
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("portfolio.py", encoding="utf-8") as fh:
            port = fh.read()
        with open("scripts/spy_rs.js", encoding="utf-8") as fh:
            spy_js = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()

        # Storage key, handler name, HTML control ids
        self.assertIn("whats-news-price-alerts", alerts)
        self.assertIn("PRICE_ALERTS_KEY", alerts)
        self.assertIn("function onDailyPriceAlertClick", alerts)
        self.assertIn("shiftKey", alerts)
        self.assertIn('id="price-alert-chips"', html)
        self.assertIn('id="pill-price-alerts"', html)
        idx = html.index('id="pill-price-alerts"')
        snippet = html[idx : idx + 280]
        self.assertIn("aria-pressed", snippet)
        self.assertIn("scripts/price_alerts.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/price_alerts.js"))

        # charts.js only calls hooks if present; weekly stays journal-only
        self.assertIn("if (freq === 'daily' && typeof onDailyPriceAlertClick === 'function')", charts)
        self.assertIn("if (onDailyPriceAlertClick(param)) return", charts)
        self.assertIn("typeof applyPriceAlerts === 'function'", charts)
        self.assertIn("typeof forgetPriceAlertLines === 'function'", charts)
        self.assertIn("freq === 'daily'", charts)

        # Plain click still hits the journal path
        self.assertIn("function setupBarClickJournal", charts)
        self.assertIn("subscribeClick", charts)
        self.assertIn("onChartBarClick", charts)
        self.assertIn("function onChartBarClick", app_js)
        self.assertIn("function openJournalForDate", app_js)

        # Shift+click does not call openJournalForDate
        self.assertNotIn("openJournalForDate", alerts)
        self.assertNotIn("onChartBarClick", alerts)
        hook_at = charts.index("if (onDailyPriceAlertClick(param)) return")
        journal_at = charts.index("onChartBarClick({ freq, date })")
        self.assertLess(hook_at, journal_at)

        # User price lines, not RSI tape alerts, not a published rating
        self.assertIn("not RSI", alerts)
        self.assertIn("not a published rating", alerts)
        self.assertIn("title: PRICE_ALERT_TITLE", alerts)
        self.assertIn("PRICE_ALERT_TITLE = 'Alert'", alerts)
        self.assertIn("coordinateToPrice", alerts)
        self.assertIn("createPriceLine", alerts)
        self.assertIn("PRICE_ALERTS_MAX = 8", alerts)
        self.assertIn("Weekly pane: do not add alerts", alerts)
        self.assertIn("localStorage.getItem(PRICE_ALERTS_KEY)", alerts)
        self.assertNotIn("series.weekly", alerts)

        for blob in (alerts, charts, html, app_js, port, spy_js, setup):
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
