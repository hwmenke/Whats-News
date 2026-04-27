"""
strategy_tester.py — Vectorized backtest engine with walk-forward optimization.

Public API:
    run_backtest(symbol, freq, config) -> dict
    walk_forward_optimize(symbol, freq, config) -> dict
    monte_carlo(trades, n_sim) -> dict
"""

import math
import numpy as np
import pandas as pd
import database as db
import indicators as ind
import adaptive_trend as adt
from ta_core import _kama, _rsi, _bollinger, _macd

# ── JSON helpers ───────────────────────────────────────────────────────────────

def _safe(val):
    if val is None:
        return None
    try:
        if np.isnan(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return val


def _s2l(s):
    return [_safe(v) for v in s]


# ── Cross helpers ──────────────────────────────────────────────────────────────

def _cross_above(a: pd.Series, b) -> pd.Series:
    if not isinstance(b, pd.Series):
        b = pd.Series(b, index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_below(a: pd.Series, b) -> pd.Series:
    if not isinstance(b, pd.Series):
        b = pd.Series(b, index=a.index)
    return (a < b) & (a.shift(1) >= b.shift(1))


# ── Condition DSL ──────────────────────────────────────────────────────────────

def _eval_leaf(df: pd.DataFrame, kind: str, params: dict, op: str) -> pd.Series:
    """Evaluate one atomic condition into a bool pd.Series."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    false = pd.Series(False, index=df.index)

    try:
        if kind == "kama_cross":
            fast_k = _kama(close, window=int(params.get("fast", 10)))
            slow_k = _kama(close, window=int(params.get("slow", 30)))
            if op == "cross_above":
                return _cross_above(fast_k, slow_k)
            elif op == "cross_below":
                return _cross_below(fast_k, slow_k)

        elif kind == "price_kama_cross":
            k = _kama(close, window=int(params.get("period", 20)))
            if op == "cross_above":
                return _cross_above(close, k)
            elif op == "cross_below":
                return _cross_below(close, k)
            elif op == "above":
                return close > k
            elif op == "below":
                return close < k

        elif kind == "rsi_level":
            r = _rsi(close, window=int(params.get("period", 14)))
            level = float(params.get("level", 50))
            if op == "above":
                return r > level
            elif op == "below":
                return r < level
            elif op == "cross_above":
                return _cross_above(r, level)
            elif op == "cross_below":
                return _cross_below(r, level)

        elif kind == "macd_cross":
            ml, sl, hist = _macd(
                close,
                fast=int(params.get("fast", 12)),
                slow=int(params.get("slow", 26)),
                signal=int(params.get("signal", 9)),
            )
            if op == "line_above_signal":
                return ml > sl
            elif op == "line_below_signal":
                return ml < sl
            elif op == "hist_above_zero":
                return hist > 0
            elif op == "hist_below_zero":
                return hist < 0
            elif op == "cross_above_signal":
                return _cross_above(ml, sl)
            elif op == "cross_below_signal":
                return _cross_below(ml, sl)

        elif kind == "bb_touch":
            upper, mid, lower = _bollinger(
                close,
                window=int(params.get("window", 20)),
                num_std=float(params.get("num_std", 2.0)),
            )
            if op == "close_above_upper":
                return close > upper
            elif op == "close_below_lower":
                return close < lower
            elif op == "close_below_mid":
                return close < mid
            elif op == "close_above_mid":
                return close > mid

        elif kind == "price_change":
            lb  = int(params.get("lookback", 5))
            pct = float(params.get("pct", 0.0))
            chg = close.pct_change(lb)
            if op == "gt":
                return chg > pct
            elif op == "lt":
                return chg < pct

        elif kind == "trend_regime":
            trend = adt._build_trend(df, "kama", adt.DEFAULT_PARAMS)
            ms = pd.Series(
                [r["value"] for r in trend["medium_state"]],
                index=df.index,
            )
            if op == "long":
                return ms == 1
            elif op == "short":
                return ms == -1
            elif op == "flat":
                return ms == 0

    except Exception:
        pass

    return false


def _eval_condition(df: pd.DataFrame, cond) -> pd.Series:
    """Recursively evaluate a condition tree → bool pd.Series."""
    if cond is None:
        return pd.Series(False, index=df.index)

    if cond.get("type") == "leaf":
        return _eval_leaf(df, cond["kind"], cond.get("params", {}), cond.get("op", ""))

    # group node
    logic    = cond.get("logic", "AND")
    children = cond.get("children", [])
    if not children:
        return pd.Series(False, index=df.index)

    parts = [_eval_condition(df, c) for c in children]
    combined = pd.concat(parts, axis=1)
    if logic == "AND":
        return combined.all(axis=1)
    else:
        return combined.any(axis=1)


# ── Positions ──────────────────────────────────────────────────────────────────

def _build_positions(entry_long: pd.Series,
                     exit_long,
                     entry_short,
                     exit_short,
                     allow_short: bool = False) -> pd.Series:
    """Convert entry/exit bool series to a +1/0/-1 position series."""
    n     = len(entry_long)
    pos   = np.zeros(n, dtype=int)
    cur   = 0

    # Normalise optional series
    el  = entry_long.values.astype(bool)
    xl  = (exit_long.values.astype(bool)   if isinstance(exit_long,  pd.Series) else np.zeros(n, bool))
    es  = (entry_short.values.astype(bool) if isinstance(entry_short, pd.Series) else np.zeros(n, bool))
    xs  = (exit_short.values.astype(bool)  if isinstance(exit_short,  pd.Series) else np.zeros(n, bool))

    for i in range(n):
        if cur == 1:
            if xl[i] or (allow_short and es[i]):
                cur = -1 if (allow_short and es[i]) else 0
        elif cur == -1:
            if xs[i] or el[i]:
                cur = 1 if el[i] else 0
        else:
            if el[i]:
                cur = 1
            elif allow_short and es[i]:
                cur = -1
        pos[i] = cur

    return pd.Series(pos, index=entry_long.index)


# ── Trade extraction ───────────────────────────────────────────────────────────

def _extract_trades(df: pd.DataFrame, position: pd.Series,
                    commission_pct: float, slippage_pct: float,
                    bar_delay: int = 1) -> list:
    """Walk position changes and build trade list.

    Uses bar_delay to match the fill-price assumption in _equity_curve:
    when bar_delay=1 the fill is the close of the next bar after the signal.
    """
    closes  = df["close"].values
    highs   = df["high"].values
    lows    = df["low"].values
    pos     = position.values
    dates   = [d.strftime("%Y-%m-%d") for d in df.index]
    cost    = commission_pct + slippage_pct  # one-way cost
    n       = len(closes)

    def _fill_price(signal_i: int) -> float:
        fi = min(signal_i + bar_delay, n - 1)
        return closes[fi]

    trades  = []
    in_pos  = False
    entry_i = None
    entry_p = None
    direction = None

    for i in range(1, len(pos)):
        prev, curr = pos[i - 1], pos[i]

        if not in_pos and curr != 0:
            in_pos    = True
            entry_i   = i
            entry_p   = _fill_price(i)
            direction = curr
        elif in_pos and (curr == 0 or curr != direction):
            exit_i = i
            exit_p = _fill_price(i)

            # MFE / MAE over trade window
            if direction == 1:
                mfe = (np.max(highs[entry_i:exit_i + 1])  - entry_p) / entry_p
                mae = (np.min(lows[entry_i:exit_i + 1])   - entry_p) / entry_p
            else:
                mfe = (entry_p - np.min(lows[entry_i:exit_i + 1]))   / entry_p
                mae = (entry_p - np.max(highs[entry_i:exit_i + 1]))  / entry_p

            gross_ret = direction * (exit_p - entry_p) / entry_p
            net_ret   = gross_ret - 2 * cost  # entry + exit

            trades.append({
                "entry_date":  dates[entry_i],
                "exit_date":   dates[exit_i],
                "direction":   int(direction),
                "entry_price": float(entry_p),
                "exit_price":  float(exit_p),
                "bars_held":   int(exit_i - entry_i),
                "gross_ret":   round(float(gross_ret), 6),
                "net_ret":     round(float(net_ret), 6),
                "mfe":         round(float(mfe), 6),
                "mae":         round(float(mae), 6),
            })

            if curr != 0:
                in_pos    = True
                entry_i   = i
                entry_p   = closes[i]
                direction = curr
            else:
                in_pos = False

    return trades


# ── Equity curve ───────────────────────────────────────────────────────────────

def _equity_curve(df: pd.DataFrame, position: pd.Series,
                  commission_pct: float, slippage_pct: float,
                  bar_delay: int = 1) -> pd.DataFrame:
    """Build equity curve from position series."""
    cost_per_side = commission_pct + slippage_pct

    bar_ret  = df["close"].pct_change().fillna(0.0)
    pos_lag  = position.shift(bar_delay).fillna(0)
    gross    = bar_ret * pos_lag

    # Cost fires on position-change bars
    pos_change = (position.diff().abs() > 0).astype(float)
    cost_drag  = pos_change * cost_per_side

    net_ret  = gross - cost_drag
    equity   = (1.0 + net_ret).cumprod()

    peak       = equity.cummax()
    drawdown   = (equity / peak - 1.0)

    return pd.DataFrame({
        "position": position.values,
        "bar_ret":  bar_ret.values,
        "net_ret":  net_ret.values,
        "equity":   equity.values,
        "peak":     peak.values,
        "drawdown": drawdown.values,
    }, index=df.index)


# ── Performance metrics ────────────────────────────────────────────────────────

def _ann_factor(freq: str) -> float:
    return 252.0 if freq == "daily" else 52.0


def _compute_metrics(eq: pd.DataFrame, trades: list, freq: str = "daily") -> dict:
    ann = _ann_factor(freq)
    nr  = eq["net_ret"].values
    eq_v = eq["equity"].values
    dd   = eq["drawdown"].values

    total_return = float(eq_v[-1] - 1.0) if len(eq_v) else 0.0
    n_years      = len(nr) / ann
    cagr         = float((eq_v[-1] ** (1.0 / max(n_years, 0.01))) - 1.0) if len(eq_v) else 0.0

    ret_mean = float(np.mean(nr))
    ret_std  = float(np.std(nr, ddof=1)) if len(nr) > 1 else 1e-9
    vol_ann  = ret_std * math.sqrt(ann)

    sharpe   = (ret_mean / ret_std * math.sqrt(ann)) if ret_std > 1e-12 else 0.0
    down_std = float(np.std(nr[nr < 0], ddof=1)) if np.any(nr < 0) else 1e-9
    sortino  = (ret_mean / down_std * math.sqrt(ann)) if down_std > 1e-12 else 0.0

    max_dd       = float(np.min(dd)) if len(dd) else 0.0
    calmar       = cagr / abs(max_dd) if abs(max_dd) > 1e-9 else 0.0
    exposure_pct = float(np.mean(np.abs(eq["position"].values)))

    # Trade stats
    n_trades = len(trades)
    if n_trades:
        rets    = np.array([t["net_ret"] for t in trades])
        wins    = rets[rets > 0]
        losses  = rets[rets <= 0]
        win_rate     = float(len(wins) / n_trades)
        avg_win      = float(wins.mean()) if len(wins) else 0.0
        avg_loss     = float(losses.mean()) if len(losses) else 0.0
        profit_factor = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
        expectancy    = float(rets.mean())
        avg_bars_held = float(np.mean([t["bars_held"] for t in trades]))
        # Kelly
        W = win_rate
        A = avg_win if avg_win > 0 else 1e-9
        B = abs(avg_loss) if abs(avg_loss) > 1e-9 else 1e-9
        kelly = W / B - (1 - W) / A
        kelly = max(0.0, min(kelly, 1.0))
    else:
        win_rate = avg_win = avg_loss = avg_bars_held = kelly = expectancy = 0.0
        profit_factor = 0.0

    return {
        "total_return":     round(total_return, 4),
        "cagr":             round(cagr, 4),
        "vol_ann":          round(vol_ann, 4),
        "sharpe":           round(sharpe, 4),
        "sortino":          round(sortino, 4),
        "max_drawdown":     round(max_dd, 4),
        "calmar":           round(calmar, 4),
        "n_trades":         n_trades,
        "win_rate":         round(win_rate, 4),
        "avg_win":          round(avg_win, 4),
        "avg_loss":         round(avg_loss, 4),
        "profit_factor":    round(float(profit_factor), 4) if math.isfinite(profit_factor) else 0.0,
        "expectancy":       round(expectancy, 6),
        "avg_bars_held":    round(avg_bars_held, 1),
        "kelly_fraction":   round(kelly, 4),
        "kelly_half":       round(kelly / 2, 4),
        "exposure_pct":     round(exposure_pct, 4),
    }


# ── Bootstrap confidence intervals ─────────────────────────────────────────────

def _stationary_block_bootstrap(arr: np.ndarray, block_len: int,
                                 n_boot: int = 1000, seed: int = 42) -> np.ndarray:
    """
    Politis-Romano stationary block bootstrap.
    Draws random block starts uniformly; blocks wrap around circularly.
    Returns array of shape (n_boot, len(arr)).
    """
    rng = np.random.default_rng(seed)
    n   = len(arr)
    out = np.empty((n_boot, n), dtype=float)
    starts = rng.integers(0, n, size=(n_boot, math.ceil(n / block_len) + 1))
    for b in range(n_boot):
        idx = 0
        row = out[b]
        for s in starts[b]:
            take = min(block_len, n - idx)
            for k in range(take):
                row[idx] = arr[(s + k) % n]
                idx += 1
            if idx >= n:
                break
    return out


def add_bootstrap_ci(metrics: dict, eq: pd.DataFrame,
                     freq: str = "daily", n_boot: int = 1000) -> dict:
    """
    Augment a metrics dict with bootstrap 95% CIs and p-values.
    Modifies metrics in-place and returns it.
    """
    nr  = eq["net_ret"].values
    ann = _ann_factor(freq)
    if len(nr) < 20:
        return metrics

    avg_bars = metrics.get("avg_bars_held", 1) or 1
    block_len = max(2, int(round(avg_bars)))
    boot = _stationary_block_bootstrap(nr, block_len, n_boot)

    std_b = boot.std(axis=1, ddof=1)
    std_b[std_b < 1e-12] = 1e-12
    boot_sharpe = boot.mean(axis=1) / std_b * math.sqrt(ann)

    boot_cagr = np.array([
        (np.cumprod(1.0 + s)[-1] ** (1.0 / max(len(s) / ann, 0.01)) - 1.0)
        for s in boot
    ])

    lo_s, hi_s = np.percentile(boot_sharpe, [2.5, 97.5])
    lo_c, hi_c = np.percentile(boot_cagr,   [2.5, 97.5])

    metrics["sharpe_ci95"]  = [round(float(lo_s), 4), round(float(hi_s), 4)]
    metrics["cagr_ci95"]    = [round(float(lo_c), 4), round(float(hi_c), 4)]
    # One-sided p-value: P(bootstrap Sharpe ≤ 0 | observed data)
    metrics["sharpe_p_val"] = round(float(np.mean(boot_sharpe <= 0)), 4)
    return metrics


# ── LWC marker builder ─────────────────────────────────────────────────────────

def _build_markers(trades: list) -> list:
    markers = []
    for t in trades:
        markers.append({
            "time":     t["entry_date"],
            "position": "belowBar" if t["direction"] == 1 else "aboveBar",
            "color":    "#22c55e" if t["direction"] == 1 else "#ef4444",
            "shape":    "arrowUp" if t["direction"] == 1 else "arrowDown",
            "text":     "L" if t["direction"] == 1 else "S",
        })
        markers.append({
            "time":     t["exit_date"],
            "position": "aboveBar" if t["direction"] == 1 else "belowBar",
            "color":    "#94a3b8",
            "shape":    "arrowDown" if t["direction"] == 1 else "arrowUp",
            "text":     "X",
        })
    return markers


# ── Public: single backtest ────────────────────────────────────────────────────

DEFAULT_COSTS = {"commission_pct": 0.0005, "slippage_pct": 0.0005}


def run_backtest(symbol: str, freq: str, config: dict) -> dict:
    """
    Run a full vectorised backtest. config keys:
        entry_long, exit_long, entry_short, exit_short : condition dicts
        allow_short      : bool
        bar_delay        : int (default 1)
        commission_pct   : float
        slippage_pct     : float
        regime_filter    : "none"|"long_only"|"short_only"|"trend_aligned"
        limit            : int (default 2000)
        bootstrap        : bool (default False) — add 95% CI on Sharpe/CAGR
        n_boot           : int (default 1000)
    """
    limit = int(config.get("limit", 2000))
    df    = db.get_ohlcv_df(symbol, freq, limit=limit)
    if df.empty or len(df) < 30:
        return {"error": "Insufficient data"}

    commission = float(config.get("commission_pct", DEFAULT_COSTS["commission_pct"]))
    slippage   = float(config.get("slippage_pct",   DEFAULT_COSTS["slippage_pct"]))
    bar_delay  = int(config.get("bar_delay", 1))
    allow_short = bool(config.get("allow_short", False))
    reg_filter  = config.get("regime_filter", "none")

    entry_long  = _eval_condition(df, config.get("entry_long"))
    exit_long   = _eval_condition(df, config.get("exit_long"))   if config.get("exit_long")   else None
    entry_short = _eval_condition(df, config.get("entry_short")) if config.get("entry_short") else None
    exit_short  = _eval_condition(df, config.get("exit_short"))  if config.get("exit_short")  else None

    # Regime filter
    if reg_filter != "none":
        try:
            trend = adt._build_trend(df, "kama", adt.DEFAULT_PARAMS)
            ms = pd.Series(
                [r["value"] for r in trend["medium_state"]],
                index=df.index,
            )
            if reg_filter == "long_only":
                entry_long  = entry_long  & (ms >= 0)
                if entry_short is not None:
                    entry_short = pd.Series(False, index=df.index)
            elif reg_filter == "short_only":
                if entry_short is not None:
                    entry_short = entry_short & (ms <= 0)
                entry_long = pd.Series(False, index=df.index)
            elif reg_filter == "trend_aligned":
                entry_long  = entry_long  & (ms == 1)
                if entry_short is not None:
                    entry_short = entry_short & (ms == -1)
        except Exception:
            pass

    position = _build_positions(entry_long, exit_long, entry_short, exit_short, allow_short)
    trades   = _extract_trades(df, position, commission, slippage, bar_delay)
    eq       = _equity_curve(df, position, commission, slippage, bar_delay)
    metrics  = _compute_metrics(eq, trades, freq)

    if bool(config.get("bootstrap", False)):
        n_boot = int(config.get("n_boot", 1000))
        add_bootstrap_ci(metrics, eq, freq, n_boot)

    # Benchmark (buy-and-hold)
    bh_pos = pd.Series(1, index=df.index)
    bh_eq  = _equity_curve(df, bh_pos, 0.0, 0.0, bar_delay=0)
    bh_metrics = _compute_metrics(bh_eq, [], freq)

    dates = [d.strftime("%Y-%m-%d") for d in df.index]

    return {
        "dates":             dates,
        "price":             _s2l(df["close"].values),
        "position":          _s2l(position.values),
        "equity":            _s2l(eq["equity"].values),
        "benchmark":         _s2l(bh_eq["equity"].values),
        "drawdown":          _s2l(eq["drawdown"].values),
        "markers":           _build_markers(trades),
        "trades":            trades,
        "metrics":           metrics,
        "benchmark_metrics": bh_metrics,
        "config_echo":       config,
    }


# ── Public: walk-forward optimization ─────────────────────────────────────────

def walk_forward_optimize(symbol: str, freq: str, config: dict) -> dict:
    """
    Walk-forward optimization over param_grid.
    config adds:
        param_grid : { "kind__param": [v1, v2, ...], ... }
            e.g.  {"rsi_level__period": [7, 14, 21], "rsi_level__level": [25, 30, 35]}
        n_folds    : int (default 5)
        train_pct  : float (default 0.7)
        anchored   : bool (default False — rolling window)
    """
    limit      = int(config.get("limit", 2000))
    df         = db.get_ohlcv_df(symbol, freq, limit=limit)
    if df.empty or len(df) < 60:
        return {"error": "Insufficient data"}

    n_folds   = int(config.get("n_folds", 5))
    train_pct = float(config.get("train_pct", 0.7))
    anchored  = bool(config.get("anchored", False))
    param_grid = config.get("param_grid", {})

    # Build grid of param overrides
    if param_grid:
        keys   = list(param_grid.keys())
        combos = _cartesian([param_grid[k] for k in keys])
    else:
        keys   = []
        combos = [{}]

    total = len(df)
    fold_size = total // n_folds

    folds_out = []
    combined_eq_segments = []
    combined_dates_segments = []
    # track best param per fold for stability
    param_fold_values = {k: [] for k in keys}

    for fold_i in range(n_folds):
        test_start  = fold_size * fold_i
        test_end    = fold_size * (fold_i + 1) if fold_i < n_folds - 1 else total
        train_start = 0 if anchored else max(0, test_start - int(fold_size / train_pct * (1 - train_pct)))
        train_end   = test_start

        if train_end - train_start < 30 or test_end - test_start < 10:
            continue

        df_train = df.iloc[train_start:train_end]
        df_test  = df.iloc[test_start:test_end]

        best_sharpe = -1e9
        best_cfg    = config.copy()

        for combo in combos:
            fold_cfg = _apply_param_combo(config, keys, combo)
            try:
                pos = _build_positions_from_config(df_train, fold_cfg)
                eq  = _equity_curve(
                    df_train, pos,
                    float(fold_cfg.get("commission_pct", DEFAULT_COSTS["commission_pct"])),
                    float(fold_cfg.get("slippage_pct",   DEFAULT_COSTS["slippage_pct"])),
                )
                trades_is = _extract_trades(df_train, pos, 0, 0)
                m = _compute_metrics(eq, trades_is, freq)
                if m["sharpe"] > best_sharpe:
                    best_sharpe = m["sharpe"]
                    best_cfg    = fold_cfg
            except Exception:
                continue

        # Evaluate OOS with best params
        try:
            pos_oos   = _build_positions_from_config(df_test, best_cfg)
            eq_oos    = _equity_curve(
                df_test, pos_oos,
                float(best_cfg.get("commission_pct", DEFAULT_COSTS["commission_pct"])),
                float(best_cfg.get("slippage_pct",   DEFAULT_COSTS["slippage_pct"])),
            )
            trades_oos = _extract_trades(df_test, pos_oos, 0, 0)
            oos_m  = _compute_metrics(eq_oos, trades_oos, freq)
            oos_eq = list(eq_oos["equity"].values)
        except Exception:
            oos_m  = {}
            oos_eq = []

        # Collect OOS equity for combined curve
        combined_eq_segments.extend(oos_eq)
        combined_dates_segments.extend([d.strftime("%Y-%m-%d") for d in df_test.index])

        # Param values for stability
        best_params_flat = _flatten_config(best_cfg, keys)
        for k in keys:
            param_fold_values[k].append(best_params_flat.get(k))

        folds_out.append({
            "fold":         fold_i + 1,
            "train_start":  df.index[train_start].strftime("%Y-%m-%d"),
            "train_end":    df.index[train_end - 1].strftime("%Y-%m-%d"),
            "test_start":   df.index[test_start].strftime("%Y-%m-%d"),
            "test_end":     df.index[test_end - 1].strftime("%Y-%m-%d"),
            "best_params":  best_params_flat,
            "is_metric":    round(best_sharpe, 4),
            "oos_metric":   oos_m.get("sharpe", None),
            "oos_return":   oos_m.get("total_return", None),
        })

    # Combined OOS metrics
    if combined_eq_segments:
        combined_arr = np.array(combined_eq_segments)
        nr_combined  = np.diff(combined_arr) / combined_arr[:-1]
        ann = _ann_factor(freq)
        combined_sharpe = (float(np.mean(nr_combined)) / float(np.std(nr_combined, ddof=1)) * math.sqrt(ann)) if len(nr_combined) > 1 and np.std(nr_combined) > 1e-12 else 0.0
        combined_return = float(combined_arr[-1] / combined_arr[0] - 1.0) if combined_arr[0] > 0 else 0.0
        dd_combined  = np.minimum.accumulate(combined_arr / np.maximum.accumulate(combined_arr)) - 1.0
        combined_metrics = {
            "sharpe":       round(combined_sharpe, 4),
            "total_return": round(combined_return, 4),
            "max_drawdown": round(float(np.min(dd_combined)), 4),
        }
    else:
        combined_metrics = {}

    # Param stability (CV = std/|mean|, lower = more stable)
    param_stability = {}
    for k, vals in param_fold_values.items():
        valid = [v for v in vals if v is not None]
        if len(valid) >= 2:
            m = abs(float(np.mean(valid)))
            s = float(np.std(valid))
            param_stability[k] = round(s / m, 4) if m > 1e-9 else None
        else:
            param_stability[k] = None

    return {
        "folds":             folds_out,
        "combined_equity":   [_safe(v) for v in combined_eq_segments],
        "combined_dates":    combined_dates_segments,
        "combined_metrics":  combined_metrics,
        "param_stability":   param_stability,
    }


# ── Monte Carlo ────────────────────────────────────────────────────────────────

def monte_carlo(trades: list, n_sim: int = 1000) -> dict:
    """Bootstrap-resample trade returns to build equity path distribution."""
    if not trades:
        return {"error": "No trades"}

    rets = np.array([t.get("net_ret", 0.0) for t in trades])
    n    = len(rets)

    rng   = np.random.default_rng(42)
    paths = rng.choice(rets, size=(n_sim, n), replace=True)
    equity = np.cumprod(1.0 + paths, axis=1)

    pcts = {
        "p5":  list(np.percentile(equity, 5,  axis=0)),
        "p25": list(np.percentile(equity, 25, axis=0)),
        "p50": list(np.percentile(equity, 50, axis=0)),
        "p75": list(np.percentile(equity, 75, axis=0)),
        "p95": list(np.percentile(equity, 95, axis=0)),
    }

    return {"n_sim": n_sim, "n_trades": n, "percentiles": pcts}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _build_positions_from_config(df: pd.DataFrame, config: dict) -> pd.Series:
    allow_short = bool(config.get("allow_short", False))
    entry_long  = _eval_condition(df, config.get("entry_long"))
    exit_long   = _eval_condition(df, config.get("exit_long"))   if config.get("exit_long")   else None
    entry_short = _eval_condition(df, config.get("entry_short")) if config.get("entry_short") else None
    exit_short  = _eval_condition(df, config.get("exit_short"))  if config.get("exit_short")  else None
    return _build_positions(entry_long, exit_long, entry_short, exit_short, allow_short)


def _cartesian(lists):
    """Cartesian product of lists → list of tuples."""
    result = [()]
    for lst in lists:
        result = [x + (v,) for x in result for v in lst]
    return result


def _apply_param_combo(config: dict, keys: list, combo: tuple) -> dict:
    """Deep-copy config and patch leaf-node params for a given combo."""
    import copy
    cfg = copy.deepcopy(config)
    for k, v in zip(keys, combo):
        # key format: "kind__param"  e.g. "rsi_level__period"
        parts = k.split("__", 1)
        if len(parts) == 2:
            kind_key, param_key = parts
            _patch_condition(cfg.get("entry_long"),  kind_key, param_key, v)
            _patch_condition(cfg.get("exit_long"),   kind_key, param_key, v)
            _patch_condition(cfg.get("entry_short"), kind_key, param_key, v)
            _patch_condition(cfg.get("exit_short"),  kind_key, param_key, v)
    return cfg


def _patch_condition(cond, kind_key: str, param_key: str, value):
    """Recursively patch params in a condition tree."""
    if cond is None:
        return
    if cond.get("type") == "leaf":
        if cond.get("kind") == kind_key:
            cond.setdefault("params", {})[param_key] = value
    elif cond.get("type") == "group":
        for child in cond.get("children", []):
            _patch_condition(child, kind_key, param_key, value)


def _flatten_config(config: dict, keys: list) -> dict:
    """Extract current param values for the given keys from a config."""
    result = {}
    for k in keys:
        parts = k.split("__", 1)
        if len(parts) == 2:
            kind_key, param_key = parts
            val = _find_param(config.get("entry_long"),  kind_key, param_key)
            if val is None:
                val = _find_param(config.get("exit_long"),   kind_key, param_key)
            if val is None:
                val = _find_param(config.get("entry_short"), kind_key, param_key)
            result[k] = val
    return result


def _find_param(cond, kind_key: str, param_key: str):
    if cond is None:
        return None
    if cond.get("type") == "leaf" and cond.get("kind") == kind_key:
        return cond.get("params", {}).get(param_key)
    for child in cond.get("children", []):
        v = _find_param(child, kind_key, param_key)
        if v is not None:
            return v
    return None
