"""Tests for `apps/accounts/middleware.py` — THE load-bearing module.

`ActiveLocationMiddleware` is the cross-location IDOR boundary for the whole
product: it re-validates the session's active location against
`user.assigned_locations()` on EVERY request, never trusting a stored id on its
own. These tests exercise the middleware classes directly (constructed with a
stub `get_response`) so every edge of `_resolve()` is provable without going
through a full view stack; `SessionPolicyMiddleware`'s idle-logout behaviour is
also exercised through a real `Client` for the message/redirect integration.
"""
import time

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone as dj_timezone

from apps.accounts.middleware import (
    ACTIVE_LOCATION_SESSION_KEY,
    LAST_ACTIVITY_SESSION_KEY,
    ActiveLocationMiddleware,
    SessionPolicyMiddleware,
    TenantMiddleware,
)
from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location

pytestmark = pytest.mark.django_db


def _new_session():
    store = SessionStore()
    store.create()
    return store


def _stub(get_response=None):
    calls = {'count': 0}

    def default(request):
        calls['count'] += 1
        return HttpResponse('ok')

    return get_response or default, calls


# --------------------------------------------------------------------------- #
# TenantMiddleware
# --------------------------------------------------------------------------- #

def test_tenant_middleware_sets_tenant_for_authenticated_user(tenant_a, admin_user):
    request = RequestFactory().get('/')
    request.user = admin_user
    captured = {}

    def get_response(req):
        captured['tenant'] = req.tenant
        return HttpResponse('ok')

    TenantMiddleware(get_response)(request)
    assert captured['tenant'] == tenant_a


def test_tenant_middleware_sets_none_for_superuser(db):
    superuser = User.objects.create_superuser(email='root-mw@platform.example', password='x')
    request = RequestFactory().get('/')
    request.user = superuser
    captured = {}

    def get_response(req):
        captured['tenant'] = req.tenant
        return HttpResponse('ok')

    TenantMiddleware(get_response)(request)
    assert superuser.tenant_id is None
    assert captured['tenant'] is None


def test_tenant_middleware_sets_none_for_anonymous(db):
    request = RequestFactory().get('/')
    request.user = AnonymousUser()
    captured = {}

    def get_response(req):
        captured['tenant'] = req.tenant
        return HttpResponse('ok')

    TenantMiddleware(get_response)(request)
    assert captured['tenant'] is None


def test_tenant_middleware_never_raises_when_request_has_no_user_attr(db):
    """A request that never went through AuthenticationMiddleware must still be
    handled — `getattr(request, 'user', None)` is the guard.
    """
    request = RequestFactory().get('/')
    captured = {}

    def get_response(req):
        captured['tenant'] = req.tenant
        return HttpResponse('ok')

    TenantMiddleware(get_response)(request)
    assert captured['tenant'] is None


# --------------------------------------------------------------------------- #
# ActiveLocationMiddleware — the cross-location IDOR boundary
# --------------------------------------------------------------------------- #

def _mw_request(user, tenant, session_data=None):
    request = RequestFactory().get('/')
    request.user = user
    request.tenant = tenant
    store = _new_session()
    if session_data:
        for key, value in session_data.items():
            store[key] = value
        store.save()
    request.session = store
    return request


def _run_active_location(request, get_response=None):
    captured = {}

    def default(req):
        captured['called'] = True
        captured['tzname'] = dj_timezone.get_current_timezone_name()
        return HttpResponse('ok')

    ActiveLocationMiddleware(get_response or default)(request)
    return captured


def test_resolves_none_for_anonymous_without_raising(db):
    request = _mw_request(AnonymousUser(), None)
    captured = _run_active_location(request)
    assert request.location is None
    assert captured.get('called') is True


def test_resolves_none_when_tenant_is_none(db):
    superuser = User.objects.create_superuser(email='root-mw2@platform.example', password='x')
    request = _mw_request(superuser, None)
    _run_active_location(request)
    assert request.location is None


def test_auto_activates_the_sole_assignment(tenant_a, location_a1, member_user):
    """`member_user` is assigned to exactly one location — no session value at
    all — and the middleware activates it without being asked.
    """
    request = _mw_request(member_user, tenant_a)
    _run_active_location(request)
    assert request.location == location_a1
    assert request.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_two_assignments_with_nothing_stored_resolves_to_none(tenant_a, admin_user):
    """`admin_user` is assigned to BOTH A1 and A2 — with nothing chosen yet, the
    middleware must not guess.
    """
    request = _mw_request(admin_user, tenant_a)
    _run_active_location(request)
    assert request.location is None
    assert ACTIVE_LOCATION_SESSION_KEY not in request.session


