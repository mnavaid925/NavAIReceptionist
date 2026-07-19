"""Tests for the day/week calendar grid (sub-module 4.4) — a VIEW sub-module,
zero models, zero migrations.

Pure geometry helpers (`_px`, `_visible_window`, `_hour_labels`, `_pack_lanes`,
`_block_span`) are imported and called directly — they have no DB cost and are
the highest-value tests. View-level tests hit `calendar_day`/`calendar_week`
through the client; click-through tests cover `appointment_create_view`'s
`?start=`/`?resource=`/`?provider=` pre-fill, which 4.4 added.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone as dj_timezone

from apps.scheduling.models import Appointment
from apps.scheduling.views.CalendarViews import Calendar as cal

pytestmark = pytest.mark.django_db

UTC = ZoneInfo('UTC')


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


# --------------------------------------------------------------------------- #
# Pure geometry — `_px`
# --------------------------------------------------------------------------- #

def test_px_returns_int_for_every_input():
    for minutes in (0, 1, 7, 15, 47, 90, 1440):
        assert isinstance(cal._px(minutes), int)


def test_px_of_one_slot_equals_slot_px():
    assert cal._px(cal.SLOT_MINUTES) == cal.SLOT_PX


# --------------------------------------------------------------------------- #
# Pure geometry — `_visible_window`
# --------------------------------------------------------------------------- #

def test_visible_window_empty_gives_default_business_day():
    assert cal._visible_window([]) == (
        cal.DEFAULT_WINDOW_START_MIN, cal.DEFAULT_WINDOW_END_MIN,
    )


def test_visible_window_early_span_widens_start_to_a_whole_hour():
    # 07:00-08:20 is earlier than the 08:00 default start.
    start, end = cal._visible_window([(420, 500)])
    assert start == 420  # already a whole hour
    assert end == cal.DEFAULT_WINDOW_END_MIN
    assert start % 60 == 0
    assert end % 60 == 0
    assert end > start


def test_visible_window_late_span_widens_end_to_a_whole_hour():
    # 16:40-21:40 is later than the 18:00 default end; 21:40 rounds up to 22:00.
    start, end = cal._visible_window([(1000, 1300)])
    assert start == cal.DEFAULT_WINDOW_START_MIN
    assert end == 1320
    assert start % 60 == 0
    assert end % 60 == 0
    assert end > start


def test_visible_window_span_past_midnight_clamps_to_1440_and_never_inverts():
    # 23:30 + 90min = 25:00 (1500 minutes) — a booking running past midnight.
    start, end = cal._visible_window([(1410, 1500)])
    assert end == cal.MINUTES_IN_DAY
    assert end > start
    assert start % 60 == 0
    assert end % 60 == 0


# --------------------------------------------------------------------------- #
# Pure geometry — `_hour_labels`
# --------------------------------------------------------------------------- #

def test_hour_labels_ascend_from_window_start():
    labels = cal._hour_labels(0, 90)
    assert [entry['label'] for entry in labels] == ['00:00', '01:00']
    assert labels[0]['top_px'] == 0
    assert labels[1]['top_px'] > labels[0]['top_px']


def test_hour_labels_start_at_the_given_hour_not_always_zero():
    labels = cal._hour_labels(cal.DEFAULT_WINDOW_START_MIN, cal.DEFAULT_WINDOW_END_MIN)
    # `range(window_start//60, ceil(window_end/60))` — the row AT window_end is
    # the bottom gridline, not a labelled row, so the default 08:00-18:00 window
    # labels 08:00 through 17:00 (10 rows).
    assert labels[0]['label'] == '08:00'
    assert labels[-1]['label'] == '17:00'
    assert len(labels) == 10


# --------------------------------------------------------------------------- #
# Pure geometry — `_pack_lanes`
# --------------------------------------------------------------------------- #

def _item(start_min, end_min):
    return {'start_min': start_min, 'end_min': end_min}


def test_pack_lanes_single_item_is_lane_0_of_1():
    items = [_item(0, 30)]
    lane_count = cal._pack_lanes(items)
    assert lane_count == 1
    assert items[0]['lane'] == 0
    assert items[0]['lane_count'] == 1


def test_pack_lanes_two_overlapping_items_get_different_lanes():
    items = [_item(0, 60), _item(30, 90)]
    lane_count = cal._pack_lanes(items)
    assert lane_count == 2
    lanes = {item['lane'] for item in items}
    assert lanes == {0, 1}
    assert all(item['lane_count'] == 2 for item in items)


def test_pack_lanes_later_non_overlapping_item_reuses_lane_0():
    items = [_item(0, 60), _item(30, 90), _item(90, 120)]
    cal._pack_lanes(items)
    by_start = {item['start_min']: item for item in items}
    assert by_start[0]['lane'] == 0
    assert by_start[30]['lane'] == 1
    assert by_start[90]['lane'] == 0


def test_pack_lanes_three_mutually_overlapping_items_get_three_lanes():
    items = [_item(0, 60), _item(10, 70), _item(20, 80)]
    lane_count = cal._pack_lanes(items)
    assert lane_count == 3
    lanes = sorted(item['lane'] for item in items)
    assert lanes == [0, 1, 2]


# --------------------------------------------------------------------------- #
# Pure geometry — `_block_span`
# --------------------------------------------------------------------------- #

def test_block_span_derives_duration_from_the_stored_span():
    start = datetime(2030, 6, 15, 10, 15, tzinfo=UTC)
    end = start + timedelta(minutes=47)
    # No `service` attribute at all: if `_block_span` touched `.service` this
    # would raise `AttributeError` before any assertion below could run — proof
    # the duration comes from `end_at - start_at`, not the (SET_NULL) service.
    appointment = SimpleNamespace(start_at=start, end_at=end)

    start_min, end_min = cal._block_span(appointment, UTC)

    assert start_min == 10 * 60 + 15
    assert end_min == start_min + 47


def test_block_span_after_the_real_service_is_deleted_keeps_its_real_length(
    tenant_a, location_a1, contact_a, service_all_a, make_appointment,
):
    """Integration companion to the pure test above, through an actual
    `SET_NULL` delete.
    """
    start = dj_timezone.now().replace(
        hour=10, minute=0, second=0, microsecond=0
    ) + timedelta(days=2)
    appt = make_appointment(
        tenant_a, location_a1, contact_a, service=service_all_a,
        start_at=start, duration_minutes=45,
    )
    service_all_a.delete()
    appt.refresh_from_db()
    assert appt.service_id is None

    start_min, end_min = cal._block_span(appt, location_a1.tzinfo)
    assert end_min - start_min == 45


# --------------------------------------------------------------------------- #
# calendar_day_view — rendering basics
# --------------------------------------------------------------------------- #

def test_day_view_renders_200_for_tenant_admin(client_a):
    response = client_a.get(_url('calendar_day'))
    assert response.status_code == 200
    assert 'scheduling/calendar/day.html' in [t.name for t in response.templates]


def test_day_view_with_no_active_location_renders_empty_state_not_500(admin_user):
    client = Client()
    client.force_login(admin_user)
    response = client.get(_url('calendar_day'))
    assert response.status_code == 200
    assert response.context['no_location'] is True


def test_day_view_default_date_is_the_locations_today(client_a, location_a1):
    response = client_a.get(_url('calendar_day'))
    assert response.context['day'] == location_a1.local_now().date()


def test_day_view_default_mode_is_resource(client_a):
    response = client_a.get(_url('calendar_day'))
    assert response.context['mode'] == 'resource'


def test_day_view_by_junk_falls_back_to_resource(client_a):
    response = client_a.get(_url('calendar_day'), {'by': 'not-a-real-mode'})
    assert response.context['mode'] == 'resource'


@pytest.mark.parametrize('junk_date', ['not-a-date', '²', '１', '9999-12-31'])
def test_day_view_junk_date_degrades_to_200(client_a, junk_date):
    response = client_a.get(_url('calendar_day'), {'date': junk_date})
    assert response.status_code == 200


@pytest.mark.parametrize('junk_date', ['not-a-date', '²', '１', '9999-12-31'])
def test_week_view_junk_date_degrades_to_200(client_a, junk_date):
    response = client_a.get(_url('calendar_week'), {'date': junk_date})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# calendar_day_view — cancelled / no-show exclusion
# --------------------------------------------------------------------------- #

def _blocks(columns):
    """Flatten every column's blocks into one list."""
    return [block for column in columns for block in column['blocks']]


