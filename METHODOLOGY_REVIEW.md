# Methodology Review — Whats-News

Specialist audits of the current PM Desk branch against five trading schools.
Agents: [Brandt](bc-7d9b7a9e-6e23-51ce-8919-bba5c837351e) · [Qullamaggie](bc-1c88a8b8-9aea-58a3-b9d4-588fc676d648) · [Neumann](bc-4704709a-edfb-5ee7-96ec-c102ddd99942) · [Darvas](bc-e5ef3fb6-8e2f-57ba-adc1-e102514c325b) · [O’Neil](bc-eec22bc7-62f3-5fef-9a95-d33123cb5023).

## Shared verdict

Whats-News is a strong **local risk + book-scan desk** (tape, D/W regime, RS-in-book, ATR size, Yahoo news). It is **not yet** a classical-chart, Darvas-box, CAN SLIM, or Qullamaggie breakout factory. Biggest shared risk: **over-claiming** (calling KAMA/RSI/ATR a “pattern,” “box,” or “IBD RS”).

| School | Fit today | One-line gap |
|--------|-----------|--------------|
| **Brandt** | Risk sizing + D/W charts align; structure does not | No drawings, pivots, measured-move risk box |
| **Qullamaggie** | RS tape / “what’s working” aligns | No VCP/EP/MA-stack; RSI alerts are anti-fit for entries |
| **Neumann** | Pre-trade scan + ATR size strong | No checklist, journal, or R-tracking |
| **Darvas** | Strength/RS attitude; stops “rhyme” | No boxes, breakout-from-box, stop-at-box-low |
| **O’Neil / CAN SLIM** | Partial L + light M | No C–A–N/I; book RS ≠ IBD RS Rating |

## Cross-cutting must-not-dos

1. Don’t label indicator confluence (KAMA regime + RSI + 1.5×ATR) as classical/Darvas/Factor setups.
2. Don’t brand watchlist 21D ranks as IBD **RS Ratings**, or invent EPS/sponsorship.
3. Don’t make **RSI OS / weak RS** the default “what to trade” loop for a momentum product.
4. Don’t add more predictive tabs before checklist + journal + structural risk exist.

## Prioritized suggestions (merged)

### High (ship next)

1. **Structural / user risk box** — entry · stop · target on chart; size off *user stop*, ATR as fallback (Brandt + Neumann + Qullamaggie risk).
2. **Honest RS + breakout queue** — UI label “Book RS (21D)”; tape filter: near N-day high + volume surge + D/W up (O’Neil + Qullamaggie).
3. **Playbook checklist → Copy setup → journal + R** (Neumann; helps all).
4. **Darvas box levels** (high/low/state) + breakout alert lane; chart overlay; stop option = last box low (Darvas).
5. **Price-first chart mode** — hide RSI/MACD/Trend Score by default (Brandt “keep it simple”).

### Medium

6. VCP / contraction score + volume dry-up (Qullamaggie).
7. EP path: gap + volume; Book news → **strong** names, not weakest RS (Qullamaggie).
8. Simple **M panel** on SPY/QQQ (O’Neil).
9. Theme leader board by `group_tag` / peer ETF (Qullamaggie + O’Neil).
10. Drawing tools: horizontals, trendlines, swing pivots (Brandt).
11. Yahoo-honest “N lite” (earnings date if present) — never fake C/A (O’Neil).
12. Optional EMA 10/20/50 stack strip beside KAMA (Qullamaggie).

## What to keep

- Dual daily/weekly charts and D/W regime heatmap  
- Book tape, day %, peer ETF, ATR `$` risk sizing  
- Real Yahoo news (no placeholder magazine)  
- Local SQLite / no API keys  

## Suggested product north star

**One desk, multiple lenses (presets)** — not five separate apps:

| Preset | Default alerts / tape | Chart mode |
|--------|----------------------|------------|
| Classical (Brandt) | Structure / range breaks | Price + drawings |
| Momentum (Qullamaggie) | Near-high + tight + EP | MA stack + volume |
| Process (Neumann) | Checklist gate | Setup card → journal |
| Boxes (Darvas) | Box breakout / fail | Box overlay |
| Growth (O’Neil) | Book RS + M clock + vol@high | Bases later; fundamentals only if real |

## TA specialist agents (repo)

Cursor agent prompts live in `.cursor/agents/` (Minervini, Stockbee, Qullamaggie, Darvas,
Brandt, Stage/Jacobs, O’Neil). Scanner families **Minervini** / **Stockbee** are wired in
`ta_templates.py` + `setup_scanner.py` as **mechanical book tags only** — never licensed
SEPA, Stockbee Market Monitor, IBD RS, or Factor signals.

---

*Synthesized for Caspar’s Whats-News. Full specialist write-ups were produced by the five agents linked above.*
