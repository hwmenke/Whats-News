# Reference X post: https://x.com/hnnngmnk/status/2048884245158846885
"""
SPY/VIX Phase-Plane Diagram
============================
State variables
---------------
nu  : vol-of-vol proxy
      = annualized 21-day rolling std of daily Δlog(VIX)
rho : leverage-effect proxy
      = 63-day rolling correlation of SPY log-returns with Δlog(VIX)

Notes
-----
* All data is fetched from yfinance (SPY + ^VIX, 1990–today).
* If the network is unavailable a synthetic fallback is used automatically;
  the plot is then labelled "SYNTHETIC DATA – illustrative only".
* The k_eff = 0 divider is a linear public-data proxy, not option-surface
  curvature; see inline comments for details.

Public API
----------
generate_figure_bytes() -> (bytes, bool)
    Returns raw PNG bytes and a flag indicating whether synthetic data was used.
    Suitable for serving directly from a Flask endpoint.

main()
    CLI entry point — saves spy_vix_phase_plane.png to disk.
"""
from __future__ import annotations

import io
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.ndimage import gaussian_filter
from scipy.stats import gaussian_kde

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
START_DATE   = "1990-01-01"
SPY_TICKER   = "SPY"
VIX_TICKER   = "^VIX"

VOV_WINDOW   = 21    # rolling window for vol-of-vol (trading days)
CORR_WINDOW  = 63    # rolling correlation window (~3 months)
SMOOTH_SPAN  = 5     # EWM span for mild trajectory smoothing
FLOW_HORIZON = 5     # forward steps used for empirical drift vectors

NX_BINS      = 34
NY_BINS      = 30
SMOOTH_SIGMA = 1.25  # Gaussian σ applied to histogram counts before smoothing

OUTPUT_FILE  = "spy_vix_phase_plane.png"
DPI          = 200


# ─────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────
def _adj_close_from_df(df: "pd.DataFrame", ticker: str) -> "pd.Series":
    """Extract the best available close column regardless of yfinance index shape."""
    if isinstance(df.columns, pd.MultiIndex):
        for col in df.columns:
            if "adj close" in " ".join(map(str, col)).lower():
                return df[col].squeeze().rename(ticker)
        for col in df.columns:
            if "close" in " ".join(map(str, col)).lower():
                return df[col].squeeze().rename(ticker)
    else:
        if "Adj Close" in df.columns:
            return df["Adj Close"].rename(ticker)
        if "Close" in df.columns:
            return df["Close"].rename(ticker)
    raise KeyError(f"No close column found for {ticker}.")


def _download(ticker: str, start: str) -> "pd.Series":
    """Download adjusted close from yfinance. Raises RuntimeError on failure."""
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False,
                     auto_adjust=False, actions=False)
    if df.empty:
        raise RuntimeError(f"Empty download for {ticker}.")
    return _adj_close_from_df(df, ticker)


def _synthetic_data() -> tuple["pd.Series", "pd.Series"]:
    """
    Generate synthetic SPY + VIX histories that reproduce realistic phase-plane
    geometry (mean-reverting VIX, negative correlation, occasional vol spikes).
    Used as a fallback when yfinance is unreachable.

    Model
    -----
    * log(VIX) follows AR(1) with φ=0.98, σ_v=0.06, mean=log(18).
    * SPY daily log-returns ~ 0.035 % drift + VIX-scaled noise.
    * corr(ε_SPY, ε_VIX) = −0.75 (leverage effect).
    * Three synthetic crisis episodes are added (dotcom, GFC, COVID-like).
    """
    rng = np.random.default_rng(42)
    n   = 8_200  # ≈ 32.5 years of trading days

    # Correlated innovations
    rho_true = -0.75
    cov = np.array([[1.0, rho_true], [rho_true, 1.0]])
    Z   = rng.multivariate_normal([0.0, 0.0], cov, n)
    eps_s, eps_v = Z[:, 0], Z[:, 1]

    # Log-VIX: mean-reverting AR(1)
    phi, mu_v, sigma_v = 0.980, np.log(18.0), 0.060
    log_vix = np.empty(n)
    log_vix[0] = mu_v
    for i in range(1, n):
        log_vix[i] = mu_v + phi * (log_vix[i - 1] - mu_v) + sigma_v * eps_v[i]

    # Synthetic crisis spikes (start_idx, peak_rise, decay_half_life_days)
    crises = [(1_700, 2.2, 80), (3_700, 3.6, 120), (6_900, 3.8, 60)]
    for start, height, tau in crises:
        end = min(n, start + int(4 * tau))
        t   = np.arange(end - start)
        # fast rise, exponential decay
        rise = np.clip(t / max(tau / 8, 1), 0, 1)
        decay = np.exp(-t / tau)
        spike = height * rise * decay
        log_vix[start:end] += spike

    vix = np.exp(log_vix)

    # SPY daily log-returns, vol scaled to VIX
    spy_daily_vol  = vix / 100.0 / np.sqrt(252.0)
    spy_logret     = 0.00035 + spy_daily_vol * eps_s
    spy_price      = 200.0 * np.exp(np.cumsum(spy_logret))

    dates = pd.bdate_range("1993-01-29", periods=n)
    return (
        pd.Series(spy_price, index=dates, name=SPY_TICKER),
        pd.Series(vix,       index=dates, name=VIX_TICKER),
    )


