"""``apply_tool_call`` — the dispatcher, sub-module 3.3's security core.

Covers, in order: Invariant 3 identity stripping and the "no identified contact,
no write" preconditions; the IDOR guards on a model-supplied ``appointment_id``
and ``slot_token`` (cross-tenant, cross-location, cross-contact, forged,
foreign-scoped, expired); the identity-FACTOR rules (a caller-supplied phone is
a claim, not a credential; the carrier ANI is; the ``search_contact``
brute-force cap; the transfer tools' re-check at the point of action); PII
redaction into ``CallSession.logs``; the real booking round-trip through
``apps.scheduling.availability`` (idempotent replay, pagination, the
provider-pool query-count fan-out fix); containment (unknown tool, a handler
that raises); and finally the SAME dispatcher driven two ways — directly (the
turn-based unit-test path) and through the real media-stream consumer over a
``WebsocketCommunicator`` (the realtime hot path) — because the two-paths-one-
dispatcher drift is this module's top regression risk.

``PROVIDER_MODE=fake`` throughout (``config.settings_test``); nothing here can
reach a real provider.
"""
import json
import math
import struct
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.calls.models import CallSession
from apps.runtime.agent import (
    FALLBACK_LINE,
    CallState,
    ProviderBundle,
    apply_tool_call,
    run_turn,
)
from apps.runtime.agent.dispatcher import TOOL_HANDLERS, _get_open_slots, _redact_args
from apps.runtime.providers.audio import STT_SAMPLE_RATE
from apps.runtime.providers.llm import FakeLlmBackend, clear_fake_script, set_fake_script
from apps.runtime.providers.stt import FakeSttBackend
from apps.runtime.providers.tokens import mint_stream_token
from apps.runtime.providers.tts import FakeTtsBackend
from apps.runtime.tests._ws import amake, arefresh, connect, drain, speak_utterance
from apps.scheduling import availability
from apps.scheduling.models import Appointment, CallbackRequest, Contact, Service

pytestmark = pytest.mark.django_db(transaction=True)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _state(tenant, location, session, **kw):
    """A `CallState` for a call already resolved to `(tenant, location, session)`.

    `agent_setting_id` and the ANI default to placeholders that only the
    transfer tools and the identity-factor tests respectively care about —
    override them per-test via `**kw`.
    """
    st = CallState(tenant_id=tenant.pk, location_id=location.pk,
                   session_id=session.pk, agent_setting_id=kw.pop('agent_setting_id', 1),
                   voice_provider=kw.pop('voice_provider', 'live'),
                   started_at=session.started_at)
    st.variables = {'from_e164': kw.pop('from_e164', '+13125559999')}
    for key, value in kw.items():
        setattr(st, key, value)
    return st


def _utterance_pcm(seconds=0.1, amplitude=6000, hz=200):
    n = int(STT_SAMPLE_RATE * seconds)
    step = 2 * math.pi * hz / STT_SAMPLE_RATE
    return struct.pack(f'<{n}h', *(int(amplitude * math.sin(step * i)) for i in range(n)))


def _bundle(llm):
    return ProviderBundle(stt=FakeSttBackend(), tts=FakeTtsBackend(voice_provider='live'), llm=llm)


def _book_first_offered_slot(history):
    """Script step: book the first slot the PREVIOUS `get_open_slots` returned.

    A static script cannot name a `slot_token` — the server mints them at
    search time — so this reads the most recent tool result out of `history`
    (a tool-role turn the turn loop appended) and echoes its token back exactly
    as a real model would. Mirrors `simulate_call`'s own helper.
    """
    for entry in reversed(history or []):
        if entry.get('role') != 'tool':
            continue
        try:
            envelope = json.loads(entry.get('text') or '{}')
        except ValueError:
            continue
        slots = ((envelope.get('data') or {}).get('slots')) or []
        if slots:
            return [{'name': 'book_appointment',
                     'args': {'slot_token': slots[0]['slot_token'], 'reason': 'Test'}}]
    return []


# --------------------------------------------------------------------------- #
# Invariant 3 — identity from server state only
# --------------------------------------------------------------------------- #

async def test_identity_args_are_stripped_before_a_handler_sees_them(
    tenant_a, tenant_b, location_a1, location_b1, make_call_session,
):
    """A spoofed tenant_id/location_id/contact_id/session_id in args must not
    redirect the write — it is dropped, not merely ignored."""
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'create_contact', {
        'first_name': 'Eve', 'last_name': 'Spoof',
        'tenant_id': tenant_b.pk, 'location_id': location_b1.pk,
        'contact_id': 999, 'session_id': 999,
    })
    assert result['ok'], result
    contact = await amake(Contact.objects.get, pk=result['data']['contact_id'])
    assert contact.tenant_id == tenant_a.pk        # NOT tenant_b


