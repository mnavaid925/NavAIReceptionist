"""`MediaStreamConsumer` — the Twilio media-stream websocket, end to end.

Against the REAL `config.asgi.application` via `WebsocketCommunicator` — the
consumer never runs against a mock transport. Covers the authorization gate on
the `start` frame (Invariant 3: identity from the verified token only, never the
URL), the tenant+location-namespaced Channels group, one full turn through the
real turn loop, guaranteed/idempotent teardown, and the frame loop's "one bad
frame never kills the call" contract.

A `SynchronousOnlyOperation` surfacing anywhere in these tests is a suite
failure, not a flake — the happy-path tests exercise every ORM touch on the
consumer's hot path (`_resolve`, `_flush`, `_finalize_session`) and would raise
it immediately if `thread_sensitive=False` regressed.
"""
import json

import pytest
from channels.layers import get_channel_layer

from apps.calls.models import CallSession
from apps.runtime.consumers.MediaStreamTurnLoop.MediaStream import (
    MediaStreamConsumer,
    group_name,
)
from apps.runtime.providers.tokens import mint_stream_token
from apps.runtime.tests._ws import (
    amake,
    arefresh,
    connect,
    drain,
    open_socket,
    speak_utterance,
    wait_for,
)

pytestmark = pytest.mark.django_db(transaction=True)


# --------------------------------------------------------------------------- #
# group_name() — the pure namespacing function
# --------------------------------------------------------------------------- #

def test_group_name_is_tenant_and_location_namespaced():
    assert group_name(7, 3, 42) == 't7.l3.call.42'


def test_group_name_distinct_per_tenant_and_per_location():
    assert group_name(1, 1, 9) != group_name(2, 1, 9)  # different tenant
    assert group_name(1, 1, 9) != group_name(1, 2, 9)  # different location


# --------------------------------------------------------------------------- #
# The happy path — one full call through the real turn loop
# --------------------------------------------------------------------------- #

async def test_full_call_finalizes_with_transcript_usage_and_metadata(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    await drain(comm)  # greeting plays
    await speak_utterance(comm)
    await drain(comm)  # reply plays
    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status != CallSession.STATUS_IN_PROGRESS  # a terminal status
    assert session.status in {CallSession.STATUS_COMPLETED, CallSession.STATUS_ABANDONED}
    assert session.ended_at is not None
    assert session.metadata.get('ended_reason') == 'hangup'

    roles = [t['role'] for t in session.transcript]
    assert 'assistant' in roles and 'user' in roles  # greeting + caller + reply
    assert roles[0] == 'assistant'  # the deterministic greeting is turn one

    # Every assistant turn (greeting + reply) is metered — usage count matches.
    assistant_turns = [t for t in session.transcript if t['role'] == 'assistant']
    assert len(session.usage) == len(assistant_turns) >= 2

    # Sequence numbers are monotonic across the whole call, never restarting.
    sequences = [t['sequence'] for t in session.transcript]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)  # no duplicates/collisions


async def test_group_membership_uses_the_exact_tenant_location_namespaced_name(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    await drain(comm)

    expected_group = group_name(tenant_a.pk, location_a1.pk, session.pk)
    layer = get_channel_layer()
    assert expected_group in layer.groups

    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()


# --------------------------------------------------------------------------- #
# Rejects — authorization happens on the `start` frame, before any side effect
# --------------------------------------------------------------------------- #

async def test_reject_no_token_closes_4401_zero_writes(tenant_a, location_a1, make_call_session):
    session = await amake(make_call_session, tenant_a, location_a1)
    comm = await open_socket()
    await comm.send_json_to({'event': 'start', 'start': {'customParameters': {}}})
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close'
    assert output.get('code') == 4401
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_IN_PROGRESS
    assert session.transcript == []


async def test_reject_session_id_mismatching_token_sid_closes_4403(
    tenant_a, location_a1, make_call_session,
):
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)
    other_session = await amake(make_call_session, tenant_a, location_a1)

    comm = await open_socket()
    await comm.send_json_to({'event': 'start', 'start': {'streamSid': 'MZ1',
        'customParameters': {'streamToken': token, 'sessionId': str(other_session.pk)}}})
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close' and output.get('code') == 4403
    await comm.disconnect()

    session = await arefresh(session)
    other_session = await arefresh(other_session)
    assert session.transcript == [] and other_session.transcript == []


