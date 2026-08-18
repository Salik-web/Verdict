# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Fetch layer for the scraper.

`Fetcher` is the interface; `HttpxFetcher` is the httpx implementation with the
SSRF guard applied on the initial URL and on every redirect hop, plus caps
(timeout, max redirects, response size) and a polite User-Agent. A
`PlaywrightFetcher` (headless render for JS-heavy pages) can be added behind this
same interface later without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urljoin, urlsplit

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
    # True when `text` is only the first max_bytes of the response. Silence here
    # was a real defect: a 2.9 MB page was clipped at the 2 MB cap and every
    # "not found on this page" conclusion was drawn from 69% of the document with
    # nothing recording that fact.
    truncated: bool = False
    # Full size of the response body, before any clipping.
    content_bytes: int = 0


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
            raw = text.encode("utf-8", "ignore")
            truncated = len(raw) > self.cfg.max_bytes
            if truncated:
                text = raw[: self.cfg.max_bytes].decode("utf-8", "ignore")
            return FetchResult(
                url=url,
                final_url=str(resp.url),
                status=resp.status_code,
                ok=resp.is_success,
                headers={k.lower(): v for k, v in resp.headers.items()},
                text=text,
                content_type=resp.headers.get("content-type"),
                truncated=truncated,
                content_bytes=len(raw),
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


class FixtureFetcher(Fetcher):
    """Serves a canned site from config/fixtures/site/ instead of the network.

    The mock-mode analogue of the gateway's response fixtures: it lets the WHOLE
    pipeline (including Diagnosis, which is the one stage that would otherwise
    need real HTTP) run end-to-end offline and deterministically — no keys, no
    network, no dependence on the account's domain actually resolving.

    Path-based: `/robots.txt` -> robots.txt fixture, `/sitemap.xml` ->
    sitemap.xml fixture, `/` -> home.html, anything else (llms.txt, competitor
    pages) -> 404, which is what drives the missing_llms_txt gap.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir

    def _read(self, name: str) -> str | None:
        path = self._dir / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def get(self, url: str) -> FetchResult:
        path = urlsplit(url).path or "/"
        body: str | None
        content_type = "text/html; charset=utf-8"
        if path.rstrip("/") == "/robots.txt".rstrip("/") or path == "/robots.txt":
            body = self._read("robots.txt")
            content_type = "text/plain; charset=utf-8"
        elif path == "/sitemap.xml":
            body = self._read("sitemap.xml")
            content_type = "application/xml"
        elif path in ("", "/"):
            body = self._read("home.html")
        else:
            body = None

        if body is None:
            return FetchResult(url=url, final_url=url, status=404, ok=False)
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            ok=True,
            headers={"content-type": content_type},
            text=body,
            content_type=content_type,
        )