# ─────────────────────────────────────────────
# Phase-state construction
# ─────────────────────────────────────────────
def _compute_state(spy: "pd.Series", vix: "pd.Series") -> "pd.DataFrame":
    """Build (nu, rho) state variables from raw close price series."""
    data = pd.concat([spy, vix], axis=1, join="inner").dropna()
    data.columns = ["SPY", "VIX"]
    data = data[(data["SPY"] > 0) & (data["VIX"] > 0)].copy()

    data["spy_lr"] = np.log(data["SPY"]).diff()
    data["vix_lr"] = np.log(data["VIX"]).diff()

    # Vol-of-vol proxy: annualised rolling std of Δlog(VIX)
    data["vov"] = data["vix_lr"].rolling(VOV_WINDOW).std() * np.sqrt(252.0)

    # Leverage-effect proxy: rolling corr of equity returns with vol changes
    data["rho"] = data["spy_lr"].rolling(CORR_WINDOW).corr(data["vix_lr"])

    # Mild EWM smoothing for readability
    data["vov_sm"] = data["vov"].ewm(span=SMOOTH_SPAN, adjust=False, min_periods=3).mean()
    data["rho_sm"] = data["rho"].ewm(span=SMOOTH_SPAN, adjust=False, min_periods=3).mean()

    return data.dropna(subset=["vov_sm", "rho_sm"])


