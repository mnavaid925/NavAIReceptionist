"""View helpers shared by MORE THAN ONE sub-module of Module 5.

`_location_sessions` lived in `CallLogList/CallSessions.py` while 5.1 was the only
reader of call sessions. 5.2's transcript print page is the second reader, which
is the moment CLAUDE.md's Backend Package Structure rule 5 names for promoting a
helper out of its entity module — so it moved here rather than being reached into
across sub-module folders. 5.3's cost page and 5.4's recording page will import it
from here too.

Keeping the scoping in ONE place is the point: a second tenant+location filter
over `CallSession` is a second place for a cross-location leak to hide, and a call
session carries a transcript, so that leak is caller PII rather than a timestamp.
"""
from apps.calls.models import CallSession

__all__ = ['location_sessions']


def location_sessions(request):
    """Calls at the active location. Tenant AND location scoped, always.

    Returns nothing when no location is active — the safe direction, matching
    `scheduling.views._helpers.location_appointments`. A user who has not chosen
    a site sees an empty log and the global "choose a location" banner, never
    another site's calls.

    `select_related('contact', 'location')` because every row on the list renders
    the caller's display name and the site's timezone; without it a 25-row page
    costs 51 queries.

    `prefetch_related('booked_appointments__service')` for the same reason one
    level out: both the list and the detail page render what the call booked, and
    that is a REVERSE FK, which `select_related` cannot follow — and `service` is
    a FORWARD FK on the far side of it, so spanning only `booked_appointments`
    would still pay a query per booking for the service. Without it the list pays
    one extra query per row, the N+1 that `select_related` is there to prevent,
    reintroduced by a different relation. The transcript print page (5.2) never
    renders bookings and so carries this prefetch as one cheap, bounded, unused
    query — a deliberate trade for a single audited scoping surface over two.
    """
    if request.location is None:
        return CallSession.objects.none()
    return CallSession.objects.filter(
        tenant=request.tenant, location=request.location
    ).select_related('contact', 'location').prefetch_related(
        'booked_appointments__service',
    )
