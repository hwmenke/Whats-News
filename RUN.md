# Run — Caspar Mac (usable today)

Checkout: `/Users/hmenke/Whats-News-pr60`  
Branch: `cursor/iphone-whats-news-client-15b5` (PR 60). Do not merge.

Public Yahoo + local `finance.db` only. No keys. Paper P&L — not live.

## 1. API (leave running)

```bash
cd /Users/hmenke/Whats-News-pr60
chmod +x start.sh          # once
./start.sh
```

Wait until it prints the dashboard URL. Confirm:

```bash
curl -s http://127.0.0.1:8050/api/health
```

Need `"schema_ok": true`. Open http://localhost:8050 if you want the web desk.

## 2. iPhone Sim (second terminal)

```bash
open -a Simulator
cd /Users/hmenke/Whats-News-pr60/mobile
flutter pub get
flutter run -d "iPhone 16"
```

Xcode / Flutter missing? See `mobile/README.md`. Gear → server `http://127.0.0.1:8050`.

## 3. Seed a sleeve once

Empty cards are missing Yahoo bars — not a fake print.

- Watchlist → open **Macro** (or Watchlist **gear** → Universe)
- Tap **Seed Core 50** *or* one sleeve chip (Indexes / Big Tech / Sectors)
- Wait for the fetch. Yahoo may throttle; retry the same tap later. Once is enough.

Do **not** Register S&P / archive unless you want a slow univ:* dump.

## 4. Daily tabs

| Tab | What you should see |
|-----|---------------------|
| **Watchlist** | Seeded names + day%. Tap a symbol → Chart |
| **Scans** | Pattern / RSI-C / Maps from stored bars. Empty = no bars yet |
| **P&L** | TODAY’S P&L + chart axes from stored daily marks + Equities/Longs/Shorts/Net + day%. Empty book → Upload a Fidelity Positions CSV (`Symbol` + `Quantity`) |
| **Risk** | Ranked %VaR when the book is marked and thick enough. Thin book stays blank — not invented |

Same four surfaces on web: Watchlist sidebar, Scans, P&L, Risk.

## Stop

API: `Ctrl+C` in the `./start.sh` terminal. Sim: quit Simulator.
