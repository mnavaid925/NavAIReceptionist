"""Staff-to-location assignment (sub-module 1.3).

ONE matrix page rather than two CRUD screens: rows are the business's users,
columns are its active sites, and each checkbox is a `accounts.UserLocation` row.
"Assign from either side" is served by the same page via `?user=` / `?location=`
highlighting, not by a second implementation that could drift.

SECURITY. `UserLocation` is the cross-location IDOR boundary — it is what
`ActiveLocationMiddleware` re-validates against on every request and what
`switch_location_view` filters a posted id through. So this view never trusts a
posted id as an identifier: every user id and location id in the submission is
intersected with the tenant's own querysets before anything is written.
"""
import logging

from django.db.models import Q

from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location
from apps.tenants.views._common import *  # noqa: F401,F403
from apps.tenants.views._helpers import (
    future_appointment_count,
    remaining_assignment_count,
)

logger = logging.getLogger(__name__)

__all__ = ['staff_locations_view', 'toggle_provider_view']


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def staff_locations_view(request):
    """The assignment matrix."""
    users = list(
        User.objects.filter(tenant=request.tenant)
        .order_by('full_name', 'email')
    )
    locations = list(
        Location.objects.filter(tenant=request.tenant, is_active=True)
        .order_by('name')
    )

    if request.method == 'POST':
        return _save_matrix(request, users, locations)

    assigned = set(
        UserLocation.objects.filter(tenant=request.tenant)
        .values_list('user_id', 'location_id')
    )

    # Pre-computed in the view: a template cannot test set membership on a pair,
    # and faking it with nested loops is how a matrix ends up one column off.
    rows = [
        {
            'user': user,
            'cells': [
                {'location': location, 'checked': (user.pk, location.pk) in assigned}
                for location in locations
            ],
            'assigned_count': sum(
                1 for location in locations if (user.pk, location.pk) in assigned
            ),
        }
        for user in users
    ]

    return render(request, 'tenants/staff/matrix.html', {  # noqa: F405
        'rows': rows,
        'locations': locations,
        'highlight_user': _int_or_none(request.GET.get('user')),
        'highlight_location': _int_or_none(request.GET.get('location')),
        'confirm_required': request.GET.get('confirm') == '1',
    })


def _int_or_none(raw):
    """Parse a query-string id defensively — junk must not raise."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _save_matrix(request, users, locations):
    """Diff the submitted checkboxes against what is stored, and apply.

    A diff rather than delete-all-then-recreate: recreating would churn every row
    on every save and briefly leave users with no assignment at all, which
    `ActiveLocationMiddleware` would observe.
    """
    valid_user_ids = {user.pk for user in users}
    valid_location_ids = {location.pk for location in locations}

    # `assign` arrives as "<user_pk>:<location_pk>" pairs. Both halves are
    # intersected with the tenant's own ids, so a forged pair naming another
    # business's user or site matches nothing and is silently dropped.
    submitted = set()
    for raw in request.POST.getlist('assign'):
        parts = raw.split(':')
        if len(parts) != 2:
            continue
        user_id, location_id = _int_or_none(parts[0]), _int_or_none(parts[1])
        if user_id in valid_user_ids and location_id in valid_location_ids:
            submitted.add((user_id, location_id))

    existing = set(
        UserLocation.objects.filter(
            tenant=request.tenant,
            user_id__in=valid_user_ids,
            location_id__in=valid_location_ids,
        ).values_list('user_id', 'location_id')
    )

    to_add = submitted - existing
    to_remove = existing - submitted

    users_by_id = {user.pk: user for user in users}

    # Guard: would any removal leave someone with no site at all?
    if to_remove and request.POST.get('confirm') != '1':
        stranded = []
        for user_id in {user_id for user_id, _ in to_remove}:
            removing = [loc_id for u_id, loc_id in to_remove if u_id == user_id]
            if remaining_assignment_count(
                users_by_id[user_id], excluding_location_ids=removing
            ) == 0:
                stranded.append(users_by_id[user_id])

        if stranded:
            names = ', '.join(user.display_name for user in stranded)
            messages.warning(  # noqa: F405
                request,
                f'{names} would be left with no location and unable to work '
                'anywhere. Submit again to confirm.',
            )
            return redirect(f'{reverse("tenants:staff_locations")}?confirm=1')  # noqa: F405

    for user_id, location_id in to_add:
        UserLocation.objects.get_or_create(
            user_id=user_id, location_id=location_id,
            defaults={'tenant': request.tenant},
        )

    if to_remove:
        # An OR of exact pairs. Two separate __in filters would form a cross
        # product and delete assignments nobody touched.
        pair_filter = Q()
        for user_id, location_id in to_remove:
            pair_filter |= Q(user_id=user_id, location_id=location_id)
        UserLocation.objects.filter(tenant=request.tenant).filter(pair_filter).delete()

    orphaned = sum(
        future_appointment_count(
            user=users_by_id[user_id],
            location=next((l for l in locations if l.pk == location_id), None),
        )
        for user_id, location_id in to_remove
    )

    logger.info('Assignments updated tenant_id=%s added=%d removed=%d by user_id=%s',
                request.tenant.pk, len(to_add), len(to_remove), request.user.pk)

    if to_add or to_remove:
        messages.success(  # noqa: F405
            request,
            f'Assignments saved — {len(to_add)} added, {len(to_remove)} removed.',
        )
    else:
        messages.info(request, 'No assignment changes to save.')  # noqa: F405

    if orphaned:
        messages.warning(  # noqa: F405
            request,
            f'{orphaned} future appointment{"s" if orphaned != 1 else ""} were '
            'booked with a provider who no longer works at that location.',
        )

    return redirect('tenants:staff_locations')  # noqa: F405


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def toggle_provider_view(request, pk):
    """Flip a user's bookable-provider flag from the matrix.

    A provider IS the bookable clinician — there is no separate provider entity —
    so this one boolean is what makes someone appear as a booking target.
    """
    user = get_object_or_404(  # noqa: F405
        User.objects.filter(tenant=request.tenant), pk=pk
    )
    user.is_provider = not user.is_provider
    user.save(update_fields=['is_provider', 'updated_at'])

    logger.info('Provider flag set to %s for user_id=%s by user_id=%s',
                user.is_provider, user.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        f'{user.display_name} is {"now" if user.is_provider else "no longer"} '
        'bookable.',
    )
    return redirect(safe_redirect_target(  # noqa: F405
        request, default='tenants:staff_locations'
    ))
