"""Agent setup views (sub-module 2.1)."""
import logging

from apps.agents.forms import AgentConfigForm
from apps.agents.services import build_runtime_context, render_template, sample_runtime_context
from apps.agents.views._common import *  # noqa: F401,F403
from apps.agents.views._helpers import get_setting_for_active_location

logger = logging.getLogger(__name__)

__all__ = ['agent_setup_view', 'agent_setup_edit_view', 'agent_preview_view']


@login_required  # noqa: F405
def agent_setup_view(request):
    """The overview: what this location's agent will say, and what is missing."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    context = build_runtime_context(setting)
    return render(request, 'agents/setup/detail.html', {  # noqa: F405
        'setting': setting,
        'issues': setting.readiness_issues(),
        'rendered_greeting': render_template(setting.greeting, context),
        'variable_count': len(setting.variables or {}),
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def agent_setup_edit_view(request):
    """Edit the greeting, prompt, variables and voice mode."""
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    form = AgentConfigForm(request.POST or None, instance=setting, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Agent config saved for location_id=%s by user_id=%s',
                    setting.location_id, request.user.pk)
        messages.success(request, 'Agent configuration saved.')  # noqa: F405
        return redirect('agents:agent_setup')  # noqa: F405

    return render(request, 'agents/setup/form.html', {  # noqa: F405
        'form': form,
        'setting': setting,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
def agent_preview_view(request):
    """Show the greeting and prompt as the caller's session would render them.

    Uses the same `render_template` the runtime will, against a representative
    context — so what is previewed here is what a caller hears, not an
    approximation drawn by a different code path.
    """
    setting, redirect_response = get_setting_for_active_location(request)
    if redirect_response:
        return redirect_response

    context = sample_runtime_context(setting)
    return render(request, 'agents/setup/preview.html', {  # noqa: F405
        'setting': setting,
        'context': sorted(context.items()),
        'rendered_greeting': render_template(setting.greeting, context),
        'rendered_prompt': render_template(setting.prompt_text, context),
    })
