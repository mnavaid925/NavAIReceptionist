"""Transfer execution — sub-module 3.4.

Two halves:

1. **Pure `transfer.py` helpers** — ``build_transfer_record`` (the one
   ``CallSession.transfer`` shape) and the injection-safety gates
   ``looks_like_e164`` / ``looks_like_call_sid``. No ORM, no Channels, no
   provider — plain function tests.
2. **The deferred handoff driven end to end through the REAL media-stream
   consumer** (``WebsocketCommunicator`` against ``config.asgi.application``,
   never a mock). The dispatcher's off-hours/open-hours GATING is covered in
   ``test_dispatcher.py`` (extended for 3.4) — this file starts from a call
   already armed for transfer (``state.pending_transfer`` set) and covers what
   only the transport can: the redirect, its failure mode, the toll-fraud /
   injection abort, the single-fire guard, and the finalize race the
   realtime-reviewer flagged as Critical.

``PROVIDER_MODE=fake`` throughout (``config.settings_test``) —
``FakeTelephonyBackend.redirect_call`` is exercised directly and through the
consumer, never mocked at the SDK level.
"""
import asyncio

import pytest
from django.utils import timezone

from apps.calls.models import CallSession
from apps.runtime.agent.transfer import (
    RESULT_CONNECTED,
    build_transfer_record,
    looks_like_call_sid,
    looks_like_e164,
)
from apps.runtime.providers.llm import clear_fake_script, set_fake_script
from apps.runtime.providers.telephony import FakeTelephonyBackend
from apps.runtime.providers.tokens import mint_stream_token
from apps.runtime.tests._ws import amake, arefresh, connect, drain, speak_utterance, wait_for
from apps.scheduling.models import CallbackRequest

pytestmark = pytest.mark.django_db(transaction=True)


# --------------------------------------------------------------------------- #
# build_transfer_record — the one CallSession.transfer shape
# --------------------------------------------------------------------------- #

def test_build_transfer_record_shape_with_no_attempts():
    moment = timezone.now()
    record = build_transfer_record(
        result=RESULT_CONNECTED, reason='Caller asked to speak with a person.',
        destination='+13125550101', initiated_at=moment,
    )
    assert record == {
        'result': RESULT_CONNECTED,
        'reason': 'Caller asked to speak with a person.',
        'destination': '+13125550101',
        'initiated_at': moment.isoformat(),
        'duration_seconds': 0,
    }
    assert 'attempts' not in record


def test_build_transfer_record_defaults_initiated_at_to_now_and_isoformats_it():
    before = timezone.now()
    record = build_transfer_record(result=RESULT_CONNECTED)
    after = timezone.now()
    stamped = timezone.datetime.fromisoformat(record['initiated_at'])
    assert before <= stamped <= after


def test_build_transfer_record_keeps_attempts_only_when_supplied():
    record = build_transfer_record(
        result=RESULT_CONNECTED,
        attempts=[{'destination': '+13125550101', 'result': 'no_answer'}],
    )
    assert record['attempts'] == [{'destination': '+13125550101', 'result': 'no_answer'}]


def test_build_transfer_record_rejects_an_out_of_vocabulary_result():
    with pytest.raises(ValueError):
        build_transfer_record(result='bogus_result')


# --------------------------------------------------------------------------- #
# looks_like_e164 / looks_like_call_sid — the toll-fraud / injection gates
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', ['+13125550101', '+447911123456', '+15005550006'])
def test_looks_like_e164_accepts_strict_e164(value):
    assert looks_like_e164(value) is True


@pytest.mark.parametrize('value', [
    '3125550101',           # no leading +, so this is a NATIONAL number
    '+1<script>',           # injection character
    '+1 312 555 0101',      # whitespace
    '',
    None,
])
def test_looks_like_e164_rejects_everything_else(value):
    assert looks_like_e164(value) is False


@pytest.mark.parametrize('value', ['CA' + '1' * 32, 'SIM-abc123', 'CA1', 'TURN-1'])
def test_looks_like_call_sid_accepts_safe_opaque_tokens(value):
    assert looks_like_call_sid(value) is True


