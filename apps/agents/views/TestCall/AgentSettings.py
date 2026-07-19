"""Test call (sub-module 2.4).

**THE FORM TAKES NO DESTINATION NUMBER, AND THAT IS THE SECURITY DESIGN.**

An endpoint that dials an arbitrary number supplied by the client is a toll-fraud
gadget: any authenticated user — including a compromised staff account — could
make the tenant's Twilio account ring premium-rate numbers repeatedly, at the
tenant's expense. Accepting the number and validating it is not sufficient,
because "valid E.164" and "safe to dial" are different questions.

So the destination is derived server-side from the signed-in user's own profile
phone. You can only ever ring yourself, and the class of abuse is absent rather
than filtered.
"""
import logging

from django.core.cache import cache

from apps.agents import telephony
from apps.agents.views._common import *  # noqa: F401,F403
from apps.agents.views._helpers import get_setting_for_active_location

logger = logging.getLogger(__name__)

__all__ = ['test_call_view']

#: Even ringing your own phone costs money and is annoying. Bounded per location.
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 3600


def _rate_key(setting):
    return f'navai:testcall:{setting.tenant_id}:{setting.location_id}'


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def test_call_view(request):
    """Hear the agent before going live."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    issues = setting.readiness_issues()
    # The destination is READ, never posted.
    destination = (request.user.primary_phone or '').strip()

    if request.method == 'POST':
        key = _rate_key(setting)
        attempts = cache.get(key) or 0

        if issues:
            messages.error(  # noqa: F405
                request, 'Fix the setup issues below before placing a test call.'
            )
        elif not destination:
            messages.error(  # noqa: F405
                request,
                'Add a phone number to your profile first — the test call rings '
                'you, and it is never sent to a number typed into this page.',
            )
        elif attempts >= RATE_LIMIT:
            messages.error(  # noqa: F405
                request,
                f'That is {RATE_LIMIT} test calls in the last hour for this '
                'location. Try again later.',
            )
        else:
            if not cache.add(key, 1, RATE_WINDOW_SECONDS):
                try:
                    cache.incr(key)
                except ValueError:
                    pass

            result = telephony.place_test_call(setting, destination)
            logger.info('Test call for location_id=%s ok=%s mode=%s simulated=%s '
                        'by user_id=%s', setting.location_id, result.ok,
                        result.mode, result.simulated, request.user.pk)
            if result.ok:
                messages.success(request, f'{result.summary}. {result.detail}')  # noqa: F405
            else:
                messages.error(request, f'{result.summary}. {result.detail}')  # noqa: F405

        return redirect('agents:test_call')  # noqa: F405

    return render(request, 'agents/testcall/index.html', {  # noqa: F405
        'setting': setting,
        'issues': issues,
        'destination': destination,
        'provider_mode': settings.PROVIDER_MODE,  # noqa: F405
        'is_simulated': settings.PROVIDER_MODE != 'live',  # noqa: F405
        'attempts_left': max(0, RATE_LIMIT - (cache.get(_rate_key(setting)) or 0)),
    })
