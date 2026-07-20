# NavAIReceptionist — Core Data Model (ERD)

> **This document is INTENT. The code is truth — grep before you FK.**
>
> Nothing in this repo is built yet — there is no `apps/` directory. Every table below is a *decision about where a
> fact will live*, not a claim that a migration exists. Before you add a field, a model, or a foreign key, grep the
> real code for the entity name. If the code and this document disagree, the code wins and this document is the
> bug — fix it in the same change.

**Product.** A multi-tenant Django app where a business with **multiple locations** configures a Twilio phone
number and an AI voice agent **per location**. The agent answers inbound calls, books appointments into a
calendar, transfers to a human when asked, and logs the call in detail.

**Stack.** All-Django: Django 4.2 LTS + Channels/ASGI (the realtime Twilio media-stream websocket), Tailwind + HTMX +
Lucide, MySQL (`navai_receptionist`). `AUTH_USER_MODEL = 'accounts.User'`. `PROVIDER_MODE=fake` is the dev,
test and seed default — a non-`live` mode never places a real call.

**Shape of the model.** Eleven models across six apps. There is no shared "spine app": each app owns its own
tables, and the two cross-app anchors are `scheduling.Contact` (the one identity table) and `calls.CallSession`
(the one call log).

---

## 1. Tenancy and location — the query rule

This is the central rule of the application. There are two scopes, not one, and **cross-location access is a real
bug class** — an IDOR that reaches another location's calendar or call log is as serious as one that reaches
another tenant's.

**Every** model carries a `tenant` FK. Location-scoped models carry a `location` FK **as well**:

| Scope | Models |
|---|---|
| `tenant` only | `tenants.Location`, `accounts.User`, `accounts.UserLocation`, `scheduling.Contact` |
| `tenant` **and** `location` | `agents.AgentSetting`, `scheduling.Resource`, `scheduling.Appointment`, `scheduling.CallbackRequest`, `calls.CallSession` |
| `tenant` + **nullable** `location` | `scheduling.Service` (null = offered at all locations) |

`scheduling.Contact` is deliberately **not** location-scoped: a caller belongs to the business and may book at any
of its locations.

**The HTTP rule.** `tenant=request.tenant` on every queryset, always, no exceptions. For a location-scoped model
also `location=request.location`. `request.location` is the session's **active location**, set by the location
switcher in `accounts` and **validated against the requesting user's `accounts.UserLocation` rows on every
request** — a user must never reach a location they are not assigned to. A switch to an unassigned location is
rejected, not silently ignored.

**The webhook / consumer rule.** A Twilio webhook and a media-stream consumer have no `request`, so they have no
`request.tenant` and no `request.location`. Both are resolved from the **dialed number**:

```python
setting = AgentSetting.objects.get(inbound_phone_number=to_number)   # → setting.tenant, setting.location
```

Never from a query-string or body parameter the caller controls. **This is why
`AgentSetting.inbound_phone_number` is globally unique across all tenants** — it is the routing key, and two
locations cannot own the same DID, ever. The Twilio signature is then verified against the raw body and the exact
public URL using **that row's** `twilio_account_sid` / `twilio_auth_token`, **before any side effect**. A consumer
that takes `tenant_id` or `location_id` from the websocket URL is a cross-tenant vulnerability.

Global masters (`Voice`, `TelephonyProvider`, `Country`) carry no tenant FK — and are added only if actually
needed.

---

## 2. The three invariants

> Reproduced verbatim. CLAUDE.md and every review agent quote these by number — the wording must be identical in
> every file that carries them.

1. **One contact identity table.** Callers, bookers and attendees are `scheduling.Contact` rows. **Flag any new standalone `Lead`, `Caller`, `Patient` or `Attendee` model.**
2. **One call log.** A call is exactly one `calls.CallSession`; its transcript, event log, per-turn usage, analysis and transfer outcome are **JSON columns on that row**. **Flag a second transcript, turn, tool-call or call-event table.**
3. **Server owns identity; the model owns wording.** The tool dispatcher is `apply_tool_call(state, name, args)`. `tenant_id`, `location_id`, `contact_id` and `session_id` come from server-side session state and are **never tool parameters**. Any id the model does supply (`appointment_id`, `slot_token`) is authorized server-side against tenant, location **and** the identified contact.

