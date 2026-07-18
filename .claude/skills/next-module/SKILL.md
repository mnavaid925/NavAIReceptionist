---
name: next-module
description: Build the next NavAIReceptionist SUB-module end-to-end — ONE sub-module ("N.M") per run, NOT a whole module. Extend the module's Django app under apps/<slug> with that sub-module's tenant-scoped models, full CRUD views/forms/urls/admin, Tailwind+HTMX templates, any Channels consumers / LLM tools / provider-adapter methods it needs, an idempotent seeder, navigation wiring (a LIVE_LINKS "N.M" entry), and migrations — reusing the unified core spine (NavAIReceptionist-ERD.md) and the foundation-app conventions. Use when the user says "new", "next", "next sub-module", "build/create the next sub-module", "continue the modules", or invokes /next-module. Takes an optional argument — a specific sub-module "N.M" (e.g. "/next-module 10.3"), a sub-module name (e.g. "availability", "missed-call text-back"), or a whole module number/name (build its next unbuilt sub-module). With no argument, auto-detect and build the next unbuilt sub-module of the module currently in progress.
---

# next-module — NavAIReceptionist module builder

When this skill is invoked, you build **one NavAIReceptionist sub-module** (`N.M`) end-to-end — the **next unbuilt
sub-module of the module currently in progress**, NOT the whole module in one pass. Modules are large (Voice Agent
Studio has 8 sub-modules, the Realtime Conversation Runtime 8, Call Records 6); each "next"/`/next-module` run
delivers exactly **one** sub-module's slice, then stops. If the module's app already exists under `apps/<slug>`, you
**extend** it (add that sub-module's models + pages + a `LIVE_LINKS["N.M"]` entry) — you do NOT re-scaffold the app.
You match the conventions established in the codebase and the unified core spine. Module 0 (**System Admin &
Security**) is realized by the foundation apps `core` / `accounts` / `tenants` / `dashboard` — once built these are
the **canonical reference implementation** for a tenant-scoped CRUD module, and `apps/core` owns the **entire**
spine. Read them (especially `apps/tenants`) whenever you are unsure how something should look. The shared data
spine is defined in **`NavAIReceptionist.md`** (catalog) and **`NavAIReceptionist-ERD.md`** (entities) — new modules
POINT AT the spine instead of duplicating it.

## Triggers
- User says: **"new"**, **"next"**, "next sub-module", "build/create the next sub-module", "continue the modules". **"new"/"next" mean the next *sub-module*, one per run — never the whole module.**
- User invokes **`/next-module`** (optionally with a sub-module `N.M` like `10.3`, a sub-module name like `availability`/`missed-call text-back`, or a whole module number `1`–`13` / module name — in which case you build that module's *next unbuilt* sub-module).

## When NOT to use
- User wants the design-system / template pattern reference → `/frontend-design`.
- User wants the realtime + tool-dispatcher contract → `/voice-agent-runtime`.
- User wants tests for a module → run the `test-writer` agent; for a render sweep run `qa-smoke-tester`.
- User wants to fix a specific bug → just fix it.
- User wants to change the foundation (Module 0 / dashboard / auth) → edit those directly; this skill is for **new** domain modules 1–13.

---

## Project conventions (NavAIReceptionist, as-built + planned)

- **Stack:** Django 5.1, **Django Channels/ASGI** for the realtime telephony media-stream websockets and live-call
  UI (**all-Django, one codebase, no separate microservice**), **function-based views** with `@login_required`,
  **Tailwind CSS (Play CDN) + HTMX + Chart.js + Lucide**, MySQL/MariaDB (XAMPP) via PyMySQL. DB is
  **`navai_receptionist`**. Run Python through the venv: `venv\Scripts\python.exe manage.py ...` (PowerShell) —
  Django is not on system Python. The dev server is **Daphne**, never `runserver`, for anything touching websockets:
  `venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`. Provider webhooks in dev need a
  tunnel whose public URL matches `TWILIO_WEBHOOK_BASE_URL` **exactly**, or signature verification fails. Tests run
  under `config.settings_test` (SQLite in-memory, `InMemoryChannelLayer`, `PROVIDER_MODE = "fake"`) with pytest +
  pytest-django + pytest-asyncio.
- **Unified core spine (mandatory — `NavAIReceptionist-ERD.md` is the INTENT; the code is the truth):**
  **`apps/core` (Module 0) owns the ENTIRE spine** — modules 1–13 own their domain tables and the UI/engines over
  the spine, never a spine table. The six invariants (quoted verbatim from `NavAIReceptionist-ERD.md` §4 — the
  wording must be identical in every file that carries them):
  1. **One identity table.** Leads, prospects, customers, callers, attendees and staff are `core.ContactRole` rows on `core.Contact`. **Flag any new standalone person table.** A phone number belongs to `core.ContactChannel` / `core.PhoneNumber` — flag any module storing raw phone strings on its own model.
  2. **One communication log.** Every call, SMS and email is a `core.Interaction` + append-only `core.InteractionEvent` rows. Conversation history, transcripts and tool-call audit are **derived by query**, never copied into a module table. **Flag a second transcript/message/activity table.**
  3. **One metering ledger.** Every billable unit is a `core.UsageEvent`. **Flag a stored, hand-editable `minutes_used`, `credit_balance`, `calls_placed` or `spend_to_date` field, or code that mutates a usage total directly instead of appending an event.**
  4. **Append-only means append-only.** `InteractionEvent` and `UsageEvent` have no update or delete path. Corrections are compensating rows. Redaction is the sole exception and goes through the compliance module's documented redaction service, which writes an `AuditLog` row.
  5. **One outbound gate.** Every outbound call, SMS or voicemail drop calls exactly one service function — `apps/core/compliance.check_outbound_allowed(contact, channel, now)` — which consults `ConsentRecord` + `SuppressionEntry` + `QuietHoursPolicy` + `Contact.status`. **There is no second DNC list and no inline `if not contact.do_not_call` check anywhere.** Flag both.
  6. **Server owns identity; the model owns wording.** The LLM tool dispatcher signature is `apply_tool_call(state, name, args)` and is **transport-agnostic** (the same dispatcher serves the turn-based path and the realtime websocket path). Identity arguments — `tenant_id`, `contact_id`, `interaction_id` — are injected from server-side session state and are **never tool parameters**. Any ID the model *does* supply (`appointment_id`, `slot_token`) must be authorized server-side against tenant **and** the identified contact.

  FK into core entities **by string** (e.g. `models.ForeignKey('core.Contact', ...)`). **Before FK'ing any spine
  entity, verify it exists** (`grep -rn "^class <Name>" apps/*/models/` — `models` is a **package** in every app, so
  the grep must be recursive and target directories, never a nonexistent `models.py`). When a planned master is
  missing, build a documented tenant-scoped stand-in and note the future migration — never a hard FK to an unbuilt
  master. Your module owns only its domain-specific tables.
- **App layout:** `apps/<slug>/`, AppConfig `name = 'apps.<slug>'`. Register in `config/settings.py`
  `INSTALLED_APPS` and add `path('<slug>/', include('apps.<slug>.urls'))` to `config/urls.py`. If the module has a
  websocket surface, add its `routing.py` patterns to the `ProtocolTypeRouter` in `config/asgi.py`.
- **Backend packages (MANDATORY):** `models/`, `forms/`, `views/`, `urls/` (and `consumers/` when the sub-module has
  a realtime surface) are **packages**, never flat `.py` files — **one folder per sub-module, then one file per
  entity** (`apps/<slug>/models/<SubModule>/<Entity>.py`), exactly mirroring the template rule. Each package's
  `__init__.py` re-exports everything it owns; imports inside them are **absolute**. See §2a.
- **Templates:** project-level `templates/<slug>/<submodule>/<entity>/<page>.html` (**one folder per sub-module,
  then one folder per entity, with a bare `list/detail/form.html` page filename — MANDATORY**, see
  CLAUDE.md "Template Folder Structure"; landing page stays at `templates/<slug>/` root), **extend
  `templates/base.html`**, use the design-system classes from `static/css/theme.css`: `.page-header .page-title
  .breadcrumb .page-actions`, `.card .card-header .card-body`, `.btn .btn-primary .btn-outline .btn-danger
  .btn-icon`, `.badge .badge-green/.badge-red/.badge-amber/.badge-info/.badge-muted/.badge-slate` (**colour-named
  ONLY — semantic `-success/-warning/-danger` variants do NOT exist and render unstyled**), `.table-wrap .table
  .table-actions`, `.form-group .form-label .form-input .form-select .form-textarea .form-error`, `.stat-card`
  (stat-icon colours: `blue/green/orange/purple/slate` only), `.empty-state`, `.pagination`, `.avatar-initial`,
  `.progress .progress-bar`, plus the voice components `.call-status-dot`, `.transcript-turn` (+ `.agent`/`.user`),
  `.live-badge`, `.waveform`. Before using ANY theme.css modifier class, confirm it exists
  (`grep -oE '\.(badge-[a-z]+|stat-icon(\.[a-z]+)?|text-[a-z]+)' static/css/theme.css | sort -u`) or copy a
  sibling template's badge line verbatim. Canonical call-status badge map: `ringing`→`badge-amber`,
  `in_progress`→`badge-info`, `transferred`→`badge-info`, `completed`→`badge-green`, `missed`→`badge-red`,
  `failed`→`badge-red`, `no_answer`→`badge-muted`, `busy`→`badge-muted`, `voicemail`→`badge-slate`. Nine statuses
  share six badge classes; `badge-info`, `badge-red` and `badge-muted` are each intentionally used twice. There is
  no `badge-purple`. Always pair the map with an `{% else %}` fallback to `{{ obj.get_status_display }}`. Icons:
  `<i data-lucide="NAME"></i>` (list actions: eye / pencil / trash-2).
- **Multi-tenancy (mandatory):** every model has `tenant = models.ForeignKey('core.Tenant',
  on_delete=models.CASCADE, related_name='<unique>')`. Every view filters `Model.objects.filter(tenant=request.tenant)`
  — never `.all()`. `request.tenant` is set by `apps.core.middleware.TenantMiddleware`. **Channels consumers,
  background tasks and telephony webhooks have no `request.tenant`** — there the tenant is resolved from a verified
  source (the dialed `core.PhoneNumber`, the `core.Interaction` row, or a signature-verified provider payload),
  never from a URL or body parameter the caller controls. A consumer that trusts `tenant_id` from the websocket URL
  is a cross-tenant vulnerability.
- **CRUD completeness (mandatory for any model with a list page):** **list (search + filters + pagination),
  detail, create, edit, delete (POST-only + confirm + csrf)**. List templates have an Actions column
  (view/edit/delete). See CLAUDE.md "CRUD Completeness Rules" + "Filter Implementation Rules". Append-only ledger
  rows (`InteractionEvent`, `UsageEvent`) and provider-written records legitimately omit edit/delete.
- **Filters:** parse `request.GET` and apply BEFORE pagination. Pass `status_choices` + any FK querysets the
  template's filter dropdowns need (agents, phone numbers, campaigns, contacts, dispositions). pk filters compare
  with `|stringformat:"d"`.
- **Seeders:** idempotent (guard `if Model.objects.filter(tenant=tenant).exists()`), `get_or_create`,
  existence-check auto-numbers. Create both `management/__init__.py` and `management/commands/__init__.py`. A seeder
  must never reach a live provider — it runs against the fake adapters under `PROVIDER_MODE=fake`.
- **Auto-numbers:** human-readable per-tenant numbers like `CALL-00001` / `APPT-00001` / `CMP-00001` / `MSG-00001` /
  `CB-00001` where it fits — use the app's abstract `TenantNumbered` base in `apps/<slug>/models/_base.py` built on
  `apps/core/utils.next_number`; the single-model reference pattern is `Invoice.save()` in
  `apps/tenants/models/Invoice.py` (`SINV-#####` with a concurrent-collision retry).
- **Git:** at the end, output a **PowerShell-safe one-file-per-commit** snippet (`git add 'f'; git commit -m '...'`).
  Commit per CLAUDE.md / project memory (one file per commit, to `main`); do NOT `git push` — the user pushes.
- **Security:** flag vulnerabilities with a `# WARNING:` comment + secure alternative. Provider credentials
  (Twilio auth token, LLM/STT/TTS keys, webhook signing secrets) never appear in `Meta.fields`, in `messages.*`, in
  a template, or in a log line.

Reference files to read before building: **`NavAIReceptionist-ERD.md`** (the spine — read this first),
`NavAIReceptionist.md` (the catalog and the `### N.M` sub-module headings), and — once Module 0 exists —
`apps/core/navigation.py`, `apps/core/models/` (the spine, a package with entity files at its root),
`apps/core/compliance.py` (the single outbound gate), `apps/core/providers/` (telephony/STT/TTS/LLM adapters + their
fakes), `apps/core/agent/` (prompt rendering, session state, tool declarations, the `apply_tool_call` dispatcher),
`config/asgi.py` + `config/settings.py` (`ASGI_APPLICATION`, `CHANNEL_LAYERS`). For foundation-style CRUD/auth
patterns read `apps/tenants/models/`, `apps/tenants/views/`, `apps/tenants/forms/` (packages with entity files at
the root, no sub-module level), `templates/tenants/<entity>/<page>.html`, `static/css/theme.css`, and the foundation
seeders the Module 0 build will provide — `seed_core`, `seed_accounts` and `seed_tenants`
(`apps/core/management/commands/seed_core.py`, `apps/accounts/management/commands/seed_accounts.py`,
`apps/tenants/management/commands/seed_tenants.py`; there is NO `seed_demo`). Patterns worth copying from `apps/tenants` / `apps/accounts` **once those apps exist**: `Invoice.save()` per-tenant
auto-numbering (`SINV-#####`); **`EncryptionKey.generate_plaintext()` / `set_secret()`** (stores only prefix +
SHA-256 hash — the plaintext is never persisted; this is the canonical write-only-secret pattern and it is exactly
what per-tenant carrier/LLM credentials must use); the `OnboardingForm` wizard (`apps/tenants/forms/Onboarding.py`);
`TenantRegisterForm` (`apps/accounts/forms.py`) with its `transaction.atomic()` registration view; and the
`HEX_COLOR` validator on `BrandingSetting` colors. **Never point at or FK a file you have not confirmed exists.**

> ⚠️ **NavAIReceptionist modules are large — build ONE sub-module per run.** Each module in
> `NavAIReceptionist.md` has many sub-modules. **Each `/next-module` run (and each "next"/"new") builds exactly ONE
> sub-module (`N.M`)** — its 1–4 own tenant-scoped models, get them fully CRUD + tenant-scoped + wired
> (`LIVE_LINKS["N.M"]`) + seeded + verified, then STOP. Do NOT build the rest of the module's sub-modules in the
> same run. The module's app is built up **sub-module by sub-module across many runs**. Reuse the unified core spine
> so you build domain logic, not plumbing. (The first run for a brand-new module also scaffolds the app skeleton —
> see Step 1 + Step 2.)

---

## Step 0 — Is the foundation built? (greenfield check)

NavAIReceptionist starts as a documentation repo. Before any domain module exists, the **foundation (Module 0)**
must be built: `core` (Tenant + TenantMiddleware + `navigation.py` (`parse_catalog()` builds the module 0–13 catalog
from NavAIReceptionist.md + `MODULE_ICONS` + `LIVE_LINKS`) + AuditLog + decorators + `crud.py`/`utils.py` helpers +
**the entire spine**, which includes (see `NavAIReceptionist-ERD.md` for the complete list) —
Contact/ContactRole/ContactChannel/PhoneNumber/Agent/AgentVersion/Voice/TelephonyProvider/
Service/Resource/Location/BusinessHours, the two append-only ledgers Interaction/InteractionEvent and UsageEvent,
the outcome documents Appointment/Recording/CallbackRequest, and the compliance gate ConsentRecord/SuppressionEntry/
QuietHoursPolicy + `compliance.py` — plus `providers/`, `agent/`, `routing.py`), `accounts` (User/Role/Permission/
UserInvite + auth/IAM/RBAC), `tenants` (subscription/plans/billing/usage rollups/branding/keys/health), `dashboard`
(KPI aggregation), plus `config/` (including `asgi.py` + `CHANNEL_LAYERS`), `templates/base.html`,
`static/css/theme.css`, `.env`, and the seeders. If `apps/core` / `config/settings.py` do not exist yet, build the
foundation first (enter plan mode, follow `NavAIReceptionist-ERD.md` + `NavAIReceptionist.md` + `README.md`) — it is the reference every
domain module clones.

## Step 1 — Decide which SUB-MODULE to build

> **You always resolve to exactly ONE sub-module `N.M`** (e.g. `10.3 Availability Search & Slot Offering`). The
> "build unit" is a sub-module, never a whole module. **How "built" is tracked:** a sub-module is BUILT iff it has a
> `LIVE_LINKS["N.M"]` entry in `apps/core/navigation.py` (the sidebar lights it up). Read that dict + the
> `### N.M …` sub-module headings in `NavAIReceptionist.md` (or call `parse_catalog()`) to know the order and what's
> done.

1. **If the user passed an argument, resolve it to exactly one sub-module** (case-insensitive, punctuation/`&`/`and`
   ignored):
   - **Sub-module number `N.M`** — e.g. `10.3`, `2.5`, `module 10.3`, `#10.3` → exactly that sub-module. Build it
     (extend module N's app). This is the most direct form.
   - **Sub-module name** — e.g. `availability`, `missed-call text-back`, `barge-in`, `A2P`, `slot offering` → match
     it against the `### N.M <name>` headings in `NavAIReceptionist.md` and resolve to that one `N.M`. (Match on the
     sub-module title and its feature bullets.)
   - **Whole module number `1`–`13`, app slug, or module name** — e.g. `10`, `scheduling`, `"Appointments &
     Scheduling"`, `campaigns` → resolve to that module, then pick its **next unbuilt sub-module** = the
     lowest-numbered `N.M` (NavAIReceptionist.md order) with **no** `LIVE_LINKS["N.M"]` entry. (Building "module 10"
     means building 10's next sub-module, NOT all of module 10.)
   - If the text matches **more than one** sub-module/module → ask the user to pick via `AskUserQuestion`. If it
     matches **none** → tell the user and show the relevant `### N.M` list.

   Examples: `/next-module 10.3` → Availability Search & Slot Offering. `/next-module barge-in` → Runtime 4.4.
   `/next-module 9` → Messaging's next unbuilt sub-module. `/next-module telephony` → Telephony's next unbuilt
   sub-module.

2. **If no argument**, **auto-detect the next unbuilt sub-module** of the module currently in progress:
   1. **Active module** = the **highest-numbered** module `N` (1–13) whose app slug (table below) already exists
      under `apps/` — that's the module under construction. (If NO domain app exists yet, the active module is the
      lowest unbuilt one, normally **Module 1 = `telephony`**, and this run scaffolds its app + builds `1.1`.)
   2. **Next sub-module** within the active module = the **lowest-numbered `N.M`** (NavAIReceptionist.md document
      order) that has **no** `LIVE_LINKS["N.M"]` entry. That is what you build. **Always read the *real* current
      `LIVE_LINKS` keys at run time** — the built set changes every run (and other sessions may build in parallel),
      so never assume it from memory or from this doc. *(Illustration of the rule only, NOT live state: if a module
      has `LIVE_LINKS` entries for `X.1, X.2, X.3, X.6`, the lowest `N.M` with no entry is **X.4**, so "next" → X.4,
      then X.5 … Out-of-order earlier builds (X.6) don't matter — you always take the lowest-numbered unbuilt one.)*
   3. **Module rollover:** if the active module has a `LIVE_LINKS` entry for **every** `### N.M` in
      NavAIReceptionist.md (fully wired), advance to the **next module** = the lowest `1..13` whose app does NOT
      exist, scaffold its app, and build its **first** sub-module (`N.1`). Only then does a new app get created.

3. **State the one sub-module you resolved** (`N.M <name>`) and which models it adds, then proceed: enter plan mode
   per CLAUDE.md, present the short model/page spec for **that sub-module only**, then build it and STOP. If the
   user wanted a different sub-module they can pass an explicit `N.M`. Lean toward building, don't over-deliberate.

### Module → app-slug + suggested models (module-level reference — pick the slice your sub-module needs)

This table is the **module-level** map (app slug + the kinds of models a module owns). For a single-sub-module run,
build only the **1–4 models that sub-module needs** — not every model listed for the module. The "reuses" column is
the **spine** (`apps/core`, Module 0); the models column is each module's **own** domain tables. **Always run the
verify-grep below before FK'ing a spine entity** — nothing is built until it is built.

**Which spine entities each module reuses is NOT repeated here** — the module-ownership table in
`NavAIReceptionist-ERD.md` is the single copy. Read it there, then confirm against the code with the verify-grep
below. (Three copies of one map is exactly what goes stale.)

| # | Module | app slug | Own tenant-scoped models |
|---|--------|----------|--------------------------|
| 0 | System Admin & Security | `core` + `accounts` + `tenants` + `dashboard` | `accounts`: User, Role, Permission, UserInvite · `tenants`: Plan, Subscription, RateCard, BillingPeriod, Invoice[SINV-], Payment, PaymentMethod, TaxCode, SpendCap (+ BrandingSetting, EncryptionKey, TenantHealth). `core` **owns the entire spine** (see the ERD), plus the provider adapter interfaces, their fakes and `PROVIDER_MODE` resolution in `apps/core/providers/` |
| 1 | Telephony & Number Management | `telephony` | NumberOrder, PortRequest[PORT-], CarrierAccount, SipTrunk, NumberRoutingBinding, ReputationCheck, ConcurrencyPolicy |
| 2 | Voice Agent Studio | `agents` | PromptSection, PromptVariableDef, ToolEnablement, GuardrailPolicy, EscalationRule, AgentTemplate, TrafficSplit |
| 3 | Knowledge Base & Business Facts | `knowledge` | KnowledgeBase, KnowledgeSource, KnowledgePassage, FaqEntry, PronunciationEntry, IngestionRun |
| 4 | Realtime Conversation Runtime | `runtime` | TurnMetric, EndedReasonCode, RuntimeFault, CallerRateLimit, DestinationPolicy — **infrastructure module, see the service variant in Step 2**. Module 4 owns the realtime **orchestration** (consumer, turn loop, VAD/barge-in, audio chain); Module 0 owns the adapter interfaces, the fakes and `PROVIDER_MODE` resolution in `apps/core/providers/` |
| 5 | Inbound Call Handling & Routing | `inbound` | RoutingRule, TransferTarget, RingGroup, ScreeningRule, VoicemailBox, IntentCategory |
| 6 | Compliance, Consent & Trust | `compliance` | DisclosurePolicy, RecordingConsentPolicy, BrandRegistration, CampaignRegistration[A2P-], RetentionPolicy, SubjectRequest — **administers the records the gate reads; it does not own the gate** |
| 7 | Contacts, Leads & Qualification | `contacts` | QualificationScript, ScriptQuestion, QualificationAnswer, LeadScoreRule, PipelineStage, ContactPipelineEntry, ContactSegment, ImportBatch |
| 8 | Outbound Calling & Campaigns | `campaigns` | Campaign[CMP-], CampaignStep, CallAttempt, DialerPolicy, SpeedToLeadTrigger, AttemptOutcome |
| 9 | Messaging & Missed-Opportunity Recovery | `messaging` | MessageTemplate[MSG-], SmsThread, TextBackRule, FollowUpSequence, SequenceStep, NotificationRoute |
| 10 | Appointments & Scheduling | `scheduling` | AvailabilityRule, ResourceBlackout, CalendarConnection, SlotOffer, WaitlistEntry, ReminderPolicy |
| 11 | Call Records, Transcripts & Post-Call Intelligence | `calls` | CallTag, CallReview, ExtractionSchema, ExtractionResult, SavedCallView, ArtifactDelivery |
| 12 | Testing, QA & Analytics | `analytics` | TestScenario, ScenarioRun, QaScorecard, ScorecardResult, ReportDefinition, AlertRule — reads aggregates over the spine, minimal writes |
| 13 | Integrations, API & Onboarding | `integrations` | WebhookEndpoint, WebhookDelivery, Connector, FieldMapping, ApiKey, OnboardingProgress, VerticalPack |

**Four entries in that table need their boundary spelled out, because the obvious model is a spine duplicate or a
name collision:**

- **`runtime.DestinationPolicy` (Module 4)** — allow/deny by country code or dial prefix, for toll-fraud and
  traffic-pumping protection. *This is a destination policy, not a consent or DNC list. It must never be consulted
  for consent, and `check_outbound_allowed` remains the only consent gate.* There is **no** `BlocklistEntry` and no
  second suppression list — caller/contact suppression is `core.SuppressionEntry`, consulted only through
  `check_outbound_allowed` (Invariant 5).
- **`inbound.VoicemailBox` (Module 5)** — the voicemail **configuration** (greeting, delivery targets,
  transcription on/off). There is **no** `VoicemailMessage` table (Invariant 2): a voicemail *is* a
  `core.Interaction` with `status='voicemail'`, its audio a `core.Recording`, its text an `InteractionEvent`, and
  its follow-up a `core.CallbackRequest`. Module 5 may own the box, never the message.
- **`contacts.PipelineStage` + `contacts.ContactPipelineEntry` (Module 7)** — the tenant-configurable, ordered
  pipeline and the contact ↔ stage entry (with `entered_at`). *These never redefine `core.Contact.status`*, which
  is the coarse spine status with exactly the values `new / contacted / qualified / disqualified / customer / dnc`.
- **`runtime.RuntimeFault` (Module 4)** — the per-call runtime failure record (provider timeout, STT/TTS/LLM error,
  dead-air fallback). It is deliberately **not** named `RuntimeError`: **never name a model after a Python builtin —
  the mandatory `__init__.py` re-export makes the shadow global to the package**, so `from apps.runtime.models
  import *` would rebind `RuntimeError` to a model class and silently break every `except RuntimeError:` in it.

Aim for **1–4 models** per sub-module pass (the one `N.M` you resolved) so that sub-module's features each map to a
real list page (or, for a service sub-module, a real diagnostics/settings surface). **This 1–4 target is a ceiling
for CRUD sub-modules only — it defers to the shape branches in Step 2.** A **service** sub-module may add zero or a
handful of infrastructure models; a **view** sub-module (`11.1`, `11.2`, `5.6`, `12.4`, `12.5`) adds **ZERO** models
and zero migrations. *Inventing a model to satisfy the 1–4-model target is the bug the view branch exists to
prevent. If the data already lives in the spine, the sub-module is a view — ship the pages, not a table.* Decide the
shape (CRUD / service / view) BEFORE you pick any models. Some sub-modules are covered by
the foundation (`accounts:role_list`, `accounts:user_list`, `core:audit_log`, all `tenants:*`) or by an earlier
sub-module — keep those mappings and only build the missing pieces. Before coding, **verify the spine/sibling models
you plan to reuse actually exist** (`grep -rn "^class <Name>" apps/*/models/` — `models` is a **package** in every
app, so the grep must be recursive and target the directories, never a nonexistent `models.py`); if a planned parent
was researched but never built, make this sub-module self-contained and note the future migration.

---

## Step 2 — Build the sub-module (prefer a parallel agent Workflow for speed)

**Existing module vs. new module.** First check whether `apps/<slug>/` already exists:
- **App exists (the common case — you're adding a sub-module):** you **extend** it by **adding a new
  `<SubModule>/` folder to each of the four packages** (`models/`, `forms/`, `views/`, `urls/` — plus `consumers/`
  if it has a realtime surface) with one `<Entity>.py` per model — then **add that sub-module's re-export block to
  each package's `__init__.py`** (and wire the new url module into `urls/__init__.py`, the new websocket patterns
  into `routing.py`). Register the models in `admin.py` and extend the existing `seed_<slug>.py`. **Skip** the
  `apps.py`/`__init__.py` scaffolding and the `config/settings.py` `INSTALLED_APPS` + `config/urls.py` `include(...)`
  wire-up — those are already done. The only navigation change is **one new `LIVE_LINKS["N.M"]` entry**.
  `makemigrations <slug>` produces a new incremental migration (e.g. `0002_…`).
  - If you are extending an **entity that already exists** (a new field, an extra child model), edit that entity's
    existing `<Entity>.py` in each layer rather than creating a parallel file.
  - **Legacy flat apps:** if an app somehow starts flat (`models.py` etc.), convert it to the package layout as part
    of the run — do **not** append to the monolith and do **not** add a `*_advanced.py` sidecar.
- **App does NOT exist (first run for a brand-new module):** scaffold the full app skeleton below (`apps.py`,
  `__init__.py`, `migrations/__init__.py`, the four **packages** with their `__init__.py` + `_base.py`/`_common.py`,
  the `management/commands` tree) AND do the `config/settings.py` + `config/urls.py` wire-up (plus `config/asgi.py`
  if it has websocket routes) — then build that module's first sub-module (`N.1`).

**Service sub-module variant (Module 4 `runtime`, and parts of 1, 6, 9, 13).** Some sub-modules produce
**consumers, services, provider adapters and diagnostics**, not list/detail/form CRUD over tenant models. When the
resolved `N.M` is one of these, say so up front and follow this branch instead:
- It **MAY ship zero CRUD templates.** The mandatory CRUD/filter rules apply only to sub-modules that introduce a
  tenant-scoped model with a list page.
- It **MUST still ship**: tenant scoping on every query (resolved from a verified source in non-HTTP paths), a
  `LIVE_LINKS["N.M"]` entry pointing at its diagnostics or settings page, migrations if it adds models, tests, an
  idempotent seeder if it adds data, and a **fake provider implementation so the whole path runs with
  `PROVIDER_MODE=fake`**.
- It **MUST ship at least one observable surface** — a diagnostics page, a settings form, or a management command —
  so `qa-smoke-tester` has something to assert against. A sub-module with no observable surface is not done.

**View sub-module variant (11.1, 11.2, 5.6, 12.4, 12.5).** Some sub-modules add **no data of their own** — they are
the reading surface over spine tables that already exist. A **view sub-module** ships **ZERO new models and ZERO
migrations**: it is pages, filters, search, detail views, exports and a `LIVE_LINKS["N.M"]` entry built over spine
tables it only **READS**. When the resolved `N.M` is one of these, say so up front and follow this branch instead:
- *Inventing a model to satisfy the 1–4-model target is the bug this branch exists to prevent. If the data already
  lives in the spine, the sub-module is a view — ship the pages, not a table.* Concretely, `11.2 Transcript &
  Tool-Call Trace` is **the transcript view over `core.InteractionEvent`** — a `Transcript`, `TranscriptTurn` or
  `ToolCall` table there is an **Invariant 2** violation that `code-reviewer` will reject.
- It **MAY ship zero new models, zero forms, zero migrations** and no create/edit/delete views — their absence is
  correct here. The backend layers it does touch (`views/<SubModule>/<Entity>.py`,
  `urls/<SubModule>/<Entity>.py`) still follow §2a, re-exports included.
- It **MUST still ship**: **tenant scoping on every query** (`tenant=request.tenant`, and a verified-source tenant in
  any non-HTTP path), the **`LIVE_LINKS["N.M"]` entry**, its **templates** under
  `templates/<slug>/<submodule>/<entity>/` (list + detail, filter bar, pagination, empty-state), **tests**, and
  **seeded demo data reachable through the pages — seeded into the spine, never into a new table** (extend the
  existing `seed_<slug>` idempotently with `core.Interaction` / `core.InteractionEvent` / `core.Recording` rows).

The user prefers fanning work out across agents. For one sub-module a small **2–3 agent Workflow** works well:
keep **backend + migrations + seed** as one solo agent (single DB writer), then **templates** as 1–2 agents.
You may also build it inline if it's quick. Produce ALL of the following **for the one sub-module** (for an existing
app, "create" means "append to the existing file"):

### 2a. Backend (`apps/<slug>/`) — **models / forms / views / urls are PACKAGES, never flat .py files**

**MANDATORY — Backend Package Structure.** Exactly like the template rule, the backend layers are organized
**one folder per sub-module, then one file per entity**.

```
apps/<slug>/
  models/     __init__.py (re-exports EVERY model)   _base.py  (shared imports + abstract Tenant* base)
  forms/      __init__.py (re-exports EVERY form)    _common.py (shared imports)
  views/      __init__.py (re-exports EVERY view)    _common.py (shared imports) [+ _helpers.py]
  urls/       __init__.py (app_name + concatenates each entity module's urlpatterns)
  consumers/  __init__.py (re-exports EVERY consumer)  [realtime sub-modules only]
  routing.py  (flat — websocket URLPatterns for this app)
     +-- <SubModule>/          # PascalCase catalog sub-module title, e.g. CallLogRecording, TranscriptTrace
           __init__.py
           <Entity>.py         # PascalCase entity, e.g. CallSessions.py, CallReviews.py
```

The layers **line up one-to-one**: `models/CallLogRecording/CallSessions.py` ↔
`forms/CallLogRecording/CallSessions.py` ↔ `views/CallLogRecording/CallSessions.py` ↔
`urls/CallLogRecording/CallSessions.py` (↔ `consumers/CallLogRecording/CallSessions.py`). Folder = the
NavAIReceptionist.md sub-module title in PascalCase — real examples, both Module 11 (`apps/calls`):
`### 11.1 Call Log & Recording` → `CallLogRecording/`, `### 11.2 Transcript & Tool-Call Trace` →
`TranscriptTrace/`; full path `apps/calls/models/CallLogRecording/CallSessions.py`. In another app, Module 5
(`apps/inbound`): `### 5.4 Transfer & Escalation` → `TransferEscalation/`. An entity file holds the primary model
**plus its children** (`CallReviews.py` = `CallReview` + `CallReviewNote`; `ExtractionSchemas.py` =
`ExtractionSchema` + `ExtractionField`).

**Non-negotiable rules:**
1. **Every package `__init__.py` re-exports everything** it owns (`from .<SubModule>.<Entity> import (A, B)`).
   This is what keeps `from apps.<slug>.models import X`, `views.<name>` in the URLconf, and
   `include('apps.<slug>.urls')` working. **If you add a model/form/view/consumer and forget the re-export block, it breaks.**
2. **Imports inside these packages MUST be ABSOLUTE** — `from apps.<slug>.models import X`. A relative
   `from .models import X` resolves to the wrong package one level deeper and will `ImportError`/silently misbehave.
   Entity modules pull the shared toolkit via `from apps.<slug>.models._base import *` (resp. `forms._common`,
   `views._common`).
3. **`urls/__init__.py`** sets `app_name = '<slug>'` and concatenates each entity module's `urlpatterns`. Django is
   **first-match-wins**, so order is behaviour: keep literal routes before `<int:pk>` ones, and check any new greedy
   `<str:token>` route against the whole list. **`routing.py` is the same rule for websockets** — a greedy
   `<str:token>` media-stream route must be checked against the whole concatenated `URLRouter` list.
4. **Shared private helpers** used by MORE THAN ONE sub-module go in `views/_helpers.py`. Helpers used by one entity
   stay in that entity's module.
5. **NEVER create `models_advanced.py` / `views_advanced.py` / a second flat file for "advanced" features** — a later
   sub-module's models just get their own `<SubModule>/<Entity>.py`.

**What each layer contains** (unchanged rules, new locations):
- `models/<SubModule>/<Entity>.py` — this sub-module's 1–4 models. Each: `tenant` FK, timestamps, `STATUS_CHOICES`
  class attrs where relevant, `__str__`, `class Meta: ordering`. FK into the spine **by string**
  (`models.ForeignKey('core.Contact', ...)`). Auto-number in `save()` with an existence guard. Communication and
  metering effects append `InteractionEvent` / `UsageEvent` rows through the core service helpers inside
  `transaction.atomic()` — never mutate a stored total. Models sit deeper than the app root, but Django still
  derives `app_label` from the app config — **migrations are unaffected**.
- `forms/<SubModule>/<Entity>.py` — ModelForms; **exclude** `tenant`, auto-`number`, provider-supplied fields
  (`duration`, `recording_url`, `from`/`to`, `provider_sid`) and any derived/appended field. Secrets are write-only.
- `views/<SubModule>/<Entity>.py` — function-based, `@login_required` (privileged writes `@tenant_admin_required`),
  tenant-scoped, full CRUD + search + filters + pagination. Write an `AuditLog` row via
  `from apps.core.audit import write_audit_log` → `write_audit_log(request, action, obj, before=None, after=None)`.
- `urls/<SubModule>/<Entity>.py` — `urlpatterns = [...]` with names
  `<entity>_list/_detail/_create/_edit/_delete`; imports views absolutely (`from apps.<slug> import views`).
- `consumers/<SubModule>/<Entity>.py` + `routing.py` — realtime sub-modules only; see **2e**.
- `webhooks.py` — flat at the app root; provider ingress with **signature verification before any side effect** and
  an idempotency key on `(provider, provider_sid, event_type)`.
- `admin.py` — stays a flat file; register the new model(s) (`from .models import ...` still works via the re-export).
- `apps.py` / `__init__.py` — **new-app run only** (skip if the app exists).
- `migrations/` — `makemigrations <slug>` yields `0001_initial.py` for a new app, or the next incremental migration (`000N_…`) for an existing one. (`migrations/__init__.py` exists already on an existing app.)
- `management/commands/seed_<slug>.py` — for a new app create the `management/__init__.py` + `management/commands/__init__.py` tree + the command; for an existing app **extend the existing `seed_<slug>.py`** with this sub-module's demo rows (idempotent per-tenant guard; reuse existing Contact/PhoneNumber/Agent rows rather than inventing duplicates).

### 2b. Wire-up
- `config/settings.py` — add `'apps.<slug>'` to `INSTALLED_APPS` **only for a brand-new app** (skip if already present).
- `config/urls.py` — add `path('<slug>/', include('apps.<slug>.urls'))` **only for a brand-new app** (skip if already present).
- `config/asgi.py` — add the app's `routing.websocket_urlpatterns` to the `ProtocolTypeRouter`/`URLRouter` **only when this sub-module introduces the app's first websocket route**.
- **Module 8 first run ONLY — the deferred `core.Interaction.campaign` FK.** This is the **one and only** case in
  which a later module build pass legitimately edits a spine model file; every other spine change belongs to
  Module 0. `makemigrations campaigns` can **never** emit an operation against a `core` model (Django derives
  `app_label` from the model's own app). **No manual dependency editing is needed or safe — Django wires it
  automatically.** The ordering is the procedure:
  1. write the `campaigns` models;
  2. run `makemigrations campaigns` **FIRST**, so `campaigns/0001_initial` exists and depends only on the
     already-applied `core` migrations (in practice `core/0002_initial`, the latest at that point — **not**
     `core/0001_initial`) and never on the `core` migration that adds the `campaign` FK;
  3. add the `campaign` FK (`models.ForeignKey('campaigns.Campaign', null=True, blank=True,
     on_delete=models.SET_NULL, …)`) **and** the `(tenant, campaign)` index to `apps/core/models/Interaction.py`;
  4. run `makemigrations core`, which auto-depends on `campaigns/0001_initial`;
  5. run `migrate`, committing each generated migration file as its own commit.
  **WARNING — never hand-add a `core` dependency to `campaigns/0001_initial`; that closes the cycle and produces
  `CircularDependencyError`. Django already points `core/000N` at `campaigns/0001_initial` for you.**
  Note that a single `makemigrations` run can author files in more than one app — `git status` after every run and
  commit each generated migration separately.
  Skip this bullet entirely on every other module. See the migration note in `NavAIReceptionist-ERD.md` §3.2.
- `apps/core/navigation.py` — add **one `LIVE_LINKS["N.M"]` entry** for the sub-module you built, mapping its exact
  NavAIReceptionist.md feature-bullet names → `'<slug>:<entity>_list'` (or the most relevant live page; for a
  service sub-module, its diagnostics or settings page). After this the sidebar shows that sub-module as **Live**
  instead of the roadmap placeholder. Do NOT touch the catalog machinery (`parse_catalog()` / `MODULE_ICONS` — the
  names come from NavAIReceptionist.md and are already correct) and do NOT touch other sub-modules' `LIVE_LINKS`
  entries.

### 2c. Frontend (`templates/<slug>/<submodule>/<entity>/<page>.html`)
- **One folder per sub-module, then one folder per entity, with a bare `list/detail/form.html` page filename
  (MANDATORY — see CLAUDE.md "Template Folder Structure").** Templates live at
  `templates/<slug>/<submodule>/<entity>/<page>.html`, grouped by the NavAIReceptionist.md sub-module that owns each
  model — never a flat `templates/<slug>/<submodule>/<entity>_<page>.html` file. The view's `render()`/`crud_*`
  `template=` uses that full path (e.g. `"calls/calllog/callsession/detail.html"`). The sub-module folder is a real
  catalog sub-module slug — Calls (Module 11, `apps/calls`): `calllog/ transcript/ summaries/ scoring/ review/
  delivery/`; Contacts (Module 7, `apps/contacts`): `directory/ capture/ qualification/ pipeline/ hygiene/`;
  Inbound (Module 5, `apps/inbound`): `greeting/ screening/ routing/ transfer/ voicemail/ monitoring/`. Worked
  paths: `templates/calls/calllog/callsession/{list,detail,form}.html`,
  `templates/contacts/directory/contact/list.html`; the banned flat form is `callsession_detail.html`. The module
  landing/overview page
  stays at the app root (`templates/<slug>/overview.html` or `dashboard.html`); standalone reports, print pages and
  wizards stay at the sub-module level (no entity folder), e.g. `analytics/reports/call_volume.html`,
  `calls/transcript/transcript_print.html`.
- For each new model, an entity folder under the sub-module with `list.html`, `detail.html`, `form.html`
  (shared create/edit). For a single-entity sub-module the sub-module folder doubles as the entity folder — keep
  `persona/list.html`, NOT `persona/persona/list.html`. A secondary entity-action page goes inside the entity folder
  (`contacts/directory/contact/import.html`).
- Extend `base.html`; use the design-system classes; list pages get a GET filter form (search `q` + status/FK
  selects reflecting `request.GET`), an Actions column (view/edit/delete POST+confirm+csrf), pagination, and an
  `.empty-state`. Badges use the model's exact choice values + `{{ obj.get_<field>_display }}` fallback (the call
  status values are `'no_answer'`/`'in_progress'`/`'voicemail'` — not `'noanswer'`/`'inprogress'`/`'vm'`).
  Caller-controlled text (transcript turns, tool-call payloads, contact names) is **never** `|safe`. Recordings play
  through a plain `<audio controls>` against a short-lived signed URL. If the module already has a
  landing/overview page, link the new pages from it; only add a new overview page on a brand-new-app run.

### 2d. Migrate + seed + verify (venv python)
```
venv\Scripts\python.exe manage.py makemigrations <slug>
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py seed_<slug>
venv\Scripts\python.exe manage.py seed_<slug>   # 2nd run must be idempotent
venv\Scripts\python.exe manage.py check
```
For a **view** sub-module `makemigrations` must report **"No changes detected"** — a new migration here means you
added a table you should not have.

### 2e. Realtime & agent surface (only when the sub-module has one)
Skip this step entirely for a pure-CRUD sub-module. When the sub-module touches the live call path, ship **all** of:
- **Consumer + route.** `consumers/<SubModule>/<Entity>.py` plus the `routing.py` entry. The consumer **authorizes
  in `connect()`** (`@login_required` does not apply to consumers) and closes with a code rather than
  accepting-then-checking; it resolves tenant from the verified `core.Interaction` / dialed `core.PhoneNumber`,
  never from the websocket URL. Group names are **tenant-namespaced** — `t{tenant_id}:call:{interaction_id}`. No
  synchronous ORM, provider SDK, `requests`/`httpx.Client`, file I/O or `time.sleep` inside an `async def`; use
  `database_sync_to_async` / `sync_to_async(thread_sensitive=False)` / `asyncio.to_thread`. `disconnect()` finalizes
  the interaction and flushes buffered events; an exception on one frame must not kill the call.
- **Tool declaration + dispatcher branch.** Declarations are **plain provider-agnostic dicts** (`name`,
  `description`, `parameters`). The dispatcher signature is **`apply_tool_call(state, name, args)` and is
  transport-agnostic** — the same dispatcher serves the turn-based and the realtime path, and every new tool must be
  traced through **both**. Identity args (`tenant_id`, `contact_id`, `interaction_id`) come from server-side session
  state and are **never tool parameters**; any model-supplied ID (`appointment_id`, `slot_token`) is authorized
  server-side against tenant **and** the identified contact. Every tool returns the one envelope
  `{"ok": bool, "data": {...}, "error": {"code": ..., "message": ...} | null}` — never prose, never a bare `{"id": …}`.
  Register the tool on `AgentVersion.enabled_tools`. A per-turn tool-iteration cap (default **4**) with a spoken
  fallback, so a looping model never produces dead air.
- **Prompt & variables.** Add any new runtime variable to the variable set and recompute time-sensitive ones per
  turn. **The prompt names no tool and no tool parameter**, and must not promise a capability whose tool is disabled
  for that tenant. The greeting/opener is deterministic and never waits on an LLM.
- **Provider adapter + fake.** Adapters are **Module 0 foundation** — the interfaces, the fakes and `PROVIDER_MODE`
  resolution live in `apps/core/providers/`; your sub-module calls them. Any new external call gets an adapter
  method there **and its fake implementation in the same pass**, with an explicit timeout and a bounded retry.
  `PROVIDER_MODE` ∈ `fake | sandbox | live` and **`fake` is the default** for dev, tests and seeders. When the mode
  is not `live`, the adapter resolves to the fake/sandbox implementation and **must never reach a real provider**.
  The **live** adapter refuses to initialize unless `PROVIDER_MODE == "live"`, and live mode additionally requires
  real credentials — missing credentials in live mode is the hard failure. A test, seed or dev path must never
  place a real call or send a real SMS.
- **Metering.** State which `core.UsageEvent` categories this sub-module emits (`voice_minute`, `stt_second`,
  `tts_character`, `llm_input_token`, `llm_output_token`, `sms_segment`, …) and append them per turn as deltas —
  never re-aggregate the whole call each turn.
- **Compliance.** If the sub-module can initiate outbound contact, its `check_outbound_allowed(contact, channel, now)`
  call site is a required item. No inline consent/DNC check, no second suppression list.
- **Deferred transport actions.** Transfer and hangup set a pending signal on state; the transport acts only after
  the turn's audio has finished playing, and a single-fire guard is set before any `await`.

Full contract: `/voice-agent-runtime`.

---

## Step 3 — Verify (don't mark done until proven)

Render every new page as a tenant admin against seeded data and assert no errors / no leaks. Use a throwaway
script in `temp/` (gitignored) like the foundation smoke test:

- **First, assert `PROVIDER_MODE` is `fake`** and that `apps/core/providers` resolves to the fake adapters. A verify
  run must never place a real call, send a real SMS, or hit a paid LLM endpoint.
- Log in via Django test client `force_login(User.objects.get(username='admin_acme'))` (set
  `settings.ALLOWED_HOSTS=['testserver',...]`), then GET every `<slug>:*` url (use `reverse`, sample a pk per
  model) and assert status in `(200, 302)`.
- Fetch one list page's HTML and assert **no** `'{#'` / `'{% comment'` leak markers (Django `{# #}` comments are
  single-line only — use `{% comment %}` for multi-line notes), and that the page title + a seeded record appear.
- Cross-tenant IDOR: as `admin_acme`, request an `admin_globex` record's pk → expect **404**.
- **If the sub-module has a websocket surface:** `channels.testing.WebsocketCommunicator` against
  `config.asgi.application` — connect with a valid session → accepted; connect without auth or with another
  tenant's interaction id → **rejected**; send a synthetic audio frame → the consumer responds without raising.
- **If it has a webhook:** valid signature → 200 + the expected body; absent/invalid signature → 403 with **zero**
  side effects; the same valid payload twice → exactly one `Interaction`/`UsageEvent` row.
- **If it can dial or text:** a suppressed contact and a contact outside quiet hours are both refused.
- Fix anything that isn't 200/302 (usual culprit: a wrong reverse-accessor name or a context-variable
  mismatch — read the view to confirm the exact name).

Credentials: the tenant admins the foundation seeder creates — `admin_acme` / `admin_globex` — with the password
`seed_accounts` prints at the end of its run; read
`apps/accounts/management/commands/seed_accounts.py` for the current values rather than assuming them. The
superuser `admin` has `tenant=None` and sees no module data (by design).

---

## Step 4 — Document + commit snippet
1. Update `README.md` (mark **this sub-module** complete in the roadmap; ensure `seed_<slug>` is in the seeding section).
2. Update `.claude/tasks/todo.md` with a short review of the sub-module just built.
3. Output the **one-file-per-commit** PowerShell snippet for every created/changed file — with the package layout
   this is one commit per entity module per layer, e.g.
   `git add 'apps/<slug>/models/<SubModule>/<Entity>.py'; git commit -m 'feat(<slug>): N.M <Entity> models (...)'`
   then the same for `forms/`, `views/`, `urls/`, `consumers/`, **and the touched `__init__.py` re-export blocks** —
   plus the edits to `apps/core/navigation.py` (the new `LIVE_LINKS["N.M"]` entry) and `README.md` — and, **on a
   brand-new-app run only**, `config/settings.py` + `config/urls.py` (+ `config/asgi.py` for a first websocket
   route). One `git add` + one `git commit` per file — never bundle. Commit to `main`; do NOT `git push`.
   Note that a single `makemigrations` run can author files in more than one app — `git status` after every run and
   commit each generated migration separately.

---

## Step 5 — Close with the specialist review agents (CLAUDE.md "Module Creation Sequence")
The full sequence is **twelve steps**, run **one at a time, in order**, each ending with `git add` + `git commit`
(one file per commit, PowerShell-safe `;`) and **never** a `git push`:
`research` → `todo` → **write the module code** → `code-reviewer` → `explorer` → `frontend-reviewer` →
`performance-reviewer` → **`realtime-reviewer`** → `qa-smoke-tester` → `security-reviewer` → `test-writer` →
**create or update the module's Claude Code skill**. Steps 1–3 happen before and during the build (Steps 1–4 above);
after the build verifies, run the eight review agents scoped to the sub-module's new files, applying each one's
findings and committing between steps. This is the quality bar, not optional. Then step 12: **create or update the
module's Claude Code skill** (`.claude/skills/<slug>/SKILL.md`) — **author** it only on a brand-new-app run;
otherwise **UPDATE** the existing one with this sub-module's models / routes / templates / seeder rows, plus its
*Tools & prompt surface* and *Realtime surfaces* subsections. Never re-author an existing skill: a second sub-module
run that rewrites the file clobbers the previous sub-module's documentation. Commit the skill on its own.

---

## Continue / repeat
If the user says "next" again after a sub-module is done, repeat Step 1 — auto-detect now returns **the next
unbuilt sub-module** (the lowest `N.M` without a `LIVE_LINKS["N.M"]` entry in the active module), and you build that
ONE. Keep going **sub-module by sub-module** within a module; only roll over to the next module (building its `N.1`)
once every sub-module of the current one is wired (Step 1 rollover rule).

## Quality bar
A delivered sub-module must: live in the **backend package layout** (§2a — a `<SubModule>/` folder with one
`<Entity>.py` per model in each of `models/ forms/ views/ urls/` (+ `consumers/`), **plus the re-export block added
to every touched `__init__.py`**, absolute imports throughout, and **no flat `models.py`/`*_advanced.py`**);
migrate cleanly to `navai_receptionist` (incremental migration on an existing app); seed idempotently; pass
`manage.py check`; have every new list page rendering 200 with working search/filters/pagination + Actions (or, for
a service sub-module, at least one observable diagnostics/settings surface; or, for a **view** sub-module, its
list/detail pages over the spine rendering 200 with working search/filters/pagination and **no new table**);
appear as **Live** in the sidebar via
its new `LIVE_LINKS["N.M"]` entry; reuse the spine — one identity table, one communication log, one metering ledger,
one outbound gate — instead of duplicating contacts, transcripts, usage totals or DNC lists; run entirely on the
fake providers under `PROVIDER_MODE=fake`; match the blue/white Tailwind design system; and isolate data per tenant
in HTTP, websocket, task and webhook paths alike. The run builds **exactly one sub-module** — if you find yourself
adding a second sub-module's models, stop. Would a staff engineer approve it? If a piece feels hacky, redo it the
elegant way before presenting.