async def test_booking_tools_refuse_with_no_identified_contact_and_write_nothing(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    for name, args in (('book_appointment', {'slot_token': 'x'}),
                       ('reschedule_appointment', {'appointment_id': 1, 'slot_token': 'x'}),
                       ('cancel_appointment', {'appointment_id': 1})):
        result = await apply_tool_call(state, name, args)
        assert result['ok'] is False
        assert result['error']['code'] == 'not_permitted', (name, result)
    assert await amake(Appointment.objects.count) == 0


# --------------------------------------------------------------------------- #
# IDOR — a model-supplied appointment_id, authorised server-side
# --------------------------------------------------------------------------- #

async def test_cross_tenant_appointment_id_is_not_found_and_untouched(
    tenant_a, tenant_b, location_a1, location_b1, make_call_session, make_bookable_service,
):
    service_b, _p = await amake(make_bookable_service, tenant_b, location_b1)
    contact_b = await amake(Contact.objects.create, tenant=tenant_b,
                            first_name='Bea', last_name='B')
    other = await amake(
        Appointment.objects.create, tenant=tenant_b, location=location_b1,
        contact=contact_b, service=service_b,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, minutes=30),
        status=Appointment.STATUS_SCHEDULED)

    contact_a = await amake(Contact.objects.create, tenant=tenant_a,
                            first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact_a.pk)
    result = await apply_tool_call(state, 'cancel_appointment', {'appointment_id': other.pk})
    assert result['ok'] is False and result['error']['code'] == 'not_found'
    refreshed = await amake(Appointment.objects.get, pk=other.pk)
    assert refreshed.status == Appointment.STATUS_SCHEDULED


async def test_cross_location_appointment_id_is_not_found_and_untouched(
    tenant_a, location_a1, location_a2, make_call_session, make_bookable_service,
):
    """Same tenant, WRONG location — still not_found, still untouched."""
    service, _p = await amake(make_bookable_service, tenant_a, location_a2)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    other = await amake(
        Appointment.objects.create, tenant=tenant_a, location=location_a2,
        contact=contact, service=service,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, minutes=30),
        status=Appointment.STATUS_SCHEDULED)

    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)
    result = await apply_tool_call(state, 'cancel_appointment', {'appointment_id': other.pk})
    assert result['ok'] is False and result['error']['code'] == 'not_found'
    refreshed = await amake(Appointment.objects.get, pk=other.pk)
    assert refreshed.status == Appointment.STATUS_SCHEDULED


async def test_cross_contact_appointment_id_is_not_found_not_an_oracle(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    """Same tenant AND location, but somebody ELSE's booking: deliberately
    collapsed to not_found (not not_permitted) so an identified caller cannot
    use the distinction to probe which appointment ids exist here."""
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    mine = await amake(Contact.objects.create, tenant=tenant_a,
                       first_name='Mine', last_name='Caller')
    theirs = await amake(Contact.objects.create, tenant=tenant_a,
                         first_name='Their', last_name='Booking')
    other = await amake(
        Appointment.objects.create, tenant=tenant_a, location=location_a1,
        contact=theirs, service=service,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, minutes=30),
        status=Appointment.STATUS_SCHEDULED)

    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=mine.pk)
    result = await apply_tool_call(state, 'cancel_appointment', {'appointment_id': other.pk})
    assert result['ok'] is False and result['error']['code'] == 'not_found'
    refreshed = await amake(Appointment.objects.get, pk=other.pk)
    assert refreshed.status == Appointment.STATUS_SCHEDULED


async def test_get_contact_appointments_never_leaks_another_locations_bookings(
    tenant_a, location_a1, location_a2, make_call_session, make_bookable_service,
):
    service, _p = await amake(make_bookable_service, tenant_a, location_a2)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A', phone_e164='+13125559999')
    await amake(Appointment.objects.create, tenant=tenant_a, location=location_a2,
               contact=contact, service=service,
               start_at=timezone.now() + timedelta(days=1),
               end_at=timezone.now() + timedelta(days=1, minutes=30),
               status=Appointment.STATUS_SCHEDULED)

    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'get_contact_appointments', {})
    assert result['ok']
    assert result['data']['contact_id'] == contact.pk    # identified, correctly
    assert result['data']['appointments'] == []           # but NOT the A2 booking


