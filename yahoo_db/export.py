"""
export.py - Dump tables out of the SQLite store.

SQLite is the system of record; this is for handing the data to something else
(pandas, DuckDB, a notebook) without teaching it the schema.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

TABLES = ("tickers", "prices", "dividends", "splits", "profiles", "fetch_log")


def export_table(store, table: str, out_dir, fmt: str = "csv",
                 interval: str = None, chunk_size: int = 500_000) -> dict:
    """Write one table to `out_dir` as CSV or Parquet.

    `prices` is streamed in chunks so a multi-gigabyte table does not have to
    fit in memory at once (CSV appends; Parquet needs one frame, so it is
    written per chunk as part-files).
    """
    if table not in TABLES:
        raise ValueError(f"unknown table '{table}' (known: {', '.join(TABLES)})")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sql = f"SELECT * FROM {table}"
    params = []
    if table == "prices" and interval:
        sql += " WHERE interval = ?"
        params.append(interval)

    written = 0
    parts = 0
    if fmt == "csv":
        path = out_dir / f"{table}.csv"
        header = True
        mode = "w"
        for chunk in pd.read_sql_query(sql, store.conn, params=params,
                                       chunksize=chunk_size):
            chunk.to_csv(path, mode=mode, header=header, index=False)
            header, mode = False, "a"
            written += len(chunk)
        if written == 0:      # still leave an empty file with headers
            pd.read_sql_query(f"{sql} LIMIT 0", store.conn, params=params).to_csv(
                path, index=False)
        return {"table": table, "rows": written, "path": str(path)}

    if fmt == "parquet":
        _require_parquet()
        paths = []
        dtypes = None
        for chunk in pd.read_sql_query(sql, store.conn, params=params,
                                       chunksize=chunk_size):
            # SQLite is untyped per row, so a column that happens to be all
            # NULL in one chunk and numeric in the next infers different
            # dtypes — which gives the part-files incompatible Arrow schemas
            # and breaks any reader that globs the directory. Pin every chunk
            # to the first one's dtypes.
            if dtypes is None:
                dtypes = chunk.dtypes
            else:
                chunk = chunk.astype(dtypes, errors="ignore")
            path = out_dir / (f"{table}.parquet" if parts == 0
                              else f"{table}.part{parts}.parquet")
            chunk.to_parquet(path, index=False)
            paths.append(str(path))
            written += len(chunk)
            parts += 1
        if not paths:
            path = out_dir / f"{table}.parquet"
            pd.read_sql_query(f"{sql} LIMIT 0", store.conn,
                              params=params).to_parquet(path, index=False)
            paths.append(str(path))
        return {"table": table, "rows": written, "path": ", ".join(paths)}

    raise ValueError(f"unknown format '{fmt}' (use csv or parquet)")


def export_all(store, out_dir, fmt: str = "csv", interval: str = None) -> list:
    return [export_table(store, table, out_dir, fmt=fmt, interval=interval)
            for table in TABLES]


def _require_parquet():
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Parquet export needs pyarrow — pip install pyarrow"
        ) from exc
