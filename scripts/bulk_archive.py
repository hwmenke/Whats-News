#!/usr/bin/env python3
"""
bulk_archive.py — One-time (or rare) full history download + daily incremental refresh.

Examples:
  # Register ~2000 US index tickers in DB (no Yahoo download yet)
  python scripts/bulk_archive.py --sync-indices all

  # Full archive from 2000 (run once; takes hours)
  python scripts/bulk_archive.py --archive --start 2000-01-01 --delay 1.5

  # Daily refresh — only last few days per symbol (run after market close)
  python scripts/bulk_archive.py --refresh --overlap-days 5 --delay 0.8

  # Archive only symbols missing daily data
  python scripts/bulk_archive.py --archive --only-missing
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import database as db
import data_fetcher as fetcher
from index_universe import merged_universe


def _symbols_for_job(only_missing: bool) -> list[str]:
    if only_missing:
        have = set(db.list_symbols_with_ohlcv("daily", min_bars=1))
        all_syms = db.list_symbol_codes()
        return [s for s in all_syms if s not in have]
    return db.list_symbol_codes()


def cmd_sync(indices: list[str]) -> int:
    db.init_db()
    merged = merged_universe(indices)
    print(f"Universe: {merged['total_unique']} unique symbols")
    for idx, n in merged.get("per_index", {}).items():
        print(f"  {idx}: {n}")
    for idx, err in merged.get("errors", {}).items():
        print(f"  !! {idx}: {err}")

    mapping = merged.get("symbol_indices") or {}
    result = db.add_universe_symbols(mapping)
    print(f"Added {len(result['added'])}, skipped {len(result['skipped'])}, retagged {len(result.get('retagged', []))}")
    return 0


def cmd_archive(start: str, delay: float, only_missing: bool, limit: int) -> int:
    db.init_db()
    symbols = _symbols_for_job(only_missing)
    if limit:
        symbols = symbols[:limit]
    print(f"Archiving {len(symbols)} symbols from {start} …")
    ok, fail = 0, 0
    for i, sym in enumerate(symbols, 1):
        res = fetcher.fetch_full_history(sym, start=start)
        if "error" in res:
            fail += 1
            print(f"[{i}/{len(symbols)}] FAIL {sym}: {res['error']}")
        else:
            ok += 1
            print(f"[{i}/{len(symbols)}] OK {sym}: {res.get('daily_rows')}d")
        if i < len(symbols):
            time.sleep(delay)
    print(f"Done. ok={ok} failed={fail}")
    if ok:
        db.optimize_db()
    return 0 if fail == 0 else 1


def cmd_refresh(delay: float, overlap_days: int, only_missing: bool, limit: int) -> int:
    db.init_db()
    symbols = _symbols_for_job(only_missing)
    if limit:
        symbols = symbols[:limit]
    print(f"Refreshing {len(symbols)} symbols (overlap {overlap_days}d) …")
    ok, fail, skip = 0, 0, 0
    for i, sym in enumerate(symbols, 1):
        if db.is_recently_fetched(sym, hours=4):
            skip += 1
            continue
        res = fetcher.fetch_and_store(sym, overlap_days=overlap_days)
        if "error" in res:
            fail += 1
            print(f"[{i}/{len(symbols)}] FAIL {sym}: {res['error']}")
        else:
            ok += 1
        if i < len(symbols):
            time.sleep(delay)
    print(f"Done. ok={ok} skipped_recent={skip} failed={fail}")
    return 0 if fail == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Whats-News bulk archive / refresh")
    parser.add_argument(
        "--sync-indices",
        nargs="*",
        metavar="ID",
        help="Register index tickers (sp500, sp400, sp600, ndx100, russell2000, or all)",
    )
    parser.add_argument("--archive", action="store_true", help="Download full history")
    parser.add_argument("--refresh", action="store_true", help="Incremental refresh only")
    parser.add_argument("--start", default="2000-01-01", help="Archive start date")
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds between Yahoo calls")
    parser.add_argument("--overlap-days", type=int, default=5, help="Refresh overlap window")
    parser.add_argument("--only-missing", action="store_true", help="Archive symbols without daily data")
    parser.add_argument("--limit", type=int, default=0, help="Max symbols to process (0 = all)")
    args = parser.parse_args()

    if args.sync_indices:
        return cmd_sync(args.sync_indices)

    if args.archive:
        return cmd_archive(args.start, args.delay, args.only_missing, args.limit)

    if args.refresh:
        return cmd_refresh(args.delay, args.overlap_days, args.only_missing, args.limit)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
