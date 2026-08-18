# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Where a provider's API key comes from — a deployment mode, not a fork.

Two deployments need different answers to the same question, and both must run
the SAME code:

  * **self_hosted** (the default, and what an open-source user runs). One set of
    keys, supplied by the operator through the environment or `.env`. The user
    brings their own keys — BYOK — and nothing else is involved.

  * **managed** (what a hosted product runs). Keys belong to a tenant and are
    fetched server-side per account, so one deployment serves many customers
    without any of them seeing another's key.

`DEPLOYMENT_MODE` selects between them. Nothing downstream changes: providers
still call `resolve_api_key(env_name)` and get a string or None.

The managed resolver deliberately does NOT define a database table. A hosted
product's key storage is its own concern — Postgres, Vault, KMS, a secrets
manager — so this ships the SEAM (`lookup`) and lets the product supply the
implementation. That is what keeps the multi-tenant path available without
forcing an unused table into an open-source install.

Account scoping travels by contextvar rather than as a parameter on
`Provider.generate`. That signature is the public extension point for
third-party adapters (see providers/registry.py); widening it to carry an
account id would break every external adapter for a concern no adapter should
have to think about.
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.config import get_settings

#: The account whose keys the current call should use. Set by the gateway for the
#: duration of a provider call; None in self-hosted deployments.
_current_account: ContextVar[uuid.UUID | None] = ContextVar(
    "geo_current_account", default=None
)


@contextmanager
def account_scope(account_id: uuid.UUID | None) -> Iterator[None]:
    """Bind the account whose credentials apply inside this block."""
    token = _current_account.set(account_id)
    try:
        yield
    finally:
        _current_account.reset(token)


def current_account() -> uuid.UUID | None:
    return _current_account.get()


class CredentialResolver(ABC):
    """env var name -> API key, or None when the deployment has no such key."""

    @abstractmethod
    def resolve(self, env_name: str, account_id: uuid.UUID | None = None) -> str | None:
        raise NotImplementedError


class EnvCredentialResolver(CredentialResolver):
    """Self-hosted BYOK: the operator's own keys, from the environment.

    Checks the process environment first, then Settings. The fallback is the
    important half: pydantic-settings reads services/pipeline/.env into the
    Settings OBJECT, it does not export those values into os.environ — so a key
    that lives only in .env is invisible to `os.environ.get()`. Reading
    os.environ alone means "the key is in .env" and "the provider can see the
    key" are different things, which fails at the worst possible moment.
    """

    def resolve(self, env_name: str, account_id: uuid.UUID | None = None) -> str | None:
        value = os.environ.get(env_name)
        if value:
            return value
        # Settings field names are the lowercase env var names (GOOGLE_API_KEY ->
        # google_api_key), so this stays in sync with .env.example automatically.
        return getattr(get_settings(), env_name.lower(), None)


#: (account_id, env_var_name) -> key or None. Supplied by a hosted product.
AccountKeyLookup = Callable[[uuid.UUID, str], "str | None"]


class AccountCredentialResolver(CredentialResolver):
    """Managed multi-tenant: the tenant's key, fetched server-side.

    `lookup` is injected by the hosting application — this package never reads a
    credentials table, so an open-source install carries no schema it does not
    use. `fallback_to_env` lets a hosted deployment keep operator-owned keys for
    tenants who have not supplied their own (a shared trial key, say); turn it
    off to guarantee a tenant can only ever spend against its own key.
    """

    def __init__(
        self, lookup: AccountKeyLookup, *, fallback_to_env: bool = True
    ) -> None:
        self._lookup = lookup
        self._env = EnvCredentialResolver()
        self._fallback_to_env = fallback_to_env

    def resolve(self, env_name: str, account_id: uuid.UUID | None = None) -> str | None:
        account_id = account_id or current_account()
        if account_id is not None:
            key = self._lookup(account_id, env_name)
            if key:
                return key
        return self._env.resolve(env_name) if self._fallback_to_env else None


_resolver: CredentialResolver | None = None
_warned_managed_without_lookup = False


def set_credential_resolver(resolver: CredentialResolver | None) -> None:
    """Install the resolver for this process. `None` restores the default for
    the configured deployment mode. A hosted product calls this once at start-up
    with its own `AccountCredentialResolver`."""
    global _resolver
    _resolver = resolver


def get_credential_resolver() -> CredentialResolver:
    """The active resolver.

    `self_hosted` resolves from the environment. `managed` is expected to have
    had a resolver installed by the hosting application; if none was, this falls
    back to environment resolution and warns once per process — the failure is
    otherwise silent, and its consequence is a tenant spending against the
    operator's key. Falling back rather than raising is deliberate: a
    misconfigured deployment should still boot and report per-engine status (see
    `gateway.availability`) instead of dying on the first model call, which is
    far harder to diagnose.

    The managed branch is not memoised, so installing a resolver later takes
    effect on the next call rather than being shadowed by a cached default.
    """
    global _resolver, _warned_managed_without_lookup
    if _resolver is not None:
        return _resolver

    if get_settings().deployment_mode == "managed":
        if not _warned_managed_without_lookup:
            _warned_managed_without_lookup = True
            logging.getLogger(__name__).warning(
                "DEPLOYMENT_MODE=managed but no credential resolver was installed; "
                "falling back to environment keys. Every tenant will spend against "
                "the operator's key. Call set_credential_resolver("
                "AccountCredentialResolver(lookup)) at start-up."
            )
        # Not cached: installing a resolver later must take effect immediately,
        # and the warning above should keep firing until someone does.
        return EnvCredentialResolver()

    _resolver = EnvCredentialResolver()
    return _resolver


def resolve_api_key(env_name: str) -> str | None:
    """Find a provider's API key under the active deployment mode."""
    return get_credential_resolver().resolve(env_name)
