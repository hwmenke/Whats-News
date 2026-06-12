"""
fair_value_lab.py — fair-value divergence models with walk-forward validation.

The question this module answers: "the price is X% away from a model fair
value — does that actually predict the price moving BACK?"

Anchor models
─────────────
trend   Rolling 126-bar log-linear trend channel (causal: each bar's fair
        value uses only the past 126 bars).  Simple, but the anchor partly
        follows price — the validation below tells you how much.

pca     Avellaneda-Lee style statistical-arbitrage anchor.  Watchlist log
        returns → PCA eigenportfolios (estimated on a trailing 252-bar
        window, refit monthly, applied strictly out-of-window) → the
        symbol's factor-implied return.  The 63-bar cumulative residual,
        re-centred on its trailing mean, is the divergence; fair value is
        price with the divergence removed.  Because the anchor is built
        from OTHER assets' comovement, it cannot mechanically chase the
        target's own price.

Forecast & validation (both models, fully causal)
─────────────────────────────────────────────────
For h ∈ {5, 21} bars an expanding-window OLS of forward h-bar log return on
the divergence z-score is refit every 21 bars; predictions are only ever
made with coefficients estimated on data ending ≥ h bars earlier.  Reported
out-of-sample:

    ic           Pearson corr(prediction, realised) on the OOS region
    slope        last fitted response (should be negative: rich → down)
    hit rate     after |z| ≥ 2 events (10-bar cool-off), how often price
                 moved toward the anchor over the horizon
    price share  when the gap closed, the fraction closed by PRICE moving
                 to the model rather than the model moving to price —
                 the direct answer to "is the anchor just following?"

Verdict: STRONG / OK / WEAK from the 1-month hit rate and price share.
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np
import pandas as pd

import database as db
import indicator_cache as cache
from quant_lab import _trend_channel, _fl, _fl_list

ANN        = 252
MIN_BARS   = 420
HORIZONS   = (5, 21)
SERIES_N   = 378          # bars sent for the chart panels (~18 months)
DIST_N     = 504          # divergence sample for the distribution panel

PCA_WINDOW = 252          # estimation window for eigenportfolios
PCA_REFIT  = 21           # refit cadence (bars)
PCA_K      = 3            # number of principal components
PCA_SPREAD = 63           # cumulative-residual window (the spread)
PCA_MIN_SYMBOLS = 8
PCA_MIN_OVERLAP = 600


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── anchors ───────────────────────────────────────────────────────────────────
# Each returns (fv_log, sigma_log, meta) aligned to the input frame, where
# divergence D = log(price) − fv_log and sigma_log is the local σ of D.

def _trend_anchor(logp: np.ndarray):
    fit, sig, _, _ = _trend_channel(logp, 126)
    return fit, sig, {"anchor": "126-bar log-linear trend channel"}


# PCA panels of watchlist log prices, memoised for 10 minutes per scope.
# Scopes: the whole watchlist, or a sector (symbols sharing a group_tag) —
# sector panels give sharper residuals when enough peers exist.
# The lock matters: the signal scanner calls pca_divergence() from a thread
# pool, and without it every worker would rebuild the panel simultaneously.
_PANEL_MEMO: dict = {}            # scope key → {"ts", "panel"}
_PANEL_LOCK = threading.Lock()
PCA_MIN_SECTOR = 6                # sector panels may be smaller than watchlist


def _build_pca_panel(symbols: list[str] | None = None, key: str = "__ALL__",
                     min_symbols: int = PCA_MIN_SYMBOLS) -> pd.DataFrame | None:
    with _PANEL_LOCK:
        return _build_pca_panel_locked(symbols, key, min_symbols)


def _build_pca_panel_locked(symbols, key, min_symbols) -> pd.DataFrame | None:
    now = time.time()
    memo = _PANEL_MEMO.get(key)
    if memo is not None and now - memo["ts"] < 600:
        return memo["panel"]

    universe = symbols if symbols is not None else \
        [row["symbol"] for row in db.list_symbols()]
    series = {}
    for sym in universe[:60]:
        df = db.get_ohlcv_df(sym, "daily", limit=1300)
        if len(df) >= PCA_MIN_OVERLAP:
            series[sym] = np.log(df["close"].clip(lower=1e-9))

    panel = None
    if series:
        joined = pd.DataFrame(series)                      # outer join on dates
        # drop STALE symbols (no data near the panel's most recent date)
        # rather than letting them truncate everyone else's recent history
        last  = {c: joined[c].last_valid_index() for c in joined.columns}
        max_d = max(last.values())
        fresh = [c for c in joined.columns if (max_d - last[c]).days <= 7]
        panel = joined[fresh].dropna()
        if panel.shape[0] < PCA_MIN_OVERLAP or panel.shape[1] < min_symbols:
            panel = None
        elif panel.shape[1] > 40:
            panel = panel.iloc[:, :40]

    _PANEL_MEMO[key] = {"ts": now, "panel": panel}
    return panel


def _panel_for(symbol: str):
    """Pick the tightest valid panel for `symbol`: its sector (group_tag)
    when ≥ PCA_MIN_SECTOR fresh peers exist, else the whole watchlist.
    Returns (panel | None, scope_label)."""
    groups = {row["symbol"]: (row.get("group_tag") or "")
              for row in db.list_symbols()}
    tag = groups.get(symbol, "")
    if tag:
        peers = [s for s, t in groups.items() if t == tag]
        if len(peers) >= PCA_MIN_SECTOR:
            panel = _build_pca_panel(peers, key=f"grp:{tag}",
                                     min_symbols=PCA_MIN_SECTOR)
            if panel is not None and symbol in panel.columns:
                return panel, f"sector:{tag}"
    return _build_pca_panel(), "watchlist"


def _pca_residuals(panel: pd.DataFrame, symbol: str) -> np.ndarray | None:
    """Out-of-window residual returns of `symbol` vs PCA eigenportfolios.

    The target is EXCLUDED from factor construction — otherwise its own
    idiosyncratic moves leak into the "factor-implied" return and the anchor
    chases the price (the exact failure mode this lab is built to expose).
    """
    R_all = panel.diff().iloc[1:].values         # (n, m) log returns
    ti = list(panel.columns).index(symbol)
    y  = R_all[:, ti]
    R  = np.delete(R_all, ti, axis=1)            # peers only
    n  = len(R)
    if n < PCA_WINDOW + PCA_REFIT:
        return None

    resid = np.full(n, np.nan)
    for t0 in range(PCA_WINDOW, n, PCA_REFIT):
        est = R[t0 - PCA_WINDOW: t0]
        sd  = est.std(axis=0)
        sd[sd < 1e-12] = 1.0
        Z   = (est - est.mean(axis=0)) / sd
        C   = Z.T @ Z / (PCA_WINDOW - 1)
        _, V = np.linalg.eigh(C)
        Q   = (V[:, ::-1][:, :PCA_K]) / sd[:, None]      # eigenportfolio weights

        F_est = est @ Q                                  # factor returns, est window
        A     = np.c_[np.ones(len(F_est)), F_est]
        beta, *_ = np.linalg.lstsq(A, y[t0 - PCA_WINDOW: t0], rcond=None)

        # residual keeps the idiosyncratic drift (intercept is used only to
        # de-bias the beta fit) — otherwise a persistent run-up would be
        # absorbed into the anchor and the model would chase the price
        seg = slice(t0, min(t0 + PCA_REFIT, n))          # strictly out-of-window
        resid[seg] = y[seg] - (R[seg] @ Q) @ beta[1:]
    return resid


def _pca_anchor(symbol: str, df: pd.DataFrame):
    panel, scope = _panel_for(symbol)
    if panel is None:
        return None, None, {"error": f"PCA needs ≥ {PCA_MIN_SYMBOLS} watchlist symbols "
                                     f"with ≥ {PCA_MIN_OVERLAP} shared daily bars"}
    if symbol not in panel.columns:
        return None, None, {"error": f"{symbol} lacks {PCA_MIN_OVERLAP} bars overlapping the watchlist panel"}

    resid = _pca_residuals(panel, symbol)
    if resid is None:
        return None, None, {"error": "not enough overlapping history for PCA estimation"}

    # spread = trailing cumulative residual, re-centred on its trailing mean
    S   = pd.Series(resid).rolling(PCA_SPREAD, min_periods=40).sum()
    mu  = S.rolling(ANN, min_periods=126).mean()
    sd  = S.rolling(ANN, min_periods=126).std()
    D   = (S - mu).values
    sig = sd.values

    # align panel dates (offset by 1 from diff) onto the symbol's own frame
    dates  = panel.index[1:]
    d_ser  = pd.Series(D, index=dates).reindex(df.index)
    s_ser  = pd.Series(sig, index=dates).reindex(df.index)
    logp   = np.log(df["close"].clip(lower=1e-9)).values
    fv_log = logp - d_ser.values
    meta = {"anchor": f"PCA({PCA_K}) eigenportfolio factor anchor",
            "panel_scope": scope,
            "universe": list(panel.columns), "n_universe": panel.shape[1]}
    return fv_log, s_ser.values, meta


# ── walk-forward forecast & validation ───────────────────────────────────────

def _wf_predictions(logp: np.ndarray, z: np.ndarray, h: int,
                    min_train: int = 378, refit: int = 21):
    """Expanding-window OLS of fwd h-bar return on z; strictly causal."""
    n    = len(logp)
    fwd  = np.full(n, np.nan)
    fwd[: n - h] = logp[h:] - logp[: n - h]
    pred = np.full(n, np.nan)
    last_fit = None
    for t0 in range(min_train, n, refit):
        zz, yy = z[: t0 - h], fwd[: t0 - h]          # fwd known by t0
        m = np.isfinite(zz) & np.isfinite(yy)
        if m.sum() < 120:
            continue
        slope, intercept = np.polyfit(zz[m], yy[m], 1)
        last_fit = (slope, intercept)
        seg = slice(t0, min(t0 + refit, n))
        pred[seg] = intercept + slope * z[seg]
    return pred, fwd, last_fit


def _events(z: np.ndarray, thresh: float = 2.0, cooloff: int = 10) -> list[int]:
    out, last = [], -10_000
    for i in range(len(z)):
        if np.isfinite(z[i]) and abs(z[i]) >= thresh and i - last >= cooloff:
            out.append(i)
            last = i
    return out


def _validate_horizon(logp, z, h) -> dict:
    pred, fwd, last_fit = _wf_predictions(logp, z, h)
    m = np.isfinite(pred) & np.isfinite(fwd)
    ic = (float(np.corrcoef(pred[m], fwd[m])[0, 1])
          if m.sum() > 60 and pred[m].std() > 1e-12 else None)

    ev    = [i for i in _events(z) if np.isfinite(pred[i]) and i + h < len(logp)
             and np.isfinite(fwd[i])]
    hits  = [np.sign(fwd[i]) == -np.sign(z[i]) for i in ev]
    longs  = [fwd[i] for i in ev if z[i] <= -2.0]
    shorts = [fwd[i] for i in ev if z[i] >= 2.0]

    fcast = None
    if last_fit is not None and np.isfinite(z[-1]):
        fcast = float(np.expm1(last_fit[1] + last_fit[0] * z[-1]))

    return {
        "h":          h,
        "ic":         _fl(ic, 3),
        "slope":      _fl(last_fit[0], 5) if last_fit else None,
        "n_events":   len(ev),
        "hit":        _fl(np.mean(hits), 3) if hits else None,
        "mean_cheap": _fl(np.expm1(np.mean(longs))) if longs else None,
        "mean_rich":  _fl(np.expm1(np.mean(shorts))) if shorts else None,
        "forecast":   _fl(fcast),
    }


def _price_share(logp: np.ndarray, fv_log: np.ndarray, z: np.ndarray,
                 h: int = 21) -> dict:
    """Of the gap closed after |z| ≥ 2 events, how much was PRICE moving to
    the model (vs the model moving to price)?"""
    D = logp - fv_log
    price_work, total_work, n_conv, n_ev = 0.0, 0.0, 0, 0
    for i in _events(z):
        if i + h >= len(logp) or not (np.isfinite(D[i]) and np.isfinite(D[i + h])):
            continue
        n_ev += 1
        if abs(D[i + h]) >= abs(D[i]):
            continue                                   # gap did not close
        n_conv += 1
        sgn = np.sign(D[i])
        price_contrib  = -sgn * (logp[i + h] - logp[i])         # price toward anchor
        anchor_contrib =  sgn * (fv_log[i + h] - fv_log[i])     # anchor toward price
        closed = price_contrib + anchor_contrib                 # = |D_i| − ±|D_i+h|
        if closed > 1e-12:
            price_work += max(price_contrib, 0.0)
            total_work += closed
    return {
        "n_events":    n_ev,
        "n_converged": n_conv,
        "conv_rate":   _fl(n_conv / n_ev, 3) if n_ev else None,
        "price_share": _fl(min(price_work / total_work, 1.0), 3) if total_work > 1e-12 else None,
    }


def _verdict(v21: dict, ps: dict) -> str:
    hit, share = v21.get("hit"), ps.get("price_share")
    if hit is None or share is None or v21.get("n_events", 0) < 8:
        return "INSUFFICIENT"
    if hit >= 0.60 and share >= 0.55:
        return "STRONG"
    if hit >= 0.52 and share >= 0.40:
        return "OK"
    return "WEAK"


# ── public entry point ────────────────────────────────────────────────────────

def compute_fair_value(symbol: str, model: str = "trend") -> dict:
    return cache.get_or_compute("fair_value", symbol, "daily",
                                lambda: _compute_inner(symbol, model),
                                model=model)


def _compute_inner(symbol: str, model: str) -> dict:
    df = db.get_ohlcv_df(symbol, "daily", limit=2000)
    if df.empty or len(df) < MIN_BARS:
        return {"error": f"Need ≥ {MIN_BARS} daily bars, got {len(df)}"}

    logp = np.log(df["close"].clip(lower=1e-9)).values

    if model == "pca":
        fv_log, sigma, meta = _pca_anchor(symbol, df)
        if fv_log is None:
            return {"error": meta["error"]}
    else:
        fv_log, sigma, meta = _trend_anchor(logp)

    sigma = np.where(np.asarray(sigma, dtype=float) < 1e-9, np.nan, sigma)
    D = logp - fv_log
    z = np.clip(D / sigma, -6, 6)
    if not np.isfinite(z[-1]):
        return {"error": "divergence undefined on the latest bar "
                         "(degenerate price series or insufficient overlap)"}

    # — validation —
    v = {f"h{h}": _validate_horizon(logp, z, h) for h in HORIZONS}
    ps = _price_share(logp, fv_log, z, 21)
    verdict = _verdict(v["h21"], ps)

    # — current state —
    z_hist = z[np.isfinite(z)][-DIST_N:]
    z_now  = float(z[-1])
    pct_emp  = float((z_hist < z_now).mean())
    mu_h, sd_h = float(z_hist.mean()), float(z_hist.std())
    pct_norm = _norm_cdf((z_now - mu_h) / sd_h) if sd_h > 1e-9 else None

    # — chart series (last SERIES_N bars) —
    tail   = slice(max(0, len(df) - SERIES_N), len(df))
    fv_t   = fv_log[tail]
    sig_t  = sigma[tail]
    close_t = df["close"].values[tail]

    return {
        "symbol":     symbol,
        "model":      model,
        "as_of":      df.index[-1].strftime("%Y-%m-%d"),
        "last_close": _fl(close_t[-1], 4),
        "n_bars":     int(len(df)),
        "meta":       {k: v2 for k, v2 in meta.items() if k != "universe"},
        "universe":   meta.get("universe"),
        "current": {
            "z":        _fl(z_now, 2),
            "gap_pct":  _fl(float(np.expm1(D[-1])), 4),      # price vs FV, %
            "pct_emp":  _fl(pct_emp, 4),
            "pct_norm": _fl(pct_norm, 4),
            "fcast_1w": v["h5"]["forecast"],
            "fcast_1m": v["h21"]["forecast"],
        },
        "validation": {"h5": v["h5"], "h21": v["h21"],
                       "price_work": ps, "verdict": verdict},
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in df.index[tail]],
            "close": _fl_list(close_t, 4),
            "fv":    _fl_list(np.exp(fv_t), 4),
            "up1":   _fl_list(np.exp(fv_t + sig_t), 4),
            "dn1":   _fl_list(np.exp(fv_t - sig_t), 4),
            "up2":   _fl_list(np.exp(fv_t + 2 * sig_t), 4),
            "dn2":   _fl_list(np.exp(fv_t - 2 * sig_t), 4),
            "z":     _fl_list(z[tail], 3),
        },
        "dist": {"z_hist": _fl_list(z_hist, 3), "mu": _fl(mu_h, 3), "sd": _fl(sd_h, 3)},
    }


# ── light-weight hook for the signal scanner ─────────────────────────────────

def pca_divergence(symbol: str) -> dict | None:
    """Current PCA divergence z for `symbol`, or None if unavailable."""
    panel, _scope = _panel_for(symbol)
    if panel is None or symbol not in panel.columns:
        return None
    resid = _pca_residuals(panel, symbol)
    if resid is None:
        return None
    S  = pd.Series(resid).rolling(PCA_SPREAD, min_periods=40).sum()
    mu = S.rolling(ANN, min_periods=126).mean()
    sd = S.rolling(ANN, min_periods=126).std()
    z  = float(((S - mu) / sd.replace(0, np.nan)).iloc[-1])
    if not np.isfinite(z):
        return None
    return {"z": z, "n_universe": panel.shape[1]}
