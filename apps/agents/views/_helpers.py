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

    **Both values are resolved from Module 3's real routes, never hand-written.**
    They were string literals while Module 3 was unbuilt, and by the time 3.1/3.2
    shipped the literals no longer matched (`/ws/runtime/media/` for a route that
    is really `/ws/media-stream/`) — a page instructing staff to paste a URL that
    does not resolve is worse than one that says nothing. `reverse()` and
    `media_stream_ws_url()` cannot drift from the routes the same way.

    There is deliberately **no status-callback URL**: no such route exists. The
    `<Dial action>` status callback is a tracked deferral, and offering a 404 for
    a caller to configure would break every call it was set on.
    """
    base = (django_settings.TWILIO_WEBHOOK_BASE_URL or '').rstrip('/')
    if not base:
        return {}
    from django.urls import reverse

    from apps.runtime.providers.telephony import media_stream_ws_url

    return {
        'voice': f"{base}{reverse('runtime:voice_webhook')}",
        'stream': media_stream_ws_url(),
    }
