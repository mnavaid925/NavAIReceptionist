"""Auth, tenant/location isolation and tier-gating tests for the service and
resource catalogue (sub-module 4.2).
"""
import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User, UserLocation
from apps.scheduling.models import Resource, Service

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


def _service_post(**overrides):
    data = {
        'name': 'Consult',
        'duration_minutes': '30',
        'buffer_minutes': '0',
        'display_order': '0',
    }
    data.update(overrides)
    return data


def _resource_post(**overrides):
    data = {'name': 'Room 1', 'display_order': '0'}
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

@pytest.mark.parametrize('name', ['service_list', 'service_create', 'resource_list', 'resource_create'])
def test_anonymous_get_redirects_to_login(client, name):
    response = client.get(_url(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #

def test_csrf_is_enforced_on_service_create_post(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)

    response = csrf_client.post(_url('service_create'), _service_post(name='Blocked'))

    assert response.status_code == 403
    assert not Service.objects.filter(name='Blocked').exists()


def test_csrf_is_enforced_on_resource_create_post(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)

    response = csrf_client.post(_url('resource_create'), _resource_post(name='Blocked'))

    assert response.status_code == 403
    assert not Resource.objects.filter(name='Blocked').exists()


# --------------------------------------------------------------------------- #
# Cross-tenant IDOR — Service
# --------------------------------------------------------------------------- #

def test_service_detail_view_cross_tenant_pk_is_404(client_a, service_b):
    response = client_a.get(_url('service_detail', service_b.pk))
    assert response.status_code == 404


def test_service_edit_view_cross_tenant_pk_is_404(client_a, service_b):
    response = client_a.get(_url('service_edit', service_b.pk))
    assert response.status_code == 404


def test_service_edit_view_cross_tenant_post_is_404_and_does_not_write(client_a, service_b):
    original_name = service_b.name

    response = client_a.post(_url('service_edit', service_b.pk), _service_post(name='Hijacked'))

    assert response.status_code == 404
    service_b.refresh_from_db()
    assert service_b.name == original_name


def test_service_delete_view_cross_tenant_pk_is_404_and_row_survives(client_a, service_b):
    response = client_a.post(_url('service_delete', service_b.pk))
    assert response.status_code == 404
    assert Service.objects.filter(pk=service_b.pk).exists()


def test_service_list_view_never_contains_another_tenants_rows(client_a, service_a1, service_b):
    response = client_a.get(_url('service_list'))
    results = list(response.context['services'])
    assert service_a1 in results
    assert service_b not in results


def test_service_create_view_crafted_tenant_field_cannot_assign_another_tenant(
    client_a, tenant_a, tenant_b,
):
    response = client_a.post(
        _url('service_create'), _service_post(name='Ada Service', tenant=str(tenant_b.pk)),
    )

    assert response.status_code == 302
    obj = Service.objects.get(name='Ada Service')
    assert obj.tenant_id == tenant_a.pk


# --------------------------------------------------------------------------- #
# Cross-tenant IDOR — Resource
# --------------------------------------------------------------------------- #

def test_resource_detail_view_cross_tenant_pk_is_404(client_a, resource_b):
    response = client_a.get(_url('resource_detail', resource_b.pk))
    assert response.status_code == 404


def test_resource_edit_view_cross_tenant_pk_is_404(client_a, resource_b):
    response = client_a.get(_url('resource_edit', resource_b.pk))
    assert response.status_code == 404


def test_resource_edit_view_cross_tenant_post_is_404_and_does_not_write(client_a, resource_b):
    original_name = resource_b.name

    response = client_a.post(_url('resource_edit', resource_b.pk), _resource_post(name='Hijacked'))

    assert response.status_code == 404
    resource_b.refresh_from_db()
    assert resource_b.name == original_name


def test_resource_delete_view_cross_tenant_pk_is_404_and_row_survives(client_a, resource_b):
    response = client_a.post(_url('resource_delete', resource_b.pk))
    assert response.status_code == 404
    assert Resource.objects.filter(pk=resource_b.pk).exists()


def test_resource_create_view_crafted_tenant_field_cannot_assign_another_tenant(
    client_a, tenant_a, tenant_b,
):
    response = client_a.post(
        _url('resource_create'), _resource_post(name='Ada Room', tenant=str(tenant_b.pk)),
    )

    assert response.status_code == 302
    obj = Resource.objects.get(name='Ada Room')
    assert obj.tenant_id == tenant_a.pk


# --------------------------------------------------------------------------- #
# Cross-LOCATION isolation — Resource (fully location-scoped)
# --------------------------------------------------------------------------- #

def test_resource_detail_view_cross_location_pk_is_404(client_a, resource_a2):
    """`client_a` active at A1; `resource_a2` belongs to the SAME tenant's A2."""
    response = client_a.get(_url('resource_detail', resource_a2.pk))
    assert response.status_code == 404


def test_resource_edit_view_cross_location_pk_is_404(client_a, resource_a2):
    response = client_a.get(_url('resource_edit', resource_a2.pk))
    assert response.status_code == 404


def test_resource_edit_view_cross_location_post_is_404_and_does_not_write(client_a, resource_a2):
    original_name = resource_a2.name

    response = client_a.post(_url('resource_edit', resource_a2.pk), _resource_post(name='Hijacked'))

    assert response.status_code == 404
    resource_a2.refresh_from_db()
    assert resource_a2.name == original_name


def test_resource_delete_view_cross_location_pk_is_404_and_row_survives(client_a, resource_a2):
    response = client_a.post(_url('resource_delete', resource_a2.pk))
    assert response.status_code == 404
    assert Resource.objects.filter(pk=resource_a2.pk).exists()


def test_resource_list_view_never_contains_another_locations_rows(client_a, resource_a1, resource_a2):
    response = client_a.get(_url('resource_list'))
    results = list(response.context['resources'])
    assert resource_a1 in results
    assert resource_a2 not in results


def test_resource_create_view_crafted_location_field_cannot_pin_another_location(
    client_a, location_a1, location_a2,
):
    """`location` is not a rendered `ResourceForm` field — `TenantLocationModelForm`
    pops it and stamps `request.location` regardless of what a crafted POST
    carries under that key.
    """
    response = client_a.post(
        _url('resource_create'), _resource_post(name='Sneaky Room', location=str(location_a2.pk)),
    )

    assert response.status_code == 302
    obj = Resource.objects.get(name='Sneaky Room')
    assert obj.location_id == location_a1.pk


# --------------------------------------------------------------------------- #
# delete — POST-only
# --------------------------------------------------------------------------- #

def test_service_delete_view_get_is_405_and_row_survives(client_a, service_a1):
    response = client_a.get(_url('service_delete', service_a1.pk))
    assert response.status_code == 405
    assert Service.objects.filter(pk=service_a1.pk).exists()


def test_resource_delete_view_get_is_405_and_row_survives(client_a, resource_a1):
    response = client_a.get(_url('resource_delete', resource_a1.pk))
    assert response.status_code == 405
    assert Resource.objects.filter(pk=resource_a1.pk).exists()


# --------------------------------------------------------------------------- #
# Tier gating — delete is management-tier only; everything else is open to
# staff (front-desk catalogue work).
# --------------------------------------------------------------------------- #

def test_service_delete_view_staff_tier_is_redirected_and_row_survives(member_client, service_a1):
    response = member_client.post(_url('service_delete', service_a1.pk))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    assert Service.objects.filter(pk=service_a1.pk).exists()


def test_resource_delete_view_staff_tier_is_redirected_and_row_survives(member_client, resource_a1):
    response = member_client.post(_url('resource_delete', resource_a1.pk))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    assert Resource.objects.filter(pk=resource_a1.pk).exists()


def test_service_delete_view_manager_tier_is_allowed(tenant_a, location_a1, service_a1):
    client = _manager_assigned_to(tenant_a, location_a1)
    response = client.post(_url('service_delete', service_a1.pk))
    assert response.status_code == 302
    assert not Service.objects.filter(pk=service_a1.pk).exists()


def test_resource_delete_view_manager_tier_is_allowed(tenant_a, location_a1, resource_a1):
    client = _manager_assigned_to(tenant_a, location_a1)
    response = client.post(_url('resource_delete', resource_a1.pk))
    assert response.status_code == 302
    assert not Resource.objects.filter(pk=resource_a1.pk).exists()


def test_service_list_view_is_open_to_staff_tier(member_client, service_a1):
    response = member_client.get(_url('service_list'))
    assert response.status_code == 200


def test_resource_list_view_is_open_to_staff_tier(member_client, resource_a1):
    response = member_client.get(_url('resource_list'))
    assert response.status_code == 200


def test_service_create_view_is_open_to_staff_tier(member_client):
    response = member_client.post(_url('service_create'), _service_post(name='Staff Added'))
    assert response.status_code == 302
    assert Service.objects.filter(name='Staff Added').exists()


def test_resource_create_view_is_open_to_staff_tier(member_client):
    response = member_client.post(_url('resource_create'), _resource_post(name='Staff Room'))
    assert response.status_code == 302
    assert Resource.objects.filter(name='Staff Room').exists()


# --------------------------------------------------------------------------- #
# `service_edit_view` / `service_delete_view` refuse an editor not assigned to
# the service's PINNED location — the new guard alongside 4.2. An all-locations
# service (`location_id is None`) stays editable/deletable by anyone.
# --------------------------------------------------------------------------- #

def test_service_edit_view_get_refuses_when_not_assigned_to_pinned_location(
    member_client, service_a2,
):
    """`member_client` (staff, assigned ONLY to A1) tries to open the edit form
    for a service pinned to A2 — refused before the form is even built.
    """
    response = member_client.get(_url('service_edit', service_a2.pk), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('service_detail', service_a2.pk)
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any('not assigned to that location' in m for m in messages)


def test_service_edit_view_post_refuses_when_not_assigned_to_pinned_location(
    member_client, service_a2,
):
    original_name = service_a2.name

    response = member_client.post(_url('service_edit', service_a2.pk), _service_post(name='Hijacked'))

    assert response.status_code == 302
    assert response.url == _url('service_detail', service_a2.pk)
    service_a2.refresh_from_db()
    assert service_a2.name == original_name


def test_service_delete_view_refuses_when_manager_not_assigned_to_pinned_location(
    tenant_a, location_a1, service_a2,
):
    """A MANAGEMENT-tier user still cannot delete a service pinned to a location
    they are not assigned to — tier alone is not enough.
    """
    client = _manager_assigned_to(tenant_a, location_a1)

    response = client.post(_url('service_delete', service_a2.pk), follow=True)

    assert response.status_code == 200
    assert Service.objects.filter(pk=service_a2.pk).exists()
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any('not assigned to that location' in m for m in messages)


def test_service_edit_view_all_locations_service_stays_editable_by_unassigned_staff(
    member_client, service_all_a,
):
    """An all-locations service (`location_id is None`) belongs to everyone —
    the guard only fires for a PINNED service.
    """
    response = member_client.post(_url('service_edit', service_all_a.pk), _service_post(name='Edited By Staff'))

    assert response.status_code == 302
    service_all_a.refresh_from_db()
    assert service_all_a.name == 'Edited By Staff'


def test_service_delete_view_all_locations_service_stays_deletable(
    tenant_a, location_a1, service_all_a,
):
    client = _manager_assigned_to(tenant_a, location_a1)

    response = client.post(_url('service_delete', service_all_a.pk))

    assert response.status_code == 302
    assert not Service.objects.filter(pk=service_all_a.pk).exists()


def test_service_edit_view_is_allowed_when_the_editor_is_assigned_to_the_pinned_location(
    client_a, service_a2,
):
    """`client_a` (`admin_user`) IS assigned to A2 as well as A1, so editing a
    service pinned to A2 while active at A1 must still succeed — the guard is
    about ASSIGNMENT, not about the currently active location.
    """
    response = client_a.post(_url('service_edit', service_a2.pk), _service_post(
        name='Edited By Admin', location=str(service_a2.location_id),
    ))

    assert response.status_code == 302
    service_a2.refresh_from_db()
    assert service_a2.name == 'Edited By Admin'
