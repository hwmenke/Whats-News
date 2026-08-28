# Visual Hierarchy Review — Whats-News (Chart-First Pass)

Specialist: trading-desk product/UX. Scope: pixels above the chart, chrome weight, motion, mobile.
Constraint honored: **regime heatmap + alert log must never sit in the default first viewport above charts.**

## Current stack (measured against `index.html` / `styles/main.css`)

| # | Element | Height | Source |
|---|---------|--------|--------|
| 1 | `.portfolio-tape` | ~40px | `index.html:74` / `main.css:432` |
| 2 | `.pm-panels` (regime heatmap + alert log cards) | ~120-140px | `index.html:84-93` / `main.css:517-592` |
| 3 | `.symbol-header` | ~70-80px | `index.html:96-131` / `main.css:355-429` |
| 4 | `.pm-desk` metric strip | ~70px | `index.html:134-172` / `main.css:617-665` |
| 5 | `.main-nav-tabs` | ~52-56px (bloated, see finding A) | `index.html:175-200` / `main.css:947-978` |
| 6 | `.tab-bar` (KAMA/BB indicator toggles) | ~40px, **undercounted in the brief** — this is a 6th chrome row sitting *under* nav-tabs, still above charts | `index.html:201-215` / `main.css:668-675` |

**Total chrome before first chart pixel: ~390-450px.** On a 900px-tall main content area that's ~45-50% of the viewport spent before any candle, RSI, MACD or Trend pane renders.

### Finding A — duplicate, heavier `.tab-btn` rule wins
`main.css` defines `.tab-btn` twice: a lean version at `main.css:677` (`padding:5px 14px; font-size:12px`) and a second, later, heavier one at `main.css:955` (`padding:12px 20px; font-size:14px`). CSS cascade means the **second one wins**, so `main-nav-tabs` renders ~15-20px taller than intended and inconsistent with `.tab-bar` pill sizing directly below it. This is a bug, not a design choice — it's also emblematic of the "heavy card chrome" complaint.

### Finding B — two independent chrome rows do the same job (tabs)
`.main-nav-tabs` (view switcher) and `.tab-bar` (indicator toggles) are two separate flex rows, each with their own padding/border, stacked back-to-back (`index.html:175` and `index.html:201`). They can be one row.

### Finding C — dual news surfaces add nav weight, not chart height
`topbar-nav` (`index.html:27-30`) has a standalone `/news` link *and* `#tab-news` inside `main-nav-tabs` (`index.html:179`). Doesn't cost vertical px but adds IA confusion flagged in `SUGGESTIONS.md:10`; rolled into this pass since it's part of the same nav-chrome cleanup.

---

## 1. Top 7 changes, ranked by chart-height reclaimed + clarity

| Rank | Change | Est. px reclaimed | Why it ranks here |
|---|---|---|---|
| 1 | **Move `#pm-panels` (regime heatmap + alert log) off the default flow into a collapsed drawer** | ~120-140px | Single biggest block; directly satisfies the hard constraint; today it's `display:grid` any time `data.heatmap.length` (`scripts/app.js:269`) — i.e. on by default for anyone with >0 watchlist symbols. |
| 2 | **Delete the duplicate `.tab-btn` (`main.css:955-978`) and merge `.tab-bar` indicator toggles into the same row as `.main-nav-tabs`** | ~55-65px | Fixes the CSS bug (Finding A) and collapses two chrome rows into one (Finding B). Zero functionality lost — `.tab-spacer` already exists to push content right. |
| 3 | **Fold `.pm-desk` metrics into `.symbol-header` as inline chips, action items into an overflow popover** | ~55-65px | Regime/RSI/KAMA/5D-21D/ATR/Peer are glanceable single values — they belong beside price, not in their own 70px band. Size-calc + Copy-setup (interactive, not glance) move to a popover off the price block. |
| 4 | **Compress `.symbol-header`: 12px→8px vertical padding, OHLCV to one mono line instead of stacked label/value columns** | ~15-20px | Header text sizes (20px title, 22px price) are fine; the *padding + stacked OHLCV layout* is the fat, not the type. |
| 5 | **Slim `.portfolio-tape` to a single 28-32px row; move "Book news" button into the tape's own overflow/`…` menu** | ~8-10px | Tape is already close to minimal; small trim plus one fewer always-visible button lowers noise. |
| 6 | **Strip emoji glyphs from `.tab-btn`/`.tab-icon` (`index.html:176-199`), replace with 1px-stroke SVG or drop icons entirely, use color/underline for active state** | 0px height, high clarity | Emoji render inconsistently across OS/fonts (baseline shift, color glyphs clash with dark theme), and they're the most-cited "toy UI" signal. Also unblocks tab row height being deterministic (no emoji ascent inflating line-height). |
| 7 | **Swap `Inter` for a numeral-first stack (`ui-sans-serif`/`system-ui` for labels + `font-variant-numeric: tabular-nums` everywhere `--font-mono` is already used) and collapse `/news` vs `#tab-news` into one surface** | 0px height, high clarity | Inter is a generic marketing-site font; a system stack loads instantly (no `@import` round-trip at `main.css:5`) and looks native-desk. Tabular numbers stop tape/heatmap/OHLCV digits from jittering on refresh. One news surface removes a redundant mental model (ties to `SUGGESTIONS.md:10`). |

