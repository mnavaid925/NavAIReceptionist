# Research — Sub-module 2.3: Transfer Settings (Module 2 — Agent Setup & Telephony, agents)

## Repo state checked first

- **LIVE_LINKS built so far in module 2:** none. `apps/accounts/navigation.py` only has `'0.1'`–`'0.4'` and
  `'1.1'`–`'1.4'` entries; `2.1`–`2.4` are all unbuilt sidebar placeholders today. This research targets `2.3`
  directly, as named by the invoking prompt (overriding the "next unbuilt in the module" default, per the
  resolution rule for an explicit `N.M`).
- **`apps/agents` already has partial scaffolding, but NO model.** `Glob apps/agents/**` shows only
  `__init__.py`, `apps.py`, `migrations/__init__.py`, `fields.py` — **no `models/`, `forms/`, `views/`, `urls/`
  package exists**. `apps.agents` is **not yet in `INSTALLED_APPS`** (`config/settings.py:88-104` lists only
  `apps.accounts` and `apps.tenants`). `grep "^class AgentSetting" apps/` returns **no matches** — confirms
  `agents.AgentSetting` does not exist yet anywhere in the repo. `NavAIReceptionist-ERD.md` is intent only.
  - `apps/agents/fields.py` already defines `EncryptedCharField` (Fernet, `fernet:` prefix, write-only
    semantics, `mask_secret()`, 512-char ciphertext column) — this is 2.2's `twilio_auth_token` field, already
    built ahead of the model itself. Not re-planned here; noted so `todo` doesn't recreate it.
  - `apps/agents/apps.py` sets `label = 'agents'`, `verbose_name = 'Agent Setup & Telephony'` — ready to register.
  - Because the model doesn't exist yet, **whichever sub-module actually builds it must create the full
    `AgentSetting` row-shape in one migration** (`unique(tenant, location)` — it cannot be split field-by-field
    across sub-module migrations without churn). See **Recommended build scope** below for how 2.3 should handle
    this given it is very likely to run before 2.1/2.2/2.4.
- **Sibling models verified to exist (grep evidence):**
  - `apps\tenants\models\Tenant.py:11` — `class Tenant(TimeStamped)`.
  - `apps\tenants\models\Location.py:18` — `class Location(TenantOwned)`.
  - `scheduling.CallbackRequest`, `calls.CallSession` — **NOT built**; `Glob apps/scheduling/**` and
    `Glob apps/runtime/**` both return nothing. Any feature that would reuse either is parked to its own module,
    not built against here.
- **Reusable, not re-planned:** `TenantModelForm`/`TenantLocationModelForm` (`apps/accounts/forms/_common.py`),
  `paginate()` (`apps/accounts/views/_common.py`), `tier_required()`/`safe_redirect_target()`
  (`apps/accounts/views/_helpers.py`), the `crud(base, name)` factory pattern (`apps/tenants/urls.py`),
  `base.html`, `_pagination.html`, `_empty_state.html`, the closed theme.css badge/stat-icon set.
- **Sibling research files:** `research-tenants-1.4.md` (Provider Working Hours) is the closest analogue —
  it built a **weekly-hours JSON editor** over `accounts.User.provider_hours`
  (`{"<location_id>": [{"start_time","end_time","days":[...]}]}`) with `services.py` helpers
  (`get_provider_intervals`, `validate_provider_hours`) and a formset UI. **This sub-module's
  `transfer_working_hours` shape is deliberately different** — `{weekday: {"enabled": bool, "start": "HH:MM",
  "end": "HH:MM"}}` for `monday`…`sunday`, **one interval per named weekday, keyed by weekday, not by location**
  (the whole JSON already lives on one location's `AgentSetting` row, so there is no location key to fan out
  over, unlike `provider_hours` which is one `User` row serving many locations). The two editors should **look
  visually consistent** (per-weekday rows, HH:MM inputs, a location-timezone label) but must **not** share the
  formset/service code — a different validator, a different service module, a different form shape. This is
  called out explicitly per the invoking prompt's instruction.
  No other sibling research file (`0.1`–`0.4`) touches transfer/escalation.

## Leaders surveyed (with source links)

