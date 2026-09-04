# Whats-News iPhone client

iPhone-first Flutter app for the same **Whats-News** product as the Dash
watchlist: desk symbols, Yahoo OHLCV candlesticks, and real Yahoo Finance
headlines. It talks HTTP to the Python data layer already in this repo
(`./start.sh` on `:8050`, or `python -m data_service.app` on `:8051`).

This is **not** a UIKit one-off. `lib/data/` is the shared client (models +
REST). Android and macOS targets are already in this Flutter project for later;
do not paste API keys. Paper / local only — no live trading.

The Linux cloud agent that added this **did not run the iOS Simulator** (no
Xcode on that VM). Caspar runs it on a Mac as below.

## On your Mac (Simulator)

1. Install [Flutter](https://docs.flutter.dev/get-started/install/macos)
   (stable) and Xcode, then once:

   ```bash
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   xcodebuild -runFirstLaunch
   open -a Simulator
   flutter doctor
   ```

2. In this repo, start the local Python API (same SQLite `finance.db`, no keys):

   ```bash
   ./start.sh
   ```

   `start.sh` (and the Flask app) always run `init_db` so `symbols` / `ohlcv`
   exist even if leftover `finance.db` is an empty file. Leave it running.
   Dashboard is http://localhost:8050 — the phone uses the same `/api/symbols`,
   `/api/ohlcv/<sym>`, `/api/news`, `/api/fetch/<sym>`.

   Confirm before Simulator: `curl -s http://127.0.0.1:8050/api/health` should
   show `"schema_ok": true`. An empty desk is fine; `"no such table"` is not.

3. In another terminal:

   ```bash
   cd mobile
   flutter pub get
   flutter run -d "iPhone 16"
   ```

   Or open `mobile/ios/Runner.xcworkspace` in Xcode, pick an iPhone simulator,
   Run. If CocoaPods asks: `cd ios && pod install`.

4. In the app, Watchlist → type `AAPL` → **+**. Chart tab → **Fetch from Yahoo**.
   News tab shows Yahoo headlines for the desk. Gear (Watchlist) sets the
   server URL. Simulator default is `http://127.0.0.1:8050`.

### Physical iPhone on Wi-Fi

Python must listen on the LAN:

```bash
HOST=0.0.0.0 ./start.sh
```

On the phone, gear → `http://<your-mac-lan-ip>:8050` (Settings → Wi-Fi → Mac
IP). HTTP on the LAN is allowed via `NSAllowsLocalNetworking` in Info.plist.

## Linux / CI (no Simulator)

```bash
cd mobile
flutter pub get
flutter test
flutter analyze
```

`flutter test` exercises the shared client against mock Flask JSON (watchlist,
OHLCV, Yahoo news, throttle). It is **not** an iOS Simulator run.

## Layout

| Path | Role |
|------|------|
| `lib/data/` | Shared HTTP client + models (Android/Mac reuse this) |
| `lib/ui/` | iPhone Cupertino UI (watchlist, candles, news) |
| `ios/` | Xcode project (`Runner.xcworkspace`) |
| `android/`, `macos/`, `web/` | Same app, later platforms |

No broker APIs. Yahoo via the Python process only.
