---
name: voice-agent-runtime
description: The binding contract for NavAIReceptionist's realtime voice layer — ASGI/Channels topology, the Twilio media-stream consumer lifecycle, the audio codec/resampling chain, VAD and barge-in, the deterministic greeting, the turn loop and tool-iteration cap, the tool-declaration dict schema and the {ok, data, error} envelope, the transport-agnostic apply_tool_call dispatcher, the deferred cold-transfer flow, the {{variable}} prompt-rendering rules, latency and cost budgets, provider adapters + PROVIDER_MODE fakes, and what the runtime writes to CallSession. Use when the user asks to add/change/debug anything under apps/runtime/, routing.py, config/asgi.py, apps/runtime/providers/, apps/runtime/agent/ or apps/runtime/webhooks.py, when a sub-module adds an LLM tool, a prompt variable, a media/live-call surface or a provider adapter, when a call has dead air / cut-off audio / a stuck transfer / a looping agent, or when the user invokes /voice-agent-runtime.
---

# voice-agent-runtime — the realtime layer contract

This skill is the **single source of truth for the realtime layer**. Every module build inherits it instead of
re-deriving it: a sub-module that adds a consumer, a tool, a prompt variable, a provider adapter or a webhook
follows the rules here, and the review agents check against them by section.

Nothing in this document is a description of existing code — **the repository is greenfield and there is no `apps/`
directory**. Read it as **the shape the code must take**. When code exists, the code is truth: grep before you wire.

The product is **inbound only**. A business (tenant) has multiple **locations**; each location has its own Twilio
number and its own `agents.AgentSetting` row. The agent answers, books appointments, transfers to a human when
asked, and logs the call. This layer only ever answers a call that came in; it never originates one.

The stack is **all-Django** — Django 4.2 LTS + Channels/ASGI in one codebase, no separate microservice. Serve it with
`venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`. `manage.py runserver` runs the
WSGI path and **cannot serve websocket routes at all**; a "the media stream never connects" report is this, nine
times out of ten.

## Triggers
- Work under `apps/runtime/consumers/`, `apps/runtime/routing.py`, `config/asgi.py`, `apps/runtime/providers/`,
  `apps/runtime/agent/`, `apps/runtime/webhooks.py`.
- A sub-module adds an **LLM tool**, a **prompt variable**, a **live-call surface**, a **provider adapter method**,
  or a **Twilio webhook**.
- Symptom reports from a call: dead air, clipped first syllable, the agent talking over the caller, the agent
  cutting itself off, a transfer that drops mid-sentence, a looping agent, runaway spend, audio stuttering for
  *every* concurrent call on a worker.
- The user invokes `/voice-agent-runtime`.

## When NOT to use
- CRUD pages, filters, badges and templates → `/frontend-design`.
- Building the next sub-module end-to-end → `/next-module` (it calls back into this skill at its realtime step).
- Pure data-model questions → `scope-v2.md` §S4.

---

## 1. ASGI topology

```
Caller ──PSTN──▶ Twilio ──POST /runtime/voice/──▶ Django (ASGI, HTTP path)
                                                   └─ returns TwiML <Connect><Stream url="wss://…">
       ◀── μ-law audio ──▶ Twilio ──WSS /ws/media-stream/──▶ Channels consumer (async)
                                                             ├─ apps/runtime/providers/ (telephony/STT/TTS/LLM)
                                                             ├─ apps/runtime/agent/     (prompt, state, dispatcher)
                                                             └─ calls.CallSession
Staff UI ──WSS /ws/live-call/<session_id>/──▶ live-call consumer (read-only fan-out)
```

- `config/asgi.py` is a `ProtocolTypeRouter`: `"http"` → `get_asgi_application()`, `"websocket"` → the auth /
  origin middleware stack → `URLRouter(websocket_urlpatterns)`.
