# FinDash — Quant Terminal

Python (Flask) + vanilla JS quant trading dashboard. Yahoo Finance OHLCV →
SQLite (`finance.db`, gitignored) → REST API → Chart.js / Lightweight-Charts
frontend. No build step; `index.html` loads `scripts/*.js` directly.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # setup
.venv/bin/python app.py            # serve on :8050 (PORT env to override)
.venv/bin/python -m pytest -q      # full test suite (~10s) — keep it green
```

## Architecture (quant stack)

- `quant_lab.py` — shared `_state_frame()` feature engine + six models
  (fair value, KNN fan, CTA, exhaustion, squeeze, mean reversion), composite
  VALUATION/DIRECTION dials with character-conditioned weights
  (`PROFILE_WEIGHTS`), watchlist grid. Tab: ⚡ Quant Lab.
- `signal_scanner.py` — pluggable routines via `@_routine`; adding a scanner
  is ONE decorated function (API/UI/counts pick it up automatically). Every
  scan journals fires to the `signal_journal` table; `track_record()` replays
  each routine's rule over full history. Tab: 🚨 Signals.
- `fair_value_lab.py` — trend / PCA divergence anchors with walk-forward OOS
  validation. PCA panels are sector-scoped via `group_tag` when ≥ 6 peers
  exist, else watchlist-wide; memoised per scope with a thread lock.
  Tab: ⚖️ Fair Value (FiveThirtyEight-style light theme).

## Conventions

- **Causality is sacred.** Anything labelled walk-forward/OOS must only use
  data available at prediction time (train slices end ≥ horizon bars before
  the prediction index). Validate new models against a synthetic OU process
  (must detect edge) AND near-random data (must report WEAK, not flatter).
- **Edge cases are test cases.** Financial inputs include flat prices,
  zero/NaN volume (FX), date gaps, tiny prices, < 300 bars. Engines must
  degrade gracefully (return `None`/score-less sections), never raise.
  All API payloads must survive `json.dumps(..., allow_nan=False)` —
  use `_fl` / `_fl_list` to round and None-ify non-finite values.
- **Chart.js configs always need a top-level `type`** — even mixed charts
  (per-dataset types alone throw at runtime).
- **Async UI must respect the active tab**: never toggle areas
  (`showEmptyState()` etc.) after an `await` without checking
  `state.activeTab` — slow failures must not hide the tab the user is on.
- Tests monkeypatch `database` functions (incl. `record_signals` /
  `get_signal_journal`) — never let tests write the real `finance.db`.
- Threaded code (scanner/grid use `ThreadPoolExecutor`): module-level
  memos need locks; SQLite is safe (per-call connections).

## Verification in this sandbox (Claude Code on the web)

CDNs (unpkg/jsdelivr/fonts) are blocked by the network policy. To
browser-verify the UI with Playwright (installed globally in /opt/node22):

1. `npm install --no-save chart.js@4.4.0 lightweight-charts@4.1.3` in /tmp
   (npm registry is allowed), then route-intercept the CDN URLs and fulfill
   from `/tmp/node_modules/...`; also stub fonts.googleapis.com.
2. Launch chromium with `--ignore-certificate-errors` + `ignoreHTTPSErrors`.
3. Seed demo data straight into the DB via `database.upsert_ohlcv` with
   synthetic frames (yfinance is unreachable); ≥ 900 daily bars per symbol.
4. Allow ~250 ms after UI actions before `page.reload()` — persistence
   saves are debounced.

Browser-verify every new/changed panel before declaring done.
