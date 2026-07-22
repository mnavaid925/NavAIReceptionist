"""Text-to-speech adapter — sub-module 3.2.

Narrow async interface (``voice-agent-runtime`` skill §12): ``synthesize(text) ->
(pcm16, rate)``. The consumer resamples the returned PCM down to 8 kHz μ-law and
paces it onto the carrier (``providers.audio``). The public method is bounded
(timeout + retry); the concrete backend implements ``_synthesize``.

The synth rate depends on the location's ``AgentSetting.voice_provider`` (skill
§4): the native-audio ``live`` stack emits at ``TTS_SAMPLE_RATE`` (24 kHz by
default), the cascaded ``google``/``gemini`` stacks at 16 kHz. That rate is
carried back with the audio so the consumer resamples from the right source rate.

The fake is a real implementation, not a mock: it produces **audible** PCM (a low
tone sized to the text) rather than silence, so barge-in and echo-guard tests have
genuine energy to react to. Deterministic, credential-free, and tell-able to fail
or stall so the bounded-call policy is testable.
"""
import abc
import asyncio
import math
import struct

from django.conf import settings

from apps.runtime.providers.audio import CHANNELS, STT_SAMPLE_RATE
from apps.runtime.providers.base import is_live, require_live
from apps.runtime.providers.reliability import call_bounded

__all__ = ['TtsBackend', 'FakeTtsBackend', 'LiveTtsBackend', 'get_tts_backend',
           'synth_rate_for']

#: Cascaded stacks synthesize at 16 kHz; the native-audio stack at the configured
#: (higher) rate. Kept as a helper so the consumer and the fake agree on the rate.
_NATIVE_PROVIDER = 'live'


def synth_rate_for(voice_provider):
    """The PCM sample rate a given ``voice_provider`` synthesizes at."""
    if voice_provider == _NATIVE_PROVIDER:
        return int(getattr(settings, 'TTS_SAMPLE_RATE', 24000))
    return STT_SAMPLE_RATE


class TtsBackend(abc.ABC):
    """Bounded TTS interface. Concrete backends implement ``_synthesize``."""

    async def synthesize(self, text):
        """Synthesize ``text`` to ``(pcm16, rate)``, bounded by the timeout."""
        return await call_bounded(
            lambda: self._synthesize(text),
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        )

    @abc.abstractmethod
    async def _synthesize(self, text):
        """The raw provider call — return ``(pcm16_bytes, sample_rate)``."""
        raise NotImplementedError


class FakeTtsBackend(TtsBackend):
    """Deterministic, audible TTS for non-live modes — no network.

    Emits a low ~200 Hz tone whose length scales with the text (a short floor so
    even a one-word reply is a real, cancellable blob). Amplitude sits well above
    the VAD energy threshold so an echo-guard/barge-in test fed this audio has
    something to detect. ``errors`` / ``delay`` inject failures exactly like the
    STT fake; ``self.calls`` records every call.
    """

    #: Sine amplitude — comfortably above ``VAD_ENERGY_THRESHOLD`` so the guard
    #: has real energy to react to, well under the 16-bit clip ceiling.
    _AMPLITUDE = 8000
    _TONE_HZ = 200
    _MIN_SECONDS = 0.3
    _SECONDS_PER_CHAR = 0.02

    def __init__(self, voice_provider=None, errors=None, delay=0.0):
        self.rate = synth_rate_for(voice_provider)
        self._errors = list(errors or [])
        self._delay = delay
        self.calls = []

    async def _synthesize(self, text):
        self.calls.append({'text_len': len(text or '')})
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        seconds = max(self._MIN_SECONDS, len(text or '') * self._SECONDS_PER_CHAR)
        return self._tone(seconds), self.rate

    def _tone(self, seconds):
        """A mono PCM16 sine tone of ``seconds`` at ``self.rate``."""
        sample_count = int(self.rate * seconds) * CHANNELS
        step = 2 * math.pi * self._TONE_HZ / self.rate
        samples = (
            int(self._AMPLITUDE * math.sin(step * n))
            for n in range(sample_count)
        )
        return struct.pack('<%dh' % sample_count, *samples)


class LiveTtsBackend(TtsBackend):
    """The live TTS backend — refuses to exist outside live mode (see STT)."""

    def __init__(self):
        require_live('the live TTS backend')
        raise NotImplementedError(
            'Live TTS is not implemented in 3.2 — interface, bounded-call policy '
            'and fake ship now; the vendor integration lands with credentials. '
            'Run with PROVIDER_MODE=fake.'
        )

    async def _synthesize(self, text):  # pragma: no cover - never constructed
        raise NotImplementedError


def get_tts_backend(voice_provider=None):
    """Resolve the TTS backend for the active ``PROVIDER_MODE``.

    Non-live → the fake at the rate ``voice_provider`` implies. Live → the live
    backend, which refuses to initialize without a real integration.
    """
    if is_live():
        return LiveTtsBackend()
    return FakeTtsBackend(voice_provider=voice_provider)