- `config/settings.py` sets `ASGI_APPLICATION = "config.asgi.application"` and `CHANNEL_LAYERS` (Redis via
  `REDIS_URL` in dev/prod; `channels.layers.InMemoryChannelLayer` in `config/settings_test.py`).
- `apps/runtime/routing.py` is flat at the app root, never a package. **Websocket routes resolve first-match-wins,
  exactly like `urls.py`** — a greedy `<str:token>` media-stream route placed above a literal route swallows it.
  Check any new pattern against the whole concatenated list, not just the file you are editing.
- Consumers live at `apps/runtime/consumers/<SubModule>/<Entity>.py` — the fifth backend layer, same
  sub-module → entity shape as `models`/`forms`/`views`/`urls`, with the same `__init__.py` re-export rule.
  A consumer that is not re-exported fails at route-import time, not at connect time.
- Two websocket surfaces, and they are **not** the same thing:
  - **the carrier media stream** — authenticated by a signed, short-TTL stream token minted when the voice
    webhook returns its TwiML; there is no session and no user;
  - **the staff live-call surface** — authenticated by the Django session, authorized against the session's
    tenant **and** location, read-only, never carries raw audio to the browser.

## 2. Webhook ingress (the HTTP half)

The voice webhook is the only place tenant and location are discovered from scratch. Everything downstream
inherits them.

1. **Resolve the dialed number first.** `To`/`Called` → `agents.AgentSetting.inbound_phone_number` (globally
   unique across all tenants — that is exactly why) → **tenant + location + agent config in one lookup**. An
   unmapped or disabled (`enabled=False`) number gets a polite spoken decline and a hangup, and never reaches the
   stream.
2. **Verify `X-Twilio-Signature` before any side effect** — HMAC-SHA1 over the exact public URL plus the sorted
   POST params, base64, `hmac.compare_digest`. Use **that resolved row's** `twilio_account_sid` /
   `twilio_auth_token` (decrypted from the encrypted field), falling back to the platform token in `.env` only if
   the location has none. Invalid or missing → `403`, zero writes. The public URL must equal
   `TWILIO_WEBHOOK_BASE_URL` + the path exactly; a tunnel URL that drifts from the setting fails verification and
   looks like a broken agent.
3. `@csrf_exempt` is correct here **only** because signature verification replaces it. Never one without the other.
4. **Idempotency is not optional** — Twilio redelivers. Unique-constrain `CallSession.provider_call_sid` and let
   the duplicate lose the race. A redelivery must not create a second `CallSession` or a second booking.
5. Return the provider's expected body (TwiML `application/xml`, or a bare `200`/`204`) — **never a redirect**.
   This is the deliberate exception to POST-redirect-GET.
6. The TwiML carries the stream URL plus opaque custom parameters (the stream token, and the session id once the
   row exists). It never carries `tenant_id` or `location_id` — see §3.
7. Webhook handlers live in `apps/runtime/webhooks.py` (flat), are rate-limited, and log **no** caller numbers,
   transcript text or tool arguments at INFO.

## 3. Consumer lifecycle

One consumer instance = one call. It owns all per-call state: VAD counters, resampler state, playback
bookkeeping, the turn task, the deferred-transport flags.

**`connect()` — authorize, then accept. Never accept-then-check.**
- `@login_required` does not exist for consumers. Validate explicitly:
  - media stream: verify the signed stream token (short TTL, single-session scope) and resolve
    tenant + location + `AgentSetting` + `CallSession` from it;
  - live-call surface: `self.scope["user"].is_authenticated`, the session's tenant matches the user's, **and** the
    session's location is one the user is assigned to via `accounts.UserLocation`.
- **Never trust `tenant_id`, `location_id` or `session_id` taken from the websocket URL.** That is a cross-tenant —
  and cross-location — vulnerability, not a shortcut. Resolve from the verified token or the `CallSession` row.
