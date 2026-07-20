"""List/detail, search, filter, pagination and query-count tests for
`calls.CallSession` (sub-module 5.1).

Cross-tenant/location isolation and the no-mutation-surface guard live in
`test_security.py`. Model behaviour lives in `test_models.py`.
"""
from datetime import datetime, time as dt_time, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone as dj_timezone

from apps.calls.models import CallSession
from apps.calls.views.CallLogList.CallSessions import (
    OUTCOME_CHOICES,
    OUTCOME_NO_TRANSFER,
    _location_sessions,
)
from apps.scheduling.availability import _local_naive_to_utc
from apps.scheduling.models import Contact

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'calls:{name}', args=args)


def _local(location, day, hour=10, minute=0):
    return _local_naive_to_utc(datetime.combine(day, dt_time(hour, minute)), location.tzinfo)


# --------------------------------------------------------------------------- #
# callsession_list_view — base render
# --------------------------------------------------------------------------- #

def test_list_view_renders_for_tenant_admin(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)

    response = client_a.get(_url('callsession_list'))

    assert response.status_code == 200
    assert 'calls/calllog/callsession/list.html' in [t.name for t in response.templates]
    assert list(response.context['call_sessions']) == [session]
    assert response.context['total_count'] == 1
    assert response.context['status_choices'] == CallSession.STATUS_CHOICES
    assert response.context['mode_choices'] == CallSession.MODE_CHOICES
    assert response.context['outcome_choices'] == OUTCOME_CHOICES


def test_list_view_with_no_active_location_returns_empty(admin_user):
    """`admin_user` is assigned to BOTH A1 and A2, so with no explicit switch the
    middleware activates neither — `request.location` is None and the view must
    degrade to an empty page, never a leak or a 500.
    """
    client = Client()
    client.force_login(admin_user)

    response = client.get(_url('callsession_list'))

    assert response.status_code == 200
    assert list(response.context['call_sessions']) == []


# --------------------------------------------------------------------------- #
# search — from_number, to_number, contact name and phone
# --------------------------------------------------------------------------- #

def test_list_view_search_by_from_number(client_a, tenant_a, location_a1, make_call_session):
    match = make_call_session(tenant_a, location_a1, from_number='+13125550142', provider_call_sid='CA-s-1')
    make_call_session(tenant_a, location_a1, from_number='+15035550210', provider_call_sid='CA-s-2')

    response = client_a.get(_url('callsession_list'), {'q': '5550142'})

    assert list(response.context['call_sessions']) == [match]


def test_list_view_search_by_to_number(client_a, tenant_a, location_a1, make_call_session):
    match = make_call_session(tenant_a, location_a1, to_number='+13125550140', provider_call_sid='CA-s-3')
    make_call_session(tenant_a, location_a1, to_number='+15035550150', provider_call_sid='CA-s-4')

    response = client_a.get(_url('callsession_list'), {'q': '5550140'})

    assert list(response.context['call_sessions']) == [match]


def test_list_view_search_by_contact_name(client_a, tenant_a, location_a1, make_call_session):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Priya', last_name='Raman')
    match = make_call_session(tenant_a, location_a1, contact=contact, provider_call_sid='CA-s-5')
    make_call_session(tenant_a, location_a1, provider_call_sid='CA-s-6')

    response = client_a.get(_url('callsession_list'), {'q': 'priya'})

    assert list(response.context['call_sessions']) == [match]


def test_list_view_search_by_contact_phone(client_a, tenant_a, location_a1, make_call_session):
    contact = Contact.objects.create(
        tenant=tenant_a, first_name='Theo', last_name='Nakamura', phone_e164='+15035550210',
    )
    match = make_call_session(tenant_a, location_a1, contact=contact, provider_call_sid='CA-s-7')
    make_call_session(tenant_a, location_a1, provider_call_sid='CA-s-8')

    response = client_a.get(_url('callsession_list'), {'q': '5035550210'})

    assert list(response.context['call_sessions']) == [match]


# --------------------------------------------------------------------------- #
# status / mode filters
# --------------------------------------------------------------------------- #

def test_list_view_status_narrows(client_a, tenant_a, location_a1, make_call_session):
    completed = make_call_session(tenant_a, location_a1, status=CallSession.STATUS_COMPLETED, provider_call_sid='CA-st-1')
    make_call_session(tenant_a, location_a1, status=CallSession.STATUS_FAILED, provider_call_sid='CA-st-2')

    response = client_a.get(_url('callsession_list'), {'status': 'completed'})

    assert list(response.context['call_sessions']) == [completed]


