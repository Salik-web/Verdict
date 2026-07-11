"""Fetch layer for the scraper.

`Fetcher` is the interface; `HttpxFetcher` is the httpx implementation with the
SSRF guard applied on the initial URL and on every redirect hop, plus caps
(timeout, max redirects, response size) and a polite User-Agent. A
`PlaywrightFetcher` (headless render for JS-heavy pages) can be added behind this
same interface later without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from app.pipeline.diagnosis.config import ScraperConfig
from app.pipeline.diagnosis.ssrf import assert_public_url


class FetchResult(BaseModel):
    url: str
    final_url: str
    status: int
    ok: bool
    headers: dict[str, str] = Field(default_factory=dict)
    text: str = ""
    content_type: str | None = None


class FetchError(RuntimeError):
    """Non-SSRF fetch failure (timeout, too many redirects, transport error)."""


class Fetcher(ABC):
    @abstractmethod
    def get(self, url: str) -> FetchResult:
        """Fetch a URL. Raises SSRFError if disallowed, FetchError on failure."""


class HttpxFetcher(Fetcher):
    def __init__(self, config: ScraperConfig) -> None:
        self.cfg = config

    def get(self, url: str) -> FetchResult:
        current = url
        headers = {"User-Agent": self.cfg.user_agent}
        for _ in range(self.cfg.max_redirects + 1):
            assert_public_url(current)  # every hop is re-validated
            try:
                with httpx.Client(
                    timeout=self.cfg.timeout_s, follow_redirects=False
                ) as client:
                    resp = client.get(current, headers=headers)
            except httpx.HTTPError as exc:
                raise FetchError(f"fetch failed for {current}: {exc}") from exc

            location = resp.headers.get("location")
            if resp.is_redirect and location:
                current = str(urljoin(current, location))
                continue

            text = resp.text
            if len(text.encode("utf-8", "ignore")) > self.cfg.max_bytes:
                text = text.encode("utf-8", "ignore")[: self.cfg.max_bytes].decode(
                    "utf-8", "ignore"
                )
            return FetchResult(
                url=url,
                final_url=str(resp.url),
                status=resp.status_code,
                ok=resp.is_success,
                headers={k.lower(): v for k, v in resp.headers.items()},
                text=text,
                content_type=resp.headers.get("content-type"),
            )
        raise FetchError(f"too many redirects for {url}")


class FakeFetcher(Fetcher):
    """In-memory fetcher for tests: maps URL -> FetchResult (or 404)."""

    def __init__(self, pages: dict[str, FetchResult]) -> None:
        self._pages = pages

    def get(self, url: str) -> FetchResult:
        assert_public_url(url)  # tests still exercise the guard
        if url in self._pages:
            return self._pages[url]
        return FetchResult(url=url, final_url=url, status=404, ok=False)
