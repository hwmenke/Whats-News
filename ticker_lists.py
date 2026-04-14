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


def get_category(cat_id: str):
    for cat in TICKER_LIBRARY:
        if cat["id"] == cat_id:
            return cat
    return None
