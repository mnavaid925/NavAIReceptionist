---
name: voice-agent-runtime
description: The binding contract for NavAIReceptionist's realtime voice layer — ASGI/Channels topology, the Twilio media-stream consumer lifecycle, the audio codec/resampling chain, VAD and barge-in, the deterministic greeting, the turn loop and tool-iteration cap, the tool-declaration dict schema and the {ok, data, error} envelope, the transport-agnostic apply_tool_call dispatcher, deferred transfer/hangup signals, the {{variable}} prompt-rendering rules, latency and cost budgets, provider adapters + PROVIDER_MODE fakes, and the per-turn UsageEvent emission points. Use when the user asks to add/change/debug anything under apps/*/consumers/, routing.py, config/asgi.py, apps/core/providers/, apps/core/agent/ or apps/*/webhooks.py, when a sub-module adds an LLM tool, a prompt variable, a media/live-call surface or a provider adapter, when a call has dead air / cut-off audio / a stuck transfer / a looping agent, or when the user invokes /voice-agent-runtime.
---

# voice-agent-runtime — the realtime layer contract

This skill is the **single source of truth for the realtime layer**. Every module build inherits it instead of
re-deriving it: a sub-module that adds a consumer, a tool, a prompt variable, a provider adapter or a webhook
follows the rules here, and the review agents check against them by section.

Nothing in this document is a description of existing code — the repository is greenfield and the realtime layer
is built as the modules land. Read it as **the shape the code must take**, exactly as `NavAIReceptionist-ERD.md`
is the intended data model. When code exists, the code is truth: grep before you wire.

The stack is **all-Django** — Django 5.1 + Channels/ASGI in one codebase, no separate microservice. Serve it with
`venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`. `manage.py runserver` runs the
WSGI path and **cannot serve websocket routes at all**; a "the media stream never connects" report is this, nine
times out of ten.

## Triggers
- Work under `apps/<slug>/consumers/`, `apps/<slug>/routing.py`, `config/asgi.py`, `apps/core/providers/`,
  `apps/core/agent/`, `apps/<slug>/webhooks.py`, `apps/core/compliance.py`.
- A sub-module adds an **LLM tool**, a **prompt variable**, a **live-call surface**, a **provider adapter method**,
  or a **telephony webhook**.
- Symptom reports from a call: dead air, clipped first syllable, the agent talking over the caller, the agent
  cutting itself off, a transfer that drops mid-sentence, a looping agent, runaway spend, audio stuttering for
  *every* concurrent call on a worker.
- The user invokes `/voice-agent-runtime`.

## When NOT to use
- CRUD pages, filters, badges and templates → `/frontend-design`.
- Building the next sub-module end-to-end → `/next-module` (it calls back into this skill at its realtime step).
- Pure data-model questions (what FKs exist, what is derived) → `NavAIReceptionist-ERD.md`.

---

## 1. ASGI topology

```
Caller ──PSTN──▶ Twilio ──POST /telephony/voice/──▶ Django (ASGI, HTTP path)
                                                     └─ returns TwiML <Connect><Stream url="wss://…">
       ◀── μ-law audio ──▶ Twilio ──WSS /ws/media-stream/──▶ Channels consumer (async)
                                                             ├─ apps/core/providers/  (telephony/STT/TTS/LLM)
                                                             ├─ apps/core/agent/      (prompt, state, dispatcher)
                                                             └─ core.Interaction + core.InteractionEvent + core.UsageEvent
Staff UI ──WSS /ws/live-call/<interaction_id>/──▶ live-call consumer (read-only fan-out)
```

- `config/asgi.py` is a `ProtocolTypeRouter`: `"http"` → `get_asgi_application()`, `"websocket"` → the auth /
  origin middleware stack → `URLRouter(websocket_urlpatterns)`.
- `config/settings.py` sets `ASGI_APPLICATION = "config.asgi.application"` and `CHANNEL_LAYERS` (Redis via
  `REDIS_URL` in dev/prod; `channels.layers.InMemoryChannelLayer` in `config/settings_test.py`).
