# Research — Sub-module 2.4: Test Call (Module 2 — Agent Setup & Telephony, agents)

## Repo state checked first

- **LIVE_LINKS built so far in module 2:** none. `apps/accounts/navigation.py` has `'0.1'`–`'0.4'`
  and `'1.1'`–`'1.4'` only; `'2.1'`–`'2.4'` are all absent — Module 2 is entirely unbuilt today,
  confirmed independently by `Glob apps/agents/**` → **no files** and `Glob apps/runtime/**` → **no
  files**. Neither `apps/agents` nor `apps/runtime` exists yet.
- **Sibling research files:** `Glob .claude/tasks/research-agents-*.md` → **no matches**. No 2.1/2.2/2.3
  research pass has run yet, so there is no deferred backlog handed forward into 2.4 from a sibling
  file. Sibling boundaries below are read directly from `NavAIReceptionist.md`'s own `### 2.1`/`2.2`/`2.3`
  bullets (quoted in "Belongs to sibling sub-modules").
- **`agents.AgentSetting`** — not migrated (no code exists), but its intended shape is fully specified
  in `NavAIReceptionist-ERD.md` §3.2: `tenant` FK, `location` FK, `enabled` (bool), `voice_provider`
  (`live`/`google`/`gemini`), `greeting` (Text, `{{var}}`-aware, deterministic), `prompt_text` (Text),
  `variables` (JSON dict), `inbound_phone_number` (Char32 E.164, **globally unique across all
  tenants**), `twilio_account_sid` (Char64), `twilio_auth_token` (Char128, **encrypted at rest,
  write-only in forms**), `transfer_enabled` (bool), `transfer_phone_number`, `transfer_secondary_number`
  (E.164), `transfer_timezone` (IANA), `transfer_working_hours` (JSON), `transfer_keywords` (JSON list).
  **Unique `(tenant, location)`** — exactly one row per location. This is the ONE model Module 2 owns;
  2.4 adds no fields to it, only reads it and (see below) one new presence-check *method*.
