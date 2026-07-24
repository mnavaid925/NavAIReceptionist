"""The call-recording adapter — sub-module 3.5.

The last provider seam in Module 3: where a finished call's audio becomes bytes
on disk and a path on ``CallSession.recording_blob``. Same shape as every other
adapter here — an interface, a real fake, a live backend that refuses to exist
outside ``PROVIDER_MODE=live``, and one ``get_*_backend()`` resolver.

**Writes go through ``apps.calls.storage.save_recording``, never a raw open().**
That helper roots at ``PRIVATE_MEDIA_ROOT`` (outside the web-servable
``MEDIA_ROOT``) and routes through ``safe_join``, so a malformed path raises
rather than escaping the private root. 5.4 built the read side against exactly
that storage; this is the write it was waiting for.

**Consent is not checked here — it is checked by the caller, structurally.** The
consumer computes one ``should_record`` boolean from ``CallState.consent_basis``
and writes the recording path and the ``consent_basis`` metadata key from that
same boolean in the same ``save()``. Re-deriving consent inside the backend would
create a second, divergent gate; taking ``should_record`` as an explicit argument
keeps the guarantee in one place and makes "record nothing" a first-class,
testable call rather than an omission.

**Deliberately SYNC, unlike ``TtsBackend``/``SttBackend``.** Its one call site is
``MediaStreamConsumer._finalize_session``, which is already a sync method run off
the event loop through ``database_sync_to_async``. Local file I/O needs no
timeout/retry policy the way a network call does, and making this ``async`` would
mean driving an event loop from inside an already-off-loop worker thread for no
benefit. Do not "fix" the shape asymmetry — it is the reason, not an oversight. A
future live backend that DOES cross the network belongs behind
``providers.reliability.call_bounded`` at its own call site.
"""
import abc
import io
import math
import struct
import wave

from django.core.files.base import ContentFile

from apps.runtime.providers.audio import CARRIER_SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH
from apps.runtime.providers.base import is_live, require_live

__all__ = ['RecordingBackend', 'FakeRecordingBackend', 'LiveRecordingBackend',
           'get_recording_backend', 'recording_path_for']


def recording_path_for(call_session, extension='wav'):
    """The private-storage path a call's recording is written to.

    Tenant- and location-partitioned by NUMERIC id (the consumer has no slug
    loaded at teardown, and an id cannot change under a rename the way a slug
    can), keyed on the provider call SID — which is unique across the table, so
    two calls can never collide on one file.
    """
    return (f'private/calls/{call_session.tenant_id}/{call_session.location_id}/'
            f'{call_session.provider_call_sid}.{extension}')


class RecordingBackend(abc.ABC):
    """Finalize one call's recording and return its stored path."""

    @abc.abstractmethod
    def finalize(self, call_session, *, should_record):
        """Persist the recording and return its path, or ``''`` for none.

        ``should_record=False`` MUST write nothing and return ``''`` — the caller
        has already decided consent does not permit a recording, and a backend
        that wrote anyway would defeat the gate.
        """
        raise NotImplementedError


class FakeRecordingBackend(RecordingBackend):
    """Writes a real, playable stub WAV — a fake implementation, not a mock.

    Under ``PROVIDER_MODE=fake`` there is no carrier and therefore no captured
    audio, but ``recording_blob`` must still resolve to real bytes: 5.4's player,
    its signed serve view and its Range handling are all exercised by dev and test
    runs, and a path pointing at nothing makes all three untestable (the seeded
    demo rows already have that problem — the real runtime path must not repeat
    it). So this synthesizes a short deterministic tone through the stdlib ``wave``
    module: no numpy, no network, byte-identical across runs.

    The stub's CONTENT is unrelated to ``waveform_peaks``, which is derived from
    live per-frame DSP energy in the consumer. Two independent write paths that
    merely happen to land in the same ``save()`` — the waveform stays real even
    though the fake audio is not.
    """

    _TONE_HZ = 180
    _AMPLITUDE = 6000
    _SECONDS = 0.5

    def __init__(self, sample_rate=CARRIER_SAMPLE_RATE):
        self.rate = sample_rate
        #: Every finalize() call, for tests and the diagnostics smoke.
        self.calls = []

    def finalize(self, call_session, *, should_record):
        self.calls.append({'session_id': call_session.pk,
                           'should_record': bool(should_record)})
        if not should_record:
            return ''
        path = recording_path_for(call_session, 'wav')
        # `save()` de-duplicates a name collision by suffixing, so a re-finalize
        # (which should not happen — finalize is idempotent-guarded upstream)
        # never silently overwrites a recording that already exists.
        return save_stub_wav(path, self._tone_bytes(), self.rate)

    def _tone_bytes(self):
        """Deterministic mono PCM16 tone — the stub recording's payload."""
        count = int(self.rate * self._SECONDS)
        step = 2 * math.pi * self._TONE_HZ / self.rate
        return struct.pack(
            '<%dh' % count,
            *(int(self._AMPLITUDE * math.sin(step * n)) for n in range(count)),
        )


def save_stub_wav(path, pcm16_bytes, sample_rate=CARRIER_SAMPLE_RATE):
    """Wrap raw PCM16 in a WAV container and store it, returning the saved path.

    Split out from the backend so the container-writing is testable on its own and
    so a future live encoder can reuse the storage call rather than reinventing
    the placement rules ``apps.calls.storage`` already owns.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16_bytes)
    # Imported at call time: apps.calls.storage touches settings at import, and a
    # provider module is imported early enough that a module-level import here
    # would couple this package's import order to Module 5's.
    from apps.calls.storage import save_recording

    return save_recording(path, ContentFile(buffer.getvalue()))


class LiveRecordingBackend(RecordingBackend):
    """The live recorder — refuses to exist outside live mode (see TTS/STT)."""

    def __init__(self):
        require_live('the live recording backend')
        raise NotImplementedError(
            'Live recording capture/encode/store is not implemented in 3.5 — the '
            'adapter interface, the consent gate, the retention job and the fake '
            'ship now; the vendor capture/encode integration lands with '
            'credentials. Run with PROVIDER_MODE=fake.'
        )

    def finalize(self, call_session, *, should_record):  # pragma: no cover - never constructed
        raise NotImplementedError


def get_recording_backend():
    """Resolve the recording backend for the active ``PROVIDER_MODE``.

    Anything that is not exactly ``'live'`` resolves to the fake — the same
    fail-safe rule ``providers.base`` states once for every adapter here.
    """
    if is_live():
        return LiveRecordingBackend()
    return FakeRecordingBackend()