Two supporting rules, equally binding:

**Opaque signed slot tokens.** The availability tool returns **one signed, short-TTL `slot_token` per slot** — a
blob encoding start time, resource, service and tenant — not semantic fields the model must echo back verbatim.
The model cannot mangle or invent a token, and the backend verifies the slot was actually offered *in this
session*, which closes the replay path. A tool that returns `{"start": …, "resource_id": 4, "service_id": 2}` and
expects the model to hand all three back correctly is a review finding.

**One tool-result envelope.** Every tool returns exactly:

```json
{"ok": true,  "data": {"...": "..."}, "error": null}
{"ok": false, "data": null, "error": {"code": "slot_unavailable", "message": "That time was just booked."}}
```

`error.code` is **always lower_snake_case**, from this closed set: `not_found`, `invalid_argument`,
`slot_unavailable`, `slot_expired`, `not_permitted`, `provider_error`, `rate_limited`, `internal_error`. Never
prose, never a bare `{"id": 123}`, never a different success key per tool.

---

## 3. The eleven models

Field types are Django field types. `tenant` is always
`models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, related_name=…)`; `location` is always
`models.ForeignKey('tenants.Location', on_delete=models.CASCADE, related_name=…)` unless marked null.

### 3.1 Tenancy & identity — `tenants`, `accounts`

#### `tenants.Tenant`

| Field | Type / choices |
|---|---|
| `name` | Char |
| `slug` | Slug, **unique** |
| `customer_id` | Char, **unique** — the business's Customer ID, entered at login to resolve the tenant |
| `timezone` | Char (IANA) |
| `is_active` | Bool |
| `created_at`, `updated_at` | DateTime |

The isolation root. Every other model FKs it; every queryset filters on it.

#### `tenants.Location`

*(OraOps `Location`, line 9725 — the clinic-per-org shape, kept.)*

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `name` | Char(255) |
| `slug` | Slug(255) |
| `address_line1`, `address_line2` | Char(255), blank |
| `city` | Char(128), blank |
| `state` | Char(64), blank |
| `postal_code` | Char(32), blank |
| `country` | Char(64), blank, default `"US"` |
| `timezone` | Char (IANA) — the location's own; appointment times are evaluated in it |
| `phone` | Char(32), blank |
| `is_active` | Bool, default `True` |

Unique `(tenant, slug)`. Ordering `["name"]`.

#### `accounts.User` — `AUTH_USER_MODEL`

*(OraOps `User`, line 9825, with the dental credential fields dropped.)*

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `email` | Email |
| `username` | Char(150), **null** when unset, blank — the optional login handle |
| `first_name`, `last_name` | Char(128), blank |
| `full_name` | Char(255), blank — the canonical display label, auto-derived from first/last when set |
| `primary_phone` | Char(32), blank |
| `tier` | Char(16): `owner` / `manager` / `staff` |
| `status` | Char(16), **indexed**: `active` / `inactive` / `suspended` |
| `password` | Char(128) — Django hashers, never plaintext |
| `last_login` | DateTime, null — **inherited from `AbstractBaseUser`** (see the note below) |
| `is_provider` | Bool — a `True` user IS the bookable clinician; there is no separate Provider entity |
| `provider_hours` | JSON, **keyed by location id** — `{"<location_id>": [{"start_time": "HH:MM", "end_time": "HH:MM", "days": ["mon", …]}]}` |
| `inactivity_timeout` | PositiveInt, minutes |

Unique `(tenant, email)`. Unique `(tenant, username)` **where `username` is not null**. Ordering `["email"]`.

