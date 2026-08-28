"""
conditional_dist.py - Historical conditional forward-return distributions.

Given filter conditions on indicators (for example RSI(14) < 30, price > MA(50),
MA(20) > MA(50)), report the distribution of N-trading-day forward returns on the
bars where every condition holds, next to the unconditional baseline.

Conditions only look backward (rolling / ewm windows), so the signal has no
lookahead. Forward returns are the prediction target and are the only place a
future bar is read. A bar with a NaN feature (warmup) fails its comparison and is
excluded from the matched set.

Feature spec grammar (case-insensitive):
    price, close, open, high, low, volume    bare OHLCV series
    RSI(w)                                    Wilder RSI, default window 14
    MA(w) / SMA(w)                            simple moving average of close
    EMA(w)                                    exponential moving average of close
    MACD / MACD_SIGNAL / MACD_HIST           12/26/9 MACD family

A condition is {"left": <feature>, "op": <"<"|"<="|">"|">=">, "right": <feature|number>}.
Conditions combine with AND.
"""

import re

import numpy as np
import pandas as pd

import market_data as db

DEFAULT_HORIZONS = (5, 10)
PERCENTILES = [5, 25, 50, 75, 95]

OPS = {
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}

_FEATURE_RE = re.compile(r"^([a-zA-Z_]+)\s*(?:\(\s*(\d+)\s*\))?$")
_BARE_SERIES = {"open", "high", "low", "volume"}
_PRICE_ALIASES = {"price", "close", "c"}


class ConditionError(ValueError):
    """Raised when a feature or condition spec cannot be parsed."""


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI via exponential moving average (matches indicators.py)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd_line(close: pd.Series) -> pd.Series:
    return close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()


def resolve_feature(name, df: pd.DataFrame) -> pd.Series:
    """Resolve a feature spec string to a pandas Series aligned to df.index."""
    if not isinstance(name, str):
        raise ConditionError(f"Feature must be a string, got {name!r}")
    key = name.strip()
    low = key.lower()
    close = df["close"]

    if low in _PRICE_ALIASES:
        return close
    if low in _BARE_SERIES:
        return df[low]

    match = _FEATURE_RE.match(key)
    if not match:
        raise ConditionError(f"Unrecognized feature: {name!r}")
    base = match.group(1).lower()
    period = int(match.group(2)) if match.group(2) else None

    if base == "rsi":
        return _rsi(close, period or 14)
    if base in ("ma", "sma"):
        if not period:
            raise ConditionError("Moving average needs a period, e.g. MA(50)")
        return close.rolling(period).mean()
    if base == "roc":
        if not period:
            raise ConditionError("ROC needs a period, e.g. ROC(20)")
        return close.pct_change(period) * 100.0  # percent momentum over `period` bars
    if base == "ema":
        if not period:
            raise ConditionError("EMA needs a period, e.g. EMA(20)")
        return close.ewm(span=period, adjust=False).mean()
    if base in ("macd", "macd_line"):
        return _macd_line(close)
    if base == "macd_signal":
        return _macd_line(close).ewm(span=9, adjust=False).mean()
    if base == "macd_hist":
        line = _macd_line(close)
        return line - line.ewm(span=9, adjust=False).mean()

    raise ConditionError(f"Unknown feature: {name!r}")


