"""
cli.py - Command line for the Yahoo data downloader.

    python -m yahoo_db init
    python -m yahoo_db universe --sources sec,nasdaq,static,seeds
    python -m yahoo_db universe --sources yahoo-lookup --lookup-depth 2
    python -m yahoo_db download --limit 500
    python -m yahoo_db profiles --limit 200
    python -m yahoo_db status
    python -m yahoo_db verify --limit 25
    python -m yahoo_db export --table prices --format parquet --out ./out
"""

import argparse
import json
import logging
import sys
import time

from . import export as export_mod
from . import universe
from . import verify
from .config import load_config
from .db import Store, normalize_symbol
from .downloader import Downloader

logger = logging.getLogger("yahoo_db")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yahoo_db",
        description="Download Yahoo Finance data for as many tickers as "
                    "possible — listed and delisted — into a SQLite database.",
    )
    parser.add_argument("--db", dest="db_path", help="path to the SQLite file")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("-q", "--quiet", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database and its schema")

    p_uni = sub.add_parser("universe", help="discover tickers and merge them in")
    p_uni.add_argument("--sources",
                       help="comma list: sec,nasdaq,otc,wikipedia,seeds,static,"
                            "yahoo-lookup")
    p_uni.add_argument("--lookup-depth", type=int,
                       help="prefix length for the Yahoo lookup crawl (1=A..Z, 2=AA..ZZ)")
    p_uni.add_argument("--lookup-types", help="comma list: equity,etf,mutualfund,index,future")
    p_uni.add_argument("--lookup-regions", help="comma list of Yahoo regions, e.g. US,GB,DE")
    p_uni.add_argument("--lookup-sleep", type=float, help="seconds between lookup requests")
    p_uni.add_argument("--lookup-resume-days", type=int,
                       help="re-crawl a prefix finished more than N days ago "
                            "(default 14)")
    p_uni.add_argument("--lookup-restart", action="store_true", default=None,
                       help="forget the crawl checkpoints and start from 'A'")
    p_uni.add_argument("--seeds-dir", help="directory of seed CSV/TXT files")

    p_dl = sub.add_parser("download", help="download price history")
    p_dl.add_argument("--symbols", help="comma list; default = everything due")
    p_dl.add_argument("--symbols-file", help="file with one symbol per line")
    p_dl.add_argument("--interval", help="1d (default), 1wk or 1mo")
    p_dl.add_argument("--limit", type=int, help="stop after N symbols")
    p_dl.add_argument("--batch-size", type=int)
    p_dl.add_argument("--workers", type=int)
    p_dl.add_argument("--sleep", dest="sleep_between_batches", type=float,
                      help="seconds between batches")
    p_dl.add_argument("--start", dest="history_start",
                      help="earliest date for first-time downloads (default: max)")
    p_dl.add_argument("--refresh-after-hours", type=int,
                      help="re-download a symbol only if last success is older")
    p_dl.add_argument("--types", help="only these quote types, e.g. EQUITY,ETF "
                                      "(drops symbols whose type is unknown)")
    p_dl.add_argument("--exclude-types",
                      help="skip these quote types, e.g. ETF,MUTUALFUND. Keeps "
                           "symbols of unknown type, so prefer this over "
                           "--types when you want the delisted tail")
    p_dl.add_argument("--skip-delisted", action="store_true",
                      help="do not fetch symbols already marked delisted")
    p_dl.add_argument("--no-single-retry", action="store_true",
                      help="do not re-try empty symbols one by one")
    p_dl.add_argument("--force", action="store_true",
                      help="ignore the refresh window and the failure backoff, "
                           "and re-download full history rather than the tail")
    p_dl.add_argument("--delist-after-empty", type=int,
                      dest="delist_after_empty_fetches",
                      help="empty responses on separate runs before a symbol "
                           "is written off (default 3)")
    p_dl.add_argument("--delisted-recheck-days", type=int,
                      help="how often delisted symbols are looked at again "
                           "(default 30)")

    p_prof = sub.add_parser("profiles", help="download company/fund metadata")
    p_prof.add_argument("--symbols", help="comma list; default = everything with data")
    p_prof.add_argument("--limit", type=int)
    p_prof.add_argument("--refetch-days", type=int, default=30)

    p_stat = sub.add_parser("status", help="show database statistics")
    p_stat.add_argument("--interval", help="which interval to report on")
    p_stat.add_argument("--json", action="store_true")

    p_sym = sub.add_parser("symbols", help="list symbols in the universe")
    p_sym.add_argument("--status", choices=["active", "delisted", "unknown"])
    p_sym.add_argument("--with-data", action="store_true")
    p_sym.add_argument("--limit", type=int, default=50)

    p_mark = sub.add_parser("mark-delisted",
                            help="flag symbols whose newest bar has gone stale")
    p_mark.add_argument("--interval")
    p_mark.add_argument("--stale-days", type=int)

    p_ver = sub.add_parser("verify", help="audit what is stored (never hits the network)")
    p_ver.add_argument("--interval")
    p_ver.add_argument("--limit", type=int, default=10,
                       help="offending symbols shown per check (default 10)")
    p_ver.add_argument("--gap-days", type=int, default=verify.DEFAULT_GAP_WEEKDAYS,
                       help="weekday sessions missing before a hole is a gap")
    p_ver.add_argument("--zero-volume-run", type=int,
                       default=verify.DEFAULT_ZERO_VOLUME_RUN,
                       help="consecutive zero-volume bars before reporting")
    p_ver.add_argument("--split-tolerance", type=float,
                       default=verify.DEFAULT_SPLIT_TOLERANCE,
                       help="how close a close ratio must be to a split factor")
    p_ver.add_argument("--stale-days", type=int,
                       help="days behind the market's newest bar before stale")
    p_ver.add_argument("--json", action="store_true")
    p_ver.add_argument("--fix", action="store_true",
                       help="repair has_data/delisted_at/status; never touches prices")

    p_exp = sub.add_parser("export", help="dump tables to CSV or Parquet")
    p_exp.add_argument("--table", default="all",
                       help="tickers|prices|dividends|splits|profiles|fetch_log|all")
    p_exp.add_argument("--format", default="csv", choices=["csv", "parquet"])
    p_exp.add_argument("--out", default="./export")
    p_exp.add_argument("--interval")

    p_vac = sub.add_parser("vacuum", help="prune the fetch log, VACUUM + ANALYZE")
    p_vac.add_argument("--keep-log", type=int, default=5,
                       help="attempts to keep per symbol in fetch_log "
                            "(default 5; 0 disables pruning)")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args)

    cfg = load_config(
        db_path=getattr(args, "db_path", None),
        seeds_dir=getattr(args, "seeds_dir", None),
        interval=getattr(args, "interval", None),
        batch_size=getattr(args, "batch_size", None),
        workers=getattr(args, "workers", None),
        sleep_between_batches=getattr(args, "sleep_between_batches", None),
        history_start=getattr(args, "history_start", None),
        refresh_after_hours=getattr(args, "refresh_after_hours", None),
        stale_days=getattr(args, "stale_days", None),
        delist_after_empty_fetches=getattr(args, "delist_after_empty_fetches", None),
        delisted_recheck_days=getattr(args, "delisted_recheck_days", None),
        sources=_split(getattr(args, "sources", None)),
        lookup_types=_split(getattr(args, "lookup_types", None)),
        lookup_regions=_split(getattr(args, "lookup_regions", None)),
        lookup_depth=getattr(args, "lookup_depth", None),
        lookup_sleep=getattr(args, "lookup_sleep", None),
        lookup_resume_days=getattr(args, "lookup_resume_days", None),
        lookup_restart=getattr(args, "lookup_restart", None),
    )

    store = Store(cfg.db_path)
    store.init_schema()
    try:
        return COMMANDS[args.command](args, cfg, store)
    except KeyboardInterrupt:
        print("\ninterrupted — progress is saved, re-run to resume", file=sys.stderr)
        return 130
    finally:
        store.close()


