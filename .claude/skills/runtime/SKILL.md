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
| 3.3 | Tools & Dispatcher | not built — `apply_tool_call`, the 12-tool set, signed slot tokens, the `{ok,data,error}` envelope |
| 3.4 | Transfer Execution | not built — deferred transfer signal, hours/target gating, the telephony `get_backend()` handoff |
| 3.5 | Recording, Teardown & Diagnostics | not built — consent-gated recording, teardown, waveform/cost capture, the fuller diagnostics page |

## Models

**None.** This app has no `models/` package and no migrations (`makemigrations runtime` → "No changes detected" is
the acceptance signal). It touches two existing models:

- **Reads** `agents.AgentSetting` — resolved by the globally-unique `inbound_phone_number`; provides tenant,
  location, `enabled`, `voice_provider`, `twilio_account_sid`, and the encrypted `twilio_auth_token` (decrypted
  transparently on read via `EncryptedCharField`).
- **Writes** `calls.CallSession` — one row per call, created by the webhook keyed on the unique `provider_call_sid`
  (Invariant 2: one call log, JSON columns, no second table). **3.2's consumer is the first writer of the JSON
  columns** — it appends `transcript`/`logs`/`usage` at per-turn checkpoints and, in `disconnect()`, stamps
  `ended_at` + a terminal `status` (`completed`/`abandoned`/`failed`; `transferred` is 3.4's) and
  `metadata.ended_reason`. `makemigrations runtime` → "No changes detected" still holds (3.2 adds no model).

## URLs / routes

`urls/__init__.py` sets `app_name='runtime'` and concatenates entity urlpatterns.

| Name | Path | View | Notes |
|---|---|---|---|
| `runtime:voice_webhook` | `/runtime/voice/` | `apps/runtime/webhooks.py:voice_webhook` | POST-only, `@csrf_exempt` + signature-verified. **Module 2's live test call hardcodes this exact URL** (`apps/agents/telephony.py`) — do not move it. |
| `runtime:diagnostics` | `/runtime/diagnostics/` | `views.runtime_diagnostics_view` | `@login_required` GET; the observable surface + `LIVE_LINKS['3.1']`. |

## Templates

- `templates/runtime/diagnostics.html` — standalone page (service module, no CRUD entity folders). Extends
  `base.html`, `{% load ui %}` for `phone_e164`. PROVIDER_MODE banner (`role=status`/`role=alert`), stat cards
  (active / total / agent-ready), a recent-calls table using `partials/_call_status_badge.html`, an inbound-routing
  card showing the webhook URL to configure in Twilio + the media-stream `wss://` URL, and a readiness-issues card.
  Guidance empty-state when there is no active location. Never `|safe`s caller data.

## Backend package layout (as built)

```
apps/runtime/
  apps.py            RuntimeConfig(name='apps.runtime', label='runtime'); registers system check runtime.E001
  admin.py           empty (no models — documented)
  webhooks.py        FLAT — voice_webhook(request): the whole 3.1 contract
  routing.py         FLAT — websocket_urlpatterns = [path('ws/media-stream/', MediaStreamConsumer.as_asgi())] (3.2)
  providers/
    base.py          PROVIDER_MODE resolution: active_mode()/is_live()/require_live()/LiveModeError (fail-safe)
    telephony.py     PURE Twilio helpers: webhook_public_url, media_stream_ws_url, verify_twilio_signature,
                     build_stream_twiml, build_decline_twiml. NO get_backend() — see gotchas.
    tokens.py        signed short-TTL opaque stream token: mint_stream_token / verify_stream_token
    audio.py         (3.2) μ-law⇄PCM16 codec, stateful inbound Resampler, iter_mulaw_frames, PlaybackTracker — pure DSP
    vad.py           (3.2) energy VAD/endpointing, sustained-speech barge-in, echo guard — named constants + VadState
    reliability.py   (3.2) call_bounded(): timeout + retry, RateLimited(backoff) vs transient; timeout is TERMINAL
    stt.py           (3.2) SttBackend + FakeSttBackend + LiveSttBackend + get_stt_backend() — transcribe(pcm,rate)->str
    tts.py           (3.2) TtsBackend + FakeTtsBackend + LiveTtsBackend + get_tts_backend() — synthesize(text)->(pcm,rate)
    llm.py           (3.2) LlmBackend + FakeLlmBackend + LiveLlmBackend + get_llm_backend() — generate(hist,sys,tools)
  agent/             (3.2) the conversation brain — imported by the consumer, kept apart from transport/providers
    state.py         CallState dataclass — identity (from token only), history, buffered transcript/log/usage, seams
    prompt.py        render_template / build_variables (full runtime var set) / is_open_now / render_greeting
    turn.py          run_turn() — STT→history→LLM(tool-cap seam)→TTS; ProviderBundle, TurnResult, tts_only_cost
  consumers/         (3.2) fifth backend layer — <SubModule>/<Entity>.py, re-exported in __init__
    MediaStreamTurnLoop/MediaStream.py   MediaStreamConsumer (connect/receive/disconnect + group_name())
  management/commands/simulate_call.py   (3.2) observable surface — drives a full fake call through the real consumer
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

**Tools — still NONE (3.3's job).** The turn loop calls the LLM with `tools=[]` inside a bounded iteration loop
(`MAX_TOOL_ITERATIONS`); the dispatcher branch and the `{ok,data,error}` envelope are documented no-op seams. When
3.3 lands: identity args (`tenant_id`, `location_id`, `contact_id`, `session_id`) come from server state, **never**
as tool parameters (Invariant 3); the prompt names no tool. The `apply_tool_call(state, name, args)` dispatcher and
the 12-tool declarations go in `apps/runtime/agent/` alongside the existing `prompt.py`/`turn.py`.

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

## Seeder

**None.** Neither 3.1 nor 3.2 adds data of its own; the diagnostics page reads the `calls.CallSession` rows that
`seed_calls` already creates (through the fake provider). 3.2's observable surface is instead a **management
command** — `manage.py simulate_call [--tenant <slug> --location <slug>]` drives one full fake call through the real
consumer under `PROVIDER_MODE=fake` (creating one live `CallSession` per run) and prints its finalized
transcript/logs/usage/status. If a later runtime sub-module needs seeded demo data, add an idempotent `seed_runtime`
then — do not duplicate CallSession writes across two seeders.

## Conventions & gotchas

- **Tenant AND location come from the dialed number**, resolved via `AgentSetting.inbound_phone_number` — never from
  a query-string or body parameter a caller controls. The diagnostics view scopes by `request.tenant` +
  `request.location`, delegating session queries to the single audited `apps.calls.views._helpers.location_sessions`
  (returns `.none()` when no location is active) rather than a second hand-rolled filter.
- **No `get_backend()` in `providers/telephony.py` (deliberate).** `apps/agents/telephony.py:get_backend()`
  import-guards for `from apps.runtime.providers.telephony import get_backend` and catches `ImportError`. Because
  3.1 does not define that name, Module 2 keeps using its own fake/live backends unchanged. The real backend handoff
  — with `redirect_call`/`hangup` — lands in **3.4**. Defining `get_backend()` prematurely silently reroutes Module
  2's connection-check/test-call through a backend that cannot place a call. Locked by
  `test_agents_get_backend_still_falls_through_to_fake`.
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

## Common tasks

- **Run a call end-to-end (3.2):** `venv\Scripts\python.exe manage.py simulate_call` (fake providers, no real call).
  For the live server: `venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application` (never
  `runserver` — it can't serve the websocket). The consumer is `apps/runtime/consumers/MediaStreamTurnLoop/
  MediaStream.py`; the turn loop and prompt/variable rendering are `apps/runtime/agent/`; the adapters are
  `apps/runtime/providers/{audio,vad,reliability,stt,tts,llm}.py`.
- **Add an LLM tool (3.3):** declaration dict in `apps/runtime/agent/tools.py` + a dispatcher branch in
  `apply_tool_call` + the `{ok,data,error}` envelope + identity from server state + tests through both runtime paths.
- **Add transfer execution (3.4):** the deferred-signal flow (`/voice-agent-runtime` §9) and the telephony
  `get_backend()` with `redirect_call`/`hangup`, at which point `apps/agents/telephony.py` starts delegating to it.
- **Extend the diagnostics page (3.5):** add to `runtime_diagnostics_view` + `templates/runtime/diagnostics.html`;
  keep every query tenant+location scoped through the audited helper.

## Sidebar wiring

`apps/accounts/navigation.py` — `LIVE_LINKS['3.1'] = {'Runtime Diagnostics': 'runtime:diagnostics'}` and
`LIVE_LINKS['3.2'] = {}` (built, no navigable page — the consumer and `simulate_call` are not user surfaces; same
empty-dict posture as `0.1`/`5.2`–`5.4`). What 3.2 makes real is 3.1's existing "active calls" stat, which now
reflects live sessions because `disconnect()` is the first code that moves a session out of `in_progress`. Module 3
shows Live via 3.1's link; 3.3–3.5 add their own entries as they are built.
