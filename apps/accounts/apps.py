from django.apps import AppConfig
from django.core.checks import Error, register

#: Cache backends that live inside ONE process. Anything on this list makes every
#: cache-backed security ceiling per-worker rather than per-deployment.
_PER_PROCESS_CACHE_BACKENDS = {
    'django.core.cache.backends.locmem.LocMemCache',
    'django.core.cache.backends.dummy.DummyCache',
}


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
    label = 'accounts'
    verbose_name = 'Accounts & Access'

    def ready(self):
        # Registered at app-ready time (not module import) so the check's lifetime
        # is tied to the app registry — same posture as `runtime.E001`.
        register(_check_shared_cache)


def _check_shared_cache(app_configs, **kwargs):
    """Fail LOUD when a real deployment runs on a per-process cache.

    Two security ceilings in this product are cache-backed, and each is only as
    wide as the cache is shared:

    * **Login throttling** (``apps/accounts/throttling.py``) — on a per-process
      cache an attacker spreading attempts across N workers gets N times the
      lockout ceiling, and the lockout is invisible to every worker but one.
    * **The media-stream single-use token claim** (3.5) — a replayed stream token
      presented to a different worker finds no claim and authorizes a second
      stream against one call.

    Neither fails visibly. Both still behave correctly in a single-process dev run
    and in every test, so the weakening appears only under the multi-worker
    deployment nobody exercises locally — exactly the shape of bug worth spending
    a startup error on.

    Inert under ``DEBUG``: a local run with no Redis process is the normal setup
    here, and ``LocMemCache`` is the right choice for it.
    """
    from django.conf import settings

    if settings.DEBUG:
        return []
    backend = (settings.CACHES or {}).get('default', {}).get('BACKEND', '')
    if backend not in _PER_PROCESS_CACHE_BACKENDS:
        return []
    return [
        Error(
            f'CACHES["default"] is {backend!r} outside DEBUG — a per-process cache.',
            hint='Login throttling and the media-stream single-use token claim are '
                 'both cache-backed, so on a per-process cache they are enforced '
                 'per worker instead of per deployment: an attacker spreading '
                 'login attempts across workers multiplies the lockout ceiling, '
                 'and a replayed stream token can authorize a second stream. Set '
                 'CACHE_URL to a shared Redis URL (e.g. redis://127.0.0.1:6379/1).',
            id='accounts.E001',
        )
    ]
