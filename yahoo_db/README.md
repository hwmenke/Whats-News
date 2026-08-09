# yahoo_db

A standalone app that downloads Yahoo Finance data for as many tickers as
possible — **listed and delisted** — and stores it in a SQLite database.

It shares nothing with the dashboard in the repository root: its own database
file, its own schema, its own CLI. Copy the `yahoo_db/` directory somewhere
else and it still runs.

## Install

```bash
pip install -r requirements-yahoo-db.txt     # from the repo root
```

Or install the package itself, which also puts a `yahoo-db` command on your
PATH:

```bash
pip install .            # from the repo root
pip install '.[parquet]' # …with Parquet export
```

Only `yfinance`, `pandas` and `requests` are required. `pyarrow` is optional
and only needed for Parquet export.

`yahoo-db <command>` and `python -m yahoo_db <command>` are the same program;
every example below works with either.

## Quick start

```bash
# 1. create the database
python -m yahoo_db init

# 2. build the ticker universe (~45k symbols in about a minute)
python -m yahoo_db universe --sources sec,nasdaq,wikipedia,static,seeds

# 3. add the OTC venues (~12k more, the heaviest delisting churn there is)
python -m yahoo_db universe --sources otc

# 4. go deep — crawl Yahoo's own lookup index for delisted and foreign symbols
python -m yahoo_db universe --sources yahoo-lookup --lookup-depth 2

# 5. download full price history for everything that is due
python -m yahoo_db download

# 6. see where you are
python -m yahoo_db status

# 6. audit what you actually got
python -m yahoo_db verify
```

Step 5 is resumable. Interrupt it whenever you like — every symbol's outcome
is written to `fetch_log` as it completes, and the next run picks up from
there. Run it on a schedule and it becomes an incremental daily updater.

## Where the tickers come from

| Source         | Roughly | What it gives you |
|----------------|---------|-------------------|
| `nasdaq`       | ~12k + ~30k funds | Every symbol traded on a US venue today, from the Nasdaq Trader symbol directory: stocks, ETFs, preferreds, warrants, units, mutual funds. |
| `sec`          | ~10k + ~30k funds | Every SEC registrant with a ticker — including companies that have stopped trading but are still filing — plus every mutual fund share class EDGAR knows a ticker for. |
| `otc`          | ~12k    | Everything quoted on OTCQX / OTCQB / OTCID / Pink. No other source here reaches these, and they delist faster than anything on an exchange. |
| `wikipedia`    | ~2.5k, ~800 of them dead | Current *and former* members of the S&P 500/400/600, Nasdaq-100, Dow, Russell 1000, FTSE 100, DAX, CAC 40 and S&P/TSX 60. The removals are the point: a ticker dropped from an index after an acquisition or a bankruptcy is a dead symbol with a full price history behind it. |
| `yahoo-lookup` | 10k–100k+ | A brute-force crawl of Yahoo's own lookup index (`A`, `AA`, … `ZZ` × equity/etf/fund/index/future). **This is the one that reaches deepest into delisted symbols**, because Yahoo keeps answering for tickers that stopped trading years ago. |
| `static`       | ~465    | Indices, continuous futures, FX pairs, spot metals and crypto pairs — no listing directory carries these. |
| `seeds`        | you decide | Anything you drop in `yahoo_db/seeds/` as CSV or a plain symbol list. See the README there. |

`sec`, `nasdaq`, `wikipedia`, `static` and `seeds` are the default set: a
handful of file downloads, a minute end to end. `otc` and `yahoo-lookup` are
paged crawls that take minutes to hours, so you ask for them explicitly.

Sources are additive and the universe **never shrinks**. A symbol that falls
out of the exchange directories keeps its row, keeps its history, and gets
marked `delisted` once its bars go stale. Run the tool for a year and the
archive covers every ticker that traded during that year, whether or not it
still exists.

### Recipe: US stocks only, 2010 to today, delisted included

The common case, and the one with the sharpest trap in it.

```bash
# 1. Universe. `otc` and the lookup crawl are where the dead tickers live, so
#    they are not optional for this goal.
python -m yahoo_db universe --sources sec,nasdaq,otc,wikipedia,seeds
python -m yahoo_db universe --sources yahoo-lookup --lookup-types equity

# 2. Prices. --exclude-types, NOT --types.
python -m yahoo_db download \
    --start 2010-01-01 \
    --exclude-types ETF,MUTUALFUND,CURRENCY,CRYPTOCURRENCY,INDEX,FUTURE \
    --sleep 2 --batch-size 40 -v
```