def test_day_view_cancelled_and_no_show_are_excluded_from_blocks_and_in_freed(
    client_a, tenant_a, location_a1, contact_a, resource_a1, make_appointment,
):
    day = location_a1.local_now().date() + timedelta(days=2)
    base = dj_timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2)

    live = make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1,
        status=Appointment.STATUS_SCHEDULED, start_at=base,
    )
    cancelled = make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1,
        status=Appointment.STATUS_CANCELLED, start_at=base + timedelta(hours=1),
    )
    no_show = make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1,
        status=Appointment.STATUS_NO_SHOW, start_at=base + timedelta(hours=2),
    )

    response = client_a.get(_url('calendar_day'), {'date': day.isoformat()})

    assert response.status_code == 200
    block_pks = {block['appointment'].pk for block in _blocks(response.context['columns'])}
    assert block_pks == {live.pk}
    freed_pks = {a.pk for a in response.context['freed']}
    assert freed_pks == {cancelled.pk, no_show.pk}
    assert response.context['total_count'] == 3


# --------------------------------------------------------------------------- #
# calendar_day_view — Unassigned column / deactivated resource
# --------------------------------------------------------------------------- #

def test_day_view_unassigned_column_always_renders_and_is_not_clickable(client_a):
    response = client_a.get(_url('calendar_day'))
    columns = response.context['columns']
    assert columns  # at least the Unassigned column
    unassigned = columns[-1]
    assert unassigned['head'] == 'Unassigned'
    assert unassigned['clickable'] is False