# ── commands ───────────────────────────────────────────────────────────────────

def cmd_init(args, cfg, store) -> int:
    print(f"database ready at {cfg.db_path}")
    return 0


def cmd_universe(args, cfg, store) -> int:
    before = store.count_tickers()
    crawling = any(s.strip().lower() in universe.LOOKUP_ALIASES
                   for s in cfg.sources)
    if crawling:
        _print_crawl_resume_state(cfg, store)

    start = time.time()
    summary = universe.refresh(cfg, store, progress=_lookup_progress)
    after = store.count_tickers()

    print(f"\nuniverse refresh in {time.time() - start:.0f}s")
    for name, result in summary.items():
        if "error" in result:
            print(f"  {name:<14} FAILED: {result['error']}")
        else:
            print(f"  {name:<14} {result['found']:>7} found  "
                  f"{result['inserted']:>7} new  {result['updated']:>7} updated")
    print(f"  {'total':<14} {before} -> {after} symbols "
          f"(+{after - before})")
    if crawling:
        checkpointed = store.count_lookup_prefixes_done(
            cfg.lookup_regions, cfg.lookup_types, cfg.lookup_resume_days)
        print(f"  {'checkpoints':<14} {checkpointed:>7,} prefixes done — "
              f"re-run to continue where this stopped")
    return 0


