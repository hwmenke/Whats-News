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


# Liquid Yahoo-tradable proxies for the iPhone Macro board. Not GDP, not NAV,
# not futures spots. Categories match the MARKET MOVES desk sleeves.
MACRO_SLEEVES = [
    {
        "id": "core",
        "label": "Core indices",
        "group_tag": "sleeve:core",
        "filter_kind": "index",
        "blurb": "US index ETF proxies — paper tape anchors, not forecasts.",
        "tickers": ["SPY", "QQQ", "IWM"],
    },
    {
        "id": "indexes",
        "label": "Indexes",
        "group_tag": "sleeve:indexes",
        "filter_kind": "index",
        "blurb": "Broad US index ETFs — not futures (no NQ/ES).",
        "tickers": ["SPY", "QQQ", "IWM", "DIA", "MDY", "RSP"],
    },
    {
        "id": "big_tech",
        "label": "Big Tech",
        "group_tag": "sleeve:big_tech",
        "filter_kind": "theme",
        "blurb": "Liquid mega-cap names yfinance serves.",
        "tickers": [
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
            "META", "TSLA", "NFLX", "AMD", "AVGO",
        ],
    },
    {
        "id": "countries",
        "label": "Country ETFs",
        "group_tag": "sleeve:countries",
        "filter_kind": "country",
        "blurb": "Single-country / EM ETF proxies — not country GDP.",
        "tickers": [
            "EWC", "EWJ", "EWU", "EWA", "EWG", "EWW",
            "EEM", "EWT", "EWY", "EWZ", "INDA", "MCHI",
        ],
    },
    {
        "id": "sectors",
        "label": "Sectors",
        "group_tag": "sleeve:sectors",
        "filter_kind": "sector",
        "blurb": "SPDR sector ETFs.",
        "tickers": [
            "XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
            "XLI", "XLU", "XLB", "XLRE", "XLC",
        ],
    },
    {
        "id": "tech_themes",
        "label": "Tech Themes",
        "group_tag": "sleeve:tech_themes",
        "filter_kind": "theme",
        "blurb": "Liquid theme ETFs — not a fund pick.",
        "tickers": ["SMH", "SOXX", "IGV", "BOTZ", "ICLN", "HACK", "CIBR", "ITA"],
    },
    {
        "id": "resources",
        "label": "Resource Themes",
        "group_tag": "sleeve:resources",
        "filter_kind": "theme",
        "blurb": "Miners and energy ETFs — not spot.",
        "tickers": ["GDX", "GDXJ", "SIL", "URA", "XOP", "OIH", "AMLP"],
    },
    {
        "id": "ags",
        "label": "Ags & Softs",
        "group_tag": "sleeve:ags",
        "filter_kind": "theme",
        "blurb": "No Yahoo futures (ZC=F, KC=F, …). DBA is the liquid ag ETF proxy.",
        "tickers": ["DBA"],
        "skipped": "Futures/softs are not fetched here — no invented PX/Z.",
    },
    {
        "id": "metals_energy",
        "label": "Metals & Energy",
        "group_tag": "sleeve:metals_energy",
        "filter_kind": "theme",
        "blurb": "ETF proxies — not CL/NG/HG futures.",
        "tickers": ["GLD", "SLV", "USO", "UNG", "PPLT", "PALL", "CPER"],
    },
    {
        "id": "fx",
        "label": "FX",
        "group_tag": "sleeve:fx",
        "filter_kind": "theme",
        "blurb": "Dollar ETF proxy — not EURUSD spots.",
        "tickers": ["UUP"],
        "skipped": "Spot FX pairs are not stored. UUP only.",
    },
    {
        "id": "yields",
        "label": "Yields",
        "group_tag": "sleeve:yields",
        "filter_kind": "theme",
        "blurb": "Duration ETF proxies — not raw 10Y/30Y yields.",
        "tickers": ["SHY", "IEF", "TLT"],
        "skipped": "Raw government yields are not invented. Duration ETFs only.",
    },
    {
        "id": "bonds",
        "label": "Bond ETFs",
        "group_tag": "sleeve:bonds",
        "filter_kind": "theme",
        "blurb": "Liquid fixed-income ETFs.",
        "tickers": ["TLT", "IEF", "AGG", "TIP", "EMB", "HYG", "LQD"],
    },
    {
        "id": "crypto",
        "label": "Crypto",
        "group_tag": "sleeve:crypto",
        "filter_kind": "theme",
        "blurb": "Listed proxies — not fake NAV.",
        "tickers": ["IBIT", "COIN", "MSTR", "WGMI"],
    },
]


# Curated ~50 liquid names for a one-tap desk — not the full S&P archive.
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


def get_sleeve(sleeve_id: str):
    for sleeve in MACRO_SLEEVES:
        if sleeve["id"] == sleeve_id:
            return sleeve
    return None


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
        "metal", "fx", "yield", "big_tech", "commodit",
    )):
        return "theme"
    if "index" in tag or tag in ("sleeve:core", "lib:broad_etfs", "lib:indices"):
        return "index"
    return ""