> **As-built notes — the code is truth, and these three points were settled when `accounts.User` was written.**
>
> 1. **`last_login`, not `last_login_at`.** This document originally specified `last_login_at`. `AbstractBaseUser`
>    already contributes `last_login`, and both Django's `update_last_login` signal receiver and
>    `PasswordResetTokenGenerator._make_hash_value` read it under that name. Renaming it costs a removed inherited
>    field, a disconnected built-in signal receiver and a subclassed token generator — three pieces of permanent
>    framework-fighting for a cosmetic difference. The inherited field is used.
> 2. **`is_active` is a property, not a column.** Django's auth and admin machinery expect a truthy `is_active`;
>    `status` is the domain field. `is_active` returns `status == "active"`. A stored second column would be a
>    second source of truth a view could desync — exactly what §5 forbids.
> 3. **The `(tenant, username)` rule needs no partial index.** A plain `UniqueConstraint(fields=["tenant",
>    "username"])` already means "unique where username is not null", because every SQL engine treats NULLs as
>    distinct inside a unique index. A filtered `UniqueConstraint(condition=…)` would be actively worse here:
>    MySQL has no partial indexes, so Django skips it silently and the rule ends up unenforced. This is why
>    `username` is normalised to `None` — never `""` — in both `clean()` and `save()`.
>
> A further project-wide trap, found the first time migrations were generated: a manager with
> `use_in_migrations = True` is serialised by import path, and the mandated backend layout names each entity
> module after its model, so `apps.accounts.models.User` resolves to the re-exported **class**, not the module.
> Any migration referencing it then dies with `type object 'User' has no attribute 'UserManager'`. Managers in
> this project keep `use_in_migrations = False`.

**Login is email-or-username + password, with the tenant resolved by `Tenant.customer_id`.** Because
`AUTH_USER_MODEL` is baked into every migration that references it, this must be set in `config/settings.py`
before the very first `makemigrations` — see §6.

#### `accounts.UserLocation`

*(OraOps `UserLocation`, line 9948.)*

`tenant` FK, `user` FK User (`related_name='user_locations'`), `location` FK Location.
Unique `(user, location)`.

The set of locations a user may switch into; **exactly one is active per session**. This table is the authority
the location switcher validates `request.location` against — see §1.

### 3.2 Agent setup & telephony — `agents`

#### `agents.AgentSetting` — one row per location

*(OraOps `AppointmentAgentSettings`, line 9525 — the single most directly reusable model: it already carries
agent config, Twilio credentials AND transfer settings in one row.)*

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `location` | FK Location — the location this row configures; the agent books into it |
| `enabled` | Bool, default `False` — the master switch for this location's agent |
| `voice_provider` | Char(16), default `live`: `live` / `google` / `gemini` |
| `greeting` | Text, blank — spoken the moment the call connects, `{{var}}`-aware. **Deterministic: it never waits on an LLM** |
| `prompt_text` | Text, blank — the full system prompt |
| `variables` | JSON dict — the `{{var}}` substitution map applied to prompt and greeting at call time, alongside runtime vars like `{{from_number}}` / `{{location_name}}` |
| `inbound_phone_number` | Char(32), E.164 — **globally unique across ALL tenants** (see §1) |
| `twilio_account_sid` | Char(64), blank |
| `twilio_auth_token` | Char(128), blank — **encrypted at rest, write-only in forms** (see the security note below) |
| `transfer_enabled` | Bool, default `False` |
| `transfer_phone_number` | Char(32), E.164 — the human-handoff destination |
| `transfer_secondary_number` | Char(32), E.164 — the secondary/second-language line (OraOps `spanish_transfer_number`, generalized: the second destination need not be Spanish) |
| `transfer_timezone` | Char(100), IANA, default `"America/Chicago"` |
| `transfer_working_hours` | JSON — `{weekday: {"enabled": bool, "start": "HH:MM", "end": "HH:MM"}}` for monday…sunday; empty = no restriction |
| `transfer_keywords` | JSON list — extra lowercased caller phrases that trigger a handoff, **added to** the runtime's built-in keyword set; empty = just the built-ins |

**Unique `(tenant, location)` — exactly one row per location.**

**The transfer destination is always this configured E.164 number, never caller-supplied.** A number the caller
or the model produces is not dialable.

> **Security note — a deliberate improvement over the reference.** OraOps stores `twilio_auth_token` in
> **plaintext** and its own docstring says "field encryption is a later hardening". We do not copy that.
> `twilio_auth_token` is **encrypted at rest** and **write-only in forms**: it is never rendered back into a form
> value, never in a template, never in `messages.*`, never logged at any level, and never returned by any view or
> API. The form shows a "set / not set" indicator and accepts a replacement; it never round-trips the secret. The
> same rule covers `twilio_account_sid` in logs — a sid plus a leaked token is a live Twilio account.

