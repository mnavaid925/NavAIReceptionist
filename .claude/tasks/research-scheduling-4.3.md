# Research — Sub-module 4.3: Availability & Booking (Module 4 — Calendar & Bookings, scheduling)

## Repo state checked first

- `LIVE_LINKS` built so far in module 4: `'4.1': {'Contacts': 'scheduling:contact_list'}`,
  `'4.2': {'Services': 'scheduling:service_list', 'Resources': 'scheduling:resource_list'}` (verified in
  `apps/accounts/navigation.py`). `4.3`, `4.4`, `4.5` have no entry — 4.3 is the next unbuilt sub-module, matching
  the invoking prompt.
- Sibling models available to FK, all grep-verified to exist:
  - `scheduling.Contact` — `apps/scheduling/models/ContactDirectory/Contacts.py` — tenant-scoped, NOT
    location-scoped (Invariant 1, the one identity table).
  - `scheduling.Service` — `apps/scheduling/models/ServicesResources/Services.py` — tenant-scoped with a
    hand-declared **nullable** `location` FK; has `duration_minutes`, `buffer_minutes`, `requires_resource`,
    `is_active`, and the member `total_minutes` (= duration + buffer, the value 4.3 must subtract from a working
    window per the skill).
  - `scheduling.Resource` — `apps/scheduling/models/ServicesResources/Resources.py` — tenant **and**
    location-scoped, unique on `(location, name)`, `is_active`, deliberately **no capacity field** (exclusive —
    one appointment at a time) and **no FK to the user model**.
  - `accounts.User` — `apps/accounts/models/User.py` — has `is_provider` (bool) and `provider_hours` (JSON,
    keyed by location id: `{"<location_id>": [{"start_time","end_time","days":[...]}]}`).
  - `tenants.Location` — `apps/tenants/models/Location.py` — has `timezone` (IANA string), `.tzinfo` (a
    `ZoneInfo` property that degrades to UTC on a bad/unknown name) and `.local_now()`.
  - `apps/scheduling/views/_helpers.py::save_or_report_conflict` — wraps `form.save()`, converts a lost race
    (`IntegrityError`) into a form error instead of a 500. Explicitly documented in the skill as reusable by 4.3.
  - `django.core.signing` — established in `apps/accounts/views/Auth.py` (`signing.dumps(...,
    salt=EMAIL_CHANGE_SALT)`, `signing.loads(..., max_age=...)`, catching `signing.BadSignature`) — the pattern
    for 4.3's opaque signed `slot_token` (short-TTL, self-invalidating, no extra DB table needed to expire it).
  - `apps/scheduling/views/_common.py` already defines a `tier_required` / `MANAGEMENT_TIERS` gate, used by 4.1/4.2
    to gate only delete/forget — the confirmed pattern for 4.3 (delete-only gating; list/detail/create/edit open
    to any signed-in tenant user).
- Models verified NOT to exist: `apps/calls/` has **no files at all** (`Glob apps/calls/**` returned nothing) —
  `calls.CallSession` is not installed. Per Django, a string FK to an app that isn't in `INSTALLED_APPS` fails
  `makemigrations` outright ("which is either not installed, or is abstract"). **`Appointment.booked_by_session`
  therefore cannot ship as a real FK in this pass** — see Deferred and the build-scope note below.

## Leaders surveyed (with source links)

