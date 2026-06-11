# FinDash - Financial Dashboard

A professional-grade financial dashboard built with a Python (Flask) backend and a vanilla HTML/JS frontend. Fetches OHLCV data from Yahoo Finance, stores it locally in SQLite, and offers a wide range of quantitative analysis tools.

## Quick Start

### Requirements
- Python 3.10 or later
- Internet connection (for Yahoo Finance data)

### 1. Clone the repository

```bash
git clone https://github.com/hwmenke/Whats-News.git /Users/hmenke/code/trading
cd /Users/hmenke/code/trading
git checkout claude/add-pycaret-integration-CcGEp
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

> PyCaret pulls in a large set of ML libraries (~500 MB). This step takes a few minutes on first run.

### 4. Start the server

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

### Quant Lab (flagship)
Bloomberg-terminal-style quant screen for any symbol — one request, four models,
two composite dials (**VALUATION** cheap↔rich, **DIRECTION** lower↔higher) plus a
conviction read from cross-model agreement:

- **Fair Value**: 126-bar log-linear trend channel (fair value ± 1σ/2σ bands) blended
  with KAMA-50 gap, 52-week range position, RSI percentile and slow Bollinger %B into
  a single valuation score — and an *edge curve* showing the realised forward 1-week
  return per historical valuation bucket (the current bucket highlighted)
- **KNN Analog Forecast**: the current bar's 10-feature state vector matched against
  all history; the 25 nearest non-overlapping analogs project a 21-bar percentile fan
  (P10/25/50/75/90) + analog spaghetti, with P(up) and median moves at 1w/2w/1m
- **CTA Trend Strategy**: 3-speed EWMAC (8/32, 16/64, 32/128), vol-normalised forecasts
  through the AHL response curve, vol-targeted position, costed backtest vs buy & hold
- **Exhaustion**: blow-off/capitulation composite (TD-style count, fast RSI, ATR
  stretch percentile, signed volume climax, 10-bar extension) with an event study of
  past ±70 readings vs the unconditional base rate
- **AutoML**: on-demand PyCaret classifier comparison (leaderboard, prediction,
  feature importance) straight from the header strip

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
| `quant_lab.py` | Quant Lab engine — fair-value channel, KNN fan forecast, CTA strategy, exhaustion, composite dials |
| `pycaret_model.py` | PyCaret AutoML — trains & compares classifiers to predict UP/DOWN direction |
| `swirligram.py` | RSI phase-space swirligram with buy-setup scoring |
| `ticker_lists.py` | Curated ticker library (~220 tickers, 12 categories) |
| `errors.py` | Structured API error taxonomy |

### Frontend (JavaScript)

All modules live in `scripts/`:

`app.js` · `charts.js` · `chart_helpers.js` · `data_manager.js` · `factor_model.js` · `market_regime.js` · `momentum_ranker.js` · `persistence.js` · `portfolio.js` · `quant_lab.js` · `regression.js` · `scanner.js` · `seasonality.js` · `shortcuts.js` · `strategy_tester.js` · `swirligram.js` · `trend_chart.js`

---

## Quant Lab Endpoint

`GET /api/quant-lab/<symbol>`

Runs the full quant stack (fair value, KNN fan, CTA, exhaustion, composite dials)
for a symbol with ≥ 300 daily bars. All maths is vectorised — typical response
time is ~100 ms. Powers the **⚡ Quant Lab** tab.

```bash
curl -X POST http://localhost:8050/api/fetch/AAPL
curl "http://localhost:8050/api/quant-lab/AAPL"
```

---

## PyCaret AutoML Endpoint

`GET /api/pycaret/<symbol>?horizon=5&n_models=5`

Trains and compares up to 7 classifiers (LR, DT, RF, ET, NB, Ridge, LDA) on 17
ATR-normalised technical features (same feature set as KNN Forecast) and returns
a directional prediction for the most-recent bar.

| Parameter | Default | Options |
|-----------|---------|---------|
| `horizon` | `5` | `1`, `5`, `10`, `20` (trading days) |
| `n_models` | `5` | `1`–`7` |

**Example:**
```bash
# Fetch data first, then predict
curl -X POST http://localhost:8050/api/fetch/AAPL
curl "http://localhost:8050/api/pycaret/AAPL?horizon=5&n_models=5"
```

Response includes: `prediction` (UP/DOWN), `confidence`, model `leaderboard`, `feature_importance`, and `current_features`.

---

## Running Tests

```bash
pytest
```

46 tests covering TA primitives, API validation, error taxonomy, backtest engine, and the Quant Lab models.

---

## Environment

The server binds to port `8050` by default. Override with:

```bash
PORT=8080 python3 app.py
```

Data is stored in `finance.db` (SQLite, created automatically on first run).
