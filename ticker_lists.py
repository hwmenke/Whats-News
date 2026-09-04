"""
ticker_lists.py - Curated library of tickers organized by category
Used by the Data Manager tab for bulk fetching.
"""

TICKER_LIBRARY = [
    {
        "id": "mega_tech",
        "label": "Mega-Cap Tech",
        "tickers": [
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
            "META", "TSLA", "AVGO", "ORCL", "ADBE",
            "CRM", "AMD", "QCOM", "INTC", "TXN",
            "CSCO", "NFLX", "IBM", "NOW", "INTU",
        ],
    },
    {
        "id": "finance",
        "label": "Finance",
        "tickers": [
            "JPM", "BAC", "WFC", "GS", "MS",
            "BLK", "SCHW", "AXP", "C", "USB",
            "PNC", "TFC", "COF", "BK", "STT",
            "ICE", "CME", "SPGI", "MCO", "V",
            "MA", "PYPL",
        ],
    },
    {
        "id": "healthcare",
        "label": "Healthcare",
        "tickers": [
            "LLY", "JNJ", "UNH", "ABBV", "MRK",
            "TMO", "ABT", "DHR", "PFE", "AMGN",
            "BMY", "GILD", "ISRG", "MDT", "BSX",
            "SYK", "HCA", "CVS", "CI", "ELV",
        ],
    },
    {
        "id": "energy",
        "label": "Energy",
        "tickers": [
            "XOM", "CVX", "COP", "EOG", "SLB",
            "MPC", "PSX", "VLO", "OXY", "PXD",
            "HAL", "DVN", "BKR", "HES", "FANG",
            "KMI", "WMB", "ET", "EPD",
        ],
    },
    {
        "id": "industrials",
        "label": "Industrials",
        "tickers": [
            "GE", "CAT", "HON", "UPS", "RTX",
            "LMT", "DE", "BA", "MMM", "GD",
            "NOC", "FDX", "CSX", "NSC", "UNP",
            "ETN", "EMR", "PH", "ROK", "IR",
        ],
    },
    {
        "id": "consumer_staples",
        "label": "Consumer Staples",
        "tickers": [
            "PG", "KO", "PEP", "WMT", "COST",
            "MO", "PM", "MDLZ", "KHC", "GIS",
            "K", "SJM", "HSY", "MKC", "CLX",
            "EL", "CL", "MNST",
        ],
    },
    {
        "id": "consumer_disc",
        "label": "Consumer Discretionary",
        "tickers": [
            "AMZN", "HD", "MCD", "NKE", "LOW",
            "SBUX", "TJX", "BKNG", "TGT", "ROST",
            "CMG", "YUM", "DRI", "APTV", "F",
            "GM", "ABNB", "EXPE", "MAR", "HLT",
        ],
    },
    {
        "id": "broad_etfs",
        "label": "Broad Market ETFs",
        "tickers": [
            "SPY", "QQQ", "IWM", "DIA", "VTI",
            "VOO", "IVV", "SCHB", "VEA", "VWO",
            "AGG", "BND", "TLT", "IEF", "SHY",
            "GLD", "SLV", "IAU", "USO", "UNG",
        ],
    },
    {
        "id": "sector_etfs",
        "label": "Sector ETFs",
        "tickers": [
            "XLK", "XLF", "XLV", "XLE", "XLI",
            "XLP", "XLY", "XLU", "XLB", "XLRE",
            "XLC", "SMH", "SOXX", "ARKK", "ARKG",
            "ARKW", "IBB", "XBI", "KRE", "KBE",
        ],
    },
    {
        "id": "intl_etfs",
        "label": "International ETFs",
        "tickers": [
            "EFA", "EEM", "IEFA", "IEMG", "FXI",
            "EWJ", "EWZ", "EWG", "EWC", "EWY",
            "EWA", "EWU", "EWH", "EWT", "INDA",
            "MCHI", "VGK", "VPL", "ACWI", "ACWX",
        ],
    },
    {
        "id": "indices",
        "label": "Indices / Volatility",
        "tickers": [
            "^GSPC", "^NDX", "^DJI", "^RUT", "^VIX",
            "^TNX", "^TYX", "^IRX", "^FTSE", "^N225",
            "^GDAXI", "^HSI", "^SSEC", "DX-Y.NYB",
        ],
    },
    {
        "id": "crypto",
        "label": "Crypto",
        "tickers": [
            "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD",
            "XRP-USD", "ADA-USD", "AVAX-USD", "DOGE-USD",
            "LINK-USD", "DOT-USD", "MATIC-USD", "LTC-USD",
        ],
    },
    {
        "id": "tech_themes",
        "label": "Tech Themes",
        "tickers": [
            "SMH", "SOXX", "IGV", "BOTZ", "ICLN",
            "HACK", "CIBR", "ITA", "XBI", "IBB",
        ],
    },
    {
        "id": "resource_themes",
        "label": "Resource Themes",
        "tickers": [
            "GDX", "GDXJ", "SIL", "URA", "XOP",
            "OIH", "AMLP", "DBA",
        ],
    },
    {
        "id": "bond_etfs",
        "label": "Bond ETFs",
        "tickers": [
            "TLT", "IEF", "SHY", "AGG", "TIP",
            "EMB", "HYG", "LQD",
        ],
    },
    {
        "id": "listed_crypto",
        "label": "Listed Crypto Proxies",
        "tickers": ["IBIT", "COIN", "MSTR", "WGMI"],
    },
    {
        "id": "themes",
        "label": "Themes",
        "tickers": [
            "SMH", "SOXX", "IGV", "BOTZ", "ICLN",
            "HACK", "CIBR", "ITA", "XBI",
        ],
    },
    {
        "id": "rates",
        "label": "Rates & Credit",
        "tickers": ["TLT", "IEF", "SHY", "HYG", "LQD", "UUP"],
    },
    {
        "id": "commodities",
        "label": "Commodities",
        "tickers": ["GLD", "SLV", "USO", "UNG", "DBA"],
    },
]


