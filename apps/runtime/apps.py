from django.apps import AppConfig
from django.core.checks import Error, register


class RuntimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.runtime'
    label = 'runtime'
    verbose_name = 'Call Runtime'

    def ready(self):
        # Register at app-ready time (not module import) so the check's lifetime is
        # tied to the app registry, the normal home for system checks.
        register(_check_webhook_base_url)


def _check_webhook_base_url(app_configs, **kwargs):
    """Fail LOUD when the public webhook base is missing outside DEBUG.

    The inbound Twilio signature is verified against ``TWILIO_WEBHOOK_BASE_URL`` +
    the request path (``providers.telephony.webhook_public_url``). With the setting
    unset in a real deployment, verification silently falls back to the ``Host``
    header, which will not match the URL Twilio actually signed — so every genuine
    inbound call fails with a misleading ``signature_invalid`` and inbound is
    totally, quietly broken. Surfacing it at ``manage.py check`` / deploy time
    turns a 3am incident into a startup error. Inert under ``DEBUG`` (a bare local
    run with no tunnel is expected and falls back to the request host on purpose).
    """
    from django.conf import settings

    if settings.DEBUG:
        return []
    if (getattr(settings, 'TWILIO_WEBHOOK_BASE_URL', '') or '').strip():
        return []
    return [
        Error(
            'TWILIO_WEBHOOK_BASE_URL is not set outside DEBUG.',
            hint='Inbound Twilio signatures are verified against this public base '
                 'URL plus the request path. Left unset, verification falls back '
                 'to the Host header and every real inbound call fails its '
                 'signature check. Set TWILIO_WEBHOOK_BASE_URL to the exact public '
                 'URL Twilio posts the voice webhook to.',
            id='runtime.E001',
        )
    ]
