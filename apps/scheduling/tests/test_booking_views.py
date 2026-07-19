"""CRUD, search, filter, pagination and availability-search view tests for
`Appointment` (sub-module 4.3).

Cross-tenant/location isolation and tier-gating live in `test_booking_security.py`.
Service-layer (`availability.py`) behaviour called directly lives in
`test_booking_availability.py`.
"""
from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse
from django.utils import timezone as dj_timezone

from apps.scheduling.availability import mint_slot_token
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


def _appointment_post(**overrides):
    start = dj_timezone.now() + timedelta(days=2)
    data = {
        'status': Appointment.STATUS_SCHEDULED,
        'start_at': start.strftime('%Y-%m-%dT%H:%M'),
        'reason': '',
        'notes': '',
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# appointment_list_view
# --------------------------------------------------------------------------- #

def test_list_view_renders_for_tenant_admin(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)

    response = client_a.get(_url('appointment_list'))

    assert response.status_code == 200
    assert 'scheduling/bookings/appointment/list.html' in [t.name for t in response.templates]
    assert list(response.context['appointments']) == [appt]
    assert response.context['total_count'] == 1


def test_list_view_search_by_contact_name(client_a, tenant_a, location_a1, make_contact, make_appointment):
    match_contact = make_contact(tenant_a, first_name='Priya', last_name='Raman')
    other_contact = make_contact(tenant_a, first_name='Theo', last_name='Nakamura')
    match = make_appointment(tenant_a, location_a1, match_contact)
    make_appointment(tenant_a, location_a1, other_contact)

    response = client_a.get(_url('appointment_list'), {'q': 'priya'})

    assert list(response.context['appointments']) == [match]


def test_list_view_search_by_reason(client_a, tenant_a, location_a1, contact_a, make_appointment):
    match = make_appointment(tenant_a, location_a1, contact_a, reason='Follow-up visit')
    make_appointment(tenant_a, location_a1, contact_a, reason='Unrelated')

    response = client_a.get(_url('appointment_list'), {'q': 'follow-up'})

    assert list(response.context['appointments']) == [match]


def test_list_view_status_filter(client_a, tenant_a, location_a1, contact_a, make_appointment):
    scheduled = make_appointment(tenant_a, location_a1, contact_a, status=Appointment.STATUS_SCHEDULED)
    make_appointment(tenant_a, location_a1, contact_a, status=Appointment.STATUS_COMPLETED)

    response = client_a.get(_url('appointment_list'), {'status': 'scheduled'})

    assert list(response.context['appointments']) == [scheduled]


def test_list_view_junk_status_filter_degrades_to_200(client_a, tenant_a, location_a1, contact_a, make_appointment):
    make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_list'), {'status': 'not-a-real-status'})
    assert response.status_code == 200
    assert len(response.context['appointments']) == 1


@pytest.mark.parametrize('param', ['provider', 'service', 'resource'])
def test_list_view_junk_fk_filter_degrades_to_200_not_500(
    client_a, tenant_a, location_a1, contact_a, make_appointment, param,
):
    make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_list'), {param: 'abc'})
    assert response.status_code == 200
    assert len(response.context['appointments']) == 1


@pytest.mark.parametrize('junk', ['²', '１'])
def test_list_view_unicode_digit_filter_does_not_500(client_a, tenant_a, location_a1, contact_a, make_appointment, junk):
    make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_list'), {'provider': junk})
    assert response.status_code == 200


def test_list_view_page_past_the_end_degrades_to_200(client_a, tenant_a, location_a1, contact_a, make_appointment):
    make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_list'), {'page': '999'})
    assert response.status_code == 200


def test_list_view_page_2_when_rows_exceed_page_size(client_a, tenant_a, location_a1, contact_a, make_appointment):
    for i in range(30):
        make_appointment(tenant_a, location_a1, contact_a, start_at=dj_timezone.now() + timedelta(days=i + 1))

    response = client_a.get(_url('appointment_list'), {'page': '2'})

    assert response.status_code == 200
    assert response.context['page_obj'].number == 2
    assert len(response.context['appointments']) == 5


def test_list_view_query_count_does_not_grow_with_row_count(client_a, tenant_a, location_a1, contact_a, make_appointment):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(3):
        make_appointment(tenant_a, location_a1, contact_a, start_at=dj_timezone.now() + timedelta(days=i + 1))
    with CaptureQueriesContext(connection) as small:
        response = client_a.get(_url('appointment_list'))
    assert response.status_code == 200

    for i in range(3, 30):
        make_appointment(tenant_a, location_a1, contact_a, start_at=dj_timezone.now() + timedelta(days=i + 1))
    with CaptureQueriesContext(connection) as big:
        response = client_a.get(_url('appointment_list'))
    assert response.status_code == 200

    assert len(big.captured_queries) == len(small.captured_queries)


# --------------------------------------------------------------------------- #
# appointment_create_view
# --------------------------------------------------------------------------- #

def test_create_view_get_renders_form(client_a):
    response = client_a.get(_url('appointment_create'))
    assert response.status_code == 200
    assert 'scheduling/bookings/appointment/form.html' in [t.name for t in response.templates]
    assert response.context['is_edit'] is False


def test_create_view_saves_with_tenant_and_active_location(client_a, tenant_a, location_a1, contact_a, service_all_a):
    response = client_a.post(
        _url('appointment_create'),
        _appointment_post(contact=str(contact_a.pk), service=str(service_all_a.pk)),
    )

    assert response.status_code == 302
    obj = Appointment.objects.get(contact=contact_a)
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk
    assert obj.source == Appointment.SOURCE_MANUAL


def test_create_view_invalid_submission_rerenders_form_with_errors(client_a):
    response = client_a.post(_url('appointment_create'), {'status': Appointment.STATUS_SCHEDULED})
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Appointment.objects.count() == 0


def test_create_view_refuses_without_an_active_location(admin_user, contact_a, service_all_a):
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        _url('appointment_create'),
        _appointment_post(contact=str(contact_a.pk), service=str(service_all_a.pk)),
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('appointment_list')
    assert Appointment.objects.count() == 0


# --------------------------------------------------------------------------- #
# appointment_detail_view
# --------------------------------------------------------------------------- #

def test_detail_view_renders_for_tenant_admin(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_detail', appt.pk))
    assert response.status_code == 200
    assert response.context['obj'] == appt
    assert 'cancel_form' in response.context


# --------------------------------------------------------------------------- #
# appointment_edit_view
# --------------------------------------------------------------------------- #

def test_edit_view_get_renders_prefilled_form(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_edit', appt.pk))
    assert response.status_code == 200
    assert response.context['is_edit'] is True
    assert response.context['form'].instance == appt


def test_edit_view_saves_changes(client_a, tenant_a, location_a1, contact_a, service_all_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a)
    response = client_a.post(
        _url('appointment_edit', appt.pk),
        _appointment_post(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            reason='Updated reason', start_at=appt.start_at.strftime('%Y-%m-%dT%H:%M'),
        ),
    )
    assert response.status_code == 302
    appt.refresh_from_db()
    assert appt.reason == 'Updated reason'


# -- review finding 1: the status guard --------------------------------------#

@pytest.mark.parametrize('status', [
    Appointment.STATUS_COMPLETED, Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW,
])
def test_edit_view_get_redirects_away_for_a_non_open_appointment(
    client_a, tenant_a, location_a1, contact_a, make_appointment, status,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, status=status)

    response = client_a.get(_url('appointment_edit', appt.pk), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('appointment_detail', appt.pk)
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any('no longer be changed' in m for m in messages)


@pytest.mark.parametrize('status', [
    Appointment.STATUS_COMPLETED, Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW,
])
def test_edit_view_direct_post_does_not_reopen_a_non_open_appointment(
    client_a, tenant_a, location_a1, contact_a, service_all_a, make_appointment, status,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a, status=status)
    original_status = appt.status

    response = client_a.post(
        _url('appointment_edit', appt.pk),
        _appointment_post(
            contact=str(contact_a.pk), service=str(service_all_a.pk),
            status=Appointment.STATUS_SCHEDULED,
            start_at=appt.start_at.strftime('%Y-%m-%dT%H:%M'),
        ),
    )

    assert response.status_code == 302
    assert response.url == _url('appointment_detail', appt.pk)
    appt.refresh_from_db()
    assert appt.status == original_status


def test_edit_view_open_appointment_is_editable(client_a, tenant_a, location_a1, contact_a, service_all_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a, status=Appointment.STATUS_SCHEDULED)
    response = client_a.get(_url('appointment_edit', appt.pk))
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# appointment_slots_view
# --------------------------------------------------------------------------- #

def test_slots_view_refuses_without_an_active_location(admin_user, tenant_a, service_all_a):
    client = Client()
    client.force_login(admin_user)

    response = client.get(_url('appointment_slots'), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('appointment_list')


def test_slots_view_without_a_service_does_not_search(client_a):
    response = client_a.get(_url('appointment_slots'))
    assert response.status_code == 200
    assert response.context['searched'] is False
    assert response.context['slots'] == []


def test_slots_view_with_a_service_and_provider_returns_slots(client_a, service_all_a, provider_a1):
    response = client_a.get(
        _url('appointment_slots'), {'service': str(service_all_a.pk), 'provider': str(provider_a1.pk)},
    )
    assert response.status_code == 200
    assert response.context['searched'] is True
    assert len(response.context['slots']) > 0
    slot = response.context['slots'][0]
    assert slot['provider'] == provider_a1
    assert 'token' in slot


@pytest.mark.parametrize('param', ['service', 'provider', 'resource'])
def test_slots_view_junk_fk_param_degrades_to_200(client_a, param):
    response = client_a.get(_url('appointment_slots'), {param: 'not-a-pk'})
    assert response.status_code == 200


@pytest.mark.parametrize('junk', ['²', '１'])
def test_slots_view_unicode_digit_param_does_not_500(client_a, junk):
    response = client_a.get(_url('appointment_slots'), {'service': junk})
    assert response.status_code == 200


def test_slots_view_reschedule_mode_puts_rescheduling_in_context(
    client_a, tenant_a, location_a1, contact_a, service_all_a, provider_a1, make_appointment,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a)

    response = client_a.get(
        _url('appointment_slots'),
        {'reschedule': str(appt.pk), 'service': str(service_all_a.pk), 'provider': str(provider_a1.pk)},
    )

    assert response.status_code == 200
    assert response.context['rescheduling'] == appt
    # Slots must be present for the form-with-the-reschedule-action to render at
    # all — the form lives INSIDE the per-slot loop in the template.
    assert len(response.context['slots']) > 0
    reschedule_url = _url('appointment_reschedule', appt.pk)
    assert reschedule_url.encode() in response.content


def test_slots_view_reschedule_mode_with_a_closed_appointment_redirects_to_detail(
    client_a, tenant_a, location_a1, contact_a, make_appointment,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, status=Appointment.STATUS_COMPLETED)

    response = client_a.get(_url('appointment_slots'), {'reschedule': str(appt.pk)}, follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('appointment_detail', appt.pk)


# --------------------------------------------------------------------------- #
# appointment_book_view
# --------------------------------------------------------------------------- #

def test_book_view_valid_token_books_the_appointment(client_a, tenant_a, location_a1, contact_a, service_all_a):
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )

    response = client_a.post(
        _url('appointment_book'), {'token': token, 'contact': str(contact_a.pk), 'reason': ''},
    )

    assert response.status_code == 302
    obj = Appointment.objects.get(tenant=tenant_a, contact=contact_a)
    assert obj.start_at == start
    assert response.url == _url('appointment_detail', obj.pk)


def test_book_view_missing_contact_redirects_to_slots_with_an_error(client_a, tenant_a, location_a1, service_all_a):
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )

    response = client_a.post(_url('appointment_book'), {'token': token, 'reason': ''}, follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('appointment_slots')
    assert Appointment.objects.count() == 0


def test_book_view_invalid_token_redirects_to_slots_with_an_error_and_books_nothing(client_a, contact_a):
    response = client_a.post(
        _url('appointment_book'), {'token': 'garbage', 'contact': str(contact_a.pk)}, follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('appointment_slots')
    assert Appointment.objects.count() == 0


def test_book_view_get_is_405(client_a):
    response = client_a.get(_url('appointment_book'))
    assert response.status_code == 405


# --------------------------------------------------------------------------- #
# appointment_reschedule_view — review finding 6
# --------------------------------------------------------------------------- #

def test_reschedule_view_moves_the_appointment_without_duplicating_it(
    client_a, tenant_a, location_a1, contact_a, service_all_a, make_appointment,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a)
    original_pk = appt.pk
    before_count = Appointment.objects.count()
    new_start = dj_timezone.now() + timedelta(days=6)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=new_start, service_id=service_all_a.pk,
    )

    response = client_a.post(_url('appointment_reschedule', appt.pk), {'token': token})

    assert response.status_code == 302
    assert Appointment.objects.count() == before_count
    appt.refresh_from_db()
    assert appt.pk == original_pk
    assert appt.start_at == new_start


def test_reschedule_view_invalid_token_redirects_back_to_slots_in_reschedule_mode(
    client_a, tenant_a, location_a1, contact_a, service_all_a, make_appointment,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a)
    original_start = appt.start_at

    response = client_a.post(_url('appointment_reschedule', appt.pk), {'token': 'garbage'})

    assert response.status_code == 302
    assert response.url.startswith(_url('appointment_slots'))
    assert f'reschedule={appt.pk}' in response.url
    appt.refresh_from_db()
    assert appt.start_at == original_start


def test_reschedule_view_get_is_405(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_reschedule', appt.pk))
    assert response.status_code == 405


# --------------------------------------------------------------------------- #
# appointment_cancel_view
# --------------------------------------------------------------------------- #

def test_cancel_view_cancels_with_a_reason(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)

    response = client_a.post(_url('appointment_cancel', appt.pk), {'reason': 'Caller cancelled'})

    assert response.status_code == 302
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_CANCELLED
    assert appt.cancellation_reason == 'Caller cancelled'


def test_cancel_view_refuses_an_already_closed_appointment(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a, status=Appointment.STATUS_COMPLETED)

    response = client_a.post(_url('appointment_cancel', appt.pk), {'reason': 'Too late'}, follow=True)

    assert response.status_code == 200
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_COMPLETED


def test_cancel_view_get_is_405(client_a, tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    response = client_a.get(_url('appointment_cancel', appt.pk))
    assert response.status_code == 405
