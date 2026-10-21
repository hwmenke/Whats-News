"""Quant Risk SPEC lock — 2026-09-04.

Formulas from the ship lock (file was not on disk at start; path is still
the cited source). Do not invent P&L, z, or FLAG cutoffs that are not listed.

Locks:
1) VaR 95 & 99 — parametric Gaussian μ=0 (60d Σ) + historical empirical
   quantile (N≥60, prefer 252); label method; 1d horizon
2) MVaR = z·(Σw)_i/σ·MV; CVaR = w_i·MVaR (Euler, Σ CVaR = VaR);
   % of port VaR; IVaR = VaR − VaR without i (renorm); rank by %VaR
3) Vol: show 20d & 60d ann √252 ddof=1; cov/VaR use 60d
4) Perf: day/week/MTD/YTD, max DD, Sharpe/Sortino rf=0; blank if short;
   synthetic NAV labeled if no true equity curve
5) Per-name: w, σ, β_SPY 60d, MVaR/CVaR/%VaR, FLAG
   (CONC / HIGH_BETA / VOL_SPIKE / THIN / SHORT)
6) Clusters: σ20 vs σ60 HOT/COLD; hier. avg linkage on d=√(0.5(1−ρ)),
   cut 0.7; cluster %VaR
7) Thin: <3 names or <60 overlap days or singular cov → blank stack

Paper / Yahoo stored closes only. No live orders.
"""

from __future__ import annotations

import math
import os
import numpy as np

SPEC_PATH = "/workspace/whats-news-risk-SPEC-2026-09-04.md"
# Standard normal quantiles — same z the desk already uses for Gaussian VaR.
Z95 = 1.6448536269514722
Z99 = 2.3263478740408408
MIN_NAMES = 3
MIN_OVERLAP = 60
HIST_PREF = 252
COV_N = 60
VOL_SHORT = 20
ANN = math.sqrt(252.0)
CLUSTER_CUT = 0.7
# CONC uses the already-documented book concentration threshold (not a new cutoff).
CONC_WEIGHT_PCT = 25.0
SINGULAR_EIG = 1e-14

SPEC_NOTE = (
    "1-day horizon. Parametric: Gaussian μ=0, 60d sample Σ (ddof=1). "
    "Historical: empirical quantile, N≥60 prefer 252. "
    "MVaR = z·(Σw)_i/σ·MV; CVaR = w_i·MVaR (Euler). "
    "Vol 20d/60d ann √252 ddof=1; cov/VaR use 60d. "
    f"Source: {SPEC_PATH}"
)

THIN_NOTE = (
    "Thin book — Risk stack blank. Need ≥3 marked names, ≥60 overlapping "
    "daily returns, and a non-singular 60d covariance. Never invented."
)


def spec_source() -> str:
    if os.path.isfile(SPEC_PATH):
        return SPEC_PATH
    return f"{SPEC_PATH} (locks as shipped; file not readable at compute time)"


def _finite(val):
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _round(val, digits=4):
    num = _finite(val)
    if num is None:
        return None
    return round(num, digits)


def blank_stack(*, reason: str, n_names: int = 0, overlap: int = 0) -> dict:
    return {
        "ready": False,
        "source": spec_source(),
        "note": SPEC_NOTE,
        "message": reason,
        "thin": True,
        "n_names": n_names,
        "overlap_days": overlap,
        "horizon": "1d",
        "cov_window": COV_N,
        "var": {},
        "vol": {"vol_20": None, "vol_60": None},
        "perf": {
            "day": None, "week": None, "mtd": None, "ytd": None,
            "max_dd_pct": None, "sharpe": None, "sortino": None,
            "n": 0, "curve_kind": None,
        },
        "names": [],
        "ranked": [],
        "clusters": [],
        "euler": {"param_95_ok": None, "cvar_sum_95": None, "var_95": None},
    }


def _closes_map(closes: list) -> dict[str, float]:
    out = {}
    for row in closes or []:
        if not row:
            continue
        date, px = row[0], _finite(row[1])
        if date and px is not None and px > 0:
            out[str(date)[:10]] = px
    return out


def _simple_returns(px_by_date: dict[str, float]) -> dict[str, float]:
    dates = sorted(px_by_date)
    out = {}
    for i in range(1, len(dates)):
        a, b = px_by_date[dates[i - 1]], px_by_date[dates[i]]
        if a and a > 0:
            r = b / a - 1.0
            if math.isfinite(r):
                out[dates[i]] = r
    return out