# ─────────────────────────────────────────────
# Empirical flow field
# ─────────────────────────────────────────────
def _flow_field(
    x: "pd.Series",
    y: "pd.Series",
    horizon: int = FLOW_HORIZON,
    nx: int = NX_BINS,
    ny: int = NY_BINS,
    sigma: float = SMOOTH_SIGMA,
    include_x: tuple = (),
    include_y: tuple = (),
):
    """
    Compute average empirical drift vectors on a (nu, rho) grid.
    Forward differences over `horizon` steps are binned, smoothed with a
    Gaussian filter, and returned as masked arrays ready for streamplot.
    """
    dx = x.shift(-horizon) - x
    dy = y.shift(-horizon) - y
    ph = pd.DataFrame({"x": x, "y": y, "dx": dx, "dy": dy}).dropna()

    xv, yv = ph["x"].to_numpy(), ph["y"].to_numpy()
    du = ph["dx"].to_numpy() / float(horizon)
    dv = ph["dy"].to_numpy() / float(horizon)

    xq = np.quantile(xv, [0.01, 0.99])
    yq = np.quantile(yv, [0.01, 0.99])
    xr, yr = max(xq[1] - xq[0], 1e-6), max(yq[1] - yq[0], 1e-6)

    x_lo = max(0.0, xq[0] - 0.10 * xr)
    x_hi = xq[1] + 0.10 * xr
    y_lo = yq[0] - 0.10 * yr
    y_hi = yq[1] + 0.10 * yr

    if include_x:
        x_lo = min(x_lo, min(include_x) - 0.05 * xr)
        x_hi = max(x_hi, max(include_x) + 0.05 * xr)
    if include_y:
        y_lo = min(y_lo, min(include_y) - 0.05 * yr)
        y_hi = max(y_hi, max(include_y) + 0.05 * yr)

    y_lo = max(-1.0, y_lo)
    y_hi = min(0.20, y_hi)

    if x_hi <= x_lo:
        x_lo, x_hi = max(0.0, float(np.nanmin(xv)) - 0.05), float(np.nanmax(xv)) + 0.05
    if y_hi <= y_lo:
        y_lo, y_hi = max(-1.0, float(np.nanmin(yv)) - 0.05), min(1.0, float(np.nanmax(yv)) + 0.05)

    xe = np.linspace(x_lo, x_hi, nx + 1)
    ye = np.linspace(y_lo, y_hi, ny + 1)

    cnt  = np.histogram2d(xv, yv, bins=[xe, ye])[0]
    su   = np.histogram2d(xv, yv, bins=[xe, ye], weights=du)[0]
    sv   = np.histogram2d(xv, yv, bins=[xe, ye], weights=dv)[0]

    cnt_s = gaussian_filter(cnt, sigma=sigma, mode="nearest")
    su_s  = gaussian_filter(su,  sigma=sigma, mode="nearest")
    sv_s  = gaussian_filter(sv,  sigma=sigma, mode="nearest")

    with np.errstate(divide="ignore", invalid="ignore"):
        u = (su_s / np.maximum(cnt_s, 1e-12)).T
        v = (sv_s / np.maximum(cnt_s, 1e-12)).T

    density = cnt_s.T
    floor   = (max(0.05 * np.nanmax(density),
                   np.nanpercentile(density[density > 0], 15))
               if np.any(density > 0) else 0.0)
    mask = density < floor

    speed = np.sqrt(u**2 + v**2)
    lw    = 0.70 + 1.50 * (speed / max(float(np.nanmax(speed)), 1e-9))

    xc = 0.5 * (xe[:-1] + xe[1:])
    yc = 0.5 * (ye[:-1] + ye[1:])
    return xc, yc, np.ma.masked_where(mask, u), np.ma.masked_where(mask, v), density, np.ma.masked_where(mask, lw)


