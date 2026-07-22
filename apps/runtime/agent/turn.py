"""The turn loop — sub-module 3.2.

One completed caller utterance in, one spoken reply out (``voice-agent-runtime``
skill §7). This module is pure of the transport: it runs STT → history → LLM →
TTS, appends the transcript / log / usage rows to ``CallState``'s buffers, and
returns the reply as carrier-ready μ-law for the **consumer** to pace onto the
wire. It touches no ORM and no websocket — the consumer owns both, and flushes the
buffers this fills.

Three seams are wired now so 3.3 and 3.4 plug in without reshaping the loop:

* the LLM is called with ``tools=[]`` inside a **bounded iteration loop**
  (``MAX_TOOL_ITERATIONS``); 3.3 populates the tool list and the dispatcher branch,
  and the cap already guarantees a looping model can never produce silence;
* a **deferred-transport check** after the reply is composed; 3.4 acts on
  ``state.pending_transfer`` there, 3.2 leaves it a documented no-op;
* the **per-turn cost** is appended as a delta whose ``cost_breakdown`` shape
  already differs for native-audio vs. cascaded ``voice_provider`` (skill §13).

Every provider call is bounded by the adapter (timeout + retry); on exhaustion the
loop degrades to a **spoken fallback line, never dead air** (skill §11). The one
exception it cannot speak around is TTS itself being down — there is no way to
synthesize a fallback with a broken synthesizer, so it logs and returns no audio
rather than raising into the frame loop.
"""
import time
from dataclasses import dataclass

from django.conf import settings

from apps.runtime.agent.prompt import build_variables, render_system_prompt
from apps.runtime.providers.audio import (
    SAMPLE_WIDTH,
    STT_SAMPLE_RATE,
    pcm16_to_carrier_mulaw,
)
from apps.runtime.providers.reliability import ProviderError

__all__ = ['ProviderBundle', 'TurnResult', 'run_turn', 'FALLBACK_LINE',
           'MAX_HISTORY_TURNS']

#: Spoken when a provider call is exhausted — the never-dead-air degrade (skill §11).
FALLBACK_LINE = "I'm sorry, I'm having a little trouble right now. Could you say that again?"

#: History is resent every turn, so it is trimmed to the last N turns to keep input
#: tokens — and therefore latency and cost — from growing quadratically (skill §7).
MAX_HISTORY_TURNS = 20

# Placeholder pricing — deterministic, NOT real rate cards. Real pricing is an
# integration concern once live vendors are wired; the contract 3.2 must honour is
# only "one usage delta per turn, cost_usd = sum of its breakdown" (skill §13).
_LLM_INPUT_USD_PER_1K = 0.001
_LLM_OUTPUT_USD_PER_1K = 0.002
_STT_USD_PER_SECOND = 0.0001
_TTS_USD_PER_1K_CHARS = 0.015
_AUDIO_USD_PER_SECOND = 0.0002


@dataclass
class ProviderBundle:
    """The three per-call backends, constructed once in the consumer's connect()."""
    stt: object
    tts: object
    llm: object


@dataclass
class TurnResult:
    """What the consumer needs to play and record after a turn.

    ``empty`` means STT found no speech (a false VAD trip on silence) — the
    consumer plays nothing and no transcript row is written. ``reply_mulaw`` empty
    with ``empty=False`` means the reply exists but could not be synthesized (TTS
    down) — logged, not spoken.
    """
    reply_text: str = ''
    reply_mulaw: bytes = b''
    spoke_fallback: bool = False
    empty: bool = False


def _trim_history(history):
    """Keep only the last ``MAX_HISTORY_TURNS`` entries, in place."""
    excess = len(history) - MAX_HISTORY_TURNS
    if excess > 0:
        del history[:excess]


def _cost_breakdown(voice_provider, usage, stt_seconds, tts_chars):
    """Build the per-turn ``(cost_breakdown, cost_usd)`` for the voice provider.

    Native-audio (``live``) reports audio tokens alongside any text tokens as one
    combined leg; cascaded (``google``/``gemini``) reports STT (per audio-second),
    LLM (per token) and TTS (per character) as separate line items (skill §13).
    ``cost_usd`` is the sum of the breakdown's own components — never stored
    independently.
    """
    usage = usage or {}
    llm_in = int(usage.get('input_tokens', 0) or 0)
    llm_out = int(usage.get('output_tokens', 0) or 0)
    model = usage.get('model', '')

    if voice_provider == 'live':
        # One combined native-audio leg: audio in/out priced by duration, plus any
        # text tokens the model also reported.
        input_audio_usd = round(stt_seconds * _AUDIO_USD_PER_SECOND, 6)
        text_usd = round(
            llm_in / 1000 * _LLM_INPUT_USD_PER_1K + llm_out / 1000 * _LLM_OUTPUT_USD_PER_1K, 6
        )
        breakdown = {
            'model': model,
            'input_audio_seconds': round(stt_seconds, 3),
            'output_characters': tts_chars,
            'input_text_tokens': llm_in,
            'output_text_tokens': llm_out,
            'audio_cost_usd': input_audio_usd,
            'text_cost_usd': text_usd,
        }
        return breakdown, round(input_audio_usd + text_usd, 6)

    # Cascaded: three independently-priced legs.
    llm_usd = round(llm_in / 1000 * _LLM_INPUT_USD_PER_1K + llm_out / 1000 * _LLM_OUTPUT_USD_PER_1K, 6)
    stt_usd = round(stt_seconds * _STT_USD_PER_SECOND, 6)
    tts_usd = round(tts_chars / 1000 * _TTS_USD_PER_1K_CHARS, 6)
    breakdown = {
        'model': model,
        'llm_input_tokens': llm_in,
        'llm_output_tokens': llm_out,
        'llm_cost_usd': llm_usd,
        'stt_seconds': round(stt_seconds, 3),
        'stt_cost_usd': stt_usd,
        'tts_characters': tts_chars,
        'tts_cost_usd': tts_usd,
    }
    return breakdown, round(llm_usd + stt_usd + tts_usd, 6)


