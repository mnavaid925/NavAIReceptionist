"""Runtime diagnostics — sub-module 3.1's observable surface.

A service sub-module ships no CRUD, but "no templates" never means "nothing to
look at" (``voice-agent-runtime`` skill §15). This read-only page answers, for the
**active location**, the question 3.1 exists to make answerable: *are inbound
calls being resolved, and where should Twilio point?* It shows recent resolved
call sessions, the location's agent/telephony readiness, the exact webhook URL to
configure in Twilio, and the ``PROVIDER_MODE`` the whole path is running under.

It is the seed of the fuller diagnostics page 3.5 grows (per-stage latency,
ended-reason codes, live-call count). Tenant AND location scoped on every query —
the session rows come through the single audited scoping helper.
"""
from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from django.db.models import Count, Q

from apps.runtime.providers.telephony import media_stream_ws_url
from apps.runtime.views._common import *  # noqa: F401,F403
from apps.runtime.views._helpers import location_sessions, recent_location_sessions

__all__ = ['runtime_diagnostics_view']


@login_required  # noqa: F405
@require_http_methods(['GET'])  # noqa: F405
def runtime_diagnostics_view(request):
    """The runtime status page for the active location."""
    location = request.location

    setting = None
    if location is not None:
        # Scoped by tenant AND location — pk alone is never enough, and here the
        # (tenant, location) pair is unique so this is the one row or nothing.
        setting = (
            AgentSetting.objects
            .filter(tenant=request.tenant, location=location)
            .select_related('location')
            .first()
        )

    # location_sessions returns .none() when no location is active, so the counts
    # are 0 and the list is empty without a special case here. Both totals in one
    # aggregate — one round trip, not two (and none() short-circuits to 0/0 with
    # no query at all when there is no active location).
    scoped = location_sessions(request)
    stats = scoped.aggregate(
        active=Count('pk', filter=Q(status=CallSession.STATUS_IN_PROGRESS)),
        total=Count('pk'),
    )
    sessions = list(recent_location_sessions(request))

    # The URL Twilio must POST the inbound call to. Built from the public tunnel
    # base when set (what a real Twilio number needs), else the current host so
    # the page is still useful on a bare dev run.
    webhook_path = reverse('runtime:voice_webhook')  # noqa: F405
    base = (settings.TWILIO_WEBHOOK_BASE_URL or '').rstrip('/')  # noqa: F405
    webhook_url = f'{base}{webhook_path}' if base else request.build_absolute_uri(webhook_path)

    provider_mode = settings.PROVIDER_MODE  # noqa: F405

    return render(request, 'runtime/diagnostics.html', {  # noqa: F405
        'active_location': location,
        'setting': setting,
        'readiness_issues': setting.readiness_issues() if setting else [],
        'sessions': sessions,
        'stats': stats,
        'webhook_url': webhook_url,
        'stream_ws_url': media_stream_ws_url(),
        'provider_mode': provider_mode,
        'is_simulated': provider_mode != 'live',
    })
