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

## Wave 2 — next (M effort, high value)

1. **Honest backtester**: walk-forward split (train/test), report the selected
   config's out-of-sample performance; label in-sample numbers (Quant #1).
2. **Validate the app's own signals**: push `trend_score` and composite trend
   state through `stats.get_binned_performance`; backtest MRT/MDB exit rules
   and attach historical hit-rate to the R:R card (Quant #6, #7).
3. **Watchlist that informs**: last close + change% per row, "no data" badge
   with one-click refetch (UX #3).
4. **Real error state**: dedicated retry UI instead of the misleading
   "No Symbol Selected"; unify 404-auto-fetch across all tabs; guard
   `res.json()` on non-JSON responses (UX #2).
5. **Compute cache + vectorization**: memo `(symbol, freq, config-hash,
   latest_bar_date)` for trend-scan/scanner; vectorize `_pct_rank` and KAMA
   loops (Engineer #1, #5).
6. **Adjustment drift**: overlap-check stored closes vs fresh download; full
   re-download on mismatch (Engineer #4b).
7. **Keyboard model**: `/` focuses symbol input, ↑/↓ walk the watchlist,
   focusable rows (UX #4).
8. **Re-token Statistics tab** to the app palette (Visual #2) and unify
   `--gutter-x: 16px` across remaining bars (Visual #3).

## Wave 3 — bigger bets

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
