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

### Iteration 1 detail (avg 5.5)

- **PM-A 5.5 (1.8×):** Regime vs KAMA20 visible; still wants relative-strength matrix / book heatmap.
- **PM-B 6.0 (2.0×):** RSI zone + 1.5×ATR stops help; wants alerts when RSI hits OB/OS.
- **PM-C 5.0 (1.7×):** Day % on watchlist helps; needs sorted tape + top gainer/loser banner + RS ranks.

## Stop condition

Stop the `/loop` when Iter avg ≥ 9.0 **and** min(PM-A×, PM-B×, PM-C×) ≥ 3.0.

## Next iteration candidates

1. Portfolio tape bar (sorted by day %, top gainer/loser)
2. RSI OB/OS badge alerts on watchlist
3. Relative strength rank (21D) across book
4. Keyboard: `j/k` symbols, `r` refresh, `/` add
5. One-click “setup card” copy (regime + stops + RSI)