- Each app contributes `apps/<slug>/routing.py` (flat at the app root, never a package). `config/asgi.py`
  concatenates them. **Websocket routes resolve first-match-wins, exactly like `urls.py`** — a greedy
  `<str:token>` media-stream route placed above a literal route swallows it. Check any new pattern against the
  whole concatenated list, not just the file you are editing.
- Consumers live at `apps/<slug>/consumers/<SubModule>/<Entity>.py` — the fifth backend layer, same
  sub-module → entity shape as `models`/`forms`/`views`/`urls`, with the same `__init__.py` re-export rule.
  A consumer that is not re-exported fails at route-import time, not at connect time.
- Two websocket surfaces, and they are **not** the same thing:
  - **the carrier media stream** — authenticated by a signed, short-TTL stream token minted when the voice
    webhook returns its TwiML; there is no session and no user;
  - **the staff live-call surface** — authenticated by the Django session, authorized against
    `interaction.tenant_id == user.tenant_id`, read-only, never carries raw audio to the browser.

## 2. Webhook ingress (the HTTP half)

The voice webhook is the only place the tenant is discovered from scratch. Everything downstream inherits it.

1. **Resolve the dialed number first.** `To`/`Called` → `core.PhoneNumber.e164` (globally unique across all
   tenants — that is exactly why) → tenant, agent, published `core.AgentVersion`. An unmapped or disabled number
   gets a polite spoken decline and a hangup, and never reaches the stream.
2. **Verify `X-Twilio-Signature` before any side effect** — HMAC-SHA1 over the exact public URL plus the sorted
   POST params, base64, `hmac.compare_digest`. Use the resolving tenant's auth token (per-tenant credentials are
   decrypted from the encrypted field; the platform token from `.env` is the fallback). Invalid or missing →
   `403`, zero writes. The public URL must equal `TWILIO_WEBHOOK_BASE_URL` + the path exactly; a tunnel URL that
   drifts from the setting fails verification and looks like a broken agent.
3. `@csrf_exempt` is correct here **only** because signature verification replaces it. Never one without the other.
4. **Idempotency is not optional** — providers redeliver. Unique-constrain `(provider, provider_sid, event_type)`
   and let the duplicate lose the race. A redelivery must not create a second `core.Interaction`, a second
   `core.UsageEvent`, a second booking or a second SMS.
5. Return the provider's expected body (TwiML `application/xml`, or a bare `200`/`204`) — **never a redirect**.
   This is the deliberate exception to POST-redirect-GET.
6. The TwiML carries the stream URL plus opaque custom parameters (the stream token, and the interaction id once
   the row exists). It never carries `tenant_id` — see §3.
7. Webhook handlers live in `apps/<slug>/webhooks.py` (flat), are rate-limited, and log **no** caller numbers,
   transcript text or tool arguments at INFO.

## 3. Consumer lifecycle

One consumer instance = one call. It owns all per-call state: VAD counters, resampler state, playback
bookkeeping, the turn task, the deferred-transport flags.

**`connect()` — authorize, then accept. Never accept-then-check.**
- `@login_required` does not exist for consumers. Validate explicitly:
  - media stream: verify the signed stream token (short TTL, single-interaction scope) and resolve
    tenant + agent version + interaction from it;
  - live-call surface: `self.scope["user"].is_authenticated` and the interaction's tenant matches the user's.
- **Never trust `tenant_id` or `interaction_id` taken from the websocket URL.** That is a cross-tenant
  vulnerability, not a shortcut. Resolve from the verified token or the interaction row.
- Reject with an explicit close code (`4401` unauthorized, `4403` forbidden, `4404` unknown interaction).
- Join **tenant-namespaced** groups only: `t{tenant_id}:call:{interaction_id}`. An un-namespaced group name lets
  tenant A subscribe to tenant B's live call.

**`receive()` — the frame loop.** Twilio sends JSON text frames: `connected`, `start`, `media`, `stop`, `mark`.
- `start` carries `streamSid`, `callSid` and the custom parameters. Re-resolve and re-check that the number is
  still served and the agent still enabled before serving any audio; a stale token must not get a call.
