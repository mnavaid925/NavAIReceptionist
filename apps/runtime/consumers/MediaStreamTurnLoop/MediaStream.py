"""The Twilio media-stream consumer — sub-module 3.2, the live-call hot path.

One consumer instance = one inbound call. It terminates Twilio's bidirectional
media websocket, owns all per-call transport state, and drives the turn loop. The
binding contract is ``voice-agent-runtime`` §3–§7; the load-bearing points:

**Authorization happens on the ``start`` frame, before any side effect — not on
the raw socket accept.** Twilio delivers the stream's custom ``<Parameter>`` values
(our signed token, the session id) in the ``start`` event, *after* the socket is
open — there is no token to verify at ``connect()`` time (3.1 mints it into a
``<Parameter>``, not the URL). So ``connect()`` accepts the socket but does nothing
else; the very first thing ``receive()`` does on ``start`` is
``verify_stream_token()``, and **no audio is served, no group is joined and no row
is written until that verifies** (Invariant 3). Identity is read only from the
verified token payload, never from the URL. This reconciles the skill's
connect()-centric wording with Twilio's actual handshake — the guarantee that
matters ("no side effect before authorization") is preserved either way.

**Group names are tenant- AND location-namespaced** —
``t{tenant_id}:l{location_id}:call:{session_id}`` (CLAUDE.md realtime rule 3),
resolving the discrepancy with the skill's older ``t{tenant}:call:{sid}`` form.

**Nothing synchronous runs on the event loop.** Every ORM touch goes through
``database_sync_to_async(..., thread_sensitive=False)``; the codec/VAD math is pure
CPU with no I/O. A blocked coroutine here freezes audio for every concurrent call
on the worker. ``thread_sensitive=False`` is load-bearing: the default
(``True``) runs every sync call on ONE process-global thread with no
``ThreadSensitiveContext`` on the websocket path, so one call's DB write would
serialize — and thereby stall audio for — every other concurrent call. Django DB
connections are thread-local, so per-thread execution is safe here.

**One in-flight turn, a single-slot pending queue.** A completed utterance is
dispatched as a background task guarded by ``turn_busy``; an utterance captured
while a turn runs overwrites a single ``pending_utterance`` slot (dropping it loses
the caller's correction, queueing all of them replays a backlog into a dead call).

**Barge-in cancels the turn task** (which is where playback lives), flushes Twilio's
outbound buffer with a ``clear``, and lets the interrupting speech become the next
utterance. The greeting is non-interruptible.

**Teardown is guaranteed and never raises.** ``disconnect()`` (and a Twilio
``stop``) both route through one ``_finalize()`` that flushes the buffered
transcript/logs/usage, stamps ``ended_at`` and a terminal ``status``, and runs even
on an abnormal drop — a carrier hangup is the normal case, not the exception. 3.5
hangs the consent-gated recording and the two-channel waveform off that same one
path, so an abnormal drop persists exactly what a clean hangup does.
"""
import asyncio
import base64
import binascii
import json
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.agents.models import AgentSetting
from apps.agents.services import resolve_transfer_number
from apps.calls.models import CallSession
from apps.runtime.agent import (
    CONSENT_ANNOUNCEMENT_LINE,
    CONSENT_NOT_RECORDED,
    FALLBACK_LINE,
    REASON_BY_KIND,
    RESULT_CONNECTED,
    RESULT_FAILED,
    CallState,
    ProviderBundle,
    build_open_intervals,
    build_transfer_record,
    build_variables,
    looks_like_call_sid,
    looks_like_e164,
    render_greeting,
    resolve_consent,
    run_turn,
    tts_only_cost,
)
from apps.runtime.providers.audio import (
    CARRIER_SAMPLE_RATE,
    FRAME_SECONDS,
    PlaybackTracker,
    Resampler,
    STT_SAMPLE_RATE,
    WaveformAccumulator,
    iter_mulaw_frames,
    mulaw_to_pcm16,
    pcm16_to_carrier_mulaw,
)
from apps.runtime.providers.llm import get_llm_backend
from apps.runtime.providers.recording import get_recording_backend
from apps.runtime.providers.reliability import ProviderError, call_bounded
from apps.runtime.providers.stt import get_stt_backend
from apps.runtime.providers.telephony import get_backend
from apps.runtime.providers.tts import get_tts_backend
from apps.runtime.providers.tokens import STREAM_TOKEN_TTL_SECONDS, verify_stream_token
from apps.runtime.providers.vad import BARGE_IN, UTTERANCE_END, VadState

logger = logging.getLogger(__name__)

# Explicit websocket close codes (skill §3). 4401 unauthorized, 4403 forbidden
# (session/param mismatch or a disabled number), 4404 unknown session.
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404

def group_name(tenant_id, location_id, session_id):
    """The tenant- AND location-namespaced Channels group for one call.

    CLAUDE.md rule 3 writes this scheme as ``t{tenant}:l{location}:call:{session}``,
    but that is the *logical* namespace: Channels rejects a group name containing a
    colon (``require_valid_group_name`` allows only ``[A-Za-z0-9._-]``), so the
    physical name substitutes ``.`` for ``:``. The security property CLAUDE.md
    cares about — a group that another tenant OR another location can never guess
    or share — is fully preserved; only the separator changes to a legal one.
    """
    return f't{tenant_id}.l{location_id}.call.{session_id}'


