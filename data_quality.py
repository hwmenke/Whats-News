"""
data_quality.py — OHLCV data-quality checks.

validate(df, freq) -> {"ok": bool, "issues": [...]}
Each issue: {"check": str, "severity": "critical"|"warning", "detail": str}
"""

import numpy as np
import pandas as pd


def _expected_gap_days(freq: str) -> int:
    """Max calendar-day gap before flagging as missing data."""
    return 5 if freq == "daily" else 14


def validate(df: pd.DataFrame, freq: str) -> dict:
    """
    Run all data-quality checks on an OHLCV DataFrame.
    Returns {"ok": bool, "issues": list[dict]}.
    ok is False when any critical issue is found.
    """
    issues = []

    if df is None or df.empty or len(df) < 2:
        return {"ok": True, "issues": []}

    # 1. Duplicate dates
    if df.index.duplicated().any():
        dups = df.index[df.index.duplicated()].strftime("%Y-%m-%d").tolist()
        issues.append({
            "check": "duplicate_dates",
            "severity": "critical",
            "detail": f"Duplicate dates: {dups[:5]}" + (" ..." if len(dups) > 5 else ""),
        })

    # 2. OHLC logic errors
    if "high" in df.columns and "low" in df.columns and "close" in df.columns:
        bad_hl = df["high"] < df["low"]
        bad_hc = df["high"] < df["close"]
        bad_lc = df["low"] > df["close"]
        bad = bad_hl | bad_hc | bad_lc
        if bad.any():
            dates = df.index[bad].strftime("%Y-%m-%d").tolist()
            issues.append({
                "check": "ohlc_logic",
                "severity": "critical",
                "detail": f"OHLC logic error on {len(dates)} bar(s): {dates[:3]}",
            })

    # 3. Calendar gaps > expected
    if len(df.index) > 1:
        gap_days = _expected_gap_days(freq)
        diffs = (df.index[1:] - df.index[:-1]).days
        big_gaps = np.where(diffs > gap_days)[0]
        if len(big_gaps) > 0:
            worst_i = big_gaps[np.argmax(diffs[big_gaps])]
            detail = (
                f"{len(big_gaps)} gap(s) > {gap_days} calendar days; "
                f"largest: {diffs[worst_i]}d ending {df.index[worst_i + 1].strftime('%Y-%m-%d')}"
            )
            issues.append({
                "check": "calendar_gaps",
                "severity": "critical",
                "detail": detail,
            })

    # 4. Price spikes > 40% (likely unadjusted split)
    if "close" in df.columns:
        ret = df["close"].pct_change().abs()
        spikes = ret[ret > 0.40].dropna()
        if not spikes.empty:
            dates = spikes.index.strftime("%Y-%m-%d").tolist()
            pcts = [f"{v:.0%}" for v in spikes.values]
            issues.append({
                "check": "price_spike",
                "severity": "critical",
                "detail": f"Price spike(s) >40%: {list(zip(dates[:3], pcts[:3]))}",
            })

    # 5. Stale close (>5 consecutive identical values)
    if "close" in df.columns:
        closes = df["close"].values
        max_run = 1
        cur_run = 1
        run_end = None
        for i in range(1, len(closes)):
            if np.isclose(closes[i], closes[i - 1], rtol=0, atol=1e-9):
                cur_run += 1
                if cur_run > max_run:
                    max_run = cur_run
                    run_end = df.index[i].strftime("%Y-%m-%d")
            else:
                cur_run = 1
        if max_run > 5:
            issues.append({
                "check": "stale_close",
                "severity": "warning",
                "detail": f"{max_run} consecutive identical closes ending {run_end}",
            })

    ok = all(iss["severity"] != "critical" for iss in issues)
    return {"ok": ok, "issues": issues}
