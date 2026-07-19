"""CRUD, search, pagination and business-rule tests for the contact directory
views (sub-module 4.1).

Cross-tenant/location isolation and tier-gating live in `test_security.py`.
"""
from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.scheduling.models import Contact

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #

def test_list_view_renders_for_tenant_admin(client_a, contact_a):
    response = client_a.get(_url('contact_list'))

    assert response.status_code == 200
    assert 'scheduling/directory/contact/list.html' in [t.name for t in response.templates]
    assert list(response.context['contacts']) == [contact_a]
    assert response.context['total_count'] == 1
    assert response.context['source_choices'] == Contact.SOURCE_CHOICES


def test_list_view_junk_source_filter_degrades_to_200(client_a, contact_a):
    response = client_a.get(_url('contact_list'), {'source': 'not-a-real-source'})

    assert response.status_code == 200
    assert list(response.context['contacts']) == [contact_a]


def test_list_view_valid_source_filter_narrows_results(client_a, tenant_a, make_contact):
    manual = make_contact(tenant_a, first_name='Manual', source=Contact.SOURCE_MANUAL)
    make_contact(tenant_a, first_name='FromCall', source=Contact.SOURCE_AI_PHONE)

    response = client_a.get(_url('contact_list'), {'source': Contact.SOURCE_MANUAL})

    assert response.status_code == 200
    assert list(response.context['contacts']) == [manual]


def test_list_view_page_past_the_end_degrades_to_200(client_a, contact_a):
    response = client_a.get(_url('contact_list'), {'page': '999'})
    assert response.status_code == 200


