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

### Bulk universe archive (2000+ US index tickers)

One-time registration + archive, then a short daily refresh:

```bash
export DATA_SERVICE_MODE=embedded

# 1) Register S&P 500/400/600, Nasdaq-100, Russell 2000 (~1500–2500 unique)
python3 scripts/bulk_archive.py --sync-indices all

# 2) Full history (run once; hours — use delay 1.5+ to avoid Yahoo throttling)
python3 scripts/bulk_archive.py --archive --start 2000-01-01 --delay 1.5

# 3) After each close — only last few days per symbol
python3 scripts/bulk_archive.py --refresh --overlap-days 5 --delay 0.8
```

**In the UI:** open **Data** → sync indices → **Archive history** → later **Daily refresh**. Universe tickers stay tagged `univ:*` and are hidden from the sidebar until you **Promote to desk** (+ Desk on setup scan or ↑ on sidebar).

**Scanners:** **Scanner** tab → **Setup scanner** (EP, Darvas, breakout queue, RSI) on the full archive; metrics heatmap below scans the same stored data. Charts, Adaptive Trend, KNN, and Statistics work on any symbol with stored OHLCV.


## Project layout (developers)

| Path | Purpose |
|------|---------|
| `app.py` | Analysis dashboard (charts, scanner, news, PM Desk) |
| `data_service/` | Optional data plane (SQLite + Yahoo fetches) |
| `data_client.py` / `market_data.py` | Embedded or HTTP access to watchlist/OHLCV |
| `database.py` / `data_fetcher.py` | SQLite + Yahoo downloads |
| `index_universe.py` / `scripts/bulk_archive.py` | US index lists + bulk archive CLI |
| `setup_scanner.py` | Setup families (Qullamaggie, Minervini, Stockbee, Darvas, Brandt, Stage) |
| `ta_templates.py` | Mechanical Minervini Trend Template + Stockbee EP/RE/EMA |
| `methodology_badges.py` | Compact badges (KQ/MM/SB4/SBW/SB9/DB/ON/2A/2B) for watchlists |
| `.cursor/agents/` | TA specialist agent prompts (Minervini, Stockbee, …) |
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