def test_day_view_deactivated_resource_booking_appears_in_unassigned(
    client_a, tenant_a, location_a1, contact_a, resource_a1, make_appointment,
):
    day = location_a1.local_now().date() + timedelta(days=2)
    base = dj_timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2)
    appt = make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1, start_at=base,
    )
    resource_a1.is_active = False
    resource_a1.save(update_fields=['is_active'])

    response = client_a.get(_url('calendar_day'), {'date': day.isoformat()})

    columns = response.context['columns']
    # The deactivated resource has no column of its own any more...
    assert not any(c['head'] == str(resource_a1) for c in columns[:-1])
    # ...but the booking (whose `resource_id` is still set, not null) still shows,
    # keyed on column membership rather than FK null-ness — in Unassigned.
    unassigned = columns[-1]
    assert unassigned['head'] == 'Unassigned'
    assert {block['appointment'].pk for block in unassigned['blocks']} == {appt.pk}
    assert unassigned['clickable'] is False


# --------------------------------------------------------------------------- #
# calendar_day_view — `?by=provider` switches columns
# --------------------------------------------------------------------------- #

def test_by_provider_switches_which_column_holds_a_booking(
    client_a, tenant_a, location_a1, contact_a, resource_a1, provider_a1, make_appointment,
):
    day = location_a1.local_now().date() + timedelta(days=2)
    base = dj_timezone.now().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
    appt = make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1, provider=provider_a1,
        start_at=base,
    )

    resource_columns = client_a.get(
        _url('calendar_day'), {'date': day.isoformat(), 'by': 'resource'}
    ).context['columns']
    provider_columns = client_a.get(
        _url('calendar_day'), {'date': day.isoformat(), 'by': 'provider'}
    ).context['columns']

    resource_heads = [c['head'] for c in resource_columns]
    provider_heads = [c['head'] for c in provider_columns]
    assert str(resource_a1) in resource_heads
    assert str(provider_a1) not in resource_heads
    assert str(provider_a1) in provider_heads
    assert str(resource_a1) not in provider_heads

    def _blocks_for(columns, head):
        return next(c for c in columns if c['head'] == head)['blocks']

    assert {b['appointment'].pk for b in _blocks_for(resource_columns, str(resource_a1))} == {appt.pk}
    assert {b['appointment'].pk for b in _blocks_for(provider_columns, str(provider_a1))} == {appt.pk}


# --------------------------------------------------------------------------- #
# calendar_week_view
# --------------------------------------------------------------------------- #

def test_week_view_renders_200_for_tenant_admin(client_a):
    response = client_a.get(_url('calendar_week'))
    assert response.status_code == 200
    assert 'scheduling/calendar/week.html' in [t.name for t in response.templates]


def test_week_view_with_no_active_location_renders_empty_state_not_500(admin_user):
    client = Client()
    client.force_login(admin_user)
    response = client.get(_url('calendar_week'))
    assert response.status_code == 200
    assert response.context['no_location'] is True


def test_week_view_has_exactly_7_columns_monday_anchored(client_a):
    response = client_a.get(_url('calendar_week'))
    assert len(response.context['columns']) == 7
    assert response.context['week_start'].weekday() == 0


def test_week_view_chosen_defaults_to_the_first_column(client_a, resource_a1):
    response = client_a.get(_url('calendar_week'))
    assert response.context['chosen'] == resource_a1


@pytest.mark.parametrize('foreign_fixture', ['resource_b', 'resource_a2'])
def test_week_view_column_param_with_a_foreign_pk_is_ignored(
    client_a, resource_a1, foreign_fixture, request,
):
    """A cross-tenant OR cross-location resource pk in `?column=` must not be
    honoured — it degrades to the same fallback as no `?column=` at all.
    """
    foreign = request.getfixturevalue(foreign_fixture)
    response = client_a.get(_url('calendar_week'), {'column': str(foreign.pk)})
    assert response.context['chosen'] == resource_a1


def test_week_view_column_param_selects_an_authorised_resource(
    client_a, tenant_a, location_a1, resource_a1, make_resource,
):
    other = make_resource(tenant_a, location_a1, name='Room 2')
    response = client_a.get(_url('calendar_week'), {'column': str(other.pk)})
    assert response.context['chosen'] == other