# --------------------------------------------------------------------------- #
# IDOR — a model-supplied slot_token
# --------------------------------------------------------------------------- #

async def test_a_garbage_slot_token_is_invalid_argument(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)
    result = await apply_tool_call(state, 'book_appointment',
                                   {'slot_token': 'not-a-real-token'})
    assert result['ok'] is False
    assert result['error']['code'] == 'invalid_argument'


async def test_a_slot_token_minted_for_another_tenant_or_location_is_not_permitted(
    tenant_a, tenant_b, location_a1, location_a2, location_b1,
    make_call_session, make_bookable_service,
):
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)

    def _mint_for(tenant, location):
        # mint_slot_token/redeem_slot_token touch no DB — safe to call inline.
        return availability.mint_slot_token(
            tenant_id=tenant.pk, location_id=location.pk,
            start_utc=timezone.now() + timedelta(days=1), service_id=service.pk,
        )

    foreign_tenant_token = _mint_for(tenant_b, location_b1)
    result = await apply_tool_call(state, 'book_appointment',
                                   {'slot_token': foreign_tenant_token})
    assert result['ok'] is False and result['error']['code'] == 'not_permitted'

    # Same tenant, a DIFFERENT location under it (location_a2, not location_a1).
    cross_location_token = _mint_for(tenant_a, location_a2)
    result2 = await apply_tool_call(state, 'book_appointment',
                                    {'slot_token': cross_location_token})
    assert result2['ok'] is False and result2['error']['code'] == 'not_permitted'
    assert await amake(Appointment.objects.count) == 0


async def test_an_expired_slot_token_is_slot_expired(
    monkeypatch, tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)

    slots = await apply_tool_call(state, 'get_open_slots', {'service_id': service.pk})
    token = slots['data']['slots'][0]['slot_token']

    # A negative TTL means "already expired the instant it was minted" — no
    # real clock travel required, and it affects only redeem_slot_token's
    # max_age, not the signature itself.
    monkeypatch.setattr(availability, 'SLOT_TOKEN_TTL_SECONDS', -1)
    result = await apply_tool_call(state, 'book_appointment', {'slot_token': token})
    assert result['ok'] is False
    assert result['error']['code'] == 'slot_expired'
    assert await amake(Appointment.objects.count) == 0


# --------------------------------------------------------------------------- #
# Identity FACTORS — a claimed phone does not identify; the ANI does
# --------------------------------------------------------------------------- #

async def test_a_caller_claimed_phone_number_cannot_identify_anyone(
    tenant_a, location_a1, make_call_session,
):
    victim = await amake(Contact.objects.create, tenant=tenant_a, first_name='Vic',
                         last_name='Tim', phone_e164='+13125550001')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)     # ANI is +13125559999

    result = await apply_tool_call(state, 'get_contact_appointments',
                                   {'phone': '+13125550001'})
    assert result['ok']
    assert result['data']['contact_id'] is None         # NOT identified as the victim
    assert state.contact_id is None
    blocked = await apply_tool_call(state, 'cancel_appointment', {'appointment_id': 1})
    assert blocked['error']['code'] == 'not_permitted'
    assert victim.pk                                     # (victim untouched)


async def test_the_verified_ani_still_identifies_the_caller(
    tenant_a, location_a1, make_call_session,
):
    contact = await amake(Contact.objects.create, tenant=tenant_a, first_name='Ann',
                          last_name='A', phone_e164='+13125559999')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'get_contact_appointments', {})
    assert result['data']['contact_id'] == contact.pk
    assert state.contact_id == contact.pk


async def test_search_contact_failed_attempts_are_capped_per_call(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    for _ in range(3):
        r = await apply_tool_call(state, 'search_contact',
                                  {'first': 'No', 'last': 'Body',
                                   'date_of_birth': '01/01/1980'})
        assert r['ok']       # a miss is ok(), just no match
    blocked = await apply_tool_call(state, 'search_contact',
                                    {'first': 'No', 'last': 'Body',
                                     'date_of_birth': '01/02/1980'})
    assert blocked['ok'] is False and blocked['error']['code'] == 'not_permitted'


async def test_search_contact_missing_fields_is_invalid_argument_not_a_failed_attempt(
    tenant_a, location_a1, make_call_session,
):
    """A malformed request never reached the lookup — it must not count against
    the brute-force cap, which only counts genuine misses/ambiguous matches."""
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'search_contact', {'first': 'No'})
    assert result['ok'] is False and result['error']['code'] == 'invalid_argument'
    assert state.search_attempts == 0


