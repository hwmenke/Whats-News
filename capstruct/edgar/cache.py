"""
cache.py - On-disk response cache.

Cache policy is NOT uniform, which is the thing that bites people:

  * Documents and exhibits under /Archives/ are immutable once filed and are
    cached forever, keyed by accession number.
  * companyfacts / companyconcept / submissions are REBUILT as new filings
    land. Caching those aggressively serves a stale capital structure, so
    they get a short TTL plus ETag revalidation.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "capstruct"

# Seconds. None == immutable, never expires.
IMMUTABLE = None
MUTABLE_TTL = 6 * 3600


@dataclass
class CacheEntry:
    body: bytes
    etag: str | None
    fetched_at: float
    ttl: float | None

    @property
    def expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.fetched_at) > self.ttl


def policy_for(url: str) -> float | None:
    """TTL for a URL. Archives are immutable; the JSON APIs are not."""
    if "/Archives/" in url:
        return IMMUTABLE
    return MUTABLE_TTL


class ResponseCache:
    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory else DEFAULT_CACHE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        sub = self.dir / key[:2]
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{key}.body", sub / f"{key}.meta.json"

    def get(self, url: str) -> CacheEntry | None:
        body_p, meta_p = self._paths(url)
        if not (body_p.exists() and meta_p.exists()):
            return None
        try:
            meta = json.loads(meta_p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        return CacheEntry(
            body=body_p.read_bytes(),
            etag=meta.get("etag"),
            fetched_at=meta.get("fetched_at", 0.0),
            ttl=meta.get("ttl"),
        )

    def put(self, url: str, body: bytes, etag: str | None = None,
            ttl: float | None = "__auto__") -> None:      # type: ignore[assignment]
        body_p, meta_p = self._paths(url)
        resolved = policy_for(url) if ttl == "__auto__" else ttl
        body_p.write_bytes(body)
        meta_p.write_text(json.dumps({
            "url": url,
            "etag": etag,
            "fetched_at": time.time(),
            "ttl": resolved,
        }))

    def touch(self, url: str) -> None:
        """Mark a revalidated (304) entry as fresh without rewriting the body."""
        _, meta_p = self._paths(url)
        if not meta_p.exists():
            return
        meta = json.loads(meta_p.read_text())
        meta["fetched_at"] = time.time()
        meta_p.write_text(json.dumps(meta))

    def clear(self) -> int:
        n = 0
        for p in self.dir.rglob("*.body"):
            p.unlink(missing_ok=True)
            p.with_suffix("").with_suffix(".meta.json").unlink(missing_ok=True)
            n += 1
        return n