- `media.payload` is base64 μ-law 8 kHz — decode, resample, meter, feed VAD (§4, §5).
- `stop` finalizes. `mark` is acknowledgement bookkeeping.
- A malformed frame is skipped, not fatal. **Wrap the loop body so one bad frame cannot kill the call**, and log
  the exception without the payload.
- Frame handling must stay cheap. A completed utterance is dispatched as a **background task**
  (`asyncio.create_task`) so LLM and tool work never stalls the next inbound frame. Guard with a `turn_busy` flag;
  an utterance captured while a turn is in flight goes into a **single-slot pending queue** and is processed when
  the turn ends — dropping it loses the caller's correction, queueing them all replays a backlog into a dead call.

**`disconnect()` — guaranteed teardown, best-effort, never raises.**
- Cancel the outbound playback task and the in-flight turn task.
- Close the provider sessions.
- Assemble and upload the recording **in a thread** (`asyncio.to_thread`) — WAV assembly on a long call is
  CPU-heavy and would pace every other call on the worker.
- Flush buffered `core.InteractionEvent` rows, stamp `ended_at` / `duration_seconds` / `status` / ended-reason on
  `core.Interaction`, emit the final `core.UsageEvent` rows, enqueue post-call analysis.
- Teardown runs on abnormal termination too — a carrier drop is the normal case, not the exception.

**Async discipline (the single most expensive bug class in this product).**
- No sync ORM, no `requests`/`httpx.Client`, no `time.sleep`, no file I/O, no blocking SDK call inside an
  `async def`. Use `database_sync_to_async`, `sync_to_async(thread_sensitive=False)`, `asyncio.to_thread`, or an
  async client.
- One blocked coroutine freezes audio for **every concurrent call on that worker**, not just the offending one.
  A `SynchronousOnlyOperation` in a test is a failure, never a flake.

## 4. Audio chain

| Leg | Format | Where it converts |
|---|---|---|
| Carrier → us | base64 μ-law (G.711) **8 kHz** mono, 20 ms frames (160 bytes) | decode → PCM16 8 kHz → resample → **PCM16 16 kHz** for VAD/STT |
| Us → carrier | PCM16 at the synth rate (**24 kHz** for native-audio models, 16 kHz otherwise) | resample → 8 kHz → μ-law encode → slice into 20 ms frames |

- Keep the codec/resampling helpers in one module (`apps/core/providers/audio.py`) — never inline in a consumer.
- **Thread the inbound resampler state across frames.** A fresh state per frame produces an audible click at every
  20 ms boundary. Outbound is the opposite: each synthesized blob is independent, so it gets a fresh state.
- **Pace outbound frames** — send one 20 ms frame, `await asyncio.sleep(0.020)`, repeat. Dumping the whole blob at
  once fills the carrier buffer and makes the audio uncancellable, which breaks barge-in.
- **Account only for audio actually played.** Barge-in cancels the playback task mid-blob; record the played
  prefix (cut proportionally to frames sent, on an even byte boundary) into the recording. Recording the whole
  blob makes the agent channel run ahead of the caller wall-clock and ruins QA playback and diarization.
- Recordings are written as two channels (caller / agent) so review and diarization are clean.

## 5. VAD, barge-in and the echo guard

Energy VAD with tuned, **named constants in one module** — never magic numbers scattered across a consumer:
energy threshold, minimum speech duration, end-of-speech silence, maximum utterance length, echo cooldown,
barge-in grace, barge-in sustain.

- **Utterance end** = speech seen for at least the minimum duration **and** silence for the end-silence window,
  or the hard utterance cap fires.
- **Pre-roll buffering**: keep a bounded window of pre-speech audio so the first syllable is never clipped, and
  trim it while idle so a silent line cannot grow the buffer without bound.
- **Barge-in fires only on sustained speech** past a grace window after playback starts. A cough, a click or a
  line pop must not cut the agent off. When it fires: cancel the outbound task, drop the queued audio, skip the
  echo cooldown, and treat the caller's speech as the next utterance.
- **Echo guard**: suppress listening while the agent is playing and for a short cooldown after. Without it the
  agent's own audio arrives back as caller speech and the call devolves into the agent interviewing itself.
