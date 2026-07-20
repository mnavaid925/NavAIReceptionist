"""CRUD, search, filter, pagination and resolve view tests for `CallbackRequest`
(sub-module 4.5).

Cross-tenant/location isolation and tier-gating live in `test_callback_security.py`.
Model behaviour and the erasure cascade live in `test_callback_models.py`.
"""
import pytest
from django.test import Client
from django.urls import reverse

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


# --------------------------------------------------------------------------- #
# callbackrequest_list_view
# --------------------------------------------------------------------------- #

def test_list_view_renders_for_tenant_admin(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)

    response = client_a.get(_url('callbackrequest_list'))

    assert response.status_code == 200
    assert 'scheduling/callbacks/callbackrequest/list.html' in [t.name for t in response.templates]
    assert list(response.context['callback_requests']) == [cb]
    assert response.context['total_count'] == 1


def test_list_view_search_by_caller_name(client_a, tenant_a, location_a1, make_callback):
    match = make_callback(tenant_a, location_a1, caller_name='Priya Raman')
    make_callback(tenant_a, location_a1, caller_name='Theo Nakamura')

    response = client_a.get(_url('callbackrequest_list'), {'q': 'priya'})

    assert list(response.context['callback_requests']) == [match]


def test_list_view_search_by_caller_phone(client_a, tenant_a, location_a1, make_callback):
    match = make_callback(tenant_a, location_a1, caller_phone='+13125550142')
    make_callback(tenant_a, location_a1, caller_phone='+15035550210')

    response = client_a.get(_url('callbackrequest_list'), {'q': '5550142'})

    assert list(response.context['callback_requests']) == [match]


def test_list_view_search_by_reason(client_a, tenant_a, location_a1, make_callback):
    match = make_callback(tenant_a, location_a1, reason='Follow-up on prescription')
    make_callback(tenant_a, location_a1, reason='Unrelated')

    response = client_a.get(_url('callbackrequest_list'), {'q': 'follow-up'})

    assert list(response.context['callback_requests']) == [match]


def test_list_view_search_by_linked_contact_name(client_a, tenant_a, location_a1, contact_a, make_callback):
    match = make_callback(tenant_a, location_a1, contact=contact_a, caller_name='')
    make_callback(tenant_a, location_a1, caller_name='Someone Else')

    response = client_a.get(_url('callbackrequest_list'), {'q': contact_a.first_name})

    assert list(response.context['callback_requests']) == [match]


# -- the subtle one: absent / empty / explicit / junk `status` ----------------#

def test_list_view_status_absent_defaults_to_pending(client_a, tenant_a, location_a1, make_callback):
    pending = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_PENDING)
    make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CLOSED)

    response = client_a.get(_url('callbackrequest_list'))

    assert list(response.context['callback_requests']) == [pending]
    assert response.context['selected_status'] == CallbackRequest.STATUS_PENDING


def test_list_view_status_explicit_empty_returns_all_statuses(client_a, tenant_a, location_a1, make_callback):
    pending = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_PENDING)
    closed = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CLOSED)
    contacted = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CONTACTED)

    response = client_a.get(_url('callbackrequest_list'), {'status': ''})

    results = set(response.context['callback_requests'])
    assert results == {pending, closed, contacted}
    assert response.context['selected_status'] == ''


def test_list_view_status_closed_narrows(client_a, tenant_a, location_a1, make_callback):
    make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_PENDING)
    closed = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CLOSED)

    response = client_a.get(_url('callbackrequest_list'), {'status': 'closed'})

    assert list(response.context['callback_requests']) == [closed]
    assert response.context['selected_status'] == 'closed'


def test_list_view_junk_status_degrades_to_all_not_500(client_a, tenant_a, location_a1, make_callback):
    pending = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_PENDING)
    closed = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CLOSED)

    response = client_a.get(_url('callbackrequest_list'), {'status': 'nonsense'})

    assert response.status_code == 200
    results = set(response.context['callback_requests'])
    assert results == {pending, closed}
    assert response.context['selected_status'] == ''


# -- pagination ----------------------------------------------------------- #

def test_list_view_page_past_the_end_degrades_to_200(client_a, tenant_a, location_a1, make_callback):
    make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CLOSED)
    response = client_a.get(_url('callbackrequest_list'), {'status': '', 'page': '999'})
    assert response.status_code == 200