1. **Cal.com** — open-source scheduling/booking API; the closest analog to "availability engine as a library" —
   [Slots API discussion & buffer handling](https://cal.com/docs/api-reference/v2/bookings/create-a-booking), [GET
   /slots buffer bug report](https://github.com/calcom/cal.com/issues/24540)
2. **Acuity Scheduling** — availability controls: padding (buffer), minimum notice, per-service-type scheduling
   limits — [Appointment Availability Controls](https://acuityscheduling.com/features/availability-controls),
   [Adding padding between appointments](https://help.acuityscheduling.com/hc/en-us/articles/16676926857101-Adding-padding-between-appointments)
3. **Retell AI** — "Check Availability" / "Book Appointment" voice-agent tools, calendar-linked (Cal.com) —
   [Book Appointments feature page](https://www.retellai.com/features/book-appointments)
4. **Vapi** — documented pattern of separate `get_slots` / `book_slot` / `confirm_booking` tools rather than one
   combined tool, and an explicit race-condition warning: a 200–400 ms gap between availability check and booking
   write is a real double-booking window unless the slot is locked before caller confirmation —
   [Introduction to Tools](https://docs.vapi.ai/tools), [VAPI healthcare scheduling build guide (pessimistic
   locking, 3-slot offer, TTL lock)](https://dev.to/callstacktech/how-to-set-up-vapi-for-ai-appointment-scheduling-in-healthcare-a-developers-guide-4de0)
5. **Smith.ai** — books directly into the connected calendar (not just a message), so a live seat is reserved the
   instant the call books it — [New: Appointment scheduling for AI Receptionist](https://smith.ai/blog/new-appointment-scheduling-for-ai-receptionist)
6. **Goodcall** — no-code AI phone agent with calendar-linked booking for local/service businesses —
   [7 Best AI Receptionist Software](https://lunacal.ai/blogs/ai-receptionist-2026)
7. **Rosie AI** — calendar integrations (Google/Outlook/Calendly/Acuity/Appointlet); tiered — read-only slot
   suggestion vs. real auto-booking that locks the slot in real time — [7 Best AI Receptionist Software
   (2026)](https://lunacal.ai/blogs/ai-receptionist-2026)
8. **NexHealth** — real-time calendar read (10–15 s propagation), waitlist re-offer on a freed slot with instant
   invalidation of a stale claim — [NexHealth Scheduling](https://www.nexhealth.com/features/scheduling)
9. **Calendly** — reschedule/cancel links, a *displayed* cancellation policy that is advisory only (Calendly does
   not enforce a cutoff window server-side) — [How to cancel, reschedule and make changes to an
   event](https://help.calendly.com/hc/en-us/articles/223145167-How-to-cancel-reschedule-and-make-changes-to-an-event),
   [community: minimum notice not enforced on reschedule](https://community.calendly.com/how-do-i-40/why-does-the-ability-to-cancel-or-reschedule-not-respect-the-minimum-notice-2359)
10. **Mindbody** — capacity / staff-concurrency and resource-overbooking settings as the explicit *cause* of
    double-booking when misconfigured — used here as a negative example (exclusive resource-locking is the safer
    default) — [Reasons clients may be able to double book appointments](https://support.mindbodyonline.com/s/article/203275113-Thor-Why-can-clients-double-book-Capacity-Prep-Times?language=en_US)

## Feature catalog (this sub-module only)

### Availability Search
- **Working-hours-driven slot generation** — turns a provider's `provider_hours[location_id]` weekly windows
  into candidate slots for a date range · seen in: Acuity, Cal.com · priority: table-stakes · model: reuses
  `accounts.User.provider_hours` (no new table) — read-only in this pass (tenant + location scoped by which
  provider is queried) · realtime: **live-call hot path** (the `get_availability` tool) and post-call (the
  booking-form's slot widget) · tool-surface: feeds `get_availability(date_from, date_to, service_id,
  resource_id?, provider_id?)` — identity (`tenant_id`, `location_id`) from server state, the rest are the
  model's own free choices · buildable now.
- **Duration + buffer subtraction** — a slot's true footprint is `service.total_minutes`
  (`duration_minutes + buffer_minutes`), not just duration; a candidate slot must clear a busy window by that
  full amount before the *next* appointment can start · seen in: Acuity (padding), Cal.com (post-event buffer) ·
  priority: REQUIRED (a slot that ignores buffer double-books the room/provider on the very next call) · model:
  reuses `Service.total_minutes` (already built in 4.2) · realtime: live-call hot path · tool-surface: internal
  to the availability computation, no separate tool · buildable now.
- **Resource exclusivity check** — a candidate slot for a service with `requires_resource=True` is dropped if
  any `Resource` at that location already has a conflicting `Appointment` in that window; `Resource` carries no
  capacity, so one active appointment fully occupies it · seen in: Mindbody (negative case — overbooking is an
  explicit opt-in they warn about), Cal.com · priority: REQUIRED · model: reuses `Resource` +
  new `Appointment.resource` FK · realtime: live-call hot path · tool-surface: internal to `get_availability` ·
  buildable now.
- **Minimum notice / lead time** — no slot is offered inside a configurable "book at least N hours/minutes from
  now" window · seen in: Acuity (per-service-type minimum notice), Calendly (advisory only — noted as a gap to
  avoid copying) · priority: table-stakes · model: a simple settings constant for this pass (e.g. a
  `MIN_BOOKING_NOTICE_MINUTES` default), not a new field — no researched leader ties it to a field this product
  is missing, and Service/AgentSetting don't carry one yet · realtime: live-call hot path · tool-surface: internal
  to `get_availability` · buildable now (deferred: a per-service or per-location override field — see Deferred).
- **Timezone-correct evaluation** — every slot's wall-clock time is computed in the **location's** timezone
  (`Location.tzinfo` / `local_now()`), never the server's or the caller's · seen in: all calendar leaders (table
  stakes) · priority: REQUIRED (a wrong-timezone slot double-books or offers a slot in the past) · model: reuses
  `Location.tzinfo`/`local_now()` · realtime: live-call hot path · tool-surface: internal · buildable now.

### Server-Capped Slot Set
- **Small pre-ranked slot list for a voice conversation** — a caller cannot process 40 spoken time options; cap
  the returned set (research converges on **~3**, "offer 3 backup times") and rank by soonest-first · seen in:
  the Vapi healthcare build guide (explicit "offer 3 backup times"), Retell (implicit — "confirm the right time
  slot" flow assumes a short list) · priority: differentiator (most calendar UIs show a full grid; this is
  specific to a **voice** channel with no screen) · model: no new table — a query-time `LIMIT` + ordering, capped
  **server-side** so a manipulated or verbose model prompt cannot ask for more · realtime: live-call hot path ·
  tool-surface: `get_availability` returns `data.slots` capped at a server constant (e.g. `MAX_OFFERED_SLOTS = 5`,
  configurable but never model-controlled) · buildable now.
- **Slot count independent of the booking-form UI** — the same capped-list logic is reused by the human-facing
  booking form (fewer, better slots beat a giant dropdown) rather than duplicated · seen in: Cal.com, Acuity ·
  priority: common · model: shared helper function, not a model · realtime: post-call (form) reusing the same
  live-call-hot-path function · tool-surface: pure UI on the human side · buildable now.

### Booking with Slot Locking
- **Opaque signed short-TTL slot token** — the availability tool returns one signed token per slot (not raw
  start/end/resource fields the model must echo back correctly); booking is `book_appointment(slot_token,
  contact confirmation)` · this is the project's own **supporting invariant**, converged with Vapi's documented
  "lock the slot BEFORE confirming with the patient" pattern and the general opaque-capability pattern used
  elsewhere in this codebase (`django.core.signing`, `EMAIL_CHANGE_SALT`) · priority: REQUIRED (Invariant-adjacent
  — named explicitly in the sub-module's own bullets and in the project's supporting rules) · model: no new
  table — `signing.dumps({"location_id":…, "resource_id":…, "provider_id":…, "service_id":…, "start_at":…,
  "end_at":…}, salt="scheduling.slot", …)` with `max_age` on `loads()`; the payload is never trusted for
  identity (tenant/location are re-validated against server state on redemption) · realtime: live-call hot path
  · tool-surface: `get_availability` returns `data.slots = [{"slot_token": "...", "starts_at": "...",
  "provider_label": "...", ...display fields only...}]`; `book_appointment` takes `slot_token` (opaque) plus
  `service_id`/`reason` — never raw start/end/resource ids · buildable now.
- **Race-safe write, not a distributed lock** — Vapi's own guide reaches for a 5-minute Redis-style pessimistic
  lock; this product has no cache/lock service in scope. The safer local equivalent: (a) re-validate the slot is
  still open against `Appointment` at write time inside `transaction.atomic()` with `select_for_update()` on any
  overlapping rows for that resource/provider, and (b) a DB-level uniqueness/overlap guard as the final backstop
  so a lost race surfaces as a caught `IntegrityError`/conflict, not a double-booked calendar · seen in: Cal.com
  (buffer-respecting slot rejection "the instant it is taken"), Vapi guide (pessimistic lock + TTL) · priority:
  REQUIRED · model: `Appointment` write path reuses `save_or_report_conflict` from `views/_helpers.py`, extended
  with a `select_for_update()` re-check for the tool path (the tool path has no form, so it needs its own
  version of the same idea) · realtime: live-call hot path · tool-surface: `book_appointment` result:
  `{"ok": false, "error": {"code": "slot_unavailable", "message": "..."}}` on a lost race,
  `{"ok": false, "error": {"code": "slot_expired", ...}}` on an expired token · buildable now (no external
  dependency — pure DB transaction semantics).
- **Idempotent booking write** — a retried tool call (model retries after a timeout, or Twilio-style redelivery
  at the runtime layer) must not create two appointments for the same slot_token · seen in: Vapi's own
  documented webhook-retry idempotency problem ("duplicate Salesforce updates... billing issues") · priority:
  REQUIRED · model: no new table — a short-lived idempotency check keyed on the token's own signed payload
  (booking the same `slot_token` twice returns the existing `Appointment`, not a duplicate) · realtime: live-call
  hot path · tool-surface: `book_appointment` behaviour, not a new tool · buildable now.

### Reschedule & Cancel
- **Move with reason + timestamp, authorised against tenant, location AND the identified contact** — this is
  the sub-module's own bullet; the important addition from research is that a reschedule is booking-again against
  a fresh slot token (reuse the whole Booking-with-Slot-Locking machinery), not a bare `start_at` field edit ·
  seen in: Calendly (self-serve reschedule link), Acuity · priority: table-stakes · model: reuses `Appointment` —
  a reschedule updates `start_at`/`end_at`/`resource`/`provider` on the same row (keeps history simple; no
  separate reschedule-log table, which would be a needless second table for a small app) · realtime: live-call
  hot path (`reschedule_appointment` tool) and post-call (staff-driven reschedule from the booking-list UI, which
  is 4.5's surface but the underlying model logic lives here) · tool-surface: `reschedule_appointment(slot_token,
  appointment_id)` — `appointment_id` is authorised server-side against `tenant`, `location` **and**
  `session.contact_id` before any write (Invariant 3) · buildable now.
- **Cancel with reason + timestamp** — `cancelled_at` + `cancellation_reason` stamped, status flips to
  `cancelled`; the slot becomes immediately available to the next search · seen in: Calendly, Acuity, Cal.com ·
  priority: table-stakes · model: reuses `Appointment.cancelled_at` / `cancellation_reason` (ERD fields) ·
  realtime: live-call hot path (`cancel_appointment` tool) and post-call (staff cancel from 4.5's list) ·
  tool-surface: `cancel_appointment(appointment_id, reason)` — `appointment_id` authorised the same way ·
  buildable now.
- **Cutoff-window policy is advisory in the leaders, not a hard requirement here** — Calendly explicitly does
  **not** enforce a minimum-notice cutoff on cancel/reschedule server-side (checked and confirmed in research);
  Acuity ties it to minimum-notice settings on booking, not specifically to cancel. **Recommendation: do not
  invent a per-service cancellation-cutoff field this pass** — it is not in the ERD, not in the sub-module's
  bullets, and the researched leaders don't converge on one hard rule to copy. Reschedule/cancel remain always
  permitted (subject to identity authorization), consistent with "no-show" existing as its own status for the
  case where a cutoff would have mattered anyway.
- **No-show as a distinct terminal status** — distinguishes "cancelled in advance" from "never showed", which
  matters for provider utilization reporting even though this pass ships no reporting UI · seen in: Acuity,
  Cal.com, Mindbody (all distinguish no-show from cancel) · priority: common · model: reuses `Appointment.status`
  choice `no_show` (already in the ERD) · realtime: post-call (a staff action, not something the live call sets)
  · tool-surface: none — status transition is a plain form action in the (future 4.5) bookings list · buildable
  now (field ships in 4.3; the UI to flip it explicitly may land with 4.5's booking list, since 4.3's own
  CRUD form still needs a status field/action per the CRUD-completeness rule).

### Booking Provenance
- **Source tagging** — every appointment records how it was created (`ai_phone` / `manual` / `web`) · seen in:
  Smith.ai (calendar write vs. "just a message"), all calendar leaders distinguish self-serve vs. staff-entered
  bookings · priority: table-stakes · model: reuses `Appointment.source` (ERD field, mirrors
  `Contact.source`'s already-established choices) · realtime: the value is stamped server-side at write time
  (never a form field the caller-facing tool sets arbitrarily — `source='ai_phone'` is hard-coded on the tool
  path, never taken from `args`) · tool-surface: `book_appointment` always writes `source='ai_phone'`; the manual
  create/edit form writes `source='manual'` · buildable now.
- **Link to the originating call** — the ERD's `booked_by_session` FK to `calls.CallSession` is the single
  strongest signal a voice-AI booking platform offers (Smith.ai's whole pitch is "the call reserved a real seat
  on your calendar") · seen in: Smith.ai, Retell, Rosie (tiered — auto-booking vs. suggestion-only) · priority:
  differentiator, but **cannot ship as a real FK in this pass** — `apps/calls` does not exist yet, and Django
  refuses `makemigrations` against a string FK to an uninstalled app. **Recommended stand-in: no field at all
  this pass**, not a fake placeholder FK/IntegerField — the ERD field lands as a genuine
  `ForeignKey('calls.CallSession', null=True, on_delete=models.SET_NULL)` added by an **additive migration in
  Module 5** once `calls.CallSession` exists, exactly as the invoking prompt instructs. Adding a same-named
  `IntegerField` now and converting it later is a needless two-step migration for a field nothing in 4.3 reads or
  writes yet (the tool dispatcher that would populate it is Module 3.3, also unbuilt). · realtime: n/a this pass
  · tool-surface: n/a this pass · integration/later (depends on Module 5).

### Beyond the bullets
- **Provider AND resource must both clear** — a booking with both `provider` and `resource` set needs the
  candidate slot to be free on **both** independently (a double-booked room with a free dentist is still
  unbookable) · seen in: NexHealth (explicitly separates provider-busy vs. operatory-busy checks, called out in
  4.2's own research) · priority: table-stakes · model: reuses `Appointment.provider` + `.resource`, both
  checked in the same availability query · realtime: live-call hot path · tool-surface: internal to
  `get_availability` · buildable now.
- **Waitlist / re-offer on cancellation** — NexHealth re-offers a freed slot to a waitlist and invalidates a
  stale claim in real time · priority: differentiator, but **out of scope for this pass** — there is no waitlist
  entity in the ERD or the sub-module's bullets, and inventing one here would be exactly the over-scoping this
  process exists to prevent → Deferred.
- **Per-service/per-location minimum-notice override** — Acuity lets minimum notice vary by service type;
  `scheduling.Service` has no such field today → Deferred (a genuinely small, well-scoped addition for a later
  pass, not this one — the sub-module's bullets don't ask for it and a sane default constant covers the demo).

## Compliance & provider constraints

- **No recording/consent surface here.** 4.3 is calendar math and a booking write; it has no telephony, no
  audio and no PII disclosure surface of its own. The REQUIRED compliance items (recording consent basis,
  two-party-consent announcement, AI disclosure, HIPAA/GDPR retention) belong to Module 3 (the call runtime) and
  Module 5 (the call log), not to this sub-module — noted here only so nothing gets wrongly imported into 4.3.
- **`Appointment.notes`/`reason` are caller-dictated text, same PII discipline as `Contact.notes`** — never
  logged at INFO, rendered with `|linebreaksbr` and never `|safe` (mirrors the established `Contact` convention
  in the skill).
- **`Appointment.contact` uses `on_delete=PROTECT`** (per ERD) — this is what forces the erasure path documented
  in the scheduling skill ("Delete vs erase") once 4.3 lands; a `Contact` with bookings can no longer be
  hard-deleted, only anonymized. This sub-module must implement `PROTECT`, not `CASCADE` or `SET_NULL`, exactly
  as the ERD specifies, or the erasure flow silently breaks.
- **Twilio/provider cost:** 4.3 itself makes no provider call (no Twilio, no STT/TTS/LLM token spend) — it is
  pure ORM/DB work. It does, however, define the **latency-critical hot-path function** (`get_availability`,
  `book_appointment`) that Module 3.3's turn loop will call synchronously inside the live-call budget (≤1.5 s p50
  to first agent audio) — so its query must stay a small, indexed read (`(tenant, location, start_at)` — already
  in the ERD's index list) rather than a full-table scan. No cost line is appended to `calls.CallSession.usage`
  by this sub-module (no CallSession exists yet); Module 5 will be the one to render slot-search latency if it
  chooses to.
- **Server-side notice/slot-count caps are a light abuse control**, not a legal requirement: they bound how much
  compute a single conversation turn can trigger, consistent with the project's existing per-turn cost-as-a-
  security-control principle, even though the concrete cost here is DB query time rather than provider spend.

## Recommended build scope (this pass)

**CRUD sub-module — 1 model:**

- **`Appointment`** — tenant **and** location-scoped. Fields per the ERD, **minus `booked_by_session`** (deferred
  — see Booking Provenance above): `tenant` FK, `location` FK, `contact` FK (`on_delete=PROTECT`), `provider` FK
  `settings.AUTH_USER_MODEL` (null), `resource` FK `scheduling.Resource` (null, `on_delete=SET_NULL`), `service`
  FK `scheduling.Service` (null, `on_delete=SET_NULL`), `start_at`/`end_at` (DateTime), `status` (Char(24),
  indexed, default `scheduled`, choices `scheduled`/`confirmed`/`completed`/`cancelled`/`no_show` — justified by
  Reschedule & Cancel + the No-Show-as-distinct-status finding), `reason` (Char(255), blank), `notes` (Text,
  blank), `source` (Char(16): `ai_phone`/`manual`/`web` — justified by Booking Provenance), `cancelled_at`
  (DateTime, null), `cancellation_reason` (Char(255), blank — both justified by Reschedule & Cancel). Indexes
  `(tenant, location, start_at)`, `(tenant, status)`, `(tenant, contact)` — the first is what the live-call
  availability query hits. Ordering `["start_at"]`. FKs verified to exist: `tenants.Tenant`, `tenants.Location`,
  `scheduling.Contact`, `settings.AUTH_USER_MODEL`, `scheduling.Resource`, `scheduling.Service` — all grepped
  above.

**Plus (not a model): the availability-search function.** A pure Python function (e.g.
`apps/scheduling/services.py` or a method-set under `views/_helpers.py`, per the "single-purpose modules stay
flat" backend rule) that: (1) builds candidate windows from `provider_hours[location_id]`, (2) subtracts
`Service.total_minutes`, (3) excludes conflicts against existing non-cancelled `Appointment` rows for the
requested `resource`/`provider`, (4) applies the minimum-notice cutoff, (5) caps and ranks the returned set, and
(6) mints one signed `slot_token` per slot via `django.core.signing`. This function is what Module 3.3's
`get_availability`/`book_appointment`/`reschedule_appointment`/`cancel_appointment` tools will call — 4.3 itself
ships no LLM tools (same "this module registers no LLM tools" posture the skill documents for 4.1/4.2), but its
CRUD views (create/edit) reuse the same function to populate the human-facing slot picker.

**Explicitly deferred out of this model:**
- `booked_by_session` — added as an additive migration when `apps/calls` exists (Module 5 / 3.3's landing).
- A distributed/pessimistic slot lock (Redis-style TTL lock) — not needed; `select_for_update()` +
  `save_or_report_conflict` inside `transaction.atomic()` covers this product's actual concurrency (single DB,
  no multi-process lock service in scope).
- A waitlist entity, a per-service minimum-notice override field, and a cancellation-cutoff-window field — none
  are in the ERD or the sub-module's bullets; see Deferred below.

## Belongs to sibling sub-modules (parked, not scoped here)

- Day/week calendar grid, resource/provider column toggle, slot click-through, status colouring → **4.4 Calendar
  Views** (a view sub-module — reads `Appointment`, ships no model).
- Appointment list with filters (date range, status, provider, resource, service) and search by contact, plus
  `CallbackRequest` CRUD → **4.5 Bookings List & Callback Requests**.
- The actual LLM tool registration/dispatch (`get_availability`, `book_appointment`, `reschedule_appointment`,
  `cancel_appointment` as callable tools inside the turn loop) and the tool-result envelope wiring → **Module 3
  (Call Runtime)**, specifically 3.3 (the turn loop / tool dispatcher). 4.3 supplies the model + the pure
  availability function 3.3 will call; it does not itself register a tool.
- `booked_by_session` FK completion → **Module 5** (when `calls.CallSession` is created), landing as an additive
  migration on `scheduling.Appointment`.

## Out of scope for this product (outside the seven capabilities)

- **Payments/deposits at booking time** (several booking platforms — Acuity, Square — support charging a card
  to hold a slot) — this product has no payments capability among its seven; a caller pays nothing to book.
- **Group classes / multi-attendee capacity** (Mindbody's capacity+concurrency settings) — `Resource` is
  deliberately exclusive with no capacity field per the 4.2 research and the as-built model; this product books
  one contact per appointment, not a class roster.
- **External calendar sync (Google/Outlook two-way sync)** — Rosie/NexHealth/Cal.com all sync to a real external
  calendar; this product's calendar **is** `scheduling.Appointment` itself — there is no second calendar to
  reconcile against, and adding one would duplicate the identity/booking model this product already owns.
- **SMS/email confirmation and reminder sending** — several leaders (Smith.ai, NexHealth) auto-send confirmations
  on booking; this product's seven capabilities don't include an outbound notification channel, and none of
  `Appointment`'s fields imply one is coming.

## Deferred (later passes / integrations)

- **`booked_by_session` FK** — blocked on Module 5 existing; added as an additive migration then, per the
  invoking prompt's explicit instruction. Until then, `Appointment` carries no field referencing the call that
  created it; the tool dispatcher (3.3) will need to note the `CallSession` id itself once it exists, and 4.3's
  migration gets extended at that time — not before.
- **Waitlist / slot re-offer on cancellation** (NexHealth) — no entity in the ERD; would need a new tenant+
  location-scoped table and isn't asked for by the sub-module's bullets.
- **Per-service or per-location minimum-notice override field** (Acuity) — a real, well-scoped future addition
  to `Service`/`AgentSetting`, deferred because the sub-module ships a working default constant and the ERD
  doesn't carry the field today; adding it now would be an uncommitted schema guess.
- **Cancellation-cutoff-window enforcement** — research shows the market leader (Calendly) explicitly does not
  enforce this server-side; not worth inventing a field/rule this product's own bullets don't ask for.
- **Distributed slot-lock cache (Redis TTL lock, as Vapi's own build guide uses)** — unnecessary complexity for
  a single-process-per-worker Django/MySQL deployment; `select_for_update()` inside `transaction.atomic()` is the
  right-sized equivalent and is what ships this pass.
