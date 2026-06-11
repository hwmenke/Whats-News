"""
quant_lab.py — Bloomberg-terminal-style quant analysis engine.

One symbol in, four models out, plus two composite dials:

    VALUATION  (-100 cheap … +100 rich)   "is it cheap or expensive?"
    DIRECTION  (-100 lower … +100 higher) "is it going up or down?"

Models
──────
FAIR VALUE   Rolling 126-bar log-linear trend channel.  The fitted trend is
             the "fair value"; the residual (in residual-σ units) is blended
             with four other stretch measures into a valuation composite.
             The edge curve bins history by valuation score and shows the
             realised forward 1-week return per bin — the empirical answer
             to "what happens after it gets this cheap/rich?".

KNN          Pattern-matching fan forecast.  The current bar is described by
             10 standardized state features (trend, valuation, exhaustion,
             vol regime, momentum, participation); the K most similar
             historical bars (de-overlapped) project their forward 21-bar
             paths into a percentile fan + analog spaghetti.

CTA          Three-speed EWMAC trend-following (8/32, 16/64, 32/128) with a
             vol-normalised forecast passed through the AHL response curve
             x·exp(-x²/4)/0.89 (fades over-extended trends).  Vol-targeted
             position, costed backtest vs buy & hold.

EXHAUSTION   Blow-off / capitulation composite: TD-sequential-style count,
             fast RSI, ATR stretch percentile, signed volume climax and
             10-bar extension.  Event study of past |score| ≥ 70 episodes
             with forward-return stats vs the unconditional base rate.

SQUEEZE      Volatility-compression model: Bollinger-width and realized-vol
             percentile blend into a 0–100 compression score.  Event study
             of past compression episodes (score ≥ 85): how big was the
             next 1-month move, and how often did the prevailing EWMAC
             trend call its direction.

MEAN REV     Ornstein-Uhlenbeck fit on the trend-channel residual: AR(1)
             phi, half-life of reversion, Hurst exponent and variance
             ratio say whether the symbol mean-reverts or trends, and a
             21-bar expected reversion path is projected from the current
             stretch.

All maths is vectorised numpy/pandas — no model fitting at request time.
PyCaret AutoML stays on its own on-demand endpoint (/api/pycaret/<symbol>).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

import database as db
import indicator_cache as cache
from ta_core import _kama, _rsi, _bollinger

ANN        = 252
MIN_BARS   = 300
KNN_H      = 21          # forward path length (bars)
KNN_K      = 25
EWMAC_SPEEDS = [(8, 32), (16, 64), (32, 128)]


# ── small helpers ─────────────────────────────────────────────────────────────

def _fl(x, nd: int = 4):
    """Float → rounded float, non-finite → None (JSON-safe)."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if np.isfinite(f) else None


def _fl_list(arr, nd: int = 4) -> list:
    return [_fl(v, nd) for v in np.asarray(arr, dtype=float)]


def _z(s: pd.Series, window: int = ANN, min_p: int = 60) -> pd.Series:
    """Rolling z-score, clipped to ±3."""
    mu = s.rolling(window, min_periods=min_p).mean()
    sd = s.rolling(window, min_periods=min_p).std()
    return ((s - mu) / sd.replace(0, np.nan)).clip(-3, 3)


