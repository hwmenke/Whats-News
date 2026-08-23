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

### Iteration 2 detail (avg 7.2)

- **PM-A 7.0 (2.3×):** Book tape + RS ranks help momentum rotation; still missing trend heatmap / multi-TF regime grid.
- **PM-B 7.5 (2.5×):** RSI_OB/OS badges + `c` copy setup + `j/k` speed are real; wants toast when alerts appear and alert filter.
- **PM-C 7.2 (2.4×):** Sorted day tape + gainer/loser/RS#1 meta is usable for a small book; wants correlation / sector buckets and news tied to alert names.

## Stop condition

Stop the `/loop` when Iter avg ≥ 9.0 **and** min(PM-A×, PM-B×, PM-C×) ≥ 3.0.

## Next iteration candidates

1. Toast + filter for RSI OB/OS alerts
2. Multi-TF regime mini-grid (D vs W) on PM Desk
3. News filtered to symbols currently alerting / weakest RS
4. Simple pairwise correlation hint for top-2 names
5. Sector/group rollup on tape
