# Research — Sub-module 3.4: Transfer Execution (Module 3 — Call Runtime, `runtime`)

## Repo state checked first

- **`LIVE_LINKS` built so far in Module 3:** `3.1` → `{'Runtime Diagnostics': 'runtime:diagnostics'}`; `3.2` → `{}`
  (media consumer, no page of its own); `3.3` → `{}` (tool dispatcher, no page of its own). No `3.4` key exists yet
  — this is the next unbuilt sub-module in the module, confirmed against the live dict at
  `apps/accounts/navigation.py`.
- **Sibling models/fields verified to exist (grep evidence, not the ERD):**
  - `agents.AgentSetting` (`apps/agents/models/AgentConfiguration/AgentSettings.py`) — one row per `(tenant,
    location)`, carries `transfer_enabled`, `transfer_phone_number`, `transfer_secondary_number`,
    `transfer_timezone` (default `America/Chicago`), `transfer_working_hours` (JSON
    `{weekday: {enabled, start, end}}`), `transfer_keywords` (JSON list, **additive** to a runtime built-in set),
    plus `twilio_account_sid` / encrypted `twilio_auth_token` / globally-unique `inbound_phone_number`.
  - `apps/agents/services.py` (2.3, already built and **pure**) already ships `is_transfer_available(setting,
    now=)`, `next_transfer_window(setting, now=)`, `resolve_transfer_number(setting, target='primary'|'secondary')`
    and `matches_transfer_keyword(utterance, setting=None)`. **These are hot-path-safe pure functions 3.4 should
    call, not reimplement.** Confirmed: `is_transfer_available` currently checks only `transfer_enabled` +
    non-blank `transfer_phone_number` + the working-hours window — it is not yet invoked anywhere under
    `apps/runtime/`.
  - `apps.runtime.agent.dispatcher._transfer_eligible` (3.3, already built) checks **only** `transfer_enabled` +
    a non-blank destination field — **it does not call the hours gate at all**. Its own docstring says so:
    *"The working-hours gate, the single-fire guard, the drain interval and the actual Twilio redirect are 3.4's,
    executed by the transport after this turn's audio has finished playing."* This is 3.4's primary as-built seam.
  - `apps.runtime.agent.state.CallState.pending_transfer: str = None` (3.2/3.3, already built) — set to
    `'human'` or `'spanish'` by the dispatcher; nothing under `apps/runtime/consumers/` reads it yet. Confirmed by
    reading the whole `_run_turn` method in `MediaStream.py`: after playback there is a `pending_hangup` branch
    (3.3's) but **no `pending_transfer` branch at all** — 3.4 adds it.
  - `calls.CallSession.transfer` (5.1, already built) is a `JSONField(default=dict)` with a **fixed, already-
    consumed shape**: `{result, reason, destination, initiated_at, duration_seconds, attempts}`. `result` is
    read by the shipped `templates/partials/_transfer_outcome.html`, which branches on exactly
    `connected` / `off_hours` / `disabled` / `failed` / `no_answer` (with an "Unknown" fallback for anything
    else), and renders `destination` through a `phone_e164` filter — i.e. **`destination` must be a real E.164
    number, not a label**. `seed_calls.py` (5.1's seeder) already populates all five `result` values plus an
    `attempts: [{destination, result}]` trail on one row. **3.4 must write into this exact, already-rendered
    shape** — it is the reading contract two already-shipped sub-modules (5.1 model docstring, 5.4 template) and
    the demo data depend on.
  - `scheduling.CallbackRequest` (4.5, already built) — `contact` (`SET_NULL`), `caller_name`, `caller_phone`,
    `reason`, `status` (`pending`/`contacted`/`closed`), `source` (`ai_phone`/`manual`/`web`, defaults to
    `ai_phone`). The dispatcher's `create_callback_request` tool (3.3, already built) already writes this model
    directly — 3.4's "falls back to a callback request when closed" bullet is a **second, transport-level writer**
    of the same model on the off-hours/no-target gating path, not a new model.
  - `apps.runtime.providers.telephony` (3.1, already built) is **pure TwiML/signature helpers only** — no
    `get_backend()`, no adapter class. Its own module docstring states this explicitly: *"the real backend
    handoff — with the media redirect and hangup the live path needs — lands with 3.4."* `apps.agents.telephony`
    (2.2/2.4, already built) already has the `BaseTelephonyBackend` / `FakeTelephonyBackend` /
    `LiveTelephonyBackend` / `get_backend()` pattern for `check_connection` / `place_test_call`, and its
    `get_backend()` **already import-guards** for `apps.runtime.providers.telephony.get_backend` — so 3.4 slots
    into an established seam, not a new one.
- **Existing design spec found and reconciled against:** `.claude/skills/voice-agent-runtime/SKILL.md` §9
  ("Deferred cold transfer") is a **complete pre-written execution spec** for this sub-module — triggering
  priority (`spanish` → `caller_requested` → `ai_offered_transfer` → `ai_cannot_answer` → `no_answer`), the
  working-hours gate (fails open on a missing/broken schedule), the 11-step execution order (single-fire guard
  before any await → hours gate → non-interruptible handoff line → ~0.6 s drain → E.164/SID validation → the
  REST `<Dial answerOnBridge="true" timeout="25">` redirect → outcome capture), and §12's adapter shape
  (`telephony.redirect_call / hangup`, async, fake-shipped-in-the-same-pass). **Two conflicts this research
  surfaces for `todo` to resolve, because the code (not the skill prose) is the contract two already-shipped
  sub-modules depend on:**
  1. **Outcome key names.** The skill's §9.3 point 11 says record `{reason, destination_kind, outcome, at}`.
     The **already-built** `CallSession.transfer` docstring, `_transfer_outcome.html` and `seed_calls.py` all use
     `{result, reason, destination, initiated_at, duration_seconds, attempts}` with `destination` as a real
     number. 3.4 must write the **already-rendered** shape (`result`/`destination`/`initiated_at`), not the
     skill's `outcome`/`destination_kind`/`at` — the skill predates the model's finalized shape.
  2. **What `transfer_secondary_number` means.** 3.3's `TRANSFER_TOOLS` mapping and the skill's §9.1 both treat
     it as **the Spanish-speaking line** (`transfer_call_spanish`'s destination, gated open regardless of hours).
     But 5.1's `CallSession` docstring and its own seeded Downtown row narrate it as a **waterfall fallback**
     for a plain human transfer ("primary rang out at `+13125550101`, secondary answered at `+13125550102`" — no
     Spanish involved). `AgentSetting` has exactly two number fields, and 3.3 has already shipped a tool that
     claims the second one for language routing — there is no third field to source a "human overflow" number
     from. **Recommendation: 3.4 should NOT implement an automatic primary→secondary waterfall dial for the
     plain `human` transfer** (there is no unclaimed field to dial from); keep `transfer_secondary_number`
     exclusively as `transfer_call_spanish`'s destination, matching the already-shipped tool surface. The
     `attempts` list stays in the model (useful for a future real waterfall once a dedicated field exists) but is
     written as a single-entry list in the pass this research recommends, not populated by a fabricated fallback.

## Leaders surveyed (with source links)

1. **Retell AI** — realtime voice-agent platform; SIP DIAL for warm transfer (sets `From`/`P-Asserted-Identity`),
   SIP REFER for cold transfer, AI-generated call summary handed to the receiving human, human-detection before
   whispering — [Transfer call tool docs](https://docs.retellai.com/build/single-multi-prompt/transfer-call),
   [Call Transfer feature page](https://www.retellai.com/features/call-transfer), [Warm vs cold transfer
   blog](https://www.retellai.com/blog/effortless-handoffs-with-retell-ais-warm-transfer-feature).
2. **Vapi** — `transferCall` default tool; cold transfer via SIP REFER or a transfer-call function; warm transfer
   requires SIP REFER enabled on the trunk or falls back to a dropped call; **assistant-based warm transfer** uses
   a dedicated hand-off assistant that can inspect context and **cancel** the transfer — [Assistant-based warm
   transfer](https://docs.vapi.ai/calls/assistant-based-warm-transfer), [Dynamic call
   transfers](https://docs.vapi.ai/calls/call-dynamic-transfers), [Default Tools](https://docs.vapi.ai/tools/default-tools).
3. **Bland AI** — Pathways "Transfer Call" node with a cold-transfer default and an opt-in **warm transfer**
   (merges into a live 3-way conversation, AI announces the introduction then steps back, holds live translation
   between parties if enabled) — [Live transfer](https://docs.bland.ai/tutorials/live-transfer), [Warm
   transfer](https://docs.bland.ai/tutorials/warm-transfer).
4. **Synthflow** — cold transfer (immediate, no briefing) vs warm transfer (private whisper or AI summary played
   to the recipient first, plus **human detection**, **retries** and **fallback behaviour** — explicitly absent
   on cold transfers); keyword-triggered transfer ("I want to talk to the manager"); SIP-header metadata passthrough
   — [Call Transfers](https://docs.synthflow.ai/call-transfers), [Call Transfer
   Node](https://docs.synthflow.ai/configure-call-transfer-node), [Phone Number
   Transfers](https://docs.synthflow.ai/transfer-calls-to-humans).
5. **PolyAI** — enterprise handoff platform; SIP REFER is the default transfer method (specifies destination to
   the client's SBC, then drops); "Handoff" actions carry a descriptive name + a "when to use" note; escalation
   payload explicitly includes transcript, recording, transfer event, structured summary, analytics fields and the
   escalation reason — [Handoff introduction](https://docs.poly.ai/call-handoff/introduction), [Agent handover —
   how to get the transfer right](https://poly.ai/blog/agent-handover).
6. **Goodcall** — default transfer target is the business line, configurable to a specific person/department;
   options besides transfer include "take a message", "send a self-service link" or "schedule a callback"; explicit
   after-hours voicemail with a "when to expect a response" message — [AI
   Receptionist](https://www.goodcall.com/voice-ai/ai-receptionist).
7. **Smith.ai** — live receptionist + AI; **never cold-transfers** — always tells the caller before connecting;
   transfers to the team are gated to configured business hours by default (or 9pm PST with none set) unless the
   business opts into off-hours transfer — [Introducing Live Transfer](https://smith.ai/blog/introducing-live-transfer),
   [24/7 Receptionists FAQ](https://docs.smith.ai/article/70s1gb2qpk-24-7-receptionists-faq).
8. **Ruby Receptionists** — human receptionists; warm "connect" with a spoken whisper (who's calling and why)
   before bridging; can route to any number the business names (office/cell/home) — [Live Virtual
   Receptionists](https://www.ruby.com/live-virtual-receptionists/), [Meet
   Ruby](https://www.ruby.com/campaign/hello-ruby/).
9. **Rosie** — AI phone answering; transfer to "the right team member"; a recent update added **waterfall
   transfer** — try multiple backup numbers in order until one answers — gated to a higher pricing tier — [Rosie AI
   Call Answering](https://heyrosie.com/), [Rosie feature summary](https://softwarefinder.com/call-center/rosie).
10. **Dialpad Ai** — contact-center/voice-agent platform; escalation routes by detected intent, carries full
    conversation context forward so the human doesn't re-ask; auto-attendant style intent routing rather than
    fixed IVR menus — [AI Voice Agents](https://www.dialpad.com/ai-voice/), [AI Virtual
    Receptionist](https://www.dialpad.com/solutions/ai-virtual-receptionist/).

Supporting technical references (Twilio's own patterns, since the transport is Twilio in this product):
[Twilio Warm transfer with Node.js](https://www.twilio.com/docs/voice/tutorials/warm-transfer),
[Connect a Voice AI agent to a Twilio
Conference](https://www.twilio.com/en-us/blog/developers/tutorials/product/connect-twiml-app-twilio-conference),
[Twilio Voice Conference docs](https://www.twilio.com/docs/voice/conference).

## Feature catalog (this sub-module only)

### Deferred Transfer Signal
- **Ack-then-act ordering** — the model's own "putting you through" line is spoken in full before any transport
  action begins, so the caller never hears a dial tone cut off a sentence · seen in: Bland AI (warm transfer
  "professional handoff, AI announces the introduction and steps back"), Smith.ai (always announces before
  connecting, calls a cold cut-off "jarring") · priority: table-stakes · model: `apps.runtime.agent.state.CallState
  .pending_transfer` (already built, 3.2/3.3) — reads it, writes nothing new · realtime: live-call hot path · 
  tool-surface: none (transport behaviour, not a tool) · buildable now.
- **Non-interruptible handoff line + short drain interval before redirect** — barge-in is suppressed for the
  handoff line itself (same rule the greeting and the goodbye line already use), and a short pause after it lets
  Twilio's carrier jitter buffer empty before the REST redirect fires, or the caller hears the line's last word
  clipped · seen in: general Twilio warm-transfer implementation pattern (conference/redirect timing), implicit in
  every surveyed product's "AI announces, then steps back" framing · priority: REQUIRED (this is a
  correctness/UX floor, not a nice-to-have — a clipped handoff line is a broken product on every call that
  transfers) · model: none, pure transport timing · realtime: live-call hot path · tool-surface: none · buildable
  now.
- **Two-line vocabulary (`human` vs `spanish`)** — the transport branches on `pending_transfer`'s value to select
  the destination field, the handoff line's language, and whether the hours gate applies at all · seen in:
  Synthflow (language/department-specific routing via keyword), Bland AI (live translation partner during warm
  transfer) · priority: table-stakes (multi-destination routing is standard; this product's specific two-value
  set is its own scope) · model: reuses `agents.AgentSetting.transfer_phone_number` /
  `.transfer_secondary_number` · realtime: live-call hot path · tool-surface: none (both tools already exist;
  3.4 only reads the signal they set) · buildable now.

### Hours & Target Gating
- **Working-hours window, evaluated in the location's own timezone** — `AgentSetting.transfer_working_hours` /
  `.transfer_timezone`, fails open on a missing schedule or a bad timezone (never breaks a live call over a
  config typo) · seen in: Smith.ai (hard business-hours gate on live transfers by default), Goodcall (after-hours
  → voicemail with a callback-time message) · priority: REQUIRED (a business-hours promise this product's own
  agent setup UI (2.3) already lets a tenant configure — failing to honour it either strands a caller off-hours
  or wakes staff who explicitly closed the window) · model: reuses `apps.agents.services.is_transfer_available`
  (already built, pure, hot-path-safe) — 3.4 is the **first caller** of this function under `apps/runtime/` ·
  realtime: live-call hot path · tool-surface: none, called from the transport, not a new tool · buildable now.
- **Language-line exemption from the hours gate** — `spanish` is "another agent, not the human team", so it
  bypasses the working-hours check entirely; only `human` (`caller_requested` / `ai_offered_transfer` /
  `ai_cannot_answer` / `no_answer`) is gated · seen in: no surveyed competitor documents this exact distinction
  (most gate ALL live transfers uniformly), making it a genuine product-specific rule already decided by this
  project's own design (skill §9.2) rather than a market pattern to import · priority: differentiator (by
  construction — a design decision unique to this build) · model: none · realtime: hot path · tool-surface: none
  · buildable now.
- **Off-hours → speak the notice once, then keep helping (not a dead end)** — the agent states the transfer is
  unavailable right now and continues the conversation rather than stalling or hanging up · seen in: Goodcall
  (after-hours voicemail with a "when to expect a response" message), Rosie/Smith.ai (fallback to message-taking
  when live transfer isn't available) · priority: table-stakes · model: none, a spoken-fallback branch · realtime:
  hot path · tool-surface: none · buildable now.
- **Off-hours / no-target / disabled → automatic callback-request fallback** — this sub-module's own bullet:
  when a human transfer is requested but gating fails (closed, `transfer_enabled=False`, or no destination
  configured), the transport (not the model) creates a `scheduling.CallbackRequest` capturing what was gathered
  so far, so the caller's request survives even if the model doesn't separately think to call
  `create_callback_request` · seen in: Goodcall ("schedule a callback" as a named fallback path alongside
  transfer), Rosie/Smith.ai (message-taking as the off-hours default) · priority: table-stakes · model: reuses
  `scheduling.CallbackRequest` (already built, 4.5) — tenant + location scoped, `source='ai_phone'`, `contact`
  from `state.contact_id` when known else null, `caller_phone` from the call's `from_number` · realtime: hot path
  (the write itself goes through `database_sync_to_async`, same discipline the dispatcher already uses) ·
  tool-surface: transport-level write, not a new LLM tool (the model already has its own
  `create_callback_request` tool from 3.3; this is a **second, independent writer** on the gating-failure path,
  not a replacement) · buildable now.
- **E.164 + Twilio-SID shape validation before interpolating into a REST URL** — the destination, the account
  SID and the live call SID are all format-checked before either goes into an HTTP call; any failure aborts
  without dialing · seen in: no surveyed competitor documents this defensively (it is an implementation-hygiene
  rule, not a market feature), but it directly defends the "destination is always the configured number, never
  caller/model-supplied" invariant already stated for 3.3's tools · priority: REQUIRED (a malformed value reaching
  a REST call the tenant's own Twilio credentials execute is a real-money, real-carrier action — the exact class
  CLAUDE.md's cost/security rules exist to prevent) · model: none · realtime: hot path · tool-surface: none ·
  buildable now.

### Single-Fire Guard
- **Mark "transfer initiated" on the consumer's own transport state before the first `await`** — a concurrent
  turn (the queued-utterance drain path 3.2 already built) or a redelivered signal must never double-execute the
  bridge, which would either double-bill the carrier minute or attempt two REST redirects against the same live
  call SID · seen in: no surveyed competitor's public docs describe this as a customer-facing feature (it is
  purely an internal correctness property), but every one of them necessarily has *some* single-fire mechanism —
  a competitor whose agent redirected a live call twice on a race would be a headline outage, not a shipped
  product · priority: REQUIRED (this is the exact race a single-slot in-flight-turn design like 3.2's makes
  possible, and CLAUDE.md's realtime rule 6 names "transport acts after the turn's audio completes" as the whole
  reason a deferred signal exists in the first place) · model: none, a boolean on the consumer instance (not on
  `CallState`, matching the existing split where transport-only flags — `turn_busy`, `is_playing` — live on the
  consumer and conversation state lives on `CallState`) · realtime: live-call hot path · tool-surface: none ·
  buildable now.

### Outcome Capture
- **Structured result taxonomy: `connected` / `no_answer` / `off_hours` / `disabled` / `failed`** — a closed,
  already-rendered vocabulary (the `_transfer_outcome.html` partial's badge map), not free text · seen in: every
  surveyed product exposes *some* closed transfer-outcome taxonomy in its call log/analytics (Dialpad's
  "containment rate"/"human handover rate", JustCall's disposition + structured summary, PolyAI's escalation
  analytics fields) · priority: REQUIRED (this is the shipped reading contract of 5.1/5.4, already live in
  production templates and seeded demo data — writing an out-of-vocabulary value silently breaks the badge and
  the outcome filter on the call log) · model: writes `calls.CallSession.transfer` + `.status` (`STATUS_TRANSFERRED`
  on a connected outcome; the existing `_STATUS_BY_REASON` map plus a new `'transferred'` ended-reason is the
  natural extension point already anticipated by `MediaStream.py`'s own comment: *"'transferred' is 3.4's to set
  and is deliberately absent here"*) — tenant + location scoped through the same row · realtime: **post-call**
  for the write itself, but the DECISION of which result to record starts on the hot path (the REST redirect's
  2xx/4xx/timeout) and, for a true `connected`/`no_answer` distinction, needs an async status callback — see
  "Transfer outcome status callback" below · tool-surface: none, a transport write · buildable now (the write);
  the accurate `no_answer` vs `connected` distinction needs the new webhook below.
- **Destination recorded as the real, dialable number, not a label** — `_transfer_outcome.html` renders
  `transfer.destination` through a `phone_e164` filter; the destination must be `AgentSetting.transfer_phone_number`
  / `.transfer_secondary_number` (whichever line this call used), never a caller/model-supplied value · seen in:
  Retell/PolyAI/Vapi all log the resolved SIP/PSTN target in their call analytics, never a caller-echoed string ·
  priority: REQUIRED (Invariant 3 + toll-fraud prevention — this is the same guarantee 3.3's zero-argument
  transfer tools already established; 3.4 must not regress it at the point the number actually gets dialed) ·
  model: `calls.CallSession.transfer.destination` · realtime: hot path (the value is fixed at dial time) ·
  tool-surface: none · buildable now.
- **Transfer outcome status callback (a new, small Twilio webhook)** — a REST `Calls(sid).update(twiml=...)`
  redirect only proves Twilio *accepted* the instruction (2xx), not that the human line rang, answered or was
  busy; a `<Dial answerOnBridge="true" action="...">` needs its `action` URL POSTed back with `DialCallStatus`
  (`completed`/`no-answer`/`busy`/`failed`) and `DialCallDuration` for `result` and `duration_seconds` to be
  anything more than "we tried" · seen in: this is exactly the gap Vapi's own Twilio integration guide and the
  Twilio warm-transfer tutorial both describe (dial status is only knowable via the action/status callback, not
  the initiating REST call) · priority: table-stakes for accurate outcome data, though the redirect + a
  provisional `connected`-on-2xx write is a defensible **Should**-tier fallback if the callback is deferred ·
  model: writes the same `calls.CallSession.transfer` row, keyed by `provider_call_sid` (idempotent against
  Twilio's redelivery, same discipline 3.1's inbound webhook already uses) · realtime: hot path arrival (Twilio
  posts this moments after the dial resolves), but it is a **separate, later HTTP request** from the original
  call's websocket lifetime — the row it updates may already be `disconnect()`-finalized, so the write must
  `select_for_update()` an existing row rather than assume the consumer is still live · tool-surface: none, a new
  webhook view (`apps/runtime/webhooks.py`, same file 3.1's `voice_webhook` lives in, per the "flat single-purpose
  module" backend rule) + a new `urls/InboundWebhook/` route, signature-verified against the resolving location's
  Twilio credentials exactly like 3.1's voice webhook · integration/later (needs the live Twilio adapter method to
  exist first; the fake path can synthesize this callback deterministically for tests/seeders without a real
  webhook).
- **`attempts` trail kept as a single-entry list for this pass** — per the reconciliation note above,
  `transfer_secondary_number` is claimed by `transfer_call_spanish`; there is no unclaimed field to source an
  automatic primary→secondary waterfall for a plain human transfer, so `attempts` is written with exactly the one
  attempt this pass makes (or omitted, matching most of the seeded rows), not fabricated as a two-line fallback ·
  priority: common (the field stays for forward-compatibility; populating it with real waterfall data is
  Deferred, see below) · model: `calls.CallSession.transfer.attempts` (optional) · realtime: hot path write ·
  tool-surface: none · buildable now.

### Beyond the bullets
- **Runtime diagnostics: transfer outcomes surfaced per location** — 3.1's diagnostics page already lists recent
  sessions and stats; 3.4 is the first sub-module with something call-outcome-shaped to add (a transferred-count,
  or the most recent transfer's result) so a tenant can see "is transfer actually working" without opening a
  specific call · seen in: Dialpad's "human handover rate" and JustCall's "containment rate" as headline
  dashboard metrics; PolyAI's "Handoff States API" for monitoring transitions · priority: common · model: none —
  reads `calls.CallSession.transfer`/`.status` through the same tenant+location-scoped queryset 3.1's diagnostics
  view already builds · realtime: post-call (a read-only aggregate) · tool-surface: pure UI (a diagnostics page
  addition) · buildable now.
- **Warm transfer with a whisper to the human before bridging** — Retell/Bland/Synthflow's headline
  differentiator: a private message or AI-generated summary is played to the *human* side only, and/or human
  detection confirms a live person before connecting · priority: differentiator (explicitly NOT this pass's
  design — the product's own skill spec (§9) is a **cold** transfer with an announcement to the *caller*, not a
  three-way whisper to the human) · model: none yet · realtime: would be hot path · tool-surface: would need a
  second outbound leg / conference, a materially bigger build · integration/later, Deferred (see below).
- **SIP REFER for a true cold transfer** (vs. a REST `<Dial>` redirect) — PolyAI's and Vapi's default cold-transfer
  mechanism; drops the carrier leg the media stream was consuming rather than keeping it alive through a dial-out,
  which is cheaper per-minute and closer to a PBX-style handoff · priority: differentiator · realtime: hot path ·
  buildable: **not with the current Twilio product surface this app targets** (SIP REFER needs a SIP trunk/SBC
  configuration this product's plain PSTN-number model doesn't assume) — Deferred, noted for awareness only.
- **Waterfall / multiple backup numbers tried in order** — Rosie's recently-shipped feature; would need a genuinely
  new `AgentSetting` field (a 2.3 change) since both existing number fields are already claimed (primary human,
  Spanish) · priority: differentiator · model: would need a new field, out of this pass's model-zero scope ·
  Deferred.
- **Keyword-triggered escalation as a deterministic backstop, not just model judgment** —
  `apps.agents.services.matches_transfer_keyword` (2.3, already built, pure) is currently **unused** anywhere
  under `apps/runtime/`. The skill's §9.1 explicitly assigns "per-turn keyword evaluation" (with priority order
  `spanish` → `caller_requested` → `ai_offered_transfer` → `ai_cannot_answer` → `no_answer`) to this flow — i.e.
  it is this sub-module's to wire, not a dangling loose end · seen in: Synthflow ("forward the call whenever a
  trigger word like 'I want to talk to the manager' is heard" — deterministic, not left to model judgment alone)
  · priority: common (a deterministic backstop for reliability, since an LLM can simply fail to call the tool
  even when the caller clearly asked) · model: none, a pure per-turn evaluation against the turn's own transcript
  text · realtime: hot path (must run every turn, cheaply, with no provider call) · tool-surface: prompt/behaviour
  change, not a new LLM tool — it sets the same `pending_transfer` signal the tool-based path sets · buildable
  now.

## Compliance & provider constraints

- **No NEW recording-consent or two-party-consent obligation is introduced by this sub-module.** The transfer
  handoff line and any human-side conversation after bridging are covered by 3.5's Consent-Gated Recording (the
  location's existing consent basis/announcement already covers the whole call, transfer included) — 3.4 does
  not add a second consent surface. Flagging this explicitly so it is **not** re-litigated here: recording
  consent stays REQUIRED and stays 3.5's.
- **Toll-fraud / cost-as-security-control is REQUIRED here specifically.** The transfer destination is dialed
  using **this tenant's own Twilio credentials** — an unvalidated or caller-influenced destination is a direct
  path to billing the tenant for calls to a number they never configured. The E.164/SID-shape validation before
  interpolation (cataloged above) and the "destination is always the configured field, never a tool argument"
  rule (already enforced by 3.3's zero-parameter transfer tools) are both REQUIRED, not table-stakes — this is
  CLAUDE.md's vulnerability rule 6/8 and the skill's own "unrestricted dial-out is toll fraud waiting to happen"
  line, verbatim.
- **Twilio rate limits / concurrency.** Placing a REST `Calls(sid).update()` redirect on an already-in-progress
  call consumes a second outbound leg's worth of concurrent-call capacity on the tenant's Twilio account for the
  duration of the bridge — a tenant near their account's concurrent-call cap could have a transfer rejected by
  Twilio (a `429`/`400`-shaped provider error), which must degrade to the same "apologize once, keep serving"
  path as any other transfer failure, never a crashed call. Every telephony call this sub-module makes goes
  through the same bounded-timeout-and-retry seam (`apps/runtime/providers/reliability.py`'s `call_bounded`,
  already built) other provider calls use, with the caveat that a redirect is **not idempotently retryable** —
  the existing "timeout is terminal, not retried" rule (already the policy for STT/TTS/LLM) applies with extra
  force here: retrying a redirect that actually landed risks a second bridge attempt.
- **Cost lines appended to `calls.CallSession.usage`: none.** A REST redirect call is not an LLM/STT/TTS turn, so
  it does not append a `usage` entry the way a conversational turn does. The **carrier minute cost of the bridged
  call itself** (the human-to-caller conversation after the redirect) is a Twilio per-minute telephony charge this
  product does not currently meter anywhere (no existing `usage` cost-breakdown key covers post-transfer minutes,
  since the media stream — the thing `usage` is metered against — has already ended once Twilio redirects away
  from it). Noted as a real gap, not silently absorbed: if per-call cost reporting is expected to include the
  transferred-call minutes, that needs a new `usage`-adjacent field or a `transfer.duration_seconds`-derived
  estimate at the 5.3 cost-breakdown read layer — flagged for `todo`/5.3 awareness, not solved in this pass.
- **AI-disclosure-before-transfer** is out of THIS sub-module's scope — several US states now require an AI
  agent to identify itself as non-human at some point in the call; that is a greeting/prompt-content concern
  (2.1/3.2), not a transfer-execution one, and no change to it is proposed here.

## Recommended build scope (this pass)

**This is a SERVICE sub-module — ZERO new models, ZERO migrations.** It writes into two already-built models
(`calls.CallSession.transfer`/`.status`, `scheduling.CallbackRequest`) and reads two already-built ones
(`agents.AgentSetting`, and indirectly `apps.agents.services`'s pure functions). The build scope is transport
behaviour, one new provider-adapter method + its fake, and an observability addition:

1. **The deferred-transfer transport flow in `MediaStreamConsumer._run_turn`** — after the turn's audio plays
   (the same point `pending_hangup` is already checked), branch on `state.pending_transfer`: set a
   consumer-level single-fire boolean before any `await`; evaluate `is_transfer_available` (human) or skip the
   gate entirely (spanish); on a pass, cancel queued playback, speak the fixed non-interruptible handoff line,
   wait the drain interval, validate E.164/SID shape, and call the new telephony adapter method.
2. **Hours/target gating with automatic callback-request fallback** — reuse `apps.agents.services
   .is_transfer_available` / `.next_transfer_window` (already built, call them for the first time); on a gating
   failure, speak the off-hours/unavailable notice once, clear the signal, create a
   `scheduling.CallbackRequest(source='ai_phone', ...)` capturing whatever `state.contact_id`/from-number/reason
   context is available, and keep the call going.
3. **The single-fire guard** — a plain boolean on the `MediaStreamConsumer` instance (transport state, not
   `CallState` — matching the existing `turn_busy`/`is_playing` split), set synchronously before the first
   `await` in the transfer branch.
4. **Outcome capture onto `CallSession.transfer` and `.status`** — write the already-established key shape
   (`result`, `reason`, `destination`, `initiated_at`, `duration_seconds`, optional `attempts`), using the
   `result` vocabulary the shipped `_transfer_outcome.html` already renders (`connected`/`no_answer`/`off_hours`/
   `disabled`/`failed`); set `status = STATUS_TRANSFERRED` and stamp `ended_at` on a connected outcome, extending
   `MediaStream.py`'s `_STATUS_BY_REASON` map with a `'transferred'` key exactly where its own comment already
   anticipates it.
5. **A telephony provider adapter method for the transfer/bridge, plus its fake** — add `redirect_call` (async,
   per the skill's §12 interface naming) to a new `apps.runtime.providers.telephony` backend class alongside the
   existing pure TwiML helpers, following the already-established `BaseTelephonyBackend` /
   `FakeTelephonyBackend` / `LiveTelephonyBackend` / `get_backend()` pattern `apps/agents/telephony.py` already
   uses for `check_connection`/`place_test_call` (whose own `get_backend()` already import-guards for this
   module's `get_backend`, so Module 2's call sites need no change). The fake never opens a socket or imports
   `twilio`, and returns a deterministic synthetic outcome so tests/seeders/`simulate_call` can exercise every
   `result` value under `PROVIDER_MODE=fake`.
6. **Diagnostics/observability of transfer outcomes** — extend `runtime/diagnostics.html` (3.1's existing page,
   no new page) with a transfer-outcome summary for the active location (a per-result count, or the most recent
   transfer's result/destination-line), reusing the same tenant+location-scoped `CallSession` queryset the page
   already builds.
7. **(Should, not Must for this pass) The transfer-outcome status callback webhook** — a small new view in
   `apps/runtime/webhooks.py` + a route in `apps/runtime/urls/InboundWebhook/`, receiving Twilio's `DialCallStatus`/
   `DialCallDuration` from the `<Dial action="...">` verb, signature-verified against the resolving location's
   credentials and idempotent on `provider_call_sid`, to correct a provisional "redirect accepted" outcome into a
   true `connected`/`no_answer`/`failed` result with a real `duration_seconds`. Can ship in the same pass if time
   allows; if deferred, the redirect's own 2xx/4xx/timeout is the provisional outcome-of-record and is clearly
   flagged as such in `logs`.

Deferred, so nothing here is lost: warm-transfer whisper-to-human / three-way conferencing (a materially bigger
build — a second call leg, a conference, human detection); SIP REFER as an alternative to REST-redirect cold
transfer (needs SIP trunk infrastructure this product doesn't assume); a true primary→secondary waterfall for the
plain human transfer (needs a new `AgentSetting` field, a 2.3 decision); metering the bridged call's carrier-minute
cost into `usage` or a `transfer`-adjacent cost figure (flagged for 5.3 awareness); a per-tenant/location transfer
rate ceiling beyond the existing call-duration/tool-iteration bounds (no surveyed competitor documents an
equivalent either).

## Belongs to sibling sub-modules (parked, not scoped here)

- Consent-gated recording, the two-party-consent announcement, `waveform_peaks`, the fuller per-stage-latency
  diagnostics page → **3.5** (3.4 only adds a transfer-outcome summary to the page 3.1 already shipped; the
  richer diagnostics rebuild is 3.5's).
- The transfer-outcome card's own rendering (`_transfer_outcome.html`, the `result` badge map, the `attempts`
  trail rendering) → **already built as 5.1/5.4**; 3.4 is a pure writer into that existing contract, not a
  template change.
- `AgentSetting.transfer_enabled`/`.transfer_phone_number`/`.transfer_secondary_number`/`.transfer_working_hours`/
  `.transfer_keywords` themselves, and their settings-form UI → **already built as 2.3**; 3.4 only reads them.
- A dedicated backup/overflow human number (a true waterfall) → would need a new field → **2.3**, if ever
  prioritized.
- `transfer_call`/`transfer_call_spanish`/`create_callback_request` tool declarations and their zero-argument
  identity-injection guarantees → **already built as 3.3**; 3.4 executes what 3.3 signals, it does not change the
  tool surface.

## Out of scope for this product (outside the seven capabilities)

- **Contact-center-style ACD/queue management** (Ruby's/Dialpad's "automatic call distribution, queue
  management") — this product transfers to a single configured destination per line, not a hunt group or agent
  queue; queueing is out of the seven capabilities entirely.
- **Live translation during a bridged call** (Bland AI's feature) — this product's agent ends its role at the
  handoff; translating a live human-to-human conversation is a different, ongoing-audio-processing product, not
  call transfer.
- **CRM/ticketing disposition-code write-back** (JustCall's "logs to the CRM, assigns a disposition code, triggers
  workflows") — there is no CRM/workflow integration surface in this product; the outcome lives on `CallSession`
  and nowhere else.

## Deferred (later passes / integrations)

- Warm-transfer whisper/summary to the human side and three-way conferencing — a materially larger build than a
  cold `<Dial>` redirect; the product's own skill spec already scopes this pass as cold-only.
- SIP REFER-based transfer — needs SIP trunk/SBC infrastructure not assumed by this product's plain-PSTN-number
  model.
- True waterfall (try primary, then secondary, for the SAME human transfer) — blocked on a new `AgentSetting`
  field; the existing `transfer_secondary_number` is already claimed by the Spanish-line tool.
- The transfer-outcome status callback webhook, if not shipped in this pass — the redirect's own accept/reject
  is the provisional outcome-of-record until it lands.
- Metering the bridged call's carrier-minute cost — no existing `usage` line covers post-redirect minutes; needs
  a decision from 5.3/cost-reporting on whether and how to estimate it from `transfer.duration_seconds`.
- A transfer-specific rate ceiling (per tenant/location, beyond existing call-duration/tool-iteration bounds) —
  no surveyed competitor documents an equivalent; existing bounds are the shipped mitigation.
