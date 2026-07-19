"""Resource CRUD (sub-module 4.2).

`Resource` is fully location-scoped, so unlike `Contact` (business-wide) and
`Service` (nullable location), EVERY queryset here carries both
`tenant=request.tenant` AND `location=request.location`. A treatment room at
Downtown must never be reachable, listable or editable from Uptown.
"""
import logging

from django.db.models import Q

from apps.scheduling.forms import ResourceForm
from apps.scheduling.models import Resource
from apps.scheduling.views._common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

__all__ = [
    'resource_list_view',
    'resource_create_view',
    'resource_detail_view',
    'resource_edit_view',
    'resource_delete_view',
]


def _location_resources(request):
    """The base queryset. Tenant AND location scoped, always.

    When there is no active location this returns nothing rather than everything
    — the safe direction. A user who has not chosen a site yet sees an empty list
    and the "choose a location" banner, not another site's rooms.
    """
    if request.location is None:
        return Resource.objects.none()
    return Resource.objects.filter(
        tenant=request.tenant, location=request.location
    )


@login_required  # noqa: F405
def resource_list_view(request):
    """The rooms, chairs and equipment at the active location."""
    queryset = _location_resources(request)

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(resource_number__icontains=search)
            | Q(description__icontains=search)
        )

    status = request.GET.get('status', '').strip()
    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'scheduling/catalog/resource/list.html', {  # noqa: F405
        'resources': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': page_obj.paginator.count,
    })


@login_required  # noqa: F405
def resource_detail_view(request, pk):
    """One resource."""
    obj = get_object_or_404(_location_resources(request), pk=pk)  # noqa: F405

    return render(request, 'scheduling/catalog/resource/detail.html', {  # noqa: F405
        'obj': obj,
        'appointment_count': _appointment_count(obj),
    })


def _appointment_count(resource):
    """How many bookings occupy this resource, or None while 4.3 is unbuilt."""
    try:
        from apps.scheduling.models import Appointment
    except ImportError:
        return None
    return Appointment.objects.filter(
        tenant_id=resource.tenant_id,
        location_id=resource.location_id,
        resource=resource,
    ).count()


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def resource_create_view(request):
    """Add a resource to the active location."""
    if request.location is None:
        messages.error(  # noqa: F405
            request, 'Choose a location before adding resources to it.'
        )
        return redirect('scheduling:resource_list')  # noqa: F405

    form = ResourceForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        logger.info(
            'Resource created resource_id=%s location_id=%s by user_id=%s',
            obj.pk, obj.location_id, request.user.pk,
        )
        messages.success(  # noqa: F405
            request,
            f'{obj.display_label} has been added to {request.location.name}.',
        )
        return redirect('scheduling:resource_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/catalog/resource/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def resource_edit_view(request, pk):
    """Edit a resource."""
    obj = get_object_or_404(_location_resources(request), pk=pk)  # noqa: F405
    form = ResourceForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Resource updated resource_id=%s by user_id=%s',
                    obj.pk, request.user.pk)
        messages.success(  # noqa: F405
            request, f'{obj.display_label} has been updated.'
        )
        return redirect('scheduling:resource_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/catalog/resource/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def resource_delete_view(request, pk):
    """Delete a resource, unless it has booking history.

    Same reasoning as the service delete: 4.3's `Appointment.resource` is
    `on_delete=SET_NULL`, so the database would let this through and silently
    blank the room on every past appointment. Refuse and point at `is_active`.
    """
    obj = get_object_or_404(_location_resources(request), pk=pk)  # noqa: F405
    label = obj.display_label

    booked = _appointment_count(obj)
    if booked:
        messages.error(  # noqa: F405
            request,
            f'{label} is on {booked} appointment{"s" if booked != 1 else ""} and '
            'cannot be deleted without blanking the room on all of them. Untick '
            '"Active" instead — it stops being offered and the history stays.',
        )
        return redirect('scheduling:resource_detail', pk=obj.pk)  # noqa: F405

    obj.delete()
    logger.info('Resource deleted resource_id=%s tenant_id=%s by user_id=%s',
                pk, request.tenant.pk, request.user.pk)
    messages.success(request, f'{label} has been deleted.')  # noqa: F405
    return redirect('scheduling:resource_list')  # noqa: F405