def _pct_rank(s: pd.Series, window: int = ANN, min_p: int = 60) -> pd.Series:
    """Rolling percentile rank in [0, 1]."""
    def _rank(x):
        return (x[:-1] < x[-1]).sum() / max(len(x) - 1, 1)
    return s.rolling(window, min_periods=min_p).apply(_rank, raw=True)


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev = df["close"].shift(1).fillna(df["close"])
    tr   = pd.concat([df["high"] - df["low"],
                      (df["high"] - prev).abs(),
                      (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd   = equity / np.where(peak <= 0, np.nan, peak) - 1.0
    return float(np.nanmin(dd)) if len(dd) else float("nan")


# ── fair-value trend channel ─────────────────────────────────────────────────

def _trend_channel(log_close: np.ndarray, window: int = 126):
    """
    Rolling OLS of log price on time.  Returns (fit, resid_sigma, resid_z,
    slope) aligned to the input — the fitted value at each window's END bar.
    """
    n = len(log_close)
    fit   = np.full(n, np.nan)
    sig   = np.full(n, np.nan)
    slp   = np.full(n, np.nan)
    if n < window:
        return fit, sig, np.full(n, np.nan), slp

    win    = sliding_window_view(log_close, window)          # (n-w+1, w)
    t      = np.arange(window, dtype=float)
    t_mean = t.mean()
    t_var  = ((t - t_mean) ** 2).sum()

    y_mean    = win.mean(axis=1)
    slope     = ((win - y_mean[:, None]) * (t - t_mean)).sum(axis=1) / t_var
    intercept = y_mean - slope * t_mean
    fitted    = intercept[:, None] + slope[:, None] * t
    resid_sd  = (win - fitted).std(axis=1)

    fit[window - 1:] = intercept + slope * (window - 1)
    sig[window - 1:] = resid_sd
    slp[window - 1:] = slope

    sig_safe = np.where(sig < 1e-12, np.nan, sig)
    resid_z  = np.clip((log_close - fit) / sig_safe, -4, 4)
    return fit, sig, resid_z, slp


# ── shared state frame ────────────────────────────────────────────────────────

def _state_frame(df: pd.DataFrame) -> pd.DataFrame:
    """All intermediate series every model draws from, aligned to df.index."""
    close, high, low = df["close"], df["high"], df["low"]
    vol = df["volume"].fillna(0.0)
    # FX pairs / some indices report no volume — neutralise volume features
    # instead of letting NaNs poison the exhaustion and KNN composites
    vol_ok = bool((vol > 0).mean() >= 0.5)
    out = pd.DataFrame(index=df.index)

    out["close"] = close
    out["ret"]   = close.pct_change()
    out["logp"]  = np.log(close.clip(lower=1e-9))
    out["atr"]   = _atr(df).clip(lower=1e-9)
    out["vol_ann"] = (out["ret"].ewm(span=32, min_periods=32).std()
                      * np.sqrt(ANN)).clip(lower=1e-4)

    # — fair-value channel —
    fit, sig, resid_z, slope = _trend_channel(out["logp"].values, 126)
    out["fv"]       = np.exp(fit)
    out["fv_sig"]   = sig
    out["resid_z"]  = resid_z
    out["fv_slope"] = slope

    # — valuation components (all roughly N(0,1)-scaled, clipped) —
    k20 = _kama(close, window=20)
    k50 = _kama(close, window=50)
    out["kama_gap_z"] = _z((close - k50) / out["atr"])

    roll_max = close.rolling(ANN, min_periods=120).max()
    roll_min = close.rolling(ANN, min_periods=120).min()
    rng      = (roll_max - roll_min).replace(0, np.nan)
    out["range_pos"] = (((close - roll_min) / rng) - 0.5) * 4.0

    rsi14 = _rsi(close, window=14)
    out["rsi14"]   = rsi14
    out["rsi_pct"] = (_pct_rank(rsi14) - 0.5) * 4.0

    up60, _, lo60 = _bollinger(close, window=60, num_std=2.0)
    bw60 = (up60 - lo60).replace(0, np.nan)
    out["bb60"] = ((((close - lo60) / bw60) - 0.5) * 4.0).clip(-3, 3)

    # — CTA forecasts —
    price_vol = (close * out["ret"].ewm(span=32, min_periods=32).std()).clip(lower=1e-9)
    for fast, slow in EWMAC_SPEEDS:
        raw  = (close.ewm(span=fast, adjust=False).mean()
                - close.ewm(span=slow, adjust=False).mean()) / price_vol
        norm = raw / raw.rolling(ANN, min_periods=64).std().replace(0, np.nan)
        norm = norm.clip(-3, 3)
        out[f"ewmac_{fast}"] = norm * np.exp(-norm ** 2 / 4.0) / 0.89

    # — exhaustion components —
    cmp4 = np.sign(close.values - close.shift(4).values)
    td   = np.zeros(len(close))
    run  = 0.0
    for i in range(len(cmp4)):
        d = cmp4[i]
        if not np.isfinite(d) or d == 0:
            run = 0.0
        elif run * d >= 0:
            run += d
        else:
            run = d
        td[i] = np.clip(run, -13, 13)
    out["td"] = td / 6.5                                   # ±2 at the TD-13 cap

    rsi3 = _rsi(close, window=3)
    out["rsi3_x"]   = ((rsi3 - 50.0) / 30.0).clip(-2, 2)
    out["stretch"]  = (_pct_rank((close - k20) / out["atr"]) - 0.5) * 4.0
    if vol_ok:
        vol_z = _z(np.log(vol.clip(lower=1)), 60, min_p=30)
        out["vol_climax"] = (vol_z * np.sign(out["ret"])).clip(-3, 3)
    else:
        out["vol_climax"] = 0.0
    out["ext10"]    = _z(np.log(close / close.shift(10).replace(0, np.nan)))

    # — extra KNN state —
    out["roc20_z"]  = _z(np.log(close / close.shift(20).replace(0, np.nan)))
    out["volp"]     = (_pct_rank(out["vol_ann"]) - 0.5) * 4.0
    if vol_ok:
        vol_ema = vol.ewm(span=20, adjust=False).mean().clip(lower=1)
        out["volume_z"] = _z(np.log((vol / vol_ema).clip(lower=1e-9)), 60, min_p=30)
    else:
        out["volume_z"] = 0.0

    # — squeeze (vol compression, 0 = loose … 100 = maximally coiled) —
    up20, _, lo20 = _bollinger(close, window=20, num_std=2.0)
    bbw_pct  = _pct_rank((up20 - lo20) / close.clip(lower=1e-9))
    vol_pct  = _pct_rank(out["vol_ann"])
    out["squeeze"] = (1.0 - (0.6 * bbw_pct + 0.4 * vol_pct)) * 100.0

    # — composites —
    val_cols = ["resid_z", "kama_gap_z", "range_pos", "rsi_pct", "bb60"]
    out["val_score"] = np.tanh(out[val_cols].clip(-3, 3).mean(axis=1) / 1.6) * 100.0

    exh_z = (0.25 * out["stretch"] + 0.20 * out["rsi3_x"] + 0.20 * out["td"]
             + 0.20 * out["ext10"] + 0.15 * out["vol_climax"])
    out["exh_score"] = np.tanh(exh_z / 1.4) * 100.0

    ew = out[[f"ewmac_{f}" for f, _ in EWMAC_SPEEDS]].mean(axis=1)
    out["cta_fc"]    = ew
    out["cta_score"] = (ew.clip(-0.9, 0.9) / 0.9) * 100.0

    return out


# ── model 1: fair value vs 1-week returns ────────────────────────────────────

VAL_BINS = [(-100, -60, "V.CHEAP"), (-60, -30, "CHEAP"), (-30, -10, "LEAN CHEAP"),
            (-10, 10, "FAIR"), (10, 30, "LEAN RICH"), (30, 60, "RICH"),
            (60, 100, "V.RICH")]


def _fair_value(st: pd.DataFrame) -> dict:
    close = st["close"]
    v     = st["val_score"]
    fwd1w = close.shift(-5) / close - 1.0

    mask  = v.notna() & fwd1w.notna()
    v_h, r_h = v[mask].values, fwd1w[mask].values
    cur_v = float(v.iloc[-1]) if np.isfinite(v.iloc[-1]) else None

    bins, cur_edge = [], None
    for lo, hi, label in VAL_BINS:
        sel = (v_h >= lo) & (v_h < hi) if hi < 100 else (v_h >= lo) & (v_h <= hi)
        n   = int(sel.sum())
        is_cur = cur_v is not None and (lo <= cur_v < hi or (hi == 100 and cur_v == 100))
        mean_r = float(r_h[sel].mean()) if n else None
        if is_cur and n >= 10:
            cur_edge = mean_r
        bins.append({
            "label":   label,
            "lo":      lo, "hi": hi,
            "n":       n,
            "mean":    _fl(mean_r) if n else None,
            "median":  _fl(np.median(r_h[sel])) if n else None,
            "hit":     _fl((r_h[sel] > 0).mean(), 3) if n else None,
            "current": is_cur,
        })

    # chart series — last 252 bars
    tail = st.tail(ANN)
    sig  = tail["fv_sig"]
    fv   = tail["fv"]
    return {
        "score":      _fl(cur_v, 1),
        "edge_1w":    _fl(cur_edge),
        "components": {
            "trend_resid": _fl(st["resid_z"].iloc[-1], 2),
            "kama_gap":    _fl(st["kama_gap_z"].iloc[-1], 2),
            "range_pos":   _fl(st["range_pos"].iloc[-1], 2),
            "rsi_pct":     _fl(st["rsi_pct"].iloc[-1], 2),
            "bb60":        _fl(st["bb60"].iloc[-1], 2),
        },
        "bins": bins,
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
            "close": _fl_list(tail["close"], 4),
            "fv":    _fl_list(fv, 4),
            "up1":   _fl_list(fv * np.exp(sig), 4),
            "dn1":   _fl_list(fv * np.exp(-sig), 4),
            "up2":   _fl_list(fv * np.exp(2 * sig), 4),
            "dn2":   _fl_list(fv * np.exp(-2 * sig), 4),
        },
    }


# ── model 2: KNN analog fan forecast ─────────────────────────────────────────

KNN_FEATURES = ["ewmac_8", "ewmac_16", "ewmac_32", "roc20_z", "rsi_pct",
                "bb60", "volp", "volume_z", "td", "stretch"]


def _knn(st: pd.DataFrame) -> dict | None:
    feats = st[KNN_FEATURES]
    valid = feats.notna().all(axis=1)
    idx_valid = np.where(valid.values)[0]
    n = len(st)
    if len(idx_valid) < 120 or not valid.iloc[-1]:
        return None

    close = st["close"].values
    mat   = feats.values

    train_idx = idx_valid[idx_valid <= n - 1 - KNN_H]
    if len(train_idx) < 100:
        return None

    train = mat[train_idx]
    mu, sd = np.nanmean(train, axis=0), np.nanstd(train, axis=0)
    sd = np.where(sd < 1e-10, 1.0, sd)
    train_n = np.clip((train - mu) / sd, -3, 3)
    query_n = np.clip((mat[n - 1] - mu) / sd, -3, 3)

    dist  = np.sqrt(((train_n - query_n) ** 2).mean(axis=1))
    order = np.argsort(dist)

    # greedy pick, de-overlapping analogs (≥ 6 bars apart)
    picked = []
    for j in order:
        abs_i = int(train_idx[j])
        if all(abs(abs_i - p) >= 6 for p in picked):
            picked.append(abs_i)
        if len(picked) >= KNN_K:
            break
    if len(picked) < 10:
        return None
    picked_d = {p: float(dist[np.where(train_idx == p)[0][0]]) for p in picked}

    # forward paths (simple cumulative returns, h = 1 … KNN_H)
    paths = np.full((len(picked), KNN_H), np.nan)
    for r, i in enumerate(picked):
        fwd = close[i + 1: i + 1 + KNN_H]
        if len(fwd) == KNN_H and close[i] > 0:
            paths[r] = fwd / close[i] - 1.0
    ok = np.isfinite(paths).all(axis=1)
    paths = paths[ok]
    picked = [p for p, k in zip(picked, ok) if k]
    if len(paths) < 10:
        return None

    pcts = {p: np.percentile(paths, p, axis=0) for p in (10, 25, 50, 75, 90)}

    horizons = []
    for h in (5, 10, KNN_H):
        col = paths[:, h - 1]
        horizons.append({
            "h":      h,
            "p_up":   _fl((col > 0).mean(), 3),
            "median": _fl(np.median(col)),
            "q25":    _fl(np.percentile(col, 25)),
            "q75":    _fl(np.percentile(col, 75)),
        })

    # direction score: median 21-bar move in 21-bar-σ units
    sigma21 = float(st["vol_ann"].iloc[-1]) / np.sqrt(ANN) * np.sqrt(KNN_H)
    med21   = float(np.median(paths[:, -1]))
    score   = float(np.clip(med21 / max(sigma21, 1e-6), -1.5, 1.5) / 1.5 * 100.0)

    d_arr  = np.array([picked_d[p] for p in picked])
    d_max  = d_arr.max() if d_arr.max() > 1e-10 else 1.0
    dates  = st.index
    spag   = sorted(range(len(picked)), key=lambda r: d_arr[r])[:10]

    hist = st.tail(60)
    return {
        "k":        len(paths),
        "n_train":  int(len(train_idx)),
        "score":    _fl(score, 1),
        "horizons": horizons,
        "fan":      {str(p): _fl_list(v) for p, v in pcts.items()},
        "history":  {"dates": [d.strftime("%Y-%m-%d") for d in hist.index],
                     "close": _fl_list(hist["close"], 4)},
        "analogs":  [{"date": dates[picked[r]].strftime("%Y-%m-%d"),
                      "sim":  _fl(1.0 - d_arr[r] / d_max, 3),
                      "path": _fl_list(paths[r])} for r in spag],
    }


# ── model 3: CTA trend strategy ───────────────────────────────────────────────

def _cta(st: pd.DataFrame) -> dict:
    ret  = st["ret"]
    fc   = st["cta_fc"]
    pos  = (fc * (0.15 / st["vol_ann"])).clip(-2.0, 2.0)

    strat = (pos.shift(1) * ret - (pos.diff().abs() * 0.0002)).fillna(0.0)
    valid = pos.shift(1).notna()
    strat = strat[valid]
    bh    = ret[valid].fillna(0.0)

    if strat.empty:                      # degenerate input (e.g. flat price)
        none_stats = {"sharpe": None, "cagr": None, "maxdd": None}
        return {"score": None, "position": None,
                "speeds": [{"label": f"EWMAC {f}/{s}", "score": None}
                           for f, s in EWMAC_SPEEDS],
                "stats": {"strategy": dict(none_stats),
                          "buy_hold": dict(none_stats), "hit": None},
                "series": {"dates": [], "equity": [], "bh": [], "forecast": []}}

    eq    = np.exp(np.log1p(strat.clip(lower=-0.99)).cumsum()) * 100.0
    eq_bh = np.exp(np.log1p(bh.clip(lower=-0.99)).cumsum()) * 100.0

    def _stats(r: pd.Series, e: np.ndarray) -> dict:
        sd = r.std()
        yrs = max(len(r) / ANN, 1e-9)
        return {
            "sharpe": _fl(r.mean() / sd * np.sqrt(ANN), 2) if sd > 1e-12 else None,
            "cagr":   _fl((e[-1] / e[0]) ** (1 / yrs) - 1.0) if len(e) > 1 else None,
            "maxdd":  _fl(_max_drawdown(e)),
        }

    tail_n = min(504, len(eq))
    dates  = strat.index[-tail_n:]
    cur_fc = float(st["cta_score"].iloc[-1]) if np.isfinite(st["cta_score"].iloc[-1]) else None

    return {
        "score":    _fl(cur_fc, 1),
        "position": _fl(pos.iloc[-1], 2),
        "speeds": [{"label": f"EWMAC {f}/{s}",
                    "score": _fl(np.clip(st[f"ewmac_{f}"].iloc[-1], -0.9, 0.9) / 0.9 * 100, 1)}
                   for f, s in EWMAC_SPEEDS],
        "stats":    {"strategy": _stats(strat, eq.values),
                     "buy_hold": _stats(bh, eq_bh.values),
                     "hit":      _fl((strat[strat != 0] > 0).mean(), 3)},
        "series": {
            "dates":    [d.strftime("%Y-%m-%d") for d in dates],
            "equity":   _fl_list(eq.values[-tail_n:] / eq.values[-tail_n] * 100.0, 2),
            "bh":       _fl_list(eq_bh.values[-tail_n:] / eq_bh.values[-tail_n] * 100.0, 2),
            "forecast": _fl_list(st["cta_score"].reindex(dates), 1),
        },
    }


# ── model 4: exhaustion ───────────────────────────────────────────────────────

def _exhaustion(st: pd.DataFrame) -> dict:
    e     = st["exh_score"]
    close = st["close"]
    fwd5  = close.shift(-5) / close - 1.0
    fwd21 = close.shift(-21) / close - 1.0

    # event detection: |E| ≥ 70, 10-bar cool-off
    ev_idx, ev_side = [], []
    last = -10_000
    e_arr = e.values
    for i in range(len(e_arr)):
        if np.isfinite(e_arr[i]) and abs(e_arr[i]) >= 70 and i - last >= 10:
            ev_idx.append(i)
            ev_side.append(1 if e_arr[i] > 0 else -1)
            last = i

    def _ev_stats(side: int) -> dict:
        sel = [i for i, s in zip(ev_idx, ev_side) if s == side]
        f5  = fwd5.values[sel];  f5 = f5[np.isfinite(f5)]
        f21 = fwd21.values[sel]; f21 = f21[np.isfinite(f21)]
        return {
            "n":     len(sel),
            "fwd5":  _fl(f5.mean()) if len(f5) else None,
            "fwd21": _fl(f21.mean()) if len(f21) else None,
            "hit5":  _fl((f5 > 0).mean(), 3) if len(f5) else None,
        }

    base5, base21 = fwd5.dropna(), fwd21.dropna()
    tail_n = min(504, len(st))
    tail   = st.tail(tail_n)
    start  = len(st) - tail_n
    events = [{"i": i - start,
               "date": st.index[i].strftime("%Y-%m-%d"),
               "side": s,
               "price": _fl(close.iloc[i], 4)}
              for i, s in zip(ev_idx, ev_side) if i >= start]

    return {
        "score": _fl(e.iloc[-1], 1),
        "components": {
            "stretch":    _fl(st["stretch"].iloc[-1], 2),
            "rsi3":       _fl(st["rsi3_x"].iloc[-1], 2),
            "td_count":   _fl(st["td"].iloc[-1] * 6.5, 0),
            "ext10":      _fl(st["ext10"].iloc[-1], 2),
            "vol_climax": _fl(st["vol_climax"].iloc[-1], 2),
        },
        "stats": {
            "blowoff":      _ev_stats(1),
            "capitulation": _ev_stats(-1),
            "base": {"fwd5":  _fl(base5.mean()) if len(base5) else None,
                     "fwd21": _fl(base21.mean()) if len(base21) else None},
        },
        "events": events,
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
            "close": _fl_list(tail["close"], 4),
            "e":     _fl_list(tail["exh_score"], 1),
        },
    }


# ── model 5: squeeze (volatility compression) ────────────────────────────────

def _squeeze(st: pd.DataFrame) -> dict:
    sq    = st["squeeze"]
    close = st["close"]
    fwd21 = close.shift(-21) / close - 1.0
    trend = st["ewmac_16"]

    # compression episodes: score crosses up through 85, 21-bar cool-off
    sq_arr = sq.values
    ev_idx = []
    last = -10_000
    for i in range(1, len(sq_arr)):
        if (np.isfinite(sq_arr[i]) and sq_arr[i] >= 85
                and (sq_arr[i - 1] < 85 or not np.isfinite(sq_arr[i - 1]))
                and i - last >= 21):
            ev_idx.append(i)
            last = i

    f21   = fwd21.values
    tr    = trend.values
    moves = np.array([f21[i] for i in ev_idx if np.isfinite(f21[i])])
    agree = np.array([np.sign(f21[i]) == np.sign(tr[i])
                      for i in ev_idx
                      if np.isfinite(f21[i]) and np.isfinite(tr[i]) and tr[i] != 0])
    base  = fwd21.dropna()

    tail_n = min(504, len(st))
    tail   = st.tail(tail_n)
    start  = len(st) - tail_n
    events = [{"i": i - start,
               "date": st.index[i].strftime("%Y-%m-%d"),
               "price": _fl(close.iloc[i], 4)}
              for i in ev_idx if i >= start]

    cur_trend = float(tr[-1]) if np.isfinite(tr[-1]) else 0.0
    return {
        "score":      _fl(sq.iloc[-1], 1),                 # 0 … 100
        "trend_side": "LONG" if cur_trend > 0 else "SHORT" if cur_trend < 0 else "FLAT",
        "stats": {
            "n_events":   len(ev_idx),
            "ev_abs_1m":  _fl(np.abs(moves).mean()) if len(moves) else None,
            "base_abs_1m": _fl(base.abs().mean()) if len(base) else None,
            "dir_agree":  _fl(agree.mean(), 3) if len(agree) else None,
        },
        "events": events,
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
            "close": _fl_list(tail["close"], 4),
            "sq":    _fl_list(tail["squeeze"], 1),
        },
    }