def _operand(value, df: pd.DataFrame):
    """A number becomes a constant; a string becomes a numeric literal or a feature."""
    if isinstance(value, bool):
        raise ConditionError(f"Invalid operand: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            return resolve_feature(text, df)
    raise ConditionError(f"Invalid operand: {value!r}")


def _normalize_condition(cond: dict) -> dict:
    """Accept left/op/right plus the friendlier feature/operator/value aliases."""
    if not isinstance(cond, dict):
        raise ConditionError("Each condition must be an object with left/op/right")
    left = cond.get("left", cond.get("feature"))
    op = cond.get("op", cond.get("operator"))
    right = cond.get("right", cond.get("value"))
    if left is None or op is None or right is None:
        raise ConditionError("Condition needs left, op and right")
    if op not in OPS:
        raise ConditionError(f"Unsupported operator: {op!r}")
    return {"left": left, "op": op, "right": right}


def evaluate_condition(df: pd.DataFrame, cond: dict) -> pd.Series:
    """Boolean mask for one condition. NaN comparisons resolve to False."""
    norm = _normalize_condition(cond)
    left = _operand(norm["left"], df)
    right = _operand(norm["right"], df)
    mask = OPS[norm["op"]](left, right)
    if np.isscalar(mask):
        mask = pd.Series(bool(mask), index=df.index)
    return mask.reindex(df.index).fillna(False).astype(bool)


def build_mask(df: pd.DataFrame, conditions) -> pd.Series:
    """AND of all conditions. Empty list matches every bar (the baseline)."""
    mask = pd.Series(True, index=df.index)
    for cond in conditions or []:
        mask &= evaluate_condition(df, cond)
    return mask


def forward_returns(close: pd.Series, horizon: int) -> pd.Series:
    """Return over the next `horizon` bars, placed on the signal bar t.

    value[t] = close[t + horizon] / close[t] - 1. The last `horizon` bars are NaN.
    """
    return close.pct_change(horizon).shift(-horizon)


def _describe(returns: pd.Series) -> dict:
    r = returns.dropna()
    n = int(len(r))
    if n == 0:
        keys = ["mean", "median", "std", "skew", "kurtosis", "min", "max",
                "p05", "p25", "p50", "p75", "p95", "win_rate"]
        return {"count": 0, **{k: None for k in keys}}
    pct = np.percentile(r, PERCENTILES)
    return {
        "count": n,
        "mean": float(r.mean()),
        "median": float(r.median()),
        "std": float(r.std()) if n > 1 else None,
        "skew": float(r.skew()) if n > 2 else None,
        "kurtosis": float(r.kurt()) if n > 3 else None,
        "min": float(r.min()),
        "max": float(r.max()),
        "p05": float(pct[0]),
        "p25": float(pct[1]),
        "p50": float(pct[2]),
        "p75": float(pct[3]),
        "p95": float(pct[4]),
        "win_rate": float((r > 0).mean()),
    }


def _histogram(cond_r: pd.Series, base_r: pd.Series, bins: int) -> dict:
    """Shared bin edges so the conditional and baseline shapes are comparable."""
    base_valid = base_r.dropna()
    if base_valid.empty:
        return {"centers": [], "conditional": [], "baseline": []}
    lo, hi = float(base_valid.min()), float(base_valid.max())
    if lo == hi:
        hi = lo + 1e-9
    edges = np.linspace(lo, hi, bins + 1)
    c_counts, _ = np.histogram(cond_r.dropna(), bins=edges)
    b_counts, _ = np.histogram(base_valid, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2.0
    return {
        "centers": [float(x) for x in centers],
        "conditional": [int(x) for x in c_counts],
        "baseline": [int(x) for x in b_counts],
    }


def compute_conditional_distribution(symbol: str, conditions, horizons=DEFAULT_HORIZONS,
                                     bins: int = 30) -> dict:
    """Forward-return distribution on matched bars vs the unconditional baseline.

    Raises ConditionError for a bad feature/condition spec.
    """
    df = db.get_ohlcv_df(symbol, "daily", limit=5000)
    if df.empty:
        return {"error": "No data found"}

    horizons = [int(h) for h in horizons] or list(DEFAULT_HORIZONS)
    mask = build_mask(df, conditions)  # validates conditions, may raise

    match_count = int(mask.sum())
    bar_count = int(len(df))
    out = {
        "symbol": symbol,
        "horizons": horizons,
        "conditions": list(conditions or []),
        "bar_count": bar_count,
        "match_count": match_count,
        "match_rate": float(mask.mean()) if bar_count else 0.0,
        "start": df.index.min().strftime("%Y-%m-%d"),
        "end": df.index.max().strftime("%Y-%m-%d"),
        "return_unit": "fraction",
        "message": f"Matched {match_count:,} of {bar_count:,} bars ({(match_count / bar_count * 100) if bar_count else 0:.1f}%)",
        "by_horizon": {},
    }

    for h in horizons:
        fr = forward_returns(df["close"], h)
        cond = _describe(fr[mask])
        # Matched bars within `h` days of each other share future days, so their
        # forward returns overlap and are autocorrelated. Report an effective
        # sample size (non-overlapping equivalent) so the count is not overread.
        cond["effective_count"] = round(cond["count"] / h, 1) if cond["count"] else 0
        out["by_horizon"][str(h)] = {
            "conditional": cond,
            "baseline": _describe(fr),
            "hist": _histogram(fr[mask], fr, bins),
        }
    return out
