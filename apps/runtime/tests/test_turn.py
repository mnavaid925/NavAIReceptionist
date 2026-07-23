"""The turn loop — `run_turn`: STT -> history -> LLM (tool-cap seam) -> TTS.

Runs against the real `apps.runtime.agent.turn.run_turn` with the fake provider
adapters directly (no consumer, no websocket) — this is the pure conversation
logic the consumer drives. Every provider-failure path degrades to the spoken
`FALLBACK_LINE` and still records a usage delta; it never raises out of the loop.
"""
import math
import struct

import pytest
from django.utils import timezone

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from apps.runtime.agent import (
    FALLBACK_LINE,
    MAX_HISTORY_TURNS,
    CallState,
    ProviderBundle,
    run_turn,
    tts_only_cost,
)
from apps.runtime.providers.audio import STT_SAMPLE_RATE
from apps.runtime.providers.llm import FakeLlmBackend
from apps.runtime.providers.reliability import TransientProviderError
from apps.runtime.providers.stt import FakeSttBackend
from apps.runtime.providers.tts import FakeTtsBackend

pytestmark = pytest.mark.django_db


def _utterance_pcm(seconds=0.1, amplitude=6000, hz=200):
    n = int(STT_SAMPLE_RATE * seconds)
    step = 2 * math.pi * hz / STT_SAMPLE_RATE
    return struct.pack(f'<{n}h', *(int(amplitude * math.sin(step * i)) for i in range(n)))


def _silence_pcm(seconds=0.1):
    n = int(STT_SAMPLE_RATE * seconds)
    return b'\x00\x00' * n


@pytest.fixture
def agent_setting(tenant_a, location_a1):
    return AgentSetting.objects.create(
        tenant=tenant_a, location=location_a1, enabled=True,
        greeting='hi', prompt_text='You are the receptionist.',
        voice_provider=AgentSetting.VOICE_LIVE,
    )


@pytest.fixture
def call_session(tenant_a, location_a1):
    return CallSession.objects.create(
        tenant=tenant_a, location=location_a1, provider_call_sid='TURN-1',
        from_number='+15005550006', to_number='+13125550140',
        status=CallSession.STATUS_IN_PROGRESS, mode=CallSession.MODE_LIVE,
        started_at=timezone.now(),
    )


@pytest.fixture
def state(tenant_a, location_a1, agent_setting, call_session):
    return CallState(
        tenant_id=tenant_a.pk, location_id=location_a1.pk, session_id=call_session.pk,
        agent_setting_id=agent_setting.pk, voice_provider=agent_setting.voice_provider,
        started_at=call_session.started_at,
    )


def _bundle(stt=None, tts=None, llm=None):
    return ProviderBundle(
        stt=stt or FakeSttBackend(),
        tts=tts or FakeTtsBackend(voice_provider='live'),
        llm=llm or FakeLlmBackend(),
    )


async def _run(state, pcm, agent_setting, call_session, location_a1, providers):
    return await run_turn(
        state, pcm, agent_setting=agent_setting, call_session=call_session,
        location=location_a1, providers=providers, now=timezone.now(),
    )


# --------------------------------------------------------------------------- #
# The happy path: one user + one assistant transcript entry, one usage delta
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_one_turn_appends_one_user_and_one_assistant_transcript(
    state, agent_setting, call_session, location_a1,
):
    providers = _bundle(llm=FakeLlmBackend(replies=['Sure, what day works?']))
    result = await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)

    roles = [t['role'] for t in state.transcript_buffer]
    assert roles == ['user', 'assistant']
    assert state.transcript_buffer[1]['text'] == 'Sure, what day works?'
    assert result.reply_text == 'Sure, what day works?'
    assert result.reply_mulaw  # TTS produced audio
    assert not result.spoke_fallback


@pytest.mark.asyncio
async def test_one_turn_appends_exactly_one_usage_delta(
    state, agent_setting, call_session, location_a1,
):
    providers = _bundle()
    await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert len(state.usage_buffer) == 1
    entry = state.usage_buffer[0]
    assert entry['turn_sequence'] == 1
    # cost_usd is the sum of its own breakdown — never independently stored.
    assert entry['cost_usd'] == round(sum(
        v for k, v in entry['cost_breakdown'].items() if k.endswith('_cost_usd')
    ), 6)


@pytest.mark.asyncio
async def test_turn_sequence_increments_across_turns(
    state, agent_setting, call_session, location_a1,
):
    providers = _bundle()
    await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert state.turn_sequence == 2
    assert [u['turn_sequence'] for u in state.usage_buffer] == [1, 2]


# --------------------------------------------------------------------------- #
# STT: empty transcript -> TurnResult(empty=True), no transcript/usage written
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_silence_yields_empty_turn_result_no_transcript_no_usage(
    state, agent_setting, call_session, location_a1,
):
    providers = _bundle()
    result = await _run(state, _silence_pcm(), agent_setting, call_session, location_a1, providers)
    assert result.empty is True
    assert state.transcript_buffer == []
    assert state.usage_buffer == []


