"""Failed-login throttling, backed by the Django cache.

No model and no table: a login-attempt counter is ephemeral, high-churn state, and
the eleven-model data set has no home for it.

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


def is_throttled(keys):
    """True when any key has reached the configured attempt limit."""
    limit = settings.LOGIN_ATTEMPT_LIMIT
    return any((cache.get(key) or 0) >= limit for key in keys)


def register_failure(keys):
    """Count a failed attempt against every key, starting the window if needed."""
    window = settings.LOGIN_ATTEMPT_WINDOW_SECONDS
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
