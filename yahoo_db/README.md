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

Only `yfinance`, `pandas` and `requests` are required. `pyarrow` is optional
and only needed for Parquet export.

## Quick start

```bash
# 1. create the database
python -m yahoo_db init

# 2. build the ticker universe (~13k US symbols in about a minute)
python -m yahoo_db universe --sources sec,nasdaq,static,seeds

# 3. go deep — crawl Yahoo's own lookup index for delisted and foreign symbols
python -m yahoo_db universe --sources yahoo-lookup --lookup-depth 2

# 4. download full price history for everything that is due
python -m yahoo_db download

# 5. see where you are
python -m yahoo_db status

# 6. audit what you actually got
python -m yahoo_db verify
```

Step 4 is resumable. Interrupt it whenever you like — every symbol's outcome
is written to `fetch_log` as it completes, and the next run picks up from
there. Run it on a schedule and it becomes an incremental daily updater.

## Where the tickers come from

| Source         | Roughly | What it gives you |
|----------------|---------|-------------------|
| `nasdaq`       | ~12k + ~30k funds | Every symbol traded on a US venue today, from the Nasdaq Trader symbol directory: stocks, ETFs, preferreds, warrants, units, mutual funds. |
| `sec`          | ~10k    | Every SEC registrant with a ticker — including companies that have stopped trading but are still filing. |
| `yahoo-lookup` | 10k–100k+ | A brute-force crawl of Yahoo's own lookup index (`A`, `AA`, … `ZZ` × equity/etf/fund/index/future). **This is the one that reaches delisted symbols**, because Yahoo keeps answering for tickers that stopped trading years ago. |
| `static`       | ~330    | Indices, continuous futures, FX pairs and crypto pairs — no listing directory carries these. |
| `seeds`        | you decide | Anything you drop in `yahoo_db/seeds/` as CSV or a plain symbol list. See the README there. |

Sources are additive and the universe **never shrinks**. A symbol that falls
out of the exchange directories keeps its row, keeps its history, and gets
marked `delisted` once its bars go stale. Run the tool for a year and the
archive covers every ticker that traded during that year, whether or not it
still exists.

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

1. Yahoo answering "no data found / may be delisted" for a symbol marks it
   delisted immediately.
2. After each download pass, any symbol whose newest bar is more than
   `--stale-days` (default 30) behind the newest bar *in the whole database*
   is marked delisted. Comparing against the market's own last trading day is
   what keeps weekends and holidays from sweeping the entire universe.
3. A `status` column in a seed file, or a filename containing `delisted`,
   marks symbols up front.

Delisted is sticky: a later source listing the symbol again will not silently
resurrect it. Delisted symbols are also fetched only once — their history is
final — which is what keeps a 100k-symbol universe practical to refresh daily.

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
--types EQUITY,ETF       only these quote types
--skip-delisted          leave dead symbols alone entirely
--force                  ignore the refresh window and the failure backoff
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
python -m unittest tests.test_yahoo_db -v
python -m unittest tests.test_yahoo_db_quality -v
```

102 tests, no network: the lookup crawl takes an injected fetcher (including
one that raises `KeyboardInterrupt` where a real Ctrl-C would land), the
SEC/Nasdaq parsers run on fixture text, the downloader runs against a stubbed
`yf.download`, and the `verify` checks run against bars written straight into a
temporary database.

## Legal note

This uses Yahoo Finance's public endpoints, which have no official API or
redistribution license. Fine for personal research; check Yahoo's terms before
building anything you plan to redistribute or sell.
