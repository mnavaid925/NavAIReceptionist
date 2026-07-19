"""Transfer settings views (sub-module 2.3)."""
import logging

from apps.agents.forms import TransferSettingsForm
from apps.agents.services import (
    DEFAULT_TRANSFER_KEYWORDS,
    is_transfer_available,
    next_transfer_window,
)
from apps.agents.views._common import *  # noqa: F401,F403
from apps.agents.views._helpers import get_setting_for_active_location

logger = logging.getLogger(__name__)

__all__ = ['transfer_settings_view', 'transfer_settings_edit_view']


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
def transfer_settings_view(request):
    """When a caller can reach a human, and where they land."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    return render(request, 'agents/transfer/detail.html', {  # noqa: F405
        'setting': setting,
        # Evaluated now, in the configured timezone — this is the same helper the
        # runtime calls, so the page cannot disagree with the live agent.
        'available_now': is_transfer_available(setting),
        'reopens_at': next_transfer_window(setting),
        'builtin_keywords': DEFAULT_TRANSFER_KEYWORDS,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def transfer_settings_edit_view(request):
    """Edit the destinations, weekly windows and escalation phrases."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    form = TransferSettingsForm(request.POST or None, instance=setting, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Transfer settings saved for location_id=%s by user_id=%s',
                    setting.location_id, request.user.pk)
        messages.success(request, 'Transfer settings saved.')  # noqa: F405
        return redirect('agents:transfer_settings')  # noqa: F405

    return render(request, 'agents/transfer/form.html', {  # noqa: F405
        'form': form,
        'setting': setting,
        'builtin_keywords': DEFAULT_TRANSFER_KEYWORDS,
    })
