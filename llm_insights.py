"""
llm_insights.py — LLM-augmented narratives, explanations, and critiques.

Three public functions, each aggressively cached (TTL keyed by input hash):
    • daily_narrative(payload) -> str
        "3 things to watch today" from the latest social-trends payload.
    • explain_trend(term, payload) -> str
        plain-English "why is this trending?" with the data as evidence.
    • critique_idea(idea, payload) -> str
        contrarian "why might this 🚀 Hot · Cold signal be wrong?" read.

If ``ANTHROPIC_API_KEY`` is set we call the Claude API; otherwise we fall back
to a template-and-rules synthesiser that still produces useful text purely
from the data, so the UI is meaningful even without a key.
"""

import hashlib
import json
import os
import time


_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 3600   # 1 hour — facts about a trend don't change fast


def _hash_inputs(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p if isinstance(p, str) else json.dumps(p, sort_keys=True, default=str)).encode())
    return h.hexdigest()[:16]


def _cached(key: str):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _store(key: str, value: str):
    _CACHE[key] = (time.time(), value)
    return value


# ── Anthropic client (optional) ──────────────────────────────────────────────
def _call_claude(system: str, user: str) -> str | None:
    """Return Claude's text reply, or None if the SDK / key isn't available."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        print("!! llm_insights: anthropic SDK not installed; using template fallback")
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # SDK returns a list of content blocks; concatenate text ones.
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:
        print(f"!! llm_insights: Claude call failed ({exc}); using template fallback")
        return None


# ── Public: daily narrative ──────────────────────────────────────────────────
def daily_narrative(payload: dict) -> dict:
    """One-paragraph 'three things to watch' from today's payload."""
    trends = (payload.get("trends") or [])[:30]
    ideas  = (payload.get("ideas")  or [])[:30]
    key = "daily:" + _hash_inputs([t["term"] for t in trends[:10]],
                                   [i["ticker"] for i in ideas[:10]])
    if (c := _cached(key)) is not None:
        return {"text": c, "cached": True}

    user = (
        "Write a 3-sentence morning briefing for a trader. Pick the single most "
        "interesting *new today / accelerating* trend, the single best 🚀 "
        "catch-up idea (trend hot, stock still cold), and one risk note.\n\n"
        f"Trends:\n{json.dumps([{'term': t['term'], 'mom': t['momentum'], 'phase': t.get('phase'), 'new': t.get('new_today'), 'accel': t.get('accelerating'), 'fade': t.get('fading_fast')} for t in trends], indent=0)}\n\n"
        f"Top ideas:\n{json.dumps([{'tk': i['ticker'], 'theme': i['theme'], 'cu': i.get('catch_up'), 'status': i['status']} for i in ideas[:15]], indent=0)}"
    )
    system = "You are a markets analyst. Be concrete, tight, factual. No hype, no hedging."
    text = _call_claude(system, user) or _template_narrative(trends, ideas)
    return {"text": _store(key, text), "cached": False}


def _template_narrative(trends, ideas) -> str:
    """Data-driven fallback that uses the same facts, just no LLM."""
    movers   = [t for t in trends if t.get("accelerating") or t.get("new_today")]
    top_mov  = movers[0] if movers else (trends[0] if trends else None)
    catchups = [i for i in ideas if i.get("status") == "catch_up" and i.get("catch_up") is not None]
    catchups.sort(key=lambda i: -i["catch_up"])
    top_cu   = catchups[0] if catchups else None
    fading   = next((t for t in trends if t.get("fading_fast")), None)

    parts = []
    if top_mov:
        tag = "🆕 NEW" if top_mov.get("new_today") else "🔥 ACCEL" if top_mov.get("accelerating") else "🔥"
        parts.append(f"Watch {tag} **{top_mov['term']}** (momentum {top_mov['momentum']}, phase {top_mov.get('phase','?')}).")
    if top_cu:
        parts.append(f"Best catch-up read: **{top_cu['ticker']}** in {top_cu['theme']} (score {top_cu['catch_up']} — stock hasn't moved with the theme).")
    if fading:
        parts.append(f"Risk: **{fading['term']}** is fading fast — late chases are risky.")
    return " ".join(parts) or "Nothing notable on the radar this morning."


