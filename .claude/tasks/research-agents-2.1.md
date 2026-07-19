# Research — Sub-module 2.1: Per-Location Agent Configuration (Module 2 — Agent Setup & Telephony, agents)

## Repo state checked first

- **LIVE_LINKS built so far in module 2:** none. `apps/accounts/navigation.py::LIVE_LINKS` has only `0.1`–`1.4`.
  `2.1`–`2.4` are all unbuilt; this run will add `LIVE_LINKS["2.1"]`.
- **`apps/agents` does not exist at all** — confirmed via `Glob apps/**` (only `accounts` and `tenants` present)
  and `grep -rn "^class AgentSetting" apps/` (zero hits). This sub-module creates the app from nothing: `apps.py`,
  `models/`, `forms/`, `views/`, `urls/`, `templates/agents/`, `admin.py`, `management/commands/seed_agents.py`.
- **Sibling models verified to exist, available to FK:**
  - `tenants.Tenant` (`apps/tenants/models/Tenant.py`) — `name`, `slug`, `customer_id`, `timezone`, `is_active`.
  - `tenants.Location` (`apps/tenants/models/Location.py`) — `tenant` FK, `name`, `slug`, address fields,
    `timezone` (IANA, default `'UTC'`), `phone`, `is_active`, plus `full_address` and `tzinfo`/`local_now()`
    properties already implemented. **No `business_hours`/open-hours field exists on `Location`** — confirmed by
    reading the file directly. This is a real gap for the `is_open_now` runtime variable (see below).
  - `accounts.User` / `accounts.UserLocation` — exist, not needed by this sub-module's model directly.
- **Reusable toolkit confirmed present, not re-planned:** `TenantLocationModelForm` /
  `TenantModelForm` (`apps/accounts/forms/_common.py`) — `AgentSetting` carries both `tenant` and `location`, so
  its form subclasses `TenantLocationModelForm`. `paginate()` (`apps/accounts/views/_common.py`),
  `tier_required(*tiers)` / `safe_redirect_target()` (`apps/accounts/views/_helpers.py`), the `crud(base, name)`
  factory (`apps/tenants/urls.py`), `templates/base.html`, `partials/_pagination.html`, `partials/_empty_state.html`.
- **Settings already in place:** `config/settings.py` defines `ENCRYPTION_KEY`, `PROVIDER_MODE` (validated into
  `{fake, sandbox, live}`, default `fake`), `TWILIO_WEBHOOK_BASE_URL`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
  (platform-level fallback credentials, `.env`-sourced). `cryptography` 49 is installed — usable for a Fernet-based
  encrypted field on `twilio_auth_token`.
- **`apps/runtime` (Module 3) does not exist.** No `apps/runtime/providers/` seam exists yet. This sub-module must
  not import it; the prompt/greeting-rendering function this pass builds is a **pure Python string-substitution
  utility inside `apps/agents`**, with no provider dependency, that Module 3 will later import and reuse verbatim
  at call time (same function, called per-turn instead of at save-time).
- **Sibling research files:** `Glob .claude/tasks/research-*.md` found `research-accounts-0.*` (4 files) and
  `research-tenants-1.*` (4 files) only. No prior `research-agents-*.md` exists — 2.1 is the first Module 2
  research pass, so there is no earlier-file backlog to inherit from within this module.

## Leaders surveyed (with source links)

