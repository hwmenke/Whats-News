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

### Going wider

```bash
# every quote type Yahoo indexes, three-character prefixes, worldwide regions
python -m yahoo_db universe --sources yahoo-lookup \
    --lookup-depth 3 \
    --lookup-types equity,etf,mutualfund,index,future,currency,cryptocurrency \
    --lookup-regions US,GB,DE,FR,CA,AU,JP,HK,IN,BR
```

Depth 3 is ~48k prefixes per type per region, so this is an overnight job —
`--lookup-sleep` sets the pace. Everything is merged, so it is safe to stop
and resume.

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
meta       key PK, value
```

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
| `export` | Dump tables to CSV or Parquet. |
| `vacuum` | `ANALYZE` + `VACUUM`. |

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
```

## Tests

```bash
python -m unittest tests.test_yahoo_db tests.test_yahoo_db_sources -v
```

No network anywhere: the lookup crawl takes an injected fetcher, every source
parser runs on fixture text, and the downloader runs against a stubbed
`yf.download`.

## Legal note

This uses Yahoo Finance's public endpoints, which have no official API or
redistribution license. Fine for personal research; check Yahoo's terms before
building anything you plan to redistribute or sell.
