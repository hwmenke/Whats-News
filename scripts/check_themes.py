#!/usr/bin/env python3
"""
check_themes.py — lint the social-trends ``themes.json`` file.

Catches the kinds of typos that quietly break the matcher:
  • missing or duplicate themes / tickers
  • out-of-range purity scores
  • keywords that are too short (false positives) or duplicated across themes
  • keywords with leading/trailing whitespace

Exit code is 0 when clean, non-zero when problems are found, so this script is
safe to wire into a pre-commit hook or CI.
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, "themes.json")


def main() -> int:
    with open(PATH, "r", encoding="utf-8") as f:
        themes = json.load(f)

    problems = []
    seen_themes = set()
    keyword_owners = defaultdict(list)  # keyword -> [theme,...]

    for i, th in enumerate(themes):
        name = th.get("theme", f"<theme #{i}>")
        if name in seen_themes:
            problems.append(f"duplicate theme name: {name}")
        seen_themes.add(name)

        kws = th.get("keywords") or []
        if not kws:
            problems.append(f"{name}: no keywords")
        seen_kws = set()
        for kw in kws:
            if not isinstance(kw, str):
                problems.append(f"{name}: non-string keyword {kw!r}")
                continue
            if kw != kw.strip():
                problems.append(f"{name}: keyword has whitespace {kw!r}")
            kw_l = kw.lower()
            if kw_l in seen_kws:
                problems.append(f"{name}: duplicate keyword {kw_l!r}")
            seen_kws.add(kw_l)
            if len(kw_l) < 2:
                problems.append(f"{name}: keyword too short {kw_l!r} (will false-positive)")
            keyword_owners[kw_l].append(name)

        seen_tickers = set()
        stocks = th.get("stocks") or []
        if not stocks:
            problems.append(f"{name}: no stocks")
        for st in stocks:
            tk = (st.get("ticker") or "").upper()
            if not tk:
                problems.append(f"{name}: stock missing ticker")
                continue
            if tk in seen_tickers:
                problems.append(f"{name}: duplicate ticker {tk}")
            seen_tickers.add(tk)
            try:
                p = float(st.get("purity", -1))
            except (TypeError, ValueError):
                problems.append(f"{name} / {tk}: non-numeric purity")
                continue
            if not 0.0 <= p <= 1.0:
                problems.append(f"{name} / {tk}: purity out of [0,1]: {p}")
            if not (st.get("name") or "").strip():
                problems.append(f"{name} / {tk}: missing display name")

    # Cross-theme keyword collisions (informational, not an error)
    print(f"{len(themes)} themes · {sum(len(t.get('stocks') or []) for t in themes)} stocks · "
          f"{sum(len(t.get('keywords') or []) for t in themes)} keywords")
    collisions = {k: v for k, v in keyword_owners.items() if len(v) > 1}
    if collisions:
        print(f"\nshared keywords ({len(collisions)}):")
        for k, owners in sorted(collisions.items()):
            print(f"  {k!r}: {', '.join(owners)}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("\n✓ themes.json looks clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
