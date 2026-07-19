"""Private view helpers shared by more than one sub-module of `accounts`."""
from apps.accounts.middleware import ACTIVE_LOCATION_SESSION_KEY


def get_client_ip(request):
    """Best-effort client IP, used as a throttle key.

    `X-Forwarded-For` is only meaningful behind a proxy that sets it. Treat this as
    a rate-limiting hint, never as an authorization input.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def set_active_location(request, location):
    """Write the active location into the session.

    The CALLER is responsible for having proved the user is assigned to this
    location — every caller resolves it out of `user.assigned_locations()`, never
    out of a raw id from a form or a URL. `ActiveLocationMiddleware` re-validates
    it on the next request regardless, so a mistake here degrades to "no active
    location" rather than to a cross-location read.
    """
    if location is None:
        request.session.pop(ACTIVE_LOCATION_SESSION_KEY, None)
        return None
    request.session[ACTIVE_LOCATION_SESSION_KEY] = location.pk
    return location


def activate_sole_location(request, user):
    """Activate the user's only assignment, if they have exactly one.

    With two or more the choice belongs to the user, through the switcher.
    """
    candidates = list(user.assigned_locations()[:2])
    if len(candidates) == 1:
        return set_active_location(request, candidates[0])
    return None
