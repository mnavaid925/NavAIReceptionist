"""Auth, tenant/location isolation and tier-gating tests for `Appointment`
(sub-module 4.3).

Mirrors `test_catalog_security.py`'s structure and conventions.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User, UserLocation
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


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

@pytest.mark.parametrize('name', [
    'appointment_list', 'appointment_create', 'appointment_slots',
])
def test_anonymous_get_redirects_to_login(client, name):
    response = client.get(_url(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #

def test_csrf_is_enforced_on_appointment_create_post(admin_user, contact_a, service_all_a):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)

    response = csrf_client.post(_url('appointment_create'), {
        'contact': str(contact_a.pk), 'service': str(service_all_a.pk),
        'status': Appointment.STATUS_SCHEDULED,
        'start_at': '2030-01-01T10:00',
    })

    assert response.status_code == 403
    assert Appointment.objects.count() == 0


# --------------------------------------------------------------------------- #
# Cross-tenant IDOR
# --------------------------------------------------------------------------- #

def test_detail_view_cross_tenant_pk_is_404(client_a, tenant_b, location_b1, contact_b, make_appointment):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    response = client_a.get(_url('appointment_detail', appt.pk))
    assert response.status_code == 404


def test_edit_view_get_cross_tenant_pk_is_404(client_a, tenant_b, location_b1, contact_b, make_appointment):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    response = client_a.get(_url('appointment_edit', appt.pk))
    assert response.status_code == 404


def test_edit_view_post_cross_tenant_pk_is_404_and_does_not_write(
    client_a, tenant_b, location_b1, contact_b, make_appointment,
):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    original_reason = appt.reason

    response = client_a.post(_url('appointment_edit', appt.pk), {
        'contact': str(contact_b.pk), 'status': Appointment.STATUS_SCHEDULED,
        'start_at': '2030-01-01T10:00', 'reason': 'Hijacked',
    })

    assert response.status_code == 404
    appt.refresh_from_db()
    assert appt.reason == original_reason


def test_delete_view_cross_tenant_pk_is_404_and_row_survives(client_a, tenant_b, location_b1, contact_b, make_appointment):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    response = client_a.post(_url('appointment_delete', appt.pk))
    assert response.status_code == 404
    assert Appointment.objects.filter(pk=appt.pk).exists()


def test_reschedule_view_cross_tenant_pk_is_404(client_a, tenant_b, location_b1, contact_b, make_appointment):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    response = client_a.post(_url('appointment_reschedule', appt.pk), {'token': 'irrelevant'})
    assert response.status_code == 404


def test_cancel_view_cross_tenant_pk_is_404_and_row_survives(client_a, tenant_b, location_b1, contact_b, make_appointment):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    response = client_a.post(_url('appointment_cancel', appt.pk), {'reason': 'nope'})
    assert response.status_code == 404
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_SCHEDULED


def test_mark_view_cross_tenant_pk_is_404_and_row_survives(client_a, tenant_b, location_b1, contact_b, make_appointment):
    appt = make_appointment(tenant_b, location_b1, contact_b, status=Appointment.STATUS_SCHEDULED)
    response = client_a.post(_url('appointment_mark', appt.pk, 'completed'))
    assert response.status_code == 404
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_SCHEDULED


def test_list_view_never_contains_another_tenants_rows(
    client_a, tenant_a, tenant_b, location_a1, location_b1, contact_a, contact_b, make_appointment,
):
    mine = make_appointment(tenant_a, location_a1, contact_a)
    theirs = make_appointment(tenant_b, location_b1, contact_b)

    response = client_a.get(_url('appointment_list'))
    results = list(response.context['appointments'])
    assert mine in results
    assert theirs not in results


def test_create_view_crafted_contact_from_another_tenant_is_rejected(
    client_a, tenant_a, contact_b, service_all_a,
):
    response = client_a.post(_url('appointment_create'), {
        'contact': str(contact_b.pk), 'service': str(service_all_a.pk),
        'status': Appointment.STATUS_SCHEDULED, 'start_at': '2030-01-01T10:00',
    })

    assert response.status_code == 200  # re-rendered with a form error, not saved
    assert not response.context['form'].is_valid()
    assert Appointment.objects.count() == 0


def test_create_view_crafted_tenant_field_cannot_assign_another_tenant(
    client_a, tenant_a, tenant_b, contact_a, service_all_a,
):
    response = client_a.post(_url('appointment_create'), {
        'contact': str(contact_a.pk), 'service': str(service_all_a.pk),
        'status': Appointment.STATUS_SCHEDULED, 'start_at': '2030-01-01T10:00',
        'tenant': str(tenant_b.pk),
    })

    assert response.status_code == 302
    obj = Appointment.objects.get(contact=contact_a)
    assert obj.tenant_id == tenant_a.pk


# --------------------------------------------------------------------------- #
# Cross-LOCATION isolation — Appointment is fully location-scoped
# --------------------------------------------------------------------------- #

def test_detail_view_cross_location_pk_is_404(client_a, tenant_a, location_a2, contact_a, make_appointment):
    """`client_a` active at A1; the appointment belongs to the SAME tenant's A2."""
    appt = make_appointment(tenant_a, location_a2, contact_a)
    response = client_a.get(_url('appointment_detail', appt.pk))
    assert response.status_code == 404


def test_edit_view_get_cross_location_pk_is_404(client_a, tenant_a, location_a2, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a2, contact_a)
    response = client_a.get(_url('appointment_edit', appt.pk))
    assert response.status_code == 404


