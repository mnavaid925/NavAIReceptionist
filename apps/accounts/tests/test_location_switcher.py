"""View tests for sub-module 0.4 — the active-location switcher.

THE cross-location IDOR gate for the whole product: a POST naming a location the
user is not assigned to, or one belonging to another tenant, must be refused and
must leave the active location exactly as it was.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.middleware import ACTIVE_LOCATION_SESSION_KEY

pytestmark = pytest.mark.django_db


def _switch(client, location_pk, follow=False):
    return client.post(reverse('accounts:switch_location'), {'location': location_pk}, follow=follow)


# --------------------------------------------------------------------------- #
# my_locations_view
# --------------------------------------------------------------------------- #

def test_my_locations_anonymous_redirects_to_login(client):
    response = client.get(reverse('accounts:my_locations'))
    assert response.status_code == 302


def test_my_locations_lists_only_this_users_assignments(client_a, admin_user, location_a1, location_a2, location_b1):
    response = client_a.get(reverse('accounts:my_locations'))
    assert response.status_code == 200
    assert set(response.context['assigned_locations']) == {location_a1, location_a2}


# --------------------------------------------------------------------------- #
# switch_location_view — method guard
# --------------------------------------------------------------------------- #

def test_switch_location_get_is_405(client_a):
    response = client_a.get(reverse('accounts:switch_location'))
    assert response.status_code == 405


def test_switch_location_anonymous_redirects_to_login(client, location_a1):
    response = _switch(client, location_a1.pk)
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# Legitimate switch
# --------------------------------------------------------------------------- #

def test_switch_to_an_assigned_location_succeeds(client_a, location_a2):
    response = _switch(client_a, location_a2.pk, follow=True)
    assert response.status_code == 200
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a2.pk


def test_switch_success_message_names_the_location(client_a, location_a2):
    response = _switch(client_a, location_a2.pk, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any(location_a2.name in m for m in messages_seen)


def test_switch_honours_the_next_parameter(client_a, location_a2):
    target = reverse('accounts:my_locations')
    response = client_a.post(f"{reverse('accounts:switch_location')}?next={target}", {'location': location_a2.pk})
    assert response.url == target


# --------------------------------------------------------------------------- #
# THE cross-location IDOR gate
# --------------------------------------------------------------------------- #

def test_switch_to_an_unassigned_same_tenant_location_is_refused(member_client, location_a1, location_a2):
    """`member_client` (root fixture) is active at A1 and assigned ONLY to A1."""
    response = _switch(member_client, location_a2.pk)
    assert response.status_code == 302
    assert member_client.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_switch_to_an_unassigned_same_tenant_location_shows_no_enumeration(member_client, location_a2):
    response = _switch(member_client, location_a2.pk, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('not available to you' in m for m in messages_seen)


def test_switch_to_another_tenants_location_is_refused(client_a, location_a1, location_b1):
    response = _switch(client_a, location_b1.pk)
    assert response.status_code == 302
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_switch_to_another_tenants_location_does_not_leak_its_existence(client_a, location_b1):
    """Refusal must read identically to a same-tenant refusal — the message
    must not confirm or deny that `location_b1` exists."""
    same_tenant_refusal = _switch(client_a, 999999, follow=True)
    cross_tenant_refusal = _switch(client_a, location_b1.pk, follow=True)
    same_messages = [str(m) for m in same_tenant_refusal.context['messages']]
    cross_messages = [str(m) for m in cross_tenant_refusal.context['messages']]
    assert same_messages == cross_messages


def test_switch_to_a_deactivated_location_is_refused(client_a, tenant_a, admin_user, location_a1, location_a2_inactive):
    from apps.accounts.models import UserLocation

    UserLocation.objects.create(tenant=tenant_a, user=admin_user, location=location_a2_inactive)

    response = _switch(client_a, location_a2_inactive.pk)

    assert response.status_code == 302
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


# --------------------------------------------------------------------------- #
# Negative-input hardening
# --------------------------------------------------------------------------- #

def test_switch_with_no_location_posted_is_refused(client_a, location_a1):
    response = client_a.post(reverse('accounts:switch_location'), {})
    assert response.status_code == 302
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_switch_with_a_non_numeric_location_is_refused_not_500(client_a, location_a1):
    response = _switch(client_a, 'not-a-number')
    assert response.status_code == 302
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_switch_with_a_nonexistent_location_id_is_refused(client_a, location_a1):
    response = _switch(client_a, 999999)
    assert response.status_code == 302
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_switch_csrf_is_enforced(admin_user, location_a1, location_a2):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = _switch(csrf_client, location_a2.pk)
    assert response.status_code == 403
