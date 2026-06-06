# Reference X post ID: https://x.com/hnnngmnk/status/2048884245158846885
"""
Recreate a conceptual SPY/VIX phase-plane diagram using only public yfinance data.

State variables used in the phase plane
----------------------------------------
nu  : public vol-of-vol proxy
      = annualized 21-day standard deviation of daily log changes in the VIX
rho : public leverage proxy
      = 63-day rolling correlation between SPY log returns and VIX log changes

Notes
-----
1) The original X chart is conceptual and references information-geometric ideas
   (Bruce H. Dean's preprint on smile geometry). With yfinance alone we do not
   have an option surface, so the plot below uses transparent, fully public
   proxies constructed from SPY and ^VIX time series.

2) The effective-curvature divider is approximated by a simple linear proxy
   centered at the empirical attractor:
       k_eff = (nu - nu*) + lambda * (rho - rho*)
   where (nu*, rho*) is the empirical attractor and lambda rescales the rho-axis
   to the same order of magnitude as the nu-axis. Positive k_eff → smile region;
   negative k_eff → frown region.

3) White streamlines are empirical average drifts in (nu, rho) space, built
   from forward changes of the rolling state over a short horizon.

Output
------
Saves a publication-style figure as: spy_vix_phase_plane.png
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # non-interactive backend so it runs headless
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.ndimage import gaussian_filter
from scipy.stats import gaussian_kde
import yfinance as yf

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
START_DATE   = "1990-01-01"
SPY_TICKER   = "SPY"
VIX_TICKER   = "^VIX"

# Rolling windows (trading days)
VOV_WINDOW   = 21    # vol-of-vol rolling std window
CORR_WINDOW  = 63    # rolling correlation window (~3 months)
SMOOTH_SPAN  = 5     # EWM span for mild state smoothing
FLOW_HORIZON = 5     # forward steps for empirical drift vectors

# Grid dimensions / smoothing for empirical vector field
NX_BINS      = 34
NY_BINS      = 30
SMOOTH_SIGMA = 1.25  # Gaussian smoothing σ applied to histogram bin counts

# Plot output
OUTPUT_FILE  = "spy_vix_phase_plane.png"
SHOW_PLOT    = False  # set True to pop up a window
DPI          = 320


# ─────────────────────────────────────────────
# Data download helper
# ─────────────────────────────────────────────
def download_adj_close(ticker: str, start: str) -> pd.Series:
    """Download a single ticker and return adjusted-close (or close) as a Series."""
    df = yf.download(
        ticker,
        start=start,
        progress=False,
        auto_adjust=False,
        actions=False,
    )
    if df.empty:
        raise RuntimeError(f"No data returned for {ticker}.")

    # yfinance sometimes returns a MultiIndex even for a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        for col in df.columns:
            label = " ".join(map(str, col)).lower()
            if "adj close" in label:
                return df[col].squeeze().rename(ticker)
        for col in df.columns:
            label = " ".join(map(str, col)).lower()
            if "close" in label:
                return df[col].squeeze().rename(ticker)
    else:
        if "Adj Close" in df.columns:
            return df["Adj Close"].rename(ticker)
        if "Close" in df.columns:
            return df["Close"].rename(ticker)

    raise KeyError(f"Could not find close column for {ticker}.")


# ─────────────────────────────────────────────
# Phase-state construction
# ─────────────────────────────────────────────
def compute_phase_state(spy_close: pd.Series, vix_close: pd.Series) -> pd.DataFrame:
    """
    Build the two public proxy state variables (nu, rho) used in the phase plane.

    nu  = annualized rolling std of daily VIX log-changes  (vol-of-vol proxy)
    rho = rolling correlation of SPY log-returns with VIX log-changes
    """
    data = pd.concat([spy_close, vix_close], axis=1, join="inner").dropna().copy()
    data.columns = ["SPY", "VIX"]
    data = data[(data["SPY"] > 0) & (data["VIX"] > 0)]

    # Daily log changes
    data["spy_logret"] = np.log(data["SPY"]).diff()
    data["vix_logret"] = np.log(data["VIX"]).diff()

    # Vol-of-vol proxy: annualized σ of daily Δlog(VIX)
    data["vov"] = data["vix_logret"].rolling(VOV_WINDOW).std() * np.sqrt(252.0)

    # Leverage-effect proxy: rolling correlation of equity returns with vol changes
    data["rho"] = data["spy_logret"].rolling(CORR_WINDOW).corr(data["vix_logret"])

    # Mild EWM smoothing so the phase trajectory is readable
    data["vov_sm"] = data["vov"].ewm(span=SMOOTH_SPAN, adjust=False, min_periods=3).mean()
    data["rho_sm"] = data["rho"].ewm(span=SMOOTH_SPAN, adjust=False, min_periods=3).mean()

    return data.dropna(subset=["vov_sm", "rho_sm"])


# ─────────────────────────────────────────────
# Empirical flow field
# ─────────────────────────────────────────────
def build_flow_field(
    x: pd.Series,
    y: pd.Series,
    horizon: int = FLOW_HORIZON,
    nx: int = NX_BINS,
    ny: int = NY_BINS,
    sigma: float = SMOOTH_SIGMA,
    include_x: tuple[float, ...] | None = None,
    include_y: tuple[float, ...] | None = None,
):
    """
    Average forward state changes inside bins of the (nu, rho) plane.

    We compute empirical drift (dx, dy) over `horizon` steps, bin observations
    on a regular grid, Gaussian-smooth the sums and counts, and return the
    per-cell average velocities ready for matplotlib's streamplot.
    """
    dx = x.shift(-horizon) - x
    dy = y.shift(-horizon) - y
    phase = pd.DataFrame({"x": x, "y": y, "dx": dx, "dy": dy}).dropna()

    xv = phase["x"].to_numpy()
    yv = phase["y"].to_numpy()
    du = phase["dx"].to_numpy() / float(horizon)
    dv = phase["dy"].to_numpy() / float(horizon)

    # Axis limits: 1–99 percentile range, padded 10 %
    xq = np.quantile(xv, [0.01, 0.99])
    yq = np.quantile(yv, [0.01, 0.99])
    x_range = max(xq[1] - xq[0], 1e-6)
    y_range = max(yq[1] - yq[0], 1e-6)
    x_pad, y_pad = 0.10 * x_range, 0.10 * y_range

    x_lo = max(0.0, xq[0] - x_pad)
    x_hi = xq[1] + x_pad
    y_lo = yq[0] - y_pad
    y_hi = yq[1] + y_pad

    # Make sure the current / attractor points are inside the grid
    if include_x:
        x_lo = min(x_lo, min(include_x) - 0.05 * x_range)
        x_hi = max(x_hi, max(include_x) + 0.05 * x_range)
    if include_y:
        y_lo = min(y_lo, min(include_y) - 0.05 * y_range)
        y_hi = max(y_hi, max(include_y) + 0.05 * y_range)

    # Correlation is bounded by [-1, 1]; cap with a small headroom
    y_lo = max(-1.0, y_lo)
    y_hi = min(0.20, y_hi)

    # Safety guards against degenerate ranges
    if not np.isfinite(x_lo) or not np.isfinite(x_hi) or x_hi <= x_lo:
        x_lo = max(0.0, float(np.nanmin(xv)) - 0.05)
        x_hi = float(np.nanmax(xv)) + 0.05
    if not np.isfinite(y_lo) or not np.isfinite(y_hi) or y_hi <= y_lo:
        y_lo = max(-1.0, float(np.nanmin(yv)) - 0.05)
        y_hi = min(1.0, float(np.nanmax(yv)) + 0.05)

    xedges = np.linspace(x_lo, x_hi, nx + 1)
    yedges = np.linspace(y_lo, y_hi, ny + 1)

    count = np.histogram2d(xv, yv, bins=[xedges, yedges])[0]
    sum_u = np.histogram2d(xv, yv, bins=[xedges, yedges], weights=du)[0]
    sum_v = np.histogram2d(xv, yv, bins=[xedges, yedges], weights=dv)[0]

    # Smooth numerators and denominator before dividing
    count_s = gaussian_filter(count, sigma=sigma, mode="nearest")
    sum_u_s = gaussian_filter(sum_u, sigma=sigma, mode="nearest")
    sum_v_s = gaussian_filter(sum_v, sigma=sigma, mode="nearest")

    with np.errstate(divide="ignore", invalid="ignore"):
        u = sum_u_s / np.maximum(count_s, 1e-12)
        v = sum_v_s / np.maximum(count_s, 1e-12)

    xcenters = 0.5 * (xedges[:-1] + xedges[1:])
    ycenters = 0.5 * (yedges[:-1] + yedges[1:])

    # streamplot wants shape (len(y_centers), len(x_centers)) — transpose
    u = u.T
    v = v.T
    density = count_s.T

    # Mask low-support cells so streamlines stay in the data cloud
    if np.any(density > 0):
        support_floor = max(
            0.05 * np.nanmax(density),
            np.nanpercentile(density[density > 0], 15),
        )
    else:
        support_floor = 0.0
    support_mask = density < support_floor

    # Variable line-width proportional to local flow speed
    speed = np.sqrt(u**2 + v**2)
    max_speed = np.nanmax(speed) if np.nanmax(speed) > 0 else 1.0
    linewidth = 0.70 + 1.50 * (speed / max_speed)

    u         = np.ma.masked_where(support_mask, u)
    v         = np.ma.masked_where(support_mask, v)
    linewidth = np.ma.masked_where(support_mask, linewidth)

    return xcenters, ycenters, u, v, density, linewidth


# ─────────────────────────────────────────────
# Stable attractor estimation
# ─────────────────────────────────────────────
def estimate_attractor(
    x: pd.Series,
    y: pd.Series,
    xlim: tuple[float, float],
    ylim: tuple[float, float],
):
    """
    Estimate the stable attractor as the mode of the historical state density
    (KDE peak). Falls back to the sample mean if KDE fails.
    """
    xv = x.to_numpy()
    yv = y.to_numpy()
    try:
        kde = gaussian_kde(np.vstack([xv, yv]))
        gx = np.linspace(xlim[0], xlim[1], 240)
        gy = np.linspace(ylim[0], ylim[1], 240)
        xx, yy = np.meshgrid(gx, gy)
        zz = kde(np.vstack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
        iy, ix = np.unravel_index(np.nanargmax(zz), zz.shape)
        return float(xx[iy, ix]), float(yy[iy, ix]), zz
    except Exception:
        return float(np.nanmean(xv)), float(np.nanmean(yv)), None


# ─────────────────────────────────────────────
# Smile / frown divider
# ─────────────────────────────────────────────
def effective_curvature_divider(
    x_values: np.ndarray,
    x_star: float,
    y_star: float,
    x_hist: pd.Series,
    y_hist: pd.Series,
) -> tuple[np.ndarray, float]:
    """
    Approximate the k_eff = 0 divider using a linear proxy centred at the
    empirical attractor (nu*, rho*):

        k_eff(nu, rho) = (nu - nu*)  +  λ * (rho - rho*)

    λ is set from the historical scale ratio of the two axes so both
    coordinates contribute on a comparable footing.

    Positive k_eff → "smile region"; negative k_eff → "frown region".
    This is an approximation; a true option-surface curvature estimate
    would require implied-vol surface data.
    """
    x_scale = float(np.nanstd(x_hist.to_numpy()))
    y_scale = float(np.nanstd(y_hist.to_numpy()))
    lam = max(x_scale / max(y_scale, 1e-8), 1e-3)

    # Solve k_eff = 0  →  rho = rho* - (nu - nu*) / λ
    y_div = y_star - (x_values - x_star) / lam
    return y_div, lam


# ─────────────────────────────────────────────
# Main plot
# ─────────────────────────────────────────────
def make_plot(data: pd.DataFrame) -> plt.Figure:
    """Build and save the phase-plane figure."""
    x = data["vov_sm"]
    y = data["rho_sm"]

    x_now       = float(x.iloc[-1])
    y_now       = float(y.iloc[-1])
    current_vix = float(data["VIX"].iloc[-1])
    last_date   = pd.Timestamp(data.index[-1])

    # ── Empirical drift field ──────────────────────────────────────────────
    xg, yg, u, v, density, linewidth = build_flow_field(
        x, y,
        include_x=(x_now,),
        include_y=(y_now,),
    )
    xlim = (float(xg[0]), float(xg[-1]))
    ylim = (float(yg[0]), float(yg[-1]))

    # ── Stable attractor (KDE mode) ────────────────────────────────────────
    x_star, y_star, _ = estimate_attractor(x, y, xlim, ylim)

    # ── k_eff = 0 divider line ─────────────────────────────────────────────
    x_line = np.linspace(xlim[0], xlim[1], 500)
    y_div, lam = effective_curvature_divider(x_line, x_star, y_star, x, y)

    # ── Figure / axes styling ──────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(13.2, 8.6), facecolor="#0b1220")
    ax.set_facecolor("#101826")

    # Shaded smile / frown regions
    ax.fill_between(x_line, y_div, ylim[1],  color="#2f5b91", alpha=0.28, zorder=0)
    ax.fill_between(x_line, ylim[0], y_div,  color="#8e2f3f", alpha=0.25, zorder=0)

    # Subtle historical state cloud
    ax.scatter(x, y, s=8, c="white", alpha=0.045, linewidths=0, zorder=1)

    # ── Empirical flow streamlines ─────────────────────────────────────────
    try:
        ax.streamplot(
            xg, yg, u, v,
            color="white",
            density=1.8,
            linewidth=linewidth,
            arrowsize=1.0,
            minlength=0.08,
            maxlength=5.0,
            integration_direction="both",
            zorder=3,
        )
    except Exception:
        # Fallback: quiver plot if streamplot chokes on masked arrays
        xx, yy = np.meshgrid(xg, yg)
        ax.quiver(
            xx, yy,
            np.ma.filled(u, np.nan),
            np.ma.filled(v, np.nan),
            color="white",
            alpha=0.75,
            zorder=3,
        )

    # ── Effective-curvature divider ────────────────────────────────────────
    ax.plot(x_line, y_div, ls="--", lw=2.2, color="#8fe3ff", alpha=0.95, zorder=4)

    # ── Stable attractor marker ────────────────────────────────────────────
    ax.scatter(
        x_star, y_star,
        s=260, marker="*",
        c="#48a8ff", edgecolors="white", linewidths=1.3,
        zorder=6,
    )

    # ── Current state marker ───────────────────────────────────────────────
    ax.scatter(
        x_now, y_now,
        s=150, marker="o",
        c="#ffd166", edgecolors="black", linewidths=1.1,
        zorder=7,
    )

    # ── Titles & axis labels ───────────────────────────────────────────────
    title = (
        "Phase Plane of Smile Coefficients – SPY/VIX Empirical Flows"
        f" (through {last_date:%B %Y})"
    )
    subtitle = (
        r"State proxies:  $\nu$ = 21 d ann. std of $\Delta\!\log(\mathrm{VIX})$,"
        r"   $\rho$ = 63 d rolling corr[SPY log-return,  $\Delta\!\log(\mathrm{VIX})$]"
    )
    ax.set_title(title, fontsize=16, color="white", weight="bold", pad=18)
    fig.text(0.5, 0.955, subtitle, ha="center", va="top",
             color="#cfd8dc", fontsize=10.0)

    ax.set_xlabel(r"Vol-of-vol proxy,  $\nu$",       fontsize=13, color="white")
    ax.set_ylabel(r"Correlation proxy,  $\rho$", fontsize=13, color="white")

    # ── Region labels ──────────────────────────────────────────────────────
    xr = xlim[1] - xlim[0]
    yr = ylim[1] - ylim[0]

    ax.text(xlim[1] - 0.06 * xr, ylim[1] - 0.06 * yr,
            "smile region", color="#dbeeff", fontsize=13, weight="bold",
            ha="right", va="top", zorder=8)
    ax.text(xlim[0] + 0.06 * xr, ylim[0] + 0.08 * yr,
            "frown region", color="#ffd9dc", fontsize=13, weight="bold",
            ha="left", va="bottom", zorder=8)

    # ── k_eff label on the divider line ───────────────────────────────────
    x_lab = xlim[0] + 0.64 * xr
    y_lab = y_star - (x_lab - x_star) / lam
    ax.text(
        x_lab, y_lab + 0.03 * yr,
        r"$k_{\mathrm{eff}} = 0$",
        color="#cfffff", fontsize=12, weight="bold",
        ha="center", va="bottom",
        bbox=dict(boxstyle="round,pad=0.22", fc=(0, 0, 0, 0.22), ec="none"),
        zorder=8,
    )

    # ── Attractor annotation ───────────────────────────────────────────────
    ax.annotate(
        "Stable attractor\n"
        rf"$\nu^*={x_star:.3f}$,  $\rho^*={y_star:.3f}$",
        xy=(x_star, y_star),
        xytext=(-82, -52),
        textcoords="offset points",
        color="white", fontsize=10.5,
        bbox=dict(boxstyle="round,pad=0.3", fc=(0, 0, 0, 0.34), ec="white", lw=0.6),
        arrowprops=dict(arrowstyle="->", color="white", lw=0.9),
        zorder=9,
    )

    # ── Current-state annotation ───────────────────────────────────────────
    ax.annotate(
        f"Current state  ({last_date:%Y-%m-%d})\n"
        f"VIX={current_vix:.2f},   ν={x_now:.3f},   ρ={y_now:.3f}",
        xy=(x_now, y_now),
        xytext=(22, 18),
        textcoords="offset points",
        color="white", fontsize=10.5,
        bbox=dict(boxstyle="round,pad=0.3", fc=(0, 0, 0, 0.38),
                  ec="#ffd166", lw=0.9),
        arrowprops=dict(arrowstyle="->", color="#ffd166", lw=1.0),
        zorder=9,
    )

    # ── Legend ─────────────────────────────────────────────────────────────
    handles = [
        Line2D([0], [0], color="white", lw=1.6,
               label="empirical flow lines"),
        Line2D([0], [0], marker="*", color="none",
               markerfacecolor="#48a8ff", markeredgecolor="white",
               markersize=15, label="stable attractor"),
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor="#ffd166", markeredgecolor="black",
               markersize=10, label="current position"),
        Line2D([0], [0], color="#8fe3ff", lw=2.2, ls="--",
               label=r"effective curvature divider  $k_{\mathrm{eff}}=0$"),
    ]
    leg = ax.legend(handles=handles, loc="upper left", fontsize=10.2,
                    frameon=True,
                    facecolor=(0, 0, 0, 0.30),
                    edgecolor=(1, 1, 1, 0.18))
    for txt in leg.get_texts():
        txt.set_color("white")

    # ── Footnote ───────────────────────────────────────────────────────────
    ax.text(
        0.01, 0.01,
        "k_eff is a public-data proxy (SPY + ^VIX only), "
        "not an option-surface curvature estimate.",
        transform=ax.transAxes, color="#cfd8dc", fontsize=8.8,
        alpha=0.92, ha="left", va="bottom",
    )

    # ── Final axis formatting ──────────────────────────────────────────────
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.grid(True, color="white", alpha=0.09, linewidth=0.8)
    ax.tick_params(colors="white", labelsize=11)
    for spine in ax.spines.values():
        spine.set_color((1, 1, 1, 0.18))

    fig.tight_layout(rect=[0.0, 0.02, 1.0, 0.93])
    fig.savefig(OUTPUT_FILE, dpi=DPI, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    return fig


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
def main() -> None:
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning)

    print("Downloading SPY and ^VIX data …")
    spy_close = download_adj_close(SPY_TICKER, START_DATE)
    vix_close = download_adj_close(VIX_TICKER, START_DATE)

    print("Computing phase-state variables …")
    data = compute_phase_state(spy_close, vix_close)
    if len(data) < 300:
        raise RuntimeError(
            f"Too few observations ({len(data)}) after building rolling state variables."
        )
    print(f"  {len(data)} trading days of state data "
          f"({data.index[0].date()} → {data.index[-1].date()})")

    print("Building plot …")
    fig = make_plot(data)
    print(f"Saved figure to: {OUTPUT_FILE}")

    if SHOW_PLOT:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()