def _ann_vol(rets: np.ndarray) -> float | None:
    if rets is None or len(rets) < 2:
        return None
    sig = float(np.std(rets, ddof=1))
    if sig <= 0 or not math.isfinite(sig):
        return None
    return sig * ANN


def _is_singular(cov: np.ndarray) -> bool:
    if cov.size == 0 or cov.shape[0] != cov.shape[1]:
        return True
    if not np.all(np.isfinite(cov)):
        return True
    try:
        evals = np.linalg.eigvalsh(cov)
    except np.linalg.LinAlgError:
        return True
    if evals.size == 0:
        return True
    mx = float(np.max(np.abs(evals)))
    mn = float(np.min(evals))
    if not math.isfinite(mn) or not math.isfinite(mx):
        return True
    if mn <= SINGULAR_EIG * max(mx, 1.0):
        return True
    try:
        sign, logdet = np.linalg.slogdet(cov)
    except np.linalg.LinAlgError:
        return True
    if sign <= 0 or not math.isfinite(logdet):
        return True
    return False


def _hist_var_frac(rets: np.ndarray, alpha: float) -> float | None:
    """Positive loss fraction: −empirical quantile. N already checked."""
    if len(rets) < MIN_OVERLAP:
        return None
    q = float(np.quantile(rets, alpha))
    if not math.isfinite(q):
        return None
    return -q


def _max_dd(nav: np.ndarray) -> float | None:
    if nav is None or len(nav) < 10:
        return None
    peak = nav[0]
    worst = 0.0
    for x in nav:
        if not math.isfinite(x):
            continue
        if x > peak:
            peak = x
        if abs(peak) <= 1e-12:
            continue
        dd = (x - peak) / abs(peak) * 100.0
        if dd < worst:
            worst = dd
    return worst


def _sharpe(rets: np.ndarray) -> float | None:
    if rets is None or len(rets) < MIN_OVERLAP:
        return None
    sig = float(np.std(rets, ddof=1))
    if sig <= 0 or not math.isfinite(sig):
        return None
    mu = float(np.mean(rets))
    return (mu / sig) * ANN


def _sortino(rets: np.ndarray) -> float | None:
    if rets is None or len(rets) < MIN_OVERLAP:
        return None
    mu = float(np.mean(rets))
    downside = rets[rets < 0.0]
    if len(downside) < 2:
        return None
    dsig = float(np.std(downside, ddof=1))
    if dsig <= 0 or not math.isfinite(dsig):
        return None
    return (mu / dsig) * ANN


def _perf_window(curve: list[dict], *, kind: str) -> float | None:
    if not curve or len(curve) < 2:
        return None
    last = curve[-1]
    last_nav = _finite(last.get("nav"))
    last_d = str(last.get("date") or "")[:10]
    if last_nav is None or abs(last_nav) <= 1e-12 or not last_d:
        return None
    if kind == "day":
        prev = _finite(curve[-2].get("nav"))
        if prev is None or abs(prev) <= 1e-12:
            return None
        return (last_nav / prev - 1.0) * 100.0
    if kind == "week":
        if len(curve) < 6:
            return None
        prev = _finite(curve[-6].get("nav"))
        if prev is None or abs(prev) <= 1e-12:
            return None
        return (last_nav / prev - 1.0) * 100.0
    try:
        y, m, _ = last_d.split("-")
        y, m = int(y), int(m)
    except ValueError:
        return None
    if kind == "mtd":
        want = f"{y:04d}-{m:02d}-"
    elif kind == "ytd":
        want = f"{y:04d}-"
    else:
        return None
    base = None
    for pt in curve:
        d = str(pt.get("date") or "")
        if d.startswith(want):
            base = _finite(pt.get("nav"))
            break
    if base is None or abs(base) <= 1e-12:
        return None
    return (last_nav / base - 1.0) * 100.0


