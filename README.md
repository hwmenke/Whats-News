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

### First visit

1. In the left sidebar, type `AAPL` and click **+**
2. Click **AAPL** in the list (use **Refresh All** if the chart is empty)
3. Open **News** in the top bar for headlines across your watchlist

### Manual start (if you prefer)

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Need Python 3? Check with `python3 --version`.

---

## What you get

- Watchlist with Yahoo Finance price history (stored in SQLite)
- Interactive charts and technical tools
- Watchlist-wide news page with source + time on every story
- Scanner / stats / backtest tabs for deeper analysis

## Project layout (developers)

| Path | Purpose |
|------|---------|
| `app.py` | Flask server (dashboard + APIs) |
| `database.py` / `data_fetcher.py` | SQLite + Yahoo downloads |
| `index.html` / `news.html` | UI |
| `scripts/` | Frontend JS |
| `tests/` | Unit tests (no live network) |
| `start.sh` | One-command launcher |
| `SUGGESTIONS.md` | Ideas for future improvements |

```bash
make test    # or: python3 -m unittest discover tests
```

---

*For Caspar and friends — keep it local, keep headlines real.*