- Reset all listening state whenever playback starts, so the agent's own audio is never accumulated as an
  utterance.
- **Idle behaviour**: after silence, speak a configured idle prompt; after a bounded no-response period
  (`IDLE_TIMEOUT_SECONDS`, default 45 s), end the call with an explicit ended-reason.

## 6. The greeting is deterministic

The opener is rendered from the agent version's configured greeting with `{{variable}}` substitution (§10) and
**never waits on an LLM** — zero tokens, zero provider round-trips, first audio immediate. A blank configured
greeting falls back to a short built-in line. The greeting is played **non-interruptible**: it must reach the
caller in full.

## 7. The turn loop and the iteration cap

```
utterance ─▶ STT ─▶ history.append(user) ─▶ ┌──────────────────────────────┐
                                            │ LLM.generate(history, system)│◀──┐
                                            └──────────────┬───────────────┘   │
                                       tool calls? ────yes──▶ apply_tool_call ─┘  (bounded)
                                            │no                       (results appended as a tool-role turn)
                                            ▼
                                     assistant text ─▶ deferred-transport check ─▶ TTS ─▶ paced frames
```

- **Cap tool iterations per turn** at `MAX_TOOL_ITERATIONS` (default **4**). When the cap is hit, speak a fallback
  line — never leave the caller in silence and never loop. Raising the cap needs a written justification.
- **Multiple tool calls in one turn are normal.** Apply them all, each with its own precondition guard, and append
  every result before the next model call.
- **Filler speech** only when a genuinely slow lookup is *starting* ("let me check that for you") — never as a
  standalone stall, never after the answer is already known.
- **Trim or summarize history on long calls.** History is resent every turn, so an unbounded list makes input
  tokens — and therefore latency and cost — grow quadratically. Flag any turn loop with no trimming policy.
- **Refresh time-sensitive variables every turn** (§10). Computing `current_date`/`current_time` once at call
  start leaves a long call, or a midnight crossing, quoting yesterday.
- The blocking LLM SDK call goes through `asyncio.to_thread` (or an async client) — see §3.
- Record per-turn STT seconds, token counts, TTS characters and model name as the turn completes (§13).

## 8. Tools: declarations, dispatcher, envelope

**Declarations are plain dicts**, provider-agnostic, in `apps/core/agent/tools.py`:

```python
{
    "name": "get_open_slots",
    "description": "Return open appointment slots …  Pass each result's slot_token unchanged to book_appointment.",
    "parameters": {"type": "object", "properties": {...}, "required": [...]},
}
```

The provider adapter converts them to the SDK's tool format — the declaration list itself imports no SDK, so it
can be asserted in tests without one. **Every declared tool must have a dispatcher branch**; a declared-but-
undispatched tool is a silent runtime failure, and the edit hook checks for it.

**One dispatcher, transport-agnostic:**

```python
async def apply_tool_call(state, name: str, args: dict) -> dict:
```

- The same function serves the turn-based path and the realtime speech-to-speech path. **Trace every new tool
  through both** — divergent argument coercion, divergent `ok` computation and divergent cost accounting between
  the two paths is the top regression risk in this layer.
- **Server owns identity; the model owns wording.** `tenant_id`, `contact_id` and `interaction_id` come from
  server-side session state and are **never tool parameters**. Any ID the model *does* supply
  (`appointment_id`, `slot_token`) is authorized server-side against the tenant **and** the identified contact.
  This is an IDOR with an LLM in the middle; treat it as one.
- Caller speech, contact names, custom fields and knowledge-base text are **untrusted input flowing into the model
  context**. A tool must never widen authority because the prompt or the caller asked it to.
- **Opaque signed slot tokens.** The availability tool returns one `slot_token` per slot — a signed, short-TTL
  blob encoding start / resource / service / tenant — not semantic fields the model must echo verbatim. The
  backend verifies the slot was actually offered *in this interaction*. Verbatim-echo drift on slot fields is the
  single most common booking-failure class; the token removes it.
- **One name per concept, everywhere.** A field is `date_of_birth` in state, in the tool schema and in the
  response — not `dob` in one and `birthdate` in another.
