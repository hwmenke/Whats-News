"""SPY-first Gaussian HMM — research label, not edge.

Regime HMM ≠ Q-trade HMM. This is a 2- or 3-state Gaussian on ~2y of stored
Yahoo daily log returns for SPY. Sticky transition priors. Labels (low-vol /
high-vol / risk-on / risk-off / stress) are derived from fitted means and
vols after the fact.

Never: 4-state quote/FV/adverse-selection, "regime flip → buy", or win rates
from state occupancy. Desk names inherit the SPY state; per-name fits skipped.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np

import database as db
import market_data as md

SOURCE = "whats-news hmm_regime (SPY Gaussian, research label)"
NOTE = (
    "research label, not edge. "
    "2- or 3-state Gaussian HMM on SPY daily log returns (stored Yahoo). "
    "Occupancy is the share of the fit window — not a win rate. "
    "Do not buy a regime flip."
)
ANCHOR = "SPY"
WINDOW = 504  # ~2y of daily returns
MIN_OBS_2 = 80
MIN_OBS_3 = 120
VAR_FLOOR = 1e-8
STICKY = 0.95
STICKY_MIX = 0.35
MAX_ITER = 40
TOL = 1e-5
N_RESTARTS = 4
PATH_DAYS = 60
CORE_INDEX = ("SPY", "QQQ", "IWM")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    return arr[np.isfinite(arr)]


def log_returns(closes) -> np.ndarray:
    p = _finite(closes)
    if len(p) < 2 or np.any(p <= 0):
        return np.asarray([], dtype=float)
    r = np.diff(np.log(p))
    return r[np.isfinite(r)]


def _logsumexp(a, axis=None):
    a = np.asarray(a, dtype=float)
    m = np.max(a, axis=axis, keepdims=True)
    out = m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True))
    if axis is None:
        return float(np.squeeze(out))
    return np.squeeze(out, axis=axis)


def _sticky_A(k: int, diag: float = STICKY) -> np.ndarray:
    off = (1.0 - diag) / max(k - 1, 1)
    A = np.full((k, k), off, dtype=float)
    np.fill_diagonal(A, diag)
    A /= A.sum(axis=1, keepdims=True)
    return A


def _emissions(x: np.ndarray, mu: np.ndarray, var: np.ndarray) -> np.ndarray:
    """Log p(x_t | k) for 1D Gaussian. Shape (T, K)."""
    z = (x[:, None] - mu[None, :]) ** 2 / var[None, :]
    return -0.5 * (np.log(2.0 * math.pi * var)[None, :] + z)


def _filtered(x, pi, A, mu, var) -> np.ndarray:
    t, k = len(x), len(mu)
    log_A = np.log(np.clip(A, 1e-12, 1.0))
    log_pi = np.log(np.clip(pi, 1e-12, 1.0))
    log_b = _emissions(x, mu, var)
    filt = np.zeros((t, k), dtype=float)
    log_a = log_pi + log_b[0]
    log_a -= _logsumexp(log_a)
    filt[0] = np.exp(log_a)
    for i in range(1, t):
        log_a = log_b[i] + _logsumexp(log_a[:, None] + log_A, axis=0)
        log_a -= _logsumexp(log_a)
        filt[i] = np.exp(log_a)
    return filt


def _forward_backward(x, pi, A, mu, var):
    """Scaled FB. Returns gamma (T,K), xi (T-1,K,K), loglik."""
    t_len, k = len(x), len(mu)
    b = np.exp(np.clip(_emissions(x, mu, var), -700, 50))
    b = np.clip(b, 1e-300, None)
    alpha = np.zeros((t_len, k))
    scale = np.zeros(t_len)
    alpha[0] = np.clip(pi, 1e-12, 1.0) * b[0]
    scale[0] = alpha[0].sum() or 1e-300
    alpha[0] /= scale[0]
    for i in range(1, t_len):
        alpha[i] = (alpha[i - 1] @ A) * b[i]
        scale[i] = alpha[i].sum() or 1e-300
        alpha[i] /= scale[i]
    beta = np.ones((t_len, k))
    for i in range(t_len - 2, -1, -1):
        beta[i] = A @ (b[i + 1] * beta[i + 1])
        beta[i] /= scale[i + 1] or 1e-300
    gamma = alpha * beta
    gamma /= np.clip(gamma.sum(axis=1, keepdims=True), 1e-300, None)
    xi = np.zeros((t_len - 1, k, k))
    for i in range(t_len - 1):
        outer = alpha[i][:, None] * A * (b[i + 1] * beta[i + 1])[None, :]
        tot = outer.sum() or 1e-300
        xi[i] = outer / tot
    loglik = float(np.sum(np.log(np.clip(scale, 1e-300, None))))
    return gamma, xi, loglik


def _init_params(x: np.ndarray, k: int, rng: np.random.Generator):
    pi = np.full(k, 1.0 / k)
    A = _sticky_A(k)
    if k == 2:
        lo, hi = np.quantile(np.abs(x), [0.35, 0.75])
        # split by |return| so vol states separate
        mask = np.abs(x) <= max(lo, 1e-6)
        mu = np.array([
            float(x[mask].mean()) if mask.any() else float(x.mean()),
            float(x[~mask].mean()) if (~mask).any() else float(x.mean()),
        ])
        var = np.array([
            float(x[mask].var()) if mask.sum() > 2 else float(x.var()),
            float(x[~mask].var()) if (~mask).sum() > 2 else float(x.var()) * 2,
        ])
    else:
        qs = np.quantile(x, np.linspace(0.15, 0.85, k))
        jitter = rng.normal(0, float(np.std(x) or 1e-4) * 0.15, size=k)
        mu = qs + jitter
        var = np.full(k, float(x.var()) or VAR_FLOOR)
        var = var * rng.uniform(0.6, 1.8, size=k)
    var = np.maximum(var, VAR_FLOOR)
    return pi, A, mu, var


def fit_gaussian_hmm(returns, n_states: int = 2, *, seed: int = 0) -> dict | None:
    """EM with sticky prior mix. None if the series is too short or degenerate."""
    x = _finite(returns)
    k = 2 if n_states <= 2 else 3
    need = MIN_OBS_2 if k == 2 else MIN_OBS_3
    if len(x) < need:
        return None
    if float(np.std(x)) < 1e-12:
        return None

    best = None
    for restart in range(N_RESTARTS):
        rng = np.random.default_rng(seed + 17 * restart)
        pi, A, mu, var = _init_params(x, k, rng)
        prev_ll = -np.inf
        ok = False
        for _ in range(MAX_ITER):
            try:
                gamma, xi, ll = _forward_backward(x, pi, A, mu, var)
            except Exception:
                ok = False
                break
            if not np.isfinite(ll):
                break
            pi = gamma[0] / max(gamma[0].sum(), 1e-12)
            A_hat = xi.sum(axis=0)
            A_hat /= np.clip(A_hat.sum(axis=1, keepdims=True), 1e-12, None)
            A = (1.0 - STICKY_MIX) * A_hat + STICKY_MIX * _sticky_A(k)
            A /= A.sum(axis=1, keepdims=True)
            mass = gamma.sum(axis=0)
            mu = (gamma * x[:, None]).sum(axis=0) / np.clip(mass, 1e-12, None)
            var = (gamma * (x[:, None] - mu[None, :]) ** 2).sum(axis=0) / np.clip(mass, 1e-12, None)
            var = np.maximum(var, VAR_FLOOR)
            ok = True
            if abs(ll - prev_ll) < TOL:
                break
            prev_ll = ll
        if not ok:
            continue
        pack = {"pi": pi, "A": A, "mu": mu, "var": var, "loglik": prev_ll, "k": k}
        if best is None or pack["loglik"] > best["loglik"]:
            best = pack
    return best


def _label_states(mu: np.ndarray, var: np.ndarray) -> list[str]:
    """Research labels from fitted mean/vol only — not a trade book."""
    k = len(mu)
    sig = np.sqrt(np.maximum(var, VAR_FLOOR))
    labels = [""] * k
    vol_rank = list(np.argsort(sig))  # low vol → high vol
    if k == 2:
        labels[vol_rank[0]] = "low-vol"
        labels[vol_rank[1]] = "high-vol"
        return labels
    # 3-state: highest vol = stress; remaining two by mean → risk-on / risk-off
    labels[vol_rank[-1]] = "stress"
    rest = vol_rank[:2]
    if mu[rest[0]] >= mu[rest[1]]:
        labels[rest[0]] = "risk-on"
        labels[rest[1]] = "risk-off"
    else:
        labels[rest[0]] = "risk-off"
        labels[rest[1]] = "risk-on"
    return labels


def interpret_fit(x, dates, params: dict) -> dict:
    mu = np.asarray(params["mu"], dtype=float)
    var = np.asarray(params["var"], dtype=float)
    pi = np.asarray(params["pi"], dtype=float)
    A = np.asarray(params["A"], dtype=float)
    k = int(params["k"])
    labels = _label_states(mu, var)
    filt = _filtered(x, pi, A, mu, var)
    hard = filt.argmax(axis=1)
    states = []
    for i in range(k):
        mask = hard == i
        realized = float(x[mask].std(ddof=1)) if mask.sum() >= 2 else None
        occupancy = float(mask.mean()) if len(hard) else 0.0
        states.append({
            "id": i,
            "label": labels[i],
            "mean": round(float(mu[i]), 6),
            "vol": round(float(math.sqrt(max(float(var[i]), VAR_FLOOR))), 6),
            "realized_vol": None if realized is None else round(realized, 6),
            "occupancy": round(occupancy, 4),
            "occupancy_note": "share of fit-window days (not a win rate)",
        })
    path = []
    start = max(0, len(x) - PATH_DAYS)
    for i in range(start, len(x)):
        sid = int(hard[i])
        item = {
            "date": dates[i] if i < len(dates) else "",
            "state_id": sid,
            "label": labels[sid],
            "probs": [round(float(p), 4) for p in filt[i]],
        }
        path.append(item)
    last = int(hard[-1])
    return {
        "n_states": k,
        "states": states,
        "current_state_id": last,
        "current_label": labels[last],
        "current_probs": [round(float(p), 4) for p in filt[-1]],
        "path": path,
        "loglik": None if not math.isfinite(params.get("loglik", float("nan"))) else round(float(params["loglik"]), 3),
        "n_obs": int(len(x)),
    }


def empty_regime(reason: str, *, n_states: int = 2) -> dict:
    return {
        "available": False,
        "ready": False,
        "symbol": ANCHOR,
        "inherited": False,
        "n_states": n_states,
        "current_label": "",
        "current_state_id": None,
        "current_probs": [],
        "states": [],
        "path": [],
        "reason": reason,
        "note": NOTE,
        "source": SOURCE,
        "research_label": True,
        "as_of": None,
    }


def _daily_pack(symbol: str, limit: int = WINDOW + 8):
    df = md.get_ohlcv_df(symbol, "daily", limit=limit)
    if df is None or df.empty or "close" not in df.columns:
        return np.asarray([], dtype=float), []
    closes = np.asarray(df["close"].astype(float), dtype=float)
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10] for d in df.index]
    return closes, dates


def _cache_key(n_states: int) -> str:
    return f"{ANCHOR}:{int(n_states)}:{WINDOW}"


def _load_cache(key: str) -> dict | None:
    _ensure_tables()
    with db.connection() as conn:
        row = conn.execute(
            "SELECT as_of, fitted_at, payload_json FROM hmm_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"] or "")
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        payload["from_cache"] = True
        payload["fitted_at"] = row["fitted_at"]
        return payload
    return None


def _save_cache(key: str, as_of: str, payload: dict) -> None:
    _ensure_tables()
    with db.connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO hmm_cache(cache_key, as_of, fitted_at, payload_json)
               VALUES (?, ?, ?, ?)""",
            (key, as_of, _now(), json.dumps(payload)),
        )


