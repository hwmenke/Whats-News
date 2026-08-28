# Suggestions for Whats-News

Ideas to improve the product beyond this UX pass. Prioritized roughly by impact vs effort.

## High impact

1. **Default single-process, optional split**  
   Keep the “data service + analysis app” work (PR #10) as an advanced mode. Friends should keep using `./start.sh` (one process). Auto-start both processes only when explicitly requested.

2. **One news surface**  
   Today there is `/news` *and* an in-dashboard News tab. Pick one primary UX (or clearly label “this symbol” vs “whole watchlist”) and share one component.

3. **Smarter first fetch**  
   After adding a symbol, auto-fetch history once so the chart isn’t empty. Show a clear progress toast.

4. **Watchlist search / folders at scale**  
   When the list grows past ~50 tickers, add filter-as-you-type and stronger group tags (ties into the SQLite scaling PR).

5. **Offline / rate-limit honesty**  
   Yahoo can throttle. Surface a friendly “try again in a minute” banner instead of a blank chart.

## Medium impact

6. **Light theme or system preference** — current UI is dark-only.  
7. **Export CSV** of OHLCV or scanner results.  
8. **Keyboard shortcuts** — `/` focus add-symbol, `r` refresh active, `n` open news.  
9. **Docker Compose** — zero local Python for people who already use Docker.  
10. **Windows double-click launcher** (`start.bat`) mirroring `start.sh`.

## Nice to have

11. Portfolio notes / tags per symbol.  
12. Email or desktop digest of overnight headlines (still no fake stories).  
13. Pin favorite charts.  
14. CI badge + GitHub Action running `unittest`.  
15. Short Loom/GIF in the README showing add → chart → news.

## Please avoid

- Shipping placeholder / magazine-style fake headlines (see rejected PR #5 approach).  
- Committing `finance.db` or API keys.  
- Dropping a second design system (React/Babel) on top of the current CSS unless you intentionally rebuild the UI.

---

PRs already related: news (#7/#8), SQLite scale (#9), data-service split (#10). Merge order suggestion: UX (this) → scale → split, with split defaulting to embedded for casual use.
