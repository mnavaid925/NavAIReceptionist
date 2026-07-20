# Research — Sub-module 5.1: Call Log List (Module 5 — Call Logs, calls)

## Repo state checked first

- `LIVE_LINKS` has **no `5.*` entry at all** (verified in `apps/accounts/navigation.py`) — Module 5 is fully
  unbuilt and 5.1 is the correct next sub-module. Module 4 is fully built (`4.1`–`4.5` all present); Module 2
  fully built (`2.1`–`2.4`).
- `apps/calls/` — confirmed **does not exist** (`Glob apps/calls/**` → no files). This is a brand-new app.
  `apps/runtime/` — confirmed **does not exist either** — Module 3 (the service module that will WRITE
  `CallSession` rows from a real call) is also unbuilt. This matters: 5.1 creates the table and its own list UI,
  but nothing yet produces a real row except the seeder.
- Models verified to exist, grepped directly, all available for 5.1 to FK or reuse:
  - `agents.AgentSetting` — `apps/agents/models/AgentConfiguration/AgentSettings.py` — one row per
    `(tenant, location)`, `voice_provider` choices `live`/`google`/`gemini` (`VOICE_PROVIDER_CHOICES`) — this is
    what `CallSession.mode` mirrors per the ERD.
  - `scheduling.Contact` — `apps/scheduling/models/ContactDirectory/Contacts.py` — tenant-scoped only (Invariant
    1), has `display_name` (never blank — falls back to phone, then `"Unknown caller"`) and `anonymize()` (GDPR
    erasure; blanks identifying fields, stamps `anonymized_at`, cascades to `CallbackRequest` but — see below —
    has **no** cascade path to `CallSession` yet, because `CallSession` doesn't exist).
  - `scheduling.Appointment` — `apps/scheduling/models/Bookings/Appointments.py` — its own docstring **already
    documents the exact gap this pass closes**: *"`booked_by_session` is deliberately absent. The ERD specifies
    an FK to `calls.CallSession`... but `apps.calls` does not exist yet... Module 5 adds it as an additive
    migration."* Confirms the instruction given for this task is exactly what the scheduling app's own code is
    waiting for.
  - `scheduling.CallbackRequest` — `apps/scheduling/models/CallbackRequests/CallbackRequests.py` — its docstring
    is explicit that it carries **no FK to `calls.CallSession` at all**, by ERD design, not by omission. This
    closes off one candidate interpretation of the "outcome" filter — see below.
  - `apps/accounts/models/_base.py` — `TenantOwned` / `TenantLocationOwned` / `TimeStamped` abstract bases.
    `CallSession` is location-scoped per the ERD, so it takes `TenantLocationOwned` (gives `tenant`, `location`,
    `created_at`, `updated_at` for free).
  - `apps/agents/fields.py` — `EncryptedCharField` pattern for provider secrets — not needed by `CallSession`
    itself (it carries no credential), but its existence confirms the project's "sensitive field never rendered,
    never logged" discipline that also governs `CallSession.transcript`/`.recording_blob`.
- **Two already-shipped surfaces encode the CallSession contract ahead of this pass** — this is the
  "code is truth" signal the task calls for, even though there's no `CallSession` model yet to grep directly:
  1. `templates/partials/_call_status_badge.html` **already exists and is already wired into
     `templates/scheduling/directory/contact/detail.html`** (its "Calls" card, import-guarded on
     `apps.calls.models.CallSession`). It hard-codes **five** status branches:
     `in_progress`→`badge-info`, `completed`→`badge-green`, `abandoned`→`badge-muted`,
     `transferred`→`badge-info`, `failed`→`badge-red` — verbatim the same five CLAUDE.md's own Filter
     Implementation Rules section names as "the canonical call-status map."
  2. `apps/scheduling/views/ContactDirectory/Contacts.py::_call_sessions_for()` **already queries**
     `CallSession.objects.filter(tenant_id=contact.tenant_id, contact=contact,
     location_id__in=_visible_location_ids(request)).select_related('location').order_by('-started_at')[:10]`
     — confirming the field names `contact`, `tenant_id`, `location`, `started_at` and the location-visibility
     scoping pattern (`request.user.assigned_locations()`, not a raw `request.location`) that 5.1 must also use.
  3. `templates/partials/_transfer_outcome.html` **already exists**, reads `session.transfer` and branches on
     `transfer.result` ∈ `connected` / `off_hours` / `disabled` / `failed` / `no_answer`. Nothing in Module 5
     built it yet — it was authored ahead of time, presumably alongside 2.3/2.4 work — but it is the authoritative
     shape of the `transfer` JSON dict and directly informs the "outcome" filter below.

  **Finding — the ERD's own field table for `calls.CallSession` is stale on `status`.** ERD line 324 lists only
  three choices: `in_progress` / `completed` / `abandoned`. But (a) the sub-module's own bullet text says
  *"Renders `in_progress`, `completed`, `abandoned`, `transferred` and `failed`"* (five), (b) CLAUDE.md's Filter
  Implementation Rules section states the same five as "the canonical call-status map", and (c) the badge
  partial above is **already shipped code** hard-coding all five. Per this project's own rule — "the code is
  truth, so grep before you FK" — the two already-committed artifacts (the badge partial + the calling view) win
  over the ERD's stale table. **`CallSession.STATUS_CHOICES` must ship with five values, not three**; building
  it with the ERD's literal three would make the already-shipped partial's `transferred`/`failed` branches
  unreachable dead code and would contradict the sub-module's own bullet. This is flagged here, not silently
  "fixed" in the ERD, per the project's own instruction to fix the doc in the same change that discovers the
  drift.
- Sibling research files: none exist yet for Module 5 (`Glob .claude/tasks/research-calls-*.md` → only this
  file). 5.1 is the first pass on this module; there is no earlier-deferred backlog to inherit.

## Leaders surveyed (with source links)

1. **Smith.ai** — human+AI receptionist with a client call dashboard; the strongest researched example of
   at-a-glance row summarization via action icons — [Using and Accessing the Smith.ai Call
   Dashboard](https://docs.smith.ai/article/n40myw0flr-using-and-accessing-the-smith-ai-call-dashboard), [Call
   Analytics & Call Intelligence](https://smith.ai/features/call-intelligence-and-metadata)
2. **Dialpad AI** — contact-center-grade call log with the richest filter taxonomy researched (category, purpose,
   talk-time, keyword/moment, agent-expertise) — [Call Logs and Call History for Contact
   Centers](https://www.dialpad.com/features/call-logs/), [Using Conversation
   History](https://help.dialpad.com/docs/using-conversation-history)
3. **Retell AI** — voice-agent-native "Session History" dashboard, closest domain match to this product —
   [Monitor sessions via dashboard](https://docs.retellai.com/features/session-history)
4. **Vapi** — the clearest single-column disposition model: `endedReason` as both a column and a filter, with a
   documented closed taxonomy — [Call ended reasons](https://docs.vapi.ai/calls/call-ended-reason)
5. **Bland AI** — the most directly comparable list-page mechanics found: quick filters, time-range presets, a
   structured advanced-filter builder, configurable/draggable columns, click-a-number-to-filter —
   [Call Logs tutorial](https://docs.bland.ai/tutorials/call-logs)
6. **Synthflow** — unifies call/chat/API/webhook logs; documents filtering by date/type/status/duration/labels and
   explicitly warns that unfiltered-by-date queries are slow at volume — [Calls — Call
   Logs](https://docs.synthflow.ai/docs/call-logs), [Logs](https://docs.synthflow.ai/logs)
7. **Ruby Receptionists** — simple activity list (call/chat/voicemail unified), click-through to full detail,
   export — [Ruby's Online Portal](https://rubyhelpcenter.helpjuice.com/en_US/apponline-portal/rubys-online-portal)
8. **Rosie AI** — unified inbox merging calls+texts with an AI summary and lead details surfaced per row, mobile
   push notification tied to the same event — [Rosie mobile app](https://heyrosie.com/features/mobile-app)
9. **PolyAI** — analytics-layered call review (containment, sentiment, resolution) sitting on top of a
   conversation-review table — used here mainly as a negative/deferred example: most of what it adds belongs to
   analysis (5.2/5.3), not the list — [Conversational analytics](https://poly.ai/blog/conversational-analytics)
10. **Goodcall** — dashboard framed around "intent and outcome" of every call, with plan-tiered call-history
    retention windows — used as the retention-window signal noted under Compliance —
    [Goodcall AI Receptionist](https://www.goodcall.com/)

## Feature catalog (this sub-module only)

### Session List
- **Newest-first ordering by actual call start, not row-creation order** — every leader researched defaults to
  most-recent-first (Bland: *"sorted most recent first by default"*; Retell's dashboard is inherently
  chronological) · seen in: Bland, Retell, Synthflow · priority: table-stakes · model: reuses `CallSession`,
  ordered `.order_by('-started_at')` in the view — **matches the ordering `_call_sessions_for()` already uses in
  4.1's shipped code**, even though the ERD's own `Meta.ordering` on the model is `["-created_at"]` (an explicit
  `.order_by()` in the view always wins over `Meta.ordering`, so there is no conflict — just don't rely on the
  model default for "newest call first," rely on the explicit clause) · realtime: post-call (list page) ·
  tool-surface: pure UI · buildable now.
- **Duration column, computed, never stored** — Bland shows a dedicated Duration column; nothing in the ERD's own
  "Derived, never stored" table names call duration explicitly, but the same principle it states for cost applies
  identically: a `duration_seconds` column a retry or manual edit could desync from `started_at`/`ended_at` is
  exactly the anti-pattern §5 forbids · seen in: Bland, Dialpad, Vapi (duration is always a first-class visible
  value across every leader) · priority: table-stakes · model: a `duration_display` **property** on `CallSession`
  — `ended_at - started_at` when both are set, else "in progress" (started, no `ended_at`) or "—" (neither set) ·
  realtime: post-call · tool-surface: pure UI (template property) · buildable now.
- **From/To numbers as real columns, not buried in metadata** — the ERD already made this exact choice a
  deliberate delta from its own OraOps reference (*"`from_number`/`to_number`/`provider_call_sid` are added as
  real columns, where OraOps carried them inside `metadata`"*), and every leader surfaces the numbers as plain
  list columns · seen in: Bland (From/To), Dialpad, Smith.ai (caller info column) · priority: table-stakes ·
  model: reuses `CallSession.from_number` / `.to_number` (ERD fields, indexed) · realtime: post-call · tool-surface:
  pure UI · buildable now.
- **Contact column with the same never-blank display convention as the rest of the app** — `Contact.display_name`
  already falls back phone → "Unknown caller"; the call log's Contact column must render the identical fallback
  so an unidentified caller reads as "we don't know who this was," never as a blank/broken cell · seen in: Smith.ai
  (caller "Unknown"/"New Lead" bucket), Ruby (voicemail-only rows still show a caller line) · priority: table-stakes
  · model: reuses `scheduling.Contact.display_name` through the nullable `CallSession.contact` FK · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Row-level column configurability (hide/reorder/show columns)** — Bland and Retell both let the operator
  customize the table's columns · priority: differentiator · model: none — pure client-side/session preference,
  no new field · realtime: post-call · tool-surface: pure UI · **integration/later** — real but not asked for by
  this sub-module's bullets; the four named columns (duration, from/to, contact, status) plus the two link columns
  are the committed scope this pass.

### Filters
- **Date range: presets + custom** — every leader offers relative presets (today/yesterday/this week/last
  week/this month/last month/custom — Smith.ai; 1h/24h/today/7d/30d — Bland) layered over a raw from/to date
  picker; Synthflow explicitly warns that querying without a date filter is slow at volume, which is the
  performance argument for making this the primary predicate · seen in: Smith.ai, Bland, Synthflow · priority:
  table-stakes · model: reuses `CallSession.started_at`, filtered with `date_from`/`date_to` GET params against
  the `(tenant, location, started_at)` composite index the ERD already specifies · realtime: post-call ·
  tool-surface: pure UI (query params) · buildable now.
- **Status filter** — dropdown from the model's own choices, per this app's standing Filter Implementation Rules
  (pass `status_choices` from `Model.STATUS_CHOICES`, compare on exact string) · seen in: Retell (filter by
  status), Bland (Status column doubles as the filter axis) · priority: table-stakes · model: reuses
  `CallSession.status` (the five-value set established above) · realtime: post-call · tool-surface: pure UI ·
  buildable now.
- **Mode filter** — this product's own axis (mirrors `AgentSetting.voice_provider`: `live`/`google`/`gemini`); the
  closest researched analogue is Retell's "filter by agent" and Synthflow's agent-scoping filter, since in both
  cases the operator is narrowing by *which engine/config handled the call*, not by outcome · seen in: Retell,
  Synthflow (as an analogous axis, not the identical field) · priority: common · model: reuses `CallSession.mode`
  · realtime: post-call · tool-surface: pure UI · buildable now.
- **Outcome filter — resolved to the `transfer` JSON dict's `result` key, not a new field.** This is the one
  filter axis this pass had to actually design, because nothing in the ERD's field table is literally named
  "outcome." Vapi's `endedReason` column/filter and Retell's "disconnection reason" filter are the closest
  researched analogues — both are a single closed-enum disposition value read straight off the session object,
  not a join across other tables. This product already has exactly that shape sitting unused: the
  `_transfer_outcome.html` partial (shipped, see Repo state above) branches on `transfer.result` ∈ `connected` /
  `off_hours` / `disabled` / `failed` / `no_answer`, plus the natural "no transfer attempted" case (`transfer` is
  empty/absent — the common case, since most calls never ask for a human). **Recommendation: `outcome` filters on
  `CallSession.transfer__result`** via Django's JSONField key-transform lookup (supported on MySQL in Django 4.2),
  with an explicit "no transfer" bucket for an empty/missing `transfer` dict — zero new columns, and it reuses a
  vocabulary the codebase already committed to. *(A second candidate — "booked" vs. "not booked", keyed off the
  new `booked_by_session` reverse relation — is real and buildable this pass too, but it reads better as a
  per-row icon under "Contact & Booking Links" below than as a fourth value crammed into one "outcome" dropdown;
  see that section.)* · seen in: Vapi (`endedReason`), Retell (disconnection reason), and this product's own
  already-shipped partial · priority: table-stakes (it's a named bullet) · model: reuses `CallSession.transfer`
  (ERD JSON dict field, no new column) · realtime: post-call · tool-surface: pure UI (a JSON key-transform
  `.filter()`, not a tool) · buildable now.
- **Search by caller number or contact name** — Bland's "click a number to filter to that contact's history" and
  Synthflow's "search by identifier rather than freeform keyword for speed" both converge on the same UX this
  bullet names directly · priority: table-stakes · model: `Q(from_number__icontains=q) | Q(to_number__icontains=q)
  | Q(contact__first_name__icontains=q) | Q(contact__last_name__icontains=q)` against the existing `Contact` FK —
  no new field · realtime: post-call · tool-surface: pure UI · buildable now.

### Status Badges
- **Reuse the shipped partial verbatim — do not re-author the branch logic.** `_call_status_badge.html` already
  exists, is already the single source of truth CLAUDE.md's own comment block names ("never inline the branches
  at a call site"), and is already `{% include %}`-ed from 4.1's contact detail page. 5.1's list template includes
  the same partial per row (`{% include "partials/_call_status_badge.html" with obj=session %}`) rather than
  reimplementing the five-way branch · seen in: this codebase's own established convention (`badge-info` reused
  twice by design, deliberate: *"There is no badge-purple in this design system"*) · priority: **REQUIRED** — not
  a style preference; CLAUDE.md's Filter Implementation Rules pin these five exact class/value pairs project-wide,
  and a second implementation is a maintenance fork of a rule the framework already states must have one
  authority · model: reuses `CallSession.status` (five-value choices, see Repo state finding above) · realtime:
  post-call · tool-surface: pure UI · buildable now.

### Contact & Booking Links
- **Link to `scheduling.Contact`'s existing detail page when identified** — `scheduling:contact_detail` already
  exists (4.1); the "Contact" column is a link when `contact_id` is set, and renders `Contact.display_name`
  un-linked (with its own "Unknown caller" fallback) when it is not · seen in: Smith.ai (clickable caller row),
  Ruby, Rosie (both link straight into the caller/lead's own record) · priority: table-stakes · model: no new
  field — the existing nullable `CallSession.contact` FK · realtime: post-call · tool-surface: pure UI · buildable
  now.
- **Link to the appointment this call produced, via the additive `booked_by_session` migration.** This is the
  literal instruction for this pass, and it's what makes Smith.ai's single strongest researched signal
  (per-row action icons — "scheduling an appointment," "transferring the call") concretely buildable here: once
  `Appointment.booked_by_session` exists, a row can show a small "Booked" indicator/link straight to
  `scheduling:appointment_detail` wherever `session.booked_appointments.exists()` is true (recommended
  `related_name='booked_appointments'` on the new FK, since a single call could in principle produce more than
  one appointment — e.g., two different services booked in the same call — so the reverse accessor should not
  assume exactly one row) · seen in: Smith.ai (action icon: "scheduling an appointment"), Bland/Vapi (tool-call
  outcome surfaced on the call), this product's own explicit deferred-FK note in `Appointment`'s docstring ·
  priority: **REQUIRED** — it is the sub-module's own named bullet, and it is the concrete reason the additive
  migration exists · model: **additive migration on `scheduling.Appointment`**, not a new model:
  `booked_by_session = models.ForeignKey('calls.CallSession', null=True, blank=True,
  on_delete=models.SET_NULL, related_name='booked_appointments')` — location-scoped through the existing
  `Appointment` row, no new location FK needed on `CallSession` beyond what it already carries · realtime: n/a
  (post-call link) · tool-surface: pure UI — no tool reads or writes this field yet (Module 3.3's
  `book_appointment` tool, which would populate it, doesn't exist until Module 3 is built; this pass ships the
  column, not a writer) · buildable now (schema only; population is integration/later, same posture 4.3's own
  research already recorded for the mirror image of this same field).

### Beyond the bullets
- **Per-row disposition icon set (Smith.ai's strongest signal)** — icons for "booked," "transferred," etc. at a
  glance without opening the row · priority: differentiator · model: composed entirely from already-available
  data (`booked_appointments.exists()`, `transfer.result`, `status`) — no new field · realtime: post-call ·
  tool-surface: pure UI · buildable now, but **treated as a "beyond the bullets" nice-to-have**, not required —
  the bullet only asks for links, not iconography; a future pass can add icons without a schema change.
- **AI-generated one-line summary shown inline in the list row (Dialpad's "AI recap," Rosie's "AI summary")** —
  reads `CallSession.analysis.summary` · priority: common among leaders, but this is explicitly **5.2's surface**
  ("Analysis Panel" is a named 5.2 bullet) → parked, not built here, so the list row doesn't quietly duplicate
  5.2's content before 5.2 exists.
- **Configurable/hideable/reorderable columns** (Bland, Retell) — differentiator, no schema impact, genuinely
  deferred (not asked for by this sub-module's bullets).
- **Talk-time / speaker-ratio filter** (Dialpad) — would require deriving a metric from `transcript` at query
  time; expensive over a JSON column at list-scale, and belongs conceptually with 5.3's cost/analysis surfaces,
  not the plain list → parked.
- **Custom post-call analysis field filtering** (Retell's enum/bool/number custom fields) — reads
  `CallSession.analysis.extracted_data`; real, but it's 5.2's "Analysis Panel" territory, and the sub-module's own
  filter bullet names exactly four axes (date range, status, mode, outcome) — adding a fifth, open-ended one here
  would be scope creep the bullets don't ask for → parked to 5.2/5.3.
- **Issue/quality severity badges** (Bland's Issues column) — overlaps with 5.3's "Runtime Error Surface" bullet
  → parked to 5.3.
- **Caller classification / lead-priority tiers** (Smith.ai's New Lead/Existing Client/Attorney, priority
  Low/Normal/Urgent) — **out of scope for this product**, see below; there is no CRM-style scoring layer among
  the seven capabilities and `Contact.source` (`ai_phone`/`manual`/`web`) already covers this product's actual
  provenance axis.

## Compliance & provider constraints

- **REQUIRED — the model must carry the fields a later consent/retention feature needs, even though 5.1 builds
  none of that UI itself.** The ERD is explicit that *"the consent basis for a recording and its retention window
  live in `metadata` on the row that was actually recorded"* — so `CallSession.metadata` (JSON dict, default
  `dict`) must ship in this pass exactly as specified, even though the announce-before-record flow (Module 3.5)
  and the recording/consent UI (5.4) are both unbuilt. Shipping the model without this field, or with `metadata`
  typed as something narrower, would block 3.5 and 5.4 from ever landing correctly.
- **REQUIRED — two-party-consent announcement and AI-disclosure are Module 3.5/5.4 surfaces, not 5.1's, but 5.1
  must not preclude them.** Noted here only so nothing is wrongly built (or wrongly skipped) in this pass:
  `recording_blob` (private storage path, blank = no recording) and `transfer` (per-call handoff outcome) both
  ship as plain columns this pass with no consent logic behind them yet — they are inert until Module 3 writes to
  them.
- **REQUIRED — HIPAA/GDPR retention & subject-rights interaction with `Contact.anonymize()`.** `Contact` already
  has a working erasure path (`anonymize()`), and it already cascades to `CallbackRequest` (`SET_NULL` FK,
  free-text `caller_name`/`caller_phone` scrubbed because those are a **duplicated copy** of the caller's
  identity). `CallSession.contact` should be **`on_delete=models.SET_NULL`** — same precedent as
  `CallbackRequest.contact` — so an erased/removed contact never cascade-deletes the call record. **But
  `CallSession.from_number`/`to_number`/`transcript` are NOT the same kind of field as `CallbackRequest`'s
  `caller_name`/`caller_phone`: they are the call detail record itself**, not a duplicated identity field
  captured before identification. This pass does **not** extend `Contact.anonymize()`'s scrub cascade to
  `CallSession` — the call detail record's own retention window (enforced by Module 3.5's scheduled job, per the
  Module 3 catalog: *"the retention window is enforced by a scheduled job"*) is the correct erasure mechanism for
  it, not a contact-triggered field blank. This is a deliberate scoping decision, flagged here rather than
  silently assumed, because getting it wrong either way is a compliance bug: scrubbing the CDR on contact erasure
  destroys a record a retention policy may still require keeping; never scrubbing it anywhere is its own GDPR
  gap that Module 3.5's job must close later.
- **PII discipline on the list/search surface itself.** Never log a search query, a phone number or a contact
  name at INFO from the list view — a receptionist's search box is exactly the kind of value CLAUDE.md's PII rule
  calls out (*"a `create_contact` args payload is a full name and date of birth"* — the same logic applies to a
  free-text search query here). If the view logs anything (e.g., "list viewed, N results"), it must not include
  the raw `q` param.
- **No provider cost line originates in this sub-module.** 5.1 is pure ORM + templates: no Twilio call, no
  STT/TTS/LLM token spend, no row appended to `CallSession.usage` (that JSON list is written by Module 3's
  runtime; 5.1 doesn't even render it — that's 5.3's job). The one performance-relevant constraint is query
  shape, not provider cost: the list view's default query **must** hit the `(tenant, location, started_at)`
  composite index the ERD already specifies (`select_related('contact', 'location')`, date-range predicate
  applied before pagination), because Synthflow's own docs explicitly warn that an unfiltered-by-date call-log
  query degrades at volume — the same failure mode applies to a MySQL table growing one row per inbound call.
- **Seeder note.** Module 3 (the fake/live/sandbox provider adapters under `apps/runtime/providers/`) does not
  exist yet, so `seed_calls` cannot literally route through a fake provider object — there is no such object to
  route through. This is not a violation of the "seeders never touch a real provider" rule: that rule is about
  never placing a real call, and a seeder that hand-authors plausible `transcript`/`logs`/`analysis`/`usage`/
  `transfer` JSON directly onto synthetic rows (unique `provider_call_sid` values, never dialing anything) trivially
  satisfies it. Seed across **at least two locations per tenant** (per the standing Seed Command Rule), covering
  all five statuses (so the badge partial's every branch is exercised), a mix of `mode` values, some rows with a
  linked `Contact` and some `contact=None` (unknown caller), and — once the additive migration lands — a few rows
  with a `booked_appointments` link so the Contact & Booking Links surface has something to click through to.

## Recommended build scope (this pass)

**CRUD sub-module — 1 model** (this is the one sub-module in Module 5 that adds a model; 5.2–5.4 are VIEW
sub-modules over this same row and add none):

- **`CallSession`** (`apps/calls/models/CallLogList/CallSessions.py` per the backend package-structure rule,
  sub-module folder `CallLogList`) — tenant **and** location scoped (`TenantLocationOwned`). Fields, per the ERD
  with the one flagged correction:
  - `contact` — FK `scheduling.Contact`, **null=True, blank=True, on_delete=models.SET_NULL** (ERD says null but
    is silent on `on_delete`; `SET_NULL` matches the `CallbackRequest.contact` precedent and the reasoning above).
  - `channel` — Char(32), default `"agent_phone"` (ERD field, no choices enumerated — freeform, single value in
    practice for this pass).
  - `mode` — Char(16), choices mirroring `AgentSetting.VOICE_PROVIDER_CHOICES` (`live`/`google`/`gemini`).
  - `status` — Char(16), default `in_progress`, **choices expanded to the five values already live in the
    shipped badge partial**: `in_progress` / `completed` / `abandoned` / `transferred` / `failed` — see the
    flagged ERD-vs-code discrepancy above; this is the one deviation from the ERD's literal table in this pass,
    and it is a correction, not a scope addition (the values already exist in shipped, running code).
  - `from_number`, `to_number` — Char(32), E.164, indexed.
  - `provider_call_sid` — Char(64), **unique** — the webhook idempotency key (Module 3's job to write; this pass
    just needs the column and its unique constraint present).
  - `transcript` — JSONField, default `list`.
  - `logs` — JSONField, default `list`.
  - `analysis` — JSONField, default `dict`.
  - `usage` — JSONField, default `list`.
  - `recording_blob` — Char(512), blank — private storage path, `""` = no recording.
  - `transfer` — JSONField, default `dict` — shape already fixed by the shipped `_transfer_outcome.html` partial:
    `{result, reason, destination, initiated_at, duration_seconds}`.
  - `waveform_peaks` — JSONField, null=True.
  - `started_at`, `ended_at` — DateTime, null=True.
  - `metadata` — JSONField, default `dict`.
  - Indexes: `(tenant, location, started_at)`, `(tenant, status)`, `(tenant, contact)` — all three named in the
    ERD; the first is the one this sub-module's own list query hits on every page load. Unique on
    `provider_call_sid`. `Meta.ordering = ["-created_at"]` per the ERD (the list view's own explicit
    `.order_by('-started_at')` is what actually governs display order, matching the ERD's own convention that an
    explicit view-level order always supersedes the model default).
  - FKs verified to exist: `tenants.Tenant`, `tenants.Location` (via `TenantLocationOwned`), `scheduling.Contact`
    — all grepped above.

  **Views this pass ships:** `list_view` (search + the four filter axes + the two link columns) is the whole of
  this sub-module's bullet scope. A minimal `detail_view` is also recommended — rendering only the header fields
  every leader treats as baseline (numbers, contact, location, mode, status, start/end, computed duration) with
  an explicit "transcript, event log, cost and recording land in a later pass" placeholder, mirroring the
  established house pattern (`{% if call_sessions is None %}` in 4.1's contact detail) rather than leaving zero
  click-through target for a row. **`create_view` and `edit_view` are correctly absent** — CLAUDE.md's own CRUD
  Completeness Rules name `calls.CallSession` as the explicit example of a model with no edit view, because it is
  "a record of what happened," written only by Module 3's runtime, never by a human form. **`delete_view` is also
  recommended absent this pass** — for the same reason plus the compliance point above: a tenant-facing delete
  button on a call detail record undermines the retention-window job Module 3.5 is meant to own; if row cleanup
  is ever needed it belongs behind Django admin, not a tenant CRUD action.

- **Additive migration on `scheduling.Appointment`** (not a new model — the second deliverable this pass, per
  the invoking instruction and the ERD line-286 note): `booked_by_session = models.ForeignKey('calls.CallSession',
  null=True, blank=True, on_delete=models.SET_NULL, related_name='booked_appointments')`, authored as its own
  migration in `apps/scheduling/migrations/`, dependent on `apps/calls`'s initial migration. This is what makes
  the "Contact & Booking Links" bullet's appointment-link half concretely buildable.

**Seeder:** extend a new `seed_calls` command (idempotent on `provider_call_sid`) creating synthetic
`CallSession` rows across at least two locations per demo tenant, covering all five statuses, a mix of `mode`
values, some `contact=None` rows, and — once the migration above lands — a handful linked via
`booked_by_session` so the appointment-link column has real data to click through to. No real provider is ever
touched (see Compliance note above for why this is not a rule violation despite Module 3 not existing yet).

## Belongs to sibling sub-modules (parked, not scoped here)

- Session header detail rendering, speaker-attributed transcript, analysis panel, transcript print view →
  **5.2 Call Detail & Transcript** (reads `CallSession.transcript`/`.analysis`, no new model).
- Structured event log, tool-call trace, per-turn cost breakdown, runtime error surface →
  **5.3 Event Log & Cost** (reads `CallSession.logs`/`.usage`, no new model).
- Waveform player, signed media access, transfer outcome panel (the full detail-page version — 5.1 only needs the
  *filter*, not the panel), PII handling write-up → **5.4 Recording & Transfer Outcome** (reads
  `CallSession.waveform_peaks`/`.recording_blob`/`.transfer`, no new model).
- The actual writer of `CallSession` rows from a real inbound call (webhook resolution, the media-stream
  consumer, the turn loop) → **Module 3 (Call Runtime)**, all sub-modules, none of which exist yet. 5.1 supplies
  the table only.
- Populating `booked_by_session` from a live call → **Module 3.3** (the `book_appointment` tool), once it exists.

## Out of scope for this product (outside the seven capabilities)

- **Lead-priority tiers and caller classification** (Smith.ai's New Lead/Existing Client/Attorney buckets,
  Low/Normal/Urgent priority) — this product has no CRM-style scoring layer among its seven capabilities;
  `Contact.source` already covers the one provenance axis this product actually models.
- **Multi-channel unified inbox** (Ruby/Rosie merging voice + SMS + chat into one activity feed) — this product
  is inbound-phone-only; `CallSession.channel` defaulting to `"agent_phone"` is the one channel that exists, and
  there is no second channel to unify with.
- **Contact-center agent performance analytics** (Dialpad's AI Scorecard, agent-expertise filters, PolyAI's
  containment/AHT/FTE metrics) — there are no human agents fielding these calls in this product's model; the
  "agent" is the AI voice agent configured per location, and per-human performance scoring has no place among the
  seven capabilities.
- **CSV/data export of the call log** (Synthflow, Ruby) — not named by any of Module 5's four sub-modules'
  bullets; would need its own explicit scoping pass if ever added.

## Deferred (later passes / integrations)

- **Per-row disposition icons** (composed from already-available `booked_appointments`/`transfer.result`/
  `status`) — real and buildable now, but genuinely "beyond the bullets"; left for a polish pass so this one
  ships exactly the four named columns plus the two named links.
- **Booking-outcome as a second "outcome" filter value** (`booked` vs. `not booked`, via
  `booked_appointments.exists()`) — buildable the moment the additive migration lands; deliberately not folded
  into the same "outcome" dropdown as `transfer.result` in this pass, to keep that filter's semantics singular
  (see Filters section) — worth a dedicated icon/column instead, in a later polish pass.
- **Configurable/reorderable list columns** (Bland, Retell) — no schema impact, but not asked for by the bullets.
- **Custom post-call analysis field filtering** (Retell) and **talk-time/speaker-ratio filtering** (Dialpad) —
  both belong conceptually with 5.2/5.3's analysis surfaces, not the plain list.
- **`Contact.anonymize()`'s cascade extended to `CallSession`** — deliberately NOT done this pass (see Compliance
  section); revisit only alongside Module 3.5's retention-window job, since the two are the same policy decision
  made once, not twice.
- **CSV export of filtered call log rows** — real leader feature (Synthflow, Ruby), not named by any Module 5
  sub-module's bullets; would need its own scoping decision if ever prioritized.
