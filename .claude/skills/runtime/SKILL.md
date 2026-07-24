---
name: runtime
description: Work on the Call Runtime module (Module 3 — the service module: Twilio webhook ingress, dialed-number call resolution, the media-stream consumer, turn loop, LLM tools, transfer execution, recording, and a diagnostics surface). Use when the user asks to add/change/debug anything under apps/runtime or templates/runtime, anything about the /runtime/voice/ voice webhook, X-Twilio-Signature verification, dialed-number → tenant+location resolution, the signed media-stream token, the runtime diagnostics page, PROVIDER_MODE / provider adapters, or invokes /runtime. For the binding realtime contract itself (consumer lifecycle, audio chain, turn loop, tool envelope) use /voice-agent-runtime.
---

# runtime — Module 3, the Call Runtime service module

## Overview

`apps/runtime` is the **service module**: consumers, the Twilio webhook ingress, the turn loop, the tool
dispatcher, provider adapters and a diagnostics page. **It ships no CRUD and owns no models.** It resolves tenant +
location from the dialed number and writes the `calls.CallSession` row that Module 5 reads. App path: `apps/runtime`,
mounted at `/runtime/` (`config/urls.py`), `app_name = 'runtime'`.

**The binding contract for everything realtime is `.claude/skills/voice-agent-runtime/SKILL.md`** — this skill is
the as-built index; that skill is the law (webhook ingress §2, consumer lifecycle §3, audio chain §4, turn loop §7,
tool envelope §8, deferred transfer §9, providers/PROVIDER_MODE §12, what the runtime writes to CallSession §14).

### Sub-modules

