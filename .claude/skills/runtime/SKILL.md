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
| 3.2 | Media Stream & Turn Loop | not built — the Channels consumer, audio codec chain, VAD/barge-in, off-loop work, bounded provider calls |
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
  (Invariant 2: one call log, JSON columns, no second table). The consumer (3.2) finalizes it in `disconnect()`.

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
  routing.py         FLAT — websocket_urlpatterns = [] (STUB; media route + asgi wiring land in 3.2)
  providers/
    base.py          PROVIDER_MODE resolution: active_mode()/is_live()/require_live()/LiveModeError (fail-safe)
    telephony.py     PURE Twilio helpers: webhook_public_url, media_stream_ws_url, verify_twilio_signature,
                     build_stream_twiml, build_decline_twiml. NO get_backend() — see gotchas.
    tokens.py        signed short-TTL opaque stream token: mint_stream_token / verify_stream_token
  views/
    _common.py       re-exports apps.accounts.views._common
    _helpers.py      recent_location_sessions(request) — delegates to apps.calls.views._helpers.location_sessions
    InboundWebhook/Diagnostics.py   runtime_diagnostics_view
  urls/
    InboundWebhook/Webhook.py       /runtime/voice/
    InboundWebhook/Diagnostics.py   /runtime/diagnostics/
```

## Tools & prompt surface

**None yet.** The LLM tool declarations, the `apply_tool_call(state, name, args)` dispatcher and prompt-variable
rendering arrive with 3.3 (`apps/runtime/agent/`). When they do: identity args (`tenant_id`, `location_id`,
`contact_id`, `session_id`) come from server-side session state, **never** as tool parameters (Invariant 3); every
tool returns the one envelope `{"ok", "data", "error"}` with lower_snake_case codes; the prompt names no tool.

## Realtime surfaces

- **Webhook ingress (built, 3.1)** — `apps/runtime/webhooks.py`. The one place tenant + location are discovered
  from scratch, from the dialed number only. Signature verified against **that resolved row's** per-location
  `twilio_auth_token` (via `providers.telephony.verify_twilio_signature`, Twilio's `RequestValidator`, constant-time)
  **before any side effect**; `@csrf_exempt` is paired with it. Idempotent on `provider_call_sid`. Returns
  `<Connect><Stream>` TwiML (`application/xml`, never a redirect) carrying the **opaque signed stream token** — never
  cleartext tenant/location ids.
- **Stream token** — `providers/tokens.py`. The media stream has no session and no user; this signed, short-TTL
  (300s) token IS its credential. Payload `{sid, ten, loc}` lives *inside* the signed blob. The 3.2 consumer will
  `verify_stream_token()` in `connect()` and resolve identity FROM it, never from the websocket URL.
- **routing.py is an empty stub; `config/asgi.py` is NOT wired.** The `wss://…/ws/media-stream/` route and its asgi
  wiring belong to 3.2. First-match-wins applies across the whole concatenated `URLRouter` list.
- **Group-naming is unresolved and deferred to 3.2:** CLAUDE.md says `t{tenant_id}:l{location_id}:call:{session_id}`
  while `voice-agent-runtime` §3 says `t{tenant_id}:call:{session_id}`. 3.1 introduces no group; reconcile these when
  the consumer joins one.

## Seeder

**None.** 3.1 adds no data of its own; the diagnostics page reads the `calls.CallSession` rows that `seed_calls`
already creates (through the fake provider). If a later runtime sub-module needs its own demo data, add an
idempotent `seed_runtime` then — do not duplicate CallSession writes across two seeders.

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

## Common tasks

- **Add the media consumer (3.2):** create `apps/runtime/consumers/<SubModule>/<Entity>.py`, re-export it in
  `consumers/__init__.py`, add its `path()` to `routing.py`, and wire `apps.runtime.routing.websocket_urlpatterns`
  into `config/asgi.py`. `connect()` authorizes via `verify_stream_token()` (never the URL), resolves
  tenant+location+CallSession from it, joins a tenant-namespaced group, and uses `database_sync_to_async` for every
  ORM touch. Follow `/voice-agent-runtime` §3–§5 exactly.
- **Add an LLM tool (3.3):** declaration dict in `apps/runtime/agent/tools.py` + a dispatcher branch in
  `apply_tool_call` + the `{ok,data,error}` envelope + identity from server state + tests through both runtime paths.
- **Add transfer execution (3.4):** the deferred-signal flow (`/voice-agent-runtime` §9) and the telephony
  `get_backend()` with `redirect_call`/`hangup`, at which point `apps/agents/telephony.py` starts delegating to it.
- **Extend the diagnostics page (3.5):** add to `runtime_diagnostics_view` + `templates/runtime/diagnostics.html`;
  keep every query tenant+location scoped through the audited helper.

## Sidebar wiring

`apps/accounts/navigation.py` — `LIVE_LINKS['3.1'] = {'Runtime Diagnostics': 'runtime:diagnostics'}`. Module 3 shows
Live in the sidebar via this one entry; 3.2–3.5 add their own entries as they are built.
