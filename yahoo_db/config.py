"""
config.py - Runtime settings for the Yahoo data downloader.

Every value can be overridden with an environment variable (YDB_*) or a CLI
flag. CLI flags win over env vars, env vars win over the defaults below.
"""

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PKG_DIR.parent / "data"


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(key: str, default: list) -> list:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return list(default)
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass
class Config:
    # ── Storage ────────────────────────────────────────────────────────────────
    db_path: Path = field(
        default_factory=lambda: Path(
            _env_str("YDB_DB_PATH", str(DEFAULT_DATA_DIR / "market.db"))
        )
    )
    seeds_dir: Path = field(
        default_factory=lambda: Path(_env_str("YDB_SEEDS_DIR", str(PKG_DIR / "seeds")))
    )

    # ── Download behaviour ─────────────────────────────────────────────────────
    interval: str = field(default_factory=lambda: _env_str("YDB_INTERVAL", "1d"))
    batch_size: int = field(default_factory=lambda: _env_int("YDB_BATCH_SIZE", 50))
    workers: int = field(default_factory=lambda: _env_int("YDB_WORKERS", 8))
    sleep_between_batches: float = field(
        default_factory=lambda: _env_float("YDB_SLEEP", 1.0)
    )
    max_retries: int = field(default_factory=lambda: _env_int("YDB_MAX_RETRIES", 3))
    retry_backoff: float = field(default_factory=lambda: _env_float("YDB_BACKOFF", 5.0))
    request_timeout: int = field(default_factory=lambda: _env_int("YDB_TIMEOUT", 30))

    # Re-download a symbol only if its last successful fetch is older than this.
    refresh_after_hours: int = field(
        default_factory=lambda: _env_int("YDB_REFRESH_AFTER_HOURS", 20)
    )
    # Overlap re-downloaded on incremental fetches so split/dividend adjustments
    # to recent bars are picked up instead of frozen at their pre-adjust values.
    incremental_overlap_days: int = field(
        default_factory=lambda: _env_int("YDB_OVERLAP_DAYS", 7)
    )
    # Full-history start when a symbol has no stored bars ("max" = everything).
    history_start: str = field(default_factory=lambda: _env_str("YDB_START", "max"))

    # A symbol whose newest bar is older than this is treated as delisted.
    stale_days: int = field(default_factory=lambda: _env_int("YDB_STALE_DAYS", 30))
    # Cap on the exponential backoff applied to symbols that keep failing, so a
    # universe full of dead tickers does not eat every run.
    max_failure_backoff_days: int = field(
        default_factory=lambda: _env_int("YDB_MAX_BACKOFF_DAYS", 30)
    )

    # ── Universe discovery ─────────────────────────────────────────────────────
    sources: list = field(
        default_factory=lambda: _env_list(
            "YDB_SOURCES", ["sec", "nasdaq", "seeds", "static"]
        )
    )
    lookup_types: list = field(
        default_factory=lambda: _env_list(
            "YDB_LOOKUP_TYPES", ["equity", "etf", "mutualfund", "index", "future"]
        )
    )
    lookup_regions: list = field(
        default_factory=lambda: _env_list("YDB_LOOKUP_REGIONS", ["US"])
    )
    # Query depth for the Yahoo lookup crawl: 1 = "A".."Z", 2 = "AA".."ZZ", …
    lookup_depth: int = field(default_factory=lambda: _env_int("YDB_LOOKUP_DEPTH", 2))
    lookup_sleep: float = field(
        default_factory=lambda: _env_float("YDB_LOOKUP_SLEEP", 0.4)
    )
    # A deep crawl is an overnight job, so it checkpoints every finished
    # (region, type, prefix) triple and skips those on the next run. Completion
    # goes stale — the universe gains and loses symbols — so a triple older than
    # this is crawled again. Two weeks is short enough to track new listings and
    # long enough that a multi-night crawl is never re-done from the start.
    lookup_resume_days: int = field(
        default_factory=lambda: _env_int("YDB_LOOKUP_RESUME_DAYS", 14)
    )
    # Throw the checkpoints away and crawl every prefix again.
    lookup_restart: bool = field(
        default_factory=lambda: _env_bool("YDB_LOOKUP_RESTART", False)
    )

    user_agent: str = field(
        default_factory=lambda: _env_str(
            "YDB_USER_AGENT",
            "yahoo-db/1.0 (market data archiver; contact: set YDB_USER_AGENT)",
        )
    )

    def with_overrides(self, **kwargs) -> "Config":
        """Return a copy with any non-None keyword applied."""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self


def load_config(**overrides) -> Config:
    return Config().with_overrides(**overrides)