def cmd_download(args, cfg, store) -> int:
    symbols = _resolve_symbols(args)
    downloader = Downloader(cfg, store)
    start = time.time()
    result = downloader.run(
        symbols=symbols,
        interval=cfg.interval,
        limit=args.limit,
        include_delisted=not args.skip_delisted,
        quote_types=_split(args.types),
        exclude_types=_split(args.exclude_types),
        single_retry=not args.no_single_retry,
        force=args.force,
        progress=_download_progress,
    )
    elapsed = time.time() - start
    print(f"\ndownload finished in {elapsed:.0f}s")
    for key in ("symbols", "ok", "empty", "error", "rows", "dividends", "splits",
                "marked_delisted", "marked_delisted_stale"):
        if result.get(key):
            print(f"  {key:<22} {result[key]:>10,}")
    return 0


def cmd_profiles(args, cfg, store) -> int:
    downloader = Downloader(cfg, store)
    result = downloader.fetch_profiles(
        symbols=_split(args.symbols),
        limit=args.limit,
        refetch_days=args.refetch_days,
        progress=_download_progress,
    )
    print("\nprofiles finished")
    for key in ("symbols", "profiles_ok", "profiles_empty", "profiles_error"):
        if result.get(key):
            print(f"  {key:<16} {result[key]:>10,}")
    return 0


def cmd_status(args, cfg, store) -> int:
    stats = store.stats(interval=cfg.interval)
    if args.json:
        print(json.dumps(stats, indent=2, default=str))
        return 0

    print(f"database        {stats['db_path']}  ({stats['db_size_mb']} MB)")
    print(f"interval        {cfg.interval}")
    print()
    print(f"tickers total   {stats['tickers_total']:>12,}")
    print(f"  active        {stats['tickers_active']:>12,}")
    print(f"  delisted      {stats['tickers_delisted']:>12,}")
    print(f"  unknown       {stats['tickers_unknown']:>12,}")
    print(f"  with data     {stats['tickers_with_data']:>12,}")
    print()
    print(f"price rows      {stats['price_rows']:>12,}")
    print(f"  symbols       {stats['symbols_with_prices']:>12,}")
    print(f"  date range    {stats['date_min']} .. {stats['date_max']}")
    print(f"dividends       {stats['dividend_rows']:>12,}")
    print(f"splits          {stats['split_rows']:>12,}")
    print(f"profiles        {stats['profiles']:>12,}")
    if stats["by_type"]:
        print("\nby quote type")
        for row in stats["by_type"]:
            print(f"  {row['quote_type']:<16} {row['n']:>10,}")
    if stats["by_source"]:
        print("\nby discovery source")
        for row in stats["by_source"]:
            print(f"  {(row['sources'] or '?'):<28} {row['n']:>10,}")
    return 0


