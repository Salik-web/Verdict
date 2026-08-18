# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""SSRF guard: reject internal/private/metadata targets, allow public ones."""

from __future__ import annotations

import pytest

from app.pipeline.diagnosis.ssrf import SSRFError, assert_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",  # loopback
        "http://localhost/admin",  # loopback via name
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://metadata.google.internal/",  # metadata hostname
        "http://10.0.0.5/",  # RFC1918
        "http://192.168.1.1/",  # RFC1918
        "http://172.16.0.1/",  # RFC1918
        "http://[::1]/",  # IPv6 loopback
        "file:///etc/passwd",  # non-http scheme
        "ftp://example.com/",  # non-http scheme
        "http://100.64.0.1/",  # CGNAT / shared
    ],
)
def test_blocks_internal_and_non_http(url):
    with pytest.raises(SSRFError):
        assert_public_url(url)


def test_allows_public_hosts():
    # Public IP literals (no DNS needed, so this holds offline). The guard must
    # NOT raise for globally-routable addresses.
    assert_public_url("https://1.1.1.1/")
    assert_public_url("http://8.8.8.8/robots.txt")
