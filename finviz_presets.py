"""Named Finviz screener presets for the Whats-News paper desk.

Filter codes are the public `f=` tokens Finviz puts on
``https://finviz.com/screener.ashx?v=111&f=...`` (no Elite / no login).

These are Qulla-style *screens* (price, volume, near-high, growth) — not
Kristjan Qullamaggie formulas and not claimed returns. Empty Finviz HTML
must stay empty; presets never invent tickers.
"""

from __future__ import annotations

QUOTE_URL = "https://finviz.com/quote.ashx"
SCREENER_URL = "https://finviz.com/screener.ashx"

# Public screener view 111 = overview table (Ticker, Company, Sector, …).
SCREENER_VIEW = "111"

# Documented Finviz `f=` codes used below (comma-joined on the URL).
#   sh_price_o10            Price over $10
#   sh_avgvol_o400          Average Volume over 400K
#   sh_avgvol_o1000         Average Volume over 1M
#   sh_relvol_o1.5          Relative Volume over 1.5
#   sh_relvol_o2            Relative Volume over 2
#   ta_highlow52w_b0to5h    0–5% below 52-week high
#   ta_highlow52w_nh        New 52-week high
#   fa_epsyoy_o25           EPS growth this year over 25%
#   fa_epsqoq_o25           EPS growth QoQ over 25%
#   fa_salesqoq_o25         Sales growth QoQ over 25%
#   fa_salesyoyttm_o25      Sales Y/Y TTM over 25%
FILTER_DOCS = {
    "sh_price_o10": "Price over $10",
    "sh_avgvol_o400": "Average Volume over 400K",
    "sh_avgvol_o1000": "Average Volume over 1M",
    "sh_relvol_o1.5": "Relative Volume over 1.5",
    "sh_relvol_o2": "Relative Volume over 2",
    "ta_highlow52w_b0to5h": "0–5% below 52-week high",
    "ta_highlow52w_nh": "New 52-week high",
    "fa_epsyoy_o25": "EPS growth this year over 25%",
    "fa_epsqoq_o25": "EPS growth quarter-over-quarter over 25%",
    "fa_salesqoq_o25": "Sales growth quarter-over-quarter over 25%",
    "fa_salesyoyttm_o25": "Sales Y/Y TTM over 25%",
}

DEFAULT_PRESET = "qulla_momentum"

PRESETS = {
    "qulla_momentum": {
        "id": "qulla_momentum",
        "label": "Qulla / momentum",
        "blurb": (
            "Price > $10, avg vol > 400K, RVOL > 1.5, within 5% of 52w high, "
            "EPS YoY > 25%, sales QoQ > 25%. Desk screen — not a Qulla formula."
        ),
        "filters": [
            "sh_price_o10",
            "sh_avgvol_o400",
            "sh_relvol_o1.5",
            "ta_highlow52w_b0to5h",
            "fa_epsyoy_o25",
            "fa_salesqoq_o25",
        ],
    },
    "near_high": {
        "id": "near_high",
        "label": "Near 52-week high",
        "blurb": "Price > $10, avg vol > 400K, 0–5% below 52-week high.",
        "filters": [
            "sh_price_o10",
            "sh_avgvol_o400",
            "ta_highlow52w_b0to5h",
        ],
    },
    "vol_surge": {
        "id": "vol_surge",
        "label": "Relative volume surge",
        "blurb": "Price > $10, avg vol > 400K, RVOL > 2.",
        "filters": [
            "sh_price_o10",
            "sh_avgvol_o400",
            "sh_relvol_o2",
        ],
    },
    "new_high": {
        "id": "new_high",
        "label": "New 52-week high",
        "blurb": "Price > $10, avg vol > 1M, new 52-week high.",
        "filters": [
            "sh_price_o10",
            "sh_avgvol_o1000",
            "ta_highlow52w_nh",
        ],
    },
    "eps_growth": {
        "id": "eps_growth",
        "label": "EPS + sales growth",
        "blurb": "Price > $10, avg vol > 400K, EPS YoY and QoQ > 25%, sales TTM > 25%.",
        "filters": [
            "sh_price_o10",
            "sh_avgvol_o400",
            "fa_epsyoy_o25",
            "fa_epsqoq_o25",
            "fa_salesyoyttm_o25",
        ],
    },
}


def get_preset(preset_id: str | None) -> dict | None:
    key = (preset_id or DEFAULT_PRESET).strip().lower()
    return PRESETS.get(key)


def list_presets() -> list[dict]:
    rows = []
    for item in PRESETS.values():
        rows.append({
            **item,
            "filter_docs": {code: FILTER_DOCS.get(code, code) for code in item["filters"]},
            "url": screener_url(item["filters"]),
        })
    return rows


def screener_url(filters: list[str]) -> str:
    joined = ",".join(code for code in filters if code)
    return f"{SCREENER_URL}?v={SCREENER_VIEW}&ft=4&f={joined}"


def quote_url(symbol: str) -> str:
    return f"{QUOTE_URL}?t={finviz_ticker(symbol)}"


def finviz_ticker(symbol: str) -> str:
    """Finviz uses hyphen class shares (BRK-B), uppercase."""
    return (symbol or "").strip().upper().replace(".", "-")


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace("-", ".")
