"""Private view helpers shared across Module 1's sub-modules."""
import logging

logger = logging.getLogger(__name__)

__all__ = [
    'future_appointment_count',
    'remaining_assignment_count',
    'users_left_without_location',
]


def future_appointment_count(user=None, location=None):
    """How many future appointments would be orphaned by removing an assignment.

    `scheduling.Appointment` does not exist until Module 4, so today this returns
    0 — and that is deliberate rather than a stub to remember. The import is
    guarded so THE CALL SITE NEVER CHANGES: when Module 4 lands, this function
    starts returning real numbers and every guard that calls it tightens
    automatically, with no edit to the views.
    """
    try:
        from apps.scheduling.models import Appointment
    except (ImportError, ModuleNotFoundError):
        return 0

    from django.utils import timezone

    queryset = Appointment.objects.filter(
        start_at__gte=timezone.now(),
        status__in=('scheduled', 'confirmed'),
    )
    if user is not None:
        queryset = queryset.filter(provider=user)
    if location is not None:
        queryset = queryset.filter(location=location)
    return queryset.count()


def remaining_assignment_count(user, excluding_location_ids=()):
    """Assignments this user would have left if the given ones were removed.

    Zero means they would be locked out of every site: `request.location` would
    resolve to None on their next request and every location-scoped page would
    show them nothing.
    """
    from apps.accounts.models import UserLocation

    excluded = {int(pk) for pk in excluding_location_ids}
    queryset = UserLocation.objects.filter(user=user)
    if excluded:
        queryset = queryset.exclude(location_id__in=excluded)
    return queryset.count()


def users_left_without_location(tenant, location):
    """Users whose ONLY assignment is `location`.

    Used to warn before deactivating a site — the people who would silently lose
    all access are exactly the ones nobody thinks about at the time.
    """
    from apps.accounts.models import UserLocation

    user_ids = UserLocation.objects.filter(
        tenant=tenant, location=location
    ).values_list('user_id', flat=True)

    stranded = []
    for user_id in user_ids:
        others = UserLocation.objects.filter(user_id=user_id).exclude(
            location=location
        ).count()
        if others == 0:
            stranded.append(user_id)

    if not stranded:
        return []

    from apps.accounts.models import User

    return list(User.objects.filter(pk__in=stranded).order_by('full_name', 'email'))