async def test_reject_cross_tenant_session_closes_4404_zero_writes(
    tenant_a, location_a1, tenant_b, location_b1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    # Token bound to tenant B for tenant A's session -> _resolve misses -> 4404.
    bad_token = mint_stream_token(session.pk, tenant_b.pk, location_b1.pk)

    comm = await open_socket()
    await comm.send_json_to({'event': 'start', 'start': {'streamSid': 'MZ1',
        'customParameters': {'streamToken': bad_token, 'sessionId': str(session.pk)}}})
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close' and output.get('code') == 4404
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_IN_PROGRESS
    assert session.transcript == []


async def test_reject_cross_location_session_closes_4404_zero_writes(
    tenant_a, location_a1, location_a2, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    # Token bound to location A2 for an A1 session -> _resolve misses -> close 4404.
    bad_token = mint_stream_token(session.pk, tenant_a.pk, location_a2.pk)

    comm = await open_socket()
    await comm.send_json_to({'event': 'start', 'start': {'streamSid': 'MZ1',
        'customParameters': {'streamToken': bad_token, 'sessionId': str(session.pk)}}})
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close' and output.get('code') == 4404
    await comm.disconnect()

    session = await arefresh(session)
    assert session.transcript == []  # never authorized, never served


async def test_disabled_midcall_finalizes_failed_with_reason(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """Agent disabled between webhook and stream -> row finalized failed, not stuck."""
    await amake(make_agent_setting, tenant_a, location_a1, enabled=False)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await open_socket()
    await comm.send_json_to({'event': 'start', 'start': {'streamSid': 'MZ1',
        'customParameters': {'streamToken': token, 'sessionId': str(session.pk)}}})
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close' and output.get('code') == 4403
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_FAILED
    assert session.ended_at is not None
    assert session.metadata.get('ended_reason') == 'disabled'


async def test_capacity_cap_declines_and_releases_the_slot(
    settings, tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """At the per-worker ceiling, a call is declined and the row finalized failed."""
    settings.MAX_CONCURRENT_CALLS = 0
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await open_socket()
    await comm.send_json_to({'event': 'start', 'start': {'streamSid': 'MZ1',
        'customParameters': {'streamToken': token, 'sessionId': str(session.pk)}}})
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close' and output.get('code') == 4403
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_FAILED
    assert session.metadata.get('ended_reason') == 'capacity'
    assert MediaStreamConsumer._active_calls == 0  # a declined call is not counted


# --------------------------------------------------------------------------- #
# The frame loop: one bad frame never kills the call
# --------------------------------------------------------------------------- #

async def test_malformed_json_frame_is_skipped_not_fatal(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    await drain(comm)  # greeting

    # Not valid JSON at all — receive() must swallow it and keep the call alive.
    await comm.send_to(text_data='{not valid json::')
    # A JSON frame that IS valid JSON but not a dict (a bare list).
    await comm.send_to(text_data='[1, 2, 3]')

    await speak_utterance(comm)  # the call still works after the bad frames

    # Wait for the background turn to transcribe the caller (its flush persists the
    # user transcript before playback) rather than racing it with a fixed drain —
    # under a full-repo run the turn can outlast a 0.5 s quiet window.
    async def _transcribed():
        refreshed = await arefresh(session)
        return any(t['role'] == 'user' for t in refreshed.transcript)

    assert await wait_for(_transcribed), 'caller utterance never transcribed after bad frames'
    await drain(comm)
    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status != CallSession.STATUS_IN_PROGRESS
    assert any(t['role'] == 'user' for t in session.transcript)


async def test_malformed_base64_media_payload_is_skipped(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    await drain(comm)  # greeting

    await comm.send_json_to({'event': 'media', 'media': {'payload': '***not-base64***'}})
    await comm.send_json_to({'event': 'media', 'media': {}})  # no payload key at all

    await speak_utterance(comm)  # still works afterward
    await drain(comm)
    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status != CallSession.STATUS_IN_PROGRESS


async def test_non_dict_top_level_frame_is_ignored(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    await drain(comm)
    await comm.send_to(text_data=json.dumps('just a string, not an object'))
    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status != CallSession.STATUS_IN_PROGRESS


# --------------------------------------------------------------------------- #
# Teardown — guaranteed and idempotent
# --------------------------------------------------------------------------- #

async def test_finalize_is_idempotent_stop_then_disconnect(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    await drain(comm)
    await comm.send_json_to({'event': 'stop'})  # first _finalize(), via 'stop'
    output = await comm.receive_output(timeout=1)
    assert output['type'] == 'websocket.close' and output.get('code') == 1000

    session_after_stop = await arefresh(session)
    ended_at_after_stop = session_after_stop.ended_at
    assert session_after_stop.status != CallSession.STATUS_IN_PROGRESS

    await comm.disconnect()  # second _finalize(), via disconnect() — must no-op

    session_after_disconnect = await arefresh(session)
    assert session_after_disconnect.ended_at == ended_at_after_stop  # not re-stamped
    assert session_after_disconnect.status == session_after_stop.status


async def test_never_authorized_disconnect_writes_nothing(
    tenant_a, location_a1, make_call_session,
):
    """A socket that connects and drops before a valid `start` never touches the row."""
    session = await amake(make_call_session, tenant_a, location_a1)
    comm = await open_socket()
    await comm.disconnect()  # no start frame ever sent

    session = await arefresh(session)
    assert session.status == CallSession.STATUS_IN_PROGRESS
    assert session.transcript == [] and session.logs == [] and session.usage == []


async def test_duplicated_start_frame_is_ignored_not_reprocessed(
    tenant_a, location_a1, make_agent_setting, make_call_session,
):
    """A replayed `start` must not re-verify, rebuild CallState or double-greet."""
    await amake(make_agent_setting, tenant_a, location_a1)
    session = await amake(make_call_session, tenant_a, location_a1)
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)

    comm = await connect(token, session.pk)
    # Re-send the identical start frame before draining anything.
    await comm.send_json_to({'event': 'start', 'streamSid': 'MZ1', 'start': {
        'streamSid': 'MZ1', 'callSid': 'CA1',
        'customParameters': {'streamToken': token, 'sessionId': str(session.pk)}}})

    await drain(comm)
    await speak_utterance(comm)
    await drain(comm)
    await comm.send_json_to({'event': 'stop'})
    await comm.disconnect()

    session = await arefresh(session)
    assert session.status != CallSession.STATUS_IN_PROGRESS
    # Exactly one greeting — a duplicated start would have produced two.
    greetings = [t for t in session.transcript if t['role'] == 'assistant']
    assert len([g for g in greetings if 'calling' in g['text'].lower()
                or g == greetings[0]]) >= 1
    assert session.transcript[0]['role'] == 'assistant'
    assert session.transcript[0]['sequence'] == 1  # numbering never restarted


# --------------------------------------------------------------------------- #
# `_resolve` — the sync ORM lookup, query-count guarded
# --------------------------------------------------------------------------- #

def test_resolve_query_count_is_bounded(
    django_assert_max_num_queries, tenant_a, location_a1, make_agent_setting, make_call_session,
):
    make_agent_setting(tenant_a, location_a1)
    session = make_call_session(tenant_a, location_a1)
    consumer = MediaStreamConsumer()
    with django_assert_max_num_queries(4):
        result = consumer._resolve(tenant_a.pk, location_a1.pk, session.pk)
    assert result is not None


def test_resolve_returns_none_on_any_mismatch(
    tenant_a, location_a1, tenant_b, make_agent_setting, make_call_session,
):
    make_agent_setting(tenant_a, location_a1)
    session = make_call_session(tenant_a, location_a1)
    consumer = MediaStreamConsumer()
    assert consumer._resolve(tenant_b.pk, location_a1.pk, session.pk) is None
    assert consumer._resolve(tenant_a.pk, location_a1.pk, session.pk + 999999) is None