**Use `--exclude-types`, not `--types EQUITY`.** Several sources — including
the lookup crawl, which is where most delisted symbols come from — leave
`quote_type` blank. `--types EQUITY` keeps only symbols positively identified
as equities and therefore drops exactly the delisted tail you are trying to
collect. `--exclude-types` removes what you know you do not want and keeps
everything unclassified.

Once `profiles` has run, Yahoo's own `quoteType` is stored per symbol, so you
can tighten the filter later if you want.

Ballpark for this scope: ~10–12k symbols including the delisted tail, ~4,100
bars each, so **≈50M rows and ~6 GB** (measured at 114 bytes/row on this
schema), and a few hours for the first pass.

### Going wider

```bash
# every quote type Yahoo indexes, three-character prefixes, worldwide regions
python -m yahoo_db universe --sources yahoo-lookup \
    --lookup-depth 3 \
    --lookup-types equity,etf,mutualfund,index,future,currency,cryptocurrency \
    --lookup-regions US,GB,DE,FR,CA,AU,JP,HK,IN,BR
```

Depth 3 is ~48k prefixes per type per region, so this is an overnight job —
`--lookup-sleep` sets the pace.

**The crawl resumes.** Every `(region, quote type, prefix)` triple is written to
`lookup_progress` once its pagination has finished, *after* its symbols are in
the database. Stop the job with Ctrl-C and the next run skips straight past
everything that completed:

```
$ python -m yahoo_db universe --sources yahoo-lookup --lookup-depth 3
resuming lookup crawl — skipping 12,431 prefixes finished in the last 14 days
  lookup 41,900/48,600 prefixes (12,431 resumed)  73,914 symbols
```

* a triple that failed, timed out, or was half-paginated is **not** recorded,
  so the next run crawls it again;
* completion goes stale — the universe changes — so a triple finished more than
  `--lookup-resume-days` (default 14) ago is crawled again anyway;
* `--lookup-restart` throws the checkpoints away and starts from `A`, narrowed
  to the regions and types you are crawling.

Resuming is the default; there is no flag to turn it on.

## How delisting is decided

The hard part is that Yahoo answers a dead ticker and a bad afternoon the same
way: an empty response. yfinance hides the underlying exception by default, so
a 500, a rate limit and a genuinely dead company all arrive as an empty frame.
Believing that frame means "delisted" lets one outage permanently bury every
symbol it touched, which is why the rules are deliberately slow to condemn:

1. Exceptions are un-hidden and classified. A *prices-missing* error is
   evidence about the symbol; a rate limit or a timeout is evidence about
   Yahoo, and never counts against the ticker.
2. A symbol with no stored bars must come back empty on
   `--delist-after-empty` (default 3) **separate runs** before it is written
   off. The counter resets on any non-empty outcome.
3. A whole batch coming back empty is treated as throttling, not as fifty
   simultaneous delistings — the run backs off instead of firing fifty more
   requests at a wall.
4. After a *full* download pass, any symbol whose newest bar is more than
   `--stale-days` (default 30) behind the newest bar *in the whole database*
   is marked delisted. Comparing against the market's own last trading day is
   what keeps weekends and holidays from sweeping the universe. A run over an
   explicit `--symbols` / `--limit` / `--types` subset never sweeps.
5. A `status` column in a seed file, or a filename containing `delisted`,
   marks symbols up front.

Delisting is **reversible by evidence**: bars arriving for a symbol we had
written off revive it, and delisted symbols are re-checked every
`--delisted-recheck-days` (default 30) rather than never — so a symbol buried
during an outage comes back on its own. A source merely re-listing a symbol is
not evidence and will not resurrect it.

Not re-fetching dead symbols daily is what keeps a 100k-symbol universe
practical to refresh.

### Splits

Yahoo restates a symbol's **entire** price history when it splits, so an
incremental fetch of the last few days would leave a permanent cliff in the
stored series. When a split appears that we have not seen before, the symbol is
flagged and its whole history is re-downloaded on the next pass. `--force`
does the same thing on demand.

## Point-in-time index membership

