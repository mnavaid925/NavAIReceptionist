"""Django settings for NavAIReceptionist.

Every value that differs per environment is read from `.env` (see `.env.example`
for the documented template). Nothing here carries a real credential.

CRITICAL: `AUTH_USER_MODEL = 'accounts.User'` is declared BEFORE the very first
`makemigrations`. Django bakes the user model into every migration that references
it, so changing it later requires a destructive reset, not a refactor.
"""
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


# --------------------------------------------------------------------------- #
# .env helpers
# --------------------------------------------------------------------------- #

def env(key, default=''):
    """Read a string from the environment, falling back to `default`."""
    value = os.environ.get(key)
    return default if value is None or value == '' else value


def env_bool(key, default=False):
    """Read a boolean; accepts the usual truthy spellings."""
    raw = os.environ.get(key)
    if raw is None or raw == '':
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(key, default):
    """Read an int, degrading to `default` rather than raising on junk."""
    try:
        return int(env(key, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(key, default):
    """Read a float, degrading to `default` rather than raising on junk."""
    try:
        return float(env(key, str(default)))
    except (TypeError, ValueError):
        return default


def env_list(key, default=''):
    """Read a comma-separated list, dropping blank entries."""
    return [item.strip() for item in env(key, default).split(',') if item.strip()]


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #

SECRET_KEY = env('SECRET_KEY', 'dev-only-insecure-change-me-0000000000000000000000')

DEBUG = env_bool('DEBUG', True)

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', '127.0.0.1,localhost')

CSRF_TRUSTED_ORIGINS = env_list(
    'CSRF_TRUSTED_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000'
)

ROOT_URLCONF = 'config.urls'

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --------------------------------------------------------------------------- #
# Applications
#
# `daphne` must precede `django.contrib.staticfiles` so its runserver override
# wins; `channels` supplies the ASGI protocol routing the media stream needs.
# --------------------------------------------------------------------------- #

INSTALLED_APPS = [
    'daphne',
    'channels',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Module 0 — Accounts & Access
    'apps.accounts',
    # Module 1 — Business & Locations
    'apps.tenants',
    # Module 2 — Agent Setup & Telephony
    'apps.agents',
    # Module 4 — Calendar & Bookings
    'apps.scheduling',
    # Module 5 — Call Logs
    'apps.calls',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # MessageMiddleware precedes the app middlewares below because
    # SessionPolicyMiddleware flashes a message when it ends an idle session, and
    # `messages.info()` raises MessageFailure if `request._messages` has not been
    # installed yet — a 500 on the exact path that is supposed to log you out
    # gracefully.
    'django.contrib.messages.middleware.MessageMiddleware',
    # All three depend on request.user, so they sit AFTER AuthenticationMiddleware.
    # SessionPolicyMiddleware runs first so an idle session is ended before any
    # tenant or location is resolved for it. TenantMiddleware then sets
    # request.tenant, and ActiveLocationMiddleware sets request.location and
    # re-validates it against the user's UserLocation rows on EVERY request —
    # that revalidation is the cross-location IDOR boundary.
    'apps.accounts.middleware.SessionPolicyMiddleware',
    'apps.accounts.middleware.TenantMiddleware',
    'apps.accounts.middleware.ActiveLocationMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Supplies the sidebar catalog, the active location and the user's
                # assignable locations to every rendered page.
                'apps.accounts.context_processors.navigation',
            ],
        },
    },
]


# --------------------------------------------------------------------------- #
# Database — MySQL / MariaDB (XAMPP) through the PyMySQL shim in config/__init__
# --------------------------------------------------------------------------- #

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('DB_NAME', 'navai_receptionist'),
        'USER': env('DB_USER', 'root'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': env('DB_HOST', '127.0.0.1'),
        'PORT': env('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}


# --------------------------------------------------------------------------- #
# Channels — the media-stream websocket and the live-call UI
# --------------------------------------------------------------------------- #

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [env('REDIS_URL', 'redis://127.0.0.1:6379/0')]},
    }
}


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    # Resolves the tenant from the submitted customer id, then matches the
    # identifier against email OR username within that tenant.
    'apps.accounts.backends.CustomerScopedBackend',
]

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'

# auth.W004 warns that USERNAME_FIELD ('email') is not globally unique. That is the
# product's central design decision, not an oversight: `(tenant, email)` is the
# unique pair, so the same person's address can exist in two businesses. The check's
# own hint — "ensure your authentication backend can handle non-unique usernames" —
# is satisfied by CustomerScopedBackend, which resolves the tenant from the submitted
# customer id BEFORE looking up any user. Silenced by name so genuine new warnings
# stay visible.
SILENCED_SYSTEM_CHECKS = ['auth.W004']

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Failed-login throttling (sub-module 0.1). Enforced against the Django cache,
# keyed per (customer_id, identifier) and per client IP — no model, no table.
LOGIN_ATTEMPT_LIMIT = env_int('LOGIN_ATTEMPT_LIMIT', 5)
LOGIN_ATTEMPT_WINDOW_SECONDS = env_int('LOGIN_ATTEMPT_WINDOW_SECONDS', 900)

