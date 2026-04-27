# FinDash - Financial Dashboard

A professional-grade financial dashboard built with a Python (Flask) backend and a vanilla HTML/JS frontend. Fetches OHLCV data from Yahoo Finance, stores it locally in SQLite, and offers a wide range of quantitative analysis tools.

## Quick Start

### Requirements
- Python 3.10 or later
- Internet connection (for Yahoo Finance data)

### 1. Clone the repository

```bash
git clone <repo-url>
cd Whats-News
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the server

```bash
python3 app.py
```

### 4. Open the dashboard

Navigate to **http://localhost:8050** in your browser.

---

## Features

### Data
- **Watchlist**: Add/remove tickers; auto-fetch daily + weekly OHLCV from Yahoo Finance
- **Data Manager**: Bulk-fetch full history for curated ticker lists (12 categories, ~220 symbols)
- **Price Ratios**: Create synthetic A/B ratio series from any two fetched tickers
- **Data Quality**: Automated OHLC-logic, gap, spike, and stale-close checks

### Charts & Analysis
- **Main Chart**: Candlestick with SMA, EMA, Bollinger Bands, RSI, MACD, Volume overlays
- **Adaptive Trend**: Multi-horizon KAMA/ADMA trend system with regime states, ratchet bands, and parameter optimizer
- **Swirligram**: RSI phase-space charts with buy-setup signal scoring (daily + weekly)
- **Scanner**: Multi-timeframe heatmap (daily/weekly/monthly) across all watchlist symbols

### Strategy & Portfolio
- **Strategy Tester**: Visual drag-and-drop backtester with a condition DSL (KAMA cross, RSI, MACD, Bollinger Bands, trend regime), walk-forward optimization, bootstrap confidence intervals, and Monte Carlo simulation
- **Portfolio Backtest**: Multi-asset portfolio backtest with vol-target, risk-parity, and equal-weight sizing

### Analytics
- **Market Regime**: 5-state classifier (BULL STRONG / BULL / CHOP / BEAR / CRASH) with forward-return statistics per regime
- **Momentum Ranker**: Jegadeesh-Titman momentum composite with z-score ranking across watchlist
- **Seasonality**: Day-of-week, monthly, and quarterly return heatmaps
- **Factor Model**: Fama-French 5-factor rolling OLS for every watchlist symbol (alpha, beta, R², attribution)
- **KNN Forecast**: 17-feature weighted K-Nearest-Neighbor pattern-recognition forecast across 4 horizons (5/20/63/126 bars)
- **Macro Regression**: OLS regression of any symbol's forward returns on 24 macro factors and cross-asset spread features

---

## Project Structure

### Backend (Python)

| File | Role |
|------|------|
| `app.py` | Flask REST API server — entry point |
| `database.py` | SQLite manager (WAL mode, upsert) |
| `data_fetcher.py` | Yahoo Finance downloader; daily + weekly storage; ratio series |
| `data_quality.py` | OHLC integrity, gap, spike, stale-close validation |
| `indicator_cache.py` | Thread-safe LRU cache with version-based invalidation |
| `ta_core.py` | Canonical TA primitives: KAMA (numba-JIT), RSI, Bollinger, MACD, CCI |
| `indicators.py` | Full indicator suite for the main chart |
| `stats.py` | Summary statistics and KAMA analysis |
| `adaptive_trend.py` | Multi-horizon adaptive trend system + grid optimizer |
| `scanner.py` | Multi-timeframe scanner with heatmap output |
| `strategy_tester.py` | Vectorised backtest engine, walk-forward, bootstrap CI, Monte Carlo |
| `portfolio_backtest.py` | Multi-asset portfolio backtest with dynamic sizing |
| `market_regime.py` | 5-state market regime classifier |
| `momentum_ranker.py` | Jegadeesh-Titman momentum composite ranker |
| `seasonality.py` | Day-of-week, monthly, quarterly seasonality |
| `factor_model.py` | Cross-sectional 5-factor OLS model for all watchlist symbols |
| `factor_attribution.py` | Per-strategy factor attribution using Fama-French factors |
| `regression.py` | Macro-factor OLS regression (24 factors, pure numpy) |
| `knn_forecast.py` | Weighted KNN pattern-recognition forecast (17 features, 4 horizons) |
| `swirligram.py` | RSI phase-space swirligram with buy-setup scoring |
| `ticker_lists.py` | Curated ticker library (~220 tickers, 12 categories) |
| `errors.py` | Structured API error taxonomy |

### Frontend (JavaScript)

All modules live in `scripts/`:

`app.js` · `charts.js` · `chart_helpers.js` · `data_manager.js` · `factor_model.js` · `knn_forecast.js` · `market_regime.js` · `momentum_ranker.js` · `persistence.js` · `portfolio.js` · `regression.js` · `scanner.js` · `seasonality.js` · `shortcuts.js` · `strategy_tester.js` · `swirligram.js` · `trend_chart.js`

---

## Running Tests

```bash
pytest
```

38 tests covering TA primitives, API validation, error taxonomy, and backtest engine.

---

## Environment

The server binds to port `8050` by default. Override with:

```bash
PORT=8080 python3 app.py
```

Data is stored in `finance.db` (SQLite, created automatically on first run).