- **Never announce success before the write returns.** "You're all booked" with no `core.Appointment` row is the
  worst failure this product can produce.
- **Never re-check availability after the caller confirms.** Re-offering traps the caller in an endless offer
  loop; confirm against the token you already hold.

**One envelope, every tool, no exceptions:**

```json
{"ok": true, "data": {"...": "..."}, "error": null}
```
```json
{"ok": false, "data": null, "error": {"code": "slot_unavailable", "message": "That time was just booked."}}
```

`error.code` is **always lower_snake_case**, drawn from one closed set — `not_found`, `invalid_argument`,
`slot_unavailable`, `slot_expired`, `not_permitted`, `provider_error`, `rate_limited`, `internal_error`. The
human-readable string goes in `message`; the code is what callers branch on, so it is never prose and never
re-cased per tool.

Never prose, never a bare `{"id": ...}`, never a different success key per tool. `ok` is what the event recorder,
the diagnostics page and the "did it actually succeed" rules key off.

Enablement: a tool is offered to the model only when its name is in `core.AgentVersion.enabled_tools`. **The
prompt must never name a tool or a tool parameter**, and must never promise a capability whose tool is disabled
for that tenant.

## 9. Deferred transport actions

Transfer, hangup and any other transport-mutating tool **do not act inside the dispatcher**. They set a deferred
signal on session state and return a short acknowledgement. The transport executes it after the turn's audio has
played.

The sequence, in order, is load-bearing:

1. Dispatcher sets `state.pending_transfer = "human" | "spanish" | …` and returns `{"ok": true, …}`.
2. The turn ends. The transport checks the signal **before** speaking the model's reply — the model's
   "connecting you now" line is usually misleading by then and must be suppressed if the transport speaks instead.
3. **Set the single-fire guard before any `await`**, so a concurrent turn cannot double-execute the transfer.
4. Cancel queued playback, then speak the fixed handoff line **non-interruptible**.
5. **Wait a short drain interval (~0.6 s)** so the carrier jitter buffer empties before the redirect. Skip it and
   the caller hears the handoff line cut off mid-word.
6. Place the redirect through the telephony adapter. The destination is **always** the tenant-configured E.164
   number — never anything derived from caller speech. Validate it as E.164 and validate any provider SID shape
   before interpolating it into a REST URL. Restrict destinations to an allow-list; unrestricted dial-out is toll
   fraud waiting to happen.
7. Gate a human transfer on the tenant's configured working hours in the **tenant's** timezone; speak the
   off-hours notice **once** and keep serving the caller with the agent.
8. Transfer wanted but disabled or misconfigured → say so once, clear the pending signal so it does not retry
   every turn, and keep helping.
9. Redirect failed → apologize once, keep the guard set (do not retry a configuration bug on every turn), keep
   serving.
10. Record the outcome (`connected` / `failed` / `off_hours` / `unavailable`) as an `InteractionEvent` with the
    destination and reason, so the call detail page can show where a bridge broke.

An **explicit end-call tool** ends the call deterministically for voicemail, do-not-call and wrong-number
outcomes — waiting on a silence timeout burns minutes and looks broken.

## 10. Prompt and variable rendering

- Placeholders are `{{key}}`, whitespace-tolerant (`{{ key }}` resolves identically). Regex:
  `\{\{\s*([\w.\-]+)\s*\}\}`.
- **A missing key renders as an empty string** — never leak a raw `{{placeholder}}` to a caller.
- Variables merge in one direction: the agent version's configured `variables` first, then the **runtime vars
  computed per call/turn, which always win**.
- Runtime var set (extend it here, in one place, when a module adds one): `from_e164`, `to_e164`, `tenant_name`,
  `location_id`, `location_name`, `location_address`, `is_open_now`, `current_date`, `current_time`,
  `caller_display_name`, `agent_name`.
- **`is_open_now` is computed server-side** from `core.BusinessHours` + `core.HoursException` and injected as
  the literal string `"yes"` / `"no"`. The model must never derive open/closed from raw hours plus a clock.
  The name is `is_open_now` everywhere — in this skill, in `NavAIReceptionist-ERD.md` and in `realtime-reviewer`.
  A missing key renders as an empty string (see above), so a spelling drift here fails **silently** on a live call.
