# Yahoo seed → fetch → score

Path: `docs/YAHOO_SEED.md`.

Public Yahoo/SQLite only. Seed registers names. Fetch writes `ohlcv`. Scans and ENGINE score **desk** names (`list_desk_symbols`). Archive `univ:*` is hidden from the desk.

## Paths

1. **Market Moves sleeves (Indexes / Big Tech / Sectors)**  
   `POST /api/market-moves/seed` then `POST /api/market-moves/fetch-core`  
   Web: Market Moves → Fetch Indexes + Big Tech + Sectors.  
   iPhone: Seed Core 50 / sleeve also calls `POST /api/desk/seed-fetch`.

2. **Scanner / desk universe**  
   `POST /api/universe/core50` or `POST /api/sleeves/<id>/seed` puts names on the desk.  
   Bars only after Fetch: `POST /api/fetch/<SYM>` or `POST /api/desk/seed-fetch`.  
   Core 50 seed alone does **not** download Yahoo.

3. **Archive (optional, slow)**  
   `POST /api/universe/sync` then `POST /api/universe/archive`.  
   `stored_n` can be >0 from archive while the desk is empty. Breadth must not say “Empty universe” in that case.

## Score

- `GET /api/scans/breadth?desk=1` and `GET /api/engine/*?desk=1` use the desk list.  
- Empty desk + `stored_n>0` → “Desk list empty — N names have stored bars.”  
- “Empty universe — no stored bars” only when **no** symbol in SQLite has ≥20 daily bars.

## Maps / Coil

Coil needs ~28 weekly bars (`coil_12 = r12/r26`). `POST /api/desk/seed-fetch` uses period `2y` and still fetches desk extras if Market Moves `fetch_core` throttles.

- Empty maps + `stored_n=0` → “Empty maps — seed a sleeve and Fetch Yahoo.”
- Empty maps + `stored_n>0` → “Desk maps empty — N names have stored bars. Refresh after Fetch.”
- iPhone: Seed Core 50 / sleeve calls seed-fetch then `reloadMapsAfterSeed()` so Scans → Maps is not a stale empty.

## iPhone empty vs Warnings hits

If Warnings has hits, stored bars exist. Breadth/Scans must use `stored_n` (and ENGINE ready) and must not show Empty-universe copy. Maps must not keep the seed-a-sleeve lie when `stored_n>0`.