def cmd_symbols(args, cfg, store) -> int:
    where, params = ["1=1"], []
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    if args.with_data:
        where.append("has_data = 1")
    sql = (f"SELECT symbol, name, quote_type, status, sources, delisted_at "
           f"FROM tickers WHERE {' AND '.join(where)} ORDER BY symbol LIMIT ?")
    params.append(args.limit)
    for row in store.conn.execute(sql, params).fetchall():
        print(f"{row['symbol']:<14} {(row['quote_type'] or ''):<14} "
              f"{row['status']:<9} {(row['delisted_at'] or ''):<11} "
              f"{(row['name'] or '')[:40]:<42} {row['sources']}")
    return 0


def cmd_mark_delisted(args, cfg, store) -> int:
    changed = store.mark_stale_as_delisted(cfg.interval, cfg.stale_days)
    print(f"marked {changed:,} symbols delisted "
          f"(no {cfg.interval} bar in the last {cfg.stale_days} days)")
    return 0


def cmd_verify(args, cfg, store) -> int:
    report = verify.run(
        store,
        interval=cfg.interval,
        limit=args.limit,
        gap_weekdays=args.gap_days,
        stale_days=cfg.stale_days,
        zero_volume_run=args.zero_volume_run,
        split_tolerance=args.split_tolerance,
    )
    # Fixes run after the audit so the report shows what was wrong, not what
    # survived the repair.
    if args.fix:
        report["fixes"] = verify.apply_fixes(store, cfg.interval, cfg.stale_days)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    _print_verify(report)
    return 0


def cmd_export(args, cfg, store) -> int:
    if args.table == "all":
        results = export_mod.export_all(store, args.out, fmt=args.format,
                                        interval=args.interval)
    else:
        results = [export_mod.export_table(store, args.table, args.out,
                                           fmt=args.format, interval=args.interval)]
    for result in results:
        print(f"{result['table']:<12} {result['rows']:>12,} rows -> {result['path']}")
    return 0


def cmd_vacuum(args, cfg, store) -> int:
    if args.keep_log:
        pruned = store.prune_fetch_log(args.keep_log)
        print(f"pruned {pruned:,} fetch_log rows "
              f"(kept the newest {args.keep_log} per symbol)")
    store.conn.execute("ANALYZE")
    store.conn.execute("VACUUM")
    print("vacuum + analyze done")
    return 0


COMMANDS = {
    "init": cmd_init,
    "universe": cmd_universe,
    "download": cmd_download,
    "profiles": cmd_profiles,
    "status": cmd_status,
    "symbols": cmd_symbols,
    "mark-delisted": cmd_mark_delisted,
    "verify": cmd_verify,
    "export": cmd_export,
    "vacuum": cmd_vacuum,
}


# ── helpers ────────────────────────────────────────────────────────────────────

