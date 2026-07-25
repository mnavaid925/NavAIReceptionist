"""The shared failed-attempt counter, backed by the Django cache.

No model and no table: an attempt counter is ephemeral, high-churn state, and the
eleven-model data set has no home for it.

Two callers, deliberately on SEPARATE key namespaces:

* **Login and credential changes** (`accounts.backends`, `accounts.views.Auth`)
  via `build_keys`, keyed on the account AND the client IP.
* **The Twilio voice webhook** (`runtime.webhooks`) via `scoped_ip_keys`, keyed on
  the client IP alone, with its own limit and window.

`build_keys`'s IP key is scope-less on purpose — a spraying run should burn one
budget across login, reset and change-password alike. The webhook must NOT share
it: a scanner hitting a public endpoint would otherwise lock real users out of
signing in, and the two have completely different legitimate rates.

The rule this implements is *rate-limit without disclosure*. A counter is
incremented on EVERY failed attempt — including attempts against a customer id or
an identifier that does not exist — so "too many attempts" looks identical whether
or not the account is real. Combined with the single uniform failure message in
`views/Auth.py`, that closes the account-enumeration channel.

Two independent keys are checked per attempt:

* `(customer_id, identifier)` — protects one account from a targeted guessing run.
* client IP — protects the whole tenant estate from a spraying run across accounts.

NOTE for deployment: `LocMemCache` is per-process, so counters are not shared
across ASGI workers. Production must point `CACHES['default']` at the Redis
instance already provisioned for Channels, or the effective limit is
`LOGIN_ATTEMPT_LIMIT x worker_count`.
"""
import hashlib

from django.conf import settings
from django.core.cache import cache

CACHE_PREFIX = 'navai:login-attempts:'


def _cache_key(scope, value):
    """Hash the key material so no email or IP is stored in the cache verbatim."""
    digest = hashlib.sha256(f'{scope}:{value}'.lower().encode('utf-8')).hexdigest()
    return f'{CACHE_PREFIX}{scope}:{digest}'


def build_keys(customer_id, identifier, client_ip):
    """The cache keys guarding one login attempt."""
    keys = []
    if customer_id or identifier:
        keys.append(_cache_key('account', f'{customer_id or ""}|{identifier or ""}'))
    if client_ip:
        keys.append(_cache_key('ip', client_ip))
    return keys


def scoped_ip_keys(scope, client_ip):
    """An IP counter in its OWN namespace, for a caller that is not a login.

    Separate from `build_keys`'s scope-less `ip` key so one surface's abuse budget
    cannot be spent by another's — see the module docstring.
    """
    return [_cache_key(f'{scope}-ip', client_ip)] if client_ip else []


def is_throttled(keys, limit=None):
    """True when any key has reached the attempt limit.

    `limit` defaults to the login ceiling; a caller with a different legitimate
    rate (the webhook) passes its own.
    """
    limit = settings.LOGIN_ATTEMPT_LIMIT if limit is None else limit
    return any((cache.get(key) or 0) >= limit for key in keys)


def register_failure(keys, window=None):
    """Count a failed attempt against every key, starting the window if needed."""
    window = settings.LOGIN_ATTEMPT_WINDOW_SECONDS if window is None else window
    for key in keys:
        try:
            cache.incr(key)
        except ValueError:
            # Key absent or expired — start a fresh window. `add` rather than
            # `set` so two concurrent failures cannot reset each other's window.
            if not cache.add(key, 1, window):
                try:
                    cache.incr(key)
                except ValueError:
                    pass


def clear(keys):
    """Reset the counters. Called after a successful authentication."""
    cache.delete_many(list(keys))


def retry_after_seconds():
    """How long a throttled caller is told to wait."""
    return settings.LOGIN_ATTEMPT_WINDOW_SECONDS
