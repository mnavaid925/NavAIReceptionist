"""Request-scoped tenant and location resolution, plus session and cache policy.

Four middlewares, all sitting AFTER `AuthenticationMiddleware` because they read
`request.user`:

1. `SessionPolicyMiddleware` — ends idle sessions before anything else runs.
2. `TenantMiddleware` — sets `request.tenant`.
3. `ActiveLocationMiddleware` — sets `request.location`, re-validated every request.
4. `PrivateCacheMiddleware` — marks every authenticated response no-store.

Note what these do NOT cover. Channels consumers, Twilio webhooks and background
tasks have no `request` and therefore no `request.tenant` / `request.location`.
There, both are resolved from the DIALED NUMBER
(`AgentSetting.objects.get(inbound_phone_number=<To>)`) — never from a websocket
URL segment, a query string or a body parameter the caller controls.
"""
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.utils import timezone as django_timezone
from django.contrib.auth.views import redirect_to_login

ACTIVE_LOCATION_SESSION_KEY = 'active_location_id'
LAST_ACTIVITY_SESSION_KEY = 'last_activity'

# Only rewrite the activity stamp this often, so a DB-backed session store is not
# written on literally every request.
ACTIVITY_WRITE_INTERVAL_SECONDS = 60


class TenantMiddleware:
    """Set `request.tenant` from the signed-in user's business.

    The platform superuser has `tenant=None`, so `request.tenant` is None and every
    tenant-scoped queryset returns empty. That is BY DESIGN — log in as a tenant
    admin to see module data.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        request.tenant = user.tenant if (user and user.is_authenticated) else None
        return self.get_response(request)


class ActiveLocationMiddleware:
    """Set `request.location` — the session's active location.

    THIS IS THE CROSS-LOCATION IDOR BOUNDARY. The stored id is re-validated against
    the user's `accounts.UserLocation` rows on EVERY request, not merely at the
    moment it is chosen. A session value, a form field, a URL kwarg or a query
    string is never trusted on its own: an id that no longer resolves to an
    assignment is discarded and `request.location` degrades to None, at which point
    location-scoped views correctly return nothing rather than leaking a site the
    user may not reach.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.location = self._resolve(request)

        # Render every datetime in the ACTIVE LOCATION's timezone.
        #
        # Django stores datetimes in UTC (USE_TZ) and renders them in
        # `settings.TIME_ZONE`, which is UTC here. Without this, a 15:00 booking
        # at an America/Chicago site displays as 15:00 to the receptionist
        # standing in that site at 09:00 — silently wrong, on every page, with
        # nothing to indicate it.
        #
        # This is the project rule ("appointment and transfer-hours calculations
        # are evaluated in the location's own timezone, never the server's and
        # never the browser's") applied at the one place that makes it true for
        # every template at once, rather than per-view and forgotten somewhere.
        #
        # Deactivate when there is no active location so a request never inherits
        # the previous one's zone — threads are reused between requests.
        if request.location is not None:
            django_timezone.activate(request.location.tzinfo)
        else:
            django_timezone.deactivate()

        try:
            return self.get_response(request)
        finally:
            # Leave the thread as we found it. A leaked activation would follow
            # this worker into the next request, for a different location.
            django_timezone.deactivate()

    def _resolve(self, request):
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated) or getattr(request, 'tenant', None) is None:
            return None

        assigned = user.assigned_locations()

        stored_id = request.session.get(ACTIVE_LOCATION_SESSION_KEY)
        if stored_id is not None:
            location = assigned.filter(pk=stored_id).first()
            if location is not None:
                return location
            # Assignment revoked, location deleted, or an id that was never the
            # user's. Drop it rather than honouring it.
            request.session.pop(ACTIVE_LOCATION_SESSION_KEY, None)

        # Exactly one assignment needs no choosing — activate it. With two or more
        # the user picks via the switcher (sub-module 0.4); until then there is no
        # active location, which is correct rather than guessing on their behalf.
        candidates = list(assigned[:2])
        if len(candidates) == 1:
            request.session[ACTIVE_LOCATION_SESSION_KEY] = candidates[0].pk
            return candidates[0]

        return None


class SessionPolicyMiddleware:
    """End sessions idle longer than the user's `inactivity_timeout`.

    Logging out flushes the whole session, so the active location is cleared with
    it — a re-login re-derives it from `UserLocation` rather than restoring a stale
    choice.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)

        if user and user.is_authenticated:
            now = time.time()
            last_activity = request.session.get(LAST_ACTIVITY_SESSION_KEY)
            timeout_seconds = user.effective_inactivity_timeout * 60

            if last_activity is not None and (now - last_activity) > timeout_seconds:
                logout(request)
                if self._expects_html(request):
                    messages.info(request, 'You were signed out after a period of inactivity.')
                    return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            elif last_activity is None or (now - last_activity) > ACTIVITY_WRITE_INTERVAL_SECONDS:
                request.session[LAST_ACTIVITY_SESSION_KEY] = now

        return self.get_response(request)

    @staticmethod
    def _expects_html(request):
        """Don't bounce an XHR/HTMX request into a login page mid-swap."""
        if request.headers.get('HX-Request') == 'true':
            return False
        return 'text/html' in request.headers.get('Accept', 'text/html')


class PrivateCacheMiddleware:
    """Mark every AUTHENTICATED response no-store.

    Essentially every signed-in page in this product renders tenant PII — a
    caller's name and number, a transcript, an appointment. A browser's
    back-forward cache will happily restore such a page after logout, so on a
    shared clinic or salon workstation the next person can read the previous
    receptionist's conversation by pressing Back. No authentication check runs on
    a bfcache restore; the page is simply redisplayed from memory.

    5.2 recognised this and put `@never_cache` on the two transcript-bearing
    pages, noting in a comment that the list page and the rest of the product
    carried the same latent gap and wanted a shared fix. This is that fix. Doing
    it here rather than as a decorator per view is the point: the failure mode of
    the decorator approach is silent — a new PII page ships uncovered and nothing
    complains — whereas a middleware covers pages nobody remembered to annotate.
    The existing `@never_cache` decorators are left in place; they set the same
    directives, so they are now redundant rather than wrong, and they document
    intent at the two most sensitive views.

    Anonymous responses are deliberately untouched: the login page carries no
    tenant data, and leaving them cacheable keeps the unauthenticated path (and
    Django's own static handling in development) alone.
    """

    #: `no-store` is the directive that actually suppresses the back-forward
    #: cache; the rest are belt-and-braces for intermediaries and older browsers.
    CACHE_CONTROL = 'no-store, no-cache, must-revalidate, max-age=0, private'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            response['Cache-Control'] = self.CACHE_CONTROL
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        return response
