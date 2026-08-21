# 📰 Whats-News - Financial Dashboard & Watchlist News

A professional-grade financial dashboard built with a Python (Flask) backend and a modern HTML/JS frontend. Features real-time data fetching from Yahoo Finance, persistent storage in SQLite, interactive technical analysis charts, and real-time news feeds for your watchlist.

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
- **Watchlist News**: Real news headlines for your watchlist symbols from Yahoo Finance.
- **Interactive Charts**: Powered by TradingView's Lightweight Charts.
- **Technical Analysis**: SMA, EMA, Bollinger Bands, RSI, MACD, and Volume.
- **Daily & Weekly Views**: Toggle between daily and weekly timeframes.
- **Persistent Storage**: All data is saved locally in an SQLite database.

### News Feed

Access the news page at `/news` to see real headlines for all symbols in your watchlist. The news feed:
- Fetches real headlines from Yahoo Finance using the yfinance API
- Displays source, publish time, and article summary for each story
- Deduplicates articles that appear for multiple symbols
- Shows honest status messages when news is unavailable or fetch fails
- Requires no API keys or external configuration

> **Note**: The news feed shows real data from Yahoo Finance. PR #5 contains an unrelated React prototype with placeholder data and should not be confused with this implementation.

## 📁 Project Structure
- `app.py`: Flask REST API server (dashboard + news endpoints).
- `database.py`: SQLite database manager.
- `data_fetcher.py`: Yahoo Finance data downloader.
- `indicators.py`: Technical analysis engine.
- `index.html`: Main dashboard UI.
- `news.html`: News feed page.
- `styles/main.css`: Premium styling.
- `scripts/app.js`: Frontend application logic.
- `scripts/charts.js`: Chart rendering logic.
- `tests/`: Unit tests with mocked yfinance (no network calls).

## 🧪 Testing

Run tests with:
```bash
python3 -m unittest discover tests
```

Tests use mocked yfinance responses to avoid network calls in CI/CD.

---
*Built with ❤️ for financial analysis and staying informed.*