- Reject with an explicit close code (`4401` unauthorized, `4403` forbidden, `4404` unknown session).
- Join **tenant-namespaced** groups only: `t{tenant_id}:call:{session_id}`. An un-namespaced group name lets
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
- Flush the buffered transcript and log entries onto the `CallSession` row, stamp `ended_at` / `status`, write
  `waveform_peaks` and `recording_blob`, enqueue post-call analysis into `CallSession.analysis`.
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

- Keep the codec/resampling helpers in one module (`apps/runtime/providers/audio.py`) — never inline in a consumer.
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

The opener is rendered from `agents.AgentSetting.greeting` with `{{variable}}` substitution (§10) and
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
- Append the turn's cost to `CallSession.usage` as the turn completes (§13).

## 8. Tools: declarations, dispatcher, envelope

**Declarations are plain dicts**, provider-agnostic, in `apps/runtime/agent/tools.py`:

```python
{
    "name": "get_open_slots",
    "description": "Return open appointment slots …  Pass each result's slot_token unchanged to book_appointment.",
    "parameters": {"type": "object", "properties": {...}, "required": [...]},
}
```

The provider adapter converts them to the SDK's tool format — the declaration list itself imports no SDK, so it
can be asserted in tests without one. **Every declared tool must have a dispatcher branch**; a declared-but-
undispatched tool is a silent runtime failure.

### 8.1 The tool surface

Twelve tools, no more. Each is dispatched against the server-held `state` (tenant, location, session, contact).

