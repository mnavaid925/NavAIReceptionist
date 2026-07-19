"""Location directory CRUD (sub-module 1.2).

`tenants.Location` is tenant-scoped but NOT location-scoped — it IS the location
— so every queryset here filters on `tenant=request.tenant` and nothing else.
Adding `location=request.location` would mean a site could only ever see itself.
"""
import logging

from django.db.models import Count, Q

from apps.tenants.forms import LocationForm
from apps.tenants.models import Location
from apps.tenants.views._common import *  # noqa: F401,F403
from apps.tenants.views._helpers import (
    future_appointment_count,
    users_left_without_location,
)

logger = logging.getLogger(__name__)

__all__ = [
    'location_list_view',
    'location_create_view',
    'location_detail_view',
    'location_edit_view',
    'location_delete_view',
]


def _tenant_locations(request):
    """The base queryset. Tenant-scoped, always."""
    return Location.objects.filter(tenant=request.tenant)


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
def location_list_view(request):
    """List the business's sites, with search and an active/inactive filter."""
    queryset = _tenant_locations(request)

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(slug__icontains=search)
            | Q(city__icontains=search)
            | Q(state__icontains=search)
            | Q(postal_code__icontains=search)
            | Q(phone__icontains=search)
        )

    # 'active' / 'inactive' map onto the boolean; anything else means no filter.
    status = request.GET.get('status', '').strip()
    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)

    # One extra query for the whole page instead of one per row in the template.
    queryset = queryset.annotate(staff_count=Count('user_assignments', distinct=True))
    queryset = queryset.order_by('name')

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'tenants/location/list.html', {  # noqa: F405
        'locations': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': queryset.count(),
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
def location_detail_view(request, pk):
    """One site: address, timezone, staff, and its agent configuration."""
    obj = get_object_or_404(_tenant_locations(request), pk=pk)  # noqa: F405

    from apps.accounts.models import UserLocation

    assignments = (
        UserLocation.objects.filter(tenant=request.tenant, location=obj)
        .select_related('user')
        .order_by('user__full_name', 'user__email')
    )

    return render(request, 'tenants/location/detail.html', {  # noqa: F405
        'obj': obj,
        'assignments': assignments,
        'agent_setting': _agent_setting_for(obj),
        'is_active_location': (
            request.location is not None and request.location.pk == obj.pk
        ),
    })


def _agent_setting_for(location):
    """This location's agent configuration, or None while Module 2 is unbuilt.

    Import-guarded rather than assumed: `apps.agents` does not exist yet, and a
    hard import would make the whole location directory un-importable until it
    does. When Module 2 lands this starts returning real rows with no edit here.
    """
    try:
        from apps.agents.models import AgentSetting
    except (ImportError, ModuleNotFoundError):
        return None
    return AgentSetting.objects.filter(
        tenant_id=location.tenant_id, location=location
    ).first()


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def location_create_view(request):
    """Add a site."""
    form = LocationForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        logger.info('Location created location_id=%s tenant_id=%s by user_id=%s',
                    obj.pk, request.tenant.pk, request.user.pk)
        messages.success(  # noqa: F405
            request,
            f'{obj.name} has been added. Assign staff to it so they can work there.',
        )
        return redirect('tenants:location_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'tenants/location/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def location_edit_view(request, pk):
    """Edit a site. This is also how a deactivated site is brought back."""
    obj = get_object_or_404(_tenant_locations(request), pk=pk)  # noqa: F405
    form = LocationForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Location updated location_id=%s by user_id=%s',
                    obj.pk, request.user.pk)
        messages.success(request, f'{obj.name} has been updated.')  # noqa: F405
        return redirect('tenants:location_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'tenants/location/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def location_delete_view(request, pk):
    """Deactivate a site. This never deletes the row.

    Call logs, appointments and callback requests all carry a `location` FK with
    `on_delete=CASCADE`, so deleting a site would take its entire history with it.
    Deactivation keeps every record readable while removing the site from the
    switcher — `User.assigned_locations()` filters `is_active=True`, so nobody can
    keep working in it.
    """
    obj = get_object_or_404(_tenant_locations(request), pk=pk)  # noqa: F405

    if not obj.is_active:
        messages.info(request, f'{obj.name} is already inactive.')  # noqa: F405
        return redirect('tenants:location_detail', pk=obj.pk)  # noqa: F405

    if _tenant_locations(request).filter(is_active=True).count() <= 1:
        messages.error(  # noqa: F405
            request,
            'This is the only active location. Add another before deactivating it, '
            'or the business would have nowhere to take bookings.',
        )
        return redirect('tenants:location_detail', pk=obj.pk)  # noqa: F405

    stranded = users_left_without_location(request.tenant, obj)
    pending = future_appointment_count(location=obj)

    obj.is_active = False
    obj.save(update_fields=['is_active', 'updated_at'])

    # If the acting user was working in this site, drop it from their session
    # rather than leaving a stale id the middleware would silently discard.
    if request.location is not None and request.location.pk == obj.pk:
        from apps.accounts.views._helpers import set_active_location

        set_active_location(request, None)

    logger.info('Location deactivated location_id=%s by user_id=%s',
                obj.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        f'{obj.name} has been deactivated. Its history is unchanged.',
    )
    if stranded:
        names = ', '.join(user.display_name for user in stranded[:5])
        more = f' and {len(stranded) - 5} more' if len(stranded) > 5 else ''
        messages.warning(  # noqa: F405
            request,
            f'{names}{more} had no other location and can no longer work anywhere. '
            'Assign them to another site.',
        )
    if pending:
        messages.warning(  # noqa: F405
            request,
            f'{pending} future appointment{"s" if pending != 1 else ""} at this '
            'location still need rescheduling.',
        )
    return redirect('tenants:location_list')  # noqa: F405