The `wikipedia` source records not just who is in an index but **when each
symbol joined and left**. That turns the archive into something you can ask a
question no free price feed answers on its own:

```bash
python -m yahoo_db universe --sources wikipedia

python -m yahoo_db constituents                       # what is stored
python -m yahoo_db constituents --index "S&P 500"     # members today
python -m yahoo_db constituents --index "S&P 500" --on 2015-06-30
```

```
S&P 500 on 2015-06-30: 501 members (312 changes rewound)
```

### Why this matters more than it looks

Backtesting today's S&P 500 over 2010–2020 is the classic way to manufacture a
strategy that works beautifully in testing and fails live. Today's members are
the companies that *survived and grew into the index*; the ones that were in it
in 2015 and then collapsed are missing entirely. Selecting on the outcome is
the bias, and it flatters returns badly.

With membership history you test the 2015 index against 2015 prices, delisted
constituents included — which is what the `otc`, `seeds` and `yahoo-lookup`
sources are collecting for you.

```python
from yahoo_db.db import Store

store = Store("data/market.db")
members = store.constituents_on("S&P 500", "2015-06-30")
for symbol in members["symbols"]:
    bars = store.get_ohlcv_df(symbol, "1d")   # includes companies since dead
```

### How it is reconstructed, and where it stops being true

Membership is rewound, not stored per day: start from today's member list and
undo every change dated after the target — a symbol added since then comes out,
a symbol removed since then goes back in. A change dated exactly on the target
counts as in effect, since index changes take effect at that day's open.

That means the answer is only as good as the change history. Ask for a date
before the oldest change on the page and the result is simply the membership as
of that oldest change — so the reconstruction says so rather than handing you a
confident wrong list:

```
WARNING: change history only goes back to 2000-01-02; a date before that
cannot be reconstructed and this list is not point-in-time.
```

`constituents` with no `--index` prints each index's coverage span, which is
the honest boundary of what you can backtest.

Two caveats worth keeping in mind: the tables are hand-maintained by Wikipedia
editors, so they are good but not audited, and a symbol that was recycled to a
different company later will resolve to whatever Yahoo serves under that ticker
today.

## Plugging it into the What's News dashboard

`whats_news.py` is a drop-in replacement for the dashboard's `database.py` and
`data_fetcher.py`, backed by the archive. Change two lines in `app.py`:

```python
# import database as db
# import data_fetcher as fetcher
from yahoo_db import whats_news as db
from yahoo_db import whats_news as fetcher
```

That is the whole integration. Every function the dashboard calls keeps its
name, parameters and return shape — there is a test that imports the real
`database.py` and `data_fetcher.py` and asserts the signatures still match, so
this cannot drift silently. Point it at an archive with `YDB_DB_PATH`, or call
`whats_news.configure(db_path=...)` before the first request.

Nothing about the charts, indicators or scanner changes: `freq` still means
`daily`/`weekly`, and `get_ohlcv` still returns the same row dicts, oldest
first.

**Weekly and monthly bars are resampled from daily**, so the timeframe toggle
works against a daily-only archive with no second download pass. If you do run
`download --interval 1wk`, the stored bars are used instead.

Two behaviours differ on purpose:

* **The sidebar shows a watchlist, not the universe.** The dashboard renders
  every row `list_symbols()` returns, and the archive holds tens of thousands
  of symbols. So the adapter keeps a small `watchlist` table and lists that.
  `add_symbol()` adds to it (and registers the symbol in the universe if it is
  new), and `search_symbols(query)` is there for finding things to add — that
  is how you reach the rest of the archive from the UI. Wiring it to a route
  is three lines:

  ```python
  @app.route("/api/search")
  def search():
      return jsonify(db.search_symbols(request.args.get("q", ""), limit=25))
  ```

* **`remove_symbol()` does not delete price history.** In the dashboard's own
  database that dropped the symbol's bars, which was fine for two years of
  refetchable data. Here those bars may be fifteen years of a delisted company
  Yahoo will never serve again, so removal takes the symbol off the watchlist
  and leaves the archive alone.

The dashboard's "fetch" buttons still work — `fetch_and_store()` and
`fetch_full_history()` run the archive's downloader for that one symbol, so a
refresh from the UI and a refresh from the CLI go through the same code and
land in the same place.

## Schema

