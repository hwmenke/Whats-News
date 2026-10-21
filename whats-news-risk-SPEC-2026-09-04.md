# Whats-News Quant Risk SPEC — 2026-09-04

Locked sheet. Paper / Yahoo stored closes only. No live orders. Never invent P&L.

1. **VaR 95 & 99** — parametric Gaussian μ=0 (60d Σ) + historical empirical quantile (N≥60, prefer 252); label method; 1d horizon.
2. **MVaR** = z·(Σw)_i/σ·MV; **CVaR** = w_i·MVaR (Euler, Σ CVaR = VaR); % of port VaR; **IVaR** = VaR − VaR without i (renorm); rank main risk by %VaR.
3. **Vol:** show 20d & 60d ann √252 ddof=1; **cov/VaR use 60d**.
4. **Perf:** day/week/MTD/YTD, max DD, Sharpe/Sortino rf=0; blank if short; synthetic NAV labeled if no true equity curve — never invent P&L.
5. **Per-name:** w, σ, β_SPY 60d, MVaR/CVaR/%VaR, FLAG (CONC/HIGH_BETA/VOL_SPIKE/THIN/SHORT).
6. **Clusters:** σ20 vs σ60 HOT/COLD; hierarchical average linkage on d=√(0.5(1−ρ)), cut 0.7; cluster %VaR.
7. **Thin:** <3 names or <60 overlap days or singular cov → blank stack.

FLAG notes (only cutoffs that already exist on this desk or are stated above):
- CONC: weight ≥ 25% (existing `CONCENTRATED_TOP_WEIGHT`).
- SHORT: side is short.
- THIN: name has fewer than 61 stored daily closes.
- VOL_SPIKE: σ20 > σ60 (same comparison as cluster HOT).
- HIGH_BETA: listed as a FLAG; no numeric cutoff is on this sheet — do not invent one.

Web + iPhone Risk surface. Tests assert thin-book blanks + Euler sum.