# ── model 6: mean reversion & character ──────────────────────────────────────

def _mean_reversion(st: pd.DataFrame) -> dict | None:
    logp = st["logp"].values
    fv   = st["fv"].values
    with np.errstate(invalid="ignore"):
        resid = logp - np.log(np.where(fv > 0, fv, np.nan))

    ok = np.isfinite(resid)
    if ok.sum() < 200:
        return None
    r_tail = resid[ok][-504:]

    # AR(1):  Δx_t = a + b·x_{t-1}   →  φ = 1 + b
    x, dx = r_tail[:-1], np.diff(r_tail)
    var_x = x.var()
    if var_x < 1e-14:
        return None
    b   = np.cov(x, dx)[0, 1] / var_x
    phi = 1.0 + b
    half_life = float(-np.log(2) / np.log(phi)) if 0 < phi < 1 else None

    # Hurst exponent: slope of log σ(q-bar returns) vs log q
    lp = st["logp"].values[-504:]
    qs, sds = [], []
    for q in (1, 2, 4, 8, 16):
        d = lp[q:] - lp[:-q]
        d = d[np.isfinite(d)]
        if len(d) > 30 and d.std() > 1e-12:
            qs.append(np.log(q))
            sds.append(np.log(d.std()))
    hurst = float(np.polyfit(qs, sds, 1)[0]) if len(qs) >= 3 else None

    r1 = np.diff(lp)
    r1 = r1[np.isfinite(r1)]
    d10 = lp[10:] - lp[:-10]
    d10 = d10[np.isfinite(d10)]
    vr10 = (float(d10.var() / (10 * r1.var()))
            if len(r1) > 50 and r1.var() > 1e-14 else None)

    character = ("MEAN-REVERTING" if (hurst is not None and hurst < 0.45
                                      and half_life is not None) else
                 "TRENDING" if (hurst is not None and hurst > 0.55) else "MIXED")

    # reversion hit rate: after |z| ≥ 2, was |z| smaller 21 bars later?
    z = st["resid_z"].values
    hits, n_ev, last = 0, 0, -10_000
    for i in range(len(z) - 21):
        if np.isfinite(z[i]) and abs(z[i]) >= 2.0 and i - last >= 10:
            last = i
            if np.isfinite(z[i + 21]):
                n_ev += 1
                hits += abs(z[i + 21]) < abs(z[i])
    revert_hit = hits / n_ev if n_ev else None

    # 21-bar projection: residual decays at φ, fair value drifts at slope
    cur_resid = float(resid[ok][-1])
    slope     = float(st["fv_slope"].iloc[-1]) if np.isfinite(st["fv_slope"].iloc[-1]) else 0.0
    log_fv0   = float(np.log(fv[-1])) if np.isfinite(fv[-1]) and fv[-1] > 0 else None
    proj, fv_path = [], []
    if log_fv0 is not None and half_life is not None:
        for h in range(1, 22):
            fv_h = log_fv0 + slope * h
            fv_path.append(np.exp(fv_h))
            proj.append(np.exp(fv_h + cur_resid * phi ** h))

    # direction kicker: expected 21-bar move from residual decay, in σ21 units
    score = 0.0
    if half_life is not None and half_life <= 126:
        exp_ret = np.exp(cur_resid * (phi ** 21 - 1.0)) - 1.0
        sigma21 = float(st["vol_ann"].iloc[-1]) / np.sqrt(ANN) * np.sqrt(21)
        score   = float(np.clip(exp_ret / max(sigma21, 1e-6), -1.5, 1.5) / 1.5 * 100.0)

    tail = st.tail(ANN)
    return {
        "score":      _fl(score, 1),
        "character":  character,
        "phi":        _fl(phi, 3),
        "half_life":  _fl(half_life, 1),
        "hurst":      _fl(hurst, 2),
        "vr10":       _fl(vr10, 2),
        "resid_z":    _fl(st["resid_z"].iloc[-1], 2),
        "revert_hit": _fl(revert_hit, 3),
        "n_stretch_events": n_ev,
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
            "close": _fl_list(tail["close"], 4),
            "fv":    _fl_list(tail["fv"], 4),
            "proj":    _fl_list(proj, 4),
            "fv_path": _fl_list(fv_path, 4),
        },
    }