def get_all_tickers() -> list:
    """Return deduplicated flat list of all tickers across categories."""
    seen = set()
    result = []
    for cat in TICKER_LIBRARY:
        for t in cat["tickers"]:
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result


# Desk sleeves wrap TICKER_LIBRARY — no second universe file.
# Aliases keep older /api/sleeves/<id>/seed paths working.
_SLEEVE_ALIASES = {
    "indexes": "broad_etfs",
    "index": "broad_etfs",
    "countries": "intl_etfs",
    "sectors": "sector_etfs",
    "big_tech": "mega_tech",
    "bonds": "rates",
    "crypto": "listed_crypto",
    "tech_themes": "themes",
    "resources": "commodities",
    "ags": "commodities",
    "metals_energy": "commodities",
    "fx": "rates",
    "yields": "rates",
}

_CORE_FROM_BROAD = ("SPY", "QQQ", "IWM")

_SLEEVE_KIND = {
    "broad_etfs": "index",
    "sector_etfs": "sector",
    "intl_etfs": "country",
    "mega_tech": "theme",
    "themes": "theme",
    "rates": "theme",
    "commodities": "theme",
    "listed_crypto": "theme",
    "tech_themes": "theme",
    "resource_themes": "theme",
    "bond_etfs": "theme",
}


def _category_tickers(cat_id: str) -> list:
    cat = get_category(cat_id)
    if not cat:
        return []
    return [str(t).strip().upper() for t in cat.get("tickers") or [] if str(t).strip()]


def _sleeve_from_library(cat_id: str, *, blurb: str = "") -> dict:
    cat = get_category(cat_id) or {"id": cat_id, "label": cat_id, "tickers": []}
    return {
        "id": cat_id,
        "label": cat.get("label") or cat_id,
        "group_tag": f"lib:{cat_id}",
        "filter_kind": _SLEEVE_KIND.get(cat_id) or filter_kind_for_tag(f"lib:{cat_id}"),
        "library_id": cat_id,
        "blurb": blurb or f"{cat.get('label') or cat_id} from ticker_lists — Yahoo names only.",
        "tickers": _category_tickers(cat_id),
    }