def _setup_logging(args):
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    if args.quiet:
        level = logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # yfinance is chatty about every delisted symbol; that is our normal case.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _print_verify(report):
    totals = report["totals"]
    print(f"data quality    {report['db_path']}")
    print(f"interval        {report['interval']}   "
          f"market last bar {report['market_last_date'] or '-'}")
    print(f"tickers         {totals['tickers']:>12,}  "
          f"({totals['symbols_with_prices']:,} with prices, "
          f"{totals['price_rows']:,} bars, {totals['split_rows']:,} splits)")
    print()

    for name, check in report["checks"].items():
        mark = "ok " if check["count"] == 0 else "** "
        print(f"{mark}{name:<22} {check['count']:>12,}  {check['label']}")
        if check.get("skipped"):
            print(f"      skipped: {check['skipped']}")
            continue
        if not check["count"]:
            continue
        if check.get("note"):
            print(f"      note: {check['note']}")
        for key, label in (("symbols", "symbols affected"),
                           ("checked_candidates", "candidates examined")):
            if check.get(key):
                print(f"      {label}: {check[key]:,}")
        grouped = check.get("by_status") or {}
        for status, block in grouped.items():
            counts = ", ".join(f"{k}={v:,}" for k, v in block.items()
                               if isinstance(v, int))
            symbols = ", ".join(block.get("sample") or [])
            print(f"      {status:<10} {counts}"
                  + (f"   {symbols}" if symbols else ""))
        for row in check.get("top_errors") or []:
            print(f"      {row['n']:>6,}x  {(row['error'] or '')[:90]}")
        # Skip the flat sample when the per-status lines already carried it.
        listed = any(block.get("sample") for block in grouped.values())
        for row in ([] if listed else check.get("sample") or []):
            print(f"      {_sample_line(row)}")

    if "fixes" in report:
        print("\nfixes applied (counts above are from before the fix)")
        for key, value in report["fixes"].items():
            print(f"  {key:<24} {value:>10,}")


def _sample_line(row) -> str:
    """One offender, symbol first and everything else as key=value — the checks
    all report different shapes and none of them is worth its own formatter."""
    if not isinstance(row, dict):
        return str(row)
    rest = " ".join(f"{k}={v}" for k, v in row.items() if k != "symbol")
    return f"{row.get('symbol', ''):<14} {rest}".rstrip()


def _print_crawl_resume_state(cfg, store):
    """Say up front how much of the crawl is already in the bag — the number
    that tells you whether last night's interrupted run is being resumed."""
    if cfg.lookup_restart:
        print("lookup crawl restarting from scratch (--lookup-restart)")
        return
    resumed = store.count_lookup_prefixes_done(
        cfg.lookup_regions, cfg.lookup_types, cfg.lookup_resume_days)
    if resumed:
        print(f"resuming lookup crawl — skipping {resumed:,} prefixes finished "
              f"in the last {cfg.lookup_resume_days} days")


def _split(value):
    if not value:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def _resolve_symbols(args):
    """-> list of symbols, or None meaning "whatever is due".

    An *empty* selector is not the same as no selector. Returning None for a
    `--symbols-file` a cron job failed to populate would silently turn a
    200-symbol job into a run over the entire universe, so that is an error.
    """
    selectors = []
    symbols = []
    if getattr(args, "symbols", None):
        selectors.append("--symbols")
        symbols.extend(_split(args.symbols) or [])
    if getattr(args, "symbols_file", None):
        selectors.append(f"--symbols-file {args.symbols_file}")
        with open(args.symbols_file, encoding="utf-8") as handle:
            symbols.extend(line.strip() for line in handle
                           if line.strip() and not line.startswith("#"))

    cleaned = [s for s in (normalize_symbol(s) for s in symbols) if s]
    if not selectors:
        return None
    if not cleaned:
        raise SystemExit(
            f"error: {' and '.join(selectors)} matched no usable symbols. "
            "Omit the flag entirely to download everything that is due."
        )
    return cleaned


def _download_progress(done, total, stats):
    rows = stats.get("rows", 0)
    sys.stderr.write(
        f"\r  {done:>7,}/{total:<7,} symbols  "
        f"ok={stats.get('ok', 0):,} empty={stats.get('empty', 0):,} "
        f"err={stats.get('error', 0):,} rows={rows:,}   "
    )
    sys.stderr.flush()


def _lookup_progress(done, total, found, skipped=0):
    resumed = f" ({skipped:,} resumed)" if skipped else ""
    sys.stderr.write(f"\r  lookup {done:>6,}/{total:<6,} prefixes{resumed}  "
                     f"{found:,} symbols   ")
    sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
