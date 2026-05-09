"""
config.py - Central home for tunable constants used across modules.
Import individual names rather than star-importing.
"""

# ── KAMA ──────────────────────────────────────────────────────────────────────
KAMA_PERIODS = [10, 20, 50]          # default period set used throughout the app

# ── RSI ───────────────────────────────────────────────────────────────────────
DEFAULT_RSI_PERIOD = 14

# ── Bollinger Bands ───────────────────────────────────────────────────────────
BB_WINDOW  = 20
BB_NUM_STD = 2.0

# ── MACD ──────────────────────────────────────────────────────────────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ── ATR ───────────────────────────────────────────────────────────────────────
ATR_WINDOW = 14

# ── CCI ───────────────────────────────────────────────────────────────────────
CCI_WINDOW = 20
