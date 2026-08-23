# Consensus & Ship — Chart-First + Process Tools

Summary of what the review docs (`VISUAL_REVIEW.md`, `PM_REVIEW.md`, `METHODOLOGY_REVIEW.md`, `SUGGESTIONS.md`) agreed on unanimously, and what actually shipped in this pass across `index.html`, `scripts/app.js`, `scripts/charts.js`, `styles/main.css`, `app.py`, and `portfolio.py`.

## Unanimous agreements going in

1. **The regime heatmap + alert log must never occupy the default first viewport above the charts.** It was a permanent ~120-140px block; it had to move behind an explicit action.
2. **Two chrome rows doing the same job (`.main-nav-tabs` + `.tab-bar`) should merge into one.** No functionality lost — the tab-spacer trick already existed.
3. **The duplicate, heavier `.tab-btn` CSS rule was a bug, not a design choice**, and needed deleting outright (the lean rule wins by default now).
4. **`.pm-desk`'s glance metrics (regime/RSI/KAMA/returns/RS/ATR/peer/box) belong inline next to price, not in their own 70px band** — they're single values, not an interactive panel.
5. **Breakout queue and portfolio tape are the same surface with different filters**, not two competing UI elements — collapse into tape-mode chips (All / Breakout / Alerts).
6. **RS labeling must always read "Book RS #n/n"**, never bare "RS" or "IBD" — this is a book-relative rank against the watchlist, not an IBD RS Rating, and mislabeling it is a methodology risk (`METHODOLOGY_REVIEW.md`).
7. **Darvas box state is a distinct structural concept from KAMA/RSI indicators** and needed its own overlay + its own glance chip (`#pm-darvas`), never conflated with the trend/momentum panes.
8. **Sizing math should key off whichever stop is actually in play** (ATR, box low, or a user-entered stop) rather than always defaulting to 1.5×ATR — the old `position_size()` had no way to accept a structural stop.
9. **Emoji tabs and stacked OHLCV columns are chart-height/clarity liabilities** and should be replaced with plain labels and a single compact mono line.
10. **Optional indicator panes (RSI/MACD/Trend) should default off** — price-first, chart-first — and be toggle-able per-pane rather than all-or-nothing.

## What shipped

**Backend (`app.py`, `portfolio.py`)**
- `position_size()` now accepts an explicit `stop_price` and reports `stop_source` (`user_stop` vs `atr`) instead of always assuming ATR.
- New `darvas_box()` — simple N-bar consolidation-box detector (top/bottom/state: `in_box` / `breakout` / `failed`).
- `/api/pm-desk/<symbol>` now reads `stop` (`atr`/`box`/`user`), `stop_price`, and `target` query params, feeds the right stop into `position_size`, and returns a `risk_box` (entry/stop/target/r_multiple) for the chart overlay + copy-setup card.
- New `/api/darvas-box/<symbol>` endpoint for standalone box queries.

**Frontend behavior (`scripts/app.js`)**
- `renderPortfolioTape` is driven by `state.tapeMode` (`all` / `breakout` / `alerts`) via the new segmented `.tape-mode-btn` control — one tape surface, three filtered views. `renderBreakoutQueue` is gone; breakout is now a tape mode.
- Every RS display goes through `bookRsLabel()` → `Book RS #n/n` (or `Book RS —` when rank isn't available). No bare "RS"/"IBD" anywhere.
- Regime heatmap + alert log + theme leaders moved into `#book-drawer`, a right-side overlay drawer (open/close via `#btn-book-drawer` / backdrop / `Escape` / `h`), with `#pm-panels-badge` for at-a-glance alert count.
- New trade journal: `#journal-drawer` backed by `localStorage` (`whats-news-journal`), opened via `#btn-journal` / `Shift+J`, entries capture symbol/date/entry/stop/target/R and support inline close-with-R.
- New process-tools popover (`#pm-tools-popover`, `#btn-pm-tools`): entry/stop/target inputs with live R-multiple, stop-mode radios (ATR / box / user), a 4-item checklist that gates Copy Setup and Save to Journal until all boxes are checked, and a "Draw risk box" action wired to `charts.js`.
- `#pm-book-rs` / `#pm-darvas` glance chips filled from the pm-desk response; `#ohlcv-inline` gives a single compact `O · H · L · C · V` line in the header.
- Indicator pane pills (`#pill-pane-rsi/macd/trend`) and `#pill-darvas` toggle chart panes/overlays via `window.setIndicatorPane` / overlay APIs and persist to `localStorage` (`whats-news-panes`).
- Focus mode (`#pill-focus`, key `f`) hides the portfolio tape for a chart-only view.
- Popover has click-outside-to-close and closes automatically when either drawer opens, so it never gets stuck covering the pill row underneath it.

**Charts (`scripts/charts.js`)**
- New `applyRiskBox(entry, stop, target)` / `clearRiskBox()` — `createPriceLine` on both daily and weekly candle series (green/red/blue).
- New `applyDarvasBox(box)` / `clearDarvasBox()` — dashed orange top/bottom lines on the daily main pane, gated by `activeOverlays.darvas`.
- New `setIndicatorPane(pane, visible)` — toggles the pane wrapper + its divider on both daily and weekly, then resizes. Saved panes are re-applied on `initCharts()` (default: hidden, price-first).
- New `resizeAllCharts()` for callers (focus mode, pane toggles) that need a resize outside the `ResizeObserver` callback.
- **Fixed a real bug found during manual testing**: `setupResizeObserver()` created a new `ResizeObserver` per `initCharts()` call (i.e., every symbol switch) but never disconnected the previous one. Stale observers kept firing `chart.resize()` against already-`remove()`'d chart instances, throwing `Object is disposed` in the console on every pane toggle after a symbol switch. Fixed by tracking observers in `resizeObservers` and disconnecting them in `destroyCharts()` before charts are removed; also wrapped `chart.resize()` calls in try/catch as a second line of defense.

**Styles (`styles/main.css`)**
- Deleted the duplicate heavier `.tab-btn` block; the lean rule now wins unambiguously.
- `.symbol-header` compacted to `6px 12px` padding; PM desk metrics live inline as `.pm-desk-inline` (flex row, wrap, no full-width band/gradient).
- `.portfolio-tape` slimmed to `4px 12px`.
- `.main-nav-tabs` merged nav + indicator-toggle row, lean padding, no more stacked chrome rows.
- New: `.book-drawer` (+ `.journal-drawer` modifier), `.book-drawer-backdrop`, `.pm-tools-popover`, `.tape-mode` segmented control, `.pm-checklist`, `.journal-list`/`.journal-item`, `.theme-leaders`, `.visually-hidden`.
- `.focus-mode #portfolio-tape { display: none !important; }`.
- `.pane-optional[hidden]` / `.chart-divider-{rsi,macd,trend}[hidden]` collapse cleanly; `.chart-wrapper-main` gets `flex: 1.6` via `:has()` when all optional panes are hidden, so price gets the reclaimed height instead of leaving a gap.
- `.ind-pill.active-darvas` styling; `tabular-nums` applied to mono/numeric displays so tape/heatmap/OHLCV digits don't jitter.

## Verification

- `DATA_SERVICE_MODE=embedded python3 -m unittest discover tests -v` — 39/39 passing.
- Manual Playwright smoke test against a live embedded-mode server: symbol switching, all three tape modes, book drawer, journal drawer (save + list render), process-tools popover (risk box inputs, R-multiple, checklist gating, draw risk box), focus mode, all three pane toggles, and the Darvas pill — zero page errors after the `ResizeObserver` fix, across 9 repeated symbol switches with pane toggling on each.