### 3.3 Calendar & bookings — `scheduling`

#### `scheduling.Contact` — the single identity table

*(OraOps `Patient`, generalized; every clinical, insurance and household field dropped.)*

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `first_name`, `last_name` | Char(128), blank allowed (an unknown caller has neither) |
| `phone_e164` | Char(16), **indexed**, E.164 only |
| `email` | Email, blank |
| `date_of_birth` | Date, null |
| `notes` | Text, blank |
| `source` | Char(16): `ai_phone` / `manual` / `web` |
| `created_at`, `updated_at` | DateTime |

Indexes: `(tenant, phone_e164)`, `(tenant, last_name, first_name)`.
**Not location-scoped** — a caller belongs to the business and may book anywhere. This is the table Invariant 1
names: callers, bookers and attendees are all rows here.

#### `scheduling.Service`

`tenant` FK, `location` FK (**null = offered at all locations**), `name` (Char), `duration_minutes` (PositiveInt),
`buffer_minutes` (PositiveInt, default 0), `is_active` (Bool, default `True`), `display_order` (Int, default 0).
Ordering `["display_order", "name"]`.

#### `scheduling.Resource`

*(OraOps `Operatory`, line 8983 — the bookable room/chair/bay, degenericized from dentistry.)*

`tenant` FK, `location` FK, `name` (Char(128)), `resource_number` (PositiveInt, null),
`description` (Char(255), blank), `display_order` (Int, default 0), `is_active` (Bool, default `True`).
**Unique `(location, name)`.** Ordering `["display_order", "name"]`.

#### `scheduling.Appointment`

*(OraOps `Appointment`, line 9123, with **all** dental/clinical fields dropped — no `procedures`, `lab_case`,
`lab_case_due`, `clinical_note`, `note_tooth`, `note_signed_at`, `note_signed_by`, `note_signature`,
`note_addenda`, `premedicate`, `additional_provider_id`.)*

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `location` | FK Location |
| `contact` | FK Contact, `on_delete=PROTECT` |
| `provider` | FK `settings.AUTH_USER_MODEL`, **null** — an `is_provider` user |
| `resource` | FK Resource, null, `on_delete=SET_NULL` |
| `service` | FK Service, null, `on_delete=SET_NULL` |
| `start_at`, `end_at` | DateTime |
| `status` | Char(24), **indexed**, default `scheduled`: `scheduled` / `confirmed` / `completed` / `cancelled` / `no_show` |
| `reason` | Char(255), blank |
| `notes` | Text, blank |
| `source` | Char(16): `ai_phone` / `manual` / `web` |
| `booked_by_session` | FK `calls.CallSession`, null, `on_delete=SET_NULL` — the call that produced this booking |
| `cancelled_at` | DateTime, null |
| `cancellation_reason` | Char(255), blank |

Index `(tenant, location, start_at)`, plus `(tenant, status)` and `(tenant, contact)`. Ordering `["start_at"]`.
The calendar reads this index; every calendar query carries both `tenant` and `location`.

#### `scheduling.CallbackRequest`

