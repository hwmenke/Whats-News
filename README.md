# FinDash - Financial Dashboard

A professional-grade financial dashboard built with a Python (Flask) backend and a vanilla HTML/JS frontend. Fetches OHLCV data from Yahoo Finance, stores it locally in SQLite, and offers a wide range of swing-trading and quantitative analysis tools.

## Quick Start

### Requirements
- Python 3.10 or later
- Internet connection (for Yahoo Finance data)

### 1. Clone the repository

```bash
git clone https://github.com/hwmenke/Whats-News.git
cd Whats-News
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the server

```bash
python3 app.py
```

### 5. Open the dashboard

Navigate to **http://localhost:8050** in your browser.

---

## Features

### Terminal Shell
- **Ticker tape**: scrolling live strip of watchlist quotes under the top bar (click to jump to a symbol; hover to pause)
- **Status bar**: connection state, New York clock with NYSE session (PRE / OPEN / POST / CLOSED + countdown), market regime, risk pedal, watchlist size, data freshness
- **Watchlist sidebar**: per-symbol price, daily change, and 20-bar sparkline with skeleton loading
- **Quote board**: monospace tabular price header with OHLCV strip and 52-week range bar
- **Keyboard-first**: command palette (Ctrl+K), numbered tab hotkeys shown on the tab bar, J/K symbol navigation

### Data
- **Watchlist**: Add/remove tickers; auto-fetch daily + weekly OHLCV from Yahoo Finance
- **Data Manager**: Bulk-fetch full history for curated ticker lists (12 categories, ~220 symbols); Finviz screener import (paste a screener URL — public scrape or Elite CSV export with auth token)
- **Price Ratios**: Create synthetic A/B ratio series from any two fetched tickers
- **Data Quality**: Automated OHLC-logic, gap, spike, and stale-close checks

### Charts & Analysis
- **Main Chart**: Dual-panel daily/weekly candlesticks with KAMA, Bollinger Bands, volume
- **Multi-TF**: Multi-timeframe chart grid for one symbol
- **Compare**: Overlay several symbols' normalized performance
- **Statistics**: Return distributions, volatility, Sharpe, drawdown, win-rate
- **Adaptive Trend**: Multi-horizon KAMA/ADMA trend system with regime states, ratchet bands, and parameter optimizer
- **Swirligram**: RSI phase-space charts with buy-setup signal scoring (daily + weekly)
- **Seasonality**: Day-of-week, monthly, and quarterly return heatmaps
- **Momentum**: Jegadeesh-Titman momentum composite with z-score ranking across watchlist
- **Market Regime**: 5-state classifier (BULL STRONG / BULL / CHOP / BEAR / CRASH) with forward-return statistics per regime

### Scanning & Workflow
- **Scanner**: Jeff Sun setup scanner — actionable swing setups with opportunity scores, regime gating, earnings proximity, and a focus pipeline board
- **Sector**: Sector heatmap of the watchlist
- **Market Dashboard**: Risk pedal (green/yellow/red posture from regime + breadth + index extension + SPY up-streak), watchlist breadth with RSP/SPY and QQQE/QQQ equal-weight ratios, symbol strength ranking, focus pipeline (Back Burner → Watchlist → Stalk → Focus → Active), entry planner (trigger/stop/R-per-share with hard-rule + pocket-pivot/dry-up flags), EOD screens (high-ADR, pullback, parabolic, recent IPO), market diary, daily + weekly checklists
- **Morning Routine**: One-click daily workflow — refresh data, regime check, Jeff scan, breadth, signals — with configurable components
- **Settings**: Enable/disable and reorder routine components; CSV exports

### Trading
- **Journal**: Trade log with R-multiples, setup tags, thesis, T+3 day tracking, auto-computed MAE/MFE excursion, auto-captured entry context (regime/RVOL/LoD), open-position management hints (shave >2R, T+3 breakeven, 10-MA exit prep, 8× ATR partials), max-3-per-day overtrading guard, and post-trade review (grade, mistakes, lesson)
- **Analytics**: R-distribution scorecard, 100-trade expectancy review, performance by setup type and review grade, hard-rule compliance slicing, mistake frequency
- **Risk Calc**: R-based position sizer with 3-stop strategy breakdown, liquidity cap vs avg dollar volume, and journal handoff
- **Portfolio Backtest**: Multi-asset portfolio backtest with vol-target, risk-parity, and equal-weight sizing
- **Process**: Trading process checklists and rules

### News
- **News**: Per-symbol headlines with sentiment
- **Calendar**: Macro & earnings calendar
- **Daily Edge**: Auto-generated daily newsletter from your watchlist data

---

## Project Structure

### Backend (Python)

| File / Directory | Role |
|-----------------|------|
| `app.py` | Flask REST API server — entry point |
| `api/` | Domain blueprints: `symbols_meta`, `alerts`, `market`, `trade`, `news_routes`, `swing` |
| `database.py` | SQLite manager (WAL mode, upsert) |
| `data_fetcher.py` | Yahoo Finance downloader; daily + weekly storage; ratio series |
| `data_quality.py` | OHLC integrity, gap, spike, stale-close validation |
| `indicator_cache.py` | Thread-safe LRU cache with version-based invalidation |
| `ta_core.py` | Canonical TA primitives: KAMA (numba-JIT), RSI, Bollinger, MACD, CCI |
| `indicators.py` | Full indicator suite for the main chart |
| `stats.py` | Summary statistics and KAMA analysis |
| `adaptive_trend.py` | Multi-horizon adaptive trend system + grid optimizer |
| `scanner.py` | Multi-timeframe scanner with heatmap output |
| `jeff_scanner.py` | Jeff Sun swing-setup scanner with opportunity scoring |
| `swing_core.py` | Swing-trading core: setup detection, regime gate, R-multiples |
| `portfolio_backtest.py` | Multi-asset portfolio backtest with dynamic sizing |
| `strategy_tester.py` | Vectorised backtest engine (used by portfolio_backtest) |
| `market_regime.py` | 5-state market regime classifier |
| `momentum_ranker.py` | Jegadeesh-Titman momentum composite ranker |
| `seasonality.py` | Day-of-week, monthly, quarterly seasonality |
| `newsletter_engine.py` | Daily Edge newsletter generator |
| `swirligram.py` | RSI phase-space swirligram with buy-setup scoring |
| `ticker_lists.py` | Curated ticker library (~220 tickers, 12 categories) |
| `errors.py` | Structured API error taxonomy |

### Frontend (JavaScript)

All modules live in `scripts/` — one module per tab plus shared helpers
(`app.js`, `chart_helpers.js`, `persistence.js`, `shortcuts.js`,
`command_palette.js`).

---

## Running Tests

```bash
pytest
```

Tests cover TA primitives, API validation, error taxonomy, the backtest
engine, and the swing/scanner modules.

---

## Environment

The server binds to port `8050` by default. Override with:

```bash
PORT=8080 python3 app.py
```

Data is stored in `finance.db` (SQLite, created automatically on first run).