```
tickers    symbol PK, name, quote_type, exchange, exchange_name, status,
           sources, first_seen, last_seen, delisted_at, has_data, notes
prices     (symbol, interval, date) PK, open, high, low, close, adj_close, volume
dividends  (symbol, date) PK, amount
splits     (symbol, date) PK, ratio
profiles   symbol PK, long_name, sector, industry, country, currency,
           market_cap, shares_outstanding, first_trade_date, raw_json, fetched_at
fetch_log  symbol, interval, status, rows, first_date, last_date, error, fetched_at
index_constituents  (index_name, symbol) PK, updated_at        -- membership today
index_changes       (index_name, symbol, action, date) PK      -- joins/departures
lookup_progress (region, quote_type, prefix) PK, symbols, completed_at
meta       key PK, value
```

`lookup_progress` arrived with schema version 2 and is what makes the lookup
crawl resumable. Every table is created with `IF NOT EXISTS` and every command
runs the schema step first, so an older database picks it up on its next run —
there is no migration to perform.

Prices are stored **unadjusted with `adj_close` alongside** (`auto_adjust=False`),
so the raw print and the adjusted series are both available and splits do not
silently rewrite what you already stored. `dividends` and `splits` come down in
the same request as the bars.

Query it like any other SQLite database:

```sql
SELECT date, close FROM prices
WHERE symbol = 'AAPL' AND interval = '1d'
ORDER BY date;

SELECT symbol, name, delisted_at FROM tickers
WHERE status = 'delisted' AND has_data = 1
ORDER BY delisted_at DESC;
```

## Commands

| Command | What it does |
|---|---|
| `init` | Create the database and schema. |
| `universe` | Run discovery sources and merge their symbols in. |
| `download` | Download price history for everything due. |
| `profiles` | Download company/fund metadata (one request per symbol). |
| `status` | Row counts, date range, breakdown by type and source. |
| `symbols` | List symbols in the universe (`--status delisted --with-data`). |
| `constituents` | Index membership, today or as it stood on a past date. |
| `mark-delisted` | Re-run the stale sweep on its own. |
| `verify` | Audit the stored data and print a quality report. Never hits the network. |
| `export` | Dump tables to CSV or Parquet. |
| `vacuum` | `ANALYZE` + `VACUUM`. |

Useful flags on `universe`:

```
--sources yahoo-lookup      which discovery sources to run
--lookup-depth 3            prefix length (1=A..Z, 2=AA..ZZ, 3=AAA..999)
--lookup-types equity,etf   quote types to crawl
--lookup-regions US,GB      Yahoo regions to crawl
--lookup-sleep 0.4          seconds between lookup requests
--lookup-resume-days 14     re-crawl a prefix finished more than N days ago
--lookup-restart            forget the checkpoints and crawl everything again
```

Useful flags on `download`:

```
--symbols AAPL,MSFT      just these
--symbols-file list.txt  one symbol per line
--interval 1wk           1d (default), 1wk or 1mo
--limit 500              stop after N symbols
--batch-size 50          symbols per yf.download call
--workers 8              threads inside each call
--sleep 1.0              seconds between batches — raise this if throttled
--start 2000-01-01       earliest date for first-time downloads (default: max)
--types EQUITY,ETF       only these quote types (drops unknown types)
--exclude-types ETF      skip these types, keep unknown ones — prefer this
                         when you want the delisted tail
--skip-delisted          leave dead symbols alone entirely
--force                  ignore the refresh window and the failure backoff,
                         and re-download full history rather than the tail
--delist-after-empty 3   empty runs before a symbol is written off
--delisted-recheck-days 30   how often dead symbols are looked at again
```

Every flag also has a `YDB_*` environment variable — see `config.py`.

## Checking the data

```bash
python -m yahoo_db verify                 # the report
python -m yahoo_db verify --json          # the same thing, machine-readable
python -m yahoo_db verify --limit 25      # more offenders per check
python -m yahoo_db verify --fix           # repair what is safe to repair
```

`verify` reads and reports; it never makes a request, so it is safe to run
beside a download that is still going. Every check gives a count and a bounded
sample of the symbols behind it:

