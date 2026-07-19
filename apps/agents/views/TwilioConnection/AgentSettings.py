"""Twilio connection views (sub-module 2.2).

NOTHING IN THIS MODULE MAY RENDER, LOG OR FLASH THE AUTH TOKEN. The views hand
the template `has_auth_token` (a boolean) and `masked_auth_token` (a tail hint)
and never the value. `messages.*` in particular is off limits for it — a message
body is serialised into the session store and outlives the page it was shown on.
"""
import logging

from apps.agents import telephony
from apps.agents.forms import TwilioConnectionForm
from apps.agents.views._common import *  # noqa: F401,F403
from apps.agents.views._helpers import get_setting_for_active_location, webhook_urls

logger = logging.getLogger(__name__)

__all__ = ['twilio_connection_view', 'twilio_connection_edit_view', 'twilio_check_view']


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
def twilio_connection_view(request):
    """Connection status and the webhook URLs to paste into Twilio."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    return render(request, 'agents/twilio/detail.html', {  # noqa: F405
        'setting': setting,
        'urls': webhook_urls(setting),
        'provider_mode': settings.PROVIDER_MODE,  # noqa: F405
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def twilio_connection_edit_view(request):
    """Edit the account SID, inbound number and (write-only) auth token."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    form = TwilioConnectionForm(request.POST or None, instance=setting, request=request)

    if request.method == 'POST' and form.is_valid():
        replaced = bool(form.cleaned_data.get('new_auth_token'))
        form.save()
        # Log THAT it changed, never the value, and never the SID either — a SID
        # plus a leaked token is a live Twilio account.
        logger.info('Twilio connection saved for location_id=%s token_replaced=%s '
                    'by user_id=%s', setting.location_id, replaced, request.user.pk)
        messages.success(  # noqa: F405
            request,
            'Twilio connection saved.' + (' The auth token was replaced.' if replaced else ''),
        )
        return redirect('agents:twilio_connection')  # noqa: F405

    return render(request, 'agents/twilio/form.html', {  # noqa: F405
        'form': form,
        'setting': setting,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def twilio_check_view(request):
    """Verify the credentials and number ownership. Places no call.

    POST-only: it reaches an external provider, so a link prefetcher or a crawler
    must not be able to trigger it.
    """
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    result = telephony.check_connection(setting)
    logger.info('Twilio check for location_id=%s ok=%s mode=%s',
                setting.location_id, result.ok, result.mode)

    if result.ok:
        messages.success(request, f'{result.summary}. {result.detail}')  # noqa: F405
    else:
        messages.error(request, f'{result.summary}. {result.detail}')  # noqa: F405
    return redirect('agents:twilio_connection')  # noqa: F405
