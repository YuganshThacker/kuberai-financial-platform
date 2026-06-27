"""
Robust NSE HTTP session for universe-scale ingestion.

NSE's public API (www.nseindia.com/api/*) is protected by cookie-based bot
detection: visiting the homepage sets cookies that every subsequent API call
must echo back. A bare GET to the API returns 401/403 or simply hangs — which
is exactly why direct calls failed intermittently at Nifty50 scale and would
fail constantly across 2,000+ symbols.

This module maintains a single warmed, cookie-bearing httpx.Client with:
  • homepage warmup to acquire bot-detection cookies (re-warmed on 401/403)
  • polite throttling (min interval between requests + jitter)
  • exponential-backoff retries on transient failures
  • thread-safety so a bounded worker pool can share one session

Use the module-level singleton via get_session().
"""
from __future__ import annotations

import random
import threading
import time
from typing import Optional

import httpx

_HOMEPAGE = "https://www.nseindia.com"
# Pages whose responses set the bot-detection cookies the API needs.
_WARMUP_PATHS = ("/", "/market-data/securities-available-for-trading")

# Realistic desktop UA strings; one is chosen per session lifetime.
_UA_POOL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
)


class NSESession:
    """Cookie-warmed, throttled, retrying HTTP client for NSE endpoints."""

    def __init__(self, min_interval: float = 0.7, max_retries: int = 4, warmup_ttl: float = 600.0):
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._warmup_ttl = warmup_ttl  # re-warm cookies after this many seconds
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._warmed_at = 0.0
        self._ua = random.choice(_UA_POOL)
        self._client: Optional[httpx.Client] = None

    # ── client lifecycle ────────────────────────────────────────────────────
    def _ensure_client(self) -> None:
        if self._client is None:
            self._client = httpx.Client(
                headers={
                    "User-Agent": self._ua,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Connection": "keep-alive",
                },
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=15.0),
            )

    def _warmup(self) -> None:
        """Acquire bot-detection cookies by hitting the homepage."""
        self._ensure_client()
        for path in _WARMUP_PATHS:
            try:
                self._client.get(_HOMEPAGE + path, timeout=20)
                time.sleep(0.4 + random.uniform(0, 0.3))
            except Exception:
                pass
        self._warmed_at = time.monotonic()

    def _maybe_warm(self) -> None:
        if self._client is None or (time.monotonic() - self._warmed_at) > self._warmup_ttl:
            self._warmup()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_request)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.3))
        self._last_request = time.monotonic()

    # ── public requests ─────────────────────────────────────────────────────
    def get_json(self, url: str, referer: str = "https://www.nseindia.com/"):
        return self._request(url, referer, want="json")

    def get_bytes(self, url: str, referer: str = "https://www.nseindia.com/") -> bytes:
        return self._request(url, referer, want="bytes")

    def _request(self, url: str, referer: str, want: str):
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            with self._lock:
                self._maybe_warm()
                self._throttle()
                client = self._client
            try:
                headers = {"Referer": referer}
                if want == "json":
                    headers["Accept"] = "application/json, text/plain, */*"
                r = client.get(url, headers=headers, timeout=45 if want == "bytes" else 30)
                if r.status_code in (401, 403, 429):
                    # cookies expired or rate-limited → force a re-warm and back off
                    with self._lock:
                        self._warmed_at = 0.0
                    raise httpx.HTTPStatusError(
                        f"status {r.status_code}", request=r.request, response=r
                    )
                r.raise_for_status()
                return r.json() if want == "json" else r.content
            except Exception as exc:
                last_exc = exc
                backoff = min(2 ** attempt, 10) + random.uniform(0, 0.6)
                time.sleep(backoff)
        raise last_exc if last_exc else RuntimeError(f"NSE request failed: {url}")


# ── module singleton ─────────────────────────────────────────────────────────
_session: Optional[NSESession] = None
_session_lock = threading.Lock()


def get_session() -> NSESession:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                _session = NSESession()
    return _session