1. **Retell AI** — voice-agent platform with the most granular transfer tool: cold/warm/"agentic warm" transfer,
   human-presence detection, whisper + three-way messages, caller-ID control —
   [Transfer call tool](https://docs.retellai.com/build/single-multi-prompt/transfer-call),
   [Call Transfer feature](https://www.retellai.com/features/call-transfer),
   [Warm Transfer blog](https://www.retellai.com/blog/effortless-handoffs-with-retell-ais-warm-transfer-feature)
2. **Vapi** — `transferCall` tool with static destinations, dynamic (model- or server-supplied) destinations, and
   a `transfer-destination-request` webhook for runtime routing —
   [Call Forwarding](https://docs.vapi.ai/call-forwarding),
   [Dynamic call transfers](https://docs.vapi.ai/calls/call-dynamic-transfers)
3. **Bland AI** — explicit-request-always-transfers policy, sentiment/intent-triggered escalation, a
   "proxy agent" that briefs the human before merging the call —
   [Warm Transfers](https://www.bland.ai/blogs/warm-transfers),
   [Live transfer docs](https://docs.bland.ai/tutorials/live-transfer),
   [Escalation management](https://www.bland.ai/blog/escalation-management)
4. **Synthflow** — TEL/SIP/dynamic transfer types, phone-number format validation with a "validate" button, a
   dedicated Transfer Settings tab governing handoff feel and failure recovery —
   [Call Transfers](https://docs.synthflow.ai/call-transfers),
   [Dynamic Transfers](https://docs.synthflow.ai/dynamic-transfers)
5. **PolyAI** — enterprise handoff with SIP REFER, full conversation-context summary passed to the human agent,
   configurable SIP-header metadata — [Handoff](https://docs.poly.ai/call-handoff/introduction),
   [Agent handover](https://poly.ai/blog/agent-handover)
6. **Smith.ai** — human-backed AI receptionist; explicit escalation-trigger taxonomy (caller request, AI
   limitation, sentiment threshold, business rule), business-hours-gated transfer with a documented default
   after-hours refusal — [AI-powered call escalation](https://smith.ai/blog/ai-powered-call-escalation),
   [24/7 receptionists FAQ](https://docs.smith.ai/article/70s1gb2qpk-24-7-receptionists-faq)
7. **Ruby Receptionists** — live-receptionist service; per-customer after-hours instructions, explicit
   operational guidance to avoid dialing personal cell numbers late at night —
   [Ruby's Business Hours and Availability](https://rubyhelpcenter.helpjuice.com/en_US/call-handling/ruby%E2%80%99s-business-hours-and-availability),
   [24/7 Reception Service](https://rubyhelpcenter.helpjuice.com/answering-hours/extended-hours-247-reception-service)
8. **Goodcall** — AI phone agent "operator" workflow: default transfer-to-business-line with tenant override to a
   specific person/department, or a take-a-message/callback fallback —
   [How Goodcall Works](https://www.goodcall.com/how-it-works)
9. **Dialpad AI** — auto-attendant with time-of-day/holiday routing rules and full-context handoff (sentiment +
   steps taken) passed to the receiving human agent —
   [Auto Attendant](https://www.dialpad.com/features/auto-attendant/),
   [AI Virtual Receptionist](https://www.dialpad.com/solutions/ai-virtual-receptionist/)

## Feature catalog (this sub-module only)

### Transfer Enable & Targets
- **Master transfer toggle** — a single on/off switch gating whether the agent ever offers a human handoff for
  this location · seen in: every leader surveyed (all gate transfer behind a location/account-level switch) ·
  priority: table-stakes · model: reuses `agents.AgentSetting.transfer_enabled` (tenant + location scoped) ·
  realtime: **post-call config**, but it gates a **live-call hot-path** decision (whether Module 3 even registers
  a transfer tool for this call) · tool-surface: no new tool in 2.3 — it is the flag Module 3's tool dispatcher
  checks before honoring any transfer request; a prompt-authoring concern for 2.1 (the system prompt should not
  offer transfer when disabled) · buildable now.
- **Primary + secondary/fallback destination numbers** — one required primary handoff number and one optional
  secondary (e.g. a second-language line, an overflow desk) · seen in: Retell (multi-destination + SIP),
  Vapi (`destinations` array), Synthflow (validated TEL entry), Ruby ("transfer to any number you wish"),
  Goodcall (business line default + override) · priority: table-stakes · model: reuses
  `AgentSetting.transfer_phone_number` / `.transfer_secondary_number` (E.164, tenant + location scoped) ·
  realtime: post-call config, consumed live · tool-surface: none new — the two stored numbers are the **only**
  two values the future `transfer_to_human` tool (Module 3) may ever dial · buildable now.
- **E.164 format validation on save** — reject a destination number that doesn't parse as E.164 before it can
  ever be dialed · seen in: Synthflow ("validation button to confirm the number is valid"), implied by every
  leader's dashboard entry field · priority: common · model: form-level `clean()` on the two number fields, no
  schema change · realtime: post-call · tool-surface: pure UI (`ValidationError`) · buildable now. *(Actually
  dialing Twilio to confirm ownership/reachability is a different feature — see "Belongs to 2.4" below.)*
- **Ordered fallback dialing (primary → secondary on no-answer/busy)** — if the primary line doesn't pick up,
  automatically try the secondary before giving up · seen in: Vapi's ordered `destinations` array, general
  call-center failover pattern (implied by Retell/Bland's warm-transfer retry framing) · priority: differentiator
  · model: no new field — behavior lives entirely in Module 3's transfer executor, which tries
  `transfer_phone_number` then `transfer_secondary_number` in that fixed order · realtime: **live-call hot path**
  (Module 3, integration/later) · tool-surface: the transfer tool's `target` argument selects *which configured
  number to try first* (`"primary"` default, `"secondary"` when the model has a reason — e.g. caller asked for
  Spanish); it never changes *what* number that resolves to · buildable now (config) / integration later
  (execution).
- **Transfer destination is always the server-configured E.164 number — never caller- or model-supplied** —
  priority: **REQUIRED** (product security invariant — **Invariant 3** and CLAUDE.md Vulnerability rule #6, not a
  market-copied feature; called out because it is the opposite of what some leaders' "dynamic transfer" features
  allow). Vapi's dynamic `transferCall` (empty `destinations` + a model- or webhook-supplied destination) and
  Synthflow's Dynamic Transfers (a custom action *returns* a phone number the transfer action then dials) are the
  explicit anti-pattern this product must not copy for the number itself: a caller's speech reaches the model
  (prompt injection is a live threat), so the tool must never accept a phone number as an argument. Model: not a
  DB field — a dispatcher-level rule enforced by Module 3's `apply_tool_call`, using only
  `AgentSetting.transfer_phone_number` / `.transfer_secondary_number` resolved from **server-side session
  state** (`tenant_id`/`location_id`), never from tool args. Tool-surface: **new tool contract to hand to Module
  3** — `transfer_to_human(target: "primary" | "secondary")`. Identity (`tenant_id`, `location_id`, `session_id`)
  comes from server state; `target` is the only caller-model-supplied argument and it selects between two
  pre-configured numbers, never supplies one. Result shape:
  `{"ok": true, "data": {"destination": "+1XXXXXXXXXX", "mode": "warm"}, "error": null}` on success,
  `{"ok": false, "data": null, "error": {"code": "not_permitted", "message": "Transfer is not available right now."}}`
  when disabled/outside hours. Buildable now (the rule + config); the tool itself is Module 3's to implement.

### Transfer Working Hours
- **Per-weekday enable + start/end window** — a caller only hears a human offered when someone is actually
  scheduled to answer that line · seen in: Smith.ai ("won't transfer after your set business hours... unless you
  request it"), Ruby (customized after-hours instructions), Dialpad ("define exactly when your auto attendant is
  active... business hours, after hours"), Goodcall (business-hours toggle) · priority: table-stakes (an explicit
  sub-module bullet) · model: reuses `AgentSetting.transfer_working_hours` JSON —
  `{"monday": {"enabled": true, "start": "09:00", "end": "17:00"}, ..., "sunday": {...}}` — **one interval per
  named weekday, keyed by weekday**, distinct in shape from 1.4's `provider_hours` (see repo-state note above) ·
  realtime: the JSON itself is post-call config; the window-check function must be **hot-path-safe** (pure,
  no I/O — Module 3 evaluates it on every transfer request) · tool-surface: no new tool in 2.3, a pure Python
  contract for Module 3 (see Recommended build scope) · buildable now.
- **Timezone-aware evaluation, own field, not the location's clock** — `AgentSetting.transfer_timezone` (IANA,
  default `America/Chicago`) is deliberately its **own** field, not a reuse of `tenants.Location.timezone` — a
  tenant may staff a shared transfer/answering line in a different timezone than the location itself operates in
  (a national call center covering several sites) · seen in: cross-domain precedent from Calendly/Square-style
  per-schedule timezones (same reasoning 1.4 applied to `Location.timezone`, deliberately *not* reused here
  because the two concepts differ) · priority: table-stakes, correctness-critical (a wrong timezone offers or
  refuses a human transfer at the wrong wall-clock hour) · model: reuses `AgentSetting.transfer_timezone` ·
  realtime: post-call config, consumed on the hot path · tool-surface: none — display-only in the form, resolved
  server-side via Python's `zoneinfo`, never trusted from the browser · buildable now.
- **Empty JSON = no restriction (transfer available whenever `transfer_enabled` is true)** — the documented
  default, and the **opposite polarity from 1.4's `provider_hours`** (there, empty/missing = zero availability).
  This asymmetry must be encoded deliberately, not copy-pasted from 1.4's helper · seen in: implied contrast with
  every leader's "always available unless configured otherwise" default when no explicit hours are set up ·
  priority: table-stakes (explicit in the sub-module's own JSON-shape note) · model: encoded in the read helper's
  contract (see Recommended build scope) · realtime: hot-path-safe pure function · tool-surface: documented
  contract, not a tool · buildable now.
- **HH:MM parse + `end > start` validation guard** — reject an unparsable time or an inverted window before save
  · seen in: implied by every leader (none allow a nonsensical window) · priority: table-stakes · model: form
  `clean()` over the JSON, no schema change · realtime: post-call · tool-surface: server-side `ValidationError` ·
  buildable now.
- **Holiday / date-specific override** (close for a holiday, extend hours for a promotion) · seen in: Dialpad
  ("Manage Holidays & Routing Rules"), Goodcall (season/holiday exceptions from Google Business Profile) ·
  priority: differentiator · model: would need a schema extension (an `"exceptions"` key by ISO date) beyond the
  weekday-only shape the ERD gives — **no room in this pass**, and 1.4 deferred the identical class of feature
  for `provider_hours` for the same reason. **Deferred**, consistent product-wide.
- **Visually consistent, structurally separate editor from 1.4** — same look (per-weekday rows, HH:MM inputs, a
  read-only timezone label) but its **own** form class and service module, because the JSON shapes genuinely
  differ (single interval per weekday here vs. a list of multi-weekday intervals per location in 1.4) · priority:
  table-stakes (explicit instruction from the invoking prompt) · model: n/a (implementation guidance) ·
  buildable now.

### Transfer Keywords
- **Built-in escalation phrase set (hardcoded, not stored per tenant)** — a baseline list like "speak to a
  person", "talk to a human", "representative", "operator", "real person", "customer service", "manager",
  "supervisor", "connect me", "transfer me" that always triggers a transfer offer, so a tenant starts with
  working escalation on day one · seen in: Bland ("an explicit request... is always an immediate transfer — no
  negotiation"), Smith.ai (customer-initiated requests as a named trigger category), PolyAI/Retell (prompted
  escalation on explicit ask) · priority: table-stakes · model: a Python constant Module 3 owns (e.g.
  `DEFAULT_TRANSFER_KEYWORDS`), **not** a DB row — `AgentSetting.transfer_keywords` stores only the tenant's
  additions on top of it · realtime: the match itself is a cheap substring/phrase check on the hot path ·
  tool-surface: not a tool — a pre-filter signal feeding the model's own judgment (see next item) · buildable
  now.
- **Tenant-added extra phrases (`transfer_keywords`), lowercased and de-duplicated against the built-ins)** — a
  structured, non-prompt-engineering way for a tenant to add industry jargon ("front desk", "oral surgeon",
  "loan officer") without editing the system prompt · seen in: **no surveyed competitor exposes a raw editable
  keyword list** — Retell/Bland/Vapi/Synthflow all route escalation triggers through free-text prompt
  instructions or built-in sentiment/intent classifiers instead. This is a genuine product differentiator, not a
  copied feature · priority: differentiator · model: reuses `AgentSetting.transfer_keywords` (JSON list) ·
  realtime: hot-path-safe pure match function · tool-surface: none new — form-level normalization (`.strip()`,
  `.lower()`, de-dupe, a sane max-count cap so the prompt/keyword surface can't grow unbounded) · buildable now.
- **Important nuance for the runtime spec:** the keyword list is a **pre-filter/hint**, not the *exclusive* gate
  — the LLM itself decides whether to call the transfer tool at all, informed by `prompt_text` (2.1). Coding the
  runtime as "only transfer on a literal keyword hit" would regress behind every surveyed leader, all of which
  reason about intent/sentiment, not string matching alone. 2.3 ships the keyword list; Module 3 decides how much
  weight it carries in the model's own reasoning.
- **Sentiment/frustration-triggered escalation** (transfer on detected anger/confusion, independent of any
  literal phrase) · seen in: Smith.ai ("sentiment thresholds"), Bland ("customer is angry... low confidence"),
  Dialpad (passes "customer's sentiment" to the human) · priority: differentiator · **belongs to Module 3** — this
  is a live-call reasoning behavior (LLM judgment over conversation state), not a config list; 2.3 ships no field
  for it. Park.
- **Intent/department-based multi-destination routing** ("billing" → number A, "sales" → number B) · seen in:
  Vapi (prompt-driven destination selection per department), Dialpad ("routed by intent... directly to sales,
  support, billing") · priority: differentiator · **out of scope for this pass** — `AgentSetting` has exactly two
  configured destinations (primary/secondary), not a department map; would need a schema extension. **Deferred.**

### Off-Hours Behaviour
- **Deterministic apology + branching when transfer is unavailable (disabled or outside the window)** · seen in:
  Smith.ai (documented after-hours refusal), Ruby (custom after-hours instructions), Rosie (auto-learned hours,
  after-hours-vs-default branching), Goodcall ("take a message, send a self-service link, or schedule a
  callback" as the operator fallback) · priority: table-stakes (an explicit sub-module bullet: "what the agent
  says and does") · model: **no new field** — the ERD's given `AgentSetting` field list has no
  `off_hours_message` column, so this is realized two ways instead: (a) two **runtime-injected prompt
  variables**, `{{transfer_available}}` (bool) and `{{transfer_reopens_at}}` (a human string from the
  `next_transfer_window()` helper — see build scope), merged into the same `{{var}}` substitution mechanism the
  ERD already documents for `{{from_number}}`/`{{location_name}}` (owned by 2.1's `variables` field, reused here
  rather than duplicated); and (b) a **hardcoded, zero-LLM-token spoken fallback** for the moment the transfer
  tool itself is actually invoked and refused, mirroring the deterministic-greeting pattern (CLAUDE.md Realtime
  Rule 5) and the "failures degrade to a spoken fallback, never dead air" rule (Rule 4). realtime: **live-call hot
  path** — the `not_permitted` refusal itself must be instant (no LLM round trip), though the model's own next
  turn phrases the apology using the injected variables. tool-surface: this is exactly the
  `transfer_to_human(target)` contract named above — `{"ok": false, "data": null, "error": {"code":
  "not_permitted", "message": "Transfer is not available right now."}}` when closed/disabled. Buildable now
  (config + the two pure helper functions); the tool and its wiring into the prompt are Module 3's,
  integration/later.
- **Offer a callback/voicemail alternative instead of a bare apology** · seen in: Ruby ("take a message"),
  Goodcall ("schedule a callback workflow"), Smith.ai/Dialpad (message-taking as the fallback path) · priority:
  common · **belongs to Module 4** — `scheduling.CallbackRequest` is the model that stores this and is not built
  yet; 2.3 has nothing to build for callback creation itself. Once 4 exists, the off-hours prompt instruction
  (2.1) will reference a future `create_callback_request` tool; 2.3 only needs to ensure its
  `{{transfer_reopens_at}}` variable is available for that later prompt to use. Park.
- **Always announce before connecting, never a silent cold transfer** · seen in: Smith.ai ("always inform the
  caller before connecting them to a human agent, avoiding cold transfers"), Retell/Bland's warm-transfer whisper
  patterns · priority: table-stakes · **belongs to Module 3** (the actual spoken announcement + SIP/telephony
  mechanics at transfer time) — the ERD's `AgentSetting` field list has no warm/cold toggle, so recommend Module
  3 default to a single warm-style announcement ("One moment, I'm connecting you.") with no per-tenant
  customization in this pass. A future `transfer_announcement_text` field would need a schema extension —
  **Deferred**, not built here.

### Beyond the bullets
- **Human-presence detection before bridging** (only complete the connection if a human actually answers) · seen
  in: Retell ("Human Detection... will only complete the connection if it confirms a human is on the receiving
  end") · priority: differentiator · **belongs to Module 3** (telephony/provider-adapter mechanics — AMD/answer
  detection via the Twilio adapter). Park, integration/later.
- **Whisper / three-way announce messages to the transfer target** (a private message only the human hears
  before the caller is bridged) · seen in: Retell (whisper + three-way messages, on-hold music) · priority:
  differentiator · would need a new field (`transfer_whisper_text` or similar) not in the ERD's given list —
  **Deferred**, low priority for an MVP inbound receptionist (most surveyed leaders default to a fixed system
  message rather than a per-tenant custom whisper).
- **SIP URI transfer destinations** alongside plain E.164 numbers · seen in: Retell, Synthflow, PolyAI (all
  support `sip:user@domain` targets) · priority: differentiator · **out of scope for this pass** —
  `transfer_phone_number`/`transfer_secondary_number` are E.164-typed `Char(32)` per the ERD's given field spec;
  no PBX/SIP integration need has surfaced for a phone-based SMB inbound receptionist. **Deferred.**
- **"Verify/test-dial the destination number before saving"** (Synthflow's validate button; a live readiness
  check) · priority: common · **belongs to 2.4 Test Call** — its own bullet is literally "Setup Readiness Check —
  flags a missing... transfer target." Do not duplicate here; 2.3 only validates *format*, 2.4 validates
  *reachability*.
- **Live conversation-context summary handed to the human agent at transfer time** · seen in: PolyAI (handoff
  summary + metadata via SIP headers/API), Dialpad ("full conversation context carries forward... reason for the
  call, steps already taken, sentiment"), Bland (proxy-agent briefing) · priority: differentiator · **belongs to
  Module 3**, and the summary is built from `calls.CallSession.transcript`/`.analysis` (Module 5's model,
  **Invariant 2** — no new table). The eventual write target is `CallSession.transfer` (a JSON column already on
  that row). Park.
- **Secondary number as an explicit language/overflow routing target** — already covered structurally by the
  primary/secondary fields plus the `transfer_to_human(target)` enum above; no additional feature needed. Noted
  here only to confirm the OraOps-derived "Spanish transfer number" precedent generalizes cleanly to "any second
  destination," matching the ERD's own field comment.

## Compliance & provider constraints

- **No REQUIRED recording-consent / two-party-consent / HIPAA / GDPR trigger inherent to 2.3 itself.** This
  sub-module stores phone numbers, a timezone and phrase lists — it does not record audio, store a transcript, or
  touch call PII in motion. Those obligations attach to Module 3 (the actual transfer execution + recording) and
  Module 5 (the stored `CallSession`), not to this config surface.
- **REQUIRED product security invariant surfaced by this research:** the transfer destination must always be the
  server-configured E.164 number, never a value the caller's speech or the model's tool call supplies (see
  "Transfer Enable & Targets" above). This is **Invariant 3** plus CLAUDE.md's Vulnerability rule #6
  (prompt-injection is a live threat) applied concretely to this sub-module — surfaced *because* two leaders
  (Vapi, Synthflow) document "dynamic transfer" patterns that let a backend or model supply an arbitrary
  destination at runtime. That pattern is explicitly the anti-pattern here.
- **Operational/liability note, not a legal mandate:** per-weekday `transfer_working_hours` exists precisely so
  the agent never auto-dials a human's personal line outside the configured window — Ruby's own published
  guidance ("limit the time they're dialing cell phones... aren't trying to transfer a call at 3am") is the
  direct real-world precedent for why this sub-module's gating matters even though it isn't itself a statute.
- **Twilio cost/provider note:** a completed transfer opens a **second concurrent call leg** (the agent-to-human
  dial), which Twilio bills per-minute independently of the original inbound leg. 2.3 itself places no call and
  appends nothing to `calls.CallSession.usage` — but it names the future usage key
  (`usage.transfer_leg_minutes` / `usage.transfer_leg_cost`) that Module 3's transfer executor should append when
  it actually dials, so Module 5's cost breakdown has a stable key to read. No STT/TTS/LLM token line is specific
  to this sub-module; ordinary conversation-turn cost already covers the model's decision to call the tool.
- **`PROVIDER_MODE` implication:** the two config-time helpers this sub-module ships
  (`is_transfer_available`, `resolve_transfer_number`, `matches_transfer_keyword`) are pure Python with no
  provider I/O, so they run identically under `fake`/`sandbox`/`live` — the actual dial is entirely Module 3's
  concern and must resolve to the fake adapter whenever `PROVIDER_MODE != 'live'`.

## Recommended build scope (this pass)

**CRUD sub-module — 1 model** (the ERD's single Module 2 model; no room for a second per the eleven-model
ceiling, and none of the researched features need one):

- **`agents.AgentSetting`** — tenant + location scoped, `unique(tenant, location)`. Because the model does not
  exist anywhere in the repo yet (confirmed by grep) and Module 2 has no built sub-module to have created it
  first, **this pass should create the model in full** — every ERD-documented field (`enabled`, `voice_provider`,
  `greeting`, `prompt_text`, `variables`, `inbound_phone_number`, `twilio_account_sid`, `twilio_auth_token`, plus
  the six `transfer_*` fields) — in one migration, since a `unique(tenant, location)` settings row can't
  sensibly be split across sub-module migrations. **2.3's own build ships UI/forms/views for the Transfer
  fieldset ONLY**; 2.1/2.2/2.4 add their own form/view/url modules over the same row later, with **no new
  migration** (per Backend Package Structure rule 8). Fields this pass's form/view actually justify, from the
  research above:
  - `transfer_enabled` (Bool) — Transfer Enable & Targets: master toggle.
  - `transfer_phone_number`, `transfer_secondary_number` (Char(32), E.164) — Transfer Enable & Targets: primary +
    secondary destinations, format-validated on save.
  - `transfer_timezone` (Char(100), IANA, default `America/Chicago`) — Transfer Working Hours: timezone-aware
    evaluation, deliberately independent of `Location.timezone`.
  - `transfer_working_hours` (JSON, `{weekday: {"enabled","start","end"}}`) — Transfer Working Hours: per-weekday
    window, empty = no restriction, HH:MM + `end>start` validated.
  - `transfer_keywords` (JSON list) — Transfer Keywords: tenant additions to the built-in phrase set,
    lowercased/deduped/capped.
  - FKs: `tenant` → `tenants.Tenant` (verified), `location` → `tenants.Location` (verified).

**What ships, concretely:**
- `apps/agents/models/...` — the full `AgentSetting` model (placement/sub-module-folder naming is a `todo`/build
  decision given the model is genuinely shared across four sub-modules of the same app; flagging this explicitly
  so `todo` picks one canonical home — e.g. under the "setup"/2.1-named folder since "One Setting per Location"
  is that sub-module's own first bullet — and every other sub-module imports the re-exported class rather than
  redefining it).
- `apps/agents/forms/TransferSettings/AgentSetting.py` — a plain form (or small fixed-7-row formset) for the
  transfer fieldset: enable toggle, two E.164 fields, timezone choice, the 7-weekday working-hours rows, and the
  keyword-list editor. Built independently of `tenants`' 1.4 formset per the shape difference documented above.
- `apps/agents/views/TransferSettings/AgentSetting.py` — a location-scoped settings view
  (get-or-create-on-first-visit + edit, analogous to `tenants:business_settings`'s singleton-edit pattern, but
  scoped to `request.location`), gated the same way other owner/manager-tier settings pages are.
- `apps/agents/services.py` (module-level functions, the Module-3-facing contract, mirroring 1.4's
  `get_provider_intervals` pattern):
  ```
  DEFAULT_TRANSFER_KEYWORDS = ("speak to a person", "talk to a human", "representative", ...)

  def is_transfer_available(agent_setting, at=None) -> bool:
      """transfer_enabled AND (transfer_working_hours is empty OR today's weekday
      window, in transfer_timezone, contains `at`). Empty JSON = no restriction —
      the OPPOSITE default from tenants.get_provider_intervals. Never raises."""

  def next_transfer_window(agent_setting, at=None) -> str | None:
      """Human-readable next open window ('Monday at 9:00 AM Central'), for the
      {{transfer_reopens_at}} prompt variable. None if no restriction is set."""

  def resolve_transfer_number(agent_setting, target="primary") -> str | None:
      """Returns transfer_phone_number or transfer_secondary_number. Never accepts
      a number as input — this IS the enforcement point for Invariant 3."""

  def matches_transfer_keyword(utterance, agent_setting) -> bool:
      """Lowercase substring check against DEFAULT_TRANSFER_KEYWORDS ∪
      agent_setting.transfer_keywords. A pre-filter signal, not the sole gate —
      see the runtime-spec nuance above."""
  ```
- Templates (single-entity sub-module — `transfer/` doubles as the entity folder, per Template Folder Structure
  rule 3): `templates/agents/transfer/form.html` (the settings editor) — no `list.html` (one row per location,
  nothing to list), a small `detail.html`/summary block if the settings page has a read view before edit.
- `LIVE_LINKS["2.3"]` entry pointing at the transfer-settings edit page.
- Tests: `is_transfer_available` (enabled/disabled, empty-JSON default, weekday+timezone boundary correctness,
  malformed-JSON never raises), `resolve_transfer_number` (never accepts external input, correct field per
  target), `matches_transfer_keyword` (built-in hit, tenant-added hit, case-insensitivity, no false positive on
  unrelated text), form validation (E.164 rejection, HH:MM parse, `end>start`, keyword de-dupe/cap).
- Seeder: extend `seed_agents.py` (new) to populate `transfer_enabled=True`, both destination numbers, a
  realistic per-weekday window (e.g. Mon–Fri 9–5, weekends disabled) and 2–3 tenant keyword additions for at
  least one seeded location per tenant, across the required **two locations per tenant** (per the Seed Command
  Rules) — through no external provider (this sub-module has none).

**Deferred, so nothing is lost:**
- Holiday/date-specific transfer overrides — needs an `"exceptions"` schema extension; consistent with 1.4's
  identical deferral for `provider_hours`.
- Warm/cold transfer mode toggle, whisper text, on-hold music — no field in the ERD's given list; Module 3
  defaults to a single warm-style announcement.
- SIP URI destinations — E.164-only per the ERD's field types; no PBX integration need identified.
- Department/intent-based multi-destination routing — only two destinations exist in this model; would need a
  schema extension.
- Sentiment-based escalation, human-presence detection, live handoff-summary — all Module 3 runtime behaviors,
  not config.

## Belongs to sibling sub-modules (parked, not scoped here)

- `enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables` fields and their forms/views →
  **2.1 Per-Location Agent Configuration** (same model row, different fieldset).
- `inbound_phone_number`, `twilio_account_sid`, `twilio_auth_token`, webhook URL display, connection check →
  **2.2 Twilio Connection**.
- Test-dial / reachability verification of the transfer destination, setup-readiness flags for a missing transfer
  target → **2.4 Test Call**.
- Actual transfer execution (SIP dial, warm-transfer whisper, human-presence detection, deferred
  transport-mutating signal per CLAUDE.md Realtime Rule 6), the `transfer_to_human` tool's real implementation,
  sentiment-based escalation reasoning, conversation-context summary construction → **Module 3 (`runtime`)**.
- `scheduling.CallbackRequest` creation as an off-hours alternative to a bare apology → **Module 4
  (`scheduling`)**.
- Writing the realized transfer outcome (`CallSession.transfer` JSON, cost lines) and displaying it in the call
  detail view → **Module 5 (`calls`)**.

## Out of scope for this product (outside the seven capabilities)

- Outbound proactive-transfer/callback dialing to the caller after the call ends — this product is inbound-only;
  no outbound calling capability exists among the seven.
- CRM/ticketing-system handoff metadata (Zendesk integration, ticket creation on transfer) — no CRM capability in
  this product's seven capabilities.
- Multi-department IVR menu / DTMF-based pre-routing before the agent even answers — this product's agent
  answers every call itself; there is no separate IVR-menu layer to configure.

## Deferred (later passes / integrations)

- **Holiday/date-specific transfer-hours exceptions** — needs a schema extension beyond the current weekday-only
  `transfer_working_hours` shape; revisit only if a future pass deliberately reopens that field's contract
  (mirrors 1.4's identical deferral for `provider_hours`, so the product treats "hours JSON" consistently
  everywhere it appears).
- **Warm/cold transfer mode + whisper/three-way message customization + on-hold music** — no field in the ERD's
  current `AgentSetting`; Module 3 ships one fixed warm-announcement behavior for now.
- **SIP URI transfer targets** — E.164-only per the ERD; add only if a real PBX/SIP customer need appears.
- **Department/intent-based multi-destination routing** — the model has exactly two destinations; a department
  map would be a genuine schema extension, not a fit for this pass.
- **Human-presence (answering-machine) detection before bridging** — a provider-adapter capability Module 3 will
  need to evaluate against the Twilio adapter's actual AMD support.
- **Live handoff-summary construction from `CallSession.transcript`** — depends on Module 5's `CallSession`
  existing with populated transcript/analysis JSON; not buildable before that.