def test_stored_valid_id_is_honoured(tenant_a, location_a2, admin_user):
    request = _mw_request(admin_user, tenant_a, {ACTIVE_LOCATION_SESSION_KEY: location_a2.pk})
    _run_active_location(request)
    assert request.location == location_a2


def test_stored_id_the_user_is_not_assigned_to_is_discarded(tenant_a, location_a1, location_a2, member_user):
    """`member_user` is only assigned to A1. A session carrying A2's id (a real
    location in the SAME tenant) must be refused, not trusted — and because
    exactly one valid assignment remains, the middleware falls back to it.
    """
    request = _mw_request(member_user, tenant_a, {ACTIVE_LOCATION_SESSION_KEY: location_a2.pk})
    _run_active_location(request)
    assert request.location == location_a1
    # The stale id was never honoured, even transiently.
    assert request.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_stored_id_from_another_tenant_is_discarded(tenant_a, admin_user, location_b1):
    """A session value naming tenant B's location, while signed in as a tenant A
    user, must be refused — `admin_user` has two A-side assignments so there is
    no sole fallback, and the result must be None, never `location_b1`.
    """
    request = _mw_request(admin_user, tenant_a, {ACTIVE_LOCATION_SESSION_KEY: location_b1.pk})
    _run_active_location(request)
    assert request.location is None
    assert ACTIVE_LOCATION_SESSION_KEY not in request.session


def test_stored_id_for_a_nonexistent_location_is_discarded_without_raising(tenant_a, admin_user):
    request = _mw_request(admin_user, tenant_a, {ACTIVE_LOCATION_SESSION_KEY: 999999})
    _run_active_location(request)
    assert request.location is None


def test_deactivated_location_is_never_honoured(tenant_a, location_a1, location_a2_inactive, member_user):
    """A `UserLocation` row survives a location being deactivated, but
    `assigned_locations()` excludes it — the stored id must be discarded and,
    since only A1 remains a valid candidate, the middleware falls back to it.
    """
    UserLocation.objects.create(tenant=tenant_a, user=member_user, location=location_a2_inactive)
    request = _mw_request(member_user, tenant_a, {ACTIVE_LOCATION_SESSION_KEY: location_a2_inactive.pk})
    _run_active_location(request)
    assert request.location == location_a1


def test_activates_the_locations_own_timezone_during_the_request(tenant_a, make_user):
    chicago = Location.objects.create(
        tenant=tenant_a, name='Chicago', slug='chicago-mw', timezone='America/Chicago',
    )
    user = make_user(tenant_a, locations=[chicago], email='chi-mw@acme-test.example')
    request = _mw_request(user, tenant_a)

    captured = _run_active_location(request)

    assert captured['tzname'] == 'America/Chicago'
    # The thread is left exactly as it was found — a leaked activation would
    # follow this worker into the next, unrelated request.
    assert dj_timezone.get_current_timezone_name() == 'UTC'


def test_deactivates_timezone_when_there_is_no_active_location(tenant_a, admin_user):
    request = _mw_request(admin_user, tenant_a)  # two assignments -> None
    captured = _run_active_location(request)
    assert request.location is None
    assert captured['tzname'] == 'UTC'


def test_timezone_is_deactivated_even_if_get_response_raises(tenant_a, location_a1, member_user):
    request = _mw_request(member_user, tenant_a)

    def boom(req):
        raise RuntimeError('downstream failure')

    with pytest.raises(RuntimeError):
        ActiveLocationMiddleware(boom)(request)

    assert dj_timezone.get_current_timezone_name() == 'UTC'


# --------------------------------------------------------------------------- #
# SessionPolicyMiddleware — idle-session termination
# --------------------------------------------------------------------------- #

def test_last_activity_written_on_first_request(tenant_a, admin_user):
    request = RequestFactory().get('/')
    request.user = admin_user
    request.session = _new_session()

    SessionPolicyMiddleware(_stub()[0])(request)

    assert LAST_ACTIVITY_SESSION_KEY in request.session