def _ensure_tables():
    with db.connection() as conn:
        db._create_research_cache(conn)


def fit_spy(*, n_states: int = 2, force: bool = False, closes=None, dates=None) -> dict:
    """Trailing-window SPY fit. Cached by as-of last bar date."""
    k = 2 if int(n_states) <= 2 else 3
    if closes is None:
        closes, dates = _daily_pack(ANCHOR)
    dates = list(dates or [])
    r = log_returns(closes)
    if len(r) < (MIN_OBS_2 if k == 2 else MIN_OBS_3):
        return empty_regime(
            f"Need ≥{MIN_OBS_2 if k == 2 else MIN_OBS_3} SPY daily log returns in finance.db "
            f"(have {len(r)}). Fetch Yahoo for SPY — not invented.",
            n_states=k,
        )
    # align dates to returns (drop first close)
    r_dates = dates[1:] if len(dates) == len(closes) else dates[-len(r):]
    if len(r) > WINDOW:
        r = r[-WINDOW:]
        r_dates = r_dates[-WINDOW:]
    as_of = r_dates[-1] if r_dates else None
    key = _cache_key(k)
    if not force and as_of:
        cached = _load_cache(key)
        if cached and cached.get("as_of") == as_of and cached.get("available"):
            return cached

    params = fit_gaussian_hmm(r, n_states=k, seed=7)
    if params is None:
        return empty_regime("HMM fit failed (degenerate series). No invented states.", n_states=k)

    interpreted = interpret_fit(r, r_dates, params)
    payload = {
        "available": True,
        "ready": True,
        "symbol": ANCHOR,
        "inherited": False,
        "n_states": k,
        "current_label": interpreted["current_label"],
        "current_state_id": interpreted["current_state_id"],
        "current_probs": interpreted["current_probs"],
        "states": interpreted["states"],
        "path": interpreted["path"],
        "loglik": interpreted["loglik"],
        "n_obs": interpreted["n_obs"],
        "window": WINDOW,
        "as_of": as_of,
        "fitted_at": _now(),
        "from_cache": False,
        "reason": NOTE,
        "note": NOTE,
        "source": SOURCE,
        "research_label": True,
        "tag": f"SPY state = {interpreted['current_label']}",
        "params": {
            "pi": [round(float(v), 6) for v in params["pi"]],
            "A": [[round(float(v), 6) for v in row] for row in params["A"]],
            "mu": [round(float(v), 6) for v in params["mu"]],
            "var": [round(float(v), 8) for v in params["var"]],
        },
    }
    if as_of:
        _save_cache(key, as_of, payload)
    return payload


