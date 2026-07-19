"""Service catalogue CRUD (sub-module 4.2).

`Service` is tenant-scoped with a NULLABLE location, so the queryset here filters
on `tenant` and applies location as an ADDITIVE filter, never as a hard
`location=request.location`. A service offered at every site must stay visible
from every site — filtering it out is the obvious bug in this shape, and the one
this module goes out of its way to avoid.
"""
import logging

from django.db.models import Q

from apps.scheduling.forms import ServiceForm
from apps.scheduling.models import Service
from apps.scheduling.views._common import *  # noqa: F401,F403
from apps.scheduling.views._helpers import save_or_report_conflict

logger = logging.getLogger(__name__)

#: Shown when two writers race for the same name. `ServiceForm.clean` catches the
#: ordinary case; this covers the window between that check and the insert.
_NAME_CONFLICT = (
    'Someone just added a service with that name at the same location. '
    'Give this one a different name.'
)

__all__ = [
    'service_list_view',
    'service_create_view',
    'service_detail_view',
    'service_edit_view',
    'service_delete_view',
]


def _tenant_services(request):
    """The base queryset: everything this business offers, at any of its sites.

    Location is NOT applied here. Each view decides how to treat it, because
    "which services exist" and "which services can be booked right here" are
    different questions and only the second one is location-filtered.
    """
    return Service.objects.filter(tenant=request.tenant).select_related('location')


def _bookable_here(queryset, location):
    """Narrow to what can actually be booked at `location`.

    ADDITIVE: this-location services OR all-location ones. Writing
    `filter(location=location)` instead would silently hide every business-wide
    service, which is the majority of most catalogues.
    """
    if location is None:
        return queryset
    return queryset.filter(Q(location=location) | Q(location__isnull=True))


@login_required  # noqa: F405
def service_list_view(request):
    """The catalogue, with search and location/status filters."""
    queryset = _tenant_services(request)

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(description__icontains=search)
        )

    # 'here' = bookable at the active location (this-site + all-sites).
    # 'all_locations' = only the business-wide ones.
    # A pk = that specific site's own services.
    # Anything else degrades to no filter.
    scope = request.GET.get('scope', '').strip()
    if scope == 'here':
        queryset = _bookable_here(queryset, request.location)
    elif scope == 'all_locations':
        queryset = queryset.filter(location__isnull=True)
    elif scope.isdecimal():
        # `isdecimal`, NOT `isdigit`: `isdigit` is True for characters like '²'
        # and fullwidth '１' that `int()` then refuses, so an `isdigit` guard
        # turns `?scope=²` into an unhandled ValueError — a 500 from a query
        # string, which the project's filter rule explicitly forbids.
        #
        # Authorise the id against the user's own assignments — a raw pk from a
        # query string is never trusted, even for a read-only filter.
        allowed = request.user.assigned_locations().filter(pk=int(scope)).first()
        if allowed is not None:
            queryset = queryset.filter(location=allowed)

    status = request.GET.get('status', '').strip()
    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'scheduling/catalog/service/list.html', {  # noqa: F405
        'services': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': page_obj.paginator.count,
        'locations': request.user.assigned_locations(),
    })


@login_required  # noqa: F405
def service_detail_view(request, pk):
    """One service."""
    obj = get_object_or_404(_tenant_services(request), pk=pk)  # noqa: F405

    return render(request, 'scheduling/catalog/service/detail.html', {  # noqa: F405
        'obj': obj,
        'bookable_here': obj.is_offered_at(request.location),
        'appointment_count': _appointment_count(obj),
    })


def _appointment_count(service):
    """How many bookings reference this service, or None while 4.3 is unbuilt.

    Import-guarded: `Appointment` does not exist yet and a hard import would make
    the whole catalogue un-importable until it does.
    """
    try:
        from apps.scheduling.models import Appointment
    except ImportError:
        return None
    return Appointment.objects.filter(
        tenant_id=service.tenant_id, service=service
    ).count()


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def service_create_view(request):
    """Add a service."""
    form = ServiceForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = save_or_report_conflict(form, _NAME_CONFLICT)
        if obj is not None:
            logger.info('Service created service_id=%s tenant_id=%s by user_id=%s',
                        obj.pk, request.tenant.pk, request.user.pk)
            messages.success(  # noqa: F405
                request, f'{obj.name} has been added to your catalogue.'
            )
            return redirect('scheduling:service_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/catalog/service/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def service_edit_view(request, pk):
    """Edit a service. This is also how an inactive one is brought back."""
    obj = get_object_or_404(_tenant_services(request), pk=pk)  # noqa: F405

    # READING the catalogue is business-wide; WRITING to a site-pinned service is
    # not. `duration_minutes`, `is_active` and `requires_resource` decide what the
    # agent offers and books at that site, so editing them from a branch you are
    # not assigned to is a change to someone else's operation. An all-locations
    # service (`location_id is None`) belongs to everyone and stays editable.
    if obj.location_id and not request.user.assigned_locations().filter(
        pk=obj.location_id
    ).exists():
        messages.error(  # noqa: F405
            request,
            f'{obj.name} is offered only at {obj.location.name}, and you are not '
            'assigned to that location. Ask someone who works there to change it.',
        )
        return redirect('scheduling:service_detail', pk=obj.pk)  # noqa: F405

    form = ServiceForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        if save_or_report_conflict(form, _NAME_CONFLICT) is not None:
            logger.info('Service updated service_id=%s by user_id=%s',
                        obj.pk, request.user.pk)
            messages.success(request, f'{obj.name} has been updated.')  # noqa: F405
            return redirect('scheduling:service_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/catalog/service/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def service_delete_view(request, pk):
    """Delete a service, unless it has booking history.

    4.3's `Appointment.service` is `on_delete=SET_NULL`, so the database would
    happily let this through and quietly orphan every past booking's service —
    a completed appointment would render with a blank service forever, with no
    error anywhere. The guard is therefore at the view, not the FK: refuse, and
    point at the `is_active` toggle, which removes the service from what the
    agent offers while keeping the history readable.
    """
    obj = get_object_or_404(_tenant_services(request), pk=pk)  # noqa: F405
    label = obj.name

    # Same rule as the edit view: a site-pinned service is that site's to remove.
    if obj.location_id and not request.user.assigned_locations().filter(
        pk=obj.location_id
    ).exists():
        messages.error(  # noqa: F405
            request,
            f'{label} is offered only at {obj.location.name}, and you are not '
            'assigned to that location.',
        )
        return redirect('scheduling:service_detail', pk=obj.pk)  # noqa: F405

    booked = _appointment_count(obj)
    if booked:
        messages.error(  # noqa: F405
            request,
            f'{label} is on {booked} appointment{"s" if booked != 1 else ""} and '
            'cannot be deleted without blanking the service on all of them. '
            'Untick "Active" instead — the agent stops offering it and the '
            'history stays readable.',
        )
        return redirect('scheduling:service_detail', pk=obj.pk)  # noqa: F405

    obj.delete()
    logger.info('Service deleted service_id=%s tenant_id=%s by user_id=%s',
                pk, request.tenant.pk, request.user.pk)
    messages.success(request, f'{label} has been deleted.')  # noqa: F405
    return redirect('scheduling:service_list')  # noqa: F405