1. **Retell AI** — developer-first voice-agent platform; explicit `{{variable}}` dynamic-variable system, agent-level
   default values, and a documented set of auto-populated system variables (`current_time`, `call_id`, etc.) —
   [Dynamic Variables](https://docs.retellai.com/build/dynamic-variables),
   [Configure basic settings](https://docs.retellai.com/build/single-multi-prompt/configure-basic-settings),
   [Choose a voice](https://docs.retellai.com/build/voice)
2. **Vapi** — assistant builder with `{{variableName}}` templating resolved via `assistantOverrides.variableValues`,
   a fixed set of built-in time/call variables, and LiquidJS-based conditional/date formatting —
   [Variables](https://docs.vapi.ai/assistants/dynamic-variables)
3. **Synthflow** — no-code agent builder distinguishing a dedicated "Greeting Message" (first thing the caller
   hears) from the agent's flow/prompt, plus a separate Voice Configuration panel (voice model, speed, stability) —
   [Create an Agent](https://docs.synthflow.ai/create-an-agent),
   [Voice Configuration](https://docs.synthflow.ai/voice-configuration),
   [The Agent Editor](https://docs.synthflow.ai/the-agent-editor)
4. **Bland AI** — pathway/flow builder with a `first_sentence` field distinct from node prompts, `dynamic_data`
   injected from a webhook, and per-node choice between a scripted fixed sentence and an AI-generated reply —
   [Conversational Pathways](https://docs.bland.ai/tutorials/pathways)
5. **ElevenLabs Agents** — explicit separation of "system prompt" (persona/policy) from "first message" (spoken
   greeting), `{{ var_name }}` dynamic variables, and automatically available system variables
   (`system__caller_id`, `system__called_number`, `system__call_duration_secs`) —
   [Dynamic variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables),
   [Personalization](https://elevenlabs.io/docs/eleven-agents/customization/personalization)
6. **Goodcall** — managed AI receptionist; greeting is explicitly tailorable by **Open Hours vs. After Hours**
   state, i.e. an `is_open_now`-style branch baked directly into the scripted greeting —
   [How to Create the Perfect Greeting](https://help.goodcall.com/en/articles/8348837-how-to-create-the-perfect-greeting-for-your-ai-assistant)
7. **Dialpad AI** — auto-attendant / AI receptionist with time-of-day and holiday-aware routing that swaps the
   greeting and script automatically at the boundary, confirming "is it open" must be evaluated live, not once —
   [AI Virtual Receptionist](https://www.dialpad.com/solutions/ai-virtual-receptionist/)
8. **Smith.ai** — hybrid AI + human receptionist; "AI receptionist prompting" as a documented discipline (persona,
   tone, escalation triggers) even without exposing raw `{{var}}` templating to the customer —
   [AI Receptionist Prompting](https://smith.ai/blog/ai-receptionist-prompting)
9. **PolyAI** — enterprise voice AI; per-site/per-brand configuration is standard at their scale, though public
   docs on the exact greeting/prompt authoring UI are limited — [poly.ai](https://poly.ai/)

**Finding confirmed across the developer-platform group (Retell, Vapi, Synthflow, Bland, ElevenLabs):** all five
separate a **deterministic opening line** (`begin_message` / `first message` / `first_sentence` / "Greeting
Message") from the **system prompt**, and all five support `{{variable}}`-style substitution in both. This is the
strongest, most consistent signal in the whole survey and validates the sub-module's own "Deterministic Greeting"
+ "Prompt Variables" split exactly. The managed-service group (Goodcall, Dialpad, Smith.ai) confirms the
**business-hours-aware greeting** pattern independently, from the receptionist-operations side rather than the
developer-platform side — i.e. two very different market segments converge on the same requirement.

## Feature catalog (this sub-module only)

### One Setting per Location
- **Single row per (tenant, location), enforced at the DB layer** — what it does: makes "the location's agent" an
  unambiguous lookup (`AgentSetting.objects.get(tenant=t, location=l)`), never a list to disambiguate · seen in:
  Retell/Vapi/Synthflow (one agent config object per number/assistant — never many competing configs per number) ·
  priority: table-stakes · model: `agents.AgentSetting`, **new table**, tenant + location scoped, `unique_together`
  or `UniqueConstraint(fields=["tenant", "location"])` · realtime: post-call (a config lookup, not a hot-path
  computation itself — though the row IS read on the hot path by Module 3) · tool-surface: pure UI/model
  constraint, no tool · buildable now.
- **Auto-provision an empty (disabled) row when a location is created, or provision on first visit to Setup** —
  what it does: means a fresh location always has *something* to edit rather than a 404/blank state · seen in:
  Retell/Vapi (every new assistant starts life "empty but existing", not absent) · priority: common · model:
  reuses `agents.AgentSetting` — `get_or_create(tenant=request.tenant, location=request.location, defaults={...})`
  in the setup view · realtime: post-call · tool-surface: pure UI · buildable now.

### Enable Toggle & Voice Mode
- **Master enable/disable switch, independent of field completeness** — what it does: lets an admin flip the
  location's agent off without deleting its configuration (e.g. temporarily route to voicemail) · seen in: every
  platform surveyed has an equivalent published/live vs. draft/disabled state (Retell agent versions, Vapi
  assistant active flag, Goodcall "activate line") · priority: table-stakes · model: reuses `agents.AgentSetting`
  (`enabled` Bool) · realtime: **live-call hot path** — Module 3's webhook resolution reads `enabled` before
  connecting the media stream; a disabled location must degrade to an out-of-service message rather than silently
  answering (this sub-module only stores the flag; the branch itself is 3.1's Unmapped/Disabled-Number Handling) ·
  tool-surface: pure UI (the flag is read by the runtime, never set by the model) · buildable now.
- **Voice/provider mode selection (`live` / `google` / `gemini`)** — what it does: chooses which underlying
  realtime STT+LLM+TTS pipeline answers this location's calls · seen in: Retell/Vapi/Synthflow all expose an
  analogous provider/model choice (LLM provider, TTS provider, STT provider — Retell explicitly supports
  ElevenLabs/OpenAI/Cartesia/PlayHT with automatic fallback); the managed-service group (Smith.ai, Goodcall, Rosie)
  does **not** expose this at all — it is an internal implementation detail for them · priority: common (roughly
  half the surveyed group has an analogous concept; the other half abstracts it away entirely — note this split
  explicitly rather than overstating consensus) · model: reuses `agents.AgentSetting.voice_provider` (Char(16),
  choices already fixed by the ERD: `live`/`google`/`gemini`) · realtime: **live-call hot path** — Module 3 branches
  its provider-adapter selection on this value; this sub-module only stores the enum, it does not implement any
  adapter · tool-surface: pure UI, a `<select>` bound to the three fixed choices — no new tool · integration/later
  for the actual pipeline behind each choice (Module 3's `apps/runtime/providers/`); the field itself is buildable
  now.
- **`CallSession.mode` mirrors `AgentSetting.voice_provider` at call start** — what it does: the ERD already
  states `calls.CallSession.mode` "mirrors `AgentSetting.voice_provider`" — noted here only so the `todo` agent
  does not treat this as a 2.1 concern: the mirroring write happens in Module 3 at call setup, not in this
  sub-module. Belongs to 3.1/3.2.

### Deterministic Greeting
- **Greeting is a separate field from the system prompt, spoken with zero LLM round trip** — what it does: the
  opening line plays the instant the call connects, with no model call on the critical path · seen in: Retell
  (`begin_message`), Vapi (`first message`), Synthflow ("Greeting Message"), Bland (`first_sentence`), ElevenLabs
  ("first message") — **five-for-five** of the developer platforms surveyed separate these two fields · priority:
  **table-stakes**, and separately re-affirmed as a hard project invariant (CLAUDE.md Realtime Rule 5: "The
  greeting/opener is deterministic... rendered server-side from `AgentSetting.greeting`, costs 0 LLM tokens") ·
  model: reuses `agents.AgentSetting.greeting` (Text, blank, `{{var}}`-aware) · realtime: **live-call hot path** —
  the single highest-latency-sensitivity feature in this whole sub-module, since it determines first-audio timing;
  this sub-module's job is only to store and validate the text — the actual zero-token server-side render at
  connect time is Module 3's job · tool-surface: pure UI in this sub-module (no tool — Module 3 later calls the
  shared render function, not a tool) · buildable now (the field, its validation and its preview); the runtime
  render path is integration/later (Module 3).
- **Business-hours-aware greeting (different opening line when closed)** — what it does: swaps the greeting's
  content based on whether a human/the business is currently "open" · seen in: Goodcall (explicit Open Hours vs.
  After Hours greeting tailoring), Dialpad (time-of-day and holiday-aware greeting/routing swap) · priority:
  common · model: **no new field** — deliver this through the existing `{{is_open_now}}` server-computed variable
  inside the single `greeting` field (e.g. "{% raw %}{{is_open_now}}{% endraw %}"-style conditional phrasing is
  out of scope for a plain `{{var}}` substitution engine that has no `if`/`else` — so the practical delivery is:
  the admin writes the greeting to read naturally either way, using `{{is_open_now}}` as a yes/no literal the
  model or a short scripted branch can react to, OR — cleaner for a pure string-substitution field — the greeting
  simply never claims "we're open" and the **prompt** (which the LLM does reason over) is what branches behavior
  based on `{{is_open_now}}`. Recommendation: keep `greeting` itself hours-neutral ("Thanks for calling
  {{location_name}}.") and let `prompt_text` carry the open/closed branching, since only the LLM can conditionally
  reason over a literal — the deterministic greeting field has no control-flow capability by design (that is
  exactly why it costs 0 LLM tokens). realtime: **live-call hot path** for the variable's value, computed at
  connect time · tool-surface: none — this is a modeling/authoring-guidance finding, not a new field · buildable
  now (as the `is_open_now` variable definition below), with the caveat that true conditional greeting text is a
  documented limitation of a template-only deterministic field, not a gap to be closed by a new model.
- **Greeting length / delivery guidance surfaced in the editor** — what it does: nudges authors toward a short,
  clear opening line rather than a paragraph, since a long deterministic greeting still delays the caller's first
  turn even without an LLM call · seen in: Smith.ai's greeting-script guidance content, Goodcall's "greeting is the
  most important part... guide callers down the right path" advice · priority: common · model: none — pure UI
  (character-count hint / help text) · realtime: post-call (an authoring-time nudge) · tool-surface: pure UI ·
  buildable now.

### Prompt Authoring
- **Full system-prompt text editor, separate from the greeting** — what it does: the persona/policy/guardrail text
  the LLM actually reasons over across the whole call · seen in: ElevenLabs ("system prompt is the personality and
  policy blueprint"), Retell/Vapi ("Prompts" configuration section) · priority: table-stakes · model: reuses
  `agents.AgentSetting.prompt_text` (Text, blank) · realtime: **live-call hot path** — this text is the LLM's
  system message on every turn of the call; this sub-module only stores/validates it, Module 3 injects it verbatim
  (post-substitution) at session start · tool-surface: pure UI (textarea) · buildable now.
- **Rendered preview before saving (variables substituted with sample/server-computed values)** — what it does: a
  side panel or "preview" action shows the prompt/greeting as it would actually read on a live call, with
  `{{var}}` tokens replaced by either the admin's own `variables` values or realistic sample runtime values ·
  seen in: adjacent to Retell's `{{` variable-picker (autocomplete while typing) and the live-testing tools all
  five developer platforms ship (Retell LLM Playground/chat simulation, Vapi web-call test, ElevenLabs test
  conversation) — none of those surveyed is a *static substitution preview* specifically, they are full
  conversational tests; a lightweight text-substitution preview is a lighter-weight, cheaper-to-build analogue of
  the same underlying need ("see what the caller will actually hear/read before it goes live") · priority: common
  (the *need* is table-stakes across every platform surveyed; the specific *static-preview* mechanism is this
  product's own simpler take on it — full live-call testing is 2.4's Test Call, not this sub-module's job) ·
  model: no new field — a pure server-side render using the same substitution function the save-time validator and
  Module 3 both use, fed with either the row's own `variables` values or a documented set of representative sample
  values for the reserved runtime variables · realtime: post-call (an authoring-time HTMX-driven preview, not a
  call in progress) · tool-surface: pure UI — an HTMX endpoint that returns the rendered HTML fragment, no LLM
  tool · buildable now.
- **Prompt-engineering guidance / templates surfaced in the editor** — what it does: starter prompt text, section
  headers (role, tone, escalation rules) to reduce blank-page problem · seen in: Retell's "Prompt Engineering
  Guide" and "5 Useful Prompts" content, Smith.ai's "AI Receptionist Prompting" guide (role, tone, formality,
  escalation triggers as explicit dimensions) · priority: differentiator · model: none — static help text /
  a default `prompt_text` seed value on row creation · realtime: post-call · tool-surface: pure UI · buildable now
  (cheap to include, but not required for a first pass — flagged as differentiator, not table-stakes).

### Prompt Variables
- **`{{variable}}` substitution syntax, shared between greeting and prompt** — what it does: the single templating
  mechanism both deterministic and LLM-reasoned text use · seen in: Retell, Vapi, Bland, ElevenLabs, Synthflow —
  **five-for-five** · priority: table-stakes · model: reuses `agents.AgentSetting.variables` (JSON dict — the
  admin-defined map) · realtime: the *substitution itself* is **live-call hot path** (must happen before the
  greeting plays and before the first LLM turn); the *authoring* of the map is post-call/UI · tool-surface: pure
  UI for authoring; a plain Python `render(text, values) -> str` service function for substitution — **not** an
  LLM tool, since the model never calls this, the server always applies it before the model or the caller sees
  anything · buildable now (the function and its validation); its reuse inside the live turn loop is
  integration/later (Module 3 imports the same function).
- **Server-computed runtime variables, injected alongside the admin's own map** — what it does: a fixed set of
  values the *server* knows and the admin cannot mistype, merged into the substitution context at call setup ·
  seen in: Retell's automatic system variables (`current_time`, `call_id`, `direction`), Vapi's built-ins (`now`,
  `date`, `time`, `customer.number`, `call.id`), ElevenLabs' `system__*` variables (`system__caller_id`,
  `system__called_number`, `system__call_duration_secs`) — **three-for-three** of the platforms that expose raw
  `{{var}}` templating also ship a reserved, always-available variable set · priority: **table-stakes** · model:
  reuses `agents.AgentSetting.variables` semantics (the reserved names are never *stored* on the row — they are
  computed and merged at render time, so they cannot go stale or be hand-edited) · realtime: **live-call hot
  path**, with a critical distinction the research surfaced clearly — **static-at-setup vs. must-recompute-per-turn**:
  - Computed **once** at call setup, safe to freeze for the call's duration: `location_name` (`Location.name`),
    `business_name` (`Tenant.name`), `location_address` (`Location.full_address`), `location_timezone`
    (`Location.timezone`), `from_number` (the caller's ANI from the Twilio webhook), `to_number` (the dialed
    number == `AgentSetting.inbound_phone_number`).
  - **Must be recomputed on every turn, never captured once at call start**: `current_date`, `current_time`, and
    `is_open_now`. This is the exact trap Retell's own docs implicitly avoid by documenting `{{current_time}}` as
    a **live, per-request** substitution rather than a cached call-start value — a call that runs 20+ minutes
    (this product's own hard cap is 15 minutes default, but even a 5-minute call crossing a business-hours
    boundary) must not keep telling the caller "we're open" after closing time simply because that literal was
    baked in at minute zero. **This is a Module 3 runtime-loop responsibility** (recompute before each greeting/
    prompt render, not once at `connect()`), but the *variable's existence and its "always live" contract* is
    defined here, in 2.1, as part of the reserved-variable catalog.
  - tool-surface: none of these are LLM tools — they are server-side context injected before generation, distinct
    from the `get_business_info` **tool** (Module 3.3's Built-In Tool Set) that lets the model actively *query*
    business info mid-call. The two are complementary: injected variables avoid a tool round-trip for the most
    common facts; the tool exists for anything not pre-injected. · buildable now (2.1 defines the reserved-name
    list and a placeholder resolver for its own preview — see `is_open_now` gap below); full per-turn recomputation
    is integration/later (Module 3).
  - **Known data gap for `is_open_now`:** there is **no `Location`-level business-hours field** in the eleven-model
    set (verified — `tenants.Location` has no such field; `agents.AgentSetting.transfer_working_hours` is scoped
    to the human-transfer window, a 2.3 concept, not general "is the business open" semantics). Recommendation:
    2.1 defines `is_open_now` in the reserved-variable catalog and documents its **fallback semantics now**
    (always `"yes"` — an AI receptionist that answers 24/7 has no true "closed" state at the agent layer) so the
    variable is never undefined; if a future pass adds real business hours to `Location` (out of this sub-module's
    scope — would need a new field on an already-shipped foundation-app model, i.e. a `tenants` migration, not an
    `agents` one), `is_open_now` starts reflecting it with no prompt-authoring change required, because the admin
    only ever references the variable name, never its source.
- **Reject unknown placeholders at save time** — what it does: a `{{typo_var}}` in `greeting` or `prompt_text`
  that matches neither the admin's own `variables` keys nor the reserved runtime-variable names is a hard
  validation error on save, not a silently-broken call later · seen in: **not** the common behavior among the
  platforms surveyed — Retell's own docs state an unmatched variable simply "remain[s] in its raw form with the
  curly braces intact" (graceful runtime degradation, no save-time block); Vapi's validation errors observed in
  support cases are incidental (payload-shape mismatches), not a designed "reject on save" feature. **This
  sub-module's documented bullet is a deliberate, stricter design choice than the market norm** — worth stating
  plainly rather than mis-citing it as table-stakes. priority: table-stakes **for this product specifically**
  (it is an explicit bullet in `NavAIReceptionist.md`, and the safer failure mode for a small business admin who
  will not be reading Retell-style raw-braces output on a live customer call) · model: no new field — pure
  `form.clean()` validation: regex-extract `{{...}}` tokens from both `greeting` and `prompt_text`, check each
  against `set(instance.variables.keys()) | RESERVED_RUNTIME_VARIABLE_NAMES`, reject with the offending token
  names listed if any are outside that union · realtime: post-call (save-time only; nothing about this runs on the
  hot path) · tool-surface: pure UI/form validation, no tool · buildable now.
- **Reserved-name collision guard** — what it does: an admin cannot define a custom variable named `current_time`,
  `is_open_now`, etc. in their own `variables` JSON map, because that would silently shadow the server-computed
  value with a stale/wrong one · seen in: implied by every platform's "system variables are read-only /
  automatically available" framing (Retell, Vapi, ElevenLabs all describe their built-ins as non-overridable) ·
  priority: table-stakes · model: same validator as above — reject any `variables` key that collides with
  `RESERVED_RUNTIME_VARIABLE_NAMES` · realtime: post-call (save-time) · tool-surface: pure UI/form validation ·
  buildable now.
- **Untemplated-string safety** — what it does: `greeting`/`prompt_text` with zero `{{...}}` tokens (a location
  that wants fully static text) is valid and common, not an error · seen in: implicit in every platform (templating
  is opt-in, not mandatory) · priority: table-stakes · model: none, a validator behavior note · realtime: n/a ·
  tool-surface: pure UI · buildable now.
- **Do not use Django's full template engine (`{% %}` tags) for this substitution** — what it does/why it matters:
  a security- and correctness-relevant implementation note surfaced by this research, not a competitor feature —
  `greeting`/`prompt_text` are authored by a tenant admin (a semi-trusted but not developer-trusted actor) and
  will later be rendered server-side on every call; using Django's `Template`/`Context` machinery (which
  interprets `{% ... %}` tags, filters and attribute-lookup chains, not just `{{ var }}`) on admin-supplied text
  is unnecessary surface area for a feature that only needs flat key→string substitution. Recommendation: a
  minimal regex-based `{{identifier}}` -> `str(value)` replacer, with no filter/tag support, no attribute
  traversal, and unmatched tokens left as an explicit save-time validation error (see above) rather than silently
  rendered or executed. priority: table-stakes (this is a correctness/security baseline, not optional) · model:
  none — a pure function in `apps/agents/services.py` · realtime: the function itself runs on the hot path in
  Module 3 later, but authoring/validation here is post-call · tool-surface: none · buildable now.

### Beyond the bullets
- **Voice/tone style presets (formal, friendly, concise) as prompt-authoring shortcuts** — what it does: quick-pick
  chips that insert boilerplate phrasing into `prompt_text` · seen in: Smith.ai's documented persona dimensions
  (communication style, formality, response length) · priority: differentiator · model: none, pure UI · realtime:
  post-call · tool-surface: pure UI · deferred — nice-to-have, not requested by any bullet, adds editor complexity
  for a first pass.
- **Prompt version history / rollback** — what it does: keeps prior `prompt_text`/`greeting` revisions so a bad
  edit can be reverted · seen in: Retell's agent versioning and environment tags · priority: differentiator ·
  model: would need a new revision-history table — **violates the zero-second-model constraint for this pass** ·
  deferred.
- **A/B testing two prompt variants** — seen in: not directly documented by any surveyed product's public docs at
  the per-agent level (more of an enterprise/PolyAI-scale capability) · priority: differentiator · out of scope
  for this product — no experimentation capability among the seven documented capabilities.

## Compliance & provider constraints

- **REQUIRED — AI-interaction / recording-consent disclosure text has to live somewhere, and the greeting is the
  correct place to author it.** Several US states require an up-front AI-interaction disclosure, and two-party-
  consent jurisdictions require a recording announcement before recording starts. The deterministic `greeting`
  field is spoken before anything else on the call, so it is the natural (and in this product, the *only*)
  authoring surface for that required wording. **This sub-module does not need a new field** — `greeting` already
  supports free text — but the Setup form should surface help text/a default template reminding the admin that
  jurisdiction-required disclosure belongs in this field, and the actual consent-gating logic (deciding *whether*
  to record, based on the announcement having played) is **Module 3.5's** job (`Consent-Gated Recording`), not
  this sub-module's. Flagging this here so the `todo` agent does not drop it as "not our concern" — the *place*
  for the wording is decided in 2.1 even though the *enforcement* is decided in 3.5.
- **No HIPAA/GDPR retention trigger in this sub-module.** 2.1 stores configuration text (greeting, prompt,
  variable names/values), not call content, transcripts or recordings — those obligations attach to
  `calls.CallSession` (Module 5) and the recording pipeline (Module 3.5), not to `agents.AgentSetting`.
- **`twilio_auth_token` encryption-at-rest is a REQUIRED constraint on the model this pass creates, even though
  2.1's own form never touches the field.** Because `agents.AgentSetting` is the single model for the whole
  `agents` app and this is its first migration, the column must be created encryption-ready from day one — a
  plaintext-then-retrofit path is the exact anti-pattern CLAUDE.md's Vulnerability section calls out. Use
  `cryptography.fernet.Fernet(settings.ENCRYPTION_KEY)` behind a small custom field/property; 2.2 (Twilio
  Connection) builds the write-only form around it, but the column's storage contract is decided now.
- **No Twilio/STT/TTS/LLM cost lines from this sub-module.** 2.1 touches no live provider call and appends nothing
  to `calls.CallSession.usage` — greeting/prompt authoring and its preview are pure local rendering, zero token
  cost, zero API cost. (Contrast with the *runtime* render of the same text at call time, which is what actually
  costs LLM tokens for `prompt_text` — the `greeting` render costs **zero** LLM tokens even at call time, per the
  documented bullet and CLAUDE.md Realtime Rule 5.)
- **`PROVIDER_MODE` has no bearing on this sub-module.** There is no provider call anywhere in 2.1's scope (no
  Twilio, no STT/TTS/LLM) — the fake/sandbox/live distinction becomes relevant starting at 2.2 (Connection Check)
  and 2.4 (Test Call), not here.

## Recommended build scope (this pass)

**CRUD sub-module — 1 model** (the only model the whole `agents` app owns, per the eleven-model ceiling; built in
full now because it is a single reused row across 2.1/2.2/2.3, not four separate tables):

- **`agents.AgentSetting`** — tenant **and** location scoped — `UniqueConstraint(fields=["tenant", "location"])`.
  Full ERD field set is created in this pass's migration (all of it lives in one table per the ERD's explicit
  design intent — "the single most directly reusable model: it already carries agent config, Twilio credentials
  AND transfer settings in one row"): `tenant` FK, `location` FK, `enabled` (Bool, default `False`),
  `voice_provider` (Char(16), choices `live`/`google`/`gemini`, default `live`), `greeting` (Text, blank),
  `prompt_text` (Text, blank), `variables` (JSON dict, default `{}`), `inbound_phone_number` (Char(32), E.164,
  globally unique), `twilio_account_sid` (Char(64), blank), `twilio_auth_token` (Char(128), blank — **encrypted
  at rest via a custom field, write-only in forms from day one**), `transfer_enabled` (Bool, default `False`),
  `transfer_phone_number` (Char(32)), `transfer_secondary_number` (Char(32)), `transfer_timezone` (Char(100),
  default `"America/Chicago"`), `transfer_working_hours` (JSON), `transfer_keywords` (JSON list).
  **However, THIS sub-module's own forms/views/templates touch only the 2.1-bulleted columns**:
  `enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables` — justified by: One Setting per Location,
  Enable Toggle & Voice Mode, Deterministic Greeting, Prompt Authoring, Prompt Variables (all above). The
  remaining columns exist on the row from this migration onward but get their own dedicated forms/views/templates
  in sibling sub-modules — see "Belongs to sibling sub-modules" below. This keeps 2.1's Setup page focused on
  exactly its five documented bullets while avoiding a second migration later for the same table.
  FKs: `tenants.Tenant` (verified), `tenants.Location` (verified).

**Supporting service, not a model:** `apps/agents/services.py::render_template(text: str, values: dict) -> str` —
the shared `{{var}}`-substitution function used by (a) the save-time "reject unknown placeholders" validator,
(b) the authoring-time rendered preview (HTMX fragment), and (c) later, verbatim, by Module 3's turn loop for both
the deterministic greeting render and the system-prompt render at call setup. Also
`apps/agents/services.py::RESERVED_RUNTIME_VARIABLE_NAMES` and a
`apps/agents/services.py::sample_runtime_context(location)` helper that returns representative values (including
`is_open_now` always `"yes"`, per the documented gap/fallback above) for the preview to use when the row has no
`variables` override for a reserved name.

**Deferred — no field/model added this pass:**
- A `Location`-level business-hours field to make `is_open_now` reflect real open/closed state — would be a
  `tenants` app migration (an already-shipped foundation app), out of this sub-module's ownership; `is_open_now`
  defaults to always-open until such a field exists.
- Prompt version history/rollback — needs a new revision table, violates the zero-second-model constraint.
- Voice/tone style preset chips, prompt-engineering starter templates — pure UI sugar, not requested by any bullet.

## Belongs to sibling sub-modules (parked, not scoped here)

- `twilio_account_sid` / `twilio_auth_token` write-only form, `inbound_phone_number` binding, webhook URL display,
  connection check against Twilio → **2.2 Per-Location Credentials / Twilio Connection**
- `transfer_enabled`, `transfer_phone_number`, `transfer_secondary_number`, `transfer_timezone`,
  `transfer_working_hours`, `transfer_keywords` forms/views → **2.3 Transfer Settings**
- Placed test call, fake-mode test path, setup-readiness check (flagging a missing greeting/prompt/inbound
  number/transfer target) → **2.4 Test Call**
- The actual server-side render of `greeting`/`prompt_text` at call connect time, per-turn recomputation of
  `current_date`/`current_time`/`is_open_now`, and `CallSession.mode` mirroring `AgentSetting.voice_provider` →
  **3.1/3.2 Inbound Webhook & Media Stream** (Module 3)
- `get_business_info` LLM tool (model actively querying business facts mid-call) → **3.3 Tools & Dispatcher**
  (Module 3) — complementary to, not a replacement for, this sub-module's injected variables
- Consent-gating logic that decides whether recording actually starts → **3.5 Recording, Teardown & Diagnostics**
  (Module 3)

## Out of scope for this product (outside the seven capabilities)

- Prompt A/B testing / experimentation framework — no experimentation capability among login / password-email /
  calendar / bookings / agent setup+Twilio / call transfer / user profile
- Directory-listing sync (Google Business Profile) to auto-fill business hours for `is_open_now` — no
  listing-integration capability documented anywhere in the product

## Deferred (later passes / integrations)

- Real `is_open_now` semantics backed by a genuine business-hours field — needs a `tenants.Location` migration,
  which is a foundation-app change outside this sub-module's scope; documented here as a known limitation, not
  silently ignored
- Prompt version history/rollback — needs a new model; deferred until there's a concrete requirement to justify it
- Voice/tone preset chips, prompt-engineering starter-template library — editor-polish, not requested by any bullet
- The full realtime rendering/recomputation path itself — belongs to Module 3, which does not exist yet; 2.1 only
  builds the shared pure-Python render function and its validation, for Module 3 to import later