# ─────────────────────────────────────────────
# Attractor & divider
# ─────────────────────────────────────────────
def _attractor(x: "pd.Series", y: "pd.Series", xlim, ylim):
    """Stable attractor = KDE mode of the historical state density."""
    xv, yv = x.to_numpy(), y.to_numpy()
    try:
        kde = gaussian_kde(np.vstack([xv, yv]))
        gx, gy = np.linspace(*xlim, 240), np.linspace(*ylim, 240)
        xx, yy = np.meshgrid(gx, gy)
        zz = kde(np.vstack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
        iy, ix = np.unravel_index(np.nanargmax(zz), zz.shape)
        return float(xx[iy, ix]), float(yy[iy, ix])
    except Exception:
        return float(np.nanmean(xv)), float(np.nanmean(yv))


def _keff_divider(x_vals, x_star, y_star, x_hist, y_hist):
    """
    Linear proxy for k_eff = 0:
        k_eff = (nu − nu*) + λ(ρ − ρ*)
    λ = σ_nu / σ_rho equalises the two axes in scale units.
    Positive k_eff → smile; negative → frown.
    """
    lam = max(float(np.nanstd(x_hist)) / max(float(np.nanstd(y_hist)), 1e-8), 1e-3)
    return y_star - (x_vals - x_star) / lam, lam


# ─────────────────────────────────────────────
# Plot builder
# ─────────────────────────────────────────────
def _build_figure(data: "pd.DataFrame", synthetic: bool) -> "plt.Figure":
    x, y        = data["vov_sm"], data["rho_sm"]
    x_now       = float(x.iloc[-1])
    y_now       = float(y.iloc[-1])
    current_vix = float(data["VIX"].iloc[-1])
    last_date   = pd.Timestamp(data.index[-1])

    xg, yg, u, v, density, lw = _flow_field(
        x, y, include_x=(x_now,), include_y=(y_now,)
    )
    xlim = (float(xg[0]), float(xg[-1]))
    ylim = (float(yg[0]), float(yg[-1]))

    x_star, y_star = _attractor(x, y, xlim, ylim)
    x_line         = np.linspace(xlim[0], xlim[1], 500)
    y_div, lam     = _keff_divider(x_line, x_star, y_star, x, y)

    fig, ax = plt.subplots(figsize=(13.2, 8.6), facecolor="#0b1220")
    ax.set_facecolor("#101826")

    # Smile / frown shading
    ax.fill_between(x_line, y_div, ylim[1],  color="#2f5b91", alpha=0.28, zorder=0)
    ax.fill_between(x_line, ylim[0], y_div,  color="#8e2f3f", alpha=0.25, zorder=0)

    # Historical state cloud
    ax.scatter(x, y, s=8, c="white", alpha=0.045, linewidths=0, zorder=1)

    # Empirical flow streamlines
    try:
        ax.streamplot(xg, yg, u, v,
                      color="white", density=1.8, linewidth=lw,
                      arrowsize=1.0, minlength=0.08, maxlength=5.0,
                      integration_direction="both", zorder=3)
    except Exception:
        xx, yy = np.meshgrid(xg, yg)
        ax.quiver(xx, yy, np.ma.filled(u, np.nan), np.ma.filled(v, np.nan),
                  color="white", alpha=0.75, zorder=3)

    # k_eff divider
    ax.plot(x_line, y_div, ls="--", lw=2.2, color="#8fe3ff", alpha=0.95, zorder=4)

    # Attractor & current-state markers
    ax.scatter(x_star, y_star, s=260, marker="*",
               c="#48a8ff", edgecolors="white", linewidths=1.3, zorder=6)
    ax.scatter(x_now, y_now, s=150, marker="o",
               c="#ffd166", edgecolors="black", linewidths=1.1, zorder=7)

    # Title & subtitle
    data_tag = "SYNTHETIC DATA – illustrative only" if synthetic else f"through {last_date:%B %Y}"
    title    = f"Phase Plane of Smile Coefficients – SPY/VIX Empirical Flows ({data_tag})"
    subtitle = (
        r"State proxies:  $\nu$ = 21 d ann. std of $\Delta\!\log(\mathrm{VIX})$,"
        r"   $\rho$ = 63 d rolling corr[SPY log-ret,  $\Delta\!\log(\mathrm{VIX})$]"
    )
    title_color = "#ff9966" if synthetic else "white"
    ax.set_title(title, fontsize=15, color=title_color, weight="bold", pad=18)
    fig.text(0.5, 0.955, subtitle, ha="center", va="top", color="#cfd8dc", fontsize=10.0)

    ax.set_xlabel(r"Vol-of-vol proxy,  $\nu$",     fontsize=13, color="white")
    ax.set_ylabel(r"Correlation proxy,  $\rho$",   fontsize=13, color="white")

    xr, yr = xlim[1] - xlim[0], ylim[1] - ylim[0]
    ax.text(xlim[1] - 0.06 * xr, ylim[1] - 0.06 * yr,
            "smile region", color="#dbeeff", fontsize=13, weight="bold",
            ha="right", va="top", zorder=8)
    ax.text(xlim[0] + 0.06 * xr, ylim[0] + 0.08 * yr,
            "frown region", color="#ffd9dc", fontsize=13, weight="bold",
            ha="left", va="bottom", zorder=8)

    x_lab = xlim[0] + 0.64 * xr
    y_lab = y_star - (x_lab - x_star) / lam
    ax.text(x_lab, y_lab + 0.03 * yr,
            r"$k_{\mathrm{eff}} = 0$",
            color="#cfffff", fontsize=12, weight="bold", ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.22", fc=(0, 0, 0, 0.22), ec="none"),
            zorder=8)

    ax.annotate(
        f"Stable attractor\n"
        rf"$\nu^*={x_star:.3f}$,  $\rho^*={y_star:.3f}$",
        xy=(x_star, y_star), xytext=(-82, -52), textcoords="offset points",
        color="white", fontsize=10.5,
        bbox=dict(boxstyle="round,pad=0.3", fc=(0, 0, 0, 0.34), ec="white", lw=0.6),
        arrowprops=dict(arrowstyle="->", color="white", lw=0.9), zorder=9)

    ax.annotate(
        f"Current state  ({last_date:%Y-%m-%d})\n"
        f"VIX={current_vix:.2f},   ν={x_now:.3f},   ρ={y_now:.3f}",
        xy=(x_now, y_now), xytext=(22, 18), textcoords="offset points",
        color="white", fontsize=10.5,
        bbox=dict(boxstyle="round,pad=0.3", fc=(0, 0, 0, 0.38), ec="#ffd166", lw=0.9),
        arrowprops=dict(arrowstyle="->", color="#ffd166", lw=1.0), zorder=9)

    handles = [
        Line2D([0], [0], color="white", lw=1.6, label="empirical flow lines"),
        Line2D([0], [0], marker="*", color="none", markerfacecolor="#48a8ff",
               markeredgecolor="white", markersize=15, label="stable attractor"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#ffd166",
               markeredgecolor="black", markersize=10, label="current position"),
        Line2D([0], [0], color="#8fe3ff", lw=2.2, ls="--",
               label=r"effective curvature divider  $k_{\mathrm{eff}}=0$"),
    ]
    leg = ax.legend(handles=handles, loc="upper left", fontsize=10.2,
                    frameon=True, facecolor=(0, 0, 0, 0.30), edgecolor=(1, 1, 1, 0.18))
    for txt in leg.get_texts():
        txt.set_color("white")

    footnote = ("SYNTHETIC DATA – network unavailable; diagram is illustrative only.  "
                if synthetic else
                "k_eff is a public-data proxy (SPY + ^VIX only), "
                "not an option-surface curvature estimate.")
    ax.text(0.01, 0.01, footnote, transform=ax.transAxes,
            color="#ff9966" if synthetic else "#cfd8dc",
            fontsize=8.8, alpha=0.92, ha="left", va="bottom")

    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.grid(True, color="white", alpha=0.09, linewidth=0.8)
    ax.tick_params(colors="white", labelsize=11)
    for spine in ax.spines.values():
        spine.set_color((1, 1, 1, 0.18))

    fig.tight_layout(rect=[0.0, 0.02, 1.0, 0.93])
    return fig


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
def generate_figure_bytes() -> tuple[bytes, bool]:
    """
    Build the phase-plane figure and return it as raw PNG bytes.

    Returns
    -------
    (png_bytes, synthetic)
        png_bytes  : bytes — the rendered PNG
        synthetic  : bool  — True when the synthetic fallback was used
    """
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning)

    synthetic = False
    try:
        spy = _download(SPY_TICKER, START_DATE)
        vix = _download(VIX_TICKER, START_DATE)
    except Exception:
        spy, vix = _synthetic_data()
        synthetic = True

    data = _compute_state(spy, vix)
    if len(data) < 300:
        spy, vix = _synthetic_data()
        data      = _compute_state(spy, vix)
        synthetic = True

    fig = _build_figure(data, synthetic)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read(), synthetic


def generate_meta() -> dict:
    """
    Return current state scalar values as a plain dict (no chart).
    Used by the /api/phase-plane/meta endpoint for the KPI cards.
    """
    warnings.filterwarnings("ignore")
    synthetic = False
    try:
        spy = _download(SPY_TICKER, START_DATE)
        vix = _download(VIX_TICKER, START_DATE)
    except Exception:
        spy, vix = _synthetic_data()
        synthetic = True

    data = _compute_state(spy, vix)
    if len(data) < 300:
        spy, vix  = _synthetic_data()
        data      = _compute_state(spy, vix)
        synthetic = True

    last = data.iloc[-1]
    return {
        "vix":        round(float(last["VIX"]),     2),
        "nu":         round(float(last["vov_sm"]),   4),
        "rho":        round(float(last["rho_sm"]),   4),
        "date":       pd.Timestamp(data.index[-1]).strftime("%Y-%m-%d"),
        "n_obs":      len(data),
        "synthetic":  synthetic,
    }


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────
def main() -> None:
    png_bytes, synthetic = generate_figure_bytes()
    with open(OUTPUT_FILE, "wb") as f:
        f.write(png_bytes)
    tag = " (SYNTHETIC)" if synthetic else ""
    print(f"Saved{tag}: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