| N.M | Title | State |
|---|---|---|
| **3.1** | **Inbound Webhook & Call Resolution** | **BUILT** — the HTTP half: voice webhook, signature verification, dialed-number resolution, idempotent CallSession creation, unmapped/disabled decline, diagnostics page |
| **3.2** | **Media Stream & Turn Loop** | **BUILT** — the media-stream consumer (`connect`/`receive`/`disconnect`), the audio codec chain, VAD/barge-in + echo guard, the agent package (state, prompt/variable rendering, turn loop), bounded STT/TTS/LLM adapters + fakes, and the `simulate_call` observable surface |
| **3.3** | **Tools & Dispatcher** | **BUILT** — the 12 tool declarations, the `{ok,data,error}` envelope over a closed 8-code set, and `apply_tool_call` (identity from server state only). Wraps 4.3's `scheduling/availability.py` booking engine rather than reinventing it |
| **3.4** | **Transfer Execution** | **BUILT** — the dispatcher hours/target gate (human gated on `is_transfer_available`, off-hours → an `off_hours` `CallSession.transfer` record + a de-duped `CallbackRequest`; Spanish skips the hours gate), the consumer's deferred `_execute_transfer` (single-fire guard, E.164/SID validation, drained bounded `redirect_call`, outcome capture, spoken apology + callback on failure), the telephony `get_backend()`/`redirect_call` handoff, and a diagnostics transfer-outcome summary |
| **3.5** | **Recording, Teardown & Diagnostics** | **BUILT** — the location-jurisdiction consent resolver + the spoken notice, the recording adapter and its real fake, the two-channel waveform accumulator, the consent-gated recording/waveform write inside the one guaranteed-teardown path, the single-use stream-token claim (closing 3.2's replay deferral), the `purge_expired_recordings` retention job, and the fuller diagnostics page (ended-reason tally, per-stage latency, recent errors, spend today) |

**Module 3 is complete: 3.1–3.5 all built.**

## Models

**None.** This app has no `models/` package and no migrations (`makemigrations runtime` → "No changes detected" is
the acceptance signal). It touches two existing models:

- **Reads** `agents.AgentSetting` — resolved by the globally-unique `inbound_phone_number`; provides tenant,
  location, `enabled`, `voice_provider`, `twilio_account_sid`, and the encrypted `twilio_auth_token` (decrypted
  transparently on read via `EncryptedCharField`).
- **Writes** `calls.CallSession` — one row per call, created by the webhook keyed on the unique `provider_call_sid`
  (Invariant 2: one call log, JSON columns, no second table). **3.2's consumer is the first writer of the JSON
  columns** — it appends `transcript`/`logs`/`usage` at per-turn checkpoints and, in `disconnect()`, stamps
  `ended_at` + a terminal `status` (`completed`/`abandoned`/`failed`) and `metadata.ended_reason`. **3.4 writes
  the `transfer` JSON column** (`{result, reason, destination, initiated_at, duration_seconds}`, the shape 5.4's
  `_transfer_outcome.html` reads) and sets `status='transferred'` via `ended_reason='transferred'`. **3.5 writes
  `recording_blob`, `waveform_peaks` and the consent keys on `metadata`** (`recorded`, `consent_basis`,
  `consent_announced`, `retention_days`) — all in the SAME `save()` as the terminal status, which is what makes the
  consent gate structural. Also **writes `scheduling.CallbackRequest`** on the off-hours and failed-transfer
  fallbacks. `makemigrations runtime` → "No changes detected" still holds through 3.5 (no sub-module of Module 3
  adds a model — they write existing columns).
- **Reads** `tenants.Location.state` / `.country` (3.5) for the recording consent jurisdiction. Read-only, no new
  field — the jurisdiction is the LOCATION's, never the caller's number.

## URLs / routes

`urls/__init__.py` sets `app_name='runtime'` and concatenates entity urlpatterns.

| Name | Path | View | Notes |
|---|---|---|---|
| `runtime:voice_webhook` | `/runtime/voice/` | `apps/runtime/webhooks.py:voice_webhook` | POST-only, `@csrf_exempt` + signature-verified. **Module 2's live test call hardcodes this exact URL** (`apps/agents/telephony.py`) — do not move it. |
| `runtime:diagnostics` | `/runtime/diagnostics/` | `views.runtime_diagnostics_view` | `@login_required` GET; the observable surface + `LIVE_LINKS['3.1']`. |

## Templates

- `templates/runtime/diagnostics.html` — standalone page (service module, no CRUD entity folders). Extends
  `base.html`, `{% load ui %}` for `phone_e164`. PROVIDER_MODE banner (`role=status`/`role=alert`), stat cards
  (active / total / agent-ready / **transferred** — 3.4), a recent-calls table using
  `partials/_call_status_badge.html`, an inbound-routing card showing the webhook URL to configure in Twilio + the
  media-stream `wss://` URL, a **transfer-outcome tally card** (3.4, per-result counts with the same badge colours as
  `_transfer_outcome.html`, rendered only when there are transfers), and a readiness-issues card.
  Guidance empty-state when there is no active location. Never `|safe`s caller data.
  **3.5 added four panels to this same page** (no new template): a fifth **Spend today** stat card (the card spans
  both columns at the 2-col tier so five cards never orphan one at half width), an **Ended reasons** badge tally
  driven by `agent.state.ENDED_REASON_DISPLAY`, a **Per-stage latency** p50/p95 table (labelled per stage — it is
  deliberately NOT the end-to-end turn budget, since the log rows carry no turn-correlation id to sum by), and a
  **Recent runtime errors** table linking each row to `calls:callsession_detail`. The errors panel surfaces
  `level`/`category`/`title`/`call_sid` only — **never `raw_json`**, which is redacted at write time but still
  describes caller data.

## Backend package layout (as built)

```
apps/runtime/
  apps.py            RuntimeConfig(name='apps.runtime', label='runtime'); registers system check runtime.E001
  admin.py           empty (no models — documented)
  webhooks.py        FLAT — voice_webhook(request): the whole 3.1 contract
  routing.py         FLAT — websocket_urlpatterns = [path('ws/media-stream/', MediaStreamConsumer.as_asgi())] (3.2)
  providers/
    base.py          PROVIDER_MODE resolution: active_mode()/is_live()/require_live()/LiveModeError (fail-safe)
    telephony.py     Twilio helpers: webhook_public_url, media_stream_ws_url, verify_twilio_signature,
                     build_stream_twiml, build_decline_twiml (pure, 3.1) + (3.4) get_backend() and the
                     Fake/LiveTelephonyBackend transfer redirect — subclass Module 2's backends, add
                     async redirect_call(setting, call_sid, destination); live wraps the REST call in asyncio.to_thread
    tokens.py        signed short-TTL opaque stream token: mint_stream_token / verify_stream_token
    audio.py         (3.2) μ-law⇄PCM16 codec, stateful inbound Resampler, iter_mulaw_frames, PlaybackTracker — pure DSP
                     (3.5) WaveformAccumulator — per-CALL two-lane energy capture, binned at teardown
    recording.py     (3.5) RecordingBackend + FakeRecordingBackend (writes a real stub WAV through
                     apps.calls.storage.save_recording) + LiveRecordingBackend + get_recording_backend();
                     recording_path_for() shape-checks the SID. DELIBERATELY SYNC — its only call site is
                     already off-loop; read the module docstring before "fixing" the asymmetry
    vad.py           (3.2) energy VAD/endpointing, sustained-speech barge-in, echo guard — named constants + VadState
    reliability.py   (3.2) call_bounded(): timeout + retry, RateLimited(backoff) vs transient; timeout is TERMINAL
    stt.py           (3.2) SttBackend + FakeSttBackend + LiveSttBackend + get_stt_backend() — transcribe(pcm,rate)->str
    tts.py           (3.2) TtsBackend + FakeTtsBackend + LiveTtsBackend + get_tts_backend() — synthesize(text)->(pcm,rate)
    llm.py           (3.2) LlmBackend + FakeLlmBackend + LiveLlmBackend + get_llm_backend() — generate(hist,sys,tools)
  agent/             (3.2) the conversation brain — imported by the consumer, kept apart from transport/providers
    state.py         CallState dataclass — identity (from token only), history, buffered transcript/log/usage, seams
    prompt.py        render_template / build_variables (full runtime var set) / is_open_now / render_greeting
    turn.py          run_turn() — STT→history→LLM→tools→TTS; ProviderBundle, TurnResult, tts_only_cost
    tools.py         (3.3) TOOL_DECLARATIONS (12 plain dicts, no SDK import) + active_tools(agent_setting)
    envelope.py      (3.3) ok()/err() — the one result shape; err() asserts the CLOSED 8-code set
    dispatcher.py    (3.3) apply_tool_call(state, name, args) — Invariant 3, wraps scheduling/availability.py;
                     (3.4) transfer hours-gate + off-hours callback fallback in _transfer_call/_transfer_call_spanish
    transfer.py      (3.4) PURE — build_transfer_record() (the ONE CallSession.transfer shape builder, both writers),
                     looks_like_e164/looks_like_call_sid (injection gates), RESULT_* vocabulary, REASON_BY_KIND
    consent.py       (3.5) PURE, no ORM — resolve_consent(location) -> CONSENT_TWO_PARTY|CONSENT_ONE_PARTY from the
                     LOCATION's state/country; TWO_PARTY_CONSENT_STATES, US_STATE_CODES, CONSENT_ANNOUNCEMENT_LINE
  consumers/         (3.2) fifth backend layer — <SubModule>/<Entity>.py, re-exported in __init__
    MediaStreamTurnLoop/MediaStream.py   MediaStreamConsumer (connect/receive/disconnect + group_name());
                     (3.4) _execute_transfer — the deferred transport transfer executed after the ack audio
                     (3.5) the single-use stream claim, _announce_recording, the two waveform hooks,
                     _discard_recording, and the recording/waveform/consent write in _finalize_session
  management/commands/simulate_call.py   (3.2) observable surface — drives a full fake call through the real consumer
                     (3.5) reports the recording block and hard-fails a `recorded` row whose blob has no bytes
  management/commands/purge_expired_recordings.py   (3.5) the retention job — per-row retention_days, idempotent
  views/
    _common.py       re-exports apps.accounts.views._common
    _helpers.py      recent_location_sessions(request) — delegates to apps.calls.views._helpers.location_sessions
    InboundWebhook/Diagnostics.py   runtime_diagnostics_view
  urls/
    InboundWebhook/Webhook.py       /runtime/voice/
    InboundWebhook/Diagnostics.py   /runtime/diagnostics/
```

## Tools & prompt surface

**Prompt & variables — BUILT (3.2), in `apps/runtime/agent/prompt.py`.** `render_template(text, variables)` does the
`{{key}}` / `{{ key }}` substitution (regex `\{\{\s*([\w.\-]+)\s*\}\}`); **a missing key renders as `''`** (never
leak a raw `{{placeholder}}` to a caller). `build_variables(agent_setting, call_session, location, now,
open_intervals, contact=None)` computes the full runtime var set — `from_e164`, `to_e164`, `tenant_name`,
`location_id`, `location_name`, `location_address`, `is_open_now`, `current_date`, `current_time`,
`caller_display_name`, `agent_name` — merged as `{**AgentSetting.variables, **runtime_vars}` (**runtime wins**).
`is_open_now` is the literal `"yes"`/`"no"`, computed server-side from the location's **provider** working hours
(there is no location-hours field; the union of `accounts.User.provider_hours` at the location is the source,
gathered once at connect via `build_open_intervals` so the per-turn check is pure). `current_date`/`current_time`
are in the **location's** timezone, recomputed each turn, portable strftime (no `%-d`/`%-I`). The greeting is
rendered from `AgentSetting.greeting`, deterministic, 0 LLM tokens.

**Tools — BUILT (3.3).** `agent/tools.py` holds `TOOL_DECLARATIONS`: 12 plain provider-agnostic dicts
(`name`, `description`, `parameters` JSON-schema) importing no SDK, so they are assertable in tests.
`active_tools(agent_setting)` returns the subset to offer on THIS call.

| Tool | Model-supplied args | Notes |
|---|---|---|
| `get_contact_appointments` | `phone?` | Call first for any appointment intent. **Only the verified ANI identifies** — a caller-supplied number is a claim, not a credential, and returns a neutral shape |
| `search_contact` | `first`, `last`, `date_of_birth` | The second factor. Failed attempts capped per call (`_MAX_SEARCH_ATTEMPTS`) so it is not a DOB oracle |
| `create_contact` | `first_name`, `last_name`, `date_of_birth?`, `phone?` | `source='ai_phone'`; either name is enough |
| `get_open_slots` | `service_id`, `date_from?`, `date_to?`, `weekdays?`, `time_from?`, `time_to?`, `duration_minutes?`, `provider_ids?`, `resource_ids?`, `page?`, `page_size?` | Returns one opaque `slot_token` per slot |
| `book_appointment` | `slot_token`, `reason?`, `notes?` | Requires an identified contact |
| `reschedule_appointment` | `appointment_id`, `slot_token` | |
| `cancel_appointment` | `appointment_id`, `cancellation_reason?` | |
| `create_callback_request` | `caller_name?`, `caller_phone?`, `reason` | **No** identified-contact precondition |
| `get_location_hours` | *(none)* | Reuses `state.open_intervals` — no hours query |
| `transfer_call` / `transfer_call_spanish` | *(none)* | (3.4) `transfer_call` re-checks `AgentSetting` eligibility AND `is_transfer_available` (hours) — arms `pending_transfer='human'` (`status:'connecting'`) when open, else logs a de-duped off-hours `CallbackRequest` + `off_hours` transfer record and returns `status:'off_hours'` WITHOUT arming. `transfer_call_spanish` skips the hours gate (separate language line), arms `'spanish'`. Destination is server-resolved (`resolve_transfer_number(setting, label)`), never a tool arg |
| `end_call` | *(none)* | Sets `pending_hangup`; the consumer closes after the goodbye |

Formats: `date_*` are `MM/DD/YYYY`, `time_*` are 24h `HH:MM`, `weekdays` is `['mon','tue',…]`.

**Identity args (`tenant_id`, `location_id`, `contact_id`, `session_id`) come from server-side session state and
are NEVER tool parameters** (Invariant 3). No declaration exposes one, AND `apply_tool_call` strips those keys from
`args` before any handler runs — both layers, deliberately. Every model-supplied id (`appointment_id`,
`slot_token`, `service_id`, `provider_ids`, `resource_ids`) is re-authorised server-side against tenant **and**
location, and reschedule/cancel additionally bind to the identified contact via `availability.py`'s
`actor_contact`. The prompt names no tool.

**The envelope** (`agent/envelope.py`): every tool returns `{"ok", "data", "error"}`; `err()` raises on a code
outside the closed set `{not_found, invalid_argument, slot_unavailable, slot_expired, not_permitted,
provider_error, rate_limited, internal_error}`. `SlotError`'s four codes are a subset, so a `SlotError` from the
booking engine passes through **untranslated**.

**The tool-call trace** is a `CallSession.logs` row with `category='tool'` and
`raw_json = {tool, arguments, ok, error}` — the exact shape Module 5.3's event-log template reads. `arguments` is
redacted by an **allow-list** (`_LOG_SAFE_ARGS`): ids/counts/dates verbatim, phones masked, names to an initial,
`date_of_birth` dropped, tokens elided, and anything unrecognised reduced to a length marker (fail closed).
`result['data']` is never logged. Invariant 2 holds — no `ToolCall` table.

## Realtime surfaces

- **Webhook ingress (built, 3.1)** — `apps/runtime/webhooks.py`. The one place tenant + location are discovered
  from scratch, from the dialed number only. Signature verified against **that resolved row's** per-location
  `twilio_auth_token` (via `providers.telephony.verify_twilio_signature`, Twilio's `RequestValidator`, constant-time)
  **before any side effect**; `@csrf_exempt` is paired with it. Idempotent on `provider_call_sid`. Returns
  `<Connect><Stream>` TwiML (`application/xml`, never a redirect) carrying the **opaque signed stream token** — never
  cleartext tenant/location ids.
- **Stream token** — `providers/tokens.py`. The media stream has no session and no user; this signed, short-TTL
  (300s) token IS its credential. Payload `{sid, ten, loc}` lives *inside* the signed blob.
- **Media-stream consumer (built, 3.2)** — `apps/runtime/consumers/MediaStreamTurnLoop/MediaStream.py`,
  `MediaStreamConsumer`. **Authorizes on the Twilio `start` frame, not at connect** — Twilio delivers the stream's
  custom `<Parameter>` values (`streamToken`, `sessionId`) in the `start` event, *after* the socket opens, so
  `connect()` only `accept()`s and does nothing else; `receive()` on `start` calls `verify_stream_token()` FIRST and
  serves no audio / joins no group / writes no row until it verifies. Identity comes only from the token payload,
  never the URL; the `sessionId` param is cross-checked against the token's `sid`. Reject codes: `4401`
  unauthorized, `4403` forbidden (param mismatch / disabled number / at capacity), `4404` unknown session. Every ORM
  touch is `database_sync_to_async(..., thread_sensitive=False)` (the default `True` serializes ALL concurrent calls
  onto one thread). Barge-in cancels the turn task (playback lives there) + sends Twilio `clear`; teardown is one
  idempotent `_finalize()` that flushes buffers, stamps terminal status/`ended_at`, releases the capacity slot, and
  never raises. A per-worker `MAX_CONCURRENT_CALLS` gate declines at capacity (cross-worker enforcement → 3.5).
- **Route + ASGI (built, 3.2)** — `routing.py` mounts `path('ws/media-stream/', MediaStreamConsumer.as_asgi())`;
  `config/asgi.py` wires `apps.runtime.routing.websocket_urlpatterns` into the `ProtocolTypeRouter["websocket"]`
  URLRouter (behind `AllowedHostsOriginValidator` — a test/`simulate_call` communicator MUST send an `Origin`
  header). First-match-wins applies across the whole concatenated list; a later staff live-call route is checked
  against this one.
- **Group name (resolved, 3.2)** — `group_name(tenant_id, location_id, session_id)` returns
  `t{tenant_id}.l{location_id}.call.{session_id}`. CLAUDE.md rule 3 writes it with colons
  (`t{t}:l{l}:call:{s}`), but that is the *logical* namespace — **Channels forbids `:` in a group name**
  (`require_valid_group_name` allows only `[A-Za-z0-9._-]`), so the physical separator is `.`. Tenant AND location
  namespacing is fully preserved. (`voice-agent-runtime` §3 was updated to match.)
- **Deferred transfer execution (built, 3.4)** — the transport half of the handoff. 3.3's `transfer_call` tools set
  `CallState.pending_transfer` (`'human'`/`'spanish'`); the dispatcher gates it (see the tool table). In `_run_turn`,
  after the acknowledgement audio plays **non-interruptibly** (`interruptible=not (pending_hangup or
  pending_transfer)` — so barge-in can't strand it), an `elif pending_transfer` branch runs `_execute_transfer`
  behind the consumer-instance `_transfer_started` **single-fire** boolean (set before any await). `_execute_transfer`
  sets `ended_reason='transferred'` **synchronously first** (so a racing `stop`/`disconnect` finalize stamps
  `transferred`, not `hangup`), then re-resolves `(setting, destination, call_sid)` off-loop, **validates
  `looks_like_e164(destination)` + `looks_like_call_sid(call_sid)` before any REST interpolation** (toll-fraud/XML
  injection), waits `settings.TRANSFER_DRAIN_SECONDS` (drains the jitter buffer), then `call_bounded(...,
  retries=0)` around `get_backend().redirect_call(...)` (a redirect is NOT idempotently retryable). Outcome →
  `connected`/`failed` written to `CallSession.transfer`; on `failed` it speaks an apology + logs a `CallbackRequest`
  (never dead air). **`_finalize()` must NOT cancel the turn_task while `_transfer_started`** — CancelledError is a
  BaseException that would skip the outcome write, losing the transfer JSON. `no_answer` needs a `<Dial action>`
  status callback (deferred); the live redirect's 2xx is a provisional `connected`.
- **Single-use stream claim (built, 3.5)** — closes 3.2's tracked replay deferral. In `_authorize_and_start`, right
  after the `sessionId` cross-check and **before** the DB resolve (cheapest reject, zero side effect),
  `cache.add('runtime:stream-claim:{session_id}', True, timeout=STREAM_TOKEN_TTL_SECONDS)` claims the session; a
  second socket presenting the same still-valid token is closed `4403`. `cache.add` is Django's atomic SETNX. It
  goes through `sync_to_async(..., thread_sensitive=False)` **even though the configured backend is `LocMemCache`**:
  the intended fix for the cross-worker gap is a shared Redis cache, which would silently turn this into a network
  call on every call's authorization path. One thread hop once per call beats a documented footgun. The claim is
  never released — it expires with the token's own TTL, and a genuinely new call mints a fresh token.
  **Still per-process**: a `LocMemCache` claim does not span a worker fleet (carried with the cross-worker
  `MAX_CONCURRENT_CALLS` deferral).
- **Consent-gated recording + guaranteed teardown (built, 3.5)** — the last realtime surface.
  `agent/consent.py:resolve_consent(location)` runs **once**, in `_authorize_and_start` **after** the
  enabled/capacity gates (so a declined call never resolves a basis and finalizes as `not_recorded`). If the basis is
  two-party, `_greet` follows the opener with `_announce_recording()` — a second **non-interruptible** utterance. It
  sets `self.interruptible = False` **before the TTS synthesize await**, because `_play`'s `finally` resets it the
  instant the greeting's audio ends; without that, caller speech in the gap would barge-in, cancel the `_greet` task
  and skip the disclosure. Restored in a `finally` on every path. `consent_announced` is set only **after** the audio
  really played — and `CallState.should_record` **requires it** in a two-party jurisdiction, so a call whose notice
  never reached the caller is simply not recorded, and the row says so honestly (`basis=announced_notice`,
  `announced=False`, `recorded=False`).
  `_finalize_session` is the ONE guaranteed-teardown write reached by every termination path, so an abnormal drop
  persists exactly what a clean hangup does. The recorder runs **before** `transaction.atomic()` (never hold
  `select_for_update` across file I/O), with `_discard_recording(blob)` deleting the orphan if the guarded write
  finds a vanished or already-terminal row. The recording path, the waveform and the four consent metadata keys all
  land in **one `save()`** — that is what makes the gate structural rather than merely documented.
- **Waveform capture (built, 3.5)** — `providers/audio.py:WaveformAccumulator`, ONE instance per call (created in
  `connect()`, unlike `PlaybackTracker` which `_play` recreates per blob). `add_caller_frame` on every inbound frame;
  `add_bot_frame` at the same per-frame point as `playback_tracker.mark`, so the agent lane shows only audio
  actually sent and inherits barge-in accuracy for free. `finalize()` **snapshots each lane with `list()` before
  binning** — it runs on the teardown worker thread while a cancelled playback can still be appending on the event
  loop, and `_bin` reads `len()` repeatedly.

## Seeder

**None.** No sub-module of Module 3 adds data of its own; the diagnostics page reads the `calls.CallSession` rows
that `seed_calls` already creates (through the fake provider). 3.5's one seeder change lives in **Module 5's**
`seed_calls._build_metadata` — it now stamps `metadata['ended_reason']` from each spec's terminal status, because
without it the new ended-reason tally renders empty on a freshly seeded demo while the real path populates it.
Module 3's observable surfaces are **management commands** instead:

- `manage.py simulate_call [--tenant <slug> --location <slug>] [--script chat|booking|transfer]` (3.2) — drives one
  full fake call through the real consumer under `PROVIDER_MODE=fake` (one live `CallSession` per run) and prints
  its finalized transcript/logs/usage/status. **3.5 added the recording block** (consent basis, whether the notice
  announced, retention window, blob path, waveform bin counts) plus a **hard failure** when a row claims
  `recorded` but `recording_exists()` finds no bytes. No new `--script` value: consent/recording/waveform are wired
  into every call's authorize/greet/finalize path, so every existing script already exercises them. Run it against
  locations in different states to see both consent branches (seeded Downtown/Uptown are IL — two-party;
  Riverside/Lakeside are OR/CO — one-party).
- `manage.py purge_expired_recordings [--tenant …] [--location …] [--dry-run]` (3.5) — the retention job. Not a
  seeder: it is maintenance over data other passes write. Per-ROW `metadata['retention_days']`, stamped at teardown
  from the setting in force at call time, so lowering `RECORDING_RETENTION_DAYS` never retroactively expires older
  recordings. Idempotent by construction (`.exclude(recording_blob='')` is both the driving filter and the guard),
  chunked `.iterator()`, file deleted **before** the row is cleared so a storage failure can never orphan bytes the
  row-walking job could not come back for.

If a later runtime sub-module needs seeded demo data, add an idempotent `seed_runtime` then — do not duplicate
CallSession writes across two seeders.

## Conventions & gotchas

- **Tenant AND location come from the dialed number**, resolved via `AgentSetting.inbound_phone_number` — never from
  a query-string or body parameter a caller controls. The diagnostics view scopes by `request.tenant` +
  `request.location`, delegating session queries to the single audited `apps.calls.views._helpers.location_sessions`
  (returns `.none()` when no location is active) rather than a second hand-rolled filter.
- **The `get_backend()` handoff (built, 3.4).** `apps/agents/telephony.py:get_backend()` import-guards for
  `from apps.runtime.providers.telephony import get_backend`. 3.4 now defines it, so Module 2's
  connection-check/test-call **delegate to the runtime backend** — which SUBCLASSES Module 2's Fake/Live backends
  (inheriting `check_connection`/`place_test_call` verbatim, zero behaviour change) and ADDS `redirect_call`. No
  import cycle: `providers/telephony.py` imports `apps.agents.telephony` at module top, while `agents.telephony`
  imports the runtime `get_backend` only *lazily inside its own function*. The runtime backend reports a redirect as
  a boolean `TelephonyResult.ok` and never imports the transfer-outcome vocabulary — the consumer maps `ok` →
  `connected`/`failed`, keeping the provider layer free of the conversation layer. Locked by
  `test_agents_get_backend_delegates_to_runtime_backend`.
- **`CallSession.transfer` has TWO writers, one shape (3.4).** The dispatcher's off-hours path and the consumer's
  `_execute_transfer` both build the record through `agent/transfer.py:build_transfer_record` — the single source
  of truth for `{result, reason, destination, initiated_at, duration_seconds}` (attempts omitted for a single try).
  Never hand-write a second dict literal; the 5.4 reader (`_transfer_outcome.html`) and the calls-app outcome filter
  depend on this exact shape (NOT the stale `voice-agent-runtime` §9.3 `{outcome, destination_kind, at}` wording).
- **Off-hours callback is de-duped per call** via `CallState.offhours_callback_logged` (same single-fire discipline
  as `search_attempts`) — a model calling `transfer_call` repeatedly off-hours logs exactly one `CallbackRequest`.
- **`TWILIO_WEBHOOK_BASE_URL` must be set outside DEBUG.** Signatures are verified against that base + the request
  path; unset, verification falls back to the `Host` header and every real call fails. `apps/runtime/apps.py`
  registers system check **`runtime.E001`** (Error) to surface this at `manage.py check` / deploy time. Inert under
  DEBUG (bare local run with no tunnel is expected).
- **PII discipline:** the webhook logs a closed reason-code set only (`REASON_UNMAPPED`, `REASON_DISABLED`,
  `REASON_SIGNATURE_INVALID`, `REASON_MISSING_CALLSID`, `REASON_DUPLICATE`) — never a caller number, body or
  signature, at any level. `twilio_auth_token` is never rendered, logged or put in a template context.
- **Rate limiting is a tracked deferral** (documented in `webhooks.py`, tracked in `.claude/tasks/todo.md`): a naive
  per-number/per-IP throttle would block legitimate redelivery and concurrent calls; size it against real traffic in
  3.5. The interim abuse surface is bounded (unmapped/disabled = zero writes; forged signature = one indexed lookup
  + HMAC + 403).
- **`caplog` cannot see `apps.*` logs by default** — `config/settings.py` sets `apps` logger `propagate=False`. A
  test that wants to assert log content flips `propagate=True` via `monkeypatch` for the test (see
  `_capture_apps_logs` in `apps/runtime/tests/test_webhook.py`).
- **PROVIDER_MODE fake is the default;** the webhook places no real call (returns TwiML only). Anything not exactly
  `'live'` fails safe to the fake path.

### 3.2 realtime gotchas

- **`thread_sensitive=False` on every consumer ORM call.** `database_sync_to_async(fn)` defaults to
  `thread_sensitive=True`, which runs every sync call on ONE process-global thread (no `ThreadSensitiveContext` on
  the websocket path) — so one call's DB write serializes, and stalls audio for, every concurrent call. Always pass
  `thread_sensitive=False` here.
- **Authorize on the `start` frame, not `connect()`.** Twilio's custom `<Parameter>` values arrive in `start`, so
  `connect()` accepts but does nothing; the token is verified in `receive()`'s `start` branch before any side effect.
- **Channels group names forbid `:`** — use the `.`-separated `group_name()` helper, never the raw colon form.
- **A `WebsocketCommunicator` needs an `Origin` header** (`[(b'origin', b'http://localhost')]`) or
  `AllowedHostsOriginValidator` refuses the socket — the #1 test gotcha (see `apps/runtime/tests/_ws.py`).
- **Audio is `audioop` (stdlib), not numpy** — `mulaw⇄PCM16` + `ratecv`. **Thread the inbound `Resampler` across
  frames** (one instance on the call); a fresh resampler per outbound synthesis. Python 3.10 has `audioop`; it is
  removed in 3.13, a migration-time concern only.
- **`is_open_now` has no location-hours field** — it is the union of `accounts.User.provider_hours` at the location,
  gathered once at connect (`build_open_intervals`) so the per-turn check is a pure in-memory evaluation.
- **A provider timeout is TERMINAL** (`reliability.call_bounded`) — no retry; it fails fast to the spoken fallback.
  Only `RateLimited` (backoff) and transient errors retry. `PROVIDER_TIMEOUT_SECONDS` default is **6**.
- **`MediaStreamConsumer._active_calls`** is a process-global class attribute (the capacity counter) — a test must
  reset it between cases (an autouse fixture in `apps/runtime/tests/conftest.py` does).
- **`simulate_call` uses `asyncio.run`**, so a pytest test invokes it from a SYNC test via `call_command`, never an
  async one.

### 3.3 tool/dispatcher gotchas

- **Never reinvent booking.** `apps/scheduling/availability.py` (4.3) was written *for* these tools — it owns slot
  search, the signed slot tokens, and the race-safe book/reschedule/cancel writes, each re-authorising tenant,
  location and `actor_contact` itself. The dispatcher is a thin wrapper. 3.3's only change to it was threading
  **`booked_by_session=`** through `book_slot()` (additive, keyword-only, no migration) so a booking carries the
  call it was made on.
- **`book_slot` is idempotent by design** — it checks "did this contact already book this slot?" *before* the
  conflict check, so a model retrying a tool call gets the same appointment back instead of being told it failed
  after it actually succeeded. A test asserting a replay ERRORS is testing the wrong thing.
- **`find_available_slots` takes `providers=`/`resources=` POOLS** (plural) as well as the singular pins. Use the
  pools — calling it once per (provider, resource) pair re-runs the same provider-independent window query for
  every pair, mid-call. A pool given but empty means "the filter matched nobody" → no slots, not "everyone".
- **The declaration list and the dispatch table must stay equal** (`TOOL_NAMES == set(TOOL_HANDLERS)`). A
  declared-but-undispatched tool fails silently mid-call. **A repo hook enforces this on edit** — adding a
  declaration without a handler blocks the write.
- **`MAX_OFFERED_SLOTS` is a per-page DISPLAY cap, not a search cap.** Searching with it makes every page after
  the first empty.
- **`set_fake_script` is process-global** (a ContextVar was tried and does NOT reach the ASGI application task).
  It refuses to arm over an existing script; always clear it in a `finally`.

### 3.5 recording/consent gotchas

- **A two-party consent basis is a REQUIREMENT, not a permission.** `CallState.should_record` returns False until
  `consent_announced` is True, so a TTS failure on the notice means the call is not recorded. Do not "simplify" it
  back to `bool(consent_basis)` — recording a two-party call whose disclosure never played is the failure this whole
  sub-module exists to prevent.
- **The consent vocabulary is persisted data shared with Module 5.** `announced_notice` / `one_party_notice` /
  `not_recorded` — `apps/runtime/agent/consent.py` is the authority, `seed_calls` writes the same strings, and
  `apps/accounts/templatetags/ui.py:_CONSENT_BASIS_LABELS` maps them for display. Rename one and old rows stop
  matching; drift here fails **silently** (the label filter falls back to the raw value), so
  `apps/calls/tests/test_ui_filters.py` asserts the map covers every constant.
- **`provider_call_sid` is a path component.** The webhook shape-checks it with `looks_like_call_sid` at ingestion,
  and `recording_path_for` checks it again. `safe_join` guards the `PRIVATE_MEDIA_ROOT` boundary but **not** the
  `private/calls/{tenant}/{location}/` partition inside it, so a `../`-bearing SID would write outside its own
  prefix. Both gates are load-bearing; `apps/runtime/tests/test_webhook.py` regression-covers them.
- **`ENDED_REASON_DISPLAY` (state.py) and `_STATUS_BY_REASON` (the consumer) describe the same closed key set** for
  two different purposes. Add a reason to one and forget the other and it silently falls through the status default
  AND vanishes from the diagnostics tally —
  `test_call_state.test_ended_reason_vocabulary_matches_the_consumer_status_map` is the guard.
- **`recording.py` is deliberately SYNC** while every other adapter here is async. Its one call site
  (`_finalize_session`) is already off-loop via `database_sync_to_async`; making it async would drive an event loop
  from inside a worker thread for no benefit. The module docstring says so — do not "fix" the asymmetry.
- **The waveform is NOT derived from the recorded audio.** It comes from live per-frame DSP energy, which is why an
  early drop still yields genuinely partial-but-real peaks while the fake recorder's stub bytes are unrelated to
  call length. Two independent write paths that merely finalize together.

## Common tasks

- **Run a call end-to-end (3.2):** `venv\Scripts\python.exe manage.py simulate_call` (fake providers, no real call).
  For the live server: `venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application` (never
  `runserver` — it can't serve the websocket). The consumer is `apps/runtime/consumers/MediaStreamTurnLoop/
  MediaStream.py`; the turn loop and prompt/variable rendering are `apps/runtime/agent/`; the adapters are
  `apps/runtime/providers/{audio,vad,reliability,stt,tts,llm}.py`.
- **Exercise the tools end to end (3.3):** `venv\Scripts\python.exe manage.py simulate_call --script booking`
  drives identify → create contact → find slots → book through the REAL dispatcher and booking engine under
  `PROVIDER_MODE=fake`, then prints the tool trace and the appointment it created. `--script chat` is the plain
  one-turn conversation.
- **Add an LLM tool:** declaration dict in `apps/runtime/agent/tools.py` + a dispatcher branch in
  `apply_tool_call` + the `{ok,data,error}` envelope + identity from server state + tests through both runtime paths.
- **Exercise a transfer end to end (3.4):** `venv\Scripts\python.exe manage.py simulate_call --script transfer`
  scripts `transfer_call` through the real consumer to a `transferred`/`connected` session via the FAKE redirect
  (no carrier). The gate lives in `agent/dispatcher.py:_transfer_call` (reuses `apps.agents.services`
  `is_transfer_available`/`resolve_transfer_number` — never reinvent the hours logic); the execution + outcome write
  live in `consumers/…/MediaStream.py:_execute_transfer`; the record shape in `agent/transfer.py`.
- **Extend the diagnostics page:** add to `runtime_diagnostics_view` + `templates/runtime/diagnostics.html`; keep
  every query tenant+location scoped through the audited `location_sessions` helper. **Reuse the shared `recent`
  sample** rather than adding a fourth query for a fourth panel — 3.5's three panels all read one bounded 50-row
  list. If a panel genuinely needs its own read, narrow it (`select_related(None).only(...)`, `.iterator()`) the way
  the uncapped spend-today query does, and update the query-budget test in `apps/runtime/tests/test_diagnostics.py`
  (currently 8) with the reason.
- **Change the recording behaviour (3.5):** the consent basis is `agent/consent.py`; whether a call is recorded at
  all is `CallState.should_record`; where the bytes go is `providers/recording.py` (through
  `apps.calls.storage.save_recording` — never a raw `open()`); when they are deleted is
  `manage.py purge_expired_recordings`. Verify with `manage.py simulate_call --location downtown` (IL → two-party,
  announces) vs `--location riverside` (OR → one-party, no notice).
- **Add a live provider backend:** implement `LiveRecordingBackend.finalize` (it currently `require_live()`s then
  raises `NotImplementedError`, matching `LiveTtsBackend`/`LiveSttBackend`). A live encode/upload crosses the
  network, so wrap it in `providers.reliability.call_bounded` at its call site — the sync interface is correct only
  because the fake's I/O is local.

## Sidebar wiring

`apps/accounts/navigation.py` — `LIVE_LINKS['3.1'] = {'Runtime Diagnostics': 'runtime:diagnostics'}` and
`LIVE_LINKS['3.2'] = {}` (built, no navigable page — the consumer and `simulate_call` are not user surfaces; same
empty-dict posture as `0.1`/`5.2`–`5.4`). What 3.2 makes real is 3.1's existing "active calls" stat, which now
reflects live sessions because `disconnect()` is the first code that moves a session out of `in_progress`. Module 3
shows Live via 3.1's link. `LIVE_LINKS['3.3'] = {}` for the same reason — a tool dispatcher is not a page; what
3.3 makes visible is the `category='tool'` trace it writes into `CallSession.logs`, which Module 5.3's event-log
panel on the call detail page renders. `LIVE_LINKS['3.4'] = {}` for the same reason — transfer execution is
transport behaviour, not a page; what 3.4 makes visible is the `CallSession.transfer` outcome (5.4's transfer card
on the call detail page), the transfer-outcome summary on 3.1's diagnostics page, and `simulate_call --script
transfer`. Pointing 3.4 at `runtime:diagnostics` would just duplicate 3.1's row. `LIVE_LINKS['3.5'] = {}` closes
Module 3 out on the same posture: 3.5 **extends** the diagnostics page 3.1 already links (four new panels) rather
than adding one, and its other surfaces — the recorder inside the consumer's teardown and
`purge_expired_recordings` — are not pages either.

**All five keys `3.1`–`3.5` are present, so Module 3 is fully BUILT.** It shows Live in the sidebar through 3.1's
single link, which is the whole module's navigable surface by design.