@pytest.mark.parametrize('value', [
    'CA<script>', 'CA&x', 'CA one two', 'CA/1', '', None, 'x' * 65,
])
def test_looks_like_call_sid_rejects_injection_shaped_or_oversized_values(value):
    assert looks_like_call_sid(value) is False


# --------------------------------------------------------------------------- #
# The realtime path — the deferred transfer driven through the REAL consumer
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_fake_llm_script():
    """`set_fake_script` is process-global and refuses to arm twice — always
    clear it, including if a test raises before reaching its own cleanup."""
    clear_fake_script()
    yield
    clear_fake_script()


@pytest.fixture(autouse=True)
def _clear_redirect_script():
    """`FakeTelephonyBackend._scripted_ok` is process-global class state."""
    FakeTelephonyBackend.clear_redirect_script()
    yield
    FakeTelephonyBackend.clear_redirect_script()


def _arm_transfer_script():
    """One tool round (`transfer_call`) then a plain reply — the shape
    `simulate_call --script transfer` itself uses."""
    set_fake_script(
        replies=['Connecting you now.', 'One moment.'],
        tool_calls=[[{'name': 'transfer_call', 'args': {}}], []],
    )


async def _drain_until_closed(comm, timeout=3):
    """Read frames until the consumer closes the socket ITSELF.

    3.4's transfer path self-closes once the redirect resolves — there is no
    `stop` frame for this test to send, unlike the plain chat/booking path.
    """
    while True:
        output = await comm.receive_output(timeout=timeout)
        if output['type'] == 'websocket.close':
            return output
        assert output['type'] == 'websocket.send'


async def test_transfer_happy_path_connects_marks_transferred_no_attempts_key(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1,
               transfer_enabled=True, transfer_phone_number='+13125550101')
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)
    _arm_transfer_script()

    comm = await connect(token, session.pk)
    await drain(comm)               # greeting
    await speak_utterance(comm)
    output = await _drain_until_closed(comm)
    assert output.get('code') == 1000
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_TRANSFERRED
    assert session.transfer['result'] == 'connected'
    assert session.transfer['destination'] == '+13125550101'
    assert 'attempts' not in session.transfer
    assert session.metadata.get('ended_reason') == 'transferred'


