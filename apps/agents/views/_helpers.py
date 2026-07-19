"""Shared view helpers for Module 2.

The important one is `get_setting_for_active_location`, which every view in this
module uses instead of accepting a pk.
"""
from django.conf import settings as django_settings

__all__ = ['get_setting_for_active_location', 'webhook_urls']


def get_setting_for_active_location(request):
    """The AgentSetting row for the session's active location, creating it if new.

    **NO PK APPEARS IN ANY MODULE 2 URL, and that is the security design.** The
    row is resolved entirely from `request.tenant` and `request.location`, both
    set by middleware and re-validated against the user's `UserLocation` rows on
    every request. With no id to tamper with, there is no cross-tenant or
    cross-location IDOR surface here to defend — the class of bug is absent
    rather than guarded against.

    Returns `(setting, None)` or `(None, redirect_response)` when there is no
    active location to configure.
    """
    from django.contrib import messages
    from django.shortcuts import redirect

    from apps.agents.models import AgentSetting

    if request.tenant is None or request.location is None:
        messages.error(
            request,
            'Choose a location first — an agent is configured per location.',
        )
        return None, redirect('accounts:my_locations')

    setting, _ = AgentSetting.objects.get_or_create(
        tenant=request.tenant,
        location=request.location,
    )
    return setting, None


def webhook_urls(setting):
    """The exact URLs to paste into the Twilio console for this number.

    Shown rather than auto-configured: writing to a tenant's Twilio account would
    need broader API permission than reading, and getting it wrong silently
    breaks their phone line.

    The paths are Module 3's ingress and do not resolve yet, so they are built as
    strings rather than through `reverse()`.
    """
    base = (django_settings.TWILIO_WEBHOOK_BASE_URL or '').rstrip('/')
    if not base:
        return {}
    stream_base = base.replace('https://', 'wss://').replace('http://', 'ws://')
    return {
        'voice': f'{base}/runtime/voice/',
        'status': f'{base}/runtime/status/',
        'stream': f'{stream_base}/ws/runtime/media/',
    }
