# FinDash Improvement Roadmap

Synthesis of a four-expert panel review (2026-07): two UX/visual designers, a
hedge-fund quant, and a trading-platform engineer each audited the codebase
independently. This file records where they converged, the ranked plan, and
what has shipped.

## Panel verdicts (one line each)

- **UX designer** — "Powerful engine, unfinished cockpit": the analytics are ahead
  of many retail tools, but the seven tabs each invented their own refresh,
  error, and click semantics; no keyboard model.
- **Visual designer** — Real defects, not taste: duplicate CSS blocks broke the
  active-tab contrast; Statistics uses an alien palette; smallest text had the
  worst contrast; line colors have three disagreeing sources of truth.
- **Quant** — "A well-engineered *descriptive* dashboard wearing the costume of a
  *predictive* one": correct KAMA/regime plumbing, but the backtester and R:R
  panels flatter the user with claims the data doesn't support.
- **Engineer** — Good bones (parameterized upserts, endpoint smoke suite, active
  debt paydown) but nothing built for >10 symbols or concurrent use; two data-
  correctness bugs poisoning downstream indicators.

## Cross-panel convergence (independent agreement = highest confidence)

| Issue | Flagged by |
|---|---|
| LINE_META captions document parameters the system doesn't use | UX, Quant, Visual |
| Dead/duplicate legacy CSS + scanner code paths | UX, Visual |
| Toast flood on Refresh All | UX, Engineer |
| Scanner recomputes everything on every tab visit | UX, Engineer |
| Stale scan table after freq/method change | UX (workflow), Engineer (cache) |
| R:R shown without hit-rate context | Quant (misleading), UX (unclear) |

## Wave 1 — SHIPPED (small, high-impact, consensus)

