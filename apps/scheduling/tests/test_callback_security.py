"""Auth, tenant/location isolation and tier-gating tests for `CallbackRequest`
(sub-module 4.5).

Mirrors `test_booking_security.py`'s structure and conventions.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User, UserLocation
from apps.scheduling.models import CallbackRequest

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


def _callback_post(**overrides):
    data = {
        'caller_name': 'Dana Caller',
        'caller_phone': '3125550199',
        'reason': 'Wants to reschedule',
        'status': CallbackRequest.STATUS_PENDING,
        'notes': '',
    }
    data.update(overrides)
    return data


def _manager_assigned_to(tenant, location, email='manager@acme-test.example'):
    manager = User.objects.create_user(
        tenant=tenant, email=email, password='pass-1234', tier=User.TIER_MANAGER,
    )
    UserLocation.objects.create(tenant=tenant, user=manager, location=location)
    client = Client()
    client.force_login(manager)
    return client


# --------------------------------------------------------------------------- #
# Anonymous access
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('name', ['callbackrequest_list', 'callbackrequest_create'])
def test_anonymous_get_redirects_to_login(client, name):
    response = client.get(_url(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #

def test_csrf_is_enforced_on_callback_create_post(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)

    response = csrf_client.post(_url('callbackrequest_create'), _callback_post())

    assert response.status_code == 403
    assert CallbackRequest.objects.count() == 0


# --------------------------------------------------------------------------- #
# Cross-tenant IDOR
# --------------------------------------------------------------------------- #

def test_detail_view_cross_tenant_pk_is_404(client_a, tenant_b, location_b1, make_callback):
    cb = make_callback(tenant_b, location_b1)
    response = client_a.get(_url('callbackrequest_detail', cb.pk))
    assert response.status_code == 404


def test_edit_view_get_cross_tenant_pk_is_404(client_a, tenant_b, location_b1, make_callback):
    cb = make_callback(tenant_b, location_b1)
    response = client_a.get(_url('callbackrequest_edit', cb.pk))
    assert response.status_code == 404


def test_edit_view_post_cross_tenant_pk_is_404_and_does_not_write(client_a, tenant_b, location_b1, make_callback):
    cb = make_callback(tenant_b, location_b1)
    original_reason = cb.reason

    response = client_a.post(_url('callbackrequest_edit', cb.pk), _callback_post(reason='Hijacked'))

    assert response.status_code == 404
    cb.refresh_from_db()
    assert cb.reason == original_reason


def test_resolve_view_cross_tenant_pk_is_404_and_row_survives(client_a, tenant_b, location_b1, make_callback):
    cb = make_callback(tenant_b, location_b1)
    original_status = cb.status

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CLOSED, 'notes': 'Hijacked',
    })

    assert response.status_code == 404
    cb.refresh_from_db()
    assert cb.status == original_status
    assert cb.notes == ''


def test_delete_view_cross_tenant_pk_is_404_and_row_survives(client_a, tenant_b, location_b1, make_callback):
    cb = make_callback(tenant_b, location_b1)
    response = client_a.post(_url('callbackrequest_delete', cb.pk))
    assert response.status_code == 404
    assert CallbackRequest.objects.filter(pk=cb.pk).exists()


def test_list_view_never_contains_another_tenants_rows(
    client_a, tenant_a, tenant_b, location_a1, location_b1, make_callback,
):
    mine = make_callback(tenant_a, location_a1)
    theirs = make_callback(tenant_b, location_b1)

    response = client_a.get(_url('callbackrequest_list'), {'status': ''})
    results = list(response.context['callback_requests'])
    assert mine in results
    assert theirs not in results


def test_create_view_crafted_contact_from_another_tenant_is_rejected(client_a, contact_b):
    response = client_a.post(_url('callbackrequest_create'), _callback_post(contact=str(contact_b.pk)))

    assert response.status_code == 200  # re-rendered with a form error, not saved
    assert not response.context['form'].is_valid()
    assert CallbackRequest.objects.count() == 0


def test_create_view_crafted_tenant_field_cannot_assign_another_tenant(client_a, tenant_a, tenant_b):
    response = client_a.post(_url('callbackrequest_create'), _callback_post(tenant=str(tenant_b.pk)))

    assert response.status_code == 302
    obj = CallbackRequest.objects.get(caller_name='Dana Caller')
    assert obj.tenant_id == tenant_a.pk


# --------------------------------------------------------------------------- #
# Cross-LOCATION isolation — CallbackRequest is fully location-scoped
# --------------------------------------------------------------------------- #

def test_detail_view_cross_location_pk_is_404(client_a, tenant_a, location_a2, make_callback):
    """`client_a` active at A1; the callback belongs to the SAME tenant's A2."""
    cb = make_callback(tenant_a, location_a2)
    response = client_a.get(_url('callbackrequest_detail', cb.pk))
    assert response.status_code == 404


