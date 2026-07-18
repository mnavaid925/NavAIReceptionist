# NavAIReceptionist — Core Data Model (ERD)

> **This document is INTENT. The code is truth — grep before you FK.**
>
> Nothing in this repo is built yet. Every table below is a *decision about where a fact will live*, not a claim
> that a migration exists. Before you add a field, a model, or a foreign key, grep the real code for the entity
> name. If the code and this document disagree, the code wins and this document is the bug — fix it in the same
> change.

**Product.** NavAIReceptionist is a multi-tenant SaaS AI voice agent for inbound and outbound phone calls, running
24/7: it answers calls instantly, follows up with new leads, qualifies prospects, sends SMS, and books appointments
automatically so no opportunity is missed.

**Stack.** All-Django: Django 5.1 + Channels/ASGI (realtime telephony media-stream websockets), Tailwind + HTMX,
MySQL (`navai_receptionist`). Multi-tenant: a `tenant` FK on every model and `tenant=request.tenant` on every
queryset. No separate microservice.

**Ownership.** `apps/core` (Module 0) owns the **entire** spine. This is deliberate: the communication log is
*written* by telephony, messaging and campaigns and *read* by contacts, scheduling, analytics, compliance and
billing — it cannot land in a later module, or nothing before that module can work. Modules 1–13 own their own
domain tables and the UI/engines over the spine; **they never own a spine table.**

---

## 1. The three structural ideas the spine encodes

The spine is three ideas, not a list of tables. Each one exists because without it every module ships its own
version of the same thing.

### 1.1 ONE identity union

The caller, the lead, the staff member and the attendee are all *roles*, not tables — so this product ships one
identity table plus role rows rather than thirteen person tables.

The caller, the person the booking is *for*, the
lead in a campaign, the staff member a call transfers to, and the appointment attendee are all **`core.Contact`**
rows carrying **`core.ContactRole`** rows. Every reachable endpoint — a mobile number, a work number, an email —
is a **`core.ContactChannel`** row, so consent and opt-out attach to the endpoint that was actually consented,
not to the human.

> A new standalone `Lead`, `Caller`, `Prospect`, `Customer`, `Patient` or `Attendee` model is a spine violation.
> A raw phone string stored on a module's own model is a spine violation.

### 1.2 ONE append-only event log per reality

One append-only log per reality. Nothing mutates a running total; you append a row, and a mistake is corrected by
appending a compensating row, never an UPDATE.

This product has two realities:

- **Communication** — every call, SMS, email and voicemail is one **`core.Interaction`** header with append-only
  **`core.InteractionEvent`** rows. The transcript, the tool-call trace and the provider webhook log are the *same
  table*; three tables would be three competing answers to "what actually happened on this call".
- **Metering** — every billable unit (voice minute, STT second, TTS character, LLM token, SMS segment, number
  rental, recording storage) is an append-only **`core.UsageEvent`** row.

### 1.3 Derived state, never stored editable

Derived state is never stored editable — it is an `aggregate()` result over the log. A stored `balance`-style
column is a bug, because the moment it exists something can write to it without writing an event.

Here: minutes used this period, spend to date, credit balance, answer rate, agent utilization, a contact's
conversation history, a call's transcript, campaign attempt counts and current on-call concurrency are **all
derived by query**. See §6 for the exact aggregate behind each, and the exact stored field that would be the bug.

The same discipline is applied to *configuration*: a published **`core.AgentVersion`** is immutable. You do not edit
it; you publish a new one. That is what makes a call auditable — every `Interaction` FKs the exact `AgentVersion`
that ran, so "which prompt said that?" always has an answer.

---