# Terminal status by ended-reason. A clean hangup or the hard duration cap is a
# completed call; caller silence is abandoned; a number disabled mid-ring, or a
# consumer/provider crash, is failed. ('error' is wired for a future fatal-error
# path — no branch sets it yet; a turn crash logs and keeps the call up rather
# than ending it — but the mapping is kept so that path lands on the right status
# when added.)
_STATUS_BY_REASON = {
    'hangup': CallSession.STATUS_COMPLETED,
    'max_duration': CallSession.STATUS_COMPLETED,
    'idle_timeout': CallSession.STATUS_ABANDONED,
    # 3.3's end_call tool: the caller was done (or it was a wrong number) and the
    # agent hung up deterministically rather than burning minutes on a silence
    # timeout. That is a completed call, with a more specific ended-reason than
    # the plain 'hangup' default.
    'end_call': CallSession.STATUS_COMPLETED,
    # 3.4's deferred transfer: the human/Spanish-line handoff ran (whether the
    # redirect connected or failed, the media leg left this consumer's control) —
    # `_execute_transfer` sets ended_reason='transferred' and the transfer JSON
    # carries the connected/failed detail.
    'transferred': CallSession.STATUS_TRANSFERRED,
    'disabled': CallSession.STATUS_FAILED,
    'capacity': CallSession.STATUS_FAILED,
    'error': CallSession.STATUS_FAILED,
}


