# Research — Sub-module 3.1: Inbound Webhook & Call Resolution (Module 3 — Call Runtime, `runtime`)

## Repo state checked first

- **`LIVE_LINKS` in `apps/accounts/navigation.py`**: Module 3 has **zero** entries (`'3.1'`…`'3.5'` are all absent from
  the dict). 3.1 is the first sub-module built in this module. Every other module (0, 1, 2, 4, 5) is fully built —
  their models are real and groppable, and 3.1 may read them but owns none of them.
- **`apps/runtime/` does not exist yet** — confirmed by `Glob("apps/runtime/**")` returning no files. This research
  targets a brand-new app.
- **Sibling models verified to exist** (grepped, not assumed from the ERD):
  - `agents.AgentSetting` — `apps/agents/models/AgentConfiguration/AgentSettings.py`. Confirmed fields:
    `enabled` (bool), `voice_provider`, `greeting`, `prompt_text`, `variables` (JSON),
    `inbound_phone_number` (CharField, `null=True, blank=True, unique=True` — **globally unique**, normalised to
    `None` in `clean()`/`save()` so `""` never defeats the unique index), `twilio_account_sid`,
    `twilio_auth_token` (`EncryptedCharField`, write-only by convention), `transfer_enabled`,
    `transfer_phone_number`, `transfer_secondary_number`, `transfer_timezone`, `transfer_working_hours`,
    `transfer_keywords`. Unique `(tenant, location)`. Ships `readiness_issues()` / `is_ready` already — 3.1's
    resolver can lean on `enabled` directly without re-deriving readiness.
  - `calls.CallSession` — `apps/calls/models/CallLogList/CallSessions.py`. Confirmed fields:
    `tenant`, `location`, `contact` (FK, `SET_NULL`, null), `channel`, `mode`, `status` (5 choices:
    `in_progress`/`completed`/`abandoned`/`transferred`/`failed`), `from_number`, `to_number` (both indexed),
    `provider_call_sid` (**`unique=True`** — confirmed, this is the idempotency key), `transcript`, `logs`,
    `analysis`, `usage`, `transfer`, `waveform_peaks`, `metadata` (all JSON, Invariant 2's whole surface),
    `recording_blob`, `started_at`, `ended_at`. **No `ModelForm` exists for this model by design** — 5.1 shipped
    list+detail only, confirming Module 5 never writes it; 3.1 is the first writer.
  - `scheduling.Contact` — confirmed to exist (`apps/scheduling/models/ContactDirectory/Contacts.py`), the one
    identity table (Invariant 1). 3.1 does not touch it (no caller is identified before the stream opens).
  - `tenants.Tenant`, `tenants.Location` — confirmed to exist and are what `AgentSetting` and `CallSession` FK.
- **Conclusion for scope:** 3.1 is a **SERVICE sub-module**. It adds **zero models**. Its entire job is to
  populate one already-existing row (`AgentSetting`, read-only here) and create/find one already-existing row
  (`CallSession`, the only write) through a webhook, before any audio ever flows. Modules 3.2–3.5 own the
  websocket, the tools, the transfer bridge and the recording — none of that is built or referenced here except
  to say where this sub-module's outputs hand off to them.

---

## Leaders surveyed (with source links)

1. **Vapi** — telephony-infrastructure platform for voice agents; the closest analogue to this sub-module's exact
   job (bind a Twilio DID to an assistant, answer via webhook, bridge into a media stream with custom params).
   — [Import number from Twilio](https://docs.vapi.ai/phone-numbers/import-twilio),
   [Call Handling with Vapi and Twilio](https://docs.vapi.ai/calls/call-handling-with-vapi-and-twilio),
   [Debugging voice agents](https://docs.vapi.ai/debugging)
2. **Retell AI** — voice-agent platform with a documented Twilio bridge (webhook → TwiML `<Connect><Stream>`) and
   its own webhook signature/idempotency contract.
   — [Connect AI call agent to Twilio](https://www.retellai.com/integrations/twilio),
   [Webhook Overview](https://docs.retellai.com/features/webhook-overview),
   [Custom telephony](https://docs.retellai.com/deploy/custom-telephony)
3. **Bland AI** — webhook-signing (HMAC-SHA256) reference and inbound/outbound number handling docs; useful as
   the "signature scheme varies by vendor, the pattern doesn't" data point.
   — [Webhook Signing](https://docs.bland.ai/tutorials/webhook-signing),
   [Handling Inbound and Outbound Numbers](https://university.bland.ai/modules/2/lesson-4)
4. **Synthflow** — explicitly documents the exact routing invariant this product's `AgentSetting` enforces: "no
   two inbound Assistants can use the same number," plus a Phone Numbers dashboard showing every number's
   assigned agent and active state.
   — [About Phone Numbers](https://docs.synthflow.ai/about-phone-numbers),
   [Phone numbers overview](https://docs.synthflow.ai/docs/phone-numbers-overview)
5. **PolyAI** — enterprise conversational platform; documents number provisioning, SIP trunking and a routing
   dashboard for viewing call data and configuration.
   — [Call Routing](https://poly.ai/use-cases/call-routing)
6. **Goodcall** — AI call-answering product with a real-time analytics dashboard surfacing call performance and
   routing outcomes; representative of the "AI receptionist" competitor set proper (vs. the infra platforms
   above).
   — [Goodcall — enterprise call management](https://www.goodcall.com/voice-ai/best-voice-ai-for-enterprise-call-management)
7. **Twilio** (the carrier this product is built on) — the ground truth for the webhook contract itself:
   signature verification, at-least-once redelivery, and the 15-second response SLA that makes idempotency
   non-optional.
   — [Guide to Twilio Webhooks](https://hookdeck.com/webhooks/platforms/twilio-webhooks-features-and-best-practices-guide),
   [Webhooks FAQ](https://www.twilio.com/docs/usage/webhooks/webhooks-faq)
8. **Telnyx** — an alternative telephony carrier with an Ed25519-based webhook-signing scheme (vs. Twilio's
   HMAC-SHA1), useful for confirming that "verify a provider signature against a per-account secret before any
   side effect" is a carrier-agnostic pattern, not a Twilio-specific one — reinforces that this sub-module's
   verification step must key off **this location's** stored credential, not a hardcoded scheme assumption.
   — [How to Leverage Webhooks](https://support.telnyx.com/en/articles/4334722-how-to-leverage-webhooks)

---

## Feature catalog (this sub-module only)

### Twilio Voice Webhook

- **Single inbound POST endpoint returning `<Connect><Stream>` TwiML** — the webhook answers with a media-stream
  bridge instruction rather than any interactive `<Gather>`/IVR tree · seen in: Vapi, Retell AI, Bland AI,
  Synthflow (all bridge Twilio → their own realtime endpoint this way) · priority: table-stakes · model: none —
  pure view function in `apps/runtime/webhooks.py` · realtime: **live-call hot path** (Twilio expects TwiML back
  promptly; a slow webhook is a failed call, not a slow page) · tool-surface: pure webhook/prompt infra, no LLM
  tool · buildable now (no external dependency beyond Django itself to *return* TwiML).
- **Opaque custom `<Parameter>` passing into the stream** — Vapi's own docs show `<Parameter name="assistantId"
  .../>` / `<Parameter name="metadata" .../>` children of `<Stream>`; Retell instead encodes the agent id as a
  URL path segment. Either shape is "pass an opaque handle, not raw identity fields" · seen in: Vapi, Retell AI ·
  priority: table-stakes · model: none · realtime: hot path · tool-surface: none · **binding constraint from this
  repo's own contract (not optional):** the parameter is a **signed, short-TTL stream token** minted here, never
  `tenant_id`/`location_id`/`session_id` in cleartext — a websocket route that reads those from the URL is a
  cross-tenant vulnerability per Invariant 3 and the realtime skill's §3. Buildable now with Django's own
  `django.core.signing` (no provider dependency).
- **Pre-stream disclosure announcement** — a brief `<Say>` played *before* `<Connect>`, distinct from the
  deterministic in-agent greeting (2.1), for jurisdictions that require an AI-interaction disclosure before any
  interactive dialogue begins at all · seen in: general Twilio IVR pattern, not a named feature of any single
  competitor's docs surveyed, but the shape (`<Say>` then `<Connect>`) is standard TwiML composition available
  today · priority: **REQUIRED where the location's jurisdiction mandates it** (see Compliance section) ·
  model: none (a literal string, not a stored field — see the "deferred" note below on a per-location message) ·
  realtime: hot path, but deterministic (zero LLM tokens, same posture as the greeting) · tool-surface: none ·
  buildable now.

### Signature Verification

- **HMAC-style provider-signature verification before any side effect** — Twilio's `X-Twilio-Signature`
  (HMAC-SHA1 over the exact public URL + sorted POST params, base64), Bland's `X-Webhook-Signature`
  (HMAC-SHA256 hex), Telnyx's `telnyx-signature-ed25519` (public-key, not HMAC) — three different schemes, one
  identical rule: verify against **the resolved account's own secret**, reject before touching the database ·
  seen in: Twilio (the carrier itself), Bland AI, Retell AI (`x-retell-signature`), Telnyx · priority:
  **REQUIRED** — a carrier-mandated security control, not a nice-to-have; an unverified webhook lets anyone who
  guesses the URL forge a call event · model: reuses `agents.AgentSetting` (`twilio_account_sid` +
  decrypted `twilio_auth_token`), resolved **per (tenant, location)** — no new model · realtime: hot path (gates
  every subsequent write) · tool-surface: none — a pure function, `verify_twilio_signature(request, setting)` ·
  buildable now (the verification algorithm itself needs no live Twilio account — it's deterministic HMAC over
  fixed inputs, fully testable with a fake secret under `PROVIDER_MODE=fake`); **integration/later**: confirming
  byte-for-byte behaviour against a real Twilio-delivered request (exact param ordering, exact public URL string)
  is only provable once a real tunnel + real Twilio number exists.
- **Per-location (not per-platform) secret resolution** — this product's threat model is stronger than most
  single-tenant integrations shown in the competitor docs above (which typically verify against one global
  account secret): here, each location may run its **own** Twilio subaccount, so the verifying secret must be
  **the resolved row's own token**, not a shared platform token · priority: differentiator (a direct consequence
  of this product's multi-location design, not something the surveyed single-account tutorials needed to solve) ·
  model: reuses `AgentSetting` · realtime: hot path · tool-surface: none · buildable now.
- **Fallback to a platform-level token when the location has none configured** — a graceful-degradation path
  already anticipated in `voice-agent-runtime` SKILL §2.2 · priority: common · model: reuses `AgentSetting`,
  reads `.env` platform default as fallback only · buildable now.
- **Exact-public-URL matching as the single most common failure mode** — Retell's and Vapi's own troubleshooting
  guidance repeatedly comes back to "double-check the exact webhook URL" when signature verification appears
  broken; a dev tunnel (ngrok) URL drifting from the configured `TWILIO_WEBHOOK_BASE_URL` fails verification and
  *looks like* a broken agent rather than a URL mismatch · priority: common (a documented gotcha across every
  platform surveyed, not a feature to build so much as a diagnostic to surface — see the observability group
  below) · tool-surface: none.

### Dialed-Number Resolution

- **Single-lookup number → tenant + location + agent-config resolution** keyed on the dialed E.164 number ·
  seen in: Vapi (`assistantId` bound to a number), Retell AI (agent id resolved from the number/URL), Synthflow
  (number ↔ exactly one inbound assistant) · priority: table-stakes · model: reuses `agents.AgentSetting`
  (`inbound_phone_number`, confirmed globally unique) — no new model · realtime: hot path, and it is the **very
  first** resolution step: everything downstream (tenant, location, signature secret, greeting, prompt) is
  derived from this one row · tool-surface: none — a plain resolver function, and this is exactly where
  Invariant 3's "server owns identity" begins: once resolved, `tenant_id`/`location_id` become server-held state
  for the rest of the call and are **never** re-derived from anything the caller says or the model produces ·
  buildable now.
- **Enforced one-inbound-number-per-agent uniqueness** — Synthflow's docs state this as an explicit product rule
  ("no two inbound Assistants can use the same number") · priority: table-stakes · model: already satisfied —
  `AgentSetting.inbound_phone_number` carries `unique=True` today; this sub-module needs zero additional
  enforcement, only to rely on `.get()` (which naturally raises `DoesNotExist` for an unmapped number and cannot
  return two rows for one dialed number).
- **Enabled/disabled gating on the resolved row** — most competitors let an operator pause a number without
  un-assigning it (Synthflow's active/inactive toggle, Vapi's assistant-level enable) · priority: common ·
  model: reuses `AgentSetting.enabled` · realtime: hot path · tool-surface: none · this is the fork point between
  the two failure paths in "Unmapped-Number Handling" below (no row at all vs. a row with `enabled=False`).
- **The resolver is a shared artefact, not webhook-only code** — `voice-agent-runtime` SKILL §3 requires the
  *consumer* to re-resolve and re-check "the number is still served and the agent still enabled" at the `start`
  frame, so a number disabled between webhook-answer and stream-connect never gets served. That re-check reuses
  **this sub-module's** resolver function; it does not duplicate the lookup logic. (The re-check call site itself
  is 3.2's, noted under "Belongs to sibling sub-modules.")

### Idempotent Handling

- **Provider-call-SID as the idempotency key, unique-constrained** — Twilio's own guidance states at-least-once
  delivery and recommends `CallSid` (+ status) as the dedup key; Retell's webhook docs recommend `event` +
  `call_id`; Bland's webhook path is signature-gated the same way · seen in: Twilio (the carrier), Retell AI ·
  priority: **REQUIRED** — Twilio *will* redeliver in production, not a hypothetical · model: reuses
  `calls.CallSession.provider_call_sid`, confirmed `unique=True` in the grepped model — no new model ·
  realtime: hot path (must resolve within the single webhook request, not asynchronously) · tool-surface: none.
- **Race-safe get-or-create, not a bare existence check** — two near-simultaneous redeliveries of the same
  `CallSid` must not both pass a `.filter().exists()` check and then both `.create()`; the pattern is
  `get_or_create` backstopped by the DB unique constraint, catching `IntegrityError` on the losing writer and
  re-fetching rather than trusting a single unguarded check-then-write · priority: table-stakes engineering
  detail (this is the exact case Twilio's blog calls out — "retries can produce duplicates") · model: reuses
  `CallSession` · buildable now (pure Django transaction logic, no external dependency).
- **A redelivery must return the same TwiML, not open a second stream** — once a `CallSession` for this `CallSid`
  already exists, the webhook returns the same `<Connect><Stream>` response (or, if the session already
  finished, a terminal response) rather than minting a second stream token/session for a call already in
  progress · priority: table-stakes · tool-surface: none.

### Unmapped-Number Handling

- **A spoken decline plus a clean hangup, never silence** — this is the product's own bulleted requirement
  and also the researched norm: every surveyed platform's failure mode when a number is mis-provisioned is *some*
  spoken or DTMF-tone response, never dead air (Twilio's own "application error" tone is the example of what
  *not* to reproduce — every AI-receptionist competitor's docs push the integrator toward a graceful fallback
  instead) · priority: **REQUIRED** (directly named in this sub-module's own bullet, and it is the product's core
  promise — a business's caller must never hear nothing) · model: none for the decline itself (a canned TwiML
  `<Say>` + `<Hangup>`) · realtime: hot path, deterministic, zero LLM tokens · tool-surface: none · buildable now.
- **Disabled-vs-truly-unmapped is a real distinction worth keeping** — a number with **no** `AgentSetting` row at
  all has no tenant/location to attribute anything to (log it at the platform level only); a number that *does*
  resolve to a row but with `enabled=False` has a known tenant + location, so the missed-call attempt is
  meaningful business information for that tenant (analogous to how human-receptionist services like the ones in
  this domain report "missed while paused" distinctly from "wrong number," since a business specifically wants
  to know it missed a call because its own agent was switched off) · priority: differentiator (a genuine
  research finding, not a guess — most infra platforms treat both cases as an equally opaque error) ·
  model: reuses `calls.CallSession` for the disabled-but-known case only (`tenant`, `location` both resolvable) —
  written with `status='failed'`, `from_number`/`to_number` set, no transcript, a `logs` entry explaining why;
  the truly-unmapped case writes **no** `CallSession` row (there is no tenant/location to satisfy the model's
  non-nullable FKs) — it goes to the structured application log only · realtime: hot path decision, the resulting
  write is not itself latency-sensitive (the call is ending regardless) · tool-surface: none.
- **A configurable per-number decline message** — Synthflow and Vapi both allow a custom message for an
  inactive/paused number · priority: common among leaders, but **deferred here** — for the truly-unmapped case
  there is no row to hold a custom string on, and for the disabled case adding one means a new field on
  `AgentSetting`, which is a 2.1/2.2 decision, not this sub-module's to make unasked. Ship one platform-level
  constant message for both cases in this pass; revisit only if a later sub-module adds the field.

### Beyond the bullets

- **Number-to-location mapping status view** — Synthflow's "Phone Numbers" tab (every number, its assigned
  agent, active/inactive) and Vapi's phone-numbers dashboard are the direct analogue of the **observable surface**
  this service sub-module is required to ship · priority: table-stakes among the infra platforms surveyed ·
  model: reuses `agents.AgentSetting` — a **read-only** listing (`inbound_phone_number`, `enabled`,
  `tenant`/`location`, `twilio_connected`) — zero new models · realtime: post-call/administrative, not hot path ·
  tool-surface: pure UI · this is the concrete shape of 3.1's mandated `LIVE_LINKS["3.1"]` surface.
- **Webhook delivery / verification health log** — Vapi's "Webhook Logs" (delivery attempts + response codes)
  and Retell's documented retry/timeout behaviour (10 s timeout, up to 3 retries) are the analogue of a small,
  structured per-attempt log this sub-module should keep: resolved tenant/location (or "unmapped"), signature
  result, response status, at what stage it terminated · priority: common · model: none — an application-level
  structured log entry (Python `logging`, not a DB row); reading it back is the diagnostics surface above ·
  realtime: written synchronously during the hot path, **read** post-call/administrative.
- **A closed reason-code set for "why didn't this number answer"** — Vapi documents call-end reasons for the
  in-call case; this sub-module's pre-stream equivalent is its own small, concrete, buildable-now enum:
  `unmapped`, `disabled`, `signature_invalid`, `duplicate_delivery`, `provider_error` · priority: differentiator
  (genuinely useful and cheap — a plain Python constant list, no provider dependency) · model: none · tool-surface:
  none (server-side only, never caller-facing) · this is what turns the health log above from "an error happened"
  into "here is exactly which of five things happened."
- **Live/active-call count on a dashboard** — Retell's "Live Monitoring" and Vapi's in-progress call view ·
  priority: differentiator, but **mostly belongs to 3.2/3.5** (it needs the consumer's live state, which does not
  exist until the media-stream sub-module is built). 3.1's own contribution is only that a `CallSession` row with
  `status='in_progress'` now exists for a later diagnostics page to count — noted here so it isn't lost, scoped
  to 3.5 below.

---

## Compliance & provider constraints

- **Signature verification and idempotency are non-negotiable, carrier-mandated controls** (see REQUIRED entries
  above) — they are not a compliance obligation in the legal sense (no HIPAA/GDPR angle at this layer), but
  CLAUDE.md's own hard security rules treat them with the same non-optional weight, so they are marked REQUIRED
  in this catalog rather than table-stakes.
- **Twilio's ~15-second webhook response SLA** is a hard provider constraint on this sub-module specifically: the
  webhook view must return TwiML promptly (signature verification, the number lookup and the `CallSession`
  get-or-create all happen synchronously inside one request-response cycle) — any slow step here (a blocking
  external call, a lock held too long) is a **failed inbound call**, not a slow page load.
- **At-least-once delivery is a documented Twilio guarantee, not a rare edge case** — the idempotency behaviour
  above must be exercised by tests that simulate a genuine redelivery (same `CallSid`, second POST), because in
  production this *will* happen (a slow first response, a network blip, Twilio's own retry policy).
- **AI-interaction disclosure** — where the location's jurisdiction requires disclosure that the caller is
  speaking with an AI system, that disclosure must occur at or before the first interactive turn. This
  sub-module's webhook response is one legitimate place to satisfy it (a pre-`<Connect>` `<Say>`), and it must
  not be *prevented* from doing so — but the actual spoken content is either a platform-level constant (this
  pass) or eventually part of `AgentSetting.greeting` rendering (2.1/3.2's territory). Marked **REQUIRED** in the
  feature catalog above wherever jurisdiction mandates it; **not deferred**.
- **Recording consent (two-party-consent announcement, HIPAA/GDPR retention) is explicitly NOT this sub-module's
  concern** — no recording exists before the stream opens, so there is nothing to gate here. This is a genuine
  scope boundary, not a deferral of a compliance obligation this sub-module actually touches: 3.5 owns the
  consent-gated recorder, the announcement and the retention window. Naming it here only to be explicit that its
  absence in this file is deliberate, per the "belongs to a sibling sub-module" rule, not an oversight.
- **Cost implication:** this sub-module appends **nothing** to `calls.CallSession.usage` — no LLM/STT/TTS cost
  line originates before the stream connects. Twilio itself begins metering the call leg the moment it is
  answered (voice-minute billing starts at answer, independent of whether a stream ever opens), which is a
  provider-cost fact worth knowing but not one this application meters anywhere (per the ERD's "derived, never
  stored" table — there is no `minutes_used` counter in this product). The unmapped/disabled decline path
  therefore still incurs a small Twilio answer-and-hangup cost even though it produces no `CallSession.usage`
  entry; that is expected and not a bug.
- **Twilio rate limits / concurrency**: no per-number concurrency cap is enforced by this sub-module itself (that
  belongs to the per-call cost ceilings in 3.2/3.5 — max duration, max turns); 3.1's only rate-sensitive surface
  is the webhook endpoint itself, which should be rate-limited per the realtime skill's §2.7 ("webhook handlers
  … are rate-limited"), guarding against a flood of forged/retried requests rather than legitimate concurrent
  calls.

---

## Recommended build scope (this pass)

**This is a SERVICE sub-module — zero models, zero migrations attributable to 3.1.** It reuses two already-built
models read-only/write-once respectively (`agents.AgentSetting` read, `calls.CallSession` written) and adds no
table of its own. The build scope is the following behaviours/guarantees, plus one observable surface:

- **The voice webhook view** (`apps/runtime/webhooks.py: voice_webhook`) — `POST`-only, `@csrf_exempt` paired with
  mandatory signature verification, returns `application/xml` TwiML, never a redirect.
- **The signature-verification function** — HMAC-SHA1 over the exact public URL + sorted POST params, base64,
  `hmac.compare_digest`, using the **resolved location's** `twilio_account_sid`/`twilio_auth_token` (decrypted),
  falling back to a platform token from `.env` only when the location has none. Invalid/missing → `403`, zero
  writes, before the number lookup even runs.
- **The dialed-number resolver** — a single function resolving `To`/`Called` → `agents.AgentSetting` via
  `inbound_phone_number`, shared by this webhook and (later) 3.2's `start`-frame re-check. Returns "no row" and
  "row but disabled" as two distinguishable outcomes, not one generic failure.
- **Idempotent `CallSession` creation** — race-safe get-or-create keyed on `provider_call_sid`, backstopped by
  the model's existing unique constraint; a redelivery of the same `CallSid` returns the same TwiML rather than
  minting a second session or a second stream token.
- **The signed, short-TTL stream token** — minted here (Django's `core.signing`, single-session scope), embedded
  as an opaque `<Parameter>` in `<Connect><Stream>`, never carrying `tenant_id`/`location_id`/`session_id` in
  cleartext. This is what 3.2's consumer will verify in `connect()` — 3.1 only mints it, never redeems it.
- **The unmapped/disabled decline path** — a canned `<Say>`+`<Hangup>` TwiML response; the disabled-but-known case
  additionally writes one minimal `CallSession` (`status='failed'`, no transcript) so that location's call history
  shows the missed attempt; the truly-unmapped case writes only a structured application log line (no tenant to
  attribute a `CallSession` row to).
- **A closed reason-code set** for why a webhook attempt did not reach the stream: `unmapped`, `disabled`,
  `signature_invalid`, `duplicate_delivery`, `provider_error` — logged per attempt, read back on the diagnostics
  surface below.
- **The observable surface** (required of every service sub-module, per CLAUDE.md and the realtime skill §15):
  a lightweight `templates/runtime/overview.html` (or `diagnostics.html`, whichever this pass's `todo` names it)
  showing, **for the active tenant + location**: this location's number-mapping status (bound number, enabled/
  disabled, Twilio-connected), and a short recent-webhook-attempts list with its reason code. This is intentionally
  the seed of the fuller diagnostics page 3.5 later extends with per-stage latency and ended-reason codes across
  the whole call — 3.1 does not build that full page, only its own slice of it. Wired with a
  `LIVE_LINKS["3.1"]` entry.
- **`PROVIDER_MODE` resolution for this sub-module**: in `fake`/`sandbox` mode, signature verification runs
  against a fixed test secret and never contacts Twilio; the webhook path is fully exercisable by tests and by an
  idempotent seeder/management command without any real credentials. The `live` path additionally requires the
  resolved location to actually have `twilio_account_sid`/`twilio_auth_token` set — a missing credential in live
  mode is the hard failure, not a silent no-op.
- **Tests**: valid signature → 200 + expected TwiML; invalid/absent signature → 403, zero `CallSession` rows
  created; duplicate delivery (same `CallSid`) → exactly one `CallSession`; unmapped number → decline TwiML, no
  `CallSession`; disabled number → decline TwiML + one `failed` `CallSession`; malformed payload → 4xx, never 500;
  the signature is checked against the **resolved location's** credentials, never a global token.
- **Seeder**: extend the idempotent seeder path (or a small management command) to exercise the webhook end to
  end under `PROVIDER_MODE=fake` — POST a synthetic Twilio-shaped request through Django's test client/
  `RequestFactory`, proving a `CallSession` is created, and that a repeat POST does not create a second one.

Deferred to later sub-modules, so nothing here is lost: the media-stream consumer that actually redeems the
stream token and opens audio (3.2); the tool declarations and dispatcher (3.3); transfer execution (3.4);
recording, consent, waveform/cost capture and the *full* diagnostics page with per-stage latency (3.5).

---

## Belongs to sibling sub-modules (parked, not scoped here)

- ASGI media-stream consumer, audio codec chain, VAD/barge-in, the `start`-frame re-check that redeems the stream
  token and re-validates the number is still served → **3.2**
- Tool declarations, the `apply_tool_call` dispatcher, the `{ok, data, error}` envelope, the twelve-tool surface →
  **3.3**
- Deferred transfer signal, working-hours gating, the actual REST redirect to a human → **3.4**
- Consent-gated recording, the two-party-consent announcement content and its `logs` proof, waveform peaks,
  per-turn cost capture, the *full* runtime diagnostics page (per-stage latency, ended-reason codes across the
  whole call, active-session count, worker health) → **3.5**
- A per-location custom "closed"/"paused" spoken message (would need a new field on `agents.AgentSetting`) →
  **2.1/2.2**, not this sub-module's to add unasked
- Live/active-call count and worker health on a dashboard → mostly **3.5** (needs consumer state 3.1 has no
  access to); 3.1 only supplies the `in_progress` `CallSession` row such a page will later count

## Out of scope for this product (outside the seven capabilities)

- **Outbound call origination / campaign dialing** — this product is inbound-only end to end; the telephony
  adapter interface itself has no dial-out method by design (per the realtime skill §12).
- **SMS/messaging webhooks** — no SMS capability exists among the seven capabilities; several competitors
  surveyed (Vapi's inbound-SMS docs, Bland's SMS webhook) support it, but this product does not.
- **Multi-channel routing (web chat, WhatsApp, etc.)** — telephony-only; not one of the seven capabilities.
- **A number marketplace / DID purchase workflow inside the app** — 2.2 (Twilio Connection) only binds a number
  the tenant already owns in their own Twilio account; buying/porting a new number is a Twilio-console task, not
  a page in this product.
- **Carrier-agnostic multi-provider ingress (Telnyx, Vonage) at this layer** — the ERD and this product commit to
  Twilio; Telnyx's Ed25519 scheme was researched only to confirm the verification *pattern* is carrier-agnostic,
  not to propose supporting a second carrier here.

## Deferred (later passes / integrations)

- **Live-mode signature verification against a real Twilio account** — the algorithm is buildable and fully
  testable now against a fixed fake secret; proving it byte-for-byte against a real Twilio-delivered request
  needs a real number + ngrok tunnel, which is an integration exercise, not a code gap.
- **A per-location custom unmapped/disabled decline message** — deferred until a later sub-module decides to add
  a field for it on `AgentSetting`; this pass ships one platform-level constant message for both cases.
- **The full runtime diagnostics page** (per-stage latency, ended-reason codes spanning the whole call, active
  session count, worker health) — 3.1 ships only its own routing/webhook-health slice; 3.5 is where the page
  gains the rest.
- **Rate-limiting tuning** for the webhook endpoint — a bounded limiter is expected per the realtime skill, but
  the exact threshold is an operational tuning decision to make once real traffic patterns exist, not a research
  finding to hard-code now.