| Tool | Purpose | Model-supplied arguments |
|---|---|---|
| `get_contact_appointments` | Look up the caller by phone to determine new-vs-existing and fetch their appointments. **Call this FIRST for any appointment intent.** | `phone` (optional — defaults to the caller's number on file) |
| `search_contact` | Find an existing contact by name + date of birth, when the phone lookup was ambiguous | `first`, `last`, `date_of_birth` |
| `create_contact` | Create a NEW `scheduling.Contact` | `first_name`, `last_name`, `date_of_birth`, `phone` |
| `get_open_slots` | Return open slots, filtered | `date_from`, `date_to`, `weekdays`, `time_from`, `time_to`, `duration_minutes`, `service_id`, `provider_ids`, `resource_ids`, `page`, `page_size` |
| `book_appointment` | Book the chosen slot for the identified contact | `slot_token`, `reason`, `notes` |
| `reschedule_appointment` | Move an existing appointment to a new slot | `appointment_id`, `slot_token` |
| `cancel_appointment` | Cancel by id — confirm with the caller first | `appointment_id`, `cancellation_reason` |
| `create_callback_request` | Log a `scheduling.CallbackRequest` so the team calls back in business hours | `caller_name`, `caller_phone`, `reason` |
| `get_location_hours` | Return this location's opening hours + address so the agent can read them out | *(none)* |
| `transfer_call` | Hand the call to a human at this location. Returns an ack; the transfer happens after the reply | *(none)* |
| `transfer_call_spanish` | Transfer to the Spanish-speaking line. Allowed regardless of working hours | *(none)* |
| `end_call` | End the call deterministically (wrong number, caller done, nothing further to help with) | *(none)* |

`date_from`/`date_to` are `MM/DD/YYYY`; `time_from`/`time_to` are 24-hour `HH:MM`; `weekdays` is a string array
(`['mon','tue']`). `get_open_slots` returns one **`slot_token`** per slot plus human-readable display text — see
below.

**Opaque signed slot tokens replace verbatim echo — binding.** The reference implementation tells the model to
store `start_at`, `provider_id` and `operatory_id` VERBATIM and pass them back unchanged. We do not.
`get_open_slots` returns one `slot_token` per slot — a signed, short-TTL blob encoding start / resource / service /
provider / location / tenant — and `book_appointment` / `reschedule_appointment` take that token instead of the
three fields. The model cannot mangle or invent a token, and the backend verifies the slot was actually offered
**in this session**. Verbatim-echo drift on slot fields is the single most common booking-failure class; the token
removes it.

**If a tool is not in the table above, it does not exist** — no insurance tool, no clinical note, nothing
vertical-specific.

### 8.2 One dispatcher, transport-agnostic

```python
async def apply_tool_call(state, name: str, args: dict) -> dict:
```

- The same function serves the turn-based path and the realtime speech-to-speech path. **Trace every new tool
  through both** — divergent argument coercion, divergent `ok` computation and divergent cost accounting between
  the two paths is the top regression risk in this layer.
- **Server owns identity; the model owns wording.** `tenant_id`, `location_id`, `contact_id` and `session_id` come
  from server-side session state and are **never tool parameters**. Any ID the model *does* supply
  (`appointment_id`, `slot_token`, `service_id`, `provider_ids`, `resource_ids`) is authorized server-side against
  the tenant, the **location** and the identified contact. This is an IDOR with an LLM in the middle; treat it as
  one. A caller who reaches Location A must never be able to read or move an appointment at Location B.
- Caller speech, contact names and custom fields are **untrusted input flowing into the model context**. A tool
  must never widen authority because the prompt or the caller asked it to.
- **One name per concept, everywhere.** A field is `date_of_birth` in state, in the tool schema and in the
  response — not `dob` in one and `birthdate` in another.
- **Never announce success before the write returns.** "You're all booked" with no `scheduling.Appointment` row is
  the worst failure this product can produce.
- **Never re-check availability after the caller confirms.** Re-offering traps the caller in an endless offer
  loop; confirm against the token you already hold.

### 8.3 One envelope, every tool, no exceptions

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

Never prose, never a bare `{"id": ...}`, never a different success key per tool. `ok` is what the log recorder,
the diagnostics page and the "did it actually succeed" rules key off.

Enablement follows the location's `AgentSetting`: `transfer_call` and `transfer_call_spanish` are offered only
when `transfer_enabled` is true and a destination is configured. **The prompt must never name a tool or a tool
parameter**, and must never promise a capability whose tool is disabled for that location.

## 9. Deferred cold transfer

Transfer is a first-class owner-requested feature and the flow is load-bearing in order. Transfer, hangup and any
other transport-mutating tool **do not act inside the dispatcher** — they set a deferred signal on session state
and return a short acknowledgement. The transport executes it after the turn's audio has played.

**The destination is ALWAYS the configured number.** `transfer_call` dials
`AgentSetting.transfer_phone_number`; `transfer_call_spanish` dials `AgentSetting.transfer_secondary_number`.
Neither is ever derived from caller speech, from a tool argument, or from anything the model produced. This module
decides *whether* to transfer and dials *where the configuration says* — never where the caller says. Unrestricted
dial-out is toll fraud waiting to happen.

### 9.1 Triggering

A transfer fires either because the model called `transfer_call` / `transfer_call_spanish`, or because the
per-turn keyword evaluation matched. The evaluation returns `(should: bool, reason: str | None)` where `reason` is
one of `spanish`, `caller_requested`, `ai_offered_transfer`, `ai_cannot_answer`, `no_answer`, and is checked in
that priority order:

0. **`spanish` first** — an explicit request for Spanish (`"speak spanish"`, `"spanish please"`,
   `"habla español"`, `"no hablo inglés"`). Routes to the secondary line and is **allowed regardless of working
   hours** — it is another agent, not the human team. Only *explicit* requests count: bare tokens like `spanish`,
   `hola` or `gracias` are deliberately excluded because they misfire on ordinary English
   ("is the form available in spanish?").
1. **`caller_requested`** — the caller asks for a person: a built-in keyword set (`"talk to a human"`,
   `"speak to someone"`, `"front desk"`, `"receptionist"`, `"put me through"`, `"customer service"`, …) plus
   article-tolerant regexes for *verb + human noun*. The location's configured `AgentSetting.transfer_keywords`
   **extend** the built-in set; they never replace it.
2. **`ai_offered_transfer`** — the agent's own reply already promised a transfer ("let me transfer you",
   "connect you with our team").