## 2. Tier overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TIER 0 — tenancy & plumbing                                                 │
│   core.Tenant   core.AuditLog   core.Document   core.Currency               │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▲
┌─────────────────────────────────────────────────────────────────────────────┐
│ TIER 1 — shared masters (the identity union + the bookable catalog)         │
│   core.Contact ──< core.ContactRole                                         │
│        │        ──< core.ContactChannel                                     │
│        └────────── core.ContactRelationship                                 │
│   core.PhoneNumber   core.Agent ──< core.AgentVersion                       │
│   core.Voice*   core.TelephonyProvider*   core.Country*      (*global)      │
│   core.Service   core.Resource   core.Location ──< core.BusinessHours       │
│                                                └< core.HoursException       │
│   core.Address                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▲
┌─────────────────────────────────────────────────────────────────────────────┐
│ TIER 2 — THE TWO APPEND-ONLY LEDGERS                                        │
│   core.Interaction ──< core.InteractionEvent      (communication reality)   │
│   core.UsageEvent                                 (metering reality)        │
│                       ↑ no UPDATE · no DELETE · corrections are new rows    │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▲
┌─────────────────────────────────────────────────────────────────────────────┐
│ TIER 3 — outcome documents (mutable; their history lives in the ledger)     │
│   core.Appointment   core.Recording   core.CallbackRequest                  │
│   (exactly three — the transcript and tool trace are InteractionEvent rows) │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ▲
┌─────────────────────────────────────────────────────────────────────────────┐
│ TIER 4 — the compliance gate                                                │
│   core.ConsentRecord   core.SuppressionEntry   core.QuietHoursPolicy        │
│   ── all read by the single gate: core.compliance.check_outbound_allowed()  │
└─────────────────────────────────────────────────────────────────────────────┘
```

Read the tiers bottom-up as dependency order and top-down as authority: Tier 2 is the source of truth, Tier 3 is
what the business looks at, Tier 4 is what the law looks at, and Tier 1 is what all three point to.

---

## 3. The spine models

Field types are Django field types. `tenant` is always
`models.ForeignKey('core.Tenant', on_delete=models.CASCADE, related_name=…)` unless the row is explicitly marked
**global**.

### 3.0 Tier 0 — tenancy & plumbing

| Model | Fields | Why it is spine |
|---|---|---|
| **`core.Tenant`** | `name` (Char), `slug` (Slug, **unique**), `timezone` (Char), `locale` (Char), `status` (Char: `trial/active/past_due/suspended/closed`), `created_at`, `logo`, `primary_colour` | The isolation root. Every other tenant-scoped table FKs it; every queryset filters on it. |
| **`core.AuditLog`** | `tenant`, `actor` FK `settings.AUTH_USER_MODEL` (null for system), `action` (Char), `object_type` (Char), `object_id` (Char), `before` (JSON), `after` (JSON), `ip_address` (GenericIPAddress), `user_agent` (Text), `created_at` (indexed) | The only legal way to record that an append-only row was redacted, and the record of who saw PII. Index `(tenant, created_at)`, `(tenant, object_type, object_id)`. |
| **`core.Document`** | `tenant`, `title`, `file` (File), `content_type` (Char), `size_bytes` (BigInt), `uploaded_by`, `uploaded_at`, `related_object_type`/`related_object_id` | One attachment table. Recordings are **not** documents — audio has its own retention and consent semantics, so it gets `core.Recording`. |
| **`core.Currency`** | `code` (Char(3), **unique**), `symbol`, `name`, `decimal_places` (Int) | Deliberately **global** — no tenant FK. A currency is not tenant data. |

### 3.1 Tier 1 — shared masters

#### `core.Contact` — the single identity table

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `first_name`, `last_name` | Char, blank allowed (an unknown caller has neither) |
| `display_name` | Char — computed on save, used everywhere in the UI |
| `primary_phone_e164` | Char(16), **indexed**, E.164 only |
| `email` | Email, blank |
| `date_of_birth` | Date, null |
| `timezone` | Char — the contact's, **not** the tenant's; quiet hours are evaluated in it |
| `language` | Char |
| `source` | Char (`inbound_call/web_form/import/manual/campaign/sms/widget`) |
| `status` | Char: `new` / `contacted` / `qualified` / `disqualified` / `customer` / `dnc` |
| `score` | Int, default 0 |
| `custom_fields` | JSON — tenant-defined schema, so verticals never add columns |
| `owner` | FK `settings.AUTH_USER_MODEL`, null |
| `last_contacted_at` | DateTime, null — **denormalized cache only, see §6** |
| `next_followup_at` | DateTime, null — a *schedule*, not a derived value |
| `merged_into` | self FK, null — dedupe never deletes |

Indexes: `(tenant, primary_phone_e164)`, `(tenant, status)`, `(tenant, owner)`, `(tenant, next_followup_at)`.
**Why spine:** thirteen modules each want "a person table". They get this one.

**`status` is the coarse spine status and its values are exactly `new` / `contacted` / `qualified` /
`disqualified` / `customer` / `dnc` — no module adds a value.** A richer sales pipeline is a Module 7 domain
concern: Module 7 owns `PipelineStage` (tenant-configurable, ordered) and `ContactPipelineEntry` (contact ↔ stage,
with `entered_at`). **Tenant-configurable stages never redefine `Contact.status`.** The `dnc` value is a
denormalized display convenience only — it is never the authority and never the thing a gate reads;
`check_outbound_allowed` is (Invariant 5).

#### `core.ContactRole`

`tenant`, `contact` FK, `role` (Char: `lead/prospect/customer/caller/staff/vendor/attendee`), `since` (Date),
`is_active` (Bool). Unique on `(tenant, contact, role)`.
**Why spine:** roles are rows, not tables. This is what stops the identity union from fragmenting the first time a
module needs "just a staff list".

#### `core.ContactChannel`

`tenant`, `contact` FK, `kind` (Char: `phone/email/whatsapp`), `value` (Char — E.164 for phone, address for email),
`is_primary` (Bool), `verified_at` (DateTime, null), `sms_opt_in` (Bool), `opt_in_source` (Char),
`opt_in_at` (DateTime, null), `opt_out_at` (DateTime, null).
**Unique on `(tenant, kind, value)`.** Index `(tenant, value)`.
**Why spine:** **consent lives on the channel, not the contact.** A contact can be voice-reachable and
SMS-suppressed at the same time, and only a per-endpoint row can express that honestly.

#### `core.ContactRelationship`

`tenant`, `from_contact` FK, `to_contact` FK, `relationship` (Char: `household/employer/guardian/booking_for/other`),
`is_active`. Unique on `(tenant, from_contact, to_contact, relationship)`.
**Why spine:** third-party bookings ("I'm calling for my mother") are the norm, and the caller/subject pair must be
expressible without duplicating either person.

#### `core.PhoneNumber`

`tenant`, `e164` (Char(16), **globally unique across ALL tenants**), `provider` FK TelephonyProvider,
`provider_sid` (Char, unique), `capabilities` (JSON: voice/sms/mms), `direction_role`
(Char: `inbound_did/outbound_caller_id/both`), `agent` FK Agent (null), `location` FK (null),
`forward_to_e164` (Char, blank), `label` (Char), `is_active` (Bool), `purchased_at`, `released_at` (null).
**Why spine:** this is the **multi-tenant routing key**. An inbound provider webhook has no session and no
`request.tenant`; it resolves the tenant from the dialed number. Global uniqueness is an intentional, documented
exception to tenant-scoped uniqueness — two tenants cannot own the same DID, ever.

#### `core.Agent`

`tenant`, `name`, `slug` (unique with tenant), `description` (Text), `is_enabled` (Bool),
`direction` (Char: `inbound/outbound/both`), `active_version` FK AgentVersion (null, `SET_NULL`).
**Why spine:** the persona a call ran under is referenced by calls, campaigns, numbers, analytics and QA. One table.

#### `core.AgentVersion` — immutable once published

`tenant`, `agent` FK, `version` (Int, unique with agent), `status` (Char: `draft/published/archived`),
`prompt_body` (Text), `greeting_body` (Text), `variables` (JSON), `voice` FK Voice, `llm_model` (Char),
`temperature` (Decimal), `max_tool_iterations` (Int, **default 4**), `enabled_tools` (JSON list),
`published_at` (null), `published_by` FK `settings.AUTH_USER_MODEL` (null).
Index `(tenant, agent, status)`.
**Why spine:** **editing a published version is forbidden — you publish a new one.** This is append-only discipline
applied to configuration, and it is the only thing that makes a call auditable after the fact. Every `Interaction`
FKs the exact version it ran.

#### `core.Voice` — **global**

`provider` (Char), `voice_id` (Char), `display_name`, `language`, `gender`, `sample_url` (URL).
Unique on `(provider, voice_id)`. No tenant FK — a provider's voice catalog is not tenant data.

#### `core.TelephonyProvider` — **global**

`code` (Char, **unique**), `display_name`, `capabilities` (JSON), `is_active`. No tenant FK.

#### `core.Country` — **global**

`iso2` (Char(2), **unique**), `name`, `dial_code` (Char), `default_timezone` (Char). No tenant FK.
Used for E.164 normalization and for jurisdiction defaults in Tier 4.

#### `core.Service` — the bookable-thing catalog

`tenant`, `name`, `code` (Char, unique with tenant), `duration_minutes` (Int), `buffer_minutes` (Int, default 0),
`is_default_for_new_contacts` (Bool), `price` (Decimal, null), `currency` FK Currency, `is_active` (Bool).
**Why spine:** scheduling, analytics, knowledge, pricing answers and campaign targeting all need "the thing being
booked". One catalog.

#### `core.Resource`

`tenant`, `name`, `resource_type` (Char: `staff/room/equipment/vehicle`), `is_bookable` (Bool),
`working_hours` (JSON), `capacity` (Int, default 1), `external_calendar_id` (Char, blank),
`contact` FK Contact (null — a staff resource *is* a Contact with a `staff` role), `services` M2M Service.
**Why spine:** one polymorphic bookable table instead of a table per vertical (chair, bay, operatory, room).

#### `core.Location`, `core.BusinessHours`, `core.HoursException`

- **`core.Location`** — `tenant`, `name`, `address` FK Address, `timezone` (Char), `phone` (Char), `is_active`.
- **`core.BusinessHours`** — `tenant`, `location` FK, `weekday` (Int 0–6), `opens_at` (Time), `closes_at` (Time),
  `is_closed` (Bool). Unique on `(location, weekday)`.
- **`core.HoursException`** — `tenant`, `location` FK, `date` (Date), `opens_at` (null), `closes_at` (null),
  `is_closed` (Bool), `label` (Char). Unique on `(location, date)`.

**Why spine, and the rule that comes with it:** **`is_open_now` is COMPUTED server-side and injected into the prompt
as the literal string `"yes"` / `"no"`.** The LLM must never be handed hours plus a clock and asked to derive
open/closed. This is a data-model rule because it dictates that the open state is never a stored column either.

#### `core.Address`

`tenant`, `line1`, `line2`, `city`, `region`, `postal_code`, `country` FK Country, `latitude`/`longitude`
(Decimal, null). Kept from the same shape as any business-address table: service addresses and business locations.

---

### 3.2 Tier 2 — the two append-only ledgers

#### `core.Interaction` — the communication header

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `number` | Char, auto (`CALL-00001`, `MSG-00001`), unique with tenant |
| `channel` | Char: `voice` / `sms` / `email` / `web_chat` |
| `direction` | Char: `inbound` / `outbound` |
| `contact` | FK Contact, **null** (unknown / blocked caller ID is normal) — the *caller* |
| `subject_contact` | FK Contact, null — **who the booking is FOR**, distinct from the caller |
| `phone_number` | FK PhoneNumber, null |
| `from_e164`, `to_e164` | Char(16), indexed |
| `agent_version` | FK AgentVersion, null (a human-handled or screened call has none) |
| `provider` | FK TelephonyProvider |
| `provider_sid` | Char — **unique per provider**; the idempotency key for webhook redelivery |
| `status` | Char — **voice values** (`channel='voice'`): `ringing` / `in_progress` / `completed` / `missed` / `voicemail` / `transferred` / `no_answer` / `busy`. **SMS values** (`channel='sms'`): `queued` / `sent` / `delivered` / `undelivered`. **`failed` is shared by both.** |
| `disposition` | Char, blank (tenant-configurable outcome taxonomy) |
| `started_at`, `answered_at` (null), `ended_at` (null) | DateTime |
| `duration_seconds` | Int, null — provider-reported, **never form-editable** |
| `language_detected` | Char, blank |
| `campaign` | FK `campaigns.Campaign`, null — **added by Module 8, not present in Module 0's `0001_initial`** (see the migration note below) |
| `attempt_number` | Int, default 1 |
| `parent_interaction` | self FK, null (the SMS follow-up to a call) |
| `sentiment` | Decimal, null |
| `summary` | Text, blank — written once by post-call analysis |

Indexes: `(tenant, started_at)`, `(tenant, status)`, `(tenant, contact)`, `(tenant, direction, started_at)`,
`(tenant, campaign)`. Unique: `(provider, provider_sid)`.

**Migration note — the spine never hard-depends on a MODULE app.** The rule is precisely this: **no spine field
may FK a module app (Modules 1–13) at initial-migration time.** A **Module 0 sibling app is permitted** — `core`
and `tenants` are both Module 0 and are built in the same foundation pass, so `core.UsageEvent.rate_card` →
`tenants.RateCard` and `core.UsageEvent.billing_period` → `tenants.BillingPeriod` are legal even though every
`tenants` model FKs `core.Tenant` back. That is a genuine **mutual dependency between `core` and `tenants` at
initial-migration time**, and Django resolves it by itself: it splits `core` into a base migration plus a
follow-up that carries the two `tenants` FKs.

**`accounts` is the second Module 0 sibling with exactly this shape — and it must be declared on day one.**
`accounts` is a Module 0 foundation app, so **`AUTH_USER_MODEL = 'accounts.User'` is set in `config/settings.py`
before the very first `makemigrations`.** Getting this wrong later is not a refactor: Django bakes the user model
into every migration that references it, so switching `AUTH_USER_MODEL` after the initial migrations exist
requires a **destructive migration reset** (drop the database, delete and regenerate every migration). It must be
right from the first migration.

Four spine models FK the user model — `core.AuditLog.actor`, `core.Contact.owner`, `core.AgentVersion.published_by`
and `core.CallbackRequest.assigned_to` — and **every one of them MUST reference `settings.AUTH_USER_MODEL`, never
a direct import**:

```python
from django.conf import settings
actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='…')
```

and in the migration, `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` in `dependencies` (Django emits
this itself when the FK is written the swappable way). **A `from apps.accounts.models import User` inside
`apps/core/models/…` is a defect**, not a style preference: `accounts.User` carries a `tenant` FK to `core.Tenant`
while `core` FKs back to the user model, so the direct import is an **import cycle at module-load time**. The
string/`settings` reference is what breaks the cycle — Django resolves the resulting core↔accounts mutual
dependency at migration time by exactly the same base + follow-up split it uses for `tenants`.

**Expected foundation migration graph — this split is CORRECT, not a bug:**

Shown in true **apply** order — note that `accounts` applies **first**, not last, because `core/0001_initial`
carries `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`:

```
accounts/0001_initial   — the User model itself; depends on auth/0012
core/0001_initial       — swappable_dependency(AUTH_USER_MODEL) -> accounts/0001_initial
tenants/0001_initial    — depends on core/0001_initial (every tenants model FKs core.Tenant)
core/0002_initial       — depends on core/0001 + tenants/0001; carries the deferred FK AddFields
accounts/0002_initial   — depends on accounts/0001 + core/0002; carries User.tenant
```

The follow-up migration carries whichever FK `AddField` operations Django must **defer in order to break the
`core`↔`tenants` and `core`↔`accounts` cycles** — in practice the `tenants` FKs on `usageevent`, plus any index
that touches a deferred field. Same-app FKs and the swappable-user FKs are usually resolved inside `0001_initial`
and do **not** move to the follow-up. **The exact set, count, ordering and file names vary with the model set —
expect fewer or more operations than any example here. The split itself is what matters, and it is correct.**
**Do not "fix" the
split by moving `RateCard`/`BillingPeriod` into `core`** — the Module 0 ownership table in §8 puts
`Plan`/`Subscription`/`RateCard`/`BillingPeriod`/`Invoice`/… in `apps/tenants`, and moving them would contradict
it. Do not "fix" it by dropping the two FKs either; they are how a metered row is attached to the period it bills
in.

**The deferred module FK — the exact, mechanically correct procedure.** `core.Interaction.campaign` FKs
`campaigns.Campaign`, a **Module 8** app, so Module 0 ships `core.Interaction` **without** it. It is added on the
**first Module 8 run**, and the procedure is *not* "an AddField inside `campaigns/0001_initial`" —
`makemigrations campaigns` never emits an operation against a `core` model, because Django derives `app_label`
from the model's own app. **No manual dependency editing is needed or safe — Django wires the ordering itself.**
The order of operations is what makes it work:

1. Write the `campaigns` models.
2. Run `makemigrations campaigns` **FIRST**, so `campaigns/0001_initial` exists and depends only on the
   already-applied `core` migrations — in practice `core/0002_initial`, whichever is latest at that point, **not**
   `core/0001_initial`. The load-bearing invariant is that it must never depend on the `core` migration that adds
   the `campaign` FK; the specific number is incidental and will differ as `core` grows.
3. Add the `campaign` FK **and** the `(tenant, campaign)` index to `apps/core/models/Interaction.py`
   (`models.ForeignKey('campaigns.Campaign', null=True, blank=True, on_delete=models.SET_NULL, …)`).
4. Run `makemigrations core`, which auto-depends on `campaigns/0001_initial`.
5. Run `migrate`. Commit each generated migration file as its own commit.

> **WARNING —** Never hand-add a `core` dependency to `campaigns/0001_initial` — that closes the cycle and
> produces `CircularDependencyError`. Django already points `core/000N` at `campaigns/0001_initial` for you.

Note also that a single `makemigrations` run can author files in more than one app — `git status` after every run
and commit each generated migration separately.

**This is the ONLY case in which a later module build pass legitimately edits a spine model file.** Every other
spine change belongs to Module 0. `campaign` is currently the only deferred module FK in this document; if a
future spine field needs one, it gets exactly this treatment and is marked "added by Module N" in its field table.

**SMS delivery status.** Because every SMS is an `Interaction` (Invariant 2), carrier delivery state is
`Interaction.status` (`queued` / `sent` / `delivered` / `undelivered` / `failed`) and nothing else. Each carrier
delivery callback lands as a `provider_webhook` `core.InteractionEvent` row carrying the raw carrier body and
error code in `payload`, **deduplicated on `(provider, provider_sid, event_type)`** so a redelivered callback is a
no-op. Module 9 owns templates, sequences and opt-in/10DLC registration records — **it does not own a message
table or a delivery-status table.**

**How an SMS thread joins its messages — the membership through-table.** `messaging.SmsThread` is a legitimate
Module 9 domain table (inbox state: subject, assignee, unread flag, opened/closed), and 9.2 "opens a thread" —
but the messages *in* that thread are `core.Interaction` rows, and **a spine model may never FK a Module 1–13
app**, so `Interaction` cannot take a `thread` FK. The sanctioned join is a Module 9 through-table:

**`messaging.SmsThreadMessage`** — `tenant` FK, `thread` FK `messaging.SmsThread`, `interaction` FK
`core.Interaction`, **unique on `(tenant, interaction)`** (a message belongs to at most one thread).
Index `(tenant, thread)`. It stores **membership and nothing else**: no body, no direction, no delivery status,
no timestamps that duplicate the spine — body and direction are `core.Interaction` / its `core.InteractionEvent`
rows, delivery status is `Interaction.status`. A `body`, `direction` or `status` column appearing here is the
Invariant 2 violation this shape exists to prevent; thread ordering is `Interaction.started_at`, and the thread's
last-message time is an `aggregate(Max('started_at'))`, never a stored column.

**This is the general pattern.** Whenever a module needs to *group* spine rows — a thread of SMS interactions, a
review queue of calls, a QA cohort, a campaign's attempt set — it adds a module-owned through-table
(`tenant`, `<group>` FK, `<spine row>` FK, unique on `(tenant, <spine row>)`) that carries membership only. The
module owns the grouping; the spine keeps the content. A grouping table that starts copying content is a second
communication log wearing a different name.

**Why spine:** **every** call, SMS, email and voicemail creates exactly one row here. No module gets its own
message or call table. This header is mutable during the call's life (status transitions, provider-reported
duration, post-call summary) — its *history* is the event rows below.

#### `core.InteractionEvent` — append-only lines

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `interaction` | FK Interaction, `related_name='events'` |
| `sequence` | Int — **unique with `interaction`**; the total order of the call |
| `occurred_at` | DateTime, indexed |
| `event_type` | Char: `ringing` / `answered` / `turn_user` / `turn_agent` / `dtmf` / `tool_call` / `tool_result` / `transfer_requested` / `transfer_completed` / `recording_available` / `barge_in` / `provider_webhook` / `error` / `hangup` |
| `role` | Char: `caller` / `agent` / `system` / `provider` |
| `text` | Text, blank — the spoken/typed content of a turn |
| `payload` | JSON — tool args/results, provider bodies, error detail; **redacted before persisting** |
| `is_partial` | Bool — interim recognition result |
| `duration_ms` | Int, null |

Indexes: `(interaction, sequence)`, `(tenant, event_type, occurred_at)`.

**Why spine:** **APPEND ONLY.** The transcript, the tool-call trace and the provider event log are all this one
table. Three tables would be three sources of truth for "what happened on the call" — and they would drift within a
week.

#### `core.UsageEvent` — the metering ledger

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `interaction` | FK Interaction, **null** (number rentals and storage accrue with no call) |
| `interaction_event` | FK InteractionEvent, **null** — the turn this unit belongs to. **Every per-turn row (`stt_second`, `llm_input_token`, `llm_output_token`, `tts_character`) sets it**; call-level and non-call rows (`voice_minute`, `number_rental`, `recording_storage_gb_day`) leave it null. This FK is what makes per-turn cost derivable without a second cost table. |
| `occurred_at` | DateTime, indexed |
| `category` | Char: `voice_minute` / `stt_second` / `tts_character` / `llm_input_token` / `llm_output_token` / `sms_segment` / `number_rental` / `recording_storage_gb_day` |
| `quantity` | Decimal |
| `unit_cost` | Decimal |
| `currency` | FK Currency |
| `provider` | Char |
| `provider_ref` | Char, blank — the provider's own usage record id |
| `rate_card` | FK `tenants.RateCard`, null — **`tenants` is a Module 0 sibling app, so this FK is legal at initial-migration time**; it lands in `core`'s follow-up migration (Django names it itself — typically `core/0002_initial`) because `core` and `tenants` are mutually dependent (see the migration note above) |
| `billing_period` | FK `tenants.BillingPeriod`, null — same Module 0 sibling FK, same follow-up migration; **not** a deferred module FK like `Interaction.campaign` |

Indexes: `(tenant, occurred_at)`, `(tenant, category, occurred_at)`, `(tenant, billing_period)`, `(interaction,)`,
`(tenant, interaction, interaction_event)`.
Unique on `(provider, provider_ref)` where `provider_ref` is set — **this is what makes a webhook retry
non-double-charging.**

**Why spine, and why it stays in `core`:** the billing *product* (plans, subscriptions, invoices, payment methods,
spend caps, rate cards) lives in `apps/tenants` as Module 0.2/0.3. The metering **ledger** does not: it is written
by the realtime runtime on every single turn and read by analytics, campaigns and the concurrency gate. It is
spine, and it is append-only. Tenant minutes used, spend, credit balance, margin and plan-limit checks are
**`aggregate()` results** over this table.

---

### 3.3 Tier 3 — the outcome documents

These are mutable — a booking gets rescheduled, a callback gets resolved. That is fine, because their *history* is
in Tier 2: the interaction that created them, and the events within it, are immutable.

The Tier 3 outcome documents are exactly three: **`core.Appointment`, `core.Recording`, `core.CallbackRequest`.**
There is no `core.Transcript` model and no `core.ToolCall` model — Invariant 2 forbids exactly that. The transcript,
the tool-call trace and the provider event log are all `core.InteractionEvent` rows distinguished by `event_type`.
Where this document needs to name the transcript concept it means *the transcript view over
`core.InteractionEvent`*, and likewise the tool-call trace view. A module-owned `Transcript`, `TranscriptTurn`,
`ToolCall`, `Message`, `CallEvent` or `ActivityLog` table is an Invariant 2 violation.

#### `core.Appointment`

`tenant`, `number` (Char, auto `APPT-00001`, unique with tenant), `contact` FK, `service` FK,
`resources` M2M Resource, `location` FK (null), `start_at` (DateTime), `end_at` (DateTime), `timezone` (Char),
`status` (Char: `scheduled/confirmed/completed/cancelled/no_show/rescheduled`),
`source` (Char: `ai_voice_inbound/ai_voice_outbound/sms/web/manual`), `booked_by_interaction` FK Interaction (null),
`rescheduled_from` self FK (null), `cancelled_at` (null), `cancellation_reason` (Char, blank),
`external_event_id` (Char, blank), `idempotency_key` (Char, **unique with tenant**).
Indexes: `(tenant, start_at)`, `(tenant, status)`, `(tenant, contact)`.
**Why spine:** the booking is the product's headline outcome and is referenced by scheduling, messaging (reminders),
campaigns (post-appointment follow-up) and analytics (conversion). The `idempotency_key` is what makes a retried
booking tool call safe.

#### `core.Recording`

`tenant`, `interaction` FK, `storage_key` (Char), `duration_seconds` (Int), `format` (Char),
`provider_sid` (Char, unique), `consent_basis`
(Char: `two_party_announced/one_party/not_recorded`), `retention_until` (Date, indexed),
`redacted_at` (null), `deleted_at` (null).
**Why spine:** audio is the most legally sensitive artefact in the product. Consent basis and retention are stored
*per recording*, not per tenant, because the policy that applied is the policy at the time of the call. Access is
always through a short-lived signed URL — never a public media path.

#### `core.CallbackRequest`

`tenant`, `number` (Char, auto `CB-00001`, unique with tenant), `interaction` FK (null), `contact` FK,
`callback_e164` (Char(16)), `reason` (Text), `priority` (Char: `urgent/routine`),
`status` (Char: `open/assigned/resolved/cancelled`), `due_by` (DateTime — computed against business hours),
`assigned_to` FK `settings.AUTH_USER_MODEL` (null), `resolved_at` (null).
Indexes: `(tenant, status, due_by)`.
**Why spine:** "take a message" is a first-class outcome of an inbound call, an after-hours rule, an escalation
trigger and a campaign step. All four write this one table.

---

### 3.4 Tier 4 — the compliance gate

Tier 4 has no analogue elsewhere in the spine. It is mandatory, and it exists **from Module 0** — Module 6 builds the
management UI, registration workflows and policy records *over a gate that already exists*.

#### `core.ConsentRecord`

`tenant`, `contact` FK, `channel_kind` (Char: `phone/email/whatsapp/all`),
`consent_type` (Char: `marketing/transactional/recording`), `granted` (Bool), `source` (Char),
`evidence` (JSON — exact wording played or shown, IP, timestamp, recording reference),
`granted_at` (DateTime), `revoked_at` (DateTime, null).
Indexes: `(tenant, contact, consent_type)`.
**Why spine:** consent is evidence. `evidence` holds the exact wording because "they consented" is not a defence;
"they were played this sentence at this timestamp" is.

#### `core.SuppressionEntry`

`tenant` (FK, **null = platform-wide**), `e164` (Char(16)), `scope` (Char: `voice/sms/all`),
`reason` (Char: `stop_keyword/verbal_dnc/federal_dnc/complaint/manual`), `interaction` FK (null),
`created_at`, `expires_at` (null).
**Indexed on `(tenant, e164)`.** Unique on `(tenant, e164, scope)`.
**Why spine:** this is **the** suppression list. A nullable tenant lets one row suppress a number platform-wide.

#### `core.QuietHoursPolicy`

`tenant`, `channel` (Char: `voice/sms/all`), `earliest_local_time` (Time), `latest_local_time` (Time),
`blocked_weekdays` (JSON list of ints), `jurisdiction` (Char — ISO country / region code), `is_active`.
Unique on `(tenant, channel, jurisdiction)`.
**Why spine:** the window is evaluated in the **contact's** timezone, not the tenant's — which is only possible
because `Contact.timezone` and this policy are both spine.

**The gate itself:** `apps/core/compliance.py::check_outbound_allowed(contact, channel, now)` reads
`ConsentRecord` + `SuppressionEntry` + `QuietHoursPolicy` + `Contact.status` and returns an allow/deny with a
reason. It is the only path. See Invariant 5.

---

## 4. The six spine invariants

> Reproduced verbatim. CLAUDE.md and every review agent quote these by number — the wording must be identical in
> every file that carries them.

1. **One identity table.** Leads, prospects, customers, callers, attendees and staff are `core.ContactRole` rows on `core.Contact`. **Flag any new standalone person table.** A phone number belongs to `core.ContactChannel` / `core.PhoneNumber` — flag any module storing raw phone strings on its own model.
2. **One communication log.** Every call, SMS and email is a `core.Interaction` + append-only `core.InteractionEvent` rows. Conversation history, transcripts and tool-call audit are **derived by query**, never copied into a module table. **Flag a second transcript/message/activity table.**
3. **One metering ledger.** Every billable unit is a `core.UsageEvent`. **Flag a stored, hand-editable `minutes_used`, `credit_balance`, `calls_placed` or `spend_to_date` field, or code that mutates a usage total directly instead of appending an event.**
4. **Append-only means append-only.** `InteractionEvent` and `UsageEvent` have no update or delete path. Corrections are compensating rows. Redaction is the sole exception and goes through the compliance module's documented redaction service, which writes an `AuditLog` row.
5. **One outbound gate.** Every outbound call, SMS or voicemail drop calls exactly one service function — `apps/core/compliance.check_outbound_allowed(contact, channel, now)` — which consults `ConsentRecord` + `SuppressionEntry` + `QuietHoursPolicy` + `Contact.status`. **There is no second DNC list and no inline `if not contact.do_not_call` check anywhere.** Flag both.
6. **Server owns identity; the model owns wording.** The LLM tool dispatcher signature is `apply_tool_call(state, name, args)` and is **transport-agnostic** (the same dispatcher serves the turn-based path and the realtime websocket path). Identity arguments — `tenant_id`, `contact_id`, `interaction_id` — are injected from server-side session state and are **never tool parameters**. Any ID the model *does* supply (`appointment_id`, `slot_token`) must be authorized server-side against tenant **and** the identified contact.

---

## 5. The append-only contract

Applies to **`core.InteractionEvent`** and **`core.UsageEvent`**, without exception.

**No UPDATE.** These models expose no edit view, no edit form, no `ModelForm`, no admin change permission, and no
`.update()` / `.save()` on an existing pk anywhere in application code. A row is written once.

**No DELETE.** No delete view, no `.delete()`, no admin delete permission, no cascade that silently removes rows
other than the tenant-level cascade. Bulk deletes on these tables are a review-blocking finding.

**Corrections are compensating rows.** A wrong metered quantity is corrected by appending a `UsageEvent` with a
negative `quantity` and a `provider_ref` that references the original — a compensating row, never an edit to the
original line. A mis-transcribed turn is corrected by appending a new event, not by
rewriting the old one. Aggregates then produce the right answer *and* the audit trail survives.

**Redaction is the sole exception.** PII/PHI removal, subject-erasure requests and zero-retention purges are real
legal requirements that must physically alter stored rows. They are permitted only through the documented redaction
service, which:

1. runs as an explicit, named service function — never ad-hoc ORM in a view, task or shell;
2. nulls or masks only the PII-bearing fields (`InteractionEvent.text`, `InteractionEvent.payload`,
   `Recording.storage_key` + the object itself), never the
   structural columns (`sequence`, `occurred_at`, `event_type`, `quantity`, `unit_cost`) — the shape of what
   happened survives even when the content does not;
3. stamps `redacted_at` on the affected row;
4. **writes a `core.AuditLog` row** recording actor, legal basis, scope and count. A redaction with no `AuditLog`
   row did not legally happen.

**Why this matters operationally:** telephony providers redeliver webhooks. If a handler can UPDATE a usage total,
a retry double-charges. If it can only append, and the append is guarded by a unique
`(provider, provider_ref)` / `(provider, provider_sid, event_type)` constraint, a retry is a no-op. Append-only and
idempotency are the same property viewed from two sides.

---

## 6. Derived, never stored

For each value: what it is derived **from**, and the stored field whose existence would be the bug.

| Derived value | Derived FROM (the actual query) | The stored field that would be a bug |
|---|---|---|
| **Minutes used this period** | `UsageEvent.objects.filter(tenant=t, category='voice_minute', billing_period=p).aggregate(Sum('quantity'))` | `Tenant.minutes_used` / `Subscription.minutes_consumed` — anything writable that a retry or a manual fix can desync from the ledger. |
| **Spend to date** | `UsageEvent.objects.filter(tenant=t, occurred_at__gte=start).aggregate(total=Sum(F('quantity') * F('unit_cost')))` | `Tenant.spend_to_date`, `SpendCap.current_spend`. The cap is a *ceiling* row; the spend is an aggregate compared against it. |
| **Credit balance** | prepaid top-ups (`tenants.Payment` credits) **minus** `UsageEvent` cost sum, both aggregated | `Tenant.credit_balance` — the single most tempting and most corrupting column in the schema. |
| **Conversation history (for the LLM)** | `InteractionEvent.objects.filter(interaction__contact=c, event_type__in=('turn_user','turn_agent')).order_by('-occurred_at')[:N]` across that contact's prior interactions, trimmed/summarized | A `Contact.conversation_history` JSON blob, or a per-module `ConversationMemory` table. Both are Invariant 2 violations. |
| **Contact last-contacted-at** | `Interaction.objects.filter(tenant=t, contact=c).aggregate(Max('started_at'))` | `Contact.last_contacted_at` **as an authority**. The column exists purely as a query-performance cache for list sorting: it is written only by the same code path that appends the interaction, is never hand-editable, is never in `Meta.fields`, and must be exactly reproducible by the aggregate above. If it ever diverges, the aggregate is right. |
| **Call transcript** | `interaction.events.filter(event_type__in=('turn_user','turn_agent'), is_partial=False).order_by('sequence')` | A `core.Transcript` model, or a second `Message`, `CallTurn` or `ChatLog` table owned by any module. The transcript is a **view over `core.InteractionEvent`**, never a table. |
| **Tool-call trace** | `interaction.events.filter(event_type__in=('tool_call','tool_result')).order_by('sequence')` | A `core.ToolCall` model, or a module-owned tool-audit table. The tool-call trace is a **view over `core.InteractionEvent`**, same rule as the transcript. |
| **Per-turn cost** (the turn-level token / STT / TTS / telephony breakdown behind catalog 11.2) | `UsageEvent.objects.filter(interaction=i).values('interaction_event').annotate(cost=Sum(F('quantity') * F('unit_cost')), qty=Sum('quantity'))` — grouped by the `interaction_event` FK on each per-turn row, joined back to the turn `core.InteractionEvent` for ordering by `sequence` | A `cost`, `tokens_in`/`tokens_out` or `turn_cost` column on `core.Interaction` or on any module-owned turn table. Per-turn cost is an `annotate()` over the metering ledger; **11.2 is a view sub-module and adds no table for it.** |
| **Campaign attempt counts** (queued / in-flight / completed / connect rate) | `Interaction.objects.filter(tenant=t, campaign=c).values('status').annotate(n=Count('id'))`, and per-contact `Max('attempt_number')` | `Campaign.calls_placed`, `Campaign.connect_rate`, `CampaignContact.attempts_made`. Counters drift the first time a dial fails mid-write. |
| **On-call concurrency** (live calls now) | `Interaction.objects.filter(tenant=t, status='in_progress', ended_at__isnull=True).count()` | `Tenant.active_calls` — an incremented/decremented counter leaks a slot on every crashed worker and eventually locks the tenant out of its own plan. |
| **Answer rate / containment / agent utilization** | `Interaction` counts grouped by `status` / `disposition` / `agent_version` over a date window | Any `*_rate` or `*_count` column on `Agent`, `AgentVersion`, `PhoneNumber` or `Tenant`. |
| **Is the business open now** | `BusinessHours` + `HoursException` for the location, evaluated **server-side** in the location's timezone | A stored `Location.is_open` flag — and equally, handing the LLM the hours and the clock and letting it decide. The server computes it and injects the literal `"yes"` / `"no"`. |

**The rule behind the table:** a value is allowed to be stored only when it is (a) an immutable historical fact
recorded at the moment it happened (`Interaction.duration_seconds` as reported by the provider), or (b) an
explicitly-labelled cache written by exactly one code path and byte-for-byte reproducible from the ledger
(`Contact.last_contacted_at`). Everything else is an `aggregate()`.

---

## 7. Two spine rules for the agent surface

These are **rules, not suggestions**. They are part of the data model because they determine what crosses the
boundary between the server and the language model.

### 7.1 Opaque signed slot tokens

The availability tool returns **one `slot_token` per slot** — a signed, short-TTL blob encoding start time,
resource, service, tenant and the issuing interaction — **not** three semantic fields the model must echo back
verbatim.

- The model cannot mangle a token, and it cannot invent one.
- The backend verifies the slot was actually offered **in this interaction**, closing the replay path from another
  session.
- Booking consumes the token together with an `Appointment.idempotency_key`, so a retried tool call cannot
  double-book.

This removes the single most common booking failure class. A tool that returns `{"start": "...", "resource_id": 4,
"service_id": 2}` and expects the model to hand all three back correctly is a review finding.

### 7.2 One tool-result envelope

Every tool returns exactly `{"ok": bool, "data": {...}, "error": {"code": "...", "message": "..."} | null}`:

```json
{"ok": true, "data": {"...": "..."}, "error": null}
```
```json
{"ok": false, "data": null, "error": {"code": "slot_unavailable", "message": "That time was just booked."}}
```

**`error.code` is always lower_snake_case, from this closed set:** `not_found`, `invalid_argument`,
`slot_unavailable`, `slot_expired`, `not_permitted`, `provider_error`, `rate_limited`, `internal_error`.

Never prose. Never a bare `{"id": 123}`. Never a different success key per tool. The recorder writes the envelope
into the `tool_result` `core.InteractionEvent` row (`ok` and `error.code` inside `payload`), the escalation counters
key off `ok`, the "confirmed before claimed" guardrail keys off it, and reviewers check the shape. A tool with its
own result shape breaks all four at once.

---

## 8. Which module owns what

Module numbering follows the product catalog (`NavAIReceptionist.md`, modules 0–13). **Module 0 owns the entire
spine; modules 1–13 own domain tables and the UI/engines over it, and never own a spine table.**

| # | Module | app slug | Owns (domain tables) | Reads (spine) |
|---|---|---|---|---|
| 0 | System Admin & Security | `core` · `accounts` · `tenants` · `dashboard` | **the whole spine** (Tiers 0–4), plus `accounts.User`/`Role`, `tenants.Plan`/`Subscription`/`RateCard`/`BillingPeriod`/`Invoice`/`Payment`/`PaymentMethod`/`SpendCap`/`TaxCode`, dashboard views; **plus the provider-adapter layer in `apps/core/providers/`** — the telephony/STT/TTS/LLM adapter interfaces, the fakes and `PROVIDER_MODE` resolution | — |
| 1 | Telephony & Number Management | `telephony` | port-in requests, carrier/SIP credentials, routing maps, per-number overrides, caller-ID reputation records, concurrency policy | `PhoneNumber`, `TelephonyProvider`, `Tenant`, `Location`, `AgentVersion`, `Interaction` |
| 2 | Voice Agent Studio | `agents` | prompt sections, escalation/counter rules, guardrail policies, templates & vertical packs, A/B traffic splits | `Agent`, `AgentVersion`, `Voice`, `Service`, `Location` |
| 3 | Knowledge Base & Business Facts | `knowledge` | knowledge sources, crawled pages, curated Q&A, ingestion/refresh jobs, retrieval config | `Location`, `BusinessHours`, `HoursException`, `Service`, `Resource`, `Document`, `Contact` |
| 4 | Realtime Conversation Runtime | `runtime` | the realtime **orchestration** that calls the Module 0 adapters (media-stream consumer, turn loop, VAD/barge-in, audio chain); session state, `DestinationPolicy`, latency/ended-reason diagnostics, fraud/rate-limit records. **Does not own the provider adapters — those are Module 0, `apps/core/providers/`.** | `AgentVersion`, `PhoneNumber`, `Contact`, `Location`; **writes** `Interaction`, `InteractionEvent`, `UsageEvent`, `Recording` (spine tables it writes but does not own) |
| 5 | Inbound Call Handling & Routing | `inbound` | routing rules, spam/allow-block lists, transfer destinations & ring groups, IVR/DTMF maps, voicemail-box configuration, live-monitor views | `Interaction`, `InteractionEvent`, `Contact`, `PhoneNumber`, `BusinessHours`, `CallbackRequest` |
| 6 | Compliance, Consent & Trust | `compliance` | disclosure templates, jurisdiction policies, A2P/10DLC brand & campaign registrations, retention policies, the redaction service, subject-rights requests | `ConsentRecord`, `SuppressionEntry`, `QuietHoursPolicy`, `Recording`, `InteractionEvent`, `AuditLog` |
| 7 | Contacts, Leads & Qualification | `contacts` | qualification scripts & answers, scoring rules, `PipelineStage` + `ContactPipelineEntry`, saved views, import mappings, segments | `Contact`, `ContactRole`, `ContactChannel`, `ContactRelationship`, `Interaction`, `Appointment` |
| 8 | Outbound Calling & Campaigns | `campaigns` | campaigns, cadences, attempt queue rows, dialer/throughput policy, speed-to-lead triggers, reactivation rules | `Contact`, `ContactChannel`, `PhoneNumber`, `AgentVersion`, `Interaction`, **`check_outbound_allowed()`** |
| 9 | Messaging & Missed-Opportunity Recovery | `messaging` | SMS templates, thread/inbox state, opt-in and A2P 10DLC registration records, notification routing rules, follow-up sequences. **Delivery status is not a Module 9 table** — it is `core.Interaction.status` (`queued`/`sent`/`delivered`/`undelivered`/`failed`) plus `provider_webhook` `core.InteractionEvent` rows | `Interaction`, `InteractionEvent`, `ContactChannel`, `SuppressionEntry`, **`check_outbound_allowed()`** |
| 10 | Appointments & Scheduling | `scheduling` | availability rules & blackouts, calendar connections/tokens, slot-token issuance, reminder schedules, waitlist entries | `Appointment`, `Service`, `Resource`, `Location`, `BusinessHours`, `Contact`, `Interaction` |
| 11 | Call Records, Transcripts & Post-Call Intelligence | `calls` | dispositions/outcome taxonomy, tags, extraction schemas & extracted values, sentiment/rubric scores, review queue, artifact-delivery log | `Interaction`, `InteractionEvent` (the transcript and tool-call-trace views), `Recording`, `UsageEvent`, `AgentVersion` |
| 12 | Testing, QA & Analytics | `analytics` | test-call sessions, simulated-caller scenarios & runs, QA cohorts & scorecards, saved reports, alert rules & incidents | `Interaction`, `InteractionEvent`, `UsageEvent`, `Appointment`, `AgentVersion`, `Contact` |
| 13 | Integrations, API & Onboarding | `integrations` | webhook endpoints & delivery log, CRM/calendar connectors & field maps, API keys & quotas, widget config, onboarding wizard state, vertical packs | effectively all spine tables (read-only, permission-scoped) |

**How to read this table:** if you are building module N and you need a person, a call, a message, a metered unit, a
booking, a recording or a consent decision — you **read** the spine. If you find yourself creating a table that
holds one of those things, stop: you are about to violate an invariant, and the reviewers will find it.

---

*Last word: this document is INTENT. The code is truth — grep before you FK.*