def test_last_activity_not_rewritten_within_the_write_interval(tenant_a, admin_user):
    request = RequestFactory().get('/')
    request.user = admin_user
    store = _new_session()
    now = time.time()
    store[LAST_ACTIVITY_SESSION_KEY] = now
    store.save()
    request.session = store

    SessionPolicyMiddleware(_stub()[0])(request)

    assert request.session[LAST_ACTIVITY_SESSION_KEY] == now


def test_idle_timeout_logs_out_and_redirects_to_login(tenant_a, admin_user):
    request = RequestFactory().get('/')
    request.user = admin_user
    store = _new_session()
    timeout_seconds = admin_user.effective_inactivity_timeout * 60
    store[LAST_ACTIVITY_SESSION_KEY] = time.time() - timeout_seconds - 120
    store.save()
    request.session = store
    request._messages = FallbackStorage(request)

    def get_response(req):
        raise AssertionError('get_response must not run once the idle redirect fires')

    response = SessionPolicyMiddleware(get_response)(request)

    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_htmx_idle_request_logs_out_but_does_not_redirect(tenant_a, admin_user):
    """An HTMX request must not be bounced mid-swap into a full login page — the
    session is still ended, but the response falls through to `get_response`.
    """
    request = RequestFactory().get('/', HTTP_HX_REQUEST='true')
    request.user = admin_user
    store = _new_session()
    timeout_seconds = admin_user.effective_inactivity_timeout * 60
    store[LAST_ACTIVITY_SESSION_KEY] = time.time() - timeout_seconds - 120
    store.save()
    request.session = store
    request._messages = FallbackStorage(request)

    get_response, calls = _stub()
    response = SessionPolicyMiddleware(get_response)(request)

    assert calls['count'] == 1
    assert response.status_code == 200


def test_idle_session_via_client_redirects_and_flushes_active_location(client_a, admin_user):
    """End-to-end through a real `Client`: the session is flushed (which clears
    the active location with it), and the login page shows the one message.
    """
    session = client_a.session
    timeout_seconds = admin_user.effective_inactivity_timeout * 60
    session[LAST_ACTIVITY_SESSION_KEY] = time.time() - timeout_seconds - 120
    session.save()

    response = client_a.get(reverse('accounts:dashboard'), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('signed out after a period of inactivity' in m for m in messages_seen)
    assert ACTIVE_LOCATION_SESSION_KEY not in client_a.session


def test_active_session_is_not_ended(client_a):
    """A normal, active session keeps working — the dashboard renders 200 with
    no redirect."""
    response = client_a.get(reverse('accounts:dashboard'))
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# PrivateCacheMiddleware — the shared-workstation back-button leak.
#
# A browser's back-forward cache restores a page with NO authentication check, so
# after logout the next person at the same machine can press Back and read the
# previous user's tenant data. 5.2 covered the two transcript pages with
# `@never_cache` and noted the rest of the product had the same gap; this is the
# shared fix, so these tests deliberately target pages that were NEVER decorated.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('url_name', [
    'accounts:dashboard',
    'accounts:profile',
    'accounts:user_list',
    'accounts:my_locations',
])
def test_authenticated_pages_are_no_store(client_a, url_name):
    response = client_a.get(reverse(url_name))
    assert response.status_code == 200
    assert 'no-store' in response['Cache-Control']


def test_a_pii_list_page_that_was_never_decorated_is_covered(client_a):
    """The call log LIST — the page 5.2's own comment flagged as still exposed.

    It renders caller numbers and contact names, and it never carried
    `@never_cache`. A per-view decorator fails silently for exactly this reason:
    nothing complains when a new PII page ships without one.
    """
    response = client_a.get(reverse('calls:callsession_list'))
    assert response.status_code == 200
    assert 'no-store' in response['Cache-Control']


def test_scheduling_pii_pages_are_covered(client_a):
    for url_name in ('scheduling:contact_list', 'scheduling:appointment_list'):
        response = client_a.get(reverse(url_name))
        assert response.status_code == 200
        assert 'no-store' in response['Cache-Control'], url_name


def test_anonymous_responses_are_left_alone(client):
    """Deliberately untouched: the login page carries no tenant data, and this
    keeps the unauthenticated path (and dev static handling) unaffected."""
    response = client.get(reverse('accounts:login'))
    assert 'no-store' not in response.get('Cache-Control', '')