**Net reclaim if 1-5 ship: ~255-300px** — chrome above chart drops from ~390-450px to ~110-140px. That alone roughly doubles chart+indicator pane height on a typical 900px-tall desk monitor.

---

## 2. Proposed layout order — default vs optional

### Default (always visible, above charts, target ≤120px total)

```
topbar                                   40px   (unchanged)
├─ compact command bar                  ~32px   (was: portfolio-tape + symbol-header + pm-desk)
│    [ticker · price · Δbadge]  [tape chips, scroll-x]  [Regime|RSI|ATR chips]  [🔔N alerts]  [⋯]
├─ merged nav row                       ~36px   (was: main-nav-tabs + tab-bar)
│    Charts  News  Stats  KNN  Backtest  Trend  Scanner  Data        …spacer…   KAMA pills · BB
└─ chart + indicator panes              everything else
```

### Optional / opt-in (off-canvas, revealed on demand, never pushes chart layout)

- **Regime heatmap + alert log** → right-side drawer, two internal mini-tabs ("Regime" / "Alerts"), opened via the `🔔N` badge in the command bar or a keyboard shortcut. Closed by default, state persisted per user.
- **PM Desk detail** (Size @ $ risk, 1.5×ATR stops, Copy setup) → popover anchored to the price block, opened on click of the price or a small `⋯` affordance. Regime/RSI/ATR stay as always-on glance chips; only the *interactive* calc widgets move to the popover.
- **Full OHLCV** → collapses to O/H/L/C/V shown on hover/focus of the price badge instead of a permanent second line; still one click/hover from visible.
- **Symbol subtitle/exchange metadata** → tooltip on the ticker, not a persistent second text line.

---

## 3. Specialist consensus — heatmap + alert log must NOT be in default first viewport above charts

