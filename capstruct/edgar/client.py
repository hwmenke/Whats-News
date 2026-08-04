"""
client.py - SEC EDGAR HTTP client.

Every request goes through the token bucket and the response cache. SEC
requires a descriptive User-Agent with a contact email; requests without one
are refused, so the client will not construct without it.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .cache import ResponseCache, policy_for
from .ratelimit import TokenBucket

DATA_SEC = "https://data.sec.gov"
WWW_SEC = "https://www.sec.gov"
EFTS_SEC = "https://efts.sec.gov"


class EdgarUnreachable(RuntimeError):
    """
    Raised when SEC cannot be reached at all (blocked egress, DNS, proxy).

    Distinct from an HTTP error: it means the environment has no route to
    SEC, so callers can surface "no network access to sec.gov" instead of
    reporting the issuer as having no data.
    """


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache: ResponseCache | None = None,
        bucket: TokenBucket | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        ua = user_agent or os.environ.get("CAPSTRUCT_USER_AGENT")
        if not ua or "@" not in ua:
            raise ValueError(
                "SEC requires a descriptive User-Agent including a contact email, "
                'e.g. "CapStruct Research you@example.com". Pass user_agent= or '
                "set CAPSTRUCT_USER_AGENT."
            )
        self.user_agent = ua
        self.cache = cache if cache is not None else ResponseCache()
        self.bucket = bucket or TokenBucket()
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={
                "User-Agent": ua,
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
        )

    # ── core fetch ──────────────────────────────────────────────────────
    def get(self, url: str, *, force: bool = False) -> bytes:
        """Fetch a URL through the cache + limiter. Returns the body."""
        entry = None if force else self.cache.get(url)
        if entry and not entry.expired:
            return entry.body

        headers = {}
        # Expired-but-present entries are revalidated rather than refetched.
        if entry and entry.etag:
            headers["If-None-Match"] = entry.etag

        self.bucket.acquire()
        try:
            resp = self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            if entry:
                # Serve stale rather than fail — a stale filing beats nothing,
                # and the caller can see it via the cache metadata.
                return entry.body
            raise EdgarUnreachable(f"cannot reach {url}: {exc}") from exc

        if resp.status_code == 304 and entry:
            self.cache.touch(url)
            return entry.body

        if resp.status_code == 403:
            raise EdgarUnreachable(
                f"403 for {url} — this is either a blocked network egress or a "
                "User-Agent SEC rejected. Check that sec.gov is reachable and "
                "that the UA includes a contact email."
            )
        resp.raise_for_status()

        self.cache.put(url, resp.content, etag=resp.headers.get("ETag"),
                       ttl=policy_for(url))
        return resp.content

    def get_json(self, url: str, *, force: bool = False) -> Any:
        body = self.get(url, force=force)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"non-JSON response from {url}: {exc}") from exc

    # ── endpoints ───────────────────────────────────────────────────────
    @staticmethod
    def _cik10(cik: int | str) -> str:
        return str(int(str(cik).lstrip("0") or 0)).zfill(10)

    def submissions(self, cik: int | str) -> dict:
        return self.get_json(f"{DATA_SEC}/submissions/CIK{self._cik10(cik)}.json")

    def company_facts(self, cik: int | str) -> dict:
        return self.get_json(
            f"{DATA_SEC}/api/xbrl/companyfacts/CIK{self._cik10(cik)}.json"
        )

    def company_concept(self, cik: int | str, tag: str,
                        namespace: str = "us-gaap") -> dict:
        # Namespace is parameterised: cover-page facts such as
        # EntityCommonStockSharesOutstanding live under `dei`, not `us-gaap`.
        return self.get_json(
            f"{DATA_SEC}/api/xbrl/companyconcept/CIK{self._cik10(cik)}"
            f"/{namespace}/{tag}.json"
        )

    def company_tickers(self) -> dict:
        return self.get_json(f"{WWW_SEC}/files/company_tickers.json")

    def filing_index(self, cik: int | str, accession_number: str) -> dict:
        acc = accession_number.replace("-", "")
        cik_int = int(str(cik).lstrip("0") or 0)
        return self.get_json(
            f"{WWW_SEC}/Archives/edgar/data/{cik_int}/{acc}/index.json"
        )

    def document(self, cik: int | str, accession_number: str, filename: str) -> bytes:
        acc = accession_number.replace("-", "")
        cik_int = int(str(cik).lstrip("0") or 0)
        return self.get(
            f"{WWW_SEC}/Archives/edgar/data/{cik_int}/{acc}/{filename}"
        )

    def full_text_search(self, query: str, forms: str | None = None) -> dict:
        url = f"{EFTS_SEC}/LATEST/search-index?q={httpx.QueryParams({'q': query})['q']}"
        if forms:
            url += f"&forms={forms}"
        return self.get_json(url)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
