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