*(OraOps `AppointmentCallback`, line 9577 — the "take a message" outcome of an after-hours or can't-help call.)*

`tenant` FK, `location` FK, `contact` FK (**null** — the caller may be unknown), `caller_name` (Char(255), blank),
`caller_phone` (Char(32), blank — the confirmed callback number), `reason` (Text, blank),
`status` (Char(16), default `pending`: `pending` / `contacted` / `closed`), `source` (Char(32), default
`ai_phone`), `notes` (Text, blank).
Index `(tenant, location, status)`. Ordering `["-created_at"]`.

Deltas from the reference: `metadata` is **dropped** (nothing writes it here — `CallSession.metadata` already
carries the call-level detail), `location` is **non-null** (a callback is always about one location's calendar),
and `source` is harmonized to `ai_phone` / `manual` / `web`.

> **Corrected 5.1.** This paragraph previously read "and the callback links to that session", which contradicted
> the field list directly above it — that list specifies no session FK, and 4.5 built none. The field list is
> authoritative and the prose was wrong. `CallbackRequest` has **no** FK to `calls.CallSession`, deliberately,
> unlike `Appointment.booked_by_session`. Adding one later is a real option (it would be a clean additive
> migration — `CallSession.callback_requests` does not clash with `Contact.callback_requests`, and a nullable
> column leaves `idx_callback_tenant_loc_status` untouched), but it is a decision to take on purpose, not a
> thing to infer from a stray sentence.

### 3.4 Call logs — `calls`

#### `calls.CallSession` — the one call log

*(OraOps `AgentSession`, line 9470 — reproduced faithfully, because the owner asked for OraOps' call logs
exactly. Three deliberate deltas: `patient_id` becomes the `contact` FK; the registration-form fields
`form_id` and `submission_snapshot` are **dropped** (there are no registration forms in this product); and
`from_number` / `to_number` / `provider_call_sid` are **added** as real columns, where OraOps carried them
inside `metadata` — `provider_call_sid` is the webhook idempotency key and needs a unique constraint.)*

| Field | Type / choices |
|---|---|
| `tenant` | FK Tenant |
| `location` | FK Location |
| `contact` | FK Contact, **null** (an unknown or withheld caller ID is normal) |
| `channel` | Char(32), default `agent_phone` |
| `mode` | Char(16): `live` / `google` / `gemini` — mirrors `AgentSetting.voice_provider` |
| `status` | Char(16), default `in_progress`: `in_progress` / `completed` / `abandoned` / `transferred` / `failed` |
| `from_number`, `to_number` | Char(32), E.164, indexed |
| `provider_call_sid` | Char(64), **unique** — the Twilio CallSid; the idempotency key for webhook redelivery |
| `transcript` | JSON list — `[{sequence, role, text, at, offset}]` |
| `logs` | JSON list — the event log, `[{sequence, level, category, title, raw_json, occurred_at}]` |
| `analysis` | JSON dict — `{summary, success_evaluation, extracted_data}` |
| `usage` | JSON list — per-turn cost, `[{turn_sequence, cost_breakdown, cost_usd}]` |
| `recording_blob` | Char(512), blank — the **private** storage path; `""` = no recording. Served only through a short-lived signed URL, never a public media path |
| `transfer` | JSON dict — the per-call human-handoff outcome |
| `waveform_peaks` | JSON, null — `{caller, bot, bins}` for the call-detail waveform |
| `started_at`, `ended_at` | DateTime, null |
| `metadata` | JSON dict |

Indexes: `(tenant, location, started_at)`, `(tenant, status)`, `(tenant, contact)`. Unique `provider_call_sid`.
Ordering `["-created_at"]`.

> **Why this is ONE table with JSON columns, and not a normalized event log.**
>
> A call session is **written once by one process** — the media-stream consumer that owns the call — and **read as
> a whole**, on one detail page. Nothing in the application queries across turns: there is no cross-call transcript
> search, no per-turn billing rollup, no analytics module. The transcript, the event log, the per-turn usage and
> the transfer outcome are all *documents about this one call*, and they are always fetched together with it.
>
> At this size the JSON columns are the right call: one row written, one row read, no join, no ordering bug, no
> second source of truth for "what happened on this call". A three-table split (`Call` + `CallTurn` + `CallEvent`)
> would buy query power nothing uses and cost a write path per turn on the latency-critical realtime loop.
>
> **This is stated here so a future reader does not "improve" it into three tables.** Doing so is an Invariant 2
> violation, not a refactor.
>
> Recording consent still applies — it is an inbound concern. The consent basis for a recording and its retention
> window live in `metadata` on the row that was actually recorded, because the policy that applied is the policy
> at the time of the call.

**PII rule.** Transcripts, caller numbers and tool-call argument blobs are PII by definition. Never log a
transcript body, a caller number or a `create_contact` args payload at INFO — that payload is a full name and a
date of birth. Redact tool-call arguments before persisting them into `logs`.

---

## 4. Which module owns what

| # | Module | app slug | Owns | Reads |
|---|---|---|---|---|
| 0 | Accounts & Access | `accounts` | `User`, `UserLocation`; login, logout, password change, email change, profile, roles, the active-location switcher | `Tenant`, `Location` |
| 1 | Business & Locations | `tenants` | `Tenant`, `Location`; business settings, staff↔location assignment, provider working hours | `User`, `UserLocation` |
| 2 | Agent Setup & Telephony | `agents` | `AgentSetting`; agent config, Twilio connection, transfer settings, test call | `Tenant`, `Location` |
| 3 | Call Runtime | `runtime` | **no models** — a service module: Twilio webhooks + signature verification, the media-stream consumer, the turn loop, the LLM tools, transfer execution, recording, a diagnostics page | `AgentSetting`, `Contact`, `Service`, `Resource`; **writes** `CallSession`, `Appointment`, `CallbackRequest`, `Contact` |
| 4 | Calendar & Bookings | `scheduling` | `Contact`, `Service`, `Resource`, `Appointment`, `CallbackRequest`; calendar views, booking CRUD, availability | `Location`, `User` (providers), `CallSession` |
| 5 | Call Logs | `calls` | `CallSession`; session list + detail, transcript, event log, cost breakdown, recording playback, transfer outcome | `Contact`, `Location`, `Appointment` |

Module 3 owns no tables — it is the writer of tables owned by `calls` and `scheduling`. That is deliberate: the
runtime is a process, not a domain.

---

## 5. Derived, never stored

The one rule that survives the cut: a stored counter that a retry or a manual edit can desync from its source is
a bug.

| Derived value | Derived FROM | The stored field that would be a bug |
|---|---|---|
| A call's cost | `sum(turn["cost_usd"] for turn in session.usage)` | A `cost_usd` column on `CallSession` that a view can write independently of `usage`. |
| Calls today / this week | `CallSession.objects.filter(tenant=t, location=l, started_at__gte=…).count()` | `Location.calls_today`, `Tenant.total_calls`. |
| A location's booked slots | `Appointment.objects.filter(tenant=t, location=l, start_at__range=…)` | An `is_booked` flag on `Resource`, or a stored per-day slot map. |
| Is the location open now | `Location.timezone` + the configured hours, evaluated **server-side** | A stored `Location.is_open` flag — and equally, handing the LLM the hours plus a clock and asking it to decide. **The server computes it and injects the literal `"yes"` / `"no"` into the prompt.** |

---

## 6. Migration notes

**`AUTH_USER_MODEL = 'accounts.User'` is set in `config/settings.py` before the very first `makemigrations`.**
Django bakes the user model into every migration that references it, so switching it after the initial migrations
exist is not a refactor — it requires a **destructive reset** (drop the database, delete and regenerate every
migration). It must be right from the first migration.

**Every FK to the user model uses `settings.AUTH_USER_MODEL`, never a direct import.** In this model set that is
`scheduling.Appointment.provider`, and any later FK of the same kind:

```python
from django.conf import settings
provider = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name='appointments')
```

Django emits `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` into the migration's `dependencies`
itself when the FK is written this way. A `from apps.accounts.models import User` inside another app's models is
a **defect**, not a style preference: `accounts.User` FKs `tenants.Tenant` while other apps FK back to the user
model, so the direct import is an import cycle at module-load time. The `settings` reference is what breaks it.

**The base + follow-up migration split is CORRECT, not a bug.** `accounts.User` carries a `tenant` FK to
`tenants.Tenant`, and `tenants` models FK nothing back — but where any mutual app dependency does arise, Django
resolves it by splitting one app into a base migration plus a follow-up that carries the deferred FK `AddField`
operations. The expected foundation apply order is:

```
accounts/0001_initial   — the User model; depends on auth/0012
tenants/0001_initial    — Tenant + Location; swappable_dependency(AUTH_USER_MODEL) where needed
accounts/0002_initial   — depends on accounts/0001 + tenants/0001; carries User.tenant
```

**The exact set, count, ordering and file names vary with the model set — expect fewer or more operations than
this example. The split itself is what matters, and it is correct.** Do not "fix" it by moving a model between
apps or by dropping an FK.

A single `makemigrations` run can author files in more than one app — run `git status` after every run and commit
each generated migration as its own commit.

---

*Last word: this document is INTENT. The code is truth — grep before you FK.*