def test_edit_view_post_cross_location_pk_is_404_and_does_not_write(
    client_a, tenant_a, location_a2, contact_a, make_appointment,
):
    appt = make_appointment(tenant_a, location_a2, contact_a)
    original_reason = appt.reason

    response = client_a.post(_url('appointment_edit', appt.pk), {
        'contact': str(contact_a.pk), 'status': Appointment.STATUS_SCHEDULED,
        'start_at': '2030-01-01T10:00', 'reason': 'Hijacked',
    })

    assert response.status_code == 404
    appt.refresh_from_db()
    assert appt.reason == original_reason


def test_delete_view_cross_location_pk_is_404_and_row_survives(client_a, tenant_a, location_a2, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a2, contact_a)
    response = client_a.post(_url('appointment_delete', appt.pk))
    assert response.status_code == 404
    assert Appointment.objects.filter(pk=appt.pk).exists()


def test_reschedule_view_cross_location_pk_is_404(client_a, tenant_a, location_a2, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a2, contact_a)
    response = client_a.post(_url('appointment_reschedule', appt.pk), {'token': 'irrelevant'})
    assert response.status_code == 404


def test_cancel_view_cross_location_pk_is_404_and_row_survives(client_a, tenant_a, location_a2, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a2, contact_a)
    response = client_a.post(_url('appointment_cancel', appt.pk), {'reason': 'nope'})
    assert response.status_code == 404
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_SCHEDULED


def test_mark_view_cross_location_pk_is_404_and_row_survives(client_a, tenant_a, location_a2, contact_a, make_appointment):
    """`client_a` active at A1; the appointment belongs to the SAME tenant's A2."""
    appt = make_appointment(tenant_a, location_a2, contact_a, status=Appointment.STATUS_SCHEDULED)
    response = client_a.post(_url('appointment_mark', appt.pk, 'completed'))
    assert response.status_code == 404
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_SCHEDULED


def test_list_view_never_contains_another_locations_rows(
    client_a, tenant_a, location_a1, location_a2, contact_a, make_appointment,
):
    here = make_appointment(tenant_a, location_a1, contact_a)
    elsewhere = make_appointment(tenant_a, location_a2, contact_a)

    response = client_a.get(_url('appointment_list'))
    results = list(response.context['appointments'])
    assert here in results
    assert elsewhere not in results


def test_create_view_crafted_resource_from_another_location_is_rejected(
    client_a, tenant_a, contact_a, service_all_a, resource_a2,
):
    """`resource_a2` belongs to the SAME tenant's A2 — `client_a` is active at
    A1, so it must not be a selectable choice on the form.
    """
    response = client_a.post(_url('appointment_create'), {
        'contact': str(contact_a.pk), 'service': str(service_all_a.pk),
        'resource': str(resource_a2.pk),
        'status': Appointment.STATUS_SCHEDULED, 'start_at': '2030-01-01T10:00',
    })

    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Appointment.objects.count() == 0


def test_create_view_crafted_provider_from_another_location_is_rejected(
    client_a, tenant_a, contact_a, service_all_a, location_a2, make_provider,
):
    provider_a2 = make_provider(tenant_a, location_a2, email='provider.a2@acme-test.example')

    response = client_a.post(_url('appointment_create'), {
        'contact': str(contact_a.pk), 'service': str(service_all_a.pk),
        'provider': str(provider_a2.pk),
        'status': Appointment.STATUS_SCHEDULED, 'start_at': '2030-01-01T10:00',
    })

    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Appointment.objects.count() == 0


def test_create_view_crafted_location_field_cannot_pin_another_location(
    client_a, tenant_a, location_a1, location_a2, contact_a, service_all_a,
):
    response = client_a.post(_url('appointment_create'), {
        'contact': str(contact_a.pk), 'service': str(service_all_a.pk),
        'status': Appointment.STATUS_SCHEDULED, 'start_at': '2030-01-01T10:00',
        'location': str(location_a2.pk),
    })

    assert response.status_code == 302
    obj = Appointment.objects.get(contact=contact_a)
    assert obj.location_id == location_a1.pk


# --------------------------------------------------------------------------- #
# delete — POST-only
# --------------------------------------------------------------------------- #

def test_delete_view_get_is_405_and_row_survives(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_delete', appt.pk))
    assert response.status_code == 405
    assert Appointment.objects.filter(pk=appt.pk).exists()


# --------------------------------------------------------------------------- #
# Tier gating — delete is management-tier only
# --------------------------------------------------------------------------- #

def test_delete_view_staff_tier_is_redirected_and_row_survives(member_client, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    response = member_client.post(_url('appointment_delete', appt.pk))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    assert Appointment.objects.filter(pk=appt.pk).exists()


def test_delete_view_manager_tier_is_allowed(tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    client = _manager_assigned_to(tenant_a, location_a1)

    response = client.post(_url('appointment_delete', appt.pk))

    assert response.status_code == 302
    assert not Appointment.objects.filter(pk=appt.pk).exists()


def test_list_view_is_open_to_staff_tier(member_client, tenant_a, location_a1, contact_a, make_appointment):
    make_appointment(tenant_a, location_a1, contact_a)
    response = member_client.get(_url('appointment_list'))
    assert response.status_code == 200


def test_create_view_is_open_to_staff_tier(member_client, tenant_a, contact_a, service_all_a):
    response = member_client.post(_url('appointment_create'), {
        'contact': str(contact_a.pk), 'service': str(service_all_a.pk),
        'status': Appointment.STATUS_SCHEDULED, 'start_at': '2030-01-01T10:00',
    })
    assert response.status_code == 302
    assert Appointment.objects.filter(contact=contact_a).exists()
