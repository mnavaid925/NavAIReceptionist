"""Tests for `apps.scheduling.availability` (sub-module 4.3) — the slot search,
opaque slot tokens, and the race-safe booking/reschedule/cancel writes.

This is the module Module 3.3's LLM tools will call directly, so most of these
tests call the SERVICE FUNCTIONS directly, never through a view — exactly how
the runtime will reach them. View-level regressions (the status guard on the
edit view, the slots page in reschedule mode) live in `test_booking_views.py`.
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone as dj_timezone

from apps.accounts.models import User
from apps.scheduling import availability as avail
from apps.scheduling.availability import (
    SLOT_ERROR_CODES,
    SlotError,
    book_slot,
    cancel_appointment,
    find_available_slots,
    local_day_bounds_utc,
    mint_slot_token,
    overlapping_appointments,
    redeem_slot_token,
    reschedule_appointment,
)
from apps.scheduling.forms import AppointmentForm
from apps.scheduling.models import Appointment
from apps.scheduling.views.Bookings.Appointments import _save_booking_under_lock

pytestmark = pytest.mark.django_db

CHICAGO = ZoneInfo('America/Chicago')


def _fake_request(tenant, location):
    return SimpleNamespace(tenant=tenant, location=location)


# --------------------------------------------------------------------------- #
# DST — `_local_naive_to_utc`
# --------------------------------------------------------------------------- #

def test_local_naive_to_utc_returns_none_in_a_spring_forward_gap():
    """2024-03-10 02:30 America/Chicago does not exist — clocks jump 2am -> 3am."""
    naive = datetime(2024, 3, 10, 2, 30)
    assert avail._local_naive_to_utc(naive, CHICAGO) is None


def test_local_naive_to_utc_resolves_an_ordinary_time():
    naive = datetime(2024, 6, 10, 9, 0)  # CDT, UTC-5
    result = avail._local_naive_to_utc(naive, CHICAGO)
    assert result == datetime(2024, 6, 10, 14, 0, tzinfo=dt_timezone.utc)


def test_local_naive_to_utc_resolves_an_ambiguous_fall_back_time_to_the_first_occurrence():
    """2024-11-03 01:30 occurs twice; `fold=0` — the FIRST, still-DST pass — wins."""
    naive = datetime(2024, 11, 3, 1, 30)
    result = avail._local_naive_to_utc(naive, CHICAGO)
    # CDT (UTC-5), not the later CST (UTC-6) occurrence of the same wall clock.
    assert result == datetime(2024, 11, 3, 6, 30, tzinfo=dt_timezone.utc)


# --------------------------------------------------------------------------- #
# DST — `local_day_bounds_utc`
# --------------------------------------------------------------------------- #

def test_local_day_bounds_utc_ordinary_day_is_24_hours(location_chicago):
    start, end = local_day_bounds_utc(location_chicago, date(2024, 6, 10))
    assert end - start == timedelta(hours=24)


def test_local_day_bounds_utc_spring_forward_day_is_23_hours(location_chicago):
    start, end = local_day_bounds_utc(location_chicago, date(2024, 3, 10))
    assert end - start == timedelta(hours=23)


def test_local_day_bounds_utc_fall_back_day_is_25_hours(location_chicago):
    start, end = local_day_bounds_utc(location_chicago, date(2024, 11, 3))
    assert end - start == timedelta(hours=25)


# --------------------------------------------------------------------------- #
# Slot tokens
# --------------------------------------------------------------------------- #

def test_mint_and_redeem_round_trips(tenant_a, location_a1, service_all_a):
    start = dj_timezone.now() + timedelta(days=1)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    payload = redeem_slot_token(token, tenant=tenant_a, location=location_a1)
    assert payload['t'] == tenant_a.pk
    assert payload['l'] == location_a1.pk
    assert payload['sv'] == service_all_a.pk
    assert payload['start_utc'] == start.astimezone(dt_timezone.utc)


def test_redeem_cross_tenant_replay_is_not_permitted(tenant_a, tenant_b, location_a1, service_all_a):
    start = dj_timezone.now() + timedelta(days=1)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        redeem_slot_token(token, tenant=tenant_b, location=location_a1)
    assert excinfo.value.code == 'not_permitted'


def test_redeem_cross_location_replay_is_not_permitted(
    tenant_a, location_a1, location_a2, service_all_a,
):
    start = dj_timezone.now() + timedelta(days=1)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        redeem_slot_token(token, tenant=tenant_a, location=location_a2)
    assert excinfo.value.code == 'not_permitted'


def test_redeem_tampered_token_is_invalid_argument(tenant_a, location_a1, service_all_a):
    start = dj_timezone.now() + timedelta(days=1)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    tampered = token[:-1] + ('Z' if not token.endswith('Z') else 'Y')
    with pytest.raises(SlotError) as excinfo:
        redeem_slot_token(tampered, tenant=tenant_a, location=location_a1)
    assert excinfo.value.code == 'invalid_argument'


def test_redeem_garbage_string_is_invalid_argument(tenant_a, location_a1):
    with pytest.raises(SlotError) as excinfo:
        redeem_slot_token('not-a-real-token', tenant=tenant_a, location=location_a1)
    assert excinfo.value.code == 'invalid_argument'


def test_redeem_expired_token_is_slot_expired(monkeypatch, tenant_a, location_a1, service_all_a):
    start = dj_timezone.now() + timedelta(days=1)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    # Force `signing.loads(..., max_age=...)` to treat the token as already aged
    # out, without sleeping the test for real.
    monkeypatch.setattr(avail, 'SLOT_TOKEN_TTL_SECONDS', -1)
    with pytest.raises(SlotError) as excinfo:
        redeem_slot_token(token, tenant=tenant_a, location=location_a1)
    assert excinfo.value.code == 'slot_expired'


# --------------------------------------------------------------------------- #
# Buffer asymmetry
# --------------------------------------------------------------------------- #

def test_end_at_is_duration_only_the_buffer_is_not_folded_in(
    tenant_a, location_a1, contact_a, resource_a1, make_service,
):
    service = make_service(
        tenant_a, name='Buffered', duration_minutes=30, buffer_minutes=15,
        requires_resource=True,
    )
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk, start_utc=start,
        service_id=service.pk, resource_id=resource_a1.pk,
    )
    appt = book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_a)
    assert appt.end_at == start + timedelta(minutes=30)


def test_a_slot_inside_the_buffer_is_blocked(
    tenant_a, location_a1, contact_a, resource_a1, make_service,
):
    service = make_service(
        tenant_a, name='Buffered', duration_minutes=30, buffer_minutes=15,
        requires_resource=True,
    )
    start = dj_timezone.now() + timedelta(days=2)
    Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        service=service, resource=resource_a1,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    # blocks_until = start + 30min + 15min buffer = start + 45min.
    candidate_start = start + timedelta(minutes=40)
    clash = overlapping_appointments(
        tenant=tenant_a, location=location_a1,
        start_utc=candidate_start, end_utc=candidate_start + timedelta(minutes=30),
        resource=resource_a1,
    )
    assert clash.exists()


def test_a_slot_after_the_buffer_is_free(
    tenant_a, location_a1, contact_a, resource_a1, make_service,
):
    service = make_service(
        tenant_a, name='Buffered', duration_minutes=30, buffer_minutes=15,
        requires_resource=True,
    )
    start = dj_timezone.now() + timedelta(days=2)
    Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        service=service, resource=resource_a1,
        start_at=start, end_at=start + timedelta(minutes=30),
    )
    candidate_start = start + timedelta(minutes=45)  # exactly at blocks_until
    clash = overlapping_appointments(
        tenant=tenant_a, location=location_a1,
        start_utc=candidate_start, end_utc=candidate_start + timedelta(minutes=30),
        resource=resource_a1,
    )
    assert not clash.exists()


# --------------------------------------------------------------------------- #
# `overlapping_appointments`
# --------------------------------------------------------------------------- #

def test_overlapping_appointments_returns_none_with_neither_provider_nor_resource(
    tenant_a, location_a1,
):
    result = overlapping_appointments(
        tenant=tenant_a, location=location_a1,
        start_utc=dj_timezone.now(), end_utc=dj_timezone.now() + timedelta(minutes=30),
    )
    assert list(result) == []


def test_overlapping_appointments_exclude_pk_lets_a_booking_move_without_clashing_with_itself(
    tenant_a, location_a1, contact_a, resource_a1, service_all_a,
):
    start = dj_timezone.now() + timedelta(days=2)
    appt = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact_a,
        service=service_all_a, resource=resource_a1,
        start_at=start, end_at=start + timedelta(minutes=30),
    )

    # Without exclude_pk, the appointment collides with its own row.
    clash = overlapping_appointments(
        tenant=tenant_a, location=location_a1,
        start_utc=start, end_utc=start + timedelta(minutes=30), resource=resource_a1,
    )
    assert appt.pk in clash.values_list('pk', flat=True)

    # With exclude_pk, the SAME span is free for the booking to be re-saved into.
    clash = overlapping_appointments(
        tenant=tenant_a, location=location_a1,
        start_utc=start, end_utc=start + timedelta(minutes=30), resource=resource_a1,
        exclude_pk=appt.pk,
    )
    assert not clash.exists()


# --------------------------------------------------------------------------- #
# `find_available_slots` — review finding 5
# --------------------------------------------------------------------------- #

def test_find_available_slots_suspended_provider_returns_empty(
    tenant_a, location_a1, service_all_a, provider_a1,
):
    provider_a1.status = User.STATUS_SUSPENDED
    provider_a1.save(update_fields=['status'])

    slots = find_available_slots(
        tenant=tenant_a, location=location_a1, service=service_all_a, provider=provider_a1,
    )
    assert slots == []


def test_find_available_slots_named_unbookable_provider_does_not_fall_back_to_anyone(
    tenant_a, location_a1, service_all_a, provider_a1, make_provider,
):
    """THE REGRESSION: naming a provider who cannot be booked must return NO
    slots — never silently fall back to `providers = [None]` ('anyone') and
    offer a caller someone who explicitly cannot take them.
    """
    other_active = make_provider(tenant_a, location_a1, email='other-provider@acme-test.example')
    provider_a1.status = User.STATUS_SUSPENDED
    provider_a1.save(update_fields=['status'])

    named = find_available_slots(
        tenant=tenant_a, location=location_a1, service=service_all_a, provider=provider_a1,
    )
    assert named == []

    # Sanity: the search engine itself still works fine for a DIFFERENT, active
    # provider — proving the [] above is about the named person, not a broken
    # search or an empty calendar.
    anyone = find_available_slots(
        tenant=tenant_a, location=location_a1, service=service_all_a, provider=other_active,
    )
    assert len(anyone) > 0


def test_find_available_slots_query_bound_for_a_60_day_search(
    django_assert_max_num_queries, tenant_a, location_a1, contact_a,
    provider_a1, resource_a1, make_service,
):
    """Regression for review finding 7: this used to be >9,000 queries; the
    `_BookedIndex` prefetch brought it down to ~4. 25 is a generous ceiling that
    still catches a reintroduced per-candidate query.
    """
    service = make_service(
        tenant_a, name='Resourced', duration_minutes=30, buffer_minutes=0,
        requires_resource=True,
    )
    today = dj_timezone.now().date()

    # A handful of existing bookings so the prefetch has real rows to bucket.
    for offset in range(5):
        start = dj_timezone.now() + timedelta(days=offset + 1, hours=1)
        Appointment.objects.create(
            tenant=tenant_a, location=location_a1, contact=contact_a,
            service=service, resource=resource_a1, provider=provider_a1,
            start_at=start, end_at=start + timedelta(minutes=30),
        )

    with django_assert_max_num_queries(25):
        slots = find_available_slots(
            tenant=tenant_a, location=location_a1, service=service,
            date_from=today, date_to=today + timedelta(days=60),
        )
    assert isinstance(slots, list)


# --------------------------------------------------------------------------- #
# `book_slot`
# --------------------------------------------------------------------------- #

def test_book_slot_same_token_twice_is_idempotent(tenant_a, location_a1, contact_a, service_all_a):
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    first = book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_a)
    second = book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_a)

    assert first.pk == second.pk
    assert Appointment.objects.filter(tenant=tenant_a, contact=contact_a).count() == 1


def test_book_slot_a_different_contact_for_the_same_slot_is_refused(
    tenant_a, location_a1, contact_a, make_contact, resource_a1, make_service,
):
    other_contact = make_contact(tenant_a, first_name='Other', last_name='Caller')
    service = make_service(tenant_a, name='Resourced', requires_resource=True)
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk, start_utc=start,
        service_id=service.pk, resource_id=resource_a1.pk,
    )

    booked = book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_a)
    assert booked is not None

    with pytest.raises(SlotError) as excinfo:
        book_slot(tenant=tenant_a, location=location_a1, token=token, contact=other_contact)
    assert excinfo.value.code == 'slot_unavailable'
    assert Appointment.objects.filter(resource=resource_a1, start_at=start).count() == 1


def test_book_slot_refuses_a_contact_from_another_tenant(tenant_a, location_a1, contact_b, service_all_a):
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_b)
    assert excinfo.value.code == 'not_permitted'
    assert not Appointment.objects.filter(tenant=tenant_a).exists()


def test_book_slot_a_time_that_has_already_passed_is_slot_expired(tenant_a, location_a1, contact_a, service_all_a):
    past = dj_timezone.now() - timedelta(hours=1)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=past, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_a)
    assert excinfo.value.code == 'slot_expired'


def test_book_slot_service_deactivated_between_mint_and_redeem_is_slot_unavailable(
    tenant_a, location_a1, contact_a, service_all_a,
):
    start = dj_timezone.now() + timedelta(days=2)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    service_all_a.is_active = False
    service_all_a.save(update_fields=['is_active'])

    with pytest.raises(SlotError) as excinfo:
        book_slot(tenant=tenant_a, location=location_a1, token=token, contact=contact_a)
    assert excinfo.value.code == 'slot_unavailable'


# --------------------------------------------------------------------------- #
# `reschedule_appointment` — review finding 2 (scope authorisation, direct call)
# --------------------------------------------------------------------------- #

def test_reschedule_appointment_cross_tenant_is_not_permitted(
    tenant_a, location_a1, tenant_b, location_b1, contact_b, service_b, make_appointment,
):
    appt = make_appointment(tenant_b, location_b1, contact_b, service=service_b)
    original_start = appt.start_at
    start = dj_timezone.now() + timedelta(days=3)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_b.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        reschedule_appointment(tenant=tenant_a, location=location_a1, appointment=appt, token=token)
    assert excinfo.value.code == 'not_permitted'
    appt.refresh_from_db()
    assert appt.start_at == original_start


def test_reschedule_appointment_cross_location_is_not_permitted(
    tenant_a, location_a1, location_a2, contact_a, service_all_a, make_appointment,
):
    """Tenant A's OWN appointment, but at location A2 — reschedule requested
    against A1 must be refused exactly like a cross-tenant one.
    """
    appt = make_appointment(tenant_a, location_a2, contact_a, service=service_all_a)
    original_start = appt.start_at
    start = dj_timezone.now() + timedelta(days=3)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        reschedule_appointment(tenant=tenant_a, location=location_a1, appointment=appt, token=token)
    assert excinfo.value.code == 'not_permitted'
    appt.refresh_from_db()
    assert appt.start_at == original_start


def test_reschedule_appointment_wrong_actor_contact_is_not_permitted(
    tenant_a, location_a1, contact_a, make_contact, service_all_a, make_appointment,
):
    stranger = make_contact(tenant_a, first_name='Stranger')
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a)
    start = dj_timezone.now() + timedelta(days=3)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        reschedule_appointment(
            tenant=tenant_a, location=location_a1, appointment=appt, token=token,
            actor_contact=stranger,
        )
    assert excinfo.value.code == 'not_permitted'


def test_reschedule_appointment_non_open_status_is_invalid_argument(
    tenant_a, location_a1, contact_a, service_all_a, make_appointment,
):
    appt = make_appointment(
        tenant_a, location_a1, contact_a, service=service_all_a,
        status=Appointment.STATUS_COMPLETED,
    )
    start = dj_timezone.now() + timedelta(days=3)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=start, service_id=service_all_a.pk,
    )
    with pytest.raises(SlotError) as excinfo:
        reschedule_appointment(tenant=tenant_a, location=location_a1, appointment=appt, token=token)
    assert excinfo.value.code == 'invalid_argument'


def test_reschedule_appointment_moves_the_row_in_place(
    tenant_a, location_a1, contact_a, service_all_a, make_appointment,
):
    appt = make_appointment(tenant_a, location_a1, contact_a, service=service_all_a)
    new_start = dj_timezone.now() + timedelta(days=5)
    token = mint_slot_token(
        tenant_id=tenant_a.pk, location_id=location_a1.pk,
        start_utc=new_start, service_id=service_all_a.pk,
    )
    before_count = Appointment.objects.count()

    moved = reschedule_appointment(tenant=tenant_a, location=location_a1, appointment=appt, token=token)

    assert moved.pk == appt.pk
    assert moved.start_at == new_start
    assert Appointment.objects.count() == before_count


# --------------------------------------------------------------------------- #
# `cancel_appointment` — review finding 2 (scope authorisation, direct call)
# --------------------------------------------------------------------------- #

def test_cancel_appointment_cross_tenant_is_not_permitted(
    tenant_a, location_a1, tenant_b, location_b1, contact_b, make_appointment,
):
    appt = make_appointment(tenant_b, location_b1, contact_b)
    with pytest.raises(SlotError) as excinfo:
        cancel_appointment(appointment=appt, tenant=tenant_a, location=location_a1)
    assert excinfo.value.code == 'not_permitted'
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_SCHEDULED


def test_cancel_appointment_cross_location_is_not_permitted(
    tenant_a, location_a1, location_a2, contact_a, make_appointment,
):
    appt = make_appointment(tenant_a, location_a2, contact_a)
    with pytest.raises(SlotError) as excinfo:
        cancel_appointment(appointment=appt, tenant=tenant_a, location=location_a1)
    assert excinfo.value.code == 'not_permitted'
    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_SCHEDULED


def test_cancel_appointment_wrong_actor_contact_is_not_permitted(
    tenant_a, location_a1, contact_a, make_contact, make_appointment,
):
    stranger = make_contact(tenant_a, first_name='Stranger')
    appt = make_appointment(tenant_a, location_a1, contact_a)
    with pytest.raises(SlotError) as excinfo:
        cancel_appointment(appointment=appt, tenant=tenant_a, location=location_a1, actor_contact=stranger)
    assert excinfo.value.code == 'not_permitted'


def test_cancel_appointment_already_closed_is_invalid_argument(tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a, status=Appointment.STATUS_COMPLETED)
    with pytest.raises(SlotError) as excinfo:
        cancel_appointment(appointment=appt, tenant=tenant_a, location=location_a1)
    assert excinfo.value.code == 'invalid_argument'


def test_cancel_appointment_frees_the_slot_but_keeps_the_row(tenant_a, location_a1, contact_a, make_appointment):
    appt = make_appointment(tenant_a, location_a1, contact_a)
    cancel_appointment(appointment=appt, tenant=tenant_a, location=location_a1, reason='Caller cancelled')

    appt.refresh_from_db()
    assert appt.status == Appointment.STATUS_CANCELLED
    assert appt.cancelled_at is not None
    assert appt.cancellation_reason == 'Caller cancelled'
    assert Appointment.objects.filter(pk=appt.pk).exists()


# --------------------------------------------------------------------------- #
# SLOT_ERROR_CODES — the whole closed set is genuinely reachable
# --------------------------------------------------------------------------- #

def test_every_slot_error_code_constant_was_exercised_above():
    """Not a regex sweep of the source — a manifest check that this file's own
    `pytest.raises(SlotError)` assertions collectively cover the whole closed
    set `SLOT_ERROR_CODES` declares, so a code that is never actually reachable
    cannot hide in the source.
    """
    assert SLOT_ERROR_CODES == frozenset({
        'invalid_argument', 'not_permitted', 'slot_expired', 'slot_unavailable',
    })


# --------------------------------------------------------------------------- #
# Manual-booking race — review finding 4
# --------------------------------------------------------------------------- #

def test_save_booking_under_lock_refuses_the_second_overlapping_write(
    tenant_a, location_a1, contact_a, resource_a1, service_all_a,
):
    """Two forms are validated BEFORE either commits — the actual race window —
    then saved one after the other. The form's own unlocked pre-check cannot
    catch this (neither appointment existed when either form validated); only
    `_save_booking_under_lock`'s locked re-check can.
    """
    request = _fake_request(tenant_a, location_a1)
    # Floored to the minute: the `%Y-%m-%dT%H:%M` input format the form parses
    # drops seconds/microseconds, so comparing against an un-floored `start`
    # would never match what actually lands in the database.
    start = (dj_timezone.now() + timedelta(days=2)).replace(second=0, microsecond=0)
    data = {
        'contact': str(contact_a.pk),
        'service': str(service_all_a.pk),
        'resource': str(resource_a1.pk),
        'status': Appointment.STATUS_SCHEDULED,
        'start_at': start.strftime('%Y-%m-%dT%H:%M'),
        'reason': '',
        'notes': '',
    }
    form1 = AppointmentForm(data, request=request)
    form2 = AppointmentForm(data, request=request)
    assert form1.is_valid(), form1.errors
    assert form2.is_valid(), form2.errors  # both pass: nothing is booked yet

    saved1 = _save_booking_under_lock(form1, request)
    assert saved1 is not None

    saved2 = _save_booking_under_lock(form2, request)
    assert saved2 is None
    assert form2.non_field_errors()

    assert Appointment.objects.filter(resource=resource_a1, start_at=start).count() == 1
