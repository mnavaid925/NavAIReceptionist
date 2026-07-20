"""View helpers shared by MORE THAN ONE sub-module of Module 4.

Helpers used by a single entity stay in that entity's own view module. These are
here because 4.4's calendar reads exactly the same appointments, columns and
query parameters that 4.3's bookings pages do.

**`parse_local_date` has a cross-app consumer**: Module 5's call-log list
(`apps/calls/views/CallLogList/CallSessions.py`) imports it for its own date
filter. That is deliberate — the clamping in `MIN_QUERY_DATE`/`MAX_QUERY_DATE`
below exists to stop `?date=9999-12-31` reaching arithmetic that raises
`OverflowError`, and a second copy in `apps/calls` would be one more place for
that bound to rot out of sync. Anything moved or renamed in here is therefore
not private to this app; check `apps/calls` before changing it.
"""
import logging
from datetime import date, datetime

from django.db import IntegrityError
from django.db.models import Q

logger = logging.getLogger(__name__)

__all__ = [
    'save_or_report_conflict',
    'location_appointments',
    'parse_local_date',
    'authorised_pk',
    'bookable_resources',
    'bookable_providers',
    'bookable_services',
]

#: Outer bounds for any date parsed from a query string.
#:
#: `local_day_bounds_utc` does `day + timedelta(days=1)`, and `date.max` plus a
#: day raises `OverflowError` — an uncaught 500 from `?date=9999-12-31`. Clamping
#: at parse time fixes it for every caller at once, including 4.3's `?from=`/`?to=`
#: filters, which have the same latent hole.
MIN_QUERY_DATE = date(1900, 1, 1)
MAX_QUERY_DATE = date(2200, 1, 1)


def location_appointments(request):
    """Appointments at the active location. Tenant AND location scoped, always.

    Returns nothing when no location is active — the safe direction. A user who
    has not chosen a site sees an empty page and the global "choose a location"
    banner, never another site's diary.
    """
    from apps.scheduling.models import Appointment

    if request.location is None:
        return Appointment.objects.none()
    return Appointment.objects.filter(
        tenant=request.tenant, location=request.location
    ).select_related('contact', 'service', 'resource', 'provider', 'location')


def parse_local_date(raw):
    """Parse `YYYY-MM-DD` from a query string, or None. Never raises.

    Out-of-range dates return None rather than a `date` no downstream arithmetic
    can survive — see `MIN_QUERY_DATE`.
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    if not (MIN_QUERY_DATE <= parsed <= MAX_QUERY_DATE):
        return None
    return parsed


def authorised_pk(model_queryset, raw):
    """Resolve a pk from a query string against an ALREADY-SCOPED queryset.

    `.isdecimal()`, not `.isdigit()`: `isdigit()` is True for characters such as
    '²' and fullwidth '１' that `int()` then refuses, turning a junk filter into a
    500. Returns None for anything not found, so a foreign pk degrades to
    "no filter" rather than leaking or raising.
    """
    raw = (raw or '').strip()
    if not raw.isdecimal():
        return None
    return model_queryset.filter(pk=int(raw)).first()


def bookable_resources(request):
    """ACTIVE resources at the active location.

    Named `bookable_` rather than `location_` on purpose: 4.2's own
    `views/ServicesResources/Resources.py::_location_resources` deliberately does
    NOT filter `is_active`, because the resource CRUD list must still show
    deactivated rooms. Two different questions, so two different names — a shared
    helper under the generic name would eventually be imported into the CRUD list
    and silently hide every inactive room.
    """
    from apps.scheduling.models import Resource

    if request.location is None:
        return Resource.objects.none()
    return Resource.objects.filter(
        tenant=request.tenant, location=request.location, is_active=True
    ).order_by('display_order', 'name')


def bookable_providers(request):
    """ACTIVE providers assigned to the active location.

    `user_locations` is the accessor from User to UserLocation (`user_assignments`
    is the one from Location — getting them backwards is a silent FieldError).
    `status=STATUS_ACTIVE` matters: a suspended user cannot be booked, so they
    must not head a calendar column either.
    """
    from apps.accounts.models import User

    if request.location is None:
        return User.objects.none()
    return User.objects.filter(
        tenant=request.tenant,
        is_provider=True,
        status=User.STATUS_ACTIVE,
        user_locations__location=request.location,
    ).distinct().order_by('full_name', 'email')


def bookable_services(request):
    """Services bookable at the active location — this site's PLUS all-location.

    ADDITIVE, never `filter(location=...)`, which would hide every business-wide
    service — most of a typical catalogue.
    """
    from apps.scheduling.models import Service

    if request.tenant is None:
        return Service.objects.none()
    queryset = Service.objects.filter(tenant=request.tenant, is_active=True)
    if request.location is not None:
        queryset = queryset.filter(
            Q(location=request.location) | Q(location__isnull=True)
        )
    return queryset.order_by('display_order', 'name')


def save_or_report_conflict(form, message):
    """`form.save()`, converting a unique-constraint collision into a form error.

    Returns the saved instance, or `None` if the insert lost a race.

    Several forms in this module hand-enforce a uniqueness rule that Django
    cannot check itself, because part of the constraint's field tuple is excluded
    from the form and stamped from the request instead (`Resource`'s
    `(location, name)` is the canonical case — `location` is never rendered, so
    Django skips the constraint entirely).

    A hand-rolled `.exists()` check is check-then-act: two concurrent submissions,
    or one impatient double-click, can both pass validation and the second insert
    then raises a raw `IntegrityError` — a 500 on exactly the path the manual
    check was written to keep friendly. The `.exists()` check still earns its
    place (it produces a good message in the overwhelmingly common single-writer
    case); this closes the narrow window behind it.

    Deliberately catches `IntegrityError` broadly rather than parsing the driver's
    message for a constraint name: those strings differ between MySQL, MariaDB and
    SQLite, and a parser that silently stops matching would turn this guard back
    into the 500 it exists to prevent.
    """
    try:
        return form.save()
    except IntegrityError:
        # `exception`, not `info`: this catch is deliberately broad, so it can
        # also swallow a FK or NOT NULL violation caused by a bug elsewhere and
        # show it to the user as a name clash. Without the traceback in the log,
        # that misdirection is invisible during triage.
        logger.exception(
            'Save failed on an integrity error form=%s', type(form).__name__
        )
        form.add_error(None, message)
        return None
