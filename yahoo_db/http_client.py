"""
http_client.py - One shared HTTP session for the non-yfinance data sources.

Yahoo's JSON endpoints are reached through yfinance's own session (it manages
the cookie/crumb handshake); everything else — SEC, Nasdaq Trader — is plain
HTTP and goes through here.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, user_agent: str, timeout: int = 30, max_retries: int = 3,
                 backoff: float = 5.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
        })

    def get(self, url: str, params: dict = None) -> requests.Response:
        """GET with retries on transient status codes and network errors."""
        delay = self.backoff
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code in RETRY_STATUS:
                    raise requests.HTTPError(
                        f"{resp.status_code} from {url}", response=resp
                    )
                resp.raise_for_status()
                return resp
            except Exception as exc:      # network error or retryable status
                last_exc = exc
                if attempt < self.max_retries:
                    logger.warning("GET %s failed (%s); retry %d in %.0fs",
                                   url, exc, attempt, delay)
                    time.sleep(delay)
                    delay *= 2
        raise last_exc

    def get_json(self, url: str, params: dict = None):
        return self.get(url, params=params).json()

    def get_text(self, url: str, params: dict = None) -> str:
        return self.get(url, params=params).text

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
