"""Model tests for `scheduling.Appointment` (sub-module 4.3)."""
from datetime import timedelta

import pytest
from django.utils import timezone as dj_timezone

from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def _future():
    return dj_timezone.now() + timedelta(days=2)


# --------------------------------------------------------------------------- #
# Defaults and choices
# --------------------------------------------------------------------------- #

def test_default_status_is_scheduled(tenant_a, location_a1, contact_a):
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert obj.status == Appointment.STATUS_SCHEDULED


def test_default_source_is_manual(tenant_a, location_a1, contact_a):
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert obj.source == Appointment.SOURCE_MANUAL


def test_status_choices_use_underscore_no_show_not_noshow():
    """The shared badge partial branches on the literal string `no_show`."""
    values = dict(Appointment.STATUS_CHOICES)
    assert 'no_show' in values
    assert 'noshow' not in values


def test_open_statuses_are_scheduled_and_confirmed():
    assert Appointment.OPEN_STATUSES == (
        Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED,
    )


def test_str_renders_contact_and_start(tenant_a, location_a1, contact_a):
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert str(obj) == f'{contact_a} — {start:%Y-%m-%d %H:%M}'


# --------------------------------------------------------------------------- #
# Computed properties
# --------------------------------------------------------------------------- #

def test_duration_minutes_reflects_the_stored_span(tenant_a, location_a1, contact_a):
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        start_at=start, end_at=start + timedelta(minutes=45),
    )
    assert obj.duration_minutes == 45


def test_buffer_minutes_reads_from_the_service(tenant_a, location_a1, contact_a, make_service):
    service = make_service(tenant_a, name='Buffered', buffer_minutes=15)
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, service=service,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert obj.buffer_minutes == 15


def test_buffer_minutes_is_zero_when_service_is_null(tenant_a, location_a1, contact_a):
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, service=None,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert obj.buffer_minutes == 0


def test_blocks_until_is_end_at_plus_buffer(tenant_a, location_a1, contact_a, make_service):
    service = make_service(tenant_a, name='Buffered', buffer_minutes=10)
    start = _future()
    end = start + timedelta(minutes=30)
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, service=service,
        start_at=start, end_at=end,
    )
    assert obj.blocks_until == end + timedelta(minutes=10)


@pytest.mark.parametrize('status, expected', [
    (Appointment.STATUS_SCHEDULED, True),
    (Appointment.STATUS_CONFIRMED, True),
    (Appointment.STATUS_COMPLETED, False),
    (Appointment.STATUS_CANCELLED, False),
    (Appointment.STATUS_NO_SHOW, False),
])
def test_is_open_matches_open_statuses(tenant_a, location_a1, contact_a, status, expected):
    start = _future()
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a, status=status,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert obj.is_open is expected


def test_is_cancelled_true_only_for_cancelled(tenant_a, location_a1, contact_a):
    start = _future()
    scheduled = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        status=Appointment.STATUS_SCHEDULED,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    cancelled = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        status=Appointment.STATUS_CANCELLED,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert scheduled.is_cancelled is False
    assert cancelled.is_cancelled is True


def test_local_start_and_local_end_use_the_locations_timezone(
    tenant_a, location_chicago, contact_a,
):
    from zoneinfo import ZoneInfo

    start = dj_timezone.now() + timedelta(days=2)
    obj = Appointment.objects.create(
        tenant=tenant_a, location=location_chicago, contact=contact_a,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    assert obj.local_start() == start.astimezone(ZoneInfo('America/Chicago'))
    assert obj.local_end() == obj.end_at.astimezone(ZoneInfo('America/Chicago'))
    # A real offset, not the UTC 0:00 the raw `start_at` would render as.
    assert obj.local_start().utcoffset() != timedelta(0)
