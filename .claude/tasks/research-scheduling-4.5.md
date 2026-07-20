# Research — Sub-module 4.5: Bookings List & Callback Requests (Module 4 — Calendar & Bookings, scheduling)

## Repo state checked first

- `LIVE_LINKS` built so far in module 4 (`apps/accounts/navigation.py`): `'4.1': {'Contacts': 'scheduling:contact_list'}`,
  `'4.2': {'Services': 'scheduling:service_list', 'Resources': 'scheduling:resource_list'}`,
  `'4.3': {'Appointments': 'scheduling:appointment_list', 'Find a slot': 'scheduling:appointment_slots'}`,
  `'4.4': {'Calendar': 'scheduling:calendar_day', 'Week view': 'scheduling:calendar_week'}`. `4.5` has no entry —
  the next unbuilt sub-module, matching the invoking prompt.
- Models grep-verified to exist (`grep -rn "^class " apps/scheduling/models/`):
  - `scheduling.Contact` — `apps/scheduling/models/ContactDirectory/Contacts.py` — `TenantOwned`, NOT
    location-scoped (Invariant 1). Carries `anonymized_at` (erasure marker, not in the ERD but real), `source`
    choices `ai_phone`/`manual`/`web`, `.display_name`.
  - `scheduling.Service` — `apps/scheduling/models/ServicesResources/Services.py` — `TenantOwned` with a
    hand-declared nullable `location`.
  - `scheduling.Resource` — `apps/scheduling/models/ServicesResources/Resources.py` — `TenantLocationOwned`.
  - `scheduling.Appointment` — `apps/scheduling/models/Bookings/Appointments.py` — `TenantLocationOwned`.
    `contact` FK is `on_delete=PROTECT` (deliberately — a person's booking history must survive their deletion);
    `booked_by_session` is **deliberately absent** — the model's own docstring explains `apps.calls` isn't
    installed yet and Django refuses a relation to an uninstalled app; the placeholder is `source` alone, added
    as an additive migration once Module 5 exists.
  - `apps/scheduling/models/_base.py` — its own docstring **already lists `CallbackRequest` alongside `Resource`
    and `Appointment`** as a `TenantLocationOwned` model, confirming the intended base class before this pass
    writes a line of code.
- **`scheduling.CallbackRequest` does NOT exist** — confirmed by the grep above (only `Appointment`, `Resource`,
  `Contact`, `Service` classes are defined anywhere under `apps/scheduling/models/`). This is the one new model
  for this pass, exactly as the invoking prompt specifies.
- `apps/calls/` still has no files (re-confirmed) — `calls.CallSession` is not installed, so nothing in this
  sub-module can take a real FK to it either.
- **The "Booking List" and "Appointment Detail" bullets are already substantially built by 4.3**, verified by
  reading the actual view/template code, not assumed from the doc:
  - `apps/scheduling/views/Bookings/Appointments.py::appointment_list_view` already filters by search (`q` across
    contact first/last/phone and `reason`), `status`, date range (`from`/`to` via
    `availability.local_day_bounds_utc`, timezone-correct), `provider`, `service` and `resource` — i.e. the
    **exact filter set the 4.5 bullet describes**, with every dropdown's queryset passed explicitly
    (`status_choices`, `providers`, `services`, `resources`) per the project's own Filter Implementation Rules.
  - `templates/scheduling/bookings/appointment/detail.html` already shows contact, service, resource
    ("with"/"where"), reason, notes, status, source, and location, plus a **defensive placeholder** ("The
    recording and transcript of the call that made this booking will link here once the call logs module is
    built") for the one field the bullet asks for that cannot ship yet — the originating call.
  - `AppointmentForm` already exposes `status` (scheduled/confirmed/completed/no_show, `cancelled` excluded
    because that transition is a separate flow) — so status **can** be changed today, but only through a full
    edit-form round trip; there is no one-click "mark completed"/"mark no-show" action on the list or detail page.
  - This means 4.5's real, honest scope on the appointments side is a **small enrichment**, not a rebuild: 4.3's
    own research file explicitly flagged this gap ("the UI to flip [no_show] explicitly may land with 4.5's
    booking list, since 4.3's own CRUD form still needs a status field/action per the CRUD-completeness rule").
- Sibling research file `research-scheduling-4.3.md` explicitly parks two things at this sub-module: "Appointment
  list with filters ... and search by contact, plus `CallbackRequest` CRUD → 4.5 Bookings List & Callback
  Requests" — the list itself is done; the CRUD explicitly deferred is `CallbackRequest`.

## Leaders surveyed (with source links)

Calendar-side leaders (Calendly, Acuity, Cal.com, Square Appointments, NexHealth, Setmore) were already surveyed
in depth for the bookings/filters/detail contract in `research-scheduling-4.3.md`; not re-surveyed here since that
contract is already built. This pass's fresh research targets the domain 4.3 didn't cover: **how inbound-call
answering products handle the caller they could NOT fully serve.**

1. **Smith.ai** — 24/7 AI receptionist backed by live agents; every call is tagged with type, urgency and action
   taken in the client dashboard, plus a same-day digest — [24/7 AI Receptionist with human
   backup](https://smith.ai/features/24-7-answering-service), [All Features & What We Do](https://smith.ai/all-features/what-we-do)
2. **Ruby Receptionists** — live virtual receptionists; message-taking with multi-channel notification
   (email/text/app) and user-settable follow-up reminders — [Live Virtual
   Receptionists](https://www.ruby.com/live-virtual-receptionists/), [Receptionist Service Quick Start
   Guide](https://rubyhelpcenter.helpjuice.com/en_US/getting-started/receptionist-service-quick-start-guide)
3. **Rosie AI** — AI answering service; unified calls+texts inbox, instant push notification with AI summary, and
   "tap the notification to call back immediately" — [Rosie Mobile App](https://heyrosie.com/features/mobile-app),
   [Rosie AI Call Answering Service](https://heyrosie.com/)
4. **Dialpad AI** — visual voicemail (transcribed, cross-device) and an **in-queue callback** feature that holds a
   caller's place in a *live* hold queue — used here as a **negative/contrast example**: that is a concurrent-call
   ACD concept this product does not have (single transfer destination, not a multi-agent queue) —
   [Visual Voicemail](https://www.dialpad.com/features/voicemail/), [In-Queue
   Callback](https://help.dialpad.com/docs/in-queue-callback)
5. **Goodcall** — no-code AI phone agent; captures every missed-call lead's contact details and pushes them to
   SMS/email/Sheets/CRM automatically — [24/7 Answering Service to Capture Leads](https://www.goodcall.com/answering-services)
6. **PolyAI** — enterprise voice assistant; on escalation to a human, the agent passes a full conversation summary
   and every data point gathered so the caller never repeats themselves — [How PolyAI's voice agents are
   reinventing customer service](https://ukstories.microsoft.com/features/how-polyai-voice-agents-are-reinventing-customer-service/)
7. **Retell AI / Vapi / Synthflow / Bland AI** (compared together) — voice-agent platforms; documented patterns
   for a clean hand-off to voicemail or human callback as an edge case in the call flow, with Retell's handoff
   rated most polished and Bland's built specifically for outbound lead-callback workflows — [Retell vs Vapi vs
   Bland vs Synthflow, tested head-to-head](https://tested.media/retell-vs-vapi-vs-bland-vs-synthflow/)
8. **Thoughtly** (comparative roundup of missed-call-recovery agents) — the strongest pattern across vendors is a
   missed call becoming a callback *and* a text follow-up *and* a booking path in the same recovery flow, and the
   roundup's own caveat is the discriminator this catalog leans on: many vendors "only log a call note" rather
   than writing a structured outcome that drives a follow-up action — [8 Best AI Agents for Missed-Call
   Recovery](https://thoughtly.com/blog/best-ai-agents-missed-call-recovery)

## Feature catalog (this sub-module only)

### Booking List
- **Multi-filter appointment list (date range, status, provider, resource, service, search by contact)** —
  **ALREADY BUILT in 4.3** (`appointment_list_view`, verified above) · seen in: Calendly, Acuity, Cal.com, Square
  Appointments, NexHealth, Setmore (table-stakes across every calendar leader) · priority: table-stakes ·
  model: reuses `Appointment` — **no new work this pass**.
- **One-click status transition (Mark Completed / Mark No-show) from the list row and detail sidebar** — closes
  the actual gap: today the only way to flip `Appointment.status` is the full edit form · seen in: Acuity
  (inline appointment-status actions), Calendly (host marks a no-show without opening the full editor), Cal.com
  (a status action menu on the bookings table) · priority: differentiator relative to what's already shipped,
  but this is the one honestly-missing piece 4.3's own research flagged for 4.5 · model: reuses
  `Appointment.status` (existing field, existing choices `completed`/`no_show`) — no new column, no new table ·
  realtime: post-call (a staff action on a past-tense booking, never something a live call sets) · tool-surface:
  pure UI — a small scoped POST view (e.g. `appointment_mark_view(pk, status)`) authorised against
  `location_appointments(request)` exactly like `appointment_cancel_view`, guarded to only accept
  `completed`/`no_show` (never `cancelled`, which has its own reasoned flow) · buildable now.
- **Quick date-range presets (Today / This week / Upcoming) above the filter bar** — turns the existing
  `?from=`/`?to=` query params into one-click buttons instead of two date pickers every time · seen in: Acuity,
  Calendly, Cal.com admin views (all default to "upcoming" and offer a one-click "today") · priority: common ·
  model: none — pure template/view sugar over the already-existing `local_day_bounds_utc`-driven filter · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **CSV/print export of the filtered list** — seen in a subset of leaders (e.g. Acuity's export) · priority:
  differentiator · not requested by the sub-module's bullets and no reporting capability exists in this product →
  Deferred, not built this pass.

### Appointment Detail
- **Contact, service, resource, provider, notes shown together** — **ALREADY BUILT in 4.3**
  (`templates/scheduling/bookings/appointment/detail.html`, verified above) · priority: table-stakes across every
  calendar leader · model: reuses `Appointment` — no work this pass.
- **Originating call** — the bullet's fourth element. The detail page already carries a **defensive placeholder**
  saying the link appears once Module 5 exists, mirroring Smith.ai's "the call reserved a real seat on your
  calendar" pitch (the strongest signal a voice-AI booking product can show). This is correctly **integration/
  later**, blocked on `calls.CallSession` and `Appointment.booked_by_session` (both explicitly deferred by 4.3's
  own research) — 4.5 does not attempt to build around that gap with a stand-in field; the placeholder text is
  the right answer until Module 5 lands.

### Callback Request Queue
- **Name + phone + reason captured even for an unidentified caller** — the sub-module's own bullet, and the
  single strongest pattern across every answering-service leader: Smith.ai tags every call (resolved or not) with
  type and detail; Ruby takes a message "when we can't connect a call"; Rosie captures lead details on every
  missed call · seen in: Smith.ai, Ruby, Rosie · priority: REQUIRED (this is the core failure mode these products
  all sell against — losing an unresolved caller is the thing a "queue" exists to prevent) · model: new
  `scheduling.CallbackRequest`, tenant **and** location-scoped (`TenantLocationOwned`, confirmed as the intended
  base by `_base.py`'s own docstring) — `contact` FK to `scheduling.Contact`, **nullable** (Invariant 1: never a
  second identity table; an already-identified caller gets `contact` set from server state, an unknown one leaves
  it null and `caller_name`/`caller_phone` free-text fields carry whatever was actually said) · realtime: the
  eventual **write** happens on the **live-call hot path** (Module 3.3's future `request_callback` tool, and
  Module 3.4's documented off-hours/no-answer transfer fallback) — but that tool does not exist yet, so 4.5 itself
  is entirely **post-call**: the queue is worked by staff after the fact · tool-surface: this pass ships **no LLM
  tool** — `CallbackRequest` is the write target of a future `request_callback(reason, caller_name?,
  caller_phone?)` tool, with `tenant_id`/`location_id`/`contact_id` (when known) from server session state, never
  model args, exactly mirroring how 4.3 supplies `Appointment` as the write target for `book_appointment` without
  itself registering a tool · buildable now (model + CRUD); the tool + its live-call caller is integration/later
  (Module 3, not built).
- **`pending` / `contacted` / `closed` status workflow** — the sub-module's own bullet, generalizing Ruby's
  message-then-reminder flow and Smith.ai's "action taken" tag into three explicit states · priority: REQUIRED
  (explicit bullet) · model: `CallbackRequest.status` CharField, choices as named, default `pending`, indexed
  `(tenant, location, status)` per the ERD · realtime: post-call · tool-surface: pure UI (a status field on the
  edit/resolve form) · buildable now.
- **The queue defaults to `pending`, not a full history** — mirrors the operational "inbox of things still to do"
  every answering-service dashboard leads with (Ruby's Activity feed, Smith.ai's dashboard, Rosie's unified inbox
  all default to what's unresolved) rather than a flat historical log · priority: common · model: view-level
  default (`status=pending` unless the querystring overrides it) — no new field · realtime: post-call ·
  tool-surface: pure UI · buildable now.
- **Search + filter on the queue itself (status, search by name/phone/reason)** — the same filter contract the
  Booking List bullet already established for `Appointment`, applied to `CallbackRequest`, per this project's own
  Filter Implementation Rules (`status_choices` passed explicitly, `Q()`-based search, junk values degrade to "no
  filter") · priority: table-stakes · model: reuses `CallbackRequest` fields — no new column · realtime: post-call
  · tool-surface: pure UI · buildable now.
- **Tap-to-call the logged number directly from the queue** — Rosie's own headline pattern ("tap the notification
  to call back immediately") reduced to its cheapest honest form for this product: a `tel:` link on
  `caller_phone` · seen in: Rosie · priority: common, essentially free · model: none — template-only · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Instant multi-channel notification the moment a callback is logged (email/SMS/push)** — the headline feature
  of Ruby, Smith.ai and Rosie alike (a receptionist or owner is alerted within seconds) · priority: differentiator
  among the leaders · **out of scope for this product** — none of the seven capabilities include an outbound
  notification/messaging channel for staff alerts (email exists only for the account-security flows in Module 0);
  inventing one here would add an eighth capability → parked to Out of scope, not silently dropped.
- **Urgency/priority tagging** (Smith.ai tags "type + urgency") · priority: differentiator · not in the ERD or the
  sub-module's bullets → Deferred, not added as a field this pass — keeps the model to exactly what's asked.
- **Scheduled follow-up reminders** (Ruby: "set follow-up reminders" on a message) · priority: differentiator ·
  requires a reminder/notification engine this product does not have → Deferred.
- **Live in-queue hold / ACD position** (Dialpad's In-Queue Callback) · this is a *concurrent live-call* hold
  queue, not a post-call message queue — this product transfers to one configured destination number (2.3/3.4),
  it does not run a multi-agent live call queue → **out of scope**, the wrong domain entirely for this bullet.
- **CRM / Zapier / Google-Sheets auto-export of every lead** (Goodcall) · priority: differentiator · no
  integrations capability among the seven → **out of scope**.
- **Unified inbox merging voice calls and SMS/text threads** (Rosie) · no SMS channel in this product → **out of
  scope**.

### Callback Resolution
- **Close with notes** — the sub-module's own bullet, matching Ruby's message-resolution pattern and PolyAI's
  design principle that nothing gathered about the caller's need should be lost by the time a human reaches them
  · priority: REQUIRED (explicit bullet) · model: reuses `CallbackRequest.notes` (Text) + `status` transitioning
  to `closed` · realtime: post-call · tool-surface: pure UI, a form combining `status` + `notes` · buildable now.
- **No rigid linear state machine** — none of the researched leaders enforce "must pass through `contacted`
  before `closed`"; a callback resolved on the very first callback attempt goes straight from `pending` to
  `closed` · priority: table-stakes (flexibility over rigidity) · model: plain `status` field, any transition
  permitted through the resolve form — consistent with how 4.3's own `AppointmentForm` permits any of its
  non-cancelled status transitions through one form, not a guarded workflow engine · realtime: post-call ·
  tool-surface: pure UI · buildable now.
- **Who closed it / when, beyond the row's own `updated_at`** — no researched leader's public documentation
  specifies a distinct `resolved_by`/`resolved_at` pair, and the ERD's `CallbackRequest` doesn't carry one ·
  priority: deferred — `updated_at` (inherited from `TenantLocationOwned`'s base) already timestamps the last
  change; a dedicated audit pair is a reasonable future addition, not built this pass.

### Beyond the bullets
- **`CallbackRequest` as the documented transfer-fallback destination** — Module 3.4's own bullet ("Hours &
  Target Gating ... falling back to a callback request when closed") is an **already-written cross-module
  contract**, not speculative research — this sub-module's model must actually support being written from that
  future path even though Module 3 doesn't exist yet · priority: REQUIRED (it's already committed elsewhere in
  the catalog, so 4.5 cannot ship a model shape that path can't use) · model: `CallbackRequest.source` default
  `ai_phone` (mirrors `Contact.source`/`Appointment.source`'s established three-choice pattern:
  `ai_phone`/`manual`/`web`) — stamped server-side only, never model/tool-supplied, same discipline as
  `Appointment.source` · realtime: n/a this pass (the future write is Module 3's hot path) · tool-surface: n/a
  this pass · buildable now for the column; integration/later for the actual write path.
- **`contact` FK uses `SET_NULL`, not `PROTECT` (a deliberate contrast with `Appointment.contact`)** — an
  appointment is permanent booking history and must never silently vanish if its contact is removed, which is
  why 4.3 chose `PROTECT`; a callback request is a transient operational queue item, not a permanent record of a
  service rendered, so it should survive a contact's removal without blocking that removal · priority: a design
  decision this research surfaces, not copied from a single competitor · model: `CallbackRequest.contact`,
  `on_delete=models.SET_NULL`, `null=True` · buildable now.

## Compliance & provider constraints

- **REQUIRED — `caller_phone` and `reason` are PII by the same discipline already established for
  `Contact.notes` and `Appointment.reason`.** A caller's phone number plus an unresolved need (which may be
  medical, financial or otherwise sensitive, dictated by an unidentified caller under duress of being turned
  away) is never logged at INFO, is rendered with `|linebreaksbr` and never `|safe`, exactly matching the
  established `Contact`/`Appointment` convention in this codebase.
- **REQUIRED — `source` is stamped server-side only, never accepted from a tool argument or a form field a
  caller-facing path could forge.** This mirrors `Contact.source`/`Appointment.source`'s existing provenance
  discipline and closes the same prompt-injection surface Invariant 3 names generally: a caller's speech must
  never be able to claim a false provenance for the record their call produced.
- **No recording/consent surface here.** 4.5 is a queue CRUD page; it has no telephony, no audio and no
  consent-basis logic of its own. The REQUIRED compliance items (recording consent basis, two-party-consent
  announcement, AI disclosure, HIPAA/GDPR retention) belong to Module 3 (call runtime) and Module 5 (call log),
  matching the same note carried in 4.1–4.4's research files — recorded here only so nothing gets wrongly
  imported into this sub-module.
- **GDPR/CCPA erasure interaction.** Because `CallbackRequest.contact` is `SET_NULL` (see "Beyond the bullets"
  above), a `Contact.anonymize()` call — which blanks fields but keeps the row — leaves the `CallbackRequest` row
  intact with its own free-text `caller_name`/`caller_phone`, which is itself PII independent of the `Contact`
  row. An erasure request against a `Contact` does **not** automatically scrub the `caller_name`/`caller_phone`
  already captured on a linked or orphaned `CallbackRequest` row — this is a genuine gap worth flagging to the
  `todo` agent, not solved silently here: the erasure flow this product already has (from 4.1) may need to reach
  into `CallbackRequest` too. Not fixing this now is a defensible scope boundary (4.1 didn't build erasure to
  cascade into other apps' models, and 4.5 shouldn't unilaterally invent that cascade either), but the gap should
  be visible.
- **Twilio/provider cost.** 4.5 makes no provider call of its own (no Twilio, no STT/TTS/LLM token spend) — it is
  pure ORM/DB work, same as 4.3. No cost line is appended to `calls.CallSession.usage` by this sub-module (no
  `CallSession` exists yet). The only latency-relevant surface is the future `request_callback` tool call
  (Module 3.3's hot path, not built) — this sub-module's job is only to make sure the write it performs (a single
  indexed insert on `(tenant, location, status)`) is cheap enough for that future caller, the same posture 4.3
  took for `get_availability`/`book_appointment`.

## Recommended build scope (this pass)

**CRUD sub-module — 1 model:**

- **`CallbackRequest`** — tenant **and** location-scoped (`TenantLocationOwned`, per the ERD and per
  `_base.py`'s own docstring, which already names this model). Fields, all justified above:
  - `contact` — FK `scheduling.Contact`, **null**, `on_delete=models.SET_NULL` (contrast with
    `Appointment.contact`'s `PROTECT` — justified under "Beyond the bullets").
  - `caller_name` — Char(255), blank.
  - `caller_phone` — Char(32), blank — the confirmed callback number (Callback Request Queue).
  - `reason` — Text, blank (Callback Request Queue).
  - `status` — Char(16), indexed, default `pending`, choices `pending`/`contacted`/`closed` (Callback Request
    Queue + Callback Resolution).
  - `source` — Char(32), default `ai_phone`, mirrors `Contact.source`/`Appointment.source`'s
    `ai_phone`/`manual`/`web` pattern (Beyond the bullets — the transfer-fallback contract).
  - `notes` — Text, blank (Callback Resolution).
  - Index `(tenant, location, status)` per the ERD. Ordering `["-created_at"]` per the ERD.
  - FKs verified to exist: `tenants.Tenant`, `tenants.Location` (via `TenantLocationOwned`), `scheduling.Contact`
    (grepped above).

**Plus, not a new model — enrichment of the existing `Appointment` CRUD (4.3), directly requested by the
invoking prompt:**
- A small, scoped POST view for one-click `completed`/`no_show` status transitions from the appointments list
  row and the detail-page sidebar, reusing `location_appointments(request)` for authorization exactly like the
  existing `appointment_cancel_view`.
- Quick date-range preset buttons (Today / This week / Upcoming) on the appointments list, built on the
  already-existing `?from=`/`?to=`/`local_day_bounds_utc` machinery — template/view sugar only.

**Explicitly NOT rebuilt this pass** (already shipped by 4.3, verified above): the appointment list's
date-range/status/provider/resource/service filters and contact search; the appointment detail page's
contact/service/resource/provider/notes panel and its originating-call placeholder.

**Explicitly deferred out of the `CallbackRequest` model:** urgency/priority field, `resolved_by`/`resolved_at`
audit pair, any notification-dispatch mechanism, CSV/print export — none are in the ERD or the sub-module's
bullets; adding them now would be the exact over-scoping this process exists to prevent.

## Belongs to sibling sub-modules (parked, not scoped here)

- The `request_callback` LLM tool, its registration in the dispatcher, and the actual live-call write into
  `CallbackRequest` → **Module 3.3 (Tools & Dispatcher)**. 4.5 supplies the model only, exactly as 4.3 supplies
  `Appointment` for `book_appointment` without registering a tool itself.
- The off-hours/no-answer transfer-fallback path that writes a `CallbackRequest` when a transfer cannot complete
  → **Module 3.4 (Transfer Execution)** — already documented there ("falling back to a callback request when
  closed"); 4.5 only needs to make sure the model shape (nullable `contact`, `source` default) can receive that
  write later.
- `Appointment.booked_by_session` FK completion (to complete the Appointment Detail bullet's "originating call")
  → **Module 5**, when `calls.CallSession` exists — already deferred by 4.3's own research, re-confirmed rather
  than re-litigated here.
- Recording consent basis, transfer outcome capture on `CallSession.transfer` JSON, and the call-detail page that
  would eventually show a `CallbackRequest`'s originating call → **Module 3.5 / Module 5**.

## Out of scope for this product (outside the seven capabilities)

- **Instant multi-channel staff notification on a new callback** (email/SMS/push — Ruby, Smith.ai, Rosie all lead
  with this) — no outbound notification/messaging capability exists among the seven; this product's email use is
  limited to the Module 0 account-security flows (password reset, email-change confirmation).
- **CRM / Zapier / Google-Sheets auto-export of leads** (Goodcall) — no integrations capability among the seven.
- **Live in-queue hold / ACD callback position** (Dialpad's In-Queue Callback) — a concurrent-live-call hold-queue
  concept; this product transfers to a single configured destination number, it does not run a multi-agent live
  call queue.
- **Unified inbox merging voice calls with SMS/text threads** (Rosie) — no SMS channel among the seven.
- **Scheduled follow-up reminders** (Ruby) — would need a reminder/notification engine this product doesn't have.

## Deferred (later passes / integrations)

- **`request_callback` tool registration and its live-call write path** — blocked on Module 3 (Call Runtime) not
  existing yet; the model this pass ships is the write target, not the writer.
- **The off-hours/no-answer transfer-fallback write into `CallbackRequest`** — same blocker (Module 3.4).
- **`Appointment.booked_by_session` FK completion** — blocked on Module 5 (`calls` app); carried forward from
  4.3's own Deferred list, not re-litigated.
- **Urgency/priority tagging on `CallbackRequest`** (Smith.ai) — real leader feature, not in the ERD or bullets;
  a well-scoped future addition if ever asked for.
- **`resolved_by`/`resolved_at` audit pair on `CallbackRequest`** — reasonable future addition; `updated_at`
  covers "when" well enough for this pass.
- **CSV/print export of the bookings list or the callback queue** — seen in a subset of leaders (Acuity); no
  reporting capability documented for this product yet.
- **Cascading a `Contact.anonymize()` erasure into any linked `CallbackRequest`'s free-text `caller_name`/
  `caller_phone`** — flagged as a genuine gap under Compliance above; not solved this pass because 4.1 didn't
  build a cross-app erasure cascade either, and inventing one unilaterally here would be scope creep in the
  other direction.