async def test_transfer_provider_failure_speaks_apology_and_logs_one_callback(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """No dead air on a failed redirect (CLAUDE.md realtime rule 4): the call
    still ends 'transferred' (a handoff was genuinely attempted), the outcome
    is 'failed', the caller hears the apology, and a callback survives the
    failed handoff."""
    await amake(make_agent_setting, tenant_a, location_a1,
               transfer_enabled=True, transfer_phone_number='+13125550101')
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    FakeTelephonyBackend.script_redirect(ok=False)
    _arm_transfer_script()

    comm = await connect(token, session.pk)
    await drain(comm)
    await speak_utterance(comm)
    await _drain_until_closed(comm)
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_TRANSFERRED
    assert session.transfer['result'] == 'failed'
    assert any("wasn't able to connect" in (turn.get('text') or '')
              for turn in session.transcript if turn['role'] == 'assistant')

    callbacks = await amake(lambda: list(
        CallbackRequest.objects.filter(tenant=tenant_a, location=location_a1)))
    assert len(callbacks) == 1
    assert callbacks[0].reason == 'Transfer to a person failed to connect.'
    assert callbacks[0].status == CallbackRequest.STATUS_PENDING
    assert callbacks[0].source == CallbackRequest.SOURCE_AI_PHONE


async def test_transfer_with_malformed_destination_aborts_without_calling_redirect(
    monkeypatch, tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """A non-E.164 `transfer_phone_number` passes the dispatcher's non-blank
    eligibility check (it only asks "is a destination configured?") but must
    never reach the REST redirect — `_run_transfer_redirect`'s toll-fraud /
    injection shape gate catches it first."""
    bogus_destination = '12345550101'   # no leading '+' -> fails looks_like_e164
    assert looks_like_e164(bogus_destination) is False   # precondition

    await amake(make_agent_setting, tenant_a, location_a1,
               transfer_enabled=True, transfer_phone_number=bogus_destination)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    calls = []
    original = FakeTelephonyBackend.redirect_call

    async def _spy(self, setting, call_sid, destination):
        calls.append((call_sid, destination))
        return await original(self, setting, call_sid, destination)

    monkeypatch.setattr(FakeTelephonyBackend, 'redirect_call', _spy)
    _arm_transfer_script()

    comm = await connect(token, session.pk)
    await drain(comm)
    await speak_utterance(comm)
    await _drain_until_closed(comm)
    await comm.disconnect()

    assert calls == [], 'redirect_call must never be reached with an invalid destination'
    session = await arefresh(session)
    assert session.status == CallSession.STATUS_TRANSFERRED
    assert session.transfer['result'] == 'failed'


async def test_transfer_redirect_fires_exactly_once_even_with_a_second_queued_utterance(
    monkeypatch, tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """`turn_busy` stays True for the WHOLE armed turn — through the ack
    playback and the redirect itself — so a second utterance arriving mid-way
    can only ever overwrite the single `pending_utterance` slot, never spawn a
    second turn (and therefore never a second redirect) against the same
    live call SID."""
    await amake(make_agent_setting, tenant_a, location_a1,
               transfer_enabled=True, transfer_phone_number='+13125550101')
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    calls = []
    original = FakeTelephonyBackend.redirect_call

    async def _counting(self, setting, call_sid, destination):
        calls.append(1)
        return await original(self, setting, call_sid, destination)

    monkeypatch.setattr(FakeTelephonyBackend, 'redirect_call', _counting)
    _arm_transfer_script()

    comm = await connect(token, session.pk)
    await drain(comm)               # greeting
    await speak_utterance(comm)     # triggers the armed turn; turn_busy -> True
    await speak_utterance(comm)     # queued into the single pending_utterance slot
    await _drain_until_closed(comm)
    await comm.disconnect()

    assert len(calls) == 1, f'redirect_call invoked {len(calls)} times, expected exactly 1'
    session = await arefresh(session)
    assert session.status == CallSession.STATUS_TRANSFERRED
    assert session.transfer['result'] == 'connected'


async def test_transfer_survives_the_finalize_race_with_a_racing_stop(
    monkeypatch, settings, tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """The realtime-reviewer's Critical finding: a `stop`/disconnect racing an
    in-flight redirect must never lose the transfer outcome. `_finalize()`
    deliberately does NOT cancel the transfer task once it has started — it
    stamps status/ended_at/metadata now (from `ended_reason`, already set
    synchronously before the redirect awaits), and the `transfer` JSON lands
    moments later from the still-running `_execute_transfer`, in a SEPARATE
    write `_finalize_session`'s own guard cannot clobber.
    """
    settings.TRANSFER_DRAIN_SECONDS = 0   # isolate the monkeypatched delay below
    await amake(make_agent_setting, tenant_a, location_a1,
               transfer_enabled=True, transfer_phone_number='+13125550101')
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    original = FakeTelephonyBackend.redirect_call

    async def _slow(self, setting, call_sid, destination):
        await asyncio.sleep(1.0)
        return await original(self, setting, call_sid, destination)

    monkeypatch.setattr(FakeTelephonyBackend, 'redirect_call', _slow)
    _arm_transfer_script()

    comm = await connect(token, session.pk)
    await drain(comm)               # greeting
    await speak_utterance(comm)
    await drain(comm)               # the ack plays; returns while the slow redirect still sleeps

    # RACE: send `stop` WHILE `_execute_transfer` is awaiting the slow redirect.
    await comm.send_json_to({'event': 'stop'})
    output = await comm.receive_output(timeout=2)
    assert output['type'] == 'websocket.close' and output.get('code') == 1000

    async def _connected():
        refreshed = await arefresh(session)
        return refreshed.transfer.get('result') == 'connected'

    assert await wait_for(_connected, tries=40, delay=0.1), (
        'the transfer JSON was lost to the finalize race')

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_TRANSFERRED
    assert session.transfer['result'] == 'connected'

    await comm.disconnect()