3. **`ai_cannot_answer`** — the agent's reply admitted defeat ("i don't have that information", "i'm unable").
4. **`no_answer`** — the turn's LLM status was `error`, `timeout`, `config_error` or `empty_response`.

**A turn with no real transcript can never trigger a transfer.** Guard on `had_real_transcript` first and return
early — otherwise a false VAD trip on silence hands the caller off for no reason.

### 9.2 The working-hours window

A **human** transfer (`caller_requested`, `ai_offered_transfer`, `ai_cannot_answer`, `no_answer`) is gated on
`AgentSetting.transfer_working_hours` evaluated in `AgentSetting.transfer_timezone` — **the location's timezone,
never the server's**. The JSON shape is `{weekday: {enabled, start, end}}` with `HH:MM` times.

The gate **fails open**, and that is deliberate: an empty or missing schedule, an unusable timezone, or a parse
error all return "allowed". A present-but-disabled weekday, or a weekday absent from the schedule, returns
"not allowed". A day window may wrap past midnight (`end <= start`), and `start == end` means all day. A
timezone/parse bug must never break a live call.

Off-hours: speak the off-hours notice **once**, clear the pending signal, and keep serving the caller with the
agent. `spanish` skips this gate entirely.

### 9.3 Execution, in order

1. Dispatcher sets `state.pending_transfer = "human" | "spanish"` and returns `{"ok": true, …}`.
2. The turn ends. The transport checks the signal **before** speaking the model's reply — the model's
   "connecting you now" line is usually misleading by then and must be suppressed if the transport speaks instead.
3. **Set the single-fire guard before any `await`**, so a concurrent turn cannot double-execute the transfer.
4. Evaluate the working-hours gate (§9.2). Off-hours or `transfer_enabled=False` or a missing destination → say so
   once, clear the signal so it does not retry every turn, keep helping.
5. Cancel queued playback, then speak the fixed handoff line **non-interruptible** — the English line for `human`,
   the Spanish line for `spanish`.
6. **Wait a short drain interval (~0.6 s)** so the carrier jitter buffer empties before the redirect. Skip it and
   the caller hears the handoff line cut off mid-word.
7. **Validate before interpolating.** The destination must match E.164 (`^\+[1-9]\d{6,14}$`); the account SID and
   the live call SID must match the Twilio SID shape (`^[A-Za-z0-9]{34}$`) before either goes into a REST URL.
   Any failure aborts the transfer and logs — it never dials a half-validated number.
8. Place the redirect through the telephony adapter: `POST` the Calls REST resource with TwiML
   `<Dial answerOnBridge="true" timeout="25" callerId="…"><Number>{destination}</Number></Dial>` followed by a
   `<Say>` fallback line, using **this location's** `twilio_account_sid` / `twilio_auth_token`. XML-escape the
   destination and quote the caller id. A 2xx means Twilio **accepted the redirect** — not that anyone answered.
9. A **404** here means the credentials authenticated but the live call is not under that account: the location's
   `twilio_account_sid` must own the dialed number, or the caller already hung up. It is almost never an
   hours/gate problem — say so in the log rather than sending the reader to the schedule.
10. Redirect failed → apologize once, keep the guard set (do not retry a configuration bug on every turn), keep
    serving.
11. Record the outcome into `CallSession.transfer` — `{reason, destination_kind, outcome, at}` where `outcome` is
    `connected` / `failed` / `off_hours` / `disabled` — so the call detail page can show where a bridge broke.
    Record the destination **kind** (`primary` / `secondary`), not the raw number.

An **explicit `end_call` tool** ends the call deterministically for wrong-number and caller-done outcomes —
waiting on a silence timeout burns minutes and looks broken.

## 10. Prompt and variable rendering

- Placeholders are `{{key}}`, whitespace-tolerant (`{{ key }}` resolves identically). Regex:
  `\{\{\s*([\w.\-]+)\s*\}\}`.