def _cluster_labels(rho: np.ndarray) -> np.ndarray:
    n = rho.shape[0]
    if n < 2:
        return np.ones(n, dtype=int)
    r = np.clip(rho, -1.0, 1.0)
    dist = np.sqrt(np.maximum(0.0, 0.5 * (1.0 - r)))
    np.fill_diagonal(dist, 0.0)
    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import squareform
        condensed = squareform(dist, checks=False)
        if condensed.size == 0:
            return np.ones(n, dtype=int)
        z = linkage(condensed, method="average")
        return np.asarray(fcluster(z, CLUSTER_CUT, criterion="distance"), dtype=int)
    except Exception:
        return np.ones(n, dtype=int)


def _pack(frac: float | None, nav: float | None) -> dict:
    if frac is None or not math.isfinite(frac):
        return {"pct": None, "usd": None}
    scale = abs(nav) if nav is not None else None
    return {
        "pct": _round(frac * 100.0, 3),
        "usd": _round(frac * scale, 2) if scale is not None else None,
    }


def evaluate(ready: list[dict], *, curve: list[dict] | None = None,
             spy_closes: list | None = None) -> dict:
    """SPEC Risk stack from marked names that still hold `_closes`."""
    names = []
    for m in ready or []:
        if not m.get("ready"):
            continue
        mv = _finite(m.get("market_value"))
        if mv is None:
            continue
        cmap = _closes_map(m.get("_closes") or [])
        rets = _simple_returns(cmap)
        names.append({
            "symbol": str(m.get("symbol") or "").upper(),
            "side": m.get("side") or ("short" if (m.get("qty") or 0) < 0 else "long"),
            "mv": mv,
            "rets": rets,
            "bars": len(cmap),
        })
    n = len(names)
    if n < MIN_NAMES:
        return blank_stack(
            reason=f"{THIN_NOTE} (<{MIN_NAMES} marked names).",
            n_names=n,
        )

    common = None
    for row in names:
        keys = set(row["rets"])
        common = keys if common is None else (common & keys)
    overlap = sorted(common or [])
    if len(overlap) < MIN_OVERLAP:
        return blank_stack(
            reason=f"{THIN_NOTE} ({len(overlap)} overlap days < {MIN_OVERLAP}).",
            n_names=n,
            overlap=len(overlap),
        )

    cov_dates = overlap[-COV_N:]
    hist_dates = overlap[-HIST_PREF:] if len(overlap) >= HIST_PREF else overlap
    R60 = np.asarray([[row["rets"][d] for d in cov_dates] for row in names], dtype=float).T
    # R60: T×N
    if R60.shape[0] < COV_N or R60.shape[1] != n:
        return blank_stack(
            reason=f"{THIN_NOTE} (60d return window incomplete).",
            n_names=n,
            overlap=len(overlap),
        )
    cov = np.cov(R60, rowvar=False, ddof=1)
    if cov.ndim == 0:
        cov = np.asarray([[float(cov)]])
    if _is_singular(cov):
        return blank_stack(
            reason=f"{THIN_NOTE} (singular 60d covariance).",
            n_names=n,
            overlap=len(overlap),
        )

    nav = float(sum(row["mv"] for row in names))
    if abs(nav) <= 1e-9:
        return blank_stack(
            reason=f"{THIN_NOTE} (net NAV ≈ 0 — weights undefined).",
            n_names=n,
            overlap=len(overlap),
        )
    w = np.asarray([row["mv"] / nav for row in names], dtype=float)
    sigma_w = cov @ w
    port_var = float(w @ sigma_w)
    if port_var <= 0 or not math.isfinite(port_var):
        return blank_stack(
            reason=f"{THIN_NOTE} (portfolio 60d variance ≤ 0).",
            n_names=n,
            overlap=len(overlap),
        )
    sigma = math.sqrt(port_var)
    mv_abs = abs(nav)

    def param_frac(z):
        return z * sigma  # μ=0, 1d, as loss fraction of |NAV| when scaled by |NAV|

    # Dollar Euler uses MV = |NAV| so Σ CVaR = z·σ·|NAV|
    def mvar_usd(z, i):
        return z * float(sigma_w[i]) / sigma * mv_abs

    R_hist = np.asarray([[row["rets"][d] for d in hist_dates] for row in names], dtype=float).T
    port_hist = R_hist @ w
    hist95 = _hist_var_frac(port_hist, 0.05)
    hist99 = _hist_var_frac(port_hist, 0.01)

    p95 = param_frac(Z95)
    p99 = param_frac(Z99)
    var = {
        "horizon": "1d",
        "cov_window": COV_N,
        "hist_n": int(len(port_hist)),
        "hist_window": int(len(hist_dates)),
        "mu": 0.0,
        "port_sigma_daily": _round(sigma, 6),
        "hist_95": {**_pack(hist95, nav), "method": "historical empirical quantile"},
        "hist_99": {**_pack(hist99, nav), "method": "historical empirical quantile"},
        "param_95": {**_pack(p95, nav), "method": "parametric Gaussian μ=0, 60d Σ"},
        "param_99": {**_pack(p99, nav), "method": "parametric Gaussian μ=0, 60d Σ"},
        "note": SPEC_NOTE,
    }

    # Per-name vols / beta / flags
    spy_rets = _simple_returns(_closes_map(spy_closes or []))
    spy60 = np.asarray([spy_rets[d] for d in cov_dates if d in spy_rets], dtype=float) if spy_rets else np.asarray([])
    spy_aligned = None
    if len(spy60) == len(cov_dates):
        spy_aligned = np.asarray([spy_rets[d] for d in cov_dates], dtype=float)
        spy_var = float(np.var(spy_aligned, ddof=1)) if len(spy_aligned) >= 2 else 0.0
        if spy_var <= 0:
            spy_aligned = None

    rho = np.corrcoef(R60, rowvar=False)
    if rho.ndim == 0:
        rho = np.asarray([[1.0]])
    rho = np.clip(np.nan_to_num(rho, nan=0.0), -1.0, 1.0)
    np.fill_diagonal(rho, 1.0)

    rows_out = []
    cvar95 = []
    for i, row in enumerate(names):
        series = np.asarray([row["rets"][d] for d in overlap], dtype=float)
        v20 = _ann_vol(series[-VOL_SHORT:]) if len(series) >= VOL_SHORT else None
        v60 = _ann_vol(series[-COV_N:]) if len(series) >= COV_N else None
        beta = None
        if spy_aligned is not None:
            ri = R60[:, i]
            beta = float(np.cov(ri, spy_aligned, ddof=1)[0, 1] / float(np.var(spy_aligned, ddof=1)))
            if not math.isfinite(beta):
                beta = None
        m95 = mvar_usd(Z95, i)
        c95 = float(w[i]) * m95
        cvar95.append(c95)
        port_var_usd = p95 * mv_abs
        pct_var = (c95 / port_var_usd * 100.0) if abs(port_var_usd) > 1e-12 else None
        # IVaR: drop i, renormalize remaining w
        ivar = None
        if n > 1:
            mask = np.ones(n, dtype=bool)
            mask[i] = False
            w_rest = w[mask]
            s = float(w_rest.sum())
            if abs(s) > 1e-12:
                wr = w_rest / s
                cov_r = cov[np.ix_(mask, mask)]
                if not _is_singular(cov_r):
                    pr = float(wr @ (cov_r @ wr))
                    if pr > 0 and math.isfinite(pr):
                        var_wo = Z95 * math.sqrt(pr) * mv_abs
                        ivar = (p95 * mv_abs) - var_wo
        flags = []
        wpct = abs(w[i]) * 100.0
        if wpct >= CONC_WEIGHT_PCT:
            flags.append("CONC")
        if row["side"] == "short":
            flags.append("SHORT")
        if row["bars"] < MIN_OVERLAP + 1:
            flags.append("THIN")
        if v20 is not None and v60 is not None and v20 > v60:
            flags.append("VOL_SPIKE")
        # HIGH_BETA: no numeric cutoff in the 7 locks — do not invent one.
        rows_out.append({
            "symbol": row["symbol"],
            "side": row["side"],
            "weight": _round(w[i], 6),
            "weight_pct": _round(w[i] * 100.0, 2),
            "vol_20": _round(v20 * 100.0, 2) if v20 is not None else None,
            "vol_60": _round(v60 * 100.0, 2) if v60 is not None else None,
            "beta_spy_60": _round(beta, 3),
            "mvar_95": _round(m95, 2),
            "cvar_95": _round(c95, 2),
            "pct_var": _round(pct_var, 2),
            "ivar_95": _round(ivar, 2),
            "flags": flags,
            "regime": (
                "HOT" if v20 is not None and v60 is not None and v20 > v60
                else "COLD" if v20 is not None and v60 is not None and v20 < v60
                else None
            ),
        })

    ranked = sorted(rows_out, key=lambda r: -(abs(r["pct_var"]) if r["pct_var"] is not None else -1))
    labels = _cluster_labels(rho)
    clusters = []
    for lab in sorted(set(int(x) for x in labels)):
        idx = [i for i, L in enumerate(labels) if int(L) == lab]
        members = [names[i]["symbol"] for i in idx]
        cvar_sum = sum(cvar95[i] for i in idx)
        port_var_usd = p95 * mv_abs
        cpct = (cvar_sum / port_var_usd * 100.0) if abs(port_var_usd) > 1e-12 else None
        # cluster vol: MV-weighted member returns on overlap
        w_c = w[idx]
        if abs(float(w_c.sum())) > 1e-12:
            wc = w_c / w_c.sum()
            rc = R60[:, idx] @ wc
            cv20 = _ann_vol(rc[-VOL_SHORT:]) if len(rc) >= VOL_SHORT else None
            cv60 = _ann_vol(rc[-COV_N:]) if len(rc) >= COV_N else None
        else:
            cv20 = cv60 = None
        regime = None
        if cv20 is not None and cv60 is not None:
            regime = "HOT" if cv20 > cv60 else ("COLD" if cv20 < cv60 else None)
        clusters.append({
            "id": int(lab),
            "members": members,
            "n": len(members),
            "pct_var": _round(cpct, 2),
            "vol_20": _round(cv20 * 100.0, 2) if cv20 is not None else None,
            "vol_60": _round(cv60 * 100.0, 2) if cv60 is not None else None,
            "regime": regime,
        })

    port_series = np.asarray([sum(names[i]["rets"][d] * w[i] for i in range(n)) for d in overlap])
    vol20 = _ann_vol(port_series[-VOL_SHORT:]) if len(port_series) >= VOL_SHORT else None
    vol60 = _ann_vol(port_series[-COV_N:]) if len(port_series) >= COV_N else None

    syn = list(curve or [])
    curve_kind = "synthetic_nav_from_stored_closes" if syn else None
    nav_arr = np.asarray([_finite(p.get("nav")) for p in syn if _finite(p.get("nav")) is not None], dtype=float)
    syn_rets = None
    if len(nav_arr) >= 2:
        prev = nav_arr[:-1]
        ok = np.abs(prev) > 1e-12
        syn_rets = ((nav_arr[1:] - prev) / np.abs(prev))[ok]

    perf = {
        "day": _round(_perf_window(syn, kind="day"), 3),
        "week": _round(_perf_window(syn, kind="week"), 3),
        "mtd": _round(_perf_window(syn, kind="mtd"), 3),
        "ytd": _round(_perf_window(syn, kind="ytd"), 3),
        "max_dd_pct": _round(_max_dd(nav_arr), 2) if len(nav_arr) >= 10 else None,
        "sharpe": _round(_sharpe(syn_rets), 3) if syn_rets is not None else None,
        "sortino": _round(_sortino(syn_rets), 3) if syn_rets is not None else None,
        "n": int(len(syn_rets) if syn_rets is not None else 0),
        "curve_kind": curve_kind,
        "curve_label": (
            "synthetic NAV from stored Yahoo closes — not a broker equity curve"
            if curve_kind else None
        ),
    }

    cvar_sum = float(sum(cvar95))
    var_usd = p95 * mv_abs
    euler_ok = abs(cvar_sum - var_usd) <= max(1e-6, 1e-8 * max(abs(var_usd), 1.0))

    return {
        "ready": True,
        "source": spec_source(),
        "note": SPEC_NOTE,
        "message": None,
        "thin": False,
        "n_names": n,
        "overlap_days": len(overlap),
        "horizon": "1d",
        "cov_window": COV_N,
        "var": var,
        "vol": {
            "vol_20": _round(vol20 * 100.0, 2) if vol20 is not None else None,
            "vol_60": _round(vol60 * 100.0, 2) if vol60 is not None else None,
        },
        "perf": perf,
        "names": rows_out,
        "ranked": ranked,
        "clusters": clusters,
        "euler": {
            "param_95_ok": bool(euler_ok),
            "cvar_sum_95": _round(cvar_sum, 4),
            "var_95": _round(var_usd, 4),
        },
    }