- **`current_date` / `current_time` are computed in the tenant's/contact's timezone, never the server's**, and
  **recomputed each turn**. Without a date anchor the model mislabels today's slots as tomorrow and stalls booking.
- **Use portable strftime.** `%-d` and `%-I` are unsupported on the Windows dev host — build the day number and
  strip a leading zero explicitly.
- **One source of truth for the default prompt.** A `PromptTemplate` row (or a null on the version meaning
  "inherit the current default") — never a default string duplicated across modules to drift apart.
- The rendered system prompt is composed once per turn from the published `core.AgentVersion.prompt_body`. A
  published version is **immutable**: to change wording you publish a new version. Every `core.Interaction` FKs
  the exact version it ran, which is what makes "which prompt said that?" answerable.

## 11. Latency and cost budgets

| Budget | Value |
|---|---|
| First audio (greeting) | immediate — deterministic, **0 LLM tokens** |
| Turn latency | ≤ **1.5 s** p50, ≤ **3 s** p95, measured utterance-end → first outbound frame |
| Tool iterations per turn | **4** (`MAX_TOOL_ITERATIONS`) |
| No-audio idle timeout | **45 s** (`IDLE_TIMEOUT_SECONDS`) |
| Hard max call duration | tenant-configurable, default **15 min** (`MAX_CALL_SECONDS`) |
| Provider call | explicit timeout + bounded retry on every telephony/STT/TTS/LLM call |
| Failure mode | a spoken fallback, **never dead air** |

- Count the serial round-trips a turn makes (STT → LLM → tool → LLM → TTS). Adding an unnecessary serial hop, or
  a tool that runs N queries where one `select_related` would do, is a latency defect — review it as one.
- Attribute latency per stage (ASR / LLM / tool / TTS) and record it as `runtime.TurnMetric` rows keyed on
  `(interaction, interaction_event)` — or in the `duration_ms` / `payload` of the turn `core.InteractionEvent`.
  Never add a latency column to `core.Interaction`: Module 4 writes the spine, it does not extend it.
- **Cost is a security control.** Per-tenant spend caps (`TENANT_SPEND_CAP_DEFAULT`), per-call duration and turn
  ceilings, per-caller rate limiting and destination allow-lists are what stop a prompt-injected or looping agent
  from burning unbounded provider spend.

## 12. Provider adapters, `PROVIDER_MODE` and fakes

Every external dependency sits behind an adapter in `apps/core/providers/` — telephony, STT, TTS, LLM, storage.
Consumers and tools call the adapter interface, never an SDK directly.

**Ownership.** The adapters are **Module 0 foundation**: Module 0 owns the adapter interfaces, the fakes and
`PROVIDER_MODE` resolution, in `apps/core/providers/`. **Module 4 owns the realtime orchestration that calls
them** — the consumer, the turn loop, VAD/barge-in and the audio chain. Module 4 does not own the adapters;
Module 1 (telephony) needs them before Module 4 exists.

- Interfaces are narrow and async: `telephony.place_call / redirect_call / hangup / send_sms`,
  `stt.transcribe(pcm, rate)`, `tts.synthesize(text) -> (pcm, rate)`,
  `llm.generate(history, system, tools) -> (text, tool_calls, usage)`.
- **Every adapter ships its fake in the same pass.** The fake is a real implementation of the interface —
  deterministic synthetic audio, canned transcripts, scripted tool calls — not a mock. Tests and seeders run
  against the fakes so the **adapter contract itself** is exercised; SDK-level mocking hides contract drift.
- `PROVIDER_MODE` ∈ `fake | sandbox | live`, resolved in `apps/core/providers/`. The rules, in this direction:
  1. **`fake` is the default** for dev, tests and seeders.
  2. When the mode is **not** `live`, adapters resolve to the fake/sandbox implementation and **must never reach a
     real provider** — no real call placed, no real SMS sent, no billable API call. Non-`live` is the safe path,
     not a failure path; it must run cleanly with no credentials at all.
  3. The **live** adapter refuses to initialize unless `PROVIDER_MODE == "live"`, and live mode additionally
     requires real credentials to be present — **missing credentials in live mode is the hard failure**.
  4. `on_stop.py` warns loudly if `PROVIDER_MODE=live` is set in a dev environment.

  A seeder, test, fixture, management command or `DEBUG=True` path that can reach a live provider is a defect, not
  a configuration choice.