async def _synthesize_to_carrier(tts, text):
    """TTS ``text`` and convert to 8 kHz carrier μ-law, or ``b''`` if TTS is down."""
    pcm, rate = await tts.synthesize(text)
    return pcm16_to_carrier_mulaw(pcm, rate)


async def run_turn(state, utterance_pcm, *, agent_setting, call_session, location,
                   providers, now):
    """Run one turn to completion. Returns a :class:`TurnResult`; never raises for a
    provider failure — it degrades to a spoken fallback instead.
    """
    state.turn_sequence += 1
    stt_seconds = len(utterance_pcm or b'') / (STT_SAMPLE_RATE * SAMPLE_WIDTH)

    # Recompute variables (fresh `now`) so current_date/current_time/is_open_now
    # are current this turn (skill §10).
    variables = build_variables(agent_setting, call_session, location, now,
                                state.open_intervals)
    system_prompt = render_system_prompt(agent_setting, variables)

    # -- STT ---------------------------------------------------------------- #
    started = time.monotonic()
    try:
        transcript = (await providers.stt.transcribe(utterance_pcm, STT_SAMPLE_RATE)).strip()
    except ProviderError as exc:
        state.add_log('error', 'asr', 'STT failed', {'error': type(exc).__name__})
        return await _fallback(state, providers, 'asr_failed')
    state.add_log('debug', 'asr', 'STT complete',
                  {'ms': int((time.monotonic() - started) * 1000)})

    if not transcript:
        # A false VAD trip on silence/echo — nothing was said, so there is no turn.
        return TurnResult(empty=True)

    state.add_transcript('user', transcript)
    state.history.append({'role': 'user', 'text': transcript})
    _trim_history(state.history)

    # -- LLM (bounded tool-iteration loop; tools empty until 3.3) ----------- #
    started = time.monotonic()
    reply_text = ''
    usage = {}
    iterations = 0
    try:
        while True:
            reply_text, tool_calls, usage = await providers.llm.generate(
                state.history, system_prompt, tools=[])
            iterations += 1
            if not tool_calls:
                break
            # -- 3.3 seam: apply_tool_call for each tool_call, append the results
            #    as a tool-role turn, and loop. Empty in 3.2 (tools=[] => never
            #    reached), but the cap below already protects a looping model.
            if iterations >= settings.MAX_TOOL_ITERATIONS:
                state.add_log('warning', 'llm', 'Tool-iteration cap hit',
                              {'cap': settings.MAX_TOOL_ITERATIONS})
                reply_text = reply_text or FALLBACK_LINE
                break
    except ProviderError as exc:
        state.add_log('error', 'llm', 'LLM failed', {'error': type(exc).__name__})
        return await _fallback(state, providers, 'llm_failed')
    state.add_log('debug', 'llm', 'LLM complete',
                  {'ms': int((time.monotonic() - started) * 1000), 'iterations': iterations})

    state.add_transcript('assistant', reply_text)
    state.history.append({'role': 'assistant', 'text': reply_text})
    _trim_history(state.history)

    # -- 3.4 seam: deferred-transport check. If state.pending_transfer is set, the
    #    transport executes the transfer AFTER this turn's audio plays. 3.2 sets it
    #    never, so this is a documented no-op that 3.4 fills in.

    # -- TTS ---------------------------------------------------------------- #
    started = time.monotonic()
    try:
        reply_mulaw = await _synthesize_to_carrier(providers.tts, reply_text)
    except ProviderError as exc:
        # Cannot synthesize a fallback with a broken synthesizer — log and return
        # the (recorded) reply with no audio rather than raising into the loop.
        state.add_log('error', 'tts', 'TTS failed', {'error': type(exc).__name__})
        reply_mulaw = b''
    else:
        state.add_log('debug', 'tts', 'TTS complete',
                      {'ms': int((time.monotonic() - started) * 1000)})

    breakdown, cost_usd = _cost_breakdown(state.voice_provider, usage, stt_seconds,
                                          len(reply_text))
    state.add_usage(breakdown, cost_usd)

    return TurnResult(reply_text=reply_text, reply_mulaw=reply_mulaw)


async def _fallback(state, providers, reason):
    """Speak the fallback line after a provider failure — never dead air (skill §11).

    Still appends a usage delta (a turn happened, even a degraded one) and records
    the fallback as the assistant transcript so the call log shows what the caller
    actually heard.
    """
    state.add_transcript('assistant', FALLBACK_LINE)
    try:
        reply_mulaw = await _synthesize_to_carrier(providers.tts, FALLBACK_LINE)
    except ProviderError:
        reply_mulaw = b''  # synthesizer is down too — nothing can be spoken.
    breakdown, cost_usd = _cost_breakdown(state.voice_provider, {}, 0.0, len(FALLBACK_LINE))
    state.add_usage(breakdown, cost_usd)
    state.add_log('warning', 'turn', 'Spoken fallback', {'reason': reason})
    return TurnResult(reply_text=FALLBACK_LINE, reply_mulaw=reply_mulaw, spoke_fallback=True)