def test_week_view_with_no_columns_at_all_chosen_is_none_and_queryset_empty(
    client_a, tenant_a, location_a1, contact_a, resource_a1, make_appointment,
):
    day = location_a1.local_now().date() + timedelta(days=2)
    base = dj_timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2)
    # A booking tied to a resource that is about to be deactivated...
    make_appointment(tenant_a, location_a1, contact_a, resource=resource_a1, start_at=base)
    # ...and one genuinely unassigned booking (`resource=None`) that a buggy
    # `.filter(resource=None)` fallback would incorrectly surface.
    make_appointment(tenant_a, location_a1, contact_a, start_at=base + timedelta(hours=1))
    resource_a1.is_active = False
    resource_a1.save(update_fields=['is_active'])

    response = client_a.get(_url('calendar_week'), {'date': day.isoformat()})

    assert response.context['chosen'] is None
    assert response.context['total_count'] == 0
    assert all(len(c['blocks']) == 0 for c in response.context['columns'])


def test_week_view_total_count_excludes_cancelled(
    client_a, tenant_a, location_a1, contact_a, resource_a1, make_appointment,
):
    day = location_a1.local_now().date() + timedelta(days=2)
    base = dj_timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=2)
    make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1,
        status=Appointment.STATUS_SCHEDULED, start_at=base,
    )
    make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1,
        status=Appointment.STATUS_COMPLETED, start_at=base + timedelta(hours=1),
    )
    make_appointment(
        tenant_a, location_a1, contact_a, resource=resource_a1,
        status=Appointment.STATUS_CANCELLED, start_at=base + timedelta(hours=2),
    )

    response = client_a.get(_url('calendar_week'), {'date': day.isoformat()})

    assert response.context['total_count'] == 2


# --------------------------------------------------------------------------- #
# appointment_create_view click-through (4.4's addition)
# --------------------------------------------------------------------------- #

def test_create_view_start_param_prefills_the_clicked_wall_clock(client_a):
    response = client_a.get(_url('appointment_create'), {'start': '2030-06-15T14:30'})
    assert response.status_code == 200
    initial_start = response.context['form'].initial['start_at']
    assert (initial_start.year, initial_start.month, initial_start.day) == (2030, 6, 15)
    assert (initial_start.hour, initial_start.minute) == (14, 30)


def test_create_view_resource_param_prefills_when_authorised(client_a, resource_a1):
    response = client_a.get(_url('appointment_create'), {'resource': str(resource_a1.pk)})
    assert response.context['form'].initial.get('resource') == resource_a1.pk


def test_create_view_provider_param_prefills_when_authorised(client_a, provider_a1):
    response = client_a.get(_url('appointment_create'), {'provider': str(provider_a1.pk)})
    assert response.context['form'].initial.get('provider') == provider_a1.pk


def test_create_view_resource_param_cross_location_is_not_honoured(client_a, resource_a2):
    response = client_a.get(_url('appointment_create'), {'resource': str(resource_a2.pk)})
    assert response.status_code == 200
    assert 'resource' not in response.context['form'].initial


def test_create_view_resource_param_cross_tenant_is_not_honoured(client_a, resource_b):
    response = client_a.get(_url('appointment_create'), {'resource': str(resource_b.pk)})
    assert response.status_code == 200
    assert 'resource' not in response.context['form'].initial


def test_create_view_absurd_start_param_degrades_to_200(client_a):
    response = client_a.get(_url('appointment_create'), {'start': '9999-12-31T10:00'})
    assert response.status_code == 200
    assert 'start_at' not in response.context['form'].initial


# --------------------------------------------------------------------------- #
# Query bound — one `scheduling_appointment` query regardless of row count
# --------------------------------------------------------------------------- #

def test_day_view_issues_one_appointment_query_regardless_of_row_count(
    client_a, tenant_a, location_a1, contact_a, make_appointment, make_resource,
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    resources = [make_resource(tenant_a, location_a1, name=f'Room {i}') for i in range(4)]
    day = location_a1.local_now().date() + timedelta(days=2)
    base = dj_timezone.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=2)
    for i in range(20):
        make_appointment(
            tenant_a, location_a1, contact_a,
            resource=resources[i % len(resources)],
            start_at=base + timedelta(minutes=i * 15),
            duration_minutes=15,
        )

    with CaptureQueriesContext(connection) as captured:
        response = client_a.get(_url('calendar_day'), {'date': day.isoformat()})

    assert response.status_code == 200
    appointment_queries = [
        q for q in captured.captured_queries
        if 'scheduling_appointment' in q['sql'].lower()
    ]
    assert len(appointment_queries) == 1
