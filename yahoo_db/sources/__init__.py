"""Symbol universe sources."""

from . import (nasdaq, otc, sec, seeds, static_symbols,  # noqa: F401
               wikipedia_indices, yahoo_lookup)

SOURCE_NAMES = ["sec", "nasdaq", "otc", "wikipedia", "seeds", "static",
                "yahoo-lookup"]
