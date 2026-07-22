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
on an abnormal drop — a carrier hangup is the normal case, not the exception.
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
from django.db import transaction
from django.utils import timezone

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from apps.runtime.agent import (
    FALLBACK_LINE,
    CallState,
    ProviderBundle,
    build_open_intervals,
    build_variables,
    render_greeting,
    run_turn,
    tts_only_cost,
)
from apps.runtime.providers.audio import (
    CARRIER_SAMPLE_RATE,
    FRAME_SECONDS,
    PlaybackTracker,
    Resampler,
    STT_SAMPLE_RATE,
    iter_mulaw_frames,
    mulaw_to_pcm16,
    pcm16_to_carrier_mulaw,
)
from apps.runtime.providers.llm import get_llm_backend
from apps.runtime.providers.reliability import ProviderError
from apps.runtime.providers.stt import get_stt_backend
from apps.runtime.providers.tts import get_tts_backend
from apps.runtime.providers.tokens import verify_stream_token
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
# consumer/provider crash, is failed. 'transferred' is 3.4's to set and is
# deliberately absent here. ('error' is wired for a future fatal-error path — no
# branch sets it yet; a turn crash logs and keeps the call up rather than ending
# it — but the mapping is kept so that path lands on the right status when added.)
_STATUS_BY_REASON = {
    'hangup': CallSession.STATUS_COMPLETED,
    'max_duration': CallSession.STATUS_COMPLETED,
    'idle_timeout': CallSession.STATUS_ABANDONED,
    'disabled': CallSession.STATUS_FAILED,
    'capacity': CallSession.STATUS_FAILED,
    'error': CallSession.STATUS_FAILED,
}


class MediaStreamConsumer(AsyncWebsocketConsumer):
    """Terminates one Twilio media stream and runs the agent turn loop over it."""

    #: Per-worker-process count of live authorized calls, for the MAX_CONCURRENT_CALLS
    #: capacity gate (cost is a security control, skill §11). Touched only from the
    #: single-threaded event loop, so a plain += is safe. This bounds ONE worker;
    #: cross-worker enforcement needs a shared Redis/DB counter — 3.5's worker-health
    #: pass. A per-process ceiling is still the right first layer (and the whole
    #: ceiling on a single-process dev/Daphne run).
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

        self.turn_busy = False
        self.pending_utterance = None
        self.turn_task = None
        self.watchdog_task = None
        self.is_playing = False
        self.interruptible = True
        self.playback_tracker = None

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
        # WARNING: single-use/replay protection is a tracked deferral, not shipped
        # here. The token is signed and short-TTL (300 s) and is never logged or
        # echoed by this app, so a replay needs an already-leaked valid token; but a
        # second socket presenting the same still-valid token would authorize a
        # second stream on one CallSession. The fix (a single-use claim marker) is
        # deferred to 3.5 because it wants either a CallSession field — a migration
        # this service sub-module must not add — or a shared cache SETNX claim, a
        # design choice better made with 3.5's recording/teardown pass. Tracked in
        # .claude/tasks/todo.md.
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
                await self._play(result.reply_mulaw, interruptible=True)
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

        for task in (self.turn_task, self.watchdog_task):
            if task is not None and not task.done():
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
        """Sync: stamp the terminal status, ended_at and ended-reason on the row."""
        reason = self.state.ended_reason or 'hangup'
        status = _STATUS_BY_REASON.get(reason, CallSession.STATUS_COMPLETED)
        with transaction.atomic():
            cs = (
                CallSession.objects.select_for_update()
                .filter(pk=self.state.session_id, tenant_id=self.state.tenant_id,
                        location_id=self.state.location_id)
                .first()
            )
            if cs is None:
                return
            # Only advance a still-live call. Never overwrite a terminal status a
            # later sub-module (3.4's 'transferred') may already have set.
            if cs.status != CallSession.STATUS_IN_PROGRESS:
                return
            cs.status = status
            cs.ended_at = timezone.now()
            metadata = dict(cs.metadata or {})
            metadata['ended_reason'] = reason
            cs.metadata = metadata
            cs.save(update_fields=['status', 'ended_at', 'metadata', 'updated_at'])