def regime(symbol: str | None = None, *, n_states: int = 2, force: bool = False) -> dict:
    """SPY fit. Other symbols inherit SPY — no per-name HMM."""
    spy = fit_spy(n_states=n_states, force=force)
    want = (symbol or ANCHOR).strip().upper() or ANCHOR
    if want in ("", ANCHOR, "SPX", "^GSPC"):
        return spy
    inherited = {
        **spy,
        "symbol": want,
        "inherited": True,
        "anchor": ANCHOR,
        "reason": (
            f"{want} inherits the SPY research label "
            f"({spy.get('current_label') or 'unavailable'}). "
            "Per-name HMM skipped (noisy). " + NOTE
        ),
    }
    return inherited


def scan(*, desk: bool = True, n_states: int = 2, state: str | None = None, force: bool = False) -> dict:
    """Desk rows tagged with the SPY research label. Informational — not a trigger."""
    spy = fit_spy(n_states=n_states, force=force)
    label_filter = (state or "").strip().lower()
    if not spy.get("available"):
        return {
            "available": False,
            "ready": False,
            "anchor": ANCHOR,
            "n_states": spy.get("n_states"),
            "spy": {
                "current_label": "",
                "current_state_id": None,
                "current_probs": [],
                "states": [],
                "as_of": None,
                "path": [],
            },
            "rows": [],
            "count": 0,
            "filter": label_filter or None,
            "reason": spy.get("reason") or NOTE,
            "note": NOTE,
            "source": SOURCE,
            "research_label": True,
            "message": NOTE,
        }
    symbols = _scan_symbols(desk=desk)
    rows = []
    for sym in symbols:
        row = {
            "symbol": sym,
            "inherited": sym != ANCHOR,
            "spy_state": spy.get("current_label") or "",
            "spy_state_id": spy.get("current_state_id"),
            "spy_prob": (spy.get("current_probs") or [None])[spy["current_state_id"]]
            if spy.get("available") and spy.get("current_state_id") is not None
            else None,
            "tag": spy.get("tag") or "",
            "as_of": spy.get("as_of"),
            "note": "research label, not edge",
        }
        if label_filter and (row["spy_state"] or "").lower() != label_filter:
            continue
        rows.append(row)
    return {
        "available": bool(spy.get("available")),
        "ready": bool(spy.get("available")),
        "anchor": ANCHOR,
        "n_states": spy.get("n_states"),
        "spy": {
            "current_label": spy.get("current_label") or "",
            "current_state_id": spy.get("current_state_id"),
            "current_probs": spy.get("current_probs") or [],
            "states": spy.get("states") or [],
            "as_of": spy.get("as_of"),
            "path": spy.get("path") or [],
        },
        "rows": rows,
        "count": len(rows),
        "filter": label_filter or None,
        "reason": spy.get("reason") or NOTE,
        "note": NOTE,
        "source": SOURCE,
        "research_label": True,
        "message": NOTE,
    }


def status() -> dict:
    return {
        "available": True,
        "source": SOURCE,
        "note": NOTE,
        "reason": NOTE,
        "research_label": True,
        "anchor": ANCHOR,
        "n_states_default": 2,
        "window": WINDOW,
    }


def empty_scan() -> dict:
    return {
        **status(),
        "ready": False,
        "spy": {
            "current_label": "",
            "current_state_id": None,
            "current_probs": [],
            "states": [],
            "as_of": None,
            "path": [],
        },
        "rows": [],
        "count": 0,
        "message": NOTE,
    }


def _scan_symbols(desk: bool = True) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    try:
        rows = md.list_desk_symbols() if desk else md.list_symbols()
    except Exception:
        rows = []
    for row in rows or []:
        sym = str((row or {}).get("symbol") or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    for sym in CORE_INDEX:
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out
