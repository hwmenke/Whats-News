# Whats-News

Local watchlist app: charts + analysis + **real** Yahoo Finance headlines.
No API keys. Data stays on your computer in `finance.db`.

## Quick start (easiest)

In a terminal, go into this folder, then run:

```bash
chmod +x start.sh   # only needed once
./start.sh
```

When it says the server is running, open your browser:

- **Dashboard:** http://localhost:8050  
- **News:** http://localhost:8050/news  

Stop with `Ctrl+C`.

`start.sh` uses **embedded** data mode (one process). For the optional two-process layout, see below.

### First visit

1. In the left sidebar, type `AAPL` and click **+**
2. Click **AAPL** in the list (use **Refresh All** if the chart is empty)
3. Open **News** in the top bar for headlines across your watchlist

### Manual start (if you prefer)

```bash
python3 -m pip install -r requirements.txt
export DATA_SERVICE_MODE=embedded
python3 app.py
```

### Optional: separate data service

```bash
# Terminal 1 — data plane (default :8051)
python3 -m data_service.app

# Terminal 2 — analysis UI (default :8050)
unset DATA_SERVICE_MODE   # or DATA_SERVICE_MODE=http
python3 app.py
```

- Data service UI → http://localhost:8051  
- Set `DATA_SERVICE_URL` if the data service is not on `http://127.0.0.1:8051`

Need Python 3? Check with `python3 --version`.

---

## What you get

- Watchlist with Yahoo Finance price history (stored in SQLite)
- Interactive charts and technical tools
- Watchlist-wide news page with source + time on every story
- Scanner / stats / backtest tabs for deeper analysis
- PM Desk: book tape, RS ranks, regime heatmap, ATR sizing

### Scaling the watchlist

SQLite stays the datastore. The DB layer is set up so hundreds of tickers stay practical:

- **WAL journal** + busy timeout so refreshes/scanner can run alongside the UI
- **Bulk upserts** for OHLCV (vectorized, not row-by-row)
- **Indexes** on `(symbol, freq, date)` and watchlist grouping
- **Bulk add**: `POST /api/symbols` with `{"symbols": ["AAPL", "MSFT", ...]}`
- **Stats / optimize**: `GET /api/db/stats`, `POST /api/db/optimize` after large imports

`finance.db` (and WAL sidecars) stay gitignored — never commit the database file.

## Project layout (developers)

| Path | Purpose |
|------|---------|
| `app.py` | Analysis dashboard (charts, scanner, news, PM Desk) |
| `data_service/` | Optional data plane (SQLite + Yahoo fetches) |
| `data_client.py` / `market_data.py` | Embedded or HTTP access to watchlist/OHLCV |
| `database.py` / `data_fetcher.py` | SQLite + Yahoo downloads |
| `index.html` / `news.html` | UI |
| `scripts/` | Frontend JS |
| `tests/` | Unit tests (no live network) |
| `start.sh` | One-command launcher (embedded mode) |
| `SUGGESTIONS.md` | Ideas for future improvements |
| `PM_REVIEW.md` / `METHODOLOGY_REVIEW.md` / `VISUAL_REVIEW.md` | Desk review notes |

```bash
DATA_SERVICE_MODE=embedded make test
# or: DATA_SERVICE_MODE=embedded python3 -m unittest discover tests
```

---

*For Caspar and friends — keep it local, keep headlines real.*