| Check | What it means |
|---|---|
| `no_prices` | Universe symbols with no bars at all, split by status. Delisted ones are usually tickers Yahoo never carried; active/unknown ones are the download backlog. |
| `price_gaps` | Holes of **five or more weekday sessions** in a daily series. US exchanges have never closed for five straight weekdays in the modern era — the longest is four (9/11) — so holidays stay quiet and only real holes show. Trading halts and genuinely illiquid symbols do land here, deliberately. |
| `high_below_low`, `close_outside_range`, `non_positive_price`, `negative_volume` | Bars that contradict their own arithmetic. |
| `zero_volume_runs` | Five or more consecutive zero-volume bars — but only for symbols that report volume somewhere. An index or FX pair carries volume 0 on every bar by convention, which is not a defect. |
| `malformed_dates`, `duplicate_dates`, `future_dates` | The primary key already rules out true duplicate rows and there is no stored ordering to be wrong, so what these check is the way a date string can lie: a value that is not plain `YYYY-MM-DD` sorts wrongly and lets one trading day in twice under two spellings, and a date past today means a bad parse upstream. |
| `split_suspects` | A day-over-day `close` ratio within 4% of 2, 3, 1.5, 10 or their inverses with no `splits` row within four days. Prices are stored unadjusted, so a real split should have both. A suspect list, not a verdict — the sample carries both closes so you can judge a penny stock that simply doubled. |
| `stale_active` | Still marked `active`, but the newest bar is more than `--stale-days` behind **the newest bar in the database** (not behind today, so a weekend or an unrefreshed archive does not condemn the universe). |
| `fetch_log` | Attempts by outcome, the most common error messages, and the symbols whose *most recent* attempt failed. |

Thresholds: `--gap-days`, `--zero-volume-run`, `--split-tolerance`,
`--stale-days`, `--interval`.

### `--fix`

`--fix` is deliberately small. It only rewrites columns that are *derived* from
rows already in the database, and it never writes or deletes a price:

* `has_data` and `delisted_at` on `tickers` are caches of "does this symbol have
  bars, and what is the newest one" — the `prices` table is the authority, so
  re-deriving them cannot lose information;
* the stale sweep, which is exactly what `mark-delisted` does and what every
  download run already finishes with.

Re-queueing symbols for download is **not** auto-fixed. `fetch_log` is
append-only evidence and `symbols_to_fetch` reads it as "how many times have we
tried, and when", so writing a row makes a symbol *less* due rather than more,
and deleting rows would throw away the record of why it failed. Use the report
instead:

```bash
python -m yahoo_db verify --json --limit 500 > report.json
python -m yahoo_db download --force --symbols AAPL,MSFT
```

## Rate limits

Yahoo's endpoints are undocumented and throttled. The defaults (50 symbols per
request, 8 threads, 1s between batches) are deliberately unhurried; a full
first pass over tens of thousands of symbols with full history takes hours,
and that is the expected shape of the job. If you start seeing rate-limit
errors in the log, raise `--sleep` and lower `--batch-size` — the run resumes
where it left off either way, so nothing is lost.

The downloader backs off exponentially on failures, retries rate-limited
batches four times harder, and gives every symbol that comes back empty in a
batch one solo retry before believing it is dead.

## Scheduling

```cron
# refresh the universe weekly, top up prices every weekday evening
30 6 * * 0  cd /path/to/repo && python -m yahoo_db universe -v >> ydb.log 2>&1
0 22 * * 1-5 cd /path/to/repo && python -m yahoo_db download -v >> ydb.log 2>&1
# audit on Sunday, after the universe refresh
0 8 * * 0   cd /path/to/repo && python -m yahoo_db verify >> ydb-quality.log 2>&1
```

A deep lookup crawl works well on a schedule too: give it a nightly window and
let it resume, one bite at a time, until the checkpoints cover every prefix.

## Tests

```bash
python -m unittest tests.test_yahoo_db \
                  tests.test_yahoo_db_sources \
                  tests.test_yahoo_db_quality
```

No network anywhere: the lookup crawl takes an injected fetcher (including one
that raises `KeyboardInterrupt` where a real Ctrl-C would land), every source
parser runs on fixture text, the downloader runs against a stubbed
`yf.download`, and the `verify` checks run against bars written straight into a
temporary database.

## Legal note

This uses Yahoo Finance's public endpoints, which have no official API or
redistribution license. Fine for personal research; check Yahoo's terms before
building anything you plan to redistribute or sell.
