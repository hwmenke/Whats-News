"""
fred_fetcher.py - Download macro series from FRED and store them in the DB.

Uses the keyless CSV endpoint (no API key required):
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>

FRED emits "." for missing observations; those become NULL values so gaps
stay gaps instead of being silently forward-filled.
"""

import io
import time

import pandas as pd
import requests

import database as db

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# Series worth watching next to an equity trend system. `invert` marks series
# where RISING is bad for risk assets (credit stress, unemployment claims), so
# the UI can colour the trend badge correctly.
DEFAULT_SERIES = [
    {"id": "T10Y2Y",        "label": "10Y-2Y Spread",   "unit": "%",    "invert": False},
    {"id": "BAMLH0A0HYM2",  "label": "HY Credit Spread", "unit": "%",   "invert": True},
    {"id": "ICSA",          "label": "Initial Claims",  "unit": "k",    "invert": True},
    {"id": "DFF",           "label": "Fed Funds Rate",  "unit": "%",    "invert": True},
    {"id": "USREC",         "label": "Recession Flag",  "unit": "",     "invert": True},
]


def _parse_csv(text: str, series: str):
    """
    Parse a FRED CSV into [(date_str, value_or_None), ...].
    The date column is 'DATE' on older responses and 'observation_date' on
    newer ones; the value column is named after the series id.
    """
    df = pd.read_csv(io.StringIO(text))
    if df.empty or len(df.columns) < 2:
        return []

    date_col = next(
        (c for c in df.columns if c.strip().lower() in ("date", "observation_date")),
        df.columns[0],
    )
    value_col = next((c for c in df.columns if c != date_col), df.columns[1])

    dates  = pd.to_datetime(df[date_col], errors="coerce")
    values = pd.to_numeric(df[value_col], errors="coerce")   # "." → NaN

    rows = []
    for d, v in zip(dates, values):
        if pd.isna(d):
            continue
        rows.append((d.strftime("%Y-%m-%d"), None if pd.isna(v) else float(v)))
    return rows


def fetch_series(series: str, max_retries: int = 3, timeout: int = 20) -> dict:
    """
    Download one FRED series and store it. Retries with exponential back-off.
    Returns {"series", "rows"} or {"series", "error"}.
    """
    sid   = series.upper()
    delay = 3

    for attempt in range(1, max_retries + 1):
        try:
            print(f"++ FRED: fetching {sid} (attempt {attempt})")
            resp = requests.get(FRED_CSV_URL.format(series=sid), timeout=timeout)
            resp.raise_for_status()

            rows = _parse_csv(resp.text, sid)
            if not rows:
                return {"series": sid, "error": f"No observations returned for {sid}"}

            count = db.upsert_macro(sid, rows)
            print(f"++ FRED: stored {count} observations for {sid}")
            return {"series": sid, "rows": count}

        except Exception as exc:
            print(f"!! FRED: attempt {attempt} failed for {sid}: {exc}")
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
            else:
                return {"series": sid, "error": str(exc)}


def fetch_all(series_ids=None) -> list:
    """Fetch every default series (or the given ids). Never raises."""
    ids = series_ids or [s["id"] for s in DEFAULT_SERIES]
    results = []
    for sid in ids:
        try:
            results.append(fetch_series(sid))
        except Exception as exc:                      # belt and braces
            results.append({"series": sid, "error": str(exc)})
    return results


def recession_ranges() -> list:
    """
    Convert the stored USREC 0/1 indicator into [{from, to}] date ranges.
    A range still open at the end of the series has to == the last date.
    """
    obs = db.get_macro("USREC").get("USREC", [])
    ranges, start = [], None

    for row in obs:
        in_rec = bool(row["value"])
        if in_rec and start is None:
            start = row["date"]
        elif not in_rec and start is not None:
            ranges.append({"from": start, "to": row["date"]})
            start = None

    if start is not None and obs:
        ranges.append({"from": start, "to": obs[-1]["date"]})
    return ranges
