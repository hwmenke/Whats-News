# Board column + measure registry

JSON (`registry.json`) is the machine source. YAML (`registry.yaml`) is the
human twin emitted by `python3 board_registry.py`.

Canonical boards: `market_moves`, `engine` (alias of `engine_setup`),
`setup`, `macro` (alias of `engine_sigma`). Used by Market Moves and ENGINE:

- ordered columns
- visibility + locked identity columns
- measure id → formula / payload key
- format
- heat scale

## APIs

- `GET /api/boards/registry`
- `columns[]` is also stamped on `GET /api/market-moves`, `/api/engine/board`,
  `/api/engine/sigma`, `/api/engine/maps`

Formulas stay locked in `market_moves.py` / `equity_engine.py`. This registry
does not compute PX, z, D, or TMAC*.

## Customize (web first)

Dash: Customize on Market Moves + ENGINE Setup / Sigma / Maps.
Prefs: `localStorage['whats-news-desk-prefs'].boardColumns`.

## Visual v4.1

Font C: Public Sans + Inter + JetBrains Mono. Ink `#111`. Soft R/G heat. Mint ≤1
OPPORTUNITY fill. No borders — zebra/fills only. Neon / cream / v3 mint
theater discarded. Market Moves stays utilitarian red/green z heat.

## Flutter path

1. `WhatsNewsApi.getBoardRegistry()` → `GET /api/boards/registry`
   (or use `columns` on the board payload).
2. Persist the same `boardColumns` map under SharedPreferences key
   `whats-news-desk-prefs` (already shared with desk prefs).
3. Apply order + hidden in `ScansPage._movesSlivers` and `_setupEngineSlivers`.
4. Locked `name` / `symbol` / ENGINE stay visible. Blank cells stay `—`.
