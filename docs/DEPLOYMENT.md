# Deployment modes

Two independent switches. They are often confused, so: one picks **which model
answers**, the other picks **where its API key comes from**.

| Env var | Values | Decides |
| --- | --- | --- |
| `GATEWAY_MODE` | `mock` \| `dev` \| `prod` | Which provider/model serves each task (`config/models.yaml`) |
| `DEPLOYMENT_MODE` | `self_hosted` \| `managed` | Where that provider's API key is read from |

`GATEWAY_MODE=mock` needs no keys at all — the whole pipeline runs against
canned fixtures. That is the default, and it is how you should evaluate the
project before spending anything.

---

## `self_hosted` — bring your own keys (the default)

One set of keys, yours, read from the process environment or
`services/pipeline/.env`. Nothing else is involved: no key database, no
encryption at rest, no tenancy.

```bash
GATEWAY_MODE=dev
DEPLOYMENT_MODE=self_hosted
GOOGLE_API_KEY=...        # only the engines you actually want
PERPLEXITY_API_KEY=...
```

Keys are resolved by `EnvCredentialResolver`, which checks `os.environ` first
and then the pydantic `Settings` object. That second step matters: pydantic
reads `.env` into the settings object, it does **not** export those values into
`os.environ`. Reading `os.environ` alone would mean "the key is in `.env`" and
"the provider can see the key" are different things — a failure that only shows
up on the first real model call.

### You only need keys for the engines you want

A missing key is a **state**, not a crash. Engines whose key is absent are
dropped before any call is made, so a user with only a Perplexity key gets a
working Perplexity-only scan rather than a scan that dies partway through having
already spent money on the engines that did work.

```python
from app.gateway.availability import all_task_statuses

for s in all_task_statuses("dev"):
    print(s.task, s.label, s.available, s.reason)
```

Only when *no* engine is usable does the monitor raise `NoEngineAvailable`, and
the message names the environment variable to set.

---

## `managed` — per-tenant keys, server-side

For building a multi-tenant product on top. Keys belong to an account and are
fetched per call, so one deployment serves many customers and none of them sees
another's key.

This package ships the **seam**, not a schema. Where you keep tenant keys —
Postgres, Vault, KMS, a secrets manager — is your product's decision, so an
open-source install carries no credentials table it never uses.

```python
# once, at application start-up
from app.gateway.credentials import (
    AccountCredentialResolver,
    set_credential_resolver,
)

def lookup(account_id, env_name):        # your storage, your encryption
    return my_vault.get(account_id, env_name)

set_credential_resolver(
    AccountCredentialResolver(lookup, fallback_to_env=False)
)
```

`fallback_to_env=False` guarantees a tenant can only ever spend against its own
key. Leave it `True` only if you deliberately want operator-owned keys to serve
tenants who have not supplied their own (a shared trial key, say).

### How the account reaches the resolver

`Gateway.call(...)` binds the account for the duration of the provider call, via
a context variable. Adapters never see it and never need to.

This is deliberate. `Provider.generate(target, messages, params)` is the public
extension point for third-party adapters — widening that signature to carry an
account id would break every external adapter for a concern no adapter should
have to think about.

### If you forget to install a resolver

`DEPLOYMENT_MODE=managed` with no resolver installed falls back to environment
keys and logs a warning once per process. It does not raise: a misconfigured
deployment should still boot and report per-engine status rather than dying on
its first model call, which is far harder to diagnose. The warning is loud
because the consequence is quiet — every tenant would spend against the
operator's key.

---

## Cost control

Whichever mode you run, `llm_cost_log` records one row per issued call,
including cache hits (flagged, zero cost) and failures (status `error`). Costs
are **modelled** from `config/models.yaml` pricing, not billed amounts — a
free-tier call still shows its list price so unit economics stay meaningful.
Read `SCALING.md` before quoting those numbers as spend.
