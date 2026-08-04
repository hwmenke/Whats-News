# capstruct — SEC Capital Structure & Liquidity Extractor

Builds an as-of-date capital structure for a US-listed issuer directly from SEC
filings, with every figure traceable back to the filing it came from.

Runs standalone (CLI) or summoned by FinDash (**Cap Structure** tab →
`GET /api/capstruct/<ticker>`).

## Status

Phase 1 of the build sequence is complete: EDGAR client, rate limiter, cache,
filing selection, XBRL liquidity/equity extraction, and the net-debt bridge.

| Layer | State |
|---|---|
| `edgar/` — client, token bucket, cache, tickers, filing selection | done |
| `xbrl/` — companyfacts, tag fallback chains | done (liquidity + equity) |
| `models/` — `Sourced[T]` provenance, snapshot schema | done |
| `analytics/` — net-debt bridge | done |
| `documents/` — footnote location + HTML→text | not started |
| `extract/` — LLM structured extraction | not started |
| straight debt · convertibles · warrants · preferred | not started |

Instrument collections are already in the schema as empty lists, so the shape
never changes as those land.

## Setup

SEC requires a descriptive User-Agent with a contact email on every request and
refuses traffic without one:

```bash
export CAPSTRUCT_USER_AGENT="YourName Research you@example.com"
```

## Use

```bash
capstruct fetch AAPL
capstruct fetch AAPL --as-of 2025-06-30
capstruct fetch 0000320193 --output capital_structure.json
capstruct audit AAPL                      # provenance for every field
```

Or from FinDash: pick a watchlist symbol, open **Cap Structure**, press
**Extract Capital Structure**.

## Design decisions worth knowing

**Point-in-time by default.** `--as-of 2025-06-30` means *what was knowable on
that date* — only filings with `filing_date <= as_of` are eligible. A Q2 balance
sheet filed in August will not appear in a June snapshot. Pass `--period-based`
for the other reading (latest data *for* a period, regardless of when it was
filed).

**Amendments supersede.** A 10-K/A replaces the 10-K for the same period;
filings are folded by `(base form, period end)` with the newest filing date
winning, so a restatement never double-counts.

**Cache policy is not uniform.** Documents under `/Archives/` are immutable once
filed and cached forever. `companyfacts` / `companyconcept` / `submissions` are
*rebuilt* as new filings land, so they get a 6-hour TTL plus ETag revalidation —
caching those aggressively would silently serve a stale capital structure.

**Tag fallback degrades confidence.** Each concept has an ordered tag chain
(most specific first). Falling past the preferred tag drops confidence from
`high` to `medium`/`low`, because the later tags are broader roll-ups — e.g.
`CashCashEquivalentsRestrictedCash…` includes restricted cash and is not the
same number as the clean cash tag.

**Cover-page facts are `dei`, not `us-gaap`.** Shares outstanding from the
10-K/10-Q cover page (`dei:EntityCommonStockSharesOutstanding`) is more current
than the balance-sheet figure; both are captured with their own dates.

**Nothing is silently null.** A field is either `Sourced[T]` with a full audit
trail, or `Missing` naming every tag that was tried and why it failed.

**An incomplete net-debt bridge says so.** Missing cash overstates net debt;
missing debt understates it. Both are wrong, so `incomplete` and explanatory
notes travel with the result rather than a smaller-looking number. Restricted
cash is deliberately *not* netted (it can't repay debt) but is surfaced.

## Rate limiting

Hard 10 req/s SEC cap; the bucket defaults to 9/s because the limit is enforced
over a sliding window on their side and a full-rate client plus clock skew is
what turns "at the limit" into "blocked IP". Thread-safe — the client is
designed to be driven from a pool.

## Tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -t . -p "test_*.py"
```

31 tests, no network: the limiter runs on an injected clock, the client on an
`httpx.MockTransport`, and the XBRL layer against hand-built companyfacts
fixtures encoding each trap (fallback chains, `dei` namespace, extension
taxonomies, point-in-time selection).

Next step per the build sequence is fixture capture from real filings for the
five instructive issuers (clean IG filer, live convertible with capped call,
de-SPAC with liability-classified warrants, multi-class shares, custom
extension tags) — that needs SEC network access, which is currently blocked in
this environment.
