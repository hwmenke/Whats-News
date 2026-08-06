"""
sources/static_symbols.py - Symbols no listing directory carries.

Indices, currency pairs, continuous futures and the major crypto pairs are not
in the SEC or Nasdaq files, but Yahoo has full history for all of them. They
are cheap to enumerate, so they are baked in here.
"""

from ..db import STATUS_ACTIVE

SOURCE = "static"

INDICES = [
    # US
    "^GSPC", "^DJI", "^IXIC", "^NDX", "^RUT", "^OEX", "^MID", "^SML",
    "^W5000", "^NYA", "^XAX", "^VIX", "^VXN", "^VVIX", "^OVX", "^GVZ",
    "^SP500TR", "^DJT", "^DJU", "^DJA",
    # US rates
    "^IRX", "^FVX", "^TNX", "^TYX",
    # Europe
    "^FTSE", "^GDAXI", "^FCHI", "^STOXX", "^STOXX50E", "^IBEX", "^AEX",
    "^SSMI", "^OMX", "^BFX", "FTSEMIB.MI", "^PSI20", "^ATX", "^BUX",
    # Asia-Pacific
    "^N225", "^TOPX", "^HSI", "^SSEC", "^SZSC", "^STI", "^KS11", "^KQ11",
    "^TWII", "^AXJO", "^AORD", "^NZ50", "^JKSE", "^KLSE", "^SET.BK",
    "^BSESN", "^NSEI", "^VNINDEX",
    # Americas / EMEA
    "^GSPTSE", "^BVSP", "^MXX", "^MERV", "^IPSA", "^TA125.TA", "^CASE30",
    "^JN0U.JO",
    # Currency / commodity indices
    "DX-Y.NYB", "^XDE", "^XDN", "^XDB", "^XDA",
]

FUTURES = [
    # Equity index
    "ES=F", "NQ=F", "YM=F", "RTY=F", "NKD=F", "FDAX=F",
    # Rates
    "ZB=F", "ZN=F", "ZF=F", "ZT=F", "GE=F", "SR3=F",
    # Energy
    "CL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "QM=F",
    # Metals
    "GC=F", "SI=F", "HG=F", "PL=F", "PA=F", "ALI=F", "MGC=F", "SIL=F",
    # Grains / softs
    "ZC=F", "ZS=F", "ZW=F", "ZL=F", "ZM=F", "ZO=F", "ZR=F", "KE=F",
    "CT=F", "KC=F", "CC=F", "SB=F", "OJ=F", "LBS=F",
    # Livestock
    "LE=F", "GF=F", "HE=F",
    # FX futures
    "6E=F", "6J=F", "6B=F", "6C=F", "6A=F", "6S=F", "6M=F", "6N=F",
]

# Everything sensible against USD, plus the crosses people actually quote.
_CURRENCIES = [
    "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "HKD", "SGD",
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "TRY", "ZAR", "MXN",
    "BRL", "CLP", "COP", "ARS", "PEN", "INR", "IDR", "KRW", "THB", "MYR",
    "PHP", "TWD", "VND", "ILS", "AED", "SAR", "QAR", "KWD", "EGP", "NGN",
    "KES", "MAD", "RUB", "UAH", "ISK", "HRK", "BGN", "PKR", "BDT", "LKR",
]
_CROSS_BASES = ["EUR", "GBP", "AUD", "NZD", "CAD", "CHF"]
_CROSS_QUOTES = ["JPY", "CHF", "GBP", "AUD", "NZD", "CAD", "SEK", "NOK"]

_CRYPTO = [
    "BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "USDC", "ADA", "AVAX", "DOGE",
    "TRX", "DOT", "MATIC", "LTC", "SHIB", "BCH", "LINK", "XLM", "UNI", "ATOM",
    "XMR", "ETC", "HBAR", "FIL", "ICP", "APT", "ARB", "OP", "NEAR", "VET",
    "ALGO", "AAVE", "MKR", "GRT", "SAND", "MANA", "AXS", "EGLD", "THETA",
    "FTM", "XTZ", "EOS", "CRV", "SNX", "COMP", "ZEC", "DASH", "CAKE", "RUNE",
    "INJ", "SUI", "SEI", "TIA", "PEPE", "WIF", "BONK", "RNDR", "IMX", "LDO",
]
_CRYPTO_QUOTES = ["USD", "EUR"]


def _currency_pairs() -> list:
    pairs = [f"{code}USD=X" if code in ("EUR", "GBP", "AUD", "NZD")
             else f"USD{code}=X" for code in _CURRENCIES]
    for base in _CROSS_BASES:
        for quote in _CROSS_QUOTES:
            if base != quote:
                pairs.append(f"{base}{quote}=X")
    return pairs


def _crypto_pairs() -> list:
    return [f"{coin}-{quote}" for coin in _CRYPTO for quote in _CRYPTO_QUOTES]


def fetch() -> list:
    """Return the built-in non-equity symbols."""
    groups = [
        (INDICES, "INDEX"),
        (FUTURES, "FUTURE"),
        (_currency_pairs(), "CURRENCY"),
        (_crypto_pairs(), "CRYPTOCURRENCY"),
    ]
    records = {}
    for symbols, quote_type in groups:
        for symbol in symbols:
            records.setdefault(symbol, {
                "symbol": symbol,
                "quote_type": quote_type,
                "status": STATUS_ACTIVE,
                "source": SOURCE,
            })
    return list(records.values())