def sleeves() -> list:
    """Thin desk view over TICKER_LIBRARY. Core is SPY/QQQ/IWM from Broad Market ETFs."""
    broad = set(_category_tickers("broad_etfs"))
    core_tickers = [t for t in _CORE_FROM_BROAD if t in broad] or list(_CORE_FROM_BROAD)
    out = [
        {
            "id": "core",
            "label": "Core indices",
            "group_tag": "sleeve:core",
            "filter_kind": "index",
            "library_id": "broad_etfs",
            "blurb": "SPY / QQQ / IWM from Broad Market ETFs — not a new universe.",
            "tickers": core_tickers,
        },
        _sleeve_from_library("broad_etfs", blurb="Broad Market ETFs from ticker_lists."),
        _sleeve_from_library("sector_etfs", blurb="Sector ETFs from ticker_lists."),
        _sleeve_from_library("intl_etfs", blurb="International ETFs from ticker_lists — not GDP."),
        _sleeve_from_library("mega_tech", blurb="Mega-cap tech from ticker_lists."),
        _sleeve_from_library("themes", blurb="Theme ETFs from ticker_lists — not a fund pick."),
        _sleeve_from_library("rates", blurb="Duration, credit, and dollar ETF proxies."),
        _sleeve_from_library("commodities", blurb="Metals / energy / ag ETF proxies — not spot or futures."),
        _sleeve_from_library("listed_crypto", blurb="Listed crypto proxies — not fake NAV."),
    ]
    return out


def get_sleeve(sleeve_id: str):
    raw = (sleeve_id or "").strip()
    if not raw:
        return None
    if raw == "core":
        for sleeve in sleeves():
            if sleeve["id"] == "core":
                return sleeve
        return None
    resolved = _SLEEVE_ALIASES.get(raw, raw)
    for sleeve in sleeves():
        if sleeve["id"] == raw or sleeve["id"] == resolved:
            return sleeve
    if get_category(resolved):
        return _sleeve_from_library(resolved)
    return None


def __getattr__(name: str):
    if name == "MACRO_SLEEVES":
        return sleeves()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Curated ~50 liquid names for a one-tap desk — taken from TICKER_LIBRARY, not S&P scrape.
CORE50 = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL", "AMD",
    "NFLX", "CRM", "INTC", "IBM",
    "JPM", "BAC", "GS", "V", "MA",
    "LLY", "JNJ", "UNH", "ABBV",
    "XOM", "CVX",
    "CAT", "GE", "BA", "HON",
    "PG", "KO", "PEP", "WMT", "COST",
    "HD", "MCD", "NKE", "DIS",
    "SPY", "QQQ", "IWM", "DIA",
    "XLK", "XLF", "XLE", "XLV",
    "TLT", "GLD",
    "EWJ", "EEM",
]


def get_category(cat_id: str):
    for cat in TICKER_LIBRARY:
        if cat["id"] == cat_id:
            return cat
    return None


def core50_tickers() -> list:
    seen = set()
    out = []
    for raw in CORE50:
        sym = str(raw).strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def library_group_tag(symbol: str) -> str:
    """First library category wins — used to tag Core 50 for Country/Sector/Theme filters."""
    sym = str(symbol).strip().upper()
    for cat in TICKER_LIBRARY:
        if sym in cat["tickers"]:
            return f"lib:{cat['id']}"
    return "core50"


def filter_kind_for_tag(group_tag: str) -> str:
    tag = (group_tag or "").lower()
    if "countries" in tag or "intl" in tag:
        return "country"
    if "sector" in tag:
        return "sector"
    if any(k in tag for k in (
        "theme", "tech", "resource", "crypto", "bond", "ags",
        "metal", "fx", "yield", "big_tech", "commodit", "rates",
    )):
        return "theme"
    if "index" in tag or tag in ("sleeve:core", "lib:broad_etfs", "lib:indices"):
        return "index"
    return ""
