"""The active-location switcher (sub-module 0.4).

THIS VIEW IS THE CROSS-LOCATION IDOR BOUNDARY. Everything downstream — the
calendar, the call log, resources, agent settings — filters on
`location=request.location`, and this is the one place a user chooses what that
resolves to. If it ever trusted the posted id, every location-scoped page in the
product would inherit the hole.

So the posted value is never used as an identifier. It is used as a FILTER over
`request.user.assigned_locations()`, which is itself derived from the user's
`accounts.UserLocation` rows. An id belonging to another tenant, or to a
same-tenant site the user is not assigned to, simply matches nothing.

`ActiveLocationMiddleware` re-validates the stored id on every subsequent request
too, so even a session written some other way cannot survive.
"""
import logging

from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._helpers import safe_redirect_target, set_active_location

logger = logging.getLogger(__name__)

__all__ = ['switch_location_view', 'my_locations_view']


@login_required  # noqa: F405
def my_locations_view(request):
    """The Assigned-Location List — every site this user may work in.

    The switcher in the topbar changes the active site from wherever you are; this
    page is the place that answers "which sites am I allowed into, and which one am
    I in right now?" — which is not otherwise visible anywhere.

    Read-only over `UserLocation`: assigning a user to a site is Module 1.3, not
    something anyone does to themselves here.
    """
    return render(request, 'accounts/location/list.html', {  # noqa: F405
        'assigned_locations': request.user.assigned_locations(),
    })


@login_required  # noqa: F405
@require_POST  # noqa: F405
def switch_location_view(request):
    """Set the session's active location.

    POST-only: it mutates session state, so a link prefetcher, a crawler or a
    browser accelerator must not be able to trigger it.
    """
    raw_id = (request.POST.get('location') or '').strip()
    target = safe_redirect_target(request)

    if not raw_id:
        messages.error(request, 'Choose a location to switch to.')  # noqa: F405
        return redirect(target)  # noqa: F405

    # `.isdigit()` first: feeding a non-numeric string straight to a pk filter
    # raises ValueError, which would turn a junk POST into a 500.
    if not raw_id.isdigit():
        logger.warning('Rejected non-numeric location switch by user_id=%s',
                       request.user.pk)
        messages.error(request, 'That location is not available to you.')  # noqa: F405
        return redirect(target)  # noqa: F405

    # The authorization step. Not `Location.objects.get(pk=raw_id)` — that would
    # reach any location in the database.
    location = request.user.assigned_locations().filter(pk=int(raw_id)).first()

    if location is None:
        # Covers another tenant's location, a same-tenant location this user has no
        # UserLocation row for, a deleted location, and a stale id. All refused
        # identically, and none of them reveals whether the location exists.
        logger.warning(
            'Refused location switch to id=%s for user_id=%s tenant_id=%s',
            raw_id, request.user.pk, request.user.tenant_id,
        )
        messages.error(request, 'That location is not available to you.')  # noqa: F405
        return redirect(target)  # noqa: F405

    set_active_location(request, location)
    logger.info('Active location set to location_id=%s for user_id=%s',
                location.pk, request.user.pk)
    messages.success(request, f'Now working in {location.name}.')  # noqa: F405
    return redirect(target)  # noqa: F405
