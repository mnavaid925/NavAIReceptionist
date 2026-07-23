"""The STT/TTS/LLM provider adapter contract — resolution, fakes, bounded calls.

`apps/runtime/tests/test_providers.py` already covers the 3.1 telephony helper
module (`providers.telephony`) under that filename; this file is the 3.2 adapter
families (`stt` / `tts` / `llm` / `reliability` / `base`) it does not touch.

The fakes are real contract implementations, not mocks (CLAUDE.md's provider-fake
rule) — these tests exercise the adapter interface itself: resolution by
`PROVIDER_MODE`, deterministic behaviour, and the shared bounded-call policy
(timeout is terminal, `RateLimited` backs off then retries, a transient error
retries) that STT/TTS/LLM all inherit from `providers.reliability`.
"""
import pytest

from apps.runtime.providers.base import LiveModeError, is_live
from apps.runtime.providers.llm import (
    FakeLlmBackend,
    LiveLlmBackend,
    get_llm_backend,
)
from apps.runtime.providers.reliability import (
    ProviderTimeout,
    RateLimited,
    TransientProviderError,
    call_bounded,
)
from apps.runtime.providers.stt import (
    FakeSttBackend,
    LiveSttBackend,
    get_stt_backend,
)
from apps.runtime.providers.tts import (
    FakeTtsBackend,
    LiveTtsBackend,
    get_tts_backend,
    synth_rate_for,
)


# --------------------------------------------------------------------------- #
# Resolution by PROVIDER_MODE
# --------------------------------------------------------------------------- #

def test_get_backends_return_the_fake_under_fake_mode():
    assert is_live() is False
    assert isinstance(get_stt_backend(), FakeSttBackend)
    assert isinstance(get_tts_backend(), FakeTtsBackend)
    assert isinstance(get_llm_backend(), FakeLlmBackend)


def test_live_backends_refuse_construction_outside_live_mode():
    with pytest.raises(LiveModeError):
        LiveSttBackend()
    with pytest.raises(LiveModeError):
        LiveTtsBackend()
    with pytest.raises(LiveModeError):
        LiveLlmBackend()


def test_live_backends_raise_even_when_the_mode_IS_live(settings):
    """`require_live` passes under live mode, but no vendor SDK is wired yet —
    construction still fails, just with a different (NotImplementedError) shape,
    and crucially without ever reaching a network call."""
    settings.PROVIDER_MODE = 'live'
    with pytest.raises(NotImplementedError):
        LiveSttBackend()
    with pytest.raises(NotImplementedError):
        LiveTtsBackend()
    with pytest.raises(NotImplementedError):
        LiveLlmBackend()


def test_get_backends_resolve_to_live_under_live_mode(settings):
    settings.PROVIDER_MODE = 'live'
    with pytest.raises(NotImplementedError):
        get_stt_backend()
    with pytest.raises(NotImplementedError):
        get_tts_backend()
    with pytest.raises(NotImplementedError):
        get_llm_backend()


# --------------------------------------------------------------------------- #
# The fakes are deterministic, real contract implementations
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_stt_silence_yields_empty_transcript():
    backend = FakeSttBackend()
    silence = b'\x00\x00' * 800
    assert await backend.transcribe(silence, 16000) == ''


@pytest.mark.asyncio
async def test_stt_scripted_transcripts_consumed_in_order():
    backend = FakeSttBackend(transcripts=['first', 'second'])
    loud = b'\x10\x27' * 800  # well above the fake's silence RMS floor
    assert await backend.transcribe(loud, 16000) == 'first'
    assert await backend.transcribe(loud, 16000) == 'second'
    # Script exhausted — falls back to the default deterministic line.
    third = await backend.transcribe(loud, 16000)
    assert third and third != 'first' and third != 'second'


@pytest.mark.asyncio
async def test_llm_fake_scripted_replies_and_no_tool_calls():
    backend = FakeLlmBackend(replies=['hello there'])
    text, tool_calls, usage = await backend.generate([], 'system prompt', tools=[])
    assert text == 'hello there'
    assert tool_calls == []  # 3.2 never populates tool calls — that is 3.3's
    assert usage['model'] and 'input_tokens' in usage and 'output_tokens' in usage


@pytest.mark.asyncio
async def test_tts_rate_follows_voice_provider(settings):
    assert synth_rate_for('live') == settings.TTS_SAMPLE_RATE
    assert synth_rate_for('google') == 16000
    assert synth_rate_for('gemini') == 16000

    live_backend = get_tts_backend(voice_provider='live')
    google_backend = get_tts_backend(voice_provider='google')
    assert live_backend.rate == settings.TTS_SAMPLE_RATE
    assert google_backend.rate == 16000


@pytest.mark.asyncio
async def test_tts_fake_produces_audible_non_empty_pcm():
    backend = FakeTtsBackend(voice_provider='google')
    pcm, rate = await backend.synthesize('a short reply')
    assert pcm and rate == 16000


# --------------------------------------------------------------------------- #
# call_bounded — the shared timeout/retry/backoff policy
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_timeout_is_terminal_no_retry(settings):
    """A hung provider is NOT retried — one attempt, then ProviderTimeout."""
    settings.PROVIDER_TIMEOUT_SECONDS = 0.05
    backend = FakeSttBackend(delay=1.0)
    with pytest.raises(ProviderTimeout):
        await backend.transcribe(b'\x10\x27' * 800, 16000)
    assert len(backend.calls) == 1  # exactly one attempt, never a second


@pytest.mark.asyncio
async def test_rate_limited_backs_off_then_retries():
    """A RateLimited failure sleeps, then the bounded call retries once."""
    backend = FakeSttBackend(errors=[RateLimited(), None])
    text = await backend.transcribe(b'\x10\x27' * 800, 16000)
    assert text  # the retry succeeded
    assert len(backend.calls) == 2  # first attempt + the one bounded retry


@pytest.mark.asyncio
async def test_transient_error_retries():
    backend = FakeLlmBackend(errors=[TransientProviderError(), None])
    text, tool_calls, usage = await backend.generate([], 'sys', tools=[])
    assert text
    assert len(backend.calls) == 2


@pytest.mark.asyncio
async def test_exhausted_retries_raise_the_last_error():
    backend = FakeTtsBackend(errors=[TransientProviderError(), TransientProviderError()])
    with pytest.raises(TransientProviderError):
        await backend.synthesize('hello')
    assert len(backend.calls) == 2  # first attempt + the one retry, then give up


@pytest.mark.asyncio
async def test_non_provider_exception_propagates_without_retry():
    """A bug in our own code is not a retryable provider failure."""
    calls = []

    async def factory():
        calls.append(1)
        raise ValueError('not a provider failure')

    with pytest.raises(ValueError):
        await call_bounded(factory, timeout=1.0)
    assert len(calls) == 1  # never retried