def test_list_view_mode_narrows(client_a, tenant_a, location_a1, make_call_session):
    gemini = make_call_session(tenant_a, location_a1, mode=CallSession.MODE_GEMINI, provider_call_sid='CA-md-1')
    make_call_session(tenant_a, location_a1, mode=CallSession.MODE_LIVE, provider_call_sid='CA-md-2')

    response = client_a.get(_url('callsession_list'), {'mode': 'gemini'})

    assert list(response.context['call_sessions']) == [gemini]


# --------------------------------------------------------------------------- #
# date range — LOCAL calendar days at the active location, never `__date`
# --------------------------------------------------------------------------- #

def test_list_view_date_range_narrows_to_the_local_day(client_a, tenant_a, location_a1, make_call_session):
    today = location_a1.local_now().date()
    recent = make_call_session(
        tenant_a, location_a1, started_at=_local(location_a1, today), provider_call_sid='CA-dt-1',
    )
    old = make_call_session(
        tenant_a, location_a1,
        started_at=_local(location_a1, today - timedelta(days=10)),
        provider_call_sid='CA-dt-2',
    )

    response = client_a.get(_url('callsession_list'), {
        'from': today.isoformat(), 'to': today.isoformat(),
    })

    results = list(response.context['call_sessions'])
    assert recent in results
    assert old not in results


def test_list_view_from_only_excludes_everything_before_it(client_a, tenant_a, location_a1, make_call_session):
    today = location_a1.local_now().date()
    recent = make_call_session(
        tenant_a, location_a1, started_at=_local(location_a1, today), provider_call_sid='CA-dt-3',
    )
    old = make_call_session(
        tenant_a, location_a1,
        started_at=_local(location_a1, today - timedelta(days=5)),
        provider_call_sid='CA-dt-4',
    )

    response = client_a.get(_url('callsession_list'), {'from': today.isoformat()})

    results = list(response.context['call_sessions'])
    assert recent in results
    assert old not in results


# --------------------------------------------------------------------------- #
# THE SUBTLE ONE — the outcome filter
# --------------------------------------------------------------------------- #

def test_outcome_no_transfer_matches_empty_dict(client_a, tenant_a, location_a1, make_call_session):
    never_attempted = make_call_session(tenant_a, location_a1, transfer={}, provider_call_sid='CA-oc-1')

    response = client_a.get(_url('callsession_list'), {'outcome': OUTCOME_NO_TRANSFER})

    assert never_attempted in list(response.context['call_sessions'])


def test_outcome_no_transfer_also_matches_a_transfer_dict_with_no_result_key(
    client_a, tenant_a, location_a1, make_call_session,
):
    """The runtime died mid-transfer: `transfer` is non-empty but has no
    `result` key yet. `__isnull=True` on the JSON key transform catches this
    case too — a dict-equality check against `{}` would miss it, which is
    exactly why `__isnull` was chosen over comparing to `{}` (identical on
    SQLite and MySQL).
    """
    died_mid_transfer = make_call_session(
        tenant_a, location_a1,
        transfer={'reason': 'caller asked for billing', 'initiated_at': '2026-01-01T00:00:00Z'},
        provider_call_sid='CA-oc-2',
    )

    response = client_a.get(_url('callsession_list'), {'outcome': OUTCOME_NO_TRANSFER})

    assert died_mid_transfer in list(response.context['call_sessions'])


def test_outcome_no_transfer_excludes_a_resolved_transfer(client_a, tenant_a, location_a1, make_call_session):
    never_attempted = make_call_session(tenant_a, location_a1, transfer={}, provider_call_sid='CA-oc-3')
    connected = make_call_session(
        tenant_a, location_a1, transfer={'result': 'connected'}, provider_call_sid='CA-oc-4',
    )

    response = client_a.get(_url('callsession_list'), {'outcome': OUTCOME_NO_TRANSFER})

    results = list(response.context['call_sessions'])
    assert never_attempted in results
    assert connected not in results


def test_outcome_connected_matches_only_that_result(client_a, tenant_a, location_a1, make_call_session):
    connected = make_call_session(
        tenant_a, location_a1, transfer={'result': 'connected'}, provider_call_sid='CA-oc-5',
    )
    no_answer = make_call_session(
        tenant_a, location_a1, transfer={'result': 'no_answer'}, provider_call_sid='CA-oc-6',
    )
    never_attempted = make_call_session(tenant_a, location_a1, transfer={}, provider_call_sid='CA-oc-7')

    response = client_a.get(_url('callsession_list'), {'outcome': 'connected'})

    results = list(response.context['call_sessions'])
    assert results == [connected]
    assert no_answer not in results
    assert never_attempted not in results


def test_outcome_junk_degrades_to_no_filter_not_500(client_a, tenant_a, location_a1, make_call_session):
    connected = make_call_session(
        tenant_a, location_a1, transfer={'result': 'connected'}, provider_call_sid='CA-oc-8',
    )
    never_attempted = make_call_session(tenant_a, location_a1, transfer={}, provider_call_sid='CA-oc-9')

    response = client_a.get(_url('callsession_list'), {'outcome': 'junk-outcome'})

    assert response.status_code == 200
    results = set(response.context['call_sessions'])
    assert results == {connected, never_attempted}