- **A missing key renders as an empty string** — never leak a raw `{{placeholder}}` to a caller.
- Variables merge in one direction: `AgentSetting.variables` first, then the **runtime vars computed per
  call/turn, which always win**.
- Runtime var set (extend it here, in one place, when a module adds one): `from_e164`, `to_e164`, `tenant_name`,
  `location_id`, `location_name`, `location_address`, `is_open_now`, `current_date`, `current_time`,
  `caller_display_name`, `agent_name`.
- **`is_open_now` is computed server-side** from the location's hours and injected as the literal string
  `"yes"` / `"no"`. The model must never derive open/closed from raw hours plus a clock. The name is `is_open_now`
  everywhere — in this skill and in `realtime-reviewer`. A missing key renders as an empty string (see above), so
  a spelling drift here fails **silently** on a live call.
- **`current_date` / `current_time` are computed in the location's timezone, never the server's**, and
  **recomputed each turn**. Without a date anchor the model mislabels today's slots as tomorrow and stalls booking.
- **Use portable strftime.** `%-d` and `%-I` are unsupported on the Windows dev host — build the day number and
  strip a leading zero explicitly.
- The rendered system prompt is composed once per turn from `AgentSetting.prompt_text`. `CallSession.metadata`
  records which prompt text ran, which is what makes "which prompt said that?" answerable.

## 11. Latency and cost budgets

| Budget | Value |
|---|---|
| First audio (greeting) | immediate — deterministic, **0 LLM tokens** |
| Turn latency | ≤ **1.5 s** p50, ≤ **3 s** p95, measured utterance-end → first outbound frame |
| Tool iterations per turn | **4** (`MAX_TOOL_ITERATIONS`) |
| No-audio idle timeout | **45 s** (`IDLE_TIMEOUT_SECONDS`) |
| Hard max call duration | configurable, default **15 min** (`MAX_CALL_SECONDS`) |
| Provider call | explicit timeout + bounded retry on every telephony/STT/TTS/LLM call |
| Failure mode | a spoken fallback, **never dead air** |

- Count the serial round-trips a turn makes (STT → LLM → tool → LLM → TTS). Adding an unnecessary serial hop, or
  a tool that runs N queries where one `select_related` would do, is a latency defect — review it as one.
- Attribute latency per stage (ASR / LLM / tool / TTS) and append it to the turn's entry in `CallSession.logs`.
- **Cost is a security control.** Per-call duration and turn ceilings, plus per-caller rate limiting, are what stop
  a prompt-injected or looping agent from burning unbounded provider spend.

## 12. Provider adapters, `PROVIDER_MODE` and fakes

Every external dependency sits behind an adapter in `apps/runtime/providers/` — telephony, STT, TTS, LLM, storage.
Consumers and tools call the adapter interface, never an SDK directly.

- Interfaces are narrow and async: `telephony.redirect_call / hangup`, `stt.transcribe(pcm, rate)`,
  `tts.synthesize(text) -> (pcm, rate)`, `llm.generate(history, system, tools) -> (text, tool_calls, usage)`.
  The interface has **no dial-out method** — the only call the runtime touches is one the caller placed.
- **Every adapter ships its fake in the same pass.** The fake is a real implementation of the interface —
  deterministic synthetic audio, canned transcripts, scripted tool calls — not a mock. Tests and seeders run
  against the fakes so the **adapter contract itself** is exercised; SDK-level mocking hides contract drift.
- `PROVIDER_MODE` ∈ `fake | sandbox | live`, resolved in `apps/runtime/providers/`. The rules, in this direction:
  1. **`fake` is the default** for dev, tests and seeders.
  2. When the mode is **not** `live`, adapters resolve to the fake/sandbox implementation and **must never reach a
     real provider** — no real call answered or redirected, no billable API call. Non-`live` is the safe path,
     not a failure path; it must run cleanly with no credentials at all.
  3. The **live** adapter refuses to initialize unless `PROVIDER_MODE == "live"`, and live mode additionally
     requires real credentials to be present — **missing credentials in live mode is the hard failure**.
  4. `on_stop.py` warns loudly if `PROVIDER_MODE=live` is set in a dev environment.

  A seeder, test, fixture, management command or `DEBUG=True` path that can reach a live provider is a defect, not
  a configuration choice.
