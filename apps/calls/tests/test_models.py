"""Model tests for `calls.CallSession` (sub-module 5.1).

Covers Invariant 2's whole surface — the seven JSON columns default correctly —
plus the two things that make this row safe to build on: `provider_call_sid`'s
DB-level uniqueness (Module 3's webhook idempotency key) and the two SET_NULL
relations that must survive the row they point at being deleted.
"""
import json

from django.db import IntegrityError, transaction
from django.utils import timezone as dj_timezone

import pytest

from apps.calls.models import CallSession
from apps.scheduling.models import Appointment, Contact

pytestmark = pytest.mark.django_db


def _minimal(tenant, location, **overrides):
    """A bare `CallSession.objects.create(...)` with only the required fields,
    so defaults are visible rather than shadowed by a fixture's own opinions.
    """
    defaults = {
        'from_number': '+13125550101',
        'to_number': '+13125550140',
        'provider_call_sid': 'CA0000000000000000000000000001',
    }
    defaults.update(overrides)
    return CallSession.objects.create(tenant=tenant, location=location, **defaults)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

def test_default_channel_is_agent_phone(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.channel == 'agent_phone'


def test_default_mode_is_live(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.mode == CallSession.MODE_LIVE


def test_default_status_is_in_progress(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.status == CallSession.STATUS_IN_PROGRESS


def test_default_contact_is_null(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.contact_id is None


def test_default_recording_blob_is_empty_string(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.recording_blob == ''


def test_default_started_and_ended_at_are_null(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.started_at is None
    assert obj.ended_at is None


# -- the seven JSON columns — Invariant 2's whole surface -------------------- #

def test_default_transcript_is_empty_list(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.transcript == []


def test_default_logs_is_empty_list(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.logs == []


def test_default_analysis_is_empty_dict(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.analysis == {}


def test_default_usage_is_empty_list(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.usage == []


def test_default_transfer_is_empty_dict(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.transfer == {}


def test_default_waveform_peaks_is_null_not_empty_dict(tenant_a, location_a1):
    """NULL, not `{}` — absent means "never computed", which is not the same
    claim as a recording that is genuinely silent (the column's own help text).
    """
    obj = _minimal(tenant_a, location_a1)
    assert obj.waveform_peaks is None


def test_default_metadata_is_empty_dict(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.metadata == {}


def test_json_columns_round_trip_their_shapes(tenant_a, location_a1):
    """Appended turns keep `sequence` ordering; usage sums to the call total."""
    transcript = [
        {'sequence': 1, 'role': 'agent', 'text': 'Hello', 'at': '2026-01-01T00:00:00+00:00', 'offset': 0},
        {'sequence': 2, 'role': 'user', 'text': 'Hi', 'at': '2026-01-01T00:00:05+00:00', 'offset': 5},
    ]
    usage = [
        {'turn_sequence': 1, 'cost_breakdown': {'stt_usd': 0.001, 'llm_usd': 0.002}, 'cost_usd': 0.003},
        {'turn_sequence': 2, 'cost_breakdown': {'stt_usd': 0.001, 'llm_usd': 0.004}, 'cost_usd': 0.005},
    ]
    obj = _minimal(tenant_a, location_a1, transcript=transcript, usage=usage)
    obj.refresh_from_db()

    assert [t['sequence'] for t in obj.transcript] == [1, 2]
    assert obj.transcript == transcript
    total = round(sum(u['cost_usd'] for u in obj.usage), 4)
    assert total == 0.008


# --------------------------------------------------------------------------- #
# Ordering, __str__, choices
# --------------------------------------------------------------------------- #

def test_ordering_is_newest_created_first(tenant_a, location_a1):
    from datetime import timedelta

    older = _minimal(tenant_a, location_a1, provider_call_sid='CA-older')
    newer = _minimal(tenant_a, location_a1, provider_call_sid='CA-newer')
    # `auto_now_add` stamps both from the real clock, which on Windows can tie at
    # its ~15ms resolution — back-date one explicitly so ordering is deterministic.
    CallSession.objects.filter(pk=older.pk).update(
        created_at=dj_timezone.now() - timedelta(hours=1),
    )

    assert list(CallSession.objects.filter(tenant=tenant_a)) == [newer, older]


def test_str_renders_sid_and_status_display(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1, status=CallSession.STATUS_TRANSFERRED)
    assert str(obj) == f'{obj.provider_call_sid} — Transferred'


def test_status_choices_have_exactly_five_values():
    values = [value for value, _ in CallSession.STATUS_CHOICES]
    assert values == ['in_progress', 'completed', 'abandoned', 'transferred', 'failed']


def test_mode_choices_are_live_google_gemini():
    values = [value for value, _ in CallSession.MODE_CHOICES]
    assert values == ['live', 'google', 'gemini']


# --------------------------------------------------------------------------- #
# duration_display — every case, including the skewed-clock one
# --------------------------------------------------------------------------- #

def test_duration_display_both_stamps_set(tenant_a, location_a1):
    from datetime import timedelta

    started = dj_timezone.now()
    obj = _minimal(tenant_a, location_a1, started_at=started, ended_at=started + timedelta(seconds=95))
    assert obj.duration_display == '1m 35s'


def test_duration_display_seconds_only(tenant_a, location_a1):
    from datetime import timedelta

    started = dj_timezone.now()
    obj = _minimal(tenant_a, location_a1, started_at=started, ended_at=started + timedelta(seconds=45))
    assert obj.duration_display == '45s'


def test_duration_display_hours_minutes_seconds(tenant_a, location_a1):
    from datetime import timedelta

    started = dj_timezone.now()
    obj = _minimal(tenant_a, location_a1, started_at=started, ended_at=started + timedelta(hours=1, minutes=2, seconds=3))
    assert obj.duration_display == '1h 2m 3s'


def test_duration_display_only_started_at_reads_in_progress(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1, started_at=dj_timezone.now())
    assert obj.duration_display == 'In progress'


def test_duration_display_neither_stamp_reads_dash(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.duration_display == '—'


def test_duration_display_ended_with_no_started_reads_dash(tenant_a, location_a1):
    """An `ended_at` with no `started_at` — nothing to measure from."""
    obj = _minimal(tenant_a, location_a1, ended_at=dj_timezone.now())
    assert obj.duration_display == '—'


def test_duration_display_skewed_clocks_never_print_a_negative(tenant_a, location_a1):
    """`ended_at` before `started_at` — two provider clocks disagreeing. The
    property must report the dash, never a negative duration.
    """
    from datetime import timedelta

    started = dj_timezone.now()
    obj = _minimal(tenant_a, location_a1, started_at=started, ended_at=started - timedelta(seconds=30))
    assert obj.duration_display == '—'
    assert '-' not in obj.duration_display


# --------------------------------------------------------------------------- #
# provider_call_sid — the DB-level uniqueness that makes webhook redelivery
# idempotent. Module 3's whole idempotency story depends on this being a REAL
# constraint, not merely a declared one.
# --------------------------------------------------------------------------- #

def test_provider_call_sid_is_unique_across_the_same_tenant(tenant_a, location_a1):
    _minimal(tenant_a, location_a1, provider_call_sid='CA-dupe-0001')

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _minimal(tenant_a, location_a1, provider_call_sid='CA-dupe-0001')


def test_provider_call_sid_is_unique_across_different_tenants(tenant_a, tenant_b, location_a1, location_b1):
    """The global exception CLAUDE.md calls out for `inbound_phone_number` does
    NOT apply here — `provider_call_sid` has no such carve-out, and two tenants
    racing the same Twilio CallSid (impossible in practice, but the constraint
    must not assume that) must still collide.
    """
    _minimal(tenant_a, location_a1, provider_call_sid='CA-global-dupe')

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _minimal(tenant_b, location_b1, provider_call_sid='CA-global-dupe')


# --------------------------------------------------------------------------- #
# contact SET_NULL — erasing a person must never delete the call record
# --------------------------------------------------------------------------- #

def test_contact_delete_sets_null_and_keeps_the_session(tenant_a, location_a1):
    contact = Contact.objects.create(tenant=tenant_a, first_name='Priya', last_name='Raman')
    session = _minimal(tenant_a, location_a1, contact=contact, provider_call_sid='CA-contact-0001')

    contact.delete()
    session.refresh_from_db()

    assert session.contact_id is None
    assert CallSession.objects.filter(pk=session.pk).exists()


# --------------------------------------------------------------------------- #
# booked_by_session SET_NULL (on Appointment) — deleting the CALL must never
# delete the booking it produced, and the reverse accessor must work.
# --------------------------------------------------------------------------- #

def test_deleting_call_session_nulls_booked_by_session_but_keeps_the_appointment(
    tenant_a, location_a1,
):
    from datetime import timedelta

    contact = Contact.objects.create(tenant=tenant_a, first_name='Dana', last_name='Whitfield')
    session = _minimal(tenant_a, location_a1, contact=contact, provider_call_sid='CA-books-0001')
    start = dj_timezone.now() + timedelta(days=1)
    appt = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact,
        start_at=start, end_at=start + timedelta(minutes=30),
        source=Appointment.SOURCE_AI_PHONE, booked_by_session=session,
    )

    session.delete()
    appt.refresh_from_db()

    assert appt.booked_by_session_id is None
    assert Appointment.objects.filter(pk=appt.pk).exists()
    # `source` is untouched — it is the provenance record and survives the FK
    # going null, exactly as the model's own docstring says it must.
    assert appt.source == Appointment.SOURCE_AI_PHONE


# --------------------------------------------------------------------------- #
# total_cost_usd — derived at read time from `usage`, sub-module 5.3
# --------------------------------------------------------------------------- #

def test_total_cost_usd_sums_across_turns(tenant_a, location_a1):
    usage = [
        {'turn_sequence': 1, 'cost_usd': 0.01},
        {'turn_sequence': 2, 'cost_usd': 0.02},
        {'turn_sequence': 3, 'cost_usd': 0.005},
    ]
    obj = _minimal(tenant_a, location_a1, usage=usage)
    assert obj.total_cost_usd == 0.035


def test_total_cost_usd_is_zero_for_empty_usage_list(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1, usage=[])
    assert obj.total_cost_usd == 0


def test_total_cost_usd_is_zero_for_default_usage(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    assert obj.usage == []
    assert obj.total_cost_usd == 0


@pytest.mark.parametrize('bad_usage', [42, {'x': 1}, 'not-a-list', True, None])
def test_total_cost_usd_returns_zero_for_non_list_usage_never_raises(tenant_a, location_a1, bad_usage):
    """Regression: `usage` that is not a list at all — a bare number, a dict, a
    bool, `None` — must contribute 0 rather than raise `TypeError` out of the
    property (`for turn in 42` would otherwise 500 the detail page).
    """
    obj = _minimal(tenant_a, location_a1)
    obj.usage = bad_usage
    assert obj.total_cost_usd == 0


def test_total_cost_usd_skips_a_non_dict_entry(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    obj.usage = ['not-a-dict', 42, None, {'turn_sequence': 1, 'cost_usd': 0.03}]
    assert obj.total_cost_usd == 0.03


def test_total_cost_usd_skips_a_non_numeric_cost(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    obj.usage = [
        {'turn_sequence': 1, 'cost_usd': 'not-a-number'},
        {'turn_sequence': 2, 'cost_usd': 0.05},
    ]
    assert obj.total_cost_usd == 0.05


def test_total_cost_usd_skips_nan_and_infinity_but_sums_real_charges(tenant_a, location_a1):
    """`json.loads` accepts `NaN`/`Infinity`/`-Infinity` as an extension, and
    both would otherwise propagate through the sum onto a billing figure — a
    corrupted row, not a real charge, so each is skipped rather than poisoning
    the total.
    """
    usage = json.loads(
        '[{"cost_usd": NaN}, {"cost_usd": Infinity}, {"cost_usd": -Infinity}, '
        '{"cost_usd": 0.02}]'
    )
    obj = _minimal(tenant_a, location_a1)
    obj.usage = usage
    assert obj.total_cost_usd == 0.02


def test_total_cost_usd_rounds_to_four_decimal_places(tenant_a, location_a1):
    obj = _minimal(tenant_a, location_a1)
    obj.usage = [{'cost_usd': 0.1}, {'cost_usd': 0.2}]
    assert obj.total_cost_usd == 0.3


def test_booked_appointments_reverse_accessor(tenant_a, location_a1):
    """`session.booked_appointments` — the reverse of `Appointment.booked_by_session`.
    Plural, because one call can book more than one appointment.
    """
    from datetime import timedelta

    contact = Contact.objects.create(tenant=tenant_a, first_name='Owen', last_name='Baptiste')
    session = _minimal(tenant_a, location_a1, contact=contact, provider_call_sid='CA-reverse-0001')
    start = dj_timezone.now() + timedelta(days=2)

    first_appt = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact,
        start_at=start, end_at=start + timedelta(minutes=30),
        booked_by_session=session,
    )
    second_appt = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact,
        start_at=start + timedelta(days=1), end_at=start + timedelta(days=1, minutes=30),
        booked_by_session=session,
    )
    unrelated = Appointment.objects.create(
        tenant=tenant_a, location=location_a1, contact=contact,
        start_at=start + timedelta(days=2), end_at=start + timedelta(days=2, minutes=30),
    )

    booked = set(session.booked_appointments.all())
    assert booked == {first_appt, second_appt}
    assert unrelated not in booked
