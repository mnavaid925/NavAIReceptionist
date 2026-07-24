"""`apps.runtime.providers.recording` — the call-recording adapter (3.5).

Mirrors `test_provider_adapters.py`'s Live*Backend pattern (`LiveModeError`
outside live mode, `NotImplementedError` under live mode with no vendor SDK
wired yet — never a network call either way) and `test_storage.py`'s
real-file discipline: every write this file makes is cleaned up in a
`finally`, so the suite leaves `PRIVATE_MEDIA_ROOT` exactly as it found it.
"""
import io
import wave

import pytest

from apps.calls.storage import (
    open_recording,
    recording_exists,
    recording_size,
    recording_storage,
)
from apps.runtime.providers.audio import CARRIER_SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH
from apps.runtime.providers.base import LiveModeError, is_live
from apps.runtime.providers.recording import (
    FakeRecordingBackend,
    LiveRecordingBackend,
    get_recording_backend,
    recording_path_for,
    save_stub_wav,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# get_recording_backend / LiveRecordingBackend — PROVIDER_MODE resolution
# --------------------------------------------------------------------------- #

def test_get_recording_backend_is_fake_under_fake_mode():
    assert is_live() is False
    assert isinstance(get_recording_backend(), FakeRecordingBackend)


def test_get_recording_backend_is_fake_under_sandbox_mode(settings):
    """Anything that is not EXACTLY 'live' fails safe to the fake — sandbox
    included, per `providers.base`'s one rule every adapter obeys."""
    settings.PROVIDER_MODE = 'sandbox'
    assert isinstance(get_recording_backend(), FakeRecordingBackend)


def test_get_recording_backend_is_fake_under_an_unrecognised_mode(settings):
    settings.PROVIDER_MODE = 'not-a-real-mode'
    assert isinstance(get_recording_backend(), FakeRecordingBackend)


def test_live_recording_backend_refuses_construction_outside_live_mode():
    with pytest.raises(LiveModeError):
        LiveRecordingBackend()


def test_live_recording_backend_raises_not_implemented_under_live_mode(settings):
    """`require_live` passes under live mode, but no vendor capture/encode/store
    integration is wired yet — construction still fails, just with a different
    (`NotImplementedError`) shape, and crucially without ever reaching a
    network call or opening a socket."""
    settings.PROVIDER_MODE = 'live'
    with pytest.raises(NotImplementedError):
        LiveRecordingBackend()


def test_get_recording_backend_resolves_to_live_under_live_mode(settings):
    settings.PROVIDER_MODE = 'live'
    with pytest.raises(NotImplementedError):
        get_recording_backend()


# --------------------------------------------------------------------------- #
# recording_path_for — tenant/location partitioned, SID shape-checked
# --------------------------------------------------------------------------- #

def test_recording_path_for_is_tenant_and_location_partitioned(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1)
    path = recording_path_for(session, 'wav')
    assert path == (
        f'private/calls/{tenant_a.pk}/{location_a1.pk}/{session.provider_call_sid}.wav'
    )


def test_recording_path_for_rejects_an_unsafe_provider_call_sid(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(
        tenant_a, location_a1, provider_call_sid='../../etc/passwd')
    with pytest.raises(ValueError):
        recording_path_for(session, 'wav')


def test_recording_path_for_rejects_a_blank_provider_call_sid(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, provider_call_sid='')
    with pytest.raises(ValueError):
        recording_path_for(session, 'wav')


# --------------------------------------------------------------------------- #
# FakeRecordingBackend.finalize(should_record=False) — writes nothing
# --------------------------------------------------------------------------- #

def test_finalize_should_record_false_returns_empty_and_writes_nothing(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1)
    backend = FakeRecordingBackend()
    result = backend.finalize(session, should_record=False)

    assert result == ''
    assert backend.calls == [{'session_id': session.pk, 'should_record': False}]
    # Nothing was ever written at the path that a should_record=True call
    # would have used.
    assert recording_exists(recording_path_for(session, 'wav')) is False


# --------------------------------------------------------------------------- #
# FakeRecordingBackend.finalize(should_record=True) — a real, playable WAV
# --------------------------------------------------------------------------- #

def test_finalize_should_record_true_writes_a_real_playable_wav(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1)
    backend = FakeRecordingBackend()
    path = backend.finalize(session, should_record=True)
    try:
        assert path == recording_path_for(session, 'wav')
        assert backend.calls == [{'session_id': session.pk, 'should_record': True}]

        # apps.calls.storage's whole read surface succeeds on this exact path —
        # not a dangling path pointing at nothing.
        assert recording_exists(path) is True
        size = recording_size(path)
        assert size > 44  # more than a bare 44-byte WAV header — real payload

        fh = open_recording(path)
        try:
            data = fh.read()
        finally:
            fh.close()
        assert len(data) == size

        # A genuinely valid, readable WAV container — not just arbitrary bytes.
        with wave.open(io.BytesIO(data), 'rb') as handle:
            assert handle.getnchannels() == CHANNELS
            assert handle.getsampwidth() == SAMPLE_WIDTH
            assert handle.getframerate() == CARRIER_SAMPLE_RATE
            frames = handle.readframes(handle.getnframes())
        assert frames  # real, non-empty audio payload, not a silent/empty stub
    finally:
        recording_storage.delete(path)


def test_finalize_honours_a_custom_sample_rate(tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)
    backend = FakeRecordingBackend(sample_rate=16000)
    path = backend.finalize(session, should_record=True)
    try:
        fh = open_recording(path)
        try:
            with wave.open(fh, 'rb') as handle:
                assert handle.getframerate() == 16000
        finally:
            fh.close()
    finally:
        recording_storage.delete(path)


def test_finalize_is_a_real_fake_not_a_mock_calls_are_tracked_for_diagnostics(
    tenant_a, location_a1, make_call_session,
):
    """`.calls` is the diagnostics/test introspection hook the docstring names —
    every finalize() call is recorded, success or no-op alike."""
    session_a = make_call_session(tenant_a, location_a1)
    session_b = make_call_session(tenant_a, location_a1)
    backend = FakeRecordingBackend()
    backend.finalize(session_a, should_record=False)
    path_b = backend.finalize(session_b, should_record=True)
    try:
        assert len(backend.calls) == 2
        assert backend.calls[0] == {'session_id': session_a.pk, 'should_record': False}
        assert backend.calls[1] == {'session_id': session_b.pk, 'should_record': True}
    finally:
        recording_storage.delete(path_b)


# --------------------------------------------------------------------------- #
# save_stub_wav — the container-writing helper, testable on its own
# --------------------------------------------------------------------------- #

def test_save_stub_wav_writes_a_valid_wav_container():
    import uuid

    path_name = f'test/{uuid.uuid4().hex}-stub.wav'
    pcm16 = b'\x10\x00' * 400  # 400 samples of a fixed (non-silent) value
    path = save_stub_wav(path_name, pcm16, sample_rate=8000)
    try:
        assert recording_exists(path) is True
        fh = open_recording(path)
        try:
            with wave.open(fh, 'rb') as handle:
                assert handle.getnchannels() == CHANNELS
                assert handle.getsampwidth() == SAMPLE_WIDTH
                assert handle.getframerate() == 8000
                assert handle.getnframes() == 400
        finally:
            fh.close()
    finally:
        recording_storage.delete(path)