async def test_create_contact_with_no_name_at_all_is_invalid_argument(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'create_contact', {'phone': '+13125550000'})
    assert result['ok'] is False and result['error']['code'] == 'invalid_argument'
    assert await amake(Contact.objects.count) == 0


async def test_book_appointment_with_no_slot_token_is_invalid_argument(
    tenant_a, location_a1, make_call_session,
):
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)
    result = await apply_tool_call(state, 'book_appointment', {})
    assert result['ok'] is False and result['error']['code'] == 'invalid_argument'


async def test_get_open_slots_unparseable_date_is_invalid_argument(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'get_open_slots',
                                   {'service_id': service.pk, 'date_from': 'not-a-date'})
    assert result['ok'] is False and result['error']['code'] == 'invalid_argument'


async def test_a_non_integer_appointment_id_is_not_found_not_a_crash(
    tenant_a, location_a1, make_call_session,
):
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)
    result = await apply_tool_call(state, 'cancel_appointment',
                                   {'appointment_id': 'not-an-int'})
    assert result['ok'] is False and result['error']['code'] == 'not_found'


# --------------------------------------------------------------------------- #
# Reschedule / cancel — the happy paths (the IDOR tests above only cover refusal)
# --------------------------------------------------------------------------- #

async def test_reschedule_appointment_moves_a_real_booking_to_a_new_slot(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _provider = await amake(make_bookable_service, tenant_a, location_a1)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)

    first_slots = await apply_tool_call(state, 'get_open_slots', {'service_id': service.pk})
    booked = await apply_tool_call(
        state, 'book_appointment',
        {'slot_token': first_slots['data']['slots'][0]['slot_token']})
    assert booked['ok'], booked
    appointment_id = booked['data']['appointment_id']

    # A slot search AFTER booking must not offer the now-occupied time back —
    # page 2 of a fresh page_size=1 search is guaranteed a DIFFERENT slot.
    later_slots = await apply_tool_call(
        state, 'get_open_slots',
        {'service_id': service.pk, 'page': 2, 'page_size': 1})
    assert later_slots['ok'] and later_slots['data']['slots']
    new_token = later_slots['data']['slots'][0]['slot_token']

    moved = await apply_tool_call(
        state, 'reschedule_appointment',
        {'appointment_id': appointment_id, 'slot_token': new_token})
    assert moved['ok'], moved
    assert moved['data']['appointment_id'] == appointment_id
    refreshed = await amake(Appointment.objects.get, pk=appointment_id)
    assert refreshed.start_at.isoformat() == moved['data']['start_at']
    assert await amake(Appointment.objects.count) == 1     # moved, not duplicated


async def test_reschedule_appointment_with_no_slot_token_is_invalid_argument(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _provider = await amake(make_bookable_service, tenant_a, location_a1)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)

    slots = await apply_tool_call(state, 'get_open_slots', {'service_id': service.pk})
    booked = await apply_tool_call(
        state, 'book_appointment', {'slot_token': slots['data']['slots'][0]['slot_token']})
    result = await apply_tool_call(
        state, 'reschedule_appointment',
        {'appointment_id': booked['data']['appointment_id']})
    assert result['ok'] is False and result['error']['code'] == 'invalid_argument'


async def test_cancel_appointment_marks_a_real_booking_cancelled(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _provider = await amake(make_bookable_service, tenant_a, location_a1)
    contact = await amake(Contact.objects.create, tenant=tenant_a,
                          first_name='Ann', last_name='A')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, contact_id=contact.pk)

    slots = await apply_tool_call(state, 'get_open_slots', {'service_id': service.pk})
    booked = await apply_tool_call(
        state, 'book_appointment', {'slot_token': slots['data']['slots'][0]['slot_token']})
    appointment_id = booked['data']['appointment_id']

    cancelled = await apply_tool_call(
        state, 'cancel_appointment',
        {'appointment_id': appointment_id, 'cancellation_reason': 'Change of plans'})
    assert cancelled['ok'], cancelled
    assert cancelled['data']['status'] == Appointment.STATUS_CANCELLED
    refreshed = await amake(Appointment.objects.get, pk=appointment_id)
    assert refreshed.status == Appointment.STATUS_CANCELLED
    assert refreshed.cancelled_at is not None


# --------------------------------------------------------------------------- #
# Transfer tools re-check eligibility at the point of action
# --------------------------------------------------------------------------- #