- Credentials come from `.env` (platform) or a per-tenant encrypted field (tenant-owned Twilio accounts). Never in
  `Meta.fields`, never in `messages.*`, never logged, never rendered. Display as prefix + hash; rotate through a
  write-only flow with a pop-once reveal.
- Build TTS lazily where a path may not need it, latch a failed build so it is not retried every line, and let a
  missing provider skip the spoken line rather than raise — the flow (a transfer redirect) still has to proceed.

## 13. Metering: where `core.UsageEvent` rows come from

Every billable unit is an appended `core.UsageEvent`. **Nothing stores a running total** — minutes used, spend,
credit balance and call counts are `aggregate()` results.

| Emission point | Categories |
|---|---|
| Per turn, as the turn completes | `stt_second`, `llm_input_token`, `llm_output_token`, `tts_character` |
| On call finalize | `voice_minute` (from `duration_seconds`) |
| On SMS send / receive | `sms_segment` |
| Nightly / on storage write | `number_rental`, `recording_storage_gb_day` |

- **Every per-turn row carries the `core.InteractionEvent` it belongs to.** Set `UsageEvent.interaction_event` to
  the turn's event row on every `stt_second`, `llm_input_token`, `llm_output_token` and `tts_character` row — write
  the turn event first, then the usage rows against it. This FK is the *only* thing that makes per-turn cost
  derivable (`UsageEvent.objects.filter(interaction=i).values('interaction_event').annotate(...)`), and catalog
  11.2's turn-level cost column is built on it. Call-level and non-call rows (`voice_minute`, `number_rental`,
  `recording_storage_gb_day`) leave it null. A per-turn row emitted with a null `interaction_event` is a defect:
  it silently drops that turn out of the breakdown, and there is no second cost table to recover it from.
- Record **deltas per turn**, never by re-aggregating the whole call each turn.
- Every row carries `provider` + `provider_ref` so a retry can be deduplicated and a provider invoice reconciled.
- The same webhook delivered twice must produce **one** set of rows — the idempotency key in §2 is what enforces it.
- `UsageEvent` is append-only: corrections are compensating rows, never an UPDATE.

## 14. What the runtime writes to the spine

- **One `core.Interaction` per call** (`CALL-00001`), created at ring, carrying tenant, phone number, agent
  version, provider SID (unique), status, timestamps, duration and the ended-reason.
- **`core.InteractionEvent` rows, append-only, monotonic `sequence`** — `ringing`, `answered`, `turn_user`,
  `turn_agent`, `dtmf`, `tool_call`, `tool_result`, `transfer_requested`, `transfer_completed`,
  `recording_available`, `barge_in`, `provider_webhook`, `error`, `hangup`. Transcript, tool-call audit and
  provider event log are **all this one table** — three tables would be three answers to "what happened on the
  call". Interim/partial recognitions set `is_partial`.
- **There is no `core.Transcript` model and no `core.ToolCall` model.** "The transcript" is a *view over
  `core.InteractionEvent`* — the turn rows of one interaction, ordered by `sequence` — and the tool-call trace is
  the same table filtered to `tool_call` / `tool_result`. A module-owned `Transcript`, `TranscriptTurn`,
  `ToolCall`, `Message`, `CallEvent` or `ActivityLog` table is an **Invariant 2** violation: three tables would be
  three answers to "what happened on the call".
- **`core.Recording`** with a `consent_basis` and a `retention_until`. A recording without a recorded consent
  basis must not be creatable; in two-party jurisdictions the announcement must have been played, and the
  `InteractionEvent` proving it is the evidence.
- Callers are `core.Contact` + `core.ContactRole` — the runtime never creates a `Caller` or `Lead` table, and
  never stores a raw phone string on a module model.
