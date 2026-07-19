"""Auth, tenant/location isolation and tier-gating tests for the contact
directory (sub-module 4.1).

`scheduling.Contact` is tenant-scoped but explicitly NOT location-scoped (see
`Contacts.py`'s module docstring), so there is no A1-vs-A2 isolation test here
in the usual sense — that guard is exercised in `test_views.py` against
`_appointments_for` / `_call_sessions_for` instead, the two functions that
actually do carry a location boundary on this page.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.scheduling.models import Contact

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


# --------------------------------------------------------------------------- #
# Anonymous access
# --------------------------------------------------------------------------- #

def test_anonymous_list_redirects_to_login(client):
    response = client.get(_url('contact_list'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_anonymous_create_redirects_to_login(client):
    response = client.get(_url('contact_create'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #

def test_csrf_is_enforced_on_create_post(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)

    response = csrf_client.post(_url('contact_create'), {'first_name': 'Ada'})

    assert response.status_code == 403
    assert not Contact.objects.filter(first_name='Ada').exists()


# --------------------------------------------------------------------------- #
# Cross-tenant IDOR — a Tenant B pk reached through Tenant A's session
# --------------------------------------------------------------------------- #

def test_detail_view_cross_tenant_pk_is_404(client_a, contact_b):
    response = client_a.get(_url('contact_detail', contact_b.pk))
    assert response.status_code == 404


def test_edit_view_cross_tenant_pk_is_404(client_a, contact_b):
    response = client_a.get(_url('contact_edit', contact_b.pk))
    assert response.status_code == 404


def test_edit_view_cross_tenant_post_is_404_and_does_not_write(client_a, contact_b):
    original_name = contact_b.first_name

    response = client_a.post(_url('contact_edit', contact_b.pk), {'first_name': 'Hijacked'})

    assert response.status_code == 404
    contact_b.refresh_from_db()
    assert contact_b.first_name == original_name


def test_delete_view_cross_tenant_pk_is_404_and_row_survives(client_a, contact_b):
    response = client_a.post(_url('contact_delete', contact_b.pk))

    assert response.status_code == 404
    assert Contact.objects.filter(pk=contact_b.pk).exists()


def test_forget_view_cross_tenant_pk_is_404_and_row_survives(client_a, contact_b):
    response = client_a.post(_url('contact_forget', contact_b.pk))

    assert response.status_code == 404
    contact_b.refresh_from_db()
    assert contact_b.is_anonymized is False


def test_list_view_never_contains_another_tenants_rows(client_a, contact_a, contact_b):
    response = client_a.get(_url('contact_list'))
    results = list(response.context['contacts'])

    assert contact_a in results
    assert contact_b not in results


def test_tenant_b_admin_cannot_log_into_tenant_a(client_b, contact_a):
    """`client_b` is tenant B's own, legitimately logged-in session — proves it
    simply never sees tenant A's directory, the other half of isolation.
    """
    response = client_b.get(_url('contact_list'))
    results = list(response.context['contacts'])
    assert contact_a not in results


def test_create_view_crafted_tenant_field_cannot_assign_another_tenant(
    client_a, tenant_a, tenant_b,
):
    """`tenant` is not a form field, so a crafted POST carrying tenant B's pk
    under that key is simply ignored — the object is always stamped with the
    REQUEST's tenant.
    """
    response = client_a.post(_url('contact_create'), {
        'first_name': 'Ada', 'tenant': str(tenant_b.pk),
    })

    assert response.status_code == 302
    obj = Contact.objects.get(first_name='Ada')
    assert obj.tenant_id == tenant_a.pk


# --------------------------------------------------------------------------- #
# delete / forget — POST-only
# --------------------------------------------------------------------------- #

def test_delete_view_get_is_405_and_row_survives(client_a, contact_a):
    response = client_a.get(_url('contact_delete', contact_a.pk))

    assert response.status_code == 405
    assert Contact.objects.filter(pk=contact_a.pk).exists()


def test_forget_view_get_is_405_and_row_survives(client_a, contact_a):
    response = client_a.get(_url('contact_forget', contact_a.pk))

    assert response.status_code == 405
    contact_a.refresh_from_db()
    assert contact_a.is_anonymized is False


# --------------------------------------------------------------------------- #
# Tier gating — delete/forget are management-tier only; everything else is
# open to staff, which is a deliberate product decision (front-desk work).
# --------------------------------------------------------------------------- #

def test_delete_view_staff_tier_is_redirected_and_row_survives(member_client, contact_a):
    response = member_client.post(_url('contact_delete', contact_a.pk))

    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    assert Contact.objects.filter(pk=contact_a.pk).exists()


def test_forget_view_staff_tier_is_redirected_and_row_survives(member_client, contact_a):
    response = member_client.post(_url('contact_forget', contact_a.pk))

    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    contact_a.refresh_from_db()
    assert contact_a.is_anonymized is False


def test_list_view_is_open_to_staff_tier(member_client, contact_a):
    response = member_client.get(_url('contact_list'))
    assert response.status_code == 200
    assert list(response.context['contacts']) == [contact_a]


def test_detail_view_is_open_to_staff_tier(member_client, contact_a):
    response = member_client.get(_url('contact_detail', contact_a.pk))
    assert response.status_code == 200


def test_create_view_is_open_to_staff_tier(member_client):
    response = member_client.post(_url('contact_create'), {'first_name': 'Sam'})

    assert response.status_code == 302
    assert Contact.objects.filter(first_name='Sam').exists()


def test_edit_view_is_open_to_staff_tier(member_client, contact_a):
    response = member_client.post(_url('contact_edit', contact_a.pk), {
        'first_name': 'Edited', 'last_name': contact_a.last_name,
        'phone_e164': contact_a.phone_e164, 'email': contact_a.email,
    })

    assert response.status_code == 302
    contact_a.refresh_from_db()
    assert contact_a.first_name == 'Edited'


def test_delete_view_manager_tier_is_allowed(tenant_a, location_a1, contact_a):
    manager = User.objects.create_user(
        tenant=tenant_a, email='manager@acme-test.example', password='pass-1234',
        tier=User.TIER_MANAGER,
    )
    from apps.accounts.models import UserLocation
    UserLocation.objects.create(tenant=tenant_a, user=manager, location=location_a1)

    client = Client()
    client.force_login(manager)

    response = client.post(_url('contact_delete', contact_a.pk))

    assert response.status_code == 302
    assert not Contact.objects.filter(pk=contact_a.pk).exists()
