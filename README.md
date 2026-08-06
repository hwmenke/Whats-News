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

## 📁 Project Structure
- `app.py`: Flask REST API server.
- `database.py`: SQLite database manager.
- `data_fetcher.py`: Yahoo Finance data downloader.
- `indicators.py`: Technical analysis engine.
- `index.html`: Main dashboard UI.
- `styles/main.css`: Premium styling.
- `scripts/app.js`: Frontend application logic.
- `scripts/charts.js`: Chart rendering logic.
- `yahoo_db/`: Standalone bulk data archiver (separate app, see below).

---

## 🗄️ Bulk data archiver (`yahoo_db`)

A separate, self-contained app that downloads Yahoo Finance history for as
many tickers as possible — listed **and delisted** — into its own SQLite
database. It shares no code or database with the dashboard above.

```bash
python3 -m pip install -r requirements-yahoo-db.txt
python3 -m yahoo_db init
python3 -m yahoo_db universe --sources sec,nasdaq,static,seeds
python3 -m yahoo_db download
python3 -m yahoo_db status
```

Full documentation: [`yahoo_db/README.md`](yahoo_db/README.md)

---
*Built with ❤️ for financial analysis.*