def _composite(st: pd.DataFrame, fv: dict, knn: dict | None,
               cta: dict, exh: dict, mr: dict | None) -> dict:
    val = fv.get("score")
    cta_s = cta.get("score") or 0.0
    knn_s = (knn or {}).get("score") or 0.0
    e     = exh.get("score") or 0.0
    mr_s  = (mr or {}).get("score") or 0.0

    # exhaustion kicker: contrarian, only meaningful at extremes
    exh_kick = -e * (abs(e) / 100.0) ** 2

    direction = float(np.clip(0.45 * cta_s + 0.25 * knn_s
                              + 0.15 * exh_kick + 0.15 * mr_s, -100, 100))

    # conviction: how many of {CTA, KNN, MR, valuation-edge} agree with the call
    votes, agree = 0, 0
    edge = fv.get("edge_1w")
    for sig in (cta_s, knn_s, mr_s,
                (edge or 0.0) * 1e4 if edge is not None else None):
        if sig is None or abs(sig) < 1e-9:
            continue
        votes += 1
        if np.sign(sig) == np.sign(direction or 1):
            agree += 1
    conviction = ("HIGH" if votes >= 2 and agree == votes else
                  "MED" if votes >= 2 and agree >= votes - 1 else "LOW")

    return {
        "valuation":  _fl(val, 1),
        "direction":  _fl(direction, 1),
        "conviction": conviction,
        "components": {
            "cta":      _fl(cta_s, 1),
            "knn":      _fl(knn_s, 1),
            "exh_kick": _fl(exh_kick, 1),
            "mr":       _fl(mr_s, 1),
            "fv_edge_1w": _fl(edge),
        },
    }


# ── public entry point ────────────────────────────────────────────────────────

def compute_quant_lab(symbol: str) -> dict:
    return cache.get_or_compute("quant_lab", symbol, "daily",
                                lambda: _compute_inner(symbol))


def _compute_inner(symbol: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=2500)
    if df.empty:
        return {"error": "No OHLCV data — fetch the symbol first"}
    if len(df) < MIN_BARS:
        return {"error": f"Need ≥ {MIN_BARS} daily bars, got {len(df)}"}

    st = _state_frame(df)

    fv  = _fair_value(st)
    knn = _knn(st)
    cta = _cta(st)
    exh = _exhaustion(st)
    sqz = _squeeze(st)
    mr  = _mean_reversion(st)

    return {
        "symbol":     symbol,
        "as_of":      st.index[-1].strftime("%Y-%m-%d"),
        "last_close": _fl(st["close"].iloc[-1], 4),
        "n_bars":     int(len(st)),
        "composite":  _composite(st, fv, knn, cta, exh, mr),
        "fair_value": fv,
        "knn":        knn,
        "cta":        cta,
        "exhaustion": exh,
        "squeeze":    sqz,
        "mean_reversion": mr,
    }