async def test_transfer_refuses_when_transfer_is_disabled(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    setting = await amake(make_agent_setting, tenant_a, location_a1,
                          transfer_enabled=False)
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, agent_setting_id=setting.pk)
    result = await apply_tool_call(state, 'transfer_call', {})
    assert result['ok'] is False and result['error']['code'] == 'not_permitted'
    assert state.pending_transfer is None


async def test_transfer_refuses_when_enabled_but_destination_blank(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    setting = await amake(make_agent_setting, tenant_a, location_a1,
                          transfer_enabled=True, transfer_phone_number='')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, agent_setting_id=setting.pk)
    result = await apply_tool_call(state, 'transfer_call', {})
    assert result['ok'] is False and result['error']['code'] == 'not_permitted'
    assert state.pending_transfer is None


async def test_transfer_refuses_with_no_matching_agent_setting_row(
    tenant_a, location_a1, make_call_session,
):
    """`_transfer_eligible` re-reads the `AgentSetting` row itself — a state
    pointed at one that no longer resolves must fail closed, not raise."""
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, agent_setting_id=999999999)
    result = await apply_tool_call(state, 'transfer_call', {})
    assert result['ok'] is False and result['error']['code'] == 'not_permitted'
    assert state.pending_transfer is None


async def test_transfer_and_end_call_only_set_deferred_flags(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    setting = await amake(make_agent_setting, tenant_a, location_a1,
                          transfer_enabled=True, transfer_phone_number='+13125550101',
                          transfer_secondary_number='+13125550102')
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session, agent_setting_id=setting.pk)

    assert (await apply_tool_call(state, 'transfer_call', {}))['ok']
    assert state.pending_transfer == 'human'
    assert (await apply_tool_call(state, 'transfer_call_spanish', {}))['ok']
    assert state.pending_transfer == 'spanish'

    assert (await apply_tool_call(state, 'end_call', {}))['ok']
    assert state.pending_hangup is True
    assert state.ended_reason == 'end_call'


# --------------------------------------------------------------------------- #
# PII redaction into CallSession.logs
# --------------------------------------------------------------------------- #

def test_redact_args_keeps_the_allow_list_and_fails_closed_on_unknown_keys():
    out = _redact_args({'service_id': 7, 'email': 'a@b.test',
                        'insurance_id': 'XYZ123'})
    assert out['service_id'] == 7                 # allow-listed, kept verbatim
    assert 'a@b.test' not in str(out)              # unknown -> length marker only
    assert 'XYZ123' not in str(out)