# Signed-token TTLs, in seconds.
PASSWORD_RESET_TIMEOUT = env_int('PASSWORD_RESET_TIMEOUT', 3600)
EMAIL_CHANGE_TOKEN_MAX_AGE = env_int('EMAIL_CHANGE_TOKEN_MAX_AGE', 3600)

# Fallback when a user has no inactivity_timeout of their own, in minutes.
DEFAULT_INACTIVITY_TIMEOUT_MINUTES = env_int('DEFAULT_INACTIVITY_TIMEOUT_MINUTES', 60)


# --------------------------------------------------------------------------- #
# Sessions, cache and security
# --------------------------------------------------------------------------- #

SESSION_ENGINE = 'django.contrib.sessions.backends.db'
# Absolute ceiling on a session's life, independent of activity. Django's own
# default is two weeks, which is far too loose for an account that can reconfigure
# a phone agent and read call transcripts. The per-user `inactivity_timeout`
# enforced by SessionPolicyMiddleware is the tighter, activity-based limit.
SESSION_COOKIE_AGE = env_int('SESSION_COOKIE_AGE', 12 * 60 * 60)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

CSRF_COOKIE_HTTPONLY = False  # the HTMX hx-headers snippet in base.html reads it
CSRF_COOKIE_SAMESITE = 'Lax'

X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'navai-default',
    }
}

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'


# --------------------------------------------------------------------------- #
# Email — console in development; the reset, email-change and credential-change
# notices all go through this backend.
# --------------------------------------------------------------------------- #

EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
    if DEBUG
    else 'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = env('EMAIL_HOST', 'localhost')
EMAIL_PORT = env_int('EMAIL_PORT', 25)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', 'no-reply@navaireceptionist.local')


# --------------------------------------------------------------------------- #
# Internationalization
# --------------------------------------------------------------------------- #

LANGUAGE_CODE = 'en-us'
TIME_ZONE = env('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------------- #
# Static & media
# --------------------------------------------------------------------------- #

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'


# --------------------------------------------------------------------------- #
# Providers — telephony / STT / TTS / LLM
#
# `fake` is the default for dev, tests and seeders. When the mode is not `live`
# the adapters resolve to the fake/sandbox implementation and must never reach a
# real provider: no real call placed, no billable API call. Per-location Twilio
# credentials live encrypted on `agents.AgentSetting`, NOT here.
# --------------------------------------------------------------------------- #

PROVIDER_MODE = env('PROVIDER_MODE', 'fake').strip().lower()
if PROVIDER_MODE not in {'fake', 'sandbox', 'live'}:
    PROVIDER_MODE = 'fake'

TWILIO_WEBHOOK_BASE_URL = env('TWILIO_WEBHOOK_BASE_URL', '').rstrip('/')
TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')

LLM_PROVIDER = env('LLM_PROVIDER', 'fake')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_MODEL = env('LLM_MODEL', 'placeholder-model')
LLM_TEMPERATURE = env_float('LLM_TEMPERATURE', 0.4)

STT_PROVIDER = env('STT_PROVIDER', 'fake')
STT_API_KEY = os.environ.get('STT_API_KEY', '')
STT_MODEL = env('STT_MODEL', 'placeholder-stt')
STT_LANGUAGE = env('STT_LANGUAGE', 'en-US')

TTS_PROVIDER = env('TTS_PROVIDER', 'fake')
TTS_API_KEY = os.environ.get('TTS_API_KEY', '')
TTS_VOICE_ID = env('TTS_VOICE_ID', 'placeholder-voice')
TTS_SAMPLE_RATE = env_int('TTS_SAMPLE_RATE', 24000)


# --------------------------------------------------------------------------- #
# Storage, retention and encryption
# --------------------------------------------------------------------------- #

RECORDING_STORAGE_BUCKET = env('RECORDING_STORAGE_BUCKET', 'navai-recordings-dev')
RECORDING_RETENTION_DAYS = env_int('RECORDING_RETENTION_DAYS', 30)
RECORDING_SIGNED_URL_TTL = env_int('RECORDING_SIGNED_URL_TTL', 300)

# Fernet key used to encrypt per-location Twilio credentials at rest (Module 2).
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')


# --------------------------------------------------------------------------- #
# Runtime limits — cost is a security control
# --------------------------------------------------------------------------- #

MAX_CALL_SECONDS = env_int('MAX_CALL_SECONDS', 900)
MAX_TOOL_ITERATIONS = env_int('MAX_TOOL_ITERATIONS', 4)
IDLE_TIMEOUT_SECONDS = env_int('IDLE_TIMEOUT_SECONDS', 45)
PROVIDER_TIMEOUT_SECONDS = env_int('PROVIDER_TIMEOUT_SECONDS', 10)
MAX_CONCURRENT_CALLS = env_int('MAX_CONCURRENT_CALLS', 25)


# --------------------------------------------------------------------------- #
# Logging
#
# PII rule: transcript bodies, caller numbers and tool-call argument payloads are
# never logged at INFO. Redact before persisting into CallSession.logs.
# --------------------------------------------------------------------------- #

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '[{asctime}] {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django.db.backends': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'apps': {'handlers': ['console'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
    },
}