def test_list_view_junk_page_value_degrades_to_200(client_a, contact_a):
    response = client_a.get(_url('contact_list'), {'page': 'not-a-number'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 1


def test_list_view_page_2_when_rows_exceed_page_size(client_a, tenant_a, make_contact):
    for i in range(30):
        make_contact(tenant_a, first_name=f'Contact{i:02d}')

    response = client_a.get(_url('contact_list'), {'page': '2'})

    assert response.status_code == 200
    assert response.context['page_obj'].number == 2
    assert len(response.context['contacts']) == 5  # 30 rows, 25 per page


def test_list_view_search_by_national_format_finds_stored_e164_row(client_a, tenant_a, make_contact):
    contact = make_contact(tenant_a, first_name='Priya', last_name='Raman', phone_e164='+13125550142')
    other = make_contact(tenant_a, first_name='Someone', last_name='Else', phone_e164='+19995551234')

    response = client_a.get(_url('contact_list'), {'q': '(312) 555-0142'})

    assert response.status_code == 200
    results = list(response.context['contacts'])
    assert results == [contact]
    assert other not in results


def test_list_view_superuser_gets_empty_list_not_an_error(contact_a):
    superuser = User.objects.create_superuser(email='root@navai.example', password='pass-1234')
    client = Client()
    client.force_login(superuser)

    response = client.get(_url('contact_list'))

    assert response.status_code == 200
    assert list(response.context['contacts']) == []


def test_list_view_query_count_does_not_grow_with_row_count(client_a, tenant_a, make_contact):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(3):
        make_contact(tenant_a, first_name=f'Small{i}')
    with CaptureQueriesContext(connection) as small:
        response = client_a.get(_url('contact_list'))
    assert response.status_code == 200

    for i in range(30):
        make_contact(tenant_a, first_name=f'Big{i}')
    with CaptureQueriesContext(connection) as big:
        response = client_a.get(_url('contact_list'))
    assert response.status_code == 200

    # Contact carries no FK relations the template walks, so the query count
    # for 33 rows across two pages must equal the count for 3 rows on one page
    # — any growth means a per-row query crept in (N+1).
    assert len(big.captured_queries) == len(small.captured_queries)


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #

def test_create_view_get_renders_form(client_a):
    response = client_a.get(_url('contact_create'))

    assert response.status_code == 200
    assert 'scheduling/directory/contact/form.html' in [t.name for t in response.templates]
    assert response.context['is_edit'] is False


def test_create_view_saves_with_the_request_tenant(client_a, tenant_a):
    response = client_a.post(_url('contact_create'), {
        'first_name': 'Ada', 'last_name': 'Lovelace', 'phone_e164': '+13125550142',
    })

    assert response.status_code == 302
    obj = Contact.objects.get(first_name='Ada', last_name='Lovelace')
    assert obj.tenant_id == tenant_a.pk


def test_create_view_stamps_source_manual_regardless_of_posted_source(client_a):
    response = client_a.post(_url('contact_create'), {
        'first_name': 'Ada', 'source': Contact.SOURCE_AI_PHONE,
    })

    assert response.status_code == 302
    obj = Contact.objects.get(first_name='Ada')
    assert obj.source == Contact.SOURCE_MANUAL


def test_create_view_warns_about_a_shared_phone_number(client_a, tenant_a, make_contact):
    existing = make_contact(tenant_a, first_name='Dana', phone_e164='+13125550101')

    response = client_a.post(_url('contact_create'), {
        'first_name': 'Marcus', 'phone_e164': '312-555-0101',
    }, follow=True)

    assert response.status_code == 200
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any('also on file for' in m and existing.display_name in m for m in messages)


def test_create_view_invalid_submission_rerenders_form_with_errors(client_a):
    response = client_a.post(_url('contact_create'), {})

    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Contact.objects.count() == 0


# --------------------------------------------------------------------------- #
# detail
# --------------------------------------------------------------------------- #

def test_detail_view_renders_for_tenant_admin(client_a, contact_a):
    response = client_a.get(_url('contact_detail', contact_a.pk))

    assert response.status_code == 200
    assert response.context['obj'] == contact_a


def test_detail_view_surfaces_other_contacts_on_the_same_number(client_a, tenant_a, make_contact):
    dana = make_contact(tenant_a, first_name='Dana', phone_e164='+13125550101')
    marcus = make_contact(tenant_a, first_name='Marcus', phone_e164='+13125550101')

    response = client_a.get(_url('contact_detail', dana.pk))

    assert list(response.context['also_on_this_number']) == [marcus]


# --------------------------------------------------------------------------- #
# location-scoping regression guard (mandatory per sub-module 4.1 spec)
# --------------------------------------------------------------------------- #

def test_contact_detail_appointments_are_scoped_to_visible_locations(
    client_a, contact_a, member_user, location_a1, location_a2, service_all_a,
):
    """THE cross-location assertion the 4.1 TODO marker asked for.

    `scheduling.Appointment` now exists, so `_visible_location_ids()` is finally
    testable: a user assigned ONLY to location A1 must see this contact's A1
    booking on the contact page and must NOT see their A2 one. The contact row
    itself is business-wide; the location-scoped records hanging off it are not.

    (`calls.CallSession` is still unbuilt, so `call_sessions` stays `None` —
    replace that half when Module 5 lands.)
    """
    from django.utils import timezone as dj_timezone

    from apps.accounts.models import UserLocation
    from apps.scheduling.models import Appointment

    start = dj_timezone.now() + timedelta(days=3)
    here = Appointment.objects.create(
        tenant=contact_a.tenant, location=location_a1, contact=contact_a,
        service=service_all_a, start_at=start,
        end_at=start + timedelta(minutes=30), reason='visible one',
    )
    elsewhere = Appointment.objects.create(
        tenant=contact_a.tenant, location=location_a2, contact=contact_a,
        service=service_all_a, start_at=start,
        end_at=start + timedelta(minutes=30), reason='hidden one',
    )

    # Narrow the member to A1 only, then look at the contact page as them.
    UserLocation.objects.filter(user=member_user).exclude(
        location=location_a1
    ).delete()
    UserLocation.objects.get_or_create(
        user=member_user, tenant=member_user.tenant, location=location_a1
    )

    client = Client()
    client.force_login(member_user)
    client.post(reverse('accounts:switch_location'), {'location': location_a1.pk})

    response = client.get(_url('contact_detail', contact_a.pk))
    assert response.status_code == 200

    visible = list(response.context['appointments'])
    assert here in visible
    assert elsewhere not in visible, (
        'An appointment at a location this user is not assigned to leaked onto '
        'the contact page.'
    )
    assert response.context['call_sessions'] is None


def test_private_location_guard_function_filters_by_assignment(
    rf, member_user, contact_a, location_a1, location_a2, service_all_a,
):
    """Same guard as a plain function call, independent of template rendering."""
    from django.utils import timezone as dj_timezone

    from apps.accounts.models import UserLocation
    from apps.scheduling.models import Appointment
    from apps.scheduling.views.ContactDirectory.Contacts import (
        _appointments_for,
        _call_sessions_for,
    )

    start = dj_timezone.now() + timedelta(days=4)
    here = Appointment.objects.create(
        tenant=contact_a.tenant, location=location_a1, contact=contact_a,
        service=service_all_a, start_at=start,
        end_at=start + timedelta(minutes=30),
    )
    elsewhere = Appointment.objects.create(
        tenant=contact_a.tenant, location=location_a2, contact=contact_a,
        service=service_all_a, start_at=start,
        end_at=start + timedelta(minutes=30),
    )

    UserLocation.objects.filter(user=member_user).exclude(
        location=location_a1
    ).delete()
    UserLocation.objects.get_or_create(
        user=member_user, tenant=member_user.tenant, location=location_a1
    )

    request = rf.get('/')
    request.user = member_user

    visible = list(_appointments_for(contact_a, request))
    assert here in visible
    assert elsewhere not in visible

    # Module 5 is still unbuilt, so this half stays import-guarded.
    assert _call_sessions_for(contact_a, request) is None


# --------------------------------------------------------------------------- #
# edit
# --------------------------------------------------------------------------- #

def test_edit_view_get_renders_prefilled_form(client_a, contact_a):
    response = client_a.get(_url('contact_edit', contact_a.pk))

    assert response.status_code == 200
    assert response.context['is_edit'] is True
    assert response.context['form'].instance == contact_a


def test_edit_view_saves_changes(client_a, contact_a):
    response = client_a.post(_url('contact_edit', contact_a.pk), {
        'first_name': 'Updated', 'last_name': contact_a.last_name,
        'phone_e164': contact_a.phone_e164, 'email': contact_a.email,
    })

    assert response.status_code == 302
    contact_a.refresh_from_db()
    assert contact_a.first_name == 'Updated'


def test_edit_view_refuses_an_anonymized_contact(client_a, tenant_a, make_contact):
    contact = make_contact(tenant_a, first_name='Ada')
    contact.anonymize()

    response = client_a.get(_url('contact_edit', contact.pk), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('contact_detail', contact.pk)
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any('cannot be edited' in m for m in messages)

    # Nothing about the erased row changed.
    contact.refresh_from_db()
    assert contact.is_anonymized is True
    assert contact.first_name == ''


# --------------------------------------------------------------------------- #
# delete / forget — happy path for a management-tier user
# (POST-only + tier-gating negative cases live in test_security.py)
# --------------------------------------------------------------------------- #

def test_delete_view_removes_the_row(client_a, contact_a):
    pk = contact_a.pk

    response = client_a.post(_url('contact_delete', pk))

    assert response.status_code == 302
    assert response.url == _url('contact_list')
    assert not Contact.objects.filter(pk=pk).exists()


def test_forget_view_anonymizes_without_deleting(client_a, contact_a):
    response = client_a.post(_url('contact_forget', contact_a.pk))

    assert response.status_code == 302
    contact_a.refresh_from_db()
    assert contact_a.is_anonymized is True
    assert Contact.objects.filter(pk=contact_a.pk).exists()


def test_forget_view_twice_is_a_no_op_second_time(client_a, contact_a):
    client_a.post(_url('contact_forget', contact_a.pk))
    contact_a.refresh_from_db()
    first_timestamp = contact_a.anonymized_at

    response = client_a.post(_url('contact_forget', contact_a.pk))

    assert response.status_code == 302
    contact_a.refresh_from_db()
    assert contact_a.anonymized_at == first_timestamp
