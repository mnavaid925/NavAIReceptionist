"""Test settings — SQLite in-memory, in-memory channel layer, fake providers.

Selected by `pytest.ini` (`DJANGO_SETTINGS_MODULE = config.settings_test`), so
`venv\\Scripts\\python.exe -m pytest -q apps/<app>` needs no --ds flag.

PROVIDER_MODE is pinned to "fake" here and asserted by the suite: a test that can
place a real call or make a billable API call is a Critical defect, not a config
choice.
"""
from config.settings import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CHANNEL_LAYERS = {
    'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
}

# Never anything but "fake" in the test suite.
PROVIDER_MODE = 'fake'

# 3.4's pre-redirect drain exists to let a real carrier's jitter buffer flush the
# handoff line's last frames before the media leg is cut, so the caller does not
# lose the final word. A FAKE backend has no jitter buffer and no carrier, so the
# wait buys nothing here.
#
# It is not merely wasted time, it is a RACE. The production default is 0.6s and
# `simulate_call._drain` polls with a 0.6s quiet window — a dead heat. Whichever
# side won decided the test: if the drain gave up first, the command sent `stop`
# and disconnected, cancelling `_execute_transfer` before it had written
# `CallSession.transfer`, and the transfer assertions failed. That is why the
# transfer tests passed alone and intermittently failed in a loaded full-suite
# run. Shortening it here makes the ordering deterministic instead of a coin
# flip, and leaves the real 0.6s untouched where it actually does something.
TRANSFER_DRAIN_SECONDS = 0.05

# Fast, deliberately insecure hasher — test-only.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'navai-test',
    }
}

# Keep the suite's output readable.
LOGGING['root']['level'] = 'ERROR'  # noqa: F405
LOGGING['loggers']['apps']['level'] = 'ERROR'  # noqa: F405

ALLOWED_HOSTS = ['testserver', '127.0.0.1', 'localhost']

# Media and static writes land in a throwaway directory during tests.
MEDIA_ROOT = BASE_DIR / 'temp' / 'test-media'  # noqa: F405
# Same isolation for private recordings (5.4) — without this override a test that
# writes through `recording_storage` would land real files inside the project's
# `private_media/`, the exact leak the `MEDIA_ROOT` redirect above already prevents.
PRIVATE_MEDIA_ROOT = BASE_DIR / 'temp' / 'test-private-media'  # noqa: F405
