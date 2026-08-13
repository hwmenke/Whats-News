# Seed files

Anything you drop in this directory joins the ticker universe on the next
`python -m yahoo_db universe --sources seeds`.

This is the escape hatch for symbol lists no API will hand you: historical
index constituents, a broker's delisted-securities export, an old watchlist, a
list of tickers scraped out of 2009 filings. The more you put here, the deeper
the archive reaches into companies that no longer trade.

## Accepted formats

`.txt` / `.csv` / `.tsv`. Either one symbol per line:

```
AAPL
MSFT
BRK.B
```

or a table with a header row:

```csv
symbol,name,status
ENRN,Enron Corp,delisted
AAPL,Apple Inc.,active
```

Recognised symbol columns: `symbol`, `ticker`, `act symbol`, `nasdaq symbol`,
`code`. Optional columns: `name`/`security name`/`company`, `status`
(`active` / `delisted` / `unknown`), `exchange`, `quote_type`/`type`.

## Conventions

* A file with `delisted` in its name marks every symbol in it as delisted
  unless a `status` column says otherwise.
* Symbols are normalised to Yahoo's spelling on the way in, so `BRK.B` and
  `BRK-B` both land as `BRK-B`.
* Lines starting with `#` in a plain list file are ignored.
* Duplicates across files are harmless — the universe is a set.

## What is here already

`delisted_notable.csv` — a starter list of well-known US tickers that stopped
trading (bankruptcies, buyouts, mergers). It is a bootstrap, not a census: the
real depth comes from the `yahoo-lookup` source and from your own exports.

Whether Yahoo still serves history for any given dead symbol is Yahoo's call,
not ours. Symbols it no longer answers for are recorded in the universe,
marked `delisted`, and skipped on later runs — they cost one request, once.