- [x] SQLite WAL mode + busy timeout; drop redundant index (Engineer #3) —
      eliminates reader stalls / "database is locked" during bulk fetches.
- [x] Request-generation guards in the four view loaders (Engineer #2) —
      fast symbol/tab switching can no longer render stale data under the
      wrong header.
- [x] Incremental fetch: rebuild weekly bars from full stored daily history
      (Engineer #4a) — partial W-FRI candles no longer overwrite correct ones.
- [x] Scanner symbol click navigates to the chart (UX #1).
- [x] Transaction costs (5 bps/side) in backtester metrics + equity curve;
      status line now says "· 5 bps/side costs · in-sample" (Quant #2, #1 partial).
- [x] Delete duplicate `.tab-btn` block → active tab readable again; re-token
      nav tabs to the app palette (Visual #1, part of #2).
- [x] Delete dead legacy scanner CSS block (Visual #9).
- [x] `--text-dim` #4a5568 → #7d8590 (≥4.5:1 on bg) (Visual #4).
- [x] Trend line captions generated from live `trendConfig`; LB color single
      source of truth; "built-in 2:1 R:R" copy corrected to construction ratio
      (UX #9, Quant #7, Visual #5).
- [x] Trend scan re-runs on freq/method change — no stale table under fresh
      pills (UX #5).
- [x] Refresh All: one summary toast instead of N (UX #8, Engineer #7).
- [x] Empty state no longer shows the floating KAMA toolbar (UX #10).

## Wave 2 — SHIPPED

- [x] **Honest backtester**: configs ranked on the first 75% of history only;
      selected config's holdout metrics + OOS buy-and-hold shown in a second
      KPI row; equity curve overlays the holdout segment (Quant #1).
- [x] **Validate the app's own signals**: `trend_score_analysis` (fwd 1d/5d +
      N per score level) rendered as a Statistics card; `system_stats` replays
      the MRT/MDB exit rules and shows TP-first rate / win rate / expectancy
      under the signal grid (Quant #6, #7).
- [x] **Watchlist that informs**: change% badge per row from a single window-
      function query; explicit "no data" badge (UX #3).
- [x] **Real error state**: dedicated retry UI replaces the misleading
      "No Symbol Selected"; `res.json()` guarded by content-type (UX #2).
- [x] **Scan caches**: 5-min TTL keyed on config + latest bar date; repeat
      trend-scan 1.3 s → 14 ms measured (Engineer #1, #5 — vectorizing the
      cold path remains open, see Wave 3).
- [x] **Adjustment drift**: 7-day overlap check on incremental fetch; full
      re-download on close mismatch (Engineer #4b).
- [x] **Keyboard model**: `/` focuses symbol input, ↑/↓ walk the watchlist
      (UX #4 — focusable rows / ARIA remain open).
- [x] **Re-token Statistics tab** to the app palette; unify topbar /
      symbol-header / tab-bar / scanner-controls to the 16px gutter; lift
      9/9.5px table headers to 10px (Visual #2, #3, part of #8/#10).

## Wave 3 / AAA verification pass — SHIPPED

A second agent panel (release auditor + fresh-eyes polish hunter) verified all
Wave 1/2 claims against the code. Auditor verdict: everything VERIFIED except
three findings, all fixed:

- [x] **HIGH — `_system_stats` exit ordering**: the regime-flip check now runs
      before the stop/TP checks (the ratchet band resets to the short side on
      the flip bar, so flips were recorded as profitable stop-outs at
      fictitious prices). Two regression tests pin the semantics.
- [x] Trend-tab coherence: method change on the scan sub-tab invalidates the
      chart's cached series; `loadTrendScan` and `loadBacktest` gained
      ordering guards.
- [x] Dead `heatmap`/`fast_periods`/`slow_periods` payload removed from the
      backtest response; scan caches no longer cache error rows.
- [x] Polish panel: stale backtest results cleared on symbol change; Stats tab
      loading overlay; scan-table sticky headers restored + Chg% cells frozen;
      trend-scan header offsets fixed; directional sort arrows; global
      :focus-visible; disabled-hover guards; FinDash wordmark; aria-labels;
      aria-live toasts; localized header price; trend-scan first-run CTA.
- [x] Wave 3 usefulness: settings persistence (KAMA pills, trend config/
      method/freq/visibility, scanner groups, risk $); undo-toast for symbol
      removal; click-to-dismiss toasts; position-size calculator
      (risk $ ÷ (price − MRT)).

## Chart panel (2 designers + 2 quants) — SHIPPED

- [x] Crosshair OHLC + indicator legends on all price charts.
- [x] Trade markers: entries (▲L/▼S) + replayed exits (TP with R-multiple /
      stop / flip) drawn on the trend chart; `_system_stats` returns
      per-trade records with gap-aware fills (stop fills at the open when a
      bar gaps through the level).
- [x] Volume panes on every price chart (was stored, never charted).
- [x] Validated visual spec: MB master line near-white 2.5px (was candle-red),
      teal targets / rose stops / dotted long-horizon, regime strip as
      full-row heatband ribbons with visible neutral, background fills above
      gridline salience, slate BB, RSI-14 hierarchy, CVD-safe KAMA pool,
      cross-tab KAMA color identity, Chart.js mono type + system accent.
- [x] Crosshair mirrored across all panes (72px shared axis gutter),
      log-scale toggle (persisted), 3M/1Y/All presets, double-click reset,
      zoom preserved across symbol switches and trend re-fetches.
- [x] Correctness (HIGH): candles now fetched at the indicator/trend window
      (1000/1500 bars) — indicator lines no longer float over candle-less
      regions and fitContent covers real data.
- [x] Correctness: in-progress weekly bar no longer future-stamped (final
      W-FRI bin re-stamped to the last trading day; weekly bars replaced
      wholesale on rebuild); daily↔weekly sync guard rewritten (the rAF-async
      event model made the boolean flag a no-op — edges drifted to Friday
      stamps); RSI pane pinned to 0-100 and trend-score to ±3.5; header
      change badge labeled "wk" on weekly; scan-row click adopts the scan's
      frequency; trend `_toLine` emits whitespace instead of bridging gaps;
      holdout equity overlay starts after the mixed split week.

### Chart backlog (not yet shipped)
- Subchart hover readouts (RSI/MACD values at crosshair) + collapsible panes.
- Equity curve: drawdown sub-panel, log y-axis, split-date annotation.
- Per-trade R-multiple histogram; SPY relative-strength pane.
- Hoist a shared TREND_WINDOW constant (scan aux columns still use 600-bar
  warmup vs chart 1000); dim MRT/MDB bands during neutral regimes (they
  forward-fill and read as live levels); "back to latest" button; decile
  error bars; bars-vs-calendar period disclosure.

## Wave 4 — remaining (from the verification panel)

- Crosshair OHLC/indicator legend + crosshair sync across panels (the
  biggest "amateur vs terminal" tell; polish hunter #7).
- Responsive: scrollable tab strip, stacking chart panels ~1100px, flex-based
  Data Manager height (polish #10).
- Shared number-format module (price/pct/ratio consistent across tabs,
  polish #6); monochrome icon set (polish #12).
- Route stats/KNN/trend errors to the retry error-state (auditor note).
- Test gaps: drift detection, weekly rebuild-from-full-history, cache
  invalidation on new bar date (auditor blocker #5, partially closed).
- Unify the two remaining trend-score copies (backtester/scanner use `ta`,
  indicators/stats use local impls — edge-case divergence at series start).

## Wave 3 (original) — bigger bets

- Position-size calculator from MRT (`shares = risk_$ / (price − stop)`),
  "signals changed since yesterday" diff, RS-vs-SPY column (Quant #9).
- Persist trend config / KAMA pills / band visibility across reloads (UX #6).
- Columnar + gzipped API payloads; incremental chart updates without full
  teardown; preserve zoom across symbol switches (Engineer #6, #8).
- SSE batch: server-side job state, resume after disconnect, skip
  recently-fetched (Engineer #10).
- ES-module frontend refactor to retire cross-file globals (Engineer #9).
- Decile/seasonality panels: error bars, N per bin, gray out |t| < 2
  (Quant #4, #5); undo-toast for symbol removal (UX #7).