def test_list_view_page_2_when_rows_exceed_page_size(client_a, tenant_a, location_a1, make_callback):
    for i in range(30):
        make_callback(tenant_a, location_a1, caller_name=f'Caller {i}', status=CallbackRequest.STATUS_CLOSED)

    response = client_a.get(_url('callbackrequest_list'), {'status': '', 'page': '2'})

    assert response.status_code == 200
    assert response.context['page_obj'].number == 2
    assert len(response.context['callback_requests']) == 5


# --------------------------------------------------------------------------- #
# callbackrequest_create_view
# --------------------------------------------------------------------------- #

def test_create_view_get_renders_form(client_a):
    response = client_a.get(_url('callbackrequest_create'))
    assert response.status_code == 200
    assert 'scheduling/callbacks/callbackrequest/form.html' in [t.name for t in response.templates]
    assert response.context['is_edit'] is False


def test_create_view_saves_with_tenant_active_location_and_manual_source(
    client_a, tenant_a, location_a1,
):
    response = client_a.post(_url('callbackrequest_create'), _callback_post())

    assert response.status_code == 302
    obj = CallbackRequest.objects.get(caller_name='Dana Caller')
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk
    assert obj.source == CallbackRequest.SOURCE_MANUAL


def test_create_view_invalid_submission_rerenders_form_with_errors(client_a):
    response = client_a.post(_url('callbackrequest_create'), _callback_post(
        caller_name='', caller_phone='',
    ))
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert CallbackRequest.objects.count() == 0


def test_create_view_refuses_without_an_active_location(admin_user):
    client = Client()
    client.force_login(admin_user)

    response = client.post(_url('callbackrequest_create'), _callback_post(), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('callbackrequest_list')
    assert CallbackRequest.objects.count() == 0


# --------------------------------------------------------------------------- #
# callbackrequest_detail_view
# --------------------------------------------------------------------------- #

def test_detail_view_renders_for_tenant_admin(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.get(_url('callbackrequest_detail', cb.pk))
    assert response.status_code == 200
    assert response.context['obj'] == cb
    assert 'resolve_form' in response.context


# --------------------------------------------------------------------------- #
# callbackrequest_edit_view — editable at ANY status, unlike Appointment
# --------------------------------------------------------------------------- #

def test_edit_view_get_renders_prefilled_form(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.get(_url('callbackrequest_edit', cb.pk))
    assert response.status_code == 200
    assert response.context['is_edit'] is True
    assert response.context['form'].instance == cb


def test_edit_view_saves_changes(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.post(
        _url('callbackrequest_edit', cb.pk),
        _callback_post(reason='Updated reason'),
    )
    assert response.status_code == 302
    cb.refresh_from_db()
    assert cb.reason == 'Updated reason'


def test_edit_view_is_reachable_on_a_closed_callback(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CLOSED)

    response = client_a.get(_url('callbackrequest_edit', cb.pk))
    assert response.status_code == 200

    response = client_a.post(
        _url('callbackrequest_edit', cb.pk),
        _callback_post(status=CallbackRequest.STATUS_PENDING, reason='Reopened by mistake fix'),
    )
    assert response.status_code == 302
    cb.refresh_from_db()
    assert cb.status == CallbackRequest.STATUS_PENDING


# --------------------------------------------------------------------------- #
# callbackrequest_resolve_view
# --------------------------------------------------------------------------- #

def test_resolve_view_marks_contacted_with_notes(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CONTACTED, 'notes': 'Left a voicemail',
    })

    assert response.status_code == 302
    cb.refresh_from_db()
    assert cb.status == CallbackRequest.STATUS_CONTACTED
    assert cb.notes == 'Left a voicemail'


def test_resolve_view_marks_closed(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CLOSED, 'notes': 'All done',
    })

    assert response.status_code == 302
    cb.refresh_from_db()
    assert cb.status == CallbackRequest.STATUS_CLOSED


def test_resolve_view_refuses_pending_and_leaves_row_unchanged(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1, status=CallbackRequest.STATUS_CONTACTED, notes='Original')

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_PENDING, 'notes': 'Sneaky',
    }, follow=True)

    assert response.status_code == 200
    cb.refresh_from_db()
    assert cb.status == CallbackRequest.STATUS_CONTACTED
    assert cb.notes == 'Original'