def test_edit_view_get_cross_location_pk_is_404(client_a, tenant_a, location_a2, make_callback):
    cb = make_callback(tenant_a, location_a2)
    response = client_a.get(_url('callbackrequest_edit', cb.pk))
    assert response.status_code == 404


def test_edit_view_post_cross_location_pk_is_404_and_does_not_write(client_a, tenant_a, location_a2, make_callback):
    cb = make_callback(tenant_a, location_a2)
    original_reason = cb.reason

    response = client_a.post(_url('callbackrequest_edit', cb.pk), _callback_post(reason='Hijacked'))

    assert response.status_code == 404
    cb.refresh_from_db()
    assert cb.reason == original_reason


def test_resolve_view_cross_location_pk_is_404_and_row_survives(client_a, tenant_a, location_a2, make_callback):
    cb = make_callback(tenant_a, location_a2)
    original_status = cb.status

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CLOSED, 'notes': 'Hijacked',
    })

    assert response.status_code == 404
    cb.refresh_from_db()
    assert cb.status == original_status
    assert cb.notes == ''


def test_delete_view_cross_location_pk_is_404_and_row_survives(client_a, tenant_a, location_a2, make_callback):
    cb = make_callback(tenant_a, location_a2)
    response = client_a.post(_url('callbackrequest_delete', cb.pk))
    assert response.status_code == 404
    assert CallbackRequest.objects.filter(pk=cb.pk).exists()


def test_list_view_never_contains_another_locations_rows(
    client_a, tenant_a, location_a1, location_a2, make_callback,
):
    here = make_callback(tenant_a, location_a1)
    elsewhere = make_callback(tenant_a, location_a2)

    response = client_a.get(_url('callbackrequest_list'), {'status': ''})
    results = list(response.context['callback_requests'])
    assert here in results
    assert elsewhere not in results


def test_create_view_crafted_location_field_cannot_pin_another_location(
    client_a, tenant_a, location_a1, location_a2,
):
    response = client_a.post(_url('callbackrequest_create'), _callback_post(location=str(location_a2.pk)))

    assert response.status_code == 302
    obj = CallbackRequest.objects.get(caller_name='Dana Caller')
    assert obj.location_id == location_a1.pk


# --------------------------------------------------------------------------- #
# delete — POST-only (repeated from test_callback_views.py for the security
# suite's own completeness; see that file for the base case)
# --------------------------------------------------------------------------- #

def test_delete_view_get_is_405_and_row_survives(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.get(_url('callbackrequest_delete', cb.pk))
    assert response.status_code == 405
    assert CallbackRequest.objects.filter(pk=cb.pk).exists()


# --------------------------------------------------------------------------- #
# Tier gating — delete is management-tier only; everything else (including
# resolve) is open to staff, front-desk work.
# --------------------------------------------------------------------------- #

def test_delete_view_staff_tier_is_redirected_and_row_survives(member_client, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = member_client.post(_url('callbackrequest_delete', cb.pk))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    assert CallbackRequest.objects.filter(pk=cb.pk).exists()


def test_delete_view_manager_tier_is_allowed(tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    client = _manager_assigned_to(tenant_a, location_a1)

    response = client.post(_url('callbackrequest_delete', cb.pk))

    assert response.status_code == 302
    assert not CallbackRequest.objects.filter(pk=cb.pk).exists()


def test_list_view_is_open_to_staff_tier(member_client, tenant_a, location_a1, make_callback):
    make_callback(tenant_a, location_a1)
    response = member_client.get(_url('callbackrequest_list'))
    assert response.status_code == 200


def test_create_view_is_open_to_staff_tier(member_client, tenant_a):
    response = member_client.post(_url('callbackrequest_create'), _callback_post())
    assert response.status_code == 302
    assert CallbackRequest.objects.filter(tenant=tenant_a, caller_name='Dana Caller').exists()


def test_resolve_view_is_open_to_staff_tier(member_client, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = member_client.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CLOSED, 'notes': '',
    })
    assert response.status_code == 302
    cb.refresh_from_db()
    assert cb.status == CallbackRequest.STATUS_CLOSED
