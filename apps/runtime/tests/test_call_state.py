"""`CallState` — buffered transcript/log/usage with monotonic sequence counters.

The sequence counters must never restart at a flush: the buffers are cleared on
every checkpoint (they hold only the un-persisted delta), so a naive `len()+1`
scheme would renumber from 1 again after each flush and collide with what is
already on the row. `_transcript_seq` / `_log_seq` count across the whole call
instead, independent of how many times the buffer has been drained.
"""
from django.utils import timezone

from apps.runtime.agent import CallState


def _state(**kw):
    defaults = dict(tenant_id=1, location_id=1, session_id=1, agent_setting_id=1,
                     voice_provider='live', started_at=timezone.now())
    defaults.update(kw)
    return CallState(**defaults)


# --------------------------------------------------------------------------- #
# Transcript sequence — survives repeated flush-and-clear cycles
# --------------------------------------------------------------------------- #

def test_transcript_sequence_increments_within_one_buffer():
    state = _state()
    state.add_transcript('assistant', 'hello')
    state.add_transcript('user', 'hi there')
    state.add_transcript('assistant', 'how can I help?')
    assert [t['sequence'] for t in state.transcript_buffer] == [1, 2, 3]


def test_transcript_sequence_survives_a_flush_clear_cycle():
    state = _state()
    state.add_transcript('assistant', 'greeting')
    state.add_transcript('user', 'turn one')
    assert [t['sequence'] for t in state.transcript_buffer] == [1, 2]

    # Simulate the consumer's flush: capture-and-clear the buffer.
    state.transcript_buffer.clear()

    state.add_transcript('assistant', 'reply one')
    state.add_transcript('user', 'turn two')
    # Sequence keeps counting from 3, not restarting at 1.
    assert [t['sequence'] for t in state.transcript_buffer] == [3, 4]


def test_transcript_sequence_survives_multiple_flush_cycles():
    state = _state()
    expected_seq = 0
    for cycle in range(5):
        state.add_transcript('user', f'utterance {cycle}')
        expected_seq += 1
        assert state.transcript_buffer[-1]['sequence'] == expected_seq
        state.transcript_buffer.clear()  # flush


def test_transcript_entry_shape_and_offset():
    state = _state(started_at=timezone.now())
    state.add_transcript('user', 'hello')
    entry = state.transcript_buffer[0]
    assert set(entry.keys()) == {'sequence', 'role', 'text', 'at', 'offset'}
    assert entry['role'] == 'user' and entry['text'] == 'hello'
    assert entry['offset'] >= 0.0


def test_transcript_offset_is_zero_when_started_at_unknown():
    state = _state(started_at=None)
    state.add_transcript('assistant', 'hi')
    assert state.transcript_buffer[0]['offset'] == 0.0


# --------------------------------------------------------------------------- #
# Log sequence — same discipline, independent counter from transcript
# --------------------------------------------------------------------------- #

def test_log_sequence_survives_flush_cycles_independently_of_transcript():
    state = _state()
    state.add_transcript('user', 'a')  # transcript_seq -> 1
    state.add_log('info', 'call', 'first event')  # log_seq -> 1
    state.add_log('debug', 'asr', 'second event')  # log_seq -> 2
    assert [entry['sequence'] for entry in state.logs_buffer] == [1, 2]

    state.transcript_buffer.clear()
    state.logs_buffer.clear()

    state.add_transcript('user', 'b')  # transcript_seq -> 2, unaffected by log_seq
    state.add_log('warning', 'vad', 'third event')  # log_seq -> 3, not 1
    assert state.transcript_buffer[0]['sequence'] == 2
    assert state.logs_buffer[0]['sequence'] == 3


def test_log_entry_defaults_raw_json_to_empty_dict():
    state = _state()
    state.add_log('info', 'call', 'no payload')
    assert state.logs_buffer[0]['raw_json'] == {}


def test_log_entry_carries_the_given_raw_json():
    state = _state()
    state.add_log('error', 'asr', 'STT failed', {'error': 'TransientProviderError'})
    assert state.logs_buffer[0]['raw_json'] == {'error': 'TransientProviderError'}


# --------------------------------------------------------------------------- #
# Usage — keyed by turn_sequence, not its own counter
# --------------------------------------------------------------------------- #

def test_add_usage_uses_current_turn_sequence():
    state = _state()
    state.turn_sequence = 1
    state.add_usage({'model': 'fake'}, 0.001)
    state.turn_sequence = 2
    state.add_usage({'model': 'fake'}, 0.002)
    assert [u['turn_sequence'] for u in state.usage_buffer] == [1, 2]
    assert [u['cost_usd'] for u in state.usage_buffer] == [0.001, 0.002]


def test_usage_buffer_survives_a_flush_and_keeps_using_live_turn_sequence():
    state = _state()
    state.turn_sequence = 5
    state.add_usage({'model': 'fake'}, 0.01)
    state.usage_buffer.clear()  # flush
    state.turn_sequence = 6
    state.add_usage({'model': 'fake'}, 0.02)
    assert state.usage_buffer == [
        {'turn_sequence': 6, 'cost_breakdown': {'model': 'fake'}, 'cost_usd': 0.02},
    ]
