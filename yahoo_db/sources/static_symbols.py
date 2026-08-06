"""
sources/static_symbols.py - Symbols no listing directory carries.

Indices, currency pairs, continuous futures and the major crypto pairs are not
in the SEC or Nasdaq files, but Yahoo has full history for all of them. They
are cheap to enumerate, so they are baked in here.
"""

from ..db import STATUS_ACTIVE

SOURCE = "static"

INDICES = [
    # US broad market
    "^GSPC", "^DJI", "^IXIC", "^NDX", "^RUT", "^RUI", "^RUA", "^OEX",
    "^MID", "^SML", "^W5000", "^NYA", "^XAX", "^SP500TR", "^DJT", "^DJU",
    "^DJA", "^GDOW",
    # US volatility
    "^VIX", "^VIX9D", "^VIX3M", "^VXN", "^VVIX", "^RVX", "^VXD", "^SKEW",
    "^OVX", "^GVZ", "^MOVE",
    # US sectors: the eleven GICS sub-indices of the S&P 500, plus the older
    # PHLX/Arca sector benchmarks that predate them.
    "^SP500-10", "^SP500-15", "^SP500-20", "^SP500-25", "^SP500-30",
    "^SP500-35", "^SP500-40", "^SP500-45", "^SP500-50", "^SP500-55",
    "^SP500-60",
    "^SOX", "^XAU", "^HUI", "^BKX", "^XOI", "^OSX",
    # US rates
    "^IRX", "^FVX", "^TNX", "^TYX",
    # Europe
    "^FTSE", "^FTMC", "^FTAS", "^GDAXI", "^MDAXI", "^SDAXI", "^TECDAX",
    "^FCHI", "^N100", "^STOXX", "^STOXX50E", "^IBEX", "^AEX", "^SSMI",
    "^OMX", "^BFX", "FTSEMIB.MI", "^PSI20", "^ATX", "^BUX", "XU100.IS",
    # Asia-Pacific
    "^N225", "^TOPX", "^HSI", "^HSCE", "^SSEC", "^SZSC", "^STI", "^KS11",
    "^KQ11", "^TWII", "^AXJO", "^AORD", "^NZ50", "^JKSE", "^KLSE",
    "^SET.BK", "^BSESN", "^NSEI", "^NSEBANK", "^VNINDEX",
    # Americas / EMEA
    "^GSPTSE", "^BVSP", "^MXX", "^MERV", "^IPSA", "^TA125.TA", "^TA35.TA",
    "^CASE30", "^JN0U.JO",
    # Currency / commodity indices
    "DX-Y.NYB", "^XDE", "^XDN", "^XDB", "^XDA", "^SPGSCI", "^BCOM",
]

FUTURES = [
    # Equity index, full size and micro
    "ES=F", "NQ=F", "YM=F", "RTY=F", "EMD=F", "NKD=F", "FDAX=F",
    "MES=F", "MNQ=F", "MYM=F", "M2K=F",
    # Rates
    "ZB=F", "UB=F", "ZN=F", "TN=F", "ZF=F", "ZT=F", "ZQ=F", "GE=F", "SR3=F",
    # Energy
    "CL=F", "MCL=F", "BZ=F", "NG=F", "RB=F", "HO=F", "QM=F",
    # Metals
    "GC=F", "SI=F", "HG=F", "PL=F", "PA=F", "ALI=F", "MGC=F", "SIL=F",
    # Grains / softs
    "ZC=F", "ZS=F", "ZW=F", "ZL=F", "ZM=F", "ZO=F", "ZR=F", "KE=F",
    "CT=F", "KC=F", "CC=F", "SB=F", "OJ=F", "LBS=F", "LBR=F",
    # Livestock
    "LE=F", "GF=F", "HE=F",
    # FX futures, and the dollar index the cash market has no ticker for
    "6E=F", "6J=F", "6B=F", "6C=F", "6A=F", "6S=F", "6M=F", "6N=F", "DX=F",
    # Crypto futures
    "BTC=F", "ETH=F",
]

# Everything sensible against USD, plus the crosses people actually quote.
_CURRENCIES = [
    "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "HKD", "SGD",
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "TRY", "ZAR", "MXN",
    "BRL", "CLP", "COP", "ARS", "PEN", "INR", "IDR", "KRW", "THB", "MYR",
    "PHP", "TWD", "VND", "ILS", "AED", "SAR", "QAR", "KWD", "EGP", "NGN",
    "KES", "MAD", "RUB", "UAH", "ISK", "HRK", "BGN", "PKR", "BDT", "LKR",
    "CNH",
]
_CROSS_BASES = ["EUR", "GBP", "AUD", "NZD", "CAD", "CHF"]
_CROSS_QUOTES = ["JPY", "CHF", "GBP", "AUD", "NZD", "CAD", "SEK", "NOK"]

# Euro and sterling are quoted against the liquid emerging-market currencies as
# well; the other majors mostly are not, so this stays a separate small matrix.
_EM_CROSS_BASES = ["EUR", "GBP"]
_EM_CROSS_QUOTES = ["PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD",
                    "INR"]

# Precious metals also quote as FX pairs, which is the only way to get spot
# gold/silver history without going through the futures curve.
_METAL_PAIRS = ["XAUUSD=X", "XAGUSD=X", "XPTUSD=X", "XPDUSD=X"]

_CRYPTO = [
    "BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "USDC", "ADA", "AVAX", "DOGE",
    "TRX", "DOT", "MATIC", "LTC", "SHIB", "BCH", "LINK", "XLM", "UNI", "ATOM",
    "XMR", "ETC", "HBAR", "FIL", "ICP", "APT", "ARB", "OP", "NEAR", "VET",
    "ALGO", "AAVE", "MKR", "GRT", "SAND", "MANA", "AXS", "EGLD", "THETA",
    "FTM", "XTZ", "EOS", "CRV", "SNX", "COMP", "ZEC", "DASH", "CAKE", "RUNE",
    "INJ", "SUI", "SEI", "TIA", "PEPE", "WIF", "BONK", "RNDR", "IMX", "LDO",
    "TON", "KAS", "STX", "FLOW", "CHZ", "GALA", "ENS", "BAT", "ZIL", "QNT",
    "NEO", "KSM", "ROSE", "ANKR", "ZRX", "YFI", "SUSHI", "DYDX", "JUP",
    "PYTH", "ONDO", "ENA", "STRK", "BLUR", "GMX", "FET", "TAO", "JASMY",
    "AR", "MINA",
]
_CRYPTO_QUOTES = ["USD", "EUR"]


def _currency_pairs() -> list:
    pairs = [f"{code}USD=X" if code in ("EUR", "GBP", "AUD", "NZD")
             else f"USD{code}=X" for code in _CURRENCIES]
    for bases, quotes in ((_CROSS_BASES, _CROSS_QUOTES),
                          (_EM_CROSS_BASES, _EM_CROSS_QUOTES)):
        for base in bases:
            for quote in quotes:
                if base != quote:
                    pairs.append(f"{base}{quote}=X")
    pairs.extend(_METAL_PAIRS)
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
