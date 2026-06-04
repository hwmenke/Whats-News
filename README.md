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

### 🔥 Social Trends — what's in the tab
- **Trending Words** — biggest movers with sparklines, momentum bars, source chips, and direction. Each card carries a **phase** (`building / peaking / fading / flat`) plus anomaly badges (🆕 *new today* · 🔥 *accelerating* · 💤 *fading fast*) computed against persistent SQLite snapshots. The dominant source per term is marked with a ▸ arrow. Hover a sparkline to see day-by-day values; click a term to drill into its 90-day history.
- **Pure-Play Ideas** — ranked stock table with sortable columns and a **catch-up read**: each idea cross-references the trend's heat against the stock's own 20-day price move (from stored data), badging it 🚀 *Trend hot · stock cold*, ✅ *Already moved*, or ❄️ *Fading*. Toggle **🚀 Catch-up only** to surface trends the stock hasn't run on yet, or **★ Watchlist only** to filter to your existing names. Click any theme name for a drill-down modal with the full cohort.
- **Search box** — filters both panels (terms / tickers / themes) live.
- **One-click add** — add a single ticker, **+ Theme** to add every pure play for a theme as a tagged watchlist group, or per-row **Fetch** to pull OHLCV for a single no-data row.
- **Auto-prime prices** — first time you open the tab, the server kicks a background OHLCV sweep for the top ~20 pure plays so catch-up is populated without you doing anything. Status appears in the toolbar.
- **Always-visible banner** — a top-movers strip in the header (refreshes every 5 min) jumps you straight into a trend or ticker from any tab.
- **Reverse view** — when you open any ticker's chart, themes that ticker plays into show as chips next to the symbol name.
- **Fast & bookmarkable** — the trend sweep is cached server-side (10 min) and snapshots persist to SQLite; tabs are bookmarkable (`#social`) and the app reopens on your last tab. The **⟳ Scan Trends** button forces a live re-fetch.
- **Installable PWA** — add to home screen on iOS/Android (`manifest.webmanifest` + a tiny offline shell SW) so the dashboard opens like a native app.

### 🔥 Social Trends — live data sources
The Social Trends tab works out of the box on **curated sample data** so the UI
is always populated. To pull live feeds, set the appropriate env var; each
source falls back to sample data when its key/integration is absent, and the UI
labels every source `LIVE` or `SEED`:

| Source        | Env var                                | Notes                                                       |
|---------------|----------------------------------------|-------------------------------------------------------------|
| Google Trends | *(none — auto via `pytrends`)*         | Free; rate-limited; works when the host can reach Google    |
| Twitter / X   | `TWITTER_BEARER_TOKEN`                 | v2 `/2/trends/by/woeid`; paid tier required                 |
| TikTok        | `APIFY_TOKEN` (+ `APIFY_TIKTOK_ACTOR`) | Apify Creative Center actor; cheapest realistic option      |
| Instagram     | *(no viable API)*                      | Seed-only — add an Apify hashtag scraper if you really need |

The trend → ticker knowledge base lives in **`themes.json`** — edit it to add
themes, tickers, or tune the `purity` scores. The app **hot-reloads** the file
on each request (no restart), and the linter catches typos:

```bash
python3 scripts/check_themes.py    # reports duplicate keywords, bad purity, etc.
```

You can also POST `/api/social-trends/reload-themes` to force-reload immediately.

## 🐳 Run with Docker

```bash
docker compose up -d --build
# Dashboard:  http://localhost:8050
# Data dir:   ./data  (SQLite DB persists here)
```

Set `DASHBOARD_PASSWORD` in `docker-compose.yml` to enable HTTP basic auth
(strongly recommended before exposing the dashboard beyond localhost).

## 🌐 Reach it from your phone — Cloudflare Tunnel

The dashboard is a single-user local Flask app, but you can put it behind a
free Cloudflare Tunnel and reach it from anywhere:

```bash
# 1. Turn on basic auth before exposing it!
export DASHBOARD_PASSWORD=$(openssl rand -hex 16)
# 2. Run the app (locally or via Docker)
python3 app.py
# 3. In another shell, start the tunnel
cloudflared tunnel --url http://localhost:8050
```

Cloudflare prints a `*.trycloudflare.com` URL — open it on your phone, log in
with `admin` / your password. Install to home screen via the browser menu and
you get a PWA-style app icon courtesy of `manifest.webmanifest`.

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