- **Twilio credentials are per-location in the database**, not in `.env` — `AgentSetting.twilio_account_sid` and
  the **encrypted, write-only** `AgentSetting.twilio_auth_token`. `.env` holds only platform defaults and
  `PROVIDER_MODE`. Never in `Meta.fields` as a readable value, never in `messages.*`, never logged, never
  rendered. Display as prefix + hash; rotate through a write-only flow.
- Build TTS lazily where a path may not need it, latch a failed build so it is not retried every line, and let a
  missing provider skip the spoken line rather than raise — the flow (a transfer redirect) still has to proceed.

## 13. Per-turn cost lives on the CallSession

There is no separate metering table. **Per-turn cost is appended to `CallSession.usage`**, a
JSON list of `{turn_sequence, cost_breakdown, cost_usd}` — one entry per assistant turn, appended as the turn
completes.

- `cost_breakdown` carries the components the model actually consumed — input tokens, output tokens, input/output
  audio tokens, the model name — so a turn's cost is reconstructable without a second table.
- **Append deltas per turn, never re-aggregate the whole call each turn.** Rewriting the list from scratch every
  turn is both quadratic and lossy under concurrency.
- The call's total is a **sum over the list**, computed when read. Nothing stores a running total; there is no
  hand-editable `minutes_used`, `credit_balance` or `spend_to_date` field anywhere in this product.
- The cost breakdown on the call detail page reads this list directly. It is not a separate model — see
  Invariant 2.

## 14. What the runtime writes: one CallSession per call

**Invariant 2 — One call log.** A call is exactly one `calls.CallSession`; its transcript, event log, per-turn
usage, analysis and transfer outcome are **JSON columns on that row**. **Flag a second transcript, turn, tool-call
or call-event table.**

The row is created when the voice webhook resolves the dialed number, and finalized in `disconnect()`:

| Column | Contents |
|---|---|
| `tenant`, `location` | resolved from `AgentSetting.inbound_phone_number` — never from the URL or body |
| `contact` | the `scheduling.Contact` once the agent identifies or creates the caller; null until then |
| `from_number`, `to_number`, `provider_call_sid` (unique), `status`, `mode`, `started_at`, `ended_at` | call facts |
| `transcript` | JSON list of `{sequence, role, text, at, offset}` — the whole conversation |
| `logs` | JSON list of `{sequence, level, category, title, raw_json, occurred_at}` — provider events, tool calls and results, barge-ins, errors, latency attribution |
| `analysis` | JSON `{summary, success_evaluation, extracted_data}`, written post-call |
| `usage` | JSON list of per-turn cost (§13) |
| `transfer` | JSON handoff outcome (§9.3) |
| `waveform_peaks`, `recording_blob` | JSON peaks and the private storage path |

**Why one table with JSON, not a normalized event log:** a call session is written once by one process and read as
a whole on one detail page. Nothing queries across turns. A `Transcript`, `TranscriptTurn`, `ToolCall`, `Message`,
`CallEvent` or `ActivityLog` table is an **Invariant 2** violation — three tables would be three answers to "what
happened on the call".

Callers are `scheduling.Contact` rows (**Invariant 1**) — the runtime never creates a `Caller`, `Lead` or
`Patient` table.

**Recording consent stays.** A recording carries its consent basis and its retention window; where the location's
jurisdiction requires two-party consent the announcement is played before recording begins, and the `logs` entry
proving it is the evidence. A recording without a recorded consent basis must not be creatable.

**PII discipline:** transcripts, caller numbers and tool-call argument blobs are PII by definition. Never log them
at INFO — a `create_contact` args payload is a full name and a date of birth. Redact the tool-call payload before
persisting it into `logs`.

