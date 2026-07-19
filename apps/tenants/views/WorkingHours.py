"""Provider working hours (sub-module 1.4).

Edits `accounts.User.provider_hours` — a JSON dict keyed by location id — through
a validated formset. All the rules and the JSON shape live in
`apps.tenants.services`, so this module never touches the blob directly and
Module 4's availability search reads through the same helper.

Who may edit: a provider may set their own hours; owners and managers may set
anyone's. Both paths go through the same view and the same tenant scoping.
"""
import logging

from apps.accounts.models import User
from apps.tenants.forms import IntervalFormSet, build_interval_initial
from apps.tenants.models import Location
from apps.tenants.services import (
    WEEKDAYS,
    clear_provider_hours,
    get_provider_intervals,
    has_configured_hours,
    set_provider_hours,
    validate_provider_hours,
    weekly_summary,
)
from apps.tenants.views._common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

__all__ = ['provider_hours_view', 'provider_hours_report_view']


def _may_edit(request, provider):
    """Yourself, or anyone if you administer the business."""
    return provider.pk == request.user.pk or request.user.tier in MANAGEMENT_TIERS  # noqa: F405


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def provider_hours_view(request, pk, location_pk):
    """Edit one provider's hours at one location."""
    provider = get_object_or_404(  # noqa: F405
        User.objects.filter(tenant=request.tenant), pk=pk
    )
    location = get_object_or_404(  # noqa: F405
        Location.objects.filter(tenant=request.tenant), pk=location_pk
    )

    if not _may_edit(request, provider):
        messages.error(request, 'You can only edit your own working hours.')  # noqa: F405
        return redirect('accounts:dashboard')  # noqa: F405

    # Hours only mean something at a site the provider actually works at.
    assigned_ids = list(provider.assigned_locations().values_list('pk', flat=True))
    if location.pk not in assigned_ids:
        messages.error(  # noqa: F405
            request,
            f'{provider.display_name} is not assigned to {location.name}. '
            'Assign them first, then set their hours.',
        )
        return redirect('tenants:staff_locations')  # noqa: F405

    stored = get_provider_intervals(provider, location)

    if request.method == 'POST':
        if request.POST.get('action') == 'clear':
            clear_provider_hours(provider, location.pk)
            logger.info('Hours cleared for user_id=%s location_id=%s by user_id=%s',
                        provider.pk, location.pk, request.user.pk)
            messages.success(  # noqa: F405
                request,
                f'{provider.display_name} is now marked as not working at '
                f'{location.name}.',
            )
            return redirect('tenants:provider_hours',  # noqa: F405
                            pk=provider.pk, location_pk=location.pk)

        formset = IntervalFormSet(request.POST, prefix='intervals')
        if formset.is_valid():
            intervals = [
                {
                    'start_time': form.cleaned_data['start_time'],
                    'end_time': form.cleaned_data['end_time'],
                    'days': form.cleaned_data['days'],
                }
                for form in formset.forms
                if not form.is_blank
            ]
            errors = validate_provider_hours(
                intervals,
                location_id=location.pk,
                assigned_location_ids=assigned_ids,
            )
            if errors:
                for error in errors:
                    messages.error(request, error)  # noqa: F405
            else:
                set_provider_hours(provider, location.pk, intervals)
                logger.info('Hours saved for user_id=%s location_id=%s by user_id=%s',
                            provider.pk, location.pk, request.user.pk)
                messages.success(  # noqa: F405
                    request,
                    f"{provider.display_name}'s hours at {location.name} have "
                    'been saved.',
                )
                return redirect('tenants:provider_hours',  # noqa: F405
                                pk=provider.pk, location_pk=location.pk)
    else:
        formset = IntervalFormSet(
            initial=build_interval_initial(stored), prefix='intervals'
        )

    return render(request, 'tenants/hours/form.html', {  # noqa: F405
        'formset': formset,
        'provider': provider,
        'location': location,
        'weekdays': WEEKDAYS,
        'summary': weekly_summary(provider, location),
        'is_configured': has_configured_hours(provider, location.pk),
        'has_intervals': bool(stored),
        'other_locations': provider.assigned_locations().exclude(pk=location.pk),
        'is_self': provider.pk == request.user.pk,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
def provider_hours_report_view(request):
    """Every provider's hours across every site they work at.

    The answer to "who is bookable, where, and when" in one place — which is the
    question availability search will be asking on every call.
    """
    providers = (
        User.objects.filter(tenant=request.tenant, is_provider=True)
        .order_by('full_name', 'email')
    )

    rows = []
    for provider in providers:
        for location in provider.assigned_locations():
            rows.append({
                'provider': provider,
                'location': location,
                'summary': weekly_summary(provider, location),
                'intervals': get_provider_intervals(provider, location),
                'is_configured': has_configured_hours(provider, location.pk),
            })

    return render(request, 'tenants/hours/report.html', {  # noqa: F405
        'rows': rows,
        'weekdays': WEEKDAYS,
        'provider_count': providers.count(),
    })
