# Ship List — cursor/chart-first-visual-10x-f287

Synthesis of five specialist lenses (Brandt, Qullamaggie, Neumann, Darvas, O'Neil) + the chart-first visual/UX pass. Target: what all five would sign off as **10x** on the integration branch `cursor/chart-first-visual-10x-f287`.

## Part 1 — Full prior visual consensus (restated)

*Full write-up: `VISUAL_REVIEW.md`. Restated here in full per request.*

**Baseline:** chrome above the chart was ~390-450px — portfolio-tape (~40px) + regime-heatmap/alert-log cards (~120-140px) + symbol-header (~70-80px) + pm-desk strip (~70px) + main-nav-tabs (~52-56px, inflated by a **duplicate `.tab-btn` CSS rule** at `main.css:955` overriding the leaner one at `main.css:677`) + a 6th uncounted row, `.tab-bar` indicator toggles (~40px).

**Top 7 changes (ranked by chart-height reclaimed + clarity):**
1. Move regime heatmap + alert log off default flow into a collapsed drawer — ~120-140px.
2. Delete duplicate `.tab-btn`; merge `.tab-bar` into `.main-nav-tabs` — ~55-65px.
3. Fold `.pm-desk` glance metrics into `.symbol-header` as inline chips; calc widgets (Size/Stops/Copy-setup) → popover — ~55-65px.
4. Compress `.symbol-header` padding + single-line OHLCV — ~15-20px.
5. Slim `.portfolio-tape`; move secondary buttons to overflow — ~8-10px.
6. Strip emoji from tabs; SVG or none — 0px, high clarity.
7. Inter → system-ui + `tabular-nums`; one news surface (not `/news` *and* `#tab-news`) — 0px, high clarity.

**Layout order — default:** topbar → one compact command bar (ticker+price+badge, tape chips, Regime/RSI/ATR glance chips, alert-count badge) → one merged nav row (view tabs + indicator pills, pills only visible on Charts tab) → chart + indicator panes.
**Optional/off-canvas:** regime heatmap + alert log (drawer, ≤1 click/key); PM-Desk calc widgets (popover); full OHLCV (on hover); symbol subtitle (tooltip).

**Specialist consensus:** unanimous **Y** — heatmap + alert log must not sit in the default first viewport above charts. Condition: reachable in ≤1 click/keystroke with a persistent unread-badge, no signal silently lost.

**CSS/JS approach:** right-side overlay drawer (`position:fixed`, `transform:translateX`, ~180ms, overlay not push so charts never reflow/resize) on desktop; true swipe-up bottom sheet only under `@media (max-width:640px)`. Toggle via a badge + keyboard shortcut, state in `localStorage`.

**Done criteria for "10x visual":** zero secondary panels on cold load · chrome ≤120px at ≥1280px width · one `.tab-btn` rule · zero emoji in nav · heatmap/alerts ≤1 click/key with unread badge · chart+indicator panes ≥80% of `.main` height at 900px viewport · tabular-nums everywhere numeric · one unambiguous News entry point · mobile chart pane ≥60% of viewport · transitions ≤200ms honoring `prefers-reduced-motion`.

## Part 2 — What's already shipped (Qullamaggie, commit `d90c40c`)

Volume pane per chart panel, breakout queue (near-20D-high + vol≥1.5×20-bar-avg), EP gap+volume markers (on by default), EMA 10/21/50 stack (off by default), strong-name news fix (`news_focus` leads with breakout/strong-RS, not weakest-RS — closes methodology must-not-do #3), and the regime-heatmap/alert-log `<details>` drawer with unread badge (closed by default, zero-JS toggle) — **this already satisfies visual-consensus item #1**.

**Regression introduced against the visual budget:** a new always-visible `#breakout-queue-bar` row (~32-40px) was added *stacked above* `.portfolio-tape`, re-adding a chrome row after item #1 removed one. Net effect of the commit is still a reclaim (~-60-70px), but it's short of the ~255-300px target and violates done-criterion #2 (chrome ≤120px) on its own. **Must fix before calling this branch done — see M2 below.**

## Part 3 — Agreed ship list (must-have vs stretch)

### Must-have — all five specialists + visual pass agree this is the 10x floor

| ID | Item | Owner ask(s) | Files |
|---|---|---|---|
| **M1** | Delete duplicate `.tab-btn` (`main.css:955-978`); merge `.tab-bar` indicator-toggle row into `.main-nav-tabs`, gated by `switchTab()` so pills only render for the Charts tab | Visual | `styles/main.css`, `index.html`, `scripts/app.js` |
| **M2** | Merge `#breakout-queue-bar` into `.portfolio-tape` as a segmented filter (`All / Breakout / Alerts`) over the *same* `#tape-chips` row instead of a second stacked bar — recovers the ~32-40px this feature currently costs | Visual (fix regression) + Qullamaggie + O'Neil (breakout queue must stay glanceable, just not in its own row) | `index.html`, `styles/main.css`, `scripts/app.js` (`renderPortfolioTape`, `renderBreakoutQueue`) |
| **M3** | Fold `#pm-desk` glance metrics (Regime, RSI, KAMA, 5D/21D, ATR%, Peer) into `.symbol-header` as inline chips; move Size-@-risk / 1.5×ATR-stops / Copy-setup into a popover off the price block | Visual | `index.html`, `styles/main.css`, `scripts/app.js` |
| **M4** | Structural/user risk box: entry · stop · target as horizontal price lines on the daily + weekly chart; size calc keyed off *user stop* delta, fallback to 1.5×ATR when no stop set | Brandt + Neumann + Qullamaggie (methodology High #1) | `scripts/charts.js`, `index.html` (risk-box inputs in the M3 popover), `portfolio.py` or `scripts/app.js` (size formula), `styles/main.css` |
| **M5** | Honest labeling pass: "Book RS (21D)" everywhere instead of bare "RS"; breakout-queue tooltip/copy states the exact rule (near-high% + vol× + D/W up) already computed in `portfolio.py` | O'Neil (no invented IBD RS) + Qullamaggie | `index.html`, `scripts/app.js` (label/tooltip strings) |
| **M6** | Darvas box: rolling box high/low + state (inside/breakout/fail) → two-line + shaded-band overlay on daily chart, breakout badge on tape/heatmap chip, "stop at box low" as a second stop-source option inside the M4 risk box | Darvas | `portfolio.py` or `indicators.py` (box calc), `scripts/charts.js` (overlay + badge), `index.html` (box toggle pill), `styles/main.css`, `tests/test_portfolio.py` |
| **M7** | Remaining chrome trims: strip emoji from `#tab-charts`…`#tab-data-manager` icons, `font-variant-numeric: tabular-nums` on all mono numeric fields, compress `.symbol-header` padding + single-line OHLCV | Visual | `index.html`, `styles/main.css` |

**Must-have net effect:** chrome above chart lands at ~100-120px (M1+M2+M3+M7 combined ≈ 130-170px reclaimed beyond what Qullamaggie already shipped), *and* the chart itself gains the structural-risk + Darvas-box overlays every non-visual specialist asked for. This is the combination all five would call 10x: momentum tools (shipped) + honest risk/structure (M4/M6) + chart-first chrome (M1/M2/M3/M7).

### Stretch — valuable, not required for the five-way sign-off

| ID | Item | Owner ask | Files |
|---|---|---|---|
| S1 | Trendline / horizontal drawing tools (manual pivots) | Brandt | `scripts/charts.js`, `index.html` |
| S2 | Checklist → Copy-setup → journal + R-multiple tracking | Neumann | `scripts/app.js`, `database.py` (journal table), `index.html`, `tests/test_database.py` |
| S3 | M-lite market clock: single SPY/QQQ regime chip | O'Neil | `portfolio.py`, `index.html`, `scripts/app.js`, `styles/main.css` |
| S4 | VCP/contraction score, volume dry-up flag | Qullamaggie (methodology medium) | `portfolio.py`, `scripts/charts.js` |
| S5 | One news surface (merge `/news` and `#tab-news`), Inter → system-font swap | Visual (clarity, larger IA change) | `index.html`, `news.html`, `styles/main.css` |

## Exact file touch list (must-have set, consolidated)

| File | Touched by |
|---|---|
| `index.html` | M1, M2, M3, M4, M5, M6, M7 |
| `styles/main.css` | M1, M2, M3, M4, M6, M7 |
| `scripts/app.js` | M1, M2, M3, M4, M5 |
| `scripts/charts.js` | M4, M6 |
| `portfolio.py` (or `indicators.py` for M6 box calc) | M4 (size formula), M5 (label audit only, no schema break), M6 (box calc) |
| `tests/test_portfolio.py` | M6 (box calc unit test) |

No changes required to `database.py`, `data_client.py`, `data_service/*`, `news.html`, or any Python test file outside `test_portfolio.py` for the must-have set — this is a chart/chrome/overlay pass, not a data-layer change. Stretch items S2/S3 are the only ones that touch `database.py`.