| Specialist lens | Y/N | One-line rationale |
|---|---|---|
| PM-A (trend/momentum) | **Y** | Regime is decision-support, not the decision surface — chart structure is. Heatmap belongs one click away, not permanently stealing chart height. |
| PM-B (swing/mean-reversion) | **Y**, with condition | Alerts must stay *reachable in ≤1 action* with a visible unread badge — full removal (no drawer) would slow the RSI-alert workflow this desk was built for. |
| PM-C (multi-name book) | **Y** | Book-wide context (heatmap) is a scan tool used in bursts, not continuously — a drawer preserves the scan without permanent cost. |
| Methodology panel (Brandt/Qullamaggie/Neumann/Darvas/O'Neil, `METHODOLOGY_REVIEW.md`) | **Y** | Consistent with their shared "keep it simple, chart-first" critique (`METHODOLOGY_REVIEW.md:33`, Brandt: price-first mode) — indicator confluence and book-scan tools should never outrank the primary chart. |

**Unanimous Y**, conditioned on: drawer/popover access stays ≤1 click or 1 keystroke, and an always-visible unread-alert count so no signal is silently lost.

---

## 4. Concrete CSS/JS approach

**Pattern: right-side slide-in drawer, overlay (not push).** Not a bottom sheet on desktop — trading monitors are wide, and a bottom sheet either eats chart height from below (defeats the whole point) or, if overlaid, covers chart x-axis/labels which are read constantly. Right overlay drawer clears the bottom axis and doesn't reflow `.charts-container`, so `lightweight-charts` never needs a resize/redraw when it opens.

```css
/* Toggle target lives in the command bar, not a persistent panel */
.pm-drawer {
  position: fixed;
  top: var(--topbar-h);
  right: 0;
  width: 340px;
  height: calc(100vh - var(--topbar-h));
  background: var(--bg-elevated);
  border-left: 1px solid var(--border);
  transform: translateX(100%);
  transition: transform 180ms ease;
  z-index: 50;
  display: flex;
  flex-direction: column;
}
.pm-drawer.open { transform: translateX(0); }
@media (prefers-reduced-motion: reduce) { .pm-drawer { transition: none; } }

/* Bottom sheet only below the mobile breakpoint — see §mobile */
@media (max-width: 640px) {
  .pm-drawer {
    top: auto; right: 0; left: 0; bottom: 0;
    width: 100%; height: 70vh;
    transform: translateY(100%);
    border-left: none; border-top: 1px solid var(--border);
    border-radius: 14px 14px 0 0;
  }
  .pm-drawer.open { transform: translateY(0); }
}
```

```js
// Reuse existing renderers, just point them at the drawer instead of #pm-panels
function togglePmDrawer(force) {
  const drawer = document.getElementById('pm-drawer');
  const open = force ?? !drawer.classList.contains('open');
  drawer.classList.toggle('open', open);
  localStorage.setItem('wn_pm_drawer_open', open ? '1' : '0');
}
document.getElementById('alert-bell').addEventListener('click', () => togglePmDrawer());
document.addEventListener('keydown', e => {
  if (e.key === 'g' && !e.target.closest('input,textarea')) togglePmDrawer();
});
```

- `renderRegimeHeatmap()` / `renderAlertLog()` (`scripts/app.js:260`, `scripts/app.js:288`) keep their logic; only the target container IDs change (`#pm-panels`/`#regime-heatmap`/`#alert-log` → drawer-scoped IDs). No API changes needed.
- Unread badge: increment a counter in `renderPortfolioTape` whenever a new symbol enters `data.alerts` (`scripts/app.js:203-209` already tracks `state.seenAlerts` — reuse it) and render it on `#alert-bell` as a small count pill; clear on drawer open.
- Nav-row merge: delete `main.css:955-978`; move `.indicator-toggles` markup (`index.html:201-215`) inside `.main-nav-tabs`, gated with `style.display` toggled in `switchTab()` so it only shows when `tab === 'charts'`.
- PM Desk popover: same overlay pattern as the drawer but anchored (`position:absolute` under the price block) instead of edge-docked; toggled from a `⋯` button next to `#sym-price`.
- All new toggles persist to `localStorage` (drawer open/closed, popover last state) so a desk doesn't have to re-collapse every reload — mirrors the existing preset pattern at `scripts/app.js:1590`.

---

## 5. Done criteria — "10x visual"

Read as 10x *decision speed and chart legibility*, not literal pixels — but every item below is directly verifiable:

1. **Zero** of `#pm-panels`, drawer content, or PM-Desk popover visible on a cold load with no saved preference (`display:none`/off-canvas by default).
2. Chrome height above the chart pane ≤ **120px** at ≥1280px width (down from ~390-450px) — measurable via `getBoundingClientRect()` sum of command-bar + nav-row.
3. `main.css` contains **exactly one** `.tab-btn` rule (grep count = 1); `.main-nav-tabs` computed height ≤ 40px.
4. **Zero** emoji code points in tab/nav markup (`index.html` tab buttons).
5. Regime heatmap + alert log reachable in **≤1 click / 1 keystroke**, with a persistent unread-count badge always visible — no information lost, only footprint reduced.
6. Chart + indicator panes occupy **≥80%** of `.main` height on a 900px-tall viewport at desktop width (up from ~50-55%).
7. All tape/heatmap/OHLCV/PM numerics use `font-variant-numeric: tabular-nums` (or `--font-mono`) — no layout jitter on data refresh, verified by diffing bounding boxes pre/post refresh.
8. Exactly **one** primary "News" affordance per screen (either merged surfaces or one clearly labeled entry point) — no duplicate ambiguous nav targets.
9. Mobile (≤480px): drawer becomes a true swipe-up bottom sheet; nav row is a single horizontally-scrollable strip; chart pane still gets **≥60%** of viewport height with no vertical scroll to see price + first indicator pane.
10. All new show/hide transitions ≤200ms and honor `prefers-reduced-motion` (instant, no transform, when set).

---

*Companion to `PM_REVIEW.md` (feature/decision-speed loop) and `METHODOLOGY_REVIEW.md` (trading-school fit) — this pass is chrome/pixels only, no new features, no chart-logic changes, no React.*