def test_resolve_view_honours_posted_next(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    list_url_with_query = _url('callbackrequest_list') + '?status=&q=dana'

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CLOSED, 'notes': '', 'next': list_url_with_query,
    })

    assert response.status_code == 302
    assert response.url == list_url_with_query


def test_resolve_view_defaults_to_detail_without_next(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)

    response = client_a.post(_url('callbackrequest_resolve', cb.pk), {
        'status': CallbackRequest.STATUS_CLOSED, 'notes': '',
    })

    assert response.status_code == 302
    assert response.url == _url('callbackrequest_detail', cb.pk)


def test_resolve_view_get_is_405(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.get(_url('callbackrequest_resolve', cb.pk))
    assert response.status_code == 405


# --------------------------------------------------------------------------- #
# callbackrequest_delete_view
# --------------------------------------------------------------------------- #

def test_delete_view_removes_the_row(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.post(_url('callbackrequest_delete', cb.pk))
    assert response.status_code == 302
    assert not CallbackRequest.objects.filter(pk=cb.pk).exists()


def test_delete_view_get_is_405_and_row_survives(client_a, tenant_a, location_a1, make_callback):
    cb = make_callback(tenant_a, location_a1)
    response = client_a.get(_url('callbackrequest_delete', cb.pk))
    assert response.status_code == 405
    assert CallbackRequest.objects.filter(pk=cb.pk).exists()


# --------------------------------------------------------------------------- #
# Query counts — the queue's own cost is bounded regardless of filters/rows
# --------------------------------------------------------------------------- #

def test_list_view_query_count_does_not_grow_with_row_count(client_a, tenant_a, location_a1, make_callback):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(3):
        make_callback(tenant_a, location_a1, caller_name=f'Caller {i}')
    with CaptureQueriesContext(connection) as small:
        response = client_a.get(_url('callbackrequest_list'), {'status': '', 'q': 'Caller'})
    assert response.status_code == 200

    for i in range(3, 30):
        make_callback(tenant_a, location_a1, caller_name=f'Caller {i}')
    with CaptureQueriesContext(connection) as big:
        response = client_a.get(_url('callbackrequest_list'), {'status': '', 'q': 'Caller'})
    assert response.status_code == 200

    assert len(big.captured_queries) == len(small.captured_queries)


def test_callback_queryset_costs_exactly_two_queries_with_search_status_and_pagination(
    django_assert_max_num_queries, tenant_a, location_a1, make_callback,
):
    """The queue's whole database cost is `Paginator.count()` plus one page
    SELECT — search, the status filter and pagination all fold into the SAME
    queryset (`select_related` joins rather than extra round trips), so
    exercising all three together must still cost exactly 2 queries, matching
    what `callbackrequest_list_view` itself builds in `_location_callbacks()`
    plus `paginate()`.

    Tested at this level (not through `Client`) so the count reflects the
    view's OWN query cost rather than the constant, unrelated overhead of
    session/auth/location-switcher middleware that wraps every authenticated
    request — the same reasoning `test_booking_availability.py` uses when it
    calls `find_available_slots` directly instead of through the test client.
    """
    from django.db.models import Q

    from apps.scheduling.views._common import paginate

    for i in range(30):
        make_callback(
            tenant_a, location_a1, caller_name=f'Caller {i}',
            status=CallbackRequest.STATUS_CLOSED,
        )

    queryset = CallbackRequest.objects.filter(
        tenant=tenant_a, location=location_a1,
    ).select_related('contact', 'location').filter(
        Q(caller_name__icontains='Caller') | Q(caller_phone__icontains='Caller')
        | Q(reason__icontains='Caller') | Q(contact__first_name__icontains='Caller')
        | Q(contact__last_name__icontains='Caller') | Q(contact__phone_e164__icontains='Caller'),
    ).filter(status=CallbackRequest.STATUS_CLOSED)

    class _FakeGET(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    fake_request = type('FakeRequest', (), {'GET': _FakeGET({'page': '2'})})()

    with django_assert_max_num_queries(2):
        page_obj, elided = paginate(fake_request, queryset)
        list(page_obj.object_list)
        assert page_obj.paginator.count == 30
