"""Speech-to-text adapter — sub-module 3.2.

Narrow async interface (``voice-agent-runtime`` skill §12): ``transcribe(pcm16,
rate) -> str``. The public method is **bounded** (timeout + retry via
``reliability.call_bounded``); the concrete backend implements the raw
``_transcribe``. The turn loop catches a ``ProviderError`` on exhaustion and
degrades to a spoken fallback — the adapter never returns dead air itself, it
either transcribes or raises.

``get_stt_backend()`` resolves by ``PROVIDER_MODE`` (``providers.base``): any
non-``live`` mode returns the fake, which needs no credentials and no network. The
**live** backend refuses to exist outside ``PROVIDER_MODE == 'live'`` and, because
no real vendor SDK is wired yet, raises on construction — a real STT integration
is explicitly a later/integration exercise, not a 3.2 code gap.

**The fake is a real implementation of the contract, not a mock** — deterministic
canned transcripts, silence in → empty string out — so tests exercise the adapter
contract itself. It can be told to fail (rate-limited or transient) or to stall
past the timeout, so the bounded-call policy is testable end to end.
"""
import abc
import asyncio

from django.conf import settings

from apps.runtime.providers.audio import SAMPLE_WIDTH, frame_energy
from apps.runtime.providers.base import is_live, require_live
from apps.runtime.providers.reliability import call_bounded

__all__ = ['SttBackend', 'FakeSttBackend', 'LiveSttBackend', 'get_stt_backend']

#: Below this whole-utterance RMS the fake reports no speech (empty transcript) —
#: an utterance that was pure silence/echo must not become a phantom turn.
_FAKE_SILENCE_RMS = 200

#: What the fake "hears" when no script is supplied — enough to drive a heartbeat
#: call end to end without pretending to be a real recognizer.
_FAKE_DEFAULT_TRANSCRIPT = 'Hi, I would like to book an appointment please.'


class SttBackend(abc.ABC):
    """Bounded STT interface. Concrete backends implement ``_transcribe``."""

    async def transcribe(self, pcm16, rate):
        """Transcribe one utterance, bounded by ``PROVIDER_TIMEOUT_SECONDS``."""
        return await call_bounded(
            lambda: self._transcribe(pcm16, rate),
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        )

    @abc.abstractmethod
    async def _transcribe(self, pcm16, rate):
        """The raw provider call — return the recognized text (possibly empty)."""
        raise NotImplementedError


class FakeSttBackend(SttBackend):
    """Deterministic STT for ``PROVIDER_MODE`` in {fake, sandbox} — no network.

    ``transcripts`` is an optional script consumed one entry per non-silent
    utterance; once exhausted it falls back to the default line. ``errors`` is an
    optional list of exceptions raised on successive calls (``None`` = succeed),
    and ``delay`` sleeps before returning (set it above the timeout to exercise
    the fallback path). Every call is appended to ``self.calls`` for assertions.
    """

    def __init__(self, transcripts=None, errors=None, delay=0.0):
        self._transcripts = list(transcripts or [])
        self._errors = list(errors or [])
        self._delay = delay
        self.calls = []

    async def _transcribe(self, pcm16, rate):
        self.calls.append({'bytes': len(pcm16 or b''), 'rate': rate})
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        # Silence in → empty transcript out. `frame_energy` is RMS over the whole
        # buffer here (it does not care that this is more than one frame).
        if not pcm16 or frame_energy(pcm16) < _FAKE_SILENCE_RMS:
            return ''
        if self._transcripts:
            return self._transcripts.pop(0)
        return _FAKE_DEFAULT_TRANSCRIPT


class LiveSttBackend(SttBackend):
    """The live STT backend — refuses to exist outside live mode.

    ``require_live`` blocks construction in any non-live process, so an instance
    that could reach a real recognizer cannot exist in dev, a test or a seeder. No
    real vendor SDK is wired in this pass, so construction then raises — a genuine
    integration is a later exercise once credentials exist.
    """

    def __init__(self):
        require_live('the live STT backend')
        raise NotImplementedError(
            'Live STT is not implemented in 3.2 — the interface, the bounded-call '
            'policy and the fake ship now; the real vendor integration lands once '
            'credentials exist. Run with PROVIDER_MODE=fake.'
        )

    async def _transcribe(self, pcm16, rate):  # pragma: no cover - never constructed
        raise NotImplementedError


def get_stt_backend(voice_provider=None):
    """Resolve the STT backend for the active ``PROVIDER_MODE``.

    Non-live → the fake (safe path, no credentials). Live → the live backend,
    which refuses to initialize without a real integration. ``voice_provider`` is
    accepted for interface symmetry with the other adapters; the STT contract does
    not branch on it.
    """
    if is_live():
        return LiveSttBackend()
    return FakeSttBackend()