# --------------------------------------------------------------------------- #
# Junk / hostile GET params degrade, never 500
# --------------------------------------------------------------------------- #

def test_junk_status_degrades_to_no_filter(client_a, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1, status=CallSession.STATUS_COMPLETED, provider_call_sid='CA-j-1')
    response = client_a.get(_url('callsession_list'), {'status': 'nonsense'})
    assert response.status_code == 200
    assert len(response.context['call_sessions']) == 1


def test_junk_mode_degrades_to_no_filter(client_a, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1, mode=CallSession.MODE_LIVE, provider_call_sid='CA-j-2')
    response = client_a.get(_url('callsession_list'), {'mode': 'junk'})
    assert response.status_code == 200
    assert len(response.context['call_sessions']) == 1


def test_junk_from_date_degrades_to_no_filter(client_a, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1, provider_call_sid='CA-j-3')
    response = client_a.get(_url('callsession_list'), {'from': 'notadate'})
    assert response.status_code == 200
    assert len(response.context['call_sessions']) == 1


def test_out_of_range_from_date_degrades_to_no_filter(client_a, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1, provider_call_sid='CA-j-4')
    response = client_a.get(_url('callsession_list'), {'from': '9999-99-99'})
    assert response.status_code == 200
    assert len(response.context['call_sessions']) == 1


