# The Daily Brief — news page

An editorial news + markets front page ("News Desk Pro" design), served by the Flask app at **`/news`**.

## Views
- **Top** — lead story with annotated yield-curve chart, index strip, Data Desk charts, sector small multiples, story clusters, and "The Tape" rail.
- **Markets** — FinViz-style treemap heatmap (1D/1W/1M/YTD), top movers, sector performance bars, a sortable/filterable screener, and a ticker detail drawer (click any tile or row).

## How it's built
- Static React prototype compiled in the browser: `vendor/` holds React 18.3.1, ReactDOM, and Babel standalone (vendored locally — no CDN needed), and the `*.jsx` files are loaded via Babel at runtime.
- `index.html` is the page shell and the source of truth for all styling (design tokens in `:root`).
- File map: `pro-app.jsx` (shell + nav/view routing), `pro-charts.jsx` (Data Desk charts), `pro-heatmap.jsx` (treemap), `pro-screener.jsx` (screener/movers/drawer), `pro-markets-data.jsx` (stock universe + change model), `data.jsx` (story clusters + sources), `tweaks-panel.jsx` (design tweak panel).

## Data status
All figures are **illustrative placeholder data** baked into the JSX files (per the original design handoff). Next step for live data: replace `data.jsx` (story clusters) with a feed pipeline and `pro-markets-data.jsx` (quotes/fundamentals) with real quotes — the Flask backend's `yfinance` fetcher is a natural source for the latter.