## 15. Observability — a service module still ships a surface

Module 3 has no CRUD pages, but "no templates" never means "nothing to look at". Every runtime sub-module ships at
least one observable surface, or it is not done:

- a **diagnostics page** (`templates/runtime/diagnostics.html`): per-call latency breakdown by stage, ended-reason
  codes, runtime errors surfaced rather than buried in server logs, transfer outcome and where a failed bridge
  broke, active-call count and worker health;
- a **settings form** for the tunable budgets (max duration, idle timeout, tool cap);
- or a **management command** that exercises the path end-to-end under `PROVIDER_MODE=fake`.

Plus a `LIVE_LINKS["N.M"]` entry pointing at that surface, tenant **and location** scoping on every query,
migrations, an idempotent seeder if it adds data, and tests.

## 16. Tests for this layer

- `pytest-asyncio` with `asyncio_mode = auto`; `channels.testing.WebsocketCommunicator` against
  `config.asgi.application`; `InMemoryChannelLayer` and `PROVIDER_MODE = "fake"` in `config/settings_test.py`.
  DB-touching async tests use `@pytest.mark.django_db(transaction=True)`.
- **Consumer:** accepted with a valid stream token; **rejected** with no auth, with another tenant's session id,
  and with another **location's** session id; group name is tenant-namespaced; a synthetic audio frame
  round-trips; `disconnect()` finalizes the `CallSession`; a `SynchronousOnlyOperation` is a failure, never a
  flake.
- **Webhook:** valid signature → 200 + expected body; invalid/absent → 403 with **zero** side effects (assert row
  counts unchanged); duplicate delivery → exactly one `CallSession`; malformed payload → 4xx, never 500; the
  signature is checked against the **resolved location's** credentials, not a global token.
- **Dispatcher:** declarations are plain dicts asserted by name; a missing identity precondition returns
  `{"ok": false, …}` and writes nothing; a model-supplied `appointment_id` from another tenant **or another
  location** is rejected; a `slot_token` not offered in this session is rejected; an expired `slot_token` returns
  `slot_expired`; **every tool is tested through both runtime paths**.
- **Transfer:** a silence turn (`had_real_transcript=False`) never triggers; an explicit Spanish request routes to
  the secondary number even outside working hours; a human request inside hours redirects and records
  `outcome='connected'`; outside hours it speaks the notice once, clears the signal and records `off_hours`; a
  non-E.164 configured destination aborts without dialing; the destination is **never** taken from caller
  speech — assert it equals the configured number.
- **Cost:** a call appends one `usage` entry per turn and the summed total matches them.

## 17. Adding to this layer — the checklist

Adding a **tool**: declaration dict → dispatcher branch → `{ok, data, error}` envelope → identity from server
state → gated on the location's `AgentSetting` where relevant → prompt wording that names no tool → tests through
**both** paths → the `logs` and `usage` entries it produces → update this skill.

Adding a **consumer**: `consumers/<SubModule>/<Entity>.py` → `__init__.py` re-export → `routing.py` entry checked
against the whole concatenated route list → `connect()` authorization (tenant **and** location) →
tenant-namespaced group → `database_sync_to_async` on every ORM touch → `disconnect()` teardown →
`WebsocketCommunicator` accept/reject tests.

Adding a **provider method**: interface method → live implementation → **fake implementation in the same pass** →
timeout + bounded retry → the live implementation refuses to initialize unless `PROVIDER_MODE == "live"`, and every
non-`live` mode resolves to the fake.

Adding a **prompt variable**: add it to the runtime var set in §10 → compute it in the location's timezone →
refresh it per turn if it is time-sensitive → missing renders empty → document it here.

When any of this changes in code, **update this skill in the same change**, and commit it on its own:
`git add '.claude/skills/voice-agent-runtime/SKILL.md'; git commit -m 'docs(runtime): …'`. One file per commit,
PowerShell `;` never `&&`, and **never `git push`**.