class MediaStreamConsumer(AsyncWebsocketConsumer):
    """Terminates one Twilio media stream and runs the agent turn loop over it."""

    #: Per-worker-process count of live authorized calls, for the MAX_CONCURRENT_CALLS
    #: capacity gate (cost is a security control, skill §11). Touched only from the
    #: single-threaded event loop, so a plain += is safe. This bounds ONE worker;
    #: cross-worker enforcement needs a shared Redis/DB counter, which this stack
    #: has not declared (the default cache is LocMemCache) — carried as a tracked
    #: deferral alongside the cross-worker stream-token claim below. A per-process
    #: ceiling is still the right first layer, and the whole ceiling on a
    #: single-process dev/Daphne run.
    _active_calls = 0

    async def connect(self):
        # Per-call state, all initialized before accept so a frame arriving the
        # instant after accept never hits an unset attribute.
        self.authorized = False
        self.finalized = False
        self.counted = False  # whether this call is counted in _active_calls
        self.group_name = None
        self.stream_sid = None

        self.state = None
        self.agent_setting = None
        self.call_session = None
        self.location = None
        self.providers = None

        self.inbound_resampler = Resampler(CARRIER_SAMPLE_RATE, STT_SAMPLE_RATE)
        self.vad = VadState(rate=STT_SAMPLE_RATE)
        # 3.5: ONE accumulator for the whole call — unlike `playback_tracker`,
        # which `_play()` recreates per blob. A per-playback instance would keep
        # only the last reply's peaks and silently discard the conversation.
        self.waveform = WaveformAccumulator()

        self.turn_busy = False
        self.pending_utterance = None
        self.turn_task = None
        self.watchdog_task = None
        self.is_playing = False
        self.interruptible = True
        self.playback_tracker = None
        # 3.4 single-fire guard: transport bookkeeping (like turn_busy/is_playing),
        # NOT conversation state — so it lives on the consumer, not CallState. Set
        # True synchronously before the redirect is awaited, so a concurrent turn
        # or a redelivered signal can never double-execute the bridge.
        self._transfer_started = False

        self.last_activity_at = time.monotonic()
        self.call_started_monotonic = time.monotonic()
        self.idle_prompted = False

        # Accept so Twilio can deliver the `start` frame that carries the token.
        # NOTHING with a side effect happens until that frame authorizes.
        await self.accept()

    async def disconnect(self, code):
        if self.state is not None and self.state.ended_reason is None:
            self.state.ended_reason = 'hangup'
        await self._finalize()

    # -- frame loop --------------------------------------------------------- #

    async def receive(self, text_data=None, bytes_data=None):
        """Dispatch one Twilio JSON frame. One bad frame never kills the call."""
        try:
            message = json.loads(text_data) if text_data else None
        except (TypeError, ValueError):
            return  # malformed frame — skip, do not log the payload (may be audio)
        if not isinstance(message, dict):
            return

        event = message.get('event')
        try:
            if event == 'connected':
                return
            if event == 'start':
                await self._authorize_and_start(message)
                return
            if not self.authorized:
                # Any media (or anything else) before a verified `start` is
                # unauthorized — close rather than silently accept audio.
                await self.close(code=CLOSE_UNAUTHORIZED)
                return
            if event == 'media':
                await self._on_media(message)
            elif event == 'stop':
                if self.state.ended_reason is None:
                    self.state.ended_reason = 'hangup'
                await self._finalize()
                await self.close(code=1000)
            elif event == 'mark':
                pass  # acknowledgement bookkeeping only
        except Exception:  # noqa: BLE001 — one bad frame must not kill the call
            logger.exception('media-stream frame handling error')

    # -- authorization + greeting (the `start` frame) ----------------------- #

    async def _authorize_and_start(self, message):
        # A duplicated or replayed `start` must not re-verify, rebuild CallState,
        # or spawn a second greeting/watchdog — which would orphan the running
        # watchdog (now pointed at a detached state) and discard un-flushed buffers.
        if self.authorized:
            return
        start = message.get('start') or {}
        params = start.get('customParameters') or {}
        token = params.get('streamToken')
        session_param = params.get('sessionId')

        # 1. Verify the signed token FIRST. Identity comes only from its payload.
        payload = verify_stream_token(token)
        if not payload:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return
        session_id = payload.get('sid')
        tenant_id = payload.get('ten')
        location_id = payload.get('loc')

        # 2. The sessionId custom param must match the token's sid — never trust
        #    the higher-value one, never silently reconcile a mismatch.
        if session_param is not None and str(session_param) != str(session_id):
            await self.close(code=CLOSE_FORBIDDEN)
            return

        # 2b. SINGLE-USE CLAIM (3.5 — closes 3.2's tracked replay deferral). The
        #     token is signed and short-TTL, so a replay needs an already-leaked
        #     valid token; but until now a second socket presenting the same
        #     still-valid token would have authorized a SECOND stream against one
        #     CallSession — two turn loops writing one row. `cache.add` is Django's
        #     atomic SETNX (True only on first insert), so the first stream claims
        #     the session and any later one is refused. Placed here, before the DB
        #     resolve: the cheapest possible reject point, with zero side effect —
        #     no query, no row bound, no group joined, no capacity slot taken.
        #
        #     Called directly on the event loop deliberately: the default
        #     LocMemCache is an in-process dict behind a threading.Lock — no ORM, no
        #     network, no file I/O — the same class of safe direct call this file
        #     already makes for the codec/VAD math.
        #     WARNING: on a NETWORKED cache backend (Redis, for a real multi-worker
        #     deployment) this becomes a network call and must move off-loop, and
        #     only then does the claim span the worker fleet. Per-process today,
        #     which is the whole gap on a single-process Daphne run. Tracked with
        #     the cross-worker MAX_CONCURRENT_CALLS deferral in
        #     .claude/tasks/todo.md.
        #
        #     No release on disconnect: the claim expires with the token's own TTL,
        #     and a genuinely new call mints a fresh token via 3.1's webhook, so
        #     holding the key for its full life costs nothing and releasing it early
        #     would re-open the very window this closes.
        if not cache.add(f'runtime:stream-claim:{session_id}', True,
                         timeout=STREAM_TOKEN_TTL_SECONDS):
            await self.close(code=CLOSE_FORBIDDEN)
            return

        # 3. Resolve the models by (tenant, location, session) — pk alone is never
        #    enough. A miss on any of the three closes 4404.
        resolved = await database_sync_to_async(self._resolve, thread_sensitive=False)(
            tenant_id, location_id, session_id)
        if resolved is None:
            await self.close(code=CLOSE_NOT_FOUND)
            return
        agent_setting, call_session, location, open_intervals = resolved

        # Bind the resolved row and state to self NOW — before the enabled re-check
        # below can decline the call. 3.1's webhook already created this
        # CallSession at status='in_progress'; if we decline past this point
        # without owning it, _finalize() bails (state is None) and the row is
        # stranded at in_progress with no ended_at forever. Assigning here lets the
        # decline path finalize it through the one _finalize() path.
        self.agent_setting = agent_setting
        self.call_session = call_session
        self.location = location
        self.state = CallState(
            tenant_id=tenant_id,
            location_id=location_id,
            session_id=session_id,
            agent_setting_id=agent_setting.pk,
            voice_provider=agent_setting.voice_provider,
            open_intervals=open_intervals,
            started_at=call_session.started_at,
        )

        # 4. Re-check the number is still served — a number disabled between
        #    webhook-answer and stream-connect must not get a call (TOCTOU). The
        #    row exists (the agent was enabled at answer time), so finalize it as
        #    'disabled' rather than leaving it live, then decline.
        if not agent_setting.enabled:
            self.state.ended_reason = 'disabled'
            await self._finalize()
            await self.close(code=CLOSE_FORBIDDEN)
            return

        # 4b. Capacity gate (cost is a security control). At the per-worker ceiling,
        #     decline gracefully and finalize the row rather than accepting unbounded
        #     concurrent provider spend / worker exhaustion.
        if type(self)._active_calls >= settings.MAX_CONCURRENT_CALLS:
            self.state.ended_reason = 'capacity'
            await self._finalize()
            await self.close(code=CLOSE_FORBIDDEN)
            return

        # 5. Only now: build providers, join the tenant+location-namespaced group,
        #    and mark authorized. self.accept() already happened in connect().
        self.providers = ProviderBundle(
            stt=get_stt_backend(agent_setting.voice_provider),
            tts=get_tts_backend(agent_setting.voice_provider),
            llm=get_llm_backend(agent_setting.voice_provider),
        )
        # 3.5: resolve the recording consent basis ONCE, here. Deliberately AFTER
        # the enabled/capacity gates above — a declined call never reaches this
        # line, so its `consent_basis` stays None and `_finalize_session` records
        # `not_recorded` for a call that was never really answered, rather than
        # claiming a basis for a conversation that never happened.
        self.state.consent_basis = resolve_consent(location)
        self.stream_sid = start.get('streamSid') or message.get('streamSid')
        self.group_name = group_name(tenant_id, location_id, session_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # Count this call against the per-worker ceiling; _finalize() decrements it.
        type(self)._active_calls += 1
        self.counted = True
        self.authorized = True
        self.last_activity_at = time.monotonic()
        self.call_started_monotonic = time.monotonic()

        # Play the deterministic greeting (0 LLM tokens) and start the watchdog.
        self.turn_busy = True
        self.turn_task = asyncio.create_task(self._greet())
        self.watchdog_task = asyncio.create_task(self._watchdog())

    def _resolve(self, tenant_id, location_id, session_id):
        """Sync ORM resolution of the call's models. Returns None on any miss.

        Scoped by (tenant, location, session) together, with the location→tenant
        chain select_related so the turn loop can read `location.tenant.name`
        without a query on the event loop.
        """
        call_session = (
            CallSession.objects
            .select_related('location', 'location__tenant', 'tenant')
            .filter(pk=session_id, tenant_id=tenant_id, location_id=location_id)
            .first()
        )
        if call_session is None:
            return None
        agent_setting = (
            AgentSetting.objects
            .filter(tenant_id=tenant_id, location_id=location_id)
            .first()
        )
        if agent_setting is None:
            return None
        location = call_session.location
        open_intervals = build_open_intervals(location)
        return agent_setting, call_session, location, open_intervals

    async def _greet(self):
        """Speak the deterministic opener, non-interruptible (skill §6).

        Runs as a fire-and-forget task that nothing awaits, so it MUST catch its
        own exceptions — an uncaught bug here would otherwise die silently, leaving
        the caller in dead air until the idle timeout, on the very first thing every
        caller hears.
        """
        try:
            now = timezone.now()
            variables = build_variables(
                self.agent_setting, self.call_session, self.location, now,
                self.state.open_intervals)
            text = render_greeting(self.agent_setting, variables)
            self.state.add_transcript('assistant', text)
            self.state.history.append({'role': 'assistant', 'text': text})
            self.state.add_log('info', 'call', 'Greeting played')
            try:
                pcm, rate = await self.providers.tts.synthesize(text)
                mulaw = pcm16_to_carrier_mulaw(pcm, rate)
                # The greeting spends TTS too — record its cost, flushed with the
                # transcript below, so the call total is not under-reported.
                self.state.add_usage(*tts_only_cost(self.state.voice_provider, text))
            except ProviderError:
                self.state.add_log('error', 'tts', 'Greeting synthesis failed')
                mulaw = b''
            await self._flush()
            if mulaw:
                await self._play(mulaw, interruptible=False)
            await self._announce_recording()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — never let the greeting die in silence
            logger.exception('greeting failed')
            self.state.add_log('error', 'call', 'Greeting failed')
            await self._speak_fallback_greeting()
        finally:
            self.turn_busy = False
            self.turn_task = None
            self.last_activity_at = time.monotonic()
            self._maybe_drain_pending()

    async def _announce_recording(self):
        """Speak the recording notice when the location's jurisdiction needs one.

        Runs inside ``_greet``'s task, immediately after the opener and before
        ``turn_busy`` is released, so it is non-interruptible and lands before the
        caller's first turn — a disclosure the caller talks over is not a
        disclosure. One-party locations play nothing extra and this returns at once.

        ``consent_announced`` is set only AFTER the audio actually played, so a TTS
        failure leaves it False and the finalized row says honestly that the
        announcement did not happen — and because ``CallState.should_record``
        requires it in a two-party jurisdiction, such a call is simply not
        recorded. Claiming an announcement that never played would be worse than
        recording no claim at all, so this is deliberately not set optimistically.

        **``interruptible`` is held False across the SYNTHESIS, not just the
        playback.** ``_play``'s own ``finally`` resets it to True the instant the
        greeting's audio ends, so without this a caller speaking into the gap
        while this line is being synthesized would barge-in, cancel the ``_greet``
        task this runs inside, and the notice would never play. The ``finally``
        below restores it on every path, including a TTS failure — leaving it
        False would make the whole rest of the call un-interruptible.
        """
        if not self.state.requires_announcement:
            return
        self.interruptible = False
        try:
            try:
                pcm, rate = await self.providers.tts.synthesize(CONSENT_ANNOUNCEMENT_LINE)
            except ProviderError:
                self.state.add_log('error', 'tts', 'Recording notice synthesis failed')
                return
            self.state.add_transcript('assistant', CONSENT_ANNOUNCEMENT_LINE)
            self.state.history.append(
                {'role': 'assistant', 'text': CONSENT_ANNOUNCEMENT_LINE})
            # A second TTS spend — recorded, or the call's cost under-reports it
            # (the same rule the greeting's own TTS cost already follows).
            self.state.add_usage(*tts_only_cost(self.state.voice_provider,
                                                CONSENT_ANNOUNCEMENT_LINE))
            await self._flush()
            await self._play(pcm16_to_carrier_mulaw(pcm, rate), interruptible=False)
            self.state.consent_announced = True
            self.state.add_log('info', 'call', 'Recording notice played')
        finally:
            self.interruptible = True

    async def _speak_fallback_greeting(self):
        """Best-effort spoken fallback when the greeting itself crashed."""
        try:
            pcm, rate = await self.providers.tts.synthesize(FALLBACK_LINE)
            await self._play(pcm16_to_carrier_mulaw(pcm, rate), interruptible=False)
        except Exception:  # noqa: BLE001 — synthesizer may be the thing that broke
            logger.exception('greeting fallback also failed')

    # -- inbound audio ------------------------------------------------------ #

    async def _on_media(self, message):
        payload_b64 = (message.get('media') or {}).get('payload')
        if not payload_b64:
            return
        try:
            mulaw = base64.b64decode(payload_b64)
        except (binascii.Error, ValueError):
            return  # malformed base64 — skip this frame, keep the call alive

        self.last_activity_at = time.monotonic()
        pcm8 = mulaw_to_pcm16(mulaw)
        # 3.5 waveform, caller lane. Unconditional and un-branched on is_playing:
        # Twilio's `media` event carries only the caller's leg, so unlike the VAD's
        # echo guard there is no agent audio here to filter out. Pure CPU (an RMS
        # over 160 bytes), safe on the event loop.
        self.waveform.add_caller_frame(pcm8)
        pcm16 = self.inbound_resampler.resample(pcm8)
        event, utterance = self.vad.feed(pcm16, self.is_playing)

        if event == BARGE_IN:
            if self.interruptible and self.turn_task is not None and not self.turn_task.done():
                # A real interruption of an interruptible reply: flush Twilio's
                # buffer and cancel the turn (which is where playback lives). The
                # VAD has already reset and seeded the interrupting utterance.
                await self._send_clear()
                self.turn_task.cancel()
                # Drop is_playing NOW, synchronously — the cancelled task's _play
                # finally sets it too, but not until a later loop iteration, and any
                # frame arriving in between must route to the listening path so it
                # continues the seeded utterance instead of re-triggering barge-in
                # (which would hit the else branch and discard it).
                self.is_playing = False
                self.state.add_log('info', 'vad', 'Barge-in')
            else:
                # Fired during the non-interruptible greeting (or with no active
                # turn): ignore it and discard the VAD's seeded utterance so the
                # greeting's own echo can never become a phantom caller turn.
                self.vad.reset_listening()
        elif event == UTTERANCE_END and utterance:
            if self.turn_busy:
                self.pending_utterance = utterance  # single slot — overwrite
            else:
                self.turn_busy = True
                self.turn_task = asyncio.create_task(self._run_turn(utterance))

    # -- turn execution + playback ------------------------------------------ #

    async def _run_turn(self, utterance_pcm):
        try:
            now = timezone.now()
            result = await run_turn(
                self.state, utterance_pcm,
                agent_setting=self.agent_setting,
                call_session=self.call_session,
                location=self.location,
                providers=self.providers,
                now=now,
            )
            # Flush BEFORE playback: a barge-in cancels playback, and the
            # transcript/usage of the turn must survive that cancellation.
            await self._flush()
            if not result.empty and result.reply_mulaw:
                # A goodbye that precedes a hangup — or the acknowledgement that
                # precedes a transfer — is played NON-interruptible. Otherwise a
                # caller talking over "goodbye"/"connecting you now" (the most
                # likely moment for them to) would barge-in, cancel this task before
                # the checks below, and strand `pending_hangup`/`pending_transfer`
                # unconsumed — the call would hang on until the 45s idle timeout,
                # mislabelled, and the armed transfer would never fire.
                await self._play(
                    result.reply_mulaw,
                    interruptible=not (self.state.pending_hangup
                                       or self.state.pending_transfer))
            # DEFERRED transport signals (skill §9): the dispatcher only set a flag,
            # so the acknowledgement/goodbye above is spoken in full and the
            # transport acts here, after the audio. Checked whether or not audio was
            # produced — a TTS-down or empty reply must still hang up / transfer.
            if self.state.pending_hangup:
                # 3.3's end_call: close the socket after the goodbye. No REST call.
                await self._finalize()
                await self.close(code=1000)
            elif self.state.pending_transfer:
                # 3.4's transfer: single-fire guarded — `_transfer_started` is set
                # synchronously BEFORE the redirect is awaited, so a concurrent turn
                # (the queued-utterance drain path) or a redelivered signal can never
                # double-execute the bridge against the same live call SID.
                if not self._transfer_started:
                    self._transfer_started = True
                    await self._execute_transfer()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a turn crash must not kill the call
            logger.exception('turn execution failed')
            self.state.add_log('error', 'turn', 'Turn crashed')
        finally:
            self.turn_busy = False
            self.turn_task = None
            self.last_activity_at = time.monotonic()
            self._maybe_drain_pending()

    def _maybe_drain_pending(self):
        """Start a queued utterance, if one arrived mid-turn. Sync — no await."""
        if self.finalized or self.turn_busy or self.pending_utterance is None:
            return
        utterance = self.pending_utterance
        self.pending_utterance = None
        self.turn_busy = True
        self.turn_task = asyncio.create_task(self._run_turn(utterance))

    # -- deferred transfer execution (3.4) ---------------------------------- #

    async def _execute_transfer(self):
        """Execute the deferred human/Spanish-line transfer after its audio played.

        Reached only from ``_run_turn``'s ``pending_transfer`` branch, behind the
        ``_transfer_started`` single-fire guard. The dispatcher already gated
        eligibility AND (for the human line) the working-hours window before arming
        the signal, so this method's job is purely the transport: validate the
        dialable values, drain the outbound buffer, issue the bounded REST redirect,
        capture the outcome and end the call.

        **An armed transfer always ends the call** — the outer guard maps any
        unexpected failure to a ``failed`` outcome, so a redirect that never runs
        can never leave the call hanging with the signal still set.
        """
        kind = self.state.pending_transfer
        reason = REASON_BY_KIND.get(kind, 'Transfer requested.')
        # Stamp the ended-reason SYNCHRONOUSLY, before any await. A real <Dial>
        # redirect ends the media stream, so Twilio's `stop` frame (or the socket
        # `disconnect`) can race in WHILE this method is awaiting the drain/redirect;
        # both those paths finalize with ended_reason='hangup' only when it is still
        # None. Setting it here first means whichever path wins the _finalize()
        # stamps the row 'transferred', not 'completed' — the transfer JSON's
        # `result` still records whether the human actually got it.
        self.state.ended_reason = 'transferred'
        try:
            record = await self._run_transfer_redirect(kind, reason)
        except Exception as exc:  # noqa: BLE001 — an armed transfer MUST still end the call
            logger.error('transfer execution failed (%s)', type(exc).__name__)
            record = build_transfer_record(result=RESULT_FAILED, reason=reason)
        if record.get('result') == RESULT_FAILED:
            # NEVER dead air (CLAUDE.md realtime rule 4): the caller already heard the
            # acknowledgement, so a failed redirect must be spoken, not silent — and a
            # callback is logged so the caller's request survives the failed handoff,
            # mirroring the off-hours fallback the dispatcher already makes.
            await self._handle_failed_transfer()
        await self._record_and_end_transfer(record)

    #: Spoken when a transfer was acknowledged but the redirect did not connect —
    #: keeps the failure from being dead air. A platform constant, never caller text.
    _TRANSFER_FAILED_LINE = ("I'm sorry, I wasn't able to connect you just now. "
                             "I've made a note for someone to call you back.")

    async def _handle_failed_transfer(self):
        """Log a callback and speak an apology after a redirect fails to connect."""
        try:
            await database_sync_to_async(
                self._log_failed_transfer_callback, thread_sensitive=False)()
        except Exception as exc:  # noqa: BLE001 — the apology still matters if this fails
            logger.error('failed-transfer callback write failed (%s)', type(exc).__name__)
        try:
            pcm, rate = await self.providers.tts.synthesize(self._TRANSFER_FAILED_LINE)
            self.state.add_transcript('assistant', self._TRANSFER_FAILED_LINE)
            await self._play(pcm16_to_carrier_mulaw(pcm, rate), interruptible=False)
        except Exception:  # noqa: BLE001 — TTS may be the thing that broke; never crash teardown
            logger.exception('failed-transfer apology could not be spoken')

    def _log_failed_transfer_callback(self):
        """Sync: a CallbackRequest for a caller whose transfer failed to connect."""
        from apps.scheduling.models import CallbackRequest, Contact

        contact = None
        if self.state.contact_id:
            contact = Contact.objects.filter(
                pk=self.state.contact_id, tenant_id=self.state.tenant_id).first()
        CallbackRequest.objects.create(
            tenant_id=self.state.tenant_id, location_id=self.state.location_id,
            contact=contact,
            caller_name=(contact.display_name if contact else ''),
            caller_phone=(self.state.variables or {}).get('from_e164', '') or '',
            reason='Transfer to a person failed to connect.',
            status=CallbackRequest.STATUS_PENDING,
            source=CallbackRequest.SOURCE_AI_PHONE,
        )

    async def _run_transfer_redirect(self, kind, reason):
        """Do the redirect and return the transfer record — no finalize here."""
        resolved = await database_sync_to_async(
            self._resolve_transfer_target, thread_sensitive=False)(kind)
        if resolved is None:
            # The AgentSetting/CallSession vanished mid-call (anonymised/disabled) —
            # a failed transfer, no REST call attempted.
            return build_transfer_record(result=RESULT_FAILED, reason=reason)
        setting, destination, call_sid = resolved

        # TOLL-FRAUD / INJECTION DEFENSE (REQUIRED): the destination is dialed with
        # the tenant's OWN Twilio credentials and the call SID is interpolated into
        # the REST path / TwiML body, so both are shape-checked BEFORE any REST
        # interpolation. A malformed value aborts to 'failed' without ever reaching
        # redirect_call — the destination is server-resolved, never caller-supplied,
        # but this is the belt-and-braces gate at the point it actually gets dialed.
        if not (looks_like_e164(destination) and looks_like_call_sid(call_sid)):
            self.state.add_log(
                'error', 'transfer',
                'Transfer aborted: destination or call reference invalid',
                {'kind': kind, 'result': RESULT_FAILED})
            return build_transfer_record(
                result=RESULT_FAILED,
                reason='Transfer destination or call reference was invalid.',
                destination=destination)

        # Let Twilio's carrier jitter buffer drain the handoff line's last frames
        # before the redirect cuts the media leg (else the last word is clipped).
        await asyncio.sleep(settings.TRANSFER_DRAIN_SECONDS)

        initiated_at = timezone.now()
        result = RESULT_CONNECTED
        try:
            # retries=0: a redirect is NOT idempotently retryable — a second REST
            # call against an already-redirected call SID risks a second bridge.
            outcome = await call_bounded(
                lambda: get_backend().redirect_call(setting, call_sid, destination),
                timeout=settings.PROVIDER_TIMEOUT_SECONDS, retries=0)
            if not getattr(outcome, 'ok', False):
                result = RESULT_FAILED
        except Exception as exc:  # noqa: BLE001 — a failed redirect ends 'failed', never a crash
            # Type only — a provider error's text can carry the SID/request body.
            logger.error('transfer redirect failed (%s)', type(exc).__name__)
            result = RESULT_FAILED

        self.state.add_log(
            'info' if result == RESULT_CONNECTED else 'error', 'transfer',
            f'Transfer {result}', {'kind': kind, 'result': result})
        # No `attempts` list for a single-try transfer — the reader renders the
        # trail only for 2+ attempts, and the seeder convention is to omit it. A
        # real primary→secondary waterfall (a deferred pass, needs a new field)
        # would populate it.
        return build_transfer_record(
            result=result, reason=reason, destination=destination,
            initiated_at=initiated_at, duration_seconds=0)

    def _resolve_transfer_target(self, kind):
        """Sync ORM: re-resolve ``(setting, destination, call_sid)`` for the transfer.

        Re-fetches ``AgentSetting``/``CallSession`` under the call's
        ``(tenant, location, session)`` scope rather than trusting the connect()-time
        cache — the same paranoia ``_resolve()`` applies at authorization time. The
        destination is resolved SERVER-SIDE from a label (``primary``/``secondary``);
        ``resolve_transfer_number`` never accepts a number as input (Invariant 3).
        Returns None on any miss.
        """
        setting = (
            AgentSetting.objects
            .filter(tenant_id=self.state.tenant_id, location_id=self.state.location_id)
            .first()
        )
        call_session = (
            CallSession.objects
            .filter(pk=self.state.session_id, tenant_id=self.state.tenant_id,
                    location_id=self.state.location_id)
            .first()
        )
        if setting is None or call_session is None:
            return None
        target = 'secondary' if kind == 'spanish' else 'primary'
        return setting, resolve_transfer_number(setting, target), call_session.provider_call_sid

    def _stamp_transfer(self, record):
        """Sync: write ONLY the ``transfer`` column, row-locked (see the dispatcher).

        A SEPARATE write from ``_finalize_session``'s status/ended_at stamp — never
        combined into one ``save()`` — so a finalize failure can never silently drop
        a transfer outcome that already landed.
        """
        with transaction.atomic():
            cs = (
                CallSession.objects.select_for_update()
                .filter(pk=self.state.session_id, tenant_id=self.state.tenant_id,
                        location_id=self.state.location_id)
                .first()
            )
            if cs is None:
                return
            cs.transfer = record
            cs.save(update_fields=['transfer', 'updated_at'])

    async def _record_and_end_transfer(self, record):
        """Persist the transfer outcome, then finalize the call as 'transferred'.

        `ended_reason` was already set to 'transferred' at `_execute_transfer` entry
        (before any await, to win the finalize race). The `transfer` JSON write here
        is SEPARATE from `_finalize_session`'s status/ended_at stamp — never one
        `save()` — so a finalize failure cannot silently drop an outcome that
        landed, and `_finalize_session`'s `!= IN_PROGRESS` guard leaves it untouched.
        """
        try:
            await database_sync_to_async(self._stamp_transfer, thread_sensitive=False)(record)
        except Exception as exc:  # noqa: BLE001 — outcome capture must not crash teardown
            logger.error('transfer outcome write failed (%s)', type(exc).__name__)
        # Flush the transfer log entries explicitly: if a racing stop/disconnect
        # already ran _finalize() (and its flush), the transfer's own _finalize()
        # below no-ops, so without this its 'Transfer <result>' log would be stranded
        # in the buffer. _flush() captures-and-clears synchronously, so a double call
        # is a safe no-op.
        await self._flush()
        await self._finalize()
        try:
            await self.close(code=1000)
        except Exception as exc:  # noqa: BLE001 — the transport may already be gone (race)
            logger.error('transfer socket close failed (%s)', type(exc).__name__)

    async def _play(self, mulaw, *, interruptible):
        """Pace μ-law onto the wire one 20 ms frame at a time (skill §4)."""
        self.playback_tracker = PlaybackTracker()
        self.is_playing = True
        self.interruptible = interruptible
        # Starting playback: the caller was silent up to now, so reset listening
        # state — the agent's own audio must never be accumulated as an utterance.
        self.vad.reset_listening()
        try:
            for frame in iter_mulaw_frames(mulaw):
                await self._send_media(frame)
                self.playback_tracker.mark(frame)
                # 3.5 waveform, agent lane — fed from the SAME "frames actually
                # sent" point as the tracker, so a barge-in that cancels this loop
                # leaves peaks for exactly what the caller heard, not the whole
                # synthesized reply. One hook covers every caller of _play():
                # the greeting, the recording notice, each turn's reply, the
                # fallback greeting and the failed-transfer apology.
                self.waveform.add_bot_frame(frame)
                await asyncio.sleep(FRAME_SECONDS)
        finally:
            self.is_playing = False
            self.interruptible = True

    async def _send_media(self, mulaw_frame):
        if not self.stream_sid:
            return
        await self.send(text_data=json.dumps({
            'event': 'media',
            'streamSid': self.stream_sid,
            'media': {'payload': base64.b64encode(mulaw_frame).decode('ascii')},
        }))

    async def _send_clear(self):
        """Tell Twilio to drop any outbound audio it still has buffered."""
        if not self.stream_sid:
            return
        await self.send(text_data=json.dumps({
            'event': 'clear', 'streamSid': self.stream_sid,
        }))

    # -- idle / max-duration watchdog --------------------------------------- #

    async def _watchdog(self):
        """End the call on the hard duration cap or caller-silence idle timeout.

        Cost is a security control (skill §11): a stuck or looping call cannot run
        past ``MAX_CALL_SECONDS``, and a caller who went away is not held on an
        open leg past ``IDLE_TIMEOUT_SECONDS``.
        """
        try:
            while not self.finalized:
                await asyncio.sleep(1.0)
                now = time.monotonic()
                if now - self.call_started_monotonic >= settings.MAX_CALL_SECONDS:
                    self.state.ended_reason = 'max_duration'
                    await self.close(code=1000)
                    return
                if now - self.last_activity_at >= settings.IDLE_TIMEOUT_SECONDS:
                    self.state.ended_reason = 'idle_timeout'
                    await self.close(code=1000)
                    return
        except asyncio.CancelledError:
            raise

    # -- persistence -------------------------------------------------------- #

    async def _flush(self):
        """Flush buffered transcript/log/usage deltas onto the CallSession row.

        **Capture-and-clear happens synchronously, before the await.** The event
        loop is single-threaded up to that point, so two overlapping flushes (a
        turn's own flush and a concurrent ``_finalize()`` flush, once cancellation
        is in play) cannot both grab the same entries: whichever runs first drains
        the buffer, the other captures an empty delta and no-ops. This is what makes
        a cancelled turn safe without a lock — cancelling an async task does NOT
        stop the sync thread it spawned, so awaiting the task is not enough on its
        own to prevent a duplicate append.
        """
        if self.state is None:
            return
        transcript = list(self.state.transcript_buffer)
        logs = list(self.state.logs_buffer)
        usage = list(self.state.usage_buffer)
        if not (transcript or logs or usage):
            return
        self.state.transcript_buffer.clear()
        self.state.logs_buffer.clear()
        self.state.usage_buffer.clear()
        try:
            await database_sync_to_async(self._flush_buffers, thread_sensitive=False)(
                transcript, logs, usage)
        except Exception as exc:  # noqa: BLE001
            # The DB write is atomic (nothing committed on failure), so re-buffer
            # the delta at the front to retry on the next flush rather than lose it.
            # Log the exception TYPE only — a DB driver's error text can embed a
            # fragment of the offending value (transcript / caller number = PII),
            # so never dump str(exc) or the full traceback on this path.
            logger.error('call-session flush failed (%s); re-buffering the delta',
                         type(exc).__name__)
            self.state.transcript_buffer[:0] = transcript
            self.state.logs_buffer[:0] = logs
            self.state.usage_buffer[:0] = usage

    def _flush_buffers(self, transcript, logs, usage):
        """Sync: append the captured deltas to the row's JSON lists.

        The caller already drained and cleared the buffers, so this only touches
        the DB. ``select_for_update`` inside a transaction serializes against any
        other flush's row lock; sequence counters live on CallState, so the
        already-cleared buffers do not restart numbering.
        """
        with transaction.atomic():
            cs = (
                CallSession.objects.select_for_update()
                .filter(pk=self.state.session_id, tenant_id=self.state.tenant_id,
                        location_id=self.state.location_id)
                .first()
            )
            if cs is None:
                return
            if transcript:
                cs.transcript = (cs.transcript or []) + transcript
            if logs:
                cs.logs = (cs.logs or []) + logs
            if usage:
                cs.usage = (cs.usage or []) + usage
            cs.save(update_fields=['transcript', 'logs', 'usage', 'updated_at'])

    async def _finalize(self):
        """Guaranteed teardown — idempotent, best-effort, never raises (skill §3)."""
        if self.finalized:
            return
        self.finalized = True

        # Release the capacity slot first, so a teardown error below can never leak
        # a permanent count against the per-worker ceiling.
        if self.counted:
            type(self)._active_calls = max(0, type(self)._active_calls - 1)
            self.counted = False

        # NEVER cancel the task we are currently running inside. `_finalize()` is
        # reachable FROM the turn task (3.3's `end_call` hangs up after its goodbye
        # plays) and from the watchdog; self-cancelling makes the very next `await`
        # below raise CancelledError, which is not an `Exception` and so escapes the
        # guards — aborting finalize partway with `self.finalized` already True, so
        # no later path can ever finalize the row and it is stranded `in_progress`
        # with a dead watchdog.
        current = asyncio.current_task()
        # An armed transfer in flight OWNS the turn_task and must run to completion:
        # it still has to write CallSession.transfer and close the socket itself.
        # Cancelling it here — when a racing `stop`/`disconnect` finalize arrives from
        # a DIFFERENT task while `_execute_transfer` is awaiting the drain/redirect —
        # would deliver CancelledError, a BaseException that skips `_execute_transfer`'s
        # `except Exception` guard, and the transfer outcome JSON would be lost
        # entirely, leaving a `transferred` row with an empty transfer panel. So the
        # transfer task is not cancelled; it no-ops this `_finalize()` when it reaches
        # its own (`self.finalized` is already True), and closes the socket defensively.
        cancellable = [self.watchdog_task]
        if not self._transfer_started:
            cancellable.append(self.turn_task)
        for task in cancellable:
            if task is not None and task is not current and not task.done():
                task.cancel()

        if self.group_name:
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception as exc:  # noqa: BLE001
                logger.error('group_discard failed during finalize (%s)',
                             type(exc).__name__)

        if self.state is None or self.call_session is None:
            return  # never authorized — no row of ours to finalize

        try:
            await self._flush()
            await database_sync_to_async(self._finalize_session, thread_sensitive=False)()
        except Exception as exc:  # noqa: BLE001 — teardown must not raise
            # Type only — a DB error's text can carry a PII fragment (see _flush).
            logger.error('call finalize failed (%s)', type(exc).__name__)

    def _finalize_session(self):
        """Sync: stamp the terminal status, ended-reason, recording and waveform.

        **This is the one guaranteed-teardown write.** Every termination routes
        here through ``_finalize()`` — a clean hangup, Twilio's ``stop``, the
        watchdog's idle/max-duration close, a disabled/capacity decline, the
        post-transfer close — so an abnormal drop gets the IDENTICAL recording and
        waveform write a clean hangup gets. There is no separate "abnormal path" to
        harden because there is no separate path; that is the whole design.

        The consent gate is STRUCTURAL: ``should_record`` decides both whether a
        recording path is produced AND what ``consent_basis`` says, in one
        ``save()``, so no code path can persist a ``recording_blob`` without the
        basis that justified it landing in the same write — the application-level
        rule the model's own docstring asks for (a JSON sub-key CheckConstraint is
        not portable across MySQL and SQLite).
        """
        reason = self.state.ended_reason or 'hangup'
        status = _STATUS_BY_REASON.get(reason, CallSession.STATUS_COMPLETED)
        should_record = self.state.should_record

        # Write the audio BEFORE opening the transaction. This is real file I/O
        # (and the deferred live backend will be a network encode/upload), so
        # doing it inside the block would hold `select_for_update`'s row lock for
        # the whole write. The consent gate is untouched by the move: the gate is
        # about what lands in the DATABASE write, and the path and the basis that
        # justified it still land in the one `save()` below.
        #
        # A recorder failure must not strand the row in_progress — the status
        # stamp matters more than the audio, so it degrades to "not recorded".
        # Log the TYPE only: a storage error's text carries the path, which embeds
        # the tenant and location ids.
        blob = ''
        if should_record:
            try:
                blob = get_recording_backend().finalize(
                    self.call_session, should_record=True)
            except Exception as exc:  # noqa: BLE001 — teardown must still land
                logger.error('recording finalize failed (%s)', type(exc).__name__)
                should_record = False
        # Peaks are derived from LIVE per-frame DSP, not from the stored audio, so
        # they are genuinely partial-but-real on an early drop.
        peaks = self.waveform.finalize() if should_record else None

        with transaction.atomic():
            cs = (
                CallSession.objects.select_for_update()
                .filter(pk=self.state.session_id, tenant_id=self.state.tenant_id,
                        location_id=self.state.location_id)
                .first()
            )
            # Only advance a still-live call. Never overwrite a terminal status a
            # later sub-module (3.4's 'transferred') may already have set. Either
            # bail means the file just written will never be referenced by a row,
            # so delete it rather than leaving orphaned caller audio on disk that
            # the retention job — which walks ROWS — could never reach.
            if cs is None or cs.status != CallSession.STATUS_IN_PROGRESS:
                self._discard_recording(blob)
                return
            cs.status = status
            cs.ended_at = timezone.now()
            metadata = dict(cs.metadata or {})
            metadata['ended_reason'] = reason
            metadata['recorded'] = should_record
            metadata['consent_basis'] = self.state.consent_basis or CONSENT_NOT_RECORDED
            metadata['consent_announced'] = self.state.consent_announced
            metadata['retention_days'] = (
                settings.RECORDING_RETENTION_DAYS if should_record else 0)
            cs.metadata = metadata
            cs.recording_blob = blob
            cs.waveform_peaks = peaks
            cs.save(update_fields=['status', 'ended_at', 'metadata',
                                   'recording_blob', 'waveform_peaks', 'updated_at'])

    @staticmethod
    def _discard_recording(blob):
        """Delete a recording no row will ever point at. Never raises."""
        if not blob:
            return
        try:
            from apps.calls.storage import recording_storage

            recording_storage.delete(blob)
        except Exception as exc:  # noqa: BLE001 — teardown must not raise
            logger.error('orphan recording cleanup failed (%s)', type(exc).__name__)