# --------------------------------------------------------------------------- #
# Provider failure -> spoken fallback, never a raised exception
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_stt_failure_degrades_to_fallback_and_still_records_usage(
    state, agent_setting, call_session, location_a1,
):
    stt = FakeSttBackend(errors=[TransientProviderError(), TransientProviderError()])
    providers = _bundle(stt=stt)
    result = await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert result.spoke_fallback is True
    assert result.reply_text == FALLBACK_LINE
    assert len(state.usage_buffer) == 1  # the degraded turn still costs something


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_fallback_and_still_records_usage(
    state, agent_setting, call_session, location_a1,
):
    llm = FakeLlmBackend(errors=[TransientProviderError(), TransientProviderError()])
    providers = _bundle(llm=llm)
    result = await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert result.spoke_fallback is True
    assert result.reply_text == FALLBACK_LINE
    assert len(state.usage_buffer) == 1


@pytest.mark.asyncio
async def test_llm_timeout_degrades_to_fallback(
    state, agent_setting, call_session, location_a1, settings,
):
    settings.PROVIDER_TIMEOUT_SECONDS = 0.05
    llm = FakeLlmBackend(delay=1.0)
    providers = _bundle(llm=llm)
    result = await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert result.spoke_fallback is True
    assert len(llm.calls) == 1  # a timeout is terminal — never retried


@pytest.mark.asyncio
async def test_tts_failure_never_raises_returns_empty_audio_but_keeps_the_turn(
    state, agent_setting, call_session, location_a1,
):
    """Cannot synthesize a fallback with a broken synthesizer — log and return no
    audio rather than raising into the frame loop. The reply TEXT and usage are
    still recorded."""
    tts = FakeTtsBackend(voice_provider='live',
                          errors=[TransientProviderError(), TransientProviderError()])
    providers = _bundle(tts=tts)
    result = await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert result.spoke_fallback is False  # the LLM succeeded; only TTS is broken
    assert result.reply_mulaw == b''
    assert result.reply_text  # the words are still known
    assert len(state.usage_buffer) == 1  # cost recorded despite TTS failure


@pytest.mark.asyncio
async def test_cost_delta_survives_even_when_tts_is_stubbed_to_raise(
    state, agent_setting, call_session, location_a1,
):
    """The usage delta is appended BEFORE the cancellable TTS await, so a turn
    that dies mid-synthesis (barge-in / hangup / TTS outage) still keeps its
    matching cost entry."""

    class ExplodingTts:
        async def synthesize(self, text):
            raise RuntimeError('boom - simulates a cancelled/broken TTS leg')

    providers = _bundle(tts=ExplodingTts())
    with pytest.raises(RuntimeError):
        await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    # The cost delta for this turn was appended before the raising await.
    assert len(state.usage_buffer) == 1
    assert len(state.transcript_buffer) == 2  # user + assistant text already recorded


# --------------------------------------------------------------------------- #
# History trimming
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_history_trimmed_to_max_history_turns(
    state, agent_setting, call_session, location_a1,
):
    state.history = [{'role': 'user', 'text': f'msg {i}'} for i in range(MAX_HISTORY_TURNS + 10)]
    providers = _bundle()
    await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert len(state.history) == MAX_HISTORY_TURNS
    # The newest turns (this one's user + assistant) survive the trim.
    assert state.history[-1]['role'] == 'assistant'


# --------------------------------------------------------------------------- #
# Tool-iteration cap seam: tools=[] today -> exactly one LLM call per turn
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_no_tool_calls_means_a_single_llm_call(
    state, agent_setting, call_session, location_a1,
):
    """A reply with no tool calls ends the loop after exactly one model call.

    3.2 asserted `tools == 0` here because the loop hard-coded `tools=[]`. 3.3
    fills that seam: the loop now offers the location's real tool surface
    (`active_tools`), so the meaningful assertion is that the turn still makes ONE
    call when the model asks for no tools — and that the tools it was offered are
    exactly what this location enables.
    """
    from apps.runtime.agent import active_tools

    llm = FakeLlmBackend()
    providers = _bundle(llm=llm)
    await _run(state, _utterance_pcm(), agent_setting, call_session, location_a1, providers)
    assert len(llm.calls) == 1
    assert llm.calls[0]['tools'] == len(active_tools(agent_setting))
    assert llm.calls[0]['tools'] > 0


# --------------------------------------------------------------------------- #
# tts_only_cost — the greeting's cost delta (no STT, no LLM leg)
# --------------------------------------------------------------------------- #

def test_tts_only_cost_has_no_stt_or_llm_legs():
    breakdown, cost_usd = tts_only_cost('live', 'Thanks for calling Acme.')
    assert breakdown['input_audio_seconds'] == 0.0
    assert breakdown['input_text_tokens'] == 0 and breakdown['output_text_tokens'] == 0
    assert cost_usd == round(sum(
        v for k, v in breakdown.items() if k.endswith('_cost_usd')
    ), 6)


def test_tts_only_cost_cascaded_provider_shape():
    breakdown, cost_usd = tts_only_cost('google', 'A short line.')
    assert breakdown['llm_input_tokens'] == 0 and breakdown['llm_output_tokens'] == 0
    assert breakdown['stt_seconds'] == 0.0
    assert breakdown['tts_characters'] == len('A short line.')
    assert cost_usd == breakdown['tts_cost_usd']  # the only non-zero leg
