# 📊 FinDash - Financial Dashboard

A professional-grade financial dashboard built with a Python (Flask) backend and a modern HTML/JS frontend. It features real-time data fetching from Yahoo Finance, persistent storage in SQLite, and interactive technical analysis charts.

## 🚀 Quick Start (For your friend)

Follow these steps to get the dashboard running on your machine:

### 1. Clone or Download the Code
If you have the folder, just open your terminal in that folder.

### 2. Install Dependencies
Ensure you have Python 3 installed, then run:
```bash
python3 -m pip install -r requirements.txt
```

### 3. Start the Server
Run the following command to start the backend:
```bash
python3 app.py
```

### 4. Open the Dashboard
Open your web browser and go to:
👉 **[http://localhost:8050](http://localhost:8050)**

---

## 🛠️ Features
- **Real-time Data**: Fetch OHLCV data for any ticker symbol via `yfinance`.
- **Interactive Charts**: Powered by TradingView's Lightweight Charts.
- **Technical Analysis**: SMA, EMA, Bollinger Bands, RSI, MACD, and Volume.
- **Daily & Weekly Views**: Toggle between daily and weekly timeframes.
- **Persistent Storage**: All data is saved locally in an SQLite database.
- **Social Trends Radar**: Surfaces the words moving most across Google Trends, TikTok, Twitter/X and Instagram over the last 30 days, then maps each trend to the listed stocks that are the cleanest *pure plays* on that theme (ranked by purity × momentum).

### 🔥 Social Trends — live data sources
The Social Trends tab works out of the box on **curated sample data** so the UI
is always populated. To pull live feeds, run locally (full network) and provide
keys via environment variables — each source falls back to sample data when its
key/integration is absent, and the UI labels every source `LIVE` or `SEED`:

| Source        | How it goes live                                              |
|---------------|---------------------------------------------------------------|
| Google Trends | Automatic via `pytrends` (no key needed) when reachable       |
| TikTok        | `TIKTOK_API_KEY` + an integration in `social_trends._fetch_keyed` |
| Twitter / X   | `TWITTER_BEARER_TOKEN` + integration (X trends API is paid)   |
| Instagram     | `INSTAGRAM_API_KEY` + integration                             |

The trend → ticker knowledge base lives in `social_trends.THEME_MAP` — edit it
to add themes, tickers, or tune the `purity` scores.

## 📁 Project Structure
- `app.py`: Flask REST API server.
- `database.py`: SQLite database manager.
- `data_fetcher.py`: Yahoo Finance data downloader.
- `indicators.py`: Technical analysis engine.
- `index.html`: Main dashboard UI.
- `styles/main.css`: Premium styling.
- `scripts/app.js`: Frontend application logic.
- `scripts/charts.js`: Chart rendering logic.

---
*Built with ❤️ for financial analysis.*
