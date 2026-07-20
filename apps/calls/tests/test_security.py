"""Auth, tenant/location isolation and no-mutation-surface tests for
`calls.CallSession` (sub-module 5.1).

A call session carries a transcript and both legs of a phone number — this is
the PII path, so isolation here is not optional. `CallSession` also ships with
NO create/edit/delete view at all (CLAUDE.md's CRUD-completeness carve-out), so
this file proves that absence is real: no URL name resolves, and the two
routes that DO exist accept GET only.
"""
import pytest
from django.test import Client
from django.urls import NoReverseMatch, reverse

from apps.calls.models import CallSession

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'calls:{name}', args=args)


# --------------------------------------------------------------------------- #
# Anonymous access
# --------------------------------------------------------------------------- #

def test_anonymous_list_redirects_to_login(client):
    response = client.get(_url('callsession_list'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_anonymous_detail_redirects_to_login(client, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    response = client.get(_url('callsession_detail', session.pk))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# Cross-tenant IDOR — a call session carries a transcript, so this is the PII
# path.
# --------------------------------------------------------------------------- #

def test_detail_view_cross_tenant_pk_is_404(client_a, session_b):
    response = client_a.get(_url('callsession_detail', session_b.pk))
    assert response.status_code == 404


def test_detail_view_cross_tenant_pk_leaves_the_row_untouched(client_a, session_b):
    original_transcript = list(session_b.transcript)
    original_status = session_b.status

    response = client_a.get(_url('callsession_detail', session_b.pk))

    assert response.status_code == 404
    session_b.refresh_from_db()
    assert session_b.transcript == original_transcript
    assert session_b.status == original_status


def test_list_view_never_contains_another_tenants_rows(client_a, session_a1, session_b):
    response = client_a.get(_url('callsession_list'))
    results = list(response.context['call_sessions'])
    assert session_a1 in results
    assert session_b not in results


# --------------------------------------------------------------------------- #
# Cross-LOCATION isolation — CallSession is fully location-scoped
# --------------------------------------------------------------------------- #

def test_detail_view_cross_location_pk_is_404(client_a, session_a2):
    """`client_a` is active at A1; the session belongs to the SAME tenant's A2."""
    response = client_a.get(_url('callsession_detail', session_a2.pk))
    assert response.status_code == 404


def test_detail_view_cross_location_pk_leaves_the_row_untouched(client_a, session_a2):
    original_transcript = list(session_a2.transcript)

    response = client_a.get(_url('callsession_detail', session_a2.pk))

    assert response.status_code == 404
    session_a2.refresh_from_db()
    assert session_a2.transcript == original_transcript


def test_list_view_never_contains_another_locations_rows(client_a, session_a1, session_a2):
    response = client_a.get(_url('callsession_list'))
    results = list(response.context['call_sessions'])
    assert session_a1 in results
    assert session_a2 not in results


# --------------------------------------------------------------------------- #
# The printable-transcript page (5.2) — PII-identical to the detail page, and
# scoped identically on purpose. Same `location_sessions` helper, so a pk from
# another tenant or another location must 404 here exactly as it does on the
# detail page.
# --------------------------------------------------------------------------- #

def test_print_view_cross_tenant_pk_is_404(client_a, session_b):
    response = client_a.get(_url('callsession_transcript_print', session_b.pk))
    assert response.status_code == 404


def test_print_view_cross_location_pk_is_404(client_a, session_a2):
    """`client_a` is active at A1; the session belongs to the SAME tenant's A2."""
    response = client_a.get(_url('callsession_transcript_print', session_a2.pk))
    assert response.status_code == 404


def test_print_view_anonymous_redirects_to_login(client, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    response = client.get(_url('callsession_transcript_print', session.pk))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_print_view_post_is_405(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    response = client_a.post(_url('callsession_transcript_print', session.pk), {})
    assert response.status_code == 405


def test_print_view_with_no_active_location_is_404(admin_user, tenant_a, location_a1, make_call_session):
    """`admin_user` is assigned to BOTH A1 and A2, so with no explicit switch the
    middleware activates neither — `location_sessions` returns `.none()` and
    the session must be unreachable, matching `test_list_view_with_no_active_
    location_returns_empty` in `test_views.py`.
    """
    session = make_call_session(tenant_a, location_a1)
    client = Client()
    client.force_login(admin_user)

    response = client.get(_url('callsession_transcript_print', session.pk))

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# No mutation surface — the CRUD-completeness carve-out, proven rather than
# merely documented.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('name', [
    'callsession_create', 'callsession_edit', 'callsession_delete',
])
def test_no_create_edit_or_delete_url_exists(name):
    with pytest.raises(NoReverseMatch):
        reverse(f'calls:{name}', args=[1])


def test_list_view_post_is_405_and_creates_nothing(client_a):
    response = client_a.post(_url('callsession_list'), {})
    assert response.status_code == 405
    assert CallSession.objects.count() == 0


def test_detail_view_post_is_405_and_leaves_row_unchanged(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    original_status = session.status

    response = client_a.post(_url('callsession_detail', session.pk), {'status': 'failed'})

    assert response.status_code == 405
    session.refresh_from_db()
    assert session.status == original_status


# --------------------------------------------------------------------------- #
# No tier gate — reading the call log is open to every signed-in tenant member
# --------------------------------------------------------------------------- #

def test_list_view_is_open_to_staff_tier(member_client, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1)
    response = member_client.get(_url('callsession_list'))
    assert response.status_code == 200


def test_detail_view_is_open_to_staff_tier(member_client, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    response = member_client.get(_url('callsession_detail', session.pk))
    assert response.status_code == 200
