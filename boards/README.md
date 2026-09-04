# Board column + measure registry

JSON (`registry.json`) is the machine source. YAML (`registry.yaml`) is the
human twin emitted by `python3 board_registry.py`.

Used by Market Moves and ENGINE:

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

## Visual HOLD

Neon Command/Setup/Macro comps are **rejected** — not the final desk.
`styles/theme.css` is a face/heat token hook only. Dedicated UI polish
waits on a revised Ex Ante × 538 VISUAL_SYSTEM via CoS. ENGINE math
and this registry stay.

## Flutter path

1. `WhatsNewsApi.getBoardRegistry()` → `GET /api/boards/registry`
   (or use `columns` on the board payload).
2. Persist the same `boardColumns` map under SharedPreferences key
   `whats-news-desk-prefs` (already shared with desk prefs).
3. Apply order + hidden in `ScansPage._movesSlivers` and `_setupEngineSlivers`.
4. Locked `name` / `symbol` / ENGINE stay visible. Blank cells stay `—`.