- **The caller is not necessarily the booking subject.** `Interaction.contact` is who called;
  `Interaction.subject_contact` is who the appointment is for. Conflating them books the wrong person.
- Outbound — every dial, SMS and voicemail drop — goes through the one gate,
  `apps/core/compliance.check_outbound_allowed(contact, channel, now)`, which reads consent, suppression and quiet
  hours **in the contact's timezone**. No second DNC list, no inline `if not contact.do_not_call` anywhere.

## 15. Observability — a service sub-module still ships a surface

The realtime layer has no CRUD pages, but "no templates" never means "nothing to look at". Every realtime
sub-module ships at least one observable surface, or it is not done:

- a **diagnostics page** (`templates/runtime/diagnostics.html`): per-call latency breakdown by stage,
  ended-reason codes, runtime errors surfaced on the call detail page rather than buried in server logs, transfer
  outcome and where a failed bridge broke, active-call count and worker health;
- a **settings form** for the tenant-tunable budgets (max duration, idle timeout, tool cap, spend cap);
- or a **management command** that exercises the path end-to-end under `PROVIDER_MODE=fake`.

Plus a `LIVE_LINKS["N.M"]` entry pointing at that surface, tenant scoping on every query, migrations, an
idempotent seeder if it adds data, and tests.

## 16. Tests for this layer

- `pytest-asyncio` with `asyncio_mode = auto`; `channels.testing.WebsocketCommunicator` against
  `config.asgi.application`; `InMemoryChannelLayer` and `PROVIDER_MODE = "fake"` in `config/settings_test.py`.
  DB-touching async tests use `@pytest.mark.django_db(transaction=True)`.
- **Consumer:** accepted with a valid stream token; **rejected** with no auth and with another tenant's
  interaction id; group name is tenant-namespaced; a synthetic audio frame round-trips; `disconnect()` finalizes
  the interaction; a `SynchronousOnlyOperation` is a failure, never a flake.
- **Webhook:** valid signature → 200 + expected body; invalid/absent → 403 with **zero** side effects (assert row
  counts unchanged); duplicate delivery → exactly one `Interaction` / `UsageEvent`; malformed payload → 4xx,
  never 500.
- **Dispatcher:** declarations are plain dicts asserted by name; a missing identity precondition returns
  `{"ok": false, …}` and writes nothing; a model-supplied `appointment_id` from another tenant is rejected; a
  `slot_token` not offered in this interaction is rejected; **every tool is tested through both runtime paths**.
- **Compliance:** suppressed contact → refused; quiet hours in the contact's timezone → refused, with time frozen
  and both sides of the boundary asserted; a STOP keyword creates a suppression entry and the next send is refused.
- **Metering:** a call produces the expected usage rows; the derived aggregate matches them; a spend cap blocks
  the next outbound.

## 17. Adding to this layer — the checklist

Adding a **tool**: declaration dict → dispatcher branch → `{ok, data, error}` envelope → identity from server
state → `enabled_tools` flag → prompt wording that names no tool → tests through **both** paths → the
`UsageEvent` and `InteractionEvent` rows it produces → update this skill.

Adding a **consumer**: `consumers/<SubModule>/<Entity>.py` → `__init__.py` re-export → `routing.py` entry checked
against the whole concatenated route list → `connect()` authorization → tenant-namespaced group →
`database_sync_to_async` on every ORM touch → `disconnect()` teardown → `WebsocketCommunicator` accept/reject
tests.

Adding a **provider method**: interface method → live implementation → **fake implementation in the same pass** →
timeout + bounded retry → the live implementation refuses to initialize unless `PROVIDER_MODE == "live"`, and every
non-`live` mode resolves to the fake → the usage categories it emits.

Adding a **prompt variable**: add it to the runtime var set in §10 → compute it in the tenant's timezone → refresh
it per turn if it is time-sensitive → missing renders empty → document it here.

When any of this changes in code, **update this skill in the same change**, and commit it on its own:
`git add '.claude/skills/voice-agent-runtime/SKILL.md'; git commit -m 'docs(runtime): …'`. One file per commit,
PowerShell `;` never `&&`, and **never `git push`**.