- **Import-guard precedent verified** (the pattern 2.4's telephony seam must reuse):
  - `apps/tenants/views/Location.py:97-110` — `_agent_setting_for(location)`: `try: from
    apps.agents.models import AgentSetting / except (ImportError, ModuleNotFoundError): return None`.
    Docstring: *"Import-guarded rather than assumed... When Module 2 lands this starts returning real
    rows with no edit here."*
  - `apps/tenants/views/_helpers.py:13-27` — `future_appointment_count(user=None, location=None)`:
    same shape against `apps.scheduling.models.Appointment`, returns `0` until Module 4 exists.
    Docstring: *"The import is guarded so THE CALL SITE NEVER CHANGES."*
  - Both share one property that matters for 2.4's design: **the guarded function itself never needs a
    second edit** — the moment the target module exists, the `try` branch starts succeeding and the
    caller's behaviour upgrades automatically.
- **`config/settings.py` already carries** everything 2.4 needs and nothing more: `PROVIDER_MODE`
  (`fake`/`sandbox`/`live`, default `fake`, invalid values coerce to `fake` — lines 320-322),
  `TWILIO_WEBHOOK_BASE_URL`/`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` (platform-level fallback creds —
  **not** the per-location ones, those live encrypted on `AgentSetting`), `ENCRYPTION_KEY` (line 353,
  Fernet key for the token field), `PROVIDER_TIMEOUT_SECONDS=10`, `MAX_CONCURRENT_CALLS=25` (lines
  360-364, the cost-control ceilings 2.4's rate limiting should mirror). `cryptography` 49 is installed
  per the task brief (not independently re-verified by grep here — no `apps/agents` exists yet to grep
  for its usage; this is a forward-looking note for the encrypted-field implementation, not a claim
  about existing code).

## Leaders surveyed (with source links)

1. **Retell AI** — voice-agent platform with a one-click browser "web call" test from the agent's
   dashboard page, no phone number purchase required — [Web call testing](https://docs.retellai.com/test/test-web)
2. **Vapi** — dashboard test button (no phone number) plus a genuine phone-based outbound test call via
   the `/call` endpoint against an imported or free number — [Voice Testing](https://docs.vapi.ai/test/voice-testing), [Outbound Calling](https://docs.vapi.ai/calls/outbound-calling)
3. **Synthflow** — four testing modes (Phone call, Chat, Widget, Simulation); recommends iterate-in-chat
   → confirm-with-phone-call → full-simulation-suite before deploying — [Manual Testing](https://docs.synthflow.ai/test-your-agent), [Simulations](https://docs.synthflow.ai/simulations)
4. **Bland AI** — text-based "talk to your prompt" testing tool plus an explicit pre-launch QA checklist
   (happy path / edge cases / error handling, 50+ reference calls as a regression baseline) — [How Can I Test My Voice Agent After Building It](https://www.bland.ai/blog/how-can-i-test-my-voice-agent-after-building)
5. **ElevenLabs Agents** — Simulate Conversation API (full and partial simulations) plus an embeddable
   test widget (`<elevenlabs-convai agent-id=...>`) — [Simulate Conversations](https://elevenlabs.io/docs/eleven-agents/guides/simulate-conversations), [Agent Testing](https://elevenlabs.io/docs/eleven-agents/customization/agent-testing)
6. **PolyAI** — staged draft→sandbox→live→rollback environment promotion, explicit team-demo-call
   practice before real customers, and re-runnable simulated test conversations for debugging — [How to deploy call center voice AI](https://poly.ai/blog/how-to-deploy-call-center-voice-ai/)
7. **Twilio** — trial/free accounts may only call phone numbers added as **Verified Caller IDs**
   (OTP-confirmed before the number is dialable) — the direct real-world analogue of this sub-module's
   own "verified destination" wording — [Free trial account guide](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account), [Verifying Caller IDs at Scale](https://www.twilio.com/docs/voice/api/verifying-caller-ids-scale)
8. **Goodcall** — fast (≈15 minute) setup flow with explicit test-before-launch guidance (test caller
   confusion, incomplete info, escalation) before connecting automation to every caller — [AI Receptionist](https://www.goodcall.com/voice-ai/ai-receptionist)
9. **Smith.ai / Ruby Receptionists** — human-backed onboarding runs a structured "testing phase" (script
   configuration + quality review) before live call handling begins, with ongoing AI+human quality
   monitoring after go-live — [Smith.ai vs Ruby comparison](https://smith.ai/virtual-receptionist-service-comparison/smith-ai-vs-ruby-receptionists)

## Feature catalog (this sub-module only)

None of the features below add a new LLM tool — Test Call is an operator-triggered setup-time action,
never something the live agent decides to do mid-call, so "tool-surface" is "pure UI" or "service call"
throughout, not a `apply_tool_call` entry.

### Placed Test Call
- **Outbound test call to a self-verified destination number** — dials the tester's own phone from the
  location's configured Twilio number so the tenant hears the live agent · seen in: Vapi (phone-based
  outbound test call via `/call`), Twilio (Verified Caller IDs gate) · priority: table-stakes · model:
  reuses `agents.AgentSetting` (read `inbound_phone_number`, `twilio_account_sid`, presence of the
  token) — no new model; destination number is validated E.164 input, never stored · realtime: post-call
  (a setup-time trigger; once Module 3 exists the actual audio traverses the SAME live-call hot path a
  real inbound call uses — 2.4 only triggers it) · tool-surface: pure UI + a service call to
  `get_telephony_backend().place_test_call(...)`, not an LLM tool · integration/later for the live path
  (needs real Twilio credentials + Module 3's media consumer); the trigger, form and result UI are
  buildable now against the fake backend.
- **"Verified destination" anti-toll-fraud gate — REQUIRED** — never accept an arbitrary free-text
  destination number; default the field to the signed-in tester's own `accounts.User.primary_phone`
  (existing field, no schema change) and require the tenant to re-confirm it, so the feature cannot be
  used to dial arbitrary third-party numbers repeatedly · seen in: Twilio's own trial-account
  verified-caller-ID OTP gate — the literal real-world version of this sub-module's "verified
  destination" wording · priority: **REQUIRED** (toll-fraud/cost-abuse prevention; also the exact
  phrase used in the sub-module's own bullet) · model: reuses `accounts.User.primary_phone` — no new
  table · realtime: post-call · tool-surface: pure UI + server-side validation · buildable now.
- **Rate limiting on test-call placement** — cap test calls per `(tenant, location)` per hour to bound
  live-mode provider spend, mirroring the existing `MAX_CONCURRENT_CALLS` cost-control pattern · seen
  in: implied by every platform's usage-based billing plus this product's own "cost is a security
  control" rule · priority: **REQUIRED** · model: cache-backed counter (Django `CACHES`, already
  configured) — no new table · realtime: post-call · tool-surface: pure service logic · buildable now.
- **Result/status banner** (queued → ringing → completed/failed) surfaced back to the tester · seen in:
  Vapi (call-status response from `/call`), Retell (web-call session state) · priority: common · model:
  none — the result is an ephemeral value, never persisted (no `calls.CallSession` yet, and even once
  it exists, 2.4 itself does not write it — see Deferred) · realtime: post-call · tool-surface: pure UI
  · buildable now for fake mode (deterministic canned transitions); integration/later for real live-mode
  status polling (needs a Twilio call-status callback, a Module 3 concern).
- **Browser/WebRTC test call, no phone number needed** — seen in: Retell AI (web call), Vapi (dashboard
  test button) · priority: differentiator · model: none · realtime: post-call · tool-surface: pure UI ·
  **integration/later** — needs a real-time audio pipeline in the browser that does not exist until
  Module 3's media-stream consumer does; track as a transport enhancement to this same feature once
  Module 3 ships, not a new capability.

### Fake-Mode Test
- **Simulated text preview instead of real audio when `PROVIDER_MODE != 'live'`** — renders the
  rendered greeting plus a scripted example turn or two as text so the tenant can sanity-check wording
  with zero cost and zero Twilio contact · seen in: Bland AI's text-based testing tool, Synthflow's
  Chat test mode, ElevenLabs' text-based conversation simulation · priority: table-stakes (this is
  literally the sub-module's named behaviour) · model: reuses `AgentSetting.greeting` /
  `.prompt_text` / `.variables` for rendering — no new model · realtime: post-call · tool-surface: pure
  UI/service, no LLM tool · buildable now.
- **Structurally incapable of reaching Twilio, not merely defaulted away from it — REQUIRED** — the
  fake backend must contain no `twilio-python` import and open no socket, so a misconfiguration cannot
  silently degrade into a real call · seen in: this product's own hard rule (never a competitor
  "feature," but the line the whole task brief is anchored on) · priority: **REQUIRED** · model: none —
  an implementation guarantee of `FakeTelephonyBackend` · realtime: n/a · tool-surface: n/a · buildable
  now.
- **Clearly labeled simulated result** — "Simulated — no real call was placed," so a tenant never
  mistakes a fake pass for a verified live path · seen in: general sandbox/test-mode UX discipline,
  echoed by PolyAI's explicit draft/sandbox/live environment labeling · priority: table-stakes · model:
  none · realtime: post-call · tool-surface: pure UI · buildable now.
- **`sandbox` behaves identically to `fake` for now, by design** — both resolve to
  `FakeTelephonyBackend`; documented as a deliberate simplification (matches the settings.py comment
  that fake/sandbox "must never reach a real provider"), not a bug, until Module 3 gives `sandbox` an
  independently meaningful behaviour (e.g. Twilio's own test-credential tier) · priority: table-stakes
  · model: none · realtime: n/a · tool-surface: n/a · buildable now.

### Setup Readiness Check
- **Reusable pure-function readiness gate — REQUIRED** — `check_setup_readiness(agent_setting) ->
  list[ReadinessIssue]`; no I/O, no provider call, callable from the Test Call trigger view and,
  optionally, from 2.1's own `AgentSetting` detail page · seen in: PolyAI's staged
  draft→sandbox→live promotion gate, Goodcall's pre-launch checklist guidance, Smith.ai/Ruby's
  structured "testing phase" before live handling · priority: **REQUIRED** (named explicitly in the
  sub-module's own bullet: "before the tenant tries a real call") · model: reuses `AgentSetting` fields
  only, no new model · realtime: post-call (pure logic, written allocation-light and I/O-free so it
  stays safe to reuse from a live-call hot path later — same design discipline as `1.4`'s
  `get_provider_intervals` precedent) · tool-surface: pure function; the view renders its output as a
  banner/checklist · buildable now.
- **Missing-greeting / missing-prompt blockers** — flags a blank `greeting` or `prompt_text`; these
  block **both** the fake and the live test path, since there is nothing for the agent to say either
  way · seen in: the sub-module's own bullet · priority: **REQUIRED** · model: reuses
  `AgentSetting.greeting`/`.prompt_text` · realtime: post-call · tool-surface: pure logic · buildable
  now.
- **Missing-inbound-number blocker (live-only)** — flags a blank `inbound_phone_number`; blocks a
  **live** test call (nothing to dial from) but does not block a fake-mode test, since fake mode never
  dials anything · seen in: the sub-module's own bullet · priority: **REQUIRED** · model: reuses
  `AgentSetting.inbound_phone_number` · realtime: post-call · tool-surface: pure logic · buildable now.
- **Missing-transfer-target blocker, conditional (live-only)** — raised only when `transfer_enabled` is
  `True` and `transfer_phone_number` is blank; a location that has not turned transfer on has nothing to
  flag · seen in: the sub-module's own bullet · priority: **REQUIRED** · model: reuses
  `AgentSetting.transfer_enabled`/`.transfer_phone_number` (read-only from 2.4) · realtime: post-call ·
  tool-surface: pure logic · buildable now.
- **Missing-Twilio-credentials blocker (live-only)** — flags a blank `twilio_account_sid` or an unset
  `twilio_auth_token`, checked via a boolean **method**, e.g. `AgentSetting.has_twilio_auth_token()`,
  that reports presence without ever decrypting the token · seen in: generalizes 2.2's sibling
  "Connection Check" concern to also gate a live test call · priority: **REQUIRED** · model: reuses
  `AgentSetting.twilio_account_sid` + one new boolean **method** on the existing model (not a new
  field — consistent with the ERD's "derived, never stored" discipline) · realtime: post-call ·
  tool-surface: pure logic, never logs or renders the token (write-only rule) · buildable now.
- **Field-linked issue rendering** — each `ReadinessIssue` carries the offending field name so the UI
  can deep-link to the input on the relevant 2.1/2.2/2.3 edit form, not just show a flat text list ·
  seen in: general setup-checklist UX pattern implied by PolyAI's staged gating and Goodcall's
  step-by-step checklist · priority: common · model: none — a UI convenience over the same issue list ·
  realtime: post-call · tool-surface: pure UI · buildable now.
- **Explicit "ready to go live" affirmative state** — when the issue list is empty, show a clear
  positive confirmation rather than silence, giving the tenant an unambiguous go/no-go signal · seen
  in: PolyAI's explicit sandbox→live promotion step, Bland AI's pre-launch QA checklist framing ·
  priority: common · model: none · realtime: post-call · tool-surface: pure UI · buildable now.

### Beyond the bullets
- **Regression/simulation test suites (multi-scenario, scored personas)** — Bland AI's 50-call
  regression baseline, Synthflow's Simulation mode, ElevenLabs' Simulate Conversation API, PolyAI's
  re-runnable test conversations · priority: differentiator · model: would need a new persisted "test
  scenario"/"test run" concept — **out of the eleven-model ceiling**, not proposed here · Deferred (see
  below).
- **"Call in and try it yourself" team practice** — PolyAI's advice to have staff call the live number
  and role-play caller intents · priority: common, but it is a process/runbook recommendation, not a
  feature to build · listed under Out of scope for engineering (nothing to implement).
- **Load/concurrency testing before go-live** — PolyAI's explicit load-test recommendation · priority:
  differentiator · needs Module 3's real consumer to exist to mean anything · Deferred.
- **Draft/sandbox/live staged environment versioning per agent** — PolyAI's promotion pipeline ·
  priority: differentiator · would require more than one `AgentSetting` row per location, directly
  contradicting the ERD's "exactly one row per `(tenant, location)`" constraint · Out of scope for this
  product.

## Compliance & provider constraints

- **REQUIRED — never place a real call from a test, seed or dev path.** `PROVIDER_MODE` defaults to
  `fake`; both `fake` and `sandbox` resolve to `FakeTelephonyBackend`, which is structurally incapable
  of reaching Twilio. `LiveTelephonyBackend` refuses to initialize unless `PROVIDER_MODE == 'live'`,
  and even then its `place_test_call()` additionally requires real `twilio_account_sid` +
  `twilio_auth_token` + `inbound_phone_number` on the resolved `AgentSetting` row before attempting
  anything — missing credentials in live mode is a hard failure, not a silent fallback.
- **REQUIRED — AI-disclosure parity.** A live test call plays the exact same greeting/prompt as
  production; there is no "skip disclosure, it's just a test" branch, so wherever the greeting/prompt
  already satisfies a jurisdiction's AI-voice-disclosure requirement for production calls, the test
  call satisfies it identically by construction.
- **Recording/consent — out of scope for this pass.** Module 3's consent-gated recording (3.5) does
  not exist yet, so no test call, live or fake, is ever recorded in this pass. Revisit once 3.5 lands
  to decide whether test calls should be recorded at all (most likely opt-in only, since the "caller"
  is the business's own tester, not an external member of the public).
- **Twilio rate limits / cost.** `PROVIDER_TIMEOUT_SECONDS` (10s, already in settings) must bound the
  live backend's outbound-call REST request just like any other external provider call (CLAUDE.md
  realtime rule: "every external provider call is bounded"), even though this view is a synchronous
  Django request/response action, not a Channels consumer. Rate limiting per `(tenant, location)` per
  hour is the concrete cost-control feature above. A live test call incurs a real per-minute Twilio
  voice-call charge; since `calls.CallSession` (and its `.usage` JSON) does not exist yet, there is
  **no cost-ledger row this pass can append to** — 2.4 creates no call-cost record. Once Module 5
  exists, whether a live test call should log a `CallSession.usage` entry is a decision for that later
  pass, not this one — 2.4 must not invent a parallel ledger (Invariant 2).
- **`twilio_auth_token` handling.** Never rendered, logged, or decrypted outside the live call attempt
  itself; the readiness-check accessor (`has_twilio_auth_token()`) is presence-only and never touches
  the plaintext value.

## Recommended build scope (this pass)

**ZERO new models.** 2.4 reuses `agents.AgentSetting` (owned by sibling sub-module 2.1, not created
here) read-only, plus one new boolean **method** on that existing model
(`has_twilio_auth_token()` — presence-check only, never decrypts; a "derived, never stored" accessor,
not a schema change). This is a service-flavored slice inside a CRUD module — the eleven-model ceiling
and the sub-module's own scope (place a call, run it fake, check readiness) give it no entity of its
own to persist. What ships instead:

- **`apps/agents/telephony.py`** (flat, single-purpose module per the backend-package rules) — the
  thin telephony-control seam:
  ```python
  @dataclass(frozen=True)
  class TestCallResult:
      ok: bool
      status: str          # 'queued' | 'ringing' | 'completed' | 'failed' | 'skipped'
      provider_call_sid: str
      message: str

  class TelephonyBackend:
      def place_test_call(self, *, agent_setting, destination_e164: str) -> TestCallResult: ...
      def check_connection(self, *, agent_setting) -> TestCallResult: ...

  class FakeTelephonyBackend(TelephonyBackend):
      """PROVIDER_MODE in {'fake', 'sandbox'}. No twilio-python import, no socket.
      Deterministic canned result."""

  class LiveTelephonyBackend(TelephonyBackend):
      """Refuses to initialize unless settings.PROVIDER_MODE == 'live'. place_test_call()
      additionally requires real twilio_account_sid/token/inbound_phone_number on the
      resolved AgentSetting before attempting anything."""

  def get_telephony_backend() -> TelephonyBackend:
      """The ONLY place PROVIDER_MODE is read for telephony control. Import-guarded exactly
      like `_agent_setting_for` (apps/tenants/views/Location.py) and
      `future_appointment_count` (apps/tenants/views/_helpers.py): tries
      `from apps.runtime.providers.telephony import get_telephony_backend as _real` first
      and falls back to the local Fake/Live classes above on ImportError. The moment Module 3
      ships that real adapter, this function — and every call site in apps/agents/views/ —
      starts using it automatically, with NO edit here and NO edit at any call site."""
  ```
- **`apps/agents/readiness.py`** (or folded into `telephony.py`; a naming call for the `todo` pass) —
  `ReadinessIssue` dataclass (`code`, `field`, `message`, `live_only: bool`) and
  `check_setup_readiness(agent_setting) -> list[ReadinessIssue]`, covering the four REQUIRED blockers
  above (greeting, prompt, inbound number, transfer target, Twilio credentials).
- **One view/action** — e.g. `apps/agents/views/TestCall/AgentSetting.py` — rendering the readiness
  banner and, on submit, calling `get_telephony_backend().place_test_call(...)` after re-validating the
  destination number against `request.user.primary_phone` and the rate limit.
- **Template(s)** under `templates/agents/testcall/` (a standalone action surface per the template
  rules — Test Call has no persisted entity of its own to fold into an existing `<entity>/` folder).
- **`LIVE_LINKS["2.4"]`** entry pointing at the test-call page.
- **Tests:** `FakeTelephonyBackend` never imports `twilio-python` / never opens a network connection;
  `LiveTelephonyBackend.__init__` raises when `PROVIDER_MODE != 'live'`; `place_test_call` on the live
  backend raises when credentials are incomplete even in live mode; each of the four readiness-blocker
  codes fires/clears correctly, including the `live_only` distinction; rate-limit enforcement.
- **Seeder:** none owned by 2.4 (no new model to seed). Recommend to whichever pass builds 2.1's
  `seed_agents` command: seed at least one location's `AgentSetting` deliberately incomplete (blank
  greeting, or `transfer_enabled=True` with a blank `transfer_phone_number`) so the readiness check has
  something real to flag in demo data — a note for that seeder, not scoped or owned here.

## Belongs to sibling sub-modules (parked, not scoped here)

- `AgentSetting` CRUD itself — enable toggle, voice mode, greeting, prompt authoring, prompt variables
  → **2.1 Per-Location Agent Configuration**.
- Twilio credential entry, write-only auth token handling, webhook URL display, and the "Connection
  Check" that verifies credentials/number ownership against Twilio *without placing a call* → **2.2
  Twilio Connection**. Overlap note: 2.2's Connection Check and 2.4's Placed Test Call are cousins —
  one verifies plumbing, the other verifies the experience. 2.4 should reuse 2.2's credential
  validation logic once it exists rather than re-implement it.
- `transfer_enabled`, transfer targets, transfer working hours, transfer keywords, and their editing UI
  → **2.3 Transfer Settings**. 2.4 only **reads** `transfer_enabled`/`transfer_phone_number` for the
  readiness check; it never edits them.
- The real media-stream call path, the LLM turn loop, STT/TTS adapters, real Twilio webhook handling →
  **Module 3 (`runtime`)**. `apps/agents/telephony.py` is an explicitly temporary stand-in that Module 3
  takes over transparently.
- Logging a test call into a browsable call history or transcript view → **Module 5 (`calls`)** — no
  `CallSession` exists yet, and 2.4 does not create one.
- Booking or availability behaviour during a test call → **Module 4 (`scheduling`)** — irrelevant here;
  a test call only needs to be heard, not to succeed at booking.

## Out of scope for this product (outside the seven capabilities)

- Automated multi-scenario simulation/regression suites with scored personas (Synthflow Simulations,
  ElevenLabs Simulation API, Bland's 50-call regression baseline) — a QA/testing-infrastructure
  capability, not one of the seven capabilities; a small app doesn't need a persona-scoring engine.
- Draft/sandbox/live per-agent versioning (PolyAI) — no versioning concept anywhere in the eleven-model
  ERD; `AgentSetting` is exactly one row per location, not one row per version.
- Load/concurrency testing tooling as a tenant-facing product feature — an engineering/ops practice,
  not something a tenant clicks a button for.
- "Call in and try it yourself" as a team practice (PolyAI) — a runbook recommendation, nothing to
  implement.

## Deferred (later passes / integrations)

- **Live-mode real Twilio outbound test call** — needs Module 3's `apps.runtime.providers` to exist;
  2.4 ships the seam and the fake path now, and the live path activates automatically once Module 3
  lands, via the import-guarded `get_telephony_backend()` — zero code change at 2.4's call sites.
- **Recording a test call into a browsable log** — needs Module 5's `calls.CallSession` to exist; even
  then, whether test calls should be logged at all is a decision for that pass, not this one.
- **Regression/simulation test suites** — see Out of scope; revisit only if the product's scope ever
  grows to include QA-suite functionality, which it currently does not.
- **Browser/WebRTC test call transport** — needs Module 3's real-time audio pipeline; track as a
  transport enhancement to the existing Placed Test Call feature once available, not a new feature.
- **`sandbox` behavioral divergence from `fake`** — currently identical (both never touch Twilio);
  revisit once Module 3 defines what `sandbox` should uniquely mean (e.g. Twilio's own sandbox/test
  credential tier).
- **Whether a live test call should append a `CallSession.usage` cost-ledger entry** — no ledger exists
  this pass; decide once Module 5 exists, and only then, per Invariant 2 (one call log, no parallel
  ledger).