# ── Public: explain a single trend ───────────────────────────────────────────
def explain_trend(term: str, payload: dict) -> dict:
    """Plain-English 'why is this trending?' read on a single term."""
    t = next((x for x in payload.get("trends") or [] if x["term"].lower() == term.lower()), None)
    if not t:
        return {"text": f"No data for '{term}'.", "cached": False}
    key = "expl:" + _hash_inputs(term, t.get("momentum"), t.get("phase"), t.get("sources"))
    if (c := _cached(key)) is not None:
        return {"text": c, "cached": True}

    user = (
        f"Term: {term}\n"
        f"Momentum: {t['momentum']}/100, change_pct: {t['change_pct']}%, "
        f"phase: {t.get('phase')}, direction: {t['direction']}\n"
        f"Sources: {t['sources']}, driven by: {t.get('driven_by')}\n"
        f"Category (theme): {t.get('category')}\n\n"
        "In 2–3 sentences, explain plausibly why this term is trending right now. "
        "Reference the source mix and phase. Don't invent specific news events."
    )
    system = "You are a markets analyst explaining a social trend to a trader."
    text = _call_claude(system, user) or _template_explanation(term, t)
    return {"text": _store(key, text), "cached": False}


def _template_explanation(term: str, t: dict) -> str:
    driver = t.get("driven_by")
    drv_txt = f"primarily on **{driver}**" if driver else "across multiple platforms"
    phase = t.get("phase", "flat")
    if phase == "building":
        rhythm = "Momentum is still building — attention is fresh."
    elif phase == "peaking":
        rhythm = "Momentum is peaking — be wary of late entries."
    elif phase == "fading":
        rhythm = "Momentum is fading — the conversation is rolling over."
    else:
        rhythm = "Momentum is flat — no real movement here."
    cat = t.get("category") if t.get("category") not in (None, "—") else "no curated theme"
    return (f"**{term}** is trending {drv_txt} with a 30-day change of {t['change_pct']:+.0f}% "
            f"(momentum {t['momentum']}). Mapped to the {cat} theme. {rhythm}")


# ── Public: contrarian critique of a 🚀 Hot · Cold idea ──────────────────────
def critique_idea(idea: dict, payload: dict) -> dict:
    """Why might this idea be wrong? Always bearish on the case."""
    key = "crit:" + _hash_inputs(idea.get("ticker"), idea.get("status"),
                                 idea.get("catch_up"), idea.get("trend_momentum"))
    if (c := _cached(key)) is not None:
        return {"text": c, "cached": True}

    drivers = [d["term"] for d in (idea.get("drivers") or [])[:3]]
    user = (
        f"Ticker: {idea['ticker']} ({idea['name']})\n"
        f"Theme: {idea['theme']}, purity: {idea['purity_label']} ({idea['purity']})\n"
        f"Trend momentum: {idea['trend_momentum']}, phase: {payload.get('trends', [{}])[0].get('phase','?')}\n"
        f"Catch-up score: {idea.get('catch_up')}, status: {idea['status']}\n"
        f"20d return: {idea.get('ret_20d')}%\n"
        f"Trending words driving the theme: {drivers}\n\n"
        "Give one concrete contrarian reason this 🚀 'Hot · Cold' read might be wrong. "
        "Two sentences max. Be specific to the ticker and theme."
    )
    system = "You are a sceptical risk officer poking holes in a long thesis."
    text = _call_claude(system, user) or _template_critique(idea)
    return {"text": _store(key, text), "cached": False}


def _template_critique(idea: dict) -> str:
    purity = idea.get("purity", 0)
    cu     = idea.get("catch_up") or 0
    r20    = idea.get("ret_20d")
    name   = idea.get("name", idea.get("ticker"))
    if purity < 0.6:
        return (f"{name} is only a *moderate* pure play on this theme — "
                f"its other businesses can drag price even while the theme runs.")
    if r20 is not None and r20 < -10:
        return (f"{name} is down {r20:.0f}% in the last 20 days for a reason — "
                f"there may be a company-specific overhang the theme tailwind can't offset.")
    if cu >= 70:
        return (f"A catch-up score of {cu} is unusually large — that often means the market is "
                f"discounting something specific about {name} that the social signal can't see.")
    return ("Pure-play scores assume the theme actually translates to revenue — verify "
            f"that {name}'s next earnings actually delivers on the trend before sizing up.")
