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

### Iteration 3 detail (avg 8.3)

- **PM-A 8.2 (2.7×):** Daily/weekly regime on desk + tape chips; still wants a denser multi-name regime heatmap.
- **PM-B 8.5 (2.8×):** Alert toasts + “Alerts only” filter are the swing workflow; wants persistent alert log.
- **PM-C 8.3 (2.8×):** Correlation hint + group rollup + Book news for weak/alert names; wants sector ETFs auto-context.

## Stop condition

Stop the `/loop` when Iter avg ≥ 9.0 **and** min(PM-A×, PM-B×, PM-C×) ≥ 3.0.

## Next iteration candidates

1. Compact regime heatmap (all names × D/W)
2. Persistent alert log panel
3. Auto-suggest peer ETF for active symbol
4. Position sizing helper from ATR% risk
5. Save/load watchlist presets