async def test_pii_is_redacted_in_the_persisted_tool_log_but_the_write_is_full(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    await apply_tool_call(state, 'create_contact', {
        'first_name': 'Grace', 'last_name': 'Hopper',
        'date_of_birth': '12/09/1906', 'phone': '+13125551234',
    })
    entry = [e for e in state.logs_buffer if e['category'] == 'tool'][-1]
    args = entry['raw_json']['arguments']
    assert 'date_of_birth' not in args              # dropped outright
    assert args['phone'].endswith('1234') and args['phone'].startswith('***')
    assert args['first_name'] == 'G***'              # name reduced to an initial
    contact = await amake(Contact.objects.get, tenant=tenant_a, first_name='Grace')
    assert contact.date_of_birth is not None         # ...but the write itself is full


# --------------------------------------------------------------------------- #
# The real booking round-trip through apps.scheduling.availability
# --------------------------------------------------------------------------- #

async def test_full_booking_round_trip_books_a_real_appointment(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _provider = await amake(make_bookable_service, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)

    found = await apply_tool_call(state, 'get_contact_appointments', {})
    assert found['ok'] and found['data']['is_new'] is True

    created = await apply_tool_call(state, 'create_contact',
                                    {'first_name': 'Sam', 'last_name': 'Caller',
                                     'date_of_birth': '01/02/1990'})
    assert created['ok']
    assert state.contact_id == created['data']['contact_id']   # server-owned, not model-echoed

    slots = await apply_tool_call(state, 'get_open_slots', {'service_id': service.pk})
    assert slots['ok'] and slots['data']['slots'], 'no slots offered'
    token = slots['data']['slots'][0]['slot_token']

    booked = await apply_tool_call(state, 'book_appointment',
                                   {'slot_token': token, 'reason': 'Checkup'})
    assert booked['ok'], booked
    appointment = await amake(Appointment.objects.get, pk=booked['data']['appointment_id'])
    assert appointment.source == Appointment.SOURCE_AI_PHONE
    assert appointment.booked_by_session_id == session.pk
    assert appointment.tenant_id == tenant_a.pk and appointment.location_id == location_a1.pk

    # Replaying the SAME token is IDEMPOTENT, not a double-book: availability.py
    # checks "did this contact already book this slot?" BEFORE the conflict
    # check, precisely so a model retrying a tool call is not told it failed
    # after it actually succeeded.
    again = await apply_tool_call(state, 'book_appointment', {'slot_token': token})
    assert again['ok'], again
    assert again['data']['appointment_id'] == appointment.pk
    assert await amake(Appointment.objects.count) == 1


async def test_get_open_slots_requires_a_resolvable_service(
    tenant_a, tenant_b, location_a1, location_b1, make_call_session, make_bookable_service,
):
    await amake(make_bookable_service, tenant_a, location_a1)
    foreign = await amake(Service.objects.create, tenant=tenant_b,
                          location=location_b1, name='Other', duration_minutes=30,
                          buffer_minutes=0, requires_resource=False, is_active=True)
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)

    missing = await apply_tool_call(state, 'get_open_slots', {})
    assert missing['error']['code'] == 'invalid_argument'
    leaked = await apply_tool_call(state, 'get_open_slots', {'service_id': foreign.pk})
    assert leaked['ok'] is False and leaked['error']['code'] == 'not_found'


async def test_get_open_slots_pagination_page_two_returns_distinct_results(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)

    page1 = await apply_tool_call(state, 'get_open_slots',
                                  {'service_id': service.pk, 'page': 1, 'page_size': 3})
    page2 = await apply_tool_call(state, 'get_open_slots',
                                  {'service_id': service.pk, 'page': 2, 'page_size': 3})
    assert page1['ok'] and page2['ok']
    assert page1['data']['slots'], 'precondition: page 1 has results'
    assert page2['data']['slots'], 'page 2 must also have results when more than a page exists'
    tokens1 = {s['slot_token'] for s in page1['data']['slots']}
    tokens2 = {s['slot_token'] for s in page2['data']['slots']}
    assert tokens1.isdisjoint(tokens2)


def test_unresolvable_provider_filter_yields_no_slots_not_unfiltered_ones(
    tenant_a, tenant_b, location_a1, make_call_session, make_bookable_service,
):
    from apps.accounts.models import User

    service, _p1 = make_bookable_service(tenant_a, location_a1)
    stranger = User.objects.create_user(
        tenant=tenant_b, email='x@globex-test.example', password='x',
        tier=User.TIER_STAFF, first_name='X', last_name='X', is_provider=True)
    session = make_call_session(tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)

    unfiltered = _get_open_slots(state, {'service_id': service.pk})
    assert unfiltered['data']['slots'], 'precondition: slots exist unfiltered'

    filtered = _get_open_slots(state, {'service_id': service.pk,
                                       'provider_ids': [stranger.pk]})
    assert filtered['ok'] and filtered['data']['slots'] == []


def test_slot_search_query_count_does_not_scale_with_the_provider_pool(
    tenant_a, location_a1, make_call_session, make_bookable_service,
):
    """Two providers must cost the same queries as one (the fan-out fix)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.accounts.models import User, UserLocation

    service, p1 = make_bookable_service(tenant_a, location_a1)
    p2 = User.objects.create_user(
        tenant=tenant_a, email='p2@acme-test.example', password='x',
        tier=User.TIER_STAFF, first_name='Q', last_name='Q', is_provider=True)
    UserLocation.objects.create(tenant=tenant_a, user=p2, location=location_a1)
    p2.provider_hours = p1.provider_hours
    p2.save(update_fields=['provider_hours'])

    session = make_call_session(tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)

    with CaptureQueriesContext(connection) as one:
        _get_open_slots(state, {'service_id': service.pk, 'provider_ids': [p1.pk]})
    with CaptureQueriesContext(connection) as two:
        _get_open_slots(state, {'service_id': service.pk,
                                'provider_ids': [p1.pk, p2.pk]})
    assert len(two.captured_queries) == len(one.captured_queries), (
        f'{len(one.captured_queries)} -> {len(two.captured_queries)}: slot search '
        f'still scales with the provider pool')


# --------------------------------------------------------------------------- #
# Deferred signals + callback + hours (no ORM side effect on the transfer pair)
# --------------------------------------------------------------------------- #

async def test_callback_request_needs_no_identified_contact(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'create_callback_request',
                                   {'reason': 'Wants a quote'})
    assert result['ok'], result
    cb = await amake(CallbackRequest.objects.get, pk=result['data']['callback_id'])
    assert cb.contact_id is None and cb.status == CallbackRequest.STATUS_PENDING
    assert cb.source == CallbackRequest.SOURCE_AI_PHONE
    assert cb.tenant_id == tenant_a.pk and cb.location_id == location_a1.pk


async def test_get_location_hours_uses_cached_open_intervals(
    tenant_a, location_a1, make_call_session,
):
    from datetime import time as dt_time
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    state.open_intervals = [{'start_time': dt_time(9, 0), 'end_time': dt_time(17, 0),
                             'days': ['mon', 'tue']}]
    result = await apply_tool_call(state, 'get_location_hours', {})
    assert result['ok'], result
    assert result['data']['address'] == location_a1.full_address
    assert len(result['data']['hours']) == 2


# --------------------------------------------------------------------------- #
# Containment — nothing a tool does can kill the call
# --------------------------------------------------------------------------- #

async def test_a_call_scoped_to_a_vanished_location_is_contained_as_internal_error(
    tenant_a, location_a1, make_call_session,
):
    """`_scope()` raising when `state.location_id` no longer resolves must still
    come back as a well-formed envelope, never an unhandled exception."""
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    state.location_id = 999999999          # no such Location under this tenant
    result = await apply_tool_call(state, 'get_location_hours', {})
    assert result['ok'] is False
    assert result['error']['code'] == 'internal_error'


async def test_unknown_tool_name_is_contained_as_invalid_argument(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    result = await apply_tool_call(state, 'drop_database', {})
    assert result['ok'] is False and result['error']['code'] == 'invalid_argument'


async def test_a_handler_that_raises_is_contained_as_internal_error(
    monkeypatch, tenant_a, location_a1, make_call_session,
):
    def _boom(state, args):
        raise RuntimeError('boom')

    monkeypatch.setitem(TOOL_HANDLERS, 'get_location_hours', _boom)
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)

    result = await apply_tool_call(state, 'get_location_hours', {})
    assert result['ok'] is False
    assert result['error']['code'] == 'internal_error'

    # The call survives: a further tool call on the same state still works.
    ok_after = await apply_tool_call(state, 'create_callback_request',
                                     {'reason': 'still alive'})
    assert ok_after['ok']


async def test_persisted_tool_log_entry_has_exactly_the_documented_shape(
    tenant_a, location_a1, make_call_session,
):
    """{tool, arguments, ok, error} — the shape Module 5.3's event-log template
    reads (`raw_json.tool`, `.arguments`, `.error.code`, `.error.message`)."""
    session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, session)
    await apply_tool_call(state, 'get_location_hours', {})
    entry = [e for e in state.logs_buffer if e['category'] == 'tool'][-1]
    raw = entry['raw_json']
    assert set(raw.keys()) == {'tool', 'arguments', 'ok', 'error'}
    assert raw['tool'] == 'get_location_hours'
    assert raw['ok'] is True
    assert raw['error'] is None


# --------------------------------------------------------------------------- #
# The turn-based path: apply_tool_call driven through the real turn loop
# --------------------------------------------------------------------------- #

async def test_turn_loop_applies_every_tool_call_in_a_round_and_appends_tool_turns(
    tenant_a, location_a1, make_agent_setting, make_call_session, make_bookable_service,
):
    """A callable script entry reads `history` to echo back an earlier tool's
    `slot_token` — the only way to book a slot that did not exist when the
    script was written, exactly as a real model reads its own tool results."""
    agent_setting = await amake(make_agent_setting, tenant_a, location_a1)
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    call_session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, call_session, agent_setting_id=agent_setting.pk)

    tool_calls = [
        [{'name': 'get_contact_appointments', 'args': {}},
         {'name': 'create_contact', 'args': {'first_name': 'Turn', 'last_name': 'Looper'}}],
        [{'name': 'get_open_slots', 'args': {'service_id': service.pk}}],
        _book_first_offered_slot,
        [],
    ]
    replies = ['Let me check.', 'One moment.', 'Booking now.', "You're all set."]
    llm = FakeLlmBackend(replies=replies, tool_calls=tool_calls)

    result = await run_turn(
        state, _utterance_pcm(), agent_setting=agent_setting, call_session=call_session,
        location=location_a1, providers=_bundle(llm), now=timezone.now(),
    )

    assert result.reply_text == "You're all set."
    tool_turns = [h for h in state.history if h['role'] == 'tool']
    # round 1: 2 calls, round 2: 1 call, round 3 (the callable): 1 call, round
    # 4 returns [] and breaks the loop BEFORE appending anything.
    assert len(tool_turns) == 4
    appointment = await amake(lambda: Appointment.objects.select_related('contact').get())
    assert appointment.source == Appointment.SOURCE_AI_PHONE
    assert appointment.booked_by_session_id == call_session.pk
    assert appointment.contact.first_name == 'Turn'


async def test_turn_loop_hits_the_iteration_cap_and_still_ends_in_a_spoken_line(
    tenant_a, location_a1, make_agent_setting, make_call_session, settings,
):
    """A model that never stops calling tools still ends the turn in speech —
    the per-turn tool-iteration cap's whole reason to exist."""
    agent_setting = await amake(make_agent_setting, tenant_a, location_a1)
    call_session = await amake(make_call_session, tenant_a, location_a1)
    state = _state(tenant_a, location_a1, call_session, agent_setting_id=agent_setting.pk)

    cap = settings.MAX_TOOL_ITERATIONS
    looping_call = [{'name': 'get_location_hours', 'args': {}}]
    tool_calls = [looping_call for _ in range(cap)]
    # The LAST round's own reply text is empty, so the cap branch's
    # `reply_text or FALLBACK_LINE` actually falls back — proving the cap
    # itself produced the spoken line, not just a coincidentally worded reply.
    replies = ['still working'] * (cap - 1) + ['']
    llm = FakeLlmBackend(replies=replies, tool_calls=tool_calls)

    result = await run_turn(
        state, _utterance_pcm(), agent_setting=agent_setting, call_session=call_session,
        location=location_a1, providers=_bundle(llm), now=timezone.now(),
    )

    assert len(llm.calls) == cap                # never a 5th model call
    assert result.reply_text == FALLBACK_LINE
    assert len([h for h in state.history if h['role'] == 'tool']) == cap
    cap_logs = [entry for entry in state.logs_buffer
               if entry['title'] == 'Tool-iteration cap hit']
    assert cap_logs, 'the cap-hit warning must be logged'


# --------------------------------------------------------------------------- #
# The realtime path: the SAME dispatcher, driven through the real consumer
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_fake_llm_script():
    """`set_fake_script` is process-global and refuses to arm twice — always
    clear it, including if a test raises before reaching its own cleanup."""
    clear_fake_script()
    yield
    clear_fake_script()


async def test_consumer_drives_a_scripted_booking_through_the_real_dispatcher(
    tenant_a, location_a1, make_agent_setting, make_call_session, make_bookable_service,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    service, _p = await amake(make_bookable_service, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    set_fake_script(
        replies=['Let me look you up.', 'Checking the calendar.',
                'Booking that now.', "You're all set."],
        tool_calls=[
            [{'name': 'get_contact_appointments', 'args': {}},
             {'name': 'create_contact', 'args': {'first_name': 'Wendy', 'last_name': 'Caller'}}],
            [{'name': 'get_open_slots', 'args': {'service_id': service.pk}}],
            _book_first_offered_slot,
            [],
        ],
    )

    comm = await connect(token, session.pk)
    await drain(comm)               # greeting
    await speak_utterance(comm)
    await drain(comm)               # the whole tool round-trip plays out
    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status != CallSession.STATUS_IN_PROGRESS
    appointment = await amake(Appointment.objects.get)
    assert appointment.source == Appointment.SOURCE_AI_PHONE
    assert appointment.booked_by_session_id == session.pk

    tool_names = [entry['raw_json']['tool'] for entry in session.logs
                 if entry.get('category') == 'tool']
    assert 'book_appointment' in tool_names


async def test_end_call_hangs_up_after_the_goodbye_and_marks_the_call_completed(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    set_fake_script(replies=['Goodbye, thanks for calling!'],
                    tool_calls=[[{'name': 'end_call', 'args': {}}]])

    comm = await connect(token, session.pk)
    await drain(comm)               # greeting
    await speak_utterance(comm)

    media_frames = 0
    output = None
    while True:
        output = await comm.receive_output(timeout=2)
        if output['type'] == 'websocket.close':
            break
        assert output['type'] == 'websocket.send'
        media_frames += 1
    assert media_frames > 0, 'the goodbye must be spoken BEFORE the socket closes'
    assert output.get('code') == 1000

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_COMPLETED
    assert session.ended_at is not None
    assert session.metadata.get('ended_reason') == 'end_call'

    # A following disconnect() (Channels dispatches it independently of the
    # consumer's own close()) must be a safe, idempotent no-op.
    ended_at_before = session.ended_at
    await comm.disconnect()
    session = await arefresh(session)
    assert session.ended_at == ended_at_before
    assert session.status == CallSession.STATUS_COMPLETED