def test_junk_page_degrades_to_page_1(client_a, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1, provider_call_sid='CA-j-5')
    response = client_a.get(_url('callsession_list'), {'page': 'abc'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 1


def test_page_past_the_end_degrades_to_last_valid_page(client_a, tenant_a, location_a1, make_call_session):
    for i in range(30):
        make_call_session(tenant_a, location_a1, provider_call_sid=f'CA-j-6-{i:04d}')
    response = client_a.get(_url('callsession_list'), {'page': '99999'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 2


def test_500_char_search_does_not_500(client_a, tenant_a, location_a1, make_call_session):
    make_call_session(tenant_a, location_a1, provider_call_sid='CA-j-7')
    response = client_a.get(_url('callsession_list'), {'q': 'x' * 500})
    assert response.status_code == 200
    assert len(response.context['call_sessions']) == 0


# --------------------------------------------------------------------------- #
# Pagination — page 2 when rows exceed the page size
# --------------------------------------------------------------------------- #

def test_list_view_page_2_when_rows_exceed_page_size(client_a, tenant_a, location_a1, make_call_session):
    for i in range(30):
        make_call_session(tenant_a, location_a1, provider_call_sid=f'CA-page-{i:04d}')

    response = client_a.get(_url('callsession_list'), {'page': '2'})

    assert response.status_code == 200
    assert response.context['page_obj'].number == 2
    assert len(response.context['call_sessions']) == 5


# --------------------------------------------------------------------------- #
# callsession_detail_view
# --------------------------------------------------------------------------- #

def test_detail_view_renders_for_tenant_admin(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    response = client_a.get(_url('callsession_detail', session.pk))
    assert response.status_code == 200
    assert 'calls/calllog/callsession/detail.html' in [t.name for t in response.templates]
    assert response.context['obj'] == session


def test_detail_view_malformed_json_blob_still_renders(client_a, tenant_a, location_a1, make_call_session):
    """A malformed/unexpected shape in a JSON column must render the detail
    page, not 500 — the runtime is the only writer, but a partial write from a
    crashed worker is exactly the row a staff member needs to be able to open.
    """
    session = make_call_session(
        tenant_a, location_a1,
        transcript=['not-a-dict-turn', 42, None],
        transfer={'unexpected': 'shape', 'no_result_key': True},
        analysis={'summary': None},
    )
    response = client_a.get(_url('callsession_detail', session.pk))
    assert response.status_code == 200
    assert response.context['obj'] == session


def test_detail_view_get_context_includes_booked_appointments(
    client_a, tenant_a, location_a1, make_call_session,
):
    from apps.scheduling.models import Appointment, Service

    contact = Contact.objects.create(tenant=tenant_a, first_name='Dana', last_name='Whitfield')
    session = make_call_session(tenant_a, location_a1, contact=contact)
    service = Service.objects.create(tenant=tenant_a, name='Check-up', duration_minutes=30)
    start = dj_timezone.now() + timedelta(days=1)
    appt = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact, service=service,
        start_at=start, end_at=start + timedelta(minutes=30), booked_by_session=session,
    )

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    assert appt in list(response.context['obj'].booked_appointments.all())


# --------------------------------------------------------------------------- #
# Method guard — GET only, both views
# --------------------------------------------------------------------------- #

def test_list_view_post_is_405(client_a):
    response = client_a.post(_url('callsession_list'), {})
    assert response.status_code == 405


def test_detail_view_post_is_405(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    response = client_a.post(_url('callsession_detail', session.pk), {})
    assert response.status_code == 405


# --------------------------------------------------------------------------- #
# Query counts — measured against the VIEW'S OWN queryset, not through Client
# (a Client request carries ~6 constant queries of middleware/context-processor
# overhead, so a literal max_num_queries(2) through the full stack cannot pass —
# same reasoning `test_callback_views.py` uses).
# --------------------------------------------------------------------------- #

def test_list_queryset_query_count_does_not_grow_with_row_count(tenant_a, location_a1, make_call_session):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from types import SimpleNamespace

    from apps.accounts.views._common import paginate

    request = SimpleNamespace(tenant=tenant_a, location=location_a1, GET={})

    for i in range(3):
        make_call_session(tenant_a, location_a1, provider_call_sid=f'CA-qc-small-{i:04d}')
    with CaptureQueriesContext(connection) as small:
        queryset = _location_sessions(request).order_by('-started_at').defer(
            'transcript', 'logs', 'analysis', 'usage', 'waveform_peaks', 'metadata',
        )
        page_obj, _elided = paginate(request, queryset)
        list(page_obj.object_list)

    for i in range(3, 30):
        make_call_session(tenant_a, location_a1, provider_call_sid=f'CA-qc-big-{i:04d}')
    with CaptureQueriesContext(connection) as big:
        queryset = _location_sessions(request).order_by('-started_at').defer(
            'transcript', 'logs', 'analysis', 'usage', 'waveform_peaks', 'metadata',
        )
        page_obj, _elided = paginate(request, queryset)
        list(page_obj.object_list)

    assert len(big.captured_queries) == len(small.captured_queries)


def test_list_queryset_query_count_is_bounded_regardless_of_bookings(
    django_assert_max_num_queries, tenant_a, location_a1, make_call_session,
):
    """The list page's own database cost — `select_related`, the
    `booked_appointments__service` prefetch chain and `paginate()`'s count —
    must stay bounded (main select + 2 prefetch levels + paginator.count = 4)
    even when several rows each carry a booked appointment.
    """
    from types import SimpleNamespace

    from apps.scheduling.models import Appointment, Service

    from apps.accounts.views._common import paginate

    contact = Contact.objects.create(tenant=tenant_a, first_name='Multi', last_name='Booker')
    service = Service.objects.create(tenant=tenant_a, name='Consult', duration_minutes=30)
    start = dj_timezone.now() + timedelta(days=1)

    for i in range(10):
        session = make_call_session(tenant_a, location_a1, contact=contact, provider_call_sid=f'CA-qb-{i:04d}')
        Appointment.objects.create(
            tenant=tenant_a, location=location_a1, contact=contact, service=service,
            start_at=start + timedelta(hours=i), end_at=start + timedelta(hours=i, minutes=30),
            booked_by_session=session,
        )

    request = SimpleNamespace(tenant=tenant_a, location=location_a1, GET={})

    with django_assert_max_num_queries(4):
        queryset = _location_sessions(request).order_by('-started_at').defer(
            'transcript', 'logs', 'analysis', 'usage', 'waveform_peaks', 'metadata',
        )
        page_obj, _elided = paginate(request, queryset)
        for session in page_obj.object_list:
            for appt in session.booked_appointments.all():
                assert appt.service.name == 'Consult'


def test_detail_view_does_not_n_plus_1_on_booked_appointments_service(
    django_assert_max_num_queries, tenant_a, location_a1, make_call_session,
):
    """The detail page's `_location_sessions` prefetch must cover the SAME
    reverse relation the list page does — a call that booked several
    appointments must not cost one query per appointment for `service`.
    """
    from types import SimpleNamespace

    from apps.scheduling.models import Appointment, Service

    contact = Contact.objects.create(tenant=tenant_a, first_name='Multi', last_name='Detail')
    session = make_call_session(tenant_a, location_a1, contact=contact)
    start = dj_timezone.now() + timedelta(days=1)
    for i in range(5):
        service = Service.objects.create(tenant=tenant_a, name=f'Service {i}', duration_minutes=30)
        Appointment.objects.create(
            tenant=tenant_a, location=location_a1, contact=contact, service=service,
            start_at=start + timedelta(hours=i), end_at=start + timedelta(hours=i, minutes=30),
            booked_by_session=session,
        )

    request = SimpleNamespace(tenant=tenant_a, location=location_a1)

    with django_assert_max_num_queries(3):
        obj = _location_sessions(request).get(pk=session.pk)
        names = [appt.service.name for appt in obj.booked_appointments.all()]
        assert len(names) == 5
