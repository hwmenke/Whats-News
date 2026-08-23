# 📰 Whats-News — Dashboard + Watchlist News

Local financial toolkit with two processes:

1. **Data service** (`data_service`) — owns the SQLite watchlist + OHLCV store and Yahoo Finance downloads  
2. **Analysis app** (`app.py`) — charts, indicators, scanner, news; pulls bars **on the fly** from the data service

## Quick Start

```bash
python3 -m pip install -r requirements.txt

# Terminal 1 — data plane (default :8051)
python3 -m data_service.app

# Terminal 2 — analysis UI (default :8050)
python3 app.py
```

Open:
- Analysis dashboard → http://localhost:8050  
- Data service UI → http://localhost:8051  
- Watchlist news → http://localhost:8050/news  

### Single-process / tests

```bash
export DATA_SERVICE_MODE=embedded   # analysis talks to local database.py (no HTTP)
python3 app.py
```

## Architecture

```
Browser  →  Analysis app :8050  →  Data service :8051  →  finance.db + yfinance
                 │                      │
         indicators/stats/         symbols, fetch,
         scanner/news              OHLCV, batch import
```

- Analysis modules (`indicators`, `stats`, `scanner`, …) read through `market_data` → `data_client`.
- The dashboard still exposes the same `/api/symbols`, `/api/ohlcv`, `/api/data-manager/*` routes; they proxy to the data service so the existing UI keeps working.
- Set `DATA_SERVICE_URL` if the data service is not on `http://127.0.0.1:8051`.

## Features
- **Real-time Data**: OHLCV via `yfinance`, stored by the data service.
- **Watchlist News**: Real Yahoo Finance headlines for watchlist symbols.
- **Interactive Charts**: TradingView Lightweight Charts.
- **Technical Analysis**: SMA, EMA, Bollinger, RSI, MACD, volume, adaptive trend, scanner.
- **Data Manager**: Batch import curated ticker lists (runs on the data service; UI proxied from :8050).

> News shows real Yahoo data — not the placeholder magazine from PR #5.

## Project Structure
- `data_service/` — Data management Flask app + small ops UI
- `data_client.py` / `market_data.py` — HTTP (or embedded) access for analysis
- `app.py` — Analysis dashboard
- `database.py` / `data_fetcher.py` — SQLite + Yahoo download (owned by data service)
- `index.html` / `news.html` / `styles/` / `scripts/` — frontend
- `tests/` — unittest suite (`DATA_SERVICE_MODE=embedded`, no live network)

## Testing

```bash
DATA_SERVICE_MODE=embedded python3 -m unittest discover tests
```

---
*Built for financial analysis and staying informed.*
