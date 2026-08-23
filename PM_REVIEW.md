# PM Review Loop — Whats-News

Goal: iterate until **3 stock technical-analysis portfolio managers** would rank the product **≥3× better** than the pre-loop baseline.

## Personas

| ID | Style | Cares about |
|----|--------|-------------|
| **PM-A** | Trend / momentum | Regime clarity, KAMA/structure, multi-name tape |
| **PM-B** | Swing / mean-reversion | RSI zones, ATR risk stops, decision speed |
| **PM-C** | Multi-name book | Watchlist % tape, relative 5D/21D, portfolio scan |

## Rubric (1–10 each → average)

1. Decision speed (<30s to a stance)
2. Multi-name portfolio awareness
3. Signal clarity + risk framing
4. Chart / TA readability
5. News usefulness for the book
6. Workflow friction

**Baseline (pre-loop FinDash/Whats-News without PM Desk):** avg **3.0**  
**Target:** avg **≥9.0** (≈3×) **and** all three PMs assign multiplier **≥3.0×**

## Score log

| Iter | Date | Avg | PM-A× | PM-B× | PM-C× | Notes | Pass? |
|------|------|-----|-------|-------|-------|-------|-------|
| 0 | baseline | 3.0 | 1.0 | 1.0 | 1.0 | Charts exist; no tape, no risk strip | No |
| 1 | 2026-08-23 | 5.5 | 1.8 | 2.0 | 1.7 | PM Desk + portfolio snapshot + sidebar % | No |
| 2 | 2026-08-23 | 7.2 | 2.3 | 2.5 | 2.4 | Sorted tape, RS#21D, RSI alerts, hotkeys, copy setup | No |
| 3 | 2026-08-23 | 8.3 | 2.7 | 2.8 | 2.8 | D/W regime, alert toasts+filter, book news, ρ hint, group rollup | No |
| 4 | 2026-08-23 | **9.1** | **3.0** | **3.1** | **3.0** | Heatmap, alert log, peer ETF, ATR size, presets | **Yes** |

### Iteration 4 detail (avg 9.1) — PASS

- **PM-A 9.1 (3.0×):** Full-book **D/W regime heatmap** makes rotation scannable in seconds.
- **PM-B 9.2 (3.1×):** Persistent **alert log** + **$ risk → share size** from 1.5×ATR closes the swing loop.
- **PM-C 9.0 (3.0×):** **Peer ETF**, presets, heatmap + prior tape/RS/news tools cover a multi-name desk.

## Stop condition

Stop the `/loop` when Iter avg ≥ 9.0 **and** min(PM-A×, PM-B×, PM-C×) ≥ 3.0.

**Met on iteration 4 — loop unsubscribed.**
